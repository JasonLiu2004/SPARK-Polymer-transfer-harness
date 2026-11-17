import tempfile
from pathlib import Path
import unittest
from knowledge import KnowledgeStore


class KnowledgeTests(unittest.TestCase):
    def test_persistence_dedup_project_and_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'memory.sqlite'
            store = KnowledgeStore(path)
            result = {'sources': [{'source': 'S1', 'sha256': 'fixture-hash'}],
                      'records': [{'id': 'A', 'polymer': {'value': 'PEO', 'evidence': []}}], 'issues': []}
            a = store.ingest('p1', result, {'model': 'test'})
            self.assertFalse(store.ingest('p1', result, {'model': 'test'})['inserted'])
            reopened = KnowledgeStore(path)
            self.assertEqual(len(reopened.query('p1', 'PEO')), 1)
            self.assertEqual(reopened.query('p2', 'PEO'), [])
            with self.assertRaises(ValueError):
                reopened.get('p2', a['snapshot_id'])
            result['records'][0]['polymer']['value'] = 'PAN'
            b = reopened.ingest('p1', result, {'model': 'test'})
            self.assertNotEqual(a['snapshot_id'], b['snapshot_id'])
            self.assertEqual(reopened.get('p1', a['snapshot_id'])['result']['records'][0]['polymer']['value'], 'PEO')
            self.assertEqual(reopened.query('p1', 'PAN')[0]['state'], 'unreviewed_extraction')


if __name__ == '__main__':
    unittest.main()
