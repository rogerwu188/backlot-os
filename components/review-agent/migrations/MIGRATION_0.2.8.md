# AI 审片 Agent 0.2.8 迁移说明

- `coverage_manifest` 在 `required_capabilities` 中规范化为 `coverage`，报告不再生成重复的 `coverage_manifest=NOT_RUN`。
- AgentCut 项目的音频对白与字幕时间窗可作为长镜和开场对白的 speech motivation 证据；不要求等待 ASR。原始能量检测仍保留为可回滚证据。
- 生产 regression 的长镜和静态停留区间按 AgentCut 视频 clip 明确切点重新分段。跨切点的检测保留为 `video.static_hold_reconciled` 非行动型证据，单 clip 内真正冻结仍按原硬门阻塞。
- `expectedDialogueIds`、对白音频和字幕 dialogue IDs 完整匹配时，AgentCut adapter 输出 `coverage=PASS`，并保留缺失 ID 明细。
- 规则版本升级为 `qingshan.review.rules.v8`，因此同一媒体会获得新的 review ID；issue ID 的稳定算法未改变。
