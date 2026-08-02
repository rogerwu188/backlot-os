# 《青山》AI 审片 Agent

当前版本：Agent `1.1.0`，报告 `qingshan.review.report.v2`，规则 `qingshan.review.rules.v25`。

本地、只读优先的审片工具。支持镜头、素材、成片三级请求；视频、音频、图片；默认 4 worker；单次 CLI 与并发 NDJSON 常驻协议。它不会上传、发布、替换或删除成片。

## 整集时长与视觉节奏（1.1.0）

新成片项目必须设置 `metadata.production_contract_version: 2` 并提供可审计的 `runtime_policy`。默认目标 180 秒，偏差不超过 ±10 秒 PASS，±10～20 秒 WARN，超过 ±20 秒 blocking FAIL。旧项目缺合同时保持 OPTIONAL/NOT_RUN，不追溯误杀。

```json
{
  "path": "/absolute/path/episode.mp4",
  "kind": "video",
  "scope": "final",
  "metadata": {"episode": "E37", "production_contract_version": 2},
  "runtime_policy": {
    "version": "qingshan.episode-runtime.v2.0.0",
    "target_seconds": 180,
    "soft_tolerance_seconds": 10,
    "hard_tolerance_seconds": 20
  },
  "require_visual_pacing": true,
  "evidence_inputs": {"agentcut_project": "/absolute/path/project.json"}
}
```

AgentCut 物化视频 clip 应写入 `visual_signature`、`natural_unit_id` 和素材关系 `relationship`。连续 3 镜相同视觉签名、单个自然单元选入超过 2 段素材，或单元累计超过 20 秒，均为 blocking FAIL。修复候选应使用 `REPLACEMENT_CANDIDATE` 替换旧素材，不得默认追加。

跨工具合同见 `schema/episode-runtime-contract.schema.json` 与 `schema/agentcut-visual-pacing-contract.schema.json`；兼容说明见 `outputs/MIGRATION_1.1.0.md`。

## 5 分制与镜头重要度

每项从 5.0 分起评，问题按严重度和置信度扣分：info 0.10、warning 0.35、error 1.00、critical 2.00。默认重要度通过线如下：

| importance | 典型用途 | 通过线 |
|---|---|---:|
| `utility` | 过场、氛围、可替代 B-roll | 3.0 |
| `standard` | 普通叙事镜头 | 3.5 |
| `important` | 重要对白、人物建立、关键动作 | 4.0 |
| `critical` | 高潮、证据特写、身份/连续性锚点、成片 | 4.5 |

请求可用 `pass_score` 为单个镜头覆盖默认线。数值达标仍不代表硬门通过：冻结、缺音、数字零、版权/安全及其他 blocking issue 永远一票否决，不能靠降低重要度放行。

## 快速开始

```bash
python3 -m qingshan_review.cli health
python3 -m qingshan_review.cli validate examples/e18r_not_final.json
python3 -m qingshan_review.cli review-many examples/e18r_not_final.json
python3 -m qingshan_review.cli --ledger work/issues.ndjson --registry work/rules.ndjson serve
```

NDJSON 请求：`health`、`validate`、`review`、`reviewMany`、`status`、`repairTask`、`promoteRule`、`timeoutDecision`、`humanReport`。`reviewMany` 会发送 progress event，并返回完整有序的 `items`、`passed_items`、`failed_items` 与仅含失败请求的 `retry_items`；成功兄弟项不会被丢弃或重跑。默认 4 workers。每个 issue 都有稳定 ID、严重级别、路径、时间/帧/区域位置、证据、置信度、规则版本、建议、阻塞标记和可回滚裁定。

Seedance/新视频生成审片使用故事驱动时长契约：请求提供 `task.duration_plan.duration_seconds`，计划必须在 4–15 秒；实际媒体时长与计划默认允许 ±0.20 秒编码偏差，可用 `duration_tolerance_seconds` 在 0–1 秒范围内审计式配置。不存在全局“超过 6 秒失败”：4、5、6、8、15 秒只要符合各自计划均可通过。新视频生成请求缺少计划、计划越界或实际偏差超限都会生成稳定阻塞 issue。报告 `story_duration` 和同名 capability 保留 planned/actual/delta、policy version、pass/fail 与 rollback。冻结、周期重复、黑帧、OCR、音频、ASR 门保持独立且不因时长通过而豁免。

