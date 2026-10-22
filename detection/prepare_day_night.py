"""Mix explicitly split night captures and retained day data without resplitting frames."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import yaml

from .dataset import check_dataset
from .sources import IMAGE_EXTENSIONS


def merge(day, night, output):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose an empty dataset destination')
    configs = [(tag, *check_dataset(path)) for tag, path in [('day', day), ('night', night)]]
    if configs[0][1]['names'] != configs[1][1]['names']:
        raise ValueError('Day and night class order must agree')
    result = {'path': str(output.resolve()), 'names': configs[0][1]['names']}
    counts = {}
    for split in ('train','val','test'):
        images, labels = output/'images'/split, output/'labels'/split
        images.mkdir(parents=True); labels.mkdir(parents=True)
        result[split] = 'images/'+split
        counts[split] = {}
        for tag, config, _ in configs:
            folder = Path(config[split])
            files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
            for image in files:
                label = folder.parent.parent/'labels'/split/(image.stem+'.txt')
                shutil.copy2(image, images/(tag+'_'+image.name))
                shutil.copy2(label, labels/(tag+'_'+label.name))
            counts[split][tag] = len(files)
    (output/'dataset.yaml').write_text(yaml.safe_dump(result,sort_keys=False),encoding='utf-8')
    provenance = {'synthetic_only':True,'human_review_complete':False,'frame_counts':counts,
                  'sources':{'day':str(Path(day).resolve()),'night':str(Path(night).resolve())},
                  'splits':'preserved by source capture session; full image and crop remain in same split'}
    (output/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    _, report = check_dataset(output/'dataset.yaml')
    (output/'dataset-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return provenance


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--day',required=True);p.add_argument('--night',required=True);p.add_argument('--out',required=True)
    a=p.parse_args()
    print(json.dumps(merge(a.day,a.night,a.out),ensure_ascii=False,indent=2))
