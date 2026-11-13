# Extract tab: design

Date: 2026-11-13. Status: awaiting approval.

## Intent

Firms receive documents the normal upload pipeline has no shape for: a supplier's unusual invoice, a batch of
2307s that only needs to become a spreadsheet, a delivery form. The **Extract** tab is a standalone tool for
these. A person picks a format (or lets the app detect it), drops files, checks the fields on screen with
anything suspicious coloured yellow or red, fixes values by hand and downloads an Excel file. Nothing reaches a
company's books.

Formats are flexible. A firm starts with three built-in ones (BIR 2307, Receipt, Invoice) and can add its own or
edit any of them by dropping a sample document: the app reads the sample with a high-reasoning model call,
lists every field it sees, and proposes checks (for example subtotal + VAT = total). The person picks which
fields to keep.

## Decided with the owner

- New sidebar tab **Extract** at `/accounting/extract`.
- A format dropdown: **Auto detect**, the built-ins **BIR 2307** (SnagStock's fields), **Receipt**, **Invoice**,
  the firm's own formats, and **+ Add new**. Existing formats can be edited.
- Add / edit: drop a sample, the app extracts every field and asks which to keep. Picked fields are green,
  unpicked ones faded.
- A **Missing fields?** link (not shown open) reveals a small note box to say which fields were missed. It must be
  tightly guarded against prompt injection and abuse.
- Saved formats belong to the firm only. The platform admin can see every firm's formats, read-only.
- Saving a format produces, in the backend, an extraction prompt and validation logic for its fields. The
  format-building call uses high reasoning.
- Checks highlight yellow or red for review. VAT may be 12% or 0%; both must pass.
- Extract is standalone: table on screen, hand edits, Excel download, nothing posted to books.
- Anyone in the firm can use formats; only owners and managers add or edit them.
- Editing a built-in makes the firm's own copy; the original is untouched.
- Past runs are kept and can be reopened.

## Non-goals

- No posting to books, no filing into the company databank, no link to a company at all.
- No Casper tools, no global-search group, no page tour for this tab (first version).
- No sharing of formats between firms, no format marketplace.
- No model-written code, regular expressions or formulas. Ever.

## Anti-goals

- A person's typed text or a document's printed text changing what the reader is told to do.
- One firm seeing another firm's formats, samples or results (except the admin's read-only format list).
- A check that flags every zero-VAT document, so people learn to ignore the colours.

## How it works

### Formats

A format is `fields` + `checks` + a short `detect_hint` (what the document looks like, used by Auto detect).

Field: `key` (snake_case, <= 40), `label` (<= 60), `type` (`text | number | money | date | tin | percent | code |
boolean`), `scope` (`header` or `row`), `required`, `description` (<= 200). One line-item table per format
(row-scope fields). Caps: 60 fields, 30 checks.

Built-ins live in code (`extract/builtins.py`):

- **BIR 2307** (from SnagStock): period_from, period_to, payee_tin, payee_name, payee_address, payee_zip,
  payee_foreign_address, payor_tin, payor_name, payor_address, payor_zip; rows: nature_of_payment, atc, month_1,
  month_2, month_3, total_income, tax_withheld.
- **Receipt**: document_title, receipt_number, date, seller name / TIN / address, buyer name / TIN / address,
  vatable_sales, vat_amount, vat_exempt_sales, zero_rated_sales, total_amount, withholding_tax.
- **Invoice**: the Receipt fields plus due_date, payment_terms; rows: description, quantity, unit_price, amount.

A firm copy of a built-in carries `base_key` and replaces it in that firm's dropdown. "Reset to original"
removes the copy.

### Building a format (add / edit)

1. Owner or manager drops one sample (PDF / PNG / JPG, same validation as uploads; first 5 pages are read).
2. One **high-reasoning** reader call with a fixed instruction prompt (SnagStock style: name the sections,
   exact JSON shape, reading rules) returns: document name, detect hint, every field seen (label, type, scope,
   the value found) and proposed checks chosen from the catalogue below.
