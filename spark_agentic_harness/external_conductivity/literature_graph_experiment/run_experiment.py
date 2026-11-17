"""Local source-checked literature controls -> fresh graphs -> pretrained HPG."""
import sys,json,hashlib,re,csv,copy,math
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import hpg_graph_adapter as h
import fitz
from test_public_hpg import StructureUnpickler
CORPUS=HERE.parents[3]
OUT=HERE/'results';OUT.mkdir(exist_ok=True)
cases=[
 dict(id='nano_PEO',pattern='*three-dimensional-metal-organic*.pdf',pages=[7,10,11],salt='LiTFSI',mw_g_mol=6000000,mass_g={'PEO':1,'LiTFSI':0.41},temperature_C=30,measured_sigma_S_cm=1.72e-5,measurement_status='temperature assigned from paragraph and Figure 6 context'),
 dict(id='small_PEO0',pattern='*GQDs*.pdf',pages=[2,4,10],salt='LiClO4',mw_g_mol=6000000,eo_li_ratio=20,temperature_C=None,measured_sigma_S_cm=6.79e-7,measurement_status='room temperature; exact numeric temperature not assigned'),
 dict(id='aem_PEO',pattern='*PEO-Based Solid-State Electrolytes Reinforced*.pdf',pages=[3,6],salt='LiTFSI',mw_g_mol=1000000,eo_li_ratio=16,temperature_C=None,measured_sigma_S_cm=None,measurement_status='no numeric pure PEO conductivity assigned'),
]
for s in cases:
 files=list(CORPUS.rglob(s.pop('pattern')));p=next(p for p in files if 'Groudtruth' in str(p) or 'filtered_papers' in str(p))
 with fitz.open(p) as doc:pages={str(n):doc[n-1].get_text() for n in s.pop('pages')}
 s.update(source_path=str(p),source_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),extraction_origin='local PDF text with manual source review; no LLM call',other_final_components=[],processing_assumption='dry polymer/salt control; casting solvent excluded, residual solvent not quantified')
 s['doi']=re.findall(r'10\.\d{4,9}/[A-Za-z0-9.]+',' '.join(pages.values()))
 (OUT/(s['id']+'_source_pages.json')).write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'literature_records.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
model=h.load_model();rows=[];checks=[]
def check(name,passed,**detail):
 checks.append(dict(name=name,passed=bool(passed),**detail))
def query(s,T,kind='temperature',mult=1,orientation='CCO'):
 gs,r,t,meta=h.build_input(s,T,mult,orientation)
 pred=h.predict(model,gs,r,t)
 row=dict(case=s['id'],experiment=kind,temperature_C=T,degree_multiplier=mult,orientation=orientation,**pred)
 rows.append(row);return gs,r,t,meta,pred
for s in cases:
 for T in [25,30,40,60]:query(s,T)
 T=s['temperature_C'] or 30
 gs,r,t,meta,pred=query(s,T,'baseline')
 meta.update(source=s,graphs=[h.graph_summary(g) for g in gs])
 (OUT/(s['id']+'_graph.json')).write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
 h.np.savez(OUT/(s['id']+'_polymer_graph.npz'),**h.graph_arrays(gs[0]))
 check(s['id']+'_graph_finite',all(h.graph_summary(g)['all_finite'] for g in gs))
 check(s['id']+'_fraction_sum',abs(sum(r)-1)<1e-12)
 # Relabel every node; preserve graph connectivity, all features and edge order.
 perm=[]
 for g in gs:
  a,b=g.edges();n=g.num_nodes();q=h.dgl.graph((n-1-a,n-1-b),num_nodes=n)
  q.ndata['h']=g.ndata['h'].flip(0);q.edata['e']=g.edata['e'].clone();perm.append(q)
 delta=abs(h.predict(model,perm,r,t)['log10_sigma_S_cm']-pred['log10_sigma_S_cm'])
 check(s['id']+'_node_permutation',delta<1e-5,absolute_log10_difference=delta)
 for mult in [.5,2]:query(s,T,'degree_sensitivity',mult)
 query(s,T,'repeat_representation',orientation='OCC')
 if s['temperature_C'] is not None and s['measured_sigma_S_cm']:
  pred['measured_sigma_S_cm']=s['measured_sigma_S_cm'];pred['temperature_C']=T
  pred['absolute_log10_error']=abs(pred['log10_sigma_S_cm']-math.log10(s['measured_sigma_S_cm']))
  pred['fold_error']=10**pred['absolute_log10_error']
  (OUT/'matched_measurement.json').write_text(json.dumps(pred,indent=2),encoding='utf-8')
# Exact author graph reconstruction for all four single-fragment PEO cache entries.
with (h.ROOT/'HPG/data/polyG.pt').open('rb') as f:cache=StructureUnpickler(f).load()
for key,degree,orientation in [('20190321_sc6_PEO',12500,'CCO'),('20190326_9_PEO',1000,'CCO'),('PEO5E+6',113507,'OCC'),('20190319_6_PEO',6818,'OCC')]:
 spec=h.peo_spec(1000000,orientation=orientation);spec['nodes'][0]['connections']['R'][1]=degree
 actual=h.graph_arrays(h.build_polymer(spec));expected=h.graph_arrays(h.pol2hig_mk2(cache[key]))
 check('author_cache_'+key,all(h.np.array_equal(actual[k],expected[k]) for k in actual))
bad=copy.deepcopy(cases[0]);bad.pop('mass_g')
for name,s in [('missing_ratio',bad),('unrepresented_MOF',dict(cases[0],other_final_components=['ZIF-67','cellulose']))]:
 try:h.build_input(s,30);check(name,False)
 except ValueError as e:check(name,True,error=str(e))
bad=h.peo_spec(1000000);bad['nodes'][0]['connections']['R'][0]='unknown.Q'
try:h.build_polymer(bad);check('unknown_fragment',False)
except ValueError as e:check('unknown_fragment',True,error=str(e))
s=cases[0];equivalent=dict(s);equivalent.pop('mass_g');equivalent['eo_li_ratio']=(1/h.EO_MASS)/(.41/h.SALTS['LiTFSI']['molar_mass_g_mol'])
check('mass_vs_EO_ratio_conversion',h.np.allclose(h.fractions(s),h.fractions(equivalent),atol=1e-12))
with (OUT/'predictions.csv').open('w',newline='',encoding='utf-8-sig') as f:
 writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
(OUT/'validation_checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
summary={'case_count':len(cases),'prediction_count':len(rows),'checks_passed':sum(x['passed'] for x in checks),'checks_total':len(checks),'checkpoint_sha256':hashlib.sha256((h.ROOT/'HPG/ckpt/HPG_GAT.bin').read_bytes()).hexdigest(),'matched_numeric_measurements':1,'model':'public pretrained HPG-GAT; no training','scope':'PEO salt controls only; no filler removal from composite predictions; literature records manually reviewed','predictions':rows,'checks':checks}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
if not all(x['passed'] for x in checks):raise SystemExit('Validation failed: inspect checks')
