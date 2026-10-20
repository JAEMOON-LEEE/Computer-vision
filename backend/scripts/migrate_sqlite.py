"""Back up SQLite and copy into an empty PostgreSQL database, verifying every row."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, inspect, select, func, text, Integer
from backend.app.models import Base
from backend.app import catalog_models  # noqa: F401


def normalize(row, stream_timezone="Asia/Seoul"):
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=ZoneInfo(stream_timezone) if key == "stream_fetched_at" else timezone.utc)
            result[key] = value.astimezone(timezone.utc)
    return result


def digest(rows):
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False,
                            default=lambda v: v.isoformat(), separators=(",", ":")).encode())
        h.update(b"\n")
    return h.hexdigest()


def migrate(source, target, stream_timezone="Asia/Seoul"):
    if source.dialect.name != "sqlite" or target.dialect.name != "postgresql":
        raise ValueError("Migration requires SQLite source and PostgreSQL target")
    tables = Base.metadata.sorted_tables
    source_tables = set(inspect(source).get_table_names())
    unknown = source_tables - set(Base.metadata.tables)
    if unknown:
        raise ValueError(f"Unmanaged source tables: {sorted(unknown)}")
    report = {}
    with source.connect() as src, target.begin() as dst:
        Base.metadata.create_all(dst)
        for table in tables:
            dst.execute(text(f'LOCK TABLE "{table.name}" IN ACCESS EXCLUSIVE MODE'))
            if dst.scalar(select(func.count()).select_from(table)):
                raise ValueError("Target must be empty; no existing data was overwritten")
        for table in tables:
            statement = select(table).order_by(*table.primary_key.columns)
            if table.name in source_tables:
                columns = {c["name"] for c in inspect(source).get_columns(table.name)}
                if columns != set(table.columns.keys()):
                    raise ValueError(f"Schema mismatch: {table.name}")
                rows = [normalize(r, stream_timezone) for r in src.execute(statement).mappings()]
            else:
                rows = []
            for offset in range(0, len(rows), 500):
                dst.execute(table.insert(), rows[offset:offset + 500])
            copied = [normalize(r, stream_timezone) for r in dst.execute(statement).mappings()]
            if len(rows) != len(copied) or digest(rows) != digest(copied):
                raise ValueError(f"Content verification failed: {table.name}")
            report[table.name] = {"rows": len(rows), "sha256": digest(rows)}
            pk = list(table.primary_key.columns)
            if len(pk) == 1 and isinstance(pk[0].type, Integer):
                sequence = dst.scalar(text("SELECT pg_get_serial_sequence(:table, :column)"),
                                      {"table": table.name, "column": pk[0].name})
                if sequence:
                    maximum = dst.scalar(select(func.max(pk[0])))
                    dst.execute(text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"),
                                {"sequence": sequence, "value": max(maximum or 1, 1), "called": maximum is not None})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("backend/data/twinsight.db"))
    parser.add_argument("--stream-timezone", default="Asia/Seoul")
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error("Source SQLite file does not exist")
    folder = args.source.parent / "backups"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = folder / f"{args.source.stem}-{stamp}.db"
    with sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(backup) as dst:
            src.backup(dst)
    from backend.app.config import database_url
    source = create_engine("sqlite:///" + backup.resolve().as_posix())
    target = create_engine(database_url(), hide_parameters=True)
    try:
        report = migrate(source, target, args.stream_timezone)
        output = folder / f"migration-{stamp}.json"
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Verified migration. SQLite backup: {backup}; report: {output}")
    finally:
        source.dispose()
        target.dispose()


if __name__ == "__main__":
    main()
