# -*- coding: utf-8 -*-
"""取件接口自测：上传 → 等完成 → peek 两次一致 → 正式取走 → 再取 204。

用法（服务已启动）：python tests\test_next.py [音频路径]
"""
import os
import sys
import time

import requests

BASE = os.environ.get("VOICE_BASE", "http://127.0.0.1:8765")
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_AUDIO = os.path.join(HERE, "..", "..", "audio", "sample_zh.wav")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_AUDIO
    path = os.path.abspath(path)
    with open(path, "rb") as f:
        r = requests.post(BASE + "/api/upload", files={"file": (os.path.basename(path), f, "audio/wav")},
                          data={"client": "test_next"}, timeout=60)
    r.raise_for_status()
    up = r.json()
    tid = up["task_id"]
    print("上传 %s -> %s，预计 %s 秒（第 %s 位）" % (up["filename"], tid, up["eta_seconds"], up["queue_position"]))

    for _ in range(120):
        t = requests.get(BASE + "/api/task/" + tid, timeout=10).json()
        if t["status"] in ("done", "error"):
            print("状态 %s，耗时 %s s" % (t["status"], t.get("elapsed")))
            break
        time.sleep(1)

    p1 = requests.get(BASE + "/api/next", params={"peek": 1}, timeout=10).text
    p2 = requests.get(BASE + "/api/next", params={"peek": 1}, timeout=10).text
    print("peek 两次一致：%s；包含本任务：%s" % (p1 == p2, tid in p1))

    got = requests.get(BASE + "/api/next", timeout=10).json()
    print("正式取走：%s %s，字符 %d" % (got["filename"], got["task_id"], len(got["text"])))

    r = requests.get(BASE + "/api/next", timeout=10)
    print("再取一次：HTTP %d（期望 204）" % r.status_code)


if __name__ == "__main__":
    main()
