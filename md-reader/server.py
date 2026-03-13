"""
MD Reader -- Markdown 阅读器后端 (FastAPI)
启动: py -m uvicorn server:app --host 127.0.0.1 --port 8899
访问: http://localhost:8899
"""

import os
import json
import re
import string
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse

APP_VERSION = "2.0.0"
MODE = "local"

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_ROOT = str(PROJECT_ROOT.parent)

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".cursor",
    "venv", ".venv", "env",
}
MAX_SEARCH_RESULTS = 80
CONTEXT_CHARS = 120
_KEY_FILES = ["index.html", "server.py"]

_cfg = {"root": os.environ.get("MD_READER_ROOT", DEFAULT_ROOT)}
_server_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

app = FastAPI(title="MD Reader", version=APP_VERSION)


# ── Root directory ──────────────────────────────────────────

def get_root():
    return _cfg["root"]


def set_root(path: str):
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(p):
        return None
    _cfg["root"] = p
    return p


def _resolve_safe(rel_path: str):
    """Resolve relative path under root; return None if it escapes."""
    root_dir = get_root()
    safe = os.path.normpath(rel_path)
    full = os.path.normpath(os.path.join(root_dir, safe))
    if not (full == root_dir or full.startswith(root_dir + os.sep)):
        return None
    return full


# ── File operations ─────────────────────────────────────────

def scan_md_files():
    root_dir = get_root()
    files = []
    for dirpath, dirs, filenames in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.lower().endswith(".md"):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root_dir).replace("\\", "/")
                try:
                    stat = os.stat(full)
                except OSError:
                    continue
                files.append({
                    "path": rel,
                    "name": fn,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(
                        stat.st_mtime
                    ).strftime("%Y-%m-%d %H:%M"),
                })
    files.sort(key=lambda f: f["path"])
    return files


def read_md_file(rel_path: str):
    full = _resolve_safe(rel_path)
    if not full or not os.path.isfile(full) or not full.lower().endswith(".md"):
        return None
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def search_files(query: str):
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
            rel = os.path.relpath(full, root_dir).replace("\\", "/")
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
                matches.append({"offset": m.start(), "snippet": snippet})
                if len(matches) >= 5:
                    break
            if matches:
                results.append({"path": rel, "name": fn, "matches": matches})
                if len(results) >= MAX_SEARCH_RESULTS:
                    break
    return results


# ── Annotations ─────────────────────────────────────────────

def _annotations_path(md_rel_path: str):
    full = _resolve_safe(md_rel_path)
    if not full:
        return None
    return os.path.splitext(full)[0] + ".annotations.json"


def load_annotations(md_rel_path: str):
    apath = _annotations_path(md_rel_path)
    if not apath or not os.path.isfile(apath):
        return []
    try:
        with open(apath, "r", encoding="utf-8") as f:
            return json.load(f).get("annotations", [])
    except (json.JSONDecodeError, OSError):
        return []


def save_annotations(md_rel_path: str, annotations: list):
    apath = _annotations_path(md_rel_path)
    if not apath:
        return False
    with open(apath, "w", encoding="utf-8") as f:
        json.dump({"annotations": annotations}, f, ensure_ascii=False, indent=2)
    return True


# ── Directory browsing ──────────────────────────────────────

def browse_dirs(path: str = ""):
    if not path:
        if os.name == "nt":
            drives = []
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.isdir(drive):
                    drives.append({"name": f"{letter}:", "path": f"{letter}:/"})
            return {"parent": "", "current": "", "dirs": drives}
        else:
            path = "/"

    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        return {"error": f"Not a directory: {path}"}

    parent = os.path.dirname(path)
    if parent == path:
        parent = ""

    dirs = []
    try:
        for entry in sorted(os.scandir(path), key=lambda e: e.name.lower()):
            if not entry.is_dir():
                continue
            if entry.name.startswith(".") or entry.name in SKIP_DIRS:
                continue
            dirs.append({
                "name": entry.name,
                "path": entry.path.replace("\\", "/"),
            })
    except PermissionError:
        pass

    return {
        "parent": parent.replace("\\", "/"),
        "current": path.replace("\\", "/"),
        "dirs": dirs,
    }


