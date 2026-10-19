"""Compress uploads stored before compression existed (one-off, safe to re-run).

    docker compose exec backend python -m app.services.accounting.compress_backfill [--dry-run]

Runs firm by firm with RLS bound to the firm owner. Each file is written under a new name, its row updated and
committed, and only then is the old file removed, so a crash never leaves a row pointing at a missing file. Files
already compressed come out no smaller and are left alone, so running it again does nothing.
"""

import argparse
import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from app.database import async_session
from app.dependencies import bind_session_user
from app.models.accounting import AAFile
from app.models.user import User, UserRole
from app.services.accounting.compress import compress_bytes
from app.services.accounting.storage import is_stored_path_safe

logger = logging.getLogger(__name__)
_EXT = {"pdf": ".pdf", "jpg": ".jpg", "png": ".png"}


async def _firm_ids() -> list[uuid.UUID]:
    async with async_session() as db:  # users isn't under RLS
        rows = await db.execute(select(User.id).where(User.role.in_([UserRole.ENTERPRISE, UserRole.ADMIN])))
        return [r[0] for r in rows]


async def backfill(dry_run: bool = False) -> tuple[int, int, int]:
    """(files compressed, bytes before, bytes after) across every firm."""
    done, before_total, after_total = 0, 0, 0
    loop = asyncio.get_running_loop()
    for firm in await _firm_ids():
        async with async_session() as db:
            await bind_session_user(db, str(firm))
            ids = (await db.execute(select(AAFile.id).where(AAFile.enterprise_id == firm))).scalars().all()
            for file_id in ids:
                row = await db.get(AAFile, file_id)
                src = Path(row.stored_path)
                if not is_stored_path_safe(row.stored_path) or not src.is_file():
                    continue
                data = await loop.run_in_executor(None, src.read_bytes)
                result = await loop.run_in_executor(None, compress_bytes, data, row.file_type)
                if result is None:
                    continue
                out, kind = result
                done, before_total, after_total = done + 1, before_total + len(data), after_total + len(out)
                logger.info("backfill file=%s type=%s from=%d to=%d", file_id, kind, len(data), len(out))
                if dry_run:
                    continue
                dest = src.with_name(f"{uuid.uuid4()}{_EXT[kind]}")
                await loop.run_in_executor(None, dest.write_bytes, out)
                row.stored_path, row.file_type, row.file_size = str(dest), kind, len(out)
                try:
                    await db.commit()
                except Exception:
                    await db.rollback()
                    dest.unlink(missing_ok=True)
                    raise
                src.unlink(missing_ok=True)
    return done, before_total, after_total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report the savings without changing anything")
    args = parser.parse_args()
    done, before, after = asyncio.run(backfill(args.dry_run))
    saved = before - after
    print(f"{'Would compress' if args.dry_run else 'Compressed'} {done} file(s): "
          f"{before / 1e6:.2f} MB → {after / 1e6:.2f} MB (saved {saved / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
