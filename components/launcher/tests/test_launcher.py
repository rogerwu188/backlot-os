from __future__ import annotations

import json
import socket
import zipfile
from io import BytesIO

import pytest

from backlotos_launcher import intake
from backlotos_launcher.intake import _validate_public_url, extract_source
from backlotos_launcher.models import IntakeError, ProjectOptions
from backlotos_launcher.pipeline import create_project, credit_summary, record_credit, run_story_stage, status
from backlotos_launcher.web import Handler, LauncherServer
from backlotos_launcher import agent_host
from backlotos_launcher.agent_host import RoleDispatcher


def test_short_drama_defaults_are_one_click_defaults():
    options = ProjectOptions.from_values("short_drama", None, None, "9:16")
    assert options.episode_count == 200
    assert options.episode_duration_seconds == 180
    assert options.visual_format == "live_action"


def test_long_drama_defaults_are_editable_defaults():
    options = ProjectOptions.from_values("long_drama", None, None, "16:9")
    assert options.episode_count == 40
    assert options.episode_duration_seconds == 2700


@pytest.mark.parametrize("count,minutes", [(0, 3), (1001, 3), (20, 0.1), (20, 121)])
def test_invalid_episode_plan_rejected(count, minutes):
    with pytest.raises(IntakeError):
        ProjectOptions.from_values("short_drama", count, minutes, "9:16")


def test_html_extracts_story_and_drops_page_chrome():
    source = extract_source(
        b"<html><head><title>Night Run</title><style>bad</style></head><body><nav>menu</nav><article><h1>Chapter 1</h1><p>The door opened into danger.</p></article><script>bad()</script></body></html>",
        "story.html",
        media_type="text/html",
    )
    assert source.title == "Night Run"
    assert "door opened" in source.text
    assert "menu" not in source.text
    assert "bad()" not in source.text


def test_html_prefers_chapter_content_container_over_navigation():
    source = extract_source(
        b"<html><head><title>Chapter 9</title></head><body><div id='content'><p>controls and author</p><div id='htmlContent'><p>The actual chapter begins with a reversal.</p></div><p>next chapter</p></div></body></html>",
        "chapter.html", media_type="text/html")
    assert "actual chapter" in source.text
    assert "controls and author" not in source.text
    assert "next chapter" not in source.text


