"""Explicit, label-free HPG inference inputs; no names-to-structure guessing.

This adapter uses authors' hierarchical graph and anion-only lithium-salt
encoding. Molecular weights used for mass accounting include the lithium ion.
"""
import sys,math,hashlib,json,os,warnings
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.environ['DGLBACKEND']='pytorch'
sys.path[:0]=[str(ROOT/'.deps'),str(ROOT/'HPG')]
import torch,dgl,numpy as np
from rdkit import Chem
from src.polyG import Fragment,Node,PolymerGraph
from src.mol2graph import pol2hig_mk2,mon2hig_mk2
from src.hpggat import GATNet
EO_MASS=44.053
SALTS={
 'LiTFSI':{'smiles':'O=S([N-]S(=O)(C(F)(F)F)=O)(C(F)(F)F)=O','molar_mass_g_mol':287.088},
 'LiClO4':{'smiles':'O=Cl(=O)([O-])=O','molar_mass_g_mol':106.39},
}
def positive(value,name):
 if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError(name+' must be finite and positive')
 return float(value)
def build_polymer(spec):
 nodes=spec['nodes'];names=[n['name'] for n in nodes]
 if not nodes or len(names)!=len(set(names)):raise ValueError('Unique nonempty fragment names required')
 for n in nodes:
  smiles=n['smiles']
  for site in ['R','Q','T','U']:smiles=smiles.replace('['+site+']',f'[Mg:{["R","Q","T","U"].index(site)+1}]')
  if Chem.MolFromSmiles(smiles) is None:raise ValueError('Invalid fragment SMILES')
  if not n['connections']:raise ValueError('Explicit fragment connections required')
  for site,(target,degree) in n['connections'].items():
   if '['+site+']' not in n['smiles']:raise ValueError('Source connection site absent')
   target_name,target_site=target.split('.')
   if target_name not in names:raise ValueError('Unknown target fragment')
   target_node=nodes[names.index(target_name)]
   if '['+target_site+']' not in target_node['smiles']:raise ValueError('Target connection site absent')
   positive(degree,'connection degree')
 obj=PolymerGraph(spec['name'],[Node(Fragment(n['name'],n['smiles']),n['connections']) for n in nodes],MW=positive(spec['reported_mw_g_mol'],'reported Mw'))
 return pol2hig_mk2(obj)
def peo_spec(mw,degree_multiplier=1.0,orientation='CCO'):
 positive(mw,'Mw');positive(degree_multiplier,'degree multiplier')
 if orientation not in ['CCO','OCC']:raise ValueError('Unsupported PEO representation')
 degree=max(1,round(mw/EO_MASS*degree_multiplier))
 return {'name':'PEO_literature','reported_mw_g_mol':mw,'nodes':[{'name':'PEO','smiles':'[R]'+orientation+'[Q]','connections':{'R':['PEO.Q',degree]}}],
 'representation_assumptions':['Linear PEO represented in authors repeat-fragment convention; end groups not separately modelled.','degree=round(Mw/44.053), a weight-average molecular-weight proxy, NOT measured number-average DP.'], 'degree_multiplier':degree_multiplier}
def fractions(sample):
 if sample.get('other_final_components'):raise ValueError('Unrepresented final components must not be silently dropped')
 salt=sample['salt']
 if salt not in SALTS:raise ValueError('Salt encoding not reviewed')
 if sample.get('mass_g'):
  a=positive(sample['mass_g']['PEO'],'PEO mass');b=positive(sample['mass_g'][salt],'salt mass')
 elif sample.get('eo_li_ratio') is not None:
  a=positive(sample['eo_li_ratio'],'EO:Li')*EO_MASS;b=SALTS[salt]['molar_mass_g_mol']
 else:raise ValueError('Explicit masses or EO:Li ratio required')
 return [a/(a+b),b/(a+b)]
def build_input(sample,temperature_C,degree_multiplier=1.0,orientation='CCO'):
 if type(temperature_C) not in (float,int) or not math.isfinite(temperature_C) or temperature_C<=-273.15:raise ValueError('Invalid Celsius temperature')
 weights=fractions(sample);spec=peo_spec(sample['mw_g_mol'],degree_multiplier,orientation)
 graphs=[build_polymer(spec),mon2hig_mk2(SALTS[sample['salt']]['smiles'])]
 graphs.extend(mon2hig_mk2('C') for _ in range(4))
 ratio=weights+[0.0]*4
 meta={'polymer_spec':spec,'salt':sample['salt'],'salt_smiles':SALTS[sample['salt']]['smiles'],'salt_encoding':'authors_anion_only; full salt molar mass used for ratio','weight_fractions':ratio,'temperature_C':temperature_C,'origin':'model_prediction','uncertainty':None,'eligible_for_ranking':False}
 meta['input_hash']=hashlib.sha256(json.dumps(meta,sort_keys=True).encode()).hexdigest()
 return graphs,ratio,temperature_C,meta
def load_model():
 torch.set_num_threads(4);m=GATNet()
 m.load_state_dict(torch.load(ROOT/'HPG/ckpt/HPG_GAT.bin',map_location='cpu',weights_only=True));m.eval();return m
def predict(model,graphs,ratio,temperature_C):
 # Batch creates new graph objects, since author forward mutates node features.
 inputs=[dgl.batch([g]) for g in graphs]+[torch.tensor([ratio],dtype=torch.float32),torch.tensor([[(temperature_C-33.923080)/40.216135]],dtype=torch.float32)]
 with torch.no_grad():raw=float(model(inputs).reshape(-1)[0])
 log=raw*1.836202-3.981499
 return {'log10_sigma_S_cm':log,'sigma_S_cm':10**log}
def graph_arrays(g):
 a,b=g.edges();return {'src':a.numpy(),'dst':b.numpy(),'node_features':g.ndata['h'].numpy(),'edge_features':g.edata['e'].numpy()}
def graph_summary(g):
 a=graph_arrays(g);h=hashlib.sha256()
 for k,v in a.items():h.update(k.encode());h.update(v.tobytes())
 return {'nodes':g.num_nodes(),'edges':g.num_edges(),'node_feature_dim':g.ndata['h'].shape[1],'tensor_sha256':h.hexdigest(),'all_finite':all(np.isfinite(v).all().item() for v in a.values())}
