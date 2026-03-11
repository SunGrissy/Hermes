"""
MD Reader — 轻量 Markdown 阅读器后端
启动: python server.py [根目录路径]
访问: http://localhost:8899
"""

import os
import sys
import json
import re
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path
from datetime import datetime

PORT = 8899
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".cursor", "venv", ".venv", "env",
}
MAX_SEARCH_RESULTS = 80
CONTEXT_CHARS = 120

_cfg = {"root": str(Path(__file__).resolve().parent.parent)}


def get_root():
    return _cfg["root"]


def set_root(path):
    p = os.path.expanduser(path)
    p = os.path.abspath(p)
    if not os.path.isdir(p):
        return None
    _cfg["root"] = p
    return p


def scan_md_files():
    """扫描当前根目录下所有 .md 文件"""
    root_dir = get_root()
    files = []
    for dirpath, dirs, filenames in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.lower().endswith(".md"):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root_dir)
                try:
                    stat = os.stat(full)
                except OSError:
                    continue
                files.append({
                    "path": rel,
                    "name": fn,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
    files.sort(key=lambda f: f["path"])
    return files


def _resolve_safe(rel_path: str):
    """将相对路径解析为根目录下的绝对路径，越界返回 None"""
    root_dir = get_root()
    safe = os.path.normpath(rel_path)
    full = os.path.normpath(os.path.join(root_dir, safe))
    if not full.startswith(root_dir):
        return None
    return full


def read_md_file(rel_path: str):
    """读取指定 .md 文件内容"""
    full = _resolve_safe(rel_path)
    if not full or not os.path.isfile(full) or not full.endswith(".md"):
        return None
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def get_annotations_path(md_rel_path: str):
    """获取 .annotations.json 文件的绝对路径"""
    full = _resolve_safe(md_rel_path)
    if not full:
        return None
    base = os.path.splitext(full)[0]
    return base + ".annotations.json"


def load_annotations(md_rel_path: str):
    apath = get_annotations_path(md_rel_path)
    if not apath or not os.path.isfile(apath):
        return []
    try:
        with open(apath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("annotations", [])
    except (json.JSONDecodeError, OSError):
        return []


def save_annotations(md_rel_path: str, annotations: list):
    apath = get_annotations_path(md_rel_path)
    if not apath:
        return False
    with open(apath, "w", encoding="utf-8") as f:
        json.dump({"annotations": annotations}, f, ensure_ascii=False, indent=2)
    return True


def search_files(query: str):
    """全文搜索：在所有 .md 文件中搜索关键词"""
    if not query or len(query) < 2:
        return []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results = []
    root_dir = get_root()
    for dirpath, dirs, filenames in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.lower().endswith(".md"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root_dir)
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

        if path == "/api/root":
            self._json_response({"root": get_root()})
        elif path == "/api/files":
            self._json_response(scan_md_files())
        elif path == "/api/file":
            rel = qs.get("path", [""])[0]
            content = read_md_file(unquote(rel))
            if content is None:
                self._json_response({"error": "File not found"}, 404)
            else:
                self._json_response({"path": rel, "content": content})
        elif path == "/api/annotations":
            rel = qs.get("path", [""])[0]
            self._json_response(load_annotations(unquote(rel)))
        elif path == "/api/search":
            q = qs.get("q", [""])[0]
            self._json_response(search_files(unquote(q)))
        elif path == "/" or path == "/index.html":
            self._serve_file("index.html", "text/html")
        else:
            self._json_response({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/api/set-root":
            new_root = body.get("root", "")
            result = set_root(new_root)
            if result:
                self._json_response({"ok": True, "root": result})
            else:
                self._json_response({"error": f"Directory not found: {new_root}"}, 400)

        elif path == "/api/annotations":
            md_path = body.get("path", "")
            annotation = body.get("annotation")
            if not md_path or not annotation:
                self._json_response({"error": "Missing path or annotation"}, 400)
                return
            annos = load_annotations(md_path)
            existing = next((a for a in annos if a.get("id") == annotation.get("id")), None)
            if existing:
                existing.update(annotation)
                existing["updated"] = datetime.now().isoformat()
            else:
                annotation["created"] = datetime.now().isoformat()
                annotation["updated"] = annotation["created"]
                annos.append(annotation)
            save_annotations(md_path, annos)
            self._json_response({"ok": True, "annotations": annos})

        elif path == "/api/annotations/delete":
            md_path = body.get("path", "")
            anno_id = body.get("id", "")
            if not md_path or not anno_id:
                self._json_response({"error": "Missing path or id"}, 400)
                return
            annos = load_annotations(md_path)
            annos = [a for a in annos if a.get("id") != anno_id]
            save_annotations(md_path, annos)
            self._json_response({"ok": True, "annotations": annos})

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
    if len(sys.argv) > 1:
        custom = set_root(sys.argv[1])
        if not custom:
            print(f"[ERROR] Not a valid directory: {sys.argv[1]}")
            raise SystemExit(1)

    host = "127.0.0.1"
    try:
        server = HTTPServer((host, PORT), MDReaderHandler)
    except OSError as e:
        if e.errno == 48:
            print(f"[ERROR] Port {PORT} already in use. Kill the old process or change PORT.")
        elif e.errno == 49:
            print(f"[ERROR] Cannot bind to {host}:{PORT}. Try: python3 server.py")
        else:
            print(f"[ERROR] {e}")
        raise SystemExit(1)
    print(f"MD Reader started at http://localhost:{PORT}")
    print(f"Root: {get_root()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
