# Field boxes: click a field, see it on the scan

Date: 2026-11-25 · Status: approved 2026-11-25 (updated: lazy, in-browser locating)

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

- No backfill job. Older documents still get boxes for distinctive values (TIN, number, date, names), because
  locating happens when the page is opened (section 3).
- No fixed-form templates for BIR forms (2307, 2550-Q). That is a possible later addition using MLLM-HTR's
  method.
- No boxes on line items in the Documents panel (it has no line items). Extract row fields **do** get boxes, per
  row.
- No editing of boxes by hand.

## Anti-goals (a failure even if it works)

- A box on the wrong spot, the wrong page or the wrong document. Every rule below prefers drawing nothing.
- Extra server cost: the only additions are about +15% reader output tokens for hints and a millisecond words read
  when a PDF page is opened. OCR never runs on the server.
- A slow or janky browser: OCR runs in a worker, one page at a time, only for pages that are open.
- A firm seeing another firm's boxes (they live on firm-scoped rows already under RLS).

## Approaches considered

| | How boxes are found | Trade-off |
|---|---|---|
| A. Text locate only | PDF text layer / OCR words, match the stored value | Never wrong, but no box for handwriting, computed values or values printed twice |
| B. Model boxes only | The reader returns a box per field | Covers nearly everything, but boxes are sometimes off or made up, so it can't be "always correct" |
| **C. Both (chosen)** | Model box as a hint, text locate confirms and snaps | Most work; only option that is both exact and broad |

Within C, the user then chose the cheapest way to run it: locate lazily, when a page is opened, in the browser
(Tesseract.js) rather than OCR in the extraction job (RapidOCR on Cloud Run, the first draft). Trade-offs: no server
CPU or new backend dependency, and older documents get boxes too. In exchange there is a one-time ~5 MB download and a
1 to 3 s wait before outlines appear on a newly opened scanned page.

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
- The trim crop comes from the page layout route (section 3), not from a response header. It returns the trimmed
  region as fractions of the untrimmed page, or `0,0,1,1` when untrimmed, plus the untrimmed aspect ratio. The trim
  render and the layout route call the same clip function, so they can't differ. The frontend maps a box into the
  shown image with `(x - cx0) / (cx1 - cx0)`, and the same for y. A box is not drawn when it falls outside the crop
  (more than 2%), or when the shown image's aspect ratio doesn't match the crop's (more than 2% off).

### 2. Reader asks for a hint box

- **Prompts.**
  - Documents: the detection/extraction prompts in `services/accounting/extraction.py` / `pipeline`.
  - Extract: `extract/prompts.py`.
  - Each gains a `where` object: `{field_key: {page, box}}` for header fields, and `where` inside each row object
    for row fields.
  - The page is the "Page N:" label the reader already sees. The prompt says to give a box only for a value printed
    on the page and to leave it out otherwise.
- **One coordinate format for every provider.** The prompt asks for `[page, x0, y0, x1, y1]` in 0–1000 from the
  top-left, which is Qwen VL's native order. Gemini (dev only) is told the same. `services/accounting/field_hints.py`
  turns it into fractions.
- **Chunk pages map back to file pages.** PDFs go 2 pages per call (Qwen) or 10 (Gemini), so the parser maps a
  chunk's page label back to the file page with the chunk's offset (`pipeline.read_chunks` knows it).
- **Extract row fields:** hints only for the first 20 rows of a record (my call, to keep the token cost within
  the +15% limit). Later rows use text locate without a hint (section 3).
- **Hint boxes are untrusted model output.** They are clamped to 0–1, must have positive area, at most 60% of the
  page in each dimension, and a page inside the record's `page_start..page_end`. Anything else is dropped.

### 3. Text locate, only when a page is opened, in the person's browser

The user's direction (2026-11-25): pick the cheapest, most efficient way. Locating runs only when someone opens a
page, and it runs on their computer, not the server. Nothing is located for pages nobody opens.

- **Hints** come from the extraction call that already happens (section 2), for a few more output tokens. They are
  the only thing stored on the server.
- **Words with positions**, fetched or made only when a page is shown in a panel:
  - **PDF page with a text layer:** `GET .../files/{id}/pages/{n}/words` returns `[[x0,y0,x1,y1,text], …]` as
    fractions of the untrimmed page. It is PyMuPDF `get_text("words")` in the existing isolated render child,
    with no rendering, so it takes milliseconds. It returns `[]` when the page has no text layer. It is cached
    like the page image (`private, max-age=3600`, `Vary: Authorization`), capped at 5,000 words, and firm-scoped
    like the page route.
  - **Images and scanned PDFs (`[]` above):** OCR in the browser with **Tesseract.js** in a Web Worker, on the
    page image the viewer already loaded. The worker, core WASM and `eng` fast traineddata (about 5 MB, cached by
    the browser after the first use) are self-hosted under `public/ocr/`, never a CDN. The CSP gains
    `'wasm-unsafe-eval'` in `script-src`: it allows compiling WebAssembly only, not JS eval. OCR words are in
    trimmed-image space, so they are mapped back to untrimmed fractions with the layout crop (section 1) before
    matching.
  - One OCR job at a time per tab. It is cancelled when the page or panel changes, and only runs while the tab is
    visible.
