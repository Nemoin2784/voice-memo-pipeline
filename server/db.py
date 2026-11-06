# -*- coding: utf-8 -*-
"""SQLite 任务表：接口层（app.py）和转写进程（worker.py）共用。"""
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
BACKUP_DIR = os.path.join(DATA, "backup")
DB_PATH = os.environ.get("VOICE_DB", os.path.join(DATA, "tasks.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    filename    TEXT,
    stored_path TEXT,
    bytes       INTEGER,
    duration    REAL,
    status      TEXT NOT NULL,
    text        TEXT,
    error       TEXT,
    client      TEXT,
    elapsed     REAL,
    rtf         REAL,
    sha256      TEXT,
    hidden      INTEGER DEFAULT 0,
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at);
CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);
"""


def connect(path=None):
    con = sqlite3.connect(path or DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init(path=None):
    os.makedirs(os.path.dirname(path or DB_PATH), exist_ok=True)
    with connect(path) as con:
        con.executescript(SCHEMA)
        cols = [r["name"] for r in con.execute("PRAGMA table_info(tasks)")]
        if "delivered" not in cols:
            con.execute("ALTER TABLE tasks ADD COLUMN delivered INTEGER DEFAULT 0")
        if "sha256" not in cols:
            con.execute("ALTER TABLE tasks ADD COLUMN sha256 TEXT")
        if "deliver_at" not in cols:
            # 取件队列的排序键：正常任务 = 转写完成时间；被“重新入队/重复上传”的任务 = 0（插到队首）
            con.execute("ALTER TABLE tasks ADD COLUMN deliver_at REAL")
        if "hidden" not in cols:
            # hidden=1 的任务不进入“最近转写记录”清单（测试录音用，文本和 txt 存档都还在）
            con.execute("ALTER TABLE tasks ADD COLUMN hidden INTEGER DEFAULT 0")
        # 索引放在迁移之后建，老库才不会因为缺列而报错
        con.execute("CREATE INDEX IF NOT EXISTS idx_tasks_sha ON tasks(sha256)")


def create_task(task_id, filename, stored_path, nbytes, duration, client, sha256=None):
    with connect() as con:
        con.execute(
            "INSERT INTO tasks (id, filename, stored_path, bytes, duration, status, client,"
            " created_at, sha256) VALUES (?,?,?,?,?,?,?,?,?)",
            (task_id, filename, stored_path, nbytes, duration, "queued", client,
             time.time(), sha256))
    return get_task(task_id)


def find_by_sha(sha256):
    """同一条音频（内容哈希相同）之前有没有传过：返回最近的一条排队/运行/完成的任务。"""
    if not sha256:
        return None
    with connect() as con:
        row = con.execute(
            "SELECT * FROM tasks WHERE sha256=? AND status IN ('queued','running','done')"
            " ORDER BY created_at DESC LIMIT 1", (sha256,)).fetchone()
    return dict(row) if row else None


def get_task(task_id):
    with connect() as con:
        row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def list_tasks(limit=20, undelivered=False):
    sql = ("SELECT id, filename, duration, status, created_at, started_at, finished_at,"
           " elapsed, rtf, error, length(coalesce(text,'')) AS text_len,"
           " coalesce(delivered,0) AS delivered FROM tasks")
    if undelivered:
        sql += (" WHERE status='done' AND coalesce(delivered,0)=0"
                " AND coalesce(hidden,0)=0")
    sql += " ORDER BY created_at DESC LIMIT ?"
    with connect() as con:
        rows = con.execute(sql, (limit,)).fetchall()
    return [dict(r) for r in rows]


def claim_next():
    """把最早排队的一条置为 running 并返回；没有则 None。用 BEGIN IMMEDIATE 防并发抢。"""
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM tasks WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            con.execute("COMMIT")
            return None
        con.execute("UPDATE tasks SET status='running', started_at=? WHERE id=?",
                    (time.time(), row["id"]))
        con.execute("COMMIT")
        return dict(row)
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def finish(task_id, text=None, error=None, duration=None, elapsed=None, rtf=None):
    now = time.time()
    with connect() as con:
        con.execute(
            "UPDATE tasks SET status=?, text=?, error=?, duration=coalesce(?, duration),"
            " elapsed=?, rtf=?, finished_at=?, deliver_at=coalesce(deliver_at, ?) WHERE id=?",
            ("error" if error else "done", text, error, duration, elapsed, rtf,
             now, now, task_id))


def next_deliverable():
    """最早一条“已完成但还没被快捷指令取走”的任务。

    按**转写完成时间**排序（不是上传时间）：谁先转完谁先给。
    被“重新入队 / 重复上传”的任务 deliver_at 会被置 0，插到队首 —— 用户刚刚点名要的那条先给。
    """
    with connect() as con:
        row = con.execute(
            "SELECT * FROM tasks WHERE status='done' AND coalesce(delivered,0)=0"
            " AND coalesce(hidden,0)=0"
            " ORDER BY coalesce(deliver_at, finished_at, created_at), created_at LIMIT 1").fetchone()
    return dict(row) if row else None


def mark_delivered(task_id):
    with connect() as con:
        con.execute("UPDATE tasks SET delivered=1 WHERE id=?", (task_id,))


def mark_undelivered(task_id):
    """把已有结果重新放回取件队列（放队首），让快捷指令能马上再取一次。"""
    with connect() as con:
        con.execute("UPDATE tasks SET delivered=0, deliver_at=0 WHERE id=?", (task_id,))


def set_hidden(task_id, hidden=True):
    """把一条记录从“最近转写记录”清单里收起/放回（不影响取件、不影响 txt 存档）。"""
    with connect() as con:
        con.execute("UPDATE tasks SET hidden=? WHERE id=?", (1 if hidden else 0, task_id))


def backup(keep=14):
    """把数据库快照到 data/backup/tasks-YYYYmmdd-HHMMSS.db（用 SQLite 在线备份接口，服务运行中也安全）。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_DIR, "tasks-%s.db" % stamp)
    src = connect()
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    backups = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("tasks-") and f.endswith(".db"))
    for old in backups[:-keep]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass
    set_meta("backup_at", time.time())
    return dest