成片逐帧黑帧门使用 `qingshan.black_frame.v1` 扫描全部解码帧，默认 `pblack>=99.9`、像素阈值 20；任何未获剧情明确裁定的命中均输出 frame、time、pblack 并阻塞。扫描工具缺失、超时或解码失败同样阻塞，不能无证据 PASS。`allowed_black_frames` 自 1.0.0 起不再具有豁免权；确需剧情黑帧或 strobe 时，必须由 provenance 匹配的 AgentCut shot recipe 提供精确起止帧、非空 reason 和 approved policy。

## 镜头计划与成片一致性

1.0.1 支持 AgentCut 0.9.17 正式 `agentcut.materialized_shot_recipes.v1` camelCase/nested sidecar，同时保留 1.0.0 snake_case fixture。正式输入通过 `agentcut_shot_recipe_sidecar`、`agentcut_project`、`agentcut_render_manifest` 与 `shot_recipe_provenance` 提供；共享 envelope 必须包含 project ID/version 及 candidate/project/timeline/manifest 四个精确 SHA。任一缺失或失配继续以 `STALE_EVIDENCE`/证据错误 fail closed。

逐镜审查计划运镜与阶段、主体锚点、setup/contact/result、结果 hold、beat 切点、SFX 动作峰值及最终帧文字像素高度。问题保留稳定 issue ID、recipe/clip/phase、精确秒/帧/区域、计划值、实测值、delta、证据、修复建议和回滚策略；repairTask 按 recipe phase 为所有相交 AgentCut clips 生成只读结构化修复，不发布媒体。

旧项目未提供镜头计划证据时，新能力为 OPTIONAL/NOT_RUN 且不扣分。使用 `production_profile: shot_recipe_conformance_v1`、`agentcut_director_v1`、`qingshan.production.shot_recipe.v1` 或显式 required capability 时，缺证据为 CAPABILITY_FAIL，不伪造 CONTENT_FAIL 或 PASS。正式与 fixture 两条适配路径均保持严格 provenance 和黑帧授权门。

AgentCut 混合音轨会优先读取 dialogue metadata；旧 clip ID（例如 `E20-DIA-022-AUDIO`）按 `DIA-022` 归一。对白顺序以物化视频/剧本时间线为准，coverage 报告 expected/audio order、映射数量和缺口；句审明确报告 0 句却声称 PASS 时，生成 `audio.dialogue_zero_sentence_false_pass` 阻塞问题。

成片亮度证据默认以相邻镜头 `left.end_luma` 与 `right.start_luma` 的原始差值审查，20 luma 以上视为跳变。跳变只有在逐项提供存在的 `evidence_file`、非空 `reason`、`confidence>=0.9`、`raw_jump_preserved=true` 时才能成为 `PASS_WITH_ADJUDICATION`；缺证据或字段不完整均 FAIL。原始 jump 永远保留在报告中。

## 生产证据接入

成片请求支持 `evidence_inputs`：`regression_ci_json`、`asr`、`sentence_audit`、`ocr`、`coverage_manifest`、`scene_brightness`、`action_audit` 和 `agentcut_project`。没有现成回归 JSON 时，成片默认只读调用生产线 `tools/run_regression_ci.py`。可用 `run_regression_ci:false` 禁用，但能力会标为 `NOT_RUN`。

OCR 审查窗口不再使用固定尾长。可信 AgentCut project 存在时，优先读取 `outro.actualStart`，否则以物化主视频时间线终点作为精确片尾起点；OCR 证据必须覆盖到该点。没有可信片尾 manifest 时必须采样到媒体结尾，已知品牌文字通过 `ocr_brand_allowlist`（默认含 `NALU MOTION`）分类，禁止盲目排除尾部。证据中的 `review_end_seconds`、`sample_end_seconds`、`sampled_through_seconds` 或 `exclusion_start_seconds` 若早于主内容终点，会生成阻塞的 `ocr.main_content_coverage_gap`。主内容 OCR 命中会生成 `video.readable_native_text`；若与同时段 AgentCut 字幕重合，则生成 `video.readable_native_text_duplicate`。

