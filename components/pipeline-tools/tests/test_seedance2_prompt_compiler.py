import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.seedance2_prompt_compiler import (
    compile_camera_style_plan,
    compile_prompt,
    default_local_lora_memory,
    load_local_lora_memory,
)


class Seedance2PromptCompilerTest(unittest.TestCase):
    def test_default_memory_resolves_installed_production_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            production = root / "workflow/local_lora"
            production.mkdir(parents=True)
            module = root / "tools/seedance2_prompt_compiler.py"
            module.parent.mkdir(exist_ok=True)
            with mock.patch("tools.seedance2_prompt_compiler.__file__", str(module)):
                self.assertEqual(
                    default_local_lora_memory(),
                    (production / "seedance2_prompt_failure_training.jsonl").resolve(),
                )

    def dialogue(self, speaker="陈迹", text="谁提的？", **overrides):
        row = {
            "speaker": speaker, "text": text,
            "psychological_state": "疑点突然对上但仍压住结论",
            "emotion": "克制警觉", "emotion_intensity": 3,
            "pace": "前慢后紧", "pause_map": "主语后短停，结尾收紧",
            "emphasis_words": [text.rstrip("？。！")[-2:]],
            "volume_arc": "低声起、末字略降", "breath_pattern": "浅吸后整句呼出",
            "delivery_transition": "试探转确认", "body_sync": "抬眼时开口，末字手指停住",
        }
        row.update(overrides)
        return row

    def base(self):
        return {
            "entities": [
                {"name": "陈迹", "token": "char_1", "description": "克制男声", "audio_ref": "@音频1"},
                {"name": "账房", "token": "scene_1", "description": "晴朗黄昏 merchant account room"},
            ],
            "setting": "同一时空，人物和道具连续",
            "style_and_negative": "写实；无字幕、水印、Logo、BGM。",
        }

    def test_storyboard_requires_and_emits_distinct_shot_contracts(self):
        spec = self.base()
        spec.update({
            "mode": "storyboard",
            "shots": [
                {"framing": "远景", "camera": "推近", "action": "陈迹入画", "expression_arc": "平静到警觉", "cut_reason": "动作接"},
                {"framing": "近景", "camera": "固定", "action": "陈迹抬眼", "expression_arc": "警觉到确认", "dialogue": self.dialogue(), "sound": "算盘停", "cut_reason": "视线接"},
            ],
        })
        prompt, manifest = compile_prompt(spec)
        self.assertIn("镜头1", prompt)
        self.assertIn("镜头2", prompt)
        self.assertIn("{谁提的？}", prompt)
        self.assertEqual(manifest["route"], "/api/v1/generation/omni-video")
        self.assertEqual(manifest["shot_count"], 2)

    def test_licensed_cinematic_shot_language_compiles_sectioned_time_coded_prompt(self):
        hero = "负伤同伴：深色战衣，右肩破损渗血，面部与发型保持参考资产一致。"
        battlefield = "暴雪战场：灰蓝天空，强横风向由画面右侧吹向左侧，地面脚印连续。"
        spec = self.base()
        spec.update({
            "mode": "storyboard", "duration_seconds": 8,
            "shots": [
                {"framing": "远景", "camera": "固定长焦", "action": "人物坠入雪原", "expression_arc": "冷漠到冲击", "cut_reason": "冲击接"},
                {"framing": "中景", "camera": "跟拍", "action": "同伴负伤起身奔跑", "expression_arc": "震惊到决断", "cut_reason": "动作接"},
            ],
            "cinematic_shot_language_contract": {
                "version": "1.0.0",
                "locked_descriptors": [
                    {"id": "@hero_wounded", "kind": "character_state", "text": hero, "text_sha256": hashlib.sha256(hero.encode()).hexdigest(), "paste_policy": "VERBATIM_EVERY_SHOT", "stress_test_status": "PASS"},
                    {"id": "@snow_battlefield", "kind": "location_state", "text": battlefield, "text_sha256": hashlib.sha256(battlefield.encode()).hexdigest(), "paste_policy": "VERBATIM_EVERY_SHOT", "stress_test_status": "PASS"},
                ],
                "segments": [
                    {"shot_index": 1, "start_seconds": 0, "end_seconds": 5, "narrative_purpose": "用远距离冲击证明尺度", "entry_state": "人物已在坠落", "exit_state": "雪柱与碎片形成可见结果", "descriptor_ids": ["@snow_battlefield"], "camera_motivation": "让冲击尺度可读", "geometry": {"subject_anchor": "人物占画面高度不足十分之一", "camera_side": "战场外侧", "axis_relation": "沿坠落轴", "scale_anchor": "雪柱高于人物五倍"}, "audio": {"diegetic": "风啸、撞击、碎片落雪", "dialogue_policy": "NO_DIALOGUE"}},
                    {"shot_index": 2, "start_seconds": 5, "end_seconds": 8, "narrative_purpose": "将旁观者转为行动者", "entry_state": "同伴负伤伏地", "exit_state": "同伴向落点奔跑", "descriptor_ids": ["@hero_wounded", "@snow_battlefield"], "camera_motivation": "读清起身到奔跑的连续路径", "geometry": {"subject_anchor": "伤肩与支撑手", "camera_side": "战场外侧", "axis_relation": "沿坠落轴", "scale_anchor": "人物与脚印路径同框"}, "audio": {"diegetic": "喘息、踏雪、衣料", "dialogue_policy": "NO_DIALOGUE"}},
                ],
                "shot_information_ladder": {
                    "coverage_policy": "ONE_PRIMARY_INFORMATION_UNIT_PER_SHOT",
                    "shots": [
                        {"shot_index": 1, "information_unit_id": "impact-scale", "information_type": "consequence", "subject_action": "人物撞入雪原", "visible_evidence": "雪柱和碎片超过人物高度", "visible_consequence": "地面保留冲击坑与落雪", "shot_scale": "大远景", "lens_mm": 35, "camera_role": "建立冲击尺度与落点", "entry_state": "人物已在坠落", "exit_state": "雪柱与碎片形成可见结果"},
                        {"shot_index": 2, "information_unit_id": "witness-activation", "information_type": "reaction", "subject_action": "负伤同伴起身奔向落点", "visible_evidence": "伤肩、支撑手和连续脚印同框", "shot_scale": "中景", "lens_mm": 50, "camera_role": "读取旁观者转为行动者", "entry_state": "同伴负伤伏地", "exit_state": "同伴向落点奔跑"},
                    ],
                },
                "spatial_axis_ledger": {
                    "coverage_policy": "PRESERVE_SCREEN_DIRECTION_EYELINE_AND_BACKGROUND",
                    "shots": [
                        {"shot_index": 1, "axis_id": "battlefield-axis", "axis_side": "south-bank", "axis_transition": "ESTABLISH_AXIS", "subject_descriptor_id": "@snow_battlefield", "subject_screen_region": "screen_center", "gaze_direction": "down", "eyeline_target_descriptor_id": "@snow_battlefield", "background_anchor_descriptor_id": "@snow_battlefield", "background_screen_region": "full_background", "camera_side": "战场外侧", "axis_relation": "沿坠落轴", "entry_state": "人物已在坠落", "exit_state": "雪柱与碎片形成可见结果"},
                        {"shot_index": 2, "axis_id": "battlefield-axis", "axis_side": "south-bank", "axis_transition": "HOLD_AXIS", "subject_descriptor_id": "@hero_wounded", "subject_screen_region": "screen_left", "gaze_direction": "screen_right", "eyeline_target_descriptor_id": "@snow_battlefield", "background_anchor_descriptor_id": "@snow_battlefield", "background_screen_region": "right_depth", "camera_side": "战场外侧", "axis_relation": "沿坠落轴", "entry_state": "同伴负伤伏地", "exit_state": "同伴向落点奔跑"},
                    ],
                },
                "cross_cut_state_ledger": {
                    "reset_policy": "NO_UNDECLARED_RESET_ACROSS_CUTS",
                    "tracks": [{
                        "track_id": "blizzard-direction-and-ground-trace",
                        "continuity_class": "environment_state",
                        "subject_descriptor_id": "@snow_battlefield",
                        "segment_states": [
                            {"shot_index": 1, "entry_state": "wind-right-to-left-with-unbroken-snow", "exit_state": "wind-right-to-left-with-impact-trace", "visible_evidence": "雪柱向左偏移并留下连续落雪"},
                            {"shot_index": 2, "entry_state": "wind-right-to-left-with-impact-trace", "exit_state": "wind-right-to-left-with-impact-and-footprint-traces", "visible_evidence": "旧雪柱仍在后景，新增脚印沿同一风向延伸"},
                        ],
                        "terminal_state": "wind-right-to-left-with-impact-and-footprint-traces",
                    }],
                },
                "key_rules": ["复杂动作从已经发生的起势进入", "一次只改变一个可验证变量"],
                "atmosphere_state": "暴雪、地雾和风向在每镜连续",
                "style_prefix": "写实24fps，克制手持，只在动作需要时移动",
                "negative_constraints": ["无动机环绕", "用风格词替代物理结果"],
            },
        })
        prompt, manifest = compile_prompt(spec)
        self.assertIn("【LOCKED DESCRIPTORS｜逐镜原文复用】", prompt)
        self.assertIn("【SCENE PURPOSE / GEOMETRY / TIME-CODED CUTS】", prompt)
        self.assertIn("0-5秒 / 镜头1", prompt)
        self.assertIn("【CAMERA STYLE PROFILE｜运镜文化风格标签】", prompt)
        self.assertIn("运镜风格=美式好莱坞[AMERICAN_HOLLYWOOD]", prompt)
        self.assertIn("【SHOT INFORMATION LADDER｜一镜一信息】", prompt)
        self.assertIn("【SPATIAL AXIS LEDGER｜屏幕方位、视线与背景锚点】", prompt)
        self.assertIn("【CROSS-CUT STATE LEDGER｜跨镜状态账本】", prompt)
        self.assertIn(hero, prompt)
        self.assertEqual(manifest["cinematic_shot_language_gate"], "PASS_SECTIONED_AND_TIME_CODED")
        self.assertTrue(manifest["cinematic_shot_language_contract"]["full_duration_coverage"])
        ledger = manifest["cinematic_shot_language_contract"]["cross_cut_state_ledger"]
        self.assertEqual(ledger["adapter"], "HELL_GRIND_CROSS_CUT_STATE_LEDGER_PROMPT_RULE_ADAPTER_V8")
        information = manifest["cinematic_shot_language_contract"]["shot_information_ladder"]
        self.assertEqual(information["adapter"], "HELL_GRIND_SHOT_INFORMATION_LADDER_PROMPT_RULE_ADAPTER_V9")
        spatial = manifest["cinematic_shot_language_contract"]["spatial_axis_ledger"]
        self.assertEqual(spatial["adapter"], "HELL_GRIND_SPATIAL_AXIS_PROMPT_RULE_ADAPTER_V10")
        style_plan = manifest["cinematic_shot_language_contract"]["camera_style_plan"]
        self.assertEqual(style_plan["selection_policy"], "PER_SHOT_GENRE_AWARE")
        self.assertEqual(style_plan["shots"][0]["style_profile_id"], "AMERICAN_HOLLYWOOD")
        self.assertEqual(style_plan["shots"][0]["style_label_zh"], "美式好莱坞")
        self.assertIn("EASTERN_WUXIA", style_plan["reserved_not_adapted_profiles"])

    def test_camera_style_plan_rejects_reserved_unadapted_style(self):
        segments = [{"shot_index": 1}]
        contract = {
            "camera_style_plan": {
                "selection_policy": "PER_SHOT_GENRE_AWARE",
                "shots": [{
                    "shot_index": 1,
                    "style_profile_id": "EASTERN_WUXIA",
                    "selection_reason": "武侠题材",
                }],
            },
        }
        with self.assertRaisesRegex(ValueError, "not adapted for production"):
            compile_camera_style_plan(contract, segments)

    def test_cinematic_shot_language_rejects_undeclared_axis_cross(self):
        hero = "角色锁定描述"
        spec = self.base()
        spec.update({
            "mode": "storyboard", "duration_seconds": 8,
            "shots": [
                {"framing": "中景", "camera": "固定", "action": "A", "expression_arc": "A到B", "cut_reason": "视线接"},
                {"framing": "近景", "camera": "固定", "action": "B", "expression_arc": "B到C", "cut_reason": "视线接"},
            ],
            "cinematic_shot_language_contract": {
                "version": "1.0.0",
                "locked_descriptors": [{"id": "@hero", "kind": "character", "text": hero, "text_sha256": hashlib.sha256(hero.encode()).hexdigest(), "paste_policy": "VERBATIM_EVERY_SHOT", "stress_test_status": "PASS"}],
                "segments": [
                    {"shot_index": 1, "start_seconds": 0, "end_seconds": 4, "narrative_purpose": "A", "entry_state": "A", "exit_state": "B", "descriptor_ids": ["@hero"], "camera_motivation": "A", "geometry": {"subject_anchor": "A", "camera_side": "南侧", "axis_relation": "同一对话轴", "scale_anchor": "A"}, "audio": {"diegetic": "A", "dialogue_policy": "NO_DIALOGUE"}},
                    {"shot_index": 2, "start_seconds": 4, "end_seconds": 8, "narrative_purpose": "B", "entry_state": "B", "exit_state": "C", "descriptor_ids": ["@hero"], "camera_motivation": "B", "geometry": {"subject_anchor": "B", "camera_side": "北侧", "axis_relation": "同一对话轴", "scale_anchor": "B"}, "audio": {"diegetic": "B", "dialogue_policy": "NO_DIALOGUE"}},
                ],
                "spatial_axis_ledger": {
                    "coverage_policy": "PRESERVE_SCREEN_DIRECTION_EYELINE_AND_BACKGROUND",
                    "shots": [
                        {"shot_index": 1, "axis_id": "dialogue-axis", "axis_side": "south", "axis_transition": "ESTABLISH_AXIS", "subject_descriptor_id": "@hero", "subject_screen_region": "screen_left", "gaze_direction": "screen_right", "eyeline_target_descriptor_id": "@hero", "background_anchor_descriptor_id": "@hero", "background_screen_region": "right_depth", "camera_side": "南侧", "axis_relation": "同一对话轴", "entry_state": "A", "exit_state": "B"},
                        {"shot_index": 2, "axis_id": "dialogue-axis", "axis_side": "north", "axis_transition": "HOLD_AXIS", "subject_descriptor_id": "@hero", "subject_screen_region": "screen_right", "gaze_direction": "screen_left", "eyeline_target_descriptor_id": "@hero", "background_anchor_descriptor_id": "@hero", "background_screen_region": "left_depth", "camera_side": "北侧", "axis_relation": "同一对话轴", "entry_state": "B", "exit_state": "C"},
                    ],
                },
                "key_rules": ["保持轴线"], "atmosphere_state": "连续", "style_prefix": "写实", "negative_constraints": ["未声明越轴"],
            },
        })
        with self.assertRaisesRegex(ValueError, "undeclared axis cross"):
            compile_prompt(spec)

    def test_cinematic_shot_language_rejects_duplicate_information_unit(self):
        hero = "角色锁定描述"
        spec = self.base()
        spec.update({
            "mode": "storyboard", "duration_seconds": 8,
            "shots": [
                {"framing": "远景", "camera": "固定", "action": "A", "expression_arc": "A到B", "cut_reason": "动作接"},
                {"framing": "近景", "camera": "固定", "action": "B", "expression_arc": "B到C", "cut_reason": "视线接"},
            ],
            "cinematic_shot_language_contract": {
                "version": "1.0.0",
                "locked_descriptors": [{"id": "@hero", "kind": "character", "text": hero, "text_sha256": hashlib.sha256(hero.encode()).hexdigest(), "paste_policy": "VERBATIM_EVERY_SHOT", "stress_test_status": "PASS"}],
                "segments": [
                    {"shot_index": 1, "start_seconds": 0, "end_seconds": 4, "narrative_purpose": "A", "entry_state": "A", "exit_state": "B", "descriptor_ids": ["@hero"], "camera_motivation": "A", "geometry": {"subject_anchor": "A", "camera_side": "A", "axis_relation": "A", "scale_anchor": "A"}, "audio": {"diegetic": "A", "dialogue_policy": "NO_DIALOGUE"}},
                    {"shot_index": 2, "start_seconds": 4, "end_seconds": 8, "narrative_purpose": "B", "entry_state": "B", "exit_state": "C", "descriptor_ids": ["@hero"], "camera_motivation": "B", "geometry": {"subject_anchor": "B", "camera_side": "B", "axis_relation": "B", "scale_anchor": "B"}, "audio": {"diegetic": "B", "dialogue_policy": "NO_DIALOGUE"}},
                ],
                "shot_information_ladder": {
                    "coverage_policy": "ONE_PRIMARY_INFORMATION_UNIT_PER_SHOT",
                    "shots": [
                        {"shot_index": 1, "information_unit_id": "same-picture", "information_type": "orientation", "subject_action": "A", "visible_evidence": "A", "shot_scale": "远景", "lens_mm": 35, "camera_role": "A", "entry_state": "A", "exit_state": "B"},
                        {"shot_index": 2, "information_unit_id": "same-picture", "information_type": "reaction", "subject_action": "B", "visible_evidence": "B", "shot_scale": "近景", "lens_mm": 85, "camera_role": "B", "entry_state": "B", "exit_state": "C"},
                    ],
                },
                "key_rules": ["一镜一目的"], "atmosphere_state": "连续", "style_prefix": "写实", "negative_constraints": ["重复动作画面"],
            },
        })
        with self.assertRaisesRegex(ValueError, "duplicate shot information unit"):
            compile_prompt(spec)

    def test_cinematic_shot_language_rejects_cross_cut_state_reset(self):
        hero = "角色锁定描述"
        spec = self.base()
        spec.update({
            "mode": "storyboard", "duration_seconds": 8,
            "shots": [
                {"framing": "远景", "camera": "固定", "action": "A", "expression_arc": "A到B", "cut_reason": "动作接"},
                {"framing": "近景", "camera": "固定", "action": "B", "expression_arc": "B到C", "cut_reason": "视线接"},
            ],
            "cinematic_shot_language_contract": {
                "version": "1.0.0",
                "locked_descriptors": [{"id": "@hero", "kind": "character", "text": hero, "text_sha256": hashlib.sha256(hero.encode()).hexdigest(), "paste_policy": "VERBATIM_EVERY_SHOT", "stress_test_status": "PASS"}],
                "segments": [
                    {"shot_index": 1, "start_seconds": 0, "end_seconds": 4, "narrative_purpose": "A", "entry_state": "A", "exit_state": "B", "descriptor_ids": ["@hero"], "camera_motivation": "A", "geometry": {"subject_anchor": "A", "camera_side": "A", "axis_relation": "A", "scale_anchor": "A"}, "audio": {"diegetic": "A", "dialogue_policy": "NO_DIALOGUE"}},
                    {"shot_index": 2, "start_seconds": 4, "end_seconds": 8, "narrative_purpose": "B", "entry_state": "B", "exit_state": "C", "descriptor_ids": ["@hero"], "camera_motivation": "B", "geometry": {"subject_anchor": "B", "camera_side": "B", "axis_relation": "B", "scale_anchor": "B"}, "audio": {"diegetic": "B", "dialogue_policy": "NO_DIALOGUE"}},
                ],
                "cross_cut_state_ledger": {
                    "reset_policy": "NO_UNDECLARED_RESET_ACROSS_CUTS",
                    "tracks": [{
                        "track_id": "hero-prop-state", "continuity_class": "prop_state",
                        "subject_descriptor_id": "@hero",
                        "segment_states": [
                            {"shot_index": 1, "entry_state": "prop-raised", "exit_state": "prop-damaged", "visible_evidence": "裂口可见"},
                            {"shot_index": 2, "entry_state": "prop-pristine", "exit_state": "prop-lowered", "visible_evidence": "道具仍在手中"},
                        ],
                        "terminal_state": "prop-lowered",
                    }],
                },
                "key_rules": ["一镜一目的"], "atmosphere_state": "连续", "style_prefix": "写实", "negative_constraints": ["跳切"],
            },
        })
        with self.assertRaisesRegex(ValueError, "cross-cut state handoff mismatch"):
            compile_prompt(spec)

    def test_cinematic_shot_language_rejects_timeline_gap(self):
        hero = "角色锁定描述"
        spec = self.base()
        spec.update({
            "mode": "storyboard", "duration_seconds": 8,
            "shots": [
                {"framing": "远景", "camera": "固定", "action": "A", "expression_arc": "A到B", "cut_reason": "动作接"},
                {"framing": "近景", "camera": "固定", "action": "B", "expression_arc": "B到C", "cut_reason": "视线接"},
            ],
            "cinematic_shot_language_contract": {
                "version": "1.0.0",
                "locked_descriptors": [{"id": "@hero", "kind": "character", "text": hero, "text_sha256": hashlib.sha256(hero.encode()).hexdigest(), "paste_policy": "VERBATIM_EVERY_SHOT", "stress_test_status": "PASS"}],
                "segments": [
                    {"shot_index": 1, "start_seconds": 0, "end_seconds": 3, "narrative_purpose": "A", "entry_state": "A", "exit_state": "B", "descriptor_ids": ["@hero"], "camera_motivation": "A", "geometry": {"subject_anchor": "A", "camera_side": "A", "axis_relation": "A", "scale_anchor": "A"}, "audio": {"diegetic": "A", "dialogue_policy": "NO_DIALOGUE"}},
                    {"shot_index": 2, "start_seconds": 4, "end_seconds": 8, "narrative_purpose": "B", "entry_state": "B", "exit_state": "C", "descriptor_ids": ["@hero"], "camera_motivation": "B", "geometry": {"subject_anchor": "B", "camera_side": "B", "axis_relation": "B", "scale_anchor": "B"}, "audio": {"diegetic": "B", "dialogue_policy": "NO_DIALOGUE"}},
                ],
                "key_rules": ["一镜一目的"], "atmosphere_state": "连续", "style_prefix": "写实", "negative_constraints": ["跳切"],
            },
        })
        with self.assertRaisesRegex(ValueError, "contiguous"):
            compile_prompt(spec)

    def test_storyboard_rejects_missing_cut_reason(self):
        spec = self.base()
        spec.update({"mode": "storyboard", "shots": [
            {"framing": "远景", "camera": "推近", "action": "A", "expression_arc": "A到B", "cut_reason": "动作接"},
            {"framing": "近景", "camera": "固定", "action": "B", "expression_arc": "B到C"},
        ]})
        with self.assertRaisesRegex(ValueError, "cut_reason"):
            compile_prompt(spec)

    def test_long_take_requires_one_shot_and_first_last_route(self):
        spec = self.base()
        spec.update({
            "mode": "continuous_long_take",
            "start_frame": "start.png",
            "end_frame": "end.png",
            "shots": [{"framing": "双人中景", "camera": "连续环绕", "action": "完成整段表演", "expression_arc": "戒备到震动"}],
        })
        prompt, manifest = compile_prompt(spec)
        self.assertIn("15秒一镜到底", prompt)
        self.assertEqual(manifest["route"], "/api/v1/generation/image-to-video")

    def test_long_take_rejects_numbered_multi_shot_input(self):
        spec = self.base()
        spec.update({
            "mode": "continuous_long_take",
            "start_frame": "start.png",
            "end_frame": "end.png",
            "shots": [
                {"framing": "中景", "camera": "推近", "action": "A", "expression_arc": "A到B"},
                {"framing": "近景", "camera": "固定", "action": "B", "expression_arc": "B到C"},
            ],
        })
        with self.assertRaisesRegex(ValueError, "exactly one shot"):
            compile_prompt(spec)

    def test_visual_benchmark_contract_compiles_script_lock_and_cinematic_fields(self):
        spec = self.base()
        visual = {
            "duration_seconds": 9,
            "shot_scale": "大远景",
            "lens_intent": "24mm空间揭示",
            "camera_height": "高位",
            "camera_motion": "缓降推进",
            "depth_layers": ["前景松枝", "中景马队", "后景山门"],
            "scale_anchor": "山门下六名骑手",
            "palette": {"dominant": "青绿", "contrast": "石白", "accent": "朱红"},
            "key_light": "侧逆日光",
            "atmosphere": "薄雾",
            "environmental_motion": ["旗帜随风"],
            "material_detail": ["风化石", "织物旗帜"],
            "still_prompt_contract": "单一连续画面",
            "video_motion_contract": "马队前进时镜头缓降",
            "negative_constraints": ["拼贴", "分屏", "夜景", "月光", "塑料皮肤"],
        }
        spec.update({
            "mode": "storyboard",
            "visual_benchmark_contract": {"version": "1.0.0"},
            "scene_lock": {"location": "山门", "time_of_day": "白天", "weather": "晴", "event": "马队抵达"},
            "shots": [
                dict(visual, framing="大远景", camera="缓降推进", action="马队穿过山门", expression_arc="戒备到震撼", cut_reason="空间接"),
                dict(visual, duration_seconds=5, shot_scale="中近景", framing="中近景", camera="固定", action="陈迹抬眼", expression_arc="震撼到警觉", cut_reason="视线接"),
            ],
        })
        prompt, manifest = compile_prompt(spec)
        self.assertIn("剧本场景硬锁", prompt)
        self.assertIn("尺度锚点", prompt)
        self.assertEqual(manifest["schema"], "qingshan.seedance2_prompt_compilation.v2")
        self.assertTrue(manifest["script_state_locked"])

    def test_visual_benchmark_contract_rejects_fixed_out_of_range_duration(self):
        spec = self.base()
        spec.update({
            "mode": "storyboard",
            "visual_benchmark_contract": {"version": "1.0.0"},
            "scene_lock": {"location": "山门", "time_of_day": "白天", "weather": "晴", "event": "抵达"},
            "shots": [
                {"framing": "远景", "camera": "推进", "action": "A", "expression_arc": "A到B", "cut_reason": "动作接", "duration_seconds": 3},
                {"framing": "近景", "camera": "固定", "action": "B", "expression_arc": "B到C", "cut_reason": "视线接", "duration_seconds": 5},
            ],
        })
        with self.assertRaisesRegex(ValueError, "shot 1 shot_scale"):
            compile_prompt(spec)

    def test_text_layer_post_only_rejects_literal_label_echo(self):
        spec = self.base()
        spec.update({
            "mode": "storyboard",
            "text_layer_post_only": True,
            "post_only_glyphs": ["安神药屉"],
            "shots": [
                {"framing": "中景", "camera": "固定", "action": "打开安神药屉", "expression_arc": "警觉到确认", "cut_reason": "动作接"},
                {"framing": "近景", "camera": "固定", "action": "检查空白纸张", "expression_arc": "确认到凝重", "cut_reason": "视线接"},
            ],
        })
        with self.assertRaisesRegex(ValueError, "PROMPT_LITERAL_GLYPH_SCAN"):
            compile_prompt(spec)

    def test_text_layer_post_only_accepts_opaque_prop_id(self):
        spec = self.base()
        spec.update({
            "mode": "storyboard",
            "text_layer_post_only": True,
            "post_only_glyphs": ["安神药屉"],
            "shots": [
                {"framing": "中景", "camera": "固定", "action": "打开DRAWER_TARGET_A", "expression_arc": "警觉到确认", "cut_reason": "动作接"},
                {"framing": "近景", "camera": "固定", "action": "检查空白纸张", "expression_arc": "确认到凝重", "cut_reason": "视线接"},
            ],
        })
        _prompt, manifest = compile_prompt(spec)
        self.assertTrue(manifest["text_layer_post_only"])
        self.assertEqual(manifest["post_only_glyph_count"], 1)

    def test_dialogue_mode_rejects_silent_visual_contract_with_on_camera_speech(self):
        spec = self.base()
        spec.update({
            "mode": "storyboard",
            "dialogue_mode": "ON_CAMERA_NATIVE_LIP_SYNC",
            "shots": [
                {"framing": "中景", "camera": "固定", "action": "陈迹全程不开口检查账册", "expression_arc": "迟疑到警觉", "cut_reason": "动作接"},
                {"framing": "近景", "camera": "固定", "action": "陈迹抬眼", "expression_arc": "警觉到确认", "dialogue": self.dialogue(text="不是巧合。", emphasis_words=["巧合"]), "cut_reason": "视线接"},
            ],
        })
        with self.assertRaisesRegex(ValueError, "DIALOGUE_MODE_CONSISTENCY"):
            compile_prompt(spec)

    def test_closed_mouth_voice_over_stays_out_of_visual_prompt(self):
        spec = self.base()
        spec.update({
            "mode": "storyboard",
            "dialogue_mode": "CLOSED_MOUTH_VOICE_OVER",
            "voice_over_manifest": [dict(self.dialogue(text="不是巧合。", emphasis_words=["巧合"]), audio_source="voice.wav")],
            "shots": [
                {"framing": "中景", "camera": "固定", "action": "陈迹闭口检查账册", "expression_arc": "迟疑到警觉", "cut_reason": "动作接"},
                {"framing": "近景", "camera": "固定", "action": "陈迹闭口抬眼", "expression_arc": "警觉到确认", "cut_reason": "视线接"},
            ],
        })
        prompt, manifest = compile_prompt(spec)
        self.assertNotIn("不是巧合", prompt)
        self.assertEqual(manifest["dialogue_mode"], "CLOSED_MOUTH_VOICE_OVER")
        self.assertEqual(manifest["dialogue_mode_gate"], "PASS")

    def test_dialogue_requires_line_level_psychology_and_prosody(self):
        spec = self.base()
        spec.update({
            "mode": "storyboard", "dialogue_mode": "ON_CAMERA_NATIVE_LIP_SYNC",
            "shots": [
                {"framing": "中景", "camera": "固定", "action": "陈迹翻账", "expression_arc": "平静到警觉", "cut_reason": "动作接"},
                {"framing": "近景", "camera": "固定", "action": "陈迹抬眼", "expression_arc": "警觉到确认", "dialogue": {"speaker": "陈迹", "text": "不是巧合。"}, "cut_reason": "视线接"},
            ],
        })
        with self.assertRaisesRegex(ValueError, "psychological_state"):
            compile_prompt(spec)

    def test_repeated_identical_prosody_signature_is_rejected(self):
        line = self.dialogue(text="不是巧合。", emphasis_words=["巧合"])
        spec = self.base()
        spec.update({
            "mode": "storyboard", "dialogue_mode": "ON_CAMERA_NATIVE_LIP_SYNC",
            "shots": [
                {"framing": "中景", "camera": "固定", "action": "陈迹翻账", "expression_arc": "平静到警觉", "dialogue": line, "cut_reason": "动作接"},
                {"framing": "近景", "camera": "固定", "action": "陈迹抬眼", "expression_arc": "警觉到确认", "dialogue": dict(line, text="并非偶然。", emphasis_words=["偶然"]), "cut_reason": "视线接"},
            ],
        })
        with self.assertRaisesRegex(ValueError, "EXPRESSIVE_VOICE_VARIATION"):
            compile_prompt(spec)

    def test_changed_psychology_and_prosody_are_compiled(self):
        spec = self.base()
        spec.update({
            "mode": "storyboard", "dialogue_mode": "ON_CAMERA_NATIVE_LIP_SYNC",
            "shots": [
                {"framing": "中景", "camera": "固定", "action": "陈迹翻账", "expression_arc": "平静到警觉", "dialogue": self.dialogue(text="不是巧合。", emphasis_words=["巧合"]), "cut_reason": "动作接"},
                {"framing": "近景", "camera": "固定", "action": "陈迹抬眼", "expression_arc": "警觉到决定", "dialogue": self.dialogue(text="去药房。", psychological_state="已确认内鬼路径并立即决断", emotion="低压决断", emotion_intensity=4, pace="短促", pause_map="无前停，句末截断", emphasis_words=["药房"], volume_arc="低声但更实", breath_pattern="短吸短呼", delivery_transition="确认转命令", body_sync="起身同时开口，句末迈步"), "cut_reason": "动作接"},
            ],
        })
        prompt, manifest = compile_prompt(spec)
        self.assertIn("逐句心理与语音表演硬锁", prompt)
        self.assertIn("低压决断", prompt)
        self.assertEqual(manifest["expressive_voice_contract"]["variation_gate"], "PASS")

    def test_pending_defensive_rewrite_is_precompiled_without_claiming_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = Path(directory) / "memory.jsonl"
            memory.write_text(json.dumps({
                "sample_id": "LORA-PENDING-001",
                "status": "ACTIVE_REWRITE_PENDING_POSITIVE",
                "applicable_modes": ["storyboard"],
                "compiler_guard_clause": "strip exact label glyphs",
            }) + "\n", encoding="utf-8")
            rows, _sha = load_local_lora_memory("storyboard", memory)
            self.assertEqual([row["sample_id"] for row in rows], ["LORA-PENDING-001"])
            self.assertNotIn("accepted_asset_sha256", rows[0])


if __name__ == "__main__":
    unittest.main()
