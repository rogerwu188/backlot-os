#!/usr/bin/env python3
"""Compile the two approved Seedance 2.0 prompt modes from structured JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


MODES = {"storyboard", "continuous_long_take", "multi_keyframe_long_take"}
VISUAL_FIELDS = (
    "duration_seconds", "shot_scale", "lens_intent", "camera_height", "camera_motion",
    "depth_layers", "scale_anchor", "palette", "key_light", "atmosphere",
    "environmental_motion", "material_detail", "still_prompt_contract",
    "video_motion_contract", "negative_constraints",
)


def require(value, message: str):
    if value is None or value == "" or value == []:
        raise ValueError(message)
    return value


def entity_header(entities: list[dict], setting: str) -> str:
    parts = []
    tokens = set()
    for entity in entities:
        token = require(entity.get("token"), "entity token is required")
        if token in tokens:
            raise ValueError(f"duplicate entity token: {token}")
        tokens.add(token)
        name = require(entity.get("name"), f"entity name is required: {token}")
        description = require(entity.get("description"), f"entity description is required: {token}")
        audio_ref = entity.get("audio_ref")
        audio = f"，音色参考 {audio_ref}" if audio_ref else ""
        parts.append(f"{name}[[{token}]]（{description}{audio}）")
    return "；".join(parts) + f"。整体设定：{require(setting, 'setting is required')}"


def compile_shot(shot: dict, index: int) -> str:
    framing = require(shot.get("framing"), f"shot {index} framing is required")
    camera = require(shot.get("camera"), f"shot {index} camera is required")
    action = require(shot.get("action"), f"shot {index} action is required")
    expression = require(shot.get("expression_arc"), f"shot {index} expression_arc is required")
    cut_reason = require(shot.get("cut_reason"), f"shot {index} cut_reason is required")
    line = f"镜头{index}：【{framing}，{camera}】{action}。表情弧：{expression}。"
    dialogue = shot.get("dialogue")
    if dialogue:
        speaker = require(dialogue.get("speaker"), f"shot {index} dialogue speaker is required")
        text = require(dialogue.get("text"), f"shot {index} dialogue text is required")
        line += f" {speaker}清楚说：{{{text}}} 只有{speaker}口型运动。"
    if shot.get("sound"):
        line += f" <{shot['sound']}>"
    line += f" 切因：{cut_reason}。"
    return line


def compile_visual_direction(shot: dict, index: int) -> str:
    for field in VISUAL_FIELDS:
        require(shot.get(field), f"shot {index} {field} is required by visual benchmark contract")
    duration = shot["duration_seconds"]
    if not 4 <= duration <= 15:
        raise ValueError(f"shot {index} duration_seconds must be between 4 and 15")
    depth = shot["depth_layers"]
    if len(depth) < 3:
        raise ValueError(f"shot {index} depth_layers requires foreground, midground and background")
    palette = shot["palette"]
    for role in ("dominant", "contrast", "accent"):
        require(palette.get(role), f"shot {index} palette.{role} is required")
    return (
        f"视觉合约：时长{duration}秒；景别{shot['shot_scale']}；镜头意图{shot['lens_intent']}；"
        f"机位高度{shot['camera_height']}；运镜{shot['camera_motion']}；"
        f"空间层次{' / '.join(depth)}；尺度锚点{shot['scale_anchor']}；"
        f"配色主色{palette['dominant']}、对比色{palette['contrast']}、点睛色{palette['accent']}；"
        f"动机光{shot['key_light']}；空气{shot['atmosphere']}；"
        f"环境运动{' / '.join(shot['environmental_motion'])}；材质{' / '.join(shot['material_detail'])}；"
        f"静帧约束{shot['still_prompt_contract']}；视频运动约束{shot['video_motion_contract']}；"
        f"禁止{' / '.join(shot['negative_constraints'])}。"
    )


def scene_lock_header(scene_lock: dict) -> str:
    fields = {name: require(scene_lock.get(name), f"scene_lock.{name} is required")
              for name in ("location", "time_of_day", "weather", "event")}
    return (
        f"剧本场景硬锁：地点{fields['location']}；时段{fields['time_of_day']}；"
        f"天气{fields['weather']}；事件{fields['event']}。以上四项只读，禁止为了电影感改写。"
    )


def compile_multi_keyframe_long_take(spec: dict) -> tuple[str, dict]:
    """Compile a spatially continuous 15-second Omni shot from ordered keyframes."""
    duration = require(spec.get("duration_seconds"), "duration_seconds is required")
    if duration != 15:
        raise ValueError("multi_keyframe_long_take requires exactly 15 seconds")
    if spec.get("model") != "seedance-2.0-pro":
        raise ValueError("multi_keyframe_long_take requires seedance-2.0-pro")
    if spec.get("resolution") != "1080p":
        raise ValueError("multi_keyframe_long_take requires native 1080p")
    if spec.get("real_time_1x") is not True:
        raise ValueError("multi_keyframe_long_take requires real_time_1x=true")
    camera_policy = require(spec.get("camera_motion_policy"), "camera_motion_policy is required")
    if camera_policy != "MOTIVATED_TRACK_OR_LOCKED_AXIS_NO_SWAY_NO_ORBIT_NO_ROAM":
        raise ValueError("camera_motion_policy must forbid sway, orbit and roam")
    keyframes = require(spec.get("keyframes"), "keyframes are required")
    if not 3 <= len(keyframes) <= 9:
        raise ValueError("multi_keyframe_long_take requires 3 to 9 keyframes")
    times, timeline, compiled_frames = [], [], []
    states = set()
    previous_zone = previous_state = None
    for index, frame in enumerate(keyframes, start=1):
        timestamp = float(require(frame.get("timestamp_seconds"), f"keyframe {index} timestamp_seconds is required"))
        if times and timestamp <= times[-1]:
            raise ValueError(f"keyframe {index} timestamps must be strictly increasing")
        image_path = Path(require(frame.get("image_path"), f"keyframe {index} image_path is required"))
        expected_sha = require(frame.get("image_sha256"), f"keyframe {index} image_sha256 is required")
        if not image_path.is_file():
            raise ValueError(f"keyframe {index} image does not exist: {image_path}")
        actual_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise ValueError(f"keyframe {index} image SHA mismatch")
        state = require(frame.get("state_token"), f"keyframe {index} state_token is required")
        if state in states:
            raise ValueError(f"keyframe {index} repeats action state: {state}")
        states.add(state)
        zone = require(frame.get("location_zone"), f"keyframe {index} location_zone is required")
        blocking = require(frame.get("actor_blocking"), f"keyframe {index} actor_blocking is required")
        event = require(frame.get("action_event"), f"keyframe {index} action_event is required")
        reference_role = require(frame.get("reference_role"), f"keyframe {index} reference_role is required")
        preserve = require(frame.get("preserve_from_previous"), f"keyframe {index} preserve_from_previous is required")
        reject_inheritance = require(frame.get("do_not_inherit"), f"keyframe {index} do_not_inherit is required")
        transition = frame.get("transition_from_previous")
        if previous_zone is not None and zone != previous_zone:
            if not transition or transition.get("kind") != "SAME_APERTURE_CROSSING":
                raise ValueError(f"keyframe {index} changes location without SAME_APERTURE_CROSSING")
            require(transition.get("aperture_id"), f"keyframe {index} crossing aperture_id is required")
            require(transition.get("direction"), f"keyframe {index} crossing direction is required")
        if previous_state is not None:
            if not transition:
                raise ValueError(f"keyframe {index} transition_from_previous is required")
            if transition.get("teleport_allowed") is not False:
                raise ValueError(f"keyframe {index} must explicitly forbid teleport")
            if transition.get("action_reset_allowed") is not False:
                raise ValueError(f"keyframe {index} must explicitly forbid action reset")
        timeline.append(
            f"{timestamp:g}秒到达@图片{index}：该图只负责{reference_role}；{event}；人物站位：{blocking}；"
            f"必须继承{preserve}；不得从该图继承{'、'.join(reject_inheritance)}；"
            f"动作状态从{previous_state or '镜头起始'}连续推进到{state}。"
        )
        compiled_frames.append({
            "reference": f"@图片{index}", "timestamp_seconds": timestamp,
            "image_path": str(image_path), "image_sha256": actual_sha,
            "state_token": state, "location_zone": zone,
            "reference_role": reference_role, "preserve_from_previous": preserve,
            "do_not_inherit": reject_inheritance, "transition_from_previous": transition,
        })
        times.append(timestamp)
        previous_zone, previous_state = zone, state
    if times[0] != 0 or times[-1] != 15:
        raise ValueError("keyframe timeline must start at 0 seconds and end at 15 seconds")
    subject_lock = require(spec.get("subject_and_identity_lock"), "subject_and_identity_lock is required")
    spatial_lock = require(spec.get("spatial_continuity_lock"), "spatial_continuity_lock is required")
    action_axis = require(spec.get("action_axis"), "action_axis is required")
    negative = require(spec.get("negative_constraints"), "negative_constraints are required")
    prompt = (
        f"15秒一镜到底，Seedance 2.0 Pro，原生1080p，实时1倍速。{subject_lock}\n"
        f"动作轴：{action_axis}。空间连续硬锁：{spatial_lock}。\n" + "\n".join(timeline)
        + f"\n镜头只为跟清楚动作因果而移动；禁止无动机摇摆、smooth roam、slow push、orbit、overhead reveal、慢动作、插帧、动作重演、人物瞬移、机位重置、空间跳切。禁止：{' / '.join(negative)}。\n"
    )
    return prompt, {
        "schema": "qingshan.seedance2_multi_keyframe_long_take.v1",
        "mode": "multi_keyframe_long_take", "route": "/api/v1/generation/omni-video",
        "contract": "15s_ordered_multi_keyframe_spatial_continuity", "duration_seconds": 15,
        "model": spec["model"], "resolution": spec["resolution"], "real_time_1x": True,
        "camera_motion_policy": camera_policy, "keyframes": compiled_frames,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "gates": ["ORDERED_KEYFRAME_SHA_BINDING", "REFERENCE_ROLE_AND_INHERITANCE_SCOPE",
                  "NO_REPEATED_ACTION_STATE", "NO_TELEPORT_OR_ACTION_RESET",
                  "SAME_APERTURE_LOCATION_CROSSING", "REAL_TIME_1X",
                  "NO_UNMOTIVATED_CAMERA_MOTION"],
    }


def compile_prompt(spec: dict) -> tuple[str, dict]:
    mode = require(spec.get("mode"), "mode is required")
    if mode not in MODES:
        raise ValueError(f"unsupported mode: {mode}")
    if mode == "multi_keyframe_long_take":
        return compile_multi_keyframe_long_take(spec)
    entities = require(spec.get("entities"), "entities are required")
    shots = require(spec.get("shots"), "shots are required")
    header = entity_header(entities, spec.get("setting"))
    tail = require(spec.get("style_and_negative"), "style_and_negative is required")
    visual_contract = spec.get("visual_benchmark_contract")
    if visual_contract:
        version = require(visual_contract.get("version"), "visual_benchmark_contract.version is required")
        header += "\n" + scene_lock_header(require(spec.get("scene_lock"), "scene_lock is required"))
    else:
        version = None

    if mode == "storyboard":
        if len(shots) < 2:
            raise ValueError("storyboard mode requires at least two intentional shots")
        body = "\n\n".join(
            compile_shot(shot, index)
            + ("\n" + compile_visual_direction(shot, index) if visual_contract else "")
            for index, shot in enumerate(shots, 1)
        )
        route = "/api/v1/generation/omni-video"
        contract = "numbered_shots_are_intentional_montage"
    else:
        if len(shots) != 1:
            raise ValueError("continuous_long_take mode requires exactly one shot")
        if not spec.get("start_frame") or not spec.get("end_frame"):
            raise ValueError("continuous_long_take requires start_frame and end_frame")
        shot = shots[0]
        if shot.get("cut_reason"):
            raise ValueError("continuous_long_take cannot declare a cut_reason")
        framing = require(shot.get("framing"), "continuous shot framing is required")
        camera = require(shot.get("camera"), "continuous shot camera is required")
        action = require(shot.get("action"), "continuous shot action is required")
        expression = require(shot.get("expression_arc"), "continuous shot expression_arc is required")
        body = (
            f"镜头1：【15秒一镜到底，{framing}，{camera}】{action}。"
            f"表情弧：{expression}。全程不得出现切镜、转场、分段镜头编号或机位重置。"
        )
        if visual_contract:
            body += "\n" + compile_visual_direction(shot, 1)
        route = "/api/v1/generation/image-to-video"
        contract = "single_unbroken_shot_first_last_frames"

    prompt = f"{header}\n\n{body}\n\n{tail.strip()}\n"
    manifest = {
        "schema": "qingshan.seedance2_prompt_compilation.v2" if visual_contract else "qingshan.seedance2_prompt_compilation.v1",
        "mode": mode,
        "route": route,
        "contract": contract,
        "shot_count": len(shots),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    if version:
        manifest["visual_benchmark_contract_version"] = version
        manifest["script_state_locked"] = True
    if mode == "continuous_long_take":
        manifest["start_frame"] = spec["start_frame"]
        manifest["end_frame"] = spec["end_frame"]
    return prompt, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    spec = json.loads(Path(args.input).read_text(encoding="utf-8"))
    prompt, manifest = compile_prompt(spec)
    out = Path(args.out)
    receipt = Path(args.manifest)
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    receipt.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