从 0.6.2 起，`qingshan.final_video_ocr_audit.v2` 的归一化 PASS 只有在 lexicon policy 已配置、`critical_text_failures=0`，且 Latin/未列中文/数字失败聚合均为空时才具有权威性。所有 raw recognition 仍保留，但孤立符号和不稳定低置信数字不会直接升级成可读文字。非权威 raw 结果必须显式 forbidden、置信度至少 0.85，或在相邻至少两个采样点持续出现才进入阻塞门；持续真实文字和禁显文字仍阻塞。

显式 v2 raw FAIL 也会逐条按同一策略重算：Latin/数字必须同时达到 0.85 且跨相邻采样持续；配置 lexicon 后明确 `unlisted_chinese=false` 的中文以及标记为 subtitle/intended subtitle 的命中属于允许内容；未列中文仍需达到置信度或持续性门。若所有 raw hit 均被策略拒绝，能力输出 `PASS_POLICY_NORMALIZED_RAW_FAIL`，但原始 FAIL、critical 计数、全部识别和拒绝原因原样保留。

OCR 机器裁定也可使用 `audit_scope.main_content_end`（或 `main_content_end_seconds`）声明审查终点，`PASS_ADJUDICATED` 会保留原始状态和审计窗口。适配器产生的时间窗若仅因帧率/小数格式在媒体末尾偏差不超过 50ms，会夹紧到实际 duration 并记录 `BENIGN_BOUNDARY_ROUNDING_CLAMPED`，不会把报告误判为 INVALID；更大的越界仍为 `INVALID_ISSUE_TIME_RANGE`。

派生视觉证据的规范身份链为：证据必须包含一个指向当前媒体的 `video`/`source_final_mp4` 等字段，同时在 `derived_from.decoded_video_md5`（亦支持 `decoded_stream_md5`、`decoded_visual_md5`）提供解码视频流 MD5；请求 `metadata.decoded_video_md5` 必须与之相同。只有路径当前且 MD5 相等时，旧 `media_path` 才会被视为派生源而非陈旧证据；缺任一条件仍报 `STALE_EVIDENCE`。

每项能力均输出 `PASS`、`WARN`、`FAIL`、`NOT_RUN`、`ERROR` 或 `NOT_APPLICABLE`，并标注 `requirement`：`REQUIRED`、`OPTIONAL` 或 `NOT_APPLICABLE`。只有 REQUIRED 的 `NOT_RUN/ERROR` 会生成缺口 issue 并扣分；OPTIONAL 只记录状态，NOT_APPLICABLE 不生成 issue、不扣分。请求可用 `required_capabilities` 显式提升能力要求。

显式 `asr`、`sentence_audit`、`action_audit` 和 `scene_brightness` 证据通过 provenance 后优先于旧 regression JSON 的聚合 MISSING section。亮度审计若没有顶层 `status`，但时间线顺序已验证且包含实测 shot rows，会记录为 `PASS_DERIVED`，不会静默猜测空证据为 PASS。

默认矩阵：图片要求 OCR，清晰度/亮度/构图/视觉连续性为可选，音频与动作能力不适用；纯音频要求音频分析，ASR/句审/声纹可选，视觉门不适用；视频成片要求视频、音频和生产回归，生产回归明确缺失的 action/ASR/亮度证据自动提升为 REQUIRED。coverage 与 AgentCut project 只有显式要求或生产配置要求时才是 REQUIRED。

缺工具、超时、缺少 REQUIRED 证据不会静默通过。默认音频门为数字零 `<= -90 dB`、静音 `>= 1.0s`、相邻 RMS 跳变 `> 12 dB`，版本 `qingshan.audio.v2-production-aligned`；覆盖值也会写入 `config_summary`。

WAV 快路径按 frame 正确下混多声道，不把 stereo 交错样本误作双倍时长。所有适配器 issue 时间窗在评分前强制校验并 clamp 到 `[0, media duration]`；若仍有适配器生成越界结果，报告输出 `validity=INVALID`、对应 capability `ERROR/INVALID_ISSUE_TIME_RANGE`，原 issue 标为不可行动且不参与扣分，原始时间窗保存在 `details.time_range_sanitization`。

## 环境音生产硬门

