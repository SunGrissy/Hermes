# -*- coding: utf-8 -*-
"""
SQLite 持久化封装。

表：
  reports          — 每日日报采集记录
  digest_runs      — 每次摘要运行结果
  resume_screen_log — 简历 AI 初筛记录（ct=502 文件消息触发）
  memo_items / wish_items / topic_items — 备忘、愿望、选题（选题独立 topic_seq，TR note 为 topic:#N）
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

            CREATE TABLE IF NOT EXISTS topic_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_seq   INTEGER NOT NULL,
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
            CREATE INDEX IF NOT EXISTS idx_topic_seq
                ON topic_items(topic_seq);

            CREATE TABLE IF NOT EXISTS check_items (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                check_seq        INTEGER NOT NULL,
                msg_id           TEXT NOT NULL UNIQUE,
                title            TEXT NOT NULL,
                due              TEXT,
                source_text      TEXT,
                group_cid        TEXT,
                task_reminder_id INTEGER,
                status           TEXT DEFAULT 'active',
                ts_created       INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_check_seq
                ON check_items(check_seq);
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
            c.execute("DELETE FROM topic_items WHERE status = 'deleted'")
        except Exception:
            pass
        # 简历初筛：异常退出时可能残留 LLM 前占位，启动时清掉以免永久跳过
        try:
            c.execute("DELETE FROM resume_screen_log WHERE verdict = '__processing__'")
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


def try_claim_resume_llm_slot(msg_id, group_cid, sender_uid, file_name, file_path):
    """在调用 LLM 前原子占位（INSERT OR IGNORE）。

    skill_router 轮询间隔短于 LLM 耗时且 save 在 LLM 之后才写库时，仅靠 is_resume_processed
    会误判「未处理」而跑两次。抢到返回 True；已有任意行（含占位/终态）则返回 False。
    """
    with _lock:
        c = _conn()
        cur = c.execute(
            "INSERT OR IGNORE INTO resume_screen_log "
            "(msg_id, group_cid, sender_uid, file_name, file_path, "
            " role_guess, verdict, summary, reply_sent, ts_saved) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(msg_id), group_cid, sender_uid, file_name, file_path or '',
             '—', '__processing__', 'LLM占位', 0, int(datetime.now().timestamp())),
        )
        ok = cur.rowcount > 0
        c.commit()
        c.close()
        return ok


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


def update_memo_text(memo_seq, text):
    """更新进行中备忘正文（与 TR what 对齐）。返回影响行数。"""
    if text is None:
        return 0
    text = str(text).strip()
    if not text:
        return 0
    with _lock:
        c = _conn()
        cur = c.execute(
            "UPDATE memo_items SET text=? WHERE memo_seq=? AND status='active'",
            (text, memo_seq),
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


# ── topic_items（群「选题」→ TR，topic_seq 独立，note 为 topic:#N）────────

def get_next_topic_seq():
    with _lock:
        c = _conn()
        row = c.execute("SELECT MAX(topic_seq) FROM topic_items").fetchone()
        c.close()
        return (row[0] or 0) + 1


def is_topic_processed(msg_id):
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT id FROM topic_items WHERE msg_id=?", (str(msg_id),)
        ).fetchone()
        c.close()
        return row is not None


def save_topic_item(topic_seq, msg_id, text, who='', due=None,
                    priority='medium', context=None, task_reminder_id=None):
    with _lock:
        c = _conn()
        c.execute(
            "INSERT OR IGNORE INTO topic_items "
            "(topic_seq, msg_id, text, who, due, priority, context, "
            " task_reminder_id, status, ts_created) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (topic_seq, str(msg_id), text, who, due, priority,
             context, task_reminder_id, 'active',
             int(datetime.now().timestamp())),
        )
        c.commit()
        c.close()


def upsert_topic_from_tr_sync(topic_seq, text, who='', due=None,
                              priority='medium', task_reminder_id=None):
    """以 TR 为准写入/更新本地选题：无行则插入（msg_id=tr_sync:#）。"""
    ts = int(datetime.now().timestamp())
    text = (text or '').strip()
    who = (who or '').strip()
    due = (due or '').strip() or None
    pr = (priority or 'medium').strip() or 'medium'
    tid = task_reminder_id
    synthetic_mid = f'tr_sync:{int(topic_seq)}'
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT id, msg_id FROM topic_items WHERE topic_seq=?",
            (int(topic_seq),),
        ).fetchone()
        if row:
            c.execute(
                "UPDATE topic_items SET text=?, who=?, due=?, priority=?, "
                "task_reminder_id=?, status='active', ts_closed=NULL "
                "WHERE topic_seq=?",
                (text, who, due, pr, tid, int(topic_seq)),
            )
        else:
            c.execute(
                "INSERT INTO topic_items "
                "(topic_seq, msg_id, text, who, due, priority, context, "
                " task_reminder_id, status, ts_created) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (int(topic_seq), synthetic_mid, text, who, due, pr,
                 None, tid, 'active', ts),
            )
        c.commit()
        c.close()


