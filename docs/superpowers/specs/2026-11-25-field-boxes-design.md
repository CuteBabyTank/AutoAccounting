# Field boxes: click a field, see it on the scan

Date: 2026-11-25 · Status: draft for approval

## Why

Reviewers check what the reader extracted against the paper. Today they hunt for each value on the page by eye,
which is slow and makes it easy to approve a misread. The user wants MLLM-HTR's behaviour
(`~/Documents/THESIS/MLLM-HTR/website`): click a field and the scan zooms to it with the spot outlined, and
flagged fields are boxed on the scan. The boxes must always be correct for each page: **no box is better than a
wrong box**.

MLLM-HTR can do this without AI because every COC is the same form (hand-measured boxes in `layout.py`, aligned to
each scan by its printed lines). AutoAccounting's receipts and invoices have no fixed layout, so positions come
from the reader plus a text check instead.

## Goals

- Documents panel (`components/accounting/DocumentPanel.tsx` + `PageViewer.tsx`) and Extract record panel
  (`components/extract/RecordPanel.tsx` + `PageViewer.tsx`): focusing or clicking a field that has a box switches
  to the page it's on, zooms so the box fills a comfortable part of the view, centres it, and outlines it (blue).
- Fields with a review problem (Documents: `review_reasons` / `checkDocument` flags tied to a field; Extract: flag
  `cells`) get an amber outline on the scan while their page is shown. Clicking an outlined box on the scan focuses
  its field.
- A "Zoom to field" toggle in the viewer bar (on by default, remembered per person in `localStorage`, keyed by user
  as in `lib/personal-storage.ts`). Off = outline only, no zoom.
