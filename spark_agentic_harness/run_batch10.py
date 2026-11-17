"""Ten independent real LLM plans over persisted literature/property tools."""
import concurrent.futures
import hashlib
import json
import math
import os
from datetime import datetime,timezone
from spark_harness import SparkHarness,ROOT,spec,check_args
from planner import run_planner,SYSTEM
from config import load_env
from llm import LLMClient

OUT=ROOT/'outputs/batch10_20261117'
PROPERTY=spec('assess_temperature_property',
 'Use source-checked, assistant-curated measurements of the observed paper to estimate conductivity at the target temperature. Exact source spans and hash are verified. Returns measured_at_target, computed_unreviewed, or needs_input. Missing temperatures, VTF parameters, other energy types and mismatched samples cannot be used as Arrhenius inputs. Not a structure predictor or MD. Saves a record retrievable with get_simulation_record.',
 {'paper_id':{'type':'string'},'temperature_K':{'type':'number'}},['paper_id','temperature_K'])

def calculate(case,paper,target):
    if isinstance(target,bool) or not isinstance(target,(int,float)) or not math.isfinite(target) or not 273.15<=target<=373.15:
        raise ValueError('Invalid target temperature')
    if case['paper_id']!=paper['id'] or hashlib.sha256(paper['abstract'].encode()).hexdigest()!=case['source_sha256'] or not all(q in paper['abstract'] for q in case['quotes']):
        raise ValueError('Evidence identity/hash/quote mismatch')
    result={**case,'target_temperature_K':target,'eligible_for_ranking':False,
      'model':'Arrhenius local temperature projection v1','uncertainty_interval':None,
      'limitations':['Abstract evidence only; no full-text recipe or solvent validation.',
                    'Apparent activation energy assumed constant, no phase transition.',
                    'Cross-paper numerical order is not a controlled materials ranking.']}
    if case['blocking_reason']:
        return {**result,'status':'needs_input','projected_sigma_S_cm':None}
    t0=case['reference_temperature_K']
    if abs(target-t0)>10:
        return {**result,'status':'needs_input','blocking_reason':'outside_10K_local_projection','projected_sigma_S_cm':None}
    if target==t0:
        return {**result,'status':'measured_at_target','projected_sigma_S_cm':None,'target_sigma_S_cm':case['sigma_S_cm']}
    value=case['sigma_S_cm']*math.exp(-case['Ea_eV']/8.617333262145e-5*(1/target-1/t0))
    return {**result,'status':'computed_unreviewed','projected_sigma_S_cm':value,'target_sigma_S_cm':value}

class BatchHarness(SparkHarness):
    def __init__(self,*args,case,**kwargs):
        super().__init__(*args,**kwargs);self.case=case
    def definitions(self):
        names={'read_application_paper','classify_application','get_simulation_record','spark_capabilities'}
        return [d for d in super().definitions() if d['function']['name'] in names]+[PROPERTY]
    def execute(self,name,arguments):
        if name!='assess_temperature_property':return super().execute(name,arguments)
        reply={'tool':name,'status':'error','data':None,'error':None}
        try:
            if self.tool_calls>=self.max_tool_calls:raise ValueError('Tool budget exhausted')
            self.tool_calls+=1;check_args(PROPERTY,arguments)
            paper=self.application_papers.get(arguments['paper_id'])
            if paper is None:raise ValueError('Read source first')
            value=calculate(self.case,paper,arguments['temperature_K'])
            reply.update(status='ok',data=self.simulations._save('temperature_assessment',value))
        except Exception as exc:reply['error']={'type':type(exc).__name__,'message':str(exc)}
        with (self.output/'events.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'arguments':arguments,**reply},ensure_ascii=False)+'\n')
        return reply

def run_case(case):
    folder=OUT/case['case_id']
    if (folder/'planner_result.json').exists():
        return json.loads((folder/'planner_result.json').read_text(encoding='utf-8'))
    h=BatchHarness(folder,case=case,application_catalog=OUT/'catalog.json',knowledge_db=folder/'memory.sqlite',
                   project_id='batch10-'+case['case_id'],max_model_calls=12,max_tool_calls=9)
    client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],8192,SYSTEM+
      '\nReturn exactly JSON, never DSML/tool-call markup. A tool returning needs_input is a valid scientific stop, not a request to invent values. Keep final Chinese recommendation under 650 Chinese characters.')
    task=(f'文献ID {case["paper_id"]}。完成一篇固态聚合物电解质的研究建议样例。'
          '自主使用可用工具读取文献、调用独立应用分类，评估298.15 K电导率是否可算，'
          '从记忆取回性质评估结果。基于真实返回值完成中文建议：材料与应用范围、原文实测条件、'
          '工具结果、距1e-4 S/cm目标的比较、值得验证的结构机制和下一项实验。'
          '若输入不足则说明补什么，仍需给出有证据的下一步建议。不得把室温默认25℃，'
          '不得把吸附能/解离能/HOMO/VTF参数当Arrhenius活化能，不得混用填料与复合物数值。'
          '已在目标温度测量的值标为实测，不计作预测。给出DOI和性质记忆记录ID，'
          '不得跨论文宣称已发现最优材料。只返回一个JSON动作/轮，最后finish。')
    (folder/'run_config.json').write_text(json.dumps({'model':client.model,'max_tokens':8192,'task':task},ensure_ascii=False,indent=2),encoding='utf-8')
    result=run_planner(h,client,task,max_steps=9)
    (folder/'recommendation.txt').write_text(result['answer'],encoding='utf-8')
    print(case['case_id'],result['status'],result['model_calls'],flush=True)
    return result

if __name__=='__main__':
    load_env();cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(run_case,cases))
    (OUT/'batch_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Completed',len(results),'cases',flush=True)
