"""Live LLM planning over a source-backed, bounded temperature projection demo."""
import json
import math
import os
from datetime import datetime
from spark_harness import SparkHarness, ROOT, spec, check_args
from planner import run_planner, SYSTEM
from llm import LLMClient
from config import load_env

PAPER = '8b4a24569e46a5aebdd4'
CATALOG = ROOT/'outputs/application_20261117_125231/pilot_frozen.json'
DEFINITION = spec('project_paper_conductivity',
    'Project two source-backed PEO-NaClO4/NZSP formulations from 303.15 K to a nearby temperature with the Arrhenius equation. Requires reading paper 8b4a24569e46a5aebdd4 first. Inputs were manually transcribed from its abstract; this is not new-structure ML or MD. Results are persisted; retrieve using get_simulation_record.',
    {'temperature_K': {'type':'number'}}, ['temperature_K'])


def project(paper, temperature):
    if isinstance(temperature, bool) or not isinstance(temperature,(int,float)) or not math.isfinite(temperature) or not 293.15 <= temperature <= 313.15:
        raise ValueError('Demo permits only 293.15..313.15 K; validity outside this range is not established')
    quote = '25 wt% (sigma = 3.56.10(-5) S.cm(- 1) (30 degrees C) and E-a = 0.118 eV) for ceramics-in-polymer and 150 wt% (sigma = 2.74.10(-5) S.cm(- 1) (30 degrees C) and E-a = 0.116 eV) for polymer-in-ceramics'
    if paper['id'] != PAPER or quote not in paper['abstract']:
        raise ValueError('Curated measurement evidence does not match observed source')
    rows=[]
    for loading,sigma,ea in [(25,3.56e-5,.118),(150,2.74e-5,.116)]:
        rows.append({'nzsp_loading_wt_percent_as_reported':loading,
                     'measured_sigma_S_cm':sigma,'measured_temperature_K':303.15,
                     'activation_energy_eV':ea,'target_temperature_K':temperature,
                     'projected_sigma_S_cm':sigma*math.exp(-ea/8.617333262145e-5*(1/temperature-1/303.15))})
    return {'status':'computed_unreviewed','origin':'arrhenius_temperature_projection',
            'input_origin':'assistant_curated_abstract_measurements','paper_id':PAPER,
            'doi':paper['doi'],'quote':quote,'rows':rows,
            'formula':'sigma(T)=sigma(T0)*exp[-Ea/kB*(1/T-1/T0)]',
            'assumptions':['Constant apparent activation energy near 30 C; no phase change.',
                           'Loading basis must be checked in full text before preparing recipes.'],
            'limitations':['No uncertainty intervals available from abstract.',
                           'Sodium electrolyte; cannot transfer this value to lithium.',
                           'Not an independent structure prediction or MD simulation.'],
            'eligible_for_ranking':False}


class DemoHarness(SparkHarness):
    def definitions(self):
        # This task deliberately exposes only the relevant, implemented tools.
        names={'spark_capabilities','read_application_paper','classify_application','get_simulation_record'}
        return [d for d in super().definitions() if d['function']['name'] in names]+[DEFINITION]

    def execute(self,name,arguments):
        if name!='project_paper_conductivity':
            return super().execute(name,arguments)
        reply={'tool':name,'status':'error','data':None,'error':None}
        try:
            if self.tool_calls>=self.max_tool_calls:raise ValueError('Tool budget exhausted')
            self.tool_calls+=1
            check_args(DEFINITION,arguments)
            paper=self.application_papers.get(PAPER)
            if paper is None:raise ValueError('Read the source paper first')
            reply.update(status='ok',data=self.simulations._save('temperature_projection',project(paper,arguments['temperature_K'])))
        except Exception as exc:
            reply['error']={'type':type(exc).__name__,'message':str(exc)}
        with (self.output/'events.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'arguments':arguments,**reply},ensure_ascii=False)+'\n')
        return reply


if __name__=='__main__':
    load_env()
    out=ROOT/'outputs'/datetime.now().strftime('recommendation_%Y%m%d_%H%M%S')
    h=DemoHarness(out,application_catalog=CATALOG,knowledge_db=ROOT/'outputs/memory.sqlite',
                  project_id='spark-recommendation-demo',max_model_calls=14,max_tool_calls=10)
    task=(f'完成一个真实的文献驱动推荐样例。目录中的论文ID为 {PAPER}。研究目标是固态聚合物电解质，'
          '本次允许钠体系作为方法演示，但必须明确不能迁移为锂电池性能结论。请自主选择工具了解能力、读取和判断文献应用，'
          '根据可用工具估计两种配方在298.15 K的电导率，并从记忆取回计算结果核对。'
          '给出优先继续验证的配方、两者数值和相对差异，讨论电导率与迁移数的取舍、距离1e-4 S/cm的差距，'
          '及下一步实验。说明哪些是实测、哪些是外推、哪些还无法预测。引用DOI和记录ID。'
          '原文没有的信息不得补造。得到足够证据后用finish返回中文推荐。')
    client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],8192,SYSTEM+
                    '\nKeep each tool decision concise. This is a bounded single-paper method demo, not a discovery benchmark.')
    (out/'run_config.json').write_text(json.dumps({'model':client.model,'max_tokens':8192,'task':task},ensure_ascii=False,indent=2),encoding='utf-8')
    result=run_planner(h,client,task,max_steps=11)
    (out/'recommendation.txt').write_text(result['answer'] or json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(out),**result},ensure_ascii=False,indent=2))
