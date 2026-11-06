# -*- coding: utf-8 -*-
"""从镜像下载指定版本的 wheel。

tuna 的 /pypi/<包>/json 快照比较旧，新版本会回落到 simple 索引（HTML）解析；
文件地址一律把 files.pythonhosted.org 改写到 mirrors.aliyun.com/pypi 上下载。

用法: python fetch_wheels.py 包名==版本 [包名==版本 ...]
不给参数就下载内置的 Web 依赖清单。
"""
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wheels")
TUNA = "https://pypi.tuna.tsinghua.edu.cn"
ALIYUN = "https://mirrors.aliyun.com/pypi"

DEFAULT = [
    # Web 服务
    "fastapi==0.115.6",
    "starlette==0.41.3",
    "pydantic==2.10.4",
    "pydantic-core==2.27.2",
    "annotated-types==0.7.0",
    "typing-extensions==4.12.2",
    "uvicorn==0.34.0",
    "h11==0.14.0",
    "click==8.1.8",
    "colorama==0.4.6",
    "python-multipart==0.0.20",
    "anyio==4.7.0",
    "idna==3.10",
    "sniffio==1.3.1",
    "exceptiongroup==1.2.2",
    # 识别引擎
    "sherpa-onnx==1.10.20",
    "numpy==1.26.4",
    "scipy==1.15.3",
    "soundfile==0.14.0",
    # 脚本用
    "requests==2.34.2",
    "tqdm==4.66.5",
]

USAGE = """用法:
    python scripts/fetch_wheels.py                 # 下载内置依赖清单到 wheels\\
    python scripts/fetch_wheels.py 包名==版本 ...  # 只下指定的包
然后离线安装:
    python -m pip install --no-index --find-links wheels -r requirements.txt
"""


def fetch_json(name):
    try:
        url = TUNA + "/pypi/%s/json" % name
        return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))
    except Exception:
        return None


def fetch_index(name):
    """返回 [(filename, 绝对 url), ...]"""
    url = TUNA + "/simple/%s/" % name
    h = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
    h = h.decode("utf-8", "replace")
    out = []
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>([^<]*)</a>', h):
        href = html.unescape(href).split("#")[0]
        href = urllib.parse.urljoin(url, href)
        fn = href.rsplit("/", 1)[-1] or text.strip()
        out.append((fn, href))
    return out


def pick(files):
    """files: [(filename, url)]，优先 cp310-win_amd64，其次纯 python wheel。"""
    wheels = [f for f in files if f[0].endswith(".whl")]
    for pref in ("cp310-cp310-win_amd64", "cp310-none-win_amd64",
                 "py3-none-any", "py2.py3-none-any"):
        for f in wheels:
            if pref in f[0]:
                return f
    return wheels[0] if wheels else None


def aliyun_url(u):
    if "files.pythonhosted.org" in u:
        path = u.split("files.pythonhosted.org", 1)[1].lstrip("/")
        return ALIYUN + "/" + path
    if "mirrors.aliyun.com" in u:
        return u
    return u


def fetch(spec):
    name, _, ver = spec.partition("==")
    files = []
    d = fetch_json(name)
    if d:
        if not ver:
            ver = d["info"]["version"]
        files = [(f["filename"], f["url"]) for f in (d["releases"].get(ver) or [])]
        if not files:
            # 版本比快照新：去 simple 索引里找
            idx = fetch_index(name)
            files = [f for f in idx if f[0].startswith(name.replace("-", "_") + "-" + ver)
                     or f[0].startswith(name + "-" + ver)]
    else:
        idx = fetch_index(name)
        files = [f for f in idx if not ver or ("-%s-" % ver) in f[0] or f[0].endswith("-%s.tar.gz" % ver)]
    if not files:
        print("!! %s==%s 没找到文件" % (name, ver))
        return False
    f = pick(files)
    if not f:
        print("!! %s==%s 没有 wheel（可能只有源码包）" % (name, ver))
        return False
    fn, url = f
    dst = os.path.join(OUT, fn)
    if os.path.exists(dst) and os.path.getsize(dst) > 1024:
        print("   已有", fn)
        return True
    url = aliyun_url(url)
    print("  下载 %s  <- %s" % (fn, url.split("/pypi/")[-1][:60]))
    tmp = dst + ".part"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, dst)
    print("        %.2f MB" % (os.path.getsize(dst) / 1048576))
    return True


def main():
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(USAGE)
        return 0
    specs = [a for a in args if not a.startswith("-")] or DEFAULT
    os.makedirs(OUT, exist_ok=True)
    ok = fail = 0
    for spec in specs:
        print(spec)
        try:
            if fetch(spec):
                ok += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            print("!! 失败 %s: %s" % (spec, e))
    print("完成 %d 个，失败 %d 个；wheels: %s" % (ok, fail, OUT))
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
