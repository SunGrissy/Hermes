"""探测钉钉本地数据库结构"""
import sqlite3, os

dbs = [
    os.path.expandvars(r"%APPDATA%\DingTalk\316550726_v2\Sync_v2\cache\sync.sqlite"),
    os.path.expandvars(r"%APPDATA%\DingTalk\globalStorage\storage.db"),
]

for db_path in dbs:
    print(f"\n=== {db_path} ===")
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        print(f"Tables: {tables}")
        for t in tables:
            cur.execute(f"PRAGMA table_info({t})")
            cols = [(r[1], r[2]) for r in cur.fetchall()]
            print(f"  {t}: {cols}")
            cur.execute(f"SELECT * FROM {t} LIMIT 2")
            for row in cur.fetchall():
                print(f"    {row}")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")
