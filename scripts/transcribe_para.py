# -*- coding: utf-8 -*-
"""Paraformer-zh 离线转写（sherpa-onnx，CPU，无需 PyTorch）。

用法:
    python transcribe_para.py 音频.wav
    python transcribe_para.py 录音.m4a --threads 2
    python transcribe_para.py audio\\ --outdir audio\\para
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textfix  # noqa: E402
from transcribe import (HERE, ROOT, peak_mem_mb, load_pcm,  # noqa: E402
                        collect_inputs, write_srt)

DEFAULT_DIR = os.path.join(ROOT, "models", "sherpa-onnx-paraformer-zh-2024-03-09")
DEFAULT_PUNCT_DIR = os.path.join(ROOT, "models", "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12")


def make_recognizer(model_dir, threads):
    import sherpa_onnx
    cfg = dict(
        paraformer=os.path.join(model_dir, "model.int8.onnx"),
        tokens=os.path.join(model_dir, "tokens.txt"),
        num_threads=threads,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
    )
    if not os.path.exists(cfg["paraformer"]):
        alt = os.path.join(model_dir, "model.onnx")
        if os.path.exists(alt):
            cfg["paraformer"] = alt
        else:
            raise RuntimeError("模型文件不存在: %s" % cfg["paraformer"])
    return sherpa_onnx.OfflineRecognizer.from_paraformer(**cfg)


def make_punctuation(model_dir):
    """标点模型（可选）：给没有标点的识别结果补上，。？"""
    import sherpa_onnx
    path = os.path.join(model_dir, "model.onnx")
    if not os.path.exists(path):
        return None
    cfg = sherpa_onnx.OfflinePunctuationConfig(
        model=sherpa_onnx.OfflinePunctuationModelConfig(ct_transformer=path, num_threads=1),
    )
    return sherpa_onnx.OfflinePunctuation(cfg)


def add_punctuation(punct, text, piece_len=2000):
    """补标点。CT-Transformer 一次吃整段效果最好（1146 字只要 0.9s），
    超长录音再按 2000 字切段，避免显存/内存爆掉。"""
    if not punct or not text:
        return text
    if len(text) <= piece_len:
        return punct.add_punctuation(text)
    out = []
    for i in range(0, len(text), piece_len):
        out.append(punct.add_punctuation(text[i:i + piece_len]))
    return "".join(out)


def split_chunks(x, rate=16000, max_sec=25.0, min_sec=6.0, win_sec=0.3):
    """按能量最低点切块，避免把一句话切两半（Paraformer 单段别太长）。"""
    n = len(x)
    max_len = int(max_sec * rate)
    min_len = int(min_sec * rate)
    win = max(256, int(win_sec * rate))
    pos = 0
    chunks = []
    while pos < n:
        if n - pos <= max_len:
            chunks.append((pos, x[pos:]))
            break
        # 在 [min_len, max_len] 里找最安静的一段作为切点
        seg = x[pos + min_len:pos + max_len]
        rms = np.convolve(seg.astype(np.float32) ** 2, np.ones(win, dtype=np.float32) / win, "valid")
        cut = pos + min_len + int(np.argmin(rms)) + win // 2
        chunks.append((pos, x[pos:cut]))
        pos = cut
    return chunks


def transcribe_file(recognizer, path, max_sec=25.0, punct=None):
    pcm, rate = load_pcm(path)
    pcm = pcm.astype(np.float32) / 32768.0
    dur = len(pcm) / rate
    t = time.time()
    parts = []
    for start, seg in split_chunks(pcm, rate, max_sec):
        stream = recognizer.create_stream()
        stream.accept_waveform(rate, seg)
        recognizer.decode_stream(stream)
        txt = stream.result.text.strip()
        if txt:
            parts.append(txt)
    elapsed = time.time() - t
    t2 = time.time()
    text = add_punctuation(punct, "".join(parts))
    elapsed += time.time() - t2
    return {
        "path": path,
        "duration": dur,
        "text": text,
        "elapsed": elapsed,
        "rtf": elapsed / dur if dur else 0.0,
    }


def main():
    ap = argparse.ArgumentParser(description="Paraformer-zh 离线转写 (sherpa-onnx)")
    ap.add_argument("inputs", nargs="+", help="音频文件或目录")
    ap.add_argument("--model-dir", default=DEFAULT_DIR)
    ap.add_argument("--threads", type=int, default=2, help="推理线程数（i3 双核建议 2）")
    ap.add_argument("--max-sec", type=float, default=25.0, help="单段最长秒数")
    ap.add_argument("--outdir", help="每个音频另存同名 .txt")
    ap.add_argument("--json", help="完整结果写入 JSON（单文件）")
    ap.add_argument("--punct-dir", default=DEFAULT_PUNCT_DIR, help="标点模型目录")
    ap.add_argument("--no-punct", action="store_true", help="关闭标点还原")
    ap.add_argument("--fix", default=textfix.DEFAULT_FIX, help="纠错表文件（默认 corrections.txt）")
    ap.add_argument("--no-fix", action="store_true", help="不做同音字纠正")
    args = ap.parse_args()

    fix_rules = [] if args.no_fix else textfix.load_rules(args.fix)

    t0 = time.time()
    rec = make_recognizer(args.model_dir, args.threads)
    t_model = time.time() - t0

    punct = None
    if not args.no_punct:
        try:
            punct = make_punctuation(args.punct_dir)
        except Exception as e:
            print("标点模型加载失败，跳过: %s" % e, file=sys.stderr)
    t_punct = time.time() - t0 - t_model

    files = collect_inputs(args.inputs)
    if not files:
        print("没有找到音频文件", file=sys.stderr)
        return 1

    print("模型加载 : %.2f s" % t_model, file=sys.stderr)
    print("标点模型 : %s (%.2f s)" % ("已启用" if punct else "未启用", t_punct), file=sys.stderr)
    if not args.no_fix:
        print("纠错表   : %s（%d 条规则）" % (args.fix, len(fix_rules)), file=sys.stderr)
    ok = 0
    all_results = []
    for idx, path in enumerate(files, 1):
        try:
            r = transcribe_file(rec, path, args.max_sec, punct)
        except Exception as e:
            print("[%d/%d] %s 失败: %s" % (idx, len(files), path, e), file=sys.stderr)
            continue
        ok += 1
        fix_stats = textfix.apply_to_result(r, fix_rules) if fix_rules else []
        all_results.append(r)
        print("\n===== [%d/%d] %s =====" % (idx, len(files), os.path.basename(path)), file=sys.stderr)
        print(r["text"])
        print("音频时长 : %.2f s" % r["duration"], file=sys.stderr)
        print("转写耗时 : %.2f s (RTF %.2f)" % (r["elapsed"], r["rtf"]), file=sys.stderr)
        if fix_stats:
            print("已纠正   : " + textfix.format_stats(fix_stats), file=sys.stderr)

        if args.outdir:
            os.makedirs(args.outdir, exist_ok=True)
            base = os.path.splitext(os.path.basename(path))[0]
            dst = os.path.join(args.outdir, base + ".txt")
            with open(dst, "w", encoding="utf-8") as f:
                f.write(r["text"] + "\n")
            print("已写入 " + dst, file=sys.stderr)

    mem = peak_mem_mb()
    if mem:
        print("\n峰值内存 : %.0f MB" % mem, file=sys.stderr)

    if args.json and len(all_results) == 1:
        import json
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(all_results[0], f, ensure_ascii=False, indent=2)
        print("已写入 " + args.json, file=sys.stderr)

    print("完成 %d/%d 个文件，总耗时 %.1f s"
          % (ok, len(files), time.time() - t0), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
