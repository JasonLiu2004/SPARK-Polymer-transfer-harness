import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'outputs/extended_20261117'
IDS=['01f8f3e0d373704403c1','2c164ba1ac3b05bc07bf','420e5f8879323faa1d69','45e48db5a47f1f7224f8','863525dc14cd4aee4512','a960f2b17f878759fe7a','c8a47e4e1c146580c216','ce3f9d196cf9f55c2fed','e3cc9b5cd89b531f1cfd','e6f79b7938bd921c8aeb','f461b312250cd398c9ff','5858d6516e63be19dd5d','1658c64f0b7de8021cc7','250e816b9630159cfd6d','2c16c9817c7ae68d4a56','2ca5161375704e79102a','911110d21b8dad78b6bf','98f2a46097bc4c03ee52','a269669c794d44138303','eea853119c5e41dc0cb8']
if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    src=ROOT/'outputs/application_20261117_125231/joined_records.json'
    data={p['id']:p for p in json.loads(src.read_text(encoding='utf-8'))}
    prior={p['paper_id'] for p in json.loads((ROOT/'outputs/batch10_20261117/cases.json').read_text(encoding='utf-8'))}
    assert len(set(IDS))==20 and not set(IDS)&prior
    papers=[{k:data[pid].get(k) for k in ['id','title','abstract','year','doi']} for pid in IDS]
    (OUT/'catalog.json').write_text(json.dumps(papers,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps({'n':20,'ids':IDS,'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),
      'selection':'purposive boundary cases with conductivity/energy/temperature evidence; not random benchmark',
      'evaluation':'pipeline completion, evidence checks and supported numeric conclusions; no claim of property prediction accuracy',
      'comparison':'same abstract, same model, same output schema; direct single call vs multi-call harness; not cost matched'},indent=2),encoding='utf-8')
    print('Frozen 20 new papers')
