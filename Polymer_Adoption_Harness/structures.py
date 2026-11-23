"""Constitutional-repeat design vocabulary. Material instances are created only from our dated papers."""
from dataclasses import dataclass
import re
import unicodedata

def normalized(name):
    value=unicodedata.normalize("NFKC",name).casefold().strip()
    return " ".join(re.sub(r"[‐‑–—−]","-",value).split())


def spelling(name):
    return re.sub(r"[\s()-]+","",normalized(name))


@dataclass(frozen=True)
class Repeat:
    name:str
    smiles:str
    aliases:tuple=()


def vocabulary():
    simple=[
        ("polyethylene oxide","[R]CCO[Q]",("PEO","polyoxyethylene")),
        ("polyethylene glycol","[R]CCO[Q]",("PEG",)),
        ("polypropylene oxide","[R]CC(C)O[Q]",("polyoxypropylene",)),
        ("polytetrahydrofuran","[R]CCCCO[Q]",("polytetramethylene oxide","poly(tetramethylene ether glycol)")),
        ("polyethylene carbonate","[R]OCCOC(=O)[Q]",()),
        ("polypropylene carbonate","[R]OCC(C)OC(=O)[Q]",()),
        ("polytrimethylene carbonate","[R]OCCCOC(=O)[Q]",("PTMC",)),
        ("polyethylene","[R]CC[Q]",()),("polypropylene","[R]CC(C)[Q]",()),
        ("polyisobutylene","[R]CC(C)(C)[Q]",("polyisobutene",)),
        ("polystyrene","[R]CC(c1ccccc1)[Q]",()),
        ("polyvinyl alcohol","[R]CC(O)[Q]",("PVA",)),
        ("polyvinyl acetate","[R]CC(OC(=O)C)[Q]",("PVAc",)),
        ("polyvinyl chloride","[R]CC(Cl)[Q]",("PVC",)),
        ("polyvinyl fluoride","[R]CC(F)[Q]",()),
        ("polyvinylidene fluoride","[R]CC(F)(F)[Q]",("PVDF","polyvinylidene difluoride")),
        ("polytetrafluoroethylene","[R]C(F)(F)C(F)(F)[Q]",("PTFE",)),
        ("polyacrylonitrile","[R]CC(C#N)[Q]",("PAN",)),
        ("polyacrylamide","[R]CC(C(=O)N)[Q]",("PAM",)),
        ("polyacrylic acid","[R]CC(C(=O)O)[Q]",("PAA",)),
        ("polymethacrylic acid","[R]CC(C)(C(=O)O)[Q]",()),
        ("polyvinylpyrrolidone","[R]CC(N1CCCC1=O)[Q]",("PVP","poly(N-vinyl-2-pyrrolidone)","poly(vinyl pyrrolidone)","poly(N-vinylpyrrolidone)")),
        ("poly(N-isopropylacrylamide)","[R]CC(C(=O)NC(C)C)[Q]",("PNIPAM","PNIPAAm")),
        ("poly(N,N-dimethylacrylamide)","[R]CC(C(=O)N(C)C)[Q]",()),
        ("poly(2-vinylpyridine)","[R]CC(c1ccccn1)[Q]",("P2VP",)),
        ("poly(4-vinylpyridine)","[R]CC(c1ccncc1)[Q]",("P4VP",)),
        ("poly(ethylene terephthalate)","[R]OCCOC(=O)c1ccc(C(=O)[Q])cc1",("PET",)),
        ("poly(butylene terephthalate)","[R]OCCCCOC(=O)c1ccc(C(=O)[Q])cc1",("PBT",)),
        ("poly(ethylene succinate)","[R]OCCOC(=O)CCC(=O)[Q]",()),
        ("poly(butylene succinate)","[R]OCCCCOC(=O)CCC(=O)[Q]",()),
        ("polycaprolactone","[R]OCCCCCC(=O)[Q]",("poly(epsilon-caprolactone)","poly(ε-caprolactone)","PCL")),
        ("poly(lactic acid)","[R]OC(C)C(=O)[Q]",("polylactide","PLA")),
        ("poly(glycolic acid)","[R]OCC(=O)[Q]",("polyglycolide",)),
        ("polyamide 6","[R]NCCCCCC(=O)[Q]",("nylon 6","nylon-6","polycaprolactam")),
        ("polyamide 66","[R]NCCCCCCNC(=O)CCCCC(=O)[Q]",("nylon 66","nylon-6,6","polyamide 6,6")),
        ("polydimethylsiloxane","[R][Si](C)(C)O[Q]",("PDMS",)),
        ("poly(1,3-dioxolane)","[R]OCOCC[Q]",()),
        ("polyoxymethylene","[R]CO[Q]",("polyformaldehyde",)),
        ("linear polyethyleneimine","[R]CCN[Q]",("linear poly(ethylene imine)",)),
    ]
    # Unbranched or explicitly specified ester substituents. PEG side-chain length, blends
    # and random/graft compositions cannot be inferred by stripping a name suffix.
    for ester,side in (("methyl","C"),("ethyl","CC"),("n-propyl","CCC"),("n-butyl","CCCC"),
                      ("tert-butyl","C(C)(C)C"),("benzyl","Cc1ccccc1"),("2-hydroxyethyl","CCO"),
                      ("2-methoxyethyl","CCOC"),("2-ethylhexyl","CC(CC)CCCC")):
        for cls,sub in (("acrylate",""),("methacrylate","(C)")):
            name=f"poly({ester} {cls})"
            alias={("methyl","methacrylate"):("PMMA",),("2-hydroxyethyl","methacrylate"):("PHEMA",)}.get((ester,cls),())
            simple.append((name,"[R]CC"+sub+"(C(=O)O"+side+")[Q]",alias))
    result={};lookup={}
    for n,s,a in simple:
        result[n]=Repeat(n,s,a)
        for alias in (n,*a):
            key=spelling(alias)
            if key in lookup and lookup[key]!=n:raise ValueError("Ambiguous repeat alias "+alias)
            lookup[key]=n
    return result,lookup


REPEATS,ALIASES=vocabulary()


def identity(name,segments):
    key=spelling(name)
    if key not in ALIASES:
        return normalized(name)
    candidate=ALIASES[key]
    # A bare abbreviation needs its expansion in the same publication.
    if re.fullmatch(r"[A-Za-z0-9]{2,7}",name.strip()) and name.strip().upper()==name.strip():
        long=[a for a in (candidate,*REPEATS[candidate].aliases) if len(a)>7]
        context=spelling(" ".join(segments.values()))
        if not any(spelling(a) in context for a in long):
            return "unresolved abbreviation "+name.strip()
    return candidate
