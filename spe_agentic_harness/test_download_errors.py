import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from online import download_pdf, batch, main
from download_errors import DownloadError, failure_record
from harness import ResearchHarness


class DownloadTests(unittest.TestCase):
    def test_http_classification(self):
        for code, category, retry in [(403,'access_denied',False),(404,'not_found',False),(429,'rate_limited',True),(503,'server_error',True)]:
            r = failure_record('https://example.org/original', HTTPError('https://example.org/final',code,'test',{},None))
            self.assertEqual((r['error_category'],r['retryable']),(category,retry))
            self.assertEqual(r['http_status'],code)
            self.assertEqual(r['resolved_url'],'https://example.org/final')
        self.assertEqual(failure_record('https://example.org',URLError(TimeoutError()))['error_category'],'timeout')

    def test_failure_persisted_and_harness_returned(self):
        url='https://example.org/paper.pdf'
        with tempfile.TemporaryDirectory() as tmp, patch('online.fetch', side_effect=HTTPError(url,403,'Forbidden',{},None)):
            h=ResearchHarness(Path(tmp)/'h')
            reply=h.execute('fetch_pdf',{'url':url})
            self.assertEqual(reply['error']['error_category'],'access_denied')
            event=json.loads((Path(tmp)/'h/downloads/download_events.jsonl').read_text())
            self.assertEqual(event['url'],url)
            results=batch([{'title':'Test','pdf_urls':[url]}],Path(tmp)/'batch')
            self.assertEqual(results[0]['attempts'][0]['http_status'],403)

    def test_direct_cli_saves_report(self):
        url='https://example.org/paper.pdf'
        with tempfile.TemporaryDirectory() as tmp, patch('online.fetch',side_effect=HTTPError(url,403,'Forbidden',{},None)), patch('sys.argv',['online.py','--url',url,'--download-only','--out',tmp]):
            with self.assertRaises(SystemExit) as exit:
                main()
            self.assertEqual(exit.exception.code,2)
            report=json.loads((Path(tmp)/'download_report.json').read_text())
            self.assertEqual(report['status'],'incomplete')
            self.assertEqual(report['attempts'][0]['url'],url)
