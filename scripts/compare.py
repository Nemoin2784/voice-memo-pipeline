# -*- coding: utf-8 -*-
"""同一段音频分别用不同 Vosk 模型转写，并排对比文字与速度。

用法:
    python compare.py 音频.wav                          # 默认只有 small 可用
    python compare.py 音频.m4a --models small 路径\\模型 --words
"""
import argparse
import difflib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcribe import (MODEL_ALIASES, DEFAULT_MODEL, peak_mem_mb,  # noqa: E402
                        transcribe_file)


def load(name):
    from vosk import Model
    path = MODEL_ALIASES.get(name, name)
    if not os.path.isdir(path):
        return None, path
    t = time.time()
    m = Model(path)
    return (m, time.time() - t), path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--models", nargs="+", default=list(MODEL_ALIASES))
    ap.add_argument("--words", action="store_true")
    args = ap.parse_args()

    from vosk import SetLogLevel
    SetLogLevel(-1)

    results = {}
    for name in args.models:
        t0 = time.time()
        loaded, path = load(name)
        if not loaded:
            print("跳过 %s: 模型目录不存在 (%s)" % (name, path), file=sys.stderr)
            continue
        model, t_load = loaded
        r = transcribe_file(model, args.audio, args.words)
        r["load"] = t_load
        r["wall"] = time.time() - t0
        results[name] = r
        del model

    if not results:
        print("没有可用模型", file=sys.stderr)
        return 1

    print("\n===== 对比结果 (%s, %.2f s 音频) =====" % (os.path.basename(args.audio),
                                                    next(iter(results.values()))["duration"]),
          file=sys.stderr)
    for name, r in results.items():
        print("\n--- %s ---" % name, file=sys.stderr)
        print("加载模型 %.2f s / 转写 %.2f s / RTF %.2f / 峰值内存 %s MB"
              % (r["load"], r["elapsed"], r["rtf"],
                 ("%.0f" % peak_mem_mb()) if peak_mem_mb() else "?"), file=sys.stderr)
        print(r["text"], file=sys.stderr)

    if len(results) == 2:
        (n1, r1), (n2, r2) = results.items()
        a, b = r1["text"].replace(" ", ""), r2["text"].replace(" ", "")
        sm = difflib.SequenceMatcher(None, a, b)
        diff = [op for op in sm.get_opcodes() if op[0] != "equal"]
        print("\n--- 差异 (%s vs %s, 字符级) ---" % (n1, n2), file=sys.stderr)
        if not diff:
            print("两模型输出完全一致", file=sys.stderr)
        for tag, i1, i2, j1, j2 in diff[:60]:
            print("  %-8s %-12s -> %-12s" % (tag, a[i1:i2] or "∅", b[j1:j2] or "∅"), file=sys.stderr)
        print("差异块数: %d, 相同字符占比 %.1f%%"
              % (len(diff), sm.ratio() * 100), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
