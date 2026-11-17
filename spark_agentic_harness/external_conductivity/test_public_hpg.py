"""Execute public HPG-GAT weights on its author-labelled validation subset.
No training; CPU compatibility versions recorded; no unrestricted pickle loads.
"""
import os,sys,json,pickle,hashlib,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.environ['DGLBACKEND']='pytorch'
sys.path[:0]=[str(ROOT/'.deps'),str(ROOT/'HPG')]
import torch,numpy as np,pandas as pd,dgl,rdkit
from src.polyG import PolymerGraph,Node,Fragment
from src.hpggat import GATNet,data_from_df,collate,pol2hig_mk2
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score

class StructureUnpickler(pickle.Unpickler):
    def find_class(self,module,name):
        if module=='__main__' and name in ['PolymerGraph','Node','Fragment']:
            return {'PolymerGraph':PolymerGraph,'Node':Node,'Fragment':Fragment}[name]
        raise pickle.UnpicklingError(f'Blocked unexpected class {module}.{name}')

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load():
    torch.set_num_threads(4)
    with (ROOT/'HPG/data/polyG.pt').open('rb') as f:cache=StructureUnpickler(f).load()
    graphs={k:pol2hig_mk2(v) for k,v in cache.items()}
    model=GATNet()
    model.load_state_dict(torch.load(ROOT/'HPG/ckpt/HPG_GAT.bin',map_location='cpu',weights_only=True))
    model.eval()
    return model,graphs

def predict_frame(model,graphs,frame):
    frame=frame.copy();frame['tags']=2
    _,data=data_from_df(frame,graphs)
    pred=[]
    with torch.no_grad():
        for i in range(0,len(data),16):
            inputs,_=collate(data[i:i+16]);pred.extend(model(inputs).reshape(-1).tolist())
    return np.array(pred)*1.836202-3.981499

if __name__=='__main__':
    start=time.time();out=ROOT/'results';out.mkdir(exist_ok=True)
    model,graphs=load();frame=pd.read_csv(ROOT/'HPG/data/processed_electrolytes.csv')
    test=frame[frame.tags==2].copy();pred=predict_frame(model,graphs,test);y=np.log10(test.Conductivity.to_numpy())
    test['predicted_log10_S_cm']=pred;test['predicted_sigma_S_cm']=10**pred
    test['absolute_log10_error']=abs(pred-y);test.to_csv(out/'hpg_validation_predictions.csv',index=False)
    # Sensitivity is a model query, not new experimental validation.
    probes=pd.concat([test.iloc[[0]].assign(Temperature=t) for t in [0,25,60,90]],ignore_index=True)
    probes['predicted_log10_S_cm']=predict_frame(model,graphs,probes)
    probes['predicted_sigma_S_cm']=10**probes.predicted_log10_S_cm
    probes['query_type']='temperature_sensitivity_not_validation'
    probes['source_record_temperature_C']=float(test.iloc[0].Temperature)
    probes=probes.drop(columns=['Conductivity','absolute_log10_error'])
    probes.to_csv(out/'hpg_temperature_sensitivity.csv',index=False)
    summary={'model':'HPG-GAT public pretrained weights','n':len(y),'MAE_log10_S_cm':mean_absolute_error(y,pred),
      'RMSE_log10_S_cm':float(np.sqrt(mean_squared_error(y,pred))),'R2':r2_score(y,pred),
      'within_factor_2':float(np.mean(abs(y-pred)<=np.log10(2))),'within_factor_10':float(np.mean(abs(y-pred)<=1)),
      'polymer_graph_count':len(graphs),'elapsed_seconds':time.time()-start,
      'weights_sha256':sha(ROOT/'HPG/ckpt/HPG_GAT.bin'),'data_sha256':sha(ROOT/'HPG/data/processed_electrolytes.csv'),
      'versions':{'torch':torch.__version__,'dgl':dgl.__version__,'rdkit':rdkit.__version__},
      'evaluation':'Author tags==2 validation, checkpoint selected using this validation in public notebook; NOT independent blind test.',
      'input_representation':'Original six component hierarchical graphs, original ratio calculation, original temperature and target normalization.',
      'limitations':['No new training; dependency versions differ from authors.',
        'Public preprocessing can infer ratios when missing; harness requests must prohibit silent defaults.',
        'Validation metric does not establish accuracy for new polymer families or our MOF composite.']}
    (out/'hpg_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2))
