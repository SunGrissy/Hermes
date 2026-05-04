import json, subprocess
node = 'lyQod3RxJK3Pgee4T4aoRg69Jkb4Mw9r'
cmd = [r'C:\Users\TU\.local\bin\dws.exe', 'doc', 'read', '--node', node, '--format', 'json', '--yes']
res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
print('returncode', res.returncode)
print('stdout_len', len(res.stdout))
data = json.loads(res.stdout)
md = data.get('markdown') or data.get('content') or ''
for kw in ['结合我们自己的工作', 'PM 系统', 'Vibe Coding 不是让产品变程序员', 'AI 的话不能当数据源', '高杠杆副手']:
    print(kw, kw in md)
print('chars', len(md), 'lines', md.count('\n') + 1)
