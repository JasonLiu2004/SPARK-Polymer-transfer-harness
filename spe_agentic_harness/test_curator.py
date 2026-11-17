import tempfile
import unittest
from pathlib import Path
from curator import Corpus, run, validate


class CuratorTests(unittest.TestCase):
    def test_units_and_fabricated_quote(self):
        rec = {'id': 'a', 'conductivity': {'value': 2, 'unit': 'mS/cm',
               'evidence': [{'source': 'S1', 'page': 1, 'quote': '2 mS/cm'}]}}
        issues, rows = validate([rec], {('S1', 1): 'Measured 2 mS/cm.'})
        self.assertEqual(rows[0]['conductivity_S_cm'], .002)
        self.assertFalse(any(x['issue'] == 'quote_not_in_observed_page' for x in issues))
        issues, _ = validate([rec], {('S1', 1): 'No measurement.'})
        self.assertTrue(any(x['issue'] == 'quote_not_in_observed_page' for x in issues))

    def test_retrieve_then_stop_and_budget(self):
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / 'paper.pdf'
            doc = fitz.open()
            doc.new_page().insert_text((72, 72), 'Polymer electrolyte conductivity 2 mS/cm at 25 C.')
            doc.save(pdf)
            doc.close()
            corpus = Corpus([pdf])
            calls = []
            def fake(state):
                calls.append(state)
                action = {'tool': 'read_page', 'source': 'S1', 'page': 1} if len(calls) == 1 else {'tool': 'finish'}
                return {'records': [], 'action': action}, {}
            result = run(corpus, fake, Path(tmp) / 'run', 3)
            self.assertEqual(result['calls'], 2)
            self.assertEqual(result['status'], 'finished_with_issues')
            result = run(corpus, lambda s: ({'action': {'tool': 'search', 'query': 'salt'}}, {}), Path(tmp) / 'limited', 1)
            self.assertEqual(result['status'], 'budget_exhausted')
            self.assertEqual(result['calls'], 1)

    def test_malformed_record_does_not_crash(self):
        issues, _ = validate([None, {'id': [], 'temperature': {'value': 'warm'}}], {})
        self.assertTrue(issues)


if __name__ == '__main__':
    unittest.main()
