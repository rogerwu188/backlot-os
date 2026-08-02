# AI 审片 Agent 0.2.0 迁移说明

## 兼容性

- CLI 命令和 NDJSON 方法保持兼容。
- 报告 schema 从 `qingshan.review.report.v1` 升为 `v2`，新增 `capabilities` 与 `config_summary`。
- `status` 新增真实 `active_jobs`、`jobs`、`completed_jobs`；`reviewMany` progress 现在同步写入 job 状态。
- `repairTask` schema 升为 `qingshan.agentcut.repair_task.v2`，新增 `include_warnings`、`delete_allowed:false`、逐问题 `clip_id` 和 `time_range`。NOT_FINAL 默认包含 warning。
- `review_id` 现在绑定媒体哈希、规则版本、评分/音频配置和 evidence 文件哈希；规则或证据变化会得到新 ID。

## 请求迁移

成片建议提供：

```json
{
  "path": "/absolute/final.mp4",
  "kind": "video",
  "scope": "final",
  "metadata": {"status": "NOT_FINAL"},
  "evidence_inputs": {
    "regression_ci_json": "/absolute/regression.json",
    "asr": "/absolute/asr.json",
    "sentence_audit": "/absolute/sentence.json",
    "ocr": "/absolute/ocr.json",
    "coverage_manifest": "/absolute/coverage.json",
    "scene_brightness": "/absolute/brightness.json",
    "action_audit": "/absolute/action.json",
    "agentcut_project": "/absolute/agentcut-project.json"
  }
}
```

未提供的能力明确为 `NOT_RUN`，工具失败/超时为 `ERROR`，不再视为 PASS。图片没有 OCR 或裁定证据时至少 WARN。

## 阈值变化

- digital zero：`<= -90 dB`
- 长静音：`>= 1.0s`（检测底噪默认 `-70 dB`）
- 相邻 RMS jump：`> 12 dB`
- 规则版本：`qingshan.audio.v2-production-aligned`

阈值可通过 `audio_thresholds` 覆盖，但覆盖值写入报告并影响 review ID。若已有生产 regression JSON，其按镜头边界计算的音频连续性结果优先，避免重复窗口告警。

## E18R 实测

- SHA256：`bb735601bebdcbcbc2f95c88bdf236d9c84ffac0ef78684c0cfe2d399552f365`
- 状态：FAIL，1.0/5，26 issues，12 blocking
- ASL 红线 1、长镜头过多 1、短镜头比例异常 1
- 长静音 2、相邻 RMS jump 8、开场对白能量失败 1
- 无动机静态停留 6
- action、sentence ASR、speech ASR、scene brightness、coverage、AgentCut project 均明确 NOT_RUN
- NOT_FINAL 修复任务含 26 项；发布、删除、不可逆操作均禁止