# ══════════════════════════════════════════════════════════════
#  API Routes
# ══════════════════════════════════════════════════════════════

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "MD Reader", "version": APP_VERSION}


@app.get("/api/version")
def get_version():
    files = {}
    latest = 0.0
    for f in _KEY_FILES:
        try:
            mtime = os.path.getmtime(os.path.join(PROJECT_ROOT, f))
            files[f] = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            latest = max(latest, mtime)
        except OSError:
            pass
    return {
        "app_version": APP_VERSION,
        "server_start": _server_start_time,
        "last_update": datetime.fromtimestamp(latest).strftime(
            "%m/%d %H:%M"
        ) if latest else "",
        "last_update_ts": int(latest) if latest else 0,
        "files": files,
    }


@app.get("/api/root")
def api_get_root():
    return {"root": get_root()}


@app.post("/api/set-root")
async def api_set_root(body: dict):
    new_root = body.get("root", "")
    result = set_root(new_root)
    if result:
        return {"ok": True, "root": result}
    return JSONResponse(
        {"error": f"Directory not found: {new_root}"}, status_code=400,
    )


@app.get("/api/browse-dirs")
def api_browse_dirs(path: str = ""):
    return browse_dirs(path)


@app.get("/api/files")
def api_files():
    return scan_md_files()


@app.get("/api/file")
def api_file(path: str = ""):
    content = read_md_file(path)
    if content is None:
        return JSONResponse({"error": "File not found"}, status_code=404)
    return {"path": path, "content": content}


@app.get("/api/search")
def api_search(q: str = ""):
    return search_files(q)


@app.get("/api/annotations")
def api_get_annotations(path: str = ""):
    return load_annotations(path)


@app.post("/api/annotations")
async def api_save_annotation(body: dict):
    md_path = body.get("path", "")
    annotation = body.get("annotation")
    if not md_path or not annotation:
        return JSONResponse(
            {"error": "Missing path or annotation"}, status_code=400,
        )
    annos = load_annotations(md_path)
    existing = next(
        (a for a in annos if a.get("id") == annotation.get("id")), None,
    )
    if existing:
        existing.update(annotation)
        existing["updated"] = datetime.now().isoformat()
    else:
        annotation["created"] = datetime.now().isoformat()
        annotation["updated"] = annotation["created"]
        annos.append(annotation)
    save_annotations(md_path, annos)
    return {"ok": True, "annotations": annos}


@app.post("/api/annotations/delete")
async def api_delete_annotation(body: dict):
    md_path = body.get("path", "")
    anno_id = body.get("id", "")
    if not md_path or not anno_id:
        return JSONResponse(
            {"error": "Missing path or id"}, status_code=400,
        )
    annos = load_annotations(md_path)
    annos = [a for a in annos if a.get("id") != anno_id]
    save_annotations(md_path, annos)
    return {"ok": True, "annotations": annos}


# ── Static file serving ─────────────────────────────────────

@app.get("/", response_class=FileResponse)
@app.get("/index.html", response_class=FileResponse)
def serve_index():
    filepath = PROJECT_ROOT / "index.html"
    if not filepath.is_file():
        return JSONResponse({"error": "index.html not found"}, status_code=404)
    resp = FileResponse(str(filepath), media_type="text/html")
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


# ── Entry point ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="MD Reader server")
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind address (default: 127.0.0.1, use 0.0.0.0 for LAN)",
    )
    parser.add_argument(
        "--port", type=int, default=8899,
        help="Port (default: 8899)",
    )
    parser.add_argument(
        "--root", default="",
        help="Root directory for .md files",
    )
    args = parser.parse_args()

    if args.root:
        result = set_root(args.root)
        if not result:
            print(f"[ERROR] Not a valid directory: {args.root}")
            raise SystemExit(1)

    print(f"MD Reader v{APP_VERSION}")
    print(f"Root: {get_root()}")
    uvicorn.run(app, host=args.host, port=args.port)
