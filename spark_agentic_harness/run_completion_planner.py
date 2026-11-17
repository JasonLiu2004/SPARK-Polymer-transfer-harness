"""Real LLM demonstration of archive/legacy evidence retrieval and memory."""
import json,os
from datetime import datetime
from spark_harness import SparkHarness,ROOT
from config import load_env
from llm import LLMClient
from planner import run_planner,SYSTEM

class CompletionPlannerHarness(SparkHarness):
    def definitions(self):
        names={'spark_candidates','lookup_spark_conductivity','search_legacy_conductivity','get_simulation_record'}
        return [d for d in super().definitions() if d['function']['name'] in names]

if __name__=='__main__':
    load_env()
    output=ROOT/'outputs'/('completion_planner_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    h=CompletionPlannerHarness(output,max_model_calls=10,max_tool_calls=8,project_id='completion-planner')
    client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],8192,SYSTEM)
    result=run_planner(h,client,
      '核查两件事：1. 旧抽取表中three-dimensional metal-organic framework cellulose skeleton论文是否有可用电导率值，注意空值；'
      '2. 从20260814归档候选找polymethylhydrosiloxane / imidazolium / TFSI精确母题，用专用工具查看三个种子的电导率预测。'
      '从记忆回读至少一个结果，500字以内中文解释哪些是旧抽取、哪些是模型预测、缺什么证据。候选搜索limit=50，旧表limit=2以控制上下文。',max_steps=10)
    (output/'recommendation.txt').write_text(result['answer'],encoding='utf-8')
    print(json.dumps({'output':str(output),'status':result['status'],'steps':result['steps'],'model_calls':result['model_calls']},ensure_ascii=False))
