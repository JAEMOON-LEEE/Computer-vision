"""Exercise conservative gate on existing passing clips using oracle boxes."""
import json, runpy
from collections import Counter
from pathlib import Path
from detection.facility_reference import assess_visibility
from detection.facility_state import FacilityEvidenceGate
from detection.sources import confined_image, decode_image

root=Path.cwd(); base=root/'simulation/TwinSightSim/TwinSightExport'
folders=[base/'manhole-facility-day-20261117',base/'normal-facility-day-20261117']
make_roi=runpy.run_path(str(root/'runs/manhole-facility-20261117/train_facilities.py'))['make_roi']
out=root/'runs/facility-improvement-20261117/visibility-replay.json'
if out.exists(): raise ValueError('Preserve existing replay')
sessions=[]
for folder in folders:
    for p in sorted(folder.glob('facility-test-Day-*PassingVehicle-*')):
        camera=json.loads((p/'camera.json').read_text(encoding='utf-8-sig'))
        rows=[json.loads(s) for s in (p/'ground_truth.jsonl').read_text(encoding='utf-8-sig').splitlines()]
        truth=rows[0]['scenario']['facility']; kind=truth['kind']
        if kind not in ('guardrail','manhole'): continue
        roi=make_roi(camera,truth); counts=Counter(); gate=FacilityEvidenceGate(kind,.5,min_duration_seconds=.5,min_observations=3,max_gap_seconds=.25)
        invalid_alerts=0
        for row in rows:
            image=decode_image(confined_image(p,row['image']))
            cars=[o['bbox_xyxy'] for o in row.get('objects',[]) if o.get('class_name') in ('car','truck','bus')]
            q=assess_visibility(image,roi,vehicle_boxes=cars,detector_healthy=True,camera_stable=True,min_focus=5)
            state=gate.update(row['timestamp'],.9 if q['visible'] else None,visible=q['visible'],camera_stable=True)
            counts[q['reason']]+=1
            if not q['visible'] and state!='unknown': invalid_alerts+=1
        sessions.append({'session':str(p),'kind':kind,'frames':len(rows),'reasons':dict(counts),'invalid_frames_not_unknown':invalid_alerts})
summary={kind:{'sessions':sum(s['kind']==kind for s in sessions),
    'frames':sum(s['frames'] for s in sessions if s['kind']==kind),
    'possible_vehicle_occlusion_frames':sum(s['reasons'].get('possible_vehicle_occlusion',0) for s in sessions if s['kind']==kind),
    'invalid_frames_not_unknown':sum(s['invalid_frames_not_unknown'] for s in sessions if s['kind']==kind)} for kind in ('guardrail','manhole')}
report={'note':'Simulation ground-truth vehicle boxes, stable-camera assumption, and artificially high score; validates mechanics only, not detector or real occlusion accuracy.', 'summary':summary,'sessions':sessions}
out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(summary,ensure_ascii=False))
