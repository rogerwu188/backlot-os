# AI 审片 Agent 0.3.0 迁移说明

- 新增 `ambience_analysis`，AgentCut 环境音轨自动进入素材与成片双层检查。
- 新增规则：`audio.ambience_gain_excessive`、`audio.periodic_ambience_loop`、`audio.high_frequency_hiss`、`audio.dialogue_to_ambience_ratio`、`audio.noise_floor_jump`。
- 默认阻止 volume > 1.5 的环境轨，以及短同源素材重复至少 8 次且交叉淡化不足 300ms 的机械循环。
- `evidence_inputs.audio_baseline` 可对照上一通过版本；6kHz 以上噪声增加 3dB 警告、6dB 阻塞。
- 独立环境素材使用 `metadata.audio_role=AMBIENCE`；AgentCut 项目通过 `speech_free`、kind 或 track ID 自动识别。
- 阈值记录在 `config_summary.ambience`，规则升级为 `qingshan.review.rules.v12`。
- 工具保持只读，不自动修改或发布 E18 或其他剧集成片。
