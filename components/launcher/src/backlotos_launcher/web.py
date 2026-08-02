from __future__ import annotations

import html
import json
import os
import secrets
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .intake import MAX_SOURCE_BYTES, extract_source, import_url
from .models import IntakeError, ProjectOptions
from .pipeline import create_project, credit_summary, start_in_background, status


_STYLE = """
:root{font-family:Inter,system-ui,sans-serif;color:#f3f3f3;background:#101214}*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:radial-gradient(circle at 20% 10%,#253246,#101214 45%)}
main{max-width:760px;margin:0 auto;padding:56px 24px}.card{background:#191d21;border:1px solid #343b43;border-radius:20px;padding:30px;box-shadow:0 24px 80px #0007}
h1{font-size:42px;margin:0 0 8px}.tag{color:#9da9b5;margin:0 0 30px}.field{margin:20px 0}label{display:block;font-weight:700;margin-bottom:8px}
input,select{width:100%;padding:14px;border-radius:10px;border:1px solid #46515c;background:#0e1113;color:#fff;font-size:16px}
.or{text-align:center;color:#8d98a3;margin:12px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
button{width:100%;border:0;border-radius:12px;padding:16px;background:#ffcf40;color:#171717;font-size:18px;font-weight:800;cursor:pointer}
.hint{color:#9da9b5;font-size:14px}.ok{color:#71dc9c}.warn{color:#ffd36a}.error{color:#ff8b8b}.stage{display:flex;justify-content:space-between;border-top:1px solid #32383e;padding:12px 0}
.top{display:flex;align-items:center;justify-content:space-between;gap:20px}.top a,.link{color:#ffcf40;text-decoration:none}.project{display:block;color:#fff;text-decoration:none;border:1px solid #343b43;border-radius:14px;padding:18px;margin:14px 0;background:#14181b}.project:hover{border-color:#ffcf40}.bar{height:8px;background:#30363c;border-radius:9px;overflow:hidden}.bar i{display:block;height:100%;background:#71dc9c}.tablewrap{overflow:auto;max-height:620px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid #30363c;white-space:nowrap}.pill{padding:4px 7px;border-radius:8px;background:#2a3036}.actions{display:flex;gap:12px}.actions a{background:#ffcf40;color:#171717;border-radius:10px;padding:11px 15px;text-decoration:none;font-weight:800}
@media(max-width:620px){.grid{grid-template-columns:1fr}h1{font-size:34px}}
"""


def _page(body: str, title: str = "BacklotOS") -> bytes:
    return f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>{html.escape(title)}</title><style>{_STYLE}</style></head><body><main>{body}</main></body></html>".encode("utf-8")


def _zh_status(value: str) -> str:
    return {
        "COMPLETE": "完成", "PASS": "通过", "STARTED": "已启动", "RUNNING": "进行中",
        "QUEUED": "排队中", "WAITING": "等待中", "WAITING_FOR_MODEL": "等待模型",
        "WAITING_FOR_STORY": "等待剧本", "WAITING_FOR_VISUAL_PLAN": "等待分镜",
        "WAITING_FOR_MEDIA": "等待素材", "WAITING_FOR_EDIT": "等待剪辑",
        "HUMAN_ONLY": "人工执行", "ATTENTION_REQUIRED": "需要处理",
        "CAPABILITY_FAIL": "能力不可用", "ERROR": "错误", "NOT_REPORTED": "未回报",
        "PARTIAL": "不完整", "SOURCE_PARTIAL": "原文不完整", "BLOCKED_SOURCE_PARTIAL": "原文不完整，已阻塞",
        "PROVISIONAL": "暂计", "FINAL": "已结算"
    }.get(str(value), str(value))


def _zh_option(value: str) -> str:
    return {"short_drama": "短剧", "long_drama": "长剧", "live_action": "真人", "animation": "动漫"}.get(value, value)