- **Cache:** words per (file id, page) are kept in memory for the session and in IndexedDB keyed by user. They are
  client data, so they are cleared on sign-out with the rest of `lib/personal-storage.ts`, and `public/app.js` is
  kept in step. Entries older than 7 days are pruned, total ≤ 20 MB. Reopening a page needs no new OCR.
- **Matching** (`lib/field-locate.ts`, pure TypeScript), on the stored, cleaned value against word sequences,
  normalised per type:
  - money/number: digits and the decimal point, so `1,234.50`, `₱1,234.50` and `1234.50` all match.
  - dates: every common written form of the ISO date.
  - TIN: the digits (9 to 14).
  - text: case-folded words with punctuation stripped, all words in reading order, within a small gap.
- **Decision (strict, user's choice 2026-11-25: only confirmed boxes are ever drawn):**
  - **With a hint:** a box is drawn only when exactly one match has its centre inside the hint box (expanded 25%).
    If the single match on the page is outside the hint, no box is drawn.
  - **Without a hint** (documents read before this ships, Extract rows past the first 20): a single match on the
    page is accepted only for distinctive values: TIN, document number, dates, and text of 2+ words. Amounts and
    one-word text without a hint get no box, because a lone `120.00` may be another line. Because locating is lazy,
    **older documents get these boxes too**, with no backfill.
  - **No match:** no box. The model's hint is **never drawn**.
  - Values the system produces rather than reads are never located (builder's call, mine): amounts computed
    by the cleaner (VAT split, gross from net + VAT, `vat_difference`) and any field the reader left blank. The
    server marks these in the hints (`"computed": true`); a field the cleaner changed counts as computed.
  - Boxes are recomputed from the **current** value, so a hand edit moves or removes its box automatically. No
    invalidation is stored.
- Boxes get 1% padding. `how` = `text` | `ocr`.

### 4. Storage

- Only hints are stored. Documents: new column `aa_documents.field_hints JSONB NOT NULL DEFAULT '{}'`. The model and
  `schema.py` both get it, keyed by the API's field keys (`seller_name`, `seller_tin`, `doc_number`, `doc_date`,
  `gross_amount`, `vatable_amount`, `vat_amount`, `exempt_amount`, `zero_rated_amount`, `withholding_amount`,
  `ewt_atc`, `seller_address`, `buyer_name`, `buyer_tin`, `buyer_address`). Each value is
  `{page, box: [x0,y0,x1,y1]}` or `{computed: true}`.
- Extract: new column `aa_extract_records.hints JSONB NOT NULL DEFAULT '{}'`, shaped like `values`:
  `{"header": {key: hint}, "rows": [{key: hint}]}`.
- Page range changes (split or merge) drop hints outside the new range. Moving a company keeps them.
- Hints are returned in the document and record payloads (`types/accounting.ts`, `types/extract.ts`).

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

- **Dependencies:** `tesseract.js` (pinned exact) plus its self-hosted worker, core and `eng` fast data in
  `public/ocr/`. No new backend dependency.
- **Frontend tests:** the repo has no frontend test runner. Add `vitest` (dev dependency, pinned) for
  `lib/field-locate.ts` and the crop mapping only.
- **Security:** model output is never trusted (strict clamping, no strings from boxes rendered as HTML).
  The layout route returns numbers and word text only.
- **Resumable jobs:** locating runs inside the existing resumable extraction job. A crash before boxes are stored
  just leaves no boxes.
- **Billing:** no page charges change.
- Backend tests are pure-logic, like the rest of `backend/tests`: hint parser (Qwen and Gemini formats, chunk
  offsets, bad boxes, computed marks), page-range pruning, and the words route's scoping. Frontend (vitest): matcher
  (each type, duplicates + hint, no hint, no match) and crop mapping.

## Left to the builder

- Exact prompt wording and where `where` sits in each JSON shape.
- Text-matching gap tolerances and OCR confidence cut-off (prefer strict; measure on a handful of real receipts).
- Whether `locate` runs per document or per page batch.
- Component split for the shared viewer and the overlay.
- Which fields count as "flagged" for the amber outline in the Documents panel: map `checkDocument` keys and
  `review_reasons` that name a field. Reasons without a field get no outline.
