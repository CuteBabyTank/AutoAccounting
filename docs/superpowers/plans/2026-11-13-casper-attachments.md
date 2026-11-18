# Casper temporary attachments implementation plan

**Goal:** Accept XLSX, PDF, JPG/JPEG and HEIC, at most 5 MiB total per message, without saving uploads.

**Architecture:** Send bounded base64 JSON to the existing authenticated chat route, avoiding multipart disk spooling. Validate and parse in a bounded disposable subprocess using memory only. Feed sanitized extracted text to the existing assistant as untrusted context; OCR images through the configured reader with usage metering. Keep attachment conversations out of browser storage and prevent attachment text from authorizing record changes.

**Approved scope:** User approved temporary uploads, financial statement drafts and preservation of existing guardrails in chat.

- [x] Test aggregate size, type/signature checks, workbook expansion/cell limits, PDF limits and transient parsing.
- [x] Implement attachment models, memory-only parser and OCR; account for OCR usage.
- [x] Integrate after existing authorization/rate/budget admission; preserve numeric grounding, scope and confirmation checks.
- [x] Add picker, removal, size errors and transient chat state in Casper's composer.
- [x] Run attachment and assistant tests, full backend suite, frontend lint/type checks; review diff.

Ruling: 5 MB means 5 × 1024 × 1024 bytes, matching this app's existing upload conventions. Limit attachment count to five and PDF length to ten pages to bound processing. Drafts are chat answers; this change does not add downloadable statement templates.

Review: independent reviewer found cached formula values were being discarded. Fixed by reading cached values alongside formulas; a real cached-XLSX regression passes. Re-review found no remaining concrete issues. Memory-only children share the existing PDF resource admission budget; extraction and chat share one turn deadline. OCR uses the configured Qwen or Gemini reader and counts toward assistant usage, including incomplete reads. Attachment turns cannot propose changes; temporary conversations stay in browser memory.

Validation: attachment/parser, reader metering, prompt injection, router admission and grounding tests; full backend suite; frontend TypeScript and changed-file ESLint; backend F/E9 lint. Full-suite optional tests remain skipped. Browser interaction could not be completed because the browser integration was unavailable and the native browser was being used concurrently; no live provider financial-document test was run.

Follow-up focused audit: fixed three reproduced bugs: mixed PDFs supplied the same financial text through both text extraction and whole-page OCR; stale XLSX dimension metadata silently omitted cells; account switching during asynchronous file encoding could send the old chat with the new account token. PDF pages now use one extraction path with page labels, actual workbook rows are read under the existing cell budget, and the auth token is captured and rechecked around encoding. Surplus base64 padding was tested and rejected by the current runtime; no size bypass was confirmed. Verified in network-disabled, read-only, resource-limited containers: 358 backend assistant tests and two frontend regressions pass. The HEIC decoder test could not be repeated in the audit image because that older image lacks pillow-heif; it passed during implementation. No live provider or browser test was performed in this audit.
