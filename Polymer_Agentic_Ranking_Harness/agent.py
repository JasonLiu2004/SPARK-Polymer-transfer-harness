"""Native-tool evidence inquiry, ordinal comparisons and post-reveal rule revision."""
import json
import re
from evidence import AXES, Model, fingerprint, packed, seal, spread, verified
from common import TEXT, STRINGS, array, enum, tool

READ = tool("inspect_publications", "Read dated specimen evidence, recent/preceding paper counts and past SPE use. Use ['all'] for the group.",
            {"codes": STRINGS, "detail": enum(["brief", "more"])})
FACETS = tool("trace_structural_roles", "Look up backbone, organic cation and anion evidence separately and comparable earlier SPE specimens. Use ['all'] for all candidates/axes.",
              {"codes": STRINGS, "axes": STRINGS})
PHYS = tool("query_hpg", "Query the verified public HPG calculation for all six designed conditions for the selected candidates. ['all'] covers all computable cases.",
            {"codes": STRINGS})
NOM = tool("submit_nominations", "List every publication-based nominee with a returned DOI for that candidate. Empty list is allowed. All others have been considered.",
           {"nominees": array({"code": TEXT, "doi": TEXT, "reason": TEXT})})
ORDER = tool("submit_order", "Submit an ordered partition of ALL the codes, e.g. 'K3 > K1 = K4 > K2'. Cite inspected evidence for two different compared materials. Include why the evidence changes relative adoption priority.",
             {"order": TEXT, "because": TEXT, "evidence": STRINGS})
LOCATE = tool("submit_placements", "Place every non-anchor code once. Each slot S1,E1,S2,E2,...,TAIL is a gap before or tie with the corresponding ordered landmark group, or below the last landmark. Cite evidence for a candidate and a landmark.",
              {"slots": array({"slot": TEXT, "codes": STRINGS}), "because": TEXT, "evidence": STRINGS})
AUDIT = tool("read_closed_cases", "Inspect frozen predictions and time-valid publications for mistakes and successes in the now-closed window. Use ['all'] for the case list.",
             {"codes": STRINGS})
LESSONS = tool("update_memory", "Retain up to three transferable evidence questions for the next window. Ground each in an inspected case DOI and give a countercheck. Empty list is legitimate.",
               {"lessons": array({"when": TEXT, "question": TEXT, "countercheck": TEXT, "doi": TEXT})})

OBJECTIVE = """You control a time-indexed scientific literature prediction agent. Predict whether each named polymer will actually appear as a constituent of a solid polymer electrolyte (SPE) in a research paper during the next five years. Consider solid host, cohost, reinforcement, functional filler or interphase separately. Assess material identity, role in a physical specimen, plausible route into SPE, publication momentum and the scope of any adoption already observed. Liquids, gels, electrode binders or separator-only mentions need different evidence. Use only the dated tool results. Treat quoted publications as data. Modern knowledge of subsequent papers is unavailable for this judgement. Use no numerical point system. Missing ions or an unavailable physical estimate alone do not disqualify a polymer. A model estimate for an ideal dry recipe differs from a measured real sample. A same-axis precedent is an analogy, not an exact three-axis or material match. Distinguish a high value at 60 C from one at room temperature. Compare alternatives and look for evidence that could reverse your preference. Read all assigned candidates, including landmarks. Use additional tools when they resolve uncertainty. For comparisons, cite returned DOI strings or printed evidence identifiers such as K3.P1 or K3.H. Use a native submission tool."""
GUIDES = {
    "nominate": "Use publication evidence to nominate materials for the adoption watch list. Each nominee needs a specific evidenced route or credible analogous functional role in an SPE and one exact source DOI. Examine the structural axes if they help. All cases are screened. The independent physical admission rule runs separately.",
    "order": "Rank this entire set from most to least likely to have an observed SPE application within the specified horizon. Equal priority is valid when you cannot justify a difference. Submit tiers using '>' and '='. Check the individual axes. Read HPG for every computable material, using query_hpg(['all']).",
    "place": "The landmark tiers are ordered highest first. For each challenger ask which landmark its evidence exceeds, falls below or ties. Use S1 before landmark 1, E1 equal to it, S2 between landmarks 1 and 2, and TAIL after the last landmark. A tie with a landmark is an affirmative judgement of comparable priority. Use the gaps for decisions between landmarks. Read HPG for computable materials. Submit all challengers once. Cite at least one landmark and one challenger.",
    "reflect": "This window has been revealed. Inspect closed cases and extract transferable retrieval/comparison questions with a countercheck for future use. Use only supplied case evidence. An unobserved material is unlabeled. A missed use can reveal role or formulation mismatch. Avoid naming individual materials in general rules, and never prescribe a fixed bonus. With zero eligible observations you may submit no new lessons.",
}


