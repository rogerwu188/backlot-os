from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any

from .errors import ValidationError


def _number(value: Any, path: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{path} must be a number")
    value = float(value)
    if value < minimum:
        raise ValidationError(f"{path} must be >= {minimum}")
    return value


@dataclass(frozen=True)
class Transition:
    type: str = "none"
    duration: float = 0.0

    @classmethod
    def parse(cls, value: Any, path: str) -> "Transition":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValidationError(f"{path} must be an object")
        kind = value.get("type", "none")
        if kind not in {"none", "fade"}:
            raise ValidationError(f"{path}.type must be 'none' or 'fade'")
        duration = _number(value.get("duration", 0), f"{path}.duration")
        return cls(kind, duration)


@dataclass(frozen=True)
class CleanupRegion:
    x: int
    y: int
    width: int
    height: int
    start: float = 0.0
    duration: float | None = None
    mode: str = "delogo"
    color: str = "black"
    blur: int = 12
    allow_caption_safe_band: bool = False

    @classmethod
    def parse(cls, value: Any, path: str, clip_duration: float) -> "CleanupRegion":
        if not isinstance(value, dict):
            raise ValidationError(f"{path} must be an object")
        mode = value.get("mode", "delogo")
        if mode not in {"delogo", "mask", "blur"}:
            raise ValidationError(f"{path}.mode must be delogo, mask, or blur")
        dimensions = []
        for name in ("x", "y", "width", "height"):
            item = value.get(name)
            minimum = 1 if name in {"width", "height"} else 0
            if not isinstance(item, int) or isinstance(item, bool) or item < minimum:
                raise ValidationError(f"{path}.{name} must be an integer >= {minimum}")
            dimensions.append(item)
        start = _number(value.get("start", 0), f"{path}.start")
        duration_value = value.get("duration")
        duration = clip_duration - start if duration_value is None else _number(duration_value, f"{path}.duration", minimum=0.001)
        if start + duration > clip_duration + 1e-6:
            raise ValidationError(f"{path} cleanup time exceeds clip duration")
        blur = value.get("blur", 12)
        if not isinstance(blur, int) or isinstance(blur, bool) or blur < 1:
            raise ValidationError(f"{path}.blur must be an integer >= 1")
        allow = value.get("allowCaptionSafeBand", False)
        if not isinstance(allow, bool):
            raise ValidationError(f"{path}.allowCaptionSafeBand must be a boolean")
        return cls(*dimensions, start, duration, mode, str(value.get("color", "black")), blur, allow)


@dataclass(frozen=True)
class Clip:
    id: str | None
    metadata: dict[str, Any]
    source: str
    start: float
    in_point: float
    duration: float
    volume: float = 1.0
    opacity: float = 1.0
    x: str = "0"
    y: str = "0"
    width: int | None = None
    height: int | None = None
    transition_in: Transition = field(default_factory=Transition)
    transition_out: Transition = field(default_factory=Transition)
    cleanup_regions: tuple[CleanupRegion, ...] = ()

    @classmethod
    def parse(cls, value: Any, path: str, kind: str) -> "Clip":
        if not isinstance(value, dict):
            raise ValidationError(f"{path} must be an object")
        source = value.get("source")
        if not isinstance(source, str) or not source:
            raise ValidationError(f"{path}.source must be a non-empty string")
        start = _number(value.get("start", 0), f"{path}.start")
        in_point = _number(value.get("in", 0), f"{path}.in")
        duration = _number(value.get("duration"), f"{path}.duration", minimum=0.001)
        volume = _number(value.get("volume", 1), f"{path}.volume")
        opacity = _number(value.get("opacity", 1), f"{path}.opacity")
        if opacity > 1:
            raise ValidationError(f"{path}.opacity must be <= 1")
        size = value.get("size") or {}
        if not isinstance(size, dict):
            raise ValidationError(f"{path}.size must be an object")
        width, height = size.get("width"), size.get("height")
        for name, v in (("width", width), ("height", height)):
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v <= 0):
                raise ValidationError(f"{path}.size.{name} must be a positive integer")
        position = value.get("position") or {}
        if not isinstance(position, dict):
            raise ValidationError(f"{path}.position must be an object")
        clip_id = value.get("id")
        if clip_id is not None and (not isinstance(clip_id, str) or not clip_id):
            raise ValidationError(f"{path}.id must be a non-empty string")
        metadata = value.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValidationError(f"{path}.metadata must be an object")
        action_required = metadata.get("action_required")
        if action_required is not None and not isinstance(action_required, bool):
            raise ValidationError(f"{path}.metadata.action_required must be a boolean")
        trajectory = metadata.get("action_trajectory")
        if trajectory is not None:
            if not isinstance(trajectory, dict):
                raise ValidationError(f"{path}.metadata.action_trajectory must be an object")
            unexpected = set(trajectory) - {"windup", "contact", "force", "result"}
            if unexpected:
                raise ValidationError(f"{path}.metadata.action_trajectory has unsupported fields: {', '.join(sorted(unexpected))}")
            for name, item in trajectory.items():
                if not isinstance(item, str) or not item.strip():
                    raise ValidationError(f"{path}.metadata.action_trajectory.{name} must be a non-empty string")
        reference_mode = metadata.get("source_reference_mode")
        allowed_reference_modes = {
            "native_video", "generated_video", "first_last_frames", "multi_image_sequence",
            "single_still_only", "unknown",
        }
        if reference_mode is not None and reference_mode not in allowed_reference_modes:
            raise ValidationError(
                f"{path}.metadata.source_reference_mode must be one of {', '.join(sorted(allowed_reference_modes))}"
            )
        cadence_path = metadata.get("cadence_report_path")
        if cadence_path is not None and (not isinstance(cadence_path, str) or not cadence_path.strip()):
            raise ValidationError(f"{path}.metadata.cadence_report_path must be a non-empty string")
        shot_recipe = metadata.get("shot_recipe")
        if shot_recipe is not None and not isinstance(shot_recipe, dict):
            raise ValidationError(f"{path}.metadata.shot_recipe must be an object")
        if isinstance(shot_recipe, dict):
            for name in ("recipe_id", "version"):
                item = shot_recipe.get(name)
                if item is not None and (not isinstance(item, str) or not item.strip()):
                    raise ValidationError(f"{path}.metadata.shot_recipe.{name} must be a non-empty string")
            override = shot_recipe.get("override", {})
            if not isinstance(override, dict):
                raise ValidationError(f"{path}.metadata.shot_recipe.override must be an object")
        cleanup_raw = value.get("cleanupRegions", [])
        if not isinstance(cleanup_raw, list):
            raise ValidationError(f"{path}.cleanupRegions must be an array")
        if kind != "video" and cleanup_raw:
            raise ValidationError(f"{path}.cleanupRegions is supported only on video clips")
        cleanup = tuple(CleanupRegion.parse(item, f"{path}.cleanupRegions[{i}]", duration) for i, item in enumerate(cleanup_raw))
        return cls(
            id=clip_id, metadata=metadata, source=source, start=start, in_point=in_point, duration=duration,
            volume=volume, opacity=opacity,
            x=str(position.get("x", 0)), y=str(position.get("y", 0)),
            width=width, height=height,
            transition_in=Transition.parse(value.get("transitionIn"), f"{path}.transitionIn"),
            transition_out=Transition.parse(value.get("transitionOut"), f"{path}.transitionOut"),
            cleanup_regions=cleanup,
        )


