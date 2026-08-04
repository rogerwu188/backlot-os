# AgentCut

面向 AI Agent 的无界面视频剪辑引擎。Agent 只需生成项目 JSON；AgentCut 负责校验、编译 FFmpeg 滤镜图和导出。当前版本支持 2 条视频轨、3 条音频轨、原生烧录字幕轨、剪切、拼接、画面覆盖、淡入淡出、音量、画面位置/尺寸以及多进程批量渲染。

## 快速开始

要求 Python 3.10+ 和可执行的 FFmpeg。

```bash
python -m pip install -e .
agentcut validate examples/basic.json
agentcut compile examples/basic.json
agentcut render examples/basic.json --overwrite
```

解压 macOS ARM64 独立包后也可以不安装，直接运行：

```bash
./run-agentcut agent --workers 4
```

所有 CLI 输出都是单行 JSON。成功返回 `{"ok":true,...}`，失败写入 stderr 并以非零状态退出，适合 Agent 和任务调度器解析。

macOS Apple Silicon 分发包已内置 FFmpeg 8.1.2，无需系统安装。运行时查找顺序是：`--ffmpeg` 显式路径、`AGENTCUT_FFMPEG`、随包二进制、系统 `PATH`。

## 高并发批量渲染

```bash
agentcut render-batch jobs/one.json jobs/two.json jobs/three.json \
  --workers 3 --overwrite
```

每个项目在独立进程内运行一个 FFmpeg，任务失败相互隔离。`--workers` 是并行项目数；`output.threads` 是单个 FFmpeg 的线程数。批处理环境建议按 CPU 核数分配，例如 16 核机器同时跑 4 个任务时，每个项目设 `threads: 4`。硬件编码可直接设置 `videoCodec`（例如系统已配置时使用 `h264_videotoolbox`、`h264_nvenc` 或 `h264_qsv`）。

SDK：

```python
from agentcut import AgentCutEngine

engine = AgentCutEngine()
project = engine.load("project.json")
command = engine.compile("project.json")       # 只生成命令，不执行
result = engine.render("project.json", overwrite=True)
batch = engine.render_many(
    ["job-a.json", "job-b.json", "job-c.json"],
    workers=3,
    overwrite=True,
)
```

## Task2 / 上级 Agent 调用

启动常驻并发 Agent：

```bash
agentcut agent --workers 4
```

Task2 向进程 stdin 写入 NDJSON，每行一个请求。多个请求会并行执行，响应通过相同 `id` 关联；完成顺序不保证与提交顺序相同。

```json
{"id":"check-1","method":"health","params":{}}
{"id":"edit-101","method":"render","params":{"project":"/data/job-101.json","overwrite":true}}
{"id":"batch-7","method":"renderMany","params":{"projects":["/data/a.json","/data/b.json"],"workers":2}}
```

支持的方法为 `health`、`validate`、`validateMedia`、`compile`、`render`、`renderMany`、`transformProject`、`trimProject`、`rollbackProject`、`longTakePreflight`、`validateLongTake`、`prepareFirstLastGeneration`、`finalizeFirstLastGeneration`、`generateCharacterCardPrompt`、`validateCharacterCard`、`admitCharacterCard`、`bindSeedanceCharacter`、`generateBgm`、`queryBgm`、`listSpeechVoices`、`generateSpeech`、`querySpeech`、`listShotRecipes`、`mapShotRecipeRepairs`。每个响应都是：

```json
{"id":"edit-101","ok":true,"result":{"output":"/data/out.mp4","duration":8.0}}
```

`health` 会返回当前 runtime 版本及机器可读 capability。0.9.1 起，`capabilities.requireCutReason=true`，且 `continuityGate.mode=strict`；上级 Agent 可在提交生产任务前确认所需字段为 `cut_reason`、`scene_id`、`light_key`、`axis_line`、`eyeline`。

0.9.6 的 CLI 也支持 `agentcut health`，但原有 NDJSON health 字段和值保持不变。新增 `runtimeHash`、FFmpeg/FFprobe SHA，以及 `longTake` / `giggleFirstLast` 两项 capability，供青山 wrapper 在升级前做非降级比较。

## CL2X-352/353 长镜头与 Giggle 首尾帧生产合同

多张普通参考图和分段 cue 不能被视为有序关键帧。连续镜头提交前先执行：

```bash
agentcut longtake-preflight request.json
```

当多图供应商没有明确保证跨锚点插值且无硬切时，结果为 `FAIL_BEFORE_PAID_SUBMISSION`，CLI 退出 `2`。已有候选使用 FFmpeg scene 检测：

```bash
agentcut longtake-validate candidate.mp4 --anchor-times 5,10
```

Giggle 首尾帧任务的生产字段是 `generation_mode=image_to_video_first_last`，并且 `inputs` 必须恰好包含一个 `start_frame` 和一个 `end_frame`。付款前准备：

```bash
agentcut first-last-prepare task.json \
  --client /Users/rogerwu/qingshan_short_drama/tools/giggle_api_client.py \
  --include-command
```

准备结果固定记录 `POST /api/v1/generation/image-to-video`，并证明 argv 使用 `image-to-video --start-frame ... --end-frame ...`。存在 `images`、`reference_images`、`referenceImages` 或 `anchors` 会直接拒绝，不会静默回退到 `omni-video`。

下载后必须生成最终回执并通过硬切审计：

```bash
agentcut first-last-finalize task.json candidate.mp4 --task-id REMOTE_TASK_ID
```

NDJSON 等价方法是 `prepareFirstLastGeneration` 和 `finalizeFirstLastGeneration`。最终回执包含端点、角色与源 SHA、远端 task ID、输出 SHA、时长和硬切时间码。`accepted=false` 时候选不得进入下游；cadence、OCR、ASR 仍需独立执行。

## CL2X-358 角色 canonical 三视图建卡

角色描述必须先写成结构化字段。完整 schema 与示例分别是 `schema/agentcut-character-description.schema.json` 和 `examples/character-description.json`。生成固定模板提示词：

```bash
agentcut character-card-prompt examples/character-description.json
```

模板固定要求单张 16:9：最左为正面中性大头照，之后依次为全身正面、侧面、背面；纯中性灰无缝背景、柔和棚拍、近正交、全身不裁切。脸型、五官、发型、肤色、体型、服装、配饰、材质和配色必须跨视图一致，禁止重设计、动态姿势、表情变化、额外角色、复杂背景、文字、UI 和水印。

