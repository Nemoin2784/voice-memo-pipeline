# -*- coding: utf-8 -*-
"""接口层配置。改端口/线程/令牌都在这里；环境变量可覆盖同名设置。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")

PYTHON = sys.executable
MODEL_DIR = os.environ.get("VOICE_MODEL_DIR",
                           os.path.join(ROOT, "models", "sherpa-onnx-paraformer-zh-2024-03-09"))
PUNCT_DIR = os.environ.get("VOICE_PUNCT_DIR",
                           os.path.join(ROOT, "models", "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12"))
CORRECTIONS = os.environ.get("VOICE_CORRECTIONS", os.path.join(ROOT, "corrections.txt"))

HOST = os.environ.get("VOICE_HOST", "0.0.0.0")
PORT = int(os.environ.get("VOICE_PORT", "8765"))

# 识别参数：i3-3220 上 2 线程最合适
THREADS = int(os.environ.get("VOICE_THREADS", "2"))
MAX_SEC = float(os.environ.get("VOICE_MAX_SEC", "25"))

# 等待时间估算：每秒音频耗时 + 每个任务的固定开销（标点、读写库）
RTF_DEFAULT = float(os.environ.get("VOICE_RTF", "0.20"))
OVERHEAD_SEC = float(os.environ.get("VOICE_OVERHEAD", "1.5"))
MODEL_LOAD_EST = float(os.environ.get("VOICE_MODEL_LOAD_EST", "15"))

# 单文件上限（MB）与允许的扩展名。1 小时以上的语音备忘录常有 200~400MB，故放到 1GB
MAX_UPLOAD_MB = int(os.environ.get("VOICE_MAX_UPLOAD_MB", "1024"))
AUDIO_EXT = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".wma", ".amr", ".mp4"}

# 访问令牌：留空表示不校验（只在内网用）。设置后用 ?token= 或 X-Token 头带上
TOKEN = os.environ.get("VOICE_TOKEN", "")

# 转写方式：resident = 常驻进程（模型只加载一次，快）；per_task = 每个任务起一个子进程（隔离好，慢约 12 秒）
WORKER_MODE = os.environ.get("VOICE_WORKER_MODE", "resident")

DATA = os.path.join(HERE, "data")
UPLOADS = os.path.join(DATA, "uploads")
LOGS = os.path.join(DATA, "logs")

for d in (DATA, UPLOADS, LOGS):
    os.makedirs(d, exist_ok=True)
