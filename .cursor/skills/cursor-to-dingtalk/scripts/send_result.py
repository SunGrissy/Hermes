# -*- coding: utf-8 -*-
"""
把一段文本通过 dingtalk-desktop daemon 发到钉钉。
用法:
  echo "内容" | python send_result.py
  python send_result.py "内容"
"""
import os
import sys
import json
import urllib.request
import urllib.error

def _workspace_root():
    """从脚本位置推到工作空间根目录（含 .cursor/skills 的上级）。"""
    here = os.path.abspath(os.path.dirname(__file__))
    # scripts -> cursor-to-dingtalk -> skills -> .cursor -> root
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))

def _load_default_cid():
    """从 dingtalk-desktop/digest_config.json 读 notify_target。"""
    root = _workspace_root()
    path = os.path.join(root, "dingtalk-desktop", "digest_config.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("notify_target") or None
    except Exception:
        return None

def send(message: str, daemon_url: str, cid: str = None, name: str = None):
    """POST /send。cid 与 name 二选一；若都无则用 digest_config 的 notify_target。"""
    if not message or not message.strip():
        return False, "message empty"
    body = {"message": message.strip()}
    if cid:
        body["cid"] = cid
    elif name:
        body["name"] = name
    else:
        default = _load_default_cid()
        if default:
            body["cid"] = default
        else:
            return False, "no cid/name and no notify_target in digest_config.json"
    req = urllib.request.Request(
        daemon_url.rstrip("/") + "/send",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("success"):
            return True, data
        return False, data.get("error", data)
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err = json.loads(err_body).get("error", err_body)
        except Exception:
            err = str(e)
        return False, err
    except Exception as e:
        return False, str(e)

def main():
    daemon_url = os.environ.get("DINGTALK_DAEMON_URL", "http://127.0.0.1:19200")
    target = os.environ.get("DINGTALK_SEND_TARGET", "").strip()
    cid = name = None
    if target:
        if target.isdigit():
            cid = target
        else:
            name = target

    if len(sys.argv) > 1:
        message = " ".join(sys.argv[1:])
    else:
        message = sys.stdin.read()

    ok, out = send(message, daemon_url, cid=cid, name=name)
    if ok:
        print("sent:", out if isinstance(out, dict) else "ok")
        return 0
    print("error:", out, file=sys.stderr)
    return 1

if __name__ == "__main__":
    sys.exit(main())
