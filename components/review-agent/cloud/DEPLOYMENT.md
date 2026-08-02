# 云端部署与验收

## 构建

```bash
docker build -f cloud/Dockerfile -t qingshan-review-agent:0.9.2 .
```

## 健康检查

```bash
docker run --rm qingshan-review-agent:0.9.2 health
```

预期：`status=ready`、`version=0.9.2`、`workers=4`，且 ffmpeg/ffprobe 非空。

## NDJSON 常驻 Agent

```bash
docker run --rm -i \
  -v /media:/data:ro -v /evidence:/evidence:ro -v /state:/state \
  qingshan-review-agent:0.9.2 serve
```

输入每行一个 JSON。示例见 `contracts/ndjson-examples.ndjson`。

## 外部能力

- OCR 已随容器安装 RapidOCR/ONNX Runtime。
- 语义图片审查必须配置 `QINGSHAN_IMAGE_ANALYSIS_COMMAND`；未配置会正确返回 CAPABILITY_FAIL。
- 生产回归、cadence 等复用工具应只读挂载至 `/srv/qingshan/tools`。
- 媒体和证据卷只读；`/state` 是唯一持久可写卷，用于 append-only ledger/registry。

## 云端等价验收

运行 `python cloud/smoke_test.py`，然后执行完整测试：

```bash
python -m unittest discover -s tests -q
```

通过后还需以一份真实、不可变、exact-SHA 媒体请求验证外部视觉模型和生产工具挂载。缺少外部运行器时不能宣称该能力已迁移。
