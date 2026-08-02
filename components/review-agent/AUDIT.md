# 现有能力审计（2026-07-17）

- 已复用：`tools/frame_cadence_audit.py` 的冻结（0.5 秒硬门）和周期重复帧结果；运行时自动寻找 AgentCut 自带 ffmpeg/ffprobe。
- 可适配：`final_video_ocr_audit.py`、`still_image_ocr_audit.py`、`continuity_auditor.py`、`transition_smoothness_gate.py`、`audio_source_binding_gate.py`、`final_audio_provenance_gate.py`。这些脚本 CLI/输出并不统一，MVP 不臆测参数，支持把外部结果通过 request 注入统一 issue。
- 证据形态：既有 JSON 常见字段为 `status/failures/results`，节奏报告包含精确帧号/秒数，E18R 多模态报告包含 expected/transcript/segments/ASR recall。
- AgentCut：NDJSON 多并发协议；项目 clip 可带 `id` 与 `metadata`。本工具原样映射到报告和修复任务。
- 错误账本：`workflow/agent_mistake_ledger.json` 是既有 JSON，工具只读兼容，不写入；新事件使用独立 NDJSON append-only ledger，避免覆盖旧记录。
- 人审兜底：现有政策为 900 秒；版权、验证码、登录、权限、支付、不可逆发布/替换/删除仍需人工。

## 阶段风险

MVP 已覆盖媒体存在性、探测、缺音、数字零、长静音、爆音、RMS 跳变，以及复用冻结/周期重复帧。语义 OCR、ASR、声纹、角色/服化道/场景连续性依赖生产线模型和参考清单；当前 schema 能承载结果，但不能把“未运行”误报成通过。静态图清晰度/构图、视频亮度跳变/ASL/覆盖缺口/动作实时性将在适配器扩展后成为自动硬门。
