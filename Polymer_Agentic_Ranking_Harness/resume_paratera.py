"""Resume an open window after an endpoint serializes an array-valued lookup as text."""
import argparse
import json

from agent import decode_arguments
from audit import audit
from evidence import ROOT, YEARS, file_hash, packed, read_json, seal, verified, writer, write_json
from paratera import BASE, DEFAULT_MODEL, Paratera, credential
from run_paratera import study


LOOKUP_ARRAYS = {"inspect_publications":("codes",), "trace_structural_roles":("codes","axes"),
                 "query_hpg":("codes",)}


def string_list(value):
    """Interpret only a JSON encoding of a string array, including one extra quote escape."""
    for _ in range(3):
        if isinstance(value,list):
            return value if all(isinstance(x,str) for x in value) else None
        if not isinstance(value,str):
            break
        try:
            value=json.loads(value)
        except ValueError:
            try:
                value=json.loads('"'+value+'"')
            except ValueError:
                break
    return None


def one_lookup(message):
    calls=message.get("tool_calls") or []
    if len(calls)!=1:
        return None
    fn=calls[0]["function"]
    if fn["name"] not in LOOKUP_ARRAYS:
        return None
    try:
        args=decode_arguments(fn["arguments"])
    except (TypeError,ValueError):
        return None
    return fn["name"],args


def malformed_lookup(message):
    parsed=one_lookup(message)
    if not parsed:
        return None
    name,original=parsed
    args=dict(original)
    for key in LOOKUP_ARRAYS[name]:
        value=string_list(original.get(key))
        if value is None:
            return None
        args[key]=value
    return (name,args) if args!=original else None


class Resubmission:
    def __init__(self,backend,section,amendment):
        self.backend=backend
        self.model=backend.model
        self.section=section
        self.amendment=amendment

    def call(self,system,messages,tools,max_tokens=4200):
        raw,key=self.backend.call(system,messages,tools,max_tokens)
        header=json.loads(messages[0]["content"])
        if header.get("cutoff")!=YEARS[-1] or len(header.get("challengers",[]))!=1:
            return raw,key
        correction=malformed_lookup(raw)
        if not correction:
            return raw,key
        name,args=correction
        schema=next((t for t in tools if t["function"]["name"]==name),None)
        if schema is None:
            return raw,key
        # Only the provider can replace its own call. Never synthesize a read, vote or placement.
        trace=[]
        for attempt in range(3):
            prompt=(f"Native function argument repair, attempt {attempt+1}. Reissue the single lookup {name} "
                    f"with exactly this JSON object: {packed(args)}. Send a native function call. "
                    "The fields codes and axes, when present, must be JSON arrays, never quoted JSON strings.")
            msg,retry=self.backend.call(system,[*messages,{"role":"user","content":prompt}],[schema],max_tokens)
            trace.append(retry)
            if one_lookup(msg)==(name,args):
                seal(self.section/"links"/(retry+".json"),{"amendment":self.amendment,"original":key,
                     "attempts":trace,"accepted":retry,"function":name,"identical_lookup":args})
                return msg,retry
        # The unmodified agent can issue its normal correction and try the next turn.
        return raw,key


def verify_repairs(home,amendment):
    section=home/"native_lookup_repair"
    frozen=verified(home/"2024/forecast.json")
    assert amendment["parent_protocol"]==frozen["protocol"]
    assert amendment["sha256"]==verified(section/"protocol.json")["sha256"]
    assert amendment["sealed_at"]<frozen["sealed_at"] and amendment["source_sha256"]==file_hash(__file__)
    provider=home.parent/"provider"
    links={}
    for f in (section/"links").glob("*.json"):
        entry=verified(f)
        assert entry["amendment"]==amendment["sha256"] and entry["accepted"]==entry["attempts"][-1]
        raw=verified(provider/(entry["original"]+".response.json"))
        new=verified(provider/(entry["accepted"]+".response.json"))
        request=read_json(provider/(entry["original"]+".request.json"))
        retry=read_json(provider/(entry["accepted"]+".request.json"))
        assert raw["endpoint"]==new["endpoint"]==BASE and raw["returned_model"]==new["returned_model"]==amendment["returned_model"]
        assert request["messages"]==retry["messages"][:-1] and retry["messages"][-1]["role"]=="user"
        assert json.loads(request["messages"][1]["content"])["cutoff"]==2024
        assert malformed_lookup(raw["message"])==one_lookup(new["message"])==(entry["function"],entry["identical_lookup"])
        links[entry["accepted"]]=entry
    referenced=set()
    for p in (home/"2024/decisions/place").glob("*.json"):
        referenced.update(verified(p)["receipts"])
    used=links.keys() & referenced
    assert used
    write_json(section/"audit.json",{"amendment":amendment["sha256"],"frozen_forecast":frozen["sha256"],
               "linked_provider_corrections":len(links),"corrected_lookups_in_decisions":len(used),
               "functions":sorted({links[k]["function"] for k in used})})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers",type=int,default=24)
    args=parser.parse_args()
    if not 1<=args.workers<=64:
        parser.error("Invalid worker count")
    home=ROOT/"runs"/"paratera_20261123"/DEFAULT_MODEL/"exposure_primary"
    backend=Paratera(credential(),DEFAULT_MODEL,home.parent/"provider")
    with writer(home):
        protocol=verified(home/"protocol.json")
        section=home/"native_lookup_repair"
        registration=section/"protocol.json"
        if (home/"2024/forecast.json").exists() and not registration.exists():
            raise ValueError("A completed forecast cannot acquire a post-hoc repair protocol")
        past={str(y):verified(home/str(y)/"forecast.json")["sha256"] for y in YEARS[:-1]}
        amendment=seal(registration,{"parent_protocol":protocol["sha256"],"sealed_prefix":past,
                      "open_graph":verified(home/"2024/graph.json")["sha256"],"returned_model":protocol["returned_model"],
                      "scope":"2024 single-challenger placement fallbacks; read-only JSON array fields encoded as text",
                      "policy":"Ask the same deployment to reissue exactly its chosen retrieval as a native call; preserve both receipts. All comparisons and evidence requirements follow the original protocol.",
                      "source_sha256":file_hash(__file__)})
        probe=backend.probe()
        if probe["returned_model"]!=protocol["returned_model"]:
            raise ValueError("Registered model changed")
        model=Resubmission(backend,section,amendment["sha256"])
        study(home,protocol["threshold_S_cm"],args.workers,model,probe)
        audit(home)
        verify_repairs(home,amendment)


if __name__=="__main__":
    main()
