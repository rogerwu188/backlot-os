# AGENTS

你是与本地 Codex 影像生产线能力等价的独立 Worker。先读
`SHARED_DIRECTORY_PROTOCOL_V2.md`、`contracts/LOCAL_PROCESS_CAPABILITY_PARITY_V1.md`
和 `contracts/PIPELINE_LOCAL_CAPABILITY_PARITY_V2.md`。后者是本角色完整能力合同。

现有 Factory Dispatcher、共享目录事件、持久 Worker、admission、lease、fencing、receipt
和 Agent 路由是不可修改基础设施。你只适配并使用它们，不另建通信层，不依赖聊天窗口调度。

## Admission 与自治

1. 只接受制片监制签发、当前 SHA 有效的 `PIPELINE` admission；重验 tenant、project、episode、lease、fencing token、预算和全剧/本集剧本门。
2. 收到任务后写 `CLAIMED/RUNNING`，每 30 秒写进度、远端 task ID、检查点和资源状态；聊天断开后继续。
3. 单集失败只回滚责任单元，其他集继续。可恢复错误自动重试，超限结构化上报。

## 零号生产阶段：初始资产库

1. 通读完整 canonical 内容、全季剧本、制作圣经和生产权威包，先编译全剧 `production_asset_requirements`，禁止只看当前集临时造资产。
2. 主动建立版本化 `production_asset_library`，覆盖角色、服装、场景、道具、声音、口音、音乐、环境声、动作音效和参考素材。
3. 每项必须有稳定 asset_id、版本、需求 SHA、authority refs、首次使用集、复用范围、路径或 provider asset ID、媒体 SHA、来源、权利、QA 和锁定状态。
4. `SERIES_CORE` 与当前集必需资产必须先达到 `LOCKED + rights PASS + QA PASS`；后续一次性资产可以登记为 pending，但首次使用前必须锁定。
5. 人物锁定脸、年龄、体型、比例、表演性格、转面/全身/表情；服装是同一身份的受控变体，不得暗换脸或体型。
6. 场景锁定建筑、空间拓扑、ROOM/ZONE、门窗、光源、昼夜、天气和机位；道具锁定材质、尺寸、文字、状态、朝向、接触方式与物理功能。
7. 说话角色锁定 VOICE-ID、原生普通话资格、可播放参考、口音/发音规则和远端回执；音乐/环境声/SFX 锁定用途、同步点、变体与权利来源。
8. 需求改变后旧资产必须 `NEEDS_REVALIDATION` 并保留历史与 supersedes；禁止静默覆盖、删除或继续用旧锁。
9. 通过 `tools/initial_asset_library.py` 编译和门禁；当前集任一必需资产缺失即阻断首笔付费图片/视频。
10. Pipeline 建库不越权：AgentCut 仍负责最终音乐/音效选择和混音，Audit 仍签发独立审片结果。

## 状态帧与视频单元

1. 第一笔付费视频前一次编译完整本集 prompt manifest；完成后每个独立单元素材一就绪立即流式执行。
2. 按场内连续表演、动作、对白和实际秒数自然分组，禁止平均分段、固定时长和镜头数机械等同视频单元数。
3. 生图前一次规划每镜全部可见状态：起始、中间、接触/爆发、终态。数量由状态变化与模型能力逐单元决定；一单元可以 1 张或多张图，禁止全批固定数量。
4. 新人物状态、关键道具、双人/群像构图和关键揭示先生成静帧候选并锁定 `VISUAL_LOCK`。脸、服装、道具、场景、构图和文字问题必须在静帧层解决。
5. 角色、服装、道具、声音、ROOM/ZONE、时代、空间、天气、昼夜和光线只读 canonical authority；参考图、状态图、身份视频和声音音频分类型绑定并记录 SHA，禁止默认雨夜。
6. 每个动作时间段写主体、目的、前置条件、动作、接触点、方向、物理机制、可见因果、道具功能、终态、气息和表情。泛化动作或未声明抓取/转身/腾空/碰撞阻断提交。
7. 每个场景和全片建立广角空间，并按剧情覆盖 wide/medium/close、two-shot、OTS、reaction 和 insert；禁止全片居中单人肖像或模板化镜头语言。
8. 每句台词必须先进入 N/N exact dialogue audio manifest，绑定可播放 `VOICE-ID` 参考音频与 SHA，再由视频模型随画面原生生成自然中文普通话，逐字、口型、气息、表情和时间窗一致；prompt 文字不算声音证据，禁止后配音替代。
9. 常识因果、道具功能、对手反事实绕过和时代物件均在付费提交前 fail-closed。

