#!/usr/bin/env python3
"""Compile the two approved Seedance 2.0 prompt modes from structured JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

try:
    from .local_lora_memory_sync import auto_sync
except ImportError:  # Direct script execution from components/pipeline-tools.
    from local_lora_memory_sync import auto_sync


MODES = {"storyboard", "continuous_long_take", "multi_keyframe_long_take"}
DIALOGUE_MODES = {"ON_CAMERA_NATIVE_LIP_SYNC", "CLOSED_MOUTH_VOICE_OVER", "NO_DIALOGUE"}


def default_local_lora_memory() -> Path:
    """Resolve one portable compiler source to its actual deployed memory."""
    explicit = os.environ.get("BACKLOTOS_LOCAL_LORA_MEMORY", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    module = Path(__file__).resolve()
    production_memory = module.parents[1] / "workflow/local_lora/seedance2_prompt_failure_training.jsonl"
    if production_memory.parent.is_dir():
        return production_memory
    return module.parent / "local_lora/seedance2_prompt_failure_training.jsonl"


DEFAULT_LOCAL_LORA_MEMORY = default_local_lora_memory()
STATIC_ACTOR_MOTION_TERMS = (
    "静止", "完全不动", "纹丝不动", "定格", "保持姿势", "保持原位",
    "仍在原区", "尚未启动", "留在安全区", "留在后方", "frozen", "freeze", "motionless",
)
VISUAL_FIELDS = (
    "duration_seconds", "shot_scale", "lens_intent", "camera_height", "camera_motion",
    "depth_layers", "scale_anchor", "palette", "key_light", "atmosphere",
    "environmental_motion", "material_detail", "still_prompt_contract",
    "video_motion_contract", "negative_constraints",
)
SILENT_PERFORMANCE_MARKERS = (
    "全程不开口", "全程闭口", "无人开口", "不生成语音", "无口型台词",
    "独立音频后置", "后配音", "closed-mouth", "no lip sync", "silent performance",
)

CHARACTER_SIMILARITY_LIMITS = {"face": 0.72, "wardrobe": 0.65, "voice": 0.80}
EXPRESSIVE_DIALOGUE_FIELDS = (
    "psychological_state", "emotion", "emotion_intensity", "pace", "pause_map",
    "emphasis_words", "volume_arc", "breath_pattern", "delivery_transition", "body_sync",
)

# Action-camera vocabulary is selected by dramatic function, never sampled as
# decorative motion. Short accents stay short so the action remains readable.
ACTION_CAMERA_TECHNIQUES = {
    "tracking_follow": ("空间跟随", "持续位移、追逐或绕障", "moving", 3.0),
    "arc_orientation": ("弧线定向", "交代双方站位与空间关系", "moving", 2.0),
    "crash_push": ("急速推进", "唯一一次逼近决定性接触", "accent", 0.8),
    "crash_pull": ("急速拉开", "接触后揭示受力结果与环境", "accent", 0.8),
    "low_angle_dolly": ("低机位移动", "强调步法、腾跃起点或压迫感", "moving", 2.0),
    "overhead_crane": ("高位俯拍", "交代多人包围、路线或地形", "moving", 2.0),
    "micro_slow_follow": ("短促慢速强调", "仅强调唯一决定性接触", "accent", 0.6),
    "impact_shake": ("冲击震动", "仅在真实接触瞬间表现冲量", "accent", 0.35),
    "whip_pan_cut": ("甩镜切换", "动作方向匹配的镜间交接", "edit", 0.4),
    "detail_triple_cut": ("三段特写", "起势、接触、结果三个信息点", "edit", 2.4),
    "crane_rise": ("升降揭示", "从局部结果升起交代全局", "moving", 2.0),
    "obstacle_pass": ("穿绕遮挡", "沿真实门柱、人群或障碍维持空间连续", "moving", 2.5),
    "shot_reverse_exchange": ("正反交替", "明确攻守交换与视线轴", "edit", 2.5),
    "bounded_rotation": ("有限旋转", "围绕固定接触点读取一次攻防转换", "moving", 1.5),
    "locked_impact": ("定格机位", "让动作和受力在稳定构图内自行发生", "stable", 3.0),
}
ACTION_CAMERA_EDIT_ONLY = {"whip_pan_cut", "detail_triple_cut", "shot_reverse_exchange"}
ACTION_CAMERA_DYNAMIC_FAMILIES = {"moving", "accent"}

# Licensed Scene 69 prompt-rule adapter. These are causal shot-organization
# methods, not model weights and not decorative camera presets.
COMBAT_CONTINUITY_METHODS = {
    "causal_impact_aftermath_ladder": {
        "label": "冲击后果阶梯", "min_beats": 3,
        "required_evidence": {"contact", "environment", "recovery", "relational_close"},
        "measurement_required": True,
    },
    "occlusion_breach_threat_reveal": {
        "label": "遮挡破局威胁揭示", "min_beats": 2,
        "required_evidence": {"formation", "breach", "diagnostic_detail", "relational_close"},
        "measurement_required": True,
    },
    "timed_emotional_reaction_microsequence": {
        "label": "定时情绪反应微序列", "min_beats": 2,
        "required_evidence": {"stimulus", "objective_evidence", "performance_transition", "relational_close"},
        "measurement_required": False,
    },
    "damage_accumulation_state_promotion": {
        "label": "伤势累积状态晋升", "min_beats": 2,
        "required_evidence": {"inherited_damage", "contact", "diagnostic_detail", "cumulative_result"},
        "measurement_required": False, "state_promotion_required": True,
    },
    "reversible_crowd_geometry_ceremonial_entrance": {
        "label": "可逆人群几何入场", "min_beats": 2,
        "required_evidence": {"formation", "breach", "crowd_reaction", "formation_restore", "relational_close"},
        "measurement_required": True,
    },
    "prop_geometric_anchor_momentum_recovery": {
        "label": "道具几何锚点减速", "min_beats": 2,
        "required_evidence": {"grip_change", "prop_contact", "deceleration_path", "recovery", "relational_close"},
        "measurement_required": True,
    },
    "reciprocal_charge_convergence_ladder": {
        "label": "双向冲锋收敛阶梯", "min_beats": 2,
        "required_evidence": {"start_positions", "acceleration", "shared_distance", "weapon_promotion", "relational_close"},
        "measurement_required": True,
    },
    "asymmetric_locked_clash_sustained_force": {
        "label": "非对称锁定对抗持续受力", "min_beats": 2,
        "required_evidence": {"contact", "displacement", "stance_degradation", "mechanical_strain", "relational_close"},
        "measurement_required": True,
    },
    "defense_rhythm_failure_combo_ladder": {
        "label": "防守节奏失效连击阶梯", "min_beats": 3,
        "required_evidence": {"successful_defense", "interval_compression", "failed_defense", "damage", "relational_close"},
        "measurement_required": True,
    },
    "embodied_topology_traversal_damage_combo": {
        "label": "实体拓扑穿越累积打击", "min_beats": 3,
        "required_evidence": {
            "topology_anchor", "foothold_sequence", "traversal_path", "distinct_contacts",
            "landing_relation", "cumulative_result", "relational_close",
        },
        "measurement_required": True,
    },
    "committed_miss_entrapment_counter_window": {
        "label": "承诺落空卡陷反击窗口", "min_beats": 3,
        "required_evidence": {
            "attack_commitment", "evasion_clearance", "obstacle_entrapment",
            "extraction_delay", "counterlaunch", "relational_close",
        },
        "measurement_required": True, "state_promotion_required": True,
    },
    "force_conversion_controlled_recovery_ladder": {
        "label": "受力转化受控恢复阶梯", "min_beats": 3,
        "required_evidence": {
            "defensive_contact", "force_transfer", "controlled_rotation",
            "carried_prop_continuity", "landing_absorption", "stance_recovery",
            "relational_close",
        },
        "measurement_required": True,
    },
    "follow_through_exposure_penetration_extraction_ladder": {
        "label": "收势暴露刺入拔出阶梯", "min_beats": 3,
        "required_evidence": {
            "opponent_follow_through", "exposed_target_zone", "gap_closure",
            "targeted_penetration_contact", "embedded_reaction",
            "extraction_consequence", "cumulative_damage_state",
            "relational_close",
        },
        "measurement_required": True, "state_promotion_required": True,
    },
    "near_miss_armor_interception_recovery_ladder": {
        "label": "近失装甲截击恢复阶梯", "min_beats": 3,
        "required_evidence": {
            "attack_commitment", "last_moment_evasion_clearance",
            "armor_glancing_contact", "body_protection_state",
            "fragment_consequence", "attacker_followthrough_imbalance",
            "defender_stance_recovery", "relational_close",
        },
        "measurement_required": True, "state_promotion_required": True,
    },
    "low_profile_evasion_limb_failure_counterlaunch_recovery_ladder": {
        "label": "低姿闪避肢体失效反发恢复阶梯", "min_beats": 3,
        "required_evidence": {
            "attack_commitment", "low_profile_evasion_clearance",
            "targeted_limb_contact", "support_failure",
            "counterlaunch_contact", "airborne_displacement",
            "carried_prop_continuity", "landing_absorption",
            "landing_recovery_state", "crowd_reaction", "relational_close",
        },
        "measurement_required": True, "state_promotion_required": True,
    },
}
COMBAT_EVIDENCE_TYPES = set().union(
    *(row["required_evidence"] for row in COMBAT_CONTINUITY_METHODS.values())
)
COMBAT_MEASUREMENT_KINDS = {"distance", "displacement", "clearance", "gap", "timing_interval", "angle"}
COMBAT_MEASUREMENT_UNITS = {"m", "cm", "s", "degrees", "body_lengths"}
CROSS_CUT_CONTINUITY_CLASSES = {
    "character_state", "prop_state", "spatial_relation", "environment_state",
}
SHOT_INFORMATION_TYPES = {
    "orientation", "threat", "action_setup", "contact_detail",
    "consequence", "reaction", "resolution",
}
SPATIAL_SCREEN_REGIONS = {"screen_left", "screen_center", "screen_right", "full_frame"}
SPATIAL_BACKGROUND_REGIONS = {
    "left_depth", "center_depth", "right_depth", "full_background",
}
SPATIAL_GAZE_DIRECTIONS = {"screen_left", "screen_right", "camera", "up", "down", "none"}
SPATIAL_AXIS_TRANSITIONS = {"ESTABLISH_AXIS", "HOLD_AXIS", "DECLARED_AXIS_CROSS"}
OFFSCREEN_RELATIONSHIP_POLICY = "EXPLICIT_TARGET_VISIBILITY_EVIDENCE_AND_REENTRY"
OFFSCREEN_VISIBILITY_STATES = {"ON_SCREEN", "OFF_SCREEN"}
OFFSCREEN_SIDES = {"screen_left", "screen_right", "behind_camera", "ahead_of_camera"}
OFFSCREEN_REVEAL_POLICIES = {"STAY_OFFSCREEN", "REENTER_ON_TRIGGER", "VISIBLE_HOLD"}
OFFSCREEN_EVIDENCE_TYPES = {
    "EYELINE", "DIEGETIC_AUDIO", "CONTACT_TRACE", "SHADOW_OR_REFLECTION",
    "VISIBLE_FRAME_PRESENCE",
}
CAMERA_ACTION_COUPLING_POLICY = "SUBJECT_TRIGGER_CAMERA_RESPONSE_THEN_RESULT_HOLD"
CAMERA_ACTION_COUPLING_TYPES = {"LOCKED_HOLD", "SUBJECT_TRIGGERED_MOVE"}
CAMERA_ACTION_RESPONSE_TYPES = {
    "LOCKED_FRAME", "HANDHELD_BREATHING", "PAN", "TILT", "TRACK", "DOLLY",
    "CRANE", "HANDHELD_FOLLOW", "RACK_FOCUS", "BOUNDED_ORBIT",
}
SHOT_BOUNDARY_STATE_POLICY = "FIRST_FRAME_PROVES_ENTRY_FINAL_FRAME_PROVES_EXIT"
SHOT_BOUNDARY_ENTRY_POLICY = "ALREADY_ESTABLISHED_NO_REPLAY"
SHOT_BOUNDARY_RESET_POLICY = "NO_UNDECLARED_REPLAY_OR_RESET_AT_CUT"
DEPTH_FOCUS_POLICY = "SUBJECT_TRIGGERED_FOCUS_TRANSFER_WITH_PLANE_LOCK_AND_RESULT_HOLD"
DEPTH_FOCUS_MODES = {"LOCKED_FOCUS", "SUBJECT_TRIGGERED_RACK_FOCUS"}
DEPTH_FOCUS_PLANES = {"FOREGROUND", "MIDGROUND", "BACKGROUND"}
CONTACT_FORCE_STATE_POLICY = "CONTACT_OWNERSHIP_FORCE_AND_RESULT_PERSIST_ACROSS_CUTS"
CONTACT_FORCE_STATE_MODES = {"LOCKED_CONTACT", "TRIGGERED_CONTACT_CHANGE"}
CAMERA_STYLE_PROFILES = {
    "AMERICAN_HOLLYWOOD": {
        "label_zh": "美式好莱坞",
        "cultural_tradition": "AMERICAN_HOLLYWOOD",
        "provenance": "HELL_GRIND_LICENSED_PRODUCTION_METHODOLOGY",
        "deployment_status": "ADAPTED",
        "adapter_lineage": [
            "HELL_GRIND_COMBAT_CONTINUITY_PROMPT_RULE_ADAPTER_V7",
            "HELL_GRIND_CROSS_CUT_STATE_LEDGER_PROMPT_RULE_ADAPTER_V8",
            "HELL_GRIND_SHOT_INFORMATION_LADDER_PROMPT_RULE_ADAPTER_V9",
            "HELL_GRIND_SPATIAL_AXIS_PROMPT_RULE_ADAPTER_V10",
            "HELL_GRIND_CAMERA_ACTION_COUPLING_PROMPT_RULE_ADAPTER_V11",
            "HELL_GRIND_OFFSCREEN_RELATIONSHIP_PROMPT_RULE_ADAPTER_V12",
            "HELL_GRIND_SHOT_BOUNDARY_STATE_PROMPT_RULE_ADAPTER_V13",
            "HELL_GRIND_DEPTH_FOCUS_TRANSFER_PROMPT_RULE_ADAPTER_V14",
            "HELL_GRIND_CONTACT_FORCE_STATE_PROMPT_RULE_ADAPTER_V15",
        ],
    },
    # Reserved identifiers make the selection boundary explicit without claiming
    # that these traditions have already been learned or cleared for production.
    "EASTERN_WUXIA": {
        "label_zh": "东方武侠",
        "cultural_tradition": "EASTERN_WUXIA",
        "provenance": None,
        "deployment_status": "RESERVED_NOT_ADAPTED",
        "adapter_lineage": [],
    },
    "EASTERN_KUNGFU": {
        "label_zh": "东方功夫",
        "cultural_tradition": "EASTERN_KUNGFU",
        "provenance": None,
        "deployment_status": "RESERVED_NOT_ADAPTED",
        "adapter_lineage": [],
    },
}


def compile_camera_style_plan(
    contract: dict, segments: list[dict]
) -> tuple[str, dict]:
    """Label camera grammar per shot and keep cultural styles selectable."""
    plan = contract.get("camera_style_plan")
    if not plan:
        plan = {
            "selection_policy": "PER_SHOT_GENRE_AWARE",
            "shots": [
                {
                    "shot_index": row["shot_index"],
                    "style_profile_id": "AMERICAN_HOLLYWOOD",
                    "selection_reason": "当前运镜规则来自已许可 Hell Grind 方法学",
                }
                for row in segments
            ],
        }
    if plan.get("selection_policy") != "PER_SHOT_GENRE_AWARE":
        raise ValueError(
            "camera_style_plan selection_policy must be PER_SHOT_GENRE_AWARE"
        )
    rows = require(plan.get("shots"), "camera_style_plan shots are required")
    if not isinstance(rows, list) or len(rows) != len(segments):
        raise ValueError("camera_style_plan must exactly cover all compiled shots")

    compiled = []
    for index, (row, segment) in enumerate(zip(rows, segments), start=1):
        shot_index = int(require(
            row.get("shot_index"), f"camera style row {index} shot_index is required"
        ))
        if shot_index != index or shot_index != segment["shot_index"]:
            raise ValueError("camera_style_plan shot_index must match compiled shot order")
        profile_id = require(
            row.get("style_profile_id"),
            f"camera style row {index} style_profile_id is required",
        )
        profile = CAMERA_STYLE_PROFILES.get(profile_id)
        if not profile:
            raise ValueError(f"unknown camera style profile: {profile_id}")
        if profile["deployment_status"] != "ADAPTED":
            raise ValueError(f"camera style profile is not adapted for production: {profile_id}")
        reason = require(
            row.get("selection_reason"),
            f"camera style row {index} selection_reason is required",
        )
        compiled.append({
            "shot_index": shot_index,
            "style_profile_id": profile_id,
            "style_label_zh": profile["label_zh"],
            "cultural_tradition": profile["cultural_tradition"],
            "selection_reason": reason,
            "provenance": profile["provenance"],
            "adapter_lineage": profile["adapter_lineage"],
        })

    prompt_rows = [
        f"镜头{row['shot_index']}：运镜风格={row['style_label_zh']}"
        f"[{row['style_profile_id']}]；选择依据={row['selection_reason']}"
        for row in compiled
    ]
    return (
        "\n【CAMERA STYLE PROFILE｜运镜文化风格标签】" + "。".join(prompt_rows) + "。",
        {
            "version": "1.0.0",
            "adapter": "TASK2_1_CULTURAL_CAMERA_STYLE_ROUTER_V1",
            "selection_policy": "PER_SHOT_GENRE_AWARE",
            "shots": compiled,
            "full_shot_coverage": True,
            "available_profiles": sorted({row["style_profile_id"] for row in compiled}),
            "reserved_not_adapted_profiles": [
                profile_id for profile_id, profile in CAMERA_STYLE_PROFILES.items()
                if profile["deployment_status"] != "ADAPTED"
            ],
        },
    )


def compile_spatial_axis_ledger(
    contract: dict, segments: list[dict], descriptor_ids: set[str]
) -> tuple[str, dict | None]:
    """Make screen direction, eyelines, and background geography explicit per cut."""
    ledger = contract.get("spatial_axis_ledger")
    if not ledger:
        return "", None
    if ledger.get("coverage_policy") != "PRESERVE_SCREEN_DIRECTION_EYELINE_AND_BACKGROUND":
        raise ValueError(
            "spatial_axis_ledger coverage_policy must be "
            "PRESERVE_SCREEN_DIRECTION_EYELINE_AND_BACKGROUND"
        )
    rows = require(ledger.get("shots"), "spatial_axis_ledger shots are required")
    if not isinstance(rows, list) or len(rows) != len(segments):
        raise ValueError("spatial_axis_ledger must exactly cover all compiled shots")

    compiled, axis_sides = [], {}
    for index, (row, segment) in enumerate(zip(rows, segments), start=1):
        shot_index = int(require(
            row.get("shot_index"), f"spatial axis row {index} shot_index is required"
        ))
        if shot_index != index:
            raise ValueError("spatial_axis_ledger shot_index must match compiled shot order")
        axis_id = require(row.get("axis_id"), f"spatial axis row {index} axis_id is required")
        axis_side = require(
            row.get("axis_side"), f"spatial axis row {index} axis_side is required"
        )
        transition = require(
            row.get("axis_transition"),
            f"spatial axis row {index} axis_transition is required",
        )
        if transition not in SPATIAL_AXIS_TRANSITIONS:
            raise ValueError(f"unsupported spatial axis transition: {transition}")
        previous_side = axis_sides.get(axis_id)
        if previous_side is None:
            if transition != "ESTABLISH_AXIS":
                raise ValueError(f"spatial axis {axis_id} must start with ESTABLISH_AXIS")
        elif previous_side == axis_side:
            if transition != "HOLD_AXIS":
                raise ValueError(f"spatial axis {axis_id} unchanged side must use HOLD_AXIS")
        elif transition != "DECLARED_AXIS_CROSS":
            raise ValueError(f"undeclared axis cross for spatial axis {axis_id}")
        axis_sides[axis_id] = axis_side

        subject_id = require(
            row.get("subject_descriptor_id"),
            f"spatial axis row {index} subject_descriptor_id is required",
        )
        eyeline_target_id = require(
            row.get("eyeline_target_descriptor_id"),
            f"spatial axis row {index} eyeline_target_descriptor_id is required",
        )
        background_id = require(
            row.get("background_anchor_descriptor_id"),
            f"spatial axis row {index} background_anchor_descriptor_id is required",
        )
        for field, descriptor_id in (
            ("subject_descriptor_id", subject_id),
            ("eyeline_target_descriptor_id", eyeline_target_id),
            ("background_anchor_descriptor_id", background_id),
        ):
            if descriptor_id not in descriptor_ids:
                raise ValueError(
                    f"spatial axis row {index} {field} references unknown descriptor"
                )
        subject_region = require(
            row.get("subject_screen_region"),
            f"spatial axis row {index} subject_screen_region is required",
        )
        if subject_region not in SPATIAL_SCREEN_REGIONS:
            raise ValueError(f"unsupported subject screen region: {subject_region}")
        background_region = require(
            row.get("background_screen_region"),
            f"spatial axis row {index} background_screen_region is required",
        )
        if background_region not in SPATIAL_BACKGROUND_REGIONS:
            raise ValueError(f"unsupported background screen region: {background_region}")
        gaze_direction = require(
            row.get("gaze_direction"),
            f"spatial axis row {index} gaze_direction is required",
        )
        if gaze_direction not in SPATIAL_GAZE_DIRECTIONS:
            raise ValueError(f"unsupported gaze direction: {gaze_direction}")
        camera_side = require(
            row.get("camera_side"), f"spatial axis row {index} camera_side is required"
        )
        axis_relation = require(
            row.get("axis_relation"),
            f"spatial axis row {index} axis_relation is required",
        )
        if camera_side != segment["geometry"]["camera_side"]:
            raise ValueError(f"spatial axis row {index} camera_side must match cinematic segment")
        if axis_relation != segment["geometry"]["axis_relation"]:
            raise ValueError(f"spatial axis row {index} axis_relation must match cinematic segment")
        entry_state = require(
            row.get("entry_state"), f"spatial axis row {index} entry_state is required"
        )
        exit_state = require(
            row.get("exit_state"), f"spatial axis row {index} exit_state is required"
        )
        if entry_state != segment["entry_state"] or exit_state != segment["exit_state"]:
            raise ValueError(
                f"spatial axis row {index} entry/exit state must match cinematic segment"
            )
        compiled.append({
            "shot_index": shot_index,
            "axis_id": axis_id,
            "axis_side": axis_side,
            "axis_transition": transition,
            "subject_descriptor_id": subject_id,
            "subject_screen_region": subject_region,
            "gaze_direction": gaze_direction,
            "eyeline_target_descriptor_id": eyeline_target_id,
            "background_anchor_descriptor_id": background_id,
            "background_screen_region": background_region,
            "camera_side": camera_side,
            "axis_relation": axis_relation,
            "entry_state": entry_state,
            "exit_state": exit_state,
        })

    prompt_rows = [
        f"镜头{row['shot_index']}[{row['axis_id']}/{row['axis_transition']}]："
        f"轴侧={row['axis_side']}；主体={row['subject_descriptor_id']}@{row['subject_screen_region']}；"
        f"视线={row['gaze_direction']}→{row['eyeline_target_descriptor_id']}；"
        f"背景={row['background_anchor_descriptor_id']}@{row['background_screen_region']}；"
        f"机位侧={row['camera_side']}，轴线={row['axis_relation']}；"
        f"入口={row['entry_state']}，出口={row['exit_state']}"
        for row in compiled
    ]
    return (
        "\n【SPATIAL AXIS LEDGER｜屏幕方位、视线与背景锚点】" + "。".join(prompt_rows) + "。"
        "所有切镜必须保持已声明的屏幕方向、视线目标和背景地理；只有 DECLARED_AXIS_CROSS 可以改变轴侧。",
        {
            "version": "1.0.0",
            "coverage_policy": "PRESERVE_SCREEN_DIRECTION_EYELINE_AND_BACKGROUND",
            "shots": compiled,
            "full_shot_coverage": True,
            "adapter": "HELL_GRIND_SPATIAL_AXIS_PROMPT_RULE_ADAPTER_V10",
        },
    )


def compile_offscreen_relationship_ledger(
    contract: dict,
    segments: list[dict],
    descriptor_ids: set[str],
    spatial_axis_ledger: dict | None,
) -> tuple[str, dict | None]:
    """Keep eyeline targets present without inventing undeclared on-screen bodies."""
    ledger = contract.get("offscreen_relationship_ledger")
    if not ledger:
        return "", None
    if not spatial_axis_ledger:
        raise ValueError("offscreen_relationship_ledger requires spatial_axis_ledger")
    if ledger.get("policy") != OFFSCREEN_RELATIONSHIP_POLICY:
        raise ValueError(
            "offscreen_relationship_ledger policy must be "
            f"{OFFSCREEN_RELATIONSHIP_POLICY}"
        )
    rows = require(
        ledger.get("shots"), "offscreen_relationship_ledger shots are required"
    )
    if not isinstance(rows, list) or len(rows) != len(segments):
        raise ValueError(
            "offscreen_relationship_ledger must exactly cover all compiled shots"
        )
    spatial_rows = {
        int(row["shot_index"]): row for row in spatial_axis_ledger["shots"]
    }
    compiled = []
    for index, (row, segment) in enumerate(zip(rows, segments), start=1):
        shot_index = int(require(
            row.get("shot_index"),
            f"offscreen relationship row {index} shot_index is required",
        ))
        if shot_index != index or shot_index != segment["shot_index"]:
            raise ValueError(
                "offscreen_relationship_ledger shot_index must match compiled shot order"
            )
        spatial = spatial_rows[shot_index]
        subject_id = require(
            row.get("subject_descriptor_id"),
            f"offscreen relationship row {index} subject_descriptor_id is required",
        )
        target_id = require(
            row.get("eyeline_target_descriptor_id"),
            f"offscreen relationship row {index} eyeline_target_descriptor_id is required",
        )
        if subject_id not in descriptor_ids or target_id not in descriptor_ids:
            raise ValueError(
                f"offscreen relationship row {index} references unknown descriptor"
            )
        if subject_id != spatial["subject_descriptor_id"]:
            raise ValueError(
                f"offscreen relationship row {index} subject must match spatial-axis ledger"
            )
        if target_id != spatial["eyeline_target_descriptor_id"]:
            raise ValueError(
                f"offscreen relationship row {index} target must match spatial-axis ledger"
            )
        gaze_direction = require(
            row.get("gaze_direction"),
            f"offscreen relationship row {index} gaze_direction is required",
        )
        if gaze_direction != spatial["gaze_direction"]:
            raise ValueError(
                f"offscreen relationship row {index} gaze must match spatial-axis ledger"
            )
        visibility = require(
            row.get("target_visibility"),
            f"offscreen relationship row {index} target_visibility is required",
        )
        exit_visibility = require(
            row.get("exit_visibility"),
            f"offscreen relationship row {index} exit_visibility is required",
        )
        if visibility not in OFFSCREEN_VISIBILITY_STATES:
            raise ValueError(f"unsupported target visibility: {visibility}")
        if exit_visibility not in OFFSCREEN_VISIBILITY_STATES:
            raise ValueError(f"unsupported exit visibility: {exit_visibility}")
        evidence_type = require(
            row.get("presence_evidence_type"),
            f"offscreen relationship row {index} presence_evidence_type is required",
        )
        if evidence_type not in OFFSCREEN_EVIDENCE_TYPES:
            raise ValueError(f"unsupported offscreen presence evidence: {evidence_type}")
        evidence = require(
            row.get("presence_evidence"),
            f"offscreen relationship row {index} presence_evidence is required",
        )
        reveal_policy = require(
            row.get("reveal_policy"),
            f"offscreen relationship row {index} reveal_policy is required",
        )
        if reveal_policy not in OFFSCREEN_REVEAL_POLICIES:
            raise ValueError(f"unsupported offscreen reveal policy: {reveal_policy}")
        offscreen_side = row.get("offscreen_side")
        reentry_trigger = row.get("reentry_trigger")
        if visibility == "OFF_SCREEN":
            if offscreen_side not in OFFSCREEN_SIDES:
                raise ValueError(
                    f"offscreen relationship row {index} requires a supported offscreen_side"
                )
            if evidence_type == "VISIBLE_FRAME_PRESENCE":
                raise ValueError(
                    f"offscreen relationship row {index} cannot use visible-frame evidence"
                )
            if reveal_policy == "STAY_OFFSCREEN":
                if exit_visibility != "OFF_SCREEN" or reentry_trigger is not None:
                    raise ValueError(
                        f"offscreen relationship row {index} STAY_OFFSCREEN must remain offscreen"
                    )
            elif reveal_policy == "REENTER_ON_TRIGGER":
                require(
                    reentry_trigger,
                    f"offscreen relationship row {index} reentry_trigger is required",
                )
                if exit_visibility != "ON_SCREEN":
                    raise ValueError(
                        f"offscreen relationship row {index} reentry must exit on-screen"
                    )
            else:
                raise ValueError(
                    f"offscreen relationship row {index} OFF_SCREEN target needs stay or reentry policy"
                )
        else:
            if offscreen_side is not None or reentry_trigger is not None:
                raise ValueError(
                    f"offscreen relationship row {index} on-screen target cannot have offscreen fields"
                )
            if reveal_policy != "VISIBLE_HOLD" or exit_visibility != "ON_SCREEN":
                raise ValueError(
                    f"offscreen relationship row {index} on-screen target must use VISIBLE_HOLD"
                )
            if evidence_type != "VISIBLE_FRAME_PRESENCE":
                raise ValueError(
                    f"offscreen relationship row {index} on-screen target needs visible-frame evidence"
                )
        entry_state = require(
            row.get("entry_state"),
            f"offscreen relationship row {index} entry_state is required",
        )
        exit_state = require(
            row.get("exit_state"),
            f"offscreen relationship row {index} exit_state is required",
        )
        if entry_state != segment["entry_state"] or exit_state != segment["exit_state"]:
            raise ValueError(
                f"offscreen relationship row {index} entry/exit state must match cinematic segment"
            )
        compiled.append({
            "shot_index": shot_index,
            "subject_descriptor_id": subject_id,
            "eyeline_target_descriptor_id": target_id,
            "gaze_direction": gaze_direction,
            "target_visibility": visibility,
            "offscreen_side": offscreen_side,
            "presence_evidence_type": evidence_type,
            "presence_evidence": evidence,
            "reveal_policy": reveal_policy,
            "reentry_trigger": reentry_trigger,
            "exit_visibility": exit_visibility,
            "entry_state": entry_state,
            "exit_state": exit_state,
        })

    prompt_rows = [
        f"镜头{row['shot_index']}：主体={row['subject_descriptor_id']}；"
        f"视线={row['gaze_direction']}→{row['eyeline_target_descriptor_id']}；"
        f"目标可见性={row['target_visibility']}"
        f"{('@' + row['offscreen_side']) if row['offscreen_side'] else ''}；"
        f"存在证据={row['presence_evidence_type']}:{row['presence_evidence']}；"
        f"显影策略={row['reveal_policy']}；"
        f"再入触发={row['reentry_trigger'] or '无'}；"
        f"出口可见性={row['exit_visibility']}；入口={row['entry_state']}；出口={row['exit_state']}"
        for row in compiled
    ]
    return (
        "\n【OFFSCREEN RELATIONSHIP LEDGER｜画外目标方位、证据与再入】"
        + "。".join(prompt_rows)
        + "。OFF_SCREEN 目标在再入触发前严禁入画；不得用新增人物、错误视线或无来源声画线索替代已声明的画外存在。",
        {
            "version": "1.0.0",
            "policy": OFFSCREEN_RELATIONSHIP_POLICY,
            "shots": compiled,
            "full_shot_coverage": True,
            "video_side_only": True,
            "forbidden_keyframe_fields": [
                "composition", "shot_scale", "lens_mm", "camera_height", "current_pose"
            ],
            "adapter": "HELL_GRIND_OFFSCREEN_RELATIONSHIP_PROMPT_RULE_ADAPTER_V12",
        },
    )


def compile_shot_information_ladder(
    contract: dict, segments: list[dict]
) -> tuple[str, dict | None]:
    """Bind each cut to one distinct, visible information unit and camera job."""
    ladder = contract.get("shot_information_ladder")
    if not ladder:
        return "", None
    if ladder.get("coverage_policy") != "ONE_PRIMARY_INFORMATION_UNIT_PER_SHOT":
        raise ValueError(
            "shot_information_ladder coverage_policy must be "
            "ONE_PRIMARY_INFORMATION_UNIT_PER_SHOT"
        )
    rows = require(ladder.get("shots"), "shot_information_ladder shots are required")
    if not isinstance(rows, list) or len(rows) != len(segments):
        raise ValueError("shot_information_ladder must exactly cover all compiled shots")

    compiled, unit_ids, information_types = [], set(), set()
    for index, (row, segment) in enumerate(zip(rows, segments), start=1):
        shot_index = int(require(
            row.get("shot_index"), f"shot information row {index} shot_index is required"
        ))
        if shot_index != index:
            raise ValueError("shot_information_ladder shot_index must match compiled shot order")
        unit_id = require(
            row.get("information_unit_id"),
            f"shot information row {index} information_unit_id is required",
        )
        if unit_id in unit_ids:
            raise ValueError(f"duplicate shot information unit: {unit_id}")
        unit_ids.add(unit_id)
        information_type = require(
            row.get("information_type"),
            f"shot information row {index} information_type is required",
        )
        if information_type not in SHOT_INFORMATION_TYPES:
            raise ValueError(f"unsupported shot information type: {information_type}")
        information_types.add(information_type)
        entry_state = require(
            row.get("entry_state"), f"shot information row {index} entry_state is required"
        )
        exit_state = require(
            row.get("exit_state"), f"shot information row {index} exit_state is required"
        )
        if entry_state != segment["entry_state"] or exit_state != segment["exit_state"]:
            raise ValueError(
                f"shot information row {index} entry/exit state must match cinematic segment"
            )
        lens_mm = int(require(
            row.get("lens_mm"), f"shot information row {index} lens_mm is required"
        ))
        if not 14 <= lens_mm <= 200:
            raise ValueError(f"shot information row {index} lens_mm must be between 14 and 200")
        visible_consequence = row.get("visible_consequence")
        if information_type in {"contact_detail", "consequence", "resolution"}:
            require(
                visible_consequence,
                f"shot information row {index} {information_type} requires visible_consequence",
            )
        compiled.append({
            "shot_index": shot_index,
            "information_unit_id": unit_id,
            "information_type": information_type,
            "subject_action": require(
                row.get("subject_action"), f"shot information row {index} subject_action is required"
            ),
            "visible_evidence": require(
                row.get("visible_evidence"), f"shot information row {index} visible_evidence is required"
            ),
            "visible_consequence": visible_consequence,
            "shot_scale": require(
                row.get("shot_scale"), f"shot information row {index} shot_scale is required"
            ),
            "lens_mm": lens_mm,
            "camera_role": require(
                row.get("camera_role"), f"shot information row {index} camera_role is required"
            ),
            "entry_state": entry_state,
            "exit_state": exit_state,
        })
    if len(compiled) >= 3 and len(information_types) < 3:
        raise ValueError("shot_information_ladder needs at least three information types for 3+ shots")

    prompt_rows = [
        f"镜头{row['shot_index']}[{row['information_unit_id']}/{row['information_type']}]："
        f"主体动作={row['subject_action']}；可见证据={row['visible_evidence']}；"
        f"可见后果={row['visible_consequence'] or '本镜不新增后果'}；"
        f"景别={row['shot_scale']}，镜头={row['lens_mm']}mm，机位职责={row['camera_role']}；"
        f"入口={row['entry_state']}，出口={row['exit_state']}"
        for row in compiled
    ]
    return (
        "\n【SHOT INFORMATION LADDER｜一镜一信息】" + "。".join(prompt_rows) + "。"
        "每镜只承担一个主要可见信息单元；不得用换景别、换焦段或装饰运镜重复上一镜动作画面。",
        {
            "version": "1.0.0",
            "coverage_policy": "ONE_PRIMARY_INFORMATION_UNIT_PER_SHOT",
            "shots": compiled,
            "full_shot_coverage": True,
            "unique_information_units": True,
            "adapter": "HELL_GRIND_SHOT_INFORMATION_LADDER_PROMPT_RULE_ADAPTER_V9",
        },
    )


def compile_shot_boundary_state_ledger(
    contract: dict, segments: list[dict]
) -> tuple[str, dict | None]:
    """Prove each shot's declared entry on frame one and exit at the cut."""
    ledger = contract.get("shot_boundary_state_ledger")
    if not ledger:
        return "", None
    if ledger.get("policy") != SHOT_BOUNDARY_STATE_POLICY:
        raise ValueError(
            "shot_boundary_state_ledger policy must be "
            f"{SHOT_BOUNDARY_STATE_POLICY}"
        )
    if ledger.get("reset_policy") != SHOT_BOUNDARY_RESET_POLICY:
        raise ValueError(
            "shot_boundary_state_ledger reset_policy must be "
            f"{SHOT_BOUNDARY_RESET_POLICY}"
        )
    rows = require(
        ledger.get("shots"), "shot_boundary_state_ledger shots are required"
    )
    if not isinstance(rows, list) or len(rows) != len(segments):
        raise ValueError(
            "shot_boundary_state_ledger must exactly cover all compiled shots"
        )

    compiled = []
    for index, (row, segment) in enumerate(zip(rows, segments), start=1):
        shot_index = int(require(
            row.get("shot_index"), f"shot boundary row {index} shot_index is required"
        ))
        if shot_index != index or shot_index != segment["shot_index"]:
            raise ValueError(
                "shot_boundary_state_ledger shot_index must match compiled shot order"
            )
        entry_state = require(
            row.get("entry_state"), f"shot boundary row {index} entry_state is required"
        )
        exit_state = require(
            row.get("exit_state"), f"shot boundary row {index} exit_state is required"
        )
        if entry_state != segment["entry_state"] or exit_state != segment["exit_state"]:
            raise ValueError(
                f"shot boundary row {index} entry/exit state must match cinematic segment"
            )
        if row.get("entry_policy") != SHOT_BOUNDARY_ENTRY_POLICY:
            raise ValueError(
                f"shot boundary row {index} entry_policy must be "
                f"{SHOT_BOUNDARY_ENTRY_POLICY}"
            )
        hold_seconds = float(require(
            row.get("final_result_hold_seconds"),
            f"shot boundary row {index} final_result_hold_seconds is required",
        ))
        shot_duration = segment["end_seconds"] - segment["start_seconds"]
        if hold_seconds < 0.5 or hold_seconds > shot_duration:
            raise ValueError(
                f"shot boundary row {index} final result hold must be between 0.5s and shot duration"
            )
        handoff = row.get("handoff_target_shot_index")
        expected_handoff = index + 1 if index < len(segments) else None
        if handoff != expected_handoff:
            raise ValueError(
                f"shot boundary row {index} handoff target must be the next compiled shot or null"
            )
        compiled.append({
            "shot_index": shot_index,
            "entry_state": entry_state,
            "first_frame_evidence": require(
                row.get("first_frame_evidence"),
                f"shot boundary row {index} first_frame_evidence is required",
            ),
            "entry_policy": SHOT_BOUNDARY_ENTRY_POLICY,
            "exit_state": exit_state,
            "final_frame_evidence": require(
                row.get("final_frame_evidence"),
                f"shot boundary row {index} final_frame_evidence is required",
            ),
            "final_result_hold_seconds": hold_seconds,
            "handoff_target_shot_index": handoff,
        })

    prompt_rows = [
        f"镜头{row['shot_index']}：首帧入口={row['entry_state']}；"
        f"首帧证据={row['first_frame_evidence']}；入口策略={row['entry_policy']}；"
        f"末帧出口={row['exit_state']}；末帧证据={row['final_frame_evidence']}；"
        f"结果至少保持{row['final_result_hold_seconds']:g}秒；"
        f"交接={('镜头' + str(row['handoff_target_shot_index'])) if row['handoff_target_shot_index'] else '终镜'}"
        for row in compiled
    ]
    return (
        "\n【SHOT BOUNDARY STATE LOCK｜首帧既定状态、末帧结果与交接】"
        + "。".join(prompt_rows)
        + "。每次切入必须直接呈现已声明入口，不得重演起势或重置人物、道具、环境；"
        "切出前必须让出口结果保持可读，并只交接到已声明的下一镜。",
        {
            "version": "1.0.0",
            "policy": SHOT_BOUNDARY_STATE_POLICY,
            "reset_policy": SHOT_BOUNDARY_RESET_POLICY,
            "shots": compiled,
            "full_shot_coverage": True,
            "video_side_only": True,
            "forbidden_keyframe_fields": [
                "composition", "shot_scale", "lens_mm", "camera_height", "depth_layers"
            ],
            "adapter": "HELL_GRIND_SHOT_BOUNDARY_STATE_PROMPT_RULE_ADAPTER_V13",
        },
    )


