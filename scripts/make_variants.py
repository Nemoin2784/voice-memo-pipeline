# -*- coding: utf-8 -*-
"""从 16k 单声道样本派生测试变体：44.1k 立体声、约 3 分钟长音频。"""
import os
import wave

import numpy as np
from scipy.signal import resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
src = os.path.join(ROOT, "audio", "sample_zh.wav")

with wave.open(src) as w:
    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

# 44.1k 立体声
up = resample_poly(pcm.astype(np.float32), 441, 160)
st = np.stack([up, up], axis=1).astype(np.int16)
with wave.open(os.path.join(ROOT, "audio", "sample_zh_44k_stereo.wav"), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(44100)
    w.writeframes(st.tobytes())
print("44.1k stereo ok", len(st) / 44100, "s")

# 长音频：重复 18 次 + 0.3s 静音
sil = np.zeros(int(16000 * 0.3), dtype=np.int16)
long = np.concatenate([np.concatenate([pcm, sil]) for _ in range(18)])
with wave.open(os.path.join(ROOT, "audio", "sample_zh_long.wav"), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes(long.tobytes())
print("long ok", len(long) / 16000, "s")
