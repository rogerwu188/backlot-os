# AI 审片 Agent 0.2.6 迁移说明

- repair-task v2 每个 repair 新增并保证 `rule_id`。
- 非行动型 info (`actionable:false`) 不再扣分。
- `video.motivated_long_shots` 继续留证，但分值扣除为 0。
- production visual-shot RMS jump 新增切点局部音频连续性裁定。
- 连续 bed/对白动态输出 info，不生成 repair；数字零、dropout、click 仍输出 warning。
- 原始 regression jump、局部窗口 RMS、切点和聚类 child evidence 全部保留。
- 算法为纯本地确定性计算，不改变 worker 并发协议，不发布或删除媒体。
