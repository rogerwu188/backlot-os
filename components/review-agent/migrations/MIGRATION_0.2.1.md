# AI 审片 Agent 0.2.1 迁移说明

## 行为变化

- capability 新增 `requirement`：`REQUIRED`、`OPTIONAL`、`NOT_APPLICABLE`。
- capability 状态新增 `NOT_APPLICABLE`。
- 只有 REQUIRED 的 `NOT_RUN` 或 `ERROR` 生成缺口 issue 并参与评分。
- OPTIONAL 的 `NOT_RUN` 只记录，不扣分；NOT_APPLICABLE 不生成 issue、不扣分。
- 请求新增 `required_capabilities`，用于把默认 OPTIONAL 能力提升为 REQUIRED。

## 默认矩阵

- image：OCR REQUIRED；清晰度、图片亮度、构图、视觉连续性 OPTIONAL；音频、ASR、句审、声纹、动作、视频亮度、coverage、AgentCut 均 NOT_APPLICABLE。
- audio：音频分析 REQUIRED；ASR、句审、声纹 OPTIONAL；视觉能力均 NOT_APPLICABLE。
- video final：视频、音频、生产 regression REQUIRED。生产回归明确报告缺失的 action、ASR、句审、场景亮度自动变为 REQUIRED。coverage 和 AgentCut project 默认 OPTIONAL，只有显式要求或生产配置要求时才提升。

## 实测结果

- 指定图片：WARN，4.65/5，仅 `capability.ocr.not_run` 1 项。
- DIA-A1.wav：WARN，3.88/5，仅 4 个实际 `audio.rms_jump`；视觉类能力不再扣分。
- E18R final：FAIL，1.0/5，24 issues、12 blocking；ASL、长镜头、短镜头比例、2 段静音、8 个 RMS jump、开场能量、6 个静态停留和 4 个生产 REQUIRED 缺口均保留。

报告 schema 仍为 `qingshan.review.report.v2`，但消费方应允许 capability status=`NOT_APPLICABLE` 并读取 `requirement`。
