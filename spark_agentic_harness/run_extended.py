import concurrent.futures,json,os,time
from datetime import datetime,timezone
from spark_harness import SparkHarness,ROOT,spec,check_args
from run_batch10 import BatchHarness
from transport_extraction import PROMPT,validate,assess
from planner import run_planner,SYSTEM
from llm import LLMClient
from config import load_env

OUT=ROOT/'outputs/extended_20261117'
EXTRAS=[spec('extract_transport_evidence','Call an LLM to extract sample-linked conductivity, numerical temperature and energy with exact quotes. Source must be read first. Save extraction with validation issues. Consumes one model call.',{'paper_id':{'type':'string'}},['paper_id']),
 spec('assess_extracted_transport','Numerically assess the saved extraction for 298.15 K. Deterministic quote/number/unit checks, sample/type checks, local Arrhenius or measured-at-target. Missing evidence returns needs_input. Saved output can be queried with get_simulation_record.',{'extraction_id':{'type':'string'}},['extraction_id'])]

class ExtractionHarness(SparkHarness):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.extractions={}
    def definitions(self):
        names={'read_application_paper','classify_application','get_simulation_record'}
        return [d for d in super().definitions() if d['function']['name'] in names]+EXTRAS
    def execute(self,name,arguments):
        definition=next((d for d in EXTRAS if d['function']['name']==name),None)
        if definition is None:return super().execute(name,arguments)
        reply={'tool':name,'status':'error','data':None,'error':None}
        try:
            if self.tool_calls>=self.max_tool_calls:raise ValueError('Tool budget exhausted')
            self.tool_calls+=1;check_args(definition,arguments)
            if name=='extract_transport_evidence':
                paper=self.application_papers.get(arguments['paper_id'])
                if paper is None:raise ValueError('Read paper first')
                if self.model_calls>=self.max_model_calls:raise ValueError('Model budget exhausted')
                self.model_calls+=1
                client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],8192,PROMPT)
                raw,usage=client({'paper':paper})
                value=self.simulations._save('transport_extraction',{'paper_id':paper['id'],'extraction':raw,
                    'validation_issues':validate(paper,raw),'usage':usage,'model':client.model,'origin':'llm_extraction_unreviewed'})
                self.extractions[value['record_id']]={'paper':paper,'extraction':raw}
            else:
                observed=self.extractions.get(arguments['extraction_id'])
                if observed is None:raise ValueError('Use extraction ID observed in this run')
                value=self.simulations._save('transport_assessment',{**assess(observed['paper'],observed['extraction']),
                      'extraction_id':arguments['extraction_id']})
            reply.update(status='ok',data=value)
        except Exception as exc:reply['error']={'type':type(exc).__name__,'message':'Tool execution failed; see type. No secret-bearing provider message saved.'}
        with (self.output/'events.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'arguments':arguments,**reply},ensure_ascii=False)+'\n')
        return reply

def run_job(job):
    mode,index,paper=job;folder=OUT/f'{mode}_{index:02}'
    if (folder/'complete.json').exists():
        prior=json.loads((folder/'complete.json').read_text(encoding='utf-8'))
        if prior['status']!='exception':return prior
        (folder/'initial_failure.json').write_text(json.dumps(prior,ensure_ascii=False,indent=2),encoding='utf-8')
    if datetime.now().strftime('%H:%M')>='15:50':return {'mode':mode,'index':index,'status':'not_started_deadline'}
    start=time.time();folder.mkdir(parents=True,exist_ok=True)
    metadata={'mode':mode,'index':index,'paper_id':paper.get('id',paper.get('paper_id')),'started':datetime.now().isoformat(),'model':os.environ['LLM_MODEL']}
    (folder/'config.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        if mode=='direct':
            client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],8192,PROMPT+'''
Also add a "assessment" object with status computed_unreviewed|measured_at_target|needs_input, target_sigma_S_cm number or null, issues array; and "recommendation" a Chinese recommendation under 350 characters. Target is 298.15 K. Calculate by yourself only when the same polymer electrolyte has conductivity and exact temperature and conduction Ea. Only local projection within 10 K, constant Ea assumption; do not use VTF, unrelated energies, or different samples. kB=8.617333262145e-5 eV/K. At target temperature preserve measured. Do not treat absent conductivity as zero. Use the identical abstract, no external information.''')
            raw,usage=client({'paper':paper})
            result={'status':'returned' if 'parse_error' not in raw else 'parse_error','reply':raw,'usage':usage,'model_calls':1,
                    'posthoc_evidence_issues':validate(paper,raw)}
            (folder/'direct_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        else:
            if mode=='repeat':
                case=paper
                h=BatchHarness(folder/'execution',case=case,application_catalog=ROOT/'outputs/batch10_20261117/catalog.json',knowledge_db=folder/'memory.sqlite',project_id=f'repeat-{index}',max_model_calls=12,max_tool_calls=9)
                old=json.loads((ROOT/f'outputs/batch10_20261117/{case["case_id"]}/run_config.json').read_text(encoding='utf-8'))
                task=old['task'];system=SYSTEM+'\nReturn exactly JSON, never DSML/tool-call markup. A tool returning needs_input is a valid scientific stop, not a request to invent values. Keep final Chinese recommendation under 650 Chinese characters.'
            else:
                h=ExtractionHarness(folder/'execution',application_catalog=OUT/'catalog.json',knowledge_db=folder/'memory.sqlite',project_id=f'extended-{index}',max_model_calls=14,max_tool_calls=11)
                task=(f'文献ID {paper["id"]}。自主读取文献、调用独立应用分类与性质证据抽取，评估298.15 K电导率是否有充分依据，'
                  '从记忆取回性质评估记录，再给出不超过500字的中文材料建议。包括样品身份、实测条件、性质状态、'
                  '是否能与1e-4 S/cm比较、机制与下一项实验，引用DOI和记录ID。缺数据时保留候选并提出补证据任务。'
                  '不把room temperature猜成25℃，不混用填料、复合物和不同样品，计算结果以工具为准。'
                  '每轮只返回一个JSON动作，最后finish。')
                system=SYSTEM+'\nReturn exactly JSON, never DSML. Use extract_transport_evidence for actual property extraction, then assess_extracted_transport. needs_input is a valid scientific result. Do not repeatedly retry missing evidence. Preserve issues in the final recommendation.'
            client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],8192,system)
            result=run_planner(h,client,task,max_steps=9)
            (folder/'recommendation.txt').write_text(result['answer'],encoding='utf-8')
        metadata.update(status=result['status'],model_calls=result.get('model_calls',0),elapsed_seconds=round(time.time()-start,2))
    except Exception as exc:metadata.update(status='exception',error_type=type(exc).__name__,elapsed_seconds=round(time.time()-start,2))
    (folder/'complete.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(mode,index,metadata['status'],metadata['elapsed_seconds'],flush=True)
    return metadata

if __name__=='__main__':
    load_env();papers=json.loads((OUT/'catalog.json').read_text(encoding='utf-8'))
    previous=json.loads((ROOT/'outputs/batch10_20261117/cases.json').read_text(encoding='utf-8'))
    jobs=[(m,i,p) for i,p in enumerate(papers,1) for m in ['harness','direct']]+[('repeat',i,c) for i,c in enumerate(previous,1)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(run_job,jobs))
    (OUT/'run_summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Batch finished',len(results),flush=True)
