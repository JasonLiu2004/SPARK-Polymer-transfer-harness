import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from online import batch, discover, download_pdf
from scope import restore_abstract, screen


class OnlineTests(unittest.TestCase):
    def test_target_skips_failures_and_stops(self):
        import fitz
        from urllib.error import HTTPError
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), 'Polymer electrolyte transport')
        data = doc.tobytes()
        doc.close()
        papers = [{'title': str(i), 'pdf_urls': [f'https://example.org/{i}.pdf']} for i in range(3)]
        with tempfile.TemporaryDirectory() as tmp, patch('online.fetch', side_effect=[HTTPError(papers[0]['pdf_urls'][0],403,'Forbidden',{},None),(data,papers[1]['pdf_urls'][0])]) as fetch:
            results = batch(iter(papers),tmp,target=1)
            self.assertEqual(len(results),2)
            self.assertEqual(fetch.call_count,2)
            report=json.loads((Path(tmp)/'batch.json').read_text())
            self.assertEqual(report['successful_papers'],1)
            self.assertEqual(report['stop_reason'],'target_reached')

    def setUp(self):
        self.config = json.loads(Path(__file__).with_name('scope.json').read_text())

    def test_scope(self):
        cases = [
            ('Polymerized ionic liquid ion transport', 'include'),
            ('Polymer hydrogel proton conductivity', 'include'),
            ('Polymer optical sensor fluorescence', 'manual_review'),
            ('Polymer membrane with ether groups and free volume', 'include'),
            ('Inorganic sulfide solid electrolyte', 'exclude'),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                result = screen({'title': title, 'abstract': title, 'type': 'article'}, self.config)
                self.assertEqual(result['decision'], expected)
        self.assertEqual(screen({'title': 'Unknown material'}, self.config)['decision'], 'manual_review')
        self.assertEqual(screen({'title': cases[0][0], 'type': 'review'}, self.config)['decision'], 'background')
        result = screen({'title': 'Amorphous polymer with carbonyl groups'}, self.config)
        self.assertEqual(result['inclusion_route'], 'structure_hypothesis')
        self.assertEqual(result['suitability'], 'not_assessed')

    def test_discovery_dedup_and_oa_locations(self):
        work = {'id': 'W1', 'doi': 'doi1', 'display_name': 'Polymer electrolyte',
                'abstract_inverted_index': {'ion': [0], 'transport': [1]},
                'locations': [{'is_oa': True, 'pdf_url': 'https://example.org/a.pdf'},
                              {'is_oa': False, 'pdf_url': 'https://example.org/private.pdf'}]}
        payload = json.dumps({'results': [work, work], 'meta': {}}).encode()
        with patch('online.fetch', return_value=(payload, 'https://api.openalex.org')):
            papers = discover('polymer', 5)
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]['abstract'], 'ion transport')
        self.assertEqual(len(papers[0]['pdf_urls']), 1)

    def test_html_is_not_a_pdf(self):
        with tempfile.TemporaryDirectory() as tmp, patch('online.fetch', return_value=(b'<html>login</html>', 'https://example.org')):
            with self.assertRaises(ValueError):
                download_pdf('https://example.org/paper', tmp)
            self.assertEqual(list(Path(tmp).glob('*.pdf')), [])
            event = json.loads((Path(tmp) / 'download_events.jsonl').read_text())
            self.assertEqual(event['error_category'], 'non_pdf_response')

    def test_independent_papers_global_budget(self):
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            doc = fitz.open()
            doc.new_page().insert_text((72, 72), 'Polymer electrolyte ionic conductivity')
            data = doc.tobytes()
            doc.close()
            papers = [{'id': str(i), 'title': str(i), 'pdf_urls': ['https://example.org/a.pdf']} for i in range(2)]
            with patch('online.fetch', return_value=(data, 'https://example.org/a.pdf')):
                results = batch(papers, tmp, lambda s: ({'records': [], 'action': {'tool': 'finish'}}, {}), max_total_calls=1)
            self.assertEqual(results[0]['calls'], 1)
            self.assertEqual(results[1]['status'], 'global_budget_exhausted')
            self.assertTrue((Path(tmp) / 'paper_001/result.json').exists())
            self.assertFalse((Path(tmp) / 'paper_002').exists())


if __name__ == '__main__':
    unittest.main()
