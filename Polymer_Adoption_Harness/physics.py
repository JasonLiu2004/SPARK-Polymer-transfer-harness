"""Public HPG checkpoint, inference cache and as-of material/recipe provenance."""
import json
import math
import os
import subprocess
import sys
from common import DATA,ROOT,V4,WORK,file_hash,fingerprint,packed,seal,verified,writer
from structures import REPEATS

CHECKPOINT_SHA="0f859f11015f77ab9d49a0807db24f6e1c31c5c3b4be47b01d8bda7b53bf6f38"
PUBLIC=WORK/"spark_agentic_harness/external_conductivity/HPG"
GRID=((10,20,30),(25,60))
SALT="O=S([N-]S(=O)(C(F)(F)F)=O)(C(F)(F)F)=O"
DEFAULT_THRESHOLD=1e-4


def design(r,pct,temp):
    # The public encoder represents LiTFSI by the anion graph, but the mass fraction
    # is that of the full salt. Degree of polymerisation here is a design assumption.
    item={"origin":"designed_reference","material":r.name,"source":{"basis":"ideal neutral constitutional repeat"},
        "sample":"dry polymer / LiTFSI design","temperature_c":temp,"components":[
        {"kind":"polymer","name":r.name,"weight_fraction":1-pct/100,
         "nodes":[{"name":"repeat","smiles":r.smiles,"connections":{"R":["repeat.Q",100]}}]},
        {"kind":"molecule","name":"LiTFSI","weight_fraction":pct/100,"smiles":SALT}]}
    return {**item,"recipe_id":"form_"+fingerprint(item)[:24]}


def prepare():
    path=DATA/"physics"/"grid.json"
    for p in (PUBLIC/"ckpt/HPG_GAT.bin",V4/"harness/hpg_vendor/HPG_GAT.bin"):
        if file_hash(p)!=CHECKPOINT_SHA:raise ValueError("Public HPG checkpoint mismatch")
    recipes=[(r,p,t,design(r,p,t)) for r in REPEATS.values() for p in GRID[0] for t in GRID[1]]
    contract=fingerprint([CHECKPOINT_SHA,file_hash(V4/"harness/hpg_worker.py"),[v for *_,v in recipes]])
    with writer(DATA/"physics"):
        if path.exists():
            cached=verified(path)
            if cached["contract"]!=contract:raise ValueError("Changed HPG conditions or inputs")
            return cached
        env=dict(os.environ);env.pop("LLM_API_KEY",None)
        env.update(HPG_EXTRA_PATH=str(PUBLIC.parent/".deps"),PYTHONIOENCODING="utf-8",DGLBACKEND="pytorch",
                   MPLBACKEND="Agg",PYTHONDONTWRITEBYTECODE="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
        proc=subprocess.run([sys.executable,"-B","-m","harness.hpg_worker"],cwd=V4,env=env,
            input=packed([v for *_,v in recipes]),text=True,encoding="utf-8",capture_output=True,timeout=900)
        if proc.returncode:raise RuntimeError("HPG worker failed: "+proc.stderr[-1200:])
        all_results=json.loads(proc.stdout)
        if set(all_results)!={r["recipe_id"] for *_,r in recipes}:raise ValueError("Incomplete HPG grid")
        output={}
        for r,p,t,form in recipes:
            v=all_results[form["recipe_id"]]
            if v["checkpoint_sha256"]!=CHECKPOINT_SHA:raise ValueError("HPG result checkpoint mismatch")
            row={"recipe":form["recipe_id"],"material":r.name,"repeat":r.smiles,"salt":"LiTFSI",
                 "salt_wt_pct":p,"temperature_C":t,"DP":100,"status":v["status"],"checkpoint":CHECKPOINT_SHA}
            if v["status"]=="predicted":
                if not math.isfinite(v["sigma_S_cm"]) or v["sigma_S_cm"]<=0:
                    raise ValueError("Nonphysical HPG output")
                row.update(sigma_S_cm=v["sigma_S_cm"],log10_S_cm=v["log10_sigma_S_cm"])
            else:row["reason"]=v.get("reason","unsupported structure")
            output.setdefault(r.name,[]).append(row)
        return seal(path,{"contract":contract,"checkpoint":CHECKPOINT_SHA,"source":"https://github.com/spark8ku/HPG",
            "model_time_scope":"Published modern checkpoint; use in historical windows is retrospective.","designs":output})


def dated_predictions(panel,grid,year):
    out={}
    for k,r in panel.items():
        if k not in grid["designs"]:continue
        source=min(r["sources"],key=lambda p:(p["year"],p["doi"]))
        if source["year"]>year:raise ValueError("Future material structure")
        out[k]=[{**d,"source_doi":source["doi"],"source_year":source["year"]} for d in grid["designs"][k]]
    return out


if __name__=="__main__":
    g=prepare()
    print("Independent HPG template grid",sum(map(len,g["designs"].values())),"designs",flush=True)
