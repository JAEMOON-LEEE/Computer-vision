"""Fine-tune the preserved nine-class detector on vehicle-free day scenes."""
import csv,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
import torch
from ultralytics import YOLO
from ultralytics.models.yolo.detect import DetectionTrainer
from detection.dataset import check_dataset
ROOT=Path.cwd(); WORK=ROOT/'runs/centerline-near-20261118'; DATA=WORK/'dataset/dataset.yaml'
INITIAL=ROOT/'runs/unified-yolo-20261118/training/weights/best.pt'; OUT=WORK/'training'
if OUT.exists(): raise ValueError('Preserve existing training')
if not (WORK/'dataset-report.json').is_file(): raise ValueError('Dataset audit missing')
resolved,check=check_dataset(DATA)
model=YOLO(str(INITIAL))
if list(model.names.values())!=list(resolved['names'].values()): raise ValueError('Checkpoint classes do not match dataset')
torch.set_num_threads(4)
class HeadlessTrainer(DetectionTrainer):
    def get_dataset(self): return {**resolved,'nc':len(resolved['names']),'channels':3,'yaml_file':str(DATA)}
    def final_eval(self):
        from ultralytics.utils.torch_utils import strip_optimizer
        for p in (self.last,self.best):
            if p.exists(): strip_optimizer(p)
def progress(t):
    (WORK/'training-progress.json').write_text(json.dumps({'epoch':t.epoch+1,'requested':12,'at':datetime.now(timezone.utc).isoformat(),
        'metrics':{k:float(v) for k,v in t.metrics.items()}},indent=2),encoding='utf8')
    print('EPOCH',t.epoch+1,'of 12',flush=True)
model.add_callback('on_fit_epoch_end',progress)
model.train(trainer=HeadlessTrainer,data=str(DATA),epochs=12,batch=8,imgsz=512,device='cpu',workers=0,
            seed=261119,deterministic=True,freeze=10,patience=8,mosaic=0,degrees=0,translate=.02,scale=.05,
            hsv_h=0,hsv_s=.05,hsv_v=.1,fliplr=0,flipud=0,project=str(WORK),name='training',plots=False,save=True)
best=OUT/'weights/best.pt'
if not best.is_file(): raise ValueError('No best weights')
with (OUT/'results.csv').open(encoding='utf8') as f: completed=len(list(csv.DictReader(f)))
result={'epochs_completed':completed,'epochs_requested':12,'weights':str(best),'sha256':hashlib.sha256(best.read_bytes()).hexdigest(),
        'initial_weights':str(INITIAL),'initial_sha256':hashlib.sha256(INITIAL.read_bytes()).hexdigest(),
        'initial_model_training_note':'Prior checkpoint was trained on mixed vehicle-present and vehicle-free scenes.',
        'training_images':'vehicle-free requested; no tracked vehicle; hidden known static vehicle','image_size':512,'batch_size':8,
        'seed':261119,'frozen_blocks':10,'classes':list(resolved['names'].values()),'synthetic_only':True,'production_ready':False}
(WORK/'training-complete.json').write_text(json.dumps(result,indent=2),encoding='utf8'); print(json.dumps(result),flush=True)
