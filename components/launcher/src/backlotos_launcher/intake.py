from __future__ import annotations

import hashlib
import html
import ipaddress
import mimetypes
import re
import socket
import time
import threading
import unicodedata
import concurrent.futures as futures
import urllib.parse
import urllib.request
import urllib.robotparser
import urllib.error
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from .models import IntakeError

MAX_SOURCE_BYTES = 100 * 1024 * 1024
MAX_CHAPTER_PAGES = 2000
CHAPTER_REQUEST_INTERVAL_SECONDS = 0.30
USER_AGENT = "BacklotOS/0.2 (+local novel intake)"
SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".html", ".htm", ".pdf", ".epub", ".docx"}


@dataclass(frozen=True)
class ImportedSource:
    title: str
    source_name: str
    source_uri: str | None
    media_type: str
    suffix: str
    raw_bytes: bytes
    text: str
    raw_sha256: str
    text_sha256: str
    pages: tuple[dict, ...] = ()
    crawl: dict | None = None


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._ignored = 0
        self._title = False
        self.links: list[tuple[str, str]] = []
        self._link_href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}:
            self._ignored += 1
        if tag == "title":
            self._title = True
        if tag == "a":
            self._link_href = next((value for key, value in attrs if key.lower() == "href"), None)
            self._link_text = []
        if not self._ignored and tag in {"p", "br", "div", "article", "section", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._title = False
        if tag == "a" and self._link_href:
            self.links.append((self._link_href, _clean_inline(" ".join(self._link_text))))
            self._link_href = None
            self._link_text = []
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"} and self._ignored:
            self._ignored -= 1
        if not self._ignored and tag in {"p", "div", "article", "section", "h1", "h2", "h3", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._title:
            self.title_parts.append(data)
        if self._link_href is not None:
            self._link_text.append(data)
        if not self._ignored:
            self.parts.append(data)

    @property
    def title(self) -> str:
        return _clean_inline(" ".join(self.title_parts))

    @property
    def text(self) -> str:
        return _normalize_text("".join(self.parts))


class _MainContentExtractor(HTMLParser):
    TARGETS = ("htmlContent", "chaptercontent", "chapter-content", "read-content", "content")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.buffers = {name: [] for name in self.TARGETS}
        self.active: list[dict] = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        for item in self.active:
            item["depth"] += 1
        attrs_dict = dict(attrs)
        element_id = attrs_dict.get("id")
        if element_id in self.buffers and not any(item["target"] == element_id for item in self.active):
            self.active.append({"target": element_id, "depth": 1})
        if self.active and tag.lower() in {"script", "style", "noscript", "svg"}:
            self.ignored += 1
        if self.active and not self.ignored and tag.lower() in {"p", "br", "div", "h1", "h2", "h3", "li"}:
            for item in self.active:
                self.buffers[item["target"]].append("\n")

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.ignored:
            self.ignored -= 1
        for item in self.active:
            item["depth"] -= 1
        self.active = [item for item in self.active if item["depth"] > 0]

    def handle_data(self, data):
        if self.active and not self.ignored:
            for item in self.active:
                self.buffers[item["target"]].append(data)

    @property
    def text(self) -> str:
        for target in self.TARGETS:
            value = _normalize_text("".join(self.buffers[target]))
            if len(value) >= 20:
                return value
        return ""


def _clean_inline(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IntakeError("text encoding is not supported")


def _extract_docx(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise IntakeError("DOCX file is damaged or incomplete") from exc
    root = ElementTree.fromstring(xml)
    paragraphs = []
    for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        text = "".join(node.text or "" for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
        if text.strip():
            paragraphs.append(text)
    return _normalize_text("\n\n".join(paragraphs))


def _extract_epub(raw: bytes) -> str:
    try:
        archive = zipfile.ZipFile(BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise IntakeError("EPUB file is damaged") from exc
    sections: list[str] = []
    with archive:
        names = sorted(name for name in archive.namelist() if name.lower().endswith((".xhtml", ".html", ".htm")))
        for name in names:
            parser = _TextExtractor()
            parser.feed(_decode_text(archive.read(name)))
            if parser.text:
                sections.append(parser.text)
    return _normalize_text("\n\n".join(sections))


def _extract_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IntakeError("PDF support is unavailable; reinstall BacklotOS") from exc
    try:
        reader = PdfReader(BytesIO(raw))
        return _normalize_text("\n\n".join(page.extract_text() or "" for page in reader.pages))
    except Exception as exc:
        raise IntakeError("PDF cannot be decoded; scanned PDFs need OCR before import") from exc


def extract_source(raw: bytes, source_name: str, source_uri: str | None = None, media_type: str = "") -> ImportedSource:
    if not raw:
        raise IntakeError("source is empty")
    if len(raw) > MAX_SOURCE_BYTES:
        raise IntakeError("source exceeds the 100 MB intake limit")
    suffix = Path(urllib.parse.urlparse(source_name).path).suffix.lower()
    guessed = mimetypes.guess_type(source_name)[0] or "application/octet-stream"
    media_type = media_type.split(";", 1)[0].strip().lower() or guessed
    title = Path(urllib.parse.urlparse(source_name).path).stem or "untitled-story"

    if suffix in {".html", ".htm"} or media_type == "text/html":
        parser = _TextExtractor()
        decoded = _decode_text(raw)
        parser.feed(decoded)
        main = _MainContentExtractor()
        main.feed(decoded)
        text = main.text or parser.text
        title = parser.title or title
        suffix = suffix if suffix in {".html", ".htm"} else ".html"
    elif suffix in {".txt", ".md", ".markdown"} or media_type.startswith("text/"):
        text = _normalize_text(_decode_text(raw))
        suffix = suffix or ".txt"
    elif suffix == ".pdf" or media_type == "application/pdf":
        text = _extract_pdf(raw)
        suffix = ".pdf"
    elif suffix == ".docx" or "wordprocessingml" in media_type:
        text = _extract_docx(raw)
        suffix = ".docx"
    elif suffix == ".epub" or media_type == "application/epub+zip":
        text = _extract_epub(raw)
        suffix = ".epub"
    else:
        raise IntakeError("supported formats: TXT, Markdown, HTML, PDF, EPUB, DOCX")
    if len(text) < 20:
        raise IntakeError("no usable novel text was found")
    return ImportedSource(
        title=_clean_inline(title)[:160] or "untitled-story",
        source_name=Path(urllib.parse.urlparse(source_name).path).name or "source" + suffix,
        source_uri=source_uri,
        media_type=media_type,
        suffix=suffix,
        raw_bytes=raw,
        text=text,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _validate_public_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise IntakeError("enter a complete http or https URL")
    if parsed.username or parsed.password:
        raise IntakeError("URLs containing credentials are not accepted")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise IntakeError("the URL host could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise IntakeError("local or private network URLs are not accepted")
    return parsed


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def import_url(url: str, timeout: float = 30.0, progress=None) -> ImportedSource:
    parsed = _validate_public_url(url)
    if not _robots_allowed(url):
        raise IntakeError("this website does not permit automated reading")
    final_url, raw, content_type = _fetch_url(url, timeout)
    first = extract_source(raw, final_url, final_url, content_type)
    if content_type != "text/html":
        return first
    parser = _TextExtractor()
    parser.feed(_decode_text(raw))
    chapter_urls = _chapter_links(final_url, parser.links)
    if progress:
        progress({"phase": "chapter_crawl", "discovered": len(chapter_urls), "completed": 0, "failed": 0})
    if len(chapter_urls) < 2:
        return ImportedSource(**{**first.__dict__, "pages": ({"url": final_url, "media_type": content_type, "raw": raw, "sha256": hashlib.sha256(raw).hexdigest()},)})
    page_results: list[tuple[str, bytes, str] | None] = [None] * len(chapter_urls)
    completed_count = 0
    failed_count = 0
    rate_lock = threading.Lock()
    next_request_at = [0.0]
    def throttle():
        with rate_lock:
            wait = next_request_at[0] - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            next_request_at[0] = time.monotonic() + CHAPTER_REQUEST_INTERVAL_SECONDS
    with futures.ThreadPoolExecutor(max_workers=4) as executor:
        pending = {executor.submit(_fetch_url_retry, chapter_url, timeout, 5, throttle): index for index, chapter_url in enumerate(chapter_urls)}
        for future in futures.as_completed(pending):
            index = pending[future]
            try:
                page_results[index] = future.result()
            except Exception:
                page_results[index] = None
                failed_count += 1
            completed_count += 1
            if progress and (completed_count == len(chapter_urls) or completed_count % 10 == 0):
                progress({"phase": "chapter_crawl", "discovered": len(chapter_urls), "completed": completed_count, "failed": failed_count})
    pages = []
    sections = []
    seen_text = set()
    total_bytes = 0
    fetch_failed = sum(result is None for result in page_results)
    duplicate_pages = 0
    invalid_pages = 0
    for result in page_results:
        if not result:
            continue
        page_url, page_raw, page_type = result
        total_bytes += len(page_raw)
        if total_bytes > MAX_SOURCE_BYTES:
            raise IntakeError("combined novel pages exceed the 100 MB intake limit")
        try:
            page_source = extract_source(page_raw, page_url, page_url, page_type)
        except IntakeError:
            invalid_pages += 1
            continue
        if page_source.text_sha256 in seen_text:
            duplicate_pages += 1
            continue
        seen_text.add(page_source.text_sha256)
        sections.append(f"{page_source.title}\n\n{page_source.text}")
        pages.append({"url": page_url, "media_type": page_type, "raw": page_raw, "sha256": hashlib.sha256(page_raw).hexdigest()})
    if len(pages) < 2:
        return ImportedSource(**{**first.__dict__, "pages": ({"url": final_url, "media_type": content_type, "raw": raw, "sha256": hashlib.sha256(raw).hexdigest()},)})
    combined_text = _normalize_text("\n\n".join(sections))
    aggregate_sha = hashlib.sha256("".join(page["sha256"] for page in pages).encode()).hexdigest()
    return ImportedSource(
        title=first.title,
        source_name=first.source_name,
        source_uri=final_url,
        media_type="application/vnd.backlotos.web-novel",
        suffix=".html",
        raw_bytes=raw,
        text=combined_text,
        raw_sha256=aggregate_sha,
        text_sha256=hashlib.sha256(combined_text.encode("utf-8")).hexdigest(),
        pages=tuple(pages),
        crawl={"status": "PASS" if fetch_failed == 0 and invalid_pages == 0 else "PARTIAL", "discovered": len(chapter_urls), "fetched_unique": len(pages), "fetch_failed": fetch_failed, "duplicates_removed": duplicate_pages, "invalid_pages": invalid_pages},
    )


def _robots_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    robots_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
    try:
        request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain,*/*;q=0.1"})
        with urllib.request.urlopen(request, timeout=10) as response:
            lines = _decode_text(response.read(1024 * 1024)).splitlines()
        robots = urllib.robotparser.RobotFileParser()
        robots.set_url(robots_url)
        robots.parse(lines)
        return robots.can_fetch(USER_AGENT, url)
    except urllib.error.HTTPError as exc:
        return exc.code in {404, 410}
    except Exception:
        return True


def _fetch_url(url: str, timeout: float) -> tuple[str, bytes, str]:
    _validate_public_url(url)
    opener = urllib.request.build_opener(_SafeRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,application/pdf,application/epub+zip,*/*;q=0.1"})
    try:
        with opener.open(request, timeout=timeout) as response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_SOURCE_BYTES:
                raise IntakeError("remote source exceeds the 100 MB intake limit")
            raw = response.read(MAX_SOURCE_BYTES + 1)
            if len(raw) > MAX_SOURCE_BYTES:
                raise IntakeError("remote source exceeds the 100 MB intake limit")
            final_url = response.geturl()
            _validate_public_url(final_url)
            content_type = response.headers.get_content_type()
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError(f"the URL could not be read ({type(exc).__name__})") from exc
    return final_url, raw, content_type


def _fetch_url_retry(url: str, timeout: float, attempts: int = 5, before_attempt=None) -> tuple[str, bytes, str]:
    last_error = None
    for attempt in range(attempts):
        try:
            if before_attempt:
                before_attempt()
            return _fetch_url(url, timeout)
        except IntakeError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                deterministic_jitter = (int(hashlib.sha256(url.encode()).hexdigest()[:4], 16) % 250) / 1000
                time.sleep(min(8.0, 0.75 * (2 ** attempt)) + deterministic_jitter)
    raise last_error or IntakeError("chapter could not be read")


def _chapter_links(index_url: str, links: list[tuple[str, str]]) -> list[str]:
    base = urllib.parse.urlparse(index_url)
    chapter_pattern = re.compile(r"(?:chapter|chap|episode|第\s*[0-9零一二三四五六七八九十百千]+\s*[章节回]|正文|/\d{1,12}(?:\.[a-z]+)?$)", re.I)
    path_prefix = base.path if base.path.endswith("/") else base.path.rsplit("/", 1)[0] + "/"
    marker_indexes = [index for index, (_href, label) in enumerate(links) if "全部章" in label or "完整目錄" in label or "all chapters" in label.lower()]
    if marker_indexes:
        links = links[marker_indexes[-1] + 1:]
    ordered = []
    seen = set()
    for href, label in links:
        absolute = urllib.parse.urljoin(index_url, href)
        parsed = urllib.parse.urlparse(absolute)
        canonical = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))
        if parsed.scheme not in {"http", "https"} or parsed.hostname != base.hostname:
            continue
        if path_prefix != "/" and not parsed.path.startswith(path_prefix):
            continue
        if canonical == index_url or canonical in seen:
            continue
        if not chapter_pattern.search(label) and not chapter_pattern.search(parsed.path):
            continue
        seen.add(canonical)
        ordered.append(canonical)
        if len(ordered) >= MAX_CHAPTER_PAGES:
            break
    return ordered


def import_file(path: Path) -> ImportedSource:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise IntakeError("uploaded file does not exist")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise IntakeError("supported formats: TXT, Markdown, HTML, PDF, EPUB, DOCX")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise IntakeError("source exceeds the 100 MB intake limit")
    return extract_source(path.read_bytes(), path.name)
