"""Persistence and native-tool transport. No dependency on a SPARK evidence database."""
from collections.abc import Mapping
from pathlib import Path
import json
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
# Only generic JSON/locking utilities and the standalone, pinned HPG CPU worker are reused.
V4 = WORK / "SPARK_Motif_Transfer_Harness_v4"
sys.path.insert(0,str(V4))
from harness.common import environment, file_hash, fingerprint, packed, read_json, stamp, write_json, writer

DATA = ROOT / "data"
RUN = ROOT / "runs" / "main"
YEARS = (2004,2009,2014,2019,2024)
TEXT = {"type":"string"}
STRINGS = {"type":"array","items":TEXT}


def seal(path, body):
    sig=fingerprint(body)
    if path.exists():
        old=verified(path)
        if fingerprint({k:v for k,v in old.items() if k not in ("sha256","sealed_at")})!=sig:
            raise ValueError("Changed inputs to a frozen file: "+str(path))
        return old
    with_date=dict(body,sealed_at=stamp())
    result=dict(with_date,sha256=fingerprint(with_date))
    write_json(path,result)
    return result


def verified(path):
    d=read_json(path)
    if d.get("sha256")!=fingerprint({k:v for k,v in d.items() if k!="sha256"}):
        raise ValueError("Checksum failure: "+str(path))
    return d


def enum(options):
    return {"type":"string","enum":list(options)}


def obj(fields):
    return {"type":"object","properties":fields,"required":list(fields),"additionalProperties":False}


def array(fields):
    return {"type":"array","items":obj(fields)}


def tool(name, desc, fields):
    return {"type":"function","function":{"name":name,"description":desc,"parameters":obj(fields)}}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):
        return None


class Model:
    def __init__(self, folder):
        env=environment(WORK/"Electrolyte_Harness_20261117"/".env")
        self.base=env.get("LLM_BASE_URL","").rstrip("/")
        self.model=env.get("LLM_MODEL")
        self.token=env.get("LLM_API_KEY")
        self.offline=os.environ.get("POLYMER_ADOPTION_OFFLINE")=="1"
        if self.offline and not self.model:
            self.model=verified(ROOT/"runs"/"five_windows"/"protocol.json")["model"]
        if not self.offline and (self.base not in {"https://api.deepseek.com","https://api.deepseek.com/v1"} or not self.token or not self.model):
            raise ValueError("Set the project .env to the official DeepSeek endpoint and configured model")
        self.folder=folder

    def call(self,system,messages,tools,max_tokens=4200):
        body={"model":self.model,"messages":[{"role":"system","content":system},*messages],"tools":tools,
              "tool_choice":"auto","max_tokens":max_tokens,"thinking":{"type":"disabled"},"temperature":0}
        encoded=packed(body)
        if re.search(r"(?:cmp_|mat_|form_|policy_)[a-f0-9]{8,}|(?i:sk-[a-z0-9]{20,})",encoded):
            raise ValueError("Private identifier in model input")
        key=fingerprint(body);path=self.folder/(key+".response.json")
        if path.exists():
            r=verified(path)
            if r["request"]!=key or r["http_status"]!=200 or not r["provider_id"] or r["model"]!=self.model:
                raise ValueError("Invalid provider receipt")
            return r["message"],key
        if self.offline:raise RuntimeError("Offline replay is missing an authentic provider response: "+key)
        write_json(self.folder/(key+".request.json"),body)
        req=Request(self.base+"/chat/completions",data=encoded.encode(),headers={
            "Authorization":"Bearer "+self.token,"Content-Type":"application/json"})
        for i in range(5):
            try:
                with build_opener(NoRedirect()).open(req,timeout=145) as response:
                    status=response.status;raw=json.load(response)
                message=raw["choices"][0]["message"]
                if status!=200 or not raw.get("id") or raw.get("model")!=self.model or message["role"]!="assistant":
                    raise RuntimeError("Unverifiable model response")
                keep={k:v for k,v in message.items() if k in ("role","content","tool_calls")}
                seal(path,{"request":key,"model":raw["model"],"provider_id":raw["id"],"http_status":status,
                           "usage":raw.get("usage"),"message":keep})
                return keep,key
            except (HTTPError,URLError,TimeoutError,ConnectionError) as exc:
                status=getattr(exc,"code",None)
                if status not in (None,408,409,425,429,500,502,503,504) or i==4:
                    raise RuntimeError(f"DeepSeek transport {type(exc).__name__}, HTTP {status}") from None
                time.sleep(2**(i+1))


def native_calls(msg):
    for c in msg.get("tool_calls") or []:
        try:
            args=json.loads(c["function"]["arguments"])
            if not isinstance(args, Mapping):
                args={}
        except (TypeError,ValueError):
            args={}
        yield c,c["function"]["name"],args
