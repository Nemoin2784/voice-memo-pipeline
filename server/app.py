# -*- coding: utf-8 -*-
"""语音备忘录转写接口：iOS 快捷指令上传 m4a → 返回 task_id、等待时间 → 后台转写 → 取文本。

启动：python -m uvicorn app:app --host 0.0.0.0 --port 8765   （在 server 目录下）
或者双击 start_server.bat。
"""
import asyncio
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.parse
import uuid
from fastapi import (Depends, FastAPI, File, Form, Header, HTTPException, Query, Request,
                     Response, UploadFile)
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import config  # noqa: E402
import db  # noqa: E402
import records  # noqa: E402

APP_VERSION = "0.0.0"
WORKER = {"pid": None, "started_by_us": False}


class UTF8JSONResponse(JSONResponse):
    """显式声明 charset：Safari 直接打开 /api/health 时否则可能按 GBK 解码出乱码。"""
    media_type = "application/json; charset=utf-8"


# ---------- 工具 ----------

def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(os.path.join(config.LOGS, "server.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def pid_alive(pid):
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


def worker_alive(max_age=20.0):
    """PID 还在 且 心跳在 max_age 秒内算活着（worker 每 2 秒打一次，模型加载期间也不断）。"""
    try:
        hb = float(db.get_meta("worker_heartbeat", "0") or 0)
    except ValueError:
        hb = 0
    age = time.time() - hb if hb else None
    pid = db.get_meta("worker_pid")
    alive = bool(age is not None and age < max_age and pid_alive(pid))
    return alive, age


def worker_state():
    raw = db.get_meta("worker_state", "")
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {"text": raw}


def ensure_worker(strict=False):
    # 启动瞬间用严判据（6 秒），避免复用“正在退出”的旧 worker；运行中用 20 秒宽容
    alive, age = worker_alive(6.0 if strict else 20.0)
    if alive:
        log("worker 已在运行（心跳 %.1f s 前）" % (age or 0))
        return False
    n = db.requeue_running()
    if n:
        log("上次没跑完的任务已放回队列：%d 个" % n)
    cmd = [config.PYTHON, os.path.join(HERE, "worker.py"), "--mode", config.WORKER_MODE]
    kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  cwd=HERE, close_fds=True)
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.Popen(cmd, **kwargs)
    WORKER.update(pid=p.pid, started_by_us=True)
    db.set_meta("worker_pid", p.pid)
    db.set_meta("model_ready", "0")
    db.set_meta("worker_heartbeat", time.time())
    log("启动 worker pid=%d 模式=%s" % (p.pid, config.WORKER_MODE))
    return True


def check_token(token: str = Query(default=""), x_token: str = Header(default="")):
    if not config.TOKEN:
        return True
    if token == config.TOKEN or x_token == config.TOKEN:
        return True
    raise HTTPException(status_code=401, detail="token 不对")


def clean_filename(name):
    """multipart 头按 latin-1 解码，中文文件名（UTF-8 或 GBK 字节）在这里还原。"""
    try:
        raw = name.encode("latin-1")
    except UnicodeEncodeError:
        return name
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return name


def probe_duration(path):
    """用 ffmpeg 读时长（秒）；读不到返回 0。"""
    ff = os.path.join(config.ROOT, "tools", "ffmpeg.exe")
    if not os.path.exists(ff):
        return 0.0
    try:
        p = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, timeout=30)
        err = p.stderr.decode("utf-8", "replace") + p.stdout.decode("utf-8", "replace")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 0.0


def estimate_wait(duration):
    """返回 (预计总等待秒数, 排在前面的人数)。"""
    st = db.queue_state()
    rtf = st["rtf"] or config.RTF_DEFAULT
    per = config.OVERHEAD_SEC

    def cost(d):
        return (d or 0) * rtf + per

    ahead = 0.0
    running = st["running"]
    if running:
        elapsed = max(0.0, st["now"] - (running["started_at"] or st["now"]))
        ahead += max(0.0, cost(running["duration"]) - elapsed)
    for q in st["queued"]:
        ahead += cost(q["duration"])
    if db.get_meta("model_ready") != "1":
        ahead += config.MODEL_LOAD_EST
    position = len(st["queued"]) + (1 if running else 0) + 1
    total = max(1, int(round(ahead + cost(duration))))
    return total, position


