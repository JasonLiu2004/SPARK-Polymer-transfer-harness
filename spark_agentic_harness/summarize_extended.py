import json,math
from collections import Counter
from pathlib import Path
from spark_harness import ROOT
OUT=ROOT/'outputs/extended_20261117'
def obj(p):return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
def lines(p):return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip()] if p.exists() else []
def summarize():
    reference={r['index']:r for r in obj(OUT/'assessment_reference.json')['cases']}
    rows=[]
    for i,paper in enumerate(obj(OUT/'catalog.json'),1):
        entry={'index':i,'paper_id':paper['id'],'title':paper['title'],'doi':paper['doi'],'reference':reference[i]}
        for mode in ['harness','direct']:
            folder=OUT/f'{mode}_{i:02}';complete=obj(folder/'complete.json')
            if complete.get('status')=='exception':complete={**complete,'status':'initialization_failed_pending_recovery'}
            if mode=='direct':
                r=obj(folder/'direct_result.json');reply=r.get('reply',{});a=reply.get('assessment',{})
                entry[mode]={'run_status':complete.get('status','running'),'assessment':a,'extraction':{k:v for k,v in reply.items() if k not in ['assessment','recommendation']},
                  'recommendation':reply.get('recommendation'),'evidence_issues':r.get('posthoc_evidence_issues',[]),'tokens':r.get('usage',{}).get('total_tokens',0),'model_calls':complete.get('model_calls',0)}
            else:
                events=lines(folder/'execution/events.jsonl');trace=lines(folder/'execution/planner_trace.jsonl')
                assessments=[e['data'] for e in events if e['tool']=='assess_extracted_transport' and e['status']=='ok']
                extractions=[e['data'] for e in events if e['tool']=='extract_transport_evidence' and e['status']=='ok']
                a=assessments[-1] if assessments else {}
                e=extractions[-1] if extractions else {}
                entry[mode]={'run_status':complete.get('status','running'),'assessment':a,'extraction':e.get('extraction'),
                    'evidence_issues':e.get('validation_issues',[]),'tokens':sum(t.get('usage',{}).get('total_tokens',0) for t in trace)+sum(x.get('data',{}).get('usage',{}).get('total_tokens',0) for x in events if x['status']=='ok'),
                    'model_calls':complete.get('model_calls',0),'recommendation':obj(folder/'execution/planner_result.json').get('answer'),
                    'memory_retrieved':any(x['tool']=='get_simulation_record' and x['status']=='ok' and x.get('data',{}).get('record_id')==a.get('record_id') for x in events),
                    'format_errors':sum('parse_error' in t.get('decision',{}) for t in trace)}
            entry[mode]['status_matches_reference']=a.get('status')==reference[i]['expected']
            if i==2 and a.get('target_sigma_S_cm') is not None:
                expected=1.18e-6*math.exp(-.4/8.617333262145e-5*(1/298.15-1/300.15))
                entry[mode]['value_relative_error']=abs(a['target_sigma_S_cm']/expected-1)
        rows.append(entry)
    repeats=[]
    for i in range(1,11):
        old=ROOT/f'outputs/batch10_20261117/C{i:02}'
        current=OUT/f'repeat_{i:02}';events=lines(current/'execution/events.jsonl')
        previous=lines(old/'events.jsonl')
        def last(e,name):return next((x['data'] for x in reversed(e) if x['tool']==name and x['status']=='ok'),{})
        before=last(previous,'assess_temperature_property');after=last(events,'assess_temperature_property')
        oldclass=last(previous,'classify_application').get('decision',{});newclass=last(events,'classify_application').get('decision',{})
        repeats.append({'case_id':f'C{i:02}','status':obj(current/'complete.json').get('status','running'),
          'property_same':bool(after) and before['status']==after['status'] and before.get('target_sigma_S_cm')==after.get('target_sigma_S_cm'),
          'classification_same':bool(newclass) and all(oldclass.get(k)==newclass.get(k) for k in ['spe_label','transfer_route','carrier']),
          'old_classification':oldclass,'new_classification':newclass})
    aggregate={m:{'run_status':dict(Counter(r[m]['run_status'] for r in rows)),
      'assessment_status':dict(Counter(r[m]['assessment'].get('status','not_returned') for r in rows)),
      'matches_assistant_reference':sum(r[m]['status_matches_reference'] for r in rows),
      'evidence_issue_cases':sum(bool(r[m]['evidence_issues']) for r in rows),'tokens':sum(r[m]['tokens'] for r in rows),'model_calls':sum(r[m]['model_calls'] for r in rows)} for m in ['harness','direct']}
    result={'n':20,'aggregate':aggregate,'repeats':repeats,'rows':rows,'reference_caveat':'Assistant reference, targeted 19 insufficient + 1 calculable; not expert accuracy or unbiased benchmark. Direct and harness are not cost matched.'}
    (OUT/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'aggregate':aggregate,'repeat_status':dict(Counter(r['status'] for r in repeats)),'repeat_property_same':sum(r['property_same'] for r in repeats),'repeat_classification_same':sum(r['classification_same'] for r in repeats)},ensure_ascii=False,indent=2))
    return result
if __name__=='__main__':summarize()
