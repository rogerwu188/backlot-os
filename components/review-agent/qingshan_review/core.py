from __future__ import annotations

import hashlib, json, math, os, re, shlex, shutil, statistics, subprocess, tempfile, threading, wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from .shot_recipe import CAPABILITIES as SHOT_RECIPE_CAPABILITIES, audit_shot_recipe

RULE_VERSION = "qingshan.review.rules.v25"
ACTION_MOTION_PROFILE = {"version":"qingshan.action-motion-physics.v1","near_duplicate_ratio_max":.15,"required_physics_checks":["wind_up","contact","force_transfer","result","real_hand_prop_contact","no_floating_hands","no_object_drift","complete_action_head_tail"]}
STORY_DURATION_PROFILE = {"version":"qingshan.shot_generation_duration.v1","minimum_seconds":4.0,"maximum_seconds":15.0,"encoding_tolerance_seconds":.20}
EPISODE_RUNTIME_PROFILE = {"version":"qingshan.episode-runtime.v2.0.0","target_seconds":180.0,"soft_tolerance_seconds":10.0,"hard_tolerance_seconds":20.0}
VISUAL_PACING_PROFILE = {"version":"qingshan.visual-pacing.v1.0.0","max_consecutive_similar_shots":2,"max_same_signature_in_20_seconds":3,"max_single_scene_without_visual_change_seconds":45.0,"max_sources_per_natural_unit":2,"warn_natural_unit_seconds":15.0,"fail_natural_unit_seconds":20.0}
OCR_PROFILE = {"version":"qingshan.ocr.normalized-decision.v2","default_brand_allowlist":["NALU MOTION"],"single_hit_confidence":.85,"persistence_min_samples":2,"persistence_gap_multiplier":1.5}
AUDIO_PROFILE = {"version":"qingshan.audio.v3-boundary-local","digital_zero_db":-90.0,"silence_db":-70.0,"min_silence_seconds":1.0,"max_adjacent_rms_jump_db":12.0,"window_seconds":0.5,"boundary_window_seconds":0.12}
AMBIENCE_PROFILE = {"version":"qingshan.ambience.v1","gain_warn":1.0,"gain_block":1.5,"short_loop_seconds":8.0,"repeat_warn":3,"repeat_block":8,"min_crossfade_seconds":0.3,"source_hiss_db":-50.0,"projected_hiss_db":-42.0,"dialogue_headroom_warn_db":18.0,"dialogue_headroom_block_db":12.0,"baseline_hiss_warn_delta_db":3.0,"baseline_hiss_block_delta_db":6.0}
IMPORTANCE_THRESHOLDS = {"utility": 3.0, "standard": 3.5, "important": 4.0, "critical": 4.5}
SEVERITY_DEDUCTIONS = {"info": 0.10, "warning": 0.35, "error": 1.00, "critical": 2.00}
WARNING_DEDUCTION_CAPS = {"audio.rms_jump": 1.0, "default": 1.4}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
AUDIO_EXT = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
CAPABILITIES = {"media_probe","video_analysis","action_physics","black_frame_analysis","story_duration","episode_runtime","visual_pacing","audio_analysis","ambience_analysis","ocr","image_analysis","image_clarity","image_brightness","composition","visual_continuity","asr","sentence_audit","voiceprint","action","scene_brightness","coverage","agentcut_project","regression_ci",*SHOT_RECIPE_CAPABILITIES}
CAPABILITY_ALIASES = {"audio":"audio_analysis","video":"video_analysis","sentence":"sentence_audit","speaker":"voiceprint","brightness":"scene_brightness","coverage_manifest":"coverage"}

def now() -> str: return datetime.now(timezone.utc).isoformat()
def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def media_kind(path: Path) -> str:
    s=path.suffix.lower()
    if s in VIDEO_EXT: return "video"
    if s in AUDIO_EXT: return "audio"
    if s in IMAGE_EXT: return "image"
    return "unknown"

def locate_binary(name: str) -> str|None:
    direct=shutil.which(name)
    if direct: return direct
    configured_dir=os.environ.get("BACKLOT_MEDIA_BIN_DIR")
    candidates=[
      Path(configured_dir)/name if configured_dir else None,
      Path("/usr/local/bin")/name,
      Path("/opt/homebrew/bin")/name,
      Path("/usr/bin")/name,
    ]
    return next((str(p) for p in candidates if p is not None and p.is_file()), None)

def stable_issue(rule: str, path: Path, location: dict[str,Any], severity="warning", confidence=.8,
                 recommendation="人工复核并替换或修复对应媒体区间", blocking=False, evidence=None,
                 region=None, details=None) -> dict[str,Any]:
    canonical=json.dumps([rule,str(path.resolve()),location,region],sort_keys=True,ensure_ascii=False)
    iid="QSR-"+hashlib.sha256(canonical.encode()).hexdigest()[:16].upper()
    details=details or {}
    return {"issue_id":iid,"rule_id":rule,"rule_version":RULE_VERSION,"severity":severity,"actionable":bool(details.get("actionable",severity!="info")),
      "media_path":str(path.resolve()),"location":location,"region":region,
      "evidence":evidence or [],"confidence":round(float(confidence),4),
      "recommendation":recommendation,"blocking":bool(blocking),
      "decision":{"state":"machine","rollback_allowed":True,"history":[]},"details":details}

def score_issues(issues: list[dict[str,Any]], importance: str="standard", pass_score: float|None=None) -> dict[str,Any]:
    if importance not in IMPORTANCE_THRESHOLDS: raise ValueError(f"unknown importance: {importance}")
    threshold=float(pass_score if pass_score is not None else IMPORTANCE_THRESHOLDS[importance])
    if not 1.0 <= threshold <= 5.0: raise ValueError("pass_score must be between 1 and 5")
    deductions=[]; category_totals={}; cap_summary={}
    for issue in issues:
        actionable=issue.get("actionable",issue.get("details",{}).get("actionable",True));uncapped=0.0 if not actionable else SEVERITY_DEDUCTIONS.get(issue.get("severity","warning"),.35)*float(issue.get("confidence",1)); amount=uncapped
        if issue.get("severity")=="warning" and not issue.get("blocking"):
          rule=issue.get("rule_id","unknown"); cap=WARNING_DEDUCTION_CAPS.get(rule,WARNING_DEDUCTION_CAPS["default"]); used=category_totals.get(rule,0.0); amount=max(0.0,min(uncapped,cap-used));category_totals[rule]=used+amount
          row=cap_summary.setdefault(rule,{"cap":cap,"uncapped_total":0.0,"applied_total":0.0});row["uncapped_total"]+=uncapped;row["applied_total"]+=amount
        deductions.append({"issue_id":issue["issue_id"],"severity":issue.get("severity"),"amount":round(amount,2),"uncapped_amount":round(uncapped,2)})
    score=round(max(1.0,5.0-sum(x["amount"] for x in deductions)),2)
    hard_gate=any(x.get("blocking") for x in issues)
    return {"scale":"1-5","score":score,"pass_score":threshold,"importance":importance,
      "score_passed":score>=threshold,"hard_gate_passed":not hard_gate,
      "passed":score>=threshold and not hard_gate,"deductions":deductions,"deduction_cap":{k:{x:round(y,2) for x,y in v.items()} for k,v in cap_summary.items()},
      "policy":"Hard gates override numeric score; importance only changes the numeric pass threshold."}

def adjudicate_audio_cut(samples:list[int],rate:int,cut_seconds:float,window_seconds:float=.12) -> dict[str,Any]:
    if not samples or rate<=0:return {"status":"ERROR","motivated":False,"audible_discontinuity":True,"reason":"audio_samples_unavailable"}
    center=max(0,min(len(samples)-1,int(cut_seconds*rate)));window=max(8,int(window_seconds*rate));guard=max(4,int(.02*rate))
    def db(chunk):
      if not chunk:return -120.0
      rms=math.sqrt(sum(x*x for x in chunk)/len(chunk))/32768;return 20*math.log10(max(rms,1e-12))
    before=samples[max(0,center-window):center];after=samples[center:min(len(samples),center+window)];middle=samples[max(0,center-guard):min(len(samples),center+guard)]
    before_db=db(before);after_db=db(after);middle_db=db(middle);digital_zero=before_db<=-90 or after_db<=-90
    dropout=middle_db<=-70 and before_db>-55 and after_db>-55
    discontinuity=abs(samples[center]-samples[center-1])/32768 if center>0 else 0.0; local_peak=max([abs(x) for x in middle] or [0])/32768; click=discontinuity>.75 and local_peak>.8
    audible=digital_zero or dropout or click
    return {"status":"FAIL" if audible else "PASS","motivated":not audible,"audible_discontinuity":audible,"reason":"digital_zero" if digital_zero else "dropout" if dropout else "click" if click else "continuous_bed_or_speech_dynamics","cut_seconds":cut_seconds,"window_seconds":window_seconds,"before_rms_db":round(before_db,3),"after_rms_db":round(after_db,3),"center_rms_db":round(middle_db,3),"sample_discontinuity":round(discontinuity,5),"local_peak":round(local_peak,5),"checks":{"digital_zero":digital_zero,"dropout":dropout,"click":click}}

def deduplicate_issues(raw: list[dict[str,Any]], adjacency_seconds: float=.5) -> list[dict[str,Any]]:
    temporal={}; passthrough=[]
    for issue in raw:
      loc=issue.get("location") or {}; start=loc.get("start_seconds");end=loc.get("end_seconds")
      if not isinstance(start,(int,float)) or not isinstance(end,(int,float)): passthrough.append(issue);continue
      recipe_identity=(issue.get("recipe_id") or issue.get("details",{}).get("recipe_id"),issue.get("recipe_phase") or issue.get("details",{}).get("recipe_phase")) if str(issue.get("rule_id","")).startswith("shot_recipe.") else (None,None)
      temporal.setdefault((issue.get("rule_id"),issue.get("media_path"),*recipe_identity),[]).append(issue)
    result=list(passthrough)
    for _,items in temporal.items():
      items=sorted(items,key=lambda x:(float(x["location"]["start_seconds"]),float(x["location"]["end_seconds"])))
      clusters=[]
      for issue in items:
       start=float(issue["location"]["start_seconds"]);end=float(issue["location"]["end_seconds"])
       if not clusters or start>clusters[-1]["end"]+adjacency_seconds: clusters.append({"start":start,"end":end,"items":[issue]})
       else: clusters[-1]["end"]=max(clusters[-1]["end"],end);clusters[-1]["items"].append(issue)
      for cluster in clusters:
       members=cluster["items"]
       def priority(x):
        source=x.get("details",{}).get("source_adapter"); peak=float(x.get("details",{}).get("jump_db",0) or 0)
        return (1 if source=="production_regression" else 0,peak,x.get("confidence",0))
       representative=max(members,key=priority); merged={**representative,"details":dict(representative.get("details",{}))}
       if len(members)>1:
        merged["details"]["deduplication"]={"raw_count":len(members),"raw_issue_ids":[x["issue_id"] for x in members],"sources":sorted({x.get("details",{}).get("source_adapter","unknown") for x in members}),"cluster_range":{"start_seconds":cluster["start"],"end_seconds":cluster["end"]},"child_evidence":[{"issue_id":x["issue_id"],"location":x["location"],"evidence":x.get("evidence",[]),"details":x.get("details",{})} for x in members]}
       result.append(merged)
    return sorted(result,key=lambda x:(x.get("media_path",""),float((x.get("location") or {}).get("start_seconds",-1)),x.get("rule_id","")))

def probe(path: Path, ffprobe: str|None) -> dict[str,Any]:
    if not ffprobe: return {"available":False}
    p=subprocess.run([ffprobe,"-v","error","-show_streams","-show_format","-of","json",str(path)],capture_output=True,text=True)
    if p.returncode: return {"available":True,"error":p.stderr.strip()}
    return json.loads(p.stdout)

def probe_image(path: Path) -> dict[str,Any]:
    """Validate common still-image containers without requiring ffprobe."""
    try:
      data=path.read_bytes()
      if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data)>=24:
        width=int.from_bytes(data[16:20],"big");height=int.from_bytes(data[20:24],"big");codec="png"
      elif data[:6] in {b"GIF87a",b"GIF89a"} and len(data)>=10:
        width=int.from_bytes(data[6:8],"little");height=int.from_bytes(data[8:10],"little");codec="gif"
      elif data.startswith(b"BM") and len(data)>=26:
        width=int.from_bytes(data[18:22],"little",signed=True);height=abs(int.from_bytes(data[22:26],"little",signed=True));codec="bmp"
      elif data.startswith(b"\xff\xd8"):
        width=height=0;i=2
        while i+9<len(data):
          if data[i]!=0xff:i+=1;continue
          marker=data[i+1];i+=2
          if marker in {0xd8,0xd9}:continue
          if i+2>len(data):break
          size=int.from_bytes(data[i:i+2],"big")
          if marker in {0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf} and i+7<len(data):
            height=int.from_bytes(data[i+3:i+5],"big");width=int.from_bytes(data[i+5:i+7],"big");break
          if size<2:break
          i+=size
        codec="jpeg"
      elif data.startswith(b"RIFF") and data[8:12]==b"WEBP":
        width=height=0;codec="webp"
      else:return {"available":True,"error":"unsupported or corrupt image container"}
      if codec!="webp" and (width<=0 or height<=0):return {"available":True,"error":"invalid image dimensions"}
      return {"available":True,"streams":[{"codec_type":"video","codec_name":codec,"width":width,"height":height}],"format":{"filename":str(path),"format_name":codec,"size":str(len(data))},"source_adapter":"builtin_image_probe"}
    except Exception as exc:return {"available":True,"error":f"{type(exc).__name__}: {exc}"}

def measured_mean_db(path:Path,ffmpeg:str|None,highpass_hz:float|None=None) -> float|None:
    if not ffmpeg or not path.is_file():return None
    filters=[]
    if highpass_hz:filters.append(f"highpass=f={float(highpass_hz)}")
    filters.append("volumedetect")
    try:p=subprocess.run([ffmpeg,"-hide_banner","-nostats","-i",str(path),"-vn","-af",",".join(filters),"-f","null","-"],capture_output=True,text=True,timeout=60)
    except subprocess.TimeoutExpired:return None
    matches=re.findall(r"mean_volume:\s*(-?[0-9.]+)\s*dB",p.stderr)
    return float(matches[-1]) if matches else None

def audio_pcm(path: Path, ffmpeg: str|None) -> tuple[int,list[int]]:
    if path.suffix.lower()==".wav":
        try:
            with wave.open(str(path),"rb") as w:
                rate=w.getframerate(); width=w.getsampwidth(); channels=w.getnchannels(); raw=w.readframes(w.getnframes())
            if width==2:
                import array; a=array.array("h"); a.frombytes(raw)
                if channels>1:
                    samples=list(a); mono=[round(sum(samples[i:i+channels])/channels) for i in range(0,len(samples),channels)]
                    return rate,mono
                return rate,list(a)
        except Exception: pass
    if not ffmpeg: return 0,[]
    p=subprocess.run([ffmpeg,"-v","error","-i",str(path),"-vn","-ac","1","-ar","16000","-f","s16le","-"],capture_output=True)
    if p.returncode: return 0,[]
    import array; a=array.array("h"); a.frombytes(p.stdout); return 16000,list(a)

def sanitize_issue_time_ranges(issues:list[dict[str,Any]],duration:float,boundary_tolerance_seconds:float=.05) -> list[dict[str,Any]]:
    invalid=[]
    if duration<=0:return invalid
    for issue in issues:
      loc=issue.get("location") or {};start=loc.get("start_seconds");end=loc.get("end_seconds")
      if not isinstance(start,(int,float)) and not isinstance(end,(int,float)):continue
      original={"start_seconds":start,"end_seconds":end};slight=(isinstance(start,(int,float)) and (-boundary_tolerance_seconds<=start<0 or duration<start<=duration+boundary_tolerance_seconds)) or (isinstance(end,(int,float)) and (-boundary_tolerance_seconds<=end<0 or duration<end<=duration+boundary_tolerance_seconds))
      if slight:
       if isinstance(start,(int,float)) and (-boundary_tolerance_seconds<=start<0 or duration<start<=duration+boundary_tolerance_seconds):loc["start_seconds"]=max(0.0,min(float(start),duration))
       if isinstance(end,(int,float)) and (-boundary_tolerance_seconds<=end<0 or duration<end<=duration+boundary_tolerance_seconds):loc["end_seconds"]=max(0.0,min(float(end),duration))
       issue["location"]=loc;issue.setdefault("details",{})["time_range_sanitization"]={"status":"BENIGN_BOUNDARY_ROUNDING_CLAMPED","original":original,"duration_seconds":duration,"tolerance_seconds":boundary_tolerance_seconds}
       start=loc.get("start_seconds");end=loc.get("end_seconds")
      bad=(isinstance(start,(int,float)) and (start<0 or start>duration)) or (isinstance(end,(int,float)) and (end<0 or end>duration)) or (isinstance(start,(int,float)) and isinstance(end,(int,float)) and start>end)
      if not bad:continue
      if isinstance(start,(int,float)):loc["start_seconds"]=max(0.0,min(float(start),duration))
      if isinstance(end,(int,float)):loc["end_seconds"]=max(0.0,min(float(end),duration))
      if isinstance(loc.get("start_seconds"),(int,float)) and isinstance(loc.get("end_seconds"),(int,float)) and loc["end_seconds"]<loc["start_seconds"]:loc["end_seconds"]=loc["start_seconds"]
      issue["location"]=loc;issue["blocking"]=False;issue["actionable"]=False;issue.setdefault("details",{})["time_range_sanitization"]={"status":"INVALID_CLAMPED_EXCLUDED_FROM_SCORING","original":original,"duration_seconds":duration}
      invalid.append({"issue_id":issue.get("issue_id"),"rule_id":issue.get("rule_id"),"original":original,"clamped":dict(loc)})
    return invalid

