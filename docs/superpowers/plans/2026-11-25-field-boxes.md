# Field Boxes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking or focusing a field in the Documents panel or the Extract record panel jumps to its page, zooms in
and outlines it on the scan. Flagged fields get an amber outline. A box is drawn only when it is confirmed.

**Architecture:**
- **Server:** the reader returns a hint box per field in the extraction call it already makes, and only those hints
  are stored. A light `layout` route returns a page's trim crop plus its PDF text-layer words, computed only when
  the page is opened.
- **Browser:** OCR for images and scans (Tesseract.js in a worker), matching of the field's value to words, and
  drawing. Boxes are never stored.

**Tech Stack:** FastAPI + SQLAlchemy + PyMuPDF (render child), Next.js/React/TS, tesseract.js (self-hosted), vitest.

**Spec:** `docs/superpowers/specs/2026-11-25-field-boxes-design.md`

## Global Constraints

- **Coordinates and hints:**
  - Every coordinate is a fraction (0–1) of the **untrimmed** page as the reader saw it.
  - `page` is the 1-based **file** page.
  - Hints are `{page, box: [x0,y0,x1,y1]}` or `{computed: true}`.
  - A hint is valid only if: x0<x1, y0<y1, each side ≤ 0.6, and the page is within the record's
    `page_start..page_end`.
- **Strict drawing:**
  - A model hint is **never drawn**.
  - With a hint, a box is drawn only when exactly one match has its centre inside the hint expanded by 25%.
  - Without a hint, a single match is accepted only for TIN, document number, dates, and text of 2+ words. Never for
    amounts or one-word text.
- **Values that aren't on the paper:** a field the cleaner computed or changed (its stored value doesn't normalise
  to the raw model value) or left blank gets `{computed: true}` and is never located.
- **Extract rows:** hints only for the first 20 rows of a record.
- **Server cost:** OCR never runs on the server. Words and crop come from `GET …/pages/{n}/layout` only when a page
  is opened. It is cached `private, max-age=3600`, `Vary: Authorization`, and capped at 5,000 words.
- **Browser OCR:**
  - The tesseract.js worker, core and `eng` fast traineddata are self-hosted under `frontend/public/ocr/`, never a
    CDN.
  - The CSP `script-src` gains `'wasm-unsafe-eval'`.
  - One OCR job per tab, cancelled on page or panel change, run only while `document.visibilityState === "visible"`.
- **Words cache:** in memory plus IndexedDB keyed by user, cleared on sign-out (`lib/personal-storage.ts` and
  `public/app.js`). Entries older than 7 days are pruned, total ≤ 20 MB.
- **Viewer:**
  - Zoom to make the box about 40% of the view width, clamped 1–3×, then centre it.
  - Blue solid outline for the active field, amber for flagged. Boxes get 1% padding.
  - "Zoom to field" toggle defaults on and is remembered per user in `localStorage`.
- **Pinned dependencies:** new deps are exact-pinned (`tesseract.js`, `vitest`). There are no new backend deps.
- **Schema:** schema changes go in the model *and* `services/accounting/schema.py`.
- **Routes:** new `/api/accounting` routes go in `features.ROUTES` (`tests/test_features.py` enforces it).
- **Commands:** backend tests run with `docker compose exec backend python -m pytest -q`; frontend checks with
  `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run`.

## Review Focus

1. **A trim crop that doesn't match the image shown** (a rendering fallback, a stale cached image). Expected: no
   outline at all. Test in Task 5, `boxInShown` returns null when the image aspect is off by more than 2%.
2. **A value printed twice on a page** (subtotal = total on a one-item receipt). Expected: no box unless the hint
   picks exactly one. Test in Task 5, "two matches, hint covers one" and "two matches, no hint".
3. **A rotated or sideways photo.** Expected: hints, OCR and image all use the same stored orientation, so the box
   lands correctly. Test in Task 4, layout of an image returns `words: []` and a crop from the decoded,
   EXIF-applied image.
4. **A hand edit that changes a value.** Expected: the box moves to the new text or disappears, and never stays on
   the old text. Test in Task 5, locating the edited value finds nothing → null.
5. **A switch to another page while OCR is running.** Expected: the old job is cancelled, and no outline from page
   A appears on page B. Test in Task 6, `wordsFor` called with an aborted signal rejects and does not populate the
   cache for the new key.

---

### Task 1: Hint parsing (pure)

**Files:**
- Create: `backend/app/services/accounting/field_hints.py`
- Test: `backend/tests/test_aa_field_hints.py`