AgentCut project 中 `metadata.speech_free=true`、`metadata.kind` 包含 `AMBIENCE`，或 track ID 包含 `AMB` 的音频 clip 会自动进入 `ambience_analysis`。独立环境素材可设置 `metadata.audio_role=AMBIENCE`。默认规则版本为 `qingshan.ambience.v1`：

- `audio.ambience_gain_excessive`：volume 大于 1.0 警告，大于 1.5 阻塞；禁止用增益掩盖素材底噪。
- `audio.periodic_ambience_loop`：8 秒以内同源素材重复至少 3 次且最短交叉淡化不足 300ms 时警告；重复至少 8 次阻塞。
- `audio.high_frequency_hiss`：测量素材 6kHz 以上平均能量，并结合 clip gain 估算成片 hiss；超限要求降噪或换源。
- `audio.dialogue_to_ambience_ratio`：抽样对白源与环境源响度，余量不足 18dB 警告、不足 12dB 阻塞，建议对白驱动 ducking。
- `audio.noise_floor_jump`：提供 `evidence_inputs.audio_baseline` 时，与上一通过版本比较 6kHz 以上噪声；上升超过 3dB 警告、6dB 阻塞。

所有阈值写入 `config_summary.ambience` 和 review ID。可通过 `ambience_thresholds` 配置，但冻结、版权安全和不可逆操作规则不受影响。环境音硬门只生成结构化问题与修复建议，不直接修改、发布或删除媒体。

成片门槛默认继续采用生产严格值。确需 episode/project 特例时，请求可提供审计式 `gate_policy`：必须包含非空 `version`、`reason`、`episode` 或 `project` scope，以及非空 `overrides`。当前允许覆盖 `min_runtime`、`max_runtime`、`under1_min`、`under1_max`；scope 必须与请求 metadata/project 一致。生效值、原始阈值和理由进入 issue evidence、`config_summary` 与 review ID，不能静默放宽。

## Evidence provenance

Agent `0.2.2` 会在使用 ASR、sentence audit、OCR 和 regression CI JSON 前，校验其中的 `video`、`video_path`、`source_final_mp4`、`media_path`、`project` 等 provenance。若与当前 `item.path` 或 `evidence_inputs.agentcut_project` 不一致，该证据不会进入适配器，能力标为 `ERROR`、`error_code=STALE_EVIDENCE`，并生成阻塞的稳定 issue。报告的 `evidence_provenance.checks` 保留 expected/actual mismatch 与修复建议。

AgentCut project 会读取视频、音频、字幕 clip 的 `id`、时间范围及 `metadata.dialogue_id/beat_id`。音频对白或字幕时间窗可在 ASR 尚未提供时作为长镜和开场对白的动机证据；生产回归检测出的镜头/静态区间会按 AgentCut 明确视频切点重新分段，跨多个 clip 的区间不会被当成一个冻结镜头，但各 clip 内真正达到冻结门槛的区间仍会阻塞。`expectedDialogueIds` 与音频/字幕 dialogue ID 完整匹配时可生成 `coverage=PASS`。`coverage_manifest` 是 `coverage` 的兼容别名。

短镜比例同时保留 production regression 的 FFmpeg 像素场景统计和 AgentCut 物化时间线统计。Project provenance 支持精确 `output.path`，也支持同一 episode/trial 版本身份且时间线与审片媒体时长误差不超过 0.25 秒的 mux/subtitle 派生文件；跨版本拒绝。只有 provenance 通过、视频 clip 无 overlap，且短 clip 至少一侧连接不同素材源时，项目短镜才计为有效；项目比例落在生产阈值 5%–15% 时，低灵敏度像素检测的越界结果降为非行动型 `video.under1_ratio_reconciled`，不生成 blocker。重叠或无有效边界的假切不能覆盖像素检测失败。

从 0.6.0 起，成片节奏采用 AgentCut 物化时间线与最终媒体检测双证据。报告保留像素 detector 的 cuts、ASL、短镜比例、重复帧统计和原始 failures，同时输出项目的 clip 数、逐镜时长、ASL、最大镜长、重叠和短镜统计。若 provenance 匹配的项目引用 episode 一致、状态为 `ACTIVE_HARD_GATE` 的 `qingshan.agentcut_anti_padding_contract.v1`，且对白覆盖完整、时间线无重叠、项目同时声明 `allowShorter=true` 与 `paddingForbidden=true`，全局 `runtime_min` 和机械 `under1_min` 冲突会分别裁为 `video.runtime_min_reconciled` / `video.pacing_reconciled`（info、不可行动、不扣分）。缺覆盖、伪切、冻结、黑帧、版权或其他硬门不会因此放宽。

