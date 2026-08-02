# AI 审片 Agent 0.2.2 迁移说明

- 保持 0.2.1 CLI、NDJSON 方法和 report v2 兼容。
- ASR、sentence audit、OCR、regression CI JSON 在使用前新增 provenance 校验。
- 支持的媒体 provenance 字段包括 `video`、`video_path`、`media_path`、`source_video`、`source_final_mp4`、`final_video`、`input_video`、`input_path`。
- 支持的 project provenance 字段包括 `project`、`project_path`、`agentcut_project`、`agentcut_project_path`。
- 不匹配时 capability=`ERROR`、`error_code=STALE_EVIDENCE`；旧证据从适配器输入中移除，并生成 blocking 的 `evidence.provenance_mismatch.*` issue。
- 报告新增 `evidence_provenance`，保留 evidence path、字段、actual、expected。
- AgentCut 映射新增完整 clip 表；修复任务按时间码回填 `clip_id`、`metadata.dialogue_id` 和 `metadata.beat_id`。