**Interfaces:**
- Produces:
  - `parse_hint(value: object, page_offset: int, first: int, last: int) -> dict | None`. Model form
    `[page, x0, y0, x1, y1]` with coords 0–1000 and a chunk-local page → `{"page": p + page_offset, "box": [fractions
    rounded to 4 dp]}`, or None if invalid.
  - `doc_hints(where: object, values: dict[str, str], raw_values: dict[str, str], page_offset: int, first: int,
    last: int) -> dict`. Per key:
    - a valid hint when `values[key]` is non-blank and `norm(values[key]) == norm(raw_values[key])`;
    - `{"computed": True}` when the value is non-blank but differs from raw, or raw is blank;
    - omitted when the value is blank.
  - `norm(value: str) -> str`. Money → digits and `.` (`"1,234.50"` → `"1234.50"`, so `"1234.5"` → `"1234.50"`);
    otherwise case-fold and drop punctuation and whitespace.
  - `prune(hints: dict, first: int, last: int) -> dict`. Drops hints whose page is outside the range. Works on the
    flat shape and on the Extract shape `{"header": {}, "rows": [{}]}`.

- [ ] **Step 1: Write the failing tests**

```python
from app.services.accounting.field_hints import doc_hints, parse_hint, prune

def test_parse_hint_maps_chunk_page_and_scales():
    assert parse_hint([2, 100, 200, 300, 250], page_offset=4, first=5, last=6) == {"page": 6, "box": [0.1, 0.2, 0.3, 0.25]}

def test_parse_hint_rejects_bad_boxes():
    for bad in ([1, 300, 200, 100, 250], [1, 0, 0, 900, 50], [9, 1, 1, 2, 2], "x", [1, 1, 1], [1, -5, 0, 10, 10]):
        assert parse_hint(bad, page_offset=0, first=1, last=2) is None

def test_doc_hints_marks_computed_and_skips_blank():
    where = {"gross_amount": [1, 100, 100, 200, 120], "vat_amount": [1, 100, 130, 200, 150]}
    out = doc_hints(where, {"gross_amount": "1120.00", "vat_amount": "120.00", "doc_number": ""},
                    {"gross_amount": "1,120.00", "vat_amount": ""}, 0, 1, 1)
    assert out["gross_amount"]["page"] == 1 and out["vat_amount"] == {"computed": True} and "doc_number" not in out

def test_prune_drops_out_of_range_pages_in_both_shapes():
    assert prune({"a": {"page": 3, "box": [0, 0, .1, .1]}, "b": {"computed": True}}, 1, 2) == {"b": {"computed": True}}
    assert prune({"header": {"a": {"page": 1, "box": [0, 0, .1, .1]}}, "rows": [{"q": {"page": 4, "box": [0, 0, .1, .1]}}]}, 1, 2) \
        == {"header": {"a": {"page": 1, "box": [0, 0, .1, .1]}}, "rows": [{}]}
```

- [ ] **Step 2: Run them.** `docker compose exec backend python -m pytest -q tests/test_aa_field_hints.py`. Expected:
  ImportError / FAIL.
- [ ] **Step 3: Implement the four functions in `field_hints.py`.** Bounds are 0–1000, each side ≤ 600 (0.6).
  Non-list or non-numeric input → None.
- [ ] **Step 4: Run them again.** Expected: 4 passed.
- [ ] **Step 5: Commit.** `git commit -m "Field hints: parse and validate reader box hints"`

### Task 2: Documents store hints

**Files:**
- Modify: `backend/app/services/accounting/extraction.py`:
  - `EXTRACT_PROMPT`: add the `where` rule.
  - `ExtractedDoc`: add `hints: dict = field(default_factory=dict, compare=False)`.
  - `parse_extraction` (around line 252): build hints with `doc_hints(item.get("where"), …, page_offset, start,
    end)`.
- Modify: `backend/app/models/accounting.py` (`AADocument`) and `backend/app/services/accounting/schema.py`: add
  `field_hints JSONB NOT NULL DEFAULT '{}'`.
- Modify: the pipeline step that builds `AADocument` from `ExtractedDoc` (`pipeline.py`) to set `field_hints`.
- Modify: the document out schema and serializer in `routers/accounting.py` (`field_hints: dict`).
- Modify: every place that changes `page_start` / `page_end` (split / merge / PATCH; grep `page_end =`) to call
  `prune`.
- Test: `backend/tests/test_aa_field_hints.py` (add)

