# -*- coding: utf-8 -*-
"""验证“一边转写、一边继续上传”不会互相覆盖，且严格串行排队。

做法：连续上传 3 个文件（第 1 个是长录音），每 1.5 秒轮询一次 /api/tasks，
观察状态变化与完成顺序，最后比对每条的文本是否都在、且内容各不相同。

用法: python tests\test_queue.py
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("VOICE_BASE", "http://127.0.0.1:8765")
HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO = os.path.join(HERE, "..", "..", "audio")


def post_file(path, client="queue-test"):
    name = os.path.basename(path)
    boundary = "----q%d" % int(time.time() * 1000)
    with open(path, "rb") as f:
        data = f.read()
    body = (
        ("--%s\r\n" % boundary).encode()
        + ('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % name).encode("utf-8")
        + b"Content-Type: application/octet-stream\r\n\r\n"
        + data
        + ("\r\n--%s\r\n" % boundary).encode()
        + ('Content-Disposition: form-data; name="client"\r\n\r\n%s\r\n' % client).encode("utf-8")
        + ("--%s--\r\n" % boundary).encode()
    )
    req = urllib.request.Request(
        BASE + "/api/upload?force=1", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def tasks():
    with urllib.request.urlopen(BASE + "/api/tasks?limit=20", timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))["tasks"]


def task_text(tid):
    """任务详情里不带正文，正文走单独的 text 接口。"""
    try:
        with urllib.request.urlopen("%s/api/task/%s/text?wait=5" % (BASE, tid), timeout=30) as r:
            return r.read().decode("utf-8")
    except Exception as e:  # 202/204 等
        return "<%s>" % e


def main():
    # 默认用 audio/ 下的示例音频；也可以 VOICE_TEST_DIR 指向自己的目录
    candidates = ["jldx_full.wav", "deo_16k.wav", "sample_zh.wav"]
    files = [os.path.join(AUDIO, n) for n in candidates]
    files = [p for p in files if os.path.exists(p)]
    if len(files) < 2:
        print("跳过：audio/ 下不到 2 个测试音频（先用 scripts/make_sample.py 生成，"
              "或用 VOICE_TEST_DIR 指定目录）")
        return 0

    t0 = time.time()
    ids = []
    print("== 连续上传（不等待上一个完成）==")
    for p in files:
        info = post_file(p)
        ids.append(info["task_id"])
        print("  + %-16s %.2fs  task=%s 位次=%d 预计=%ds"
              % (os.path.basename(p), info["duration"], info["task_id"],
                 info["queue_position"], info["eta_seconds"]))

    last = {}
    print("== 轮询状态（每 1.5s）==")
    while time.time() - t0 < 300:
        rows = {t["id"]: t for t in tasks() if t["id"] in ids}
        line = []
        for tid in ids:
            r = rows.get(tid) or {}
            st = r.get("status", "?")
            line.append("%s:%s" % (tid[:6], st))
            if last.get(tid) != st:
                print("  %5.1fs  %s -> %s（%.1fs 处理）"
                      % (time.time() - t0, tid[:6], st, r.get("elapsed") or 0))
                last[tid] = st
        if all((rows.get(i) or {}).get("status") in ("done", "error") for i in ids):
            break
        time.sleep(1.5)

    print("== 结果 ==")
    ok = True
    rows = {t["id"]: t for t in tasks() if t["id"] in ids}
    texts = []
    for tid in ids:
        r = rows.get(tid) or {}
        txt = task_text(tid)
        texts.append(txt)
        print("  %s  %-16s %s  %.1fs  %d 字  %s"
              % (tid, r.get("filename", "?"), r.get("status"), r.get("elapsed") or 0,
                 len(txt), txt[:24].replace("\n", " ")))
        if r.get("status") != "done" or not txt or txt.startswith("<"):
            ok = False
    if len(set(texts)) != len(texts):
        print("  !! 文本重复，可能被覆盖")
        ok = False
    else:
        print("  三份文本互不相同：没有互相覆盖")

    # 完成顺序应与上传顺序一致（串行 FIFO）
    order = sorted(ids, key=lambda i: (rows.get(i) or {}).get("finished_at") or 0)
    print("  完成顺序:", " -> ".join(i[:6] for i in order),
          "（上传顺序:", " -> ".join(i[:6] for i in ids), "）")
    if order != ids:
        ok = False

    up = sorted(os.listdir(os.path.join(HERE, "..", "data", "uploads")))
    mine = [f for f in up if any(f.startswith(i) for i in ids)]
    print("  磁盘上三个上传文件:", mine)
    if len(mine) != 3:
        ok = False

    # 取回顺序：/api/next/text 应该按上传顺序一条条给，第四条返回空正文
    got = []
    for _ in range(4):
        try:
            with urllib.request.urlopen(BASE + "/api/next/text?wait=3", timeout=20) as r:
                if not r.headers.get("X-Task-Id"):
                    got.append("空")
                    continue
                got.append((r.headers.get("X-Task-Id") or "")[:6])
        except urllib.error.HTTPError as e:
            got.append(str(e.code))
    print("  /api/next/text 依次返回:", " -> ".join(got),
          "（期望", " -> ".join(i[:6] for i in ids), "-> 空 ）")
    if got[:3] != [i[:6] for i in ids] or got[3] != "空":
        ok = False

    print("结论:", "PASS 严格串行、互不覆盖" if ok else "FAIL 见上")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
