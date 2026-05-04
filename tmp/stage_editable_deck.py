from pathlib import Path
import subprocess

repo = Path('D:/MyAgents')
file_rel = '会议材料/驯化野生硅基伙伴_可编辑互动版.html'

def run(args, check=True):
    p = subprocess.run(args, cwd=repo, text=True, encoding='utf-8', errors='replace', capture_output=True)
    print('$', ' '.join(args))
    if p.stdout:
        print(p.stdout)
    if p.stderr:
        print(p.stderr)
    if check and p.returncode != 0:
        raise SystemExit(p.returncode)
    return p

run(['git', 'add', '--', file_rel])
run(['git', 'diff', '--cached', '--stat'])
run(['git', 'diff', '--cached', '--name-status'])
