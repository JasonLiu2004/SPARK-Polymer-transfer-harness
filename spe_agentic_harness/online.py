"""Topic discovery and per-paper extraction using OpenAlex metadata and OA PDFs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlencode, urlsplit
import urllib.error
import urllib.request

from curator import Corpus, Client, run
from scope import restore_abstract, screen
from config import load_env
from download_errors import DownloadError, failure_record


def fetch(url, limit=40 * 1024 * 1024, headers=None):
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username:
        raise ValueError('Expected an HTTP(S) URL without embedded credentials')
    request = urllib.request.Request(url, headers={
        'User-Agent': 'AgenticCurator/0.1 literature-research', **(headers or {})})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Download exceeds configured byte limit')
        return data, response.geturl()


def discover(topic, limit, year_from=None):
    load_env()
    filters = ['open_access.is_oa:true']
    if year_from:
        filters.append(f'from_publication_date:{year_from}-01-01')
    params = {'search': topic, 'filter': ','.join(filters), 'per-page': min(limit, 100), 'cursor': '*'}
    headers = {}
    if os.environ.get('OPENALEX_API_KEY'):
        headers['Authorization'] = 'Bearer ' + os.environ['OPENALEX_API_KEY']
    papers, seen = [], set()
    while len(papers) < limit:
        data, _ = fetch('https://api.openalex.org/works?' + urlencode(params), headers=headers)
        payload = json.loads(data)
        for work in payload.get('results', []):
            identity = work.get('doi') or work.get('id')
            if not identity or identity in seen:
                continue
            seen.add(identity)
            locations = [work.get('best_oa_location'), work.get('primary_location'), *work.get('locations', [])]
            urls = list(dict.fromkeys(loc['pdf_url'] for loc in locations
                                     if loc and loc.get('is_oa') and loc.get('pdf_url')))
            # Repository copies often expose an abstract landing page, but no pdf_url.
            for loc in locations:
                if not loc or not loc.get('is_oa'):
                    continue
                landing = loc.get('landing_page_url') or ''
                parsed = urlsplit(landing)
                if parsed.hostname in ('arxiv.org', 'www.arxiv.org') and parsed.path.startswith('/abs/'):
                    urls.append('https://arxiv.org/pdf/' + parsed.path[len('/abs/'):])
            urls = list(dict.fromkeys(urls))
            papers.append({'id': work.get('id'), 'doi': work.get('doi'),
                           'title': work.get('display_name'), 'year': work.get('publication_year'),
                           'abstract': restore_abstract(work.get('abstract_inverted_index')),
                           'type': work.get('type'), 'pdf_urls': urls})
            if len(papers) == limit:
                break
        cursor = payload.get('meta', {}).get('next_cursor')
        if not payload.get('results') or not cursor or cursor == params['cursor']:
            break
        params['cursor'] = cursor
        time.sleep(.3)
    return papers


def download_pdf(url, directory):
    import fitz
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    resolved, stage, subtype = None, 'download', None
    try:
        data, resolved = fetch(url)
        stage = 'validate_pdf'
        if b'%PDF-' not in data[:1024]:
            subtype = 'non_pdf_response'
            raise ValueError('Response is not a PDF; it may be a landing or login page')
        with fitz.open(stream=data, filetype='pdf') as doc:
            if doc.needs_pass or not len(doc):
                subtype = 'encrypted_pdf' if doc.needs_pass else 'empty_pdf'
                raise ValueError('PDF is encrypted or contains no pages')
        stage = 'save_file'
        path = directory / (hashlib.sha256(data).hexdigest() + '.pdf')
        if not path.exists():
            path.write_bytes(data)
    except (ValueError, OSError, RuntimeError) as exc:
        record = failure_record(url, exc, resolved, stage)
        if subtype:
            record['error_category'] = subtype
        append_download_event(directory, record)
        raise DownloadError(record) from exc
    provenance = {'url': url, 'resolved_url': resolved,
                  'retrieved_at': datetime.now(timezone.utc).isoformat()}
    append_download_event(directory, {**provenance, 'status': 'downloaded', 'path': str(path)})
    return path, provenance


def append_download_event(directory, record):
    with (directory / 'download_events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def batch(papers, out, client=None, max_calls=6, max_total_calls=30, mode='agentic', target=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    results, used, successes = [], 0, 0
    attempted_urls, content_hashes = set(), set()
    for index, paper in enumerate(papers, 1):
        entry = {**paper, 'status': 'no_pdf_url', 'attempts': []}
        results.append(entry)
        if client and used >= max_total_calls:
            entry['status'] = 'global_budget_exhausted'
        else:
            for url in paper['pdf_urls'][:3]:
                if url in attempted_urls:
                    entry['attempts'].append({'url': url, 'error_category': 'already_attempted_in_batch'})
                    continue
                attempted_urls.add(url)
                try:
                    path, provenance = download_pdf(url, out / 'downloads')
                    corpus = Corpus([path])
                    corpus.sources[0].update(provenance)
                    corpus.sources[0].update({k: paper.get(k) for k in ('doi', 'title', 'id')})
                    corpus.sources[0]['screening'] = paper.get('screening')
                    if not any(text.strip() for text in corpus.pages.values()):
                        raise ValueError('PDF has no extractable text; OCR needed')
                    digest = corpus.sources[0]['sha256']
                    if digest in content_hashes:
                        entry['status'] = 'duplicate_content'
                        break
                    content_hashes.add(digest)
                except DownloadError as exc:
                    entry['attempts'].append(exc.record)
                    entry['status'] = 'download_failed'
                    continue
                except (ValueError, OSError, RuntimeError) as exc:
                    entry['attempts'].append({'url': url, 'error': str(exc)})
                    entry['status'] = 'text_extraction_failed'
                    continue
                entry.update({'status': 'downloaded', 'path': str(path), **provenance})
                if client:
                    budget = min(max_calls, max_total_calls - used)
                    def counted(state):
                        nonlocal used
                        used += 1  # Failed requests also count against the global budget.
                        return client(state)
                    try:
                        result_dir = out / f'paper_{index:03d}'
                        result = run(corpus, counted, result_dir, budget, mode)
                        entry.update({'status': result['status'], 'result': str(result_dir / 'result.json'),
                                      'records': len(result['records']), 'calls': result['calls']})
                        # Missing facts stay unknown; a supported material record can
                        # succeed without conductivity, important for cross-domain leads.
                        bad = {x.get('record') for x in result['issues'] if x['issue'] != 'missing'}
                        good = [r for r in result['records'] if isinstance(r, dict)
                                and r.get('id') not in bad and r.get('polymer')
                                and any(isinstance(v, dict) and v.get('evidence') for v in r.values())]
                        entry['successful'] = bool(good)
                        if not good:
                            entry['status'] = 'extraction_needs_review'
                    except Exception as exc:
                        entry.update({'status': 'extraction_failed', 'error': str(exc)})
                break
        if (client is None and entry['status'] == 'downloaded') or entry.get('successful'):
            successes += 1
        write_json(out / 'batch.json', {'papers': results, 'model_calls': used,
                   'successful_papers': successes, 'target': target,
                   'stop_reason': 'running'})
        print(f"[{index}] {entry['status']} | success={successes}: {paper.get('title')}", flush=True)
        if target and successes >= target:
            break
        if target and client and used >= max_total_calls:
            break
    if not papers:
        write_json(out / 'batch.json', {'papers': [], 'model_calls': 0})
    write_json(out / 'batch.json', {'papers': results, 'model_calls': used, 'successful_papers': successes,
               'target': target, 'stop_reason': 'target_reached' if target and successes >= target else
               ('model_budget_exhausted' if client and used >= max_total_calls else 'candidates_exhausted')})
    return results


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--topic', help='English topic/query, followed by the polymer/ion-transport scope gate')
    source.add_argument('--discover-spe', action='store_true', help='Search all bounded cross-domain SPE queries')
    source.add_argument('--url', nargs='+', help='Direct PDF URLs for ONE paper and its SI')
    parser.add_argument('--out', required=True)
    parser.add_argument('--limit', type=int, default=5, help='Maximum search candidates, not guaranteed downloads')
    parser.add_argument('--target', type=int, help='Required successful papers; skip failures and replenish search')
    parser.add_argument('--max-candidates', type=int, default=30, help='Total metadata search budget with --target')
    parser.add_argument('--year-from', type=int)
    parser.add_argument('--scope-file', default=str(Path(__file__).with_name('scope.json')))
    parser.add_argument('--search-only', action='store_true')
    parser.add_argument('--download-only', action='store_true')
    parser.add_argument('--max-calls', type=int, default=6)
    parser.add_argument('--max-total-calls', type=int, default=30)
    parser.add_argument('--max-output-tokens', type=int, default=5000)
    parser.add_argument('--mode', choices=['agentic', 'single'], default='agentic')
    args = parser.parse_args()
    if min(args.limit, args.max_calls, args.max_total_calls, args.max_output_tokens) < 1:
        parser.error('Limits must be positive')
    if args.max_candidates < 1 or (args.target is not None and args.target < 1):
        parser.error('Target and candidate budget must be positive')
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        parser.error('Use a new empty output directory')
    client = None
    if not args.search_only and not args.download_only:
        if not os.environ.get('LLM_MODEL') or not os.environ.get('LLM_BASE_URL'):
            parser.error('Set LLM_MODEL and LLM_BASE_URL')
        client = Client(os.environ['LLM_MODEL'], os.environ['LLM_BASE_URL'], args.max_output_tokens)
    out.mkdir(parents=True, exist_ok=True)
    if args.url:
        if args.search_only:
            parser.error('--search-only requires --topic')
        files, metadata = [], []
        attempts = []
        for url in args.url:
            try:
                path, provenance = download_pdf(url, out / 'downloads')
            except DownloadError as exc:
                attempts.append(exc.record)
                write_json(out / 'download_report.json', {'status': 'incomplete', 'attempts': attempts})
                continue
            files.append(path)
            metadata.append(provenance)
            attempts.append({**provenance, 'status': 'downloaded', 'path': str(path)})
            write_json(out / 'download_report.json', {'status': 'pending', 'attempts': attempts})
        complete = len(files) == len(args.url)
        write_json(out / 'download_report.json', {'status': 'complete' if complete else 'incomplete', 'attempts': attempts})
        if not complete:
            print('Some requested files could not be downloaded. See download_report.json. Extraction not started.')
            raise SystemExit(2)
        corpus = Corpus(files)
        for src, provenance in zip(corpus.sources, metadata):
            src.update(provenance)
        write_json(out / 'sources.json', corpus.sources)
        if client:
            run(corpus, client, out / 'extraction', min(args.max_calls, args.max_total_calls), args.mode)
        return
    config = json.loads(Path(args.scope_file).read_text(encoding='utf-8-sig'))
    queries = config['queries'] if args.discover_spe else [args.topic]
    if args.target and not args.search_only:
        def candidate_stream():
            all_papers, seen = [], set()
            # Increase each query's result window; identities prevent duplicate processing.
            for window in range(args.limit, args.max_candidates + args.limit, args.limit):
                for query in queries:
                    for paper in discover(query, min(window, args.max_candidates), args.year_from):
                        identity = paper.get('doi') or paper['id']
                        if identity in seen:
                            continue
                        seen.add(identity)
                        paper.update({'query': query, 'screening': screen(paper, config)})
                        all_papers.append(paper)
                        write_json(out / 'search.json', {'queries': queries, 'scope': config, 'papers': all_papers})
                        if paper['screening']['decision'] == 'include':
                            yield paper
                        if len(seen) >= args.max_candidates:
                            return
        batch(candidate_stream(), out, client, args.max_calls, args.max_total_calls, args.mode, args.target)
        return
    papers, seen = [], set()
    for query in queries:
        for paper in discover(query, args.limit, args.year_from):
            identity = paper.get('doi') or paper['id']
            if identity in seen:
                continue
            seen.add(identity)
            paper['query'] = query
            paper['screening'] = screen(paper, config)
            papers.append(paper)
    write_json(out / 'search.json', {'topic': args.topic, 'provider': 'OpenAlex',
               'searched_at': datetime.now(timezone.utc).isoformat(), 'year_from': args.year_from,
               'limit_per_query': args.limit, 'queries': queries, 'scope': config, 'papers': papers})
    if args.search_only:
        print(f'Found {len(papers)} candidates; saved to {out / "search.json"}')
        return
    included = [paper for paper in papers if paper['screening']['decision'] == 'include']
    batch(included, out, client, args.max_calls, args.max_total_calls, args.mode)


if __name__ == '__main__':
    main()
