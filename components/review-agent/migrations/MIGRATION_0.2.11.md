# AI 审片 Agent 0.2.11 迁移说明

- 修复 PCM16 WAV 多声道快路径：按 frame 下混为 mono，不再把 stereo 交错样本解释成双倍时间轴。
- 所有 issue 时间窗在评分前 clamp 到 `[0, media duration]`。适配器若生成越界结果，报告标为 `validity=INVALID`，对应能力为 `ERROR/INVALID_ISSUE_TIME_RANGE`；该问题保留原始/修正时间但不进入评分。
- `summary.invalid_time_range_count` 与顶层 `invalid_time_ranges` 提供机器可读诊断。
- 新增显式审计 `gate_policy`，允许按 episode 或 AgentCut project 覆盖 runtime/under-1s 门槛。必须提供版本、理由和匹配 scope，默认生产阈值不变。
- Gate policy 的原始阈值、生效阈值、版本与理由写入报告和 review ID。
- 规则版本升级为 `qingshan.review.rules.v11`。
