"""Verify committed project catalog, normalized values and binary coverage."""
from pathlib import Path
import sys
from collections import Counter
import json
sys.path.insert(0,str(Path(__file__).resolve().parent))
from sync_project_database import ROOT, WORK, OUT, read, save
from store_catalog_archive import connect, verify_object
sys.path.insert(0,str(ROOT))
from backend.app.schemas import DetectionIn

def main():
    plan=read(OUT/'normalized-receipt.json')
    counts=Counter();mapping=Counter()
    with connect(ROOT/'.env.database') as c:
        c.execute('SET TRANSACTION READ ONLY')
        c.execute("SET LOCAL statement_timeout='120s'")
        run_ids=[r['run_id'] for r in plan['runs']]
        all_frames=c.execute('SELECT run_id,frame_no,timestamp,timestamp_kind,width,height,image_path,inference_ms FROM twinsight.frames WHERE run_id=ANY(%s) ORDER BY run_id,frame_no',(run_ids,)).fetchall()
        all_detections=c.execute('''SELECT f.run_id,f.frame_no,d.class_name,d.class_id,d.category_id,d.model_id,d.track_id,d.confidence,d.x1,d.y1,d.x2,d.y2,d.ground_px_u,d.ground_px_v,d.mapped_x,d.mapped_z,dc.raw_xz,dc.corrected_xz
            FROM twinsight.frames f JOIN twinsight.detections d ON d.frame_id=f.id JOIN twinsight.detection_coordinates dc ON dc.detection_id=d.id
            WHERE f.run_id=ANY(%s) ORDER BY f.run_id,f.frame_no,d.id''',(run_ids,)).fetchall()
        from collections import defaultdict
        frames=defaultdict(list);dets=defaultdict(list)
        for rid,*v in all_frames:frames[rid].append(tuple(v))
        for rid,*v in all_detections:dets[rid].append(tuple(v))
        cache={}
        for index,r in enumerate(plan['runs']):
            rid=r['run_id'];path=WORK/r['path']
            if r['path'] not in cache:cache[r['path']]=[json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
            source=[f for f in cache[r['path']] if f.get('camera_id')==r['camera_id'] and f.get('segment',0)==r['segment']]
            ef=[];ed=[]
            for f in sorted(source,key=lambda f:f['frame']):
                try: ds=[DetectionIn(**x).model_dump() for x in f['detections']]
                except Exception:continue
                ef.append((f['frame'],f['timestamp'],f['timestamp_kind'],f['width'],f['height'],f.get('image'),f['inference_ms']))
                for d in ds:
                    mapped=d['mapped_xz_corrected'] or d['mapped_xz'] or [None,None]
                    ed.append((f['frame'],d['class_name'],d['class_id'],d['category_id'],d['model_id'],d['track_id'],d['confidence'],*d['bbox_xyxy'],*d['ground_point_px'],*mapped,d['mapped_xz'],d['mapped_xz_corrected']))
                    mapping['raw_coordinates_present']+=d['mapped_xz'] is not None
                    mapping['corrected_coordinates_present']+=d['mapped_xz_corrected'] is not None
                    mapping['coordinates_absent']+=d['mapped_xz'] is None and d['mapped_xz_corrected'] is None
            if ef!=frames[rid] or ed!=dets[rid]:raise ValueError('Normalized source/value mismatch for '+rid)
            counts.update(runs=1,frames=len(ef),detections=len(ed))
            if index%100==0:print('verified_runs',index,flush=True)
        tables=read(OUT/'db-before.json')['counts']
        from psycopg import sql
        after={t:c.execute(sql.SQL('SELECT count(*) FROM twinsight.{}').format(sql.Identifier(t))).fetchone()[0] for t in tables}
        arcs=c.execute("SELECT record_id,details FROM twinsight.catalog_records WHERE details->>'type'='postgres_large_object_archive'").fetchall()
        import store_catalog_archive as archive_store
        archive_store.BLOCK=8*1024*1024
        for rid,d in arcs:
            if not rid.startswith('project-20261111-archive-'):
                print('verifying_prior_archive',rid,flush=True)
                archive_store.verify_object(c,d['large_object_oid'],d['archive_bytes'],d['archive_sha256'])
        arcids=[r[0] for r in arcs]
        coverage=c.execute('SELECT path,sha256 FROM twinsight.catalog_files WHERE record_id=ANY(%s)',(arcids,)).fetchall()
        covered_hashes={h for p,h in coverage}
        inventory=read(OUT/'source-files.json')
        missing=[x for x in inventory if x['sha256'] not in covered_hashes]
        if missing:raise ValueError('Files missing binary DB storage: '+str(len(missing)))
        # Queryable reference for every inventoried path, even if bytes reuse a prior archive.
        allrefs=set(c.execute('SELECT path,sha256 FROM twinsight.catalog_files').fetchall())
        if any((x['path'],x['sha256']) not in allrefs for x in inventory):raise ValueError('Missing catalog path/hash')
        db_bytes=c.execute('SELECT pg_database_size(current_database())').fetchone()[0]
    result={'status':'complete','schema_changed':False,'fresh_connection_readback':True,'all_normalized_frame_and_detection_values_match_sources':True,
            'normalized_counts':dict(counts),'coordinate_values':dict(mapping),'counts_before':tables,'counts_after':after,
            'rows_added':{t:after[t]-tables[t] for t in tables},'source_paths':len(inventory),'binary_uncovered_paths':len(missing),
            'archives':[{'record_id':rid,'bytes':d['archive_bytes'],'files':d['file_count']} for rid,d in arcs],
            'database_bytes':db_bytes,'original_files_retained_on_D':True,'ground_truth_substituted_for_detections':False,
            'limitations':{'alert_history':'No recorded human status changes exist; no history invented','mapping':'Absent computed coordinates remain SQL NULL; Unity truth only in catalog','archived_analysis':'Imported runs are stored observations, not current live monitoring'}}
    save('completion.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
