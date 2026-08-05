import json
import tempfile
import unittest
from pathlib import Path

from tools.seedance2_prompt_compiler import compile_prompt, load_local_lora_memory


class Seedance2PromptCompilerTest(unittest.TestCase):
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
