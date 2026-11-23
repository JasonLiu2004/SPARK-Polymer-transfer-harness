"""OpenAI-compatible native tools on the explicitly configured Paratera service."""
import argparse
import getpass
import json
import os
import random
import re
import socket
import threading
import time
from http.client import IncompleteRead, RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from evidence import fingerprint, packed, seal, verified, write_json
from common import NoRedirect


BASE = "https://llmapi.paratera.com/v1"
DEFAULT_MODEL = "DeepSeek-V4-Flash-0731"


def credential():
    return os.environ.get("PARATERA_API_KEY") or getpass.getpass("Paratera API key (hidden): ")


class TransportError(RuntimeError):
    def __init__(self, status, detail):
        self.status = status
        super().__init__(f"Paratera HTTP {status}: {detail}")


class Paratera:
    def __init__(self, token, deployment, folder=None, returned_model=None):
        self.token = token
        self.model = deployment
        self.returned_model = returned_model
        self.folder = folder
        self.offline = False
        self.condition = threading.Lock()
        self.next_attempt = 0
        self.fatal = None

    def post(self, body):
        request = Request(BASE + "/chat/completions", data=packed(body).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.token})
        for attempt in range(6):
            with self.condition:
                if self.fatal:
                    raise self.fatal
                pause = self.next_attempt - time.monotonic()
            if pause > 0:
                time.sleep(pause + random.uniform(0.05, 0.6))
            try:
                with build_opener(NoRedirect()).open(request, timeout=150) as response:
                    raw = json.load(response)
                if not raw.get("id") or not raw.get("model") or raw["choices"][0]["message"].get("role") != "assistant":
                    raise ValueError("Provider returned an incomplete chat completion")
                return raw
            except HTTPError as exc:
                detail = exc.read(4096).decode("utf-8", errors="replace").replace(self.token, "[redacted]")
                detail = re.sub(r"sk-[\w.-]+", "[redacted]", detail)[:600]
                error = TransportError(exc.code, detail)
                if exc.code in (401, 402, 403):
                    with self.condition:
                        self.fatal = error
                if exc.code not in (408, 409, 425, 429, 500, 502, 503, 504) or attempt == 5:
                    raise error from None
                try:
                    delay = float(exc.headers.get("Retry-After", 0))
                except ValueError:
                    delay = 0
                if exc.code == 429:
                    with self.condition:
                        self.next_attempt = max(self.next_attempt, time.monotonic() + max(2 ** attempt, delay))
            except (URLError, socket.timeout, IncompleteRead, RemoteDisconnected, ConnectionError) as exc:
                if attempt == 5:
                    raise RuntimeError(f"Paratera transport failed ({type(exc).__name__})") from None
            time.sleep(min(24, 2 ** attempt) + random.uniform(0.05, 0.5))

    def probe(self):
        """Validate both a native function call and submission of the matching tool result."""
        tool = {"type":"function","function":{"name":"read_cutoff","description":"Read the frozen year",
                "parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False}}}
        messages = [{"role":"user","content":"Call read_cutoff with no arguments. After its result, answer with only the year."}]
        args = {"model": self.model, "messages": messages, "tools": [tool], "tool_choice": "auto",
                "temperature": 0, "max_tokens": 200, "thinking": {"type":"disabled"}}
        raw = self.post(args)
        message = self.message(raw)
        call = (message.get("tool_calls") or [{}])[0]
        if call.get("function", {}).get("name") != "read_cutoff" or not call.get("id"):
            raise ValueError("Probe did not return a native tool call")
        messages.extend([message, {"role":"tool","tool_call_id":call["id"],"content":'{"year":2004}'}])
        end = self.post(args)
        if end["model"] != raw["model"] or "2004" not in (end["choices"][0]["message"].get("content") or ""):
            raise ValueError("Provider failed the native tool-result round trip")
        if self.returned_model is not None and self.returned_model != raw["model"]:
            raise ValueError("Returned model differs from the registered deployment")
        self.returned_model = raw["model"]
        return {"endpoint":BASE, "deployment":self.model,"returned_model":self.returned_model,
                "native_tool_round_trip":True, "provider_ids":[raw["id"],end["id"]]}

    @staticmethod
    def message(raw):
        return {k:v for k,v in raw["choices"][0]["message"].items() if k in ("role","content","tool_calls")}

    def call(self, system, messages, tools, max_tokens=4200):
        body = {"model":self.model,"messages":[{"role":"system","content":system},*messages],
                "tools":tools,"tool_choice":"auto","temperature":0,"max_tokens":max_tokens,
                "thinking":{"type":"disabled"}}
        if re.search(r"(?:cmp_|mat_|form_|policy_)[a-f0-9]{8,}|(?i:sk-[a-z0-9]{20,})", packed(body)):
            raise ValueError("Private identifier in model input")
        key = fingerprint(body)
        path = self.folder / (key + ".response.json")
        if path.exists():
            receipt = verified(path)
            if (receipt["request"], receipt["endpoint"], receipt["model"], receipt["returned_model"],
                receipt["http_status"]) != (key, BASE, self.model, self.returned_model, 200) or not receipt["provider_id"]:
                raise ValueError("Provider receipt does not belong to the registered deployment")
            return receipt["message"], key
        write_json(self.folder / (key + ".request.json"), body)
        raw = self.post(body)
        if raw["model"] != self.returned_model:
            raise ValueError(f"Deployment changed during the experiment: {raw['model']!r}")
        message = self.message(raw)
        seal(path, {"request":key, "endpoint":BASE, "model":self.model, "returned_model":raw["model"],
                    "provider_id":raw["id"], "http_status":200, "usage":raw.get("usage"), "message":message})
        return message, key


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Test the Paratera native tool path")
    cli.add_argument("--model", default=DEFAULT_MODEL)
    args = cli.parse_args()
    print(json.dumps(Paratera(credential(), args.model).probe(), ensure_ascii=False), flush=True)
