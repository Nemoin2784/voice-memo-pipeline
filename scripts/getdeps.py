# -*- coding: utf-8 -*-
"""解析 srt / tqdm 的 wheel URL(取 pypi JSON)，改写到 aliyun 镜像并下载。"""
import json
import os
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wheels")


def j(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))


for pkg in ["srt", "tqdm"]:
    d = j("https://pypi.tuna.tsinghua.edu.cn/pypi/%s/json" % pkg)
    ver = d["info"]["version"]
    cands = [f for f in d["releases"].get(ver, [])
             if f["filename"].endswith("py3-none-any.whl") or "py2.py3-none-any" in f["filename"]]
    if not cands:
        cands = d["releases"].get(ver, [])
    f = cands[0]
    path = f["url"].split("pythonhosted.org")[-1].lstrip("/")
    url = "https://mirrors.aliyun.com/pypi/" + path
    dst = os.path.join(OUT, f["filename"])
    print(pkg, ver, f["filename"])
    urllib.request.urlretrieve(url, dst)
    print("  ->", dst, os.path.getsize(dst), "bytes")