def compile_depth_focus_ledger(
    contract: dict, segments: list[dict], descriptor_ids: set[str]
) -> tuple[str, dict | None]:
    """Bind focus ownership and any rack focus to a visible subject trigger."""
    ledger = contract.get("depth_focus_ledger")
    if not ledger:
        return "", None
    if ledger.get("policy") != DEPTH_FOCUS_POLICY:
        raise ValueError(
            "depth_focus_ledger policy must be "
            f"{DEPTH_FOCUS_POLICY}"
        )
    rows = require(ledger.get("shots"), "depth_focus_ledger shots are required")
    if not isinstance(rows, list) or len(rows) != len(segments):
        raise ValueError("depth_focus_ledger must exactly cover all compiled shots")

    compiled = []
    for index, (row, segment) in enumerate(zip(rows, segments), start=1):
        shot_index = int(require(
            row.get("shot_index"), f"depth focus row {index} shot_index is required"
        ))
        if shot_index != index or shot_index != segment["shot_index"]:
            raise ValueError(
                "depth_focus_ledger shot_index must match compiled shot order"
            )
        entry_state = require(
            row.get("entry_state"), f"depth focus row {index} entry_state is required"
        )
        exit_state = require(
            row.get("exit_state"), f"depth focus row {index} exit_state is required"
        )
        if entry_state != segment["entry_state"] or exit_state != segment["exit_state"]:
            raise ValueError(
                f"depth focus row {index} entry/exit state must match cinematic segment"
            )
        mode = require(
            row.get("focus_mode"), f"depth focus row {index} focus_mode is required"
        )
        if mode not in DEPTH_FOCUS_MODES:
            raise ValueError(f"unsupported depth focus mode: {mode}")
        entry_id = require(
            row.get("entry_focus_descriptor_id"),
            f"depth focus row {index} entry_focus_descriptor_id is required",
        )
        target_id = require(
            row.get("target_focus_descriptor_id"),
            f"depth focus row {index} target_focus_descriptor_id is required",
        )
        exit_id = require(
            row.get("exit_focus_descriptor_id"),
            f"depth focus row {index} exit_focus_descriptor_id is required",
        )
        segment_ids = set(segment["descriptor_ids"])
        for field, value in (
            ("entry_focus_descriptor_id", entry_id),
            ("target_focus_descriptor_id", target_id),
            ("exit_focus_descriptor_id", exit_id),
        ):
            if value not in descriptor_ids or value not in segment_ids:
                raise ValueError(
                    f"depth focus row {index} {field} must reference a descriptor in its segment"
                )
        entry_plane = require(
            row.get("entry_depth_plane"),
            f"depth focus row {index} entry_depth_plane is required",
        )
        target_plane = require(
            row.get("target_depth_plane"),
            f"depth focus row {index} target_depth_plane is required",
        )
        if entry_plane not in DEPTH_FOCUS_PLANES or target_plane not in DEPTH_FOCUS_PLANES:
            raise ValueError("unsupported depth focus plane")
        duration = segment["end_seconds"] - segment["start_seconds"]
        trigger_seconds = float(require(
            row.get("trigger_seconds"),
            f"depth focus row {index} trigger_seconds is required",
        ))
        if not 0 <= trigger_seconds <= duration:
            raise ValueError(
                f"depth focus row {index} trigger_seconds must be inside the shot"
            )
        hold_until = float(require(
            row.get("result_hold_until_seconds"),
            f"depth focus row {index} result_hold_until_seconds is required",
        ))
        if abs(hold_until - duration) > 0.01:
            raise ValueError(
                f"depth focus row {index} must hold the landed focus to shot end"
            )
        transfer_start = row.get("transfer_start_seconds")
        transfer_end = row.get("transfer_end_seconds")
        if mode == "LOCKED_FOCUS":
            if transfer_start is not None or transfer_end is not None:
                raise ValueError(
                    f"depth focus row {index} locked focus cannot declare a transfer window"
                )
            if entry_id != target_id or target_id != exit_id or entry_plane != target_plane:
                raise ValueError(
                    f"depth focus row {index} locked focus must keep one subject and plane"
                )
        else:
            if transfer_start is None or transfer_end is None:
                raise ValueError(
                    f"depth focus row {index} rack focus requires a transfer window"
                )
            transfer_start = float(transfer_start)
            transfer_end = float(transfer_end)
            if transfer_start < trigger_seconds:
                raise ValueError(
                    f"depth focus row {index} focus transfer cannot start before its trigger"
                )
            if not trigger_seconds <= transfer_start < transfer_end <= duration:
                raise ValueError(
                    f"depth focus row {index} transfer window must stay inside the shot"
                )
            if entry_id == target_id and entry_plane == target_plane:
                raise ValueError(
                    f"depth focus row {index} rack focus must change subject or depth plane"
                )
            if exit_id != target_id:
                raise ValueError(
                    f"depth focus row {index} exit focus must equal the declared target"
                )
        compiled.append({
            "shot_index": shot_index,
            "focus_mode": mode,
            "entry_focus_descriptor_id": entry_id,
            "entry_depth_plane": entry_plane,
            "focus_trigger": require(
                row.get("focus_trigger"),
                f"depth focus row {index} focus_trigger is required",
            ),
            "trigger_seconds": trigger_seconds,
            "target_focus_descriptor_id": target_id,
            "target_depth_plane": target_plane,
            "transfer_start_seconds": transfer_start,
            "transfer_end_seconds": transfer_end,
            "stop_condition": require(
                row.get("stop_condition"),
                f"depth focus row {index} stop_condition is required",
            ),
            "exit_focus_descriptor_id": exit_id,
            "visible_focus_evidence": require(
                row.get("visible_focus_evidence"),
                f"depth focus row {index} visible_focus_evidence is required",
            ),
            "result_hold_until_seconds": hold_until,
            "entry_state": entry_state,
            "exit_state": exit_state,
        })

    prompt_rows = [
        f"镜头{row['shot_index']}[{row['focus_mode']}]："
        f"初始焦点={row['entry_focus_descriptor_id']}@{row['entry_depth_plane']}；"
        f"触发={row['focus_trigger']}@{row['trigger_seconds']:g}秒；"
        f"目标焦点={row['target_focus_descriptor_id']}@{row['target_depth_plane']}；"
        f"转移={('保持锁焦' if row['transfer_start_seconds'] is None else str(row['transfer_start_seconds']) + '-' + str(row['transfer_end_seconds']) + '秒')}；"
        f"停止条件={row['stop_condition']}；末焦={row['exit_focus_descriptor_id']}；"
        f"锐度证据={row['visible_focus_evidence']}；保持至{row['result_hold_until_seconds']:g}秒"
        for row in compiled
    ]
    return (
        "\n【DEPTH-FOCUS TRANSFER LEDGER｜焦点主体、纵深层与触发式拉焦】"
        + "。".join(prompt_rows)
        + "。焦点不得抢在主体触发前转移，不得无动机搜索或漂移；"
        "落焦后必须以可见锐度证据保持到切出。",
        {
            "version": "1.0.0",
            "policy": DEPTH_FOCUS_POLICY,
            "modes": sorted(DEPTH_FOCUS_MODES),
            "depth_planes": sorted(DEPTH_FOCUS_PLANES),
            "shots": compiled,
            "full_shot_coverage": True,
            "video_side_only": True,
            "forbidden_keyframe_fields": [
                "composition", "shot_scale", "lens_mm", "camera_height",
                "depth_layers", "current_pose",
            ],
            "adapter": "HELL_GRIND_DEPTH_FOCUS_TRANSFER_PROMPT_RULE_ADAPTER_V14",
        },
    )


