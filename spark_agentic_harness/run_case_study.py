from pathlib import Path
import json,hashlib,os,re,copy
import fitz
from run_extended import ExtractionHarness,ROOT,EXTRAS
from spark_harness import spec,check_args
from planner import run_planner,SYSTEM
from llm import LLMClient
from config import load_env

OUT=ROOT/'outputs/extended_20261117/case_study'
PID='case_acsnano_4c01257'
MORE=[spec('search_case_fulltext','Search the local 14-page PDF text for a phrase, returning page numbers and snippets. Use when abstract evidence is insufficient.',{'query':{'type':'string'}},['query']),
      spec('read_case_pages','Read selected 1-based PDF pages and add them to the observed evidence for subsequent extraction. Does not invent missing SI values.',{'pages':{'type':'array','items':{'type':'integer'}}},['pages'])]

class CaseHarness(ExtractionHarness):
    def __init__(self,*args,pages,**kwargs):super().__init__(*args,**kwargs);self.pages=pages;self.read_pages=set()
    def definitions(self):return super().definitions()+MORE
    def execute(self,name,arguments):
        definition=next((d for d in MORE if d['function']['name']==name),None)
        if definition is None:return super().execute(name,arguments)
        reply={'tool':name,'status':'error','data':None,'error':None}
        try:
            if self.tool_calls>=self.max_tool_calls:raise ValueError('Tool budget exhausted')
            self.tool_calls+=1;check_args(definition,arguments)
            if name=='search_case_fulltext':
                q=arguments['query'].casefold();hits=[]
                if not q.strip():raise ValueError('Nonempty query required')
                for i,t in enumerate(self.pages,1):
                    at=t.casefold().find(q)
                    if at>=0:hits.append({'page':i,'snippet':t[max(0,at-120):at+650]})
                data={'hits':hits[:5],'total_hits':len(hits)}
            else:
                if PID not in self.application_papers:raise ValueError('Read abstract first')
                requested=arguments['pages']
                if not 1<=len(requested)<=3 or any(isinstance(n,bool) or not 1<=n<=len(self.pages) for n in requested):raise ValueError('Read 1..3 valid pages per call')
                self.read_pages.update(requested)
                base=json.loads((OUT/'catalog.json').read_text(encoding='utf-8'))[0]
                updated=copy.deepcopy(base)
                updated['abstract']=base['abstract']+'\n'+'\n'.join(f'[PDF page {n}] '+self.pages[n-1] for n in sorted(self.read_pages))
                self.application_papers[PID]=updated
                data={'paper_id':PID,'pages':[{'page':n,'text':self.pages[n-1]} for n in requested],
                      'source_type':'local_pdf_text','all_observed_pages':sorted(self.read_pages),'extraction_note':'Call extract_transport_evidence again to use the expanded source.'}
            reply.update(status='ok',data=self.simulations._save('pdf_evidence',data))
        except Exception as exc:reply['error']={'type':type(exc).__name__,'message':str(exc)}
        with (self.output/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'arguments':arguments,**reply},ensure_ascii=False)+'\n')
        return reply

if __name__=='__main__':
    load_env();OUT.mkdir(exist_ok=True,parents=True)
    inventory=json.loads((ROOT/'outputs/local_corpus_inventory.json').read_text(encoding='utf-8'))
    path=next(p for f in inventory['files'] for p in f['paths'] if 'three-dimensional-metal-organic' in p)
    path=Path(path) if Path(path).is_absolute() else ROOT.parent/Path(path)
    doc=fitz.open(path);pages=[re.sub(r'\s+',' ',p.get_text()).strip() for p in doc]
    abstract=pages[0].split('ABSTRACT:',1)[1].split('KEYWORDS:',1)[0]
    paper={'id':PID,'title':'Three-Dimensional Metal–Organic Framework@Cellulose Skeleton-Reinforced Composite Polymer Electrolyte for All-Solid-State Lithium Metal Battery',
           'doi':'10.1021/acsnano.4c01257','year':2024,'abstract':abstract}
    (OUT/'catalog.json').write_text(json.dumps([paper],ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'pdf_pages.json').write_text(json.dumps({'path':path,'sha256':hashlib.sha256(open(path,'rb').read()).hexdigest(),'pages':pages},ensure_ascii=False,indent=2),encoding='utf-8')
    h=CaseHarness(OUT/'execution',pages=pages,application_catalog=OUT/'catalog.json',knowledge_db=OUT/'memory.sqlite',project_id='case-study-acsnano',max_model_calls=22,max_tool_calls=18)
    task=(f'研究案例{PID}：目标是判断ZIF-67@CF/PEO-SN在25℃是否有足够电导率，并提出相对PEO与ZIF-67@CF/PEO的验证方案。'
          '从摘要开始，调用独立分类与性质抽取；若缺数据，利用本地PDF工具查找原文证据，必要时重新抽取、计算、从记忆取回结果。'
          '请明确区分摘要知道什么、全文新增什么、工具计算什么和论文已经测过什么。不要把不同样品的Ea混用。'
          '最后中文回答包含电导率、迁移数、力学/界面取舍以及下一步实验，给出页码/DOI/记录ID。'
          '25℃若只有图示没有表S1精确值，不能把计算值当原文实测。最多读取三页一次，每轮一个JSON动作。')
    client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],8192,SYSTEM+'\nReturn exactly JSON. This case supports local full-text retrieval; repair missing abstract evidence by searching and reading pages. Numeric tool estimates are not author-reported measurements.')
    result=run_planner(h,client,task,max_steps=16)
    (OUT/'recommendation.txt').write_text(result['answer'],encoding='utf-8')
    print(json.dumps({'status':result['status'],'steps':result['steps'],'calls':result['model_calls'],'pages':sorted(h.read_pages)},ensure_ascii=False),flush=True)
