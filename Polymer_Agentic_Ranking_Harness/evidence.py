"""As-of evidence available to the ranking agent. Inputs are our own dated publication extractions."""
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "Polymer_Adoption_Harness"
sys.path.insert(0, str(SOURCE))
from common import DATA, YEARS, Model, file_hash, fingerprint, packed, read_json, seal, verified, write_json, writer
from corpus import INTERVALS
from extract import read_interval
from graph import AXES, build, observations
from physics import CHECKPOINT_SHA, DEFAULT_THRESHOLD, dated_predictions, prepare
from adoption import admit
from structures import normalized


def spread(names, salt):
    """Reproducible presentation order, independent of evidence or outcomes."""
    return sorted(names, key=lambda n: (fingerprint([salt, n]), n))


def merge_interval(collection, interval):
    for doi, record in interval["records"].items():
        if doi in collection and collection[doi] != record:
            raise ValueError("Conflicting paper versions in time stream")
        collection[doi] = record


def excerpt(row):
    return {"doi": row["doi"], "year": row["year"], "name": row["name"], "sample": row["sample"],
            "role": row["role"], "quote": row["quote"], "axes": row["axes"]}


class Evidence:
    def __init__(self, year, broad, past_spe, grid, threshold):
        self.year = year
        self.threshold = threshold
        self.ledger, self.panel = build(broad, year)
        self.known = observations(past_spe, year)
        self.physical = dated_predictions(self.panel, grid, year)
        self.high = admit([], self.physical, year, threshold)
        self.by_axis = defaultdict(list)
        for name, events in self.known.items():
            for event in events:
                for axis, value in event["axes"].items():
                    if value:
                        self.by_axis[axis, normalized(value)].append((name, event))
        self.digest = fingerprint([year, self.panel, self.known, self.physical, threshold])

    def publications(self, name, extended=False):
        item = self.panel[name]
        sources = item["sources"]
        first = min(sources, key=lambda r: (r["year"], r["doi"]))
        ordered = [sources[0], first, *sources]
        chosen = {}
        for r in ordered:
            chosen.setdefault(r["doi"], excerpt(r))
            if len(chosen) >= (6 if extended else 2):
                break
        near = {r["doi"] for r in sources if self.year-4 <= r["year"] <= self.year}
        preceding = {r["doi"] for r in sources if self.year-9 <= r["year"] <= self.year-5}
        events = self.known.get(name, [])
        return {"distinct_source_dois": item["papers"], "first_year": first["year"], "last_year": item["latest"],
                "last_five_years": len(near), "previous_five_years": len(preceding),
                "sample_evidence": list(chosen.values()), "indexed_past_SPE_dois": len({e["doi"] for e in events}),
                "past_SPE_example": excerpt(events[0]) if events else None}

    def motifs(self, name, axes):
        material = self.panel[name]
        result = {}
        for axis in axes:
            if axis not in AXES:
                raise ValueError("Unknown structural axis")
            direct = [s for s in material["sources"] if s["axes"].get(axis)]
            matches = {}
            for value in material["axes"][axis]:
                for other, e in self.by_axis.get((axis, normalized(value)), []):
                    if other != name:
                        matches[(other, e["doi"])] = {"other_material": other, "matched_value": value,
                                                      "past_SPE_evidence": excerpt(e)}
            ranked = sorted(matches.values(), key=lambda m: (-m["past_SPE_evidence"]["year"], m["other_material"], m["past_SPE_evidence"]["doi"]))
            result[axis] = {"attributed_phrases": material["axes"][axis], "source": excerpt(direct[0]) if direct else None,
                            "analogue_doi_count": len({k[1] for k in matches}), "analogues": ranked[:2]}
        return result

    def hpg(self, name):
        rows = self.physical.get(name, [])
        return {"basis": "designed dry polymer/LiTFSI, DP 100, total ionic conductivity",
                "threshold_S_cm": self.threshold,
                "conditions": [{"C": d["temperature_C"], "salt_wt_pct": d["salt_wt_pct"], "status": d["status"],
                                "sigma_S_cm": d.get("sigma_S_cm"), "source_year": d["source_year"],
                                "structure_source_doi": d["source_doi"]} for d in rows]}