@dataclass(frozen=True)
class Track:
    id: str
    kind: str
    enabled: bool
    clips: tuple[Clip, ...]


@dataclass(frozen=True)
class CaptionStyle:
    font: str
    size: int = 48
    color: str = "#FFFFFF"
    outline: int = 3
    outline_color: str = "#000000"
    alignment: str = "bottom-center"
    margins: dict[str, int] = field(default_factory=lambda: {"left": 60, "right": 60, "top": 80, "bottom": 120})
    wrap: int = 18

    @classmethod
    def parse(cls, value: Any, path: str, defaults: dict[str, Any] | None = None) -> "CaptionStyle":
        raw = {**(defaults or {}), **(value or {})}
        if not isinstance(value or {}, dict):
            raise ValidationError(f"{path} must be an object")
        font = raw.get("font")
        if not isinstance(font, str) or not font.strip():
            raise ValidationError(f"{path}.font must be a non-empty font family or font file path")
        size = raw.get("size", 48)
        outline = raw.get("outline", 3)
        wrap = raw.get("wrap", 18)
        for name, item, minimum in (("size", size, 1), ("outline", outline, 0), ("wrap", wrap, 1)):
            if not isinstance(item, int) or isinstance(item, bool) or item < minimum:
                raise ValidationError(f"{path}.{name} must be an integer >= {minimum}")
        alignment = raw.get("alignment", "bottom-center")
        allowed = {"top-left", "top-center", "top-right", "middle-left", "center", "middle-right", "bottom-left", "bottom-center", "bottom-right"}
        if alignment not in allowed:
            raise ValidationError(f"{path}.alignment must be one of {', '.join(sorted(allowed))}")
        margins_raw = raw.get("margins", {})
        if isinstance(margins_raw, int) and not isinstance(margins_raw, bool):
            margins_raw = {"left": margins_raw, "right": margins_raw, "top": margins_raw, "bottom": margins_raw}
        if not isinstance(margins_raw, dict):
            raise ValidationError(f"{path}.margins must be an integer or object")
        margins = {"left": 60, "right": 60, "top": 80, "bottom": 120}
        for name in margins:
            item = margins_raw.get(name, margins[name])
            if not isinstance(item, int) or isinstance(item, bool) or item < 0:
                raise ValidationError(f"{path}.margins.{name} must be a non-negative integer")
            margins[name] = item
        color = raw.get("color", "#FFFFFF")
        outline_color = raw.get("outlineColor", "#000000")
        for name, item in (("color", color), ("outlineColor", outline_color)):
            if not isinstance(item, str) or not item:
                raise ValidationError(f"{path}.{name} must be a non-empty FFmpeg color")
        return cls(font.strip(), size, color, outline, outline_color, alignment, margins, wrap)