def compile_contact_force_state_ledger(
    contract: dict, segments: list[dict], descriptor_ids: set[str]
) -> tuple[str, dict | None]:
    """Bind physical contact ownership, force evidence, and cut-to-cut handoffs."""
    ledger = contract.get("contact_force_state_ledger")
    if not ledger:
        return "", None
    if ledger.get("policy") != CONTACT_FORCE_STATE_POLICY:
        raise ValueError(
            "contact_force_state_ledger policy must be "
            f"{CONTACT_FORCE_STATE_POLICY}"
        )
    rows = require(
        ledger.get("shots"), "contact_force_state_ledger shots are required"
    )
    if not isinstance(rows, list) or len(rows) != len(segments):
        raise ValueError(
            "contact_force_state_ledger must exactly cover all compiled shots"
        )

    compiled, prior_exit_by_track = [], {}
    for index, (row, segment) in enumerate(zip(rows, segments), start=1):
        shot_index = int(require(
            row.get("shot_index"),
            f"contact force row {index} shot_index is required",
        ))
        if shot_index != index or shot_index != segment["shot_index"]:
            raise ValueError(
                "contact_force_state_ledger shot_index must match compiled shot order"
            )
        entry_state = require(
            row.get("entry_state"), f"contact force row {index} entry_state is required"
        )
        exit_state = require(
            row.get("exit_state"), f"contact force row {index} exit_state is required"
        )
        if entry_state != segment["entry_state"] or exit_state != segment["exit_state"]:
            raise ValueError(
                f"contact force row {index} entry/exit state must match cinematic segment"
            )
        track_id = require(
            row.get("contact_track_id"),
            f"contact force row {index} contact_track_id is required",
        )
        mode = require(
            row.get("contact_mode"),
            f"contact force row {index} contact_mode is required",
        )
        if mode not in CONTACT_FORCE_STATE_MODES:
            raise ValueError(f"unsupported contact force state mode: {mode}")
        actor_id = require(
            row.get("actor_descriptor_id"),
            f"contact force row {index} actor_descriptor_id is required",
        )
        target_id = require(
            row.get("target_descriptor_id"),
            f"contact force row {index} target_descriptor_id is required",
        )
        segment_ids = set(segment["descriptor_ids"])
        for field, value in (
            ("actor_descriptor_id", actor_id),
            ("target_descriptor_id", target_id),
        ):
            if value not in descriptor_ids or value not in segment_ids:
                raise ValueError(
                    f"contact force row {index} {field} must reference a descriptor in its segment"
                )
        entry_contact = require(
            row.get("entry_contact_state"),
            f"contact force row {index} entry_contact_state is required",
        )
        target_contact = require(
            row.get("target_contact_state"),
            f"contact force row {index} target_contact_state is required",
        )
        exit_contact = require(
            row.get("exit_contact_state"),
            f"contact force row {index} exit_contact_state is required",
        )
        prior_exit = prior_exit_by_track.get(track_id)
        if prior_exit is not None and entry_contact != prior_exit:
            raise ValueError(
                f"contact force track {track_id} handoff mismatch: "
                f"previous exit {prior_exit} but shot {shot_index} enters {entry_contact}"
            )
        duration = segment["end_seconds"] - segment["start_seconds"]
        trigger_seconds = float(require(
            row.get("trigger_seconds"),
            f"contact force row {index} trigger_seconds is required",
        ))
        if not 0 <= trigger_seconds <= duration:
            raise ValueError(
                f"contact force row {index} trigger_seconds must be inside the shot"
            )
        hold_until = float(require(
            row.get("result_hold_until_seconds"),
            f"contact force row {index} result_hold_until_seconds is required",
        ))
        if abs(hold_until - duration) > 0.01:
            raise ValueError(
                f"contact force row {index} must hold the contact result to shot end"
            )
        change_start = row.get("change_start_seconds")
        change_end = row.get("change_end_seconds")
        if mode == "LOCKED_CONTACT":
            if change_start is not None or change_end is not None:
                raise ValueError(
                    f"contact force row {index} locked contact cannot declare a change window"
                )
            if entry_contact != target_contact or target_contact != exit_contact:
                raise ValueError(
                    f"contact force row {index} locked contact must preserve one state"
                )
        else:
            if change_start is None or change_end is None:
                raise ValueError(
                    f"contact force row {index} triggered change requires a change window"
                )
            change_start = float(change_start)
            change_end = float(change_end)
            if change_start < trigger_seconds:
                raise ValueError(
                    f"contact force row {index} contact change cannot start before its trigger"
                )
            if not trigger_seconds <= change_start < change_end <= duration:
                raise ValueError(
                    f"contact force row {index} change window must stay inside the shot"
                )
            if entry_contact == target_contact:
                raise ValueError(
                    f"contact force row {index} triggered change must change contact state"
                )
            if exit_contact != target_contact:
                raise ValueError(
                    f"contact force row {index} exit contact must equal the declared target"
                )
        compiled.append({
            "shot_index": shot_index,
            "contact_track_id": track_id,
            "contact_mode": mode,
            "actor_descriptor_id": actor_id,
            "target_descriptor_id": target_id,
            "contact_anchor": require(
                row.get("contact_anchor"),
                f"contact force row {index} contact_anchor is required",
            ),
            "entry_contact_state": entry_contact,
            "contact_trigger": require(
                row.get("contact_trigger"),
                f"contact force row {index} contact_trigger is required",
            ),
            "trigger_seconds": trigger_seconds,
            "target_contact_state": target_contact,
            "change_start_seconds": change_start,
            "change_end_seconds": change_end,
            "force_evidence": require(
                row.get("force_evidence"),
                f"contact force row {index} force_evidence is required",
            ),
            "visible_contact_evidence": require(
                row.get("visible_contact_evidence"),
                f"contact force row {index} visible_contact_evidence is required",
            ),
            "exit_contact_state": exit_contact,
            "result_hold_until_seconds": hold_until,
            "entry_state": entry_state,
            "exit_state": exit_state,
        })
        prior_exit_by_track[track_id] = exit_contact

    prompt_rows = [
        f"镜头{row['shot_index']}[{row['contact_track_id']}/{row['contact_mode']}]："
        f"接触双方={row['actor_descriptor_id']}→{row['target_descriptor_id']}；"
        f"接触锚点={row['contact_anchor']}；入口接触={row['entry_contact_state']}；"
        f"触发={row['contact_trigger']}@{row['trigger_seconds']:g}秒；"
        f"目标接触={row['target_contact_state']}；"
        f"变化={('保持接触' if row['change_start_seconds'] is None else str(row['change_start_seconds']) + '-' + str(row['change_end_seconds']) + '秒')}；"
        f"受力证据={row['force_evidence']}；可见接触证据={row['visible_contact_evidence']}；"
        f"出口接触={row['exit_contact_state']}；保持至{row['result_hold_until_seconds']:g}秒"
        for row in compiled
    ]
    return (
        "\n【CONTACT FORCE STATE LEDGER｜接触归属、受力证据与跨切延续】"
        + "。".join(prompt_rows)
        + "。接触变化不得抢在物理触发前发生；同一接触轨道的下一镜入口必须继承上一镜出口，"
        "并以可见接触与受力证据保持到切出。",
        {
            "version": "1.0.0",
            "policy": CONTACT_FORCE_STATE_POLICY,
            "modes": sorted(CONTACT_FORCE_STATE_MODES),
            "shots": compiled,
            "full_shot_coverage": True,
            "video_side_only": True,
            "forbidden_keyframe_fields": [
                "composition", "shot_scale", "lens_mm", "camera_height",
                "depth_layers", "current_pose",
            ],
            "adapter": "HELL_GRIND_CONTACT_FORCE_STATE_PROMPT_RULE_ADAPTER_V15",
        },
    )


