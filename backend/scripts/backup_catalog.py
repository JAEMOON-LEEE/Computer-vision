"""Consistent schema + client-side large-object backup. Contains private team data.

Run with --env-file and --pg-bin. Never commit the output directory.
The manifest is written only after all files have been verified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from dotenv import dotenv_values
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cfg = dotenv_values(args.env_file)
    url = make_url(cfg["DATABASE_URL"])
    schema = cfg.get("DATABASE_SCHEMA") or "twinsight"
    args.output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(PGHOST=url.host, PGPORT=str(url.port or 5432), PGUSER=url.username,
               PGPASSWORD=url.password, PGDATABASE=url.database, PGSSLMODE="require", PGCONNECT_TIMEOUT="15")
    with psycopg.connect(host=url.host, port=url.port or 5432, user=url.username,
                         password=url.password, dbname=url.database, sslmode="require") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename", (schema,)).fetchall()
        counts = {t: conn.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(t))).fetchone()[0] for (t,) in tables}
        subprocess.run([str(args.pg_bin / "pg_dump.exe"), "--format=custom", "--schema=" + schema,
                        "--no-blobs", "--enable-row-security", "--no-owner", "--no-privileges",
                        "--snapshot=" + snapshot, "--file=" + str(args.output / "schema-data.dump")],
                       env=env, check=True, stdout=subprocess.DEVNULL)
        print("Schema and table backup completed", flush=True)
        refs = conn.execute(sql.SQL("SELECT record_id, details FROM {}.catalog_records WHERE details::jsonb ? 'large_object_oid'").format(sql.Identifier(schema))).fetchall()
        objects = []
        for record_id, details in refs:
            oid = int(details["large_object_oid"])
            path = args.output / f"large-object-{oid}.bin"
            digest = hashlib.sha256()
            size = 0
            with path.open("wb") as target, conn.cursor(binary=True) as cursor:
                while True:
                    cursor.execute("SELECT lo_get(%s::oid,%s::bigint,%s::integer)", (oid, size, 4 * 1024 * 1024))
                    chunk = cursor.fetchone()[0]
                    if not chunk:
                        break
                    target.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            if size != int(details["archive_bytes"]) or digest.hexdigest() != details["archive_sha256"]:
                raise RuntimeError(f"Archive hash/size mismatch: {record_id}")
            objects.append({"oid": oid, "record_id": record_id, "file": path.name,
                            "bytes": size, "sha256": digest.hexdigest()})
            print(f"Verified archive {record_id}: {size} bytes", flush=True)
        owned = {r[0] for r in conn.execute("SELECT oid FROM pg_largeobject_metadata WHERE lomowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)")}
        if owned - {o["oid"] for o in objects}:
            raise RuntimeError("Uncatalogued owned large objects: backup is incomplete")
    manifest = {"schema": schema, "tables": counts, "large_objects": objects,
                "dump_sha256": hashlib.file_digest((args.output / "schema-data.dump").open("rb"), "sha256").hexdigest()}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Backup complete: {args.output}", flush=True)


if __name__ == "__main__":
    main()
