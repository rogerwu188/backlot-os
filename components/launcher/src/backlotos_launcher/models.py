from __future__ import annotations

from dataclasses import asdict, dataclass


class IntakeError(ValueError):
    """A safe, user-facing intake failure."""


@dataclass(frozen=True)
class ProjectOptions:
    production_type: str = "short_drama"
    episode_count: int = 200
    episode_duration_seconds: int = 180
    aspect_ratio: str = "9:16"
    visual_format: str = "live_action"

    def validate(self) -> "ProjectOptions":
        if self.production_type not in {"short_drama", "long_drama"}:
            raise IntakeError("production type must be short_drama or long_drama")
        if not 1 <= int(self.episode_count) <= 1000:
            raise IntakeError("episode count must be between 1 and 1000")
        if not 30 <= int(self.episode_duration_seconds) <= 7200:
            raise IntakeError("episode duration must be between 30 and 7200 seconds")
        if self.aspect_ratio not in {"9:16", "16:9"}:
            raise IntakeError("aspect ratio must be 9:16 or 16:9")
        if self.visual_format not in {"live_action", "animation"}:
            raise IntakeError("visual format must be live_action or animation")
        return self

    def to_dict(self) -> dict:
        self.validate()
        return asdict(self)

    @classmethod
    def from_values(
        cls,
        production_type: str,
        episode_count: str | int | None,
        episode_minutes: str | float | None,
        aspect_ratio: str,
        visual_format: str = "live_action",
    ) -> "ProjectOptions":
        default_episodes = 200 if production_type == "short_drama" else 40
        default_minutes = 3 if production_type == "short_drama" else 45
        try:
            count_value = default_episodes if episode_count is None or str(episode_count).strip() == "" else episode_count
            minute_value = default_minutes if episode_minutes is None or str(episode_minutes).strip() == "" else episode_minutes
            count = int(count_value)
            seconds = round(float(minute_value) * 60)
        except (TypeError, ValueError) as exc:
            raise IntakeError("episode count and duration must be numbers") from exc
        return cls(production_type, count, seconds, aspect_ratio, visual_format).validate()