def remaining_seconds(t):
    """某个排队/运行中任务还剩多少秒，以及排第几位。"""
    st = db.queue_state()
    rtf = st["rtf"] or config.RTF_DEFAULT

    def cost(d):
        return (d or 0) * rtf + config.OVERHEAD_SEC

    ahead = 0.0
    pos = 1
    running = st["running"]
    if running:
        elapsed = max(0.0, st["now"] - (running["started_at"] or st["now"]))
        left = max(0.0, cost(running["duration"]) - elapsed)
        if running["id"] == t["id"]:
            return max(1, int(round(left))), 1
        ahead += left
        pos = 2
    for q in st["queued"]:
        if q["id"] == t["id"]:
            ahead += cost(q["duration"])
            break
        ahead += cost(q["duration"])
        pos += 1
    if db.get_meta("model_ready") != "1":
        ahead += config.MODEL_LOAD_EST
    return max(1, int(round(ahead))), pos


def task_payload(t):
    if not t:
        return None
    out = {
        "task_id": t["id"],
        "status": t["status"],
        "filename": t["filename"],
        "duration": round(t["duration"] or 0, 2),
        "bytes": t["bytes"],
        "created_at": t["created_at"],
        "elapsed": round(t["elapsed"], 2) if t["elapsed"] else None,
        "rtf": t["rtf"],
        "error": t["error"],
    }
    if t["status"] == "done":
        out["text"] = t["text"] or ""
        out["text_url"] = "/api/task/%s/text" % t["id"]
    elif t["status"] in ("queued", "running"):
        eta, pos = remaining_seconds(t)
        out["eta_seconds"] = eta
        out["queue_position"] = pos
    return out


# ---------- 应用 ----------

app = FastAPI(title="语音备忘录转写接口", version=APP_VERSION,
              default_response_class=UTF8JSONResponse)


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    """每个请求进来先打一行（含来源 IP 和 Content-Length），手机端超时时能区分“没连上”还是“传到一半”。"""
    t0 = time.time()
    cl = request.headers.get("content-length") or request.headers.get("transfer-encoding") or "?"
    ua = (request.headers.get("user-agent") or "")[:40]
    log("→ %s %s len=%s ip=%s ua=%s" % (request.method, request.url.path,
                                        cl, request.client.host if request.client else "?",
                                        ua.replace("\n", " ")))
    try:
        resp = await call_next(request)
    except Exception as e:
        log("✗ %s %s 异常 %.1fs: %s" % (request.method, request.url.path, time.time() - t0, e))
        raise
    if request.url.path.startswith("/api/"):
        log("← %s %s %d %.2fs" % (request.method, request.url.path, resp.status_code, time.time() - t0))
    return resp


@app.on_event("startup")
async def _startup():
    db.init()
    log("接口启动 v%s，监听 %s:%d，模式 %s" % (APP_VERSION, config.HOST, config.PORT, config.WORKER_MODE))
    try:
        ensure_worker(strict=True)
    except Exception as e:
        log("worker 启动失败: %s" % e)
    asyncio.create_task(_supervisor())

    async def _daily_backup():
        # 每天给数据库留一份快照（SQLite 在线备份，服务不用停）
        try:
            path = await run_in_threadpool(db.maybe_backup)
            if path:
                log("数据库快照 %s（历史转写 %d 份）" % (path, records.count()))
        except Exception as e:
            log("数据库快照失败: %s" % e)

    asyncio.create_task(_daily_backup())


async def _supervisor():
    """每 5 秒检查一次 worker，挂了就拉起来（尤其是复用旧 worker 后它又被杀的情况）。"""
    while True:
        await asyncio.sleep(5)
        try:
            if not worker_alive()[0]:
                started = await run_in_threadpool(ensure_worker)
                if started:
                    log("看护线程：worker 不在，已重启")
        except Exception as e:
            log("看护线程异常: %s" % e)