3. The server cleans the reply (`extract/spec.py`): unknown types / kinds dropped, text sanitized, caps applied,
   checks that name unknown fields dropped, and its own default checks added by field type (every `tin` field gets
   the TIN format check, document dates must not be in the future (due / period-end / validity dates are exempt)).
4. The proposal is stored as a draft (`aa_extract_drafts`). The screen shows field chips with the value found;
   the person switches them on or off, may rename a label and mark a field required, and sees each check as a
   plain sentence with its own switch.
5. Save sends only keys, labels, required flags and check ids. Definitions come from the stored draft (and the
   current format when editing), never from the browser. Checks whose fields were switched off are dropped.
6. The sample file is deleted on save, or after 24 hours.

The day-to-day extraction prompt is **generated by the server from the saved fields** (`extract/prompts.py`),
never stored as free model text: role line, document name, JSON shape, per-type reading rules (the SnagStock TIN
gridline and TIN length rules for `tin` fields, `YYYY-MM-DD` dates, plain-number amounts, `""` for blanks), the
one-entry-per-document rule with `page_start` / `page_end`, and a `confidence` per document.

### Missing fields

The link opens a note box (200 characters). Guardrails:

- Text is reduced to letters, digits, spaces and `- / . , ( ) % # & '`, single line, before anything else.
- Obvious instruction text ("ignore", "system prompt", "instead", role markers, URLs) is refused without a model
  call.
- The model call sends the sample plus a fixed prompt that quotes the text as a list of field names to look for.
  It may only return fields **printed on the sample**, each with the value it read. A field with no value is
  reported as "not found on this document" and is not added.
- The reply passes through the same cleaner as a proposal. At most 10 fields added and 5 asks per draft; 20 asks
  per person per hour; drafts 10 per person per hour.
- Blast radius if all of that fails: wrong values in that firm's own extract table. The reader has no tools and
  no other firm's data in context, and replies are parsed against the format (unknown keys dropped, every value
  cleaned by type).

### Checks (fixed catalogue, run by the server)

Pure functions in `extract/checks.py`. The model only chooses a kind and its field names.

| Kind | Meaning | Example |
|---|---|---|
| `required` | field is not blank | payee TIN |
| `sum` | signed terms add up to a target (header, or within each row) | subtotal + VAT = total; months 1 to 3 = total income |
| `percent_of` | target = one of `rates` % of a base; `inclusive` for VAT-inclusive bases | VAT = 12% or 0% of VATable sales |
| `rows_sum` | a row field's total = a header field | line amounts = subtotal |
| `row_product` | a x b = c in each row | quantity x unit price = amount |
| `date_order` | a is not after b | period from <= period to |
| `same_quarter` | two dates fall in one calendar quarter | 2307 period |
| `not_future` | date is not after today (Manila) | invoice date |
| `format` | named pattern only: `tin`, `atc`, `zip` | payor TIN |
| `one_of` | value is in a list (<= 20 values) | payment terms |
| `range` | number within min / max | amounts not negative |
| `not_more_than` | a <= b | tax withheld <= income |
| `differs` | two fields are not equal | payee TIN != payor TIN |

Results per check: pass, **yellow**, **red**, or skipped (a needed field is blank and not required).

- Money: difference <= 0.05 passes; <= the larger of 1.00 and 0.1% of the target is yellow; more is red.
- `percent_of` passes when any listed rate fits. With 0 in `rates`, a zero or blank VAT passes (zero-rated,
  exempt, non-VAT sellers). A VAT that fits no listed rate is red.
- `required` and `format` failures are red; the model may mark other checks yellow-only.
- Independent of checks: a value that can't be read as its type is red on that cell, and a document whose
  `confidence` is under 70 gets a yellow marker.

### Day-to-day use

1. Pick a format or Auto detect, drop files (same limits and budget rules as uploads; pages are charged the same
   way).
