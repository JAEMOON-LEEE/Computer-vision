"""List immutable night model outputs and source code, excluding recursive DB packaging files."""
import json
from pathlib import Path
import shutil
from dotenv import dotenv_values
from sqlalchemy.engine import make_url


def main():
    repo=Path(__file__).resolve().parents[2];workspace=repo.parent
    run=repo/'runs/night-v1';db=run/'database';proof=repo/'docs/validation/day-night-v1'
    complete=run/'evaluation-complete.json'
    if complete.stat().st_mtime_ns<(repo/'detection/models/stop-zone-collision-day-night.json').stat().st_mtime_ns:
        raise ValueError('Finish evaluation for the current classifier')
    shutil.copy2(db/'metadata-registration-report.json',proof/'metadata-registration-report.json')
    files=set()
    for p in run.rglob('*'):
        rel=p.relative_to(run)
        if p.is_file() and rel.parts[0] not in {'database','rejected-lighting','failed-memory'}:
            files.add(p)
    for folder in [repo/'detection',repo/'backend/scripts']:
        files.update(folder.glob('*.py'))
    files.update((repo/'detection/tests').glob('*.py'))
    files.update((repo/'backend').glob('requirements*.txt'))
    files.update((repo/'detection').glob('*.txt'))
    for folder in [repo/'simulation/TwinSightSim/Assets/TwinSight/Scripts',
                   repo/'simulation/TwinSightSim/Assets/TwinSight/Editor']:
        files.update(folder.glob('*.cs'));files.update(folder.glob('*.cs.meta'))
    for n in ['simulation-cctv-day-night.pt','stop-zone-collision-day-night.xml','stop-zone-collision-day-night.json']:
        files.add(repo/'detection/models'/n)
    files.update(p for p in proof.rglob('*') if p.is_file())
    for n in ['README.md','detection/README.md','detection/MODEL_CARD.md','docs/day_night_training.md']:
        files.add(repo/n)
    for n in ['day-mode.png','night-mode.png','day-night-controls.png','night-training-labels.jpg',
              'night-real-caption-false-positive.jpg']:
        files.add(repo/'docs/images'/n)
    logs=repo/'simulation/TwinSightSim/Logs'
    files.update(logs.glob('night-v1-*-poses.json'))
    for n in ['night-v1-capture-complete.txt','nightqueue-v1-capture-complete.txt',
              'day-mode-verified.png','night-mode-verified.png','day-night-scene-audit.json']:
        files.add(logs/n)
    files.update((repo/'simulation/TwinSightSim/Assets/Logs').glob('*.png'))
    files.add(repo/'runs/queue-v3/candidates.jsonl')
    files.add(workspace/'tools/Run-ProjectPython.ps1')
    files.add(workspace/'project-C-night-data-check-20261022.json')
    for path in files:
        if not path.is_file() or not path.resolve().is_relative_to(workspace):
            raise ValueError('Missing/outside-workspace artifact: '+str(path))
    secrets=[v.encode() for k,v in dotenv_values(repo/'.env').items() if v and 'KEY' in k and len(v)>12]
    password=make_url(dotenv_values(repo/'.env.database')['DATABASE_URL']).password
    if password:secrets.append(password.encode())
    for path in files:
        payload=path.read_bytes()
        if any(value in payload for value in secrets):
            raise ValueError('Credential found in proposed artifact: '+str(path.relative_to(workspace)))
    source=json.loads((db/'sources-solid-manifest.json').read_text(encoding='utf-8'))
    catalog=json.loads((db/'catalog-manifest-final.json').read_text(encoding='utf-8'))
    source_hash={f['path']:f['sha256'] for f in source['files']}
    changed=[]
    for e in catalog['records']:
        for f in e['files']:
            if f['path'] in source_hash and f['sha256']!=source_hash[f['path']]:
                changed.append(f['path']);files.add(workspace/f['path'])
    report={'output_files':len(files),'output_bytes':sum(p.stat().st_size for p in files),
            'all_paths_under_D':True,'credential_scan_passed':True,
            'source_versions_changed_after_packaging':sorted(set(changed))}
    (db/'output-file-list.json').write_text(json.dumps(sorted(str(p.resolve()) for p in files),ensure_ascii=False,indent=2),encoding='utf-8')
    (db/'output-preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
