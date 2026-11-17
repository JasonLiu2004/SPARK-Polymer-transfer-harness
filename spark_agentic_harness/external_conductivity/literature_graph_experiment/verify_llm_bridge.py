"""Normalize reviewed extraction fields, build fresh graphs and compare local audit."""
import sys,json,re,math
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import hpg_graph_adapter as h
def molecular_weight(value):
 text=str(value).replace(',','').replace(' ','')
 match=re.fullmatch(r'(?:Mw[=≈])?([0-9]+(?:\.[0-9]+)?)',text)
 if not match:raise ValueError('Unreviewed molecular-weight notation: '+text)
 return float(match[1])
def ratio(value):
 parts=str(value).split(':')
 if len(parts)==1:return float(parts[0])
 if len(parts)==2:return float(parts[0])/float(parts[1])
 raise ValueError('Unknown EO ratio')
records=json.loads((HERE/'results/literature_records.json').read_text(encoding='utf-8'))
model=h.load_model();out=[]
for cid,ref in zip(['nano_control','small_control','mof_control'],records):
 raw=json.loads((HERE/'extractions'/f'{cid}.json').read_text(encoding='utf-8'));a=raw['answer']
 assert 'parse_error' not in a,cid
 assert raw['source_sha256']==ref['source_sha256']
 assert raw['quote_checks'] and all(q['verbatim'] for q in raw['quote_checks']),cid
 assert a['polymer']['value'].lower() in ['peo','polyethylene oxide','poly(ethylene oxide)']
 s={'id':cid,'mw_g_mol':molecular_weight(a['molecular_weight']['value']),'salt':a['salt']['value'],'other_final_components':a['other_final_components']}
 assert s['mw_g_mol']==ref['mw_g_mol'] and s['salt']==ref['salt']
 if a.get('polymer_mass') and a.get('salt_mass'):
  assert a['polymer_mass']['unit']==a['salt_mass']['unit']=='g'
  s['mass_g']={'PEO':float(a['polymer_mass']['value']),s['salt']:float(a['salt_mass']['value'])}
 else:s['eo_li_ratio']=ratio(a['eo_li_ratio']['value'])
 assert h.np.allclose(h.fractions(s),h.fractions(ref),atol=1e-12)
 for T in [25,30,40,60]:
  graphs,r,t,meta=h.build_input(s,T);pred=h.predict(model,graphs,r,t)
  out.append({'extraction':cid,'source_sha256':raw['source_sha256'],'normalized_input':s,'temperature_C':T,'temperature_origin':'explicit model query; not extracted measurement temperature','graph':h.graph_summary(graphs[0]),'prediction':pred})
(HERE/'results/llm_bridge_predictions.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'verified_extractions':3,'predictions':len(out),'all_compositions_match_source_review':True}))