生成图片后，按 `schema/agentcut-character-canonical-card.schema.json` 提交 manifest。准入会实际探测图片，并硬校验 16:9、视图数量与顺序、每个归一化画面区域、全身未裁切、证据来源及每一项身份/禁用内容检查：

```bash
agentcut character-card-validate examples/character-canonical-card-manifest.json
agentcut character-card-bind examples/character-canonical-card-manifest.json
agentcut character-card-admit examples/character-canonical-card-manifest.json \
  examples/character-asset-registry.json
agentcut character-card-admit examples/character-canonical-card-manifest.json \
  examples/character-asset-registry.json --output staged-registry.json --write
```

`character-card-admit` 默认 dry-run；只有显式 `--write` 才原子写入调用方指定的输出。已准入的相同 `asset_id` 不能被不同 manifest 静默替换。任一硬门失败，决定为 `REJECT_ASSET`，不会产生 Seedance 绑定。通过时输出：

```json
{"token":"[[char_1]]","slot":1,"assetId":"CHAR-LIN-QING-ANCIENT","canonicalCard":"/abs/character-card.png","canonicalCardSha256":"..."}
```

NDJSON 协议与 CLI 使用同一校验器：

```json
{"id":"p1","method":"generateCharacterCardPrompt","params":{"description":"/data/character-description.json"}}
{"id":"v1","method":"validateCharacterCard","params":{"manifest":"/data/character-card-manifest.json"}}
{"id":"b1","method":"bindSeedanceCharacter","params":{"manifest":"/data/character-card-manifest.json"}}
{"id":"a1","method":"admitCharacterCard","params":{"manifest":"/data/character-card-manifest.json","registry":"/data/asset-registry.json","dryRun":true}}
```

现有单图角色参考不会被自动迁移或改写；只有显式走 CL2X-358 新卡准入时才启用此门禁。升级与回滚见 `MIGRATION_0.9.7.md`。

## BGM 生成（0.9.11）

0.9.11 将 Giggle 音乐生成接入 Agent 视频剪辑引擎。密钥只从 AgentCut 进程环境中的 `GIGGLE_API_KEY` 读取，不接受项目 JSON 或命令行密钥参数。CLI 用法：

```bash
agentcut bgm-generate "Instrumental cinematic underscore, sparse, no vocals, loop-friendly" \
  --output-dir /data/generated-bgm
agentcut bgm-query REMOTE_TASK_ID
```

上级 Agent 可提交同等 NDJSON 请求：

```json
{"id":"bgm-1","method":"generateBgm","params":{"prompt":"Instrumental cinematic underscore, sparse, no vocals, loop-friendly","outputDir":"/data/generated-bgm","pollIntervalSeconds":20,"timeoutSeconds":1500}}
```

生成会自动轮询、原子下载 `bgm_candidate_N.mp3`，并返回本地路径、大小、SHA-256 与媒体类型；公开响应不会包含供应商签名 URL。返回文件可直接作为 AgentCut 项目音频轨 clip 的 `source`。完整请求见 `schema/agentcut-bgm-request.schema.json` 和 `examples/giggle-bgm.json`。

供应商当前未返回可验证的商用授权元数据，因此结果固定 `releaseEligible=false`。进入发行前必须完成媒体探测、时长、无人声、循环接缝、响度、人工听审和商用权利门禁。升级与回滚见 `MIGRATION_0.9.11.md`。

## 配音生成（0.9.16）

0.9.16 将 Giggle 文转音接入 Agent 视频剪辑引擎，用于剧情对白、旁白和 voiceover。密钥只从 AgentCut 进程环境中的 `GIGGLE_API_KEY` 读取，不接受项目 JSON 或命令行密钥参数。CLI 用法：

```bash
agentcut speech-voices
agentcut speech-generate "她停在门口，声音压得很低：你早就知道真相，对吗？" \
  --voice-id ttv-voice-2025092214470225-uxPJ4AuZ \
  --emotion sad \
  --output-dir /data/generated-dialogue
agentcut speech-query REMOTE_TASK_ID
```

上级 Agent 可提交同等 NDJSON 请求：

```json
{"id":"speech-1","method":"generateSpeech","params":{"text":"她停在门口，声音压得很低：你早就知道真相，对吗？","voiceId":"ttv-voice-2025092214470225-uxPJ4AuZ","emotion":"sad","outputDir":"/data/generated-dialogue","pollIntervalSeconds":5,"timeoutSeconds":120}}
```

生成会自动轮询、原子下载 `dialogue_voice.mp3`，并返回本地路径、大小、SHA-256、媒体类型和 `directTrackUse.track=Audio.Dialogue`；公开响应不会包含供应商签名 URL。完整请求见 `schema/agentcut-speech-request.schema.json` 和 `examples/giggle-speech.json`。

供应商当前未返回可验证的商用授权元数据，因此结果固定 `releaseEligible=false`。进入发行前必须完成媒体探测、对白时长/口型时间、人工听审和商用权利门禁。升级与回滚见 `MIGRATION_0.9.16.md`。

CL2X-298 严格门禁由项目顶层显式开启：

```json
{
  "requireCutReason": true,
  "timeline": {
    "videoTracks": [{
      "id": "main",
      "clips": [{
        "source": "/abs/shot.mp4",
        "start": 0,
        "duration": 2.5,
        "metadata": {
          "cut_reason": "切至角色反应以确认信息落点",
          "scene_id": "scene-01",
          "light_key": "window-left-soft",
          "axis_line": "hero-villain-180",
          "eyeline": "hero-right-villain-left"
        }
      }]
    }]
  }
}
```

开启后，任意启用的视频 clip 缺少上述任一非空字段都会产生 `CUT_REASON_REQUIRED`，使 validate 失败，并在 compile/render/renderMany 前置阶段阻断；coverage 位于 `coverage.cutReason`。未开启时保持旧项目兼容。

`render` 默认只返回紧凑的 `output` 和 `duration`，不会返回可能非常庞大的 FFmpeg 命令。按需设置 `includeHash:true` 返回输出 SHA-256，设置 `includeCommand:true` 才返回完整命令。

长渲染可设置 `progress:true`。最终响应之前会输出同一 `id` 的事件：

```json
{"id":"edit-101","event":"progress","data":{"phase":"rendering","time":42.1,"duration":168.08,"progress":0.2505}}
```

进度事件是可选的，因此未启用 `progress` 的旧调用方不会收到额外消息。

