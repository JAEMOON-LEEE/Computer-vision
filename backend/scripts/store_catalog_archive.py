"""Store an experiment ZIP's exact bytes in PostgreSQL Large Objects and the team catalog.

No schema changes. The app role owns the object; no public grants are made.
The source file list is explicit, D-drive confined, immutable and hash checked.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import lzma
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

from dotenv import dotenv_values
import psycopg
from psycopg.types.json import Json

BLOCK = 1024 * 1024


@contextmanager
def open_archive(path):
    path = Path(path)
    temporary = None
    try:
        if path.suffix == '.xz':
            # All working files remain beside the archive on D.
            with tempfile.NamedTemporaryFile(dir=path.parent,suffix='.reading.zip',delete=False) as out:
                temporary = Path(out.name)
                with lzma.open(path,'rb') as source:
                    shutil.copyfileobj(source,out,BLOCK)
            with zipfile.ZipFile(temporary) as z:
                yield z
        else:
            with zipfile.ZipFile(path) as z:
                yield z
    finally:
        if temporary is not None:
            temporary.unlink()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(BLOCK), b''):
            h.update(b)
    return h.hexdigest()


def canonical(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False, allow_nan=False)


def connect(env):
    c = dotenv_values(env)
    if c.get('DATABASE_SCHEMA') != 'twinsight' or c.get('DATABASE_AUTO_CREATE') != 'false':
        raise ValueError('Use the existing twinsight catalog with automatic creation disabled')
    return psycopg.connect(c['DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://', 1),
                           connect_timeout=15, prepare_threshold=None)


def package(workspace, paths, destination, compression_preset=3):
    workspace, destination = workspace.resolve(), destination.resolve()
    if not destination.is_relative_to(workspace) or destination.exists():
        raise ValueError('Choose a new archive inside the D-drive workspace')
    items = []
    for source in sorted({Path(p).resolve() for p in paths}):
        if not source.is_relative_to(workspace) or not source.is_file():
            raise ValueError('Every artifact must be an existing workspace file')
        rel = source.relative_to(workspace)
        if any(p.startswith('.env') or p in {'.git', '.venv', 'node_modules', '__pycache__'}
               or 'private' in p.lower() for p in rel.parts):
            raise ValueError('Private or runtime path excluded')
        digest = sha(source)
        items.append({'path': rel.as_posix(), 'size_bytes': source.stat().st_size,
                      'sha256': digest, 'member': 'blobs/' + digest})
    destination.parent.mkdir(parents=True, exist_ok=True)
    solid = destination.suffix == '.xz'
    staging = destination.with_suffix('.building.zip') if solid else destination
    with zipfile.ZipFile(staging, 'x', compression=zipfile.ZIP_STORED if solid else zipfile.ZIP_DEFLATED,
                         compresslevel=None if solid else 6) as z:
        stored = set()
        for item in items:
            source = workspace / item['path']
            if item['member'] not in stored:
                z.write(source, item['member'])
                stored.add(item['member'])
            if sha(source) != item['sha256']:
                raise ValueError('Source changed during archive creation')
        z.writestr('artifact-index.json', json.dumps(items, ensure_ascii=False, indent=2))
    if solid:
        # A shared dictionary also compresses unchanged background bytes across adjacent frames.
        with staging.open('rb') as source,lzma.open(destination,'xb',preset=compression_preset) as out:
            shutil.copyfileobj(source,out,BLOCK)
        staging.unlink()
    # Verify bytes from the actual archive, not just the source filesystem.
    with open_archive(destination) as z:
        for item in items:
            h = hashlib.sha256()
            with z.open(item['member']) as f:
                for b in iter(lambda: f.read(BLOCK), b''):
                    h.update(b)
            if h.hexdigest() != item['sha256']:
                raise ValueError('Archive member hash mismatch')
    return {'archive': str(destination), 'sha256': sha(destination),
            'archive_bytes': destination.stat().st_size, 'files': items}


def verify_object(conn, oid, size, expected_sha, destination=None):
    h = hashlib.sha256()
    writer = destination.open('xb') if destination else None
    try:
        for offset in range(0, size, BLOCK):
            b = bytes(conn.execute('SELECT lo_get(%s,%s,%s)',
                                  (oid, offset, min(BLOCK, size-offset)),binary=True).fetchone()[0])
            if len(b) != min(BLOCK, size-offset):
                raise ValueError('Incomplete DB object')
            h.update(b)
            if writer:
                writer.write(b)
            if offset % (32*BLOCK)==0:
                print('verified_bytes',min(offset+len(b),size),flush=True)
        if conn.execute('SELECT octet_length(lo_get(%s,%s,1))', (oid, size)).fetchone()[0] != 0:
            raise ValueError('DB object longer than the immutable manifest')
    finally:
        if writer:
            writer.close()
    if h.hexdigest() != expected_sha:
        raise ValueError('DB binary hash mismatch')


def upload(manifest, env, team_root, parents, report):
    sys.path.insert(0, str(team_root.resolve()))
    from backend.app.routers.catalog import RecordIn, FileIn
    archive = Path(manifest['archive'])
    if sha(archive) != manifest['sha256'] or archive.stat().st_size != manifest['archive_bytes']:
        raise ValueError('Archive changed since packaging')
    record_id = 'night-v1-binary-archive-' + manifest['sha256'][:24]
    new = False
    with connect(env) as conn:
        conn.execute("SET LOCAL statement_timeout='120s'")
        # Serialize retries before checking/creating the immutable catalog record.
        conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (record_id,))
        old = conn.execute('SELECT details FROM twinsight.catalog_records WHERE record_id=%s', (record_id,)).fetchone()
        if old:
            d = old[0]
            oid = d['large_object_oid']
            if d['archive_sha256'] != manifest['sha256'] or d['archive_bytes'] != manifest['archive_bytes']:
                raise ValueError('Existing archive record conflicts')
        else:
            oid = conn.execute('SELECT lo_create(0)').fetchone()[0]
            with archive.open('rb') as source:
                for offset in range(0, manifest['archive_bytes'], BLOCK):
                    conn.execute('SELECT lo_put(%s,%s,%s)', (oid, offset, source.read(BLOCK)))
                    if offset % (10*BLOCK) == 0:
                        print('uploaded_bytes', min(offset+BLOCK, manifest['archive_bytes']), flush=True)
            details = {'type': 'postgres_large_object_archive', 'format': 'zip+xz' if archive.suffix=='.xz' else 'zip',
                       'large_object_oid': oid, 'archive_sha256': manifest['sha256'],
                       'archive_bytes': manifest['archive_bytes'], 'file_count': len(manifest['files']),
                       'file_index': 'artifact-index.json maps original paths to deduplicated blobs/', 'file_bytes_uploaded': True,
                       'storage': {'kind': 'postgres_large_object', 'availability': 'database_app_role',
                                   'local_source_retained': True},
                       'scope': manifest.get('scope','Night experiment original files; see artifact index')}
            body = RecordIn(record_id=record_id, kind='dataset', title='Night v1 archive: '+archive.name,
                            owner='TwinSight 팀 / 이진규 실험', data_origin=manifest.get('data_origin','synthetic'), status='completed',
                            camera_id=None, detection_run_id=None, parents=sorted(set(parents)), details=details).model_dump()
            fingerprint = hashlib.sha256(canonical(body).encode()).hexdigest()
            r = body
            conn.execute('''INSERT INTO twinsight.catalog_records
                (record_id,kind,title,owner,data_origin,status,camera_id,detection_run_id,details,fingerprint,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())''',
                (r['record_id'],r['kind'],r['title'],r['owner'],r['data_origin'],r['status'],None,None,Json(details),fingerprint))
            with conn.cursor() as cur:
                cur.executemany('INSERT INTO twinsight.catalog_parents(record_id,parent_id) VALUES(%s,%s)',
                                [(record_id,p) for p in r['parents']])
                files = [FileIn(path=f['path'],size_bytes=f['size_bytes'],sha256=f['sha256'],
                                role='artifact').model_dump() for f in manifest['files']]
                cur.executemany('''INSERT INTO twinsight.catalog_files(record_id,path,size_bytes,sha256,role)
                                VALUES(%s,%s,%s,%s,%s)''',
                                [(record_id,f['path'],f['size_bytes'],f['sha256'],f['role']) for f in files])
            new = True
        verify_object(conn, oid, manifest['archive_bytes'], manifest['sha256'])
    # A second connection proves the committed remote object is readable.
    with connect(env) as conn:
        verify_object(conn, oid, manifest['archive_bytes'], manifest['sha256'])
        actual = conn.execute('SELECT path,size_bytes,sha256 FROM twinsight.catalog_files WHERE record_id=%s',
                              (record_id,)).fetchall()
        expected = [(f['path'],f['size_bytes'],f['sha256']) for f in manifest['files']]
        if sorted(actual) != sorted(expected):
            raise ValueError('DB archive file index differs')
    result = {'committed': True, 'record_id': record_id, 'new_record': new,
              'large_object_oid': oid, 'archive_sha256': manifest['sha256'],
              'archive_bytes': manifest['archive_bytes'], 'original_files': len(manifest['files']),
              'file_bytes_uploaded': True, 'fresh_connection_binary_hash_verified': True,
              'schema_changed': False, 'public_grants_added': False}
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def download(record_id, env, destination, extract_dir=None):
    destination = destination.resolve()
    workspace = Path('D:/Capston disign').resolve()
    if not destination.is_relative_to(workspace) or destination.exists():
        raise ValueError('Choose a new D-drive archive destination')
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + '.partial')
    with connect(env) as conn:
        d = conn.execute('SELECT details FROM twinsight.catalog_records WHERE record_id=%s', (record_id,)).fetchone()[0]
        if d.get('type') != 'postgres_large_object_archive':
            raise ValueError('Not a binary archive')
        verify_object(conn, d['large_object_oid'], d['archive_bytes'], d['archive_sha256'], partial)
    partial.rename(destination)
    with open_archive(destination) as z:
        index = json.loads(z.read('artifact-index.json'))
        if extract_dir is not None:
            extract_dir = extract_dir.resolve()
            if not extract_dir.is_relative_to(workspace) or extract_dir.exists():
                raise ValueError('Choose a new D-drive extraction folder')
            extract_dir.mkdir(parents=True)
        for item in index:
            h = hashlib.sha256()
            target = None
            if extract_dir is not None:
                target = (extract_dir / item['path']).resolve()
                if not target.is_relative_to(extract_dir):
                    raise ValueError('Unsafe archive path')
                target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(item.get('member',item['path'])) as f:
                writer = target.open('xb') if target else None
                try:
                    for b in iter(lambda: f.read(BLOCK), b''):
                        h.update(b)
                        if writer: writer.write(b)
                finally:
                    if writer: writer.close()
            if h.hexdigest() != item['sha256']:
                raise ValueError('Restored member hash differs')
    return {'archive_sha256': sha(destination), 'member_hashes_verified': len(index),
            'destination': str(destination), 'extracted_to': str(extract_dir) if extract_dir else None}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['package','upload','download'])
    p.add_argument('--manifest', type=Path)
    p.add_argument('--file-list', type=Path, help='JSON array of absolute paths to archive')
    p.add_argument('--archive', type=Path)
    p.add_argument('--workspace', type=Path, default=Path('D:/Capston disign'))
    p.add_argument('--team-code-root', type=Path)
    p.add_argument('--parents', nargs='*', default=[])
    p.add_argument('--env-file', type=Path, default=Path('.env.database'))
    p.add_argument('--report', type=Path)
    p.add_argument('--record-id')
    p.add_argument('--extract-dir', type=Path)
    p.add_argument('--compression-preset', type=int, choices=range(10), default=3)
    a = p.parse_args()
    if a.mode == 'package':
        result = package(a.workspace, json.loads(a.file_list.read_text(encoding='utf-8')), a.archive,a.compression_preset)
        a.manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='files'}, ensure_ascii=False))
    elif a.mode == 'upload':
        result = upload(json.loads(a.manifest.read_text(encoding='utf-8')), a.env_file,
                        a.team_code_root, a.parents, a.report)
        print(json.dumps(result, ensure_ascii=False))
    else:
        result=download(a.record_id, a.env_file, a.archive, a.extract_dir)
        if a.report:
            a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
