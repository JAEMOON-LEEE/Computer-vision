"""Append existing TwinSight evidence to the existing DB; never synthesize results.

All preparation, manifests, archives and receipts stay on D. Data imports are
immutable, content-addressed and replayable. Ground truth remains catalog data.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import yaml
from dotenv import dotenv_values
from psycopg.types.json import Json
from psycopg import sql

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT.parent
OUT=ROOT/'runs/database-sync-20261111'
TEAM=WORK/'reviews/db-catalog-3bddc0d'
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from register_experiment_catalog import Builder, upload as upload_catalog, digest, file_hash
from store_catalog_archive import connect, package, verify_object, canonical
from database_bulk import insert_rows

def save(name,value):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str),encoding='utf-8')
    return p

def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))

def discover():
    before=read(OUT/'db-before.json')
    candidates=set()
    ignored=[]
    roots=[ROOT/'runs',ROOT/'datasets',ROOT/'detection/models',ROOT/'detection/config',ROOT/'detection/configs',
           ROOT/'docs/validation',ROOT/'docs/images',ROOT/'simulation/TwinSightSim/TwinSightExport',
           ROOT/'simulation/TwinSightSim/RealCctv']
    for version in ['opencv-2b75753','geumchon-real-2b75753']:
        roots.extend([WORK/f'reviews/{version}/simulation/TwinSightSim/RealCctv',WORK/f'reviews/{version}/verification'])
    excludes={'__pycache__','.git','.venv','node_modules','.ultralytics','restored','restored-sources',
              'restored-outputs','source-restored','output-restored','restored-files','database-sync-20261111',
              'github-publish-20261023','database-registration-20261022'}
    text_ext={'.json','.jsonl','.yaml','.yml','.txt','.csv','.log','.md','.py','.ps1'}
    cfg=dotenv_values(ROOT/'.env.database')
    from sqlalchemy.engine import make_url
    secrets=[make_url(cfg['DATABASE_URL']).password]
    secrets += [v for k,v in dotenv_values(ROOT/'.env').items() if v and ('KEY' in k or 'TOKEN' in k) and len(v)>12]
    signed=re.compile(r'(?:wmsAuthSign|nimblesessionid|apiKey)\s*[=:]\s*[A-Za-z0-9%+/._-]{12,}',re.I)
    for root in roots:
        if not root.exists(): continue
        for directory,dirs,files in os.walk(root):
            dirs[:]=sorted(d for d in dirs if d not in excludes and not d.startswith('.interrupted') and 'restor' not in d.lower())
            for name in sorted(files):
                p=Path(directory)/name
                if name.startswith('.env') or p.suffix in {'.cache','.pyc','.db','.zip','.xz','.tar','.ts'}:
                    continue
                if 'public-sources' in p.parts and 'real-traffic-v1' not in p.parts: continue
                if p.suffix.lower() in text_ext:
                    text=p.read_text(encoding='utf-8-sig',errors='replace')
                    if any(s and s in text for s in secrets) or signed.search(text):
                        ignored.append({'path':p.relative_to(WORK).as_posix(),'reason':'credential or signed stream content; not uploaded'})
                        continue
                candidates.add(p)
    print('inventory_paths',len(candidates),flush=True)
    # Reuse only files whose current bytes match the previously uploaded hashes.
    known={}
    for _,path,size,sha,_ in before['files']:
        known[(path,size)]=sha
    archives={r[0] for r in before['records'] if r[3].get('type')=='postgres_large_object_archive'}
    covered={sha for rid,path,size,sha,role in before['files'] if rid in archives}
    items=[]
    for i,p in enumerate(sorted(candidates)):
        rel=p.relative_to(WORK).as_posix();st=p.stat()
        # Hash actual bytes; catalog references alone are not byte storage proof.
        sha=file_hash(p)
        if (st.st_size,st.st_mtime_ns)!=(p.stat().st_size,p.stat().st_mtime_ns): raise ValueError('File changed during inventory')
        items.append({'path':rel,'size_bytes':st.st_size,'sha256':sha,'covered_by_existing_binary_archive':sha in covered})
        if i%2000==0: print('hashed',i,flush=True)
    save('source-files.json',items)
    save('exclusions.json',{'files':ignored,'excluded_groups':['runtime caches and environments','restored copies','existing archive containers (their originals are indexed)','unused public downloads','temporary interrupted output'],
                            'truth_policy':'Unity world X/Z stays ground truth in catalog; never substituted for AI mapped X/Z',
                            'alert_history_policy':'No human state changes are fabricated'})
    print('inventory_complete',len(items),'new_bytes',sum(x['size_bytes'] for x in items if not x['covered_by_existing_binary_archive']),flush=True)

def group_for(p):
    parts=p.relative_to(ROOT).parts if p.is_relative_to(ROOT) else ()
    if not parts:return 'team-'+p.relative_to(WORK/'reviews').parts[0], 'calibration','real'
    if parts[0]=='datasets':return 'dataset-'+parts[1],'dataset','real' if parts[1] in {'real-traffic-mio-v1','public-sources'} else 'synthetic'
    if parts[0]=='runs':
        name=parts[1] if len(parts)>2 else 'loose-logs'
        if len(parts)>3 and parts[1]=='validation-lab':name+='/'+parts[2]
        return 'experiment-'+name,'evaluation','real' if name.startswith('real-') else 'mixed' if name.startswith('validation') else 'synthetic'
    if parts[:3]==('simulation','TwinSightSim','TwinSightExport'):return 'capture-'+parts[3],'capture','synthetic'
    if parts[:3]==('simulation','TwinSightSim','RealCctv'):return 'city-camera-profile','calibration','real'
    if parts[:2]==('detection','models'):return 'model-'+p.stem,'model','real' if p.stem.startswith(('real-','yolo')) else 'synthetic'
    return 'support-'+parts[0],'evaluation','mixed'

def prepare():
    if not (OUT/'source-files.json').exists():discover()
    items=read(OUT/'source-files.json')
    b=Builder(ROOT,TEAM,ROOT/'.env.database','origin/codex/local-db-validation@3bddc0d + inspected remote 12-table schema 2026-11-11')
    groups=defaultdict(list)
    for x in items:
        p=WORK/x['path'];groups[group_for(p)].append(p)
        role='image' if p.suffix.lower() in {'.png','.jpg','.jpeg'} else 'label' if 'labels' in p.parts else 'model' if p.suffix.lower() in {'.pt','.xml','.onnx'} else 'artifact'
        st=p.stat();b.file_cache[(str(p.resolve()),st.st_size,st.st_mtime_ns)]={'path':x['path'],'size_bytes':x['size_bytes'],'sha256':x['sha256'],'role':role}
    root_record=b.add('project-evidence-sync-20261111','evaluation','mixed',details={'type':'project_evidence_snapshot','synthetic_ground_truth_is_not_ai_mapping':True,'source_date':'2026-11-11','production_ready':False})
    group_ids={}
    for (name,kind,origin),files in sorted(groups.items()):
        details={'type':'artifact_group','source_group':name,'synthetic_ground_truth_is_not_ai_mapping':True,'production_ready':False}
        # Small primary reports remain structured and queryable, full reports stay as exact bytes.
        reports={}
        for p in files:
            if p.name in {'work-complete.json','provenance.json','dataset-check.json','completion.json','selection.json','camera.json','capture.json','session.json'} and p.stat().st_size<70000:
                try:reports[p.relative_to(WORK).as_posix()]=b.read_json(p)
                except (ValueError,json.JSONDecodeError):pass
        if len(canonical(reports).encode())<350000: details['reports']=reports
        safe_name=re.sub('[^A-Za-z0-9_.-]+','-',name)[:85]
        group_ids[name]=b.add('sync-20261111-'+safe_name,kind,origin,files,details,[root_record],logs=True)
    # Explicit class order, split, label bytes and image/label hashes for every dataset.
    bypath={x['path']:x for x in items}
    for folder in sorted((ROOT/'datasets').iterdir()):
        if not (folder/'dataset.yaml').exists():continue
        config=yaml.safe_load((folder/'dataset.yaml').read_text(encoding='utf-8-sig'))
        classes=config['names'];classes=list(classes.values()) if isinstance(classes,dict) else classes
        splits={}; hashes={}; overlap=[]
        for split in ['train','val','test']:
            samples=[]
            for image in sorted((folder/'images'/split).glob('*')):
                if image.suffix.lower() not in {'.jpg','.jpeg','.png','.bmp','.webp'}:continue
                label=folder/'labels'/split/(image.stem+'.txt')
                i=bypath[image.relative_to(WORK).as_posix()];l=bypath[label.relative_to(WORK).as_posix()]
                if i['sha256'] in hashes and hashes[i['sha256']]!=split:overlap.append([hashes[i['sha256']],split,i['path']])
                hashes[i['sha256']]=split
                text=label.read_bytes().decode('utf-8-sig')
                boxes=[[float(v) for v in line.split()] for line in text.splitlines() if line.strip()]
                samples.append({'image':i['path'],'image_sha256':i['sha256'],'label':l['path'],'label_sha256':l['sha256'],'label_text':text,'boxes_yolo':boxes})
            splits[split]=len(samples)
            for part,start in enumerate(range(0,len(samples),60)):
                b.add(f'sync-labels-{folder.name}-{split}-{part:03}','dataset','real' if folder.name=='real-traffic-mio-v1' else 'synthetic',
                      details={'type':'yolo_split_annotations','dataset':folder.name,'split':split,'classes':classes,'samples':samples[start:start+60],'exact_label_text_in_database':True},parents=[group_ids['dataset-'+folder.name]])
        b.add('sync-split-audit-'+folder.name,'evaluation','real' if folder.name=='real-traffic-mio-v1' else 'synthetic',details={'dataset':folder.name,'split_counts':splits,'byte_identical_cross_split_images':len(overlap),'overlap_examples':overlap[:5],'not_a_camera_independence_test':True},parents=[group_ids['dataset-'+folder.name]])
        save('split-audits/'+folder.name+'.json',{'split_counts':splits,'byte_identical_cross_split_images':len(overlap)})
    save('catalog-manifest.json',{'format':'twinsight-catalog-import-v1','workspace':str(WORK),'source_catalog_code':b.code_ref,'records':b.records,'excluded':b.excluded,'file_bytes_uploaded':False})
    save('group-record-ids.json',group_ids)
    print('catalog_prepared',len(b.records),sum(len(e['logs']) for e in b.records),flush=True)

def upload_metadata():
    print(json.dumps(upload_catalog(read(OUT/'catalog-manifest.json'),ROOT/'.env.database',OUT/'catalog-receipt.json'),ensure_ascii=False),flush=True)

def supplement():
    """Keep the original HLS media segments as well as decoded CCTV frames."""
    items=read(OUT/'source-files.json');paths={x['path'] for x in items}
    b=Builder(ROOT,TEAM,ROOT/'.env.database','existing inspected team catalog schema')
    files=[]
    for p in sorted((ROOT/'runs/real-cctv-20261022').rglob('*.ts')):
        files.append(p)
        rel=p.relative_to(WORK).as_posix()
        if rel not in paths:items.append({'path':rel,'size_bytes':p.stat().st_size,'sha256':file_hash(p),'covered_by_existing_binary_archive':False})
    parent=read(OUT/'catalog-manifest.json')['records'][0]['record']['record_id']
    b.add('sync-20261111-original-cctv-segments','capture','real',files,{'type':'original_hls_media_segments','training_use':False,'source':'ITS Geumchon archived capture; signed API response files excluded'},[parent])
    manifest={'workspace':str(WORK),'records':b.records}
    save('supplement-manifest.json',manifest)
    save('source-files.json',sorted(items,key=lambda x:x['path']))
    print(upload_catalog(manifest,ROOT/'.env.database',OUT/'supplement-receipt.json'),flush=True)

def normalize():
    from backend.app.schemas import DetectionIn, AlertIn
    items=read(OUT/'source-files.json');groups=read(OUT/'group-record-ids.json')
    expected=[];bad=[];counts=Counter()
    db=connect(ROOT/'.env.database')
    detection_files=[x for x in items if Path(x['path']).name in {'detections.jsonl','mapped.jsonl','detections-mapped.jsonl'}]
    for file in detection_files:
        path=WORK/file['path']
        source=read(path.parent/'session.json') if (path.parent/'session.json').exists() else {}
        chunks=defaultdict(list)
        for number,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
            if not line.strip():continue
            try:
                f=json.loads(line)
                for k in ['camera_id','frame','timestamp','timestamp_kind','width','height','inference_ms','detections']:
                    if k not in f:raise ValueError('missing '+k)
                if f['width']<=0 or f['height']<=0 or f['frame']<0:raise ValueError('invalid shape')
                f['detections']=[DetectionIn(**d).model_dump() for d in f['detections']]
                canonical(f)
                chunks[(f['camera_id'],f.get('segment',0))].append(f)
            except Exception as e:
                bad.append({'path':file['path'],'line':number,'reason':type(e).__name__})
        alerts=[]
        for p in sorted(path.parent.glob('*alerts.jsonl')):
            if p.relative_to(WORK).as_posix() not in {x['path'] for x in items}:continue
            for line in p.read_text(encoding='utf-8-sig').splitlines():
                if not line.strip():continue
                try: alerts.append(AlertIn(**json.loads(line)).model_dump())
                except Exception: bad.append({'path':p.relative_to(WORK).as_posix(),'reason':'alert schema mismatch'})
        for (camera_id,segment),frames in sorted(chunks.items()):
            if len({f['frame'] for f in frames})!=len(frames):
                bad.append({'path':file['path'],'reason':'repeated frame numbers; raw evidence preserved in catalog'});continue
            run_id='archive-'+hashlib.sha256((file['path']+file['sha256']+str(camera_id)+str(segment)).encode()).hexdigest()[:32]
            origin='synthetic' if any(f['timestamp_kind']=='simulation_seconds' for f in frames) else 'real' if 'real-' in file['path'] or source.get('options',{}).get('model') in {'real-coco','real-traffic'} else 'unspecified'
            matching={}
            for a in alerts:
                if a['camera_id']==camera_id and any(f['frame']==a['frame'] and abs(f['timestamp']-a['timestamp'])<0.001 for f in frames):
                    # Policy variants can reuse alert numbers: retain each variant as its own evidence ID.
                    key=a['alert_id']
                    if key in matching and matching[key]!=a: a=dict(a,alert_id=key+'-variant-'+digest(a)[:10])
                    matching[a['alert_id']]=a
            kind=frames[0]['timestamp_kind']
            if len({f['timestamp_kind'] for f in frames})!=1:raise ValueError('Mixed time bases in one run')
            with db.transaction():
                c=db
                c.execute("SET LOCAL statement_timeout='120s'")
                c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(run_id,))
                old=c.execute('SELECT camera_id FROM twinsight.runs WHERE run_id=%s',(run_id,)).fetchone()
                if not old:
                    c.execute('INSERT INTO twinsight.cameras(camera_id,name,source,image_width,image_height,status) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                              (camera_id,'보관 분석 / '+camera_id,origin+'_archive',frames[0]['width'],frames[0]['height'],'archived'))
                    started=source.get('started_at')
                    c.execute('INSERT INTO twinsight.runs(run_id,camera_id,timestamp_kind,started_at) VALUES(%s,%s,%s,%s)',(run_id,camera_id,kind,datetime.fromisoformat(started) if started else datetime.fromtimestamp(path.stat().st_mtime,timezone.utc)))
                    if camera_id in {'its-cc4277cc18','utic-국도1호선파주금촌신사거리'}:
                        pose=read(ROOT/'simulation/TwinSightSim/RealCctv/geumchon.pose.json')
                        lat,lon=pose['origin_latlon']
                        c.execute('INSERT INTO twinsight.map_references(run_id,origin_lat,origin_lon) VALUES(%s,%s,%s)',(run_id,lat,lon))
                        plat,plon=pose['position_latlon']
                        c.execute('UPDATE twinsight.cameras SET lat=COALESCE(lat,%s),lon=COALESCE(lon,%s) WHERE camera_id=%s',(plat,plon,camera_id))
                    # Batch frames, return generated IDs, then batch their detections.
                    with c.cursor() as cur:
                        insert_rows(cur,'frames','run_id,frame_no,timestamp,timestamp_kind,width,height,image_path,inference_ms',[(run_id,f['frame'],f['timestamp'],f['timestamp_kind'],f['width'],f['height'],f.get('image'),f['inference_ms']) for f in frames])
                    ids=dict(c.execute('SELECT frame_no,id FROM twinsight.frames WHERE run_id=%s',(run_id,)).fetchall())
                    values=[];coords=[]
                    for f in frames:
                        for d in f['detections']:
                            mapped=d['mapped_xz_corrected'] or d['mapped_xz'] or [None,None]
                            values.append((ids[f['frame']],d['class_name'],d['class_id'],d['category_id'],d['model_id'],d['track_id'],d['confidence'],*d['bbox_xyxy'],*d['ground_point_px'],*mapped))
                            coords.append((d['mapped_xz'],d['mapped_xz_corrected']))
                    with c.cursor() as cur:
                        if values:
                            insert_rows(cur,'detections','frame_id,class_name,class_id,category_id,model_id,track_id,confidence,x1,y1,x2,y2,ground_px_u,ground_px_v,mapped_x,mapped_z',values)
                            det_ids=[row[0] for row in c.execute('SELECT id FROM twinsight.detections WHERE frame_id=ANY(%s) ORDER BY id',(list(ids.values()),)).fetchall()]
                            if len(det_ids)!=len(coords):raise ValueError('Detection ID mapping mismatch')
                            insert_rows(cur,'detection_coordinates','detection_id,raw_xz,corrected_xz',[(i,Json(raw) if raw is not None else None,Json(corrected) if corrected is not None else None) for i,(raw,corrected) in zip(det_ids,coords)])
                        if matching:
                            insert_rows(cur,'alerts','run_id,alert_id,camera_id,frame_no,timestamp,type,severity,status,message,evidence,basis',[(run_id,a['alert_id'],camera_id,a['frame'],a['timestamp'],a['type'],a['severity'],a['status'],a['message'],Json(a['evidence']),a['basis']) for a in matching.values()])
                nf,nd,nc,na=c.execute('SELECT (SELECT count(*) FROM twinsight.frames WHERE run_id=%s),(SELECT count(*) FROM twinsight.detections d JOIN twinsight.frames f ON f.id=d.frame_id WHERE f.run_id=%s),(SELECT count(*) FROM twinsight.detection_coordinates dc JOIN twinsight.detections d ON d.id=dc.detection_id JOIN twinsight.frames f ON f.id=d.frame_id WHERE f.run_id=%s),(SELECT count(*) FROM twinsight.alerts WHERE run_id=%s)',(run_id,)*4).fetchone()
                if [nf,nd,nc,na]!=[len(frames),sum(len(f['detections']) for f in frames),sum(len(f['detections']) for f in frames),len(matching)]:raise ValueError('Normalized readback count mismatch')
            counts.update(runs=1,frames=nf,detections=nd,detection_coordinates=nc,alerts=na)
            entry={'run_id':run_id,'camera_id':camera_id,'path':file['path'],'source_sha256':file['sha256'],'origin':origin,'segment':segment,'frames':nf,'detections':nd,'alerts':na,'catalog_parent':groups[group_for(path)[0]],'new':not bool(old)}
            expected.append(entry)
            save('normalized-progress.json',{'counts':dict(counts),'runs':expected,'not_normalized':bad})
        if len(expected)%20==0: print('normalized_runs',len(expected),dict(counts),flush=True)
    db.close()
    save('normalized-receipt.json',{'committed':True,'counts':dict(counts),'runs':expected,'not_normalized':bad,'ground_truth_used_as_ai_coordinates':False,'alert_history_fabricated':False})
    print('normalized_complete',dict(counts),flush=True)

def package_new():
    items=read(OUT/'source-files.json')
    # Content deduplication across old DB archives and across this upload.
    pending=[x for x in items if not x['covered_by_existing_binary_archive']]
    chunks=[];current=[];size=0
    aliases=defaultdict(list)
    for x in pending:aliases[x['sha256']].append(x)
    for sha,paths in aliases.items():
        extra=paths[0]['size_bytes']
        if size+extra>128*1024**2 and current:chunks.append(current);current=[];size=0
        current.extend(paths);size+=extra
    if current:chunks.append(current)
    save('archive-plan.json',{'chunks':len(chunks),'paths':len(pending),'existing_covered_paths':len(items)-len(pending)})
    for number,chunk in enumerate(chunks):
        meta=OUT/f'archives/part-{number:03}.json'
        if meta.exists():continue
        archive=OUT/f'archives/part-{number:03}.zip.xz'
        result=package_snapshot(chunk,archive)
        result['data_origin']='mixed';result['scope']='TwinSight project source data, models and evaluation evidence as of 2026-11-11; exact paths in artifact-index.json'
        result['record_prefix']='project-20261111-archive-'
        result['title']='TwinSight project archive 2026-11-11 / part '+str(number)
        save(f'archives/part-{number:03}.json',result)
        print('packaged',number,'bytes',result['archive_bytes'],'files',len(result['files']),flush=True)

def package_snapshot(items, destination):
    """Bounded in-memory ZIP staging avoids extra reads of thousands of source files."""
    import io, lzma, zipfile
    if destination.exists():raise ValueError('Preserve existing archive; choose a fresh part')
    destination.parent.mkdir(parents=True,exist_ok=True)
    index=[{'path':x['path'],'size_bytes':x['size_bytes'],'sha256':x['sha256'],'member':'blobs/'+x['sha256']} for x in items]
    buffer=io.BytesIO();stored={}
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_STORED) as z:
        for x in index:
            if x['sha256'] in stored:continue
            h=hashlib.sha256();length=0
            with (WORK/x['path']).open('rb') as reader,z.open(x['member'],'w',force_zip64=True) as writer:
                for block in iter(lambda:reader.read(1024*1024),b''):
                    writer.write(block);h.update(block);length+=len(block)
            if h.hexdigest()!=x['sha256'] or length!=x['size_bytes']:raise ValueError('Source changed since inventory')
            stored[x['sha256']]=x
        z.writestr('artifact-index.json',json.dumps(index,ensure_ascii=False,indent=2))
    buffer.seek(0)
    with lzma.open(destination,'xb',preset=1) as writer:
        for block in iter(lambda:buffer.read(4*1024*1024),b''):writer.write(block)
    buffer.close()
    with lzma.open(destination,'rb') as reader: verified=io.BytesIO(reader.read())
    with zipfile.ZipFile(verified) as z:
        if json.loads(z.read('artifact-index.json'))!=index:raise ValueError('Archive index mismatch')
        for x in stored.values():
            h=hashlib.sha256()
            with z.open(x['member']) as reader:
                for block in iter(lambda:reader.read(1024*1024),b''):h.update(block)
            if h.hexdigest()!=x['sha256']:raise ValueError('Compressed archive member mismatch')
    verified.close()
    return {'archive':str(destination),'sha256':file_hash(destination),'archive_bytes':destination.stat().st_size,'files':index}

def upload_archives():
    # Existing helper is reused; prefix is archive identity, not a new schema.
    import store_catalog_archive as archive_store
    archive_store.BLOCK=8*1024*1024
    upload=archive_store.upload
    parent=read(OUT/'catalog-manifest.json')['records'][0]['record']['record_id']
    for meta in sorted((OUT/'archives').glob('part-*.json')):
        if meta.stem.endswith('-receipt'):continue
        receipt=meta.with_name(meta.stem+'-receipt.json')
        if receipt.exists():continue
        print('uploading',meta.name,flush=True)
        upload(read(meta),ROOT/'.env.database',TEAM,[parent],receipt)
        print('archive_committed',meta.name,flush=True)

def link_runs():
    sys.path.insert(0,str(TEAM))
    from backend.app.routers.catalog import RecordIn
    manifest={'workspace':str(WORK),'records':[]}
    for x in read(OUT/'normalized-receipt.json')['runs']:
        body=RecordIn(record_id='normalized-'+x['run_id'],kind='detection',title='보관 분석: '+x['path'][-220:],owner='TwinSight 팀 / 이진규 실험',data_origin=x['origin'],status='completed',camera_id=x['camera_id'],detection_run_id=x['run_id'],parents=[x['catalog_parent']],details={**x,'type':'normalized_detection_import','archived_not_live':True,'unity_ground_truth_substituted':False}).model_dump()
        manifest['records'].append({'record':body,'fingerprint':digest(body),'files':[],'logs':[]})
    print(upload_catalog(manifest,ROOT/'.env.database',OUT/'normalized-links-receipt.json'),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['discover','prepare','metadata','normalize','package','archives','link','supplement']);a=p.parse_args()
    {'discover':discover,'prepare':prepare,'metadata':upload_metadata,'normalize':normalize,'package':package_new,'archives':upload_archives,'link':link_runs,'supplement':supplement}[a.mode]()

if __name__=='__main__':main()
