"""Freeze assistant-reviewed references before model evaluation. Not expert gold."""
import copy
import hashlib
import json
from pathlib import Path
from spark_harness import ROOT
from curator import Corpus, validate
from knowledge import KnowledgeStore

OUT=ROOT/'outputs'/'review_20261117'
def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    OUT.mkdir(exist_ok=True)
    old=ROOT/'outputs'/'followup_20261117_105838'/'extraction_007'/'result.json'
    original=json.loads(old.read_text(encoding='utf-8'))
    pdf=Path(original['sources'][0]['path']); corpus=Corpus([pdf])
    reviewed=copy.deepcopy(original)
    quote='electrolytes without BN, with 1% BN and 10% BN'
    assert quote in corpus.pages[('S1',5)]
    changes=[]
    for i,rec in enumerate(reviewed['records']):
        if i>=3:
            before=copy.deepcopy(rec['sample']['evidence'])
            rec['sample']['evidence']=[{'source':'S1','page':5,'quote':quote}]
            changes.append({'record':rec['id'],'field':'sample.evidence','before':before,'after':rec['sample']['evidence']})
    issues,_=validate(reviewed['records'],corpus.pages)
    reviewed.update(status='assistant_reviewed',issues=issues,
                    review={'reviewer':'assistant; text and rendered pages checked; no independent expert review',
                            'parent_artifact':str(old),'parent_sha256':hashlib.sha256(old.read_bytes()).hexdigest(),
                            'changes':changes,'eligible_for_ranking':False,
                            'preparation_solvent':'DMF/acetone 2:1 v/v; vacuum dry 70 C 24 h (PDF page 3)',
                            'residual_solvent':'PDF page 9 reports 10% and 20% residual solvent for with/without BN; mainly DMF. Do not infer solvent-free.',
                            'measurement_context':'R1-R3 salt-ratio comparison p5; R4-R7 BN comparison p9. R1 and R4 baseline conductivities differ; do not merge.',
                            'temperature_note':'21 C is approximate room temperature from methods p5; R7 explicitly 100 C p9',
                            'coverage':'Seven preselected records, not exhaustive; p10 aged measurements omitted.'})
    save('reviewed_records.json',reviewed)
    memory=KnowledgeStore(OUT/'review_memory.sqlite')
    save('review_memory_receipt.json',memory.ingest('spark-reviewed',reviewed,{'policy_version':'assistant-review-v1','artifact':str(OUT/'reviewed_records.json')}))
    cases=[]
    targets=[{'id':r['id'],'sample_request':r['sample']['value'],
              'context':'salt ratio comparison p5' if i<3 else 'BN comparison p9; 100 C' if i==6 else 'BN comparison p9; room temperature'} for i,r in enumerate(reviewed['records'])]
    cases.append({'id':'BN','path':str(pdf),'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
                  'pages':{str(n):corpus.pages[('S1',n)] for n in [3,5,9]},'targets':targets})
    gold=[{'paper':'BN','id':r['id'],'conductivity_S_cm':r['conductivity']['value'],'temperature_C':r['temperature']['value']} for r in reviewed['records']]
    paths=sorted((ROOT.parent/'To-ljh'/'2-Performance comparison'/'Baseline'/'Groudtruth').glob('ACSAEM*.pdf'))[:4]
    values=[None,9.5e-4,1.6e-3,2.6e-4]; temps=[None,None,None,25]
    names=['PVC-TPU/LAGP composite electrolyte','DPNGE','poly(VEC10-r-LiSTFSI)','glass-fiber reinforced PEO with nano-LiF and succinonitrile']
    for i,(path,value,temp,name) in enumerate(zip(paths,values,temps,names),2):
        c=Corpus([path]);pid=f'P{i}'
        cases.append({'id':pid,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                      'pages':{'1':c.pages[('S1',1)]},'targets':[{'id':pid,'sample_request':name,'context':'main material reported in the abstract; use only supplied page'}]})
        gold.append({'paper':pid,'id':pid,'conductivity_S_cm':value,'temperature_C':temp})
    save('cases.json',cases);save('reference.json',{'scope':'5 papers, 11 selected records; page-conditioned extraction, NOT full-paper recall or independent expert gold',
                'reviewer':'assistant visual/text review before API evaluation','records':gold,
                'null_semantics':'No explicit numeric value in supplied evidence; room temperature is not silently 25 C.'})
    print('Frozen',len(cases),'papers;',len(gold),'targets; reviewed quote issues:',len(issues))