错误不会终止 Agent：

```json
{"id":"edit-101","ok":false,"error":{"type":"ValidationError","message":"..."}}
```

## StoryCloud / 容器部署

仓库包含 `Dockerfile` 和 `storycloud.yaml`。容器使用 Linux 发行版 FFmpeg、非 root 用户、`/data` 媒体卷以及 NDJSON 标准输入输出协议。若 StoryCloud 的实际清单字段与示例不同，只需映射镜像入口 `agentcut agent --workers 4`、媒体卷 `/data` 和并发数；剪辑 JSON API 不变。

```bash
docker build -t agentcut:latest .
docker run --rm -i -v "$PWD/data:/data" agentcut:latest
```

## JSON API

完整机器可读规范位于 [`schema/agentcut-project.schema.json`](schema/agentcut-project.schema.json)，完整示例位于 [`examples/basic.json`](examples/basic.json)。最小项目：

```json
{
  "version": "1.0",
  "output": {"path": "out.mp4", "width": 1920, "height": 1080, "fps": 30},
  "timeline": {
    "videoTracks": [
      {"id": "A", "clips": [{"source": "a.mp4", "start": 0, "in": 3, "duration": 5}]}
    ],
    "audioTracks": [
      {"id": "voice", "clips": [{"source": "voice.wav", "start": 0, "in": 0, "duration": 5, "volume": 1}]}
    ]
  }
}
```

时间单位统一为秒，可以是小数：

- `start`：片段在输出时间线的位置。
- `in`：从源媒体的哪个位置开始取材。
- `duration`：取材时长，也是片段在时间线上的长度。
- `transitionIn` / `transitionOut`：目前支持 `none`、`fade`，格式为 `{"type":"fade","duration":0.5}`。相邻片段通过重叠 `start`/`duration` 形成交叉淡化。
- `volume`：音量倍率，`0` 静音、`1` 原音量，可大于 1。
- `opacity`、`position`、`size`：视频透明度、位置和尺寸。视频轨按 JSON 顺序叠加，B 轨在 A 轨上方。
- `id`：片段的稳定标识；`metadata`：Agent 自定义映射信息，例如 `dialogue_id`、`beat_id`。严格校验错误和编译摘要都会原样保留它们。
- 相对媒体路径以项目 JSON 所在目录为基准；相对输出路径也写入该目录。

“拼接”无需单独操作：把片段首尾相接排列即可。剪切由 `in` 与 `duration` 表达。没有音频片段时导出静音视频。

## 严格媒体与黑场校验

普通 `validate` 保持原有快速结构校验。生产渲染前建议启用严格模式：

```bash
agentcut validate project.json --strict-media
```

或通过 Agent 协议调用任一形式：

```json
{"id":"qa-1","method":"validate","params":{"project":"/data/project.json","strictMedia":true}}
{"id":"qa-2","method":"validateMedia","params":{"project":"/data/project.json"}}
```

严格模式使用 FFprobe 并行检查每个唯一媒体源（同一路径只探测一次），并检测：

- 源文件无法读取或无法确定时长；
- 视频轨引用的源没有视频流，或音频轨引用的源没有音频流；
- `in + duration` 超出真实媒体时长；
- 输出时间线中没有任何已启用、`opacity > 0` 视频片段覆盖的区间。

黑场区间以 `VIDEO_GAP` 错误返回；相邻片段放在 `relatedClips`，包含 `trackId`、`trackIndex`、`clipIndex`、`clipId`、`metadata` 和精确 `timeRange`，可直接映射回 dialogue/beat QA。严格校验不通过时 CLI 退出码为 `2`；Agent 响应仍是成功执行的校验结果，即 `ok:true`、`result.valid:false`，便于调用方读取全部问题。

编译响应还包含紧凑 `summary`，记录每个 FFmpeg 输入对应的轨道、片段标识、metadata、源区间和时间线区间。

## 原生字幕轨与 P0 烧录门禁

字幕是时间线的一等公民，不需要预先生成 ASS，也不需要在外部追加 FFmpeg 命令。`subtitleTracks` 中的 Caption 会在最后一层视频合成后由 AgentCut 原生烧录；CLI、SDK、NDJSON `render` 和 `renderMany` 走同一条编译路径。

生产项目必须设置：

```json
{
  "requireBurnedSubtitles": true,
  "expectedDialogueIds": ["DIA-001", "DIA-002"],
  "timeline": {
    "subtitleTracks": [{
      "id": "zh-CN",
      "style": {
        "font": "/System/Library/Fonts/STHeiti Medium.ttc",
        "size": 46,
        "color": "#FFFFFF",
        "outline": 3,
        "outlineColor": "#000000",
        "alignment": "bottom-center",
        "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170},
        "wrap": 15
      },
      "clips": [
        {"id": "cap-001", "dialogue_id": "DIA-001", "text": "半夜送礼，不怕犯忌？", "start": 0.2, "duration": 2.5},
        {"id": "cap-002", "dialogue_id": "DIA-002", "text": "夫人的话，忌讳让路。", "start": 2.8, "duration": 2.7}
      ]
    }]
  }
}
```

轨道 `style` 是默认值；每个 Caption 也可以用 `style` 或同名顶层字段覆盖 `font`、`size`、`color`、`outline`、`outlineColor`、`alignment`、`margins`、`wrap`。`font` 在生产门禁中必须是存在的 `.ttf`、`.otf` 或 `.ttc` 文件，AgentCut 会读取字体 cmap 并逐字检查中文字符，禁止静默输出豆腐块。

9:16 的 720×1280 推荐安全区为左右各 72 px、顶部 96 px、底部 160–180 px；示例使用底部 170 px，避开平台标题、进度条和交互按钮。完整可运行配置见 `examples/subtitles-9x16.json`。

无论是否启用 `--strict-media`，`validate` 都会检查字幕硬门；`render` 会再次执行同一前置检查。以下情况返回 `valid:false`，且 CLI 退出码为 `2`：

- `requireBurnedSubtitles=true` 但没有已启用的 Caption；
- 空文本、时间越界或任意 Caption 重叠；
- 缺少 `dialogue_id`，或同一个 `dialogue_id` 出现多次；
- 字体文件不存在、字体无效或缺少文本所需字形；
- `expectedDialogueIds` 与字幕 `dialogue_id` 不是严格一一对应。

Coverage 输出示例：