从 0.6.1 起，`audio.rms_jump` 只使用最终成片解码音频在真实 AgentCut 物化切点前后的短窗测量参与评分。固定 0.5 秒窗或整段均值差保留为 `audio.rms_window_delta_raw` 原始 info 证据，不单独扣分。局部短窗超过 12 dB 且存在数字零、dropout 或 click 时仍输出可行动 warning；连续对白/音乐动态只作为 motivated info。生产阈值没有降低。

从 0.7.0 起，`review-many` 顶层提供权威 `status/content_status`。任一失败项都会令 CLI 非零退出；内容问题为 `CONTENT_FAIL`，缺少 REQUIRED adapter/证据为 `CAPABILITY_FAIL`。图片 `sequence` 审查支持 `image_analysis`，并按候选 SHA 绑定生产 `qingshan.storyboard_sheet_ai_visual_adjudication.v1`：统一六栏六行、构图差异、身份/场景连续、格内 OCR/现代物、打斗三段式、近景到大全景及环境力量可视化。缺少任何请求要求的语义检查时不会假 PASS。

从 0.8.0 起，普通 `image/shot` 不再依赖某个固定集次或文件名。工具会在生产 QA 目录按候选 SHA-256 索引 `qingshan.image_visual_adjudication.v1` 与 OCR 证据；没有 OCR sidecar 时会对原图现场运行全分辨率 RapidOCR。批量 OCR 的顶层失败不会污染全部 sibling，工具会按当前图片路径重新归一化。语义视觉现场运行使用 `QINGSHAN_IMAGE_ANALYSIS_COMMAND`，命令从 stdin 接收 `qingshan.image_visual_runtime.request.v1` JSON，并在 stdout 返回含 exact SHA、checks、confidence、regions 的 `qingshan.image_visual_adjudication.v1`。运行器缺失或返回错误时为 `CAPABILITY_FAIL`，不会变成内容失败或 PASS。

从 0.9.0 起，视频 `shot/source` 可声明 `action_required: true` 或 `action_intensity: high|medium|fight|combat|supernatural`。动作镜的逐镜 `near_duplicate_ratio` 硬门为 `<=0.15`，只使用当前 exact-SHA 镜头的 cadence 证据，不允许由全片平均值稀释。动作镜还必须提供 exact-SHA `action_physics` 证据，检查 wind-up、contact、force-transfer、result、手/道具真实接触、悬空手、物体漂移和动作头尾完整性。普通静态对白镜不套用该 0.15 门槛。报告保留 clip ID、SHA、阈值、帧/时间窗、置信度和可回滚修复建议。

从 0.9.1 起，视频/full-cut OCR 同时接受 `evidence_inputs.ocr` 和生产双证据形式 `ocr_raw + ocr_adjudication`。机器裁定必须绑定当前媒体 SHA、原始 OCR 文件及 SHA、逐帧视觉证据及 SHA，并明确保留 raw FAIL；有效裁定仅推翻已核验的误识别。若原始 OCR 因固定尾长造成覆盖缺口，工具会现场补扫未覆盖区间，不能用裁定掩盖未审主内容。缺证据或 provenance 不匹配仍为 OCR 能力失败。

`repairTask` 根据问题时间码优先映射到相交的视频 clip，并输出 `clip_id` 与 `clip_metadata`。

## Issue 聚类与扣分上限

同一 `rule_id + media_path` 的重叠或相邻时间窗会在评分前聚类。代表 issue 保持稳定 ID，`details.deduplication` 保存原始 issue IDs、完整子证据、来源及聚类时间范围。内建分析与生产 regression 命中同一根因时优先采用生产 regression 的 issue；例如 `115-116.5s` 与 `114.6325-116.899563s` 长静音合为一项。

报告同时输出 `summary.raw_issue_count`、`summary.deduped_issue_count` 和 `deduction_cap`。非阻塞 `audio.rms_jump` 的累计扣分上限为 1.0；其他非阻塞 warning 类默认上限为 1.4。blocking 硬门没有扣分上限，也不会因聚类或 cap 被放行。