**Interfaces:**
- Consumes: `field_hints.doc_hints`, `prune`.
- Produces: the document JSON carries `field_hints: Record<string, {page:number, box:[number,number,number,number]} | {computed:true}>`.
  The keys are the 15 listed in the spec's Storage section. The raw values per key come from the item:
  - `seller.name` → `seller_name`, `seller.tin` → `seller_tin`, and so on for the other party fields;
  - `date` → `doc_date`;
  - the money fields by their own names.

- [ ] **Step 1: Write the failing test.** `test_parse_extraction_keeps_hints_on_file_pages`: a reply with one
  document, `"page_start": 2`, `"gross_amount": "1,120.00"`,
  `"where": {"gross_amount": [2, 500, 800, 700, 830], "vat_amount": [2, 500, 840, 700, 860]}`, and no `vat_amount`.
  `parse_extraction(raw, page_offset=2, chunk_pages=2)` gives
  `docs[0].hints["gross_amount"] == {"page": 4, "box": [0.5, 0.8, 0.7, 0.83]}`, and `"vat_amount"` is absent or
  computed. Also `test_prompt_asks_for_where`: `'"where"' in EXTRACT_PROMPT and "0-1000" in EXTRACT_PROMPT`.
- [ ] **Step 2: Run it and confirm it fails.**
- [ ] **Step 3: Add the prompt rule.** Copy, verbatim:
  `- "where": for each field you filled that is printed on the page, [page, x0, y0, x1, y1] around the printed value
  only (not its label), coordinates 0-1000 from the page's top-left, page as in the "Page N:" label (1 for a single
  image). Leave out fields you worked out rather than read.`
  Then wire `hints` through parse → pipeline → column → API, and prune on page range changes.
- [ ] **Step 4: Run all backend tests.** `docker compose exec backend python -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Documents: store the reader's field hints"`

### Task 3: Extract records store hints

**Files:**
- Modify: `backend/app/services/accounting/extract/prompts.py`: the reading prompt (around lines 204–230) gets the
  same `where` rule. Header `where` sits at record level; each row object gets its own `where`, for the first 20
  rows only.
- Modify: `backend/app/models/accounting.py` (`AAExtractRecord.hints`) + `schema.py`: `JSONB NOT NULL DEFAULT '{}'`.
- Modify: `backend/app/services/accounting/extract/runner.py` (`AAExtractRecord(` around line 538): set `hints`.
  Raw values come from the model item and cleaned values from `checks.clean_record`, using `doc_hints` per scope.
- Modify: the record out serializer in `routers/accounting_extract.py`.
- Test: `backend/tests/test_aa_extract_runner.py` (add)

**Interfaces:**
- Produces: the record JSON carries
  `hints: {header: Record<key, Hint>, rows: Record<key, Hint>[]}`, with `rows[i]` aligned to `values.rows[i]`.

- [ ] **Step 1: Write the failing test.** `test_record_hints_header_rows_and_cap`: a model item with 25 rows, each
  carrying a valid `where.amount`, plus header `where.total_amount`. Assert:
  - `hints["header"]["total_amount"]["page"] == 1`;
  - `len(hints["rows"]) == 25`;
  - `hints["rows"][19]` has `amount`, and `hints["rows"][20] == {}`.
  Also a prompt test: `'"where"' in` the built reading prompt for a format with row fields.
- [ ] **Step 2: Run it and confirm it fails.**
- [ ] **Step 3: Implement.** The rows cap is `HINT_ROWS = 20` in `field_hints.py`.
- [ ] **Step 4: Run all backend tests.** Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Extract: store the reader's field hints per record"`

### Task 4: Page layout route (crop + text-layer words)

**Files:**
- Modify: `backend/app/services/accounting/page_trim.py`:
  - Extract `pdf_clip(page) -> fitz.Rect | None` from `_render_pdf_page_trimmed`. It is the exact clip the
    trimmed render uses, and the render now calls it.
  - Add `image_crop(data: bytes) -> tuple[float,float,float,float]`: `content_box` as fractions, or `(0,0,1,1)` when
    None.
