# voice-memo-pipeline

> 把 iPhone 语音备忘录变成文字：**快捷指令上传 → 家里电脑离线转写 → 再点一下取回备忘录**。
> 不经过任何云服务，录音和文本只留在你自己的硬盘上。
>
> *Turn iPhone voice memos into text — self-hosted, fully offline ASR on your own PC. No cloud, no subscription, no upload to anyone.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6.svg)](#快速开始windows)
[![Version](https://img.shields.io/badge/version-v0.0.0-brightgreen.svg)](CHANGELOG.md)

---

## 这是什么

iPhone 自带的「语音备忘录」录音很方便，但整理成文字很麻烦：要么手动听写，要么把录音传到某个云端服务。

这个项目做了一件很简单的事：**把转写引擎放在你自己的电脑上，用 iOS 快捷指令当客户端。**

- 录完音 → 点一下快捷指令「上传」→ 电脑后台排队转写；
- 过一会儿 → 点一下快捷指令「取回」→ 文本自动写进一条新备忘录；
- 所有东西都在家里：录音文件、识别模型、转写文本、历史记录。

转写用的是 [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) + **Paraformer-zh**（int8 量化，217 MB），纯 CPU、中文效果好；附带标点模型和可编辑的同音字纠错表。在 2012 年的 i3-3220 上实测 **RTF ≈ 0.2**（5 倍实时），8 GB 内存就够了。

## 架构

```
iPhone                         你的电脑（Windows / 常驻 1 个进程）
┌──────────────┐    HTTP     ┌──────────────────────────────────────────┐
│ 语音备忘录    │ ─────────▶ │ FastAPI (0.0.0.0:8765)                    │
│ 快捷指令 A    │  POST       │   上传 → SQLite 队列 → worker 串行转写    │
│ （分享表单）  │ /api/upload │        ├─ Paraformer-zh（识别）          │
└──────────────┘             │        ├─ 标点模型（可选）                │
        │                    │        └─ corrections.txt（纠错）         │
        │  快捷指令 B         │   结果 → records/*.txt + tasks.db         │
        ▼                    └──────────────────────────────────────────┘
┌──────────────┐    HTTP                 ▲
│ 新建备忘录    │ ◀───────── GET /api/next/text ┘
└──────────────┘      （没有就绪文本时返回 204）
```

在家里走局域网地址；出门在外用 [xEdge](https://xedge.cc)（Tailscale 内核）组网，手机用流量也能访问 `http://100.64.0.1:8765`。

## 功能

- **上传即排队**：支持连续上传多条，`queue_position` / `eta_seconds` 直接告诉你要等多久；单文件上限 1 GB。
- **一条 URL 取件**：`GET /api/next/text` 返回“下一条转完的”文本；没有就绪内容时 **204 + 空正文**（快捷指令判「内容 没有值」即可），不会卡住、不会给半成品。
- **历史清单**：`GET /api/recent` 列出全部历史记录（`1. 文件名 · 时长 · 时间`），`GET /api/recent/text?pick=3` 按编号重建任意一条备忘录。
- **不重复算**：同一段音频按 SHA-256 去重，重复上传直接复用旧结果（`force=1` 强制重转）。
- **取走的文本不会丢**：每篇转写都落一份 txt 到 `server/data/records/`（带元信息头部 + `index.jsonl` 索引），数据库每天自动快照 14 份。
- **串行、可恢复**：单 worker 先转先出；进程崩溃或电脑重启后，正在跑的任务自动放回队列重跑。
- **纠错表**：`corrections.txt` 一行一条 `错词 => 正确词`，转写后自动套用。
- **备忘录标题**：`&title=1` 会在正文前插一行「文件名 · 时长 · 日期」，避免整篇文章变成大号标题。
- **无云**：模型和录音都在本地，没有账号、没有用量限制。

## 快速开始（Windows）

### 0. 准备

- **Python 3.10 或 3.11（64 位）**，装好后 `python --version` 能用（3.12+ 目前不保证 sherpa-onnx 的 wheel 可用）；
- 约 **1.5 GB** 磁盘（模型 500 MB + 依赖），内存 4 GB 起，8 GB 更稳；
- 可选：`ffmpeg.exe`（处理 m4a/aac 时需要）。把 `ffmpeg.exe` 放到 `tools\` 下，或让它出现在 `PATH` 里。

### 1. 拉代码、装依赖

```bat
git clone https://github.com/<your-name>/voice-memo-pipeline.git
cd voice-memo-pipeline
python -m pip install -r requirements.txt
```

> 国内网络慢的话，可以先用 `python scripts/fetch_wheels.py` 把 wheel 下到 `wheels\`，再
> `python -m pip install --no-index --find-links wheels -r requirements.txt`。

### 2. 下载模型（约 500 MB，只需一次）

```bat
python scripts\get_models.py
```

默认从 `hf-mirror.com` 下载；想换源用 `--mirror hf`；不想要标点模型（省 280 MB）加 `--no-punct`。
模型放在 `models\`，**不进 git**。

### 3. 启动服务

```bat
cd server
start_server.bat
```

打开 <http://127.0.0.1:8765/api/health>，看到 `"status": "ok"`、`worker.alive: true` 就说明活了。
第一次启动要加载模型，约 10~15 秒。

> 端口被占用或想换地址：改写 `server/config.py`，或用环境变量 `VOICE_PORT` / `VOICE_HOST`。
> 想让手机连进来：以管理员身份跑一次 `server\allow_firewall.bat` 放行 8765。

### 4. 配置 iPhone 快捷指令

按 **[docs/ios-shortcuts.md](docs/ios-shortcuts.md)** 做两条快捷指令：

1. **上传**：分享表单接收语音备忘录 → `POST /api/upload` → 显示预计等待时间；
2. **取回**：`GET /api/next/text?title=1` → 有内容就新建备忘录 → 显示历史清单 → 可输入编号重建旧记录。

文档里同时给了「在家用局域网地址」和「出门用 xEdge 私网地址」两种写法。

### 5. 命令行直接转写（不经过手机）

```bat
python scripts\transcribe_para.py D:\录音\会议.m4a --outdir D:\录音\文本
python scripts\transcribe_para.py D:\录音\ --threads 2
```

## 接口速查

| 接口 | 说明 |
|---|---|
| `POST /api/upload` | 表单 `file=` 上传，返回 `task_id` / `queue_position` / `eta_seconds`；`force=1` 强制重转 |
| `POST /api/upload/raw` | 请求体即文件，文件名放 `X-Filename` 头（iOS 表单不好使时的备选） |
| `GET /api/next/text?title=1` | **取件**：下一条转完的文本；没有就绪内容 → `204`（`&blank=200` 退化为 200 空正文，`&wait=N` 才轮询） |
| `GET /api/next` | 同上，JSON 版；`peek=1` 只看不取 |
| `GET /api/task/{id}/text?title=1` | 按任务号取文本（取多少次都不出队） |
| `GET /api/recent` · `GET /api/recent/text?pick=N` | 历史清单（默认全部，`?limit=20` 截断） / 按编号取回 |
| `POST /api/task/{id}/requeue` | 把历史记录放回取件队首（不重转） |
| `GET /api/tasks?undelivered=1` · `GET /` | 任务列表 / 网页版（显示待取件条数） |
| `GET /api/health` | worker 状态、队列、可用地址（`addresses.lan` / `addresses.xedge`）、存档份数 |
| `POST /api/backup` | 立即给数据库拍快照 |

完整参数、返回约定、排错见 [docs/ios-shortcuts.md](docs/ios-shortcuts.md)。

## 原理与设计

- **队列**：SQLite（WAL）+ `tasks` 表；`claim_next()` 用 `BEGIN IMMEDIATE` 保证只有一个 worker 能领到任务。
- **worker**：常驻进程，模型只加载一次；主进程每 5 秒检查一次，挂了自动重启，崩溃遗留的任务自动 requeue。
- **去重**：上传时算 SHA-256，命中已完成任务就直接把旧文本带回来，并把它放回取件队首。
- **取件顺序**：按**转写完成时间**先进先出（不是上传时间），每条只被取走一次；但文本随时可以按任务号/编号再取。
- **切段**：长音频按 25 秒上限、6 秒下限，在 0.3 秒窗内找 RMS 最低点切，避免把一句话切两半。
- **标点**：CT-Transformer 标点模型（280 MB），整段一次调用，句子边界更自然；不需要就 `--no-punct`。

## 外网访问（不在家时）

家里宽带是二级 NAT（没有公网 IPv4）、路由器又没下发 IPv6 的话，端口映射走不通。项目里的做法是用 **xEdge 干将互联**（Tailscale 开源内核的国产组网，国区 App Store 免费）：

1. 电脑装 xEdge（`tools\xedge-setup.exe`，或去官网下），装完网卡 `xedTun` 固定 `100.64.0.1`；
2. 手机装 App、同一微信登录、打开组网开关；
3. 手机访问 `http://100.64.0.1:8765` —— 在家在外都写死这个地址也行。

免费额度 3 台终端、中继 1 GB/月（打洞直连不限速）。手机上传前在快捷指令里加一步「编码媒体」（AAC / 单声道）能把录音压到 1/10。

## 目录结构

```
voice-memo-pipeline/
├─ server/                  # FastAPI 服务 + SQLite 队列
│  ├─ app.py                # 路由 / 去重 / 取件 / 看护 worker
│  ├─ worker.py             # 常驻转写进程
│  ├─ db.py  config.py  records.py
│  ├─ start_server.bat      # 启动（0.0.0.0:8765）
│  ├─ allow_firewall.bat    # 放行 8765（管理员，跑一次）
│  ├─ fix_firewall.ps1
│  ├─ data/                 # 运行时数据（gitignore）：db / uploads / records / backup / logs
│  └─ tests/                # 接口自测脚本
├─ scripts/
│  ├─ transcribe_para.py    # 命令行转写（Paraformer + 标点 + 纠错）
│  ├─ transcribe.py         # Vosk 备用通道
│  ├─ get_models.py         # 下载模型
│  ├─ fetch_wheels.py       # 离线装依赖
│  ├─ textfix.py  dl.py  compare.py  make_sample.py  make_variants.py
├─ docs/
│  ├─ ios-shortcuts.md      # iPhone 快捷指令 A/B 完整步骤
│  └─ benchmarks.md         # 实测数据与选型记录
├─ models/                  # 模型（gitignore，README 里有说明）
├─ corrections.txt          # 同音字纠错表
├─ run_para.bat  run.bat    # 拖音频上来就能转
└─ .env.example             # 环境变量示例
```

## 性能

i3-3220（2012 年双核）、8.5 GB 内存上的实测：

| 音频 | 时长 | 转写耗时 | RTF | 内存 |
|---|---|---|---|---|
| 33 秒口播 | 33.4 s | 5.7 s | 0.17 | 542 MB |
| 4 分 46 秒会议 | 286.4 s | 58.7 s | 0.20 | 1.2 GB（带标点） |
| 70 分钟录音 | 4200 s | 873 s | 0.21 | — |

完整表格、Vosk / Paraformer 对比和踩坑记录见 [docs/benchmarks.md](docs/benchmarks.md)。

## 路线图

- [x] v0.0.0 — 上传 / 排队 / 取回 / 历史清单 / 去重 / 本地存档（本版本）
- [ ] v0.1.0 — 大模型总结：转写完成后自动出摘要、待办、关键词（接 OpenAI 兼容 API，可配置）
- [ ] v0.2.0 — 说话人分离 / 长时间录音分段标题目录
- [ ] 可选：Linux / macOS 安装脚本、Docker 镜像、Windows 服务化（开机自启）

## 已知限制

- 模型是中文 Paraformer：英文、方言、专业术语效果一般，可用 `corrections.txt` 兜底。
- 单 worker 串行：多人同时用会排队；如需并发可起多个 worker（按任务分片，尚未实现）。
- 默认 `0.0.0.0` 且默认无令牌：只在家庭内网 / 私有组网里用；要暴露到公网请设 `VOICE_TOKEN`。
- Windows 优先：Linux/macOS 可以跑（路径用正斜杠），但没有安装脚本和实测。

## English

**What it is:** a self-hosted speech-to-text service for iPhone voice memos. You record on iPhone, tap a Shortcut to upload, the PC transcribes offline with Paraformer-zh (sherpa-onnx), then another Shortcut fetches the text into a new Apple Note.

**Quick start**

```bash
git clone https://github.com/<your-name>/voice-memo-pipeline.git
cd voice-memo-pipeline
python -m pip install -r requirements.txt
python scripts/get_models.py            # ~500 MB, once
cd server && start_server.bat           # http://127.0.0.1:8765
```

Then follow [docs/ios-shortcuts.md](docs/ios-shortcuts.md) to build the two Shortcuts (iOS 17/18).

**Key endpoints**

| Endpoint | Purpose |
|---|---|
| `POST /api/upload` | multipart upload (`file`), returns `task_id` / `eta_seconds` |
| `GET /api/next/text?title=1` | next finished transcript; `204` when nothing is ready |
| `GET /api/recent` · `/api/recent/text?pick=N` | history list / re-print record N |
| `GET /api/task/{id}/text` | fetch any transcript by task id |
| `GET /api/health` | worker status, queue, LAN / private-network addresses |

**Performance on a 2012 i3-3220:** RTF ≈ 0.17–0.21 (about 5× realtime), 540 MB RAM for the recognizer, ~1.2 GB with the punctuation model. Details in [docs/benchmarks.md](docs/benchmarks.md).

**License:** MIT. Models are downloaded separately and keep their own licenses (see [models/README.md](models/README.md)).
