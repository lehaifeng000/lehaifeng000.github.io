import io
import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from counter.comments import INBOX_ROUTE
from counter.comments import ROUTE as COMMENTS_ROUTE
from counter.server import ROUTE, WINDOW_MS, BlogAPI

PAGES = Path(__file__).resolve().parents[1] / "docs"
ORIGIN = "https://lehaifeng000.github.io"


class ViewCounterTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "views.sqlite3"
        self.api = BlogAPI(self.database, PAGES, ORIGIN)
        self.visitor = str(uuid4())

    def request(self, method, page="home", origin=ORIGIN, visitor=None, *, route=ROUTE, payload=None, query=""):
        response = {}
        body = json.dumps(payload or {"page": page, "visitor": visitor or self.visitor}).encode()

        def start(status, headers):
            response.update(status=status, headers=dict(headers))

        payload = self.api({
            "REQUEST_METHOD": method,
            "PATH_INFO": route,
            "QUERY_STRING": "&".join(filter(None, (f"page={page}", query))) if method == "GET" else "",
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
        restarted = BlogAPI(self.database, PAGES, ORIGIN)
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


    def test_guest_comment_and_github_reply(self):
        page = "posts/keydebounce"
        guest = {
            "page": page, "parent_id": None, "kind": "guest", "name": "",
            "message": "<strong>原样保存</strong>", "submission": str(uuid4()),
        }
        first = self.request("POST", page, route=COMMENTS_ROUTE, payload=guest)
        self.assertEqual(first["status"], "200 OK")
        self.assertEqual(first["data"]["message"], guest["message"])
        self.assertEqual(self.request("POST", page, route=COMMENTS_ROUTE, payload=guest), first)
        reply = {
            **guest, "parent_id": first["data"]["id"], "kind": "github",
            "name": "https://github.com/example-user?tab=repositories",
            "message": "回复测试", "submission": str(uuid4()),
        }
        second = self.request("POST", page, route=COMMENTS_ROUTE, payload=reply)
        self.assertEqual(second["status"], "200 OK")
        self.assertEqual(second["data"]["name"], "example-user")
        self.assertEqual(second["data"]["parent_id"], first["data"]["id"])
        self.assertEqual(
            self.request("GET", page, route=COMMENTS_ROUTE)["data"],
            {"comments": [first["data"], second["data"]], "next": None},
        )
        wrong_page = {**reply, "page": "posts/numpy-bp"}
        self.assertEqual(
            self.request("POST", wrong_page["page"], route=COMMENTS_ROUTE, payload=wrong_page)["status"],
            "400 Bad Request",
        )
        self.assertEqual(self.request("GET", route=COMMENTS_ROUTE)["status"], "404 Not Found")


    def test_inbox_only_notifies_the_visitor_who_wrote_the_parent(self):
        page = "posts/keydebounce"
        visitor, other, outsider = (str(uuid4()) for _ in range(3))

        def submit(token, parent_id=None):
            data = {
                "page": page, "parent_id": parent_id, "kind": "guest", "name": "",
                "message": "测试", "submission": str(uuid4()), "visitor": token,
            }
            reply = self.request("POST", page, route=COMMENTS_ROUTE, payload=data)
            self.assertEqual(reply["status"], "200 OK")
            return reply["data"]

        def inbox(token, **details):
            return self.request(
                "POST", route=INBOX_ROUTE, payload={"visitor": token, **details},
            )["data"]

        root = submit(visitor)
        self.assertRegex(root["name"], r"^游客[0-9A-F]{8}$")
        self_reply = submit(visitor, root["id"])
        self.assertEqual(self_reply["name"], root["name"])
        self.assertEqual(inbox(visitor)["unread"], 0)

        reply = submit(other, root["id"])
        self.assertNotEqual(reply["name"], root["name"])
        received = inbox(visitor)
        self.assertEqual(received["unread"], 1)
        self.assertEqual(received["replies"], [{**reply, "page": page, "seen": False}])
        self.assertEqual(inbox(outsider), {"replies": [], "unread": 0, "next": None})
        self.assertEqual(inbox(outsider, read=reply["id"]), {"unread": 0})
        self.assertEqual(inbox(visitor)["unread"], 1)
        self.assertEqual(inbox(visitor, read=reply["id"]), {"unread": 0})
        self.assertTrue(inbox(visitor)["replies"][0]["seen"])

        with patch("counter.comments.PAGE_SIZE", 1):
            first_page = self.request("GET", page, route=COMMENTS_ROUTE)["data"]
        self.assertEqual(first_page["comments"], [root])
        link = self.request("GET", page, route=COMMENTS_ROUTE, query=f"comment={reply['id']}")
        self.assertEqual(link["data"]["comments"], [root, reply])
        elsewhere = self.request("GET", "posts/numpy-bp", route=COMMENTS_ROUTE, query=f"comment={reply['id']}")
        self.assertEqual(elsewhere["status"], "404 Not Found")


if __name__ == "__main__":
    unittest.main()
