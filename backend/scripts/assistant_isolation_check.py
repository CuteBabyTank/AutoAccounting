"""Live assistant isolation smoke check; creates fixtures and removes them in finally.

Run inside backend: python -m scripts.assistant_isolation_check
Uses the configured real DB, no LLM. Tests application filtering even with a superuser DB role.
"""

import asyncio
import json
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import delete

from app.database import async_session
from app.dependencies import bind_session_user
from app.models.accounting import AACompany, AADocument, AAFile, AAUpload
from app.models.user import User, UserRole
from app.routers.accounting_scope import scope_for
from app.services.accounting.assistant import tools


async def seed(user_id: uuid.UUID, marker: str):
    async with async_session() as db:
        user = User(id=user_id, email=f"assistant-isolation-{marker}@example.invalid", role=UserRole.ENTERPRISE)
        db.add(user)
        await db.flush()
        await bind_session_user(db, str(user_id))
        company = AACompany(enterprise_id=user_id, registered_name=f"Isolation Client {marker}",
                            books_start=date(2026, 1, 1))
        db.add(company)
        await db.flush()
        upload = AAUpload(enterprise_id=user_id, uploaded_by=user_id)
        db.add(upload)
        await db.flush()
        file = AAFile(enterprise_id=user_id, upload_id=upload.id, company_id=company.id,
                      original_filename="isolation.txt", stored_path="/tmp/assistant-isolation-unused",
                      file_type="pdf", file_size=0, sha256=marker.ljust(64, "0")[:64])
        db.add(file)
        await db.flush()
        doc = AADocument(enterprise_id=user_id, company_id=company.id, file_id=file.id,
                         doc_type="invoice", category="purchases", seller_name=f"SecretSupplier{marker}",
                         gross_amount=Decimal("9876.54"), doc_number=f"SECRET-{marker}",
                         doc_date=date(2026, 10, 1), period_year=2026, period_quarter=4)
        db.add(doc)
        await db.flush()
        fixture = {"user": user_id, "company": str(company.id), "name": company.registered_name,
                   "document": str(doc.id), "supplier": doc.seller_name, "number": doc.doc_number}
        await db.commit()
        return fixture


async def main():
    ids = [uuid.uuid4(), uuid.uuid4()]
    marker = uuid.uuid4().hex[:12]
    checks = 0
    try:
        a = await seed(ids[0], f"A{marker}")
        b = await seed(ids[1], f"B{marker}")
        async with async_session() as db:
            user = await db.get(User, a["user"])
            await bind_session_user(db, str(user.id))
            ctx = tools.Ctx(db=db, user=user, ent=scope_for(user))

            async def run(name, args, *, error=False):
                nonlocal checks
                # Rebind after loaders that commit. App-level predicates are independent of RLS.
                await bind_session_user(db, str(user.id))
                result = await tools.call(ctx, name, args)
                data = tools.as_json(result.data)
                if error:
                    assert "error" in data, (name, args, data)
                    assert not result.sources, (name, result.sources)
                else:
                    assert "error" not in data, (name, data)
                    encoded = json.dumps({"data": data, "sources": result.sources})
                    for secret in (b["document"], b["supplier"], b["number"]):
                        assert secret not in encoded, (name, secret, encoded)
                    for source in result.sources:
                        assert source.get("company_id") in (None, a["company"]), source
                checks += 1
                print(f"PASS {name} {json.dumps(args)}", flush=True)
                return data

            # Positive controls: distinguish isolation from broken tools returning nothing.
            companies = await run("list_companies", {})
            assert [c["company_id"] for c in companies["companies"]] == [a["company"]]
            own = await run("get_document", {"document_id": a["document"]})
            assert own["seller_name"] == a["supplier"]
            found = await run("search", {"query": a["supplier"]})
            assert any(g["items"] for g in found["groups"])

            foreign_doc = await run("get_document", {"document_id": b["document"]}, error=True)
            missing_doc = await run("get_document", {"document_id": str(uuid.uuid4())}, error=True)
            assert foreign_doc == missing_doc
            for ref in (b["company"], b["name"]):
                for name, args in (
                    ("search", {"query": b["supplier"]}), ("report", {"kind": "pnl"}),
                    ("aging", {"kind": "ar"}), ("aging", {"kind": "ap"}), ("company_health", {}),
                    ("filings", {}), ("quarter_returns", {"year": 2026, "quarter": 4}),
                ):
                    await run(name, {**args, "company": ref}, error=True)
            foreign_company = await run("company_health", {"company": b["company"]}, error=True)
            missing_company = await run("company_health", {"company": str(uuid.uuid4())}, error=True)
            assert foreign_company == missing_company
            for query in (b["supplier"], b["name"], b["document"], b["number"]):
                result = await run("search", {"query": query})
                assert not result["groups"], result
            await run("filings", {})
            await run("tax_reference", {"query": "2550Q"})
            await run("ask_clarification", {"question": "Which period do you mean?"})
            # Tool arguments cannot override the server's firm context.
            result = await run("list_companies", {"enterprise_id": str(b["user"]), "ent": str(b["user"])})
            assert [c["company_id"] for c in result["companies"]] == [a["company"]]
        print(f"PASS: {checks} isolation checks", flush=True)
    finally:
        # Delete only the two generated UUIDs, including partially created fixtures after a failure.
        for user_id in ids:
            async with async_session() as db:
                await bind_session_user(db, str(user_id))
                await db.execute(delete(User).where(User.id == user_id))
                await db.commit()
        print("Removed both throwaway firms and their cascading fixture rows.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