`repairTask` 新增 `include_warnings`。未传时，`NOT_FINAL` 报告自动纳入可修 warning；`publish_allowed`、`delete_allowed` 和 `irreversible_action_allowed` 始终为 false。

`repair-task` 同时接受单报告与 `review-many` 的 `{items:[...]}` 输出。单 item wrapper 自动解包；多 item 返回 `qingshan.agentcut.repair_task_batch.v1`；空数组或错误 schema 返回机器可读 `SchemaError` 和退出码 2，不输出 traceback。

聚合的 `video.too_many_long_shots` 会在 evidence 适配阶段补齐每条长镜的 `shot_index/start/end/duration/motivated/static_hold`。生成修复任务时按长镜区间展开，并为每个相交的视频 clip 生成独立 repair，保留 clip ID、dialogue/beat metadata 和稳定 repair ID。

长镜存在本身不再等于 blocker。报告分别输出 `raw_long_shot_count`、`motivated_long_shot_count`、`unmotivated_long_shot_count`；只有无动机长镜数量超过 `max_unmotivated_long_shots` 才生成 blocking 的 `video.too_many_long_shots`。有对白的低运动长镜可同时是 `static_hold:true` 和 `motivated:true`：static-hold 是画面描述，只有无对白/无动机且 static gate 不通过时才阻塞。有动机长镜以 `video.motivated_long_shots` info 留证，不生成强制拆分 repair。

非行动型 info（`actionable:false`）仅作证据，评分扣分固定为 0。所有 repair-task v2 repair 都保留原始 `rule_id`。

生产 regression 报出的视觉镜头边界 RMS jump 会进行切点局部音频连续性裁定：比较切点前后 120ms 与中心 20ms，检测数字零、掉音和高幅样本爆点。连续对白/音乐动态降为 `info + actionable:false`，保留原始 jump dB、切点、局部 RMS、置信度和聚类子证据；只有数字零、dropout 或 click 才保持 warning 并进入 repair。

`audio_analysis` 与 `regression_ci` capability 使用最终 adjudicated issues 重算状态，并保留 `raw_status`、`raw_evidence` 和裁定原因。所有 raw 音频 jump 均被局部连续性证明为有动机、且没有数字零/dropout/click 时，audio 可从 raw FAIL 裁为 PASS；仍有真实音频硬门时保持 FAIL。Regression 只有在 AgentCut 已纠正 long/static/under1、其余 REQUIRED 能力通过且没有未解决 production issue 时才可从 raw FAIL 裁为 PASS；否则为 WARN 或 FAIL。

`required_capabilities` 会先规范化别名：`audio → audio_analysis`、`video → video_analysis`、`sentence → sentence_audit`、`speaker → voiceprint`、`brightness → scene_brightness`、`coverage_manifest → coverage`。报告只输出 canonical key，并在 `config_summary.capability_aliases` 记录映射，避免同一能力一边 PASS、一边因别名 NOT_RUN。

声线注册样音可将 `asr`、`sentence_audit`、`voiceprint` 显式列为 REQUIRED。对应 `evidence_inputs` JSON 必须 provenance 匹配且包含明确 PASS/FAIL 状态；PASS 证据计为能力通过，缺证据明确 NOT_RUN，不会静默降为 OPTIONAL。

## 人审超时

调用方应记录 `requested_at`；900 秒后可保留原始结果并将 routine review 裁为 machine。若涉及验证码、登录、权限/付款、版权/风控、不可逆发布/替换/删除，必须保持人工阻塞。本 Agent 从不执行这些动作。

## Ledger 与回归

`--ledger` 和 `--registry` 均为独立 NDJSON，仅追加。不要把 `--ledger` 指向生产线旧 JSON；旧的 `/Users/rogerwu/qingshan_short_drama/workflow/agent_mistake_ledger.json` 仅作为兼容输入来源。`promoteRule` 将已确认 issue 追加成回归规则，之后自动复测。修复任务明确携带 `publish_allowed:false`。

详见 [AUDIT.md](AUDIT.md) 与 `schema/`。E18R 演示只读取 NOT_FINAL 文件。