@app.on_event("shutdown")
def _shutdown():
    if WORKER["started_by_us"] and WORKER["pid"]:
        try:
            subprocess.run(["taskkill", "/PID", str(WORKER["pid"]), "/T", "/F"],
                           capture_output=True, timeout=10)
            log("已停止 worker pid=%s" % WORKER["pid"])
        except Exception as e:
            log("停止 worker 失败: %s" % e)


def _fmt_time(v):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(v)))
    except (TypeError, ValueError):
        return None


def local_addresses():
    """本机两个可用地址：局域网（家里 Wi-Fi 用，不经过 xEdge 中继）与 xEdge 私网（在外面用）。"""
    found = {}
    for probe in ("8.8.8.8", "100.64.0.1"):      # UDP connect 不发包，只让系统挑出口网卡
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 80))
            found[probe] = s.getsockname()[0]
        except OSError:
            found[probe] = ""
        finally:
            s.close()
    lan = found.get("8.8.8.8", "")
    xt = found.get("100.64.0.1", "")
    if lan.startswith("127.") or lan.startswith("169.254."):
        lan = ""
    if not xt.startswith("100.64."):
        xt = ""
    return {
        "lan": ("http://%s:%d" % (lan, config.PORT)) if lan else None,
        "xedge": ("http://%s:%d" % (xt, config.PORT)) if xt else None,
        "hint": "家里 Wi-Fi 用 lan 地址（不走 xEdge 中继），在外面用 xedge 地址",
    }


@app.get("/api/health")
def health(ok: bool = Depends(check_token)):
    alive, age = worker_alive()
    st = db.queue_state()
    addr = local_addresses()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "addresses": addr,
        "worker": {
            "alive": alive,
            "heartbeat_age": round(age, 1) if age is not None else None,
            "state": worker_state(),
            "mode": db.get_meta("worker_mode", config.WORKER_MODE),
            "model_ready": db.get_meta("model_ready") == "1",
            "model_load_seconds": db.get_meta("model_load_seconds"),
        },
        "queue": {"running": (st["running"] or {}).get("id"), "queued": len(st["queued"])},
        "deliverable": len(db.list_tasks(200, undelivered=True)),
        "rtf_ema": st["rtf"],
        "archive": {"records": records.count(),
                    "db_backup_at": _fmt_time(db.get_meta("backup_at"))},
        "uptime_hint": "GET /api/tasks 看最近任务；测网速用 GET /api/bench?mb=2；备份用 POST /api/backup",
    }


