import re
import time
from contextlib import closing
from urllib.parse import urlsplit

ROUTE = "/api/blog-comments"
MAX_BODY = 10 * 1024
PAGE_SIZE = 50
MAX_ID = 2**53 - 1
GITHUB = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.IGNORECASE | re.ASCII)
UUID4 = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")
FIELDS = "id, parent_id, kind, name, message, created_at"


def github_name(value):
    if value.startswith(("https://", "http://")):
        link = urlsplit(value)
        if link.netloc.lower() not in {"github.com", "www.github.com"}:
            raise ValueError("invalid GitHub profile URL")
        value = link.path.strip("/")
    else:
        value = value.removeprefix("@")
    if len(value) > 39 or not GITHUB.fullmatch(value):
        raise ValueError("invalid GitHub username")
    return value


def serialize(row):
    return dict(zip(FIELDS.split(", "), row))


class CommentStore:
    def __init__(self, connect):
        self.connect = connect
        with closing(self.connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY,
                    page TEXT NOT NULL,
                    parent_id INTEGER REFERENCES comments(id),
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    submission TEXT NOT NULL,
                    UNIQUE (page, submission)
                );
                CREATE INDEX IF NOT EXISTS comments_by_page ON comments (page, id);
            """)

    def read(self, page, after):
        with closing(self.connect()) as db:
            rows = db.execute(f"""
                SELECT {FIELDS} FROM comments
                WHERE page = ? AND id > ? ORDER BY id LIMIT ?
            """, (page, after, PAGE_SIZE + 1)).fetchall()
        return {
            "comments": [serialize(row) for row in rows[:PAGE_SIZE]],
            "next": rows[PAGE_SIZE - 1][0] if len(rows) > PAGE_SIZE else None,
        }

    def add(self, page, data):
        parent = data.get("parent_id")
        kind, name = data.get("kind"), data.get("name")
        message, submission = data.get("message"), data.get("submission")
        if parent is not None and (type(parent) is not int or not 0 < parent <= MAX_ID):
            raise ValueError("invalid reply target")
        if kind not in ("guest", "github") or not isinstance(name, str) or not isinstance(message, str):
            raise ValueError("invalid comment")
        if not isinstance(submission, str) or not UUID4.fullmatch(submission):
            raise ValueError("invalid submission key")
        name, message = name.strip(), message.strip()
        if not message or len(message) > 2000 or any(ord(char) < 32 and char not in "\n\t" for char in message):
            raise ValueError("invalid message")
        if kind == "github":
            name = github_name(name)
        elif len(name) > 30 or any(ord(char) < 32 for char in name):
            raise ValueError("invalid nickname")
        # Reject unpaired surrogates from hand-crafted JSON before writing to SQLite.
        name.encode("utf-8")
        message.encode("utf-8")

        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if parent is not None and db.execute(
                "SELECT 1 FROM comments WHERE id = ? AND page = ?", (parent, page)
            ).fetchone() is None:
                raise ValueError("reply target is not on this page")
            db.execute("""
                INSERT INTO comments (page, parent_id, kind, name, message, created_at, submission)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(page, submission) DO NOTHING
            """, (page, parent, kind, name, message, int(time.time()), submission))
            row = db.execute(
                f"SELECT {FIELDS} FROM comments WHERE page = ? AND submission = ?",
                (page, submission),
            ).fetchone()
            return serialize(row)