class Reviewer:
  def __init__(self, workers=4, ledger=None, registry=None, production_root=None):
    self.workers=workers; self.ffmpeg=locate_binary("ffmpeg"); self.ffprobe=locate_binary("ffprobe")
    resolved_root=production_root or os.environ.get("BACKLOT_PROJECT_ROOT") or os.environ.get("QINGSHAN_PRODUCTION_ROOT") or os.getcwd()
    self.root=Path(resolved_root); self.ledger=Path(ledger) if ledger else None; self.registry=Path(registry) if registry else None
    self._image_evidence_lock=threading.Lock();self._image_evidence_index=None

  def _build_image_evidence_index(self):
    """Index production image evidence by exact SHA, never by batch name."""
    with self._image_evidence_lock:
      if self._image_evidence_index is not None:return self._image_evidence_index
      index={};qa=self.root/"qa"
      for candidate in qa.rglob("*.json") if qa.is_dir() else []:
        try:
          if candidate.stat().st_size>20_000_000:continue
          data=json.loads(candidate.read_text(errors="replace"))
        except Exception:continue
        schema=str(data.get("schema", "")) if isinstance(data,dict) else ""
        if schema not in {"qingshan.image_visual_adjudication.v1","qingshan.storyboard_sheet_ai_visual_adjudication.v1","qingshan.still_image_ocr_audit.v1","qingshan.runtime_still_ocr.v1"}:continue
        shas=set()
        if isinstance(data,dict):
          if isinstance(data.get("candidate_sha256"),str):shas.add(data["candidate_sha256"])
          for row in data.get("evidence",[]):
            if isinstance(row,dict) and isinstance(row.get("sha256"),str):shas.add(row["sha256"])
          for src in data.get("source_images",[]):
            try:shas.add(sha256(Path(src).expanduser()))
            except Exception:pass
        for digest in shas:index.setdefault(digest,[]).append((candidate.resolve(),data))
      self._image_evidence_index=index
      return index

  def _auto_image_evidence(self,path:Path,schema:str):
    for target,data in self._build_image_evidence_index().get(sha256(path),[]):
      if data.get("schema")==schema:return target
    return None

  def _run_image_visual_adapter(self,path:Path,item:dict[str,Any]):
    """Run a configured multimodal adapter using a stable JSON stdin contract."""
    command=os.environ.get("QINGSHAN_IMAGE_ANALYSIS_COMMAND","").strip()
    if not command:return None,{"status":"CAPABILITY_FAIL","error_code":"IMAGE_VISUAL_RUNTIME_UNAVAILABLE","adapter_contract":"qingshan.image_visual_runtime.v1","candidate_sha256":sha256(path)}
    payload={"schema":"qingshan.image_visual_runtime.request.v1","path":str(path.resolve()),"candidate_sha256":sha256(path),"metadata":item.get("metadata") or {},"review_focus":(item.get("metadata") or {}).get("review_focus") or item.get("review_focus") or {}}
    try:
      p=subprocess.run(shlex.split(command),input=json.dumps(payload,ensure_ascii=False),capture_output=True,text=True,timeout=float(item.get("image_analysis_timeout_seconds",180)))
      data=json.loads(p.stdout);row=next((x for x in data.get("evidence",[]) if x.get("sha256")==payload["candidate_sha256"]),None)
      if p.returncode not in {0,1} or not row:return None,{"status":"CAPABILITY_FAIL","error_code":"IMAGE_VISUAL_RUNTIME_INVALID_RESULT","returncode":p.returncode,"stderr_tail":p.stderr[-1000:],"candidate_sha256":payload["candidate_sha256"]}
      return data,None
    except Exception as exc:return None,{"status":"CAPABILITY_FAIL","error_code":"IMAGE_VISUAL_RUNTIME_ERROR","error":f"{type(exc).__name__}: {exc}","candidate_sha256":payload["candidate_sha256"]}

  def _run_still_ocr(self,path:Path,item:dict[str,Any]):
    script=Path(__file__).with_name("image_runtime_adapter.py");interpreters=[]
    configured=os.environ.get("QINGSHAN_OCR_PYTHON")
    if configured:interpreters.append(configured)
    interpreters.extend(["/usr/bin/python3",os.environ.get("PYTHON","python3")])
    errors=[]
    for python in dict.fromkeys(interpreters):
      if not python:continue
      with tempfile.TemporaryDirectory() as td:
        dest=Path(td)/"ocr.json"
        try:p=subprocess.run([python,str(script),"--image",str(path),"--out",str(dest),"--confidence",str(float(item.get("ocr_confidence",.75)))],capture_output=True,text=True,timeout=float(item.get("ocr_timeout_seconds",120)))
        except Exception as exc:errors.append(f"{python}: {type(exc).__name__}: {exc}");continue
        if dest.is_file():
          try:
            data=json.loads(dest.read_text())
            if data.get("candidate_sha256")==sha256(path) and data.get("status") in {"PASS","FAIL"}:return data,None
            errors.append(f"{python}: {data.get('error','invalid result')}")
          except Exception as exc:errors.append(f"{python}: {type(exc).__name__}: {exc}")
    return None,{"status":"CAPABILITY_FAIL","error_code":"OCR_RUNTIME_UNAVAILABLE","errors":errors,"candidate_sha256":sha256(path)}

  def validate(self, spec: dict[str,Any]) -> dict[str,Any]:
    errors=[]; items=spec.get("items") if isinstance(spec,dict) else None
    if not isinstance(items,list) or not items: errors.append("items must be a non-empty array")
    else:
      for i,x in enumerate(items):
        if not isinstance(x,dict) or not x.get("path"): errors.append(f"items[{i}].path is required")
        elif not Path(x["path"]).expanduser().is_file(): errors.append(f"items[{i}].path not found")
        if isinstance(x,dict) and x.get("importance","standard") not in IMPORTANCE_THRESHOLDS: errors.append(f"items[{i}].importance is invalid")
        if isinstance(x,dict) and "pass_score" in x and (not isinstance(x["pass_score"],(int,float)) or not 1 <= x["pass_score"] <= 5): errors.append(f"items[{i}].pass_score must be between 1 and 5")
        if isinstance(x,dict):
          required=x.get("required_capabilities",[])
          if not isinstance(required,list) or any(v not in CAPABILITIES and v not in CAPABILITY_ALIASES for v in required): errors.append(f"items[{i}].required_capabilities contains invalid capability")
        if isinstance(x,dict) and x.get("kind") not in (None,"video","audio","image"): errors.append(f"items[{i}].kind is invalid")
        if isinstance(x,dict) and x.get("scope","asset") not in ("shot","asset","sequence","final","full_cut"): errors.append(f"items[{i}].scope is invalid")
        if isinstance(x,dict) and "duration_tolerance_seconds" in x and (not isinstance(x["duration_tolerance_seconds"],(int,float)) or not 0<=x["duration_tolerance_seconds"]<=1):errors.append(f"items[{i}].duration_tolerance_seconds must be between 0 and 1")
        if isinstance(x,dict) and x.get("gate_policy") is not None:
          try:self._gate_policy(x)
          except ValueError as exc:errors.append(f"items[{i}].gate_policy {exc}")
        if isinstance(x,dict):
          ev=x.get("evidence_inputs",{})
          if not isinstance(ev,dict): errors.append(f"items[{i}].evidence_inputs must be an object")
          else:
            for name,ref in ev.items():
              refs=ref if isinstance(ref,list) else [ref]
              for j,v in enumerate(refs):
                if not isinstance(v,str) or not Path(v).expanduser().is_file(): errors.append(f"items[{i}].evidence_inputs.{name}[{j}] not found")
            project=ev.get("agentcut_project")
            if isinstance(project,str) and Path(project).is_file():
              try:
                data=json.loads(Path(project).read_text()); timeline=data.get("timeline",{})
                if data.get("version")!="1.0" or not isinstance(timeline.get("videoTracks",[]),list): errors.append(f"items[{i}].evidence_inputs.agentcut_project is invalid")
              except Exception as exc: errors.append(f"items[{i}].evidence_inputs.agentcut_project unreadable: {type(exc).__name__}")
    return {"valid":not errors,"errors":errors,"schema":"qingshan.review.request.v1"}

  def review(self, item: dict[str,Any]) -> dict[str,Any]:
    path=Path(item["path"]).expanduser().resolve(); kind=item.get("kind") or media_kind(path); scope=item.get("scope","asset")
    item=dict(item);item["kind"]=kind;item["scope"]=scope; item["_gate_policy_audit"]=self._gate_policy(item);requested_capabilities=list(item.get("required_capabilities") or []); normalized=[]
    for name in requested_capabilities:
      canonical=CAPABILITY_ALIASES.get(name,name)
      if canonical not in normalized: normalized.append(canonical)
    item["required_capabilities"]=normalized
    original_evidence=dict(item.get("evidence_inputs") or {}); provenance_issues,provenance_caps,provenance,clean_evidence=self._check_evidence_provenance(path,item)
    item["evidence_inputs"]=clean_evidence
    if "regression_ci" in provenance_caps: item["run_regression_ci"]=False
    mapped=self._agentcut_map(path,item)
    if mapped: item["_agentcut_context"]=mapped
    if mapped and not item.get("clip_id"): item["clip_id"]=mapped.get("clip_id")
    info=probe(path,self.ffprobe) if self.ffprobe or kind!="image" else probe_image(path);duration=float((info.get("format") or {}).get("duration",0) or 0);item["_media_duration"]=duration;issues=list(provenance_issues); capabilities={**self._explicit_evidence_capabilities(clean_evidence),**provenance_caps}
    recipe_issues,recipe_caps,recipe_audit=audit_shot_recipe(path,item,duration,stable_issue);issues+=recipe_issues
    for name,value in recipe_caps.items():
      if capabilities.get(name,{}).get("status")!="ERROR":capabilities[name]=value
    item["_intentional_effect_authorizations"]=recipe_audit.get("authorizations",[])
    capabilities["media_probe"]={"status":"ERROR" if info.get("error") or not info.get("available",True) else "PASS","evidence":str(path),"error":info.get("error")}
    if capabilities.get("sentence_audit",{}).get("derived_status")=="FAIL_ZERO_SENTENCE_FALSE_PASS":
      detail={"source_adapter":"sentence_audit_integrity","sentence_count":0,"raw_status":capabilities["sentence_audit"].get("raw_status"),"evidence":capabilities["sentence_audit"].get("evidence")}
      issues.append(stable_issue("audio.dialogue_zero_sentence_false_pass",path,{},"critical",1,"修复对白 clip 提取并按时间线重新执行句审；禁止 0 句 PASS",True,evidence=[detail],details=detail))
    if mapped:
      capabilities["agentcut_project"]={"status":"PASS","evidence":mapped.get("project"),"clip_id":mapped.get("clip_id"),"timeline_range":mapped.get("timeline_range")}
      if mapped.get("coverage"):
        coverage=mapped["coverage"]
        capabilities["coverage"]={"status":"PASS" if coverage.get("complete") else "FAIL","evidence":mapped.get("project"),"source_adapter":"agentcut_project","details":coverage}
    if kind in {"video","audio"}:
      streams=info.get("streams",[]); fmt=info.get("format",{}); dur=float(fmt.get("duration",0) or 0)
      if kind=="video":
        vs=next((s for s in streams if s.get("codec_type")=="video"),None)
        if not vs: issues.append(stable_issue("video.missing_stream",path,{"start_seconds":0},"critical",1,"重新导出含视频轨的文件",True))
        if not any(s.get("codec_type")=="audio" for s in streams): issues.append(stable_issue("audio.missing",path,{"start_seconds":0,"end_seconds":dur},"critical",1,"补齐对白/环境声并重新混音",True))
        duration_issues,duration_cap=self._story_duration(path,item,dur);issues+=duration_issues
        if duration_cap:capabilities["story_duration"]=duration_cap
        episode_issues,episode_cap=self._episode_runtime(path,item,dur);issues+=episode_issues
        if episode_cap:capabilities["episode_runtime"]=episode_cap
        pacing_issues,pacing_cap=self._visual_pacing(path,item,mapped);issues+=pacing_issues
        if pacing_cap:capabilities["visual_pacing"]=pacing_cap
        if dur and (dur<.35 or dur>(600 if duration_cap else item.get("max_duration_seconds",600))):
          issues.append(stable_issue("video.duration",path,{"start_seconds":0,"end_seconds":dur},"error",.99,"核对镜头/成片时长",True,details={"duration_seconds":dur}))
        video_issues,video_cap,action_cap=self._video_external(path,item,dur); issues += video_issues
        capabilities["video_analysis"]=video_cap
        if action_cap:capabilities["action_physics"]=action_cap
        if scope=="final":
          black_issues,black_cap=self._black_frame_scan(path,item,dur);issues+=black_issues;capabilities["black_frame_analysis"]=black_cap
          brightness_issues,brightness_cap=self._brightness_evidence(path,clean_evidence.get("scene_brightness"));issues+=brightness_issues
          if capabilities.get("scene_brightness",{}).get("status")!="ERROR":capabilities["scene_brightness"]=brightness_cap
        ocr_issues,ocr_cap=self._ocr_evidence(path,item,dur,mapped);issues+=ocr_issues
        if ocr_cap and capabilities.get("ocr",{}).get("status")!="ERROR":capabilities["ocr"]=ocr_cap
      audio_item=dict(item)
      if scope=="final" and (item.get("evidence_inputs") or {}).get("regression_ci_json"): audio_item["authoritative_continuity_evidence"]=True
      audio_issues=self._audio(path,audio_item,dur,mapped)
      ambience_issues,ambience_cap=self._ambience(path,item,mapped,dur);audio_issues+=ambience_issues
      if ambience_cap:capabilities["ambience_analysis"]=ambience_cap
      issues += audio_issues
      capabilities["audio_analysis"]={"status":"FAIL" if any(x["blocking"] for x in audio_issues) else "PASS","rule_version":AUDIO_PROFILE["version"],"thresholds":self._audio_config(item)}
      if kind=="video" and scope=="final":
        reg_issues,reg_caps=self._regression_ci(path,item); issues += reg_issues
        for name,value in reg_caps.items():
          existing=capabilities.get(name,{})
          if existing.get("status")=="ERROR": continue
          if existing.get("source_adapter")=="explicit_evidence": continue
          if existing.get("status")=="PASS" and value.get("status")=="NOT_RUN": continue
          capabilities[name]=value
    elif kind=="image":
      image_issues,image_caps=self._image(path,item,info); issues += image_issues
      for name,value in image_caps.items():
        if capabilities.get(name,{}).get("status")!="ERROR": capabilities[name]=value
    else: issues.append(stable_issue("media.unsupported",path,{},"critical",1,"转换为受支持媒体格式",True))
    issues += self._regressions(path,item)
    invalid_time_ranges=sanitize_issue_time_ranges(issues,duration)
    if invalid_time_ranges:
      affected="audio_analysis" if any(str(x["rule_id"]).startswith("audio.") for x in invalid_time_ranges) else "video_analysis"
      capabilities[affected]={"status":"ERROR","error_code":"INVALID_ISSUE_TIME_RANGE","error":"adapter emitted issue outside media duration","duration_seconds":duration,"invalid_issues":invalid_time_ranges}
    requirements=self._capability_requirements(kind,scope,item,capabilities)
    self._adjudicate_capability_statuses(capabilities,issues,requirements)
    for name,requirement in requirements.items():
      if requirement=="NOT_APPLICABLE": capabilities[name]={"status":"NOT_APPLICABLE","requirement":requirement,"reason":"not_applicable_for_media_kind_and_scope"}
      elif name not in capabilities: capabilities[name]={"status":"NOT_RUN","requirement":requirement,"reason":"evidence_not_provided_or_adapter_not_run"}
      else: capabilities[name]["requirement"]=requirement
    for name,cap in capabilities.items():
      if cap.get("requirement")=="REQUIRED" and cap["status"] in {"NOT_RUN","ERROR","CAPABILITY_FAIL"} and cap.get("error_code") not in {"STALE_EVIDENCE","INVALID_ISSUE_TIME_RANGE"}:
        issues.append(stable_issue(f"capability.{name}.{cap['status'].lower()}",path,{},"warning",1,"补齐证据或修复适配器后重审",False,evidence=[cap],details={"capability":name,"status":cap["status"]}))
    raw_issue_count=len(issues); issues=deduplicate_issues(issues); deduped_issue_count=len(issues)
    long_shot_counts={"raw_long_shot_count":0,"motivated_long_shot_count":0,"unmotivated_long_shot_count":0}
    for issue in issues:
      if issue.get("rule_id") in {"video.motivated_long_shots","video.too_many_long_shots"}:
       for key in long_shot_counts: long_shot_counts[key]=max(long_shot_counts[key],int(issue.get("details",{}).get(key,0) or 0))
    scoring=score_issues(issues,item.get("importance","standard"),item.get("pass_score"))
    evidence_fingerprints={}
    for key,value in original_evidence.items():
      refs=value if isinstance(value,list) else [value]; evidence_fingerprints[key]=[]
      for ref in refs:
       target=Path(ref).expanduser(); evidence_fingerprints[key].append({"path":str(target.resolve()),"sha256":sha256(target) if target.is_file() else None})
    config_summary={"rule_version":RULE_VERSION,"audio":self._audio_config(item),"ambience":self._ambience_config(item),"ocr":OCR_PROFILE,"action_motion_physics":{**ACTION_MOTION_PROFILE,"action_required":self._action_required(item),"action_intensity":item.get("action_intensity",(item.get("metadata") or {}).get("action_intensity")),"applied_near_duplicate_ratio_max":item.get("action_near_duplicate_ratio_max",ACTION_MOTION_PROFILE["near_duplicate_ratio_max"])},"shot_recipe_conformance":recipe_audit,"story_duration":capabilities.get("story_duration"),"gate_policy":item["_gate_policy_audit"],"importance":item.get("importance","standard"),"pass_score":item.get("pass_score"),"required_capabilities_requested":requested_capabilities,"required_capabilities_normalized":normalized,"capability_aliases":{name:CAPABILITY_ALIASES[name] for name in requested_capabilities if name in CAPABILITY_ALIASES},"evidence_inputs":evidence_fingerprints}
    config_summary["episode_runtime_policy"]=capabilities.get("episode_runtime") or EPISODE_RUNTIME_PROFILE
    config_summary["visual_pacing_policy"]=VISUAL_PACING_PROFILE
    review_seed=json.dumps([str(path),sha256(path),config_summary],sort_keys=True,ensure_ascii=False)
    required_capability_failures=[name for name,cap in capabilities.items() if cap.get("requirement")=="REQUIRED" and cap.get("status") in {"NOT_RUN","ERROR","CAPABILITY_FAIL"}]
    result_status="FAIL" if not scoring["passed"] and (scoring["hard_gate_passed"] is False or not required_capability_failures) else "CAPABILITY_FAIL" if required_capability_failures else ("WARN" if issues else "PASS")
    report={"schema":"qingshan.review.report.v2","review_id":"REV-"+hashlib.sha256(review_seed.encode()).hexdigest()[:16].upper(),
      "created_at":now(),"scope":scope,"media_kind":kind,"media_path":str(path),"media_sha256":sha256(path),
      "status":result_status,"content_status":"CONTENT_FAIL" if result_status=="FAIL" else "CAPABILITY_FAIL" if result_status=="CAPABILITY_FAIL" else "PASS","required_capability_failures":required_capability_failures,"scoring":scoring,"deduction_cap":scoring["deduction_cap"],"capabilities":capabilities,"story_duration":capabilities.get("story_duration"),"episode_runtime":capabilities.get("episode_runtime"),"visual_pacing":capabilities.get("visual_pacing"),"evidence_provenance":provenance,"config_summary":config_summary,"issues":issues,
      "validity":"INVALID" if invalid_time_ranges else "VALID","invalid_time_ranges":invalid_time_ranges,
      "summary":{"issue_count":deduped_issue_count,"raw_issue_count":raw_issue_count,"deduped_issue_count":deduped_issue_count,"blocking_count":sum(x["blocking"] for x in issues),"invalid_time_range_count":len(invalid_time_ranges),**long_shot_counts},
      "agentcut":{"clip_id":item.get("clip_id"),"metadata":{**(mapped.get("metadata",{}) if mapped else {}),**item.get("metadata",{})},"timeline_range":mapped.get("timeline_range") if mapped else None,"project":mapped.get("project") if mapped else None,"clips":mapped.get("clips",[]) if mapped else [],"pacing":mapped.get("pacing") if mapped else None,"shot_recipe_conformance":recipe_audit},
      "limitations":["语义连续性、声纹、对白顺序需提供 reference/manifest 或外部模型结果","OCR 在无可用生产线适配器时只记录能力缺口"]}
    if self.ledger: self.append_ledger({"event":"review_completed","report":report})
    return report

  def _check_evidence_provenance(self,path,item):
    evidence=dict(item.get("evidence_inputs") or {}); clean=dict(evidence); issues=[]; caps={}; rows=[]
    media_keys={"video","video_path","media_path","source_video","source_final_mp4","final_video","input_video","input_path","candidate"}
    project_keys={"project","project_path","agentcut_project","agentcut_project_path"}
    capability={"regression_ci_json":"regression_ci","asr":"asr","sentence_audit":"sentence_audit","ocr":"ocr","ocr_raw":"ocr","ocr_adjudication":"ocr","voiceprint":"voiceprint","action_audit":"action","action_physics":"action_physics","scene_brightness":"scene_brightness","cadence_audit":"video_analysis"}
    expected_project=evidence.get("agentcut_project")
    def walk(value):
      found=[]
      if isinstance(value,dict):
       for k,v in value.items():
        if k in media_keys|project_keys and isinstance(v,str): found.append((k,v))
        elif isinstance(v,(dict,list)): found.extend(walk(v))
      elif isinstance(value,list):
       for v in value: found.extend(walk(v))
      return found
    def matches(raw,expected,base):
      if not expected:return True
      candidate=Path(raw).expanduser(); target=Path(expected).expanduser().resolve()
      options=[candidate.resolve()] if candidate.is_absolute() else [(base/candidate).resolve(),(self.root/candidate).resolve()]
      return target in options
    project_ref=evidence.get("agentcut_project")
    if isinstance(project_ref,str):
      target=Path(project_ref).expanduser().resolve(); mismatches=[];lineage=None
      try:
       project_data=json.loads(target.read_text()); output_path=(project_data.get("output") or {}).get("path")
       if output_path and matches(output_path,str(path),target.parent): lineage={"method":"exact_output_path","actual":str(Path(output_path).expanduser().resolve()),"expected":str(path.resolve())}
       elif output_path:
        actual_identity=re.search(r"(E\d+R?_AGENTCUT_TRIAL_V\d+)",Path(output_path).name.upper()); expected_identity=re.search(r"(E\d+R?_AGENTCUT_TRIAL_V\d+)",path.name.upper())
        timeline_end=max([float(c.get("start",0))+float(c.get("duration",0)) for t in project_data.get("timeline",{}).get("videoTracks",[]) for c in t.get("clips",[])] or [0]); media_info=probe(path,self.ffprobe);media_duration=float((media_info.get("format") or {}).get("duration",0) or 0); duration_delta=abs(timeline_end-media_duration)
        if actual_identity and expected_identity and actual_identity.group(1)==expected_identity.group(1) and media_duration and duration_delta<=.25:
          lineage={"method":"version_identity_and_timeline_duration","identity":actual_identity.group(1),"project_output_path":str(Path(output_path).expanduser().resolve()),"review_media_path":str(path.resolve()),"timeline_duration_seconds":timeline_end,"media_duration_seconds":media_duration,"duration_delta_seconds":duration_delta}
        else:mismatches.append({"field":"output.path","actual":output_path,"expected":str(path.resolve()),"actual_identity":actual_identity.group(1) if actual_identity else None,"expected_identity":expected_identity.group(1) if expected_identity else None,"timeline_duration_seconds":timeline_end,"media_duration_seconds":media_duration,"duration_delta_seconds":duration_delta})
      except Exception: output_path=None
      rows.append({"evidence_key":"agentcut_project","path":str(target),"status":"MISMATCH" if mismatches else "MATCH","lineage":lineage,"mismatches":mismatches})
      if mismatches:
       clean.pop("agentcut_project",None); detail={"error_code":"STALE_EVIDENCE","evidence_key":"agentcut_project","evidence_path":str(target),"mismatches":mismatches}
       caps["agentcut_project"]={"status":"ERROR","requirement":"REQUIRED","error_code":"STALE_EVIDENCE","evidence":str(target),"provenance_mismatches":mismatches}
       issues.append(stable_issue("evidence.provenance_mismatch.agentcut_project",path,{},"critical",1,"传入 output.path 与当前媒体匹配的 AgentCut project",True,evidence=[detail],details=detail))
    for key,cap in capability.items():
      ref=evidence.get(key)
      if not isinstance(ref,str): continue
      target=Path(ref).expanduser().resolve(); mismatches=[]
      try:data=json.loads(target.read_text())
      except Exception: continue
      references=walk(data);expected_decoded_md5=str((item.get("metadata") or {}).get("decoded_video_md5") or "").lower();found_decoded_md5=[]
      def collect_identity(value):
       if isinstance(value,dict):
        for k,v in value.items():
         if k in {"decoded_video_md5","decoded_stream_md5","decoded_visual_md5"} and isinstance(v,str):found_decoded_md5.append(v.lower())
         elif isinstance(v,(dict,list)):collect_identity(v)
       elif isinstance(value,list):
        for v in value:collect_identity(v)
      collect_identity(data)
      has_current_media_reference=any(field in media_keys and matches(raw,str(path),target.parent) for field,raw in references)
      derived_identity_match=bool(expected_decoded_md5 and expected_decoded_md5 in found_decoded_md5 and has_current_media_reference)
      for field,raw in references:
       expected=expected_project if field in project_keys else str(path)
       if expected and not matches(raw,expected,target.parent):
        if field in media_keys and derived_identity_match:continue
        mismatches.append({"field":field,"actual":raw,"expected":str(Path(expected).expanduser().resolve())})
      status="MISMATCH" if mismatches else "MATCH_DERIVED_DECODED_VIDEO_IDENTITY" if derived_identity_match else "MATCH_OR_UNDECLARED"
      lineage={"method":"current_media_reference_and_decoded_video_md5","expected_decoded_video_md5":expected_decoded_md5,"evidence_decoded_video_md5":expected_decoded_md5,"stale_paths_treated_as_derivation_sources":sorted({raw for field,raw in references if field in media_keys and not matches(raw,str(path),target.parent)})} if derived_identity_match else None
      rows.append({"evidence_key":key,"path":str(target),"status":status,"lineage":lineage,"mismatches":mismatches})
      if mismatches:
       clean.pop(key,None); detail={"error_code":"STALE_EVIDENCE","evidence_key":key,"evidence_path":str(target),"mismatches":mismatches}
       caps[cap]={"status":"ERROR","requirement":"REQUIRED","error_code":"STALE_EVIDENCE","evidence":str(target),"provenance_mismatches":mismatches}
       issues.append(stable_issue(f"evidence.provenance_mismatch.{cap}",path,{},"critical",1,"重新生成或传入与当前媒体及 AgentCut project 匹配的证据",True,evidence=[detail],details=detail))
    return issues,caps,{"status":"MISMATCH" if issues else "PASS","checks":rows},clean

  def _explicit_evidence_capabilities(self,evidence):
    caps={}
    for key,cap in {"asr":"asr","sentence_audit":"sentence_audit","voiceprint":"voiceprint","action_audit":"action"}.items():
      ref=evidence.get(key)
      if not isinstance(ref,str):continue
      try:
       data=json.loads(Path(ref).expanduser().read_text());raw=str(data.get("status","")).upper();derived=None
       if not raw and cap=="scene_brightness" and data.get("timeline_order_verified") is True and isinstance(data.get("shots"),list) and data.get("shots"): raw="PASS_DERIVED";derived=raw
       if raw.startswith(("PASS","APPROVED","READY")):status="PASS"
       elif raw.startswith(("FAIL","REJECT","ERROR")):status="FAIL"
       else:status="ERROR"
       if cap=="sentence_audit":
        rows=data.get("sentences",data.get("rows"));has_count="sentence_count" in data or isinstance(rows,list);count=data.get("sentence_count",len(rows) if isinstance(rows,list) else None)
        if status=="PASS" and has_count and int(count or 0)==0:status="FAIL";derived="FAIL_ZERO_SENTENCE_FALSE_PASS"
       caps[cap]={"status":status,"evidence":str(Path(ref).expanduser().resolve()),"raw_status":data.get("status"),"derived_status":derived,"source_adapter":"explicit_evidence","error":"evidence status missing or unknown" if status=="ERROR" else None,"sentence_count":int(count or 0) if cap=="sentence_audit" and count is not None else None}
      except Exception as exc:caps[cap]={"status":"ERROR","evidence":str(ref),"error":f"{type(exc).__name__}: {exc}"}
    return caps

  def _adjudicate_capability_statuses(self,caps,issues,requirements):
    audio_issues=[x for x in issues if str(x.get("rule_id","")).startswith("audio.")]
    unresolved_audio=[x for x in audio_issues if x.get("actionable",True)]
    audio=caps.get("audio_analysis")
    if audio and audio.get("status")!="ERROR":
      raw=audio.get("raw_status",audio.get("status"));raw_evidence=audio.get("evidence")
      status="FAIL" if any(x.get("blocking") for x in unresolved_audio) else "WARN" if unresolved_audio else "PASS"
      audio.update({"status":status,"raw_status":raw,"raw_evidence":raw_evidence,"adjudication":"FAIL_UNRESOLVED_AUDIO_HARD_GATE" if status=="FAIL" else "WARN_ACTIONABLE_AUDIO_FINDING" if status=="WARN" else "PASS_LOCAL_CONTINUITY","adjudicated_issue_ids":[x["issue_id"] for x in audio_issues]})
    regression=caps.get("regression_ci")
    if regression and regression.get("status")!="ERROR":
      raw=regression.get("raw_status",regression.get("status"));raw_evidence=regression.get("evidence") or regression.get("tool")
      production=[x for x in issues if x.get("details",{}).get("source_adapter")=="production_regression"]
      unresolved=[x for x in production if x.get("actionable",True)];blockers=[x for x in unresolved if x.get("blocking")]
      required_gaps=[name for name,requirement in requirements.items() if name!="regression_ci" and requirement=="REQUIRED" and caps.get(name,{}).get("status") not in {"PASS","WARN"}]
      status="FAIL" if blockers else "WARN" if unresolved or required_gaps else "PASS"
      regression.update({"status":status,"raw_status":raw,"raw_evidence":raw_evidence,"adjudication":"FAIL_UNRESOLVED_HARD_GATE" if blockers else "WARN_UNRESOLVED_FINDING_OR_REQUIRED_GAP" if status=="WARN" else "PASS_ALL_RAW_FAILURES_RECONCILED","unresolved_issue_ids":[x["issue_id"] for x in unresolved],"required_capability_gaps":required_gaps})

  def _gate_policy(self,item):
    policy=item.get("gate_policy")
    if policy is None:return {"applied":False,"source":"production_defaults","overrides":{}}
    if not isinstance(policy,dict):raise ValueError("must be an object")
    if not isinstance(policy.get("version"),str) or not policy["version"].strip():raise ValueError("version is required")
    if not isinstance(policy.get("reason"),str) or not policy["reason"].strip():raise ValueError("reason is required")
    if not policy.get("episode") and not policy.get("project"):raise ValueError("episode or project scope is required")
    episode=(item.get("metadata") or {}).get("episode")
    if policy.get("episode") and policy["episode"]!=episode:raise ValueError("episode does not match item.metadata.episode")
    project=(item.get("evidence_inputs") or {}).get("agentcut_project")
    if policy.get("project") and (not project or Path(policy["project"]).expanduser().resolve()!=Path(project).expanduser().resolve()):raise ValueError("project does not match evidence_inputs.agentcut_project")
    overrides=policy.get("overrides")
    allowed={"min_runtime","max_runtime","under1_min","under1_max"}
    if not isinstance(overrides,dict) or not overrides:raise ValueError("non-empty overrides object is required")
    if any(k not in allowed or not isinstance(v,(int,float)) for k,v in overrides.items()):raise ValueError("overrides contains unsupported or non-numeric threshold")
    values={k:float(v) for k,v in overrides.items()}
    if values.get("min_runtime",0)<0 or values.get("max_runtime",float("inf"))<=0:raise ValueError("runtime thresholds must be positive")
    if any(not 0<=values[k]<=1 for k in ("under1_min","under1_max") if k in values):raise ValueError("under1 thresholds must be between 0 and 1")
    if values.get("under1_min",0)>values.get("under1_max",1):raise ValueError("under1_min must not exceed under1_max")
    return {"applied":True,"version":policy["version"],"reason":policy["reason"],"episode":policy.get("episode"),"project":str(Path(policy["project"]).expanduser().resolve()) if policy.get("project") else None,"overrides":values}

  def _capability_requirements(self,kind,scope,item,caps):
    req={name:"NOT_APPLICABLE" for name in CAPABILITIES}; req["media_probe"]="REQUIRED"
    if kind=="image":
      req.update({"ocr":"REQUIRED","image_analysis":"OPTIONAL","image_clarity":"OPTIONAL","image_brightness":"OPTIONAL","composition":"OPTIONAL","visual_continuity":"OPTIONAL"})
    elif kind=="audio":
      req.update({"audio_analysis":"REQUIRED","asr":"OPTIONAL","sentence_audit":"OPTIONAL","voiceprint":"OPTIONAL"})
    elif kind=="video":
      req.update({"video_analysis":"REQUIRED","audio_analysis":"REQUIRED","ocr":"OPTIONAL","visual_continuity":"OPTIONAL","action":"OPTIONAL","scene_brightness":"OPTIONAL","asr":"OPTIONAL","sentence_audit":"OPTIONAL","coverage":"OPTIONAL","agentcut_project":"OPTIONAL"})
      if self._action_required(item):req["action_physics"]="REQUIRED"
      if self._is_video_generation_review(item):req["story_duration"]="REQUIRED"
      if scope=="final": req.update({"regression_ci":"REQUIRED","black_frame_analysis":"REQUIRED","scene_brightness":"REQUIRED"})
    for name,cap in caps.items():
      if cap.get("requirement") in {"REQUIRED","OPTIONAL"}: req[name]=cap["requirement"]
      elif req.get(name)=="NOT_APPLICABLE": req[name]="OPTIONAL"
    if "ambience_analysis" in caps:req["ambience_analysis"]="REQUIRED"
    for name in item.get("required_capabilities",[]): req[name]="REQUIRED"
    return req

  def _is_video_generation_review(self,item):
    task=item.get("task");profile=str(item.get("review_profile","")).lower();model=str((task or {}).get("model") or (item.get("metadata") or {}).get("model") or "").lower()
    return isinstance(task,dict) or profile in {"video_generation","generation","seedance_source"} or "seedance" in model

  def _action_required(self,item):
    metadata=item.get("metadata") or {}
    if item.get("action_required") is True or metadata.get("action_required") is True:return True
    value=item.get("action_intensity",metadata.get("action_intensity"))
    if isinstance(value,(int,float)):return float(value)>0
    return str(value or "").strip().lower() in {"action","fight","combat","supernatural","high","medium","intense","required"}

  def _story_duration(self,path,item,actual_duration):
    if not self._is_video_generation_review(item):return [],None
    task=item.get("task") if isinstance(item.get("task"),dict) else {};plan=task.get("duration_plan") if isinstance(task.get("duration_plan"),dict) else None;tolerance=float(item.get("duration_tolerance_seconds",STORY_DURATION_PROFILE["encoding_tolerance_seconds"]));planned=plan.get("duration_seconds") if plan else None;policy=str((plan or {}).get("policy") or STORY_DURATION_PROFILE["version"]);minimum=STORY_DURATION_PROFILE["minimum_seconds"];maximum=STORY_DURATION_PROFILE["maximum_seconds"]
    base={"planned_duration_seconds":float(planned) if isinstance(planned,(int,float)) else None,"actual_duration_seconds":round(float(actual_duration),6),"delta_seconds":round(float(actual_duration)-float(planned),6) if isinstance(planned,(int,float)) else None,"encoding_tolerance_seconds":tolerance,"allowed_range_seconds":[minimum,maximum],"policy_version":policy,"rollback_allowed":True,"source_id":task.get("source_id"),"dialogue_id":task.get("dialogue_id")}
    issues=[];rule=None;recommendation=None
    if not plan or not isinstance(planned,(int,float)):
      rule="video.duration_plan_missing";recommendation="补齐 task.duration_plan.duration_seconds 后再生成或审片"
    elif not minimum<=float(planned)<=maximum:
      rule="video.duration_plan_out_of_range";recommendation="按剧情、对白和动作重新规划 4–15 秒的单镜时长"
    elif abs(float(actual_duration)-float(planned))>tolerance:
      rule="video.duration_plan_mismatch";recommendation="按计划时长重新生成或核对编码封装，禁止用统一 6 秒阈值裁切"
    passed=rule is None;base["passed"]=passed;base["status"]="PASS" if passed else "FAIL"
    if rule:issues.append(stable_issue(rule,path,{"start_seconds":0,"end_seconds":float(actual_duration)},"critical",1,recommendation,True,evidence=[{"type":"story_duration_plan","task":task,"actual_duration_seconds":actual_duration}],details={**base,"source_adapter":"story_duration_qa"}))
    return issues,{"status":"PASS" if passed else "FAIL","requirement":"REQUIRED","source_adapter":"story_duration_qa",**base}

  def _episode_runtime(self,path,item,actual_duration):
    if item.get("kind")!="video" or item.get("scope")!="final":return [],None
    metadata=item.get("metadata") or {}; policy=item.get("runtime_policy") or metadata.get("runtime_policy")
    new_contract=bool(item.get("require_episode_runtime") or metadata.get("require_episode_runtime") or metadata.get("production_contract_version") in {2,"2","v2"})
    if not isinstance(policy,dict):
      if not new_contract:return [],{"status":"NOT_RUN","requirement":"OPTIONAL","reason":"legacy_project_without_episode_runtime_contract","policy_version":EPISODE_RUNTIME_PROFILE["version"]}
      base={"planned_duration_seconds":None,"actual_duration_seconds":round(float(actual_duration),6),"delta_seconds":None,"policy_version":EPISODE_RUNTIME_PROFILE["version"],"passed":False,"rollback_allowed":True}
      issue=stable_issue("video.episode_runtime_plan_missing",path,{"start_seconds":0,"end_seconds":float(actual_duration)},"critical",1,"在剧本 manifest 写入机器可读 target/soft/hard tolerance 后再进入分镜与成片审查",True,evidence=[{"type":"episode_runtime_policy","status":"MISSING"}],details={**base,"source_adapter":"episode_runtime_qa"})
      return [issue],{"status":"FAIL","requirement":"REQUIRED","source_adapter":"episode_runtime_qa",**base}
    target=policy.get("target_seconds",policy.get("target_duration_seconds"));soft=policy.get("soft_tolerance_seconds",EPISODE_RUNTIME_PROFILE["soft_tolerance_seconds"]);hard=policy.get("hard_tolerance_seconds",EPISODE_RUNTIME_PROFILE["hard_tolerance_seconds"]);version=str(policy.get("version") or EPISODE_RUNTIME_PROFILE["version"])
    if not isinstance(target,(int,float)) or float(target)<=0 or not isinstance(soft,(int,float)) or not isinstance(hard,(int,float)) or float(soft)<0 or float(hard)<float(soft):
      base={"planned_duration_seconds":float(target) if isinstance(target,(int,float)) else None,"actual_duration_seconds":round(float(actual_duration),6),"delta_seconds":None,"policy_version":version,"passed":False,"rollback_allowed":True}
      issue=stable_issue("video.episode_runtime_policy_invalid",path,{"start_seconds":0,"end_seconds":float(actual_duration)},"critical",1,"修复时长合同：target>0 且 0<=soft<=hard",True,evidence=[policy],details={**base,"source_adapter":"episode_runtime_qa"})
      return [issue],{"status":"FAIL","requirement":"REQUIRED","source_adapter":"episode_runtime_qa",**base}
    target=float(target);soft=float(soft);hard=float(hard);delta=float(actual_duration)-target;absolute=abs(delta);status="PASS" if absolute<=soft else "WARN" if absolute<=hard else "FAIL"
    base={"planned_duration_seconds":target,"actual_duration_seconds":round(float(actual_duration),6),"delta_seconds":round(delta,6),"soft_tolerance_seconds":soft,"hard_tolerance_seconds":hard,"policy_version":version,"passed":status!="FAIL","within_soft_tolerance":absolute<=soft,"rollback_allowed":True}
    issues=[]
    if status=="WARN":issues.append(stable_issue("video.episode_runtime_soft_deviation",path,{"start_seconds":0,"end_seconds":float(actual_duration)},"warning",1,"压缩非核心对白、重复反应或停顿，并记录超出软容差的制作理由",False,evidence=[policy],details={**base,"source_adapter":"episode_runtime_qa"}))
    if status=="FAIL":issues.append(stable_issue("video.episode_runtime_hard_deviation",path,{"start_seconds":0,"end_seconds":float(actual_duration)},"critical",1,"退回剧本/镜头计划压缩，禁止用技术 PASS 覆盖发行时长硬门",True,evidence=[policy],details={**base,"source_adapter":"episode_runtime_qa"}))
    return issues,{"status":status,"requirement":"REQUIRED","source_adapter":"episode_runtime_qa",**base}

  def _visual_pacing(self,path,item,mapped):
    if item.get("kind")!="video" or item.get("scope")!="final":return [],None
    if not mapped or not mapped.get("clips"):return [],{"status":"NOT_RUN","requirement":"OPTIONAL","reason":"materialized_agentcut_timeline_unavailable","policy_version":VISUAL_PACING_PROFILE["version"]}
    clips=sorted((x for x in mapped["clips"] if x.get("kind")=="video"),key=lambda x:x["timeline_range"]["start_seconds"]);issues=[]
    def signature(row):
      m=row.get("metadata") or {}
      explicit=m.get("visual_signature") or m.get("composition_signature")
      if explicit:return str(explicit)
      values=[m.get("scene_id") or m.get("scene"),m.get("shot_size") or m.get("framing"),m.get("subject_id") or m.get("subject"),m.get("composition")]
      return "|".join(str(x or "") for x in values) if sum(bool(x) for x in values)>=2 else None
    run=[]; runs=[]
    for row in clips:
      sig=signature(row)
      if sig and run and signature(run[-1])==sig:run.append(row)
      else:
        if run:runs.append(run)
        run=[row] if sig else []
    if run:runs.append(run)
    repeated=[x for x in runs if len(x)>VISUAL_PACING_PROFILE["max_consecutive_similar_shots"]]
    for rows in repeated:
      start=rows[0]["timeline_range"]["start_seconds"];end=rows[-1]["timeline_range"]["end_seconds"]
      issues.append(stable_issue("video.consecutive_visual_pattern_repeat",path,{"start_seconds":start,"end_seconds":end},"error",.96,"合并伪拆分镜头，改用关系镜、反应镜、证物或空间动作提供新的视觉信息",True,evidence=[{"clip_id":x.get("clip_id"),"timeline_range":x.get("timeline_range"),"metadata":x.get("metadata")} for x in rows],details={"source_adapter":"agentcut_visual_pacing","signature":signature(rows[0]),"consecutive_count":len(rows),"threshold":VISUAL_PACING_PROFILE["max_consecutive_similar_shots"],"clip_ids":[x.get("clip_id") for x in rows]}))
    grouped={}
    for row in clips:
      unit=(row.get("metadata") or {}).get("natural_unit_id") or (row.get("metadata") or {}).get("canonical_unit_id")
      if unit:grouped.setdefault(str(unit),[]).append(row)
    for unit,rows in grouped.items():
      seconds=sum(float(x["timeline_range"]["end_seconds"])-float(x["timeline_range"]["start_seconds"]) for x in rows);count=len(rows)
      if count>VISUAL_PACING_PROFILE["max_sources_per_natural_unit"] or seconds>VISUAL_PACING_PROFILE["fail_natural_unit_seconds"]:
        issues.append(stable_issue("video.natural_unit_source_overload",path,{"start_seconds":min(x["timeline_range"]["start_seconds"] for x in rows),"end_seconds":max(x["timeline_range"]["end_seconds"] for x in rows)},"error",.98,"将修复素材标记为 REPLACEMENT_CANDIDATE，只保留一个主素材；单元确需插入时必须声明新增信息",True,evidence=[{"clip_id":x.get("clip_id"),"metadata":x.get("metadata")} for x in rows],details={"source_adapter":"agentcut_visual_pacing","natural_unit_id":unit,"source_count":count,"runtime_seconds":round(seconds,6),"source_count_max":VISUAL_PACING_PROFILE["max_sources_per_natural_unit"],"runtime_fail_seconds":VISUAL_PACING_PROFILE["fail_natural_unit_seconds"]}))
    status="FAIL" if any(x.get("blocking") for x in issues) else "PASS"
    return issues,{"status":status,"requirement":"REQUIRED" if item.get("require_visual_pacing") or (item.get("metadata") or {}).get("production_contract_version") in {2,"2","v2"} else "OPTIONAL","source_adapter":"agentcut_visual_pacing","policy_version":VISUAL_PACING_PROFILE["version"],"clip_count":len(clips),"repeated_run_count":len(repeated),"overloaded_natural_unit_count":sum(x["rule_id"]=="video.natural_unit_source_overload" for x in issues)}

  def _agentcut_map(self,path,item):
    ref=(item.get("evidence_inputs") or {}).get("agentcut_project")
    if not ref:return None
    try:data=json.loads(Path(ref).expanduser().read_text())
    except Exception:return None
    clips=[]; selected=None
    for group in ("videoTracks","audioTracks","subtitleTracks"):
      for track in data.get("timeline",{}).get(group,[]):
       for clip in track.get("clips",[]):
        start=float(clip.get("start",0));duration=float(clip.get("duration",0)); meta=clip.get("metadata",{}) or {}
        kind="video" if group=="videoTracks" else "audio" if group=="audioTracks" else "subtitle"
        dialogue_id=clip.get("dialogue_id") or meta.get("dialogue_id")
        dialogue_id_source="explicit_metadata" if dialogue_id else None
        if not dialogue_id and kind=="audio":
          match=re.search(r"(DIA(?:-V2)?-\d+)",str(clip.get("id","")).upper())
          if match:dialogue_id=match.group(1);dialogue_id_source="legacy_clip_id"
        row={"clip_id":clip.get("id"),"track_id":track.get("id"),"kind":kind,"source":clip.get("source"),"text":clip.get("text"),"volume":float(clip.get("volume",1) or 0),"transition_in":clip.get("transitionIn"),"transition_out":clip.get("transitionOut"),"timeline_range":{"start_seconds":start,"end_seconds":start+duration},"metadata":{**meta,"dialogue_id":dialogue_id,"dialogue_id_source":dialogue_id_source,"beat_id":meta.get("beat_id")}}
        clips.append(row)
        try:same=Path(clip.get("source","")).expanduser().resolve()==path
        except Exception:same=False
        if same or clip.get("id")==item.get("clip_id"):
          selected={"project":str(Path(ref).resolve()),"clip_id":clip.get("id") or item.get("clip_id"),"timeline_range":{"start_seconds":start,"end_seconds":start+duration},"metadata":meta}
    expected_order=[str(x) for x in data.get("expectedDialogueIds",[]) if x]
    if not expected_order:
      expected_order=[]
      for x in sorted((x for x in clips if x["kind"]=="video" and x["metadata"].get("dialogue_id")),key=lambda x:x["timeline_range"]["start_seconds"]):
       value=str(x["metadata"]["dialogue_id"])
       if value not in expected_order:expected_order.append(value)
    expected=set(expected_order)
    audio_ids={str(x["metadata"].get("dialogue_id")) for x in clips if x["kind"]=="audio" and x["metadata"].get("dialogue_id")}
    subtitle_ids={str(x["metadata"].get("dialogue_id")) for x in clips if x["kind"]=="subtitle" and x["metadata"].get("dialogue_id")}
    audio_order=[str(x["metadata"]["dialogue_id"]) for x in sorted((x for x in clips if x["kind"]=="audio" and x["metadata"].get("dialogue_id")),key=lambda x:x["timeline_range"]["start_seconds"])]
    coverage={"expected_dialogue_count":len(expected),"expected_dialogue_order":expected_order,"audio_dialogue_count":len(expected & audio_ids),"audio_dialogue_order":audio_order,"subtitle_dialogue_count":len(expected & subtitle_ids),"missing_audio_dialogue_ids":[x for x in expected_order if x not in audio_ids],"missing_subtitle_dialogue_ids":[x for x in expected_order if x not in subtitle_ids],"audio_order_matches_script":audio_order==expected_order,"legacy_clip_id_mapped_count":sum(x["metadata"].get("dialogue_id_source")=="legacy_clip_id" for x in clips if x["kind"]=="audio"),"burned_subtitles_required":bool(data.get("requireBurnedSubtitles")),"complete":bool(expected) and expected<=audio_ids and audio_order==expected_order and (not data.get("requireBurnedSubtitles") or expected<=subtitle_ids)}
    ordered=sorted((x for x in clips if x["kind"]=="video"),key=lambda x:(x["timeline_range"]["start_seconds"],x["timeline_range"]["end_seconds"]))
    overlap_rows=[]; short_rows=[]
    for index,row in enumerate(ordered):
      span=row["timeline_range"]; duration=float(span["end_seconds"])-float(span["start_seconds"])
      previous=ordered[index-1] if index else None; following=ordered[index+1] if index+1<len(ordered) else None
      if previous and float(span["start_seconds"])<float(previous["timeline_range"]["end_seconds"])-1e-4: overlap_rows.append({"left_clip_id":previous["clip_id"],"right_clip_id":row["clip_id"],"overlap_seconds":float(previous["timeline_range"]["end_seconds"])-float(span["start_seconds"])})
      if duration<1.0:
       left_change=bool(previous and previous.get("source")!=row.get("source")); right_change=bool(following and following.get("source")!=row.get("source")); valid=not overlap_rows and (left_change or right_change)
       short_rows.append({"clip_id":row["clip_id"],"start_seconds":span["start_seconds"],"end_seconds":span["end_seconds"],"duration_seconds":duration,"left_source_changed":left_change,"right_source_changed":right_change,"valid_materialized_cut":valid,"validation_method":"non_overlapping_timeline_and_distinct_adjacent_source"})
    if overlap_rows:
      for row in short_rows: row["valid_materialized_cut"]=False;row["invalid_reason"]="timeline_overlap"
    valid_short=[x for x in short_rows if x["valid_materialized_cut"]]
    durations=[float(x["timeline_range"]["end_seconds"])-float(x["timeline_range"]["start_seconds"]) for x in ordered]
    pacing={"clip_count":len(ordered),"durations":durations,"mean_seconds":sum(durations)/len(durations) if durations else None,"maximum_seconds":max(durations) if durations else None,"raw_under_1s_count":len(short_rows),"validated_under_1s_count":len(valid_short),"under_1s_ratio":len(valid_short)/len(ordered) if ordered else None,"overlap_count":len(overlap_rows),"overlaps":overlap_rows,"short_clips":short_rows,"timeline_start_seconds":min((x["timeline_range"]["start_seconds"] for x in ordered),default=None),"timeline_end_seconds":max((x["timeline_range"]["end_seconds"] for x in ordered),default=None),"provenance_media_path":(data.get("output") or {}).get("path"),"validation_method":"non_overlapping_materialized_timeline_and_distinct_adjacent_source"}
    # A project may explicitly make story coverage authoritative and forbid padding.
    # It is trusted only through an already provenance-matched AgentCut project, an
    # active episode-matched contract, complete dialogue coverage and a clean timeline.
    runtime_policy=data.get("runtimePolicy") if isinstance(data.get("runtimePolicy"),dict) else (data.get("metadata") or {}).get("runtimePolicy",{})
    contract_ref=(data.get("metadata") or {}).get("anti_padding_contract");contract=None;contract_path=None
    if isinstance(contract_ref,str):
      candidate=Path(contract_ref).expanduser();contract_path=candidate.resolve() if candidate.is_absolute() else (Path(ref).expanduser().resolve().parent/candidate).resolve()
      try:contract=json.loads(contract_path.read_text())
      except Exception:contract=None
    episode=(data.get("metadata") or {}).get("episode")
    machine=(contract or {}).get("machine_gate",{}) if isinstance(contract,dict) else {}
    anti_padding_valid=bool(contract and contract.get("schema")=="qingshan.agentcut_anti_padding_contract.v1" and contract.get("status")=="ACTIVE_HARD_GATE" and contract.get("episode")==episode and machine.get("padding_forbidden") is True and machine.get("shorter_runtime_allowed_when_coverage_is_complete") is True and coverage.get("complete") and not overlap_rows and runtime_policy.get("paddingForbidden") is True and runtime_policy.get("allowShorter") is True)
    anti_padding={"status":"PASS" if anti_padding_valid else "NOT_APPLIED","authoritative":anti_padding_valid,"contract":str(contract_path) if contract_path else None,"contract_schema":(contract or {}).get("schema") if isinstance(contract,dict) else None,"contract_status":(contract or {}).get("status") if isinstance(contract,dict) else None,"episode":episode,"coverage_complete":coverage.get("complete"),"timeline_overlap_count":len(overlap_rows),"runtime_policy":runtime_policy,"policy_version":(contract or {}).get("schema") if isinstance(contract,dict) else None,"reason":"complete story coverage permits shorter runtime and explicitly forbids padding" if anti_padding_valid else None}
    outro=data.get("outro") if isinstance(data.get("outro"),dict) else {}
    explicit_start=outro.get("actualStart",outro.get("actual_start_seconds"))
    main_timeline_end=max((float(x["timeline_range"]["end_seconds"]) for x in clips if x["kind"]=="video"),default=0.0)
    actual_start=float(explicit_start) if isinstance(explicit_start,(int,float)) else main_timeline_end if outro.get("enabled") and main_timeline_end>0 else None
    outro_boundary={"enabled":bool(outro.get("enabled")),"actual_start_seconds":actual_start,"duration_seconds":float(outro.get("duration",0) or 0),"source":"outro.actualStart" if isinstance(explicit_start,(int,float)) else "materialized_main_video_timeline_end" if actual_start is not None else None,"trusted":actual_start is not None}
    return {**(selected or {"project":str(Path(ref).resolve()),"clip_id":item.get("clip_id"),"timeline_range":None,"metadata":{}}),"clips":clips,"coverage":coverage,"pacing":pacing,"anti_padding":anti_padding,"outro":outro_boundary}

  def _run_video_ocr_gap(self,path,start,end,item):
    script=Path(__file__).with_name("video_ocr_gap_adapter.py");configured=os.environ.get("QINGSHAN_OCR_PYTHON");interpreters=[x for x in [configured,"/usr/bin/python3",os.environ.get("PYTHON","python3")] if x];errors=[]
    for python in dict.fromkeys(interpreters):
      with tempfile.TemporaryDirectory() as td:
        dest=Path(td)/"gap.json"
        try:p=subprocess.run([python,str(script),"--video",str(path),"--out",str(dest),"--start",str(start),"--end",str(end),"--interval",str(float(item.get("ocr_gap_interval_seconds",.5)))],capture_output=True,text=True,timeout=float(item.get("ocr_timeout_seconds",300)))
        except Exception as exc:errors.append(f"{python}: {type(exc).__name__}: {exc}");continue
        if dest.is_file():
          try:
            data=json.loads(dest.read_text())
            if data.get("status")=="PASS" and data.get("candidate_sha256")==sha256(path):return data,None
            errors.append(f"{python}: {data.get('error','invalid result')}")
          except Exception as exc:errors.append(f"{python}: {type(exc).__name__}: {exc}")
    return None,{"status":"ERROR","error_code":"OCR_GAP_SCAN_UNAVAILABLE","errors":errors,"candidate_sha256":sha256(path),"start_seconds":start,"end_seconds":end}

  def _ocr_evidence(self,path,item,duration,mapped):
    inputs=item.get("evidence_inputs") or {};ref=inputs.get("ocr") or inputs.get("ocr_raw");adjudication_ref=inputs.get("ocr_adjudication")
    if not isinstance(ref,str):return [],None
    try:data=json.loads(Path(ref).expanduser().read_text())
    except Exception as exc:return [],{"status":"ERROR","error":f"{type(exc).__name__}: {exc}","evidence":str(ref),"rule_version":OCR_PROFILE["version"]}
    adjudication=None;adjudication_valid=False;adjudication_errors=[]
    if isinstance(adjudication_ref,str):
      try:
        adjudication_path=Path(adjudication_ref).expanduser().resolve();adjudication=json.loads(adjudication_path.read_text());visual=Path(str(adjudication.get("visual_evidence",""))).expanduser();raw_target=Path(ref).expanduser().resolve();candidate_path=Path(str(adjudication.get("candidate",""))).expanduser().resolve()
        checks=[(adjudication.get("schema")=="qingshan.fullcut-ocr-machine-adjudication.v1","schema"),(candidate_path==path.resolve(),"candidate"),(adjudication.get("candidate_sha256")==sha256(path),"candidate_sha256"),(Path(str(adjudication.get("raw_ocr_report",""))).expanduser().resolve()==raw_target,"raw_ocr_report"),(adjudication.get("raw_ocr_report_sha256")==sha256(raw_target),"raw_ocr_report_sha256"),(adjudication.get("raw_report_preserved") is True,"raw_report_preserved"),(visual.is_file(),"visual_evidence"),(visual.is_file() and adjudication.get("visual_evidence_sha256")==sha256(visual),"visual_evidence_sha256"),(str(adjudication.get("status","")).upper() in {"PASS_MACHINE_ADJUDICATION","PASS_ADJUDICATED"},"status"),(float(adjudication.get("confidence",0))>=.9,"confidence"),(int(adjudication.get("critical_text_failures",-1))==0,"critical_text_failures"),(adjudication.get("platform_mutation_authorized") is False,"platform_mutation_authorized")]
        adjudication_errors=[name for ok,name in checks if not ok];adjudication_valid=not adjudication_errors
      except Exception as exc:adjudication_errors=[f"{type(exc).__name__}: {exc}"]
    outro=(mapped or {}).get("outro") or {};trusted=bool(outro.get("trusted"));main_end=float(outro["actual_start_seconds"]) if trusted else float(duration)
    boundary_source=outro.get("source") if trusted else "media_end_no_trusted_outro_manifest"
    audit_scope=data.get("audit_scope") if isinstance(data.get("audit_scope"),dict) else {}
    declared_end=next((value for value in [*(data.get(k) for k in ("review_end_seconds","sample_end_seconds","sampled_through_seconds","exclusion_start_seconds")),audit_scope.get("main_content_end"),audit_scope.get("main_content_end_seconds"),audit_scope.get("review_end_seconds"),audit_scope.get("sampled_through_seconds")] if isinstance(value,(int,float))),None)
    if declared_end is None and data.get("schema")=="qingshan.final_video_ocr_audit.v1":declared_end=float(duration)
    issues=[];coverage_ok=declared_end is not None and float(declared_end)>=main_end-1e-3;supplemental=None;supplemental_error=None
    if not coverage_ok and declared_end is not None and float(declared_end)<main_end and item.get("use_existing_tools",True):
      supplemental,supplemental_error=self._run_video_ocr_gap(path,float(declared_end),main_end,item)
      if supplemental:
        data={**data,"recognitions":[*(data.get("recognitions") or []),*(supplemental.get("recognitions") or [])]};coverage_ok=True
    if not coverage_ok:
      detail={"source_adapter":"ocr_evidence","error_code":"MAIN_CONTENT_OCR_COVERAGE_GAP","required_review_end_seconds":main_end,"declared_review_end_seconds":declared_end,"boundary_source":boundary_source,"trusted_outro_manifest":trusted,"supplemental_scan_error":supplemental_error,"rule_profile":OCR_PROFILE["version"]}
      issues.append(stable_issue("ocr.main_content_coverage_gap",path,{"start_seconds":max(0,float(declared_end or 0)),"end_seconds":main_end},"critical",1,"从当前审片媒体重新执行 OCR；采样必须覆盖到精确片尾起点，禁止固定尾长排除",True,evidence=[{"type":"ocr_audit","path":str(Path(ref).resolve())}],details=detail))
    allow={str(x).strip().casefold() for x in [*OCR_PROFILE["default_brand_allowlist"],*(item.get("ocr_brand_allowlist") or [])] if str(x).strip()}
    rows=data.get("recognitions",data.get("hits",[]));rows=rows if isinstance(rows,list) else [];hit_count=0;allowed_branding=[];raw_rejected=[]
    raw_status=str(data.get("status","")).upper()
    def zero_or_empty(value):return value in (None,0,[],{})
    authoritative_normalized_pass=bool(data.get("schema")=="qingshan.final_video_ocr_audit.v2" and raw_status.startswith(("PASS","APPROVED","READY")) and data.get("lexicon_policy_configured") is True and int(data.get("critical_text_failures",-1))==0 and int(data.get("latin_chars",-1))==0 and zero_or_empty(data.get("unlisted_chinese_hits")) and zero_or_empty(data.get("numeric_string_hits")))
    interval=float(data.get("sample_interval_seconds",.1) or .1);normalized=[]
    for hit in rows:
      text=str(hit.get("text",hit.get("recognized_text",""))).strip();key=re.sub(r"\s+","",text).casefold();t=hit.get("time",hit.get("time_seconds",hit.get("start_seconds")))
      if isinstance(t,(int,float)):normalized.append({"hit":hit,"time":float(t),"text":text,"key":key,"confidence":float(hit.get("confidence",0) or 0)})
    def persistent(row):
      if not row["key"]:return False
      neighbors=[x for x in normalized if x["key"]==row["key"] and abs(x["time"]-row["time"])<=interval*OCR_PROFILE["persistence_gap_multiplier"]+1e-6]
      return len(neighbors)>=OCR_PROFILE["persistence_min_samples"]
    for row in normalized:
      hit=row["hit"]
      t=hit.get("time",hit.get("time_seconds",hit.get("start_seconds")))
      text=row["text"];folded=text.casefold()
      is_brand=bool(folded and any(token in folded for token in allow))
      if t>=main_end and is_brand:allowed_branding.append({"time_seconds":float(t),"text":text});continue
      if t>=main_end:continue
      if is_brand:continue
      meaningful=bool(re.search(r"[A-Za-z0-9\u3400-\u9fff]",text));forbidden=bool(hit.get("forbidden") or hit.get("forbidden_tokens"));confidence=row["confidence"];is_persistent=persistent(row)
      has_chinese=bool(re.search(r"[\u3400-\u9fff]",text));has_latin=bool(re.search(r"[A-Za-z]",text));is_numeric=bool(re.fullmatch(r"[0-9\s.,:;+-]+",text));explicit_allowed=hit.get("allowed") is True or hit.get("subtitle_region") is True or hit.get("classification") in {"SUBTITLE","INTENDED_SUBTITLE","ALLOWLISTED"}
      # Respect normalized per-hit policy. With a configured lexicon, Chinese that
      # is explicitly not unlisted is policy-listed/intended (commonly subtitles).
      policy_listed_chinese=bool(data.get("lexicon_policy_configured") is True and has_chinese and hit.get("unlisted_chinese") is False)
      if forbidden:accepted=True
      elif explicit_allowed or policy_listed_chinese:accepted=False
      elif has_latin or is_numeric or hit.get("numeric_string") is True:
        accepted=meaningful and confidence>=OCR_PROFILE["single_hit_confidence"] and is_persistent
      else:accepted=meaningful and (confidence>=OCR_PROFILE["single_hit_confidence"] or is_persistent)
      from_supplemental=bool(supplemental and any(abs(float(x.get("time_seconds",-999))-float(t))<1e-6 and x.get("text")==text for x in supplemental.get("recognitions",[])))
      if (adjudication_valid and not from_supplemental) or authoritative_normalized_pass or not accepted:
        reason="EXACT_FRAME_MACHINE_ADJUDICATION" if adjudication_valid and not from_supplemental else "AUTHORITATIVE_NORMALIZED_PASS" if authoritative_normalized_pass else "EXPLICITLY_ALLOWED_OR_SUBTITLE" if explicit_allowed else "POLICY_LISTED_CHINESE" if policy_listed_chinese else "NON_MEANINGFUL_SYMBOL" if not meaningful else "LATIN_NUMERIC_REQUIRES_HIGH_CONFIDENCE_AND_PERSISTENCE" if has_latin or is_numeric or hit.get("numeric_string") is True else "BELOW_CONFIDENCE_AND_PERSISTENCE_GATE"
        raw_rejected.append({"time_seconds":float(t),"text":text,"confidence":confidence,"reason":reason,"persistent":is_persistent,"forbidden":forbidden,"character_type":"CHINESE" if has_chinese else "LATIN" if has_latin else "NUMERIC" if is_numeric else "SYMBOL_OR_OTHER"});continue
      subtitles=[x for x in (mapped or {}).get("clips",[]) if x.get("kind")=="subtitle" and float(x["timeline_range"]["start_seconds"])<=float(t)<=float(x["timeline_range"]["end_seconds"])]
      duplicate=any(text and (text in str(x.get("text") or "") or str(x.get("text") or "") in text) for x in subtitles)
      rule="video.readable_native_text_duplicate" if duplicate else "video.readable_native_text"
      details={**hit,"source_adapter":"ocr_evidence","classification":"MAIN_CONTENT_NATIVE_TEXT_DUPLICATES_SUBTITLE" if duplicate else "MAIN_CONTENT_READABLE_TEXT","subtitle_matches":[{"clip_id":x.get("clip_id"),"text":x.get("text"),"timeline_range":x.get("timeline_range")} for x in subtitles],"main_content_end_seconds":main_end,"boundary_source":boundary_source,"rule_profile":OCR_PROFILE["version"]}
      issues.append(stable_issue(rule,path,{"start_seconds":float(t),"end_seconds":min(main_end,float(t)+float(data.get("sample_interval_seconds",.1) or .1))},"error",float(hit.get("confidence",.8)),"清除主内容中的原生可读文字或更换干净画面，再重新烧录唯一字幕",True,evidence=[{"type":"ocr_recognition","path":str(Path(ref).resolve()),"time_seconds":float(t),"text":text}],region=hit.get("region"),details=details));hit_count+=1
    normalized_raw_fail_pass=bool(data.get("schema")=="qingshan.final_video_ocr_audit.v2" and data.get("lexicon_policy_configured") is True and raw_status.startswith(("FAIL","REJECT")) and normalized and hit_count==0)
    adjudicated_pass=adjudication_valid or authoritative_normalized_pass or normalized_raw_fail_pass or (raw_status.startswith(("PASS","APPROVED","READY")) and int(data.get("readable_unintended_text_count",0) or 0)==0 and int(data.get("watermark_count",0) or 0)==0)
    status="ERROR" if not coverage_ok else "FAIL" if hit_count or (raw_status.startswith(("FAIL","REJECT")) and not adjudicated_pass) else "PASS"
    return issues,{"status":status,"evidence":str(Path(ref).resolve()),"raw_status":data.get("status"),"derived_status":"PASS_MACHINE_ADJUDICATED_EXACT_FRAMES" if adjudication_valid else "PASS_NORMALIZED_AUTHORITATIVE" if authoritative_normalized_pass else "PASS_POLICY_NORMALIZED_RAW_FAIL" if normalized_raw_fail_pass else None,"source_adapter":"explicit_evidence","rule_version":OCR_PROFILE["version"],"machine_adjudication":{"provided":isinstance(adjudication_ref,str),"valid":adjudication_valid,"evidence":str(Path(adjudication_ref).expanduser().resolve()) if isinstance(adjudication_ref,str) else None,"errors":adjudication_errors,"confidence":adjudication.get("confidence") if isinstance(adjudication,dict) else None,"raw_report_preserved":adjudication.get("raw_report_preserved") if isinstance(adjudication,dict) else None},"supplemental_gap_scan":{"status":"PASS" if supplemental else "NOT_RUN" if coverage_ok and supplemental_error is None else "ERROR","start_seconds":float(declared_end) if supplemental else None,"end_seconds":main_end if supplemental else None,"sample_count":supplemental.get("sample_count") if supplemental else None,"recognition_count":len(supplemental.get("recognitions",[])) if supplemental else None,"engine":supplemental.get("engine") if supplemental else None,"error":supplemental_error},"evidence_policy":{"authoritative_normalized_decision":authoritative_normalized_pass,"policy_normalized_raw_fail":normalized_raw_fail_pass,"single_hit_confidence":OCR_PROFILE["single_hit_confidence"],"persistence_min_samples":OCR_PROFILE["persistence_min_samples"],"latin_numeric_requires_both_high_confidence_and_persistence":True,"policy_listed_chinese_allowed":True,"subtitle_region_allowed":True,"sample_interval_seconds":interval,"critical_text_failures_raw":data.get("critical_text_failures"),"latin_chars_raw":data.get("latin_chars"),"unlisted_chinese_hit_count_raw":len(data.get("unlisted_chinese_hits",[])) if isinstance(data.get("unlisted_chinese_hits"),list) else data.get("unlisted_chinese_hits"),"numeric_string_hit_count_raw":len(data.get("numeric_string_hits",[])) if isinstance(data.get("numeric_string_hits"),list) else data.get("numeric_string_hits")},"review_window":{"start_seconds":0.0,"main_content_end_seconds":main_end,"outro_start_seconds":outro.get("actual_start_seconds"),"declared_review_end_seconds":declared_end,"effective_review_end_seconds":main_end if coverage_ok else declared_end,"boundary_source":boundary_source,"trusted_outro_manifest":trusted,"blind_tail_exclusion":False},"main_content_hit_count":hit_count,"raw_recognition_count":len(normalized),"raw_rejected_count":len(raw_rejected),"raw_rejected_recognitions":raw_rejected,"allowed_branding":allowed_branding}

  def _ambience(self,path,item,mapped,dur):
    cfg=self._ambience_config(item);clips=(mapped or {}).get("clips",[])
    ambience=[x for x in clips if x.get("kind")=="audio" and (x.get("metadata",{}).get("speech_free") is True or "AMBIENCE" in str(x.get("metadata",{}).get("kind","")).upper() or "AMB" in str(x.get("track_id","")).upper())]
    role=str((item.get("metadata") or {}).get("audio_role","")).upper()
    if not ambience and role not in {"AMBIENCE","SFX_AMBIENCE","ENVIRONMENT"}:
      baseline=(item.get("evidence_inputs") or {}).get("audio_baseline")
      if not baseline:return [],None
    out=[]
    def add(rule,location,details,recommendation,severity="warning",blocking=False,confidence=.96):
      details={**details,"profile":cfg,"source_adapter":"ambience_qa"};out.append(stable_issue(rule,path,location,severity,confidence,recommendation,blocking,evidence=[{"type":"ambience_audit","project":(mapped or {}).get("project"),"sources":sorted({x.get("source") for x in ambience if x.get("source")})}],details=details))
    groups={}
    for clip in ambience:groups.setdefault(str(Path(clip.get("source","")).expanduser()),[]).append(clip)
    measurements={}
    for source,rows in sorted(groups.items()):
      source_path=Path(source);full=measured_mean_db(source_path,self.ffmpeg);high=measured_mean_db(source_path,self.ffmpeg,6000);measurements[source]={"mean_db":full,"highpass_6k_mean_db":high}
      max_volume=max(float(x.get("volume",1)) for x in rows);gain_db=20*math.log10(max(max_volume,1e-9));start=min(x["timeline_range"]["start_seconds"] for x in rows);end=max(x["timeline_range"]["end_seconds"] for x in rows);location={"start_seconds":max(0,start),"end_seconds":min(dur or end,end)}
      clip_evidence=[{"clip_id":x["clip_id"],"start_seconds":x["timeline_range"]["start_seconds"],"end_seconds":x["timeline_range"]["end_seconds"],"volume":x.get("volume"),"transition_in":x.get("transition_in"),"transition_out":x.get("transition_out")} for x in rows]
      if max_volume>cfg["gain_warn"]:
        blocking=max_volume>cfg["gain_block"];add("audio.ambience_gain_excessive",location,{"source":source,"max_volume":max_volume,"gain_db":gain_db,"clips":clip_evidence},"降低环境轨增益；素材过轻时更换或重制，禁止用暴力增益抬高底噪","error" if blocking else "warning",blocking)
      scheduled=max(float(x["timeline_range"]["end_seconds"])-float(x["timeline_range"]["start_seconds"]) for x in rows);crossfades=[]
      for x in rows:
        for transition in (x.get("transition_in"),x.get("transition_out")):
          if isinstance(transition,dict) and isinstance(transition.get("duration"),(int,float)):crossfades.append(float(transition["duration"]))
      min_fade=min(crossfades) if crossfades else 0.0
      if scheduled<=cfg["short_loop_seconds"] and len(rows)>=cfg["repeat_warn"] and min_fade<cfg["min_crossfade_seconds"]:
        blocking=len(rows)>=cfg["repeat_block"];add("audio.periodic_ambience_loop",location,{"source":source,"repeat_count":len(rows),"scheduled_clip_seconds":scheduled,"minimum_crossfade_seconds":min_fade,"clips":clip_evidence},"改用长环境底或多个变体并错位起点；循环交叉淡化至少达到策略门槛","error" if blocking else "warning",blocking)
      if high is not None:
        projected=high+gain_db
        if high>cfg["source_hiss_db"] or projected>cfg["projected_hiss_db"]:
          blocking=projected>-34;add("audio.high_frequency_hiss",location,{"source":source,"source_mean_db":full,"source_highpass_6k_mean_db":high,"gain_db":gain_db,"projected_highpass_6k_mean_db":projected,"clips":clip_evidence},"环境素材入库前降噪或替换，并柔和衰减高频 hiss；重新测量后方可使用","error" if blocking else "warning",blocking,.94)
    if ambience:
      dialogue=[x for x in clips if x.get("kind")=="audio" and x.get("metadata",{}).get("dialogue_id")][:8];dialogue_levels=[]
      for clip in dialogue:
        source=Path(clip.get("source","")).expanduser();level=measured_mean_db(source,self.ffmpeg)
        if level is not None:dialogue_levels.append(level+20*math.log10(max(float(clip.get("volume",1)),1e-9)))
      ambience_levels=[]
      for source,rows in groups.items():
        level=measurements[source]["mean_db"]
        if level is not None:ambience_levels.append(level+20*math.log10(max(max(float(x.get("volume",1)) for x in rows),1e-9)))
      if dialogue_levels and ambience_levels:
        dialogue_db=statistics.median(dialogue_levels);ambience_db=max(ambience_levels);headroom=dialogue_db-ambience_db
        if headroom<cfg["dialogue_headroom_warn_db"]:
          blocking=headroom<cfg["dialogue_headroom_block_db"];add("audio.dialogue_to_ambience_ratio",{"start_seconds":0,"end_seconds":dur},{"sampled_dialogue_count":len(dialogue_levels),"median_dialogue_db":dialogue_db,"ambience_db":ambience_db,"dialogue_headroom_db":headroom},"降低环境底并使用对白驱动 ducking；对白期间保持足够响度余量","error" if blocking else "warning",blocking,.9)
    baseline=(item.get("evidence_inputs") or {}).get("audio_baseline")
    if isinstance(baseline,str) and Path(baseline).is_file():
      current=measured_mean_db(path,self.ffmpeg,6000);previous=measured_mean_db(Path(baseline),self.ffmpeg,6000)
      if current is not None and previous is not None:
        delta=current-previous
        if delta>cfg["baseline_hiss_warn_delta_db"]:
          blocking=delta>cfg["baseline_hiss_block_delta_db"];add("audio.noise_floor_jump",{"start_seconds":0,"end_seconds":dur},{"baseline_path":str(Path(baseline).resolve()),"current_highpass_6k_mean_db":current,"baseline_highpass_6k_mean_db":previous,"delta_db":delta},"回退新增音效层并定位高频噪声来源；不得以响度提升掩盖底噪","error" if blocking else "warning",blocking,.98)
    status="FAIL" if any(x["blocking"] for x in out) else "WARN" if any(x.get("actionable") for x in out) else "PASS"
    return out,{"status":status,"profile":cfg,"ambience_clip_count":len(ambience),"unique_source_count":len(groups),"measurements":measurements,"project":(mapped or {}).get("project")}

  def _audio(self,path,item,dur,mapped=None):
    rate,s=audio_pcm(path,self.ffmpeg); out=[]; cfg=self._audio_config(item)
    if not s: return out
    peak=max(abs(x) for x in s); rms=math.sqrt(sum(x*x for x in s)/len(s))/32768; whole_db=20*math.log10(max(rms,1e-12))
    if whole_db<=cfg["digital_zero_db"]: out.append(stable_issue("audio.digital_zero",path,{"start_seconds":0,"end_seconds":dur},"critical",1,"恢复或重新生成音轨",True,details={"mean_db":whole_db,"threshold_db":cfg["digital_zero_db"],"profile":cfg["version"],"source_adapter":"builtin_audio"}))
    elif peak>=32760: out.append(stable_issue("audio.clipping",path,{"start_seconds":0,"end_seconds":dur},"error",.95,"降低增益并限制峰值",True,details={"peak":peak,"source_adapter":"builtin_audio"}))
    if item.get("authoritative_continuity_evidence"): return out
    win=max(1,int(rate*cfg["window_seconds"])); levels=[]
    for i in range(0,len(s),win):
      c=s[i:i+win]; level=math.sqrt(sum(x*x for x in c)/max(1,len(c)))/32768; levels.append(20*math.log10(max(level,1e-12)))
    silent=[i for i,x in enumerate(levels) if x<=cfg["silence_db"]]
    runs=[]
    for i in silent:
      if not runs or i>runs[-1][-1]+1:runs.append([i])
      else:runs[-1].append(i)
    for r in runs:
      if len(r)*cfg["window_seconds"]>=cfg["min_silence_seconds"]:
        st=r[0]*cfg["window_seconds"]; en=min(dur or len(s)/rate,(r[-1]+1)*cfg["window_seconds"])
        out.append(stable_issue("audio.long_silence",path,{"start_seconds":st,"end_seconds":en},"error",.94,"补齐对白/环境声或确认设计性静音",True,evidence=[{"type":"audio_window","start_seconds":st,"end_seconds":en}],details={"thresholds":cfg,"source_adapter":"builtin_audio"}))
    raw_deltas=[]
    for i,(a,b) in enumerate(zip(levels,levels[1:])):
      jump=abs(b-a)
      if jump>cfg["max_adjacent_rms_jump_db"]:
        st=(i+1)*cfg["window_seconds"];window_start=max(0,st-cfg["window_seconds"]);window_end=min(dur or len(s)/rate,st+cfg["window_seconds"]);raw_deltas.append({"start_seconds":window_start,"end_seconds":window_end,"boundary_candidate_seconds":st,"rms_before_db":a,"rms_after_db":b,"jump_db":jump})
    if raw_deltas:
      first=raw_deltas[0];last=raw_deltas[-1]
      out.append(stable_issue("audio.rms_window_delta_raw",path,{"start_seconds":first["start_seconds"],"end_seconds":last["end_seconds"]},"info",.8,"保留诊断证据；仅在真实剪辑边界用短窗复测后决定是否修复",False,evidence=[{"type":"decoded_final_fixed_windows","rows":raw_deltas}],details={"raw_count":len(raw_deltas),"raw_deltas":raw_deltas,"thresholds":cfg,"measurement_scope":"RAW_FIXED_WINDOWS_NOT_EDIT_BOUNDARIES","actionable":False,"source_adapter":"builtin_audio"}))
    # Score only audience-facing measurements immediately around real materialized
    # edit boundaries. Whole/fixed-window deltas remain raw informational evidence.
    video_clips=sorted((x for x in (mapped or {}).get("clips",[]) if x.get("kind")=="video"),key=lambda x:x.get("timeline_range",{}).get("start_seconds",0))
    boundaries=sorted({float(x["timeline_range"]["start_seconds"]) for x in video_clips[1:] if isinstance(x.get("timeline_range",{}).get("start_seconds"),(int,float))})
    for cut in boundaries:
      local=adjudicate_audio_cut(s,rate,cut,float(cfg.get("boundary_window_seconds",.12)));jump=abs(float(local.get("after_rms_db",-120))-float(local.get("before_rms_db",-120)))
      if jump<=cfg["max_adjacent_rms_jump_db"]:continue
      audible=bool(local.get("audible_discontinuity"));details={"cut_seconds":cut,"local_jump_db":round(jump,3),"threshold_db":cfg["max_adjacent_rms_jump_db"],"boundary_window_seconds":cfg.get("boundary_window_seconds",.12),"continuity_adjudication":local,"measurement_scope":"DECODED_FINAL_REAL_MATERIALIZED_BOUNDARY","motivated":not audible,"actionable":audible,"source_adapter":"builtin_audio_boundary_local"}
      out.append(stable_issue("audio.rms_jump",path,{"start_seconds":max(0,cut-float(cfg.get("boundary_window_seconds",.12))),"end_seconds":min(dur,cut+float(cfg.get("boundary_window_seconds",.12))),"cut_seconds":cut},"warning" if audible else "info",.96,"修复该切点掉音、数字零或爆点并做短交叉淡化" if audible else "保留有动机的对白/音乐动态，无需修复",False,evidence=[{"type":"decoded_final_boundary_window","cut_seconds":cut,"before_rms_db":local.get("before_rms_db"),"after_rms_db":local.get("after_rms_db")}],details=details))
    return out

  def _audio_config(self,item):
    overrides=item.get("audio_thresholds") or {}; cfg=dict(AUDIO_PROFILE)
    for k in ("digital_zero_db","silence_db","min_silence_seconds","max_adjacent_rms_jump_db","window_seconds","boundary_window_seconds"):
      if k in overrides: cfg[k]=float(overrides[k])
    return cfg

  def _ambience_config(self,item):
    overrides=item.get("ambience_thresholds") or {};cfg=dict(AMBIENCE_PROFILE)
    for key,value in overrides.items():
      if key not in AMBIENCE_PROFILE or key=="version" or not isinstance(value,(int,float)):raise ValueError(f"invalid ambience threshold: {key}")
      cfg[key]=float(value)
    return cfg

  def _regression_ci(self,path,item):
    caps={}; evidence=item.get("evidence_inputs") or {}; report_path=evidence.get("regression_ci_json"); data=None
    if report_path:
      try:data=json.loads(Path(report_path).expanduser().read_text()); caps["regression_ci"]={"status":"PASS" if data.get("status")=="PASS" else "FAIL","raw_status":data.get("status"),"evidence":str(Path(report_path).resolve()),"schema":data.get("schema")}
      except Exception as exc: caps["regression_ci"]={"status":"ERROR","evidence":report_path,"error":f"{type(exc).__name__}: {exc}"}
    elif item.get("run_regression_ci",True):
      tool=self.root/"tools/run_regression_ci.py"
      if not tool.is_file() or not self.ffmpeg: caps["regression_ci"]={"status":"ERROR","error":"tool_or_ffmpeg_missing","tool":str(tool)}
      else:
        with tempfile.TemporaryDirectory() as td:
          dest=Path(td)/"regression.json"; cmd=[os.environ.get("PYTHON","python3"),str(tool),"--video",str(path),"--out",str(dest),"--ffmpeg",self.ffmpeg]
          mapping={"coverage_manifest":"--coverage-manifest-json","action_audit":"--action-audit-json","sentence_audit":"--sentence-audit-json","asr":"--asr-json","scene_brightness":"--scene-brightness-json","ocr":"--ocr-audit-json"}
          for key,arg in mapping.items():
            if evidence.get(key): cmd += [arg,str(evidence[key])]
          try:
            proc=subprocess.run(cmd,capture_output=True,text=True,timeout=item.get("regression_timeout_seconds",900));
            if dest.is_file(): data=json.loads(dest.read_text()); caps["regression_ci"]={"status":"PASS" if data.get("status")=="PASS" else "FAIL","raw_status":data.get("status"),"tool":str(tool),"returncode":proc.returncode,"stderr":proc.stderr[-2000:]}
            else: caps["regression_ci"]={"status":"ERROR","tool":str(tool),"returncode":proc.returncode,"stdout":proc.stdout[-2000:],"stderr":proc.stderr[-2000:]}
          except subprocess.TimeoutExpired as exc: caps["regression_ci"]={"status":"ERROR","tool":str(tool),"error":f"timeout:{exc.timeout}s"}
    else: caps["regression_ci"]={"status":"NOT_RUN","reason":"disabled_by_request"}
    if not data:return [],caps
    aliases={"action_realtime":"action","asr_sentence_audit":"sentence_audit","speech_density":"asr","scene_brightness":"scene_brightness","ocr_audit":"ocr","source_manifest":"coverage","manifest_shot_reconciliation":"coverage"}
    missing_required={"action":"action_realtime_evidence_missing" in data.get("failures",[]),"sentence_audit":"asr_sentence_audit_missing" in data.get("failures",[]),"asr":"asr_speech_segments_missing" in data.get("failures",[]),"scene_brightness":"scene_brightness_audit_missing" in data.get("failures",[]),"coverage":bool(data.get("thresholds",{}).get("forward_source_gates_required"))}
    for src,dst in aliases.items():
      value=data.get(src)
      if isinstance(value,dict):
        raw=value.get("status"); status="NOT_RUN" if raw in {"MISSING","NOT_REQUESTED",None} else "PASS" if str(raw).startswith("PASS") else "FAIL"
        caps[dst]={"status":status,"requirement":"REQUIRED" if missing_required.get(dst,False) else "OPTIONAL","evidence":report_path or "generated:run_regression_ci","source_section":src,"raw_status":raw}
    issues=[]; raw_thresholds=dict(data.get("thresholds",{}));thresholds=dict(raw_thresholds);policy=item.get("_gate_policy_audit") or {"applied":False,"overrides":{}}
    if policy.get("applied"):thresholds.update(policy.get("overrides",{}))
    asl=data.get("asl",{}); agentcut=item.get("_agentcut_context") or {}
    project_clips=agentcut.get("clips",[])
    video_clips=[x for x in project_clips if x.get("kind")=="video"]
    speech_clips=[x for x in project_clips if x.get("kind") in {"audio","subtitle"} and x.get("metadata",{}).get("dialogue_id")]
    project_cuts=sorted({float(x["timeline_range"]["start_seconds"]) for x in video_clips}|{float(x["timeline_range"]["end_seconds"]) for x in video_clips})
    def overlaps(row,start,end):
      span=row.get("timeline_range") or {}; return float(span.get("start_seconds",0))<end and float(span.get("end_seconds",0))>start
    def speech_evidence(start,end):
      hits=[x for x in speech_clips if overlaps(x,start,end)]
      return {"has_speech":bool(hits),"dialogue_ids":sorted({x["metadata"]["dialogue_id"] for x in hits}),"sources":sorted({x["kind"] for x in hits}),"clip_ids":[x.get("clip_id") for x in hits]}
    def split_at_project_cuts(start,end):
      points=[start,*[x for x in project_cuts if start<x<end],end]
      return [(points[i],points[i+1]) for i in range(len(points)-1)]
    def add(rule,loc,details,recommendation="按生产回归门修复后重审",severity="error",blocking=True): issues.append(stable_issue(rule,path,loc,severity,.99,recommendation,blocking,evidence=[{"type":"qa_json","path":str(report_path) if report_path else None}],details={**details,"threshold_profile":data.get("threshold_profile"),"raw_thresholds":raw_thresholds,"thresholds":thresholds,"gate_policy":policy,"source_adapter":"production_regression"}))
    runtime=float(data.get("runtime_seconds",0) or 0);media_duration=float(item.get("_media_duration",0) or 0);location_duration=min(runtime,media_duration) if runtime and media_duration else runtime or media_duration;min_runtime=float(thresholds.get("min_runtime",0) or 0);max_runtime=float(thresholds.get("max_runtime",float("inf")) or float("inf"));anti_padding=agentcut.get("anti_padding") or {}
    if runtime and runtime<min_runtime and anti_padding.get("authoritative"):
      add("video.runtime_min_reconciled",{"start_seconds":0,"end_seconds":location_duration},{"runtime_seconds":runtime,"raw_minimum_seconds":min_runtime,"raw_failure":next((x for x in data.get("failures",[]) if str(x).startswith("runtime_")),None),"agentcut_timeline":agentcut.get("pacing"),"anti_padding_policy":anti_padding,"adjudication":"PASS_EPISODE_AUTHORITATIVE_ANTI_PADDING","actionable":False},"禁止为满足全局片长下限补空镜；保留完整剧情覆盖", "info",False)
    elif runtime and runtime<min_runtime:add("video.runtime_min",{"start_seconds":0,"end_seconds":location_duration},{"runtime_seconds":runtime,"minimum_seconds":min_runtime},"按审计策略补足片长或提供经批准的 episode/project gate_policy")
    if runtime and runtime>max_runtime:add("video.runtime_max",{"start_seconds":0,"end_seconds":location_duration},{"runtime_seconds":runtime,"maximum_seconds":max_runtime},"按审计策略缩短片长或提供经批准的 episode/project gate_policy")
    if float(asl.get("mean",0) or 0)>float(thresholds.get("redline_asl",5)): add("video.asl_redline",{"start_seconds":0,"end_seconds":location_duration},{"asl":asl.get("mean")},"缩短长镜头并提升剪辑节奏")
    longs=[x for x in asl.get("durations",[]) if x>float(thresholds.get("max_single_shot",6))]
    if longs:
      static_by_index={int(row.get("shot_index",0)):row for row in (data.get("static_hold_gate",{}).get("shot_rows") or [])}
      points=[0.0,*[float(x) for x in asl.get("cut_times",[])]]; long_rows=[]; max_single=float(thresholds.get("max_single_shot",6)); motion_max=float(thresholds.get("static_hold_motion_max",1.5)); static_seconds=float(thresholds.get("static_hold_seconds_max",4.0))
      for index,duration in enumerate(asl.get("durations",[]),start=1):
       if float(duration)<=max_single: continue
       start=points[index-1] if index-1<len(points) else sum(float(x) for x in asl.get("durations",[])[:index-1]); end=start+float(duration); static=static_by_index.get(index,{})
       segments=split_at_project_cuts(start,end) if project_cuts else [(start,end)]
       for segment_index,(segment_start,segment_end) in enumerate(segments,1):
        segment_duration=segment_end-segment_start
        if segment_duration<=max_single: continue
        speech=speech_evidence(segment_start,segment_end); has_speech=bool(static.get("has_speech",False)) or speech["has_speech"]
        is_static=float(static.get("mean_motion",motion_max+1))<=motion_max and segment_duration>static_seconds; static_status=static.get("status"); motivated=has_speech or bool(static.get("motivated",False))
        long_rows.append({"shot_index":index,"segment_index":segment_index,"start_seconds":segment_start,"end_seconds":segment_end,"duration_seconds":segment_duration,"original_detected_range":{"start_seconds":start,"end_seconds":end},"project_cut_constrained":len(segments)>1,"motivated":motivated,"motivation_reason":"agentcut_dialogue_or_subtitle" if speech["has_speech"] else "speech" if has_speech else static.get("motivation_reason"),"speech_evidence":speech,"unmotivated":not motivated,"static_hold":is_static,"static_hold_blocking":bool(is_static and not has_speech and static_status not in {"PASS","PASS_MOTIVATED"}),"mean_motion":static.get("mean_motion"),"has_speech":has_speech,"static_hold_status":static_status,"rule_interpretation":"AgentCut video cuts constrain shot boundaries; dialogue audio or subtitle overlap motivates a shot without weakening the freeze threshold."})
      motivated_rows=[row for row in long_rows if row["motivated"]];unmotivated_rows=[row for row in long_rows if row["unmotivated"]];counts={"raw_long_shot_count":len(long_rows),"motivated_long_shot_count":len(motivated_rows),"unmotivated_long_shot_count":len(unmotivated_rows),"max_unmotivated_long_shots":int(thresholds.get("max_unmotivated_long_shots",2))}
      if motivated_rows: add("video.motivated_long_shots",{"start_seconds":0,"end_seconds":location_duration},{**counts,"long_shots":motivated_rows},"保留有动机长镜；无需强制拆分", "info",False)
      if len(unmotivated_rows)>counts["max_unmotivated_long_shots"]: add("video.too_many_long_shots",{"start_seconds":0,"end_seconds":location_duration},{**counts,"durations":[row["duration_seconds"] for row in unmotivated_rows],"long_shots":unmotivated_rows},"仅拆分或替换无动机长镜头")
    ratio=asl.get("under_1s_ratio")
    under1_min=float(thresholds.get("under1_min",.05));under1_max=float(thresholds.get("under1_max",.15));project_pacing=agentcut.get("pacing") or {};project_ratio=project_pacing.get("under_1s_ratio")
    detector_stats={"segment_count":asl.get("segment_count",len(asl.get("durations",[]))),"under_1s_count":asl.get("under_1s",sum(float(x)<1 for x in asl.get("durations",[]))),"under_1s_ratio":ratio,"mean_seconds":asl.get("mean"),"durations":asl.get("durations",[]),"cut_times":asl.get("cut_times",[]),"frame_repeat":data.get("frame_repeat"),"raw_failures":[x for x in data.get("failures",[]) if str(x).startswith(("asl_","too_many_long_shots","under1_ratio","repeated_frame_cluster"))],"detector":"ffmpeg_scene_gt_0.3"}
    project_stats={**project_pacing,"threshold_min":under1_min,"threshold_max":under1_max}
    detector_out=ratio is not None and not under1_min<=float(ratio)<=under1_max
    project_valid=project_ratio is not None and int(project_pacing.get("overlap_count",0))==0
    project_pass=project_valid and under1_min<=float(project_ratio)<=under1_max
    if anti_padding.get("authoritative") and project_valid and detector_out:
      add("video.pacing_reconciled",{"start_seconds":0,"end_seconds":location_duration},{"detector":detector_stats,"agentcut_project":project_stats,"anti_padding_policy":anti_padding,"adjudication":"PASS_MATERIALIZED_TIMELINE_WITH_ANTI_PADDING","raw_failures_preserved":True,"actionable":False},"按剧情物化时间线保持当前剪辑；不得为满足短镜比例制造无意义切点", "info",False)
    elif detector_out and project_pass:
      add("video.under1_ratio_reconciled",{"start_seconds":0,"end_seconds":location_duration},{"detector":detector_stats,"agentcut_project":project_stats,"adjudication":"PASS_PROJECT_MATERIALIZED_TIMELINE","actionable":False},"保留两套统计；物化时间线短镜比例合格，无需强制修片", "info",False)
    elif detector_out or (project_valid and not project_pass):
      add("video.under1_ratio",{"start_seconds":0,"end_seconds":location_duration},{"ratio":project_ratio if project_valid else ratio,"detector":detector_stats,"agentcut_project":project_stats if project_pacing else None,"adjudication":"FAIL_PROJECT_TIMELINE" if project_valid else "FAIL_PIXEL_DETECTOR_ONLY"},"调整短镜头比例")
    audio=data.get("audio_bed_continuity",{})
    if isinstance(audio,dict): caps["audio_analysis"]={"status":"PASS" if audio.get("status")=="PASS" else "FAIL","raw_status":audio.get("status"),"evidence":report_path or "generated:run_regression_ci","source_section":"audio_bed_continuity","thresholds":audio.get("thresholds")}
    for row in audio.get("unmotivated_silence_segments",[]): add("audio.long_silence",{"start_seconds":row.get("start_sec"),"end_seconds":row.get("end_sec")},row,"补齐声音或登记有动机静音")
    shot_rows={int(x["shot_index"]):x for x in audio.get("shot_rows",[]) if "shot_index" in x}
    cut_rate,cut_samples=audio_pcm(path,self.ffmpeg)
    for row in audio.get("excessive_adjacent_rms_jumps",[]):
      left=shot_rows.get(int(row["left_shot"]),{}); right=shot_rows.get(int(row["right_shot"]),{});cut=float(left.get("end_sec",right.get("start_sec",0)) or 0); adjudication=adjudicate_audio_cut(cut_samples,cut_rate,cut)
      motivated=adjudication.get("status")=="PASS"; details={**row,"raw_regression_jump":dict(row),"cut_seconds":cut,"continuity_adjudication":adjudication,"motivated":motivated,"actionable":not motivated}
      add("audio.rms_jump",{"start_seconds":left.get("start_sec"),"end_seconds":right.get("end_sec"),"cut_seconds":cut,"left_shot":row["left_shot"],"right_shot":row["right_shot"]},details,"保留为有动机的对白/音乐动态，无需修复" if motivated else "修复切点掉音、数字零或爆点并复测","info" if motivated else "warning",False)
    mapped={"action_realtime_evidence_missing":"action","asr_sentence_audit_missing":"sentence_audit","asr_speech_segments_missing":"asr","scene_brightness_audit_missing":"scene_brightness"}
    for failure in data.get("failures",[]):
      if failure in mapped: continue
      if failure.startswith(("asl_","too_many_long_shots","under1_ratio","audio_","runtime_")): continue
      if failure.startswith("unmotivated_static_hold:"):
        m=re.search(r":(\d+):([0-9.]+)\+([0-9.]+)",failure)
        if not m: add("video.static_hold",{}, {"failure":failure},"替换无动机静态停留"); continue
        shot_index=int(m.group(1)); start=float(m.group(2)); end=start+float(m.group(3)); segments=split_at_project_cuts(start,end) if project_cuts else [(start,end)]
        actionable=[]; motivated=[]
        for segment_start,segment_end in segments:
          speech=speech_evidence(segment_start,segment_end); row={"start_seconds":segment_start,"end_seconds":segment_end,"duration_seconds":segment_end-segment_start,"speech_evidence":speech}
          (motivated if speech["has_speech"] else actionable).append(row)
        # A detector interval spanning explicit edit cuts is not a single frozen shot. Keep
        # the raw finding as non-actionable evidence; genuine within-clip holds still block.
        if len(segments)>1 or (motivated and not actionable):
          add("video.static_hold_reconciled",{"shot_index":shot_index,"start_seconds":start,"end_seconds":end},{"failure":failure,"project_cut_constrained":len(segments)>1,"segments":segments,"motivated_segments":motivated,"actionable_segments":actionable,"actionable":False},"保留原始检测证据；按 AgentCut 切点重新检测各 clip", "info",False)
        else:
          add("video.static_hold",{"shot_index":shot_index,"start_seconds":start,"end_seconds":end},{"failure":failure,"segments":actionable},"替换无动机静态停留")
      elif failure=="opening_10s_speech_energy_fail":
        speech=speech_evidence(0,10)
        if speech["has_speech"]:
          add("audio.opening_speech_energy_reconciled",{"start_seconds":0,"end_seconds":10},{"failure":failure,"metrics":data.get("opening_10s_speech_energy"),"speech_evidence":speech,"actionable":False},"AgentCut 对白/字幕已证明开场存在对白；保留原始能量检测供复核", "info",False)
        else: add("audio.opening_speech_energy",{"start_seconds":0,"end_seconds":10},{"failure":failure,"metrics":data.get("opening_10s_speech_energy")},"修复开场对白能量或补齐 ASR 证据")
    return issues,caps

  def _black_frame_scan(self,path,item,dur):
    profile={"version":"qingshan.black_frame.v1","pblack_threshold":99.9,"pixel_threshold":20,"scope":"ALL_DECODED_FRAMES"};evidence=[];issues=[]
    if not self.ffmpeg:
      detail={"source_adapter":"black_frame_scan","error_code":"FFMPEG_UNAVAILABLE","profile":profile}
      return [stable_issue("video.black_frame_scan_error",path,{},"critical",1,"安装可用 ffmpeg 后逐帧重审，禁止无证据通过",True,evidence=[detail],details=detail)],{"status":"ERROR","requirement":"REQUIRED","error_code":"FFMPEG_UNAVAILABLE","profile":profile}
    try:
      p=subprocess.run([self.ffmpeg,"-hide_banner","-nostats","-i",str(path),"-an","-vf",f"blackframe=amount={profile['pblack_threshold']}:threshold={profile['pixel_threshold']}","-f","null","-"],capture_output=True,text=True,timeout=item.get("tool_timeout_seconds",300))
    except subprocess.TimeoutExpired:
      detail={"source_adapter":"black_frame_scan","error_code":"TIMEOUT","profile":profile}
      return [stable_issue("video.black_frame_scan_error",path,{},"critical",1,"提高工具超时或拆分诊断后重新逐帧审查",True,evidence=[detail],details=detail)],{"status":"ERROR","requirement":"REQUIRED","error_code":"TIMEOUT","profile":profile}
    for m in re.finditer(r"frame:(\d+)\s+pblack:([0-9.]+)\s+pts:\d+\s+t:([0-9.]+)",p.stderr):
      frame=int(m.group(1));pblack=float(m.group(2));time=float(m.group(3));evidence.append({"frame":frame,"time_seconds":time,"pblack":pblack})
    if p.returncode:
      detail={"source_adapter":"black_frame_scan","error_code":"FFMPEG_FAILED","returncode":p.returncode,"stderr_tail":p.stderr[-2000:],"profile":profile}
      return [stable_issue("video.black_frame_scan_error",path,{},"critical",1,"修复解码错误后重新逐帧审查，禁止无证据通过",True,evidence=[detail],details=detail)],{"status":"ERROR","requirement":"REQUIRED","error_code":"FFMPEG_FAILED","profile":profile}
    # Intentional black/strobe is trusted only after shot_recipe provenance has
    # matched the exact candidate and materialized AgentCut timeline.
    allowed=item.get("_intentional_effect_authorizations") if isinstance(item.get("_intentional_effect_authorizations"),list) else []
    for row in evidence:
      exemption=next((x for x in allowed if isinstance(x,dict) and x.get("effect") in {"black","strobe"} and x.get("provenance_status")=="PASS" and x.get("candidate_sha256")==sha256(path) and isinstance(x.get("start_frame"),int) and isinstance(x.get("end_frame"),int) and x["start_frame"]<=row["frame"]<=x["end_frame"] and str(x.get("reason") or "").strip() and str(x.get("approved_policy") or "").strip() and x.get("timeline_evidence_sha256")),None)
      if exemption:
        row["adjudication"]={"status":"ALLOWED_AGENTCUT_INTENTIONAL_EFFECT","reason":exemption["reason"],"approved_policy":exemption["approved_policy"],"recipe_id":exemption.get("recipe_id"),"clip_id":exemption.get("clip_id"),"timeline_evidence_sha256":exemption["timeline_evidence_sha256"],"rollback_allowed":True}
        continue
      details={**row,"profile":profile,"source_adapter":"black_frame_scan","non_story_required":True}
      issues.append(stable_issue("video.black_frame",path,{"frame":row["frame"],"start_seconds":row["time_seconds"],"end_seconds":min(dur,row["time_seconds"]+1/24)},"critical",.999,"替换或重导出该纯黑/近纯黑帧；若为剧情必要效果，须由 AgentCut shot_recipe 提供与当前成片及时间线匹配的精确帧、理由和批准策略",True,evidence=[{"type":"black_frame","frame":row["frame"],"time_seconds":row["time_seconds"],"pblack":row["pblack"]}],details=details))
    actionable=sum("adjudication" not in x for x in evidence);decoded_matches=re.findall(r"frame=\s*(\d+)",p.stderr);decoded_count=int(decoded_matches[-1]) if decoded_matches else None
    return issues,{"status":"FAIL" if actionable else "PASS","requirement":"REQUIRED","profile":profile,"decoded_duration_seconds":dur,"decoded_frame_count":decoded_count,"detected_black_frame_count":len(evidence),"actionable_black_frame_count":actionable,"frames":evidence,"command_exit_code":p.returncode}

  def _brightness_evidence(self,path,ref):
    profile={"version":"qingshan.brightness_jump_adjudication.v1","jump_threshold_luma":20.0,"minimum_confidence":.9,"raw_jump_preserved_required":True}
    if not isinstance(ref,str):
      detail={"source_adapter":"brightness_evidence","error_code":"EVIDENCE_MISSING","profile":profile}
      return [stable_issue("video.brightness_evidence_missing",path,{},"critical",1,"提供逐镜亮度测量；跳变裁定必须含证据文件、原因、confidence>=0.9 和 raw_jump_preserved=true",True,evidence=[detail],details=detail)],{"status":"FAIL","requirement":"REQUIRED","error_code":"EVIDENCE_MISSING","profile":profile}
    target=Path(ref).expanduser().resolve()
    try:data=json.loads(target.read_text())
    except Exception as exc:
      detail={"source_adapter":"brightness_evidence","error_code":"EVIDENCE_UNREADABLE","error":f"{type(exc).__name__}: {exc}","profile":profile}
      return [stable_issue("video.brightness_evidence_error",path,{},"critical",1,"修复亮度证据文件后重审",True,evidence=[detail],details=detail)],{"status":"ERROR","requirement":"REQUIRED","error_code":"EVIDENCE_UNREADABLE","profile":profile}
    threshold=float(data.get("jump_threshold_luma",profile["jump_threshold_luma"]));shots=sorted(data.get("shots",[]),key=lambda x:float(x.get("start",0)));adjudications=data.get("adjudications",data.get("brightness_jump_adjudications",[]));jumps=[];issues=[]
    for left,right in zip(shots,shots[1:]):
      if not isinstance(left.get("end_luma"),(int,float)) or not isinstance(right.get("start_luma"),(int,float)):continue
      raw=abs(float(right["start_luma"])-float(left["end_luma"]))
      if raw<threshold:continue
      boundary=float(right.get("start",left.get("end",0)));row={"left_shot_id":left.get("shot_id"),"right_shot_id":right.get("shot_id"),"boundary_seconds":boundary,"left_end_luma":left["end_luma"],"right_start_luma":right["start_luma"],"raw_jump_luma":round(raw,4)};candidate=next((x for x in adjudications if isinstance(x,dict) and (x.get("left_shot_id"),x.get("right_shot_id"))==(row["left_shot_id"],row["right_shot_id"])),None)
      evidence_file=(candidate or {}).get("evidence_file");evidence_target=(target.parent/str(evidence_file)).resolve() if evidence_file and not Path(str(evidence_file)).is_absolute() else Path(str(evidence_file)).expanduser() if evidence_file else None
      valid=bool(candidate and evidence_target and evidence_target.is_file() and str(candidate.get("reason","")).strip() and float(candidate.get("confidence",0))>=profile["minimum_confidence"] and candidate.get("raw_jump_preserved") is True)
      row["adjudication"]={"status":"PASS_WITH_ADJUDICATION" if valid else "FAIL_MISSING_OR_INVALID_ADJUDICATION","evidence_file":str(evidence_target) if evidence_target else None,"reason":(candidate or {}).get("reason"),"confidence":(candidate or {}).get("confidence"),"raw_jump_preserved":(candidate or {}).get("raw_jump_preserved")};jumps.append(row)
      if not valid:
       details={**row,"profile":profile,"source_adapter":"brightness_evidence"};issues.append(stable_issue("video.brightness_jump_unadjudicated",path,{"start_seconds":boundary,"end_seconds":boundary},"error",1,"补齐有效亮度跳变裁定证据；不得丢弃原始 jump 数值",True,evidence=[{"type":"brightness_audit","path":str(target),"raw_jump":row}],details=details))
    status="FAIL" if issues else "PASS_WITH_ADJUDICATION" if jumps else "PASS"
    return issues,{"status":"PASS" if status.startswith("PASS") else "FAIL","requirement":"REQUIRED","raw_status":status,"derived_status":"PASS_DERIVED" if status=="PASS" else status if status=="PASS_WITH_ADJUDICATION" else None,"source_adapter":"explicit_evidence","evidence":str(target),"profile":profile,"shot_count":len(shots),"raw_jump_count":len(jumps),"adjudicated_jump_count":sum(x["adjudication"]["status"]=="PASS_WITH_ADJUDICATION" for x in jumps),"raw_jumps":jumps}

  def _video_external(self,path,item,dur):
    out=[]; tool=self.root/"tools/frame_cadence_audit.py";inputs=item.get("evidence_inputs") or {};explicit=inputs.get("cadence_audit");action_required=self._action_required(item);clip_id=item.get("clip_id");candidate_sha=sha256(path)
    data=None;evidence_path=None
    if isinstance(explicit,str):
      try:data=json.loads(Path(explicit).expanduser().read_text());evidence_path=str(Path(explicit).expanduser().resolve())
      except Exception:data=None
    elif tool.is_file() and self.ffmpeg and item.get("use_existing_tools",True):
      with tempfile.TemporaryDirectory() as td:
        dest=Path(td)/"cadence.json"
        p=subprocess.run([os.environ.get("PYTHON","python3"),str(tool),"--video",str(path),"--out",str(dest),"--ffmpeg",self.ffmpeg,"--audit-scope","VIDEO_ONLY_DIAGNOSTIC"],capture_output=True,text=True,timeout=item.get("tool_timeout_seconds",300))
        if dest.is_file():data=json.loads(dest.read_text());evidence_path=str(tool)
    if isinstance(data,dict):
      for f in data.get("unmotivated_freezes",[]):
        st=float(f.get("start_seconds",0)); du=float(f.get("duration_seconds",0))
        out.append(stable_issue("video.freeze",path,{"start_seconds":st,"end_seconds":st+du,"start_frame":f.get("start_frame")},"critical",.98,"替换冻结区间；冻结门槛 0.5 秒不可豁免",True,evidence=[{"type":"frame_window","start_seconds":st,"end_seconds":st+du,"audit":evidence_path}],details={**f,"source_adapter":"frame_cadence_audit"}))
      for f in data.get("periodic_duplicates",{}).get("periodic_chains",[]):
        out.append(stable_issue("video.periodic_duplicate",path,{"start_seconds":f.get("start_seconds"),"end_seconds":f.get("end_seconds"),"start_frame":f.get("start_frame"),"end_frame":f.get("end_frame")},"critical",.98,"从原生帧率源重导出，禁止补帧伪修复",True,evidence=[{"type":"frame_cadence_audit","path":evidence_path}],details={**f,"source_adapter":"frame_cadence_audit"}))
      for f in data.get("black_frames",data.get("black",{}).get("frames",[])):
        if not isinstance(f,dict):continue
        st=float(f.get("start_seconds",0));en=float(f.get("end_seconds",st+float(f.get("duration_seconds",0))))
        out.append(stable_issue("video.black_frame",path,{"start_seconds":st,"end_seconds":en,"start_frame":f.get("start_frame")},"critical",.99,"替换非设计性黑帧并重新导出",True,evidence=[{"type":"frame_cadence_audit","path":evidence_path}],details={**f,"source_adapter":"frame_cadence_audit"}))
    periodic=(data or {}).get("periodic_duplicates",{});ratio=periodic.get("near_duplicate_ratio");fps=float((data or {}).get("output_fps") or 24);frames=[int(x) for x in periodic.get("near_duplicate_frames",[]) if isinstance(x,(int,float))];threshold=float(item.get("action_near_duplicate_ratio_max",ACTION_MOTION_PROFILE["near_duplicate_ratio_max"]));windows=[]
    if frames:
      cluster=[frames[0]]
      for frame in frames[1:]:
        if frame<=cluster[-1]+2:cluster.append(frame)
        else:windows.append(cluster);cluster=[frame]
      windows.append(cluster)
      windows=[{"start_frame":x[0],"end_frame":x[-1],"start_seconds":round(x[0]/fps,6),"end_seconds":round(min(dur,(x[-1]+1)/fps),6),"frame_count":len(x)} for x in windows]
    if action_required and isinstance(ratio,(int,float)) and float(ratio)>threshold:
      location={"start_seconds":windows[0]["start_seconds"] if windows else 0,"end_seconds":windows[-1]["end_seconds"] if windows else dur,"start_frame":windows[0]["start_frame"] if windows else 0,"end_frame":windows[-1]["end_frame"] if windows else None}
      details={"source_adapter":"frame_cadence_audit","policy_version":ACTION_MOTION_PROFILE["version"],"clip_id":clip_id,"candidate_sha256":candidate_sha,"action_required":True,"action_intensity":item.get("action_intensity",(item.get("metadata") or {}).get("action_intensity")),"near_duplicate_ratio":float(ratio),"threshold":threshold,"near_duplicate_frame_count":periodic.get("near_duplicate_frame_count",len(frames)),"output_fps":fps,"evidence_windows":windows}
      out.append(stable_issue("video.action_near_duplicate_ratio",path,location,"critical",.99,"按实体参考与完整动作轨迹重新生成该动作镜；禁止用单关键帧慢速漂移或补帧掩盖",True,evidence=[{"type":"frame_cadence_audit","path":evidence_path,"near_duplicate_ratio":float(ratio),"threshold":threshold,"windows":windows}],details=details))
    physics_ref=inputs.get("action_physics");physics_cap=None
    if action_required:
      if not isinstance(physics_ref,str):physics_cap={"status":"CAPABILITY_FAIL","requirement":"REQUIRED","error_code":"ACTION_PHYSICS_EVIDENCE_MISSING","policy_version":ACTION_MOTION_PROFILE["version"],"clip_id":clip_id,"candidate_sha256":candidate_sha,"required_checks":ACTION_MOTION_PROFILE["required_physics_checks"]}
      else:
        try:
          target=Path(physics_ref).expanduser().resolve();physics=json.loads(target.read_text());actual_sha=str(physics.get("candidate_sha256") or physics.get("source_sha256") or "");checks=physics.get("checks") if isinstance(physics.get("checks"),dict) else {};required=ACTION_MOTION_PROFILE["required_physics_checks"]
          if actual_sha!=candidate_sha:raise ValueError(f"candidate_sha256 mismatch: {actual_sha} != {candidate_sha}")
          missing=[x for x in required if x not in checks];failures=[]
          for name in required:
            row=checks.get(name);status=str(row.get("status") if isinstance(row,dict) else row or "MISSING").upper()
            if status in {"PASS","PASS_WITH_ADJUDICATION"}:continue
            row=row if isinstance(row,dict) else {"status":status};failures.append(name);span=row.get("location") if isinstance(row.get("location"),dict) else {};location={"start_seconds":float(span.get("start_seconds",0)),"end_seconds":float(span.get("end_seconds",dur)),"start_frame":span.get("start_frame"),"end_frame":span.get("end_frame")};confidence=float(row.get("confidence",physics.get("confidence",.9)))
            out.append(stable_issue(f"video.action_physics.{name}",path,location,"critical",confidence,f"重做动作轨迹并修复 {name}：必须呈现起势、接触、发力传递和可见结果，禁止悬空手或物体漂移",True,evidence=[{"type":"action_physics_audit","path":str(target),"check":name,"location":location,"description":row.get("evidence")}],region=row.get("region"),details={"source_adapter":"action_physics_audit","policy_version":ACTION_MOTION_PROFILE["version"],"clip_id":clip_id,"candidate_sha256":candidate_sha,"check":name,"status":status,"confidence":confidence}))
          physics_cap={"status":"FAIL" if failures else "CAPABILITY_FAIL" if missing else "PASS","requirement":"REQUIRED","source_adapter":"action_physics_audit","evidence":str(target),"evidence_sha256":sha256(target),"policy_version":ACTION_MOTION_PROFILE["version"],"clip_id":clip_id,"candidate_sha256":candidate_sha,"checks":checks,"missing_checks":missing,"failed_checks":failures,"confidence":physics.get("confidence")}
        except Exception as exc:physics_cap={"status":"ERROR","requirement":"REQUIRED","error_code":"ACTION_PHYSICS_EVIDENCE_INVALID","error":f"{type(exc).__name__}: {exc}","policy_version":ACTION_MOTION_PROFILE["version"],"clip_id":clip_id,"candidate_sha256":candidate_sha,"evidence":str(physics_ref)}
    video_cap={"status":"FAIL" if any(x["blocking"] for x in out if str(x.get("rule_id","")).startswith(("video.freeze","video.periodic_duplicate","video.black_frame","video.action_near_duplicate_ratio"))) else "PASS","adapter":"frame_cadence_audit.py" if tool.is_file() else "builtin","policy_version":ACTION_MOTION_PROFILE["version"],"clip_id":clip_id,"candidate_sha256":candidate_sha,"action_required":action_required,"action_intensity":item.get("action_intensity",(item.get("metadata") or {}).get("action_intensity")),"near_duplicate_ratio":ratio,"action_near_duplicate_ratio_threshold":threshold if action_required else None,"near_duplicate_evidence_windows":windows,"cadence_evidence":evidence_path}
    return out,video_cap,physics_cap

  def _image(self,path,item,info):
    out=[]; caps={};metadata=item.get("metadata") or {};episode=str(metadata.get("episode") or "").upper();sheet_kind=str(metadata.get("sheet_kind") or "");inputs=dict(item.get("evidence_inputs") or {})
    if not inputs.get("image_visual"):
      found=self._auto_image_evidence(path,"qingshan.image_visual_adjudication.v1")
      if found:inputs["image_visual"]=str(found)
    if not inputs.get("storyboard_visual"):
      found=self._auto_image_evidence(path,"qingshan.storyboard_sheet_ai_visual_adjudication.v1")
      if found:inputs["storyboard_visual"]=str(found)
    if not inputs.get("ocr"):
      found=self._auto_image_evidence(path,"qingshan.still_image_ocr_audit.v1") or self._auto_image_evidence(path,"qingshan.runtime_still_ocr.v1")
      if found:inputs["ocr"]=str(found)
    # Generic keyframe evidence is separate from the six-column storyboard-sheet
    # contract. It must bind to the exact candidate SHA and declare every required
    # semantic check so a nearby PASS cannot authorize this image.
    keyframe_ref=inputs.get("image_visual")
    if isinstance(keyframe_ref,str):
      target=Path(keyframe_ref).expanduser();visual=None;matched=None
      try:visual=json.loads(target.read_text())
      except Exception:visual=None
      if isinstance(visual,dict) and visual.get("schema")=="qingshan.image_visual_adjudication.v1" and str(visual.get("episode","")).upper()==episode:
        for row in visual.get("evidence",[]):
          if row.get("sha256")==sha256(path):matched=row;break
      if matched:
        checks=matched.get("checks") if isinstance(matched.get("checks"),dict) else {}
        required=set(matched.get("required_checks") or visual.get("required_checks") or (
          "canonical_identity_continuity","scene_authority","story_action_clarity",
          "no_text_or_pseudotext","no_extra_or_duplicated_bodies","native_anatomy"
        ))
        failures=[]
        for name,value in checks.items():
          if str(value).upper() in {"PASS","PASS_WITH_ADJUDICATION"}:continue
          failure={"check":name,"status":value,"source_id":matched.get("source_id")};failures.append(failure)
          out.append(stable_issue(f"image.keyframe.{name}",path,{"frame":0},"error",float(visual.get("confidence",.9)),f"修复关键帧检查项 {name} 后仅重生成该镜头",True,evidence=[{"type":"image_visual_adjudication","path":str(target.resolve()),"check":name}],details={**failure,"source_adapter":"production_image_visual_adjudication","rule_version":RULE_VERSION}))
        missing=sorted(required-set(checks))
        for name in missing:
          failure={"check":name,"status":"MISSING","source_id":matched.get("source_id")};failures.append(failure)
          out.append(stable_issue(f"image.keyframe.{name}.missing",path,{"frame":0},"warning",1,f"补齐 {name} 的全分辨率视觉裁定证据",False,evidence=[{"type":"image_visual_adjudication","path":str(target.resolve())}],details={**failure,"source_adapter":"production_image_visual_adjudication"}))
        status="FAIL" if any(x["blocking"] for x in out) else "CAPABILITY_FAIL" if missing else "PASS"
        detail={"status":status,"raw_status":visual.get("status"),"source_adapter":"production_image_visual_adjudication","evidence":str(target.resolve()),"evidence_sha256":sha256(target),"candidate_sha256":matched.get("sha256"),"confidence":visual.get("confidence"),"source_id":matched.get("source_id"),"checks":checks,"required_checks":sorted(required),"missing_checks":missing,"failures":failures,"rollback":visual.get("rollback")}
        caps["image_analysis"]=detail
        caps["composition"]={**detail,"status":"PASS" if checks.get("composition") in {None,"PASS","PASS_WITH_ADJUDICATION"} else status}
        caps["visual_continuity"]={**detail,"status":"PASS" if checks.get("canonical_identity_continuity")=="PASS" else status}
        if checks.get("no_text_or_pseudotext")=="PASS":caps["ocr"]={"status":"PASS","raw_status":"PASS_WITH_ADJUDICATION","source_adapter":"production_image_visual_adjudication","evidence":str(target.resolve()),"candidate_sha256":matched.get("sha256"),"review_scope":"FULL_RESOLUTION_KEYFRAME","check":"no_text_or_pseudotext","confidence":visual.get("confidence")}
      else:
        caps["image_analysis"]={"status":"CAPABILITY_FAIL","error_code":"ADAPTER_OR_MATCHED_EVIDENCE_UNAVAILABLE","source_adapter":"image_visual_adjudication","searched":[str(target)],"candidate_sha256":sha256(path),"source_id":metadata.get("source_id") or metadata.get("beat_id")}
    # Reuse the production full-resolution multimodal adjudication. Bind it to the
    # exact candidate SHA; a nearby episode PASS can never authorize another file.
    visual_ref=inputs.get("storyboard_visual")
    candidates=[Path(visual_ref).expanduser()] if isinstance(visual_ref,str) else []
    visual=None;visual_path=None;matched=None
    for candidate in candidates:
      try:data=json.loads(candidate.read_text())
      except Exception:continue
      if data.get("schema")!="qingshan.storyboard_sheet_ai_visual_adjudication.v1" or str(data.get("episode","")).upper()!=episode:continue
      for row in data.get("evidence",[]):
        if row.get("sheet_kind")==sheet_kind and row.get("sha256")==sha256(path):visual=data;visual_path=candidate.resolve();matched=row;break
      if matched:break
    if matched and "image_analysis" not in caps:
      checks=matched.get("checks") if isinstance(matched.get("checks"),dict) else {};failures=[]
      for name,value in checks.items():
        if str(value).upper() in {"PASS","PASS_WITH_ADJUDICATION"}:continue
        failure={"check":name,"status":value,"sheet_kind":sheet_kind};failures.append(failure);region=matched.get("regions",{}).get(name) if isinstance(matched.get("regions"),dict) else None
        out.append(stable_issue(f"image.storyboard.{name}",path,{"frame":0},"error",float(visual.get("confidence",.9)),f"修复分镜表检查项 {name} 后仅重生成该 sheet",True,evidence=[{"type":"storyboard_visual_adjudication","path":str(visual_path),"check":name}],region=region,details={**failure,"source_adapter":"production_storyboard_visual_adjudication","rule_version":RULE_VERSION}))
      required={"six_column_layout","six_visual_rows","intentional_composition_difference","identity_and_location_continuity","no_text_inside_visual_panels"}
      if sheet_kind=="fight_sheet":required|={"setup_impact_tableau","close_to_wide_scale_jump","environmental_power_visualization"}
      missing=sorted(required-set(checks));
      for name in missing:
        failure={"check":name,"status":"MISSING","sheet_kind":sheet_kind};failures.append(failure)
        out.append(stable_issue(f"image.storyboard.{name}.missing",path,{"frame":0},"warning",1,f"补齐 {name} 的全分辨率视觉裁定证据",False,evidence=[{"type":"storyboard_visual_adjudication","path":str(visual_path)}],details={**failure,"source_adapter":"production_storyboard_visual_adjudication"}))
      status="FAIL" if any(x["blocking"] for x in out) else "CAPABILITY_FAIL" if missing else "PASS"
      detail={"status":status,"raw_status":visual.get("status"),"source_adapter":"production_storyboard_visual_adjudication","evidence":str(visual_path),"evidence_sha256":sha256(visual_path),"candidate_sha256":matched.get("sha256"),"confidence":visual.get("confidence"),"sheet_kind":sheet_kind,"row_count":matched.get("row_count"),"composition_sequence":matched.get("composition_sequence"),"checks":checks,"required_checks":sorted(required),"missing_checks":missing,"failures":failures,"rollback":visual.get("rollback")}
      caps.update({"image_analysis":detail,"composition":{**detail,"status":"PASS" if not any(x.get("check") in {"six_column_layout","six_visual_rows","intentional_composition_difference","setup_impact_tableau","close_to_wide_scale_jump","environmental_power_visualization"} for x in failures) else status},"visual_continuity":{**detail,"status":"PASS" if checks.get("identity_and_location_continuity")=="PASS" else status}})
      if checks.get("no_text_inside_visual_panels")=="PASS":caps["ocr"]={"status":"PASS","raw_status":"PASS_WITH_ADJUDICATION","source_adapter":"production_storyboard_visual_adjudication","evidence":str(visual_path),"candidate_sha256":matched.get("sha256"),"review_scope":"VISUAL_PANELS_ONLY","check":"no_text_inside_visual_panels","confidence":visual.get("confidence")}
    elif "image_analysis" not in caps:
      live,live_error=self._run_image_visual_adapter(path,item)
      if live:
        matched=next(x for x in live["evidence"] if x.get("sha256")==sha256(path));checks=matched.get("checks") if isinstance(matched.get("checks"),dict) else {};required=set(matched.get("required_checks") or live.get("required_checks") or ("canonical_identity_continuity","scene_authority","story_action_clarity","no_text_or_pseudotext","no_extra_or_duplicated_bodies","native_anatomy"));missing=sorted(required-set(checks));failures=[]
        for name,value in checks.items():
          if str(value).upper() in {"PASS","PASS_WITH_ADJUDICATION"}:continue
          failures.append({"check":name,"status":value});out.append(stable_issue(f"image.keyframe.{name}",path,{"frame":0},"error",float(live.get("confidence",.9)),f"修复关键帧检查项 {name} 后仅重生成该镜头",True,evidence=[{"type":"runtime_image_visual","candidate_sha256":sha256(path),"check":name}],region=(matched.get("regions") or {}).get(name),details={"source_adapter":"runtime_image_visual","check":name,"status":value,"rule_version":RULE_VERSION}))
        status="FAIL" if failures else "CAPABILITY_FAIL" if missing else "PASS";detail={"status":status,"source_adapter":"runtime_image_visual","adapter_contract":"qingshan.image_visual_runtime.v1","candidate_sha256":sha256(path),"confidence":live.get("confidence"),"checks":checks,"required_checks":sorted(required),"missing_checks":missing,"failures":failures,"rollback":live.get("rollback")};caps["image_analysis"]=detail;caps["composition"]={**detail};caps["visual_continuity"]={**detail,"status":"PASS" if checks.get("canonical_identity_continuity")=="PASS" else status}
        if checks.get("no_text_or_pseudotext")=="PASS":caps["ocr"]={"status":"PASS","raw_status":"PASS_WITH_ADJUDICATION","source_adapter":"runtime_image_visual","candidate_sha256":sha256(path),"review_scope":"FULL_RESOLUTION_KEYFRAME","confidence":live.get("confidence")}
      else:caps["image_analysis"]={**live_error,"source_adapter":"runtime_image_visual","searched":[str(x) for x in candidates],"sheet_kind":sheet_kind}
    # Existing OCR adapter is opt-in because production scripts have heterogeneous CLIs.
    if item.get("ocr_result"):
      for hit in item["ocr_result"].get("hits",[]):
        out.append(stable_issue("image.text_or_watermark",path,{"frame":0},"error",float(hit.get("confidence",.8)),"裁切、重绘或替换含文字/水印素材",True,region=hit.get("region"),details=hit))
      caps["ocr"]={"status":"FAIL" if out else "PASS","evidence":"inline:ocr_result"}
    elif "ocr" not in caps and isinstance(inputs.get("ocr"),str):
      ocr_ref=Path(inputs["ocr"]).expanduser()
      try:
        ocr_data=json.loads(ocr_ref.read_text());raw=str(ocr_data.get("status","")).upper();sources=[str(Path(x).expanduser().resolve()) for x in ocr_data.get("source_images",[]) if isinstance(x,str)];current=str(path.resolve())
        if sources and current not in sources:raise ValueError("OCR evidence does not contain current candidate path")
        all_hits=ocr_data.get("recognitions",[]);hits=[x for x in all_hits if not x.get("file") or str(Path(x["file"]).expanduser().resolve())==current]
        # Batch audit top-level counters belong to all source images. Reassess
        # this exact SHA/path using the normalized OCR policy, so a low-confidence
        # isolated glyph in one sibling cannot fail every candidate.
        actionable=[x for x in hits if x.get("forbidden") is True or float(x.get("confidence",0))>=OCR_PROFILE["single_hit_confidence"]]
        failures=len(actionable);status="FAIL" if failures else "PASS"
        caps["ocr"]={"status":status,"raw_status":raw,"derived_status":"PASS_NORMALIZED_EXACT_CANDIDATE" if status=="PASS" and raw=="FAIL" else status,"source_adapter":"still_image_ocr_audit","evidence":str(ocr_ref.resolve()),"candidate_sha256":sha256(path),"critical_text_failures":failures,"recognition_count":len(hits),"ignored_low_confidence_count":len(hits)-len(actionable),"normalization_profile":OCR_PROFILE}
        for hit in actionable:out.append(stable_issue("image.text_or_watermark",path,{"frame":0},"error",float(hit.get("confidence",.99)),"裁切、重绘或替换含文字/水印素材",True,evidence=[{"type":"still_image_ocr_audit","path":str(ocr_ref.resolve()),"text":hit.get("text"),"confidence":hit.get("confidence")}],region=hit.get("region"),details={**hit,"raw_status":raw,"source_adapter":"still_image_ocr_audit","normalization_profile":OCR_PROFILE}))
      except Exception as exc:caps["ocr"]={"status":"ERROR","evidence":str(ocr_ref),"error":f"{type(exc).__name__}: {exc}"}
    elif "ocr" not in caps:
      ocr_data,ocr_error=self._run_still_ocr(path,item)
      if ocr_data:
        hits=ocr_data.get("recognitions",[]);status=ocr_data["status"];caps["ocr"]={"status":status,"raw_status":status,"source_adapter":"runtime_still_ocr","engine":ocr_data.get("engine"),"candidate_sha256":ocr_data.get("candidate_sha256"),"confidence_threshold":ocr_data.get("confidence_threshold"),"recognition_count":len(hits),"review_scope":"FULL_RESOLUTION_KEYFRAME"}
        for hit in hits:out.append(stable_issue("image.text_or_watermark",path,{"frame":0},"error",float(hit.get("confidence",.8)),"移除画面内可读文字/水印后重新审查",True,evidence=[{"type":"runtime_still_ocr","text":hit.get("text"),"confidence":hit.get("confidence"),"region":hit.get("region")}],region=hit.get("region"),details={**hit,"source_adapter":"runtime_still_ocr","rule_version":RULE_VERSION}))
      else:caps["ocr"]={**ocr_error,"source_adapter":"runtime_still_ocr","review_scope":"FULL_RESOLUTION_KEYFRAME"}
    return out,caps

  def _regressions(self,path,item):
    if not self.registry or not self.registry.is_file(): return []
    out=[]
    for line in self.registry.read_text(errors="replace").splitlines():
      try:r=json.loads(line)
      except:continue
      if not r.get("active",True):continue
      match=r.get("match",{}); token=match.get("path_contains")
      if token and token in str(path): out.append(stable_issue("regression."+r.get("rule_id","unknown"),path,{},r.get("severity","error"),1,r.get("recommendation","按回归规则修复"),r.get("blocking",True),details={"registry_rule":r}))
    return out

  def review_many(self,items,progress:Callable|None=None):
    results=[None]*len(items)
    with ThreadPoolExecutor(max_workers=self.workers,thread_name_prefix="qingshan-review") as pool:
      fs={pool.submit(self.review,x):i for i,x in enumerate(items)}
      for n,f in enumerate(as_completed(fs),1):
        results[fs[f]]=f.result()
        if progress: progress({"phase":"review","completed":n,"total":len(items),"progress":n/max(1,len(items))})
    return results

  def review_many_report(self,items,progress:Callable|None=None):
    reports=self.review_many(items,progress);failed=[];passed=[]
    for index,(request,report) in enumerate(zip(items,reports)):
      row={"index":index,"path":request.get("path"),"review_id":report.get("review_id"),"status":report.get("status")}
      (passed if report.get("status") in {"PASS","WARN"} else failed).append(row)
    capability_failed=[x for x in failed if x["status"]=="CAPABILITY_FAIL"];content_failed=[x for x in failed if x["status"]!="CAPABILITY_FAIL"]
    status="CONTENT_FAIL" if content_failed else "CAPABILITY_FAIL" if capability_failed else "PASS"
    return {"schema":"qingshan.review_many.result.v2","status":status,"content_status":status,"items":reports,"summary":{"total":len(reports),"passed":len(passed),"failed":len(failed),"capability_failed":len(capability_failed),"content_failed":len(content_failed),"workers":self.workers},"passed_items":passed,"failed_items":failed,"capability_failed_items":capability_failed,"content_failed_items":content_failed,"retry_items":[{"index":row["index"],"item":items[row["index"]],"source_review_id":row["review_id"]} for row in failed],"retry_policy":"FAILED_ITEMS_ONLY"}

  def append_ledger(self,event):
    self.ledger.parent.mkdir(parents=True,exist_ok=True)
    with self.ledger.open("a",encoding="utf-8") as f: f.write(json.dumps({"schema":"qingshan.issue_ledger.event.v1","at":now(),**event},ensure_ascii=False)+"\n")

  def promote(self,issue,rule_id):
    if not self.registry: raise ValueError("registry path is not configured")
    self.registry.parent.mkdir(parents=True,exist_ok=True)
    row={"schema":"qingshan.anti_recurrence.rule.v1","rule_id":rule_id,"source_issue_id":issue["issue_id"],"active":True,"created_at":now(),"match":{"path_contains":Path(issue["media_path"]).name},"severity":issue["severity"],"blocking":issue["blocking"],"recommendation":issue["recommendation"]}
    with self.registry.open("a",encoding="utf-8") as f:f.write(json.dumps(row,ensure_ascii=False)+"\n")
    return row

