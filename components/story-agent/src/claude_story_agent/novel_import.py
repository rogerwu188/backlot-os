"""Deterministic, runtime-only novel import and series planning."""
from __future__ import annotations

import re

from .schemas import sha256_of

_CHAPTER_RE = re.compile(
    r"^\s*(?:第\s*[0-9〇零一二三四五六七八九十百千两]+\s*[章回节卷]|chapter\s+\d+|##+\s+\S)",
    re.IGNORECASE | re.MULTILINE,
)
_DIALOGUE_MARK_RE = re.compile(r"[「“\"『].+?[」”\"』]")
_ACTION_HINT_RE = re.compile(
    r"(杀|打|逃|追|夺|救|死|破|闯|抓|坠|烧|爆|偷|骗|揭|发现|决定|冲突|反转|威胁|背叛|"
    r"kill|fight|escape|chase|steal|betray|reveal|discover|decide|threat)",
    re.IGNORECASE,
)
_SPEAKER_RE = re.compile(r"([\w一-鿿]{2,4})(?:说|道|问|喊|答|叫)")


class NovelImportError(ValueError):
    """The requested import or plan would violate its source contract."""


def split_chapters(text: str) -> list[dict]:
    """Split source text into chapter metadata and in-memory chapter text."""
    if not isinstance(text, str) or not text.strip():
        raise NovelImportError("novel text must be a non-empty string")
    marks = list(_CHAPTER_RE.finditer(text))
    chapters: list[dict] = []
    if len(marks) >= 2:
        for index, mark in enumerate(marks):
            end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
            body = text[mark.start():end].strip()
            chapters.append({
                "index": index + 1,
                "title": body.splitlines()[0].strip(),
                "text": body,
                "char_count": len(re.sub(r"\s+", "", body)),
            })
    else:
        blocks: list[str] = []
        current: list[str] = []
        current_length = 0
        for paragraph in re.split(r"\n\s*\n", text):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            current.append(paragraph)
            current_length += len(re.sub(r"\s+", "", paragraph))
            if current_length >= 2000:
                blocks.append("\n\n".join(current))
                current, current_length = [], 0
        if current:
            blocks.append("\n\n".join(current))
        for index, body in enumerate(blocks):
            chapters.append({
                "index": index + 1,
                "title": f"segment-{index + 1}",
                "text": body,
                "char_count": len(re.sub(r"\s+", "", body)),
            })
    if not chapters:
        raise NovelImportError("no chapters or segments could be derived")
    return chapters


def extract_beats(chapter: dict) -> dict:
    """Extract deterministic action/dialogue beat and speaker candidates."""
    text = chapter["text"]
    sentences = [part.strip() for part in re.split(r"[。！？!?\n]+", text) if part.strip()]
    beats = []
    for sentence_index, sentence in enumerate(sentences):
        has_dialogue = bool(_DIALOGUE_MARK_RE.search(sentence))
        has_action = bool(_ACTION_HINT_RE.search(sentence))
        if has_action or has_dialogue:
            beats.append({
                "beat_index": len(beats) + 1,
                "sentence_index": sentence_index,
                "kind": "action" if has_action else "dialogue",
                "excerpt_chars": min(len(sentence), 60),
            })
    return {
        "chapter_index": chapter["index"],
        "beat_count": len(beats),
        "beats": beats,
        "character_candidates": sorted({m.group(1) for m in _SPEAKER_RE.finditer(text)}),
    }


def plan_series(
    chapters: list[dict],
    total_episodes: int,
    episode_duration_sec: float,
    duration_tolerance_sec: float = 15.0,
) -> dict:
    """Map source chapters to exactly the requested episode count without filler."""
    if not isinstance(total_episodes, int) or total_episodes < 1:
        raise NovelImportError("total_episodes must be a positive integer")
    if not chapters:
        raise NovelImportError("chapters must be non-empty")
    if not isinstance(episode_duration_sec, (int, float)) or episode_duration_sec <= 0:
        raise NovelImportError("episode_duration_sec must be > 0")
    if total_episodes > len(chapters) * 8:
        raise NovelImportError(
            "total_episodes far exceeds source material; refusing to plan filler episodes"
        )

    total_weight = sum(chapter["char_count"] for chapter in chapters) or 1
    weight_per_episode = total_weight / total_episodes
    episodes: list[list[int]] = []
    span: list[int] = []
    accumulated = 0.0
    for chapter in chapters:
        span.append(chapter["index"])
        accumulated += chapter["char_count"]
        while accumulated >= weight_per_episode and len(episodes) < total_episodes - 1:
            episodes.append(span)
            span = [chapter["index"]]
            accumulated -= weight_per_episode
            if accumulated < weight_per_episode:
                span = []
                break
    if span or len(episodes) < total_episodes:
        episodes.append(span or [chapters[-1]["index"]])
    while len(episodes) > total_episodes:
        tail = episodes.pop()
        episodes[-1] = sorted(set(episodes[-1] + tail))
    while len(episodes) < total_episodes:
        largest = max(range(len(episodes)), key=lambda i: len(episodes[i]))
        if len(episodes[largest]) < 2:
            raise NovelImportError(
                "not enough source chapters to fill the requested episode count without filler"
            )
        moved = episodes[largest][-1]
        episodes[largest] = episodes[largest][:-1]
        episodes.insert(largest + 1, [moved])

    plan = {
        "schema": "backlotos.series_plan.v1",
        "total_episodes": total_episodes,
        "episode_duration_sec": float(episode_duration_sec),
        "duration_tolerance_sec": float(duration_tolerance_sec),
        "pacing_policy": "backlotos.us-premium-streaming/1.1",
        "episodes": [
            {
                "episode_slot": index + 1,
                "source_chapters": sorted(set(chapter_ids)) or [chapters[-1]["index"]],
                "target_duration_sec": float(episode_duration_sec),
                "obligations": {
                    "opening_hook": True,
                    "mid_escalation": True,
                    "end_hook": True,
                    "no_recap": True,
                    "no_filler": True,
                    "every_scene_advances": True,
                },
            }
            for index, chapter_ids in enumerate(episodes)
        ],
    }
    plan["plan_sha256"] = sha256_of(plan["episodes"])
    return plan


def import_novel(text: str, total_episodes: int, episode_duration_sec: float) -> dict:
    """Split, analyze, and plan without persisting the supplied source text."""
    chapters = split_chapters(text)
    return {
        "ok": True,
        "chapter_count": len(chapters),
        "chapters": [
            {key: chapter[key] for key in ("index", "title", "char_count")}
            for chapter in chapters
        ],
        "analyses": [extract_beats(chapter) for chapter in chapters],
        "series_plan": plan_series(chapters, total_episodes, episode_duration_sec),
        "source_sha256": sha256_of(text),
    }
