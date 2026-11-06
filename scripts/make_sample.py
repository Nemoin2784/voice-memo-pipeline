# -*- coding: utf-8 -*-
"""用百度翻译的 TTS 接口合成中文样本，解码 mp3 -> 16kHz/16bit/单声道 WAV。

用法: python make_sample.py [文本文件] [输出wav]
"""
import io
import os
import sys
import urllib.parse
import urllib.request
import wave

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

text_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "audio", "sample_text.txt")
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "audio", "sample_zh.wav")

text = open(text_file, encoding="utf-8").read().strip()
print("文本:", text)

url = ("https://fanyi.baidu.com/gettts?lan=zh&spd=4&source=web&text="
       + urllib.parse.quote(text))
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
mp3 = urllib.request.urlopen(req, timeout=30).read()
print("mp3 字节:", len(mp3))

x, sr = sf.read(io.BytesIO(mp3), dtype="float32")
if x.ndim > 1:
    x = x.mean(axis=1)
print("原始: %d Hz, %.2f s" % (sr, len(x) / sr))

g = np.gcd(16000, sr)
x16 = resample_poly(x, 16000 // g, sr // g)
pcm = np.clip(x16 * 32767, -32768, 32767).astype(np.int16)

with wave.open(out, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes(pcm.tobytes())
print("已写入 %s  %.2f s" % (out, len(pcm) / 16000))
