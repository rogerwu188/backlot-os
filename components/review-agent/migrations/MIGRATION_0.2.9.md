# AI 审片 Agent 0.2.9 迁移说明

- `video.under1_ratio` 采用 detector/project 双证据裁定，报告同时保存两套 segment、under-1s 数量和比例。
- AgentCut 项目必须通过媒体 provenance：精确 `output.path`，或相同 episode/trial 版本身份且时间线与媒体时长差不超过 0.25 秒的 mux/subtitle 派生链。跨版本标为 `STALE_EVIDENCE/ERROR`，不得用于放行。
- 物化视频时间线必须无 overlap；短 clip 至少一侧素材源发生变化才计为有效短镜。
- 有效项目短镜比例位于生产阈值 5%–15% 时，像素场景检测漏切降为 `video.under1_ratio_reconciled` info，零扣分、非阻塞。
- overlap 或项目比例越界时仍保留 blocking 硬门。
- 规则版本升级为 `qingshan.review.rules.v9`。
