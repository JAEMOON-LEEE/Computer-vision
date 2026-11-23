"""Read-only DB and local artifact inventory. Never print connection secrets."""
from pathlib import Path
import json
import sys
from collections import Counter, defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parent))
from store_catalog_archive import connect

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runs/database-sync-20261111'
OUT.mkdir(parents=True, exist_ok=True)

def main():
    with connect(ROOT / '.env.database') as c:
        c.execute('SET TRANSACTION READ ONLY')
        c.execute("SET LOCAL statement_timeout='60s'")
        columns = c.execute("SELECT table_name,column_name,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema='twinsight' ORDER BY table_name,ordinal_position").fetchall()
        tables = sorted({x[0] for x in columns})
        from psycopg import sql
        counts = {t:c.execute(sql.SQL('SELECT count(*) FROM twinsight.{}').format(sql.Identifier(t))).fetchone()[0] for t in tables}
        constraints = c.execute("SELECT conrelid::regclass::text,conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace='twinsight'::regnamespace ORDER BY 1,2").fetchall()
        records = c.execute('SELECT record_id,kind,title,details FROM twinsight.catalog_records ORDER BY created_at').fetchall()
        files = c.execute('SELECT record_id,path,size_bytes,sha256,role FROM twinsight.catalog_files').fetchall()
        report={'columns':columns,'counts':counts,'constraints':constraints,'records':records,'files':files,
                'database_bytes':c.execute('SELECT pg_database_size(current_database())').fetchone()[0]}
    (OUT/'db-before.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    local=[]
    for rel in ['runs','datasets','detection/models','docs/validation','simulation/TwinSightSim/TwinSightExport','simulation/TwinSightSim/RealCctv','mapping']:
        folder=ROOT/rel
        groups=defaultdict(lambda: [0,0,Counter()])
        for p in folder.rglob('*'):
            if not p.is_file() or '__pycache__' in p.parts or p.is_relative_to(OUT): continue
            name=p.relative_to(folder).parts[0]
            s=p.stat().st_size
            groups[name][0]+=1;groups[name][1]+=s;groups[name][2][p.suffix]+=1
        local.append({'root':rel,'groups':dict(groups)})
    (OUT/'local-inventory.json').write_text(json.dumps(local,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'counts':counts,'db_bytes':report['database_bytes'],'archives':[{'id':r[0],'bytes':r[3].get('archive_bytes'),'files':r[3].get('file_count')} for r in records if r[3].get('type')=='postgres_large_object_archive'],'local':local},ensure_ascii=False,indent=2))

if __name__=='__main__':
    try: main()
    except Exception as e:
        from dotenv import dotenv_values
        import re
        msg=str(e)
        for value in dotenv_values(ROOT/'.env.database').values():
            if value and len(value)>8: msg=msg.replace(value,'[redacted]')
        msg=re.sub(r'(?:postgresql|postgres)\S+','[redacted connection]',msg)
        print(json.dumps({'error_type':type(e).__name__,'message':msg}))
        sys.exit(1)
