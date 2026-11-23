"""Package completed fixed-benchmark results without selecting or modifying models."""
from __future__ import annotations
import csv
from collections import Counter
from datetime import datetime,timezone
import hashlib
from pathlib import Path
import shutil

from .collision_scenes import read,lines
from .runner import write_json


def grouped(clips):
    result={}
    for domain in ('varied','legacy'):
      for lighting in ('Day','Night'):
        group=[c for c in clips if c['domain']==domain and c['lighting']==lighting]
        result[domain+'-'+lighting]={
            'accident_clips':sum(c['positive'] for c in group),
            'correct_after_contact_clips':sum(c['correct_pair_after_contact'] for c in group if c['positive']),
            'clean_correct_clips':sum(c['correct_pair_after_contact'] and not c['wrong_or_early_alerts'] for c in group if c['positive']),
            'normal_clips':sum(not c['positive'] for c in group),
            'normal_collision_false_alert_clips':sum(c['collision_alerts']>0 for c in group if not c['positive']),
            'clips_with_wrong_pair_or_early_alert':sum(c['wrong_or_early_alerts']>0 for c in group)}
    return result


def main():
    out=Path('runs/collision-v2');proof=Path('docs/validation/collision-v2');proof.mkdir(parents=True,exist_ok=True)
    detector=read(out/'detector-complete.json');policy=read('detection/models/collision-policy-v2.json')
    before=read(out/'before-policy-verification.json');after=read(out/'policy-verification.json')
    objects=read(out/'object-comparison.json')
    assert set(objects['models'])=={'before','after'} and len(after['clips'])==34
    digest=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert digest('detection/models/simulation-cctv-day-night.pt')=='7dd2720a7bd8c8757c3a0f38b901b7e6dea46d68e97257916a6810b6947bf1a2'
    assert digest('detection/models/stop-zone-collision-day-night.xml')=='37e3e1c0b2e4929628f2dba4d2f5b1218b2a8c1803be85027a5bd423a758ef69'
    actual=digest(detector['weights']);assert actual==detector['sha256']==policy['detector_weights_sha256']
    for source,name in [('before-policy-verification.json','before-temporal.json'),('policy-verification.json','after-temporal.json'),
                        ('object-comparison.json','objects.json'),('policy-selection.json','selection.json'),('detector-complete.json','detector.json')]:
        shutil.copy2(out/source,proof/name)
    shutil.copy2(out/'detector/results.csv',proof/'training.csv')
    shutil.copy2(out/'night-view/previews/overview.jpg','docs/images/collision-retraining-night.jpg')
    checks=read(out/'dataset-check.json');epochs=list(csv.DictReader((out/'detector/results.csv').open(encoding='utf-8-sig')))
    all_normal_alerts=[]
    for clip in after['clips']:
        if clip['positive']:continue
        alerts=lines(out/'verification'/clip['clip']/'alerts.jsonl')
        all_normal_alerts.append({'clip':clip['clip'],'alerts_by_type':dict(Counter(a['type'] for a in alerts))})
    comparison={'completed_at':datetime.now(timezone.utc).isoformat(),'retrained':True,'night_collisions_included':True,
        'synthetic_only':True,'production_ready':False,'fixed_test_previously_benchmarked':True,
        'test_used_for_training_or_threshold_selection':False,'actual_epochs':len(epochs),
        'dataset_counts':{s:x['images'] for s,x in checks['splits'].items()},
        'before':grouped(before['clips']),'after':grouped(after['clips']),
        'normal_all_warning_audit':all_normal_alerts,
        'models':{'detector':detector['weights'],'detector_sha256':actual,
                  'collision_policy':'detection/models/collision-policy-v2.xml',
                  'collision_policy_sha256':digest('detection/models/collision-policy-v2.xml')},
        'policy_selection':{k:policy[k] for k in ('depth','minimum_samples','threshold','training_samples','training_classes',
            'training_feature_sources','validation_false_alert_clips','validation_true_collision_clips')},
        'real_cctv_accuracy_evaluated':False,'human_label_review_complete':False}
    write_json(out/'comparison.json',comparison);write_json(proof/'comparison.json',comparison)
    text='\n\n## 2026-10-25 완료 결과\n\n'
    text+=f"검출기는{len(epochs)}epochs 학습을 완료했고, 별도 충돌 판정 모델의 학습·선택·시험도 완료했다. 이전 가중치는 보존했다.\n\n"
    text+='| 고정 시험 | 이전: 올바른 접촉 후 경고 | 재학습: 같은 기준 | 이전 정상 충돌 오경고 | 재학습 정상 충돌 오경고 |\n|---|---:|---:|---:|---:|\n'
    for key,label in [('varied-Day','새 주간 사고'),('varied-Night','새 야간 사고'),('legacy-Day','기존 주간 사고'),('legacy-Night','기존 야간 사고')]:
        b,a=comparison['before'][key],comparison['after'][key]
        text+=f"| {label} | {b['clean_correct_clips']}/{b['accident_clips']} | {a['clean_correct_clips']}/{a['accident_clips']} | {b['normal_collision_false_alert_clips']}/{b['normal_clips']} | {a['normal_collision_false_alert_clips']}/{a['normal_clips']} |\n"
    text+='\n표의 성공은 실제 접촉 이후 올바른 쌍으로 경고하고 같은 클립에 잘못된 쌍·조기 경고가 없는 경우다. 객체 검출 mAP와 차량 쌍 경고는 별도 지표다.\n\n'
    text+='연쇄 추돌도 실제 접촉한 쌍을 한 번 이상 올바르게 경고하면 장면 성공으로 센다. 모든 개별 접촉 쌍을 빠짐없이 경고했다는 뜻은 아니다. 표본이 작고 같은 도시·차량을 공유하므로 실제 CCTV 정확도로 바꾸어 설명하지 않는다.\n\n'
    text+=f"재학습 모델의 정상 대조{len(all_normal_alerts)}개 중 모든 경고 유형을 합쳐 경고가 발생한 영상은 {sum(bool(r['alerts_by_type']) for r in all_normal_alerts)}개다. 유형별 기록도 비교 증빙에 포함했다.\n\n"
    old,new=objects['models']['before'],objects['models']['after']
    text+=f"동일한 객체 시험424장에서 mAP50은 {old['metrics']['mAP50_101point']:.4f} → {new['metrics']['mAP50_101point']:.4f}다. 클래스·주야간별 결과는 증빙의 객체 비교 파일에 기록했다.\n\n"
    failed=[c for c in after['clips'] if (c['positive'] and not(c['correct_pair_after_contact'] and not c['wrong_or_early_alerts'])) or (not c['positive'] and c['collision_alerts'])]
    if failed:
        text+='남은 충돌 판정 실패 사례:\n\n'+''.join(f"- {c['domain']} / {c['lighting']} / {c['case']}: 접촉 후 올바른 쌍 경고={c['correct_pair_after_contact']}, 잘못된 쌍·조기 경고={c['wrong_or_early_alerts']}, 경고 수={c['collision_alerts']}\n" for c in failed)
    else:text+='이 고정 합성 시험에서는 모든 사고와 비사고 대조가 위 기준을 충족했다.\n'
    text+='\n실제 CCTV 사고 정확도·새 카메라 일반화·새 사건의 맹검 성능을 뜻하지 않는다. 전체 라벨 사람 검수도 미완료다. 모델은 실험 후보 상태로 유지한다.\n\n'
    text+='[전후 비교 증빙](validation/collision-v2/comparison.json) · [객체 결과](validation/collision-v2/objects.json) · [시험별 경고](validation/collision-v2/after-temporal.json)\n\n'
    text+='![야간 원본 장면 미리보기 — 예측 결과 그림이 아님](images/collision-retraining-night.jpg)\n'
    document=Path('docs/collision_retraining.md');body=document.read_text(encoding='utf-8').split('\n\n## 2026-10-25 완료 결과')[0]
    document.write_text(body+text,encoding='utf-8')
    print(comparison['before']);print(comparison['after']);print('TRAINING_REPORT_READY',flush=True)


if __name__=='__main__':main()
