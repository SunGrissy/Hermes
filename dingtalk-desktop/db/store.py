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

            CREATE TABLE IF NOT EXISTS memo_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                memo_seq    INTEGER NOT NULL,
                msg_id      TEXT NOT NULL UNIQUE,
                text        TEXT NOT NULL,
                who         TEXT,
                due         TEXT,
                priority    TEXT DEFAULT 'medium',
                context     TEXT,
                task_reminder_id INTEGER,
                status      TEXT DEFAULT 'active',
                ts_created  INTEGER,
                ts_closed   INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_memo_seq
                ON memo_items(memo_seq);

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

            CREATE TABLE IF NOT EXISTS doc_review_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id      TEXT NOT NULL UNIQUE,
                doc_url     TEXT,
                doc_title   TEXT,
                verdict     TEXT,
                report_id   TEXT,
                ts_saved    INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_doc_review_msg_id
                ON doc_review_log(msg_id);

            CREATE TABLE IF NOT EXISTS wish_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                wish_seq    INTEGER NOT NULL,
                msg_id      TEXT NOT NULL UNIQUE,
                text        TEXT NOT NULL,
                task_reminder_id INTEGER,
                status      TEXT DEFAULT 'active',
                ts_created  INTEGER,
                ts_closed   INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_wish_seq
                ON wish_items(wish_seq);
        """)
        # 兼容旧库：增加规范化 URL 列（用于同一文档时间窗口去重）
        try:
            info = c.execute("PRAGMA table_info(doc_review_log)").fetchall()
            col_names = [row[1] for row in info]
            if 'doc_url_normalized' not in col_names:
                c.execute("ALTER TABLE doc_review_log ADD COLUMN doc_url_normalized TEXT")
                c.execute(
                    "CREATE INDEX IF NOT EXISTS idx_doc_review_normalized_ts "
                    "ON doc_review_log(doc_url_normalized, ts_saved)"
                )
        except Exception:
            pass
        # 旧版「删除」为软删；现改为物理删。启动时清掉残留 deleted 行，避免占库与列表歧义
        try:
            c.execute("DELETE FROM memo_items WHERE status = 'deleted'")
            c.execute("DELETE FROM wish_items WHERE status = 'deleted'")
        except Exception:
            pass
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


# ── memo_items ──────────────────────────────────────────────

def get_next_memo_seq():
    with _lock:
        c = _conn()
        row = c.execute("SELECT MAX(memo_seq) FROM memo_items").fetchone()
        c.close()
        return (row[0] or 0) + 1


def is_memo_processed(msg_id):
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT id FROM memo_items WHERE msg_id=?", (str(msg_id),)
        ).fetchone()
        c.close()
        return row is not None


def save_memo_item(memo_seq, msg_id, text, who='', due=None,
                   priority='medium', context=None, task_reminder_id=None):
    with _lock:
        c = _conn()
        c.execute(
            "INSERT OR IGNORE INTO memo_items "
            "(memo_seq, msg_id, text, who, due, priority, context, "
            " task_reminder_id, status, ts_created) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (memo_seq, str(msg_id), text, who, due, priority,
             context, task_reminder_id, 'active',
             int(datetime.now().timestamp())),
        )
        c.commit()
        c.close()


def update_memo_due(memo_seq, due):
    """将进行中备忘的到期日改为 due（YYYY-MM-DD）。返回影响行数。"""
    with _lock:
        c = _conn()
        cur = c.execute(
            "UPDATE memo_items SET due=? WHERE memo_seq=? AND status='active'",
            (due, memo_seq),
        )
        n = cur.rowcount
        c.commit()
        c.close()
    return int(n or 0)


def close_memo_item(memo_seq):
    with _lock:
        c = _conn()
        c.execute(
            "UPDATE memo_items SET status='done', ts_closed=? WHERE memo_seq=?",
            (int(datetime.now().timestamp()), memo_seq),
        )
        c.commit()
        c.close()


def delete_memo_item(memo_seq):
    """从本地库物理删除备忘行（「删除 memo N」）。返回删除行数。"""
    with _lock:
        c = _conn()
        cur = c.execute("DELETE FROM memo_items WHERE memo_seq=?", (memo_seq,))
        n = cur.rowcount
        c.commit()
        c.close()
    return int(n or 0)


def get_memo_by_seq(memo_seq):
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT * FROM memo_items WHERE memo_seq=?", (memo_seq,)
        ).fetchone()
        c.close()
        return dict(row) if row else None


def get_pending_memos():
    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT * FROM memo_items WHERE status='active' ORDER BY memo_seq"
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]


def _normalize_body_dedup_key(text: str) -> str:
    """备忘/愿望正文去重键：去首尾空白、合并连续空白、截断前缀长度。"""
    if not text:
        return ''
    t = ' '.join(str(text).strip().split())
    return (t[:200] or '').strip()


def find_active_memo_duplicate_body(content: str):
    """若已有进行中备忘与 content 归一化后相同，返回该条 dict，否则 None。"""
    nk = _normalize_body_dedup_key(content)
    if not nk:
        return None
    for m in get_pending_memos():
        if _normalize_body_dedup_key(m.get('text') or '') == nk:
            return dict(m)
    return None


def find_active_wish_duplicate_body(content: str):
    """若已有进行中愿望与 content 归一化后相同，返回该条 dict，否则 None。"""
    nk = _normalize_body_dedup_key(content)
    if not nk:
        return None
    for w in get_pending_wishes():
        if _normalize_body_dedup_key(w.get('text') or '') == nk:
            return dict(w)
    return None


# ── wish_items（群「许愿」→ TaskReminder 愿望单，与备忘编号体系独立）────────

def get_next_wish_seq():
    with _lock:
        c = _conn()
        row = c.execute("SELECT MAX(wish_seq) FROM wish_items").fetchone()
        c.close()
        return (row[0] or 0) + 1


def is_wish_processed(msg_id):
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT id FROM wish_items WHERE msg_id=?", (str(msg_id),)
        ).fetchone()
        c.close()
        return row is not None


def save_wish_item(wish_seq, msg_id, text, task_reminder_id=None):
    with _lock:
        c = _conn()
        c.execute(
            "INSERT OR IGNORE INTO wish_items "
            "(wish_seq, msg_id, text, task_reminder_id, status, ts_created) "
            "VALUES (?,?,?,?,?,?)",
            (wish_seq, str(msg_id), text, task_reminder_id, 'active',
             int(datetime.now().timestamp())),
        )
        c.commit()
        c.close()


def delete_wish_item(wish_seq):
    """从本地库物理删除愿望行（「删除 wish N」）。返回删除行数。"""
    with _lock:
        c = _conn()
        cur = c.execute("DELETE FROM wish_items WHERE wish_seq=?", (wish_seq,))
        n = cur.rowcount
        c.commit()
        c.close()
    return int(n or 0)


def close_wish_item(wish_seq):
    """标记愿望为已完成（status='done'），用于「完成 wish N」指令。"""
    with _lock:
        c = _conn()
        c.execute(
            "UPDATE wish_items SET status='done', ts_closed=? WHERE wish_seq=?",
            (int(datetime.now().timestamp()), wish_seq),
        )
        c.commit()
        c.close()


def get_wish_by_seq(wish_seq):
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT * FROM wish_items WHERE wish_seq=?", (wish_seq,)
        ).fetchone()
        c.close()
        return dict(row) if row else None


def get_pending_wishes():
    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT * FROM wish_items WHERE status='active' ORDER BY wish_seq"
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]


# ── doc_review_log ───────────────────────────────────────────

def is_doc_review_processed(msg_id):
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT id FROM doc_review_log WHERE msg_id=?", (str(msg_id),)
        ).fetchone()
        c.close()
        return row is not None


def save_doc_review_result(msg_id, doc_url, doc_title='',
                            verdict='', report_id='', doc_url_normalized=''):
    with _lock:
        c = _conn()
        ts = int(datetime.now().timestamp())
        try:
            c.execute(
                "INSERT OR IGNORE INTO doc_review_log "
                "(msg_id, doc_url, doc_title, verdict, report_id, doc_url_normalized, ts_saved) "
                "VALUES (?,?,?,?,?,?,?)",
                (str(msg_id), doc_url, doc_title, verdict, report_id,
                 (doc_url_normalized or '').strip() or None, ts),
            )
        except Exception:
            c.execute(
                "INSERT OR IGNORE INTO doc_review_log "
                "(msg_id, doc_url, doc_title, verdict, report_id, ts_saved) "
                "VALUES (?,?,?,?,?,?)",
                (str(msg_id), doc_url, doc_title, verdict, report_id, ts),
            )
        c.commit()
        c.close()


def was_doc_attempted_recently(normalized_url: str, window_seconds: int) -> bool:
    """同一规范化文档 URL 在 window_seconds 内是否已有尝试记录（成功/失败/跳过都算）。"""
    if not (normalized_url or str(normalized_url).strip()):
        return False
    cutoff = int(datetime.now().timestamp()) - int(window_seconds)
    with _lock:
        c = _conn()
        try:
            row = c.execute(
                "SELECT id FROM doc_review_log WHERE doc_url_normalized=? AND ts_saved>=? LIMIT 1",
                (str(normalized_url).strip(), cutoff),
            ).fetchone()
        except Exception:
            row = None  # 旧库无 doc_url_normalized 列时视为未尝试
        c.close()
    return row is not None


if __name__ == '__main__':
    init_db()
    print('DB initialized:', _DB_PATH)