def update_topic_text(topic_seq, text):
    """更新进行中选题正文（与 TR what 对齐）。返回影响行数。"""
    if text is None:
        return 0
    text = str(text).strip()
    if not text:
        return 0
    with _lock:
        c = _conn()
        cur = c.execute(
            "UPDATE topic_items SET text=? WHERE topic_seq=? AND status='active'",
            (text, topic_seq),
        )
        n = cur.rowcount
        c.commit()
        c.close()
    return int(n or 0)


def delete_topic_item(topic_seq):
    with _lock:
        c = _conn()
        cur = c.execute("DELETE FROM topic_items WHERE topic_seq=?", (topic_seq,))
        n = cur.rowcount
        c.commit()
        c.close()
    return int(n or 0)


def close_topic_item(topic_seq):
    with _lock:
        c = _conn()
        c.execute(
            "UPDATE topic_items SET status='done', ts_closed=? WHERE topic_seq=?",
            (int(datetime.now().timestamp()), topic_seq),
        )
        c.commit()
        c.close()


def get_topic_by_seq(topic_seq):
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT * FROM topic_items WHERE topic_seq=?", (topic_seq,)
        ).fetchone()
        c.close()
        return dict(row) if row else None


def get_pending_topics():
    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT * FROM topic_items WHERE status='active' ORDER BY topic_seq"
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]


def find_active_topic_duplicate_body(content: str):
    nk = _normalize_body_dedup_key(content)
    if not nk:
        return None
    for m in get_pending_topics():
        if _normalize_body_dedup_key(m.get('text') or '') == nk:
            return dict(m)
    return None


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


# ── check_items（引用回复 TR → 跟进任务）───────────────────────

def get_next_check_seq():
    with _lock:
        c = _conn()
        row = c.execute("SELECT MAX(check_seq) FROM check_items").fetchone()
        c.close()
        return (row[0] or 0) + 1


def is_check_processed(msg_id):
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT id FROM check_items WHERE msg_id=?", (str(msg_id),)
        ).fetchone()
        c.close()
        return row is not None


def save_check_item(check_seq, msg_id, title, due=None,
                    source_text=None, group_cid=None, task_reminder_id=None):
    with _lock:
        c = _conn()
        c.execute(
            "INSERT OR IGNORE INTO check_items "
            "(check_seq, msg_id, title, due, source_text, group_cid, "
            " task_reminder_id, status, ts_created) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (check_seq, str(msg_id), title, due, source_text,
             str(group_cid or ''), task_reminder_id,
             'active', int(datetime.now().timestamp())),
        )
        c.commit()
        c.close()


def get_pending_checks():
    with _lock:
        c = _conn()
        rows = c.execute(
            "SELECT * FROM check_items WHERE status='active' ORDER BY check_seq"
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]


if __name__ == '__main__':
    init_db()
    print('DB initialized:', _DB_PATH)
