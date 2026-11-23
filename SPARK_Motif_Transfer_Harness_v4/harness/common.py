"""Content-addressed records, atomic publication, configuration and writer exclusion."""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
import tomllib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "harness/hpg_vendor/HPG_GAT.bin"
HPG_SHA = "0f859f11015f77ab9d49a0807db24f6e1c31c5c3b4be47b01d8bda7b53bf6f38"
STREAMS = ("polymer", "spe")


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


def check_policy_cutoff(policy,cutoff):
    if policy["learned_through"]>cutoff:
        raise ValueError("Ranking policy exceeds the prediction cutoff")
    memory=policy.get("order_memory",{})
    for key,field in (("recent_cases","visible_from"),("recent_windows","learned_through")):
        if any(record[field]>policy["learned_through"] for record in memory.get(key,[])):
            raise ValueError("Ranking memory contains a record beyond its declared cutoff")


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as f:
        tmp = Path(f.name)
        try:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            f.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def finite(x):
    return type(x) in (int, float) and math.isfinite(x)


@contextmanager
def database(path, *, readonly=False):
    path = Path(path).resolve()
    if readonly:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=40)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


@contextmanager
def writer(home):
    """The OS releases the lock on process exit. Readers see published generations only."""
    home.mkdir(parents=True, exist_ok=True)
    with (home / ".writer").open("a+b") as handle:
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def environment(envfile):
    result = {}
    if envfile.is_file():
        for line in envfile.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip().strip("\"'")
    return {**result, **os.environ}


class Config:
    def __init__(self, home, config, envfile):
        self.home = home.resolve()
        self.env = environment(envfile)
        with config.open("rb") as f:
            data = tomllib.load(f)
        self.study = data["study"]
        self.collection = data["collection"]
        s, c = self.study, self.collection
        if not (s["corpus_start"] <= s["baseline"] <= s["first_forecast"] < s["baseline"] + s["step"]):
            raise ValueError("Check corpus_start, baseline and first_forecast")
        if s["step"] < 1 or s["batch_size"] < 1 or s["merge_head"] < 1:
            raise ValueError("Window and batch sizes must be positive")
        if s["candidate_origin"] not in {"nonbattery", "all_polymer"}:
            raise ValueError("Unknown candidate_origin")
        if s["target_scope"] not in {"all_battery_spe","lithium_battery_spe"}:
            raise ValueError("Unknown target_scope")
        if not (1 <= c["page_size"] <= 1000 and 0 <= c["chunk_overlap"] < c["chunk_chars"] and
                c["max_results_per_query_year"] >= 0):
            raise ValueError("Invalid retrieval or text chunk settings")
        if not (0 < s["reference_salt_wt_fraction"] < 1 and s["reference_dp"] >= 1
                and finite(s["reference_temperature_c"]) and s["reference_temperature_c"] > -273.15):
            raise ValueError("Invalid HPG reference design")
        self.model = self.env.get("LLM_MODEL", "")
        self.endpoint = self.env.get("LLM_BASE_URL", "").rstrip("/")
        self.protocol = {
            "settings": data, "model": self.model, "endpoint": self.endpoint,
            "files": {p.relative_to(ROOT).as_posix(): file_hash(p)
                      for p in sorted([ROOT/"run.py",*ROOT.glob("harness/**/*.py"), *ROOT.glob("data/*.json"), CHECKPOINT])}
        }

    def bind(self):
        path = self.home / "protocol.json"
        if path.exists():
            if read_json(path) != self.protocol:
                raise ValueError("Run settings, implementation, registry or model changed. Select a new --state directory.")
        else:
            write_json(path, self.protocol)
