"""Recreate the public bibliographic inputs consumed by corpus.raw_paths()."""
import argparse
from datetime import date
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import time

from common import DATA, seal, verified, writer
from corpus import INTERVALS, JOURNAL, PMC, TOPIC, get, get_topic, plain, raw_paths


PRIMARY = ('(TITLE_ABS:"solid polymer electrolyte" OR TITLE_ABS:"solid polymer electrolytes" OR '
           'TITLE_ABS:"solid biopolymer electrolyte" OR TITLE_ABS:"composite polymer electrolyte" OR '
           'TITLE_ABS:"all-solid-state polymer electrolyte" OR TITLE_ABS:"solid-state polymer electrolyte") '
           'AND (TITLE_ABS:battery OR TITLE_ABS:batteries OR TITLE_ABS:"lithium metal cell")')
INDEPENDENT = ('TITLE:electrolyte* AND (TITLE_ABS:polymer OR TITLE_ABS:polymeric OR TITLE_ABS:biopolymer) '
               'AND (TITLE_ABS:"solid state" OR TITLE_ABS:"all solid state" OR TITLE_ABS:"solvent free") '
               'AND (TITLE_ABS:battery OR TITLE_ABS:batteries OR TITLE_ABS:"full cell" OR TITLE_ABS:"half cell")')


def crossref_page(params):
    request = Request(JOURNAL + "?" + urlencode(params),
                      headers={"Accept": "application/json", "User-Agent": "Polymer-Transfer-Harness/1.0"})
    for attempt in range(5):
        try:
            with urlopen(request, timeout=65) as response:
                return json.load(response)["message"]
        except OSError:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def journal(year, filters):
    params = {"filter": filters, "rows": 300, "cursor": "*",
              "select": "DOI,title,abstract,published-online,published-print,published"}
    papers, seen = {}, set()
    # The two original Crossref exports cover 2000–2009 and 2010–2024 respectively.
    lower, upper = (2000, 2009) if year < 2010 else (2010, 2024)
    while True:
        message = crossref_page(params)
        previous_count = len(seen)
        for entry in message["items"]:
            doi = entry["DOI"].lower()
            seen.add(doi)
            dates = [entry[key]["date-parts"][0] for key in ("published-online", "published-print", "published")
                     if entry.get(key, {}).get("date-parts") and entry[key]["date-parts"][0]]
            if not dates or not entry.get("title"):
                continue
            first = min(dates)[0]
            if lower <= first <= upper:
                papers[doi] = {"doi": doi, "year": first, "title": plain(entry["title"][0]),
                               "abstract": plain(entry.get("abstract")), "sources": ["Polymer Journal / Crossref"]}
        if len(seen) == message["total-results"]:
            return {"year": year, "source": JOURNAL, "filter": filters, "hits": len(seen), "papers": papers}
        if len(seen) == previous_count or len(message["items"]) < params["rows"] or not message.get("next-cursor"):
            raise ValueError(f"Incomplete Crossref export for {year}: {len(seen)} of {message['total-results']}")
        params["cursor"] = message["next-cursor"]


def spe_query(query, lo, hi):
    params = {"query": query, "resultType": "core", "format": "json", "pageSize": 200, "cursorMark": "*"}
    papers, seen = {}, set()
    while True:
        response = get(params)
        previous_count = len(seen)
        for entry in response["resultList"]["result"]:
            seen.add((entry["source"], entry["id"]))
            doi = (entry.get("doi") or "").lower()
            when = entry.get("firstPublicationDate")
            if not doi or not when or not entry.get("title"):
                continue
            year = date.fromisoformat(when).year
            if not lo <= year <= hi:
                continue
            record = {"doi": doi, "year": year, "date": when, "title": plain(entry["title"]),
                      "abstract": plain(entry.get("abstractText")), "types": entry.get("pubTypeList", {}).get("pubType", []),
                      "sources": ["Europe PMC"]}
            if doi not in papers or len(record["abstract"]) > len(papers[doi]["abstract"]):
                papers[doi] = record
        if len(seen) == response["hitCount"]:
            return {"source": PMC, "query": query, "hits": len(seen), "papers": papers}
        cursor = response.get("nextCursorMark")
        if len(seen) == previous_count or not cursor or cursor == params["cursorMark"]:
            raise ValueError(f"Incomplete Europe PMC export for {lo}–{hi}: {len(seen)} of {response['hitCount']}")
        params["cursorMark"] = cursor


def sources():
    """Yield the destination, source URL, exact query and a lazy fetch function."""
    broad = raw_paths("broad")
    for path in broad:
        if "_" in path.stem:
            continue
        year = int(path.stem)
        filters = f"type:journal-article,from-pub-date:{year}-01-01,until-pub-date:{year}-12-31"
        yield path, JOURNAL, filters, lambda y=year, f=filters: journal(y, f)
    for stream, query in (("broad", TOPIC), ("spe", PRIMARY), ("independent", INDEPENDENT)):
        paths = [p for p in raw_paths(stream) if "_" in p.stem]
        for interval, path in zip(INTERVALS, paths, strict=True):
            lo, hi = interval
            dated = query + f" AND FIRST_PDATE:[{lo}-01-01 TO {hi}-12-31]"
            fetch = (lambda t=interval: get_topic(t)) if stream == "broad" else (
                lambda q=dated, a=lo, b=hi: spe_query(q, a, b))
            yield path, PMC, dated, fetch


def prepare(check_only=False):
    missing = []
    for path, source, query, fetch in sources():
        if path.exists():
            snapshot = verified(path)
        elif check_only:
            missing.append(path)
            continue
        else:
            body = fetch()
            # get_topic writes and seals its own output.
            snapshot = verified(path) if path.exists() else seal(path, body)
        if snapshot["source"] != source or (snapshot.get("filter") or snapshot.get("query")) != query:
            raise ValueError(f"Input snapshot has a different query: {path}")
        print(f"{path.name}  {len(snapshot['papers'])} DOI", flush=True)
    if missing:
        raise SystemExit(f"{len(missing)} input snapshots missing. First: {missing[0]}. Run 'python run.py sources' to fetch them.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify saved input snapshots without downloading")
    args = parser.parse_args()
    if args.check:
        prepare(check_only=True)
    else:
        with writer(DATA / "sources"):
            prepare()
