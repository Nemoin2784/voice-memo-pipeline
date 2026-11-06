# models/

识别模型放这里，**不进 git**（约 500 MB），第一次使用跑：

```bash
python scripts/get_models.py            # Paraformer 主模型 + 标点模型
python scripts/get_models.py --vosk     # 额外：Vosk 小模型（备用通道，42 MB）
```

下载完成后目录结构：

```
models/
├─ sherpa-onnx-paraformer-zh-2024-03-09/
│  ├─ model.int8.onnx     217 MB  主识别模型（Paraformer-zh，int8 量化）
│  ├─ tokens.txt                  词表
│  └─ am.mvn                      特征归一化参数
├─ sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12/
│  └─ model.onnx          280 MB  标点模型（可选，--no-punct 可跳过）
└─ vosk-model-small-cn-0.22/      可选，Vosk 备用通道
```

模型来源：

- Paraformer / 标点：[`csukuangfj/sherpa-onnx-paraformer-zh-2024-03-09`](https://huggingface.co/csukuangfj/sherpa-onnx-paraformer-zh-2024-03-09)、[`csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12`](https://huggingface.co/csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12)
- Vosk：[`guloooovoooo/vosk-model-small-cn`](https://huggingface.co/guloooovoooo/vosk-model-small-cn)（上游为 alphacephei.com/vosk/models）

许可：Paraformer-zh 为 FunASR 项目模型（Apache-2.0 / MIT 视具体权重而定，商用前请自行确认），Vosk 小模型为 Apache-2.0。本仓库只提供下载脚本，不打包模型本体。
