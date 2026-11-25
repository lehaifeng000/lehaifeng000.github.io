"""Run the static blog and counter together on loopback for review."""

import argparse
import mimetypes
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from .server import ROUTE, ViewsAPI

PAGES = Path(__file__).resolve().parents[1] / "docs"


class PreviewServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    host = "127.0.0.1"
    origin = f"http://{host}:{args.port}"
    api = ViewsAPI(args.database, PAGES, origin)

    def preview(env, start):
        if env["PATH_INFO"] == ROUTE:
            return api(env, start)
        path = (PAGES / env["PATH_INFO"].lstrip("/")).resolve()
        if path.is_dir():
            path = path / "index.html"
        if path.is_relative_to(PAGES) and path.is_file():
            body = path.read_bytes()
            kind = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if kind.startswith("text/"):
                kind += "; charset=utf-8"
            start("200 OK", [("Content-Type", kind), ("Content-Length", str(len(body)))])
            return [body]
        start("404 Not Found", [("Content-Length", "0")])
        return [b""]

    with make_server(host, args.port, preview, server_class=PreviewServer) as server:
        print(f"Blog counter preview at {origin}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