def compile_camera_action_coupling_ledger(
    contract: dict, segments: list[dict]
) -> tuple[str, dict | None]:
    """Bind camera response timing to subject change and a readable result hold."""
    ledger = contract.get("camera_action_coupling_ledger")
    if not ledger:
        return "", None
    if ledger.get("policy") != CAMERA_ACTION_COUPLING_POLICY:
        raise ValueError(
            "camera_action_coupling_ledger policy must be "
            f"{CAMERA_ACTION_COUPLING_POLICY}"
        )
    rows = require(
        ledger.get("shots"), "camera_action_coupling_ledger shots are required"
    )
    if not isinstance(rows, list) or len(rows) != len(segments):
        raise ValueError(
            "camera_action_coupling_ledger must exactly cover all compiled shots"
        )

    compiled = []
    for index, (row, segment) in enumerate(zip(rows, segments), start=1):
        shot_index = int(require(
            row.get("shot_index"), f"camera coupling row {index} shot_index is required"
        ))
        if shot_index != index or shot_index != segment["shot_index"]:
            raise ValueError(
                "camera_action_coupling_ledger shot_index must match compiled shot order"
            )
        coupling_type = require(
            row.get("coupling_type"),
            f"camera coupling shot {shot_index} coupling_type is required",
        )
        if coupling_type not in CAMERA_ACTION_COUPLING_TYPES:
            raise ValueError(f"unsupported camera coupling type: {coupling_type}")
        response_type = require(
            row.get("camera_response_type"),
            f"camera coupling shot {shot_index} camera_response_type is required",
        )
        if response_type not in CAMERA_ACTION_RESPONSE_TYPES:
            raise ValueError(f"unsupported camera response type: {response_type}")
        motivation = require(
            row.get("camera_motivation"),
            f"camera coupling shot {shot_index} camera_motivation is required",
        )
        if motivation != segment["camera_motivation"]:
            raise ValueError(
                f"camera coupling shot {shot_index} camera_motivation must match its segment"
            )
        entry_state = require(
            row.get("entry_state"),
            f"camera coupling shot {shot_index} entry_state is required",
        )
        exit_state = require(
            row.get("exit_state"),
            f"camera coupling shot {shot_index} exit_state is required",
        )
        if entry_state != segment["entry_state"] or exit_state != segment["exit_state"]:
            raise ValueError(
                f"camera coupling shot {shot_index} entry/exit state must match its segment"
            )
        shot_duration = segment["end_seconds"] - segment["start_seconds"]
        trigger_seconds = float(require(
            row.get("trigger_seconds"),
            f"camera coupling shot {shot_index} trigger_seconds is required",
        ))
        result_hold_until = float(require(
            row.get("result_hold_until_seconds"),
            f"camera coupling shot {shot_index} result_hold_until_seconds is required",
        ))
        if not 0 <= trigger_seconds < shot_duration:
            raise ValueError(
                f"camera coupling shot {shot_index} trigger_seconds must be inside the shot"
            )
        if abs(result_hold_until - shot_duration) > 0.01:
            raise ValueError(
                f"camera coupling shot {shot_index} must hold the visible result to shot end"
            )

        movement_start = row.get("movement_start_seconds")
        movement_end = row.get("movement_end_seconds")
        if coupling_type == "LOCKED_HOLD":
            if response_type not in {"LOCKED_FRAME", "HANDHELD_BREATHING"}:
                raise ValueError(
                    f"camera coupling shot {shot_index} LOCKED_HOLD needs a locked response"
                )
            if movement_start is not None or movement_end is not None:
                raise ValueError(
                    f"camera coupling shot {shot_index} LOCKED_HOLD cannot declare movement timing"
                )
        else:
            if response_type in {"LOCKED_FRAME", "HANDHELD_BREATHING"}:
                raise ValueError(
                    f"camera coupling shot {shot_index} SUBJECT_TRIGGERED_MOVE needs movement"
                )
            movement_start = float(require(
                movement_start,
                f"camera coupling shot {shot_index} movement_start_seconds is required",
            ))
            movement_end = float(require(
                movement_end,
                f"camera coupling shot {shot_index} movement_end_seconds is required",
            ))
            if movement_start < trigger_seconds:
                raise ValueError(
                    f"camera coupling shot {shot_index} movement cannot start before its trigger"
                )
            if not movement_start < movement_end <= shot_duration:
                raise ValueError(
                    f"camera coupling shot {shot_index} movement timing must stay inside the shot"
                )
            if result_hold_until - movement_end < 0.5:
                raise ValueError(
                    f"camera coupling shot {shot_index} needs at least 0.5s result hold"
                )

        compiled.append({
            "shot_index": shot_index,
            "coupling_type": coupling_type,
            "physical_trigger": require(
                row.get("physical_trigger"),
                f"camera coupling shot {shot_index} physical_trigger is required",
            ),
            "trigger_seconds": trigger_seconds,
            "subject_change": require(
                row.get("subject_change"),
                f"camera coupling shot {shot_index} subject_change is required",
            ),
            "camera_response_type": response_type,
            "camera_response": require(
                row.get("camera_response"),
                f"camera coupling shot {shot_index} camera_response is required",
            ),
            "movement_start_seconds": movement_start,
            "movement_end_seconds": movement_end,
            "camera_motivation": motivation,
            "stop_condition": require(
                row.get("stop_condition"),
                f"camera coupling shot {shot_index} stop_condition is required",
            ),
            "visible_result": require(
                row.get("visible_result"),
                f"camera coupling shot {shot_index} visible_result is required",
            ),
            "result_hold_until_seconds": result_hold_until,
            "entry_state": entry_state,
            "exit_state": exit_state,
        })

    prompt_rows = []
    for row in compiled:
        movement = (
            "全镜保持构图"
            if row["coupling_type"] == "LOCKED_HOLD"
            else f"{row['movement_start_seconds']:g}-{row['movement_end_seconds']:g}秒执行"
        )
        prompt_rows.append(
            f"镜头{row['shot_index']}[{row['coupling_type']}]：{row['trigger_seconds']:g}秒"
            f"主体触发={row['physical_trigger']}，主体变化={row['subject_change']}；"
            f"镜头响应={row['camera_response_type']}({row['camera_response']})，{movement}；"
            f"动机={row['camera_motivation']}；停止条件={row['stop_condition']}；"
            f"可见结果={row['visible_result']}并保持到{row['result_hold_until_seconds']:g}秒；"
            f"入口={row['entry_state']}，出口={row['exit_state']}"
        )
    return (
        "\n【CAMERA-ACTION COUPLING LEDGER｜主体触发、镜头响应、结果停留】"
        + "。".join(prompt_rows)
        + "。镜头不得早于主体物理触发启动；到达停止条件后必须停住，并把可见结果保留到本镜结束。",
        {
            "version": "1.0.0",
            "policy": CAMERA_ACTION_COUPLING_POLICY,
            "shots": compiled,
            "full_shot_coverage": True,
            "adapter": "HELL_GRIND_CAMERA_ACTION_COUPLING_PROMPT_RULE_ADAPTER_V11",
        },
    )


