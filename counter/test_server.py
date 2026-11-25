import io
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from counter.server import ROUTE, WINDOW_MS, ViewsAPI

PAGES = Path(__file__).resolve().parents[1] / "docs"
ORIGIN = "https://lehaifeng000.github.io"


class ViewCounterTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "views.sqlite3"
        self.api = ViewsAPI(self.database, PAGES, ORIGIN)
        self.visitor = str(uuid4())

    def request(self, method, page="home", origin=ORIGIN, visitor=None):
        response = {}
        body = json.dumps({"page": page, "visitor": visitor or self.visitor}).encode()

        def start(status, headers):
            response.update(status=status, headers=dict(headers))

        payload = self.api({
            "REQUEST_METHOD": method,
            "PATH_INFO": ROUTE,
            "QUERY_STRING": f"page={page}" if method == "GET" else "",
            "HTTP_ORIGIN": origin,
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/json",
            "wsgi.input": io.BytesIO(body),
        }, start)
        response["data"] = json.loads(payload[0]) if payload[0] else None
        return response

    def test_window_is_per_page_and_starts_at_counted_open(self):
        counts = self.api.counts
        self.assertEqual(counts.record("home", self.visitor, now=10), 1)
        self.assertEqual(counts.record("home", self.visitor, now=11), 1)
        self.assertEqual(counts.record("home", self.visitor, now=9 + WINDOW_MS), 1)
        self.assertEqual(counts.record("posts/keydebounce", self.visitor, now=9 + WINDOW_MS), 1)
        self.assertEqual(counts.record("home", self.visitor, now=10 + WINDOW_MS), 2)
        self.assertEqual(counts.read("posts/keydebounce"), 1)
        self.assertEqual(counts.record("home", str(uuid4()), now=10 + WINDOW_MS), 3)

    def test_concurrent_requests_and_restart(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.request("POST")["data"]["total"], range(24)))
        self.assertEqual(results, [1] * 24)
        restarted = ViewsAPI(self.database, PAGES, ORIGIN)
        self.assertEqual(restarted.counts.record("home", self.visitor), 1)
        with closing(sqlite3.connect(self.database)) as db:
            keys = db.execute("SELECT visitor FROM recent").fetchall()
        self.assertEqual(len(keys), 1)
        self.assertIsInstance(keys[0][0], bytes)
        self.assertNotIn(self.visitor.encode(), keys[0][0])

    def test_http_validation_and_read_only(self):
        self.assertEqual(self.request("GET", origin="")["data"], {"total": 0})
        self.assertEqual(self.request("POST", origin="")["status"], "403 Forbidden")
        self.assertEqual(self.request("POST", origin="https://elsewhere.test")["status"], "403 Forbidden")
        self.assertEqual(self.request("POST", page="posts/not-on-the-blog")["status"], "404 Not Found")
        self.assertEqual(self.request("POST", visitor="nope")["status"], "400 Bad Request")
        self.assertEqual(self.request("OPTIONS")["headers"]["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(self.request("POST", page="posts/numpy-bp")["data"], {"total": 1})
        self.assertEqual(self.request("GET", page="posts/numpy-bp")["data"], {"total": 1})
        self.assertEqual(self.request("GET")["data"], {"total": 0})


if __name__ == "__main__":
    unittest.main()
