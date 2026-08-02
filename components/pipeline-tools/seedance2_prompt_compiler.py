#!/usr/bin/env python3
"""Compile the two approved Seedance 2.0 prompt modes from structured JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


MODES = {"storyboard", "continuous_long_take"}
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


def compile_prompt(spec: dict) -> tuple[str, dict]:
    mode = require(spec.get("mode"), "mode is required")
    if mode not in MODES:
        raise ValueError(f"unsupported mode: {mode}")
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
