import json
import os
import re
import sqlite3
import time
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs

from . import comments

ROUTE = "/api/blog-views"
WINDOW_MS = 30 * 60 * 1000
MAX_BODY = 512
ARTICLE = re.compile(r"posts/[a-z0-9][a-z0-9-]{0,63}")


class ViewCounts:
    def __init__(self, database):
        self.database = database
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS totals (
                    page TEXT PRIMARY KEY,
                    total INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recent (
                    visitor BLOB PRIMARY KEY,
                    counted_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS recent_by_time ON recent (counted_at);
            """)

    def connect(self):
        return sqlite3.connect(self.database, timeout=5)

    @staticmethod
    def total(db, page):
        row = db.execute("SELECT total FROM totals WHERE page = ?", (page,)).fetchone()
        return 0 if row is None else row[0]

    def read(self, page):
        with closing(self.connect()) as db:
            return self.total(db, page)

    def record(self, page, visitor, now=None):
        digest = sha256(f"{page}\0{visitor}".encode()).digest()
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            counted_at = time.time_ns() // 1_000_000 if now is None else now
            db.execute("DELETE FROM recent WHERE counted_at <= ?", (counted_at - WINDOW_MS,))
            added = db.execute(
                "INSERT INTO recent VALUES (?, ?) ON CONFLICT(visitor) DO NOTHING",
                (digest, counted_at),
            ).rowcount
            if added:
                db.execute("""
                    INSERT INTO totals VALUES (?, 1)
                    ON CONFLICT(page) DO UPDATE SET total = total + 1
                """, (page,))
            return self.total(db, page)


class BlogAPI:
    def __init__(self, database, pages, origin):
        self.counts = ViewCounts(database)
        self.comments = comments.CommentStore(self.counts.connect)
        self.pages = pages
        self.origin = origin

    def known_page(self, page):
        if not isinstance(page, str):
            return False
        if page == "home":
            return (self.pages / "index.html").is_file()
        return bool(ARTICLE.fullmatch(page) and (self.pages / page / "index.html").is_file())

    def __call__(self, env, start):
        origin = env.get("HTTP_ORIGIN", "")
        method = env["REQUEST_METHOD"]
        route = env["PATH_INFO"]
        headers = [("Cache-Control", "no-store"), ("Vary", "Origin")]
        if origin == self.origin:
            headers.append(("Access-Control-Allow-Origin", self.origin))

        def respond(status, data=None, extra=()):
            body = b"" if data is None else json.dumps(data).encode()
            body_headers = () if data is None else (
                ("Content-Length", str(len(body))),
                ("Content-Type", "application/json"),
            )
            start(status, [*headers, *extra, *body_headers])
            return [body]

        if route not in (ROUTE, comments.ROUTE, comments.INBOX_ROUTE):
            return respond("404 Not Found")
        if origin != self.origin and (origin or method != "GET"):
            return respond("403 Forbidden")
        if method == "OPTIONS":
            return respond("204 No Content", extra=(
                ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                ("Access-Control-Allow-Headers", "Content-Type"),
            ))
        if method not in {"GET", "POST"}:
            return respond("405 Method Not Allowed", extra=(("Allow", "GET, POST, OPTIONS"),))

        reading = method == "GET"
        discussion = route == comments.ROUTE
        if reading:
            try:
                query = parse_qs(env.get("QUERY_STRING", ""), max_num_fields=2 if discussion else 1)
            except ValueError:
                return respond("400 Bad Request")
            data = {key: values[0] for key, values in query.items()}
        else:
            if env.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
                return respond("415 Unsupported Media Type")
            try:
                size = int(env.get("CONTENT_LENGTH") or "0")
                maximum = comments.MAX_BODY if discussion else MAX_BODY
                if not 0 < size <= maximum:
                    return respond("400 Bad Request")
                data = json.loads(env["wsgi.input"].read(size))
            except (ValueError, UnicodeError):
                return respond("400 Bad Request")
            if not isinstance(data, dict):
                return respond("400 Bad Request")

        if route == comments.INBOX_ROUTE:
            if reading:
                return respond("405 Method Not Allowed", extra=(("Allow", "POST, OPTIONS"),))
            try:
                return respond("200 OK", self.comments.inbox(data))
            except ValueError:
                return respond("400 Bad Request")
        page = data.get("page")
        if not self.known_page(page) or (discussion and page == "home"):
            return respond("404 Not Found")

        if discussion:
            if not reading:
                try:
                    comment = self.comments.add(page, data)
                except ValueError:
                    return respond("400 Bad Request")
                return respond("200 OK", comment)
            try:
                if "comment" in data:
                    target = int(data["comment"])
                    if not 0 < target <= comments.MAX_ID:
                        return respond("400 Bad Request")
                    thread = self.comments.linked_comment(page, target)
                    return respond("200 OK", thread) if thread["comments"] else respond("404 Not Found")
                after = int(data.get("after", "0"))
                if not 0 <= after <= comments.MAX_ID:
                    return respond("400 Bad Request")
            except ValueError:
                return respond("400 Bad Request")
            return respond("200 OK", self.comments.read(page, after))

        if reading:
            return respond("200 OK", {"total": self.counts.read(page)})
        visitor = data.get("visitor")
        if not isinstance(visitor, str) or not comments.UUID4.fullmatch(visitor):
            return respond("400 Bad Request")
        return respond("200 OK", {"total": self.counts.record(page, visitor)})


def create_app():
    return BlogAPI(
        os.environ["BLOG_VIEWS_DATABASE"],
        Path(os.environ["BLOG_VIEWS_SITE_ROOT"]),
        os.environ.get("BLOG_VIEWS_ORIGIN", "https://lehaifeng000.github.io"),
    )