def compile_cross_cut_state_ledger(
    contract: dict, shot_count: int, descriptor_ids: set[str]
) -> tuple[str, dict | None]:
    """Compile exact per-shot state handoffs so cuts cannot silently reset facts."""
    ledger = contract.get("cross_cut_state_ledger")
    if not ledger:
        return "", None
    if ledger.get("reset_policy") != "NO_UNDECLARED_RESET_ACROSS_CUTS":
        raise ValueError(
            "cross_cut_state_ledger reset_policy must be NO_UNDECLARED_RESET_ACROSS_CUTS"
        )
    tracks = require(ledger.get("tracks"), "cross_cut_state_ledger tracks are required")
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 8:
        raise ValueError("cross_cut_state_ledger must contain 1 to 8 tracks")

    compiled, track_ids = [], set()
    for track_index, track in enumerate(tracks, start=1):
        track_id = require(track.get("track_id"), f"state track {track_index} track_id is required")
        if track_id in track_ids:
            raise ValueError(f"duplicate cross-cut state track: {track_id}")
        track_ids.add(track_id)
        continuity_class = require(
            track.get("continuity_class"), f"state track {track_id} continuity_class is required"
        )
        if continuity_class not in CROSS_CUT_CONTINUITY_CLASSES:
            raise ValueError(f"unsupported cross-cut continuity class: {continuity_class}")
        subject_id = require(
            track.get("subject_descriptor_id"),
            f"state track {track_id} subject_descriptor_id is required",
        )
        if subject_id not in descriptor_ids:
            raise ValueError(f"state track {track_id} references unknown descriptor: {subject_id}")
        states = require(track.get("segment_states"), f"state track {track_id} segment_states are required")
        if not isinstance(states, list) or len(states) != shot_count:
            raise ValueError(f"state track {track_id} must exactly cover all compiled shots")

        compiled_states, previous_exit = [], None
        for state_index, state in enumerate(states, start=1):
            shot_index = int(require(
                state.get("shot_index"), f"state track {track_id} row {state_index} shot_index is required"
            ))
            if shot_index != state_index:
                raise ValueError(f"state track {track_id} shot_index must match compiled shot order")
            entry_state = require(
                state.get("entry_state"), f"state track {track_id} shot {shot_index} entry_state is required"
            )
            exit_state = require(
                state.get("exit_state"), f"state track {track_id} shot {shot_index} exit_state is required"
            )
            if previous_exit is not None and entry_state != previous_exit:
                raise ValueError(
                    f"cross-cut state handoff mismatch for {track_id}: "
                    f"shot {shot_index - 1} exits {previous_exit} but shot {shot_index} enters {entry_state}"
                )
            compiled_states.append({
                "shot_index": shot_index,
                "entry_state": entry_state,
                "exit_state": exit_state,
                "visible_evidence": require(
                    state.get("visible_evidence"),
                    f"state track {track_id} shot {shot_index} visible_evidence is required",
                ),
            })
            previous_exit = exit_state
        terminal_state = require(
            track.get("terminal_state"), f"state track {track_id} terminal_state is required"
        )
        if terminal_state != previous_exit:
            raise ValueError(f"state track {track_id} terminal_state must match its final exit_state")
        compiled.append({
            "track_id": track_id,
            "continuity_class": continuity_class,
            "subject_descriptor_id": subject_id,
            "segment_states": compiled_states,
            "terminal_state": terminal_state,
        })

    track_rows = []
    for track in compiled:
        states = "；".join(
            f"镜头{state['shot_index']}入口={state['entry_state']}，可见证据={state['visible_evidence']}，出口={state['exit_state']}"
            for state in track["segment_states"]
        )
        track_rows.append(
            f"{track['track_id']}[{track['continuity_class']}]绑定{track['subject_descriptor_id']}："
            f"{states}；终态={track['terminal_state']}"
        )
    prompt = (
        "\n【CROSS-CUT STATE LEDGER｜跨镜状态账本】" + "。".join(track_rows) + "。"
        "相邻镜头必须原样继承上一镜出口状态；角色、伤势、道具、空间关系和环境结果均不得未声明复原。"
    )
    return prompt, {
        "version": "1.0.0",
        "reset_policy": "NO_UNDECLARED_RESET_ACROSS_CUTS",
        "tracks": compiled,
        "full_shot_coverage": True,
        "adapter": "HELL_GRIND_CROSS_CUT_STATE_LEDGER_PROMPT_RULE_ADAPTER_V8",
    }


def compile_cinematic_shot_language_contract(spec: dict, shot_count: int) -> tuple[str, dict | None]:
    """Compile a descriptor-first, time-coded shot prompt without mixing concerns."""
    contract = spec.get("cinematic_shot_language_contract")
    if not contract:
        return "", None
    if require(contract.get("version"), "cinematic shot language version is required") != "1.0.0":
        raise ValueError("unsupported cinematic shot language contract version")
    descriptors = require(contract.get("locked_descriptors"), "locked_descriptors are required")
    if not isinstance(descriptors, list) or not descriptors:
        raise ValueError("locked_descriptors must be a non-empty list")
    descriptor_rows, descriptor_ids = [], set()
    for index, row in enumerate(descriptors, start=1):
        descriptor_id = require(row.get("id"), f"descriptor {index} id is required")
        if descriptor_id in descriptor_ids:
            raise ValueError(f"duplicate locked descriptor: {descriptor_id}")
        descriptor_ids.add(descriptor_id)
        kind = require(row.get("kind"), f"descriptor {descriptor_id} kind is required")
        if kind not in {"character", "character_state", "location", "location_state", "prop", "prop_state"}:
            raise ValueError(f"unsupported descriptor kind: {kind}")
        descriptor_text = require(row.get("text"), f"descriptor {descriptor_id} text is required")
        digest = require(row.get("text_sha256"), f"descriptor {descriptor_id} text_sha256 is required")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
            raise ValueError(f"descriptor {descriptor_id} text_sha256 must be lowercase SHA-256")
        if hashlib.sha256(descriptor_text.encode("utf-8")).hexdigest() != digest:
            raise ValueError(f"descriptor {descriptor_id} text does not match text_sha256")
        if row.get("paste_policy") != "VERBATIM_EVERY_SHOT":
            raise ValueError(f"descriptor {descriptor_id} must use VERBATIM_EVERY_SHOT")
        if row.get("stress_test_status") != "PASS":
            raise ValueError(f"descriptor {descriptor_id} must pass its stress test")
        descriptor_rows.append(f"{descriptor_id}({kind},sha256={digest})：{descriptor_text}")

    segments = require(contract.get("segments"), "cinematic shot language segments are required")
    if not isinstance(segments, list) or len(segments) != shot_count:
        raise ValueError("cinematic shot language segments must exactly cover compiled shots")
    duration = float(require(spec.get("duration_seconds"), "duration_seconds is required"))
    cursor, compiled = 0.0, []
    for index, row in enumerate(segments, start=1):
        start = float(require(row.get("start_seconds"), f"segment {index} start_seconds is required"))
        end = float(require(row.get("end_seconds"), f"segment {index} end_seconds is required"))
        if abs(start - cursor) > 0.01 or end <= start or end > duration + 0.01:
            raise ValueError(f"segment {index} must be contiguous and inside duration_seconds")
        if int(require(row.get("shot_index"), f"segment {index} shot_index is required")) != index:
            raise ValueError("cinematic segment shot_index must match compiled shot order")
        geometry = require(row.get("geometry"), f"segment {index} geometry is required")
        geometry_fields = ("subject_anchor", "camera_side", "axis_relation", "scale_anchor")
        for field in geometry_fields:
            require(geometry.get(field), f"segment {index} geometry.{field} is required")
        refs = require(row.get("descriptor_ids"), f"segment {index} descriptor_ids are required")
        if not isinstance(refs, list) or not refs or not set(refs).issubset(descriptor_ids):
            raise ValueError(f"segment {index} references unknown or empty descriptors")
        audio = require(row.get("audio"), f"segment {index} audio is required")
        require(audio.get("diegetic"), f"segment {index} diegetic audio is required")
        dialogue_policy = require(audio.get("dialogue_policy"), f"segment {index} dialogue_policy is required")
        if dialogue_policy not in {"EXACT_QUOTED_LINES_ONLY", "NO_DIALOGUE", "CLOSED_MOUTH_VOICE_OVER"}:
            raise ValueError(f"segment {index} has unsupported dialogue_policy")
        compiled.append({
            "start_seconds": start, "end_seconds": end, "shot_index": index,
            "narrative_purpose": require(row.get("narrative_purpose"), f"segment {index} narrative_purpose is required"),
            "entry_state": require(row.get("entry_state"), f"segment {index} entry_state is required"),
            "exit_state": require(row.get("exit_state"), f"segment {index} exit_state is required"),
            "camera_motivation": require(row.get("camera_motivation"), f"segment {index} camera_motivation is required"),
            "geometry": {field: geometry[field] for field in geometry_fields},
            "descriptor_ids": refs, "audio": audio,
        })
        cursor = end
    if abs(cursor - duration) > 0.01:
        raise ValueError("cinematic shot language segments must cover the full duration")
    rules = require(contract.get("key_rules"), "cinematic shot language key_rules are required")
    if not isinstance(rules, list) or not rules:
        raise ValueError("cinematic shot language key_rules must be a non-empty list")
    atmosphere = require(contract.get("atmosphere_state"), "atmosphere_state is required")
    style = require(contract.get("style_prefix"), "style_prefix is required")
    negatives = require(contract.get("negative_constraints"), "cinematic negative_constraints are required")
    if not isinstance(negatives, list) or not negatives:
        raise ValueError("cinematic negative_constraints must be a non-empty list")
    state_ledger_prompt, state_ledger = compile_cross_cut_state_ledger(
        contract, shot_count, descriptor_ids
    )
    information_ladder_prompt, information_ladder = compile_shot_information_ladder(
        contract, compiled
    )
    spatial_axis_prompt, spatial_axis_ledger = compile_spatial_axis_ledger(
        contract, compiled, descriptor_ids
    )
    offscreen_prompt, offscreen_ledger = compile_offscreen_relationship_ledger(
        contract, compiled, descriptor_ids, spatial_axis_ledger
    )
    depth_focus_prompt, depth_focus_ledger = compile_depth_focus_ledger(
        contract, compiled, descriptor_ids
    )
    contact_force_prompt, contact_force_ledger = compile_contact_force_state_ledger(
        contract, compiled, descriptor_ids
    )
    boundary_prompt, boundary_ledger = compile_shot_boundary_state_ledger(
        contract, compiled
    )
    camera_style_prompt, camera_style_plan = compile_camera_style_plan(contract, compiled)
    coupling_prompt, coupling_ledger = compile_camera_action_coupling_ledger(
        contract, compiled
    )
    segment_rows = [
        f"{row['start_seconds']:g}-{row['end_seconds']:g}秒 / 镜头{row['shot_index']}：目的={row['narrative_purpose']}；"
        f"入口={row['entry_state']}；出口={row['exit_state']}；引用={','.join(row['descriptor_ids'])}；"
        f"几何=主体{row['geometry']['subject_anchor']}、机位侧{row['geometry']['camera_side']}、"
        f"轴线{row['geometry']['axis_relation']}、尺度{row['geometry']['scale_anchor']}；"
        f"镜头运动只为{row['camera_motivation']}；现场声={row['audio']['diegetic']}；对白策略={row['audio']['dialogue_policy']}"
        for row in compiled
    ]
    prompt = (
        "\n\n【LOCKED DESCRIPTORS｜逐镜原文复用】" + "；".join(descriptor_rows)
        + "。\n【SCENE PURPOSE / GEOMETRY / TIME-CODED CUTS】\n" + "\n".join(segment_rows)
        + camera_style_prompt
        + coupling_prompt
        + spatial_axis_prompt
        + offscreen_prompt
        + depth_focus_prompt
        + contact_force_prompt
        + boundary_prompt
        + information_ladder_prompt
        + state_ledger_prompt
        + "\n【KEY RULES】" + "；".join(rules)
        + f"。\n【ATMOSPHERE STATE】{atmosphere}。\n【STYLE PREFIX】{style}。"
        + "\n【NEGATIVE CONSTRAINTS】" + " / ".join(negatives) + "。"
        + "\n提示词各区块职责不可互相污染：动作不得夹带台词，风格不得改写角色/场景描述，负面词不得代替正向可见物理事件。"
    )
    return prompt, {
        "version": "1.0.0", "descriptor_count": len(descriptors), "segments": compiled,
        "full_duration_coverage": True, "descriptor_policy": "VERBATIM_EVERY_SHOT",
        "section_order": ["LOCKED_DESCRIPTORS", "PURPOSE_GEOMETRY_TIME_CUTS", "CAMERA_STYLE_PROFILE", "CAMERA_ACTION_COUPLING_LEDGER", "SPATIAL_AXIS_LEDGER", "OFFSCREEN_RELATIONSHIP_LEDGER", "DEPTH_FOCUS_TRANSFER_LEDGER", "CONTACT_FORCE_STATE_LEDGER", "SHOT_BOUNDARY_STATE_LOCK", "SHOT_INFORMATION_LADDER", "CROSS_CUT_STATE_LEDGER", "KEY_RULES", "AUDIO", "ATMOSPHERE", "STYLE", "NEGATIVES"],
        "camera_style_plan": camera_style_plan,
        "camera_style_gate": "PASS_PER_SHOT_GENRE_AWARE_STYLE_PROVENANCE",
        "camera_action_coupling_ledger": coupling_ledger,
        "camera_action_coupling_gate": "PASS_TRIGGER_RESPONSE_RESULT_HOLD" if coupling_ledger else "NOT_APPLICABLE",
        "spatial_axis_ledger": spatial_axis_ledger,
        "spatial_axis_gate": "PASS_SCREEN_DIRECTION_EYELINE_AND_BACKGROUND_COVERAGE" if spatial_axis_ledger else "NOT_APPLICABLE",
        "offscreen_relationship_ledger": offscreen_ledger,
        "offscreen_relationship_gate": "PASS_TARGET_VISIBILITY_EVIDENCE_AND_REENTRY" if offscreen_ledger else "NOT_APPLICABLE",
        "depth_focus_ledger": depth_focus_ledger,
        "depth_focus_gate": "PASS_TRIGGERED_FOCUS_TRANSFER_AND_TERMINAL_HOLD" if depth_focus_ledger else "NOT_APPLICABLE",
        "contact_force_state_ledger": contact_force_ledger,
        "contact_force_state_gate": "PASS_CONTACT_OWNERSHIP_FORCE_AND_CUT_HANDOFF" if contact_force_ledger else "NOT_APPLICABLE",
        "shot_boundary_state_ledger": boundary_ledger,
        "shot_boundary_state_gate": "PASS_FIRST_FRAME_ENTRY_AND_FINAL_FRAME_EXIT_EVIDENCE" if boundary_ledger else "NOT_APPLICABLE",
        "shot_information_ladder": information_ladder,
        "shot_information_gate": "PASS_UNIQUE_FULL_COVERAGE" if information_ladder else "NOT_APPLICABLE",
        "cross_cut_state_ledger": state_ledger,
        "cross_cut_state_gate": "PASS_EXACT_HANDOFF_AND_FULL_COVERAGE" if state_ledger else "NOT_APPLICABLE",
        "source_method": "HELL_GRIND_LICENSED_PRODUCTION_METHODOLOGY",
    }


