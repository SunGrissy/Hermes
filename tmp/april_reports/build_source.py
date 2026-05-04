import json, pathlib, datetime, re
base=pathlib.Path('D:/MyAgents/tmp/april_reports')
weekly=json.loads((base/'weekly_april.json').read_text(encoding='utf-8'))['result']['report_list']
daily=json.loads((base/'daily_last_week.json').read_text(encoding='utf-8'))['result']['report_list']

def get_field(r,key_contains):
    return '\n'.join((c.get('value') or '') for c in r.get('content',[]) if key_contains in c.get('key',''))

def dt(ms): return datetime.datetime.fromtimestamp(ms/1000, datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d')
full=[]
for r in weekly:
    full.append(f"\n# 周报 {dt(r['createTime'])} {r['report_id']}\n")
    for c in r.get('content',[]):
        val=(c.get('value') or '').replace('\r','')
        if c.get('type')==1 and val.strip() and c.get('key') not in ('图片','附件'):
            full.append(f"\n## {c.get('key')}\n{val}\n")
for r in daily:
    full.append(f"\n# 日报 {dt(r['createTime'])} {r['report_id']}\n")
    for c in r.get('content',[]):
        val=(c.get('value') or '').replace('\r','')
        if c.get('type')==1 and val.strip():
            full.append(f"\n## {c.get('key')}\n{val}\n")
(base/'source_full.md').write_text('\n'.join(full),encoding='utf-8')
print(str(base/'source_full.md'), 'written', len('\n'.join(full)))
