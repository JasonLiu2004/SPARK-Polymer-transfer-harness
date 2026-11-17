"""Source retrieval and numerical completion; never overwrite measured evidence."""
import csv
import hashlib
import json
import math
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parent
ARCHIVE=ROOT.parent/'SPARK_selected3_seed_shareable_20260807/SPARK_selected3_seed_shareable_20260807'
LEGACY=ROOT.parent/'To-ljh/3-Knowledge graph&Pattern discovery/4-Knowledge graph/kg_construction/构建知识图谱的数据/4_labeled_conductivity_data.csv'

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def positive(x,name):
    if type(x) not in (float,int) or not math.isfinite(x) or x<=0:raise ValueError(name+' must be finite and positive')
    return float(x)
def provenance(sample,source):
    if not isinstance(sample,str) or not sample.strip() or not isinstance(source,str) or not source.strip():raise ValueError('sample and source required')
    return {'sample':sample,'source':source,'eligible_for_ranking':False,'review_status':'unreviewed','inputs_verified':False}

def lookup_archive(candidate_id):
    outputs=[]
    for seed in [20260814,20260815,20260819]:
        folder=ARCHIVE/'04_runs/unified'/f'seed_{seed}'
        path=folder/'final_2024_property_predictions.jsonl'
        row=next((json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if json.loads(x)['candidate_id']==candidate_id),None)
        if row is None:continue
        unified_path=folder/'final_2024_unified.jsonl'
        unified=next(json.loads(x) for x in unified_path.read_text(encoding='utf-8').splitlines() if json.loads(x)['candidate_id']==candidate_id)
        outputs.append({'seed':seed,'names':unified['names'],'source_path':str(path),'source_sha256':digest(path),
            'diagnostic_sigma_S_cm':10**row['predicted_log10_s_cm'],'original_prediction':row,
            'planner_source_path':str(unified_path),'planner_source_sha256':digest(unified_path),
            'planner_property_decision':{k:unified.get(k) for k in ['property_abstained','property_abstention_reasons','property_decoder_abstained','property_decoder_abstention_reasons','property_qualified','property_modifier','property_uncertainty']},
            'decision_note':'Decoder and final planner use different gates; preserve BOTH decisions. A numeric value does not imply acceptance by the planner.'})
    return {'status':'found' if outputs else 'not_found','origin':'archived_ml_prediction',
        'candidate_id':candidate_id,'results':outputs,'eligible_for_ranking':False,
        'limitations':['Coarse motif, not an exact formulation or a measured paper value.',
          'Preserve abstentions and uncertainty; selected-seed spread is not a confidence interval.',
          'No new model inference performed; no mapping from a paper to a motif is automatic.']}

def search_legacy(query,limit=10):
    if not isinstance(query,str) or not query.strip():raise ValueError('Nonempty query required')
    if type(limit) is not int or not 1<=limit<=50:raise ValueError('limit must be 1..50')
    with LEGACY.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    terms=query.casefold().replace('-',' ').split()
    hits=[]
    for i,row in enumerate(rows,2):
        searchable=' '.join(row.get(k,'') for k in ['Title','Polymer.Name','Polymer.Abbr','Salts1.Name','Salts1.Abbr']).casefold().replace('-',' ')
        if all(t in searchable for t in terms):
            hits.append({'csv_line':i,'record':row})
    return {'status':'found' if hits else 'not_found','origin':'legacy_extraction_unverified',
      'source_path':str(LEGACY),'source_sha256':digest(LEGACY),'total_rows':len(rows),
      'matched_rows':len(hits),'results':hits[:limit],'eligible_for_ranking':False,
      'limitations':['Raw old extraction fields; do not treat as independently verified measurements.',
        'Resolve title, sample, salt ratio, units, temperature and original PDF/SI before merging.',
        'Rows may be duplicates or different formulations; missing data is not zero.']}

def from_resistance(sample,source,thickness_um,area_cm2,resistance_ohm,temperature_K,resistance_kind):
    p=provenance(sample,source)
    if resistance_kind!='electrolyte_bulk':raise ValueError('Require electrolyte bulk resistance, not charge-transfer or total cell resistance')
    l=positive(thickness_um,'thickness_um')*1e-4
    a=positive(area_cm2,'area_cm2');r=positive(resistance_ohm,'resistance_ohm');t=positive(temperature_K,'temperature_K')
    return {**p,'status':'computed_unreviewed','origin':'derived_from_resistance_geometry',
      'sigma_S_cm':l/(a*r),'temperature_K':t,'formula':'sigma=L/(R_bulk*A)',
      'inputs':{'thickness_um':thickness_um,'area_cm2':a,'resistance_ohm':r,'resistance_kind':resistance_kind},
      'limitations':['Bulk resistance selection and electrode geometry require source review.',
        'Ionic interpretation requires the appropriate experiment and negligible electronic conduction.']}

