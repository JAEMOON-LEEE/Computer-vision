"""Create review sheets for existing model false positives; no automatic relabeling."""
import json
from pathlib import Path
import cv2
import numpy as np
from detection.sources import confined_image, decode_image


def create_sheets(results, output):
    results, output = Path(results), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    summary = json.loads((results/'results.json').read_text(encoding='utf8'))
    manifest = []
    for kind in ('guardrail', 'manhole'):
        threshold = summary['models'][kind]['embedding_edge_threshold']
        records = json.loads((results/(kind+'-predictions.json')).read_text(encoding='utf8'))['test_embedding_edge']
        selected = {}
        for rec in records:
            if rec['label'] == 0 and rec['score'] >= threshold:
                selected.setdefault(rec['variant'], rec)
        tiles = []
        for index, (variant, rec) in enumerate(sorted(selected.items())):
            session = Path(rec['session'])
            rows = [json.loads(s) for s in (session/'ground_truth.jsonl').read_text(encoding='utf-8-sig').splitlines()]
            frame = rec['frames_used'][0]
            image = decode_image(confined_image(session, rows[frame]['image']))
            x1,y1,x2,y2 = rec['roi']
            crop = cv2.resize(image[y1:y2, x1:x2], (480,280), interpolation=cv2.INTER_NEAREST)
            cv2.rectangle(crop, (0,0), (479,34), (0,0,0), -1)
            cv2.putText(crop, f'{index+1} {variant} score={rec["score"]:.3f}', (5,23), cv2.FONT_HERSHEY_SIMPLEX, .52, (255,255,255), 1, cv2.LINE_AA)
            tiles.append(crop)
            manifest.append({'kind':kind,'variant':variant,'session':str(session),'frame':frame,'roi':rec['roi'],
                'score':rec['score'],'truth_state':rows[frame]['scenario']['facility']['state'],
                'ground_truth_source':'simulation_not_human_reviewed','image':str(session/rows[frame]['image'])})
        if len(tiles)%2: tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,len(tiles),2)])
        cv2.imwrite(str(output/(kind+'-false-positives.jpg')), sheet)
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')


if __name__ == '__main__':
    create_sheets('runs/facility-embedding-edge-20261117/training','runs/facility-improvement-20261117/review')