- Create: `backend/app/services/accounting/page_layout.py`:
  - `_pdf_layout_local(pdf_path, page_number) -> dict`, run in the render child as a new `render_pool` kind
    `"layout"` (JSON-encoded bytes).
  - `read_page_layout(stored_path: str, file_type: str, page: int) -> dict | None`, returning
    `{"crop": [x0,y0,x1,y1], "aspect": float, "words": [[x0,y0,x1,y1,"text"]], "text_layer": bool}`. `aspect` is
    the untrimmed width / height:
    - Crop: the `pdf_clip` fractions of `page.rect`, or `[0,0,1,1]` when None.
    - Words: `page.get_text("words")` as fractions, at most 5,000. Over the cap → `words: []`,
      `text_layer: false`.
    - Images: page 1 only, words `[]`, crop from `image_crop`.
- Modify: `backend/app/routers/accounting.py` (next to `file_page`, line 1495) and
  `routers/accounting_extract.py` (next to `extract_file_page`): add `GET /files/{id}/pages/{page}/layout`, same
  scoping and `run_pdf_work` as the page route, with the cache headers from Global Constraints.
- Modify: `backend/app/services/features.py` `ROUTES`: the two new paths, in the same areas as their page routes.
- Test: `backend/tests/test_aa_page_layout.py`

**Interfaces:**
- Produces: `GET /api/accounting/files/{id}/pages/{n}/layout` and `GET /api/accounting/extract/files/{id}/pages/{n}/layout`
  → `PageLayout = {crop:[n,n,n,n], aspect:number, words:[n,n,n,n,string][], text_layer:boolean}`.

