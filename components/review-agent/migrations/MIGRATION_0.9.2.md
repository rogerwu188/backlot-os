# 0.9.2 云端迁移说明

- 新增 `QINGSHAN_PRODUCTION_ROOT` / `--production-root`，云端不再依赖固定的本机目录。
- ledger、规则注册表、worker 数量可通过环境变量配置。
- FFmpeg/FFprobe 支持 PATH、常见系统目录与 AgentCut vendor fallback。
- request schema 与运行时校验统一支持 `full_cut`、`action_physics` 和动作镜参数。
- 云端包包含 Docker 部署文件、NDJSON 示例、外部视觉/动作物理契约、生产检测脚本和 smoke test。
- 安全边界不变：只读媒体，不发布、不删除、不自动处理登录/验证码/版权授权或不可逆平台操作。

兼容性：既有请求无需修改。原来依赖 `/Users/rogerwu/qingshan_short_drama` 的部署应显式设置 `QINGSHAN_PRODUCTION_ROOT`；未设置时仍保留旧默认值以兼容本机生产线。
