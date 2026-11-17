"""Read real archives/legacy rows and reanalyse an existing real OpenMM trajectory."""
import json
from datetime import datetime
from pathlib import Path
import numpy as np
from spark_harness import SparkHarness,ROOT
from conductivity_completion import digest

if __name__=='__main__':
    output=ROOT/'outputs'/('conductivity_completion_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    output.mkdir(parents=True)
    h=SparkHarness(output/'execution',project_id='conductivity-completion')
    replies={}
    def call(key,name,**kw):
        reply=h.execute(name,kw);replies[key]=reply
        if reply['status']!='ok':raise RuntimeError(reply)
        return reply['data']
    c=call('candidates','spark_candidates',seed=20260814,query='polymethylhydrosiloxane',limit=50)
    target=next(x for x in c['payload']['rows'] if x['names']==['polymethylhydrosiloxane','imidazolium','tfsi'])
    archive=call('archive','lookup_spark_conductivity',candidate_id=target['candidate_id'])
    call('legacy_case','search_legacy_conductivity',query='three dimensional metal organic framework cellulose',limit=10)
    call('legacy_known','search_legacy_conductivity',query='engineered interfaces hybrid ceramic',limit=2)
    call('eis_fixture','conductivity_from_resistance',sample='synthetic EIS geometry example',source='test_fixture: 100 um, 1 cm2, 100 ohm; not a paper measurement',thickness_um=100,area_cm2=1,resistance_ohm=100,temperature_K=298.15,resistance_kind='electrolyte_bulk')
    original=ROOT.parent/'spe_agentic_harness/outputs/diffusion_real_20261110_154803_725835/openmm_67128efc7867/trajectory.npz'
    if original.exists():
        with np.load(original,allow_pickle=False) as d:
            mask=np.isin(d['symbols'],['Li','Cl']);z=np.where(d['symbols'][mask]=='Li',1,-1)
            np.savez_compressed(output/'licl_carriers.npz',positions_nm=d['positions_nm'][:,mask,:],time_ps=d['time_ps'],charge_numbers=z,volume_nm3=abs(np.linalg.det(d['box_nm'])))
        (output/'trajectory_provenance.json').write_text(json.dumps({'source':str(original),'source_sha256':digest(original),'conversion':'Select Li/Cl ions; integer charges +1/-1; neutral water excluded from DC carrier transport. Fixed-volume continuous coordinates from original OpenMM run.','system':'aqueous LiCl, NOT polymer electrolyte'},indent=2),encoding='utf-8')
        for lo,hi in [(10,40),(20,50)]:
            call(f'md_{lo}_{hi}','conductivity_from_trajectory',trajectory_path=str(output/'licl_carriers.npz'),sample='aqueous LiCl benchmark, existing 100 ps trajectory',source=str(output/'trajectory_provenance.json'),temperature_K=300,fit_start_ps=lo,fit_end_ps=hi,unwrapped=True,complete_charge_carriers=True)
    recovered=call('memory','get_simulation_record',record_id=archive['record_id'])
    (output/'results.json').write_text(json.dumps(replies,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(output))
    print(json.dumps({'archive_sigma':[r['diagnostic_sigma_S_cm'] for r in archive['results']],
        'legacy_case_matches':replies['legacy_case']['data']['matched_rows'],
        'md':{k:{j:r['data'][j] for j in ['sigma_einstein_helfand_S_cm','sigma_nernst_einstein_S_cm','ionicity_sigma_over_NE']} for k,r in replies.items() if k.startswith('md_')},
        'all_tool_calls_ok':all(r['status']=='ok' for r in replies.values())},ensure_ascii=False,indent=2))
