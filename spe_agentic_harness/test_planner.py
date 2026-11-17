import json
from pathlib import Path
import tempfile
import unittest

from harness import ResearchHarness
from planner import run_planner


class PlannerTests(unittest.TestCase):
    def test_error_feedback_and_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = ResearchHarness(tmp)
            def model(state):
                n = len(state['history'])
                self.assertTrue(state['tools'])
                if n == 0:
                    return {'action': {'tool': 'predict_conductivity', 'arguments': {}}}, {}
                if n == 1:
                    self.assertEqual(state['history'][-1]['observation']['status'], 'error')
                    return {'action': {'tool': 'query_knowledge', 'arguments': {'text': 'PEO'}}}, {}
                self.assertEqual(state['history'][-1]['observation']['status'], 'ok')
                return {'action': {'tool': 'finish'}, 'answer': 'No records; prediction tool unavailable.'}, {}
            result = run_planner(h, model, 'Find PEO')
            self.assertEqual(result['status'], 'finished')
            self.assertEqual(result['model_calls'], 3)
            self.assertEqual(result['tool_calls'], 2)
            self.assertEqual(json.loads((Path(tmp) / 'planner_result.json').read_text()), result)

    def test_shared_extraction_budget(self):
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / 'paper.pdf'
            doc = fitz.open()
            doc.new_page().insert_text((72, 72), 'PEO polymer electrolyte')
            doc.save(pdf)
            doc.close()
            h = ResearchHarness(Path(tmp) / 'run', max_model_calls=2,
                client=lambda state: ({'records': [], 'action': {'tool': 'finish'}}, {}))
            cid = h.execute('open_corpus', {'paths': [str(pdf)]})['data']['corpus_id']
            def model(state):
                return {'action': {'tool': 'extract_records', 'arguments': {'corpus_id': cid, 'max_calls': 5}}}, {}
            result = run_planner(h, model, 'Extract')
            self.assertEqual(result['status'], 'model_budget_exhausted')
            self.assertEqual(result['model_calls'], 2)
            self.assertEqual(result['steps'], 1)

    def test_malformed_response_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_planner(ResearchHarness(tmp), lambda state: ({'parse_error': 'bad'}, {}), 'Extract', 2)
            self.assertEqual(result['status'], 'step_limit')
            self.assertEqual(result['steps'], 2)

    def test_provider_failure_is_saved_without_error_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            def broken(state):
                raise RuntimeError('secret-test-sentinel')
            result = run_planner(ResearchHarness(tmp), broken, 'Extract')
            self.assertEqual(result['status'], 'planner_error')
            self.assertNotIn('secret-test-sentinel', (Path(tmp) / 'planner_trace.jsonl').read_text())


if __name__ == '__main__':
    unittest.main()
