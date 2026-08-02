# AI 审片 Agent 0.2.5 迁移说明

- long-shot detector 改为逐条 motivated/unmotivated 分类。
- summary 新增 `raw_long_shot_count`、`motivated_long_shot_count`、`unmotivated_long_shot_count`。
- 只有 `unmotivated_long_shot_count > max_unmotivated_long_shots` 才产生 blocking `video.too_many_long_shots`。
- 有动机长镜改为非阻塞 `video.motivated_long_shots` info，不生成强制 repair。
- `static_hold:true` 与 `has_speech:true` 不再矛盾：前者描述低运动，后者提供对白动机；此时 `static_hold_blocking:false`。
- 无动机超限时的逐区间 AgentCut repair 展开仍保持。
