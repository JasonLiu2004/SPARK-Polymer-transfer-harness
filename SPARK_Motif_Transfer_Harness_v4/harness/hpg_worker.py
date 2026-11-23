"""One immutable checkpoint, the authors' graph encoder and normalization, no web access."""
import contextlib
import json
import math
import os
import re
import sys

from .common import CHECKPOINT, HPG_SHA, file_hash, finite, packed


def require(condition,message):
    if not condition:
        raise ValueError(message)


def to_graphs(recipe, modules):
    chem, dgl, torch, Fragment, Node, PolymerGraph, pol_graph, mol_graph = modules
    comps = recipe["components"]
    require(isinstance(comps,list) and 1<=len(comps)<=6,"HPG supports one to six components")
    temp = recipe["temperature_c"]
    require(finite(temp) and temp > -273.15,"Invalid temperature in degrees Celsius")
    weights = [c["weight_fraction"] for c in comps]
    require(all(finite(w) and 0<w<=1 for w in weights) and abs(sum(weights)-1)<=1e-6,"Mass fractions must sum to one")
    require(any(c["kind"]=="polymer" for c in comps),"Missing polymer")
    graphs = []
    for comp in comps:
        if comp["kind"]=="molecule":
            smiles = comp["smiles"]
            require(isinstance(smiles,str) and bool(smiles) and chem.MolFromSmiles(smiles) is not None,"Invalid molecular SMILES")
            graphs.append(mol_graph(smiles))
            continue
        require(comp["kind"]=="polymer","Unknown component kind")
        fragments = comp["nodes"]
        names = [f["name"] for f in fragments]
        require(names and len(set(names))==len(names) and all(n and "." not in n for n in names),"Invalid fragment names")
        sites,used,nodes = {},set(),[]
        from rdkit.Chem import Descriptors, rdMolDescriptors
        approx_mass = 0
        for f in fragments:
            name,smi = f["name"],f["smiles"]
            markers = re.findall(r"\[([RQTU])\]",smi)
            require(markers and len(markers)==len(set(markers)),"Each attachment symbol must occur once per fragment")
            sites[name] = set(markers)
            dummy = smi
            for i,k in enumerate("RQTU",1):
                dummy = dummy.replace("["+k+"]",f"[*:{i}]")
            mol = chem.MolFromSmiles(dummy)
            require(mol is not None and len(chem.GetMolFrags(mol))==1,"Invalid or disconnected repeat")
            require(all(a.GetDegree()==1 for a in mol.GetAtoms() if a.GetAtomicNum()==0),"Invalid attachment atom")
            if recipe["origin"]=="designed_reference":
                require(all(a.GetFormalCharge()==0 for a in mol.GetAtoms()),"Charged repeats require an explicit balanced formulation")
                formula = recipe["source"].get("formula")
                if formula:
                    observed = re.sub(r"\*\d*","",rdMolDescriptors.CalcMolFormula(mol))
                    require(observed==formula,"Repeat formula disagrees with the structure registry")
            for port,value in f["connections"].items():
                require(isinstance(value,(tuple,list)) and len(value)==2 and finite(value[1]) and value[1]>0,
                        "Connections need a positive multiplicity")
                dest,other = value[0].rsplit(".",1)
                require((name,port)!=(dest,other) and (name,port) not in used and (dest,other) not in used,
                        "Attachment sites must have a single partner")
                used.update([(name,port),(dest,other)])
            approx_mass += Descriptors.MolWt(mol)
            nodes.append(Node(Fragment(name,smi),f["connections"]))
        require(used=={(n,s) for n,ss in sites.items() for s in ss},"Connections must cover exactly the named attachment sites")
        # The vendor's hierarchical encoder uses nodes and connections. MW is optional bookkeeping.
        mw = comp.get("mw_g_mol",approx_mass)
        require(finite(mw) and mw>0,"Invalid polymer mass")
        graphs.append(pol_graph(PolymerGraph(comp["name"],nodes,MW=mw)))
    graphs.extend(mol_graph("C") for _ in range(6-len(graphs)))
    require(all(torch.isfinite(g.ndata["h"]).all() and torch.isfinite(g.edata["e"]).all() for g in graphs),
            "Nonfinite graph features")
    ratios = torch.tensor([weights+[0.]*(6-len(weights))],dtype=torch.float32)
    temperature = torch.tensor([[(temp-33.923080)/40.216135]],dtype=torch.float32)
    return [*[dgl.batch([g]) for g in graphs],ratios,temperature]


def main():
    if os.name=="nt":
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(3)
    if os.getenv("HPG_EXTRA_PATH"):
        sys.path.insert(0,os.environ["HPG_EXTRA_PATH"])
    require(file_hash(CHECKPOINT)==HPG_SHA,"Unexpected HPG checkpoint digest")
    recipes = json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        import dgl
        import torch
        from rdkit import Chem
        from .hpg_vendor.polyG import Fragment, Node, PolymerGraph
        from .hpg_vendor.hpggat import GATNet
        from .hpg_vendor.mol2graph import pol2hig_mk2, mon2hig_mk2
        model = GATNet()
        model.load_state_dict(torch.load(CHECKPOINT,map_location="cpu",weights_only=True))
        model.eval()
        modules = (Chem,dgl,torch,Fragment,Node,PolymerGraph,pol2hig_mk2,mon2hig_mk2)
        results = {}
        for r in recipes:
            base = {"recipe_id":r["recipe_id"],"sample":r["sample"],"origin":r["origin"],
                    "checkpoint_sha256":HPG_SHA,"temperature_c":r["temperature_c"]}
            try:
                inputs = to_graphs(r,modules)
            except (ValueError,TypeError,IndexError,KeyError) as exc:
                results[r["recipe_id"]] = {**base,"status":"unsupported_structure","reason":str(exc)}
                continue
            except Exception as exc:
                if "not in allowable set" not in str(exc):
                    raise
                results[r["recipe_id"]] = {**base,"status":"unsupported_structure","reason":str(exc)}
                continue
            with torch.inference_mode():
                lg = float(model(inputs).item())*1.836202-3.981499
            require(math.isfinite(lg) and -320 < lg < 308,"Nonfinite HPG conductivity")
            results[r["recipe_id"]] = {**base,"status":"predicted","log10_sigma_S_cm":lg,"sigma_S_cm":10**lg,
                    "observable":"total ionic conductivity of the specified formulation","unit":"S/cm","source":"HPG-GAT"}
    sys.stdout.write(packed(results))


if __name__=="__main__":
    main()
