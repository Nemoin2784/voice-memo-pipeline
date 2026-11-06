# -*- coding: utf-8 -*-
"""转写记录存档：每条任务完成后在 data/records 下留一份人可读的 .txt，并追加 index.jsonl。

数据库（tasks.db）是主存储，这里是把正文摊平成纯文本的第二份备份：
- 即使以后换机器、删库、重建 SQLite，只要 data/records 在，历史转写都还在；
- 文件名带时间和任务号，方便按时间找；正文是 UTF-8 纯文本，记事本/备忘录/VSCode 都能开。
"""
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
RECORDS_DIR = os.path.join(DATA, "records")
INDEX = os.path.join(RECORDS_DIR, "index.jsonl")


def _safe(name, limit=60):
    stem = os.path.splitext(name or "audio")[0]
    stem = re.sub(r'[\\/:*?"<>|\s]+', "_", stem)
    return (stem or "audio")[:limit]


def _dur(sec):
    sec = int(round(sec or 0))
    if sec >= 3600:
        return "%d 时 %d 分 %d 秒" % (sec // 3600, sec % 3600 // 60, sec % 60)
    if sec >= 60:
        return "%d 分 %d 秒" % (sec // 60, sec % 60)
    return "%d 秒" % sec


def path_for(task):
    created = task.get("created_at") or time.time()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(created))
    return os.path.join(RECORDS_DIR, "%s_%s_%s.txt" % (stamp, task.get("id", "unknown"),
                                                       _safe(task.get("filename"))))


def save(task):
    """把一条已完成任务写成 txt + 追加索引；返回 txt 路径。重复调用不会覆盖已有文件。"""
    os.makedirs(RECORDS_DIR, exist_ok=True)
    text = task.get("text") or ""
    path = path_for(task)
    created = task.get("created_at") or time.time()
    if not os.path.exists(path):
        elapsed = task.get("elapsed")
        rtf = task.get("rtf")
        head = [
            "# 语音转写记录",
            "文件    : %s" % (task.get("filename") or ""),
            "时间    : %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created)),
            "时长    : %s" % _dur(task.get("duration")),
            "转写    : %s" % ("%.1f 秒（RTF %.2f）" % (elapsed, rtf) if elapsed and rtf
                             else "%.1f 秒" % (elapsed or 0)),
            "任务号  : %s" % (task.get("id") or ""),
            "来源    : %s" % (task.get("client") or "-"),
            "字数    : %d" % len(text),
            "",
            "-" * 40,
            "",
        ]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(head) + text + "\n")
    entry = {
        "id": task.get("id"),
        "filename": task.get("filename"),
        "created_at": created,
        "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created)),
        "duration": round(task.get("duration") or 0, 2),
        "elapsed": round(task.get("elapsed") or 0, 2),
        "chars": len(text),
        "path": os.path.relpath(path, DATA).replace("\\", "/"),
    }
    try:
        with open(INDEX, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return path


def count():
    try:
        return len([f for f in os.listdir(RECORDS_DIR) if f.endswith(".txt")])
    except OSError:
        return 0
