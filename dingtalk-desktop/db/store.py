# -*- coding: utf-8 -*-
"""
SQLite 持久化封装。

表：
  reports          — 每日日报采集记录
  digest_runs      — 每次摘要运行结果
  resume_screen_log — 简历 AI 初筛记录（ct=502 文件消息触发）
"""
import os
import json
import sqlite3
import threading
from datetime import datetime

_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'dingtalk', 'agent.db')
_lock = threading.Lock()


def _conn():
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    c = sqlite3.connect(_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    """建表（幂等）"""
    with _lock:
        c = _conn()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS reports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                person      TEXT NOT NULL,
                date        TEXT NOT NULL,
                group_cid   TEXT,
                text        TEXT,
                quality_score INTEGER,
                flags_json  TEXT,
                ts_saved    INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_reports_person_date
                ON reports(person, date);

            CREATE TABLE IF NOT EXISTS digest_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date    TEXT NOT NULL,
                analysis_json TEXT,
                ts_saved    INTEGER
            );

            CREATE TABLE IF NOT EXISTS resume_screen_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id      TEXT NOT NULL UNIQUE,
                group_cid   TEXT,
                sender_uid  TEXT,
                file_name   TEXT,
                file_path   TEXT,
                role_guess  TEXT,
                verdict     TEXT,
                summary     TEXT,
                reply_sent  INTEGER DEFAULT 0,
                ts_saved    INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_resume_msg_id
                ON resume_screen_log(msg_id);
        """)
        c.commit()
        c.close()


# ── reports ──────────────────────────────────────────────────

def save_report(person, date, group_cid, text, quality_score=None, flags=None):
    with _lock:
        c = _conn()
        c.execute(
            "INSERT OR IGNORE INTO reports "
            "(person, date, group_cid, text, quality_score, flags_json, ts_saved) "
            "VALUES (?,?,?,?,?,?,?)",
            (person, date, group_cid, text, quality_score,
             json.dumps(flags or {}, ensure_ascii=False),
             int(datetime.now().timestamp())),
        )
        c.commit()
        c.close()


def save_digest_run(run_date, analysis):
    with _lock:
        c = _conn()
        c.execute(
            "INSERT INTO digest_runs (run_date, analysis_json, ts_saved) VALUES (?,?,?)",
            (run_date,
             json.dumps(analysis, ensure_ascii=False),
             int(datetime.now().timestamp())),
        )
        c.commit()
        c.close()


# ── resume_screen_log ────────────────────────────────────────

def is_resume_processed(msg_id):
    """检查某条 ct=502 消息是否已处理过"""
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT id FROM resume_screen_log WHERE msg_id=?", (str(msg_id),)
        ).fetchone()
        c.close()
        return row is not None


def save_resume_result(msg_id, group_cid, sender_uid, file_name, file_path,
                       role_guess, verdict, summary, reply_sent=False):
    with _lock:
        c = _conn()
        c.execute(
            "INSERT OR REPLACE INTO resume_screen_log "
            "(msg_id, group_cid, sender_uid, file_name, file_path, "
            " role_guess, verdict, summary, reply_sent, ts_saved) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(msg_id), group_cid, sender_uid, file_name, file_path,
             role_guess, verdict, summary, 1 if reply_sent else 0,
             int(datetime.now().timestamp())),
        )
        c.commit()
        c.close()


def get_recent_resume_results(days=30):
    cutoff = int(datetime.now().timestamp()) - days * 86400
    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT * FROM resume_screen_log WHERE ts_saved >= ? ORDER BY ts_saved DESC",
            (cutoff,)
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]


if __name__ == '__main__':
    init_db()
    print('DB initialized:', _DB_PATH)