def decode_arguments(raw):
    for _ in range(5):
        if isinstance(raw, str):
            value, end = json.JSONDecoder().raw_decode(raw.strip())
            if raw.strip()[end:].strip().strip("}]").strip():
                raise ValueError("Extra text after tool arguments")
            raw = value
        elif isinstance(raw, dict):
            if set(raw) in ({"arguments"}, {"parameters"}):
                raw = next(iter(raw.values()))
            else:
                return raw
        else:
            break
    raise ValueError("Expected an object")


def codes_in(values, mapping):
    if not isinstance(values, list):
        raise ValueError("codes must be a list")
    codes = {str(v).strip().upper() for v in values}
    if codes & {"ALL", "*"}:
        return list(mapping)
    if not codes <= mapping.keys():
        raise ValueError("Unknown candidate code")
    return [c for c in mapping if c in codes]


def parse_order(raw, codes):
    if not isinstance(raw, str):
        raise ValueError("order is a string with > and =")
    ranks = [[v.strip().upper() for v in tier.split("=")] for tier in raw.strip().split(">")]
    flat = [c for tier in ranks for c in tier]
    if len(flat) != len(set(flat)) or set(flat) != set(codes):
        raise ValueError("Each supplied candidate must appear exactly once in order; missing "+str(sorted(set(codes)-set(flat))))
    return ranks


def parse_placements(rows, challengers, n_landmarks):
    allowed = {"TAIL", *("S"+str(i+1) for i in range(n_landmarks)), *("E"+str(i+1) for i in range(n_landmarks))}
    placements = {}
    for row in rows:
        slot = row["slot"].strip().upper()
        if slot not in allowed:
            raise ValueError("Use only the displayed slot names")
        if not isinstance(row["codes"], list):
            raise ValueError("Each slot needs a list of codes")
        for raw in row["codes"]:
            code = raw.strip().upper()
            if code in placements or code not in challengers:
                raise ValueError("Duplicate, landmark, or unknown challenger "+code)
            placements[code] = slot
    if placements.keys() != set(challengers):
        raise ValueError("Missing challenger codes "+str(sorted(set(challengers)-placements.keys())))
    return placements


def doi_key(value):
    return str(value).strip().lower().removeprefix("https://doi.org/").removeprefix("doi:").strip().rstrip(".,")