def analyze_trajectory(trajectory_path,sample,source,temperature_K,fit_start_ps,fit_end_ps,
                       unwrapped,complete_charge_carriers):
    """NPZ contains charge-carrier COMs, formal net charges and constant-volume cell.

    Does not use atom partial-charge self diffusivities as ion diffusivities.
    Includes fixed charged polymer groups if present. This is postprocessing,
    not MD execution or a convergence claim.
    """
    p=provenance(sample,source)
    if unwrapped is not True or complete_charge_carriers is not True:raise ValueError('Require continuous unwrapped carrier centers and all charge carriers including fixed groups')
    path=Path(trajectory_path)
    if path.suffix.lower()!='.npz':raise ValueError('NPZ required')
    with np.load(path,allow_pickle=False) as d:
        xyz=np.asarray(d['positions_nm'],float);time=np.asarray(d['time_ps'],float)
        z=np.asarray(d['charge_numbers'],float);volume=float(d['volume_nm3'])
    t=positive(temperature_K,'temperature_K');positive(volume,'volume_nm3')
    if xyz.ndim!=3 or xyz.shape[2]!=3 or xyz.shape[0]<40 or xyz.shape[1]<2 or xyz.shape[0]>20000 or xyz.shape[1]>10000:raise ValueError('Need 40..20000 frames and 2..10000 carriers, xyz coordinates')
    if time.shape!=(len(xyz),) or z.shape!=(xyz.shape[1],) or not all(np.isfinite(a).all() for a in [xyz,time,z]):raise ValueError('Invalid dimensions/nonfinite values')
    if np.any(z==0) or not np.allclose(z,np.round(z)) or abs(z.sum())>1e-8:raise ValueError('Net carrier charges must be nonzero integers and sum to zero')
    dt=np.diff(time)
    if np.any(dt<=0) or not np.allclose(dt,dt[0],rtol=1e-6,atol=1e-9):raise ValueError('Uniform increasing time grid required')
    start=positive(fit_start_ps,'fit_start_ps');end=positive(fit_end_ps,'fit_end_ps')
    lags=np.arange(1,len(xyz)//2+1);lagtime=lags*dt[0]
    mask=(lagtime>=start)&(lagtime<=end)
    if end>lagtime[-1] or np.count_nonzero(mask)<5:raise ValueError('Fit needs >=5 lags, no more than half the trajectory')
    collective=np.einsum('tij,i->tj',xyz,z)
    self_msd=[];charge_msd=[]
    for k in lags:
        delta=xyz[k:]-xyz[:-k]
        self_msd.append(np.mean(np.sum(delta*delta,axis=2),axis=0))
        charge_msd.append(np.mean(np.sum((collective[k:]-collective[:-k])**2,axis=1)))
    self_msd=np.array(self_msd);charge_msd=np.array(charge_msd)
    def fit(y):
        x=lagtime[mask];v=y[mask];slope,intercept=np.polyfit(x,v,1)
        denom=np.sum((v-v.mean())**2)
        r2=float(1-np.sum((v-(slope*x+intercept))**2)/denom) if denom>0 else None
        alpha=float(np.polyfit(np.log(x),np.log(v),1)[0]) if np.all(v>0) else None
        return {'slope_nm2_ps':float(slope),'r_squared':r2,'log_log_exponent':alpha}
    eh=fit(charge_msd);ne=fit(self_msd@(z*z))
    # e²/(6VkBT) * nm²/ps -> S/m, then /100 -> S/cm.
    factor=1.602176634e-19**2/(6*volume*1e-27*1.380649e-23*t)*1e-6/100
    sigma=eh['slope_nm2_ps']*factor;sigmane=ne['slope_nm2_ps']*factor
    return {**p,'status':'preliminary' if sigma>=0 and sigmane>0 else 'needs_longer_sampling',
      'origin':'trajectory_postprocessing','trajectory_path':str(path.resolve()),'trajectory_sha256':digest(path),
      'temperature_K':t,'volume_nm3':volume,'fit_window_ps':[start,end],
      'sigma_einstein_helfand_S_cm':sigma if sigma>=0 else None,
      'sigma_nernst_einstein_S_cm':sigmane if sigmane>0 else None,
      'ionicity_sigma_over_NE':sigma/sigmane if sigmane>0 and sigma>=0 else None,
      'collective_fit':eh,'self_sum_fit':ne,
      'carrier_diffusion_m2_s':[fit(self_msd[:,i])['slope_nm2_ps']/6*1e-6 for i in range(len(z))],
      'lag_ps':lagtime.tolist(),'collective_charge_msd_e2_nm2':charge_msd.tolist(),
      'limitations':['Single-trajectory estimate; no independent uncertainty or convergence certification.',
        'Fit-window sensitivity and independent replicas must be checked.',
        'Requires constant volume and correct unwrapped charge-carrier centers; input assertions are not independently verified.',
        'No quantum chemistry, force-field construction or new MD simulation was executed.']}
