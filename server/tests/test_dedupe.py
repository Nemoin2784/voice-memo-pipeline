# -*- coding: utf-8 -*-
"""验证：同一段音频重复上传不会重复转写；force=1 可以强制重转。"""
import json
import os
import sys

import requests

BASE = os.environ.get("VOICE_BASE", "http://127.0.0.1:8765")
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
AUDIO = os.environ.get("VOICE_TEST_AUDIO", os.path.join(PROJECT, "audio", "sample_zh.wav"))


def upload(path, **params):
    with open(path, "rb") as f:
        r = requests.post(BASE + "/api/upload", params=params,
                          files={"file": (os.path.basename(path), f, "audio/wav")},
                          timeout=120)
    return r.status_code, r.json()


def main():
    if not os.path.exists(AUDIO):
        print("跳过：找不到音频 %s（用 scripts/make_sample.py 生成，或设 VOICE_TEST_AUDIO）" % AUDIO)
        return 0
    print("音频:", AUDIO, "%.2f MB" % (os.path.getsize(AUDIO) / 1048576))
    s1, a = upload(AUDIO)
    print("第一次上传:", s1, a.get("task_id"), a.get("status"), a.get("eta_seconds"))
    s2, b = upload(AUDIO)
    print("第二次上传:", s2, b.get("task_id"), b.get("status"),
          "duplicate=%s" % b.get("duplicate"), b.get("message"))
    s3, c = upload(AUDIO, force=1)
    print("force=1 上传:", s3, c.get("task_id"), c.get("status"),
          "duplicate=%s" % c.get("duplicate"))

    ok = (s2 == 200 and b.get("duplicate") is True and b.get("task_id") == a.get("task_id")
          and c.get("task_id") != a.get("task_id") and not c.get("duplicate"))
    print("\n结论:", "通过 ✔ 重复的上传被拦下、force 能重转" if ok else "失败 ✘")
    print(json.dumps({"first": a.get("task_id"), "dup": b.get("task_id"),
                      "forced": c.get("task_id")}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