class LauncherServer(ThreadingHTTPServer):
    def __init__(self, address, handler, projects_root: Path | None = None):
        super().__init__(address, handler)
        self.csrf_token = secrets.token_urlsafe(24)
        self.projects_root = Path(projects_root or os.environ.get("BACKLOT_PROJECTS_DIR", Path.home() / "BacklotOS" / "projects")).expanduser().resolve()
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.project_index: dict[str, Path] = {}
        self.index_lock = threading.Lock()
        self.refresh_index()

    @property
    def intake_root(self):
        path = self.projects_root / ".intake"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def refresh_index(self):
        found = {}
        for config in self.projects_root.glob("*/project.json"):
            found[config.parent.name] = config.parent
        with self.index_lock:
            self.project_index.update(found)


class Handler(BaseHTTPRequestHandler):
    server: LauncherServer

    def log_message(self, format, *args):
        return

    def _send(self, code: int, payload: bytes, content_type="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._send(200, _page(self._dashboard(), "BacklotOS 制片厂总控台"))
            return
        if parsed.path == "/new":
            self._send(200, _page(self._form()))
            return
        if parsed.path.startswith("/intake/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            job_path = self.server.intake_root / job_id / "job.json"
            if not job_path.is_file():
                self._send(404, _page("<div class='card'><h1>导入任务不存在</h1></div>"))
                return
            job = json.loads(job_path.read_text(encoding="utf-8"))
            self._send(200, _page(self._intake_status(job), "原文导入进度"))
            return
        if parsed.path.startswith("/project/"):
            key = parsed.path.rsplit("/", 1)[-1]
            with self.server.index_lock:
                project = self.server.project_index.get(key)
            if not project:
                self._send(404, _page("<div class='card'><h1>项目不存在</h1></div>"))
                return
            try:
                state = status(project)
                self._send(200, _page(self._status(project, state), state["project"]["title"]))
            except Exception as exc:
                self._send(500, _page(f"<div class='card'><h1>状态读取失败</h1><p class='error'>{html.escape(str(exc))}</p></div>"))
            return
        if parsed.path == "/api/projects":
            self.server.refresh_index()
            projects = []
            with self.server.index_lock:
                indexed = list(self.server.project_index.items())
            for key, project in indexed:
                try:
                    projects.append(self._project_summary(key, project, status(project)))
                except Exception:
                    continue
            self._send(200, json.dumps({"status": "PASS", "projects": projects}, ensure_ascii=False).encode(), "application/json")
            return
        if parsed.path == "/health":
            self._send(200, json.dumps({"status": "ready", "service": "backlotos-launcher"}).encode(), "application/json")
            return
        self._send(404, _page("<div class='card'><h1>页面不存在</h1></div>"))

    def do_POST(self):
        if self.path != "/projects":
            self._send(404, b"not found", "text/plain")
            return
        try:
            fields, upload = self._multipart()
            if fields.get("csrf") != self.server.csrf_token:
                raise IntakeError("页面已过期，请刷新后重试")
            options = ProjectOptions.from_values(fields.get("production_type", "short_drama"), fields.get("episode_count"), fields.get("episode_minutes"), fields.get("aspect_ratio", "9:16"), fields.get("visual_format", "live_action"))
            source_url = fields.get("source_url", "").strip()
            if source_url and upload:
                raise IntakeError("网址和文件只需提供一个")
            if not source_url and not upload:
                raise IntakeError("请输入小说网址或上传电子书")
            job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
            job_dir = self.server.intake_root / job_id
            job_dir.mkdir(parents=True, exist_ok=False)
            request = {"source_url": source_url or None, "upload_name": upload[0] if upload else None, "upload_media_type": upload[2] if upload else None, "options": options.to_dict()}
            if upload:
                (job_dir / "upload.bin").write_bytes(upload[1])
            _write_job(job_dir, {"schema": "backlotos.intake-job/1.0", "job_id": job_id, "status": "QUEUED", "created_at": _now(), "updated_at": _now(), "request": request, "progress": {"phase": "queued", "discovered": 0, "completed": 0, "failed": 0}})
            threading.Thread(target=_run_intake_job, args=(self.server, job_dir), name=f"backlotos-intake-{job_id}", daemon=True).start()
            self.send_response(303)
            self.send_header("Location", f"/intake/{job_id}")
            self.end_headers()
        except IntakeError as exc:
            self._send(400, _page(self._form(str(exc)), "无法启动"))
        except Exception as exc:
            self._send(500, _page(self._form(f"启动失败：{type(exc).__name__}"), "启动失败"))

    def _multipart(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise IntakeError("请求大小无效") from exc
        if not 0 < length <= MAX_SOURCE_BYTES + 1024 * 1024:
            raise IntakeError("上传内容超过限制")
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raise IntakeError("表单格式无效")
        raw = self.rfile.read(length)
        message = BytesParser(policy=default).parsebytes(f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw)
        fields: dict[str, str] = {}
        upload = None
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            filename = part.get_filename()
            data = part.get_payload(decode=True) or b""
            if filename and data:
                upload = (Path(filename).name, data, part.get_content_type())
            elif name:
                fields[name] = data.decode(part.get_content_charset() or "utf-8", errors="replace")
        return fields, upload

    def _form(self, error: str = "") -> str:
        alert = f"<p class='error'>{html.escape(error)}</p>" if error else ""
        return f"""<div class='card'><div class='top'><div><h1>新建作品</h1><p class='tag'>给我一个故事，剩下的交给制片厂。</p></div><a href='/'>返回总控台</a></div>{alert}
<form method='post' action='/projects' enctype='multipart/form-data'>
<input type='hidden' name='csrf' value='{self.server.csrf_token}'>
<div class='field'><label>小说网址</label><input name='source_url' type='url' placeholder='https://example.com/novel'></div>
<div class='or'>或者</div><div class='field'><label>上传电子书</label><input name='source_file' type='file' accept='.txt,.md,.markdown,.html,.htm,.pdf,.epub,.docx'><p class='hint'>支持 TXT、Markdown、HTML、PDF、EPUB、DOCX，最大 100 MB</p></div>
<div class='grid'><div class='field'><label>作品类型</label><select name='production_type' id='kind' onchange="document.getElementById('episodes').value=this.value==='short_drama'?200:40;document.getElementById('minutes').value=this.value==='short_drama'?3:45"><option value='short_drama'>短剧</option><option value='long_drama'>长剧</option></select></div>
<div class='field'><label>视觉形态</label><select name='visual_format'><option value='live_action'>真人</option><option value='animation'>动漫</option></select></div>
<div class='field'><label>总集数</label><input id='episodes' name='episode_count' type='number' min='1' max='1000' value='200' required></div>
<div class='field'><label>每集时长（分钟）</label><input id='minutes' name='episode_minutes' type='number' min='.5' max='120' step='.5' value='3' required></div>
<div class='field'><label>画幅</label><select name='aspect_ratio'><option value='9:16'>9:16 竖屏</option><option value='16:9'>16:9 横屏</option></select></div></div>
<button type='submit'>确认并启动生产线</button></form></div>"""

    def _status(self, project: Path, state: dict) -> str:
        config, pipeline, plan = state["project"], state["pipeline"], state["episode_plan"]
        stage_names = {"source_import":"原文导入","story_generation":"剧本生成","story_review":"剧本审核","visual_planning":"分镜规划","media_generation":"素材生成","editing":"剪辑","final_review":"成片审查","release":"发布"}
        stages = "".join(f"<div class='stage'><span>{stage_names.get(stage['id'], html.escape(stage['id']))}</span><strong>{html.escape(_zh_status(stage['status']))}</strong></div>" for stage in pipeline["stages"])
        density = plan["density"]
        episode_rows = []
        for episode_path in sorted((project / "episodes").glob("*.json")):
            try:
                episode = json.loads(episode_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            statuses = {item["id"]: item["status"] for item in episode.get("stages", [])}
            credits = credit_summary(project, episode.get("episode_id", episode_path.stem))
            credit_text = f"{credits['net']:g}" if credits["status"] != "NOT_REPORTED" else "未回报"
            episode_rows.append("<tr><td><strong>{}</strong></td>{}<td><span class='pill'>{}</span></td></tr>".format(
                html.escape(episode.get("episode_id", episode_path.stem)),
                "".join(f"<td><span class='pill'>{html.escape(_zh_status(statuses.get(stage, 'WAITING')))}</span></td>" for stage in ("story_generation", "story_review", "visual_planning", "media_generation", "editing", "review")), html.escape(credit_text)))
        table = "<div class='tablewrap'><table><thead><tr><th>集</th><th>剧本</th><th>剧本审核</th><th>分镜</th><th>素材</th><th>剪辑</th><th>成片审查</th><th>净 Credit</th></tr></thead><tbody>" + "".join(episode_rows) + "</tbody></table></div>"
        return f"""<div class='card'><div class='top'><div><h1>{html.escape(config['title'])}</h1><p class='ok'>生产线已启动</p></div><a href='/'>返回总控台</a></div>
<p>{config['inputs']['episode_count']} 集 · 每集 {config['inputs']['episode_duration_seconds']/60:g} 分钟 · {config['inputs']['aspect_ratio']} · {html.escape(_zh_option(config['inputs']['production_type']))} · {html.escape(_zh_option(config['inputs']['visual_format']))}</p><p><strong>项目净 Credit：{state['credits']['net'] if state['credits']['status'] != 'NOT_REPORTED' else '未回报'}</strong> · {html.escape(_zh_status(state['credits']['status']))}</p>
<p class='{'warn' if density['status']=='WARN' else 'ok'}'>{html.escape(density['message'])}（{density['characters_per_minute']} 字/分钟）</p>{stages}
<h2>逐集流水线</h2>{table}<p class='hint'>项目保存在：{html.escape(str(project))}</p><p class='hint'>页面每 10 秒自动刷新；发布不由本工作台自动执行。</p><script>setTimeout(()=>location.reload(),10000)</script></div>"""

    def _project_summary(self, key: str, project: Path, state: dict) -> dict:
        pipeline = state["pipeline"]
        story = next((stage for stage in pipeline["stages"] if stage["id"] == "story_generation"), {})
        total = int(story.get("total", state["project"]["inputs"]["episode_count"]))
        complete = int(story.get("complete", 0))
        return {"key": key, "title": state["project"]["title"], "status": pipeline["status"], "total": total, "complete": complete, "percent": round(100 * complete / max(total, 1)), "credits": state["credits"], "updated_at": pipeline.get("updated_at"), "path": str(project)}

    def _dashboard(self) -> str:
        self.server.refresh_index()
        cards = []
        with self.server.index_lock:
            indexed = sorted(self.server.project_index.items(), reverse=True)
        for key, project in indexed:
            try:
                summary = self._project_summary(key, project, status(project))
            except Exception:
                continue
            credit_text = f"{summary['credits']['net']:g} credit" if summary['credits']['status'] != 'NOT_REPORTED' else "credit 未回报"
            cards.append(f"<a class='project' href='/project/{urllib.parse.quote(key)}'><strong>{html.escape(summary['title'])}</strong><p>{summary['complete']} / {summary['total']} 集 · {html.escape(_zh_status(summary['status']))} · {html.escape(credit_text)}</p><div class='bar'><i style='width:{summary['percent']}%'></i></div></a>")
        intake_cards = []
        for job_path in sorted(self.server.intake_root.glob("*/job.json"), reverse=True):
            try:
                job = json.loads(job_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if job.get("status") not in {"COMPLETE"}:
                progress = job.get("progress", {})
                intake_cards.append(f"<a class='project' href='/intake/{html.escape(job['job_id'])}'><strong>原文导入</strong><p>{html.escape(_zh_status(job['status']))} · {progress.get('completed',0)} / {progress.get('discovered',0)} 页 · 失败 {progress.get('failed',0)}</p></a>")
        empty = "<p class='hint'>还没有项目。创建第一部作品后，这里会显示整条生产线进度。</p>" if not cards and not intake_cards else ""
        return f"""<div class='card'><div class='top'><div><h1>制片厂总控台</h1><p class='tag'>所有作品、所有集数、每一道工序。</p></div><div class='actions'><a href='/new'>新建作品</a></div></div>{empty}{''.join(intake_cards)}{''.join(cards)}<p class='hint'>工作台读取本机项目状态，重启后仍会恢复。</p><script>setTimeout(()=>location.reload(),15000)</script></div>"""

    def _intake_status(self, job: dict) -> str:
        progress = job.get("progress", {})
        destination = f"/project/{urllib.parse.quote(job['project_key'])}" if job.get("status") in {"COMPLETE", "PARTIAL"} and job.get("project_key") else None
        redirect = f"<script>setTimeout(()=>location.href='{destination}',1200)</script>" if destination else "<script>setTimeout(()=>location.reload(),3000)</script>"
        error = f"<p class='error'>{html.escape(job.get('error',''))}</p>" if job.get("status") == "ERROR" else ""
        return f"""<div class='card'><div class='top'><div><h1>原文导入</h1><p class='tag'>正在建立完整、可验证的故事源。</p></div><a href='/'>返回总控台</a></div><p><strong>{html.escape(_zh_status(job.get('status','QUEUED')))}</strong></p>{error}<div class='stage'><span>发现章节</span><strong>{progress.get('discovered',0)}</strong></div><div class='stage'><span>已处理</span><strong>{progress.get('completed',0)}</strong></div><div class='stage'><span>失败</span><strong>{progress.get('failed',0)}</strong></div><p class='hint'>完成后会自动进入逐集生产工作台。</p>{redirect}</div>"""


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_job(job_dir: Path, payload: dict):
    path = job_dir / "job.json"
    temp = job_dir / "job.json.partial"
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _run_intake_job(server: LauncherServer, job_dir: Path):
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    job["status"] = "RUNNING"
    job["updated_at"] = _now()
    _write_job(job_dir, job)
    def progress(value):
        current = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        current["progress"] = value
        current["updated_at"] = _now()
        _write_job(job_dir, current)
    try:
        request = job["request"]
        if request.get("source_url"):
            source = import_url(request["source_url"], progress=progress)
        else:
            source = extract_source((job_dir / "upload.bin").read_bytes(), request["upload_name"], media_type=request.get("upload_media_type") or "")
        options = ProjectOptions(**request["options"]).validate()
        project = create_project(source, options, server.projects_root)
        with server.index_lock:
            server.project_index[project.name] = project
        start_in_background(project)
        current = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        intake_status = "PASS" if not source.crawl or source.crawl.get("status") == "PASS" else "PARTIAL"
        current.update({"status": "COMPLETE" if intake_status == "PASS" else "PARTIAL", "updated_at": _now(), "project_key": project.name, "project_path": str(project), "source_sha256": source.raw_sha256, "crawl": source.crawl})
        _write_job(job_dir, current)
    except Exception as exc:
        current = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        current.update({"status": "ERROR", "updated_at": _now(), "error": f"导入失败（{type(exc).__name__}）：{exc}"})
        _write_job(job_dir, current)


def serve(host="127.0.0.1", port=8787, projects_root: Path | None = None, open_browser=True):
    server = LauncherServer((host, port), Handler, projects_root)
    url = f"http://{host}:{server.server_port}/"
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    print(f"BacklotOS is ready: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
