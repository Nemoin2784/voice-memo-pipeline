# -*- coding: utf-8 -*-
"""下载识别模型（不进 git，第一次使用时跑一次）。

默认从 hf-mirror.com 拉（国内快），用 --mirror hf 切回 huggingface.co。

用法:
    python scripts/get_models.py                # 主模型 + 标点模型
    python scripts/get_models.py --no-punct     # 只要主模型（省 280MB 内存里的标点重量）
    python scripts/get_models.py --vosk         # 额外下 Vosk 小模型（备用通道）
    python scripts/get_models.py --mirror hf    # 走 huggingface.co
"""
import argparse
import os
import sys
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")

MIRRORS = {
    "hf-mirror": "https://hf-mirror.com",
    "hf": "https://huggingface.co",
}

# repo -> 需要的文件
JOBS = {
    "paraformer": {
        "repo": "csukuangfj/sherpa-onnx-paraformer-zh-2024-03-09",
        "files": ["model.int8.onnx", "tokens.txt", "am.mvn"],
        "dir": "sherpa-onnx-paraformer-zh-2024-03-09",
        "optional": False,
    },
    "punct": {
        "repo": "csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12",
        "files": ["model.onnx"],
        "dir": "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12",
        "optional": True,
    },
}
VOSK_ZIP = ("guloooovoooo/vosk-model-small-cn", "vosk-model-small-cn.zip")

UA = {"User-Agent": "Mozilla/5.0 (voice-memo-pipeline setup)"}


def human(n):
    return "%.1f MB" % (n / 1048576.0) if n >= 1048576 else "%.1f KB" % (n / 1024.0)


def download(url, dst, retries=5):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        print("  已有 %s（%s），跳过" % (os.path.basename(dst), human(os.path.getsize(dst))))
        return dst
    tmp = dst + ".part"
    t0 = time.time()
    for attempt in range(1, retries + 1):
        have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
        try:
            req = urllib.request.Request(url, headers=dict(UA, Range="bytes=%d-" % have))
            with urllib.request.urlopen(req, timeout=60) as r:
                total = have + int(r.headers.get("Content-Length") or 0)
                done, last = have, 0.0
                with open(tmp, "ab") as f:
                    while True:
                        b = r.read(262144)
                        if not b:
                            break
                        f.write(b)
                        done += len(b)
                        if time.time() - last > 1.5:
                            last = time.time()
                            pct = done * 100.0 / total if total else 0
                            speed = done / max(time.time() - t0, 0.1) / 1048576
                            sys.stdout.write("\r  %5.1f%%  %s / %s  %.1f MB/s   "
                                             % (pct, human(done), human(total), speed))
                            sys.stdout.flush()
            print()
            if total and os.path.getsize(tmp) < total:
                raise IOError("下载不完整：%d / %d" % (os.path.getsize(tmp), total))
            os.replace(tmp, dst)
            print("  完成 %s（%s，%.1f 秒）" % (os.path.basename(dst), human(os.path.getsize(dst)),
                                            time.time() - t0))
            return dst
        except Exception as e:  # noqa: BLE001
            print("\n  第 %d/%d 次失败：%s" % (attempt, retries, e))
            if attempt == retries:
                raise
            time.sleep(5)
    return dst


def fetch_model(name, spec, base):
    out_dir = os.path.join(MODELS, spec["dir"])
    print("\n[%s] %s" % (name, spec["repo"]))
    for fn in spec["files"]:
        url = "%s/%s/resolve/main/%s" % (base, spec["repo"], urllib.parse.quote(fn))
        download(url, os.path.join(out_dir, fn))
    print("  -> %s" % out_dir)


def fetch_vosk(base):
    repo, fn = VOSK_ZIP
    zip_path = os.path.join(MODELS, fn)
    print("\n[vosk] %s" % repo)
    download("%s/%s/resolve/main/%s" % (base, repo, fn), zip_path)
    target = os.path.join(MODELS, "vosk-model-small-cn-0.22")
    if os.path.isdir(target) and os.listdir(target):
        print("  已解压过，跳过")
        return
    print("  解压到 %s" % target)
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.startswith("__MACOSX/")]
        top = sorted({n.split("/")[0] for n in names})
        root = top[0] if len(top) == 1 else "vosk-model-small-cn"
        for n in names:
            if n.endswith("/"):
                continue
            rel = n[len(root) + 1:] if n.startswith(root + "/") else n
            dst = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open(n) as src, open(dst, "wb") as out:
                out.write(src.read())


def main():
    ap = argparse.ArgumentParser(description="下载 voice-memo-pipeline 需要的模型")
    ap.add_argument("--mirror", choices=sorted(MIRRORS), default="hf-mirror")
    ap.add_argument("--no-punct", action="store_true", help="不下载标点模型（省 280MB）")
    ap.add_argument("--vosk", action="store_true", help="额外下载 Vosk 小模型（备用通道）")
    args = ap.parse_args()
    base = MIRRORS[args.mirror]
    os.makedirs(MODELS, exist_ok=True)
    print("镜像：%s   目标目录：%s" % (base, MODELS))

    fetch_model("paraformer", JOBS["paraformer"], base)
    if args.no_punct:
        print("\n[punct] 跳过（--no-punct）")
    else:
        fetch_model("punct", JOBS["punct"], base)
    if args.vosk:
        fetch_vosk(base)

    print("\n全部完成。启动服务：\n  cd server\n  python -m uvicorn app:app --host 0.0.0.0 --port 8765")


if __name__ == "__main__":
    main()