@dataclass(frozen=True)
class CaptionClip:
    id: str | None
    dialogue_id: str | None
    text: str
    start: float
    duration: float
    style: CaptionStyle
    metadata: dict[str, Any]

    @classmethod
    def parse(cls, value: Any, path: str, track_style: dict[str, Any] | None = None) -> "CaptionClip":
        if not isinstance(value, dict):
            raise ValidationError(f"{path} must be an object")
        text = value.get("text")
        if not isinstance(text, str):
            raise ValidationError(f"{path}.text must be a string")
        metadata = value.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValidationError(f"{path}.metadata must be an object")
        dialogue_id = value.get("dialogue_id", value.get("dialogueId", metadata.get("dialogue_id")))
        if dialogue_id is not None and (not isinstance(dialogue_id, str) or not dialogue_id.strip()):
            raise ValidationError(f"{path}.dialogue_id must be a non-empty string")
        clip_id = value.get("id")
        if clip_id is not None and (not isinstance(clip_id, str) or not clip_id):
            raise ValidationError(f"{path}.id must be a non-empty string")
        style_raw = dict(value.get("style") or {})
        for key in ("font", "size", "color", "outline", "outlineColor", "alignment", "margins", "wrap"):
            if key in value:
                style_raw[key] = value[key]
        return cls(
            clip_id, dialogue_id.strip() if dialogue_id else None, text,
            _number(value.get("start", 0), f"{path}.start"),
            _number(value.get("duration"), f"{path}.duration", minimum=0.001),
            CaptionStyle.parse(style_raw, f"{path}.style", track_style), metadata,
        )


@dataclass(frozen=True)
class SubtitleTrack:
    id: str
    enabled: bool
    clips: tuple[CaptionClip, ...]


@dataclass(frozen=True)
class Output:
    path: str
    width: int = 1920
    height: int = 1080
    fps: int = 30
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    video_bitrate: str | None = None
    audio_bitrate: str = "192k"
    pixel_format: str = "yuv420p"
    threads: int = 0


DEFAULT_NALU_ASSET = os.environ.get("AGENTCUT_NALU_ASSET", "")


@dataclass(frozen=True)
class Outro:
    enabled: bool = False
    template: str = "nalu-motion-v1"
    template_version: str = "1.0"
    brand: str = "nalu_motion"
    asset_path: str = DEFAULT_NALU_ASSET
    start: float | None = None
    duration: float = 3.0
    fit: str = "contain"
    audio_policy: str = "auto"
    transition_in: float = 0.25
    transition_out: float = 0.25
    title_text: str = "青山"
    brand_text: str = "NALU MOTION"
    next_text: str = "敬请期待"
    font: str = "/System/Library/Fonts/STHeiti Medium.ttc"
    audio_path: str | None = None
    sfx_path: str | None = None
    dialogue_duck_db: float = -12.0
    bgm_duck_db: float = -9.0
    safe_area: dict[str, int] = field(default_factory=lambda: {"left": 72, "right": 72, "top": 128, "bottom": 128})
    logo: dict[str, int] = field(default_factory=lambda: {"x": 235, "y": 590, "width": 250, "height": 141})
    include_in_total_duration: bool = True


@dataclass(frozen=True)
class MasterAudioPolicy:
    required: bool = False
    limiter: bool = True
    true_peak_ceiling_dbtp: float = -1.0
    loudness_target_lufs: float | None = -16.0
    loudness_range_lu: float = 11.0
    codec_headroom_db: float = 0.5
    max_clipped_samples: int = 0


