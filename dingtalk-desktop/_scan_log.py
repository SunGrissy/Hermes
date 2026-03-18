"""Scan message log for all content types and conversations."""
import json, os, glob

# Find the log file
candidates = [
    os.path.join("Y:/UltraAI/skills/dingtalk-desktop", "_msg_log.jsonl"),
    os.path.join("Y:/UltraAI/data/dingtalk", "_msg_log.jsonl"),
]
log = None
for c in candidates:
    if os.path.exists(c):
        log = c
        break

if not log:
    for g in glob.glob("Y:/UltraAI/**/_msg_log.jsonl", recursive=True):
        log = g
        break

if not log:
    print("LOG NOT FOUND")
    exit(1)

print(f"Using: {log}")
print(f"Size: {os.path.getsize(log)} bytes")

types = {}
cids = {}
total = 0

with open(log, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            d = json.loads(line)
            total += 1
            ct = str(d.get('content_type', d.get('type', '?')))
            cid = d.get('cid', '?')
            text = (d.get('text', '') or '')[:60]
            sender = d.get('sender_name', d.get('name', '?'))

            if ct not in types:
                types[ct] = {'count': 0, 'example_cid': cid, 'example_text': text, 
                             'all_keys': list(d.keys()), 'example_line': d}
            types[ct]['count'] += 1

            if cid not in cids:
                cids[cid] = {'name': sender, 'count': 0, 'types': set()}
            cids[cid]['count'] += 1
            cids[cid]['types'].add(ct)
        except:
            pass

print(f"\nTotal messages: {total}")
print(f"\n=== CONTENT TYPES ({len(types)}) ===")
for k, v in sorted(types.items()):
    print(f"  type={k}: count={v['count']} cid={v['example_cid']}")
    print(f"    example: {v['example_text']}")
    print(f"    keys: {v['all_keys']}")

print(f"\n=== TOP CONVERSATIONS ===")
for cid, v in sorted(cids.items(), key=lambda x: -x[1]['count'])[:15]:
    ts = ', '.join(sorted(v['types']))
    print(f"  cid={cid} count={v['count']} types=[{ts}] name={v['name']}")

# Dump full example for each non-1 type
print(f"\n=== FULL EXAMPLES OF NON-TEXT TYPES ===")
for ct, info in sorted(types.items()):
    if ct != '1' and ct != '?':
        print(f"\n--- type={ct} ---")
        print(json.dumps(info['example_line'], ensure_ascii=False, indent=2))
