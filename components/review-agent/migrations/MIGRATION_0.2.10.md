# AI 审片 Agent 0.2.10 迁移说明

- 显式 `action_audit`、`scene_brightness`、ASR 和句审证据通过 provenance 后优先于旧 regression 聚合 section。
- Scene brightness 无顶层 status 时，只有 `timeline_order_verified=true` 且存在 shot 测量行才派生 `PASS_DERIVED`。
- `audio_analysis` 根据最终音频 issues 重算为 PASS/WARN/FAIL，并保留 regression `raw_status` 与 `raw_evidence`。数字零、dropout、click 和其他真实音频硬门仍为 FAIL。
- `regression_ci` 根据已裁定 production issues 与 REQUIRED capability 矩阵重算。未解决 blocker 为 FAIL；存在可行动 finding 或 REQUIRED 缺口为 WARN；全部旧失败均有结构化纠正证据时为 PASS。
- 规则版本升级为 `qingshan.review.rules.v10`，同一媒体会生成新的 review ID。
