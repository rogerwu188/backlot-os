# AI 审片 Agent 0.2.7 迁移说明

- `required_capabilities.audio` 规范化为 canonical `audio_analysis`。
- 报告不再同时出现 `audio_analysis=PASS` 与 `audio=NOT_RUN`。
- 新增别名：video、sentence、speaker、brightness。
- `config_summary` 记录 requested、normalized 和 alias 映射。
- 纯音频的 ASR、句审、声纹可显式设为 REQUIRED。
- 匹配 provenance 且具有明确状态的 evidence 会形成 PASS/FAIL capability；缺少 REQUIRED evidence 保持 NOT_RUN 缺口。
