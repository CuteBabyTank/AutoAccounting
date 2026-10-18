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


LOCKED_REASON = "account_locked"


def locked_main_account(category: str, client_role: str, account: str, gl_override: str, chart) -> str | None:
    """The locked chart account a purchase / expense / payroll document would debit, else None."""
    if category in _BILLS and client_role == "buyer" and account != "capital_goods":
        code = chart.doc_account(account, gl_override)
    elif category == "payroll":
        code = chart.doc_account("salaries", gl_override)
    else:
        return None
    return code if chart.locked(code) else None


def flag_locked(fields: dict, chart, gl_rules: dict[str, str]) -> None:
    """A newly extracted document classified (directly or by the supplier's default account) to a locked account is
    queued for review with ``account_locked``, never posted silently and never rejected (mutates ``fields``)."""
    seller = fields.get("client_role") == "seller"
    tin = fields.get("buyer_tin" if seller else "seller_tin") or ""
    gl = fields.get("gl_account_code") or ("" if seller else gl_rules.get(tin, ""))
    if locked_main_account(fields.get("category", ""), fields.get("client_role", ""), fields.get("account", ""),
                           gl, chart) is None:
        return
    reasons = list(fields.get("review_reasons") or [])
    if LOCKED_REASON not in reasons:
        reasons.append(LOCKED_REASON)
    fields["review_reasons"] = reasons
    fields["needs_review"] = needs_review_for(reasons)


BULK_MAX = 200


def bulk_targets(docs, reason_code: str) -> tuple[list, list[tuple]]:
    """The documents a bulk resolve acts on (open and carrying ``reason_code``) and the rest with why not."""
    ok, skipped = [], []
    for d in docs:
        if d.deleted_at is not None:
            skipped.append((d.id, "deleted"))
        elif d.reviewed or d.excluded or not d.needs_review:
            skipped.append((d.id, "already resolved"))
        elif reason_code not in (d.review_reasons or []):
            skipped.append((d.id, "doesn't carry this reason"))
        else:
            ok.append(d)
    return ok, skipped