def repair_task(report, include_warnings: bool|None=None):
    if not isinstance(report,dict): raise ValueError("repair-task input must be a report object or {items:[reports]}")
    if "items" in report:
      items=report.get("items")
      if not isinstance(items,list) or not items: raise ValueError("repair-task wrapper.items must be a non-empty array")
      if len(items)==1:return repair_task(items[0],include_warnings)
      tasks=[repair_task(item,include_warnings) for item in items]
      return {"schema":"qingshan.agentcut.repair_task_batch.v1","source_review_count":len(items),"publish_allowed":False,"delete_allowed":False,"irreversible_action_allowed":False,"tasks":tasks}
    if not isinstance(report.get("review_id"),str) or not report.get("review_id"): raise ValueError("repair-task report.review_id must be a non-empty string")
    if not isinstance(report.get("issues"),list): raise ValueError("repair-task report.issues must be an array")
    metadata=report.get("agentcut",{}).get("metadata",{}); is_not_final="NOT_FINAL" in str(metadata.get("status","")).upper() or bool(metadata.get("read_only_demo"))
    if include_warnings is None: include_warnings=is_not_final
    clip_id=report.get("agentcut",{}).get("clip_id")
    repairs=[]
    for x in report["issues"]:
      if not isinstance(x,dict) or not isinstance(x.get("issue_id"),str): raise ValueError("repair-task issue must be an object with issue_id")
      if not x["blocking"] and not (include_warnings and x.get("severity") in {"warning","error","critical"}): continue
      loc=x.get("location",{}); start=loc.get("start_seconds"); end=loc.get("end_seconds"); matched=None
      if str(x.get("rule_id","")).startswith("shot_recipe."):
       candidates=[]
       for row in report.get("agentcut",{}).get("clips",[]):
        span=row.get("timeline_range") or {};a=span.get("start_seconds");b=span.get("end_seconds")
        if a is None or b is None or start is None:continue
        issue_end=float(end if isinstance(end,(int,float)) else start);overlaps=float(a)<=issue_end and float(b)>=float(start)
        if overlaps:candidates.append(row)
       if not candidates:
        candidates=[{"clip_id":x.get("clip_id") or x.get("details",{}).get("clip_id") or clip_id,"metadata":{}}]
       for row in candidates:
        mapped_clip=row.get("clip_id") or clip_id
        repair_seed=json.dumps([report["review_id"],x["issue_id"],x.get("recipe_id"),x.get("recipe_phase"),mapped_clip],sort_keys=True)
        repairs.append({"repair_id":"QRT-"+hashlib.sha256(repair_seed.encode()).hexdigest()[:16].upper(),"issue_id":x["issue_id"],"rule_id":x.get("rule_id"),"media_path":x["media_path"],"clip_id":mapped_clip,"intersecting_clip_ids":[candidate.get("clip_id") for candidate in candidates if candidate.get("clip_id")],"clip_metadata":row.get("metadata",{}),"recipe_id":x.get("recipe_id") or x.get("details",{}).get("recipe_id"),"recipe_phase":x.get("recipe_phase") or x.get("details",{}).get("recipe_phase"),"planned_value":x.get("planned_value",x.get("details",{}).get("planned_value")),"measured_value":x.get("measured_value",x.get("details",{}).get("measured_value")),"delta":x.get("delta",x.get("details",{}).get("delta")),"time_range":{"start_seconds":start,"end_seconds":end},"location":loc,"region":x.get("region"),"severity":x.get("severity"),"blocking":x.get("blocking"),"recommendation":x.get("recommendation"),"rollback":x.get("rollback") or x.get("details",{}).get("rollback") or {"allowed":True,"restore":"pre_repair_timeline"},"action":"REPAIR_AGENTCUT_RECIPE_PHASE","publish_allowed":False})
       continue
      if x.get("rule_id")=="video.too_many_long_shots" and x.get("details",{}).get("long_shots"):
       for shot in x["details"]["long_shots"]:
        shot_start=float(shot["start_seconds"]);shot_end=float(shot["end_seconds"]); candidates=[]
        for row in report.get("agentcut",{}).get("clips",[]):
         span=row.get("timeline_range") or {};a=span.get("start_seconds");b=span.get("end_seconds")
         if a is not None and b is not None and float(a)<shot_end and float(b)>shot_start:candidates.append(row)
        video_candidates=[row for row in candidates if row.get("kind")=="video"]; candidates=video_candidates or candidates or [None]
        for row in candidates:
         mapped_clip=(row or {}).get("clip_id") or clip_id; repair_seed=json.dumps([x["issue_id"],shot.get("shot_index"),mapped_clip],sort_keys=True)
         repairs.append({"repair_id":"QRT-"+hashlib.sha256(repair_seed.encode()).hexdigest()[:16].upper(),"issue_id":x["issue_id"],"rule_id":x["rule_id"],"aggregate_rule_id":x["rule_id"],"media_path":x["media_path"],"clip_id":mapped_clip,"clip_metadata":(row or {}).get("metadata",{}),"time_range":{"start_seconds":shot_start,"end_seconds":shot_end},"location":{"shot_index":shot["shot_index"],"start_seconds":shot_start,"end_seconds":shot_end},"shot_details":shot,"region":x["region"],"severity":x["severity"],"blocking":x["blocking"],"recommendation":x["recommendation"]})
       continue
      if start is not None:
       candidates=[]
       for row in report.get("agentcut",{}).get("clips",[]):
        span=row.get("timeline_range") or {}; a=span.get("start_seconds");b=span.get("end_seconds")
        if a is not None and b is not None and float(a)<=float(start)<float(b): candidates.append(row)
       if candidates: matched=sorted(candidates,key=lambda r:0 if r.get("kind")=="video" else 1)[0]
      mapped_clip=x.get("details",{}).get("clip_id") or (matched or {}).get("clip_id") or clip_id;repair_seed=json.dumps([report["review_id"],x["issue_id"],mapped_clip],sort_keys=True)
      repairs.append({"repair_id":"QRT-"+hashlib.sha256(repair_seed.encode()).hexdigest()[:16].upper(),"issue_id":x["issue_id"],"rule_id":x.get("rule_id"),"media_path":x["media_path"],"clip_id":mapped_clip,"clip_metadata":(matched or {}).get("metadata",{}),"time_range":{"start_seconds":start,"end_seconds":end},"location":x["location"],"region":x["region"],"severity":x["severity"],"blocking":x["blocking"],"recommendation":x["recommendation"]})
    return {"schema":"qingshan.agentcut.repair_task.v2","source_review_id":report["review_id"],"publish_allowed":False,"delete_allowed":False,"irreversible_action_allowed":False,"include_warnings":include_warnings,"clip_id":clip_id,"metadata":metadata,"repairs":repairs}

