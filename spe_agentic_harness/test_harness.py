from pathlib import Path
import tempfile
import unittest
from harness import ResearchHarness


class HarnessTests(unittest.TestCase):
    def test_contract_and_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = ResearchHarness(tmp, max_tool_calls=2)
            bad = h.execute('fetch_pdf', {'url': 123})
            self.assertEqual(bad['status'], 'error')
            good = h.execute('screen_candidates', {'papers': [{'title': 'Amorphous polymer ether membrane'}]})
            self.assertEqual(good['data']['papers'][0]['screening']['inclusion_route'], 'structure_hypothesis')
            self.assertEqual(h.execute('screen_candidates', {'papers': []})['status'], 'error')
            self.assertEqual(len((Path(tmp) / 'events.jsonl').read_text().splitlines()), 3)

    def test_shared_corpus_and_model_budget(self):
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'paper.pdf'
            doc = fitz.open()
            doc.new_page().insert_text((72, 72), 'Polymer conductivity 1 mS/cm.')
            doc.save(path)
            doc.close()
            fake = lambda state: ({'records': [], 'action': {'tool': 'finish'}}, {})
            h = ResearchHarness(Path(tmp) / 'run', client=fake, max_model_calls=1)
            cid = h.execute('open_corpus', {'paths': [str(path)]})['data']['corpus_id']
            field = {'value': 1, 'unit': 'mS/cm', 'evidence': [{'source': 'S1', 'page': 1, 'quote': '1 mS/cm'}]}
            args = {'corpus_id': cid, 'records': [{'id': 'A', 'conductivity': field}]}
            before = h.execute('validate_records', args)
            self.assertTrue(any(x['issue'] == 'quote_not_in_observed_page' for x in before['data']['issues']))
            h.execute('read_evidence', {'corpus_id': cid, 'source': 'S1', 'page': 1})
            after = h.execute('validate_records', args)
            self.assertFalse(any(x['issue'] == 'quote_not_in_observed_page' for x in after['data']['issues']))
            self.assertEqual(h.execute('extract_records', {'corpus_id': cid})['status'], 'ok')
            self.assertEqual(h.execute('extract_records', {'corpus_id': cid})['status'], 'error')


if __name__ == '__main__':
    unittest.main()
