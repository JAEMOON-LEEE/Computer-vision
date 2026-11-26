"""Audit old and paired captures together; paired sessions must share one split."""
import json
from pathlib import Path
from detection.facility_audit import audit_facility_splits

root=Path.cwd(); base=root/'simulation/TwinSightSim/TwinSightExport'
folders=[base/'manhole-facility-day-20261117',base/'normal-facility-day-20261117',base/'facility-expanded-day-20261117',base/'facility-paired-day-20261117']
if not (folders[-1]/'capture-complete.txt').is_file(): raise ValueError('Paired capture incomplete')
splits={s:[p for d in folders for p in sorted(d.glob('facility-'+s+'-*'))] for s in ('train','val','test')}
if any(len(paths)!=196 for paths in splits.values()): raise ValueError('Unexpected session count')
print('AUDITING_ALL_SESSIONS',flush=True)
result=audit_facility_splits(splits)
path=root/'runs/facility-improvement-20261117/combined-split-audit.json'
if path.exists(): raise ValueError('Preserve previous audit')
path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({s:{'sessions':v['sessions'],'frames':v['frames']} for s,v in result['splits'].items()}),flush=True)
