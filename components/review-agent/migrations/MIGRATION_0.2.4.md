# AI 审片 Agent 0.2.4 迁移说明

- `repair-task` 接受单报告或 `{items:[reports]}`。
- 单 item wrapper 返回原有 `qingshan.agentcut.repair_task.v2`，兼容旧消费方。
- 多 item 返回 `qingshan.agentcut.repair_task_batch.v1`，任务位于 `tasks`。
- 无效输入返回 JSON `SchemaError`，CLI 退出码为 2，不再抛 traceback。
- `video.too_many_long_shots.details.long_shots` 新增逐镜头区间及 motivated/static_hold 信息。
- 聚合长镜 issue 会展开为逐区间、逐相交视频 clip 的 repair，新增稳定 `repair_id` 与 `shot_details`。
- 发布、删除和不可逆操作权限仍为 false。