2. A run is created; files are read in the background with the format's generated prompt, chunked like the
   upload pipeline, reasoning off. One file can yield many records (a 50-page scan of 2307s).
3. Auto detect reads each file's first page against the firm's format names and hints; under 60% confidence the
   file waits for the person to pick a format.
4. The run screen shows a table: one line per record, header fields as columns, flagged cells yellow / red with
   the reason on hover; opening a record shows the page image beside its fields and row table.
5. A hand edit saves the value, marks the cell edited, and the server re-runs the checks.
6. **Download Excel** opens the workbook preview first (as every export does), then downloads: a Records sheet,
   a Lines sheet when the format has rows, flagged cells filled yellow / red, every cell through `csv_safe`.
7. Runs are listed under "Past extracts"; the creator or a manager can delete one.

### Who sees what

- Use: every firm role, gated by a new feature switch `extract` (maintenance switch + per-person access).
- Add / edit / delete / reset formats: owner and manager.
- Platform admin: a read-only "Extract formats" card on Platform admin listing every firm's formats (firm, name,
  who last edited, version, fields, checks, the generated prompt, deleted ones marked), through a SELECT-only
  admin RLS policy like `aa_assistant_usage`.

## Data

New tables, all `enterprise_id` + FORCE RLS:

- `aa_extract_formats`: name, description, base_key, fields, checks, detect_hint, version, created_by,
  updated_by, timestamps, deleted_at. Unique live name per firm; one live copy per base_key per firm.
- `aa_extract_drafts`: created_by, format_id (when editing), stored sample path, proposal, asks used, timestamps.
- `aa_extract_runs`: format key + name + snapshot of fields / checks used, status, created_by, timestamps.
- `aa_extract_files`: run, name, stored path, type, sha256, pages, status, detected format + confidence,
  interrupts, error.
- `aa_extract_records`: run, file, page_start / page_end, values (`header`, `rows`), edited keys, flags,
  confidence.

Files go under `ACCOUNTING_DIR/extract/<run id>/` through `storage.stream_upload`.

## Constraints from the codebase

- Reader: all model calls go through `gemini.call_gemini_raw`; it gains a `thinking` argument (OpenRouter
  `reasoning.enabled` + effort high, DashScope `enable_thinking`, Gemini `thinking_level=high`).
  `EXTRACT_BUILDER_MODEL` can name a stronger model; default is the reader model. Reader failures raise
  `ReaderUnavailable` and show the usual "our reader is unavailable" message.
- Background reads must be resumable (`jobs.stale_action` on run read, interrupts counted, released at shutdown).
- CPU work off the event loop; PDF chunks built one at a time inside the reader gate.
- Feature switch plumbing: `features.FEATURES` / `ROUTES`, `FeatureKey`, `access.PERSONAL_KEYS`,
  `team._ACCESS_HELP`, `tests/test_features.py`.
- Format create / edit / delete / reset and run delete are audited (`extract_format`, `extract_run`, company
  NULL).
- Body limits: run uploads share the batch upload cap; a sample is one file at `MAX_FILE_SIZE_MB`.

## Builder's calls (not decided by the owner; change freely)

- Pages read by Extract, including samples, are billed like upload pages.
- Runs are kept until someone deletes them; no automatic expiry.
- One line-item table per format.
- A missing field that isn't on the sample is not added.
- Auto detect looks at the first page only; a PDF mixing document types is read with one format.
- Samples: first 5 pages read, file deleted on save or after 24 hours.
- Admin view shows current formats with a version number, not a full edit history (the firm's audit log has it).
- Format building runs inside the request (no background job); the dialog shows a reading state.
- Field descriptions come from the model and are not editable by people; labels are.

## Left to the builder

Component breakdown, table column sizing, exact wording of check sentences and refusal messages, the builder
prompt's final text (it must follow the SnagStock structure and the rules above), test fixtures.