```json
{
  "coverage": {
    "subtitles": {
      "required": true,
      "expectedCount": 40,
      "captionCount": 40,
      "matchedCount": 40,
      "count": "40/40",
      "missingDialogueIds": [],
      "unexpectedDialogueIds": [],
      "duplicateDialogueIds": []
    }
  }
}
```

NDJSON 调用无需新方法：

```json
{"id":"e19-sub-qa","method":"validate","params":{"project":"/data/E19R.project.json"}}
{"id":"e19-render","method":"render","params":{"project":"/data/E19R.project.json","overwrite":true}}
{"id":"batch","method":"renderMany","params":{"projects":["/data/E19R.project.json"],"workers":1,"overwrite":true}}
```

## Timeline trim plan / 项目变换

`transform` 按稳定 `clip.id` 或 `metadata.dialogue_id` 对源素材执行 head trim。一次逻辑操作可以同时匹配视频和音频片段；`requiredTrackKinds:["video","audio"]` 会在缺少任一侧时拒绝变换。

每次 head trim 的语义是：

1. 匹配片段的 `in += headTrim`；
2. 匹配片段的 `duration -= headTrim`，不改变速度；
3. 匹配片段保持当前时间线起点；之前操作可能已通过 ripple 更新其 `start`；
4. 所有轨道中时间点在该片段之后的片段执行 `start -= headTrim`；
5. 不改变轨道数组和片段数组顺序。

完整计划 Schema：`schema/agentcut-trim-plan.schema.json`；可运行示例：`examples/trim-plan.json`。

生产写盘前先 dry-run：

```bash
agentcut transform /data/E18R.project.json /data/E18R.trim-plan.json \
  --dry-run --strict-media
```

确认 diff 后生成新项目和确定性审计：

```bash
agentcut transform /data/E18R.project.json /data/E18R.trim-plan.json \
  --output /data/E18R.trimmed.project.json \
  --audit /data/E18R.trim.audit.json \
  --strict-media
```

严格校验不通过时不会写项目或审计，CLI 退出码为 `2`。未传 `--dry-run` 时必须明确提供 `--output`，不会覆盖原项目。

从审计精确回滚：

```bash
agentcut rollback /data/E18R.trim.audit.json \
  --output /data/E18R.restored.project.json
```

Task2 / NDJSON dry-run：

```json
{"id":"e18r-dry","method":"transformProject","params":{"project":"/data/E18R.project.json","plan":"/data/E18R.trim-plan.json","dryRun":true,"strictMedia":true}}
```

正式写盘：

```json
{"id":"e18r-apply","method":"transformProject","params":{"project":"/data/E18R.project.json","plan":"/data/E18R.trim-plan.json","dryRun":false,"output":"/data/E18R.trimmed.project.json","auditPath":"/data/E18R.trim.audit.json","strictMedia":true}}
```

回滚：

```json
{"id":"e18r-rollback","method":"rollbackProject","params":{"audit":"/data/E18R.trim.audit.json","output":"/data/E18R.restored.project.json"}}
```

NDJSON 变换默认为 `dryRun:true`。响应默认返回 hash、总裁剪量和逐片段 diff；只有显式设置 `includeProject:true` 或 `includeAudit:true` 才内联完整对象。

E18R 的计划应设置以下硬断言，并列出全部 33 个真实 `dialogueId` 操作：

```json
{
  "version": "1.0",
  "expectedOperationCount": 33,
  "expectedTotalTrim": 6.6,
  "operations": [
    {
      "id": "trim-E18R-001",
      "match": {"dialogueId": "实际 dialogue_id"},
      "headTrim": 0.2,
      "contentGuard": "silence-head",
      "requiredTrackKinds": ["video", "audio"]
    }
  ],
  "protections": {"frozenBeatIds": ["B05"]},
  "options": {
    "ripple": true,
    "requireSynchronizedStart": true,
    "requiredTrackKinds": ["video", "audio"],
    "maxHeadTrim": 0.2,
    "preserveTrackOrder": true
  }
}
```

`contentGuard:"silence-head"` 是每条操作的必需安全断言，表示上游静音/台词 QA 已确认被移除区域不含句子；变换器本身不会猜测语言边界。`beatIds` 只禁止对该 beat 做 source trim，但允许全局 ripple 更新其 `start`；`frozenBeatIds` / `frozenClipIds` 禁止包括 ripple 在内的任何字段变化。保护时间区间同样禁止之前的操作把该区间 ripple 移动。如果 33 次裁剪与冻结 B05 的约束冲突，变换会停止并报告冲突，不会静默放宽保护。

审计不写当前时间戳，使用规范化 JSON 和 SHA-256 记录 `beforeHash`、`afterHash`、`planHash`、逻辑操作、逐字段 diff、总裁剪量及原项目回滚数据。相同项目和计划会生成完全相同的审计内容。

## 架构

```text
Agent / Scheduler
      │ project JSON
      ▼
Parser + semantic validation
      │ typed Project / Track / Clip
      ▼
Timeline compiler ──► FFmpeg filter_complex
      │
      ├─ single render ──► FFmpeg process
      └─ batch render  ──► process pool ──► multiple FFmpeg processes
```

- `models.py`：稳定的核心数据模型与语义校验。
- `validation.py`：FFprobe 媒体探测、越界检查和最终视频覆盖分析。
- `transform.py`：确定性 head-trim/ripple 变换、保护规则、审计和回滚。
- `compiler.py`：纯函数式时间线编译器，便于测试和扩展。
- `engine.py`：SDK、进程执行、并发批处理与错误隔离。
- `cli.py`：面向 Agent 的 JSON 输入/输出边界。

后续增加字幕或特效时，可在 `Clip` 上增加 `effects`，并在编译器中把效果节点插入片段滤镜链；增加轨道时只需调整校验上限，混合/叠加机制不变。生产环境还可在执行层增加持久化任务队列、GPU 资源池和缓存，核心项目格式无需改变。

## 测试

```bash
python -m unittest discover -v
```

## 两遍响度母带与原子输出（0.9.3）

当 `masterAudioPolicy.loudnessTargetLufs` 非空时，`render` 不再使用不可校准的单遍 loudnorm。运行时先把完整时间线渲染为带安全余量的无损预母带，并取得 `input_i`、`input_tp`、`input_lra`、`input_thresh`、`target_offset`；第二遍把这些参数交给 loudnorm，同时复制已经编码的视频流并编码最终音频。测量参数、预母带衰减和实际滤镜写入 `manifest.audioSafety.mastering`。