@dataclass(frozen=True)
class HoldSlot:
    id: str
    start: float
    duration: float
    mode: str
    reason: str
    replacement_condition: str
    release_blocking: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def end(self) -> float:
        return self.start + self.duration

    @classmethod
    def parse(cls, value: Any, path: str) -> "HoldSlot":
        if not isinstance(value, dict):
            raise ValidationError(f"{path} must be an object")
        slot_id = value.get("id", value.get("unit_id"))
        if not isinstance(slot_id, str) or not slot_id.strip():
            raise ValidationError(f"{path}.id must be a non-empty string")
        mode = str(value.get("mode", value.get("render_behavior", "black"))).lower()
        mode = {"black_background_gap": "black", "black_field": "black"}.get(mode, mode)
        if mode not in {"black", "placeholder"}:
            raise ValidationError(f"{path}.mode must be black or placeholder")
        reason = value.get("reason")
        replacement = value.get("replacementCondition", value.get("replacement_condition"))
        if not isinstance(reason, str) or not reason.strip():
            raise ValidationError(f"{path}.reason must be a non-empty string")
        if not isinstance(replacement, str) or not replacement.strip():
            raise ValidationError(f"{path}.replacementCondition must be a non-empty string")
        blocking = value.get("releaseBlocking", value.get("replacement_required", True))
        if not isinstance(blocking, bool):
            raise ValidationError(f"{path}.releaseBlocking must be a boolean")
        if not blocking:
            raise ValidationError(f"{path}.releaseBlocking must be true for unresolved hold slots")
        metadata = value.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValidationError(f"{path}.metadata must be an object")
        return cls(
            slot_id.strip(), _number(value.get("start"), f"{path}.start"),
            _number(value.get("duration"), f"{path}.duration", minimum=0.001),
            mode, reason.strip(), replacement.strip(), True, metadata,
        )


