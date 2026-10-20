"""The firm assistant: a read-only Gemini agent over the firm's documents, books, filings and tax references.

``loop.run`` drives Gemini function calling over the tools in ``tools.py`` and yields stream events; ``guard.py``
holds the pure safety pieces (observation sanitizing, numeric grounding, history trimming); ``prompt.py`` the
system instruction. Ported from the STAI_OCR receipts agent, re-scoped to Philippine accounting firms.
"""
