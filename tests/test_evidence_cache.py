import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from analyzer_core import evidence_cache as cache


class EvidenceCacheTests(TestCase):
    def test_credentials_filters_and_paging_are_separate_and_corrupt_cache_is_ignored(self):
        with TemporaryDirectory() as directory, patch.object(cache, "ROOT", Path(directory)):
            @cache.with_evidence_cache
            def check():
                query="query { reportData { report { events() } } }"
                credentials=SimpleNamespace(client_id="a", client_secret="secret-a")
                path=cache.query_cache_path("host",credentials,query,{"code":"report","start":1,"filter":"A"})
                cache.write_cached(path,{"events":[1]})
                self.assertEqual(cache.read_cached(path),{"events":[1]})
                for variables in ({"code":"report","start":2,"filter":"A"},{"code":"report","start":1,"filter":"B"}):
                    self.assertIsNone(cache.read_cached(cache.query_cache_path("host",credentials,query,variables)))
                other=SimpleNamespace(client_id="a",client_secret="secret-b")
                self.assertNotEqual(path,cache.query_cache_path("host",other,query,{"code":"report","start":1,"filter":"A"}))
                self.assertNotIn("secret",str(path))
                path.write_text("incomplete",encoding="utf-8")
                self.assertIsNone(cache.read_cached(path))
                self.assertEqual(cache.current_stats()["cacheHits"],1)
            check()

    def test_force_and_expiry_reject_cached_evidence(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/"cache.json"
            @cache.with_evidence_cache
            def check(force=False):
                cache.write_cached(path,{"ok":True})
                if force:
                    self.assertIsNone(cache.read_cached(path))
                else:
                    os.utime(path,(1,1))
                    self.assertIsNone(cache.read_cached(path))
            check()
            check(force=True)

    def test_no_scope_and_non_report_queries_are_never_cached(self):
        credentials=SimpleNamespace(client_id="a",client_secret="b")
        self.assertIsNone(cache.query_cache_path("host",credentials,"reportData",{"code":"r"}))
