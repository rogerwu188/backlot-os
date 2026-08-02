from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .models import CaptionClip, Clip, Project
from .shot_recipes import validate_and_materialize_shot_recipes


@dataclass(frozen=True)
class CompiledCommand:
    argv: list[str]
    filter_graph: str
    summary: dict[str, Any]


def _fade_filters(clip: Clip, *, audio: bool, materialized_duration: float | None = None) -> list[str]:
    result: list[str] = []
    prefix = "afade" if audio else "fade"
    clip_duration = materialized_duration if materialized_duration is not None else clip.duration
    if clip.transition_in.type == "fade" and clip.transition_in.duration:
        d = min(clip.transition_in.duration, clip_duration)
        result.append(f"{prefix}=t=in:st=0:d={d:g}" + ("" if audio else ":alpha=1"))
    if clip.transition_out.type == "fade" and clip.transition_out.duration:
        d = min(clip.transition_out.duration, clip_duration)
        result.append(f"{prefix}=t=out:st={clip_duration-d:g}:d={d:g}" + ("" if audio else ":alpha=1"))
    return result


def _video_frame_range(clip: Clip, fps: int) -> tuple[int, int, float, float]:
    """Map continuous edit times to a shared half-open CFR frame range."""
    start_frame = max(0, math.floor(clip.start * fps + 0.5))
    end_frame = max(start_frame + 1, math.floor((clip.start + clip.duration) * fps + 0.5))
    return start_frame, end_frame, start_frame / fps, end_frame / fps