def test_docx_extraction_without_office_runtime():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", """<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>First chapter begins in motion.</w:t></w:r></w:p><w:p><w:r><w:t>The alarm changes everything.</w:t></w:r></w:p></w:body></w:document>""")
    source = extract_source(buffer.getvalue(), "novel.docx")
    assert "First chapter" in source.text
    assert "alarm changes" in source.text


def test_epub_extraction_without_browser_runtime():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("OPS/01.xhtml", "<html><body><p>A chase starts before dawn.</p><p>The witness disappears.</p></body></html>")
    source = extract_source(buffer.getvalue(), "novel.epub")
    assert "chase starts" in source.text
    assert "witness disappears" in source.text


def test_private_network_url_is_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(IntakeError, match="private"):
        _validate_public_url("https://example.test/story")


def test_url_credentials_are_rejected():
    with pytest.raises(IntakeError, match="credentials"):
        _validate_public_url("https://user:pass@example.com/story")


def test_novel_index_crawls_ordered_same_site_chapters_with_page_sha(monkeypatch):
    index = b"<html><head><title>Fast Story</title></head><body><a href='/c2'>Chapter 2</a><a href='javascript:;'>View all chapters</a><a href='/c1'>Chapter 1</a><a href='/c2'>Chapter 2</a><a href='https://other.test/c3'>Chapter 3</a><a href='/about'>About</a></body></html>"
    pages = {
        "https://books.test/index": ("https://books.test/index", index, "text/html"),
        "https://books.test/c1": ("https://books.test/c1", b"<html><head><title>Chapter 1</title></head><body><article>The chase begins before the warning can finish.</article></body></html>", "text/html"),
        "https://books.test/c2": ("https://books.test/c2", b"<html><head><title>Chapter 2</title></head><body><article>The witness switches sides and locks the only exit.</article></body></html>", "text/html"),
    }
    monkeypatch.setattr(intake, "_validate_public_url", lambda url: __import__("urllib.parse").parse.urlparse(url))
    monkeypatch.setattr(intake, "_robots_allowed", lambda url: True)
    monkeypatch.setattr(intake, "_fetch_url", lambda url, timeout: pages[url])
    source = intake.import_url("https://books.test/index")
    assert len(source.pages) == 2
    assert source.pages[0]["url"].endswith("/c1")
    assert "chase begins" in source.text
    assert "witness switches" in source.text
    assert "other.test" not in [page["url"] for page in source.pages]
    assert len(source.raw_sha256) == 64
    assert source.crawl == {"status": "PASS", "discovered": 2, "fetched_unique": 2, "fetch_failed": 0, "duplicates_removed": 0, "invalid_pages": 0}


def test_chapter_fetch_retries_transient_failure(monkeypatch):
    attempts = {"count": 0}
    def flaky(url, timeout):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise IntakeError("temporary HTTPError")
        return url, b"chapter", "text/plain"
    monkeypatch.setattr(intake, "_fetch_url", flaky)
    monkeypatch.setattr(intake.time, "sleep", lambda value: None)
    result = intake._fetch_url_retry("https://books.test/c1", 2)
    assert result[1] == b"chapter"
    assert attempts["count"] == 3


def test_partial_web_crawl_blocks_story_generation(tmp_path):
    source = extract_source(("Conflict changes everything. " * 30).encode(), "index.html", "https://books.test/index", "text/html")
    source = intake.ImportedSource(**{**source.__dict__, "crawl": {"status": "PARTIAL", "discovered": 10, "fetched_unique": 8, "fetch_failed": 2, "duplicates_removed": 0, "invalid_pages": 0}})
    project = create_project(source, ProjectOptions("short_drama", 2, 180, "9:16"), tmp_path)
    assert status(project)["pipeline"]["status"] == "SOURCE_PARTIAL"
    assert run_story_stage(project)["status"] == "BLOCKED_SOURCE_PARTIAL"


def test_five_agent_roles_are_explicit_and_missing_claude_adapter_is_honest(monkeypatch):
    monkeypatch.delenv("BACKLOT_PRODUCER_COMMAND", raising=False)
    producer = RoleDispatcher("producer")
    health = producer.health()
    result = producer.dispatch({"method": "supervise", "params": {}})
    assert health["semantic_adapter"] == "ADAPTER_REQUIRED"
    assert result["status"] == "CAPABILITY_FAIL"


def test_external_adapter_preserves_structured_failure_on_nonzero_exit(monkeypatch):
    monkeypatch.setenv("BACKLOT_PRODUCER_COMMAND", "adapter")
    monkeypatch.setattr(agent_host, "_command_available", lambda command: True)
    completed = agent_host.subprocess.CompletedProcess(
        ["adapter"], 1, stdout='{"ok":false,"status":"CAPABILITY_FAIL","error":"model missing"}', stderr="secret detail"
    )
    monkeypatch.setattr(agent_host.subprocess, "run", lambda *args, **kwargs: completed)
    result = agent_host._external("BACKLOT_PRODUCER_COMMAND", {"verb": "dispatch"})
    assert result["status"] == "CAPABILITY_FAIL"
    assert result["adapter_exit_code"] == 1
    assert "secret detail" not in json.dumps(result)


def test_pipeline_agent_records_exact_credit_receipt(tmp_path):
    source = extract_source(("A reversal changes the plan. " * 30).encode(), "novel.txt")
    project = create_project(source, ProjectOptions("short_drama", 1, 180, "9:16"), tmp_path)
    pipeline = RoleDispatcher("pipeline")
    result = pipeline.dispatch({"method": "recordCredit", "params": {
        "project": str(project), "episode_id": "E001", "stage": "video_generation",
        "consumed": 11, "refunded": 1, "provider": "provider", "provider_task_id": "job-1",
        "evidence_ref": "evidence/job-1.json", "final": True,
    }})
    assert result["ok"] is True
    assert result["summary"]["net"] == 10
    assert result["summary"]["status"] == "FINAL"


def test_story_agent_service_reports_model_gap_without_losing_review():
    health = RoleDispatcher("story").health()
    assert health["review"] == "SUPPORTED"
    assert health["generation"] in {"SUPPORTED", "ADAPTER_REQUIRED"}


def test_project_creates_full_200_episode_plan_without_padding(tmp_path):
    text = "\n\n".join(f"Chapter {n}: conflict changes direction with a new consequence." for n in range(1, 61))
    source = extract_source(text.encode(), "novel.txt")
    options = ProjectOptions("short_drama", 200, 180, "9:16", "animation")
    project = create_project(source, options, tmp_path)
    state = status(project)
    assert state["project"]["inputs"]["episode_count"] == 200
    assert state["project"]["inputs"]["visual_format"] == "animation"
    assert state["project"]["story_policy"]["padding_allowed"] is False
    assert len(list((project / "story" / "specs").glob("*.json"))) == 200
    assert len(list((project / "jobs" / "story").glob("*.json"))) == 200
    assert state["episode_plan"]["density"]["status"] == "WARN"
    serialized = json.dumps(state, ensure_ascii=False).lower()
    assert "copyright" not in serialized
    assert "版权" not in serialized


def test_source_provenance_and_append_only_events(tmp_path):
    source = extract_source(("A decisive chapter. " * 20).encode(), "novel.txt")
    project = create_project(source, ProjectOptions("short_drama", 2, 180, "9:16"), tmp_path)
    provenance = json.loads((project / "source" / "provenance.json").read_text())
    assert provenance["raw_sha256"] == source.raw_sha256
    events = (project / "events.ndjson").read_text().splitlines()
    assert len(events) == 1
    assert json.loads(events[0])["event"] == "PROJECT_CREATED"


def test_unconfigured_model_waits_without_fake_generation(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_STORY_COMMAND", "CLAUDE_STORY_MODE"):
        monkeypatch.delenv(name, raising=False)
    source = extract_source(("Conflict and consequence. " * 20).encode(), "novel.txt")
    project = create_project(source, ProjectOptions("short_drama", 2, 180, "9:16"), tmp_path)
    result = run_story_stage(project)
    assert result["status"] == "WAITING_FOR_MODEL"
    assert not list((project / "story" / "episodes").glob("*.json"))
    assert status(project)["pipeline"]["status"] == "WAITING_FOR_MODEL"


def test_web_form_has_only_source_and_core_production_choices(tmp_path):
    server = LauncherServer(("127.0.0.1", 0), Handler, tmp_path)
    try:
        handler = object.__new__(Handler)
        handler.server = server
        form = handler._form()
        for field in ("source_url", "source_file", "production_type", "visual_format", "episode_count", "episode_minutes", "aspect_ratio"):
            assert f"name='{field}'" in form
        assert "value='200'" in form
        assert "copyright" not in form.lower()
        assert "版权" not in form
    finally:
        server.server_close()


def test_workbench_recovers_projects_and_shows_every_episode(tmp_path):
    source = extract_source(("A reversal changes the plan. " * 30).encode(), "novel.txt")
    project = create_project(source, ProjectOptions("short_drama", 3, 180, "9:16"), tmp_path)
    server = LauncherServer(("127.0.0.1", 0), Handler, tmp_path)
    try:
        handler = object.__new__(Handler)
        handler.server = server
        dashboard = handler._dashboard()
        detail = handler._status(project, status(project))
        assert "制片厂总控台" in dashboard
        assert project.name in server.project_index
        assert all(f"E{n:03d}" in detail for n in range(1, 4))
        assert all(label in detail for label in ("剧本审核", "分镜", "素材", "剪辑", "成片审查"))
        assert "净 Credit" in detail
    finally:
        server.server_close()


def test_credit_ledger_is_append_only_and_sums_per_episode(tmp_path):
    source = extract_source(("A reversal changes the plan. " * 30).encode(), "novel.txt")
    project = create_project(source, ProjectOptions("short_drama", 2, 180, "9:16"), tmp_path)
    record_credit(project, "E001", "image_generation", 12, 2, 10, "provider-a", "task-1", "evidence/task-1.json")
    record_credit(project, "E001", "video_generation", 30, 0, 25, "provider-a", "task-2", final=False)
    record_credit(project, "E002", "video_generation", 7, 0, 7, "provider-b", "task-3")
    episode = credit_summary(project, "E001")
    whole = credit_summary(project)
    assert episode["status"] == "PROVISIONAL"
    assert episode["consumed"] == 42
    assert episode["refunded"] == 2
    assert episode["net"] == 40
    assert episode["by_stage"] == {"image_generation": 10.0, "video_generation": 30.0}
    assert whole["net"] == 47
    assert len((project / "credits.ndjson").read_text().splitlines()) == 3


def test_unreported_credit_is_not_claimed_as_zero_cost(tmp_path):
    source = extract_source(("A reversal changes the plan. " * 30).encode(), "novel.txt")
    project = create_project(source, ProjectOptions("short_drama", 1, 180, "9:16"), tmp_path)
    summary = credit_summary(project, "E001")
    assert summary["status"] == "NOT_REPORTED"
    assert summary["event_count"] == 0


def test_invalid_refund_is_rejected(tmp_path):
    source = extract_source(("A reversal changes the plan. " * 30).encode(), "novel.txt")
    project = create_project(source, ProjectOptions("short_drama", 1, 180, "9:16"), tmp_path)
    with pytest.raises(IntakeError):
        record_credit(project, "E001", "video_generation", 2, refunded=3)


def test_provider_retry_is_idempotent_and_later_receipt_supersedes(tmp_path):
    source = extract_source(("A reversal changes the plan. " * 30).encode(), "novel.txt")
    project = create_project(source, ProjectOptions("short_drama", 1, 180, "9:16"), tmp_path)
    first = record_credit(project, "E001", "video_generation", 30, 0, 30, "provider", "task-1", final=False)
    duplicate = record_credit(project, "E001", "video_generation", 30, 0, 30, "provider", "task-1", final=False)
    final = record_credit(project, "E001", "video_generation", 30, 5, 30, "provider", "task-1", final=True)
    summary = credit_summary(project, "E001")
    assert duplicate["event_id"] == first["event_id"]
    assert final["supersedes_event_id"] == first["event_id"]
    assert summary["event_count"] == 2
    assert summary["effective_cost_count"] == 1
    assert summary["net"] == 25
    assert summary["status"] == "FINAL"
