# -*- coding: utf-8 -*-
"""验证 /api/next/text?title=1：上传一段样本，取回时正文前应有一行标题。

用法: python tests\test_title.py ..\audio\sample_zh.wav
"""
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.environ.get("VOICE_BASE", "http://127.0.0.1:8765")
AUDIO = sys.argv[1] if len(sys.argv) > 1 else os.path.join("..", "audio", "sample_zh.wav")


def post_file(path):
    name = os.path.basename(path)
    boundary = "----voicetest%d" % int(time.time())
    with open(path, "rb") as f:
        data = f.read()
    body = (
        ("--%s\r\n" % boundary).encode()
        + ('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % name).encode("utf-8")
        + b"Content-Type: application/octet-stream\r\n\r\n"
        + data
        + ("\r\n--%s--\r\n" % boundary).encode()
    )
    req = urllib.request.Request(
        BASE + "/api/upload", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
    return urllib.request.urlopen(req, timeout=60)


def main():
    if not os.path.exists(AUDIO):
        print("找不到音频:", AUDIO)
        return 2
    r = post_file(AUDIO)
    print("上传:", r.status, r.read().decode("utf-8"))
    url = BASE + "/api/next/text?wait=60&title=1"
    with urllib.request.urlopen(url, timeout=90) as resp:
        text = resp.read().decode("utf-8")
        print("状态:", resp.status)
        print("X-Task-Id:", resp.headers.get("X-Task-Id"))
        print("X-Filename:", urllib.parse.unquote(resp.headers.get("X-Filename") or ""))
        print("X-Title:", urllib.parse.unquote(resp.headers.get("X-Title") or ""))
    lines = text.split("\n")
    print("---- 前 4 行 ----")
    for i, line in enumerate(lines[:4]):
        print("%d| %s" % (i, line[:100]))
    ok = len(lines) >= 3 and lines[1] == "" and len(lines[0]) < 80
    print("标题行:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
