# -*- coding: utf-8 -*-
"""Vosk 中文离线转写（CPU 即可）。

用法:
    python transcribe.py 音频.wav                # 单个文件，打印文本
    python transcribe.py 录音1.m4a 录音2.mp3      # 多个文件
    python transcribe.py audio\\                   # 整个目录（只看音频后缀）
    python transcribe.py 音频.wav --words          # 词级时间戳
    python transcribe.py 音频.wav --srt 音频.srt   # 生成字幕
    python transcribe.py 音频.wav --json 结果.json # 完整结果落盘

`--outdir` 时每个文件另存一份同名 .txt。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_MODEL = os.path.join(ROOT, "models", "vosk-model-small-cn-0.22")
MODEL_ALIASES = {
    "small": os.path.join(ROOT, "models", "vosk-model-small-cn-0.22"),
}
FFMPEG = os.path.join(ROOT, "tools", "ffmpeg.exe")
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".mp4", ".amr"}

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import textfix  # noqa: E402  同目录的纠错模块


def peak_mem_mb():
    """当前进程峰值内存(MB)，仅 Windows。"""
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC),
                                               wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return None
        return pmc.PeakWorkingSetSize / 1048576
    except Exception:
        return None


def _resample_to_16k(x, rate):
    from scipy.signal import resample_poly
    g = np.gcd(16000, rate)
    x = resample_poly(x.astype(np.float32), 16000 // g, rate // g)
    return np.clip(x, -32768, 32767).astype(np.int16)


def _read_wav(path):
    with wave.open(path, "rb") as wf:
        nch, width, rate = wf.getnchannels(), wf.getsampwidth(), wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if width == 1:  # 8bit 无符号
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.int16) - 128) << 8
    elif width == 2:
        x = np.frombuffer(raw, dtype=np.int16)
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        x = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
             | (b[:, 2].astype(np.int32) << 16))
        x = (x >> 8).astype(np.int16)
    elif width == 4:
        x = (np.frombuffer(raw, dtype=np.int32) >> 16).astype(np.int16)
    else:
        raise ValueError("不支持的位深: %d 字节" % width)

    if nch > 1:
        x = x.reshape(-1, nch).mean(axis=1).astype(np.int16)
    return x, rate


def _read_soundfile(path):
    import soundfile as sf
    x, rate = sf.read(path, dtype="float32", always_2d=True)
    return np.clip(x.mean(axis=1) * 32767, -32768, 32767).astype(np.int16), rate


def _read_ffmpeg(path):
    """用随附的 ffmpeg.exe 转成 16k 单声道 wav 再读（m4a/aac/amr 等）。"""
    if not os.path.exists(FFMPEG):
        raise RuntimeError("需要 ffmpeg.exe 才能解码该格式，请放到 %s" % FFMPEG)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", path,
               "-ar", "16000", "-ac", "1", "-f", "wav", tmp.name]
        subprocess.run(cmd, check=True)
        return _read_wav(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def load_pcm(path):
    """任意常见音频 -> (int16 numpy 数组, 采样率)。依次尝试 wave / soundfile / ffmpeg。"""
    for reader in (_read_wav, _read_soundfile, _read_ffmpeg):
        try:
            x, rate = reader(path)
        except Exception:
            continue
        if rate != 16000:
            x = _resample_to_16k(x, rate)
        return x, 16000
    raise RuntimeError("无法解码音频文件: %s" % path)


def transcribe_file(model, path, want_words=False, want_segments=False):
    from vosk import KaldiRecognizer

    pcm, rate = load_pcm(path)
    dur = len(pcm) / rate
    rec = KaldiRecognizer(model, rate)
    rec.SetWords(want_words or want_segments)

    t = time.time()
    step = rate // 2  # 0.5 秒一块
    for i in range(0, len(pcm), step):
        rec.AcceptWaveform(pcm[i:i + step].tobytes())
    final = json.loads(rec.FinalResult())
    elapsed = time.time() - t

    words = final.get("result", [])
    segments = []
    if want_segments and words:
        # 按词间停顿(>=0.35s)切句，便于生成 srt
        cur = [words[0]]
        for w in words[1:]:
            if w["start"] - cur[-1]["end"] >= 0.35:
                segments.append(cur)
                cur = [w]
            else:
                cur.append(w)
        segments.append(cur)

    return {
        "path": path,
        "duration": dur,
        "text": final.get("text", ""),
        "words": words,
        "segments": [
            {"start": s[0]["start"], "end": s[-1]["end"], "text": "".join(w["word"] for w in s)}
            for s in segments
        ],
        "elapsed": elapsed,
        "rtf": elapsed / dur if dur else 0.0,
    }


def _fmt_ts(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def write_srt(segments, path):
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append("%d\n%s --> %s\n%s\n" % (i, _fmt_ts(seg["start"]), _fmt_ts(seg["end"]), seg["text"]))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def collect_inputs(args):
    files = []
    for a in args:
        if os.path.isdir(a):
            for name in sorted(os.listdir(a)):
                if os.path.splitext(name)[1].lower() in AUDIO_EXT:
                    files.append(os.path.join(a, name))
        elif os.path.isfile(a):
            files.append(a)
        else:
            print("跳过不存在的路径: %s" % a, file=sys.stderr)
    return files


def main():
    ap = argparse.ArgumentParser(description="Vosk 中文离线转写")
    ap.add_argument("inputs", nargs="+", help="音频文件或目录")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help="模型目录，或别名 small")
    ap.add_argument("--words", action="store_true", help="打印词级时间戳")
    ap.add_argument("--srt", help="生成 srt 字幕（单文件时生效）")
    ap.add_argument("--json", help="把完整结果写入 JSON（单文件时生效）")
    ap.add_argument("--outdir", help="每个音频另外保存同名 .txt 到该目录")
    ap.add_argument("--fix", default=textfix.DEFAULT_FIX, help="纠错表文件（默认 corrections.txt）")
    ap.add_argument("--no-fix", action="store_true", help="不做同音字纠正")
    args = ap.parse_args()

    fix_rules = [] if args.no_fix else textfix.load_rules(args.fix)
    if not args.no_fix:
        print("纠错表   : %s（%d 条规则）" % (args.fix, len(fix_rules)), file=sys.stderr)

    args.model = MODEL_ALIASES.get(args.model, args.model)
    if not os.path.isdir(args.model):
        print("模型目录不存在: %s\n可用别名: %s"
              % (args.model, ", ".join(MODEL_ALIASES)), file=sys.stderr)
        return 2

    from vosk import Model, SetLogLevel
    SetLogLevel(-1)

    t0 = time.time()
    model = Model(args.model)
    t_model = time.time() - t0

    files = collect_inputs(args.inputs)
    if not files:
        print("没有找到音频文件", file=sys.stderr)
        return 1

    print("模型加载 : %.2f s" % t_model, file=sys.stderr)
    mem = None
    ok = 0
    for idx, path in enumerate(files, 1):
        try:
            r = transcribe_file(model, path, args.words, want_segments=bool(args.srt))
        except Exception as e:
            print("[%d/%d] %s 失败: %s" % (idx, len(files), path, e), file=sys.stderr)
            continue
        ok += 1
        fix_stats = textfix.apply_to_result(r, fix_rules) if fix_rules else []
        if len(files) > 1:
            print("\n===== [%d/%d] %s =====" % (idx, len(files), os.path.basename(path)), file=sys.stderr)
        print(r["text"])
        print("音频时长 : %.2f s" % r["duration"], file=sys.stderr)
        print("转写耗时 : %.2f s (RTF %.2f, 即 1 秒音频耗 %.2f 秒)"
              % (r["elapsed"], r["rtf"], r["rtf"]), file=sys.stderr)
        if fix_stats:
            print("已纠正   : " + textfix.format_stats(fix_stats), file=sys.stderr)

        if args.words:
            for w in r["words"]:
                print("%8.2f-%8.2f  %s" % (w["start"], w["end"], w["word"]), file=sys.stderr)

        if args.srt and len(files) == 1:
            write_srt(r["segments"], args.srt)
            print("已写入 " + args.srt, file=sys.stderr)

        if args.json and len(files) == 1:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False, indent=2)
            print("已写入 " + args.json, file=sys.stderr)

        if args.outdir:
            os.makedirs(args.outdir, exist_ok=True)
            base = os.path.splitext(os.path.basename(path))[0]
            dst = os.path.join(args.outdir, base + ".txt")
            with open(dst, "w", encoding="utf-8") as f:
                f.write(r["text"] + "\n")
            print("已写入 " + dst, file=sys.stderr)

        mem = peak_mem_mb() or mem

    if mem:
        print("峰值内存 : %.0f MB" % mem, file=sys.stderr)
    print("完成 %d/%d 个文件，总耗时 %.1f s"
          % (ok, len(files), time.time() - t0), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
