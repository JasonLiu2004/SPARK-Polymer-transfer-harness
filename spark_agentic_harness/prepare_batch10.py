"""Freeze ten distinct, purposively selected literature cases; no benchmark labels."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'outputs/batch10_20261117'
SOURCE=ROOT/'outputs/application_20261117_125231/joined_records.json'
# Human/assistant curated input, not automatic LLM extraction. All evidence spans
# are verified against the immutable local abstract before writing the manifest.
CASES=[
 ('ff514c566fb4964d9b84','点击交联 SIPE',1.78e-4,303.15,.21,None,
  ['1.78 x 10-4 S cm- 1 at 30 degrees C','low activation energy (0.21 eV)']),
 ('0c15f21851644ce5e3ee','PEO / LiTDI / POSS-PEG',2.23e-5,296.15,.295,None,
  ['2.23 x 10(-5) S/cm','at room temperature 23 degrees C','activation energy decreased to 0.295 eV']),
 ('4e40d7c7059555d39240','PAN / LiClO₄ / GO',4e-4,303.15,1.03,None,
  ['1.0 wt% GO has reached 4.0 x 10(-4) S CM-1 at 30 degrees C','activation energy has reduced from 2.31 to 1.03 eV']),
 ('504c391074bc8deb2697','PVDF / ZIF-90',6.2e-4,303.15,.20,None,
  ['0.62 mS cm(-1) at 30 degrees C','low activation energy of 0.20 eV']),
 ('7fd2d7a1e798a4850cfb','三维陶瓷网络 / PEO',3.5e-5,293.15,.43,None,
  ['ionic conductivity of 3.5 x 10(-5) S/cm at 20 degrees C with an activation energy of 0.43 eV']),
 ('89b160e31cce43bbc029','弛豫铁电三元聚合物',3.10e-4,298.15,.26,None,
  ['3.10 x 10(-4) S cm(-1) at 25 degrees C and lower activation energy (0.26 eV)']),
 ('1eeb9931912c619e5d3a','LLZO / PVDF',1.2e-4,None,.247,'reference_temperature_unspecified',
  ['ionic conductivity at room temperature (0.12 mS/cm)','lowest activation energy (0.247 eV)']),
 ('5033b4f8c6cfec0e857b','PGMA / LiTFSI',1.23e-4,373,None,'vtf_parameters_not_arrhenius',
  ['1.23 x 10(-4) S cm(-1) at 373 K','Vogel-Tamman-Fulcher equation with an activation energy of 0.054 eV']),
 ('30051bed899dc379248b','PEO / 羟基磷灰石',6.4e-5,303.15,None,'dissociation_energy_not_activation_energy',
  ['dissociation energy of -0.76 eV','ionic conductivity of 0.064 mS cm(-1) and a Li+ transference number of 0.366 at 30 degrees C']),
 ('6e9feff806525d4d6d8a','PEO / 硫化物填料',1.4e-3,343.15,None,'filler_activation_energy_not_composite',
  ['Li6.25PS5.25Cl0.75 with high conductivity of 1.0 mS cm(-1) and low activation energy of 0.14 eV at room temperature',
   'ionic conductivity of 1.4 mS cm(-1) at 70 degrees C for CPEs-1']),
]

def main():
    data={r['id']:r for r in json.loads(SOURCE.read_text(encoding='utf-8'))}
    cases=[];papers=[]
    for i,(pid,name,sigma,temp,ea,blocked,quotes) in enumerate(CASES,1):
        paper={k:data[pid].get(k) for k in ['id','title','abstract','year','doi']}
        assert all(q in paper['abstract'] for q in quotes),(pid,quotes)
        cases.append({'case_id':f'C{i:02}','paper_id':pid,'name':name,
                      'sigma_S_cm':sigma,'reference_temperature_K':temp,'Ea_eV':ea,
                      'blocking_reason':blocked,'quotes':quotes,'doi':paper['doi'],
                      'input_origin':'assistant_curated_abstract','source_sha256':hashlib.sha256(paper['abstract'].encode()).hexdigest()})
        papers.append(paper)
    OUT.mkdir(exist_ok=True,parents=True)
    (OUT/'catalog.json').write_text(json.dumps(papers,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps({'n':10,'selection':'purposive mechanism-coverage sample, not random accuracy benchmark',
       'source':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
       'new_papers':10,'target_temperature_K':298.15,'curation':'assistant source-span checked; not independent expert review'},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Frozen 10 distinct source-checked cases')

if __name__=='__main__':main()
