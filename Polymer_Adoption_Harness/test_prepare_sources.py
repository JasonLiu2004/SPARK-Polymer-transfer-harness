"""Check the public retrieval manifest and paginated exports without calling a provider."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import corpus
import prepare_sources as retrieval
from common import seal


class SourceTests(TestCase):
    def test_manifest_covers_each_registered_input_once(self):
        expected = [path for stream in ("broad", "spe", "independent") for path in corpus.raw_paths(stream)]
        records = list(retrieval.sources())
        paths = [path for path, _, _, _ in records]
        self.assertEqual(len(paths), 40)
        self.assertCountEqual(paths, expected)
        self.assertEqual(len(set(paths)), len(paths))
        for path, source, query, _ in records:
            if source == corpus.JOURNAL:
                self.assertIn("from-pub-date:" + path.stem, query)
            else:
                self.assertEqual(source, corpus.PMC)
                start, stop = path.stem.split("_")
                self.assertIn(f"FIRST_PDATE:[{start}-01-01 TO {stop}-12-31]", query)

    def test_check_verifies_seals_and_queries_without_fetching(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "2000.json"
            fetch = Mock(side_effect=AssertionError("unexpected network request"))
            manifest = [(path, corpus.JOURNAL, "registered", fetch)]
            with patch.object(retrieval, "sources", return_value=manifest), redirect_stdout(StringIO()):
                with self.assertRaisesRegex(SystemExit, "1 input snapshots missing"):
                    retrieval.prepare(check_only=True)
                seal(path, {"source": corpus.JOURNAL, "filter": "registered", "papers": {}})
                retrieval.prepare(check_only=True)
                with patch.object(retrieval, "sources", return_value=[(path, corpus.JOURNAL, "other", fetch)]):
                    with self.assertRaisesRegex(ValueError, "different query"):
                        retrieval.prepare(check_only=True)
                path.write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Checksum"):
                    retrieval.prepare(check_only=True)
            fetch.assert_not_called()

    def test_crossref_uses_earliest_date_and_refuses_incomplete_pages(self):
        item = {"DOI": "10.1/A", "title": ["Polymer"], "abstract": "<p>Film</p>",
                "published-online": {"date-parts": [[2004, 12]]},
                "published-print": {"date-parts": [[2005, 1]]}}
        complete = {"total-results": 1, "items": [item]}
        with patch.object(retrieval, "crossref_page", return_value=complete):
            paper = retrieval.journal(2005, "registered")["papers"]["10.1/a"]
        self.assertEqual((paper["year"], paper["abstract"]), (2004, "Film"))
        with patch.object(retrieval, "crossref_page", return_value={**complete, "total-results": 2}):
            with self.assertRaisesRegex(ValueError, "Incomplete Crossref"):
                retrieval.journal(2005, "registered")

    def test_europe_pmc_keeps_longer_same_doi_and_checks_cursor(self):
        item = {"source": "MED", "id": "1", "doi": "10.1/A", "title": "Polymer",
                "firstPublicationDate": "2016-05-10", "abstractText": "Film"}
        first = {"hitCount": 2, "nextCursorMark": "page2", "resultList": {"result": [item]}}
        second = {"hitCount": 2, "resultList": {"result": [{**item, "id": "2", "abstractText": "Solid film"}]}}
        with patch.object(retrieval, "get", side_effect=[first, second]) as query:
            result = retrieval.spe_query("registered", 2015, 2019)
        self.assertEqual(query.call_count, 2)
        self.assertEqual(result["hits"], 2)
        self.assertEqual(list(result["papers"]), ["10.1/a"])
        self.assertEqual(result["papers"]["10.1/a"]["abstract"], "Solid film")
        with patch.object(retrieval, "get", return_value={**first, "nextCursorMark": "*"}):
            with self.assertRaisesRegex(ValueError, "Incomplete Europe PMC"):
                retrieval.spe_query("registered", 2015, 2019)
