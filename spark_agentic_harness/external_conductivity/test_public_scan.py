"""Public SCAN checkpoint smoke test in repository-native target units."""
import sys,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'SCAN/model'),str(ROOT/'SCAN')]
import torch,numpy as np,pandas as pd
from route_model import MultiModalNet
from descriptor import salt_properties,solvent_properties,c_unit_encode,solvent_ratio_type_code
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score
torch.set_num_threads(4)
d=pd.read_csv(ROOT/'SCAN/data/calisol.csv')
# Match the authors' descriptor code exactly, including raw T and ratio sums.
xs=[];xv=[];xc=[]
for _,r in d.iterrows():
    xs.append(salt_properties[r['salt']]);v=np.zeros(14)
    for name,ratio in r.iloc[6:].items():
        if ratio!=0:v+=np.array(solvent_properties[name])*ratio
    xv.append(v);xc.append([r['T']]+c_unit_encode[r['c units']]+solvent_ratio_type_code[r['solvent ratio type']]+[r['c']])
path=ROOT/'SCAN/trained_pth_model/MFNet_fold_1_model.pth'
state=torch.load(path,map_location='cpu',weights_only=True)
layers=state['routing_layer.routing_weights.2.weight'].shape[0]
model=MultiModalNet(feature_dims=[14,14,6],hidden_dim=16,num_layers=layers)
model.load_state_dict(state,strict=True);model.eval()
arrays=[np.array(x,dtype=np.float32) for x in [xs,xv,xc]];y=d.k.to_numpy()
_,test=next(StratifiedKFold(n_splits=5,shuffle=True,random_state=42).split(y,np.digitize(y,[1.,4.])))
with torch.no_grad():pred=model(*[torch.from_numpy(x[test]) for x in arrays]).numpy().reshape(-1)
out=ROOT/'results';out.mkdir(exist_ok=True)
frame=d.iloc[test].copy();frame['source_row']=test;frame['predicted_native_k']=pred;frame.to_csv(out/'scan_fold1_predictions.csv',index=False)
summary={'model':'SCAN public fold1 checkpoint','n':len(test),'MAE_native_k':mean_absolute_error(y[test],pred),'RMSE_native_k':float(np.sqrt(mean_squared_error(y[test],pred))),'R2':r2_score(y[test],pred),
 'target_unit':'repository native k; physical scaling not independently reconciled; no S/cm conversion performed',
 'weights_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
 'compatibility':'Published create_model defaults to 4 routing heads, checkpoint has 9; constructed same class with checkpoint-derived 9 heads, strict load succeeds.',
 'evaluation':'First fold reconstructed from authors StratifiedKFold(5,shuffle=True,random_state=42); checkpoint-fold linkage not independently certified.',
 'domain':'nonaqueous liquid electrolytes, not polymer conductivity',
 'eligible_for_ranking':False,'status':'inference_smoke_test_only'}
(out/'scan_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