目标文件始终先写入同目录隐藏临时文件。只有视频/音频时长、综合响度、真峰值和削波样本全部通过后才原子替换正式路径。任何阶段失败均以非零状态退出、清理临时文件，并保留覆盖前的已有输出。0.9.2 项目 JSON 无需迁移，`masterAudioPolicy` 字段及 -16 LUFS 等既有目标保持不变。
## Narrative Gate：拒绝“安全但无价值”的镜头

在项目根节点启用 `narrativeGate.enabled=true` 后，普通 `validate`、严格媒体校验和 `render` 前置检查都会执行叙事硬门。视频 clip 用 metadata 声明：

- `narrative_role`：`dialogue`、`action`、`reaction`、`cutaway`、`background` 等。
- `semantic_id`：镜头表达的语义单元；重复次数超过 `maxSemanticRepeats` 时返回 `NARRATIVE_SEMANTIC_DUPLICATE`。
- `maxSemanticGroupRatio`：只约束使用两次及以上的 `semantic_group` 占片比，默认 `0.15`。单次使用的独立语义不属于重复，因此短片段不会仅因镜头占比超过 15% 而失败；连续重复和 12 秒冷却门仍然独立执行。
- `information_ids`：这个镜头带来的新事实、动作或情绪变化。reaction/background 等无此字段时返回 `NARRATIVE_NO_NEW_INFORMATION`。
- Cutaway 必须提供 `relevance_to`，指向项目内存在的 dialogue、beat、event 或 information id；否则返回 `CUTAWAY_IRRELEVANT` / `CUTAWAY_CONTEXT_MISMATCH`。
- `background`、`bed`、`atmosphere`、`establishing` 共同受单镜头秒数和全片占比预算约束。
- `requiredShotIds` 与 clip 的 `metadata.shot_id`（或 clip `id`）逐项核对，缺少时以 `REQUIRED_SHOTS_MISSING` 显式失败，不再用空镜补时间。

完整参数见 [examples/narrative-gate.json](examples/narrative-gate.json)。语义判断采用 Agent 提供的结构化标注，因此是确定、可审计的硬门；视觉 embedding/LLM 可以在上游生成这些标注，但不会在渲染时产生不可重复的判断。

生产项目也可以直接使用 CL2X-282 字段：`narrative_function`、`new_information`、`semantic_group`、`fallback_only` 和根节点 `runtimePolicy`。只要出现这些字段，Narrative Gate 自动启用，不要求再增加 `narrativeGate.enabled`。结果位于 `coverage.narrative`，缺镜头清单位于 `coverage.narrative.coverageGaps`。

语义预算的判定明细位于 `coverage.narrative.semanticBudget`：`mode` 固定为 `repeated-groups-only`，并分别列出 `evaluatedGroups` 与 `singleUseGroups`。需要调整重复语义的全片预算时，在 `narrativeGate.maxSemanticGroupRatio` 中显式配置 `0 < ratio <= 1`；该参数不会关闭 `NARRATIVE_SEMANTIC_DUPLICATE`、`SEMANTIC_COOLDOWN_CONSECUTIVE` 或 `SEMANTIC_COOLDOWN_12S`。

## 本地对白候选提取

```bash
agentcut dialogue-isolate source.wav \
  --output vocal-candidate.wav \
  --report isolation-report.json
```

该命令执行确定性的中置声道提取、语音频段过滤和降噪，并输出污染/伪影风险报告。它不是专业声源分离，默认置信度门为 0.8；未通过时退出码为 `2`、`registrationEligible:false`、状态为 `SEPARATION_CONFIDENCE_FAILED`，不得把结果描述为干净声纹。即使通过，也保持 `REVIEW_REQUIRED`，注册前仍需听审。

Demucs 环境使用安全包装入口：

```bash
agentcut isolation-health
agentcut demucs-isolate source.wav --output-dir separated --report separation.json --model htdemucs
```

`isolation-health` 会让 soundfile、FFmpeg、torchaudio 分别实际写一个探测 WAV。`demucs-isolate` 在导入 Demucs、下载模型和推理之前执行同一检查；torchaudio 无可用保存 backend 时自动使用 soundfile，仍不可用则使用 FFmpeg。所有后端都失败时立即退出，绝不会先跑完模型。报告保存输入、模型文件、输出 SHA-256，以及新建文件和覆盖前备份的回滚清单。生产可通过 `--expected-model-sha256` 固定模型文件。

## Nalu Motion 片尾

项目根节点通过 `outro.enabled=true` 显式启用。已注册 `nalu-motion-v1`：720×1280 黑底、3 秒、0.25 秒入退场、中文标题、居中猫 Logo、NALU MOTION 品牌文字，默认素材为：

`/Users/rogerwu/qingshan_short_drama/libraries/brand/nalu_motion_cat_logo_v1.png`

片尾始终从 `mainDuration` 开始追加，burned subtitles 和对白只能存在于此边界之前。启用后素材缺失、空文件、非绝对路径、模板为空、转场越界、非 9:16、安全区溢出、片尾音频不可读或峰值达到数字零都会令 `validate` 和 `render` 失败，不会静默跳过。

```json
{
  "outro": {
    "enabled": true,
    "template": "nalu-motion-v1",
    "assetPath": "/Users/rogerwu/qingshan_short_drama/libraries/brand/nalu_motion_cat_logo_v1.png",
    "duration": 3,
    "transitionIn": 0.25,
    "transitionOut": 0.25,
    "titleText": "青山",
    "nextText": "敬请期待",
    "brandText": "NALU MOTION",
    "safeArea": {"left": 72, "right": 72, "top": 128, "bottom": 128},
    "logo": {"x": 235, "y": 590, "width": 250, "height": 141},
    "includeInTotalDuration": true
  }
}
```

`render`、`renderMany`、CLI 和 NDJSON 返回同一个 manifest，并写入 `<output>.manifest.json`。其中 `outro.present=true`，包含模板版本、实际起止、时长及所有片尾素材 SHA-256。完整项目见 [examples/nalu-motion-outro-720x1280.json](examples/nalu-motion-outro-720x1280.json)。

发行项目应再开启 `requireBrandedOutro:true`。这不是提示项，而是 validate、render 和 renderMany 的前置硬门：