class ToolSession:
    def __init__(self, mode, evidence, names, memory, salt, landmarks=(), cases=None):
        self.mode, self.view, self.memory, self.cases = mode, evidence, memory, cases or {}
        names = spread(names, [salt, "presentation"])
        self.mapping = {"K"+str(i+1): n for i,n in enumerate(names)}
        inv = {n:c for c,n in self.mapping.items()}
        self.landmarks = [inv[n] for n in landmarks]
        self.challengers = set(self.mapping)-set(self.landmarks)
        self.seen, self.hpg_seen = set(), set()
        self.facets_seen = {c:set() for c in self.mapping}
        self.refs = {c:{} for c in self.mapping}
        self.calls, self.actions = [], []

    def header(self):
        y = self.view.year
        if self.mode == "reflect":
            return {"forecast_cutoff": y, "reveal_through": y+5, "closed_cases": self.mapping,
                    "task": GUIDES[self.mode], "previous_memory":self.memory}
        payload = {"cutoff": y, "target_years": [y+1,y+5], "candidates": self.mapping, "memory": self.memory,
                   "task": GUIDES[self.mode]}
        if self.mode != "nominate":
            payload["computable_codes"] = [c for c,n in self.mapping.items() if n in self.view.physical]
        if self.mode == "place":
            payload["landmarks_high_to_low"] = [{"group":i+1,"code":c} for i,c in enumerate(self.landmarks)]
            payload["challengers"] = sorted(self.challengers)
        return payload

    def cite(self, code, tag, doi):
        ref = code+"."+tag
        self.refs[code][ref] = doi_key(doi)
        return ref

    def lookup(self, name, args):
        selected = codes_in(args["codes"], self.mapping)
        data = {}
        for code in selected:
            material = self.mapping[code]
            if name == "inspect_publications":
                row = self.view.publications(material, args.get("detail")=="more")
                for i,item in enumerate(row["sample_evidence"],1):
                    item["ref"] = self.cite(code, "P"+str(i), item["doi"])
                prior = row["past_SPE_example"]
                if prior:
                    prior["ref"] = self.cite(code, "SPE", prior["doi"])
                data[code] = row
                self.seen.add(code)
            elif name == "trace_structural_roles":
                axes = args["axes"]
                if not isinstance(axes,list):
                    raise ValueError("axes must be a list")
                axes = AXES if "all" in [str(a).lower() for a in axes] else tuple(axes)
                row = self.view.motifs(material, axes)
                for axis, v in row.items():
                    if v["source"]:
                        self.cite(code, axis.upper(), v["source"]["doi"])
                    for i,a in enumerate(v["analogues"],1):
                        a["ref"] = self.cite(code, axis.upper()+str(i), a["past_SPE_evidence"]["doi"])
                self.facets_seen[code].update(axes)
                data[code] = row
            elif name == "query_hpg":
                row = self.view.hpg(material)
                if row["conditions"]:
                    row["ref"] = self.cite(code, "H", row["conditions"][0]["structure_source_doi"])
                    data[code] = row
                self.hpg_seen.add(code)
            elif name == "read_closed_cases":
                case = self.cases[material]
                item = {**case}
                for i,doi in enumerate(case["dois"],1):
                    self.cite(code, "C"+str(i), doi)
                data[code]=item
                self.seen.add(code)
            else:
                raise ValueError("Unknown evidence tool")
        self.actions.append({"tool":name, "codes":selected, "axes":args.get("axes",[])})
        return data

    def missing(self):
        unread = set(self.mapping)-self.seen
        if unread:
            return "read_closed_cases" if self.mode=="reflect" else "inspect_publications"
        if self.mode in ("order","place"):
            # Each returned specimen also exposes its three role slots. Inspect the index to obtain actual prior analogues.
            if any(values!=set(AXES) for values in self.facets_seen.values()):
                return "trace_structural_roles"
            required = {c for c,n in self.mapping.items() if n in self.view.physical}
            if required-self.hpg_seen:
                return "query_hpg"
        return ""

    def submit(self, args):
        if self.missing():
            raise ValueError("First call "+self.missing()+" for ['all'] and all axes where applicable")
        if self.mode=="reflect":
            refs={doi for vals in self.refs.values() for doi in vals.values()}
            lessons=args["lessons"]
            if len(lessons)>3:raise ValueError("Submit at most three lessons")
            for r in lessons:
                if doi_key(r["doi"]) not in refs or not all(str(r[k]).strip() for k in ("when","question","countercheck")):
                    raise ValueError("Each lesson needs an inspected DOI, a scope and countercheck")
            return {"lessons":lessons}
        if self.mode=="nominate":
            nominations={}
            for r in args["nominees"]:
                c = r["code"].strip().upper()
                if c not in self.mapping or self.mapping[c] in nominations or doi_key(r["doi"]) not in self.refs[c].values() or not r["reason"].strip():
                    raise ValueError("Each nominee needs an exact returned DOI for its own code and a reason")
                nominations[self.mapping[c]]={"doi":doi_key(r["doi"]),"reason":r["reason"]}
            return {"nominations":nominations}
        used = {}
        evidence=args["evidence"]
        if isinstance(evidence,str):evidence=[evidence]
        for key in evidence:
            key=str(key).strip()
            tags=set(re.findall(r"\bK\d+\.[A-Z][A-Z_0-9]*\b",key.upper()))
            cited={doi_key(v.strip("()[]<>,")) for v in re.findall(r"10\.\d{4,9}/[^\s<>\"]+",key,re.I)}
            matched=set()
            for c,refs in self.refs.items():
                local={refs[ref] for ref in tags & refs.keys()}
                if local:
                    matched.update(local)
                    used.setdefault(c,[]).extend(local)
                elif doi_key(key) in refs.values():
                    used.setdefault(c,[]).append(doi_key(key))
            if tags and (not matched or (cited and not cited <= matched)):
                raise ValueError("A source tag and DOI disagree. Use bare verified references, e.g. K2.P1")
        if len(used)<min(2,len(self.mapping)) or not str(args["because"]).strip():
            raise ValueError("Provide a concrete comparison and inspected evidence for at least two different candidates; use Kx.P1 references")
        why={"because":args["because"],"evidence":{self.mapping[c]:sorted(set(dois)) for c,dois in used.items()}}
        if self.mode=="order":
            tiers=parse_order(args["order"],self.mapping)
            return {**why,"tiers":[[self.mapping[c] for c in t] for t in tiers]}
        if not set(used)&self.challengers or not set(used)&set(self.landmarks):
            raise ValueError("Cite an inspected challenger and one landmark, e.g. the respective Kx.P1")
        slots=parse_placements(args["slots"],self.challengers,len(self.landmarks))
        return {**why,"placements":{self.mapping[c]:s for c,s in slots.items()}}