@dataclass(frozen=True)
class Project:
    version: str
    output: Output
    video_tracks: tuple[Track, ...]
    audio_tracks: tuple[Track, ...]
    subtitle_tracks: tuple[SubtitleTrack, ...]
    background: str = "black"
    require_burned_subtitles: bool = False
    expected_dialogue_ids: tuple[str, ...] = ()
    narrative_policy: dict[str, Any] = field(default_factory=dict)
    runtime_policy: dict[str, Any] = field(default_factory=dict)
    outro: Outro = field(default_factory=Outro)
    release_project: bool = False
    master_audio_policy: MasterAudioPolicy | None = None
    require_branded_outro: bool = False
    require_cut_reason: bool = False
    source_admission_policy: dict[str, Any] = field(default_factory=dict)
    release_gate: dict[str, Any] = field(default_factory=dict)
    final_visual_policy: Any = None
    assembly_mode: str = "STANDARD"
    hold_slots: tuple[HoldSlot, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    qingshan_audit: dict[str, Any] = field(default_factory=dict)
    shot_recipe_policy: dict[str, Any] = field(default_factory=dict)

    @property
    def requires_master_audio_safety(self) -> bool:
        normalized = self.output.path.lower().replace("-", "_").replace(" ", "_")
        release_tokens = ("release_candidate", "final", "publish", "distribution", "发行")
        return self.release_project or any(token in normalized for token in release_tokens)

    @property
    def main_duration(self) -> float:
        clips = [c for t in (*self.video_tracks, *self.audio_tracks) if t.enabled for c in t.clips]
        return max(
            [c.start + c.duration for c in clips] + [slot.end for slot in self.hold_slots],
            default=0,
        )

    @property
    def duration(self) -> float:
        return self.main_duration + (self.outro.duration if self.outro.enabled else 0)

    @classmethod
    def parse(cls, data: Any, *, base_dir: Path | None = None) -> "Project":
        if not isinstance(data, dict):
            raise ValidationError("project must be an object")
        if data.get("version", "1.0") != "1.0":
            raise ValidationError("only project version '1.0' is supported")
        output_data = data.get("output")
        if not isinstance(output_data, dict) or not output_data.get("path"):
            raise ValidationError("output.path must be a non-empty string")
        def positive_int(name: str, default: int) -> int:
            v = output_data.get(name, default)
            if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
                raise ValidationError(f"output.{name} must be a positive integer")
            return v
        output = Output(
            path=output_data["path"], width=positive_int("width", 1920),
            height=positive_int("height", 1080), fps=positive_int("fps", 30),
            video_codec=output_data.get("videoCodec", "libx264"),
            audio_codec=output_data.get("audioCodec", "aac"),
            video_bitrate=output_data.get("videoBitrate"),
            audio_bitrate=output_data.get("audioBitrate", "192k"),
            pixel_format=output_data.get("pixelFormat", "yuv420p"),
            threads=positive_int("threads", 1) if output_data.get("threads", 0) != 0 else 0,
        )
        timeline = data.get("timeline", {})
        if not isinstance(timeline, dict):
            raise ValidationError("timeline must be an object")
        def tracks(key: str, kind: str, limit: int) -> tuple[Track, ...]:
            values = timeline.get(key, [])
            if not isinstance(values, list):
                raise ValidationError(f"timeline.{key} must be an array")
            if len(values) > limit:
                raise ValidationError(f"timeline.{key} supports at most {limit} tracks")
            result = []
            for i, item in enumerate(values):
                p = f"timeline.{key}[{i}]"
                if not isinstance(item, dict):
                    raise ValidationError(f"{p} must be an object")
                raw_clips = item.get("clips", [])
                if not isinstance(raw_clips, list):
                    raise ValidationError(f"{p}.clips must be an array")
                clips = []
                for j, raw in enumerate(raw_clips):
                    clip = Clip.parse(raw, f"{p}.clips[{j}]", kind)
                    if base_dir and not Path(clip.source).is_absolute():
                        clip = Clip(**{**clip.__dict__, "source": str((base_dir / clip.source).resolve())})
                    cadence_path = clip.metadata.get("cadence_report_path")
                    if base_dir and cadence_path and not Path(cadence_path).is_absolute():
                        resolved_metadata = {**clip.metadata, "cadence_report_path": str((base_dir / cadence_path).resolve())}
                        clip = Clip(**{**clip.__dict__, "metadata": resolved_metadata})
                    clips.append(clip)
                result.append(Track(str(item.get("id", f"{kind}{i}")), kind, bool(item.get("enabled", True)), tuple(clips)))
            return tuple(result)
        subtitle_values = timeline.get("subtitleTracks", [])
        if not isinstance(subtitle_values, list):
            raise ValidationError("timeline.subtitleTracks must be an array")
        subtitle_tracks = []
        for i, item in enumerate(subtitle_values):
            p = f"timeline.subtitleTracks[{i}]"
            if not isinstance(item, dict):
                raise ValidationError(f"{p} must be an object")
            raw_clips = item.get("clips", [])
            if not isinstance(raw_clips, list):
                raise ValidationError(f"{p}.clips must be an array")
            style = item.get("style") or {}
            if not isinstance(style, dict):
                raise ValidationError(f"{p}.style must be an object")
            caption_clips = []
            for j, raw in enumerate(raw_clips):
                caption = CaptionClip.parse(raw, f"{p}.clips[{j}]", style)
                font_path = Path(caption.style.font)
                if base_dir and not font_path.is_absolute() and font_path.suffix.lower() in {".ttf", ".otf", ".ttc"}:
                    resolved_style = CaptionStyle(**{**caption.style.__dict__, "font": str((base_dir / font_path).resolve())})
                    caption = CaptionClip(**{**caption.__dict__, "style": resolved_style})
                caption_clips.append(caption)
            subtitle_tracks.append(SubtitleTrack(
                str(item.get("id", f"subtitle{i}")), bool(item.get("enabled", True)), tuple(caption_clips),
            ))
        policy = data.get("subtitlePolicy") or {}
        if not isinstance(policy, dict):
            raise ValidationError("subtitlePolicy must be an object")
        expected = data.get("expectedDialogueIds", policy.get("expectedDialogueIds", []))
        if not isinstance(expected, list) or any(not isinstance(x, str) or not x for x in expected):
            raise ValidationError("expectedDialogueIds must be an array of non-empty strings")
        require_subtitles = data.get("requireBurnedSubtitles", policy.get("requireBurnedSubtitles", False))
        if not isinstance(require_subtitles, bool):
            raise ValidationError("requireBurnedSubtitles must be a boolean")
        narrative = data.get("narrativeGate") or {}
        if not isinstance(narrative, dict):
            raise ValidationError("narrativeGate must be an object")
        for key in ("enabled", "requireMetadata", "rejectDuplicateSemantics", "rejectNoInformation", "requireCutawayRelevance"):
            if key in narrative and not isinstance(narrative[key], bool):
                raise ValidationError(f"narrativeGate.{key} must be a boolean")
        for key in ("maxSemanticRepeats",):
            if key in narrative and (not isinstance(narrative[key], int) or isinstance(narrative[key], bool) or narrative[key] < 1):
                raise ValidationError(f"narrativeGate.{key} must be an integer >= 1")
        for key in ("maxBackgroundBedRatio", "maxBackgroundBedSeconds", "minCutawayRelevance"):
            if key in narrative and (isinstance(narrative[key], bool) or not isinstance(narrative[key], (int, float)) or narrative[key] < 0):
                raise ValidationError(f"narrativeGate.{key} must be a non-negative number")
        if "maxSemanticGroupRatio" in narrative:
            value = narrative["maxSemanticGroupRatio"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1:
                raise ValidationError("narrativeGate.maxSemanticGroupRatio must be a number greater than 0 and at most 1")
        required_shots = narrative.get("requiredShotIds", [])
        if not isinstance(required_shots, list) or any(not isinstance(x, str) or not x for x in required_shots):
            raise ValidationError("narrativeGate.requiredShotIds must be an array of non-empty strings")
        runtime = data.get("runtimePolicy") or {}
        if not isinstance(runtime, dict):
            raise ValidationError("runtimePolicy must be an object")
        if "allowShorter" in runtime and not isinstance(runtime["allowShorter"], bool):
            raise ValidationError("runtimePolicy.allowShorter must be a boolean")
        if "paddingForbidden" in runtime and not isinstance(runtime["paddingForbidden"], bool):
            raise ValidationError("runtimePolicy.paddingForbidden must be a boolean")
        if runtime.get("onCoverageGap", "fail") not in {"fail", "shorten", "request_asset", "placeholder"}:
            raise ValidationError("runtimePolicy.onCoverageGap must be fail, shorten, request_asset, or placeholder")
        outro_raw = data.get("outro") or {}
        if not isinstance(outro_raw, dict):
            raise ValidationError("outro must be an object")
        outro_enabled = outro_raw.get("enabled", False)
        if not isinstance(outro_enabled, bool):
            raise ValidationError("outro.enabled must be a boolean")
        safe = outro_raw.get("safeArea", {"left": 72, "right": 72, "top": 128, "bottom": 128})
        logo = outro_raw.get("logo", {"x": 235, "y": 590, "width": 250, "height": 141})
        if not isinstance(safe, dict) or not isinstance(logo, dict):
            raise ValidationError("outro.safeArea and outro.logo must be objects")
        for container, names, path_name in ((safe, ("left", "right", "top", "bottom"), "safeArea"), (logo, ("x", "y", "width", "height"), "logo")):
            for name in names:
                if not isinstance(container.get(name), int) or isinstance(container.get(name), bool) or container[name] < 0:
                    raise ValidationError(f"outro.{path_name}.{name} must be a non-negative integer")
        configured_start = outro_raw.get("start")
        if configured_start is not None:
            configured_start = _number(configured_start, "outro.start")
        fit = outro_raw.get("fit", "contain")
        if fit not in {"contain", "cover", "stretch"}:
            raise ValidationError("outro.fit must be contain, cover, or stretch")
        audio_policy = outro_raw.get("audioPolicy", "auto")
        if isinstance(audio_policy, dict):
            audio_policy = audio_policy.get("mode", "auto")
        if audio_policy not in {"auto", "silence", "asset", "mix"}:
            raise ValidationError("outro.audioPolicy must be auto, silence, asset, or mix")
        outro = Outro(
            enabled=outro_enabled, template=str(outro_raw.get("template", "nalu-motion-v1")),
            template_version=str(outro_raw.get("templateVersion", "1.0")),
            brand=str(outro_raw.get("brand", outro_raw.get("brandPreset", "nalu_motion"))),
            asset_path=str(outro_raw.get("assetPath") or os.environ.get("AGENTCUT_NALU_MOTION_OUTRO_ASSET") or DEFAULT_NALU_ASSET),
            start=configured_start,
            duration=_number(outro_raw.get("duration", 3.0), "outro.duration", minimum=0.1),
            fit=fit, audio_policy=audio_policy,
            transition_in=_number(outro_raw.get("transitionIn", 0.25), "outro.transitionIn"),
            transition_out=_number(outro_raw.get("transitionOut", 0.25), "outro.transitionOut"),
            title_text=str(outro_raw.get("titleText", "青山")), brand_text=str(outro_raw.get("brandText", "NALU MOTION")),
            next_text=str(outro_raw.get("nextText", "敬请期待")), font=str(outro_raw.get("font", "/System/Library/Fonts/STHeiti Medium.ttc")),
            audio_path=str(outro_raw["audioPath"]) if outro_raw.get("audioPath") else None,
            sfx_path=str(outro_raw["sfxPath"]) if outro_raw.get("sfxPath") else None,
            dialogue_duck_db=float(outro_raw.get("dialogueDuckDb", -12)), bgm_duck_db=float(outro_raw.get("bgmDuckDb", -9)),
            safe_area={k: int(safe[k]) for k in ("left", "right", "top", "bottom")},
            logo={k: int(logo[k]) for k in ("x", "y", "width", "height")},
            include_in_total_duration=bool(outro_raw.get("includeInTotalDuration", True)),
        )
        release_project = data.get("releaseProject", False)
        if not isinstance(release_project, bool):
            raise ValidationError("releaseProject must be a boolean")
        require_branded_outro = data.get("requireBrandedOutro", False)
        if not isinstance(require_branded_outro, bool):
            raise ValidationError("requireBrandedOutro must be a boolean")
        require_cut_reason = data.get("requireCutReason", False)
        if not isinstance(require_cut_reason, bool):
            raise ValidationError("requireCutReason must be a boolean")
        source_policy = data.get("sourceAdmissionPolicy") or {}
        if not isinstance(source_policy, dict):
            raise ValidationError("sourceAdmissionPolicy must be an object")
        for key in ("enabled", "requirePerShotCadence", "requireActionTrajectory"):
            if key in source_policy and not isinstance(source_policy[key], bool):
                raise ValidationError(f"sourceAdmissionPolicy.{key} must be a boolean")
        threshold = source_policy.get("maxActionNearDuplicateRatio", 0.15)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise ValidationError("sourceAdmissionPolicy.maxActionNearDuplicateRatio must be between 0 and 1")
        if source_policy.get("singleStillAction", "block") not in {"block", "warn"}:
            raise ValidationError("sourceAdmissionPolicy.singleStillAction must be block or warn")
        evidence_path = source_policy.get("conditionalAdmissionEvidencePath")
        if evidence_path is not None and (not isinstance(evidence_path, str) or not evidence_path.strip()):
            raise ValidationError("sourceAdmissionPolicy.conditionalAdmissionEvidencePath must be a non-empty string")
        if base_dir and evidence_path and not Path(evidence_path).is_absolute():
            source_policy = {**source_policy, "conditionalAdmissionEvidencePath": str((base_dir / evidence_path).resolve())}
        rough_exception = source_policy.get("roughAssemblyException")
        if rough_exception is not None and (not isinstance(rough_exception, str) or not rough_exception.strip()):
            raise ValidationError("sourceAdmissionPolicy.roughAssemblyException must be a non-empty string")
        for key in ("allowConditionalCadenceFailForRoughAssembly",):
            if key in source_policy and not isinstance(source_policy[key], bool):
                raise ValidationError(f"sourceAdmissionPolicy.{key} must be a boolean")
        allowed_failures = source_policy.get("allowedConditionalFailureCodes", [])
        if not isinstance(allowed_failures, list) or any(not isinstance(x, str) or not x.strip() for x in allowed_failures):
            raise ValidationError("sourceAdmissionPolicy.allowedConditionalFailureCodes must be an array of non-empty strings")
        assembly_mode = data.get("assemblyMode")
        if assembly_mode is None:
            assembly_mode = "NON_RELEASE_ROUGH_ASSEMBLY" if rough_exception else "STANDARD"
        if assembly_mode not in {"STANDARD", "NON_RELEASE_ROUGH_ASSEMBLY"}:
            raise ValidationError("assemblyMode must be STANDARD or NON_RELEASE_ROUGH_ASSEMBLY")
        metadata = data.get("metadata") or {}
        audit = data.get("qingshanAudit") or {}
        if not isinstance(metadata, dict):
            raise ValidationError("metadata must be an object")
        if not isinstance(audit, dict):
            raise ValidationError("qingshanAudit must be an object")
        shot_recipe_policy = data.get("shotRecipePolicy") or {}
        if not isinstance(shot_recipe_policy, dict):
            raise ValidationError("shotRecipePolicy must be an object")
        if "enabled" in shot_recipe_policy and not isinstance(shot_recipe_policy["enabled"], bool):
            raise ValidationError("shotRecipePolicy.enabled must be a boolean")
        for name in ("registryId", "registryVersion"):
            if name in shot_recipe_policy and (not isinstance(shot_recipe_policy[name], str) or not shot_recipe_policy[name].strip()):
                raise ValidationError(f"shotRecipePolicy.{name} must be a non-empty string")
        if "projectOverrides" in shot_recipe_policy and not isinstance(shot_recipe_policy["projectOverrides"], dict):
            raise ValidationError("shotRecipePolicy.projectOverrides must be an object")
        hold_values = timeline.get("holdSlots", [])
        if not isinstance(hold_values, list):
            raise ValidationError("timeline.holdSlots must be an array")
        hold_slots = tuple(HoldSlot.parse(item, f"timeline.holdSlots[{i}]") for i, item in enumerate(hold_values))
        # Compatibility for the first CL2X-517 builder: its hold was already
        # explicit and auditable, but lived under qingshanAudit.placeholder.
        if not hold_slots and assembly_mode == "NON_RELEASE_ROUGH_ASSEMBLY" and isinstance(audit.get("placeholder"), dict):
            legacy = dict(audit["placeholder"])
            legacy["id"] = legacy.get("id", legacy.get("unit_id"))
            legacy["replacementCondition"] = legacy.get("replacementCondition") or audit.get("releaseBlock")
            hold_slots = (HoldSlot.parse(legacy, "qingshanAudit.placeholder"),)
        release_gate = data.get("releaseGate") or {}
        if not isinstance(release_gate, dict):
            raise ValidationError("releaseGate must be an object")
        if "required" in release_gate and not isinstance(release_gate["required"], bool):
            raise ValidationError("releaseGate.required must be a boolean")
        review_path = release_gate.get("fullCutVisualReviewPath")
        if review_path is not None and (not isinstance(review_path, str) or not review_path.strip()):
            raise ValidationError("releaseGate.fullCutVisualReviewPath must be a non-empty string")
        if base_dir and review_path and not Path(review_path).is_absolute():
            release_gate = {**release_gate, "fullCutVisualReviewPath": str((base_dir / review_path).resolve())}
        # Local import avoids a model/analyzer import cycle while keeping the
        # policy contract reusable by CLI, SDK, NDJSON, and post-render gates.
        from .final_visual import FinalVisualPolicy
        final_visual_policy = FinalVisualPolicy.parse(data.get("finalVisualPolicy"), base_dir=base_dir)
        master_raw = data.get("masterAudioPolicy")
        master = None
        if master_raw is not None:
            if not isinstance(master_raw, dict):
                raise ValidationError("masterAudioPolicy must be an object")
            required = master_raw.get("required", False)
            limiter = master_raw.get("limiter", True)
            if not isinstance(required, bool) or not isinstance(limiter, bool):
                raise ValidationError("masterAudioPolicy.required and limiter must be booleans")
            ceiling = master_raw.get("truePeakCeilingDbtp", -1.0)
            target = master_raw.get("loudnessTargetLufs", -16.0)
            lra = master_raw.get("loudnessRangeLu", 11.0)
            headroom = master_raw.get("codecHeadroomDb", 0.5)
            clipped = master_raw.get("maxClippedSamples", 0)
            for name, value in (("truePeakCeilingDbtp", ceiling), ("loudnessRangeLu", lra), ("codecHeadroomDb", headroom)):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValidationError(f"masterAudioPolicy.{name} must be a number")
            if target is not None and (isinstance(target, bool) or not isinstance(target, (int, float))):
                raise ValidationError("masterAudioPolicy.loudnessTargetLufs must be a number or null")
            if not isinstance(clipped, int) or isinstance(clipped, bool) or clipped < 0:
                raise ValidationError("masterAudioPolicy.maxClippedSamples must be an integer >= 0")
            if ceiling > 0 or ceiling < -20:
                raise ValidationError("masterAudioPolicy.truePeakCeilingDbtp must be between -20 and 0")
            if headroom < 0 or headroom > 6:
                raise ValidationError("masterAudioPolicy.codecHeadroomDb must be between 0 and 6")
            master = MasterAudioPolicy(required, limiter, float(ceiling), float(target) if target is not None else None, float(lra), float(headroom), clipped)
        project = cls(
            "1.0", output, tracks("videoTracks", "video", 2), tracks("audioTracks", "audio", 3),
            tuple(subtitle_tracks), str(data.get("background", "black")), require_subtitles, tuple(expected), narrative, runtime, outro,
            release_project, master,
            require_branded_outro,
            require_cut_reason,
            source_policy,
            release_gate,
            final_visual_policy,
            assembly_mode,
            hold_slots,
            metadata,
            audit,
            shot_recipe_policy,
        )
        if project.duration <= 0:
            raise ValidationError("timeline must contain at least one enabled clip")
        return project