def maybe_backup(hours=24):
    """每天自动备份一次；返回快照路径或 None（还没到时间）。"""
    last = get_meta("backup_at")
    try:
        last = float(last) if last else 0.0
    except (TypeError, ValueError):
        last = 0.0
    if time.time() - last < hours * 3600:
        return None
    return backup()


def pending_counts():
    with connect() as con:
        rows = con.execute(
            "SELECT status, count(*) AS c FROM tasks WHERE status IN ('queued','running')"
            " GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}


def requeue_running():
    """服务/worker 异常退出后，把卡在 running 的任务放回队列。"""
    with connect() as con:
        cur = con.execute("UPDATE tasks SET status='queued', started_at=NULL"
                          " WHERE status='running'")
        return cur.rowcount


def set_meta(k, v):
    with connect() as con:
        con.execute("INSERT INTO meta(k,v) VALUES(?,?)"
                    " ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def get_meta(k, default=None):
    with connect() as con:
        row = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return row["v"] if row else default


def queue_state():
    """返回排队情况：{"queued": n, "running": task|None, "rtf": 0.2}"""
    now = time.time()
    with connect() as con:
        queued = con.execute(
            "SELECT id, duration, created_at FROM tasks WHERE status='queued'"
            " ORDER BY created_at").fetchall()
        running = con.execute(
            "SELECT id, duration, started_at FROM tasks WHERE status='running'"
            " ORDER BY started_at LIMIT 1").fetchone()
        done = con.execute(
            "SELECT rtf FROM tasks WHERE status='done' AND rtf IS NOT NULL"
            " ORDER BY finished_at DESC LIMIT 20").fetchall()
    rtfs = [r["rtf"] for r in done if r["rtf"]]
    rtf = sum(rtfs) / len(rtfs) if rtfs else 0.2
    return {"queued": [dict(r) for r in queued],
            "running": dict(running) if running else None,
            "rtf": round(rtf, 3), "now": now}
