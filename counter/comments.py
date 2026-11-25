import re
import time
from contextlib import closing
from hashlib import sha256
from urllib.parse import urlsplit

ROUTE = "/api/blog-comments"
INBOX_ROUTE = "/api/blog-replies"
MAX_BODY = 10 * 1024
PAGE_SIZE = 50
INBOX_SIZE = 30
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


def visitor_digest(visitor):
    if not isinstance(visitor, str) or not UUID4.fullmatch(visitor):
        raise ValueError("invalid visitor key")
    return sha256(visitor.encode("ascii")).digest()


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
                CREATE TABLE IF NOT EXISTS comment_tracking (
                    comment_id INTEGER PRIMARY KEY REFERENCES comments(id),
                    owner BLOB,
                    recipient BLOB,
                    seen INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS comments_for_recipient ON comment_tracking (recipient, comment_id);
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

    def linked_comment(self, page, comment_id):
        with closing(self.connect()) as db:
            rows = db.execute(f"""
                WITH RECURSIVE thread (id, parent_id) AS (
                    SELECT id, parent_id FROM comments WHERE page = ? AND id = ?
                    UNION ALL
                    SELECT c.id, c.parent_id FROM comments c JOIN thread t ON c.id = t.parent_id
                    WHERE c.page = ?
                    LIMIT 100
                )
                SELECT {FIELDS} FROM comments
                WHERE id IN (SELECT id FROM thread) ORDER BY id
            """, (page, comment_id, page)).fetchall()
        return {"comments": [serialize(row) for row in rows]}

    def inbox(self, data):
        owner = visitor_digest(data.get("visitor"))
        read = data.get("read")
        before = data.get("before", MAX_ID)
        if type(before) is not int or not 0 < before <= MAX_ID:
            raise ValueError("invalid inbox cursor")
        if read is not None and (type(read) is not int or not 0 < read <= MAX_ID):
            raise ValueError("invalid notification")

        with closing(self.connect()) as db, db:
            db.execute("BEGIN" if read is None else "BEGIN IMMEDIATE")
            if read is not None:
                db.execute(
                    "UPDATE comment_tracking SET seen = 1 WHERE recipient = ? AND comment_id = ?",
                    (owner, read),
                )
            unread = db.execute(
                "SELECT count(*) FROM comment_tracking WHERE recipient = ? AND seen = 0", (owner,)
            ).fetchone()[0]
            if read is not None:
                return {"unread": unread}

            qualified_fields = ", ".join("c." + field for field in FIELDS.split(", "))
            rows = db.execute(f"""
                SELECT {qualified_fields}, c.page, t.seen
                FROM comment_tracking t JOIN comments c ON c.id = t.comment_id
                WHERE t.recipient = ? AND t.comment_id < ?
                ORDER BY t.comment_id DESC LIMIT ?
            """, (owner, before, INBOX_SIZE + 1)).fetchall()
        return {
            "replies": [
                {**serialize(row), "page": row[-2], "seen": bool(row[-1])}
                for row in rows[:INBOX_SIZE]
            ],
            "unread": unread,
            "next": rows[INBOX_SIZE - 1][0] if len(rows) > INBOX_SIZE else None,
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
        visitor = data.get("visitor")
        owner = None if visitor is None else visitor_digest(visitor)
        name, message = name.strip(), message.strip()
        if not message or len(message) > 2000 or any(ord(char) < 32 and char not in "\n\t" for char in message):
            raise ValueError("invalid message")
        if kind == "github":
            name = github_name(name)
        elif len(name) > 30 or any(ord(char) < 32 for char in name):
            raise ValueError("invalid nickname")
        if kind == "guest" and not name and owner is not None:
            name = "游客" + owner.hex()[:8].upper()
        # Reject unpaired surrogates from hand-crafted JSON before writing to SQLite.
        name.encode("utf-8")
        message.encode("utf-8")

        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            recipient = None
            if parent is not None:
                target = db.execute("""
                    SELECT t.owner FROM comments c
                    LEFT JOIN comment_tracking t ON t.comment_id = c.id
                    WHERE c.id = ? AND c.page = ?
                """, (parent, page)).fetchone()
                if target is None:
                    raise ValueError("reply target is not on this page")
                if target[0] != owner:
                    recipient = target[0]
            inserted = db.execute("""
                INSERT INTO comments (page, parent_id, kind, name, message, created_at, submission)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(page, submission) DO NOTHING
            """, (page, parent, kind, name, message, int(time.time()), submission))
            if inserted.rowcount:
                db.execute(
                    "INSERT INTO comment_tracking (comment_id, owner, recipient) VALUES (?, ?, ?)",
                    (inserted.lastrowid, owner, recipient),
                )
            row = db.execute(
                f"SELECT {FIELDS} FROM comments WHERE page = ? AND submission = ?",
                (page, submission),
            ).fetchone()
            return serialize(row)
