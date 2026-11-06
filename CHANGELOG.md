# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)；0.x 阶段接口可能变动。

## v0.0.0 — 2026-11-06

第一个可用版本：**iPhone 语音备忘录 → 家里电脑转写 → 回填到备忘录**，全程离线、免费。

### 新增

- **本地转写服务**（`server/`）：FastAPI + SQLite 任务队列，单 worker 串行处理，电脑关机/重启后任务不丢。
- **识别引擎**：sherpa-onnx + Paraformer-zh（int8，217 MB），CPU 自带上标点模型，中文录音 RTF ≈ 0.2（5 倍实时左右）。
- **上传接口**：`POST /api/upload`（表单）与 `POST /api/upload/raw`（请求体即文件），支持中文文件名；单文件上限 1 GB。
- **取件协议**：`GET /api/next/text` 一条 URL 取走“下一条转完的”文本；没有就绪内容时返回 `204`（正文为空），快捷指令用「内容 没有值」判断即可。
- **历史清单**：`GET /api/recent` 列出全部历史转写，`GET /api/recent/text?pick=编号` 按编号重建任意一条备忘录。
- **去重与存档**：同一段音频按 SHA-256 去重（`force=1` 可强制重转）；每篇转写落一份 txt 到 `server/data/records/` + `index.jsonl`，数据库每天自动快照 14 份。
- **同音字纠错表**：`corrections.txt`（`错词 => 正确词`），服务端转写完自动套用。
- **局域网 / 远程两套地址**：家里用 `http://<局域网IP>:8765`，外面用 xEdge（Tailscale 内核）私有组网 `http://100.64.0.1:8765`，手机流量也能用。
- **iOS 快捷指令**：上传（分享表单）与取回（自动写备忘录 + 历史清单）两条快捷指令，iOS 17 / 18 适用，见 `docs/ios-shortcuts.md`。
- **辅助脚本**：`scripts/get_models.py` 下载模型、`scripts/transcribe_para.py` 命令行转写、`scripts/fetch_wheels.py` 离线装依赖。

### 已知限制

- 只认真人中文语音：模型是中文 Paraformer，英文/方言效果一般。
- 单 worker 串行：多人同时传会排队，任务按完成顺序取件。
- 服务默认 `0.0.0.0` 且默认无令牌：只建议在家庭内网或私有组网里用；要暴露到公网请设置 `VOICE_TOKEN`。
- 默认路径面向 Windows；Linux/macOS 可跑但未做安装脚本和实测。
- 大模型总结（接 LLM 出摘要）还没做，留到 v0.1。