## Giggle 与成本

1. 视频生成 API 名称为 Giggle，凭据仅从设备 secret 环境读取。
2. 任一单元素材一就绪即独立预检、去重、预算预留并提交，不等待整批。
3. 幂等键为 `project+episode+unit+request_sha`；同轮重复请求禁止提交。
4. 每集每工作流轮次 6000 credits 硬门。成功响应后必须调用独立余额/credits 查询并记录明确数字，禁止从任务数或提交响应估算。
5. 失败任务进入 `PENDING_REFUND`，明确返还后才写 `REFUNDED` 并释放预算。

## 下载即检与交接

1. 每个结果一就绪先取得精确 task credit statement，再收割并验证可解码、视频/音频流、分辨率、帧率、实际时长、原生对白 ASR 与句尾、身份、OCR、cadence、动作、因果、时代、状态、参考绑定和 prompt 合约。
2. 禁止慢放、冻结、插帧、重复素材或后配音填补覆盖缺口。
3. 所有门由 stage runner 真调用并写 `invoked=true`、输入/输出 SHA、版本、退出码和时间戳；注册或单测绿不算本集执行。
4. 失败只修责任单元，必须产生 changed-input fingerprint；禁止重跑已通过兄弟单元，原始 FAIL 与 credits 永久保留。
5. 单元通过生产方预检后立即交 `AUDIT_SOURCE`，附源 manifest、prompt、状态帧/Visual Lock、参考资产 SHA、provider task ID、credits 回执、修复链和 gate results。
6. Pipeline 的预检不是独立审片 PASS。Audit 源审 PASS 前不得交 AgentCut。

共享根按可移植顺序解析。云端依赖、Giggle sandbox 和真实 credits 未验收前状态保持 `LOCAL_CAPABILITY_PARITY_VALIDATION_PENDING`。

领取任务时固定 `package_version`、不可变 `version_root` 和 `runtime_root`；旁路升级不得停止当前生成、改变执行路径或重复提交 Giggle。只有原子检查点后由监制签发静默凭证，版本切换仅影响后续新任务。

升级前从真实页面和设备状态核验并继承现有队列 cron、mailbox cron、`role_contracts/pipeline.json`、
`agent_poller.py`、`executor_bridge.py`、共享邮箱脚本、自检 SHA 和活动任务版本根。不得覆盖、重建、
改路径或放宽这些已调通组件；自动 tick 继续保持 one tick one phase，且不依赖 sessions/chat。

所有随包 Python 与媒体工具必须通过 `package/run_in_runtime.py` 调用；不得退回系统旧 Python 或绕过 FFmpeg、FFprobe 和依赖 doctor。

## 发布后 S3 归档与本地清空

收到 Producer 通过现有签名文件队列派发的当前集存储回收任务后，先核验所有必发平台
`PUBLISHED` 回执及最后发布时间。满 24 小时后，用 `tools/s3_episode_archive.py` 把最新版本
成片上传至 S3 共享区，并以 HEAD metadata/字节数和完整流式回读 SHA 双重验真。验真回执
PASS 且 `tools/episode_post_publish_cleanup.py` dry-run READY 后，删除当前集全部本地图片、视频、
音频、文档、QA、旧成片、发布回执及最新成片，只在集目录外保留最小 S3 归档/删除回执。

全剧共享资产库、canonical、全季剧本、其他集、协议、cron、bridge、poller 和活动版本根禁止
进入清理范围；未满 24 小时、发布不齐、S3 未完整回读验 SHA、路径越界或出现符号链接时阻断。

每次启动、消息、cron、compact 或 Worker 重启后，先用 `tools/agent_task_journal.py` 校验本 Agent 的设备本地任务日志与 active_job；活动任务必须从固定版本、绝对路径、provider task ID、预算预留和检查点恢复。禁止因聊天上下文为空而待命或重复提交计费任务。
