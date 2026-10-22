"""Prepare the night experiment's catalog using the team's existing validators.

Binary archive storage is handled separately by store_catalog_archive.py.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import yaml

from register_experiment_catalog import Builder, file_hash


def prepare(repo, team_root, out, binary_parent=None):
    if out.exists():
        raise ValueError('Choose a new immutable manifest')
    completion=repo/'runs/night-v1/evaluation-complete.json'
    model_metadata=repo/'detection/models/stop-zone-collision-day-night.json'
    if not completion.exists() or completion.stat().st_mtime_ns<model_metadata.stat().st_mtime_ns:
        raise ValueError('Finish the evaluation for the current temporal model before preparing metadata')
    b = Builder(repo, team_root, repo/'.env.database', 'origin/codex/local-db-validation@3bddc0d')
    previous=b.read_json(repo/'runs/database-registration-20261022/catalog-manifest-v2.json')['records']
    old_day=next(e['record']['record_id'] for e in previous if e['record']['title']=='dataset-queue-objects-focus')
    initial_sha=file_hash(repo/'detection/models/simulation-cctv-queue.pt')
    old_model=next(e['record']['record_id'] for e in previous if e['record']['kind']=='model'
                   and any(f['sha256']==initial_sha for f in e['files']))
    capture_map={e['record']['details'].get('source_folder'):e['record']['record_id']
                 for e in previous if e['record']['kind']=='capture'}
    scripts = repo/'simulation/TwinSightSim/Assets/TwinSight/Scripts'
    profile = b.add('simulation-night-v1', 'simulation', 'synthetic',
                    [scripts/n for n in ['DayNightEnvironment.cs','NightExperimentCapture.cs',
                                         'SyntheticTrainingCapture.cs','StopZoneCapture.cs','SyntheticWarningCapture.cs',
                                         'CityLabExperiment.cs','GroundTruthExporter.cs','ExportRecords.cs']],
                    {'time_of_day_controls':['Day','Night'],'road_and_signal_assets_reused':True,
                     'camera_pose_preserved':True,'lighting_override_bug_fixed':True,
                     'source_binary_archive_record':binary_parent},[binary_parent] if binary_parent else [])
    captures = []
    still_captures = []
    for folder in sorted((repo/'simulation/TwinSightSim/TwinSightExport').glob('night*-v1-*')):
        rows = [json.loads(s) for s in (folder/'ground_truth.jsonl').read_text(encoding='utf-8-sig').splitlines()]
        if not rows or any(r['lighting']['time_of_day']!='Night' or r['lighting']['sun_intensity']>.101 for r in rows):
            raise ValueError('Reject incomplete or invalid night capture')
        capture_id=b.add('capture-'+folder.name,'capture','synthetic',b.paths(folder),
            {'frames':len(rows),'camera':b.read_json(folder/'camera.json'),
             'lighting_sun_range':[min(r['lighting']['sun_intensity'] for r in rows),max(r['lighting']['sun_intensity'] for r in rows)],
             'human_review_complete':False},[profile],logs=True)
        captures.append(capture_id);capture_map[str(folder.resolve())]=capture_id
        if folder.name.startswith('night-v1-') and '-clip-' not in folder.name:
            still_captures.append(capture_id)
    datasets = []
    for name in ['night-v1-full','night-v1-focus','day-night-v1']:
        folder=repo/'datasets'/name
        config=yaml.safe_load((folder/'dataset.yaml').read_text(encoding='utf-8'))
        subsets={s:[] for s in ['train','val','test']}
        for split,samples in subsets.items():
            for image in sorted((folder/'images'/split).iterdir()):
                if not image.is_file() or image.suffix.lower() not in {'.jpg','.jpeg','.png'}:continue
                label=folder/'labels'/split/(image.stem+'.txt')
                text=label.read_bytes().decode('utf-8')
                samples.append({'image':b.info(image)['path'],'image_sha256':b.info(image)['sha256'],
                                'label':b.info(label)['path'],'label_sha256':b.info(label)['sha256'],
                                'label_text':text,'boxes_yolo':[[float(v) for v in s.split()] for s in text.splitlines() if s.strip()]})
        key=b.add('dataset-'+name,'dataset','synthetic',b.paths(folder),
                  {'classes':config['names'],'split_counts':{s:len(v) for s,v in subsets.items()},
                   'provenance':b.read_json(folder/'provenance.json'),'human_review_complete':False},
                  still_captures if not datasets else [datasets[-1],old_day] if name=='day-night-v1' else [datasets[-1]])
        datasets.append(key)
        for split,samples in subsets.items():
            for part,start in enumerate(range(0,len(samples),100)):
                b.add(f'labels-{name}-{split}-{part:03}','dataset','synthetic',details={
                    'type':'yolo_split_annotations','dataset':name,'split':split,'classes':config['names'],
                    'samples':samples[start:start+100],'exact_label_text_in_database':True},parents=[key])
    run=repo/'runs/night-v1'
    complete=b.read_json(run/'training-complete.json')
    training=b.add('training-day-night-v1','training','synthetic',b.paths(run/'detector')+
                    [run/'training.log',run/'training-complete.json',run/'dataset-check.json',run/'dataset.resolved.yaml'],
                    complete,[datasets[-1],old_model],logs=True)
    model=repo/'detection/models/simulation-cctv-day-night.pt'
    detector=b.add('model-day-night-v1','model','synthetic',[model],
                    {'sha256':file_hash(model),'real_cctv_performance_verified':False},[training])
    classifier=repo/'detection/models/stop-zone-collision-day-night.xml'
    parents=[detector]
    if classifier.exists():
        clips=b.read_json(run/'temporal-combined/manifest.json')
        temporal_sources=[capture_map[str(Path(e['source']).resolve())] for e in clips]
        classifier_details=b.read_json(classifier.with_suffix('.json'))
        if classifier_details.get('legacy_training_feature_augmentation'):
            temporal_sources.append(next(e['record']['record_id'] for e in previous
                                         if e['record']['title']=='dataset-stop-zone-temporal'))
        temporal=b.add('training-day-night-temporal','training','synthetic',
                        b.paths(run/'temporal-combined'),classifier_details|{'test_used_for_training':False},
                        [detector,*temporal_sources],logs=True)
        parents.append(b.add('model-day-night-temporal','model','synthetic',
                            [classifier,classifier.with_suffix('.json')],classifier_details,[temporal],status='draft'))
    evaluation_files=[]
    # The combined temporal training record already owns the same predictions.
    # The binary output archive also preserves the individual stage folders.
    for name in ['evaluation','warning-checks']:
        evaluation_files+=b.paths(run/name)
    evaluation_files+=list(run.glob('*preview*.jpg'))+list(run.glob('*audit*.json'))
    evaluation_files+=[run/'validation-summary.json',run/'evaluation-complete.json']
    b.add('evaluation-day-night-v1','evaluation','mixed',evaluation_files,
          {'synthetic_only':False,'actual_cctv_ground_truth_available':False,
           'reports':{p.relative_to(run).as_posix():b.read_json(p) for p in (run/'evaluation').rglob('metrics.json')},
           'validation_summary':b.read_json(run/'validation-summary.json'),
           'test_used_for_training':False},parents,logs=True)
    rejected=run/'rejected-lighting'
    if rejected.exists():
        b.add('capture-night-lighting-rejected','capture','synthetic',b.paths(rejected),
              {'excluded_from_training':True,'reason':'Legacy sun intensity override; preserved as rejected experiment evidence'},
              [profile],status='draft',logs=True)
    result={'format':'twinsight-catalog-import-v1','workspace':str(repo.parent),
            'source_catalog_code':b.code_ref,'records':b.records,'excluded':b.excluded,'file_bytes_uploaded':False}
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'records':len(b.records),'kinds':dict(Counter(e['record']['kind'] for e in b.records))}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[2])
    p.add_argument('--team-code-root',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--binary-parent')
    a=p.parse_args();prepare(a.repo.resolve(),a.team_code_root.resolve(),a.manifest,a.binary_parent)
