# -*- coding: utf-8 -*-
"""断点续传下载 + 进度输出 + 失败重试。

用法: python dl.py URL 目标文件 [最大重试次数]
"""
import os
import sys
import time
import urllib.request

url, dst = sys.argv[1], sys.argv[2]
retries = int(sys.argv[3]) if len(sys.argv) > 3 else 20
ua = {"User-Agent": "Mozilla/5.0"}
tmp = dst + ".part"
os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)

t0 = time.time()
attempt = 0
while True:
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    try:
        req = urllib.request.Request(url, headers=dict(ua, Range="bytes=%d-" % have))
        r = urllib.request.urlopen(req, timeout=60)
        total = have + int(r.headers.get("Content-Length") or 0)
        if have and r.status == 200:      # 服务器不支持断点，重头来
            have = 0
            tmp = dst + ".part"
        done = have
        last = 0
        with open(tmp, "ab") as f:
            while True:
                b = r.read(262144)
                if not b:
                    break
                f.write(b)
                done += len(b)
                if time.time() - last > 2:
                    last = time.time()
                    pct = done * 100.0 / total if total else 0
                    rate = done / max(time.time() - t0, 0.1) / 1024
                    print("%5.1f%%  %6.1f/%6.1f MB  %7.1f KB/s"
                          % (pct, done / 1048576, total / 1048576, rate), flush=True)
        if total and os.path.getsize(tmp) < total:
            raise IOError("不完整: %d/%d" % (os.path.getsize(tmp), total))
        break
    except Exception as e:
        attempt += 1
        if attempt > retries:
            print("FAILED after %d attempts: %s" % (attempt, e), flush=True)
            sys.exit(1)
        print("retry %d/%d in 10s (%s)" % (attempt, retries, e), flush=True)
        time.sleep(10)

os.replace(tmp, dst)
print("DONE %s  %.1f MB in %.1f s" % (dst, os.path.getsize(dst) / 1048576, time.time() - t0), flush=True)