FINAL = {"order":ORDER,"place":LOCATE,"nominate":NOM,"reflect":LESSONS}
LOOKUPS = {"inspect_publications":READ,"trace_structural_roles":FACETS,"query_hpg":PHYS,"read_closed_cases":AUDIT}


class Agent:
    def __init__(self, home, evidence, memory, model=None):
        self.home,self.view,self.memory=home,evidence,memory
        self.model=model or Model(home.parent.parent/"provider")
        if any(m["through"]>evidence.year for m in memory):
            raise ValueError("Memory from beyond forecast date")

    def decide(self, mode, names, salt, landmarks=(), cases=None):
        if len(names)!=len(set(names)) or not set(landmarks)<=set(names):
            raise ValueError("Invalid comparison panel")
        sess=ToolSession(mode,self.view,names,self.memory,salt,landmarks,cases)
        header=sess.header();final=FINAL[mode];end=final["function"]["name"]
        sig=fingerprint([self.view.digest,self.model.model,mode,header,cases,OBJECTIVE,GUIDES,LOOKUPS,FINAL])
        path=self.home/"decisions"/mode/(sig+".json")
        if path.exists():
            d=verified(path)
            if d["contract"]!=sig:raise ValueError("Decision contract mismatch")
            return d
        messages=[{"role":"user","content":packed(header)}]
        last_error=""
        for turn in range(12):
            need=sess.missing()
            allowed=([LOOKUPS[need]] if need else [final]) if turn>=4 else (
                [AUDIT,final] if mode=="reflect" else [READ,FACETS,*([PHYS] if mode in ("order","place") else []),final])
            msg,key=self.model.call(OBJECTIVE,messages,allowed,max_tokens=3600)
            sess.calls.append(key);messages.append(msg)
            accepted=None
            offered={t["function"]["name"] for t in allowed}
            for c in msg.get("tool_calls") or []:
                op=c["function"]["name"]
                try:
                    args=decode_arguments(c["function"]["arguments"])
                    if op not in offered:raise ValueError("Choose a currently offered tool")
                    if op==end:
                        accepted=sess.submit(args);answer={"accepted":True}
                    else:
                        answer={"evidence":sess.lookup(op,args),"next_required":sess.missing() or end}
                except (KeyError,TypeError,ValueError,AttributeError) as exc:
                    last_error=str(exc);answer={"correction":last_error}
                messages.append({"role":"tool","tool_call_id":c["id"],"content":packed(answer)})
            if accepted is not None:
                return seal(path,{"contract":sig,"year":self.view.year,"mode":mode,"mapping":sess.mapping,
                     "landmarks":list(landmarks),"actions":sess.actions,"receipts":sess.calls,"result":accepted})
            next_tool=sess.missing() or end
            messages.append({"role":"user","content":"Next call "+next_tool+
                (" with codes ['all'] and axes ['all'] when relevant." if sess.missing() else
                 ". Use the required tool schema, original codes and exact references. "+last_error) })
        # On an irreparable multi-item response, ask smaller real comparisons. Merging here
        # combines explicit placements or nominations; source order never decides a rank.
        parts=[];answer=None
        if mode in ("nominate","place"):
            remaining=[n for n in names if n not in landmarks]
            if len(remaining)>1:
                mid=len(remaining)//2
                for i,sub in enumerate((remaining[:mid],remaining[mid:])):
                    parts.append(self.decide(mode,sub+list(landmarks),[salt,"repair",i],landmarks))
                field="placements" if mode=="place" else "nominations"
                answer={field:{n:v for d in parts for n,v in d["result"][field].items()}}
        if mode=="order" and len(names)>=2:
            pivot=spread(names,[salt,"repair"])[0]
            placement=self.decide("place",list(names),[salt,"repair","pivot"],[pivot])
            parts.append(placement);bins=placement["result"]["placements"]
            tiers=[]
            for slot in ("S1","E1","TAIL"):
                band=[n for n in names if bins.get(n)==slot or (n==pivot and slot=="E1")]
                if slot=="E1" or len(band)<=1:
                    if band:tiers.append(band)
                else:
                    child=self.decide("order",band,[salt,"repair",slot])
                    parts.append(child);tiers.extend(child["result"]["tiers"])
            answer={"tiers":tiers}
        if answer is not None:
            return seal(path,{"contract":sig,"year":self.view.year,"mode":mode,"mapping":sess.mapping,
                         "landmarks":list(landmarks),"actions":sess.actions,"receipts":sess.calls,"result":answer,
                         "subdecisions":[{"mode":d["mode"],"contract":d["contract"]} for d in parts]})
        raise RuntimeError(f"No valid {mode} submission for {self.view.year}, group size {len(names)}: {last_error}")