def _escape_drawtext(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:").replace("%", "\\%")


def _wrap_caption_lines(text: str, width: int) -> list[str]:
    lines: list[str] = []
    closing_punctuation = "，。！？；：、）》】”’…"
    opening_punctuation = "（《【“‘"
    for paragraph in text.splitlines() or [""]:
        while len(paragraph) > width:
            lines.append(paragraph[:width])
            paragraph = paragraph[width:]
        lines.append(paragraph)
    for index in range(1, len(lines)):
        while lines[index] and lines[index][0] in closing_punctuation:
            lines[index - 1] += lines[index][0]
            lines[index] = lines[index][1:]
    for index in range(len(lines) - 1):
        while lines[index] and lines[index][-1] in opening_punctuation:
            lines[index + 1] = lines[index][-1] + lines[index + 1]
            lines[index] = lines[index][:-1]
    return [line for line in lines if line]


def _caption_position(clip: CaptionClip, width: int, height: int) -> tuple[str, str]:
    m = clip.style.margins
    horizontal = clip.style.alignment.split("-")[-1] if "-" in clip.style.alignment else "center"
    vertical = clip.style.alignment.split("-")[0] if "-" in clip.style.alignment else "middle"
    x = {"left": str(m["left"]), "center": "(w-text_w)/2", "right": f"w-text_w-{m['right']}"}[horizontal]
    y = {"top": str(m["top"]), "middle": "(h-text_h)/2", "bottom": f"h-text_h-{m['bottom']}"}[vertical]
    return x, y


def _caption_line_position(clip: CaptionClip, line_index: int, line_count: int) -> tuple[str, str]:
    x, _ = _caption_position(clip, 0, 0)
    margins = clip.style.margins
    vertical = clip.style.alignment.split("-")[0] if "-" in clip.style.alignment else "middle"
    line_step = max(1, round(clip.style.size * 1.2))
    if vertical == "top":
        y = f"{margins['top']}+{line_index * line_step}"
    elif vertical == "bottom":
        offset = (line_count - 1 - line_index) * line_step
        y = f"h-text_h-{margins['bottom']}-{offset}"
    else:
        offset = (line_index - (line_count - 1) / 2) * line_step
        y = f"(h-text_h)/2{offset:+g}"
    return x, y


def compile_project(project: Project, ffmpeg: str = "ffmpeg", overwrite: bool = False,
                    master_audio_mode: str = "single-pass", premaster_attenuation_db: float = 0.0) -> CompiledCommand:
    if master_audio_mode not in {"single-pass", "premaster"}:
        raise ValueError("master_audio_mode must be single-pass or premaster")
    recipe_problems, recipe_coverage = validate_and_materialize_shot_recipes(project)
    if recipe_problems:
        detail = "; ".join(f"{item.code}: {item.message}" for item in recipe_problems[:10])
        raise ValueError(f"shot recipe materialization failed: {detail}")
    inputs: list[tuple[str, str, int, int, Clip]] = []
    for track_index, track in enumerate(project.video_tracks):
        if track.enabled:
            inputs.extend(("video", track.id, track_index, clip_index, c) for clip_index, c in enumerate(track.clips))
    for track_index, track in enumerate(project.audio_tracks):
        if track.enabled:
            inputs.extend(("audio", track.id, track_index, clip_index, c) for clip_index, c in enumerate(track.clips))

    # Decode each physical asset once. Repeating the same source as one -i per
    # clip made large projects exhaust decoder/encoder resources (V7: 154
    # inputs) even though they only referenced a much smaller asset set.
    sources = list(dict.fromkeys(clip.source for *_, clip in inputs))
    source_indexes = {source: index for index, source in enumerate(sources)}
    argv = [ffmpeg, "-hide_banner", "-y" if overwrite else "-n"]
    for source in sources:
        argv += ["-i", source]

    outro_asset_index = outro_audio_index = outro_sfx_index = None
    if project.outro.enabled:
        outro_asset_index = len(sources)
        suffix = project.outro.asset_path.lower().rsplit(".", 1)[-1]
        if suffix in {"png", "jpg", "jpeg", "webp"}:
            argv += ["-loop", "1", "-t", f"{project.outro.duration:g}", "-i", project.outro.asset_path]
        else:
            argv += ["-i", project.outro.asset_path]
        next_index = outro_asset_index + 1
        if project.outro.audio_path:
            outro_audio_index = next_index
            argv += ["-i", project.outro.audio_path]
            next_index += 1
        if project.outro.sfx_path:
            outro_sfx_index = next_index
            argv += ["-i", project.outro.sfx_path]

    w, h, fps, duration = project.output.width, project.output.height, project.output.fps, project.duration
    main_duration = project.main_duration
    filters = [f"color=c={project.background}:s={w}x{h}:r={fps}:d={main_duration:g}[vbase0]"]
    occurrence_counts: dict[tuple[str, str], int] = {}
    for kind, _, _, _, clip in inputs:
        key = (clip.source, kind)
        occurrence_counts[key] = occurrence_counts.get(key, 0) + 1
    source_labels: dict[tuple[str, str], list[str]] = {}
    for (source, kind), count in occurrence_counts.items():
        input_no = source_indexes[source]
        stream = "v" if kind == "video" else "a"
        if count == 1:
            source_labels[(source, kind)] = [f"{input_no}:{stream}"]
        else:
            labels = [f"src{stream}{input_no}_{i}" for i in range(count)]
            filters.append(f"[{input_no}:{stream}]{'split' if kind == 'video' else 'asplit'}={count}" + "".join(f"[{x}]" for x in labels))
            source_labels[(source, kind)] = labels
    source_uses: dict[tuple[str, str], int] = {}
    current_video = "vbase0"
    audio_by_track: dict[int, list[tuple[Clip, str]]] = {}
    video_no = audio_no = 0
    for _occurrence_no, (kind, _track_id, track_index, _clip_index, clip) in enumerate(inputs):
        source_key = (clip.source, kind)
        use_no = source_uses.get(source_key, 0)
        source_uses[source_key] = use_no + 1
        source_label = source_labels[source_key][use_no]
        if kind == "video":
            label = f"vc{video_no}"
            start_frame, end_frame, visual_start, visual_end = _video_frame_range(clip, fps)
            frame_count = end_frame - start_frame
            visual_duration = frame_count / fps
            chain = [
                f"[{source_label}]trim=start={clip.in_point:g}:duration={clip.duration:g}",
                "setpts=PTS-STARTPTS",
                f"fps={fps}:start_time=0",
                # overlay/eof_action=pass drops a secondary stream's final
                # frame when EOF is delivered on that same framesync tick.
                # Add exactly one out-of-range sentinel so EOF arrives on the
                # following tick; enable remains half-open, so the sentinel is
                # never visible and cannot create a cadence freeze or padding.
                f"tpad=stop_mode=clone:stop_duration={1 / fps:.12f}",
                f"trim=end_frame={frame_count + 1}",
                "setpts=PTS-STARTPTS",
            ]
            if clip.width and clip.height:
                chain.append(f"scale={clip.width}:{clip.height}")
            else:
                chain.extend([f"scale={w}:{h}:force_original_aspect_ratio=decrease", f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black@0"])
            clean_current = None
            if clip.cleanup_regions:
                clean_current = f"vclean{video_no}_base"
                filters.append(",".join(chain) + f"[{clean_current}]")
                for cleanup_no, cleanup in enumerate(clip.cleanup_regions):
                    clean_next = f"vclean{video_no}_{cleanup_no}"
                    end_local = cleanup.start + (cleanup.duration or visual_duration - cleanup.start)
                    enable = f"between(t,{cleanup.start:g},{end_local:g})"
                    if cleanup.mode == "delogo":
                        filters.append(f"[{clean_current}]delogo=x={cleanup.x}:y={cleanup.y}:w={cleanup.width}:h={cleanup.height}:show=0:enable='{enable}'[{clean_next}]")
                    elif cleanup.mode == "mask":
                        filters.append(f"[{clean_current}]drawbox=x={cleanup.x}:y={cleanup.y}:w={cleanup.width}:h={cleanup.height}:color={cleanup.color}:t=fill:enable='{enable}'[{clean_next}]")
                    else:
                        base = f"vclean{video_no}_{cleanup_no}_base"
                        crop_in = f"vclean{video_no}_{cleanup_no}_cropin"
                        blurred = f"vclean{video_no}_{cleanup_no}_blurred"
                        filters.append(f"[{clean_current}]split=2[{base}][{crop_in}]")
                        filters.append(f"[{crop_in}]crop={cleanup.width}:{cleanup.height}:{cleanup.x}:{cleanup.y},boxblur={cleanup.blur}:{cleanup.blur}[{blurred}]")
                        filters.append(f"[{base}][{blurred}]overlay=x={cleanup.x}:y={cleanup.y}:enable='{enable}':eof_action=pass[{clean_next}]")
                    clean_current = clean_next
                chain = [f"[{clean_current}]format=rgba"]
            else:
                chain.append("format=rgba")
            if clip.opacity < 1:
                chain.append(f"colorchannelmixer=aa={clip.opacity:g}")
            chain.extend(_fade_filters(clip, audio=False, materialized_duration=visual_duration))
            # Keep edit boundaries as exact frame-grid rationals. Formatting a
            # long timeline time with :g (for example 61.833333 -> 61.8333)
            # moves the secondary stream a fraction early; overlay framesync
            # then observes EOF on the final hard-cut frame. Exact frame/fps
            # PTS avoids both that black frame and any need to repeat a tail.
            chain.append(f"setpts=PTS+{start_frame}/({fps}*TB)")
            filters.append(",".join(chain) + f"[{label}]")
            out = f"vbase{video_no + 1}"
            enable_start_numerator = max(0, 2 * start_frame - 1)
            enable_end_numerator = 2 * end_frame + 1
            filters.append(
                f"[{current_video}][{label}]overlay=x={clip.x}:y={clip.y}:"
                f"enable='gte(t,{enable_start_numerator}/{2 * fps})*"
                f"lt(t,{enable_end_numerator}/{2 * fps})':"
                f"eof_action=pass:repeatlast=0[{out}]"
            )
            current_video = out
            video_no += 1
        else:
            raw_label = f"ar{audio_no}"
            chain = [
                f"[{source_label}]atrim=start={clip.in_point:g}:duration={clip.duration:g}",
                "asetpts=N/SR/TB",
                "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
            ]
            chain.extend(_fade_filters(clip, audio=True))
            chain.append(f"volume={clip.volume:g}")
            filters.append(",".join(chain) + f"[{raw_label}]")
            audio_by_track.setdefault(track_index, []).append((clip, raw_label))
            audio_no += 1

    caption_summary = []
    caption_no = 0
    for track_index, track in enumerate(project.subtitle_tracks):
        if not track.enabled:
            continue
        for clip_index, clip in enumerate(track.clips):
            lines = _wrap_caption_lines(clip.text, clip.style.wrap)
            font = _escape_drawtext(clip.style.font)
            color = clip.style.color.replace("#", "0x")
            outline_color = clip.style.outline_color.replace("#", "0x")
            end = clip.start + clip.duration
            font_option = f"fontfile='{font}'" if "/" in clip.style.font or "\\" in clip.style.font else f"font='{font}'"
            for line_index, line in enumerate(lines):
                out = f"vsub{caption_no}_{line_index}"
                x, y = _caption_line_position(clip, line_index, len(lines))
                text = _escape_drawtext(line)
                filters.append(
                    f"[{current_video}]drawtext=text='{text}':{font_option}:fontsize={clip.style.size}:fontcolor={color}:"
                    f"borderw={clip.style.outline}:bordercolor={outline_color}:x={x}:y={y}:"
                    f"enable='between(t,{clip.start:g},{end:g})'[{out}]"
                )
                current_video = out
            caption_summary.append({
                "trackId": track.id, "trackIndex": track_index, "clipIndex": clip_index,
                "clipId": clip.id, "dialogueId": clip.dialogue_id, "text": clip.text,
                "timeRange": {"start": clip.start, "end": end}, "style": {
                    "font": clip.style.font, "size": clip.style.size, "color": clip.style.color,
                    "outline": clip.style.outline, "alignment": clip.style.alignment,
                    "margins": clip.style.margins, "wrap": clip.style.wrap,
                },
            })
            caption_no += 1

    outro_summary: dict[str, Any] = {"present": False}
    if project.outro.enabled:
        outro = project.outro
        assert outro_asset_index is not None
        logo = outro.logo
        filters.append(f"color=c=black:s={w}x{h}:r={fps}:d={outro.duration:g}[ocardbase]")
        suffix = outro.asset_path.lower().rsplit(".", 1)[-1]
        asset_chain = f"[{outro_asset_index}:v]"
        if suffix not in {"png", "jpg", "jpeg", "webp"}:
            asset_chain += f"trim=duration={outro.duration:g},setpts=PTS-STARTPTS,"
        if outro.fit == "contain":
            asset_chain += f"scale={logo['width']}:{logo['height']}:force_original_aspect_ratio=decrease,pad={logo['width']}:{logo['height']}:(ow-iw)/2:(oh-ih)/2:color=black@0,format=rgba[ologo]"
        elif outro.fit == "cover":
            asset_chain += f"scale={logo['width']}:{logo['height']}:force_original_aspect_ratio=increase,crop={logo['width']}:{logo['height']},format=rgba[ologo]"
        else:
            asset_chain += f"scale={logo['width']}:{logo['height']},format=rgba[ologo]"
        filters.append(asset_chain)
        filters.append(f"[ocardbase][ologo]overlay=x={logo['x']}:y={logo['y']}:eof_action=repeat[ocardlogo]")
        font = _escape_drawtext(outro.font)
        title = _escape_drawtext(outro.title_text)
        next_text = _escape_drawtext(outro.next_text)
        brand = _escape_drawtext(outro.brand_text)
        filters.append(
            f"[ocardlogo]drawtext=fontfile='{font}':text='{title}':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=420,"
            f"drawtext=fontfile='{font}':text='{next_text}':fontcolor=white:fontsize=38:x=(w-text_w)/2:y=512,"
            f"drawtext=fontfile='{font}':text='{brand}':fontcolor=white@0.86:fontsize=24:x=(w-text_w)/2:y=905,"
            f"fade=t=in:st=0:d={outro.transition_in:g},fade=t=out:st={max(0.0, outro.duration-outro.transition_out):g}:d={outro.transition_out:g}[ocard]"
        )
        filters.append(f"[{current_video}][ocard]concat=n=2:v=1:a=0[vwithoutro]")
        current_video = "vwithoutro"
        outro_summary = {"present": True, "brand": outro.brand, "template": outro.template, "templateVersion": outro.template_version,
                         "actualStart": main_duration, "actualEnd": duration, "duration": outro.duration,
                         "endsAtTimelineEnd": True, "fit": outro.fit, "audioPolicy": outro.audio_policy,
                         "assetPath": outro.asset_path, "includeInTotalDuration": outro.include_in_total_duration,
                         "accountedDuration": duration if outro.include_in_total_duration else main_duration,
                         "dialogueDuckDb": outro.dialogue_duck_db, "bgmDuckDb": outro.bgm_duck_db}

    # Assemble clips inside each semantic track first. Sequential tracks become
    # concat chains with only their real gaps; overlapping tracks use a local
    # mix. The final mix therefore has at most one input per audio track.
    audio_labels: list[str] = []
    for track_index, entries in sorted(audio_by_track.items()):
        entries = sorted(entries, key=lambda item: item[0].start)
        cursor = 0.0
        overlaps = False
        for clip, _ in entries:
            if clip.start < cursor - 0.0005:
                overlaps = True
                break
            cursor = max(cursor, clip.start + clip.duration)
        track_label = f"atrack{track_index}"
        if not overlaps:
            segments: list[str] = []
            cursor = 0.0
            for item_no, (clip, raw_label) in enumerate(entries):
                gap = clip.start - cursor
                if gap > 0.0005:
                    gap_label = f"agap{track_index}_{item_no}"
                    filters.append(f"anullsrc=r=48000:cl=stereo:d={gap:g}[{gap_label}]")
                    segments.append(gap_label)
                segments.append(raw_label)
                cursor = clip.start + clip.duration
            if len(segments) == 1:
                filters.append(f"[{segments[0]}]anull[{track_label}]")
            else:
                filters.append("".join(f"[{x}]" for x in segments) + f"concat=n={len(segments)}:v=0:a=1[{track_label}]")
        else:
            placed: list[str] = []
            for item_no, (clip, raw_label) in enumerate(entries):
                if clip.start > 0.0005:
                    silence = f"aprefix{track_index}_{item_no}"
                    placed_label = f"aplaced{track_index}_{item_no}"
                    filters.append(f"anullsrc=r=48000:cl=stereo:d={clip.start:g}[{silence}]")
                    filters.append(f"[{silence}][{raw_label}]concat=n=2:v=0:a=1[{placed_label}]")
                    placed.append(placed_label)
                else:
                    placed.append(raw_label)
            filters.append("".join(f"[{x}]" for x in placed) + f"amix=inputs={len(placed)}:duration=longest:normalize=0[{track_label}]")
        audio_labels.append(track_label)

    if audio_labels:
        joined = "".join(f"[{x}]" for x in audio_labels)
        filters.append(
            f"{joined}amix=inputs={len(audio_labels)}:duration=longest:normalize=0,"
            f"aresample=48000:async=1:first_pts=0,atrim=duration={main_duration:g}[amain]"
        )
    if project.outro.enabled:
        outro_audio_labels: list[str] = []
        for label, input_index in (("oaudio", outro_audio_index), ("osfx", outro_sfx_index)):
            if input_index is not None:
                filters.append(f"[{input_index}:a]atrim=duration={project.outro.duration:g},asetpts=N/SR/TB,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[{label}]")
                outro_audio_labels.append(label)
        if outro_audio_labels:
            filters.append("".join(f"[{x}]" for x in outro_audio_labels) + f"amix=inputs={len(outro_audio_labels)}:duration=longest:normalize=0,apad=whole_dur={project.outro.duration:g},atrim=duration={project.outro.duration:g}[aoutro]")
        else:
            filters.append(f"anullsrc=r=48000:cl=stereo:d={project.outro.duration:g}[aoutro]")
        if audio_labels:
            filters.append(f"[amain][aoutro]concat=n=2:v=0:a=1[apremaster]")
        else:
            filters.append(f"anullsrc=r=48000:cl=stereo:d={main_duration:g}[amainsilent]")
            filters.append("[amainsilent][aoutro]concat=n=2:v=0:a=1[apremaster]")
    elif audio_labels:
        filters.append("[amain]anull[apremaster]")
    if audio_labels or project.outro.enabled:
        policy = project.master_audio_policy
        processing_ceiling = policy.true_peak_ceiling_dbtp - policy.codec_headroom_db if policy else None
        if master_audio_mode == "premaster" and policy and policy.loudness_target_lufs is not None:
            # render() measures this lossless premaster and applies loudnorm's
            # measured second pass while muxing the atomic output candidate.
            filters.append(f"[apremaster]volume={premaster_attenuation_db:g}dB[aout]")
        elif policy and policy.loudness_target_lufs is not None:
            filters.append(f"[apremaster]loudnorm=I={policy.loudness_target_lufs:g}:TP={processing_ceiling:g}:LRA={policy.loudness_range_lu:g}[aout]")
        elif policy and policy.limiter:
            linear_limit = 10 ** (processing_ceiling / 20)
            filters.append(f"[apremaster]alimiter=limit={linear_limit:.8f}:attack=5:release=50:level=0[aout]")
        else:
            filters.append("[apremaster]anull[aout]")
    graph = ";".join(filters)
    argv += ["-filter_complex", graph, "-map", f"[{current_video}]"]
    if audio_labels or project.outro.enabled:
        argv += ["-map", "[aout]"]
    else:
        argv += ["-an"]
    argv += ["-t", f"{duration:g}", "-r", str(fps), "-c:v", project.output.video_codec, "-pix_fmt", project.output.pixel_format]
    if project.output.threads:
        argv += ["-threads", str(project.output.threads)]
    if project.output.video_bitrate:
        argv += ["-b:v", project.output.video_bitrate]
    if audio_labels or project.outro.enabled:
        argv += ["-c:a", project.output.audio_codec, "-b:a", project.output.audio_bitrate]
    argv += [project.output.path]
    clip_summary = []
    for _occurrence_no, (kind, track_id, track_index, clip_index, clip) in enumerate(inputs):
        item = {
            "inputIndex": source_indexes[clip.source], "kind": kind, "trackId": track_id,
            "trackIndex": track_index, "clipIndex": clip_index, "clipId": clip.id,
            "metadata": clip.metadata, "source": clip.source,
            "sourceRange": {"start": clip.in_point, "end": clip.in_point + clip.duration},
            "timeRange": {"start": clip.start, "end": clip.start + clip.duration},
            "cleanupRegions": [{"mode": item.mode, "region": {"x": item.x, "y": item.y, "width": item.width, "height": item.height},
                                "clipTime": {"start": item.start, "duration": item.duration},
                                "timelineTime": {"start": clip.start + item.start, "end": clip.start + item.start + (item.duration or clip.duration-item.start)},
                                "allowCaptionSafeBand": item.allow_caption_safe_band} for item in clip.cleanup_regions],
        }
        if kind == "video":
            start_frame, end_frame, visual_start, visual_end = _video_frame_range(clip, fps)
            item["visualFrameRange"] = {"startFrame": start_frame, "endFrameExclusive": end_frame,
                                        "start": visual_start, "end": visual_end,
                                        "frameCount": end_frame - start_frame}
        clip_summary.append(item)
    summary = {"duration": duration, "videoTracks": len(project.video_tracks),
               "audioTracks": len(project.audio_tracks), "subtitleTracks": len(project.subtitle_tracks),
               "inputCount": len(sources) + (1 if project.outro.enabled else 0) + (1 if outro_audio_index is not None else 0) + (1 if outro_sfx_index is not None else 0),
               "clips": clip_summary, "captions": caption_summary, "outro": outro_summary,
               "masterAudioPolicy": project.master_audio_policy.__dict__ if project.master_audio_policy else None,
               "masterAudioMode": master_audio_mode,
               "premasterAttenuationDb": premaster_attenuation_db if master_audio_mode == "premaster" else 0.0,
               "renderUsesMeasuredTwoPass": bool(project.master_audio_policy and project.master_audio_policy.loudness_target_lufs is not None),
               # Preserve the exact legacy renderPlan contract. Director metadata has
               # its own render-plan namespace so older strict consumers do not break.
               "renderPlan": {"audioMastering": "measured-two-pass" if project.master_audio_policy and project.master_audio_policy.loudness_target_lufs is not None else "single-pass",
                              "atomicOutput": True},
               "directorRenderPlan": {
                   "schema": "agentcut.materialized_shot_recipes.v1",
                   "registryId": recipe_coverage.get("registryId"),
                   "registryVersion": recipe_coverage.get("registryVersion"),
                   "clips": recipe_coverage.get("materializedTimeline", []),
                   "secondsAuthoritative": True,
                   "frameRounding": "nearest-half-up",
               },
               "shotRecipes": recipe_coverage,
               "assembly": {
                   "mode": project.assembly_mode,
                   "releaseEligible": not project.hold_slots and project.assembly_mode == "STANDARD",
                   "holdSlots": [
                       {"id": slot.id, "start": slot.start, "end": slot.end, "duration": slot.duration,
                        "mode": slot.mode, "reason": slot.reason,
                        "replacementCondition": slot.replacement_condition, "releaseBlocking": True}
                       for slot in project.hold_slots
                   ],
                   "platformMutationAuthorized": False,
               }}
    return CompiledCommand(argv, graph, summary)
