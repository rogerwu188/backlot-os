# AI 审片 Agent 0.2.3 迁移说明

- report schema 仍为 v2；summary 新增 `raw_issue_count`、`deduped_issue_count`。
- 顶层及 scoring 新增 `deduction_cap`。
- 同 rule/media 的重叠或 0.5 秒内相邻时间窗在评分前聚类。
- 生产 regression 与内建分析命中同一聚类时，生产 issue 作为代表并保留其稳定 ID。
- `details.deduplication.child_evidence` 保留全部原始问题、时间窗、证据和峰值详情。
- `audio.rms_jump` 非阻塞 warning 累计最多扣 1.0 分；其他 warning 类默认最多扣 1.4 分。
- blocking 问题不应用 deduction cap，硬门逻辑不变。