@app.get("/api/bench")
def bench_get(mb: float = Query(default=1.0, ge=0.01, le=50), ok: bool = Depends(check_token)):
    """下行测速：返回 mb 兆的文本。手机 Safari 直接打开就能看这条链路有多快。"""
    n = int(mb * 1024 * 1024)
    unit = b"ABCDEFGH" * 1024          # 8 KB 一块
    body = unit * (n // len(unit)) + unit[:n % len(unit)]
    return PlainTextResponse(body, media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-store"})


@app.post("/api/bench")
async def bench_post(request: Request, ok: bool = Depends(check_token)):
    """上行测速：把请求体读掉并回传字节数，用来量手机 → 电脑的实际上传速度。"""
    t0 = time.time()
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
    dt = max(time.time() - t0, 1e-6)
    return {"bytes": size, "seconds": round(dt, 2),
            "kbps": round(size * 8 / dt / 1000, 1), "kbytes_per_s": round(size / dt / 1024, 1)}


async def _enqueue(task_id, name, stored, size, client, sha256=None):
    """文件已落盘后：探测时长 → 估算等待 → 入库 → 返回给快捷指令的 JSON。"""
    duration = await run_in_threadpool(probe_duration, stored)
    if duration <= 0:
        try:
            os.remove(stored)
        except OSError:
            pass
        raise HTTPException(400, detail="读不出音频时长：文件可能不是音频、或者被截断/损坏")
    if not worker_alive()[0]:
        await run_in_threadpool(ensure_worker)
    # 先按当前队列估算（此时本任务还没入库），再入库，避免把自己也排进“前面的人”
    wait, position = estimate_wait(duration)
    t = db.create_task(task_id, name, stored, size, duration, client, sha256=sha256)
    log("收到 %s %s %.1f MB %.1f s，预计 %d s（第 %d 位）"
        % (task_id, name, size / 1048576, duration, wait, position))
    return {
        "task_id": task_id,
        "status": "queued",
        "filename": name,
        "duration": round(duration, 2),
        "bytes": size,
        "queue_position": position,
        "eta_seconds": wait,
        "wait_seconds": wait,
        "message": "预计 %d 秒后可以取文本" % wait,
        "status_url": "/api/task/%s" % task_id,
        "text_url": "/api/task/%s/text" % task_id,
        "created_at": t["created_at"],
    }


def _too_big_msg(size):
    """413 的提示语：说清多大、上限多少、怎么办。"""
    return ("文件 %.1f MB，超过上限 %d MB；要么在快捷指令里先「编码媒体」压缩"
            "（AAC / 单声道），要么改 config.MAX_UPLOAD_MB"
            % (size / 1048576.0, config.MAX_UPLOAD_MB))


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _duplicate_payload(t, consume=False):
    """同一条音频之前传过：不再转写，直接把已有任务还给快捷指令。

    已完成的：默认重新放回取件队首，点一下快捷指令 B 就能再拿到文本；
    调用方带 consume=1 时表示“返回的 text 我会直接用掉”，于是标记为已取走，避免 B 再取到重复的一条。
    返回体里始终带 text 全文（`text` 字段），快捷指令 A 想立刻导出也能用。
    """
    if t["status"] == "done":
        if consume:
            db.mark_delivered(t["id"])
            wait, position = 0, 0
            msg = "这条音频之前已经转写过，文本已在返回结果里（text 字段）"
        else:
            db.mark_undelivered(t["id"])
            wait, position = 0, 0
            msg = "这条音频之前已经转写过，已重新放回取件队列，点「取回」即可拿到文本"
    else:
        wait, position = remaining_seconds(t)
        msg = "这条音频已经在队列里（%s），不用重复上传" % t["status"]
    log("重复上传 %s → 复用任务 %s（%s）" % (t["filename"], t["id"], t["status"]))
    payload = {
        "task_id": t["id"],
        "status": t["status"],
        "duplicate": True,
        "filename": clean_filename(t["filename"] or ""),
        "title": note_title(t),
        "duration": round(t["duration"] or 0, 2),
        "bytes": t.get("bytes") or 0,
        "queue_position": position,
        "eta_seconds": wait,
        "wait_seconds": wait,
        "message": msg,
        "status_url": "/api/task/%s" % t["id"],
        "text_url": "/api/task/%s/text" % t["id"],
        "created_at": t["created_at"],
    }
    if t["status"] == "done":
        text = t.get("text") or ""
        payload["text"] = text
        payload["text_len"] = len(text)
        payload["deliverable"] = True
    return payload


def _raw_filename(name_param, header_name, content_type):
    """POST /api/upload/raw 用的文件名：X-Filename 头优先，其次 filename 查询参数，最后按 Content-Type 猜。"""
    raw = (name_param or header_name or "").strip()
    if raw:
        try:
            raw = urllib.parse.unquote(raw)
        except Exception:
            pass
    base = os.path.basename(raw.replace("\\", "/")) or ""
    if not os.path.splitext(base)[1].lower():
        ct = (content_type or "").split(";")[0].strip().lower()
        ext = {"audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".aac",
               "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
               "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/flac": ".flac",
               "audio/ogg": ".ogg", "audio/opus": ".opus", "audio/amr": ".amr",
               "audio/x-ms-wma": ".wma"}.get(ct, ".m4a")
        base = (base or "recording") + ext
    return base


def _check_ext(name):
    ext = os.path.splitext(name)[1].lower()
    if ext not in config.AUDIO_EXT:
        raise HTTPException(400, detail="不支持的音频格式: %s（支持 %s）"
                            % (ext or "无扩展名", " ".join(sorted(config.AUDIO_EXT))))


def _stored_path(task_id, name):
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", os.path.splitext(name)[0])[:40] or "audio"
    return os.path.join(config.UPLOADS, "%s_%s%s" % (task_id, safe, os.path.splitext(name)[1].lower()))


@app.post("/api/upload")
async def upload(file: UploadFile = File(...),
                 client: str = Form(default=""),
                 x_client: str = Header(default=""),
                 force: int = Query(default=0, ge=0, le=1),
                 consume: int = Query(default=0, ge=0, le=1),
                 ok: bool = Depends(check_token)):
    name = os.path.basename(clean_filename(file.filename or "audio.m4a"))
    _check_ext(name)

    task_id = uuid.uuid4().hex[:12]
    stored = _stored_path(task_id, name)

    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    try:
        with open(stored, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, detail=_too_big_msg(size))
                f.write(chunk)
    except HTTPException:
        try:
            os.remove(stored)
        except OSError:
            pass
        raise
    if size == 0:
        os.remove(stored)
        raise HTTPException(400, detail="空文件")

    sha = await run_in_threadpool(_sha256_file, stored)
    if not force:
        dup = db.find_by_sha(sha)
        if dup:
            try:
                os.remove(stored)
            except OSError:
                pass
            return _duplicate_payload(dup, consume=bool(consume))
    return await _enqueue(task_id, name, stored, size, client or x_client or "", sha256=sha)


@app.post("/api/upload/raw")
async def upload_raw(request: Request,
                     filename: str = Query(default=""),
                     client: str = Query(default=""),
                     x_filename: str = Header(default=""),
                     x_client: str = Header(default=""),
                     force: int = Query(default=0, ge=0, le=1),
                     ok: bool = Depends(check_token)):
    """把请求体直接当音频上传（iOS 17 的“获取 URL 内容”里“表单+文件”不好使时的备选）。

    快捷指令用法：方法 POST、请求体选“文件”（快捷指令输入）、再加一个请求头
    `X-Filename` = 文件名（用 URL 编码，例如 `%E5%BD%95%E9%9F%B3.m4a`）。
    """
    name = os.path.basename(_raw_filename(filename, x_filename, request.headers.get("content-type")))
    _check_ext(name)

    task_id = uuid.uuid4().hex[:12]
    stored = _stored_path(task_id, name)
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    try:
        with open(stored, "wb") as f:
            async for chunk in request.stream():
                if not chunk:
                    continue
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, detail=_too_big_msg(size))
                f.write(chunk)
    except HTTPException:
        try:
            os.remove(stored)
        except OSError:
            pass
        raise
    except Exception:
        try:
            os.remove(stored)
        except OSError:
            pass
        raise
    if size == 0:
        os.remove(stored)
        raise HTTPException(400, detail="空文件")

    sha = await run_in_threadpool(_sha256_file, stored)
    if not force:
        dup = db.find_by_sha(sha)
        if dup:
            try:
                os.remove(stored)
            except OSError:
                pass
            return _duplicate_payload(dup)
    return await _enqueue(task_id, name, stored, size, client or x_client or "", sha256=sha)


@app.get("/api/task/{task_id}")
def get_task(task_id: str, ok: bool = Depends(check_token)):
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(404, detail="没有这个任务")
    item = dict(t)
    item.pop("stored_path", None)
    payload = task_payload(item)
    payload["text"] = item.get("text") or ""
    return payload


@app.get("/api/task/{task_id}/text", response_class=PlainTextResponse)
async def get_text(task_id: str, wait: int = Query(default=0, ge=0, le=120),
                   title: int = Query(default=0, ge=0, le=1),
                   ok: bool = Depends(check_token)):
    """取**指定任务**的转写文本（随便取多少次都行，不影响取件队列）。

    wait=30 表示最多等 30 秒（长轮询），方便快捷指令一次拿到；title=1 在正文前加标题行。
    """
    deadline = time.time() + wait
    while True:
        t = db.get_task(task_id)
        if not t:
            raise HTTPException(404, detail="没有这个任务")
        if t["status"] == "done":
            return _text_response(t, title)
        if t["status"] == "error":
            return PlainTextResponse("转写失败: %s" % (t["error"] or ""), status_code=500,
                                     media_type="text/plain; charset=utf-8")
        if time.time() >= deadline:
            break
        await asyncio.sleep(0.5)

    retry = 3
    return PlainTextResponse(
        "还在处理中（%s），约 %d 秒后再试" % (t["status"], retry),
        status_code=202, media_type="text/plain; charset=utf-8",
        headers={"Retry-After": str(retry)})


@app.get("/api/tasks")
def tasks(limit: int = Query(default=20, ge=1, le=200),
          undelivered: int = Query(default=0, ge=0, le=1),
          ok: bool = Depends(check_token)):
    """任务列表。undelivered=1 只看“已转完还没被取走”的（快捷指令取件队列）。"""
    rows = db.list_tasks(limit, undelivered=bool(undelivered))
    for r in rows:
        r["title"] = note_title(r)
        r["text_url"] = "/api/task/%s/text" % r["id"]
        r["delivered"] = bool(r.get("delivered"))
    return {"tasks": rows}


def _recent_done(limit=0):
    """最近转写完成的记录（最新的在前）。limit=0 表示全部（不含 hidden 的测试录音）。"""
    sql = ("SELECT * FROM tasks WHERE status='done' AND length(coalesce(text,''))>0"
           " AND coalesce(hidden,0)=0 ORDER BY coalesce(finished_at, created_at) DESC")
    args = ()
    if limit and limit > 0:
        sql += " LIMIT ?"
        args = (limit,)
    with db.connect() as con:
        rows = con.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/recent", response_class=PlainTextResponse)
def recent_list(limit: int = Query(default=0, ge=0, le=500), ok: bool = Depends(check_token)):
    """最近转写记录清单：编号 + 标题。默认列出全部；快捷指令里显示给用户，
    输编号去 /api/recent/text?pick=N 取回。"""
    rows = _recent_done(limit)
    if not rows:
        return PlainTextResponse("（还没有转写记录）", media_type="text/plain; charset=utf-8",
                                 headers={"Cache-Control": "no-store"})
    lines = ["%d. %s" % (i, note_title(r)) for i, r in enumerate(rows, 1)]
    lines.append("")
    if len(rows) <= 12:
        tip = "输入编号重建备忘录：%s" % "、".join(str(i) for i in range(1, len(rows) + 1))
    else:
        tip = "输入编号重建备忘录：1~%d（对应上面的编号）" % len(rows)
    lines.append(tip)
    return PlainTextResponse("\n".join(lines), media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-store"})


@app.get("/api/recent/text", response_class=PlainTextResponse)
def recent_text(pick: str = Query(default="1"), title: int = Query(default=1, ge=0, le=1),
                ok: bool = Depends(check_token)):
    """按编号（1 = 最新）或任务号，取回一条历史转写的文本。"""
    p = (pick or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{6,16}", p) and not p.isdigit():
        t = db.get_task(p.lower())
        if not t:
            raise HTTPException(404, detail="没有这个任务号")
        if t["status"] != "done":
            raise HTTPException(409, detail="这条还在处理（%s），等一会儿再试" % t["status"])
    elif p.isdigit():
        n = int(p)
        rows = _recent_done(max(n, 1))
        if n < 1 or n > len(rows):
            raise HTTPException(404, detail="编号超出范围（当前只有 %d 条已完成的记录）" % len(rows))
        t = rows[n - 1]
    else:
        raise HTTPException(400, detail="pick 填编号（数字）或任务号")
    log("按编号重取 %s %s" % (t["id"], t["filename"]))
    return _text_response(t, title)


@app.post("/api/task/{task_id}/requeue")
def requeue_task(task_id: str, ok: bool = Depends(check_token)):
    """把一条已完成的转写重新放回取件队列（不重新转写），方便再次导出。"""
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(404, detail="没有这个任务")
    if t["status"] != "done":
        raise HTTPException(409, detail="只有已完成的任务能重新入队（当前 %s）" % t["status"])
    db.mark_undelivered(t["id"])
    log("重新入队 %s %s" % (t["id"], t["filename"]))
    return {"task_id": t["id"], "requeued": True, "title": note_title(t),
            "text_len": len(t.get("text") or ""), "text_url": "/api/task/%s/text" % t["id"]}


@app.post("/api/backup")
def backup_now(ok: bool = Depends(check_token)):
    """手动立刻做一次数据库快照（服务每天也会自动做一次）。"""
    path = db.backup()
    log("手动快照 %s" % path)
    return {"db_backup": path, "records": records.count(), "records_dir": records.RECORDS_DIR}


@app.post("/api/task/{task_id}/retry")
def retry(task_id: str, ok: bool = Depends(check_token)):
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(404, detail="没有这个任务")
    if t["status"] != "error":
        raise HTTPException(400, detail="只有失败的任务能重试")
    with db.connect() as con:
        con.execute("UPDATE tasks SET status='queued', error=NULL, started_at=NULL,"
                    " finished_at=NULL WHERE id=?", (task_id,))
    wait, position = estimate_wait(t["duration"])
    return {"task_id": task_id, "status": "queued", "eta_seconds": wait, "queue_position": position}


@app.get("/api/next")
def next_task(peek: int = Query(default=0, ge=0, le=1), ok: bool = Depends(check_token)):
    """取最早一条已完成、还没被取走的转写；取走后标记 delivered，下次不会重复返回。"""
    t = db.next_deliverable()
    if t:
        if not peek:
            db.mark_delivered(t["id"])
        return {"task_id": t["id"], "filename": clean_filename(t["filename"] or ""),
                "title": note_title(t),
                "duration": round(t["duration"] or 0, 2), "text": t["text"] or "",
                "delivered": not peek}
    st = db.pending_counts()
    if st:
        return UTF8JSONResponse(status_code=202, headers={"Retry-After": "3"},
                            content={"status": "pending", "queued": st.get("queued", 0),
                                     "running": st.get("running", 0),
                                     "message": "还在转写，稍后再试"})
    return Response(status_code=204)


def note_title(t):
    """备忘录的标题行：放文件名或“语音转写 + 时间”，避免整段正文被 Notes 当标题撑大。"""
    name = clean_filename(t["filename"] or "") or "语音转写"
    stem = os.path.splitext(name)[0][:40]
    dur = int(round(t["duration"] or 0))
    stamp = time.strftime("%m-%d %H:%M", time.localtime(t["created_at"] or time.time()))
    if dur >= 60:
        dur_txt = "%d 分 %d 秒" % (dur // 60, dur % 60)
    else:
        dur_txt = "%d 秒" % dur
    return "%s · %s · %s" % (stem, dur_txt, stamp)


def _text_response(t, title=0):
    """把一条已完成任务的文本包成 PlainTextResponse（带任务号/文件名/标题头）。"""
    headers = {"X-Task-Id": t["id"],
               "X-Filename": urllib.parse.quote(clean_filename(t["filename"] or "")),
               "X-Title": urllib.parse.quote(note_title(t)),
               "Cache-Control": "no-store"}
    text = t["text"] or ""
    if title and text:
        text = note_title(t) + "\n\n" + text
    return PlainTextResponse(text, headers=headers,
                             media_type="text/plain; charset=utf-8")


@app.get("/api/next/text", response_class=PlainTextResponse)
async def next_text(task_id: str = Query(default=""),
                    wait: int = Query(default=0, ge=0, le=180),
                    peek: int = Query(default=0, ge=0, le=1),
                    title: int = Query(default=0, ge=0, le=1),
                    blank: int = Query(default=204, ge=200, le=299),
                    ok: bool = Depends(check_token)):
    """快捷指令 B 用：只返回“已经转完、还没被取走”的文本。

    没有就绪的文本时**立刻返回 204 空响应**（没有任何正文，快捷指令那边判“内容没有值”），
    不会返回正在转写的半成品。wait>0 时才做短暂轮询（最多 wait 秒，超时同样 204）。
    blank=200 时改成“200 + 空正文”，给个别把 204 当错误的 iOS 版本兜底。

    title=1：正文前面加一行标题（Notes 的第一行会显示成大字标题，单独一行才不会把整段撑大）。
    task_id=xxxx：点名取某一条（不管它之前有没有被取走过），用于“重新导出某个录音”。
    """
    if task_id:
        t = db.get_task(task_id)
        if not t:
            raise HTTPException(404, detail="没有这个任务")
        if t["status"] != "done":
            return Response(status_code=204, headers={
                "X-Pending": "1", "X-Status": t["status"], "Cache-Control": "no-store"})
        if not peek:
            db.mark_delivered(t["id"])
        return _text_response(t, title)
    deadline = time.time() + max(wait, 0)
    while True:
        t = db.next_deliverable()
        if t:
            if not peek:
                db.mark_delivered(t["id"])
            return _text_response(t, title)
        st = db.pending_counts()
        pending = sum(st.values()) if st else 0
        # 没有任何就绪文本：要么队列是空的，要么还在转 —— 两种情况都立刻回，不占着连接
        if pending == 0 or time.time() >= deadline:
            # 需求：没有可取内容时，接口要“什么都没有”，快捷指令判「内容 没有值」。
            # 默认 204 No Content（无正文、无 Content-Type），快捷指令那边就是“没有值”。
            # 万一某个 iOS 版本把 204 当错误，可以加 &blank=200 退化成“200 + 空正文”。
            headers = {"X-Pending": str(pending), "Cache-Control": "no-store"}
            if blank == 200:
                return PlainTextResponse("", headers=headers,
                                         media_type="text/plain; charset=utf-8")
            return Response(status_code=204, headers=headers)
        await asyncio.sleep(0.5)


@app.get("/", response_class=HTMLResponse)
def dashboard(ok: bool = Depends(check_token)):
    rows = db.list_tasks(50)
    alive, age = worker_alive()
    color = {"done": "#1a7f37", "running": "#9a6700", "queued": "#57606a", "error": "#cf222e"}
    trs = []
    for r in rows:
        st = r["status"]
        trs.append(
            "<tr><td>%s</td><td>%s</td><td>%.1fs</td><td style='color:%s'>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td><td><a href='/api/task/%s/text'>文本</a></td></tr>"
            % (r["created_at"] and time.strftime("%H:%M:%S", time.localtime(r["created_at"])),
               r["filename"], r["duration"] or 0, color.get(st, "#000"), st,
               ("%.1fs" % r["elapsed"]) if r["elapsed"] else "-",
               r["text_len"], (r["error"] or "")[:60], r["id"]))
    html = """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>语音转写任务</title>
<style>body{font-family:Segoe UI,Microsoft YaHei,sans-serif;margin:24px;color:#1f2328}
table{border-collapse:collapse;width:100%%}td,th{border-bottom:1px solid #d0d7de;padding:6px 8px;text-align:left;font-size:14px}
th{background:#f6f8fa}.bar{margin-bottom:16px;color:#57606a}</style></head><body>
<h2>语音转写任务</h2>
<div class="bar">worker：%s（心跳 %s）｜排队 %d｜待取件 %d｜RTF 均值 %s｜每 5 秒自动刷新</div>
<table><tr><th>时间</th><th>文件</th><th>时长</th><th>状态</th><th>转写耗时</th><th>字数</th><th>错误</th><th></th></tr>
%s</table></body></html>""" % (
        "运行中" if alive else "未运行",
        ("%.1fs 前" % age) if age is not None else "无",
        len(db.queue_state()["queued"]), len(db.list_tasks(200, undelivered=True)),
        db.get_meta("rtf_ema", config.RTF_DEFAULT),
        "".join(trs))
    return HTMLResponse(html)