def timeout_decision(original: dict[str,Any], elapsed_seconds: float, *, protected_reason: str|None=None) -> dict[str,Any]:
    protected={"verification_code","login","permission","payment","copyright","risk_control","irreversible_publish","irreversible_replace","irreversible_delete"}
    if protected_reason in protected: state="HUMAN_REQUIRED_PROTECTED"; machine=None
    elif elapsed_seconds < 900: state="HUMAN_PENDING"; machine=None
    else: state="MACHINE_DECIDED"; machine="REJECT" if original.get("status")=="FAIL" else "ACCEPT_WITH_WARNINGS" if original.get("status")=="WARN" else "ACCEPT"
    return {"schema":"qingshan.review.timeout_decision.v1","created_at":now(),"timeout_seconds":900,"elapsed_seconds":elapsed_seconds,"state":state,"machine_decision":machine,"protected_reason":protected_reason,"original_result":original,"evidence_preserved":True,"confidence_preserved":True,"rollback":{"allowed":True,"history":[],"restore":"original_result"}}

def human_report(report: dict[str,Any]) -> str:
    scoring=report.get("scoring",{}); score_text=f"；评分 {scoring.get('score','?')}/5，通过线 {scoring.get('pass_score','?')}（{scoring.get('importance','standard')}）" if scoring else ""
    summary=report["summary"]; count_text=f"原始 {summary.get('raw_issue_count',summary['issue_count'])}，去重 {summary.get('deduped_issue_count',summary['issue_count'])}"
    lines=[f"审片结果：{report['status']}（阻塞 {summary['blocking_count']}，{count_text}{score_text}）",f"媒体：{report['media_path']}"]
    if report.get("story_duration"):
      d=report["story_duration"];lines.append(f"故事时长：计划 {d.get('planned_duration_seconds')}s，实际 {d.get('actual_duration_seconds')}s，偏差 {d.get('delta_seconds')}s，策略 {d.get('policy_version')}，结果 {d.get('status')}")
    if report.get("deduction_cap"): lines.append("扣分上限："+json.dumps(report["deduction_cap"],ensure_ascii=False,sort_keys=True))
    if report.get("capabilities"):
      lines.append("能力："+"；".join(f"{name}={cap.get('status')}({cap.get('requirement','?')})" for name,cap in sorted(report["capabilities"].items())))
    for x in report["issues"][:20]:
        loc=x.get("location") or {}; lines.append(f"- [{x['severity']}] {x['rule_id']} @ {loc.get('start_seconds','?')}s：{x['recommendation']}")
    return "\n".join(lines)+"\n"