def compile_combat_camera_language(
    contract: dict, beats: list[dict], duration: float, actual_mode: str
) -> tuple[str, dict]:
    """Compile motivated action-camera choices without recreating perpetual sway."""
    plan = require(contract.get("camera_language_plan"), "combat camera_language_plan is required")
    mode = require(plan.get("generation_mode"), "combat camera_language_plan.generation_mode is required")
    if mode not in MODES:
        raise ValueError(f"unsupported combat camera generation_mode: {mode}")
    if mode != actual_mode:
        raise ValueError("combat camera generation_mode must match the generation spec mode")
    segments = require(plan.get("segments"), "combat camera_language_plan.segments are required")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 5:
        raise ValueError("combat camera language requires 1 to 5 motivated segments")

    compiled, moving = [], []
    prior_end = 0.0
    for index, row in enumerate(segments, start=1):
        technique = require(row.get("technique_id"), f"combat camera segment {index} technique_id is required")
        if technique not in ACTION_CAMERA_TECHNIQUES:
            raise ValueError(f"unsupported combat camera technique: {technique}")
        label, use_case, family, max_seconds = ACTION_CAMERA_TECHNIQUES[technique]
        start = float(require(row.get("start_seconds"), f"combat camera segment {index} start_seconds is required"))
        end = float(require(row.get("end_seconds"), f"combat camera segment {index} end_seconds is required"))
        if start < prior_end or end <= start or end > duration + 0.01:
            raise ValueError(f"combat camera segment {index} has invalid or overlapping time range")
        if end - start > max_seconds + 0.01:
            raise ValueError(f"combat camera technique {technique} exceeds {max_seconds:g}s limit")
        if technique in ACTION_CAMERA_EDIT_ONLY and mode != "storyboard":
            raise ValueError(f"combat camera technique {technique} requires storyboard mode")
        if technique == "micro_slow_follow" and row.get("contact_is_decisive") is not True:
            raise ValueError("micro_slow_follow requires contact_is_decisive=true")
        beat_index = int(require(row.get("action_beat_index"), f"combat camera segment {index} action_beat_index is required"))
        if not 1 <= beat_index <= len(beats):
            raise ValueError(f"combat camera segment {index} action_beat_index is out of range")
        motivation = require(row.get("narrative_motivation"), f"combat camera segment {index} narrative_motivation is required")
        anchor = require(row.get("subject_anchor"), f"combat camera segment {index} subject_anchor is required")
        axis = require(row.get("axis_relation"), f"combat camera segment {index} axis_relation is required")
        if family in ACTION_CAMERA_DYNAMIC_FAMILIES:
            moving.append((start, end, family, technique))
        compiled.append({
            "technique_id": technique, "label": label, "family": family,
            "start_seconds": start, "end_seconds": end, "action_beat_index": beat_index,
            "narrative_motivation": motivation, "subject_anchor": anchor,
            "axis_relation": axis, "allowed_use": use_case,
        })
        prior_end = end

    is_long_take = mode in {"continuous_long_take", "multi_keyframe_long_take"}
    if is_long_take and len(moving) > 2:
        raise ValueError("combat long take permits at most two dynamic camera techniques")
    for previous, current in zip(compiled, compiled[1:]):
        if previous["technique_id"] == current["technique_id"]:
            raise ValueError("adjacent combat camera segments cannot repeat one technique")
    for previous, current in zip(moving, moving[1:]):
        if is_long_take and current[0] - previous[1] < 1.0:
            raise ValueError("dynamic combat camera techniques require at least 1 second of stable observation between them")
        if is_long_take and previous[2] == current[2]:
            raise ValueError("adjacent dynamic combat camera techniques cannot repeat one motion family")

    rows = [
        f"{row['start_seconds']:g}-{row['end_seconds']:g}秒用{row['label']}，只为{row['narrative_motivation']}；"
        f"绑定动作拍{row['action_beat_index']}，主体锚点{row['subject_anchor']}，轴线{row['axis_relation']}"
        for row in compiled
    ]
    prompt = (
        "\n【动作镜头语言配方】" + "；".join(rows) + "。未声明时段一律稳定机位。"
        "运镜必须服务动作因果和空间读取，不得把跟拍、环绕、推拉、升降、旋转或震动当作持续装饰；"
        "禁止连续摇摆、smooth roam、无动机slow push、重复环绕、用镜头运动掩盖动作缺失。"
    )
    return prompt, {
        "version": "1.0.0", "generation_mode": mode, "segments": compiled,
        "dynamic_segment_count": len(moving),
        "stable_observation_between_dynamic_seconds": 1.0 if is_long_take else 0.0,
        "unplanned_time_policy": "LOCKED_CAMERA", "selection_gate": "PASS_MOTIVATED_ONLY",
    }


def compile_combat_continuity_ladders(
    contract: dict, beats: list[dict], camera_contract: dict
) -> tuple[str, list[dict]]:
    """Bind causal evidence and a resolving composition across combat beats."""
    plans = require(contract.get("continuity_ladders"), "combat continuity_ladders are required")
    if not isinstance(plans, list) or not 1 <= len(plans) <= 3:
        raise ValueError("combat continuity_ladders must contain 1 to 3 plans")
    camera_segments = camera_contract["segments"]
    compiled, seen_methods = [], set()
    for index, row in enumerate(plans, start=1):
        method_id = require(row.get("method_id"), f"continuity ladder {index} method_id is required")
        method = COMBAT_CONTINUITY_METHODS.get(method_id)
        if method is None:
            raise ValueError(f"unsupported combat continuity method: {method_id}")
        if method_id in seen_methods:
            raise ValueError(f"duplicate combat continuity method: {method_id}")
        seen_methods.add(method_id)
        beat_indexes = require(row.get("beat_indexes"), f"continuity ladder {index} beat_indexes are required")
        if (
            not isinstance(beat_indexes, list)
            or len(beat_indexes) < method["min_beats"]
            or beat_indexes != sorted(set(beat_indexes))
            or any(not isinstance(value, int) or not 1 <= value <= len(beats) for value in beat_indexes)
        ):
            raise ValueError(
                f"continuity method {method_id} requires at least {method['min_beats']} ordered valid beat indexes"
            )
        evidence_rows = require(
            row.get("evidence_beats"), f"continuity ladder {index} evidence_beats are required"
        )
        if not isinstance(evidence_rows, list) or not evidence_rows:
            raise ValueError(f"continuity method {method_id} evidence_beats must be non-empty")
        evidence_types, evidence_signatures, compiled_evidence = set(), set(), []
        for evidence_index, evidence in enumerate(evidence_rows, start=1):
            beat_index = int(require(
                evidence.get("action_beat_index"),
                f"continuity ladder {index} evidence {evidence_index} action_beat_index is required",
            ))
            evidence_type = require(
                evidence.get("evidence_type"),
                f"continuity ladder {index} evidence {evidence_index} evidence_type is required",
            )
            if beat_index not in beat_indexes:
                raise ValueError(f"continuity method {method_id} evidence must bind one of its beat_indexes")
            if evidence_type not in COMBAT_EVIDENCE_TYPES:
                raise ValueError(f"unsupported combat continuity evidence type: {evidence_type}")
            signature = (beat_index, evidence_type)
            if signature in evidence_signatures:
                raise ValueError(f"duplicate combat continuity evidence: {signature}")
            evidence_signatures.add(signature)
            evidence_types.add(evidence_type)
            compiled_evidence.append({
                "action_beat_index": beat_index,
                "evidence_type": evidence_type,
                "visible_result": require(
                    evidence.get("visible_result"),
                    f"continuity ladder {index} evidence {evidence_index} visible_result is required",
                ),
            })
        missing = sorted(method["required_evidence"] - evidence_types)
        if missing:
            raise ValueError(f"continuity method {method_id} missing required evidence: {','.join(missing)}")

        measurement = row.get("spatial_measurement")
        if method["measurement_required"]:
            measurement = require(measurement, f"continuity method {method_id} spatial_measurement is required")
        compiled_measurement = None
        if measurement:
            kind = require(measurement.get("kind"), f"continuity method {method_id} measurement kind is required")
            unit = require(measurement.get("unit"), f"continuity method {method_id} measurement unit is required")
            value = float(require(measurement.get("value"), f"continuity method {method_id} measurement value is required"))
            if kind not in COMBAT_MEASUREMENT_KINDS or unit not in COMBAT_MEASUREMENT_UNITS or value <= 0:
                raise ValueError(f"continuity method {method_id} has invalid spatial_measurement")
            compiled_measurement = {"kind": kind, "value": value, "unit": unit}

        promoted_state_id = row.get("promoted_state_id")
        if method.get("state_promotion_required") and not promoted_state_id:
            raise ValueError(f"continuity method {method_id} promoted_state_id is required")
        resolution = require(
            row.get("camera_resolution"), f"continuity method {method_id} camera_resolution is required"
        )
        resolution_technique = require(
            resolution.get("technique_id"), f"continuity method {method_id} camera technique is required"
        )
        resolution_beat = int(require(
            resolution.get("action_beat_index"), f"continuity method {method_id} camera beat is required"
        ))
        if resolution_beat not in beat_indexes or not any(
            segment["technique_id"] == resolution_technique
            and segment["action_beat_index"] == resolution_beat
            for segment in camera_segments
        ):
            raise ValueError(
                f"continuity method {method_id} camera_resolution must match a declared camera segment"
            )
        compiled.append({
            "method_id": method_id, "label": method["label"], "beat_indexes": beat_indexes,
            "entry_state": require(row.get("entry_state"), f"continuity method {method_id} entry_state is required"),
            "exit_state": require(row.get("exit_state"), f"continuity method {method_id} exit_state is required"),
            "persistent_evidence": compiled_evidence,
            "spatial_measurement": compiled_measurement,
            "promoted_state_id": promoted_state_id,
            "final_relational_frame": require(
                row.get("final_relational_frame"),
                f"continuity method {method_id} final_relational_frame is required",
            ),
            "camera_resolution": {
                "technique_id": resolution_technique,
                "action_beat_index": resolution_beat,
                "narrative_purpose": require(
                    resolution.get("narrative_purpose"),
                    f"continuity method {method_id} camera narrative_purpose is required",
                ),
            },
        })

    handoffs = []
    for previous, current in zip(compiled, compiled[1:]):
        previous_last_beat = previous["beat_indexes"][-1]
        current_first_beat = current["beat_indexes"][0]
        if current_first_beat < previous_last_beat:
            raise ValueError(
                "combat continuity ladders must be ordered by their causal handoff beats"
            )
        if previous["exit_state"] != current["entry_state"]:
            raise ValueError(
                "combat continuity ladder state handoff mismatch: "
                f"{previous['method_id']} exits {previous['exit_state']} but "
                f"{current['method_id']} enters {current['entry_state']}"
            )
        handoff = {
            "from_method_id": previous["method_id"],
            "to_method_id": current["method_id"],
            "shared_state": previous["exit_state"],
            "from_action_beat_index": previous_last_beat,
            "to_action_beat_index": current_first_beat,
        }
        previous["handoff_to_next"] = handoff
        current["handoff_from_previous"] = handoff
        handoffs.append(handoff)

    rows = []
    for row in compiled:
        evidence = "、".join(
            f"动作拍{item['action_beat_index']}的{item['evidence_type']}={item['visible_result']}"
            for item in row["persistent_evidence"]
        )
        measurement = row["spatial_measurement"]
        measured = (
            f"；量化变化={measurement['kind']} {measurement['value']:g}{measurement['unit']}"
            if measurement else ""
        )
        promoted = f"；状态晋升={row['promoted_state_id']}" if row["promoted_state_id"] else ""
        rows.append(
            f"{row['label']}({row['method_id']})绑定动作拍{','.join(map(str, row['beat_indexes']))}："
            f"入口={row['entry_state']}；持续证据={evidence}{measured}{promoted}；出口={row['exit_state']}；"
            f"收束构图={row['final_relational_frame']}；镜头只用{row['camera_resolution']['technique_id']}"
            f"完成{row['camera_resolution']['narrative_purpose']}"
        )
    prompt = (
        "\n【因果连续性阶梯】" + "；".join(rows) + "。"
        "每个接触必须留下可见后果，证据跨拍保留，量化空间变化不得凭空重置；"
        "最后一帧必须恢复人物、受力方向、路径与环境结果的关系读取。"
    )
    if handoffs:
        prompt += "跨阶梯状态交接：" + "；".join(
            f"{row['from_method_id']}@动作拍{row['from_action_beat_index']}"
            f"→{row['to_method_id']}@动作拍{row['to_action_beat_index']}"
            f"共享状态={row['shared_state']}"
            for row in handoffs
        ) + "。后续阶梯必须继承上一阶梯出口状态，禁止人物、伤势、道具或空间关系重置。"
    return prompt, compiled


def _verified_asset(asset: dict, label: str) -> tuple[Path, str]:
    path = Path(require(asset.get("path"), f"{label} path is required"))
    expected_sha = require(asset.get("sha256"), f"{label} sha256 is required")
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError(f"{label} SHA mismatch")
    return path, actual_sha