- Moving between two fields whose boxes are both already in view only moves the outline, with no re-zoom
  (MLLM-HTR's "same item only scrolls").
- Extract: Excel export unchanged. Boxes never enter the workbook.

## Non-goals

- No boxes for documents read before this ships. Their viewer works as it does today (no backfill job). A later
  backfill could run the text-locate half alone.
- No fixed-form templates for BIR forms (2307, 2550-Q). That is a possible later addition using MLLM-HTR's
  method.
- No boxes on line items in the Documents panel (it has no line items). Extract row fields **do** get boxes, per
  row.
- No editing of boxes by hand.

## Anti-goals (a failure even if it works)

- A box on the wrong spot, the wrong page or the wrong document. Every rule below prefers drawing nothing.
- Slower or costlier extraction in a way people notice: at most about +15% reader output tokens, and OCR adds
  ≤ 3 s CPU per scanned page, run in the background job, never in a request.
- A firm seeing another firm's boxes (they live on firm-scoped rows already under RLS).

## Approaches considered

| | How boxes are found | Trade-off |
|---|---|---|
| A. Text locate only | PDF text layer / OCR words, match the stored value | Never wrong, but no box for handwriting, computed values or values printed twice |
| B. Model boxes only | The reader returns a box per field | Covers nearly everything, but boxes are sometimes off or made up, so it can't be "always correct" |
| **C. Both (chosen)** | Model box as a hint, text locate confirms and snaps | Most work; only option that is both exact and broad |

The user picked **C**.

## How it works

### 1. Coordinates (the "always correct for each page" rule)

- A box is `{page, x0, y0, x1, y1, how}`:
  - `page` is the **file** page number (1-based), the same numbering as `GET /files/{id}/pages/{page}`.
  - The coordinates are fractions (0–1) of the **untrimmed page as the reader saw it**. That is the stored file,
    with EXIF orientation already applied by `compress.py` or the browser shrink. For a PDF it is the page's full
    rect at any DPI.
  - `how` ∈ `text` | `ocr`: which word source confirmed the box.
- The reader and the viewer use the same stored file, so a photographed sideways page is sideways in both and the
  box stays aligned. The only transform between them is the viewer's **margin trim** (`page_trim.py`).
- Both page routes (`/api/accounting/files/{id}/pages/{n}` and the Extract one) add a response header
  `X-AA-Page-Crop: x0,y0,x1,y1`: the trimmed region as fractions of the untrimmed page, or `0,0,1,1` when untrimmed.
  It must be added to CORS `expose_headers`.
  - The trim functions (`content_box`, `_render_pdf_page_trimmed`) return their box alongside the bytes. The box
    must describe exactly the pixels returned, including the pad.
  - The frontend maps a box into the shown image with
    `(x - cx0) / (cx1 - cx0)`, and the same for y.
  - A box that falls outside the crop (more than 2% of the crop size) is not drawn.
- The page `v` in `accountingApi.pageImage` is bumped, so cached images without the header are refetched.

### 2. Reader asks for a hint box

- **Prompts.**
  - Documents: the detection/extraction prompts in `services/accounting/extraction.py` / `pipeline`.
  - Extract: `extract/prompts.py`.
  - Each gains a `where` object: `{field_key: {page, box}}` for header fields, and `where` inside each row object
    for row fields.
  - The page is the "Page N:" label the reader already sees. The prompt says to give a box only for a value printed
    on the page and to leave it out otherwise.
- **Coordinate formats differ by provider.** One parser in `services/accounting/field_boxes.py` turns them into
  fractions:
  - Qwen VL: `bbox_2d [x1,y1,x2,y2]`, 0–1000.
  - Gemini: `box_2d [ymin,xmin,ymax,xmax]`, 0–1000.
- **Chunk pages map back to file pages.** PDFs go 2 pages per call (Qwen) or 10 (Gemini), so the parser maps a
  chunk's page label back to the file page with the chunk's offset (`pipeline.read_chunks` knows it).
- **Extract row fields:** hints only for the first 20 rows of a record (my call, to keep the token cost within
  the +15% limit). Later rows use text locate without a hint (section 3).
- **Hint boxes are untrusted model output.** They are clamped to 0–1, must have positive area, at most 60% of the
  page in each dimension, and a page inside the record's `page_start..page_end`. Anything else is dropped.

### 3. Text locate confirms or snaps (`field_boxes.locate`)

Runs inside the extraction job, after values are cleaned, once per page that has a field:

- **Words with positions.**
  - A PDF page with a text layer: `page.get_text("words")` (PyMuPDF), in the existing memory-capped render child.
  - Otherwise (images, scanned PDFs): OCR with **RapidOCR (onnxruntime, CPU)** on the same render the reader got.
    It runs on the PDF child slots (`pdf_budget` / `render_pool.BACKGROUND_*`) so the viewer always keeps a slot,
    and is skipped when `storage.PDF_QUEUE_MAX`-style pressure is hit (no boxes, never a failure).
  - Results are cached per (file, page) for the job only.
- **Matching** the stored, cleaned value against word sequences, normalised per type:
  - money/number: digits and the decimal point, so `1,234.50`, `₱1,234.50` and `1234.50` all match.
  - dates: every common written form of the ISO date.
  - TIN: the digits (9 to 14).
  - text: case-folded words with punctuation stripped, all words in reading order, within a small gap.
- **Decision (strict, user's choice 2026-11-25: only confirmed boxes are ever drawn):**
  - **With a hint:** a box is drawn only when exactly one match has its centre inside the hint box (expanded 25%).
    If the single match on the page is outside the hint, no box is drawn.
  - **Without a hint** (old-style output, Extract rows past the first 20): a single match on the page is accepted
    only for distinctive values: TIN, document number, dates, and text of 2+ words. Amounts and one-word text
    without a hint get no box, because a lone `120.00` may be another line.
  - **No match:** no box. The model's hint is **never drawn**.
  - Values the system produces rather than reads are never located (builder's call, mine): amounts
    computed by the cleaner (VAT split, gross from net + VAT, `vat_difference`) and any field the reader left blank.
    The cleaner marks these, and a field it changed is treated as computed.
- `how` is therefore only `text` or `ocr`. Boxes get 1% padding.

### 4. Storage

- Documents: new column `aa_documents.field_boxes JSONB NOT NULL DEFAULT '{}'`. The model and `schema.py` both get
  it, keyed by the API's field keys (`seller_name`, `seller_tin`, `doc_number`, `doc_date`, `gross_amount`,
  `vatable_amount`, `vat_amount`, `exempt_amount`, `zero_rated_amount`, `withholding_amount`, `ewt_atc`,
  `seller_address`, `buyer_name`, `buyer_tin`, `buyer_address`).
- Extract: new column `aa_extract_records.boxes JSONB NOT NULL DEFAULT '{}'`, shaped like `values`:
  `{"header": {key: box}, "rows": [{key: box}]}`.
- **Hand edits:** when a person changes a field's value, its box is removed if the new value no longer matches the
  located text. Simplest rule: drop the box on any value edit unless the new value normalises to the same thing.
  Moving a document to another company (`move_company`) keeps its boxes, because the file didn't change.
- **Split or merged documents and page changes:** if `page_start`/`page_end` change, boxes outside the new range are
  dropped.
- Boxes are returned in the document and record payloads (`types/accounting.ts`, `types/extract.ts`).

### 5. Viewer behaviour (both `PageViewer`s)

- **One viewer.** Extract's `PageViewer` is replaced by the Documents one, which already zooms 1–5× around the
  pointer, with drag, pinch and slider. It is generalised to take `pages: {n, src}[]`, `boxes`, `active`
  (field key) and `flagged` (keys), plus `onBoxClick(key)`. Extract keeps its own image fetch (blob URL, 503 retry).
- **Overlay.** Boxes are drawn in a layer inside the same element that scales with zoom, so they stay locked to the
  image at every zoom with no re-maths. Blue solid for the active field, amber for flagged. Only boxes for the page
  shown are drawn.
- **Focusing a field with a box:**
  1. If the box is on another page, switch to that page and wait for its image *and* its crop header to load.
     Until both are in, draw no outline, so an outline never shows on the wrong page.
  2. If "Zoom to field" is on and the box isn't already fully in view: zoom so the box is about 40% of the view
     width (clamped 1–3×, MLLM-HTR uses ≤ 300%), then centre it.
  3. Outline it.
- A field without a box only clears the outline.
- **Keyboard and labels:** the outline follows focus as you Tab through fields. Field labels get a small "show on
  scan" affordance only when a box exists.
- **Phones:** the same behaviour inside the existing sheet layouts. In the Documents panel's stacked small layout,
  focusing a field scrolls the viewer into view first.
- **Tours:** add a `data-tour` stop for the "Zoom to field" toggle to the Documents tour (`tours/spots.ts`).

## Constraints

- **Dependencies:** `rapidocr-onnxruntime` and its pinned deps go in `pyproject.toml` *and*
  `backend/constraints.txt`. The models ship in the image, never downloaded at runtime. Check the image size and the
  4 GiB / 768 MiB-child memory budget (`pdf_budget`).
- **OCR fallback (my call, pending the user's confirmation):** OCR goes behind a setting (`FIELD_BOX_OCR`, on by
  default). If RapidOCR doesn't fit the budget (≤ 3 s CPU per page, the 768 MiB child limit, a reasonable image
  size), ship with it off: digital PDFs get boxes from their text layer, and photos/scans get none until OCR fits.
  Plan OCR as its own phase, after the text-layer path works end to end.
- **Security:** model output is never trusted (strict clamping, no strings from boxes rendered as HTML).
  `X-AA-Page-Crop` contains numbers only.
- **Resumable jobs:** locating runs inside the existing resumable extraction job. A crash before boxes are stored
  just leaves no boxes.
- **Billing:** no page charges change.
- Tests are pure-logic, like the rest of `backend/tests`: parser (Qwen and Gemini formats, chunk offsets, bad
  boxes), matcher (each type, duplicates + hint, no match), crop mapping, edit invalidation.

## Left to the builder

- Exact prompt wording and where `where` sits in each JSON shape.
- Text-matching gap tolerances and OCR confidence cut-off (prefer strict; measure on a handful of real receipts).
- Whether `locate` runs per document or per page batch.
- Component split for the shared viewer and the overlay.
- Which fields count as "flagged" for the amber outline in the Documents panel: map `checkDocument` keys and
  `review_reasons` that name a field. Reasons without a field get no outline.
