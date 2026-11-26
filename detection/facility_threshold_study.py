"""Offline threshold tradeoff; constraints are selected using validation only."""
import json, math
from pathlib import Path


def counts(rows, threshold):
    tp=sum(r['label']==1 and r['score']>=threshold for r in rows)
    fn=sum(r['label']==1 and r['score']<threshold for r in rows)
    fp=sum(r['label']==0 and r['score']>=threshold for r in rows)
    tn=sum(r['label']==0 and r['score']<threshold for r in rows)
    return {'tp':tp,'fn':fn,'fp':fp,'tn':tn,
            'recall':tp/(tp+fn) if tp+fn else None,'false_positive_rate':fp/(fp+tn) if fp+tn else None}


def study(root, output, *, minimum_validation_recall=.9):
    root, output = Path(root), Path(output)
    if output.exists(): raise ValueError('Preserve prior threshold results')
    results=json.loads((root/'results.json').read_text(encoding='utf8'))
    report={'validation_recall_constraint':minimum_validation_recall,
            'constraint_note':'Illustrative, not a safety target or guarantee; threshold chosen on validation alone', 'models':{}}
    for kind in ('guardrail','manhole'):
        p=json.loads((root/(kind+'-predictions.json')).read_text(encoding='utf8'))
        val, test=p['validation_embedding_edge'],p['test_embedding_edge']
        positives=sum(r['label']==1 for r in val)
        candidates=[]
        for i in range(1,20):
            t=i/20; m=counts(val,t)
            if m['tp']>=math.ceil(minimum_validation_recall*positives): candidates.append((m['fp'],-m['tp'],-t,t))
        if not candidates: raise ValueError('No validation threshold satisfies recall constraint')
        threshold=min(candidates)[-1]
        f1=results['models'][kind]['embedding_edge_threshold']
        report['models'][kind]={'prior_f1_threshold':f1,'selected_threshold':threshold,
            'validation_f1_threshold':counts(val,f1),'validation_selected':counts(val,threshold),
            'test_f1_threshold':counts(test,f1),'test_selected':counts(test,threshold),
            'validation_curve':[{'threshold':i/20,**counts(val,i/20)} for i in range(1,20)]}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return report


if __name__=='__main__':
    print(json.dumps(study('runs/facility-embedding-edge-20261117/training','runs/facility-improvement-20261117/threshold-study.json'),ensure_ascii=False,indent=2))
