"""
MD Reader — 轻量 Markdown 阅读器后端
启动: python server.py
访问: http://localhost:8899
"""

import os
import json
import re
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path
from datetime import datetime

PORT = 8899
WORKSPACE = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".cursor", "venv", ".venv", "env",
}
MAX_SEARCH_RESULTS = 80
CONTEXT_CHARS = 120


def scan_md_files():
    """扫描工作空间所有 .md 文件，返回树形结构"""
    files = []
    for root, dirs, filenames in os.walk(WORKSPACE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.lower().endswith(".md"):
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, WORKSPACE)
                stat = os.stat(full)
                files.append({
                    "path": rel,
                    "name": fn,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
    files.sort(key=lambda f: f["path"])
    return files


def read_md_file(rel_path: str):
    """读取指定 .md 文件内容"""
    safe = os.path.normpath(rel_path)
    if safe.startswith("..") or os.path.isabs(safe):
        return None
    full = os.path.join(WORKSPACE, safe)
    if not os.path.isfile(full) or not full.endswith(".md"):
        return None
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def search_files(query: str):
    """全文搜索：在所有 .md 文件中搜索关键词"""
    if not query or len(query) < 2:
        return []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results = []
    for root, dirs, filenames in os.walk(WORKSPACE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.lower().endswith(".md"):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, WORKSPACE)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except (OSError, PermissionError):
                continue
            matches = []
            for m in pattern.finditer(content):
                start = max(0, m.start() - CONTEXT_CHARS)
                end = min(len(content), m.end() + CONTEXT_CHARS)
                snippet = content[start:end].replace("\n", " ")
                if start > 0:
                    snippet = "..." + snippet
                if end < len(content):
                    snippet = snippet + "..."
                matches.append({
                    "offset": m.start(),
                    "snippet": snippet,
                })
                if len(matches) >= 5:
                    break
            if matches:
                results.append({"path": rel, "name": fn, "matches": matches})
                if len(results) >= MAX_SEARCH_RESULTS:
                    break
    return results


class MDReaderHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/api/files":
            self._json_response(scan_md_files())
        elif path == "/api/file":
            rel = qs.get("path", [""])[0]
            content = read_md_file(unquote(rel))
            if content is None:
                self._json_response({"error": "File not found"}, 404)
            else:
                self._json_response({"path": rel, "content": content})
        elif path == "/api/search":
            q = qs.get("q", [""])[0]
            self._json_response(search_files(unquote(q)))
        elif path == "/" or path == "/index.html":
            self._serve_file("index.html", "text/html")
        else:
            self._json_response({"error": "Not found"}, 404)

    def _json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filename, content_type):
        filepath = os.path.join(os.path.dirname(__file__), filename)
        if not os.path.isfile(filepath):
            self._json_response({"error": "File not found"}, 404)
            return
        with open(filepath, "r", encoding="utf-8") as f:
            body = f.read().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), MDReaderHandler)
    print(f"MD Reader started at http://localhost:{PORT}")
    print(f"Workspace: {WORKSPACE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