def compile_episode_character_registry(spec: dict, actor_roster: list[str]) -> tuple[str, dict]:
    """Freeze source-grounded, unique character assets before video compilation."""
    registry = require(spec.get("episode_character_registry"), "episode_character_registry is required before video generation")
    if registry.get("frozen_before_video_generation") is not True:
        raise ValueError("episode character registry must be frozen before video generation")
    library_path, library_sha = _verified_asset(
        require(registry.get("historical_library_manifest"), "historical_library_manifest is required"),
        "historical character library manifest",
    )
    rows = require(registry.get("characters"), "episode character registry characters are required")
    if not isinstance(rows, list):
        raise ValueError("episode character registry characters must be a list")
    by_actor = {str(row.get("actor", "")).strip(): row for row in rows}
    if set(by_actor) != set(actor_roster) or len(by_actor) != len(rows):
        raise ValueError("episode character registry must exactly cover actor_roster without duplicates")

    compiled, visual_shas, voice_shas = [], set(), set()
    for actor in actor_roster:
        row = by_actor[actor]
        source = require(row.get("canonical_character_brief"), f"character {actor} canonical_character_brief is required")
        for field in ("source_locator", "era", "age", "social_role", "wardrobe", "face", "hair", "voice"):
            require(source.get(field), f"character {actor} canonical brief {field} is required")
        if source.get("writer_completed_before_asset_generation") is not True:
            raise ValueError(f"character {actor} brief must be completed by the writer before asset generation")
        visual_path, visual_sha = _verified_asset(
            require(row.get("visual_reference"), f"character {actor} visual_reference is required"),
            f"character {actor} visual reference",
        )
        voice_path, voice_sha = _verified_asset(
            require(row.get("voice_reference"), f"character {actor} voice_reference is required"),
            f"character {actor} voice reference",
        )
        if visual_sha in visual_shas or voice_sha in voice_shas:
            raise ValueError("episode characters must use distinct visual and voice references")
        visual_shas.add(visual_sha)
        voice_shas.add(voice_sha)
        audit = require(row.get("historical_uniqueness_audit"), f"character {actor} historical_uniqueness_audit is required")
        if audit.get("status") != "PASS":
            raise ValueError(f"character {actor} historical uniqueness audit must PASS")
        exception = audit.get("narrative_similarity_exception")
        for dimension, limit in CHARACTER_SIMILARITY_LIMITS.items():
            score = float(require(audit.get(f"{dimension}_similarity"), f"character {actor} {dimension}_similarity is required"))
            if score > limit and not exception:
                raise ValueError(f"character {actor} is too similar to historical library in {dimension}")
        compiled.append(
            f"{actor}=原文定位{source['source_locator']}；年代{source['era']}；年龄{source['age']}；身份{source['social_role']}；"
            f"视觉参考{visual_path}；服装{source['wardrobe']}；脸型{source['face']}；发型{source['hair']}；声音{source['voice']}；"
            "镜头全程不得换装、换脸、换发型或借用其他角色声音"
        )

    pairs = registry.get("pairwise_uniqueness_audit")
    if not isinstance(pairs, list):
        raise ValueError("pairwise_uniqueness_audit must be a list")
    expected_pairs = {tuple(sorted((a, b))) for index, a in enumerate(actor_roster) for b in actor_roster[index + 1:]}
    actual_pairs = set()
    for row in pairs:
        pair = tuple(sorted((require(row.get("actor_a"), "pair actor_a is required"), require(row.get("actor_b"), "pair actor_b is required"))))
        actual_pairs.add(pair)
        for dimension, limit in CHARACTER_SIMILARITY_LIMITS.items():
            if float(require(row.get(f"{dimension}_similarity"), f"pair {pair} {dimension}_similarity is required")) > limit:
                raise ValueError(f"episode characters {pair} are too similar in {dimension}")
    if actual_pairs != expected_pairs or len(actual_pairs) != len(pairs):
        raise ValueError("pairwise_uniqueness_audit must cover every actor pair exactly once")

    prompt = "\n【本集角色资产冻结】" + "；".join(compiled) + "。禁止临时随机生成人物，禁止同一角色黑衣变灰衣。"
    return prompt, {
        "historical_library_manifest": {"path": str(library_path), "sha256": library_sha},
        "character_visual_shas": sorted(visual_shas),
        "character_voice_shas": sorted(voice_shas),
        "pairwise_audit_count": len(pairs),
        "frozen_before_video_generation": True,
    }


def compile_combat_choreography_contract(spec: dict, actor_roster: list[str]) -> tuple[str, dict | None]:
    """Compile combat as timed physical exchanges with identity and outcome locks."""
    contract = spec.get("combat_choreography_contract")
    if not contract:
        return "", None
    participants = require(contract.get("participants"), "combat participants are required")
    if not isinstance(participants, list) or len(participants) < 2:
        raise ValueError("combat requires at least two participants")
    names, reference_shas, participant_rows = [], set(), []
    for index, row in enumerate(participants, start=1):
        name = require(row.get("actor"), f"combat participant {index} actor is required")
        if name not in actor_roster:
            raise ValueError(f"combat participant is absent from actor_roster: {name}")
        names.append(name)
        require(row.get("role"), f"combat participant {name} role is required")
        reference = require(
            row.get("independent_identity_reference"),
            f"combat participant {name} requires independent_identity_reference",
        )
        reference_path = Path(require(reference.get("path"), f"combat participant {name} identity path is required"))
        reference_sha = require(reference.get("sha256"), f"combat participant {name} identity sha256 is required")
        if not reference_path.is_file():
            raise ValueError(f"combat participant {name} identity reference does not exist: {reference_path}")
        actual_sha = hashlib.sha256(reference_path.read_bytes()).hexdigest()
        if actual_sha != reference_sha:
            raise ValueError(f"combat participant {name} identity reference SHA mismatch")
        if actual_sha in reference_shas:
            raise ValueError("combat participants must use distinct identity references")
        reference_shas.add(actual_sha)
        wardrobe = require(row.get("wardrobe_silhouette"), f"combat participant {name} wardrobe_silhouette is required")
        face = require(row.get("face_geometry"), f"combat participant {name} face_geometry is required")
        first_second = require(row.get("first_second_displacement"), f"combat participant {name} first_second_displacement is required")
        participant_rows.append(
            f"{name}={row['role']}，身份参考{reference_path}，服装轮廓{wardrobe}，脸型{face}，开场1秒位移{first_second}"
        )
    if len(set(names)) != len(names):
        raise ValueError("combat participants contain duplicates")

    reference_video = require(contract.get("action_reference_video"), "combat action_reference_video is required")
    require(reference_video.get("url"), "combat action_reference_video.url is required")
    if reference_video.get("reference_scope") != "CHOREOGRAPHY_TIMING_AND_BODY_MECHANICS_ONLY":
        raise ValueError("combat action reference scope must exclude identity, wardrobe and outcome")

    beats = require(contract.get("beats"), "combat beats are required")
    if not isinstance(beats, list) or not 3 <= len(beats) <= 6:
        raise ValueError("combat requires 3 to 6 timed beats")
    cursor, signatures, beat_rows = 0.0, set(), []
    required_fields = (
        "initiator", "target", "action", "contact_point", "force_direction",
        "footwork", "target_reaction", "end_state",
    )
    for index, beat in enumerate(beats, start=1):
        start = float(require(beat.get("start_seconds"), f"combat beat {index} start_seconds is required"))
        end = float(require(beat.get("end_seconds"), f"combat beat {index} end_seconds is required"))
        if abs(start - cursor) > 0.01 or end <= start or end - start > 3.0:
            raise ValueError(f"combat beat {index} must be contiguous and no longer than 3 seconds")
        values = {field: require(beat.get(field), f"combat beat {index} {field} is required") for field in required_fields}
        if values["initiator"] not in names or values["target"] not in names:
            raise ValueError(f"combat beat {index} initiator and target must be participants")
        if values["initiator"] == values["target"]:
            raise ValueError(f"combat beat {index} initiator and target must differ")
        signature = (values["initiator"], values["target"], values["action"], values["contact_point"])
        if signature in signatures:
            raise ValueError(f"combat beat {index} repeats an earlier exchange")
        signatures.add(signature)
        beat_rows.append(
            f"{start:g}-{end:g}秒：{values['initiator']}以{values['footwork']}完成{values['action']}，"
            f"接触{values['target']}的{values['contact_point']}，力量朝{values['force_direction']}；"
            f"{values['target']}因受力{values['target_reaction']}；终态{values['end_state']}"
        )
        cursor = end
    if abs(cursor - float(spec["duration_seconds"])) > 0.01:
        raise ValueError("combat beats must cover the full generation duration")

    camera_prompt, camera_contract = compile_combat_camera_language(
        contract, beats, float(spec["duration_seconds"]), spec["mode"]
    )
    continuity_prompt, continuity_ladders = compile_combat_continuity_ladders(
        contract, beats, camera_contract
    )

    winner = require(contract.get("winner"), "combat winner is required")
    restrained = require(contract.get("restrained_actor"), "combat restrained_actor is required")
    if winner not in names or restrained not in names or winner == restrained:
        raise ValueError("combat winner and restrained_actor must be distinct participants")
    terminal = require(contract.get("terminal_identity_hold"), "combat terminal_identity_hold is required")
    prompt = (
        "\n【打斗身份硬锁】" + "；".join(participant_rows) + "。"
        "@视频1只参考动作节拍、真实重心转移和受力反馈，不继承人物、服装、场景、胜负或运镜。"
        "\n【逐拍动作因果】" + "；".join(beat_rows) + "。"
        + camera_prompt
        + continuity_prompt
        + f"\n【胜负终态硬锁】胜者={winner}；被制服者={restrained}；终局画面={terminal}。"
        "禁止互换身份、禁止攻守倒置、禁止让胜者被按住、禁止橡皮肢体、假摔、无接触挥舞和重复招式。"
    )
    return prompt, {
        "participants": names,
        "identity_reference_shas": sorted(reference_shas),
        "action_reference_video": reference_video,
        "beats": beats,
        "winner": winner,
        "restrained_actor": restrained,
        "terminal_identity_hold": terminal,
        "camera_language_plan": camera_contract,
        "continuity_ladders": continuity_ladders,
        "continuity_adapter": "HELL_GRIND_COMBAT_CONTINUITY_PROMPT_RULE_ADAPTER_V7",
    }


def require(value, message: str):
    if value is None or value == "" or value == []:
        raise ValueError(message)
    return value


def enforce_post_only_glyph_contract(prompt: str, spec: dict) -> list[str]:
    """Keep exact audience-facing strings out of provider visual prompts."""
    if spec.get("text_layer_post_only") is not True:
        return []
    glyphs = require(
        spec.get("post_only_glyphs"),
        "text_layer_post_only requires post_only_glyphs",
    )
    if not isinstance(glyphs, list) or any(not str(value).strip() for value in glyphs):
        raise ValueError("post_only_glyphs must be a non-empty list of exact strings")
    leaked = sorted({str(value).strip() for value in glyphs if str(value).strip() in prompt})
    if leaked:
        raise ValueError(
            "PROMPT_LITERAL_GLYPH_SCAN failed; replace exact audience text with opaque PROP_IDs: "
            + ",".join(leaked)
        )
    return [str(value).strip() for value in glyphs]


def enforce_dialogue_mode_consistency(spec: dict) -> str:
    """Reject a silent visual contract that is later presented as lip-synced speech."""
    shots = spec.get("shots") or []
    dialogues = [shot["dialogue"] for shot in shots if shot.get("dialogue")]
    voice_over = spec.get("voice_over_manifest") or []
    declared = spec.get("dialogue_mode")
    mode = declared or ("ON_CAMERA_NATIVE_LIP_SYNC" if dialogues else "NO_DIALOGUE")
    if mode not in DIALOGUE_MODES:
        raise ValueError(f"unsupported dialogue_mode: {mode}")

    authored = json.dumps(spec, ensure_ascii=False).lower()
    silent_markers = [marker for marker in SILENT_PERFORMANCE_MARKERS if marker.lower() in authored]
    if dialogues and silent_markers:
        raise ValueError(
            "DIALOGUE_MODE_CONSISTENCY failed; on-camera dialogue conflicts with silent performance: "
            + ",".join(silent_markers)
        )
    if mode == "ON_CAMERA_NATIVE_LIP_SYNC":
        if not dialogues:
            raise ValueError("ON_CAMERA_NATIVE_LIP_SYNC requires shot dialogue")
        entities = {entity.get("name"): entity for entity in (spec.get("entities") or [])}
        for row in dialogues:
            speaker = require(row.get("speaker"), "dialogue speaker is required")
            entity = entities.get(speaker)
            if not entity or not entity.get("audio_ref"):
                raise ValueError(
                    f"ON_CAMERA_NATIVE_LIP_SYNC requires an audio_ref for visible speaker {speaker}"
                )
    elif mode == "CLOSED_MOUTH_VOICE_OVER":
        if dialogues:
            raise ValueError(
                "CLOSED_MOUTH_VOICE_OVER forbids shot dialogue; move exact speech to voice_over_manifest"
            )
        if not isinstance(voice_over, list) or not voice_over:
            raise ValueError("CLOSED_MOUTH_VOICE_OVER requires voice_over_manifest")
        for index, row in enumerate(voice_over, start=1):
            require(row.get("speaker"), f"voice_over_manifest {index} speaker is required")
            require(row.get("text"), f"voice_over_manifest {index} text is required")
            require(row.get("audio_source"), f"voice_over_manifest {index} audio_source is required")
    elif dialogues or voice_over:
        raise ValueError("NO_DIALOGUE forbids shot dialogue and voice_over_manifest")
    return mode


def compile_expressive_voice_contract(spec: dict, mode: str) -> tuple[str, dict | None]:
    """Compile line-level psychology and prosody before native speech generation."""
    if mode == "NO_DIALOGUE":
        return "", None
    dialogues = [shot["dialogue"] for shot in (spec.get("shots") or []) if shot.get("dialogue")]
    rows = dialogues if mode == "ON_CAMERA_NATIVE_LIP_SYNC" else (spec.get("voice_over_manifest") or [])
    profiles, speaker_signatures = [], {}
    for index, row in enumerate(rows, start=1):
        speaker = require(row.get("speaker"), f"dialogue line {index} speaker is required")
        text = require(row.get("text"), f"dialogue line {index} text is required")
        values = {
            field: require(row.get(field), f"dialogue line {index} {field} is required by expressive voice contract")
            for field in EXPRESSIVE_DIALOGUE_FIELDS
        }
        intensity = int(values["emotion_intensity"])
        if not 1 <= intensity <= 5:
            raise ValueError(f"dialogue line {index} emotion_intensity must be between 1 and 5")
        emphasis = values["emphasis_words"]
        if not isinstance(emphasis, list) or not emphasis or any(not str(word).strip() for word in emphasis):
            raise ValueError(f"dialogue line {index} emphasis_words must be a non-empty list")
        missing_words = [str(word) for word in emphasis if str(word) not in text]
        if missing_words:
            raise ValueError(f"dialogue line {index} emphasis_words are absent from text: {','.join(missing_words)}")
        signature = (
            values["psychological_state"], values["emotion"], intensity, values["pace"],
            values["pause_map"], len(emphasis), values["volume_arc"],
            values["breath_pattern"], values["delivery_transition"],
        )
        speaker_signatures.setdefault(speaker, []).append(signature)
        profiles.append({
            "line_index": index, "speaker": speaker,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            **values, "emotion_intensity": intensity,
        })
    if spec.get("allow_deliberately_monotone_performance") is not True:
        for speaker, signatures in speaker_signatures.items():
            if len(signatures) > 1 and len(set(signatures)) == 1:
                raise ValueError(
                    f"EXPRESSIVE_VOICE_VARIATION failed; {speaker} repeats one emotion/prosody signature across every line"
                )
    prompt_rows = [
        f"第{row['line_index']}句{row['speaker']}：心理{row['psychological_state']}；情绪{row['emotion']}"
        f"(强度{row['emotion_intensity']}/5)；语速{row['pace']}；停连{row['pause_map']}；"
        f"重音{'、'.join(row['emphasis_words'])}；音量{row['volume_arc']}；气息{row['breath_pattern']}；"
        f"句内转变{row['delivery_transition']}；身体同步{row['body_sync']}"
        for row in profiles
    ]
    prompt = (
        "\n【逐句心理与语音表演硬锁】保持每个角色既定声纹，不改变年龄、音色和口音；"
        + "；".join(prompt_rows)
        + "。语气必须由当句心理和事件变化驱动，禁止新闻播报腔、全句同强度、全场同语速、机械匀速、无重音、无停连。"
    )
    return prompt, {
        "profiles": profiles,
        "speaker_profile_counts": {speaker: len(rows) for speaker, rows in speaker_signatures.items()},
        "variation_gate": "PASS",
        "voice_identity_preserved": True,
    }


