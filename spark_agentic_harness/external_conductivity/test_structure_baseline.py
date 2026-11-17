"""New fingerprint baseline on public ChemArr data, NOT ChemArr reproduction."""
import sys,json,hashlib,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/'.deps'))
import numpy as np,pandas as pd
from rdkit import Chem,DataStructs
from rdkit.Chem import rdFingerprintGenerator
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.model_selection import GroupShuffleSplit,train_test_split
from sklearn.metrics import mean_absolute_error,mean_squared_error,r2_score
df=pd.read_csv(ROOT/'Chem-prop-pred/data/clean_train_data.csv')
# Complete measured inputs only; do not impute undocumented chemistry/conditions.
df=df.dropna(subset=['smiles','salt smiles','mw','molality','temperature','conductivity']).copy()
df=df[(df.mw>0)&(df.molality>=0)&(df.temperature>-273.15)].copy()
gen=rdFingerprintGenerator.GetMorganGenerator(radius=2,fpSize=256)
cache={}
for s in set(df.smiles)|set(df['salt smiles']):
    mol=Chem.MolFromSmiles(s)
    if mol is None:continue
    bits=np.zeros(256,dtype=np.int8);DataStructs.ConvertToNumpyArray(gen.GetFingerprint(mol),bits)
    cache[s]=(Chem.MolToSmiles(mol),bits)
df=df[df.smiles.isin(cache)&df['salt smiles'].isin(cache)].copy().reset_index(names='original_row')
df['polymer_group']=df.smiles.map(lambda s:cache[s][0])
df['formulation_group']=[json.dumps([cache[r.smiles][0],cache[r['salt smiles']][0],float(r.mw),float(r.molality)]) for _,r in df.iterrows()]
fp=np.array([np.concatenate([cache[r.smiles][1],cache[r['salt smiles']][1]]) for _,r in df.iterrows()])
condition=np.column_stack([np.log10(df.mw),df.molality,1000/(df.temperature+273.15)])
X=np.column_stack([fp,condition]);y=df.conductivity.to_numpy();rows=[];out=ROOT/'results';out.mkdir(exist_ok=True)
for seed in [17,29,43]:
 for split in ['random_rows','heldout_formulation','heldout_polymer']:
    idx=np.arange(len(df))
    if split=='random_rows':train,test=train_test_split(idx,test_size=.2,random_state=seed)
    else:
        group=df['formulation_group' if split=='heldout_formulation' else 'polymer_group']
        train,test=next(GroupShuffleSplit(n_splits=1,test_size=.2,random_state=seed).split(X,y,group))
    for feature,x in [('conditions_only',condition),('structure_and_conditions',X)]:
        start=time.time();m=ExtraTreesRegressor(n_estimators=120,min_samples_leaf=2,max_features=.8,random_state=seed,n_jobs=1).fit(x[train],y[train]);p=m.predict(x[test])
        r={'seed':seed,'split':split,'features':feature,'n_train':len(train),'n_test':len(test),'MAE_log10_S_cm':mean_absolute_error(y[test],p),'RMSE_log10_S_cm':float(np.sqrt(mean_squared_error(y[test],p))),'R2':r2_score(y[test],p),'seconds':time.time()-start}
        rows.append(r)
        pd.DataFrame({'original_row':df.iloc[test].original_row,'measured_log10_S_cm':y[test],'predicted_log10_S_cm':p}).to_csv(out/f'baseline_{split}_{feature}_{seed}.csv',index=False)
        print(json.dumps(r),flush=True)
summary={'method':'Our newly trained ExtraTrees + 256-bit polymer/salt Morgan fingerprints, NOT ChemArr or authors benchmark reproduction','complete_rows':len(df),'polymer_groups':df.polymer_group.nunique(),'formulation_groups':df.formulation_group.nunique(),'runs':rows,'limitations':['Three fixed splits, no hyperparameter tuning or validation-selected model.','Polymer split uses canonical input graph identity, not structural family or paper groups.','Public CSV lacks paper identifiers; inter-paper contamination is not ruled out.','Endpoint marker atoms Cu/Au are retained from authors representation.']}
(out/'structure_baseline_summary.json').write_text(json.dumps(summary,indent=2))
