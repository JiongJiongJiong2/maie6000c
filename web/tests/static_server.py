"""Serve the workspace's browser routes for tests with mocked APIs."""

from argparse import ArgumentParser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
PAGE_FILES = {
    "/web": "/web/home.html",
    "/web/search": "/web/index.html",
    "/web/library": "/web/index.html",
}


class WorkspaceHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        page = PAGE_FILES.get(urlsplit(path).path.rstrip("/"), path)
        return super().translate_path(page)


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    handler = partial(WorkspaceHandler, directory=ROOT)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        server.serve_forever()