```json
{
  "requireBrandedOutro": true,
  "outro": {
    "enabled": true,
    "brand": "nalu_motion",
    "template": "nalu-motion-v1",
    "assetPath": "/absolute/path/nalu_motion_endcard.png",
    "start": 178.691,
    "duration": 3,
    "fit": "contain",
    "audioPolicy": "asset",
    "audioPath": "/absolute/path/nalu_motion_chime.wav"
  }
}
```

`start` 若省略会确定性地取正片时间线末端；若显式提供则必须与正片末端完全一致。`fit=cover` 在严格品牌门下禁止，因为可能裁掉品牌像素。`audioPolicy` 支持 `auto`、`silence`、`asset`、`mix`。coverage 固定输出 `outro.present`、`outro.brand`、`outro.duration`、`outro.endsAtTimelineEnd`。

素材路径优先级为：项目 `assetPath` → 环境变量 `AGENTCUT_NALU_MOTION_OUTRO_ASSET` → 已注册的本机标准素材。任何被选中的素材缺失或不可读都会失败，绝不会退化成通用黑场。

迁移旧项目只需：加入 `requireBrandedOutro:true`，将原片尾配置补上 `brand:nalu_motion`、`fit` 和 `audioPolicy`；如果显式填写 `start`，使用 validate coverage 返回的正片结束时间。E19R/E20R 最小项目分别见 [E19R 示例](examples/e19r-branded-outro-minimal.json) 和 [E20R 示例](examples/e20r-branded-outro-minimal.json)。

片尾物理上始终追加，因此不会覆盖最后对白；`includeInTotalDuration` 控制制片核算字段 `accountedDuration`。设为 `false` 时实际文件仍包含片尾，但核算时长保持正片时长。由于默认片尾与正片不重叠，`dialogueDuckDb`/`bgmDuckDb` 作为明确混音策略写入 manifest；一旦未来模板允许音频交叠，必须使用这些值，不能采用隐式默认。

## Clip 原生文字清理

视频 clip 可声明 `cleanupRegions`，清理在缩放到输出画布之后、透明度/转场和 burned captions 之前执行。支持：

- `delogo`：FFmpeg 确定性区域修复，适合压制已有画面文字。
- `mask`：使用 `color` 完全覆盖区域。
- `blur`：只裁切并模糊指定区域，再按原坐标合回画面，不模糊整帧。

时间采用 clip 内相对时间；manifest 同时输出 clip 时间和最终时间线时间。

```json
{
  "source": "/absolute/path/DIA-040.mp4",
  "start": 175.2,
  "in": 0,
  "duration": 3.49,
  "cleanupRegions": [{
    "mode": "delogo",
    "x": 250, "y": 850,
    "width": 230, "height": 110,
    "start": 0,
    "duration": 3.49,
    "allowCaptionSafeBand": false
  }]
}
```

`validate` 会拒绝超出输出画布或 clip 时间的区域。根据启用字幕轨的字号、描边和 bottom margin 计算字幕安全带；cleanup 与该带相交时默认返回 `CLEANUP_CAPTION_SAFE_BAND_OVERLAP`。只有经过明确复核后才能设置 `allowCaptionSafeBand:true`。

源文件不会被修改。render manifest 为每个操作记录源 SHA-256、模式、区域、时间和显式安全带授权；`rollback.sourceFilesModified=false`，回滚方式为移除对应 `cleanupRegions` 后重新渲染。CLI、SDK、render、renderMany 和 NDJSON 使用同一项目合同。完整示例见 [examples/e19r-dia040-cleanup.json](examples/e19r-dia040-cleanup.json)。

## Master Audio Safety

发行项目必须声明 `masterAudioPolicy`。可显式设置 `releaseProject:true`；同时，输出路径包含 `release_candidate`、`final`、`publish`、`distribution` 或“发行”时也自动按发行项目处理，避免生产配置漏标。

从 0.9.18 起，显式 `releaseProject:true` 也是完整发行契约：项目必须同时设置 `requireBurnedSubtitles:true`、非空 `expectedDialogueIds`、`requireBrandedOutro:true`、启用 Nalu Motion 片尾，并设置 `releaseGate.required:true`。该契约在 `compile`、普通/严格 `validate` 和 `render` 前检中一致执行；缺少任一项都会硬失败，并写入 `coverage.releaseProjectContract`，不允许以“后续 QA 会补”为由继续渲染。

从 0.9.19 起，修复素材生成完成后必须在项目 `metadata.replacementBindingPolicy` 中声明目标 clip 与新素材 SHA。AgentCut 会读取磁盘文件重新计算 SHA，并检查 clip 元数据、目标覆盖数量、被淘汰素材 SHA 和旧路径标记。任一不一致都会阻断编译、渲染、成片视觉批准和发行；精确残留清单位于 `coverage.replacementBindings.residualClips`。

```json
{
  "metadata": {
    "replacementBindingPolicy": {
      "enabled": true,
      "expectedTargetCount": 2,
      "targets": [
        {"clipId": "U03-S1-A", "replacementSourceSha256": "<sha256>"},
        {"clipId": "U03-S1-B", "replacementSourceSha256": "<sha256>"}
      ],
      "forbiddenSourceSha256": ["<superseded-sha256>"],
      "forbiddenPathTokens": ["SMOOTH_ROAM", "OVERHEAD_REVEAL"],
      "failureAction": "BLOCK_COMPILE_RENDER_FINAL_VISUAL_RELEASE_AND_UPLOAD"
    }
  }
}
```

```json
{
  "releaseProject": true,
  "masterAudioPolicy": {
    "required": true,
    "limiter": true,
    "truePeakCeilingDbtp": -1,
    "codecHeadroomDb": 0.5,
    "loudnessTargetLufs": -16,
    "loudnessRangeLu": 11,
    "maxClippedSamples": 0
  }
}
```

`validate` 会实际测量每个音频源峰值，将线性 `clip.volume` 转为 dB，并在每个重叠时间区间按最坏情况幅度求和。结果位于 `coverage.audioSafety.projected`，相关 clip 会列出源峰值、volume、增益和单路投影峰值。未配置 master safety 时风险为 error；存在 limiter/loudness policy 时保留 warning，表示母带处理预计会介入，而不是把高增益误报为天然安全。

渲染末端在所有语义音轨、片尾音频和 SFX 混合后执行统一 master：有 loudness target 时使用 FFmpeg `loudnorm` 的 LUFS/TP/LRA 约束；只启用 limiter 时使用对应 dBTP ceiling 的 `alimiter`。AAC 等有损编码会在重建时产生约 0.1–0.3 dB 峰值上浮，因此处理目标使用 `truePeakCeilingDbtp - codecHeadroomDb`，默认 `-1.0 - 0.5 = -1.5 dBTP`。编码后的 postflight 仍严格执行声明的 `-1.0 dBTP`，不会放宽硬门。输出完成后重新解码全片并测量：

