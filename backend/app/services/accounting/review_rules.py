"""Review reasons that depend on evidence outside the document: payments (pure).

``payment_source_unknown`` (a payroll sheet says released, nothing shows the cash going out) and
``payment_unverified`` (a bill on credit terms with no payment yet) are raised from what Gemini read and
cleared once there is payment evidence: ``paid_on`` on the document, a receipt linked to it, or any id
the caller passes in ``paid_ids`` (bank-statement matches plug in there).
"""

from collections.abc import Iterable

# Shown on the document, but never put it in the review queue or block a month close.
SOFT_REASONS = frozenset({"payment_unverified"})
PAYMENT_REASONS = ("payment_source_unknown", "payment_unverified")
_BILLS = frozenset({"purchases", "expenses"})


def needs_review_for(reasons) -> bool:
    """Whether these reasons put a document in the review queue (soft reasons alone don't)."""
    return any(r not in SOFT_REASONS for r in reasons or ())


def _flag(value) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def payment_reasons(category: str, client_role: str, raw: dict | None) -> list[str]:
    """The payment reasons a document qualifies for before any evidence is considered."""
    raw = raw if isinstance(raw, dict) else {}
    if category == "payroll" and _flag(raw.get("marked_paid")):
        return ["payment_source_unknown"]
    terms = str(raw.get("payment_terms") or "").strip().lower()
    if client_role == "buyer" and category in _BILLS and terms == "credit":
        return ["payment_unverified"]
    return []


def sync_payment_flags(docs: Iterable, paid_ids: Iterable[str] = ()) -> None:
    """Add or drop the payment reasons on each document to match the evidence (mutates the documents).

    A reason is never added back to a document a person already reviewed.
    """
    docs = [d for d in docs if getattr(d, "deleted_at", None) is None]
    evidence = {str(i) for i in paid_ids}
    evidence |= {str(d.settles_document_id) for d in docs
                 if d.settles_document_id is not None and not getattr(d, "excluded", False)}
    for doc in docs:
        paid = doc.paid_on is not None or str(doc.id) in evidence
        wanted = set() if paid else set(payment_reasons(doc.category, doc.client_role, doc.raw))
        reasons = list(doc.review_reasons or [])
        kept = [r for r in reasons if r not in PAYMENT_REASONS or r in wanted]
        if not doc.reviewed:
            kept += [r for r in PAYMENT_REASONS if r in wanted and r not in kept]
        if kept != reasons:
            doc.review_reasons = kept
            doc.needs_review = needs_review_for(kept)
