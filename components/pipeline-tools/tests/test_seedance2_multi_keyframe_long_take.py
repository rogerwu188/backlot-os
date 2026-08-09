import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.seedance2_prompt_compiler import COMBAT_CONTINUITY_METHODS, compile_prompt


class MultiKeyframeLongTakeTest(unittest.TestCase):
    def frame(self, path, timestamp, state, zone="room", transition=None):
        path.write_bytes(f"frame-{timestamp}".encode())
        row = {
            "timestamp_seconds": timestamp, "image_path": str(path),
            "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "state_token": state, "location_zone": zone,
            "actor_blocking": state, "action_event": state,
            "reference_role": state, "preserve_from_previous": "identity and location",
            "camera_side": zone, "camera_position": "fixed three-quarter position",
            "camera_facing": "toward the same aperture",
            "do_not_inherit": ["text", "watermark"],
            "actor_motion": {
                "lead": {"visible": True, "continuous_micro_action": "steps through the action",
                         "event_reaction": "shifts weight toward the aperture", "motion_cues": ["breath", "footfall"]},
                "witness": {"visible": True, "continuous_micro_action": "tracks the lead with the eyes",
                            "event_reaction": "recoils half a step from the impact", "motion_cues": ["blink", "weight shift"]},
            },
        }
        if transition is not None:
            row["transition_from_previous"] = transition
        return row

    def transition(self, kind="CONTINUOUS_ACTION", camera_from="room", camera_to="room"):
        return {
            "kind": kind, "teleport_allowed": False, "action_reset_allowed": False,
            "continuous_camera_path": "locked axis", "camera_axis_reset_allowed": False,
            "camera_from_side": camera_from, "camera_to_side": camera_to,
            "camera_travel_distance_m": 0, "camera_axis_change_degrees": 0,
        }

    def spec(self, keyframes):
        root = Path(keyframes[0]["image_path"]).parent
        library = root / "historical-library.json"
        library.write_text("{}")
        characters = []
        for index, actor in enumerate(("lead", "witness")):
            visual = root / f"{actor}-visual"
            voice = root / f"{actor}-voice"
            visual.write_bytes(f"visual-{actor}".encode())
            voice.write_bytes(f"voice-{actor}".encode())
            characters.append({
                "actor": actor,
                "canonical_character_brief": {
                    "source_locator": f"scene-{index}", "era": "historical test era", "age": "adult",
                    "social_role": f"role-{index}", "wardrobe": f"wardrobe-{index}",
                    "face": f"face-{index}", "hair": f"hair-{index}", "voice": f"voice-{index}",
                    "writer_completed_before_asset_generation": True,
                },
                "visual_reference": {"path": str(visual), "sha256": hashlib.sha256(visual.read_bytes()).hexdigest()},
                "voice_reference": {"path": str(voice), "sha256": hashlib.sha256(voice.read_bytes()).hexdigest()},
                "historical_uniqueness_audit": {
                    "status": "PASS", "nearest_character_id": f"old-{index}",
                    "face_similarity": 0.2, "wardrobe_similarity": 0.2, "voice_similarity": 0.2,
                },
            })
        return {
            "mode": "multi_keyframe_long_take", "duration_seconds": 15,
            "model": "seedance-2.0-fast", "resolution": "720p", "real_time_1x": True,
            "camera_motion_policy": "MOTIVATED_TRACK_OR_LOCKED_AXIS_NO_SWAY_NO_ORBIT_NO_ROAM",
            "subject_and_identity_lock": "same people", "spatial_continuity_lock": "same breach",
            "actor_roster": ["lead", "witness"],
            "episode_character_registry": {
                "frozen_before_video_generation": True,
                "historical_library_manifest": {"path": str(library), "sha256": hashlib.sha256(library.read_bytes()).hexdigest()},
                "characters": characters,
                "pairwise_uniqueness_audit": [{
                    "actor_a": "lead", "actor_b": "witness",
                    "face_similarity": 0.2, "wardrobe_similarity": 0.2, "voice_similarity": 0.2,
                }],
            },
            "action_axis": "escape", "negative_constraints": ["slow motion"], "keyframes": keyframes,
        }

    def combat_contract(self, root):
        lead = root / "lead-identity"
        opponent = root / "opponent-identity"
        lead.write_bytes(b"lead")
        opponent.write_bytes(b"opponent")
        return {
            "participants": [
                {"actor": "lead", "role": "interceptor",
                 "independent_identity_reference": {"path": str(lead), "sha256": hashlib.sha256(lead.read_bytes()).hexdigest()},
                 "wardrobe_silhouette": "light fitted jacket", "face_geometry": "round jaw and wide brows",
                 "first_second_displacement": "steps left by half a metre and raises both forearms"},
                {"actor": "witness", "role": "intruder",
                 "independent_identity_reference": {"path": str(opponent), "sha256": hashlib.sha256(opponent.read_bytes()).hexdigest()},
                 "wardrobe_silhouette": "dark sleeveless work vest", "face_geometry": "long jaw and broken nose",
                 "first_second_displacement": "lands forward by one metre and turns the right shoulder"},
            ],
            "action_reference_video": {"url": "https://example.test/reference.mp4", "reference_scope": "CHOREOGRAPHY_TIMING_AND_BODY_MECHANICS_ONLY"},
            "beats": [
                {"start_seconds": 0, "end_seconds": 3, "initiator": "witness", "target": "lead", "action": "straight right punch", "contact_point": "raised left forearm", "force_direction": "forward and down", "footwork": "right step", "target_reaction": "absorbs the strike and shifts the left foot", "end_state": "forearms remain in contact"},
                {"start_seconds": 3, "end_seconds": 6, "initiator": "lead", "target": "witness", "action": "outside wrist turn", "contact_point": "right wrist", "force_direction": "clockwise toward the table", "footwork": "left pivot", "target_reaction": "torso turns and right elbow bends", "end_state": "intruder faces the table"},
                {"start_seconds": 6, "end_seconds": 9, "initiator": "witness", "target": "lead", "action": "left elbow escape", "contact_point": "lead right shoulder", "force_direction": "backward", "footwork": "rear cross-step", "target_reaction": "takes one recovery step", "end_state": "actors separate by one arm length"},
                {"start_seconds": 9, "end_seconds": 12, "initiator": "lead", "target": "witness", "action": "shoulder capture", "contact_point": "right shoulder and wrist", "force_direction": "down toward the table", "footwork": "right step behind the heel", "target_reaction": "knees bend and chest lowers", "end_state": "intruder is chest-down at table edge"},
                {"start_seconds": 12, "end_seconds": 15, "initiator": "lead", "target": "witness", "action": "two-point restraint", "contact_point": "right wrist and upper back", "force_direction": "down", "footwork": "stable staggered stance", "target_reaction": "stops struggling without changing identity", "end_state": "lead controls intruder"},
            ],
            "camera_language_plan": {
                "generation_mode": "multi_keyframe_long_take",
                "segments": [
                    {
                        "technique_id": "tracking_follow", "start_seconds": 0, "end_seconds": 2,
                        "action_beat_index": 1, "narrative_motivation": "keep the entry and first interception readable",
                        "subject_anchor": "shared forearm contact", "axis_relation": "camera stays on room side of the action axis",
                    },
                    {
                        "technique_id": "locked_impact", "start_seconds": 9, "end_seconds": 12,
                        "action_beat_index": 4, "narrative_motivation": "show the shoulder capture without camera compensation",
                        "subject_anchor": "witness right shoulder", "axis_relation": "same room-side axis",
                    },
                ],
            },
            "continuity_ladders": [{
                "method_id": "causal_impact_aftermath_ladder",
                "beat_indexes": [3, 4, 5],
                "entry_state": "actors separate by one arm length while prior contact remains resolved",
                "exit_state": "lead controls witness chest-down at the table edge",
                "evidence_beats": [
                    {"action_beat_index": 4, "evidence_type": "contact", "visible_result": "shoulder and wrist remain loaded at table edge"},
                    {"action_beat_index": 4, "evidence_type": "environment", "visible_result": "table edge receives and preserves the downward force path"},
                    {"action_beat_index": 5, "evidence_type": "recovery", "visible_result": "lead settles into a stable staggered stance"},
                    {"action_beat_index": 5, "evidence_type": "relational_close", "visible_result": "both identities, restraint direction and table edge remain in one frame"},
                ],
                "spatial_measurement": {"kind": "displacement", "value": 1.0, "unit": "m"},
                "final_relational_frame": "lead standing over witness chest-down, loaded wrist, table edge and force direction visible",
                "camera_resolution": {
                    "technique_id": "locked_impact", "action_beat_index": 4,
                    "narrative_purpose": "preserve the full restraint force path without camera compensation",
                },
            }],
            "winner": "lead", "restrained_actor": "witness",
            "terminal_identity_hold": "lead remains standing and pins witness chest-down; their faces and wardrobes remain distinct",
        }

    def test_accepts_same_aperture_crossing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous = self.transition()
            crossing = {
                **self.transition("SAME_APERTURE_CROSSING", "room", "street"),
                "aperture_id": "east-wall", "direction": "inside_to_outside",
                "camera_path_kind": "FOLLOW_THROUGH_SAME_APERTURE",
                "camera_crosses_with_subjects": True,
                "camera_path_aperture_id": "east-wall",
                "camera_travel_distance_m": 2, "camera_axis_change_degrees": 10,
            }
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "breach", transition=continuous), self.frame(root / "c", 15, "outside", "street", crossing)]
            prompt, manifest = compile_prompt(self.spec(frames))
            self.assertIn("@图片3", prompt)
            self.assertIn("LORA-SD2-001-REFERENCE-GEOMETRY-LEAK", prompt)
            self.assertIn("LORA-SD2-002-UNIQUE-PROP-GROUP-REACTION", prompt)
            self.assertIn("LORA-SD2-003-ADJACENT-CAMERA-TRAJECTORY", prompt)
            self.assertIn("逐人动作覆盖", prompt)
            self.assertIn("FULL_VISIBLE_ACTOR_MOTION_COVERAGE", manifest["gates"])
            self.assertIn("EPISODE_CHARACTER_ASSETS_FROZEN_AND_UNIQUE", manifest["gates"])
            self.assertEqual(manifest["route"], "/api/v1/generation/omni-video")
            applied = manifest["local_lora_memory"]["applied_sample_ids"]
            self.assertTrue({
                "LORA-SD2-001-REFERENCE-GEOMETRY-LEAK",
                "LORA-SD2-002-UNIQUE-PROP-GROUP-REACTION",
                "LORA-SD2-003-ADJACENT-CAMERA-TRAJECTORY",
                "LORA-SD2-010-DIALOGUE-MODE-CONTRACT-DRIFT",
            }.issubset(applied))

    def test_rejects_unbound_location_jump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous = self.transition()
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "breach", transition=continuous), self.frame(root / "c", 15, "outside", "street", continuous)]
            with self.assertRaisesRegex(ValueError, "SAME_APERTURE_CROSSING"):
                compile_prompt(self.spec(frames))

    def test_rejects_bare_unpriced_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            continuous = self.transition()
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=continuous), self.frame(root / "c", 15, "end", transition=continuous)]
            spec = self.spec(frames)
            spec["model"] = "seedance-2.0"
            with self.assertRaisesRegex(ValueError, "seedance-2.0-fast"):
                compile_prompt(spec)

    def test_rejects_impossible_camera_axis_jump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            impossible = self.transition()
            impossible["camera_axis_change_degrees"] = 180
            frames = [
                self.frame(root / "a", 0, "start"),
                self.frame(root / "b", 7, "middle", transition=impossible),
                self.frame(root / "c", 15, "end", transition=self.transition()),
            ]
            with self.assertRaisesRegex(ValueError, "camera axis change exceeds 90 degrees"):
                compile_prompt(self.spec(frames))

    def test_rejects_unreachable_camera_speed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            impossible = self.transition()
            impossible["camera_travel_distance_m"] = 20
            frames = [
                self.frame(root / "a", 0, "start"),
                self.frame(root / "b", 7, "middle", transition=impossible),
                self.frame(root / "c", 15, "end", transition=self.transition()),
            ]
            with self.assertRaisesRegex(ValueError, "camera path exceeds 2.5 m/s"):
                compile_prompt(self.spec(frames))

    def test_rejects_missing_visible_actor_motion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [
                self.frame(root / "a", 0, "start"),
                self.frame(root / "b", 7, "middle", transition=self.transition()),
                self.frame(root / "c", 15, "end", transition=self.transition()),
            ]
            del frames[1]["actor_motion"]["witness"]
            with self.assertRaisesRegex(ValueError, "cover the full actor roster"):
                compile_prompt(self.spec(frames))

    def test_rejects_static_position_language_as_motion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [
                self.frame(root / "a", 0, "start"),
                self.frame(root / "b", 7, "middle", transition=self.transition()),
                self.frame(root / "c", 15, "end", transition=self.transition()),
            ]
            frames[1]["actor_motion"]["witness"]["continuous_micro_action"] = "留在安全区静止"
            with self.assertRaisesRegex(ValueError, "static pose"):
                compile_prompt(self.spec(frames))

    def test_accepts_explicit_offscreen_actor_disposition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [
                self.frame(root / "a", 0, "start"),
                self.frame(root / "b", 7, "middle", transition=self.transition()),
                self.frame(root / "c", 15, "end", transition=self.transition()),
            ]
            frames[2]["actor_motion"]["witness"] = {
                "visible": False, "offscreen_reason": "exited through the same aperture during the prior interval",
            }
            prompt, manifest = compile_prompt(self.spec(frames))
            self.assertIn("已离开画面", prompt)
            self.assertFalse(manifest["keyframes"][2]["actor_motion"][1]["visible"])

    def test_combat_compiles_timed_beats_identity_refs_and_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            spec["combat_choreography_contract"] = self.combat_contract(root)
            prompt, manifest = compile_prompt(spec)
            self.assertIn("逐拍动作因果", prompt)
            self.assertIn("被制服者=witness", prompt)
            self.assertIn("@视频1只参考动作节拍", prompt)
            self.assertIn("动作镜头语言配方", prompt)
            self.assertIn("因果连续性阶梯", prompt)
            self.assertEqual(manifest["combat_choreography_contract"]["camera_language_plan"]["selection_gate"], "PASS_MOTIVATED_ONLY")
            self.assertEqual(
                manifest["combat_choreography_contract"]["continuity_ladders"][0]["method_id"],
                "causal_impact_aftermath_ladder",
            )
            self.assertEqual(
                manifest["combat_choreography_contract"]["continuity_adapter"],
                "HELL_GRIND_COMBAT_CONTINUITY_PROMPT_RULE_ADAPTER_V7",
            )
            self.assertIn("COMBAT_IDENTITY_CHOREOGRAPHY_AND_OUTCOME", manifest["gates"])
            self.assertIn("COMBAT_CAUSAL_CONTINUITY_LADDER", manifest["gates"])

    def test_combat_rejects_continuity_ladder_missing_required_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["continuity_ladders"][0]["evidence_beats"] = [
                row for row in contract["continuity_ladders"][0]["evidence_beats"]
                if row["evidence_type"] != "environment"
            ]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "missing required evidence: environment"):
                compile_prompt(spec)

    def test_combat_rejects_continuity_camera_outside_declared_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["continuity_ladders"][0]["camera_resolution"]["technique_id"] = "crash_pull"
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "must match a declared camera segment"):
                compile_prompt(spec)

    def test_combat_compiles_cross_ladder_state_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            first = contract["continuity_ladders"][0]
            first["beat_indexes"] = [1, 2, 3]
            first["exit_state"] = "weapon remains trapped while the defender owns the opening"
            first["evidence_beats"] = [
                {"action_beat_index": 1, "evidence_type": "contact", "visible_result": "weapon contact remains loaded"},
                {"action_beat_index": 2, "evidence_type": "environment", "visible_result": "table edge preserves the force path"},
                {"action_beat_index": 3, "evidence_type": "recovery", "visible_result": "defender settles without resetting distance"},
                {"action_beat_index": 3, "evidence_type": "relational_close", "visible_result": "both identities and trapped weapon remain readable"},
            ]
            first["camera_resolution"] = {
                "technique_id": "tracking_follow", "action_beat_index": 1,
                "narrative_purpose": "preserve the opening contact and route",
            }
            second = {
                "method_id": "timed_emotional_reaction_microsequence",
                "beat_indexes": [3, 4],
                "entry_state": first["exit_state"],
                "exit_state": "the reaction resolves while the trapped weapon remains visible",
                "evidence_beats": [
                    {"action_beat_index": 3, "evidence_type": "stimulus", "visible_result": "the trapped weapon creates the opening"},
                    {"action_beat_index": 3, "evidence_type": "objective_evidence", "visible_result": "the weapon remains visibly trapped"},
                    {"action_beat_index": 4, "evidence_type": "performance_transition", "visible_result": "the defender commits to the opening"},
                    {"action_beat_index": 4, "evidence_type": "relational_close", "visible_result": "both identities and inherited state share the frame"},
                ],
                "final_relational_frame": "both identities and inherited trapped-weapon state remain readable",
                "camera_resolution": {
                    "technique_id": "locked_impact", "action_beat_index": 4,
                    "narrative_purpose": "show the inherited state without camera substitution",
                },
            }
            contract["continuity_ladders"] = [first, second]
            spec["combat_choreography_contract"] = contract
            prompt, manifest = compile_prompt(spec)
            ladders = manifest["combat_choreography_contract"]["continuity_ladders"]
            self.assertIn("跨阶梯状态交接", prompt)
            self.assertEqual(ladders[0]["handoff_to_next"]["shared_state"], first["exit_state"])
            self.assertEqual(ladders[1]["handoff_from_previous"]["from_action_beat_index"], 3)

    def test_combat_rejects_cross_ladder_state_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            first = contract["continuity_ladders"][0]
            first["beat_indexes"] = [1, 2, 3]
            first["evidence_beats"] = [
                {**row, "action_beat_index": min(index, 3)}
                for index, row in enumerate(first["evidence_beats"], start=1)
            ]
            first["camera_resolution"] = {
                "technique_id": "tracking_follow", "action_beat_index": 1,
                "narrative_purpose": "preserve the opening contact and route",
            }
            second = dict(first)
            second["method_id"] = "timed_emotional_reaction_microsequence"
            second["beat_indexes"] = [3, 4]
            second["entry_state"] = "a clean reset with no inherited damage or prop state"
            second["evidence_beats"] = [
                {"action_beat_index": 3, "evidence_type": "stimulus", "visible_result": "prior contact triggers the reaction"},
                {"action_beat_index": 3, "evidence_type": "objective_evidence", "visible_result": "the prior result remains visible"},
                {"action_beat_index": 4, "evidence_type": "performance_transition", "visible_result": "the defender commits"},
                {"action_beat_index": 4, "evidence_type": "relational_close", "visible_result": "both identities share the frame"},
            ]
            second.pop("spatial_measurement", None)
            second["camera_resolution"] = {
                "technique_id": "locked_impact", "action_beat_index": 4,
                "narrative_purpose": "show the reaction in one stable relation",
            }
            contract["continuity_ladders"] = [first, second]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "state handoff mismatch"):
                compile_prompt(spec)

    def test_combat_compiles_all_licensed_continuity_methods(self):
        for method_id, method in COMBAT_CONTINUITY_METHODS.items():
            with self.subTest(method_id=method_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
                spec = self.spec(frames)
                contract = self.combat_contract(root)
                ladder = {
                    "method_id": method_id,
                    "beat_indexes": [3, 4, 5] if method["min_beats"] == 3 else [4, 5],
                    "entry_state": "the prior physical relation remains visible",
                    "exit_state": "the exchange resolves without resetting evidence",
                    "evidence_beats": [
                        {"action_beat_index": 4, "evidence_type": evidence_type, "visible_result": f"visible {evidence_type} consequence persists"}
                        for evidence_type in sorted(method["required_evidence"])
                    ],
                    "final_relational_frame": "both identities, force path, environment, and result remain readable",
                    "camera_resolution": {
                        "technique_id": "locked_impact", "action_beat_index": 4,
                        "narrative_purpose": "resolve causal evidence in a stable composition",
                    },
                }
                if method["measurement_required"]:
                    ladder["spatial_measurement"] = {"kind": "distance", "value": 1, "unit": "m"}
                if method.get("state_promotion_required"):
                    ladder["promoted_state_id"] = "witness_damage_state_2"
                contract["continuity_ladders"] = [ladder]
                spec["combat_choreography_contract"] = contract
                prompt, manifest = compile_prompt(spec)
                self.assertIn(method_id, prompt)
                self.assertEqual(
                    manifest["combat_choreography_contract"]["continuity_ladders"][0]["method_id"],
                    method_id,
                )

    def test_combat_rejects_topology_traversal_without_load_bearing_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["continuity_ladders"] = [{
                "method_id": "embodied_topology_traversal_damage_combo",
                "beat_indexes": [3, 4, 5],
                "entry_state": "the larger body is established as an inclined route",
                "exit_state": "lead lands behind the larger opponent",
                "evidence_beats": [
                    {"action_beat_index": 3, "evidence_type": evidence_type, "visible_result": f"visible {evidence_type} evidence"}
                    for evidence_type in (
                        "foothold_sequence", "traversal_path", "distinct_contacts",
                        "landing_relation", "cumulative_result", "relational_close",
                    )
                ],
                "spatial_measurement": {"kind": "displacement", "value": 1.5, "unit": "m"},
                "final_relational_frame": "route, damage and landing side remain in one frame",
                "camera_resolution": {
                    "technique_id": "locked_impact", "action_beat_index": 4,
                    "narrative_purpose": "show the route without camera substitution",
                },
            }]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "missing required evidence: topology_anchor"):
                compile_prompt(spec)

    def test_combat_rejects_committed_miss_without_entrapment_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["continuity_ladders"] = [{
                "method_id": "committed_miss_entrapment_counter_window",
                "beat_indexes": [3, 4, 5],
                "entry_state": "the attacker commits to an irreversible downward strike",
                "exit_state": "the defender launches while the weapon remains trapped",
                "evidence_beats": [
                    {"action_beat_index": 4, "evidence_type": evidence_type, "visible_result": f"visible {evidence_type} evidence"}
                    for evidence_type in (
                        "attack_commitment", "evasion_clearance", "extraction_delay",
                        "counterlaunch", "relational_close",
                    )
                ],
                "spatial_measurement": {"kind": "clearance", "value": 40, "unit": "cm"},
                "promoted_state_id": "weapon_trapped_state_1",
                "final_relational_frame": "both fighters and the trapped weapon remain readable",
                "camera_resolution": {
                    "technique_id": "locked_impact", "action_beat_index": 4,
                    "narrative_purpose": "prove the exposure window without camera substitution",
                },
            }]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "missing required evidence: obstacle_entrapment"):
                compile_prompt(spec)

    def test_combat_rejects_force_conversion_without_controlled_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["continuity_ladders"] = [{
                "method_id": "force_conversion_controlled_recovery_ladder",
                "beat_indexes": [3, 4, 5],
                "entry_state": "the defender braces against a heavier incoming strike",
                "exit_state": "the defender regains stance at a measured new distance",
                "evidence_beats": [
                    {"action_beat_index": 4, "evidence_type": evidence_type, "visible_result": f"visible {evidence_type} evidence"}
                    for evidence_type in (
                        "defensive_contact", "force_transfer", "carried_prop_continuity",
                        "landing_absorption", "stance_recovery", "relational_close",
                    )
                ],
                "spatial_measurement": {"kind": "displacement", "value": 3, "unit": "m"},
                "final_relational_frame": "both fighters, retained prop and new distance remain readable",
                "camera_resolution": {
                    "technique_id": "locked_impact", "action_beat_index": 4,
                    "narrative_purpose": "prove force transfer without camera substitution",
                },
            }]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "missing required evidence: controlled_rotation"):
                compile_prompt(spec)

    def test_combat_rejects_penetration_extraction_without_embedded_reaction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["continuity_ladders"] = [{
                "method_id": "follow_through_exposure_penetration_extraction_ladder",
                "beat_indexes": [3, 4, 5],
                "entry_state": "the opponent remains committed in a visible follow-through",
                "exit_state": "the attacker withdraws with the promoted wound state still visible",
                "evidence_beats": [
                    {"action_beat_index": 4, "evidence_type": evidence_type, "visible_result": f"visible {evidence_type} evidence"}
                    for evidence_type in (
                        "opponent_follow_through", "exposed_target_zone", "gap_closure",
                        "targeted_penetration_contact", "extraction_consequence",
                        "cumulative_damage_state", "relational_close",
                    )
                ],
                "spatial_measurement": {"kind": "distance", "value": 2, "unit": "m"},
                "promoted_state_id": "target_wound_state_2",
                "final_relational_frame": "both fighters, target zone, weapon and promoted wound remain readable",
                "camera_resolution": {
                    "technique_id": "locked_impact", "action_beat_index": 4,
                    "narrative_purpose": "prove embedded contact and extraction without camera substitution",
                },
            }]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "missing required evidence: embedded_reaction"):
                compile_prompt(spec)

    def test_combat_rejects_near_miss_without_armor_glancing_contact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["continuity_ladders"] = [{
                "method_id": "near_miss_armor_interception_recovery_ladder",
                "beat_indexes": [3, 4, 5],
                "entry_state": "the attacker commits to a readable strike line",
                "exit_state": "the body remains protected while armor damage and opposed recovery costs persist",
                "evidence_beats": [
                    {"action_beat_index": 4, "evidence_type": evidence_type, "visible_result": f"visible {evidence_type} evidence"}
                    for evidence_type in (
                        "attack_commitment", "last_moment_evasion_clearance",
                        "body_protection_state", "fragment_consequence",
                        "attacker_followthrough_imbalance", "defender_stance_recovery",
                        "relational_close",
                    )
                ],
                "spatial_measurement": {"kind": "clearance", "value": 80, "unit": "cm"},
                "promoted_state_id": "armor_damage_state_1",
                "final_relational_frame": "both fighters, attack path, protected body and persistent armor damage remain readable",
                "camera_resolution": {
                    "technique_id": "locked_impact", "action_beat_index": 4,
                    "narrative_purpose": "prove partial protective interception without camera substitution",
                },
            }]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "missing required evidence: armor_glancing_contact"):
                compile_prompt(spec)

    def test_combat_rejects_low_profile_limb_failure_without_support_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["continuity_ladders"] = [{
                "method_id": "low_profile_evasion_limb_failure_counterlaunch_recovery_ladder",
                "beat_indexes": [3, 4, 5],
                "entry_state": "the opponent commits overhead while the runner drops below the strike line",
                "exit_state": "the wounded opponent remains unstable while the displaced runner completes a prop-preserving landing",
                "evidence_beats": [
                    {"action_beat_index": 4, "evidence_type": evidence_type, "visible_result": f"visible {evidence_type} evidence"}
                    for evidence_type in (
                        "attack_commitment", "low_profile_evasion_clearance",
                        "targeted_limb_contact", "counterlaunch_contact",
                        "airborne_displacement", "carried_prop_continuity",
                        "landing_absorption", "landing_recovery_state",
                        "crowd_reaction", "relational_close",
                    )
                ],
                "spatial_measurement": {"kind": "displacement", "value": 5, "unit": "m"},
                "promoted_state_id": "opponent_support_limb_failure_state_1",
                "final_relational_frame": "wounded support limb, displaced runner, retained prop, landing stance, and reacting witnesses remain readable",
                "camera_resolution": {
                    "technique_id": "locked_impact", "action_beat_index": 4,
                    "narrative_purpose": "prove support failure and recovery without substituting camera motion for physics",
                },
            }]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "missing required evidence: support_failure"):
                compile_prompt(spec)

    def test_combat_rejects_continuous_perpetual_camera_motion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["camera_language_plan"]["segments"] = [
                {"technique_id": "tracking_follow", "start_seconds": 0, "end_seconds": 3, "action_beat_index": 1, "narrative_motivation": "follow entry", "subject_anchor": "lead", "axis_relation": "room side"},
                {"technique_id": "arc_orientation", "start_seconds": 3, "end_seconds": 5, "action_beat_index": 2, "narrative_motivation": "show positions", "subject_anchor": "shared wrists", "axis_relation": "room side"},
                {"technique_id": "low_angle_dolly", "start_seconds": 6, "end_seconds": 8, "action_beat_index": 3, "narrative_motivation": "show feet", "subject_anchor": "feet", "axis_relation": "room side"},
            ]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "at most two dynamic camera techniques"):
                compile_prompt(spec)

    def test_combat_rejects_slow_motion_without_decisive_contact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["camera_language_plan"]["segments"] = [{
                "technique_id": "micro_slow_follow", "start_seconds": 2.2, "end_seconds": 2.7,
                "action_beat_index": 1, "narrative_motivation": "decorate the punch",
                "subject_anchor": "fist", "axis_relation": "room side",
            }]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "contact_is_decisive"):
                compile_prompt(spec)

    def test_combat_rejects_camera_mode_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["camera_language_plan"]["generation_mode"] = "storyboard"
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "must match the generation spec mode"):
                compile_prompt(spec)

    def test_combat_rejects_shared_identity_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            contract = self.combat_contract(root)
            contract["participants"][1]["independent_identity_reference"] = contract["participants"][0]["independent_identity_reference"]
            spec["combat_choreography_contract"] = contract
            with self.assertRaisesRegex(ValueError, "distinct identity references"):
                compile_prompt(spec)

    def test_rejects_character_missing_from_frozen_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            spec["episode_character_registry"]["characters"].pop()
            with self.assertRaisesRegex(ValueError, "exactly cover actor_roster"):
                compile_prompt(spec)

    def test_rejects_missing_writer_character_brief(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            del spec["episode_character_registry"]["characters"][1]["canonical_character_brief"]["wardrobe"]
            with self.assertRaisesRegex(ValueError, "canonical brief wardrobe is required"):
                compile_prompt(spec)

    def test_rejects_historically_similar_character_without_story_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            spec["episode_character_registry"]["characters"][1]["historical_uniqueness_audit"]["wardrobe_similarity"] = 0.95
            with self.assertRaisesRegex(ValueError, "too similar to historical library in wardrobe"):
                compile_prompt(spec)

    def test_single_actor_registry_does_not_require_a_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = [self.frame(root / "a", 0, "start"), self.frame(root / "b", 7, "middle", transition=self.transition()), self.frame(root / "c", 15, "end", transition=self.transition())]
            spec = self.spec(frames)
            spec["actor_roster"] = ["lead"]
            spec["episode_character_registry"]["characters"] = spec["episode_character_registry"]["characters"][:1]
            spec["episode_character_registry"]["pairwise_uniqueness_audit"] = []
            for frame in frames:
                del frame["actor_motion"]["witness"]
            prompt, manifest = compile_prompt(spec)
            self.assertIn("本集角色资产冻结", prompt)
            self.assertEqual(manifest["episode_character_registry"]["pairwise_audit_count"], 0)


if __name__ == "__main__":
    unittest.main()