- [ ] **Step 1: Write the failing tests.** They build PDFs in memory with `fitz` and save them to `tmp_path`.
  - `test_pdf_layout_words_and_crop_match_trim`:
    - Build a Letter page with "TOTAL 1,234.50" inserted at (400, 600), saved to `tmp_path`.
    - Call `_pdf_layout_local`.
    - Assert `text_layer` is true.
    - Assert a word `"1,234.50"` has x0 within 0.01 of 400/612 + its offset.
    - Assert the crop equals the `pdf_clip` fractions (the trimmed render's region).
  - `test_image_layout_has_no_words_and_full_crop_for_unmarginal_photo`: a dark-background photo → crop
    `[0,0,1,1]`, `words == []`.
  - `test_layout_caps_words`: a page with 6,000 words → `words == []` and `text_layer is False`.
  - `test_features` must still pass.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.** The trimmed render and the layout must call the same `pdf_clip` (and `content_box`),
  so the crop and the shown image can't differ.
- [ ] **Step 4: Run all backend tests, then ruff.** Run all backend tests, then
  `docker compose exec backend ruff check app --select F,E9`. Expected: both clean.
- [ ] **Step 5: Commit.** `git commit -m "Page layout route: trim crop and text-layer words, on demand"`

### Task 5: Matching (pure TS) + vitest

**Files:**
- Modify: `frontend/package.json`: devDependency `vitest` (exact pin), script `"test": "vitest run"`.
- Create: `frontend/src/lib/field-locate.ts`
- Test: `frontend/src/lib/field-locate.test.ts`

**Interfaces:**
- Produces:
  - Types:
    - `type Rect = [number, number, number, number]`
    - `type Word = [number, number, number, number, string]`
    - `type Hint = { page: number; box: Rect } | { computed: true }`
    - `type FieldKind = "money" | "number" | "date" | "tin" | "docno" | "text"`
  - `locate(value: string, kind: FieldKind, words: Word[], hint: Hint | undefined, page: number): Rect | null`.
    - Rect is in untrimmed fractions, padded 1%.
    - A `computed` hint → null. A hint for another page → that page's call returns null.
    - The rest follows the strict rules in Global Constraints.
  - `boxInShown(box: Rect, crop: Rect, shownAspect: number, pageAspect: number): Rect | null`. Returns the box in
    the shown image's fractions, or null when:
    - `shownAspect` differs from `pageAspect * (crop width / crop height)` by more than 2%; or
    - the box lies more than 2% of the crop size outside the crop.
  - `pageAspect` is the untrimmed width / height. The layout route also returns `"aspect": number`, so add it in
    Task 4's return shape: PDF `page.rect`, image decoded size.

- [ ] **Step 1: Write the failing tests** (vitest, `describe("locate")`):
  - money: words `["Total","₱1,234.50"]` with a hint around the second → that word's rect, padded.
  - money with no hint → null.
  - two `1,234.50` words: the hint covers one → that one; no hint → null; the hint covers both → null.
  - date `2026-11-03` matches `Nov 3, 2026` (3 words) and `11/03/2026`.
  - tin `123456789` matches `123-456-789-000`.
  - text `"Juan Dela Cruz Hardware"` without a hint, found once in order → the union rect. The one-word text `"Cash"`
    without a hint → null.
  - `{computed: true}` → null. An edited value that isn't on the page → null.
  - `boxInShown`: crop `[0.1,0.1,0.9,0.9]` maps box `[0.5,0.5,0.6,0.6]` → `[0.5,0.5,0.625,0.625]`. An aspect off by
    5% → null.
- [ ] **Step 2: Run them and confirm they fail.** `cd frontend && npm i && npx vitest run src/lib/field-locate.test.ts`.
- [ ] **Step 3: Implement `field-locate.ts`.** Match on normalised word *sequences*: join up to 6 consecutive words
  on the same line (centres within half a word height). Normalise as in Task 1's `norm`; dates are compared via the
  forms generated from the ISO value.
- [ ] **Step 4: Run them again.** Expected: all pass. Also `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `git commit -m "Field locate: strict value-to-words matching"`

### Task 6: Page words in the browser (layout + OCR + cache)

**Files:**
- Modify: `frontend/package.json`: `tesseract.js` (exact pin).
- Create:
  - `frontend/scripts/copy-ocr.mjs`: copies the worker, the core (`tesseract-core-simd-lstm*.wasm.js`) and the `eng`
    *fast* traineddata into `public/ocr/`. Run from `postinstall`. Commit the traineddata file, since it isn't in
    node_modules.
  - `frontend/src/lib/page-words.ts`
- Modify:
  - `frontend/src/middleware.ts:45`: add `'wasm-unsafe-eval'` to `script-src`.
  - `frontend/src/lib/personal-storage.ts` `clearPersonalStorage`: also `indexedDB.deleteDatabase("aa-page-words")`.
  - `frontend/public/app.js` sign-out: the same.
  - `frontend/src/lib/accounting-api.ts`, `extract-api.ts`: add `pageLayout(fileId, page): Promise<PageLayout>`.

**Interfaces:**
- Consumes: the Task 4 routes.
- Produces: `wordsFor(src: "accounting" | "extract", fileId: string, page: number, image: HTMLImageElement, signal:
  AbortSignal): Promise<{ crop: Rect; aspect: number; words: Word[] }>`.
  - It uses the text-layer words when `text_layer` is true.
  - Otherwise it OCRs the shown image and maps the OCR words from shown → untrimmed using the crop.
  - Results are cached by `${userId}:${src}:${fileId}:${page}`.

- [ ] **Step 1: Write the failing tests.** `page-words.test.ts`, with the API and OCR mocked:
  - The text layer is used and OCR isn't called.
  - The second call for the same key hits the cache.
  - An aborted signal rejects with `AbortError` and leaves no cache entry.
  - The OCR word at shown `[0,0,0.5,0.5]` with crop `[0.2,0.2,0.6,0.6]` maps to `[0.2,0.2,0.4,0.4]`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
  - One lazily created Tesseract worker per tab: `workerPath`, `corePath` and `langPath` all point to `/ocr/`, and
    `workerBlobURL: false`.
  - One job at a time; a new request aborts the old one.
  - Skip while the tab is hidden (wait for `visibilitychange`).
  - IndexedDB `aa-page-words`: store `{key, at, bytes, value}`. Prune entries older than 7 days and the oldest ones
    past 20 MB on open. Every IDB access is in try/catch, falling back to memory only.
- [ ] **Step 4: Check it.** Run the tests, `npx tsc --noEmit` and `npm run build`. Confirm `public/ocr/` holds the
  worker, core and traineddata.
- [ ] **Step 5: Commit.** `git commit -m "Page words: text layer or in-browser OCR, cached per person"`

### Task 7: Shared viewer with overlay + zoom to field (Documents panel)

**Files:**
- Modify: `frontend/src/components/accounting/PageViewer.tsx`. New optional props:
  - `src: "accounting" | "extract"`, `fileId: string`, `pageNumbers: number[]` (file pages, aligned with `images`);
  - `targets: { key: string; value: string; kind: FieldKind; hint?: Hint }[]`;
  - `active: string | null`, `flagged: string[]`, `onBoxClick?: (key: string) => void`.
- Create: `frontend/src/components/accounting/FieldOverlay.tsx`: absolutely positioned boxes inside the zoomed page
  element (the one sized `zoom × box`). It takes the boxes in shown fractions.
- Modify: `frontend/src/components/accounting/DocumentPanel.tsx`:
  - Track `active` from each `field()` input's `onFocus` / `onClick`.
  - Build `targets` from `draft` + `doc.field_hints`. Kinds: amounts → money, dates → date, `*_tin` → tin,
    `doc_number` → docno, the rest → text.
  - `flagged` = keys with a `checkDocument` result.
  - `onBoxClick` focuses that input.
- Modify: `frontend/src/types/accounting.ts` (`field_hints`).
- Modify: `frontend/src/components/guide/tours/spots.ts`: a Documents stop for `data-tour="zoom-to-field"`.

**Interfaces:**
- Consumes: `locate`, `boxInShown` (Task 5), `wordsFor` (Task 6).

- [ ] **Step 1: Write the failing test.** `PageViewer.logic.test.ts` covers the pure helper `zoomFor(box: Rect,
  viewW: number, viewH: number, pageW: number): { zoom: number; left: number; top: number }`:
  - the box ends up about 40% of the view width, clamped 1–3;
  - it is centred;
  - a box already fully in view → `null` (keep zoom, move the outline only).
- [ ] **Step 2: Run it and confirm it fails.**
- [ ] **Step 3: Implement.**
  - For a box on another page: switch the page and draw nothing until that page's image `onLoad` **and** its
    `wordsFor` have resolved for the same `(fileId, page)`. Check the key on resolve and drop stale results.
  - Add the "Zoom to field" toggle in the bar, with `data-tour="zoom-to-field"` and its `localStorage` key
    `aa:zoom-field:${userId}` (try/catch).
  - A field with no box clears the outline.
  - Stacked small layout: `scrollIntoView` the viewer on focus.
- [ ] **Step 4: Check it.** Run the tests, `npm run lint`, `npx tsc --noEmit`. Then manually, with
  `docker compose up -d`:
  - Open a text-layer PDF invoice and a phone photo receipt (both read after Task 2).
  - Tab through the fields: the outlines land on the values, and pages switch for multi-page documents.
  - Edit an amount: its outline disappears.
- [ ] **Step 5: Commit.** `git commit -m "Documents panel: outline and zoom to the focused field"`

### Task 8: Extract record panel uses the shared viewer

**Files:**
- Modify: `frontend/src/components/extract/RecordPanel.tsx`: replace `extract/PageViewer` with the shared viewer.
  - Keep its blob fetch and the single 503 retry: load the images, then pass `images` + `pageNumbers`.
  - `targets`: header fields plus row fields keyed `row:{i}:{key}`, from `record.values` + `record.hints`. Kinds
    come from the format field types: money/number/percent → money/number, date → date, tin → tin, otherwise text.
  - `active` from `focusCell`. `flagged` from the record's flag `cells`.
- Delete: `frontend/src/components/extract/PageViewer.tsx` once it has no imports.
- Modify: `frontend/src/types/extract.ts` (`hints`).

**Interfaces:**
- Consumes: Task 7's `PageViewer` props, and `src: "extract"`.

- [ ] **Step 1: Write the failing test.** `extract-targets.test.ts` covers the pure `recordTargets(record,
  snapshot)`:
  - a row-field key `row:3:amount` carries `hints.rows[3].amount`;
  - a row with no hint has `hint` undefined;
  - a percent field maps to `number`.
- [ ] **Step 2: Run it and confirm it fails.**
- [ ] **Step 3: Implement.** Put `recordTargets` in `frontend/src/lib/extract-targets.ts`, then wire it in.
- [ ] **Step 4: Check it.** Run the tests, lint and tsc. Then manually: run an Extract on a multi-row invoice, click
  the header and row cells, and check the outlines. Rows past 20 are boxed only when the value is distinctive.
- [ ] **Step 5: Commit.** `git commit -m "Extract: outline and zoom to the focused cell"`

### Task 9: Docs + ship check

**Files:**
- Modify: `CLAUDE.md`: add a "Field boxes" gotcha. Cover:
  - hints only, the strict rule and the `computed` marks;
  - the layout route and `pdf_clip` shared with the trim;
  - browser OCR self-hosted in `public/ocr/`, `'wasm-unsafe-eval'`;
  - the IndexedDB words cache cleared on sign-out;
  - a new document field needs a `doc_hints` key + a `targets` kind.

- [ ] **Step 1: Write the CLAUDE.md entry.**
- [ ] **Step 2: Run everything.**
  - `docker compose exec backend python -m pytest -q`
  - `docker compose exec backend ruff check app --select F,E9`
  - `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run && npm run build`
  - Expected: all pass, and the build output lists no CSP or WASM errors.
- [ ] **Step 3: Commit.** `git commit -m "CLAUDE.md: field boxes"`
