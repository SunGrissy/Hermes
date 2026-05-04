import subprocess
from pathlib import Path

md = Path('tmp/alidoc_ai_share_revised.md').read_text(encoding='utf-8')
cmd = [
    r'C:\Users\TU\.local\bin\dws.exe',
    'doc', 'update',
    '--node', 'lyQod3RxJK3Pgee4T4aoRg69Jkb4Mw9r',
    '--mode', 'overwrite',
    '--markdown', md,
    '--format', 'json',
    '--yes',
]
res = subprocess.run(cmd, cwd=r'D:\MyAgents', text=True, capture_output=True, encoding='utf-8', errors='replace', timeout=180)
print('returncode', res.returncode)
print('STDOUT_START')
print(res.stdout)
print('STDOUT_END')
print('STDERR_START')
print(res.stderr)
print('STDERR_END')
raise SystemExit(res.returncode)
