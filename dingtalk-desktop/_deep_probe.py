"""Deep probe — raw probe of conversations with known non-text message types.
The probe_listmsg only returns the latest msg. We target CIDs where latest is likely non-text."""
import json, urllib.request, sys, os

DAEMON = "http://127.0.0.1:19200"

def post(path, body):
    url = f"{DAEMON}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def try_parse_json(val):
    if not isinstance(val, str):
        return val
    s = val.strip()
    if (s.startswith('{') and s.endswith('}')) or (s.startswith('[') and s.endswith(']')):
        try:
            return json.loads(s)
        except:
            pass
    return val

def deep_expand(obj, max_depth=15, depth=0):
    if depth > max_depth:
        return obj
    if isinstance(obj, dict):
        return {k: deep_expand(try_parse_json(v), max_depth, depth+1) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [deep_expand(try_parse_json(item), max_depth, depth+1) for item in obj]
    return obj

targets = [
    ("316550726:659392009", "项目助手(互动卡片2950)"),
    ("36320517564", "工作通知(日报300)"),
    ("69104164425", "群聊(富文本3100)"),
    ("316550726:6369934435", "P2P(Markdown1200)"),
    ("47856547551", "群聊(图片203)"),
    ("300405507:316550726", "笛笛(2900)"),
    ("68240494115", "群聊(1202)"),
    ("74656715046", "群聊(type2)"),
    ("324215852", "面试通知群(文本1)"),
]

def main():
    out_path = os.path.join(os.path.dirname(__file__), "_deep_probe_result.txt")
    lines = []

    seen_types = set()

    for cid, label in targets:
        lines.append("=" * 80)
        lines.append(f"RAW PROBE: {label} (cid={cid})")
        lines.append("=" * 80)

        try:
            raw = post("/probe_listmsg", {"cid": cid, "count": 1})
        except Exception as e:
            lines.append(f"  ERROR: {e}")
            continue

        if not raw.get("success"):
            lines.append(f"  FAILED: {raw.get('error', '?')}")
            continue

        obj = raw.get("raw_object")
        if not obj:
            # Maybe the data is in a different format
            lines.append(f"  No raw_object. Keys: {list(raw.keys())}")
            lines.append(json.dumps(raw, ensure_ascii=False, indent=2)[:3000])
            continue

        expanded = deep_expand(obj)
        bm = expanded.get("baseMessage", {})
        content = bm.get("content", {})
        ct = content.get("contentType", "?")
        type_key = str(ct)

        if type_key in seen_types:
            lines.append(f"  contentType={ct} already seen, skipping")
            continue

        seen_types.add(type_key)
        lines.append(f"  contentType={ct}")
        lines.append(f"  content keys: {list(content.keys())}")
        lines.append(f"  extension keys: {list(bm.get('extension', {}).keys())}")
        lines.append(f"\n  FULL EXPANDED JSON:")
        lines.append(json.dumps(expanded, ensure_ascii=False, indent=2))
        lines.append("")

    lines.append("\n" + "=" * 80)
    lines.append(f"TYPES PROBED: {sorted(seen_types)}")
    lines.append("=" * 80)

    result = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"Written {len(lines)} lines to {out_path}")
    print(f"Types seen: {sorted(seen_types)}")

if __name__ == "__main__":
    main()
