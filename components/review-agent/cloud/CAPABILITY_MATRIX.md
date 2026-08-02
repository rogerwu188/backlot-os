# 云端能力矩阵

本包迁移的是审片 Agent 的源码、规则、协议、评分、证据契约、测试和生产检测脚本。云端部署必须按下表提供运行依赖；缺失的 REQUIRED 能力应返回 `CAPABILITY_FAIL`，不得伪装成内容通过。

| 能力 | 包内实现 | 云端依赖 |
|---|---|---|
| CLI、NDJSON、并发、进度、评分、去重、ledger、修复任务 | 是 | Python 3.11+、可写 state 目录 |
| 视频/音频探测、黑帧、冻结、重复帧、运动、响度、静音 | 是 | FFmpeg/FFprobe |
| 成片 regression CI、cadence、OCR 审计脚本 | 是，位于 `cloud/runtime_tools` | FFmpeg；OCR 另需 RapidOCR |
| 图片 OCR | 是 | RapidOCR、ONNX Runtime、OpenCV |
| 图片语义审查、动作物理、角色/场景连续性 | 契约与验证在包内 | 通过 `QINGSHAN_IMAGE_ANALYSIS_COMMAND` 接入有视觉能力的云端模型；必须返回 exact SHA |
| ASR、句审、声纹 | 证据适配与 provenance 验证在包内 | 云端 ASR/声纹服务或显式证据 JSON |
| AgentCut 映射 | 是 | 显式 AgentCut project JSON |

“100% 等价”验收同时要求：代码版本一致、规则版本一致、依赖存在、外部模型配置一致、测试通过、同一不可变媒体的关键结论一致。仅上传源码不能证明外部模型行为一致。