- `integratedLoudnessLufs`
- `truePeakDbtp`
- `clippedSampleCount`（解码 PCM 中达到正/负满幅的样本数）
- `decodedSampleCount`

指标写入 render、renderMany、CLI 和 NDJSON manifest 的 `audioSafety.metrics`。发行项目缺 policy、true peak 超限、满幅样本超过预算或响度偏离目标超过 1 LU 时，render 硬失败、删除坏成片，并保留 `<output>.failed-audio-qa.json`。完整示例见 [examples/master-audio-safety.json](examples/master-audio-safety.json)。

## 无黑闪硬切（0.9.4）

AgentCut 会把连续秒时间的 video clip 映射到输出帧率的半开帧区间 `[startFrame, endFrameExclusive)`。边界采用 nearest-frame half-up，源画面不足一个已分配帧区间时复制最后一个有效视频帧；相邻 clip 使用半帧交接保护，后一个 clip 在重叠处拥有最终覆盖权。因此 FFmpeg framesync 不会在非整帧的 hard cut 之间露出黑色合成底板。

这只改变视频边界的取帧方式，`Audio.Dialogue`、`Audio.BGM`、`Audio.SFX` 的 `start/in/duration` 仍按项目声明的精确秒值执行，不做帧量化，也不增加音频 padding。`compile` summary 为每个视频 clip 输出 `visualFrameRange`，便于 QA 将剪辑点映射到准确帧号。迁移说明见 [MIGRATION_0.9.4.md](MIGRATION_0.9.4.md)。

### 0.9.5 cadence 修正

0.9.4 的可见尾帧保持会在接近 0.5 秒静止门槛的素材上把低运动区间延长一帧。0.9.5 禁止 `overlay repeatlast`，并把所有视频 PTS 写成 `整数帧/(fps*TB)` 的精确有理数。每个 clip 仅在可见半开区间之外保留一个 EOF 哨兵帧，让 FFmpeg 在最后有效帧之后才收到 EOF；哨兵不进入输出，不增加项目时长，也不构成尾帧 padding。

发布级黑帧回归固定使用 `blackframe=amount=95:threshold=32`。cadence 回归同时拒绝半秒及以上的非动机低运动连续区和周期重复链。迁移说明见 [MIGRATION_0.9.5.md](MIGRATION_0.9.5.md)。

## 逐镜源准入与 final-SHA 发布门（0.9.8）

对动作镜启用 `sourceAdmissionPolicy` 后，AgentCut 在 validate、compile、render、renderMany 和 NDJSON 前置读取每个 video clip 的真实逐镜 cadence JSON。只看 full-cut cadence 不再足够。

```json
{
  "sourceAdmissionPolicy": {
    "enabled": true,
    "requirePerShotCadence": true,
    "maxActionNearDuplicateRatio": 0.15,
    "requireActionTrajectory": true,
    "singleStillAction": "block"
  },
  "releaseGate": {
    "required": true,
    "fullCutVisualReviewPath": "/absolute/qa/FINAL_FULL_CUT_REVIEW.json"
  },
  "timeline": {
    "videoTracks": [{
      "id": "Video.Main",
      "clips": [{
        "id": "E27-N19-VIDEO",
        "source": "/absolute/candidates/E27-N19.mp4",
        "duration": 6,
        "metadata": {
          "action_required": true,
          "action_trajectory": {
            "windup": "陈迹伸手等待拓片下落",
            "contact": "手掌接住拓片",
            "force": "手腕回收并将时辰签压向残影",
            "result": "拓片、时辰签与残影形成清楚对照"
          },
          "source_reference_mode": "generated_video",
          "cadence_report_path": "/absolute/qa/E27-N19_frame_cadence.json",
          "source_admission": "PASS"
        }
      }]
    }]
  }
}
```

硬门行为：

- cadence `status != PASS`：`BLOCK_AGENTCUT_ASSEMBLY`。
- `action_required=true` 且 `near_duplicate_ratio > 0.15`：`BLOCK_AGENTCUT_ASSEMBLY`。
- cadence 报告中的 `video` 与 clip source 不一致：阻断，防止借用别的镜头报告。
- 动作镜缺少 `windup/contact/force/result` 任一阶段：阻断。
- `source_reference_mode=single_still_only` 与动作镜组合默认阻断；只有项目明确设为 `singleStillAction:"warn"` 才降为告警。

render manifest 的 `sourceAdmission` 保留逐镜判定；`releaseGate.cleanRelease` 默认保持 false。渲染后必须针对当前文件执行：

```sh
agentcut release-validate /absolute/final.mp4 /absolute/full-cut-review.json --project /absolute/project.json
```

review 必须采用 `qingshan.review.report.v2`、`media_kind=video` 和 full-cut/final scope；内部 SHA 必须等于当前 final 的实际 SHA-256，且 `hard_gate_passed=true`。任一条件不满足都返回非零并保持 `cleanRelease=false`。NDJSON 等价方法为 `validateRelease`。

即使全部通过，结果仍固定输出 `automaticPlatformReplacementAllowed=false` 和 `platformMutationAuthorized=false`。`CONDITIONAL_MACHINE_ADMISSION` 只能作为可回滚制作证据，不能触发删除、替换或发布。完整示例见 [examples/source-admission-release-gate.json](examples/source-admission-release-gate.json)，迁移说明见 [MIGRATION_0.9.8.md](MIGRATION_0.9.8.md)。

## 成片级近冻结与同构图硬门（0.9.9）

逐镜 cadence 通过不代表整片没有剪辑层面的停滞。0.9.9 新增 `finalVisualPolicy`：在成片上按默认 2 fps 采样，裁掉底部字幕带，同时计算 pHash、aHash 与相邻采样帧的平均像素运动量。

默认规则：

- 没有可核对白、没有明确叙事动作且未经审计豁免的近冻结持续超过 4 秒：FAIL。
- 同一构图形成超过 2 个有效时间簇：FAIL。
- 30 秒以上成片中，同一构图采样占比超过 6%：FAIL。
- `action_required` 只是生成前的动作承诺，不能给静止成片免责。免责必须来自对白轨语义、`narrative_action_present=true`、`motivated_hold=true`，或带非空理由的 `allowedIntervals`。

