"""Bounded live rerun of source-preserving search, then one primary-paper extraction."""
import json
import os
from datetime import datetime
from spark_harness import ROOT, SparkHarness
from planner import run_planner, SYSTEM
from llm import LLMClient
from curator import Client
from config import load_env

if __name__=='__main__':
    load_env();model,base=os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL']
    out=ROOT/'outputs'/('followup_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    h=SparkHarness(out,client=Client(model,base,10000),max_model_calls=12,max_tool_calls=16)
    print(out,flush=True)
    client=LLMClient(model,base,8192,SYSTEM+'\nUse spark_screen_search with returned paper IDs instead of screen_candidates. Never rewrite source abstracts. Archive absence of weights blocks NEW inference, not reading another seed. Keep final answer within 400 Chinese characters.')
    result=run_planner(h,client,'检索 polysiloxane imidazolium polymer electrolyte 的5篇开放文献，使用 spark_screen_search 按ID筛选。总结原创研究与综述的数量，不能把染料敏化太阳能电池电解质说成已验证的锂电池固态电解质。',max_steps=6)
    attempts=[]
    # Only primary-study leads; no substitution of reviews for extraction success.
    for paper in list(h.search_papers.values()):
        screened=h.spark_dispatch('spark_screen_search',{'paper_ids':[paper['id']]})['papers'][0]
        if screened['screening']['decision']!='include':continue
        for url in paper['pdf_urls'][:2]:
            fetched=h.execute('fetch_pdf',{'url':url})
            attempts.append({'paper_id':paper['id'],'url':url,'download':fetched})
            if fetched['status']!='ok':continue
            opened=h.execute('open_corpus',{'paths':[fetched['data']['path']]})
            if opened['status']!='ok':continue
            extracted=h.execute('extract_records',{'corpus_id':opened['data']['corpus_id'],'max_calls':4})
            attempts[-1]['extraction']=extracted
            break
        if len(attempts)>=3 or any('extraction' in a for a in attempts):break
    (out/'pilot_result.json').write_text(json.dumps({'planner':result,'fulltext_attempts':attempts},ensure_ascii=False,indent=2),encoding='utf-8')
    print(result['status'], 'download_attempts',len(attempts),flush=True)
