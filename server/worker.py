# -*- coding: utf-8 -*-
"""常驻转写进程：从 SQLite 领任务 → 转写 → 结果写回。

常驻模式（默认）启动时加载一次模型（约 12~15 s），之后每个任务只付识别时间；
per-task 模式则每个任务起一个 transcribe_para.py 子进程，隔离好但每次多等一次模型加载。

单独调试：python worker.py --once
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import config  # noqa: E402
import db  # noqa: E402
import records  # noqa: E402
import textfix  # noqa: E402

LOG_PATH = os.path.join(config.LOGS, "worker.log")
STATE = {"text": "starting"}


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def heartbeat(**extra):
    db.set_meta("worker_heartbeat", time.time())
    db.set_meta("worker_state", json.dumps(dict(STATE, **extra), ensure_ascii=False))


def start_heartbeat_thread():
    """独立线程每 2 秒打一次心跳，模型加载（十几秒）期间也不会被误判为死掉。"""
    def loop():
        while True:
            try:
                heartbeat()
            except Exception:
                pass
            time.sleep(2)

    t = threading.Thread(target=loop, name="heartbeat", daemon=True)
    t.start()
    return t


def run_resident(task, rec, punct, rules):
    import transcribe_para as tp
    path = task["stored_path"]
    t = time.time()
    r = tp.transcribe_file(rec, path, config.MAX_SEC, punct)
    fix = textfix.apply_to_result(r, rules) if rules else []
    elapsed = time.time() - t
    if fix:
        log("纠正 %s: %s" % (task["id"], textfix.format_stats(fix)))
    return r["text"], r["duration"], elapsed


def run_per_task(task, rules):
    """每个任务起一个 transcribe_para.py 子进程（--json 落盘再读回）。"""
    fd, jf = tempfile.mkstemp(suffix=".json", dir=config.DATA)
    os.close(fd)
    cmd = [config.PYTHON, os.path.join(config.SCRIPTS, "transcribe_para.py"),
           task["stored_path"], "--threads", str(config.THREADS), "--no-fix",
           "--max-sec", str(config.MAX_SEC), "--json", jf]
    t = time.time()
    try:
        p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           timeout=3600)
        if p.returncode != 0:
            raise RuntimeError(p.stderr.decode("utf-8", "replace")[-800:])
        with open(jf, encoding="utf-8") as f:
            data = json.load(f)
    finally:
        try:
            os.remove(jf)
        except OSError:
            pass
    elapsed = time.time() - t
    text, stats = textfix.apply_rules(data.get("text", ""), rules)
    if stats:
        log("纠正 %s: %s" % (task["id"], textfix.format_stats(stats)))
    return text, data.get("duration", task.get("duration") or 0), elapsed


def main():
    ap = argparse.ArgumentParser(description="常驻转写 worker")
    ap.add_argument("--mode", default=config.WORKER_MODE, choices=["resident", "per_task"])
    ap.add_argument("--once", action="store_true", help="只处理一个任务就退出（调试用）")
    args = ap.parse_args()

    db.init()
    db.set_meta("worker_pid", os.getpid())
    db.set_meta("worker_mode", args.mode)
    rules = textfix.load_rules(config.CORRECTIONS)
    start_heartbeat_thread()
    log("worker 启动 pid=%d 模式=%s 纠错规则=%d 条" % (os.getpid(), args.mode, len(rules)))

    rec = punct = None
    if args.mode == "resident":
        STATE["text"] = "loading"
        db.set_meta("model_ready", "0")
        heartbeat()
        t0 = time.time()
        import transcribe_para as tp
        rec = tp.make_recognizer(config.MODEL_DIR, config.THREADS)
        punct = tp.make_punctuation(config.PUNCT_DIR)
        load = time.time() - t0
        db.set_meta("model_ready", "1")
        db.set_meta("model_load_seconds", round(load, 2))
        log("模型加载完成 %.1f s（标点%s）" % (load, "开启" if punct else "关闭"))

    idle_since = time.time()
    while True:
        STATE["text"] = "idle"
        task = db.claim_next()
        if not task:
            if args.once:
                return 0
            time.sleep(0.4)
            continue
        STATE["text"] = "busy"
        heartbeat(current=task["id"])
        log("开始 %s %s (%.1f s)" % (task["id"], task["filename"], task.get("duration") or 0))
        t0 = time.time()
        try:
            if args.mode == "resident":
                text, dur, elapsed = run_resident(task, rec, punct, rules)
            else:
                text, dur, elapsed = run_per_task(task, rules)
            rtf = elapsed / dur if dur else None
            db.finish(task["id"], text=text, duration=dur, elapsed=elapsed, rtf=rtf)
            try:
                records.save(dict(task, text=text, duration=dur, elapsed=elapsed, rtf=rtf))
            except Exception as e:
                log("存档失败 %s: %s" % (task["id"], e))
            # 用指数滑动平均更新 RTF，给“等待时间”估算用
            ema = float(db.get_meta("rtf_ema", config.RTF_DEFAULT) or config.RTF_DEFAULT)
            if rtf:
                ema = 0.7 * ema + 0.3 * rtf
                db.set_meta("rtf_ema", round(ema, 4))
            log("完成 %s 用时 %.1f s RTF %.2f 文本 %d 字"
                % (task["id"], elapsed, rtf or 0, len(text or "")))
        except Exception as e:
            tb = traceback.format_exc(limit=4)
            db.finish(task["id"], error=str(e)[:2000])
            log("失败 %s: %s\n%s" % (task["id"], e, tb))
        finally:
            idle_since = time.time()
            if args.once:
                return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("worker 收到中断，退出")
