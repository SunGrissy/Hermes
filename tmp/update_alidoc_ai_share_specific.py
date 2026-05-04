import subprocess
from pathlib import Path
node = 'lyQod3RxJK3Pgee4T4aoRg69Jkb4Mw9r'
md = Path('D:/MyAgents/tmp/alidoc_ai_share_revised.md').read_text(encoding='utf-8')
cmd = [r'C:\Users\TU\.local\bin\dws.exe', 'doc', 'update', '--node', node, '--mode', 'overwrite', '--markdown', md, '--format', 'json', '--yes']
res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
print('returncode', res.returncode)
print(res.stdout)
if res.stderr:
    print('STDERR:', res.stderr)
raise SystemExit(res.returncode)
