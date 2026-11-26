import json
from pathlib import Path
import cv2,numpy as np
root=Path.cwd(); src=root/'simulation/TwinSightSim/TwinSightExport/centerline-nearest-smoke-20261118'; out=root/'runs/centerline-near-20261118'
views=[]; objects=[]
for session in sorted(src.glob('facility-test-*')):
    row=json.loads((session/'ground_truth.jsonl').read_text(encoding='utf-8-sig').splitlines()[0]); f=row['scenario']['facility']; img=cv2.imdecode(np.fromfile(str(session/row['image']),np.uint8),cv2.IMREAD_COLOR)
    tracked=[x for x in row['objects'] if x['class_name'].startswith(('delineator_','guardrail_','manhole_'))]
    for x in tracked:
        a,b,c,d=map(int,x['bbox_xyxy']); cv2.rectangle(img,(a,b),(c,d),(0,0,255),3)
    tile=cv2.resize(img,(576,384),interpolation=cv2.INTER_AREA); cv2.putText(tile,f['variant'],(8,25),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,255),2)
    views.append(tile); objects.append({'case':f['variant'],'reference':f['reference_position_world'],'boxes':tracked})
if len(views)!=10: raise ValueError(f'Expected 10 test views, got {len(views)}')
out.mkdir(parents=True,exist_ok=True); views.extend([np.full((384,576,3),255,np.uint8)]*2)
sheet=np.vstack([np.hstack(views[i:i+3]) for i in range(0,12,3)])
cv2.imencode('.jpg',sheet,[cv2.IMWRITE_JPEG_QUALITY,90])[1].tofile(out/'smoke-preview.jpg')
(out/'smoke-positions.json').write_text(json.dumps(objects,indent=2),encoding='utf8'); print('created',len(objects))