def load_local_lora_memory(mode: str, path: Path = DEFAULT_LOCAL_LORA_MEMORY) -> tuple[list[dict], str | None]:
    """Load admitted LoRA-ready examples whose guards apply before paid generation."""
    # Only the configured production dataset participates in centralized sync.
    # Callers may pass a temporary or episode-local memory file containing
    # pending defensive rewrites that are valid for compilation but are not
    # ADMITTED training rows and must never be staged to the collector.
    if path.expanduser().resolve() == DEFAULT_LOCAL_LORA_MEMORY.expanduser().resolve():
        auto_sync(path)
    if not path.is_file():
        return [], None
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") not in {"ADMITTED", "ACTIVE_REWRITE_PENDING_POSITIVE"} or mode not in (row.get("applicable_modes") or []):
            continue
        require(row.get("sample_id"), f"local LoRA memory line {line_number} sample_id is required")
        require(row.get("compiler_guard_clause"), f"local LoRA memory line {line_number} compiler_guard_clause is required")
        rows.append(row)
    return rows, hashlib.sha256(path.read_bytes()).hexdigest()


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
        line += (
            f" {speaker}清楚说：{{{text}}} 只有{speaker}口型运动；"
            f"心理{dialogue['psychological_state']}，情绪{dialogue['emotion']}强度{dialogue['emotion_intensity']}/5，"
            f"语速{dialogue['pace']}，停连{dialogue['pause_map']}，重音{'、'.join(dialogue['emphasis_words'])}，"
            f"音量{dialogue['volume_arc']}，气息{dialogue['breath_pattern']}，"
            f"句内转变{dialogue['delivery_transition']}，身体同步{dialogue['body_sync']}。"
        )
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


def compile_actor_motion_coverage(frame: dict, index: int, actor_roster: list[str]) -> tuple[str, list[dict]]:
    """Require an explicit motion or offscreen disposition for every actor."""
    coverage = require(frame.get("actor_motion"), f"keyframe {index} actor_motion is required")
    if not isinstance(coverage, dict):
        raise ValueError(f"keyframe {index} actor_motion must be an object keyed by actor")
    expected, actual = set(actor_roster), set(coverage)
    if actual != expected:
        missing = ",".join(sorted(expected - actual)) or "none"
        extra = ",".join(sorted(actual - expected)) or "none"
        raise ValueError(f"keyframe {index} actor_motion must cover the full actor roster; missing={missing}; extra={extra}")
    compiled, prompt_rows = [], []
    for actor in actor_roster:
        row = coverage[actor]
        if not isinstance(row, dict):
            raise ValueError(f"keyframe {index} actor_motion.{actor} must be an object")
        visible = row.get("visible")
        if visible is False:
            reason = require(row.get("offscreen_reason"), f"keyframe {index} offscreen actor {actor} requires offscreen_reason")
            compiled.append({"actor": actor, "visible": False, "offscreen_reason": reason})
            prompt_rows.append(f"{actor}=已离开画面，原因是{reason}")
            continue
        if visible is not True:
            raise ValueError(f"keyframe {index} actor_motion.{actor}.visible must be true or false")
        micro = require(row.get("continuous_micro_action"), f"keyframe {index} visible actor {actor} requires continuous_micro_action")
        reaction = require(row.get("event_reaction"), f"keyframe {index} visible actor {actor} requires event_reaction")
        motion_cues = require(row.get("motion_cues"), f"keyframe {index} visible actor {actor} requires motion_cues")
        if not isinstance(motion_cues, list) or len(motion_cues) < 2 or any(not str(cue).strip() for cue in motion_cues):
            raise ValueError(f"keyframe {index} visible actor {actor} requires at least two positive motion_cues")
        authored_motion = f"{micro} {reaction} {' '.join(str(cue) for cue in motion_cues)}".lower()
        static_terms = [term for term in STATIC_ACTOR_MOTION_TERMS if term.lower() in authored_motion]
        if static_terms:
            raise ValueError(
                f"keyframe {index} visible actor {actor} authors a static pose instead of continuous motion: {','.join(static_terms)}"
            )
        compiled.append({
            "actor": actor, "visible": True, "continuous_micro_action": micro,
            "event_reaction": reaction, "motion_cues": [str(cue) for cue in motion_cues],
        })
        prompt_rows.append(
            f"{actor}=持续动作({micro})，事件反应({reaction})，可见动势({'、'.join(str(cue) for cue in motion_cues)})"
        )
    return "；".join(prompt_rows), compiled


def compile_multi_keyframe_long_take(spec: dict) -> tuple[str, dict]:
    """Compile a spatially continuous 15-second Omni shot from ordered keyframes."""
    duration = require(spec.get("duration_seconds"), "duration_seconds is required")
    if duration != 15:
        raise ValueError("multi_keyframe_long_take requires exactly 15 seconds")
    if spec.get("model") != "seedance-2.0-fast":
        raise ValueError("multi_keyframe_long_take requires seedance-2.0-fast")
    if spec.get("resolution") != "720p":
        raise ValueError("multi_keyframe_long_take requires provider-native 720p for seedance-2.0-fast")
    if spec.get("real_time_1x") is not True:
        raise ValueError("multi_keyframe_long_take requires real_time_1x=true")
    camera_policy = require(spec.get("camera_motion_policy"), "camera_motion_policy is required")
    if camera_policy != "MOTIVATED_TRACK_OR_LOCKED_AXIS_NO_SWAY_NO_ORBIT_NO_ROAM":
        raise ValueError("camera_motion_policy must forbid sway, orbit and roam")
    keyframes = require(spec.get("keyframes"), "keyframes are required")
    if not 3 <= len(keyframes) <= 9:
        raise ValueError("multi_keyframe_long_take requires 3 to 9 keyframes")
    actor_roster = require(spec.get("actor_roster"), "multi_keyframe_long_take actor_roster is required")
    if not isinstance(actor_roster, list) or len(actor_roster) < 1 or any(not str(actor).strip() for actor in actor_roster):
        raise ValueError("multi_keyframe_long_take actor_roster must be a non-empty list")
    actor_roster = [str(actor).strip() for actor in actor_roster]
    if len(set(actor_roster)) != len(actor_roster):
        raise ValueError("multi_keyframe_long_take actor_roster contains duplicates")
    character_prompt, character_registry = compile_episode_character_registry(spec, actor_roster)
    combat_prompt, combat_contract = compile_combat_choreography_contract(spec, actor_roster)
    times, timeline, compiled_frames = [], [], []
    states = set()
    previous_zone = previous_state = None
    previous_camera_side = None
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
        actor_motion_prompt, actor_motion = compile_actor_motion_coverage(frame, index, actor_roster)
        reference_role = require(frame.get("reference_role"), f"keyframe {index} reference_role is required")
        camera_side = require(frame.get("camera_side"), f"keyframe {index} camera_side is required")
        camera_position = require(frame.get("camera_position"), f"keyframe {index} camera_position is required")
        camera_facing = require(frame.get("camera_facing"), f"keyframe {index} camera_facing is required")
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
            require(transition.get("continuous_camera_path"), f"keyframe {index} continuous_camera_path is required")
            if transition.get("camera_axis_reset_allowed") is not False:
                raise ValueError(f"keyframe {index} must explicitly forbid camera-axis reset")
            if transition.get("camera_from_side") != previous_camera_side:
                raise ValueError(f"keyframe {index} camera_from_side does not match the previous keyframe")
            if transition.get("camera_to_side") != camera_side:
                raise ValueError(f"keyframe {index} camera_to_side does not match the current keyframe")
            travel = float(require(transition.get("camera_travel_distance_m"), f"keyframe {index} camera_travel_distance_m is required"))
            axis_change = float(require(transition.get("camera_axis_change_degrees"), f"keyframe {index} camera_axis_change_degrees is required"))
            interval = timestamp - times[-1]
            if travel / interval > 2.5:
                raise ValueError(f"keyframe {index} camera path exceeds 2.5 m/s")
            if axis_change > 90:
                raise ValueError(f"keyframe {index} camera axis change exceeds 90 degrees")
            if transition.get("kind") == "SAME_APERTURE_CROSSING":
                if transition.get("camera_path_kind") != "FOLLOW_THROUGH_SAME_APERTURE":
                    raise ValueError(f"keyframe {index} crossing requires FOLLOW_THROUGH_SAME_APERTURE camera path")
                if transition.get("camera_crosses_with_subjects") is not True:
                    raise ValueError(f"keyframe {index} crossing camera must move with the subjects")
                if transition.get("camera_path_aperture_id") != transition.get("aperture_id"):
                    raise ValueError(f"keyframe {index} camera aperture does not match subject aperture")
        timeline.append(
            f"{timestamp:g}秒到达@图片{index}：该图只负责{reference_role}；{event}；人物站位：{blocking}；"
            f"逐人动作覆盖：{actor_motion_prompt}；"
            f"摄影机位于{camera_side}，位置{camera_position}，朝向{camera_facing}；"
            f"必须继承{preserve}；不得从该图继承{'、'.join(reject_inheritance)}；"
            f"动作状态从{previous_state or '镜头起始'}连续推进到{state}。"
        )
        compiled_frames.append({
            "reference": f"@图片{index}", "timestamp_seconds": timestamp,
            "image_path": str(image_path), "image_sha256": actual_sha,
            "state_token": state, "location_zone": zone,
            "reference_role": reference_role,
            "actor_motion": actor_motion,
            "camera_side": camera_side, "camera_position": camera_position,
            "camera_facing": camera_facing, "preserve_from_previous": preserve,
            "do_not_inherit": reject_inheritance, "transition_from_previous": transition,
        })
        times.append(timestamp)
        previous_zone, previous_state, previous_camera_side = zone, state, camera_side
    if times[0] != 0 or times[-1] != 15:
        raise ValueError("keyframe timeline must start at 0 seconds and end at 15 seconds")
    subject_lock = require(spec.get("subject_and_identity_lock"), "subject_and_identity_lock is required")
    spatial_lock = require(spec.get("spatial_continuity_lock"), "spatial_continuity_lock is required")
    action_axis = require(spec.get("action_axis"), "action_axis is required")
    negative = require(spec.get("negative_constraints"), "negative_constraints are required")
    memory_path = Path(spec.get("local_lora_memory_path") or DEFAULT_LOCAL_LORA_MEMORY)
    memory_rows, memory_sha = load_local_lora_memory("multi_keyframe_long_take", memory_path)
    memory_clause = ""
    if memory_rows:
        memory_clause = "\n【本地LoRA失败记忆预编译】" + "；".join(
            f"{row['sample_id']}：{row['compiler_guard_clause']}" for row in memory_rows
        ) + "。"
    prompt = (
        f"15秒一镜到底，Seedance 2.0 Fast，供应商原生720p，实时1倍速。{subject_lock}\n"
        f"动作轴：{action_axis}。空间连续硬锁：{spatial_lock}。\n" + "\n".join(timeline)
        + memory_clause
        + character_prompt
        + combat_prompt
        + f"\n镜头只为跟清楚动作因果而移动；禁止无动机摇摆、smooth roam、slow push、orbit、overhead reveal、慢动作、插帧、动作重演、人物瞬移、机位重置、空间跳切。禁止：{' / '.join(negative)}。\n"
    )
    post_only_glyphs = enforce_post_only_glyph_contract(prompt, spec)
    return prompt, {
        "schema": "qingshan.seedance2_multi_keyframe_long_take.v1",
        "mode": "multi_keyframe_long_take", "route": "/api/v1/generation/omni-video",
        "contract": "15s_ordered_multi_keyframe_spatial_continuity", "duration_seconds": 15,
        "model": spec["model"], "resolution": spec["resolution"], "real_time_1x": True,
        "camera_motion_policy": camera_policy, "keyframes": compiled_frames,
        "actor_roster": actor_roster,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "local_lora_memory": {
            "path": str(memory_path), "sha256": memory_sha,
            "applied_sample_ids": [row["sample_id"] for row in memory_rows],
            "precompiled_before_paid_generation": True,
        },
        "gates": ["ORDERED_KEYFRAME_SHA_BINDING", "REFERENCE_ROLE_AND_INHERITANCE_SCOPE",
                  "NO_REPEATED_ACTION_STATE", "NO_TELEPORT_OR_ACTION_RESET",
                  "SAME_APERTURE_LOCATION_CROSSING", "REAL_TIME_1X",
                  "NO_UNMOTIVATED_CAMERA_MOTION", "ADJACENT_CAMERA_TRAJECTORY_REACHABILITY",
                  "FULL_VISIBLE_ACTOR_MOTION_COVERAGE",
                  "EPISODE_CHARACTER_ASSETS_FROZEN_AND_UNIQUE",
                  "COMBAT_IDENTITY_CHOREOGRAPHY_AND_OUTCOME" if combat_contract else "NO_COMBAT_CONTRACT",
                  "COMBAT_CAUSAL_CONTINUITY_LADDER" if combat_contract else "NO_COMBAT_CONTINUITY_CONTRACT",
                  "LOCAL_LORA_FAILURE_MEMORY_PRECOMPILED",
                  "PROMPT_LITERAL_GLYPH_SCAN" if spec.get("text_layer_post_only") else "NO_POST_ONLY_GLYPH_CONTRACT"],
        "text_layer_post_only": bool(spec.get("text_layer_post_only")),
        "post_only_glyph_count": len(post_only_glyphs),
        "episode_character_registry": character_registry,
        "combat_choreography_contract": combat_contract,
    }


def compile_prompt(spec: dict) -> tuple[str, dict]:
    mode = require(spec.get("mode"), "mode is required")
    if mode not in MODES:
        raise ValueError(f"unsupported mode: {mode}")
    dialogue_mode = enforce_dialogue_mode_consistency(spec)
    expressive_voice_prompt, expressive_voice_contract = compile_expressive_voice_contract(spec, dialogue_mode)
    if mode == "multi_keyframe_long_take":
        prompt, manifest = compile_multi_keyframe_long_take(spec)
        manifest["dialogue_mode"] = dialogue_mode
        manifest["dialogue_mode_gate"] = "PASS"
        manifest["expressive_voice_contract"] = expressive_voice_contract
        manifest["gates"].append("EXPRESSIVE_VOICE_PSYCHOLOGY_AND_PROSODY")
        prompt += expressive_voice_prompt
        manifest["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return prompt, manifest
    entities = require(spec.get("entities"), "entities are required")
    shots = require(spec.get("shots"), "shots are required")
    header = entity_header(entities, spec.get("setting"))
    combat_prompt, combat_contract = "", None
    character_registry = None
    if spec.get("combat_choreography_contract"):
        actor_roster = require(spec.get("actor_roster"), "combat actor_roster is required")
        character_prompt, character_registry = compile_episode_character_registry(spec, actor_roster)
        combat_prompt, combat_contract = compile_combat_choreography_contract(spec, actor_roster)
        header += character_prompt
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

    cinematic_prompt, cinematic_contract = compile_cinematic_shot_language_contract(spec, len(shots))
    prompt = f"{header}\n\n{body}{combat_prompt}{expressive_voice_prompt}{cinematic_prompt}\n\n{tail.strip()}\n"
    post_only_glyphs = enforce_post_only_glyph_contract(prompt, spec)
    manifest = {
        "schema": "qingshan.seedance2_prompt_compilation.v2" if visual_contract else "qingshan.seedance2_prompt_compilation.v1",
        "mode": mode,
        "route": route,
        "contract": contract,
        "shot_count": len(shots),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "text_layer_post_only": bool(spec.get("text_layer_post_only")),
        "post_only_glyph_count": len(post_only_glyphs),
        "dialogue_mode": dialogue_mode,
        "dialogue_mode_gate": "PASS",
        "expressive_voice_contract": expressive_voice_contract,
        "episode_character_registry": character_registry,
        "combat_choreography_contract": combat_contract,
        "combat_camera_language_gate": "PASS_MOTIVATED_ONLY" if combat_contract else "NOT_APPLICABLE",
        "combat_continuity_ladder_gate": "PASS_EVIDENCE_AND_RELATIONAL_CLOSE" if combat_contract else "NOT_APPLICABLE",
        "cinematic_shot_language_contract": cinematic_contract,
        "cinematic_shot_language_gate": "PASS_SECTIONED_AND_TIME_CODED" if cinematic_contract else "NOT_APPLICABLE",
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