独立检查命令：

```sh
tools/run_agentcut.sh final-visual-validate /absolute/final.mp4 \
  --project /absolute/project.json \
  --policy examples/final-visual-gate-policy.json \
  --report /absolute/qa/FINAL_VISUAL_GATE.json
```

退出码 `0` 表示硬门通过，`2` 表示检测到内容失败。报告包含每个时间簇、pHash/aHash 距离、运动量、阈值、相关 Clip/源素材和可回滚建议。启用 `finalVisualPolicy.enabled=true` 或 `required=true` 后，render/renderMany 会在原子发布前检查暂存成片；失败时不覆盖旧输出，并写入 `.failed-visual-qa.json`。NDJSON 等价方法为 `validateFinalVisual`。

未配置该字段的旧项目保持原行为。完整参数见 [examples/final-visual-gate-policy.json](examples/final-visual-gate-policy.json)，迁移说明见 [MIGRATION_0.9.9.md](MIGRATION_0.9.9.md)。

## 不可发行粗剪与显式 HOLD（0.9.10）

0.9.10 不会把 cadence FAIL 改成 PASS。它增加的是一个受 SHA 证据约束的 `NON_RELEASE_ROUGH_ASSEMBLY`：允许制作方在素材尚未全部达标时生成供内部 full-cut review 使用的时间线，但该时间线不能通过 final、release 或平台门。

条件源必须同时绑定：当前候选文件 SHA、原始 QA 文件 SHA、原始 `FAIL` 与 failure codes、置信度、采用理由、回滚点和替换条件。Runtime 还会把原始 review 内的 `media_sha256`、状态及所有 blocking failure 逐项反查；只改条件证据中的摘要不能过门。任一证据缺失、文件 SHA 改变，或 failure code 涉及未获准的身份/剧情/媒体损坏，都会继续返回 `BLOCK_AGENTCUT_ASSEMBLY`。未配置白名单时默认只允许 `video.periodic_duplicate` 与 `audio.long_silence`；显式空数组表示不允许任何例外。

缺镜头使用 `timeline.holdSlots` 显式声明。HOLD 会计入总时长，并只消除对应区间的技术性 `VIDEO_GAP`；它不会被当成叙事覆盖。`releaseBlocking` 必须为 true，且必须写明 `reason` 与 `replacementCondition`。支持 `black` 和 `placeholder` 两种模式，两者都不可发行。

```json
{
  "assemblyMode": "NON_RELEASE_ROUGH_ASSEMBLY",
  "sourceAdmissionPolicy": {
    "enabled": true,
    "allowConditionalCadenceFailForRoughAssembly": true,
    "conditionalAdmissionEvidencePath": "/absolute/qa/E28_CONDITIONAL_ADMISSION.json",
    "allowedConditionalFailureCodes": ["video.periodic_duplicate", "audio.long_silence"]
  },
  "timeline": {
    "holdSlots": [{
      "id": "E28-CW-U09", "start": 107, "duration": 13, "mode": "black",
      "reason": "source intentionally held",
      "replacementCondition": "replace U09 and rerun full QA",
      "releaseBlocking": true
    }]
  }
}
```

`validate`、`validate-media`、`compile`、`render`、`renderMany` 以及对应 NDJSON 方法使用同一前置合约。`release-validate --project ...` 与 `final-visual-validate --project ...` 发现任一条件源或 HOLD 时必定 FAIL，即使成片 SHA 和 full-cut review 本身通过。完整项目与证据格式见 [examples/non-release-rough-assembly.json](examples/non-release-rough-assembly.json) 和 [examples/conditional-admission-evidence.json](examples/conditional-admission-evidence.json)，迁移说明见 [MIGRATION_0.9.10.md](MIGRATION_0.9.10.md)。

## 可执行镜头配方 / 导演元数据（0.9.17）

AgentCut 0.9.17 把导演语言作为版本化数据合约，而不是新增一套 GUI 或把 Remotion 变成主渲染依赖。内置 registry 从 video-shotcraft 的 Apache-2.0 结构和镜头语言中筛选 27 个适合真人/生成式短剧的配方；UI 专用卡、上游预览媒体和音频不进入默认生产 registry。对应 NOTICE 同时位于源码根目录与 wheel 包内。

每个配方包含来源、许可证、戏剧意图、适用范围、前后能量、建议时长、运镜、分阶段 motion arc、主体锚点、动作 setup/contact/result、计划停顿、转场意图、beat 锚点、符号化 SFX cue、风险、QA 合同和回滚。项目通过精确 `recipe_id + version` 引用，并可在项目或 clip 层覆盖非 provenance 字段：

```json
{
  "shotRecipePolicy": {
    "enabled": true,
    "registryId": "agentcut.short_drama.director_recipes",
    "registryVersion": "1.0.0"
  },
  "timeline": {"videoTracks": [{"id": "Video.Main", "clips": [{
    "id": "SHOT-001", "source": "/absolute/shot.mp4",
    "start": 0, "duration": 4,
    "metadata": {"shot_recipe": {
      "recipe_id": "camera.slow_push_in", "version": "1.0.0",
      "override": {"camera_motion": {"intensity": 0.65}}
    }}
  }]}]}
}
```

时间以秒为权威，输出帧按 nearest-half-up 确定性换算，720x1280/24fps 与 1920x1080/30fps 使用同一规则。未知配方、缺版本、非法或越界 motion arc、越界 SFX cue、未逐文件验权的 SFX、以及没有精确帧/理由/批准策略的 intentional black 都会在 validate/compile/render 前失败；Runtime 不会自动编造导演理由。

```sh
agentcut shot-recipe-list
agentcut shot-recipe-repairs project.json \
  --problems examples/shot-recipe-aggregate-problems.json
```

`coverage.shotRecipes`、`directorRenderPlan`、render manifest 与 `<output>.shot-recipes.json` sidecar 都保留完整 materialized metadata 和 registry SHA。聚合 QA 问题会展开到相交的 `clipId + recipe phase + 精确区间`，修复任务固定标记 `platformMutationAuthorized=false`。原有冻结、黑帧、版权、对白覆盖、字幕、音频和不可逆操作硬门不变。完整示例与迁移说明见 [examples/shot-recipe-720x1280-24fps.json](examples/shot-recipe-720x1280-24fps.json) 和 [MIGRATION_0.9.17.md](MIGRATION_0.9.17.md)。
