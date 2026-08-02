# AGENTS

你是与本地 AgentCut 后期流程能力等价的独立 Worker。先读 `SHARED_DIRECTORY_PROTOCOL_V2.md`、`contracts/LOCAL_PROCESS_CAPABILITY_PARITY_V1.md` 和质量基线。

1. 只接受 Audit 源审 PASS 且当前 SHA 有效的 `AGENTCUT` admission；重验 lease、fencing token 和全部输入。
2. 使用已验证 `agentcut==0.9.16` 真实 CLI。每次启动记录 AgentCut、Python、FFmpeg、FFprobe、ASR 模型来源和 doctor 结果；禁止固定用户名、OS 或绝对路径。
3. 按对白、动作、信息和情绪自然边界剪辑。默认不切，每刀需要说话者变化、新信息、新空间或动作节点证据。
4. 原生视频对白是权威主音轨；保留完整字尾、呼吸、表情和起止。禁止后配音替代、变速、插帧或冻结补时。
5. 用原生对白 ASR 对齐逐句字幕，只在后期烧录；字幕覆盖必须与剧本逐句一一对应。
6. BGM 必须新鲜、无可识别人声、具 task/source/SHA，能自然覆盖时间线而不循环或拉伸；对白窗口自动 duck。
7. 加入 NALU Motion 片尾，生成 AgentCut project JSON、源到时间线映射、字幕轨、BGM 轨、音频报告和编码母版。
8. 编码后在最终文件上复测音轨存在、数字零静音、逐句 ASR、响度、真峰值、字幕和片尾。
9. 最终导出产生新 SHA并撤销任何旧终审，原子交 `AUDIT_FINAL`；Audit PASS 前不得称发行版。
10. 长任务每 30 秒写 PID、处理帧数、临时文件大小和检查点；断线后恢复，禁止覆盖原始 FAIL。

云端真实 AgentCut CLI、模型和成片回归未验收前状态保持 `LOCAL_CAPABILITY_PARITY_VALIDATION_PENDING`。

领取任务时固定 `package_version`、不可变 `version_root` 和 `runtime_root`；旁路升级不得停止编码、改用新二进制或使临时工程失效。只有当前剪辑已写原子检查点且监制签发静默凭证后才可切换，切换仅影响后续新任务。

所有随包 Python、AgentCut、FFmpeg、FFprobe、Whisper 与 Demucs 调用必须经 `package/run_in_runtime.py`；不得退回系统旧 Python 或未记录的解释器。

每次启动、消息、cron、compact 或 Worker 重启后，先用 `tools/agent_task_journal.py` 校验设备本地任务日志与 active_job，并从固定工程路径、源 SHA、时间线检查点和编码进度恢复。禁止因聊天上下文为空而待命、重建工程或覆盖原始 FAIL。
