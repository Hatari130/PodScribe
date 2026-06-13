#!/usr/bin/env python3
"""
小宇宙播客 → 带时间戳的 Markdown 文字稿

用法:
    python transcribe.py <小宇宙链接> [选项]

环境变量:
    默认必剪 ASR 免费免配置。
    SILICONFLOW_API_KEY 仅在使用 --asr-provider siliconflow 时需要。

设计要点:
- 纯标准库,无第三方依赖
- 默认调用必剪 BcutASR 云端接口,免注册免 key
- 保留硅基流动 SenseVoice 兼容路径,可用 --asr-provider siliconflow 手动启用
"""

from __future__ import annotations

import argparse
import concurrent.futures
import difflib
import getpass
import hashlib
import hmac
import html as html_lib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import xml.etree.ElementTree as ET

API_ENDPOINT = "https://api.siliconflow.cn/v1/audio/transcriptions"
BCUT_API_BASE_URL = "https://member.bilibili.com/x/bcut/rubick-interface"
BCUT_API_REQ_UPLOAD = BCUT_API_BASE_URL + "/resource/create"
BCUT_API_COMMIT_UPLOAD = BCUT_API_BASE_URL + "/resource/create/complete"
BCUT_API_CREATE_TASK = BCUT_API_BASE_URL + "/task"
BCUT_API_QUERY_RESULT = BCUT_API_BASE_URL + "/task/result"
JIANYING_SIGN_URL = "https://asrtools-update.bkfeng.top/sign"
JIANYING_API_BASE_URL = "https://lv-pc-api-sinfonlinec.ulikecam.com"
DEFAULT_MODEL = "FunAudioLLM/SenseVoiceSmall"  # 中文最快最准的免费选择
ASR_PROVIDERS = ("bcut", "jianying", "siliconflow")
DEFAULT_ASR_PROVIDER = "bcut"
DEFAULT_SEGMENT_SECONDS = 30
DEFAULT_WORKERS = 5
DEFAULT_FREE_ASR_CHUNK_MINUTES = 10
DEFAULT_FREE_ASR_OVERLAP_SECONDS = 10
DEFAULT_FREE_ASR_WORKERS = 3
AUDIO_BITRATE = "64k"
SUMMARY_MODES = ("brief", "deep", "product", "investment", "obsidian")

CONFIG_TEMPLATE = {
    "asr_provider": DEFAULT_ASR_PROVIDER,
    "siliconflow_api_key": "sk-替换成你的硅基流动APIKey",
    "model": DEFAULT_MODEL,
    "api_endpoint": API_ENDPOINT,
    "segment_seconds": DEFAULT_SEGMENT_SECONDS,
    "workers": DEFAULT_WORKERS,
    "free_asr_chunk_minutes": DEFAULT_FREE_ASR_CHUNK_MINUTES,
    "free_asr_overlap_seconds": DEFAULT_FREE_ASR_OVERLAP_SECONDS,
    "free_asr_workers": DEFAULT_FREE_ASR_WORKERS,
    "audio_bitrate": AUDIO_BITRATE,
    "output": None,
    "keep_audio": False,
    "library_dir": "podcast_library",
}

TERM_REPLACEMENTS = [
    ("co定", "coding"),
    ("扣定", "coding"),
    ("口顶", "coding"),
    ("code定", "coding"),
    ("codeing", "coding"),
    ("coded人", "coding agent"),
    ("Aent", "Agent"),
    ("agentent", "agent"),
    ("git up", "GitHub"),
    ("ge upub", "GitHub"),
    ("chGP", "ChatGPT"),
    ("versel", "Vercel"),
    ("superb", "Supabase"),
    ("poli market", "Polymarket"),
    ("po market", "Polymarket"),
    ("pomarket", "Polymarket"),
    ("web three", "Web3"),
    ("cryto", "crypto"),
    ("me coin", "meme coin"),
]

# ============================================================
# 工具函数
# ============================================================

def log(msg: str, *, end: str = "\n") -> None:
    """打印到 stderr,避免污染 stdout (脚本可能被管道调用)"""
    print(msg, file=sys.stderr, end=end, flush=True)

def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """运行外部命令,失败时抛出带详细信息的异常"""
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(
            f"命令失败: {' '.join(cmd[:3])}...\n"
            f"stderr: {result.stderr[:500]}"
        )
    return result

def format_timestamp(seconds: float) -> str:
    """秒数 → MM:SS 或 HH:MM:SS"""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def sanitize_filename(name: str) -> str:
    """把标题里的非法文件名字符替换掉"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip().strip(".")
    return name[:100] or "podcast"

@dataclass(frozen=True)
class Settings:
    asr_provider: str
    api_key: str | None
    api_endpoint: str
    model: str
    segment_seconds: int
    workers: int
    free_asr_chunk_minutes: int
    free_asr_overlap_seconds: int
    free_asr_workers: int
    output: str | None
    keep_audio: bool
    audio_bitrate: str

@dataclass(frozen=True)
class Chapter:
    start: float
    end: float
    title: str

@dataclass(frozen=True)
class TranscribeResult:
    meta: "EpisodeMeta"
    output_path: Path
    duration: float
    segments: list[tuple[float, float, str]]
    transcript_text: str
    model: str

def is_placeholder_api_key(api_key: str | None) -> bool:
    if not api_key:
        return True
    lowered = api_key.strip().lower()
    return (
        lowered in {"sk-", "sk-xxx", "sk-your-api-key"}
        or "替换" in api_key
        or "你的" in api_key
        or "your" in lowered
    )

def default_config_candidates() -> list[Path]:
    """配置文件默认从当前目录和脚本目录查找。"""
    candidates = [
        Path.cwd() / "config.json",
        Path(__file__).resolve().with_name("config.json"),
    ]
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique

def load_config(path: str | None) -> tuple[dict, Path | None]:
    """读取 JSON 配置文件；未提供且默认路径不存在时返回空配置。"""
    if path:
        config_path = Path(path).expanduser()
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        candidates = [config_path]
    else:
        candidates = default_config_candidates()

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件 JSON 格式错误: {candidate} ({e})") from None
        if not isinstance(data, dict):
            raise ValueError(f"配置文件顶层必须是 JSON object: {candidate}")
        return data, candidate

    return {}, None

def config_get(config: dict, *names: str, default=None):
    for name in names:
        value = config.get(name)
        if value is not None and value != "":
            return value
    return default

def config_output_path(path: str | None) -> Path:
    """--init 的目标配置路径；不传时写到当前目录。"""
    return Path(path).expanduser() if path else Path.cwd() / "config.json"

def init_config(path: str | None, *, force: bool = False) -> int:
    """交互式生成 config.json。"""
    output = config_output_path(path)
    if output.exists() and not force:
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        key_status = "占位符" if is_placeholder_api_key(existing.get("siliconflow_api_key")) else "已填写"
        log(f"⚠️  配置文件已存在: {output.resolve()} ({key_status})")
        log("   如需覆盖,请加 --force")
        return 1

    data = dict(CONFIG_TEMPLATE)
    log("默认使用必剪免费 ASR,转录不需要 API Key。")
    log("如需使用旧硅基流动转录,可在这里填写 SiliconFlow API Key；留空也可以。")
    try:
        api_key = getpass.getpass("SiliconFlow API Key: ").strip()
    except (EOFError, KeyboardInterrupt):
        log("\n❌ 已取消")
        return 1
    if api_key:
        data["siliconflow_api_key"] = api_key

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log(f"✅ 已生成配置: {output.resolve()}")
    if is_placeholder_api_key(data["siliconflow_api_key"]):
        log("ℹ️  当前 API Key 仍是占位符；默认必剪 ASR 可直接转录,只有硅基流动转录才需要真实 key。")
    return 0

def to_int(value, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"配置项 {name} 必须是整数: {value!r}") from None

def to_bool(value, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError(f"配置项 {name} 必须是布尔值: {value!r}")

def normalize_asr_provider(value: str | None) -> str:
    provider = (value or DEFAULT_ASR_PROVIDER).strip().lower()
    aliases = {
        "bijian": "bcut",
        "b-cut": "bcut",
        "bilibili": "bcut",
        "capcut": "jianying",
        "jian-ying": "jianying",
        "silicon": "siliconflow",
        "sensevoice": "siliconflow",
    }
    provider = aliases.get(provider, provider)
    if provider not in ASR_PROVIDERS:
        raise ValueError(f"asr_provider 必须是 {', '.join(ASR_PROVIDERS)} 之一: {value!r}")
    return provider

def build_settings(args: argparse.Namespace, config: dict) -> Settings:
    """命令行参数优先,其次配置文件,最后环境变量或内置默认值。"""
    asr_provider = normalize_asr_provider(
        getattr(args, "asr_provider", None) or config_get(config, "asr_provider", "asr", default=DEFAULT_ASR_PROVIDER)
    )
    file_api_key = config_get(config, "siliconflow_api_key", "api_key")
    env_api_key = os.environ.get("SILICONFLOW_API_KEY") or os.environ.get("SILICON_API_KEY")
    api_key = env_api_key if is_placeholder_api_key(file_api_key) and env_api_key else file_api_key or env_api_key
    segment_seconds = (
        args.segment_seconds
        if args.segment_seconds is not None
        else to_int(config_get(config, "segment_seconds", default=DEFAULT_SEGMENT_SECONDS), "segment_seconds")
    )
    workers = (
        args.workers
        if args.workers is not None
        else to_int(config_get(config, "workers", default=DEFAULT_WORKERS), "workers")
    )
    free_asr_chunk_minutes = (
        args.free_asr_chunk_minutes
        if getattr(args, "free_asr_chunk_minutes", None) is not None
        else to_int(
            config_get(config, "free_asr_chunk_minutes", default=DEFAULT_FREE_ASR_CHUNK_MINUTES),
            "free_asr_chunk_minutes",
        )
    )
    free_asr_overlap_seconds = (
        args.free_asr_overlap_seconds
        if getattr(args, "free_asr_overlap_seconds", None) is not None
        else to_int(
            config_get(config, "free_asr_overlap_seconds", default=DEFAULT_FREE_ASR_OVERLAP_SECONDS),
            "free_asr_overlap_seconds",
        )
    )
    free_asr_workers = (
        args.free_asr_workers
        if getattr(args, "free_asr_workers", None) is not None
        else to_int(config_get(config, "free_asr_workers", default=DEFAULT_FREE_ASR_WORKERS), "free_asr_workers")
    )
    keep_audio = (
        args.keep_audio
        if args.keep_audio is not None
        else to_bool(config_get(config, "keep_audio", default=False), "keep_audio")
    )
    if segment_seconds <= 0:
        raise ValueError("segment_seconds 必须大于 0")
    if workers <= 0:
        raise ValueError("workers 必须大于 0")
    if free_asr_chunk_minutes <= 0:
        raise ValueError("free_asr_chunk_minutes 必须大于 0")
    if free_asr_overlap_seconds < 0:
        raise ValueError("free_asr_overlap_seconds 不能小于 0")
    if free_asr_workers <= 0:
        raise ValueError("free_asr_workers 必须大于 0")
    if free_asr_overlap_seconds >= free_asr_chunk_minutes * 60:
        raise ValueError("free_asr_overlap_seconds 必须小于 free_asr_chunk_minutes 对应秒数")

    return Settings(
        asr_provider=asr_provider,
        api_key=api_key,
        api_endpoint=args.api_endpoint or config_get(config, "api_endpoint", default=API_ENDPOINT),
        model=args.model or config_get(config, "model", default=DEFAULT_MODEL),
        segment_seconds=segment_seconds,
        workers=workers,
        free_asr_chunk_minutes=free_asr_chunk_minutes,
        free_asr_overlap_seconds=free_asr_overlap_seconds,
        free_asr_workers=free_asr_workers,
        output=args.output if args.output is not None else config_get(config, "output", default=None),
        keep_audio=keep_audio,
        audio_bitrate=args.audio_bitrate or config_get(config, "audio_bitrate", default=AUDIO_BITRATE),
    )

# ============================================================
# Step 1: 解析小宇宙页面
# ============================================================

XYZ_EPISODE_RE = re.compile(r"xiaoyuzhoufm\.com/episode/[a-f0-9]+", re.IGNORECASE)

def fetch_page(url: str) -> str:
    """抓取小宇宙 episode 页面 HTML"""
    if not XYZ_EPISODE_RE.search(url):
        raise ValueError(
            f"链接不是 episode 页面: {url}\n"
            "正确格式: https://www.xiaoyuzhoufm.com/episode/<id>"
        )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")

@dataclass
class EpisodeMeta:
    title: str
    audio_url: str
    podcast: str | None = None

def parse_episode(html: str) -> EpisodeMeta:
    """从页面 HTML 提取标题和音频 URL"""
    audio_match = re.search(
        r'https://media\.xyzcdn\.net/[^"\']+\.(?:m4a|mp3)',
        html,
    )
    if not audio_match:
        raise RuntimeError(
            "无法从页面提取音频 URL。可能页面结构变了,"
            "或者你给的链接不是 episode 页(比如是 podcast 主页)。"
        )
    audio_url = audio_match.group(0)

    title = None
    og = re.search(
        r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
        html,
    )
    if og:
        title = og.group(1)
    if not title:
        t = re.search(r"<title>([^<]+)</title>", html)
        if t:
            title = t.group(1).split("|")[0].strip()
    if not title:
        title = "未命名播客"

    podcast = None
    site = re.search(
        r'<meta\s+property=["\']og:site_name["\']\s+content=["\']([^"\']+)["\']',
        html,
    )
    if site:
        podcast = site.group(1)

    return EpisodeMeta(title=title.strip(), audio_url=audio_url, podcast=podcast)

# ============================================================
# Step 1.5: 启动前自检
# ============================================================

def api_models_url(api_endpoint: str) -> str:
    if "/v1/" in api_endpoint:
        return api_endpoint.split("/v1/", 1)[0].rstrip("/") + "/v1/models"
    return "https://api.siliconflow.cn/v1/models"

def check_command(command: str) -> str | None:
    path = shutil.which(command)
    if not path:
        return f"未找到 {command}; 请先安装 ffmpeg,并确保 {command} 在 PATH 中。"
    try:
        run([command, "-version"])
    except Exception as e:
        return f"{command} 无法运行: {e}"
    return None

def check_openai_compatible_api(api_endpoint: str, api_key: str | None, label: str) -> tuple[bool, str]:
    """检查 OpenAI 兼容 API 域名可达和 key 是否明显有效。"""
    req = urllib.request.Request(
        api_models_url(api_endpoint),
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "Mozilla/5.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if 200 <= resp.status < 300:
                return True, f"{label} API 可访问,key 已通过 /v1/models 验证。"
            return False, f"{label} API 返回异常状态码: HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        if e.code in {401, 403}:
            return False, f"{label} API Key 无效或无权限: HTTP {e.code}"
        return True, f"{label} API 可访问,但 /v1/models 返回 HTTP {e.code}; 将在请求时继续验证。"
    except Exception as e:
        return False, f"无法访问 {label} API: {e}"

def check_siliconflow(settings: Settings) -> tuple[bool, str]:
    return check_openai_compatible_api(settings.api_endpoint, settings.api_key, "硅基流动转录")

def credential_errors(settings: Settings) -> list[str]:
    errors: list[str] = []
    if settings.asr_provider == "siliconflow" and is_placeholder_api_key(settings.api_key):
        errors.append("使用 --asr-provider siliconflow 时需要 siliconflow_api_key 或 SILICONFLOW_API_KEY。")
    return errors

def run_preflight(
    settings: Settings,
    config_path: Path | None,
    url: str | None,
    summary_mode: str | None = None,
) -> EpisodeMeta | None:
    log("🧪 启动前自检...")
    errors: list[str] = []
    meta: EpisodeMeta | None = None

    if config_path:
        log(f"   ✓ config.json: {config_path.resolve()}")
    elif os.environ.get("SILICONFLOW_API_KEY") or os.environ.get("SILICON_API_KEY"):
        log("   ✓ config.json 未找到,将使用环境变量里的 API Key")
    else:
        log("   ✓ config.json/API Key: 默认免费 ASR 不需要配置")

    errors.extend(credential_errors(settings))

    if settings.asr_provider == "siliconflow":
        if is_placeholder_api_key(settings.api_key):
            pass
        else:
            log("   ✓ 硅基流动转录 API Key: 已填写")
    else:
        log(f"   ✓ ASR: {settings.asr_provider} 免费免配置")

    for command in ("ffmpeg", "ffprobe"):
        err = check_command(command)
        if err:
            errors.append(err)
        else:
            log(f"   ✓ {command}: 可用")

    if settings.asr_provider == "siliconflow" and not is_placeholder_api_key(settings.api_key):
        ok, message = check_siliconflow(settings)
        if ok:
            log(f"   ✓ {message}")
        else:
            errors.append(message)

    if summary_mode:
        log("   ✓ 摘要: 由本地 Agent 基于全文生成,脚本不自动总结")

    if url:
        try:
            html = fetch_page(url)
            meta = parse_episode(html)
            log(f"   ✓ 小宇宙页面: {meta.title}")
        except Exception as e:
            errors.append(f"小宇宙页面无法访问或解析失败: {e}")

    if errors:
        detail = "\n".join(f"   - {error}" for error in errors)
        raise RuntimeError(f"启动前自检未通过:\n{detail}")

    return meta

# ============================================================
# Step 2: 下载 + 转码 + 按时长切片
# ============================================================

def download(url: str, dst: Path) -> None:
    """下载音频文件"""
    log("⬇️  下载音频...")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.xiaoyuzhoufm.com/"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp, open(dst, "wb") as f:
        shutil.copyfileobj(resp, f)
    size_mb = dst.stat().st_size / 1024 / 1024
    log(f"   完成 ({size_mb:.1f} MB)")

def probe_duration(path: Path) -> float:
    """用 ffprobe 拿音频时长(秒)"""
    result = run([
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(path),
    ])
    return float(result.stdout.strip())

def transcode_mono(src: Path, dst: Path, audio_bitrate: str) -> None:
    """转单声道 + 64kbps MP3"""
    log("🔄 转码为单声道 MP3...")
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(src),
        "-ac", "1",
        "-b:a", audio_bitrate,
        "-vn",
        str(dst),
    ])
    size_mb = dst.stat().st_size / 1024 / 1024
    log(f"   完成 ({size_mb:.1f} MB)")

@dataclass
class Chunk:
    path: Path
    offset: float       # 在原音频中的起始时间(秒)
    duration: float     # 这一片的实际时长(秒)

def slice_by_duration(
    src: Path,
    total_duration: float,
    chunk_seconds: float,
    workdir: Path,
) -> list[Chunk]:
    """用 ffmpeg segment muxer 一次性切片,比循环调用快几十倍"""
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(src),
        "-f", "segment",
        "-segment_time", str(chunk_seconds),
        "-c", "copy",
        str(workdir / "chunk_%04d.mp3"),
    ])

    paths = sorted(workdir.glob("chunk_*.mp3"))
    chunks: list[Chunk] = []
    for i, path in enumerate(paths):
        offset = i * chunk_seconds
        duration = probe_duration(path)
        if duration < 0.5:
            continue
        chunks.append(Chunk(path=path, offset=offset, duration=duration))

    log(f"✂️  按 {chunk_seconds:.0f} 秒切分为 {len(chunks)} 段")
    return chunks

# ============================================================
# Step 3: 调硅基流动转录 API
# ============================================================

def transcribe_chunk(
    chunk: Chunk,
    api_key: str,
    api_endpoint: str,
    model: str,
    attempt: int = 1,
) -> str:
    """上传一个 chunk,返回纯文本"""
    boundary = f"----xyz{uuid.uuid4().hex}"
    body = build_multipart(
        boundary,
        file_path=chunk.path,
        fields={"model": model},
    )
    req = urllib.request.Request(
        api_endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )

    MAX_ATTEMPTS = 5
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        if e.code == 429 and attempt < MAX_ATTEMPTS:
            log(f"   ⏳ 429 速率限制,等待 30 秒后重试 (第 {attempt} 次)...")
            time.sleep(30)
            return transcribe_chunk(chunk, api_key, api_endpoint, model, attempt + 1)
        if 500 <= e.code < 600 and attempt < MAX_ATTEMPTS:
            wait = min(2 ** attempt, 30)
            log(f"   ⚠️ HTTP {e.code},{wait} 秒后重试 (第 {attempt} 次)...")
            time.sleep(wait)
            return transcribe_chunk(chunk, api_key, api_endpoint, model, attempt + 1)
        raise RuntimeError(
            f"硅基流动 API 错误 HTTP {e.code}:\n{err_body[:500]}"
        ) from None
    except (urllib.error.URLError, TimeoutError) as e:
        if attempt < MAX_ATTEMPTS:
            wait = min(2 ** attempt, 30)
            log(f"   ⚠️ 网络错误 {e},{wait} 秒后重试 (第 {attempt} 次)...")
            time.sleep(wait)
            return transcribe_chunk(chunk, api_key, api_endpoint, model, attempt + 1)
        raise

    # 硅基流动返回的是 OpenAI 兼容格式: {"text": "..."}
    return (data.get("text") or "").strip()

def build_multipart(boundary: str, file_path: Path, fields: dict) -> bytes:
    """手搓 multipart/form-data,避免引入 requests"""
    parts: list[bytes] = []
    boundary_b = boundary.encode()
    for key, value in fields.items():
        parts.append(b"--" + boundary_b + b"\r\n")
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        parts.append(str(value).encode() + b"\r\n")
    parts.append(b"--" + boundary_b + b"\r\n")
    parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode()
    )
    parts.append(b"Content-Type: audio/mpeg\r\n\r\n")
    parts.append(file_path.read_bytes())
    parts.append(b"\r\n--" + boundary_b + b"--\r\n")
    return b"".join(parts)

def http_request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, str | int] | None = None,
    timeout: int = 60,
) -> tuple[bytes, object]:
    if params:
        query = urllib.parse.urlencode(params)
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{query}"
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code} 请求失败: {url}\n{body[:500]}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络请求失败: {url}\n{e}") from None

def http_json_request(
    url: str,
    *,
    method: str = "GET",
    json_body: dict | None = None,
    raw_body: bytes | str | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, str | int] | None = None,
    timeout: int = 60,
) -> tuple[dict, object]:
    request_headers = dict(headers or {})
    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    elif raw_body is not None:
        data = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    body, response_headers = http_request(
        url,
        method=method,
        data=data,
        headers=request_headers,
        params=params,
        timeout=timeout,
    )
    text = body.decode("utf-8", errors="ignore")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"接口返回不是 JSON: {text[:500]}") from None
    if not isinstance(parsed, dict):
        raise RuntimeError(f"接口返回 JSON 顶层不是 object: {text[:500]}")
    return parsed, response_headers

def crc32_hex(data: bytes) -> str:
    return format(zlib.crc32(data) & 0xFFFFFFFF, "08x")

def slice_with_overlap(
    src: Path,
    total_duration: float,
    chunk_seconds: int,
    overlap_seconds: int,
    workdir: Path,
    audio_bitrate: str,
) -> list[Chunk]:
    """为免费云 ASR 切长音频。短音频不切,长音频按重叠窗口切。"""
    if total_duration <= chunk_seconds:
        return [Chunk(path=src, offset=0.0, duration=total_duration)]

    step_seconds = chunk_seconds - overlap_seconds
    chunks: list[Chunk] = []
    start = 0.0
    idx = 0
    while start < total_duration:
        end = min(start + chunk_seconds, total_duration)
        duration = end - start
        if duration < 1.0:
            break
        path = workdir / f"free_asr_chunk_{idx:04d}.mp3"
        run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{start:.3f}",
            "-t", f"{duration:.3f}",
            "-i", str(src),
            "-ac", "1",
            "-b:a", audio_bitrate,
            "-vn",
            str(path),
        ])
        actual_duration = probe_duration(path)
        chunks.append(Chunk(path=path, offset=start, duration=actual_duration))
        idx += 1
        if end >= total_duration:
            break
        start += step_seconds

    log(
        f"✂️  免费 ASR 长音频切分: {len(chunks)} 片, "
        f"每片 {chunk_seconds // 60} 分钟,重叠 {overlap_seconds} 秒"
    )
    return chunks

def offset_segments(
    segments: list[tuple[float, float, str]],
    offset: float,
) -> list[tuple[float, float, str]]:
    return [(start + offset, end + offset, text) for start, end, text in segments]

def normalize_for_overlap(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())

def segment_text_similarity(a: str, b: str) -> float:
    left = normalize_for_overlap(a)
    right = normalize_for_overlap(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right).ratio()

def is_probable_overlap_duplicate(
    candidate: tuple[float, float, str],
    existing: tuple[float, float, str],
    overlap_seconds: int,
) -> bool:
    start, end, text = candidate
    prev_start, prev_end, prev_text = existing
    time_overlap = min(end, prev_end) - max(start, prev_start)
    near_overlap_window = abs(start - prev_start) <= max(2, overlap_seconds)
    if time_overlap <= 0 and not near_overlap_window:
        return False
    return segment_text_similarity(text, prev_text) >= 0.82

def merge_overlapped_segments(
    segments: list[tuple[float, float, str]],
    overlap_seconds: int,
) -> list[tuple[float, float, str]]:
    """合并重叠切片结果。时间重叠且文本相似时保留较早片段。"""
    merged: list[tuple[float, float, str]] = []
    for segment in sorted(segments, key=lambda item: (item[0], item[1])):
        if not segment[2].strip():
            continue
        if any(is_probable_overlap_duplicate(segment, prev, overlap_seconds) for prev in merged[-12:]):
            continue
        merged.append(segment)
    return merged

def append_transcript_text(left: str, right: str) -> str:
    left = left.strip()
    right = right.strip()
    if not left:
        return right
    if not right:
        return left
    if re.search(r"[，。！？!?；;：:、,.]$", left) or re.search(r"^[，。！？!?；;：:、,.]", right):
        return left + right
    return f"{left} {right}"

def coalesce_segments(
    segments: list[tuple[float, float, str]],
    *,
    max_seconds: int,
    max_gap_seconds: float = 3.0,
) -> list[tuple[float, float, str]]:
    """把字幕级短句合并成更适合播客全文稿的段落。"""
    if not segments:
        return []
    merged: list[tuple[float, float, str]] = []
    cur_start: float | None = None
    cur_end: float | None = None
    cur_text = ""

    for start, end, text in sorted(segments, key=lambda item: (item[0], item[1])):
        text = text.strip()
        if not text:
            continue
        if cur_start is None or cur_end is None:
            cur_start, cur_end, cur_text = start, end, text
            continue

        would_duration = end - cur_start
        gap = start - cur_end
        if would_duration <= max_seconds and gap <= max_gap_seconds:
            cur_end = max(cur_end, end)
            cur_text = append_transcript_text(cur_text, text)
        else:
            merged.append((cur_start, cur_end, cur_text))
            cur_start, cur_end, cur_text = start, end, text

    if cur_start is not None and cur_end is not None and cur_text:
        merged.append((cur_start, cur_end, cur_text))
    return merged

def parse_bcut_segments(resp_data: dict) -> list[tuple[float, float, str]]:
    segments: list[tuple[float, float, str]] = []
    for utterance in resp_data.get("utterances") or []:
        text = (utterance.get("transcript") or "").strip()
        if not text:
            continue
        start = float(utterance.get("start_time") or 0) / 1000.0
        end = float(utterance.get("end_time") or 0) / 1000.0
        segments.append((start, end, text))
    return segments

def transcribe_with_bcut(audio_path: Path, label: str | None = None) -> list[tuple[float, float, str]]:
    """调用 B 站「必剪」云端 ASR。免 key,非官方接口。"""
    file_binary = audio_path.read_bytes()
    headers = {
        "User-Agent": "Bilibili/1.0.0 (https://www.bilibili.com)",
        "Content-Type": "application/json",
    }

    suffix = f" ({label})" if label else ""
    log(f"🎙️  调用必剪 BcutASR,免费免配置{suffix}...")
    create_resp, _ = http_json_request(
        BCUT_API_REQ_UPLOAD,
        method="POST",
        json_body={
            "type": 2,
            "name": "audio.mp3",
            "size": len(file_binary),
            "ResourceFileType": "mp3",
            "model_id": "8",
        },
        headers=headers,
        timeout=60,
    )
    upload_info = create_resp.get("data") or {}
    upload_urls = upload_info.get("upload_urls") or []
    per_size = int(upload_info.get("per_size") or len(file_binary))
    if not upload_urls:
        raise RuntimeError(f"必剪 ASR 未返回上传地址: {create_resp}")

    etags: list[str] = []
    for idx, upload_url in enumerate(upload_urls):
        start = idx * per_size
        end = min((idx + 1) * per_size, len(file_binary))
        log(f"   上传分片 {idx + 1}/{len(upload_urls)}... ", end="")
        _, upload_headers = http_request(
            upload_url,
            method="PUT",
            data=file_binary[start:end],
            headers=headers,
            timeout=180,
        )
        etag = upload_headers.get("Etag") or upload_headers.get("ETag")
        if etag:
            etags.append(etag)
        log("✓")

    commit_resp, _ = http_json_request(
        BCUT_API_COMMIT_UPLOAD,
        method="POST",
        json_body={
            "InBossKey": upload_info.get("in_boss_key"),
            "ResourceId": upload_info.get("resource_id"),
            "Etags": ",".join(etags) if etags else "",
            "UploadId": upload_info.get("upload_id"),
            "model_id": "8",
        },
        headers=headers,
        timeout=60,
    )
    download_url = ((commit_resp.get("data") or {}).get("download_url") or "").strip()
    if not download_url:
        raise RuntimeError(f"必剪 ASR 上传提交失败: {commit_resp}")

    task_resp, _ = http_json_request(
        BCUT_API_CREATE_TASK,
        method="POST",
        json_body={"resource": download_url, "model_id": "8"},
        headers=headers,
        timeout=60,
    )
    task_id = ((task_resp.get("data") or {}).get("task_id") or "").strip()
    if not task_id:
        raise RuntimeError(f"必剪 ASR 创建任务失败: {task_resp}")

    for poll in range(1, 901):
        result_resp, _ = http_json_request(
            BCUT_API_QUERY_RESULT,
            params={"model_id": 7, "task_id": task_id},
            headers=headers,
            timeout=60,
        )
        result_data = result_resp.get("data") or {}
        state = result_data.get("state")
        if state == 4:
            result_text = result_data.get("result") or "{}"
            try:
                return parse_bcut_segments(json.loads(result_text))
            except json.JSONDecodeError:
                raise RuntimeError(f"必剪 ASR 返回结果无法解析: {result_text[:500]}") from None
        if state in {5, 6, -1}:
            raise RuntimeError(f"必剪 ASR 任务失败: {result_resp}")
        if poll % 15 == 0:
            log(f"   等待识别结果... {poll}s")
        time.sleep(1)

    raise RuntimeError("必剪 ASR 等待超时。可稍后重试,或改用 --asr-provider jianying/siliconflow。")

def transcribe_with_bcut_chunked(
    settings: Settings,
    audio_path: Path,
    duration: float,
    workdir: Path,
) -> list[tuple[float, float, str]]:
    chunk_seconds = settings.free_asr_chunk_minutes * 60
    if duration <= chunk_seconds:
        return transcribe_with_bcut(audio_path)

    chunks = slice_with_overlap(
        audio_path,
        duration,
        chunk_seconds,
        settings.free_asr_overlap_seconds,
        workdir,
        settings.audio_bitrate,
    )
    all_segments: list[tuple[float, float, str] | None] = []
    ordered_results: list[list[tuple[float, float, str]] | None] = [None] * len(chunks)

    def transcribe_one(idx_chunk):
        idx, chunk = idx_chunk
        label = f"{idx + 1}/{len(chunks)} {format_timestamp(chunk.offset)}-{format_timestamp(chunk.offset + chunk.duration)}"
        segments = transcribe_with_bcut(chunk.path, label=label)
        return idx, offset_segments(segments, chunk.offset)

    max_workers = min(settings.free_asr_workers, len(chunks))
    log(f"🚀 BcutASR 分片并发: {max_workers},切片数 {len(chunks)}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(transcribe_one, (idx, chunk)): idx for idx, chunk in enumerate(chunks)}
        for future in concurrent.futures.as_completed(futures):
            idx, segments = future.result()
            ordered_results[idx] = segments
            log(f"   Bcut 分片 {idx + 1}/{len(chunks)} 完成: {len(segments)} 段")

    for segments in ordered_results:
        if segments:
            all_segments.extend(segments)
    merged = merge_overlapped_segments(
        [segment for segment in all_segments if segment is not None],
        settings.free_asr_overlap_seconds,
    )
    log(f"🔗 BcutASR 合并完成: {len(all_segments)} 段 -> {len(merged)} 段")
    return merged

def jianying_tdid() -> str:
    year_digit = str(datetime.now().year)[3]
    prefix = 390 + int(year_digit)
    suffix = "3278516897751" if int(year_digit) % 2 != 0 else f"{uuid.getnode():013d}"
    return f"{prefix}{suffix}"

def jianying_sign(path: str, tdid: str) -> tuple[str, str]:
    current_time = str(int(time.time()))
    resp, _ = http_json_request(
        JIANYING_SIGN_URL,
        method="POST",
        json_body={
            "url": path,
            "current_time": current_time,
            "pf": "4",
            "appvr": "6.6.0",
            "tdid": tdid,
        },
        headers={
            "User-Agent": "PodScribe/1.0",
            "tdid": tdid,
            "t": current_time,
        },
        timeout=30,
    )
    sign_value = (resp.get("sign") or "").strip()
    if not sign_value:
        raise RuntimeError(f"剪映签名服务未返回 sign: {resp}")
    return sign_value.lower(), current_time

def jianying_headers(path: str, tdid: str) -> dict[str, str]:
    sign_value, device_time = jianying_sign(path, tdid)
    return {
        "User-Agent": "Cronet/TTNetVersion:d4572e53 2024-06-12 QuicVersion:4bf243e0 2023-04-17",
        "appvr": "6.6.0",
        "device-time": device_time,
        "pf": "4",
        "sign": sign_value,
        "sign-ver": "1",
        "tdid": tdid,
    }

def hmac_sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

def aws_signature_key(secret_key: str, date_stamp: str, region_name: str, service_name: str) -> bytes:
    k_date = hmac_sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = hmac_sign(k_date, region_name)
    k_service = hmac_sign(k_region, service_name)
    return hmac_sign(k_service, "aws4_request")

def aws_signature(
    secret_key: str,
    request_parameters: str,
    headers: dict[str, str],
    method: str = "GET",
    payload: str = "",
    region: str = "cn",
    service: str = "vod",
) -> str:
    canonical_headers = "\n".join([f"{key}:{value}" for key, value in headers.items()]) + "\n"
    signed_headers = ";".join(headers.keys())
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = (
        f"{method}\n/\n{request_parameters}\n"
        f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )
    amz_date = headers["x-amz-date"]
    date_stamp = amz_date.split("T")[0]
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = (
        "AWS4-HMAC-SHA256\n"
        f"{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )
    signing_key = aws_signature_key(secret_key, date_stamp, region, service)
    return hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

def parse_jianying_segments(resp_data: dict) -> list[tuple[float, float, str]]:
    segments: list[tuple[float, float, str]] = []
    for utterance in ((resp_data.get("data") or {}).get("utterances") or []):
        text = (utterance.get("text") or "").strip()
        if not text:
            continue
        start = float(utterance.get("start_time") or 0) / 1000.0
        end = float(utterance.get("end_time") or 0) / 1000.0
        segments.append((start, end, text))
    return segments

def transcribe_with_jianying(audio_path: Path, duration: float) -> list[tuple[float, float, str]]:
    """调用字节「剪映」云端 ASR。依赖 VideoCaptioner 公共签名服务。"""
    file_binary = audio_path.read_bytes()
    crc = crc32_hex(file_binary)
    tdid = jianying_tdid()

    log("🎙️  调用剪映 JianYingASR,免费免配置(依赖公共签名服务)...")
    upload_sign, _ = http_json_request(
        JIANYING_API_BASE_URL + "/lv/v1/upload_sign",
        method="POST",
        json_body={"biz": "pc-recognition"},
        headers=jianying_headers("/lv/v1/upload_sign", tdid),
        timeout=60,
    )
    upload_data = upload_sign.get("data") or {}
    access_key = upload_data.get("access_key_id")
    secret_key = upload_data.get("secret_access_key")
    session_token = upload_data.get("session_token")
    if not (access_key and secret_key and session_token):
        raise RuntimeError(f"剪映 upload_sign 返回异常: {upload_sign}")

    request_parameters = (
        f"Action=ApplyUploadInner&FileSize={len(file_binary)}&FileType=object&IsInner=1"
        "&SpaceName=lv-mac-recognition&Version=2020-11-19&s=5y0udbjapi"
    )
    now_utc = datetime.now(timezone.utc)
    amz_date = now_utc.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now_utc.strftime("%Y%m%d")
    auth_headers = {"x-amz-date": amz_date, "x-amz-security-token": session_token}
    signature = aws_signature(secret_key, request_parameters, auth_headers)
    auth_headers["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{date_stamp}/cn/vod/aws4_request, "
        f"SignedHeaders=x-amz-date;x-amz-security-token, Signature={signature}"
    )
    store_infos, _ = http_json_request(
        f"https://vod.bytedanceapi.com/?{request_parameters}",
        headers=auth_headers,
        timeout=60,
    )
    upload_address = ((store_infos.get("Result") or {}).get("UploadAddress") or {})
    store_info = (upload_address.get("StoreInfos") or [{}])[0]
    store_uri = store_info.get("StoreUri")
    auth = store_info.get("Auth")
    upload_id = store_info.get("UploadID")
    session_key = upload_address.get("SessionKey")
    upload_host = (upload_address.get("UploadHosts") or [""])[0]
    if not (store_uri and auth and upload_id and session_key and upload_host):
        raise RuntimeError(f"剪映上传授权返回异常: {store_infos}")

    upload_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Authorization": auth,
        "Content-CRC32": crc,
    }
    upload_url = f"https://{upload_host}/{store_uri}?partNumber=1&uploadID={upload_id}"
    upload_resp, _ = http_json_request(
        upload_url,
        method="PUT",
        raw_body=file_binary,
        headers=upload_headers,
        timeout=300,
    )
    if upload_resp.get("success") != 0:
        raise RuntimeError(f"剪映上传文件失败: {upload_resp}")

    check_url = f"https://{upload_host}/{store_uri}?uploadID={upload_id}"
    http_json_request(
        check_url,
        method="POST",
        raw_body=f"1:{crc}",
        headers=upload_headers,
        timeout=60,
    )
    commit_url = (
        f"https://{upload_host}/{store_uri}?uploadID={upload_id}"
        f"&partNumber=1&x-amz-security-token={urllib.parse.quote(str(session_token))}"
    )
    http_request(commit_url, method="PUT", data=file_binary, headers=upload_headers, timeout=300)

    submit_payload = {
        "adjust_endtime": 200,
        "audio": store_uri,
        "caption_type": 2,
        "client_request_id": str(uuid.uuid4()),
        "max_lines": 1,
        "songs_info": [{"end_time": int(duration * 1000), "id": "", "start_time": 0}],
        "words_per_line": 16,
    }
    submit_resp, _ = http_json_request(
        JIANYING_API_BASE_URL + "/lv/v1/audio_subtitle/submit",
        method="POST",
        json_body=submit_payload,
        headers=jianying_headers("/lv/v1/audio_subtitle/submit", tdid),
        timeout=60,
    )
    if submit_resp.get("ret") != "0":
        raise RuntimeError(f"剪映 ASR 提交失败: {submit_resp}")
    query_id = ((submit_resp.get("data") or {}).get("id") or "").strip()
    if not query_id:
        raise RuntimeError(f"剪映 ASR 未返回任务 id: {submit_resp}")

    for poll in range(1, 181):
        query_resp, _ = http_json_request(
            JIANYING_API_BASE_URL + "/lv/v1/audio_subtitle/query",
            method="POST",
            json_body={"id": query_id, "pack_options": {"need_attribute": True}},
            headers=jianying_headers("/lv/v1/audio_subtitle/query", tdid),
            timeout=60,
        )
        if query_resp.get("ret") != "0":
            raise RuntimeError(f"剪映 ASR 查询失败: {query_resp}")
        if "utterances" in (query_resp.get("data") or {}):
            return parse_jianying_segments(query_resp)
        if poll % 10 == 0:
            log(f"   等待剪映识别结果... {poll * 2}s")
        time.sleep(2)

    raise RuntimeError("剪映 ASR 等待超时。可稍后重试,或改用 --asr-provider bcut/siliconflow。")

def transcribe_with_siliconflow(
    settings: Settings,
    mono_path: Path,
    duration: float,
    workdir: Path,
) -> list[tuple[float, float, str]]:
    if is_placeholder_api_key(settings.api_key):
        raise RuntimeError("硅基流动转录需要 siliconflow_api_key 或 SILICONFLOW_API_KEY。")
    t3 = time.time()
    chunks = slice_by_duration(mono_path, duration, settings.segment_seconds, workdir)
    log(f"   ⏱ 切片耗时: {time.time() - t3:.1f}s")

    log(f"🎙️  调用硅基流动 ({settings.model}),并发数 {settings.workers}...")
    maybe_segments: list[tuple[float, float, str] | None] = [None] * len(chunks)

    def transcribe_one(idx_chunk):
        i, chunk = idx_chunk
        log(f"   段 {i+1}/{len(chunks)} [{format_timestamp(chunk.offset)}]... ", end="")
        text = transcribe_chunk(chunk, settings.api_key or "", settings.api_endpoint, settings.model)
        log(f"✓ ({len(text)} 字)")
        return i, chunk, text

    with concurrent.futures.ThreadPoolExecutor(max_workers=settings.workers) as executor:
        futures = {executor.submit(transcribe_one, (i, chunk)): i for i, chunk in enumerate(chunks)}
        for future in concurrent.futures.as_completed(futures):
            i, chunk, text = future.result()
            maybe_segments[i] = (chunk.offset, chunk.offset + chunk.duration, text)

    return [segment for segment in maybe_segments if segment is not None]

def transcribe_with_provider(
    settings: Settings,
    mono_path: Path,
    duration: float,
    workdir: Path,
) -> list[tuple[float, float, str]]:
    if settings.asr_provider == "bcut":
        return transcribe_with_bcut_chunked(settings, mono_path, duration, workdir)
    if settings.asr_provider == "jianying":
        return transcribe_with_jianying(mono_path, duration)
    if settings.asr_provider == "siliconflow":
        return transcribe_with_siliconflow(settings, mono_path, duration, workdir)
    raise RuntimeError(f"未知 ASR provider: {settings.asr_provider}")

def provider_display_name(settings: Settings) -> str:
    if settings.asr_provider == "siliconflow":
        return settings.model
    if settings.asr_provider == "bcut":
        return "BcutASR (必剪)"
    if settings.asr_provider == "jianying":
        return "JianYingASR (剪映)"
    return settings.asr_provider

# ============================================================
# Step 4: 清洗和章节
# ============================================================

def clean_transcript_text(text: str) -> str:
    cleaned = text.strip()
    for old, new in TERM_REPLACEMENTS:
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"([。！？!?])\1+", r"\1", cleaned)
    return cleaned.strip()

def infer_chapter_title(text: str) -> str:
    rules = [
        (("模型", "创业", "价值"), "AI 模型冲击下的软件创业焦虑"),
        (("内部", "小工具", "自己用"), "AI coding 让个人小工具变多"),
        (("基建", "后端", "部署"), "基建决定从想法到产品的速度"),
        (("对话", "拒绝", "画像"), "与 agent 的对话成为新的差异"),
        (("模型公司", "价值", "工具"), "模型公司拿走通用生产力价值"),
        (("中型公司", "哑铃", "OPC"), "软件行业走向哑铃型结构"),
        (("情绪价值", "体验", "审美"), "长尾产品更像体验和文化作品"),
        (("容器", "平台", "消费"), "新创作形态需要新的容器"),
        (("视频", "内容", "消费"), "小产品开始具备内容属性"),
        (("社区", "连接", "回应"), "maker 社区的连接价值"),
        (("回想", "回报", "创作者"), "从回应到回想再到回报"),
        (("意义感", "impact", "影响"), "特殊性和 impact 比普遍性更重要"),
        (("投资", "小型", "文化产业"), "软件投资可能更像文化产业"),
        (("交易", "策略", "Polymarket"), "AI 策略和预测市场的经济回报"),
        (("Web3", "token", "crypto"), "Web3 提供更直接的价值转化路径"),
        (("增长", "发现", "attention"), "平台需要解决发现和增长"),
    ]
    for keywords, title in rules:
        if any(keyword in text for keyword in keywords):
            return title

    sentences = [s.strip() for s in re.split(r"[。！？!?]", text) if len(s.strip()) >= 8]
    if sentences:
        candidate = sentences[0]
        return candidate[:28] + ("..." if len(candidate) > 28 else "")
    return "本段讨论"

def build_chapters(
    segments: list[tuple[float, float, str]],
    *,
    window_seconds: int = 300,
) -> list[Chapter]:
    if not segments:
        return []

    chapters: list[Chapter] = []
    bucket_start = segments[0][0]
    bucket_end = bucket_start
    bucket_texts: list[str] = []

    for start, end, text in segments:
        if bucket_texts and start - bucket_start >= window_seconds:
            joined = " ".join(bucket_texts)
            chapters.append(Chapter(bucket_start, bucket_end, infer_chapter_title(joined)))
            bucket_start = start
            bucket_texts = []
        bucket_end = end
        if text:
            bucket_texts.append(text)

    if bucket_texts:
        joined = " ".join(bucket_texts)
        chapters.append(Chapter(bucket_start, bucket_end, infer_chapter_title(joined)))

    return chapters

# ============================================================
# Step 5: 输出 Markdown
# ============================================================

def write_markdown(
    output: Path,
    meta: EpisodeMeta,
    source_url: str,
    duration: float,
    segments: list[tuple[float, float, str]],
    model: str,
    chapters: list[Chapter] | None = None,
) -> None:
    """生成最终的 Markdown 文件"""
    from datetime import datetime

    lines: list[str] = [
        f"# {meta.title}",
        "",
        f"- **来源**: {source_url}",
    ]
    if meta.podcast:
        lines.append(f"- **节目**: {meta.podcast}")
    lines.extend([
        f"- **时长**: {format_timestamp(duration)}",
        f"- **转录时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- **模型**: {model}",
        "",
        "---",
        "",
    ])

    if chapters:
        lines.extend(["## 章节", ""])
        for chapter in chapters:
            lines.append(f"- **{format_timestamp(chapter.start)}** {chapter.title}")
        lines.extend(["", "---", ""])

    for start, end, text in segments:
        if not text:  # 跳过空段
            continue
        lines.append(f"**[{format_timestamp(start)} - {format_timestamp(end)}]** {text}")
        lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")

def segments_to_index_text(segments: list[tuple[float, float, str]]) -> str:
    return "\n".join(
        f"[{format_timestamp(start)} - {format_timestamp(end)}] {text}"
        for start, end, text in segments
        if text
    )

def transcribe_episode(
    settings: Settings,
    source_url: str,
    *,
    preflight_meta: EpisodeMeta | None = None,
    output_path: Path | None = None,
    summary_mode: str | None = None,
    chapters_enabled: bool = False,
    chapter_window: int = 300,
    clean: bool = True,
) -> TranscribeResult:
    """转录单集播客。source_url 可以是小宇宙页面,也可以配合 preflight_meta 传入 RSS 音频。"""
    workdir = Path(tempfile.mkdtemp(prefix=f"xyz_{os.getpid()}_"))
    log(f"📁 工作目录: {workdir}")

    try:
        t0 = time.time()

        log("🔍 解析单集信息...")
        if preflight_meta:
            meta = preflight_meta
        else:
            html = fetch_page(source_url)
            meta = parse_episode(html)
        log(f"   标题: {meta.title}")

        raw_suffix = Path(meta.audio_url.split("?")[0]).suffix or ".mp3"
        raw_path = workdir / f"original{raw_suffix}"
        t1 = time.time()
        download(meta.audio_url, raw_path)
        log(f"   ⏱ 下载耗时: {time.time() - t1:.1f}s")

        duration = probe_duration(raw_path)
        log(f"⏱️  时长: {format_timestamp(duration)}")

        mono_path = workdir / "mono.mp3"
        t2 = time.time()
        transcode_mono(raw_path, mono_path, settings.audio_bitrate)
        log(f"   ⏱ 转码耗时: {time.time() - t2:.1f}s")

        t4 = time.time()
        segments = transcribe_with_provider(settings, mono_path, duration, workdir)
        log(f"   ⏱ 转录耗时: {time.time() - t4:.1f}s")

        if clean:
            segments = [
                (start, end, clean_transcript_text(text))
                for start, end, text in segments
            ]

        before_coalesce = len(segments)
        segments = coalesce_segments(segments, max_seconds=settings.segment_seconds)
        if len(segments) != before_coalesce:
            log(f"🧩 合并短句: {before_coalesce} 段 -> {len(segments)} 段")

        chapters = build_chapters(segments, window_seconds=chapter_window) if (chapters_enabled or summary_mode) else []

        if output_path is None:
            output_path = Path.cwd() / f"{sanitize_filename(meta.title)}.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_markdown(
            output_path,
            meta,
            source_url,
            duration,
            segments,
            provider_display_name(settings),
            chapters=chapters if chapters_enabled else None,
        )

        if summary_mode:
            log("📝 脚本已完成转录；请让本地 Agent 基于全文稿生成摘要。")

        transcript_text = segments_to_index_text(segments)
        log(f"\n✅ 完成! 总耗时: {time.time() - t0:.1f}s")
        log(f"📄 输出: {output_path.resolve()}")
        log(f"📊 时长 {format_timestamp(duration)} | {len(segments)} 段 | "
            f"{sum(len(s[2]) for s in segments)} 字")

        return TranscribeResult(
            meta=meta,
            output_path=output_path,
            duration=duration,
            segments=segments,
            transcript_text=transcript_text,
            model=provider_display_name(settings),
        )

    finally:
        if settings.keep_audio:
            log(f"💾 保留临时文件: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

# ============================================================
# RSS 订阅库 MVP
# ============================================================

@dataclass(frozen=True)
class FeedEpisode:
    guid: str
    title: str
    published_at: str | None
    description: str
    audio_url: str | None
    episode_url: str | None
    episode_no: str | None

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def library_root(config: dict, override: str | None, config_path: Path | None = None) -> Path:
    """Resolve library_dir to an absolute path.

    - If library_dir is absolute or starts with ~ → use as-is (expanduser).
    - If library_dir is relative AND config_path is known → resolve relative to
      config_path.parent (i.e. the skill/ config directory). This makes the
      entire skill portable: copying it to another agent or machine just works.
    - If library_dir is relative and config_path is None → resolve relative to CWD
      (backward-compatible fallback).
    """
    raw = override or config_get(config, "library_dir", default="podcast_library")
    p = Path(raw).expanduser()
    if not p.is_absolute() and config_path is not None:
        return (config_path.parent / p).resolve()
    return p.resolve()

# ============================================================
# subscriptions.json 人类可读订阅清单
# ============================================================

def subscriptions_json_path(config_path: Path | None) -> Path:
    """subscriptions.json 与 config.json 同目录，如无 config 则为 cwd。"""
    if config_path:
        return config_path.parent / "subscriptions.json"
    return Path.cwd() / "subscriptions.json"

def load_subscriptions_json(path: Path) -> list[dict]:
    """读取 subscriptions.json，文件不存在或格式错误时返回空列表。"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []

def save_subscriptions_json(path: Path, subs: list[dict]) -> None:
    """写入 subscriptions.json，人类可读格式（缩进 2，ensure_ascii=False）。"""
    path.write_text(json.dumps(subs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def upsert_subscription_json(config_path: Path | None, name: str, rss_url: str, *, last_synced: str | None = None) -> None:
    """在 subscriptions.json 中添加或更新一条订阅记录。"""
    path = subscriptions_json_path(config_path)
    subs = load_subscriptions_json(path)
    now = utc_now_iso()
    for sub in subs:
        if sub.get("name") == name:
            sub["rss_url"] = rss_url
            if last_synced:
                sub["last_synced"] = last_synced
            sub["updated_at"] = now
            save_subscriptions_json(path, subs)
            return
    subs.append({
        "name": name,
        "rss_url": rss_url,
        "added_at": now,
        "last_synced": last_synced or "",
        "updated_at": now,
    })
    save_subscriptions_json(path, subs)

def open_library(root: Path) -> sqlite3.Connection:
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "library.sqlite3")
    conn.row_factory = sqlite3.Row
    ensure_library_schema(conn)
    return conn

def ensure_library_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            rss_url TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
            guid TEXT NOT NULL,
            title TEXT NOT NULL,
            published_at TEXT,
            description TEXT NOT NULL DEFAULT '',
            audio_url TEXT,
            episode_url TEXT,
            episode_no TEXT,
            status TEXT NOT NULL DEFAULT 'discovered',
            transcript_path TEXT,
            transcript_text TEXT NOT NULL DEFAULT '',
            duration_seconds REAL,
            model TEXT,
            indexed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(subscription_id, guid)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_episodes_subscription_published "
        "ON episodes(subscription_id, published_at DESC)"
    )
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS episode_fts "
            "USING fts5(title, description, transcript)"
        )
    except sqlite3.OperationalError as e:
        log(f"⚠️  SQLite FTS5 不可用,将使用普通文本搜索: {e}")
    conn.commit()

def upsert_episode_fts(
    conn: sqlite3.Connection,
    episode_id: int,
    title: str,
    description: str,
    transcript_text: str,
) -> None:
    try:
        conn.execute("DELETE FROM episode_fts WHERE rowid = ?", (episode_id,))
        conn.execute(
            "INSERT INTO episode_fts(rowid, title, description, transcript) VALUES (?, ?, ?, ?)",
            (episode_id, title, description, transcript_text),
        )
    except sqlite3.OperationalError:
        return

def fetch_text(url: str, *, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; PodScribe/1.0)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="ignore")

def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag

def child_text(element: ET.Element | None, *names: str) -> str | None:
    if element is None:
        return None
    wanted = set(names)
    for child in list(element):
        if local_tag(child.tag) in wanted and child.text:
            text = child.text.strip()
            if text:
                return text
    return None

def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def parse_feed_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")

def extract_episode_no(title: str) -> str | None:
    patterns = [
        r"第\s*([0-9]{1,5})\s*[期集]",
        r"(?i)\bep\.?\s*([0-9]{1,5})\b",
        r"(?i)\bvol\.?\s*([0-9]{1,5})\b",
        r"(?i)\bno\.?\s*([0-9]{1,5})\b",
        r"#\s*([0-9]{1,5})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, title)
        if match:
            return match.group(1)
    return None

def first_audio_url(item: ET.Element) -> str | None:
    for child in list(item):
        tag = local_tag(child.tag)
        if tag == "enclosure" and child.attrib.get("url"):
            content_type = child.attrib.get("type", "")
            if not content_type or content_type.startswith("audio/"):
                return child.attrib["url"].strip()
        if tag == "content" and child.attrib.get("url"):
            content_type = child.attrib.get("type", "")
            medium = child.attrib.get("medium", "")
            if content_type.startswith("audio/") or medium == "audio":
                return child.attrib["url"].strip()
        if tag == "link" and child.attrib.get("href"):
            rel = child.attrib.get("rel", "")
            content_type = child.attrib.get("type", "")
            if rel == "enclosure" or content_type.startswith("audio/"):
                return child.attrib["href"].strip()
    return None

def first_episode_url(item: ET.Element) -> str | None:
    rss_link = child_text(item, "link")
    if rss_link:
        return rss_link
    guid = child_text(item, "guid", "id")
    if guid and guid.startswith(("http://", "https://")):
        return guid
    for child in list(item):
        if local_tag(child.tag) == "link" and child.attrib.get("href"):
            rel = child.attrib.get("rel", "alternate")
            if rel in {"alternate", ""}:
                return child.attrib["href"].strip()
    return None

def parse_rss_feed(xml_text: str) -> tuple[str | None, list[FeedEpisode]]:
    root = ET.fromstring(xml_text)
    channel = next((node for node in root.iter() if local_tag(node.tag) == "channel"), None)
    podcast_title = child_text(channel, "title") if channel is not None else child_text(root, "title")

    raw_items = [node for node in root.iter() if local_tag(node.tag) == "item"]
    if not raw_items:
        raw_items = [node for node in root.iter() if local_tag(node.tag) == "entry"]

    episodes: list[FeedEpisode] = []
    for item in raw_items:
        title = child_text(item, "title") or "未命名单集"
        published_at = parse_feed_datetime(child_text(item, "pubDate", "published", "updated"))
        description = strip_html(child_text(item, "description", "summary", "encoded", "subtitle"))
        audio_url = first_audio_url(item)
        episode_url = first_episode_url(item)
        guid = child_text(item, "guid", "id") or episode_url or audio_url or title
        if len(guid) > 300:
            guid = hashlib.sha1(guid.encode("utf-8")).hexdigest()
        episodes.append(
            FeedEpisode(
                guid=guid,
                title=strip_html(title) or "未命名单集",
                published_at=published_at,
                description=description,
                audio_url=audio_url,
                episode_url=episode_url,
                episode_no=extract_episode_no(title),
            )
        )

    episodes.sort(key=lambda episode: episode.published_at or "", reverse=True)
    return podcast_title, episodes

def filter_feed_episodes(
    episodes: list[FeedEpisode],
    *,
    limit: int | None,
    days: int | None,
) -> list[FeedEpisode]:
    filtered = episodes
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        filtered = [
            episode for episode in filtered
            if episode.published_at is None
            or datetime.fromisoformat(episode.published_at) >= cutoff
        ]
    if limit is not None:
        filtered = filtered[:limit]
    return filtered

def get_subscription(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM subscriptions WHERE name = ?",
        (name,),
    ).fetchone()

def get_required_subscription(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = get_subscription(conn, name)
    if not row:
        raise RuntimeError(f"未找到 RSS 订阅: {name}。先运行: python transcribe.py rss add \"{name}\" \"<rss_url>\"")
    return row

def add_subscription(conn: sqlite3.Connection, name: str, rss_url: str) -> sqlite3.Row:
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO subscriptions(name, rss_url, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            rss_url = excluded.rss_url,
            updated_at = excluded.updated_at
        """,
        (name, rss_url, now, now),
    )
    conn.commit()
    return get_required_subscription(conn, name)

def sync_subscription(
    conn: sqlite3.Connection,
    subscription: sqlite3.Row,
    episodes: list[FeedEpisode],
) -> tuple[int, int]:
    new_count = 0
    updated_count = 0
    now = utc_now_iso()
    for episode in episodes:
        existing = conn.execute(
            "SELECT id FROM episodes WHERE subscription_id = ? AND guid = ?",
            (subscription["id"], episode.guid),
        ).fetchone()
        if existing:
            updated_count += 1
        else:
            new_count += 1
        conn.execute(
            """
            INSERT INTO episodes(
                subscription_id, guid, title, published_at, description,
                audio_url, episode_url, episode_no, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'discovered', ?, ?)
            ON CONFLICT(subscription_id, guid) DO UPDATE SET
                title = excluded.title,
                published_at = excluded.published_at,
                description = excluded.description,
                audio_url = COALESCE(excluded.audio_url, episodes.audio_url),
                episode_url = COALESCE(excluded.episode_url, episodes.episode_url),
                episode_no = excluded.episode_no,
                updated_at = excluded.updated_at
            """,
            (
                subscription["id"],
                episode.guid,
                episode.title,
                episode.published_at,
                episode.description,
                episode.audio_url,
                episode.episode_url,
                episode.episode_no,
                now,
                now,
            ),
        )
    conn.execute(
        "UPDATE subscriptions SET updated_at = ? WHERE id = ?",
        (now, subscription["id"]),
    )
    conn.commit()
    return new_count, updated_count

def list_episodes(
    conn: sqlite3.Connection,
    subscription_id: int,
    *,
    days: int | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    params: list[object] = [subscription_id]
    where = ["subscription_id = ?"]
    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        where.append("(published_at IS NULL OR published_at >= ?)")
        params.append(cutoff)
    sql = (
        "SELECT * FROM episodes WHERE "
        + " AND ".join(where)
        + " ORDER BY published_at IS NULL, published_at DESC, id DESC"
    )
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params))

def episode_label(row: sqlite3.Row) -> str:
    if row["episode_no"]:
        return str(row["episode_no"])
    return f"#{row['id']}"

def format_date(value: str | None) -> str:
    if not value:
        return "未知日期"
    return value[:10]

def find_episode_by_selector(
    conn: sqlite3.Connection,
    subscription_id: int,
    selector: str,
) -> sqlite3.Row | None:
    normalized = selector.strip().lstrip("#")
    if normalized.isdigit():
        row = conn.execute(
            """
            SELECT * FROM episodes
            WHERE subscription_id = ? AND episode_no = ?
            ORDER BY published_at DESC, id DESC
            LIMIT 1
            """,
            (subscription_id, normalized),
        ).fetchone()
        if row:
            return row
        row = conn.execute(
            "SELECT * FROM episodes WHERE subscription_id = ? AND id = ?",
            (subscription_id, int(normalized)),
        ).fetchone()
        if row:
            return row
    return conn.execute(
        """
        SELECT * FROM episodes
        WHERE subscription_id = ? AND guid LIKE ?
        ORDER BY published_at DESC, id DESC
        LIMIT 1
        """,
        (subscription_id, normalized + "%"),
    ).fetchone()

def default_rss_transcript_path(root: Path, podcast_name: str, episode: sqlite3.Row) -> Path:
    date_part = format_date(episode["published_at"])
    label = episode_label(episode).lstrip("#")
    filename = f"{date_part}_{label}_{sanitize_filename(episode['title'])}.md"
    return root / "transcripts" / sanitize_filename(podcast_name) / filename

def update_episode_after_transcribe(
    conn: sqlite3.Connection,
    episode_id: int,
    result: TranscribeResult,
) -> None:
    now = utc_now_iso()
    conn.execute(
        """
        UPDATE episodes SET
            status = 'indexed',
            transcript_path = ?,
            transcript_text = ?,
            duration_seconds = ?,
            model = ?,
            indexed_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            str(result.output_path.resolve()),
            result.transcript_text,
            result.duration,
            result.model,
            now,
            now,
            episode_id,
        ),
    )
    row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if row:
        upsert_episode_fts(conn, episode_id, row["title"], row["description"], row["transcript_text"])
    conn.commit()

def query_terms(query: str) -> list[str]:
    terms = [term.strip() for term in re.split(r"\s+", query) if term.strip()]
    return terms or [query.strip()]

def matched_terms(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term.lower() in lowered]

def shorten_snippet(text: str, terms: list[str], width: int = 150) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= width:
        return compact
    lowered = compact.lower()
    hit_positions = [lowered.find(term.lower()) for term in terms if term and lowered.find(term.lower()) >= 0]
    center = hit_positions[0] if hit_positions else 0
    start = max(0, center - width // 3)
    end = min(len(compact), start + width)
    snippet = compact[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(compact):
        snippet += "..."
    return snippet

def search_snippets(text: str, terms: list[str], limit: int = 2) -> list[str]:
    snippets: list[str] = []
    for line in text.splitlines():
        if matched_terms(line, terms):
            snippets.append(shorten_snippet(line, terms))
        if len(snippets) >= limit:
            break
    return snippets

def print_episode_rows(rows: list[sqlite3.Row]) -> None:
    for row in rows:
        status = "已入库" if row["status"] == "indexed" and row["transcript_text"] else "未转录"
        print(f"[{episode_label(row)}] {format_date(row['published_at'])} {status} {row['title']}")

def rss_add(args: argparse.Namespace, config: dict, config_path: Path | None = None) -> int:
    root = library_root(config, args.library_dir, config_path)
    with open_library(root) as conn:
        subscription = add_subscription(conn, args.name, args.rss_url)
    upsert_subscription_json(config_path, args.name, args.rss_url)
    print(f"已添加 RSS: {subscription['name']}")
    print(f"库目录: {root.resolve()}")
    return 0

def rss_sync(args: argparse.Namespace, config: dict, config_path: Path | None = None) -> int:
    root = library_root(config, args.library_dir, config_path)
    with open_library(root) as conn:
        subscription = get_required_subscription(conn, args.name)
        log(f"🌐 读取 RSS: {subscription['rss_url']}")
        podcast_title, episodes = parse_rss_feed(fetch_text(subscription["rss_url"]))
        selected = filter_feed_episodes(episodes, limit=args.limit, days=args.days)
        new_count, updated_count = sync_subscription(conn, subscription, selected)
    upsert_subscription_json(config_path, args.name, subscription["rss_url"], last_synced=utc_now_iso())
    print(f"已同步: {args.name}")
    if podcast_title:
        print(f"RSS 标题: {podcast_title}")
    print(f"入库范围: {len(selected)} 期")
    print(f"新增: {new_count} | 更新: {updated_count}")
    print(f"库目录: {root.resolve()}")
    return 0

def rss_list(args: argparse.Namespace, config: dict, config_path: Path | None = None) -> int:
    root = library_root(config, args.library_dir, config_path)
    with open_library(root) as conn:
        subscription = get_required_subscription(conn, args.name)
        rows = list_episodes(conn, subscription["id"], days=args.days, limit=args.limit)
    print(f"{args.name}: {len(rows)} 期")
    print_episode_rows(rows)
    return 0

def rss_subs(args: argparse.Namespace, config: dict, config_path: Path | None = None) -> int:
    """列出所有已订阅的播客（从 subscriptions.json 读取，同时补充 SQLite 里的信息）。"""
    root = library_root(config, args.library_dir, config_path)
    json_subs = load_subscriptions_json(subscriptions_json_path(None))

    # 从 SQLite 补充 episode 统计
    db_stats: dict[str, dict] = {}
    lib_path = root / "library.sqlite3"
    if lib_path.exists():
        conn = sqlite3.connect(lib_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM subscriptions ORDER BY name").fetchall()
            for row in rows:
                total = conn.execute(
                    "SELECT COUNT(*) FROM episodes WHERE subscription_id = ?", (row["id"],)
                ).fetchone()[0]
                transcribed = conn.execute(
                    "SELECT COUNT(*) FROM episodes WHERE subscription_id = ? AND status = 'indexed' AND transcript_text != ''",
                    (row["id"],),
                ).fetchone()[0]
                db_stats[row["name"]] = {"total": total, "transcribed": transcribed, "rss_url": row["rss_url"]}
        finally:
            conn.close()

    # 合并：以 json_subs 为主，补充 SQLite 中有但 json 没有的
    seen_names = set()
    all_subs = []
    for sub in json_subs:
        name = sub.get("name", "")
        seen_names.add(name)
        entry = {**sub}
        if name in db_stats:
            entry["episodes_total"] = db_stats[name]["total"]
            entry["episodes_transcribed"] = db_stats[name]["transcribed"]
        all_subs.append(entry)
    for name, info in db_stats.items():
        if name not in seen_names:
            all_subs.append({
                "name": name,
                "rss_url": info["rss_url"],
                "added_at": "",
                "last_synced": "",
                "episodes_total": info["total"],
                "episodes_transcribed": info["transcribed"],
            })

    if not all_subs:
        print("还没有添加任何 RSS 订阅。")
        print("使用: python transcribe.py rss add \"播客名\" \"<rss_url>\"")
        return 0

    print(f"共 {len(all_subs)} 个订阅:\n")
    for i, sub in enumerate(all_subs, 1):
        name = sub.get("name", "?")
        rss_url = sub.get("rss_url", "")
        added = sub.get("added_at", "")[:10] if sub.get("added_at") else ""
        synced = sub.get("last_synced", "")[:10] if sub.get("last_synced") else ""
        total = sub.get("episodes_total")
        transcribed = sub.get("episodes_transcribed")
        line = f"[{i}] {name}"
        if total is not None:
            line += f"  ({transcribed}/{total} 期已转录)"
        if added:
            line += f"  添加于 {added}"
        if synced:
            line += f"  最近同步 {synced}"
        print(line)
        print(f"    RSS: {rss_url}")
    return 0


def _load_feeds_catalog(feeds_dir: Path) -> list[dict]:
    """扫描 feeds 目录下的 *.json,返回所有条目(附带 _source_file 和 _category)."""
    all_entries: list[dict] = []
    # 支持 feeds_dir/feeds/ 子目录和 feeds_dir/ 直接放置两种结构
    json_files = sorted(feeds_dir.glob("*.json"))
    feeds_sub = feeds_dir / "feeds"
    if feeds_sub.is_dir():
        json_files = sorted(feeds_sub.glob("*.json"))

    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for entry in data:
                    if entry.get("name") and entry.get("rss_url"):
                        entry["_source_file"] = jf.name
                        entry["_category"] = entry.get("category", jf.stem)
                        all_entries.append(entry)
        except (json.JSONDecodeError, OSError):
            pass
    return all_entries


def rss_browse_feeds(args: argparse.Namespace, config: dict, config_path: Path | None = None) -> int:
    """列出 feeds 目录下所有播客,按分类展示,标注已订阅/未订阅状态."""
    script_dir = Path(__file__).resolve().parent
    feeds_dir = Path(args.feeds_dir) if args.feeds_dir else script_dir / "podscribe-feeds"

    if not feeds_dir.is_dir():
        print(f"未找到 feeds 目录: {feeds_dir}")
        return 1

    all_entries = _load_feeds_catalog(feeds_dir)
    if not all_entries:
        print(f"feeds 目录中没有播客: {feeds_dir}")
        return 1

    # 检查哪些已订阅
    root = library_root(config, args.library_dir, config_path)
    subscribed_names: set[str] = set()
    if root.exists():
        with open_library(root) as conn:
            rows = conn.execute("SELECT name FROM subscriptions").fetchall()
            subscribed_names = {r["name"] for r in rows}

    # 按分类分组
    categories: dict[str, list[dict]] = {}
    for entry in all_entries:
        cat = entry.get("_category", "uncategorized")
        categories.setdefault(cat, []).append(entry)

    total = len(all_entries)
    sub_count = 0
    unsub_count = 0

    for cat, entries in categories.items():
        print(f"\n--- {cat} ({len(entries)}) ---")
        for e in entries:
            name = e["name"]
            # 模糊匹配: feeds 里的名字可能跟 subscriptions 里的略有不同
            is_subbed = any(name in sn or sn in name for sn in subscribed_names)
            if is_subbed:
                sub_count += 1
                status = "[已订阅]"
            else:
                unsub_count += 1
                status = "[未订阅]"
            note = f"  {e.get('note', '')}" if e.get("note") else ""
            print(f"  {status} {name}{note}")

    print(f"\n共 {total} 个播客: {sub_count} 已订阅, {unsub_count} 未订阅")
    print(f"用 rss add-from-feeds \"播客名\" 选择订阅")
    return 0


def rss_add_from_feeds(args: argparse.Namespace, config: dict, config_path: Path | None = None) -> int:
    """从 feeds 目录中按名字挑选播客,加入订阅并同步."""
    script_dir = Path(__file__).resolve().parent
    feeds_dir = Path(args.feeds_dir) if args.feeds_dir else script_dir / "podscribe-feeds"

    if not feeds_dir.is_dir():
        print(f"未找到 feeds 目录: {feeds_dir}")
        return 1

    all_entries = _load_feeds_catalog(feeds_dir)
    if not all_entries:
        print(f"feeds 目录中没有播客: {feeds_dir}")
        return 1

    target = args.name

    # 模糊匹配: 支持部分名字匹配
    matches = [e for e in all_entries if target in e["name"] or e["name"] in target]
    if not matches:
        # 再试试不分大小写的匹配
        target_lower = target.lower()
        matches = [e for e in all_entries if target_lower in e["name"].lower()]
    if not matches:
        print(f"未找到匹配的播客: {target}")
        print("可用播客:")
        for e in all_entries:
            print(f"  {e['name']} ({e.get('_category', '?')})")
        return 1

    if len(matches) > 1:
        print(f"找到多个匹配:")
        for i, m in enumerate(matches, 1):
            note = f"  {m.get('note', '')}" if m.get("note") else ""
            print(f"  [{i}] {m['name']} ({m.get('_category', '?')}){note}")
        print(f"\n请用更精确的名字,例如: rss add-from-feeds \"{matches[0]['name']}\"")
        return 1

    entry = matches[0]
    name = entry["name"]
    rss_url = entry["rss_url"]
    category = entry.get("_category", "")

    # 检查是否已订阅
    root = library_root(config, args.library_dir, config_path)
    with open_library(root) as conn:
        existing = get_subscription(conn, name)
        if existing:
            ep_count = conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE subscription_id = ?", (existing["id"],)
            ).fetchone()[0]
            if ep_count > 0:
                print(f"已订阅: {name} ({ep_count} 期)")
                return 0
            # 有订阅但无数据,重试同步
            subscription = existing
            print(f"重试同步: {name}")
        else:
            # 添加新订阅
            add_subscription(conn, name, rss_url)
            subscription = get_required_subscription(conn, name)
            print(f"已添加: {name}")

        # 同步
        limit = args.limit if args.limit else 50
        print(f"同步中...")
        podcast_title, episodes = parse_rss_feed(fetch_text(rss_url))
        selected = filter_feed_episodes(episodes, limit=limit, days=None)
        new_count, updated_count = sync_subscription(conn, subscription, selected)
        upsert_subscription_json(config_path, name, rss_url, last_synced=utc_now_iso())

    if category:
        print(f"分类: {category}")
    print(f"入库: {new_count} 期")
    print(f"库目录: {root.resolve()}")
    return 0


def rss_sync_feeds(args: argparse.Namespace, config: dict, config_path: Path | None = None) -> int:
    """扫描 podscribe-feeds/*.json,批量添加未入库的播客并同步。需要 --all 或 --category 指定范围。"""
    # 确定 feeds 目录位置
    script_dir = Path(__file__).resolve().parent
    feeds_dir = Path(args.feeds_dir) if args.feeds_dir else script_dir / "podscribe-feeds"

    if not feeds_dir.is_dir():
        print(f"未找到 feeds 目录: {feeds_dir}")
        print(f"请创建 {feeds_dir} 目录并在其中放置分类 JSON 文件。")
        return 1

    all_entries = _load_feeds_catalog(feeds_dir)
    if not all_entries:
        print(f"feeds 目录中没有播客: {feeds_dir}")
        return 1

    # 按 --all / --category 过滤
    category_filter = getattr(args, "category", None)
    import_all = getattr(args, "all", False)

    if not import_all and not category_filter:
        print("请指定导入范围:")
        print(f"  --all          导入全部 {len(all_entries)} 个播客")
        print(f"  --category AI  只导入指定分类")
        print(f"  rss browse-feeds  先看看有哪些可选")
        return 1

    if category_filter:
        filtered = [e for e in all_entries if e.get("_category", "").lower() == category_filter.lower()]
        if not filtered:
            cats = sorted(set(e.get("_category", "?") for e in all_entries))
            print(f"分类 '{category_filter}' 没有匹配的播客")
            print(f"可用分类: {', '.join(cats)}")
            return 1
        all_entries = filtered
        print(f"按分类 '{category_filter}' 过滤,共 {len(all_entries)} 个播客\n")
    else:
        print(f"全部导入,共 {len(all_entries)} 个播客\n")

    root = library_root(config, args.library_dir, config_path)
    added = 0
    skipped = 0
    failed = 0

    with open_library(root) as conn:
        for entry in all_entries:
            name = entry["name"]
            rss_url = entry["rss_url"]
            source = entry.get("_source_file", "?")

            # 检查是否已存在且有数据
            existing = get_subscription(conn, name)
            try:
                if existing:
                    ep_count = conn.execute(
                        "SELECT COUNT(*) FROM episodes WHERE subscription_id = ?", (existing["id"],)
                    ).fetchone()[0]
                    if ep_count > 0:
                        skipped += 1
                        continue
                    # 已添加但无数据,重试同步
                    subscription = existing
                    print(f"  ~ 重试同步: {name}")
                else:
                    # 添加新订阅
                    add_subscription(conn, name, rss_url)
                    subscription = get_required_subscription(conn, name)
                    print(f"  + 已添加: {name}")
                    added += 1

                # 同步最近 N 期
                limit = args.limit if args.limit else 50
                print(f"    同步中...")
                podcast_title, episodes = parse_rss_feed(fetch_text(rss_url))
                selected = filter_feed_episodes(episodes, limit=limit, days=None)
                new_count, updated_count = sync_subscription(conn, subscription, selected)
                upsert_subscription_json(config_path, name, rss_url, last_synced=utc_now_iso())
                print(f"    -> {new_count} 期入库")
            except Exception as e:
                print(f"  x 失败: {name} ({e})")
                failed += 1

    print(f"\n汇总: 新增 {added} 个, 跳过 {skipped} 个(已存在), 失败 {failed} 个")
    print(f"库目录: {root.resolve()}")
    return 0

def rss_transcribe(args: argparse.Namespace, config: dict, config_path: Path | None) -> int:
    root = library_root(config, args.library_dir, config_path)
    settings = build_settings(args, config)
    errors = credential_errors(settings)
    if errors:
        log("❌ 配置缺少必要凭据:")
        for error in errors:
            log(f"   - {error}")
        return 1
    if not args.skip_preflight:
        run_preflight(settings, config_path, None, args.summary)

    with open_library(root) as conn:
        subscription = get_required_subscription(conn, args.name)
        episode = find_episode_by_selector(conn, subscription["id"], args.selector)
        if not episode:
            raise RuntimeError(f"未找到单集: {args.selector}")
        if episode["status"] == "indexed" and episode["transcript_path"] and not args.force:
            print(f"已转录: [{episode_label(episode)}] {episode['title']}")
            print(episode["transcript_path"])
            return 0
        if not episode["audio_url"]:
            raise RuntimeError(f"这期 RSS 没有 audio enclosure,无法转录: {episode['title']}")

        output_path = Path(args.output) if args.output else default_rss_transcript_path(root, subscription["name"], episode)
        source_url = episode["episode_url"] or episode["audio_url"]
        meta = EpisodeMeta(
            title=episode["title"],
            audio_url=episode["audio_url"],
            podcast=subscription["name"],
        )
        result = transcribe_episode(
            settings,
            source_url,
            preflight_meta=meta,
            output_path=output_path,
            summary_mode=args.summary,
            chapters_enabled=args.chapters,
            chapter_window=args.chapter_window,
            clean=args.clean,
        )
        update_episode_after_transcribe(conn, episode["id"], result)

    print(result.output_path.resolve())
    return 0

def rss_search(args: argparse.Namespace, config: dict, config_path: Path | None = None) -> int:
    root = library_root(config, args.library_dir, config_path)
    terms = query_terms(args.query)
    with open_library(root) as conn:
        subscription = get_required_subscription(conn, args.name)
        rows = list_episodes(conn, subscription["id"], days=args.days, limit=args.episodes)

    full_searchable = [row for row in rows if row["transcript_text"]]
    meta_only = [row for row in rows if not row["transcript_text"]]
    full_hits: list[tuple[sqlite3.Row, list[str], list[str]]] = []
    meta_hits: list[tuple[sqlite3.Row, list[str], list[str]]] = []

    for row in rows:
        meta_text = f"{row['title']}\n{row['description']}"
        transcript_text = row["transcript_text"] or ""
        if transcript_text:
            haystack = f"{meta_text}\n{transcript_text}"
            hits = matched_terms(haystack, terms)
            if hits:
                snippets = search_snippets(transcript_text, terms)
                if not snippets and matched_terms(meta_text, terms):
                    snippets = search_snippets(meta_text, terms)
                full_hits.append((row, hits, snippets))
        else:
            hits = matched_terms(meta_text, terms)
            if hits:
                meta_hits.append((row, hits, search_snippets(meta_text, terms, limit=1)))

    print(f"我检查了 {args.name} 的 {len(rows)} 期。")
    if args.days:
        print(f"时间范围: 最近 {args.days} 天")
    print(f"全文可搜索: {len(full_searchable)} 期")
    print(f"仅标题/简介可搜索: {len(meta_only)} 期")
    print(f"检索词: {', '.join(terms)}")
    print("")

    if full_hits:
        print(f"在已转录全文里找到 {min(len(full_hits), args.limit)} 期:")
        for row, hits, snippets in full_hits[:args.limit]:
            print("")
            print(f"[{episode_label(row)}] {row['title']}")
            print(f"发布时间: {format_date(row['published_at'])}")
            print(f"命中: {', '.join(hits)}")
            if row["transcript_path"]:
                print(f"全文: {row['transcript_path']}")
            for snippet in snippets:
                print(f"片段: {snippet}")
    else:
        print("在已转录全文里没有找到命中。")

    if meta_hits:
        remaining = max(0, args.limit - len(full_hits))
        show_meta = meta_hits if remaining == 0 else meta_hits[:remaining]
        print("")
        print(f"另外有 {len(meta_hits)} 期标题/简介可能相关,但还没转录:")
        for row, hits, snippets in show_meta:
            print(f"- [{episode_label(row)}] {format_date(row['published_at'])} {row['title']} (命中: {', '.join(hits)})")
            for snippet in snippets:
                print(f"  简介: {snippet}")

    return 0

def rss_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python transcribe.py rss",
        description="RSS 订阅入库、选择转录和本地搜索",
    )
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--library-dir", default=None, help="播客库目录,默认读取 config.library_dir 或 ./podcast_library")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="添加或更新 RSS 订阅")
    add_parser.add_argument("name", help="订阅名称,如: 日谈公园")
    add_parser.add_argument("rss_url", help="RSS 链接")

    sync_parser = subparsers.add_parser("sync", help="读取 RSS 并把单集元数据入库")
    sync_parser.add_argument("name", help="订阅名称")
    sync_parser.add_argument("--limit", type=int, default=50, help="最多读取多少期,默认 50")
    sync_parser.add_argument("--days", type=int, default=None, help="只同步最近 N 天")

    list_parser = subparsers.add_parser("list", help="列出已入库单集")
    list_parser.add_argument("name", help="订阅名称")
    list_parser.add_argument("--limit", type=int, default=20, help="最多显示多少期,默认 20")
    list_parser.add_argument("--days", type=int, default=None, help="只显示最近 N 天")

    transcribe_parser = subparsers.add_parser("transcribe", help="选择一期 RSS 单集转录并入库")
    transcribe_parser.add_argument("name", help="订阅名称")
    transcribe_parser.add_argument("selector", help="期号、列表里的 #id 或 guid 前缀")
    transcribe_parser.add_argument("--force", action="store_true", help="已转录时强制重新转录")
    transcribe_parser.add_argument("--skip-preflight", action="store_true", help="跳过启动前自检")
    transcribe_parser.add_argument("--output", "-o", default=None, help="输出 Markdown 路径")
    transcribe_parser.add_argument("--segment-seconds", type=int, default=None,
                                   help=f"分段时长(秒),默认 {DEFAULT_SEGMENT_SECONDS}")
    transcribe_parser.add_argument("--workers", type=int, default=None,
                                   help=f"并发请求数,默认 {DEFAULT_WORKERS}")
    transcribe_parser.add_argument("--asr-provider", choices=ASR_PROVIDERS, default=None,
                                   help=f"ASR 引擎,默认 {DEFAULT_ASR_PROVIDER}; bcut/jianying 免费免配置,siliconflow 为旧兼容接口")
    transcribe_parser.add_argument("--free-asr-chunk-minutes", type=int, default=None,
                                   help=f"免费 ASR 长音频切片分钟数,默认 {DEFAULT_FREE_ASR_CHUNK_MINUTES}")
    transcribe_parser.add_argument("--free-asr-overlap-seconds", type=int, default=None,
                                   help=f"免费 ASR 切片重叠秒数,默认 {DEFAULT_FREE_ASR_OVERLAP_SECONDS}")
    transcribe_parser.add_argument("--free-asr-workers", type=int, default=None,
                                   help=f"免费 ASR 分片并发数,默认 {DEFAULT_FREE_ASR_WORKERS}")
    transcribe_parser.add_argument("--model", default=None,
                                   help=f"siliconflow provider 使用的转录模型,默认 {DEFAULT_MODEL}")
    transcribe_parser.add_argument("--api-endpoint", default=None,
                                   help=f"siliconflow provider 使用的 endpoint,默认 {API_ENDPOINT}")
    transcribe_parser.add_argument("--audio-bitrate", default=None,
                                   help=f"转码后的音频码率,默认 {AUDIO_BITRATE}")
    transcribe_parser.add_argument("--keep-audio", action=argparse.BooleanOptionalAction,
                                   default=None, help="保留临时音频文件")
    transcribe_parser.add_argument("--clean", action=argparse.BooleanOptionalAction,
                                   default=True, help="转录后做术语纠错和基础清洗")
    transcribe_parser.add_argument("--chapters", action="store_true", help="在全文稿中写入自动章节")
    transcribe_parser.add_argument("--chapter-window", type=int, default=300,
                                   help="自动章节的时间窗口秒数,默认 300")
    transcribe_parser.add_argument("--summary", nargs="?", const="brief", choices=SUMMARY_MODES,
                                   default=None, help="兼容旧参数: 只表示期望总结风格,摘要由本地 Agent 基于全文生成")

    search_parser = subparsers.add_parser("search", help="搜索已转录全文,并提示未转录的标题/简介命中")
    search_parser.add_argument("name", help="订阅名称")
    search_parser.add_argument("query", help="搜索词,多个词用空格分隔")
    search_parser.add_argument("--days", type=int, default=None, help="只搜索最近 N 天")
    search_parser.add_argument("--episodes", type=int, default=50, help="最多扫描最近多少期,默认 50")
    search_parser.add_argument("--limit", type=int, default=20, help="最多展示多少条命中,默认 20")

    subs_parser = subparsers.add_parser("subs", help="列出所有已订阅的播客")
    subs_parser.add_argument("--library-dir", default=None, help="播客库目录")

    sync_feeds_parser = subparsers.add_parser("sync-feeds", help="批量从 podscribe-feeds 导入并同步(需 --all 或 --category)")
    sync_feeds_parser.add_argument("--feeds-dir", default=None, help="podscribe-feeds 目录路径,默认 transcribe.py 同级的 podscribe-feeds/")
    sync_feeds_parser.add_argument("--limit", type=int, default=50, help="每个播客同步多少期,默认 50")
    sync_feeds_parser.add_argument("--all", action="store_true", help="导入全部播客")
    sync_feeds_parser.add_argument("--category", default=None, help="只导入指定分类,如 AI, tech-business")
    sync_feeds_parser.add_argument("--library-dir", default=None, help="播客库目录")

    browse_feeds_parser = subparsers.add_parser("browse-feeds", help="浏览 feeds 目录下所有可选播客")
    browse_feeds_parser.add_argument("--feeds-dir", default=None, help="podscribe-feeds 目录路径")
    browse_feeds_parser.add_argument("--library-dir", default=None, help="播客库目录")

    add_from_feeds_parser = subparsers.add_parser("add-from-feeds", help="从 feeds 中选择一个播客订阅")
    add_from_feeds_parser.add_argument("name", help="播客名(支持模糊匹配)")
    add_from_feeds_parser.add_argument("--feeds-dir", default=None, help="podscribe-feeds 目录路径")
    add_from_feeds_parser.add_argument("--limit", type=int, default=50, help="同步多少期,默认 50")
    add_from_feeds_parser.add_argument("--library-dir", default=None, help="播客库目录")

    args = parser.parse_args(argv)
    try:
        config, config_path = load_config(args.config)
        if config_path:
            log(f"⚙️  配置文件: {config_path.resolve()}")
        if args.command == "add":
            return rss_add(args, config, config_path)
        if args.command == "sync":
            return rss_sync(args, config, config_path)
        if args.command == "list":
            return rss_list(args, config, config_path)
        if args.command == "subs":
            return rss_subs(args, config, config_path)
        if args.command == "sync-feeds":
            return rss_sync_feeds(args, config, config_path)
        if args.command == "browse-feeds":
            return rss_browse_feeds(args, config, config_path)
        if args.command == "add-from-feeds":
            return rss_add_from_feeds(args, config, config_path)
        if args.command == "transcribe":
            return rss_transcribe(args, config, config_path)
        if args.command == "search":
            return rss_search(args, config, config_path)
        parser.error("未知 RSS 命令")
        return 2
    except Exception as e:
        log(f"❌ {e}")
        return 1

# ============================================================
# 主流程
# ============================================================

def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "rss":
        return rss_main(sys.argv[2:])

    parser = argparse.ArgumentParser(
        description="小宇宙播客 → Markdown 文字稿(默认必剪免费 ASR)",
    )
    parser.add_argument("url", nargs="?", help="小宇宙 episode 链接")
    parser.add_argument("--init", action="store_true",
                        help="交互式生成 config.json 后退出")
    parser.add_argument("--force", action="store_true",
                        help="配合 --init 覆盖已存在的配置文件")
    parser.add_argument("--preflight-only", action="store_true",
                        help="只运行启动前自检,不下载和转录")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="跳过启动前自检")
    parser.add_argument("--config", default=None,
                        help="配置文件路径,默认自动读取 ./config.json 或脚本同目录 config.json")
    parser.add_argument("--output", "-o", default=None, help="输出文件路径")
    parser.add_argument("--segment-seconds", type=int, default=None,
                        help=f"分段时长(秒),默认 {DEFAULT_SEGMENT_SECONDS}")
    parser.add_argument("--workers", type=int, default=None,
                        help=f"并发请求数,默认 {DEFAULT_WORKERS}")
    parser.add_argument("--asr-provider", choices=ASR_PROVIDERS, default=None,
                        help=f"ASR 引擎,默认 {DEFAULT_ASR_PROVIDER}; bcut/jianying 免费免配置,siliconflow 为旧兼容接口")
    parser.add_argument("--free-asr-chunk-minutes", type=int, default=None,
                        help=f"免费 ASR 长音频切片分钟数,默认 {DEFAULT_FREE_ASR_CHUNK_MINUTES}")
    parser.add_argument("--free-asr-overlap-seconds", type=int, default=None,
                        help=f"免费 ASR 切片重叠秒数,默认 {DEFAULT_FREE_ASR_OVERLAP_SECONDS}")
    parser.add_argument("--free-asr-workers", type=int, default=None,
                        help=f"免费 ASR 分片并发数,默认 {DEFAULT_FREE_ASR_WORKERS}")
    parser.add_argument("--model", default=None,
                        help=f"siliconflow provider 使用的转录模型,默认 {DEFAULT_MODEL}")
    parser.add_argument("--api-endpoint", default=None,
                        help=f"siliconflow provider 使用的 endpoint,默认 {API_ENDPOINT}")
    parser.add_argument("--audio-bitrate", default=None,
                        help=f"转码后的音频码率,默认 {AUDIO_BITRATE}")
    parser.add_argument("--keep-audio", action=argparse.BooleanOptionalAction,
                        default=None, help="保留临时音频文件")
    parser.add_argument("--clean", action=argparse.BooleanOptionalAction,
                        default=True, help="转录后做术语纠错和基础清洗")
    parser.add_argument("--chapters", action="store_true",
                        help="在全文稿中写入自动章节")
    parser.add_argument("--chapter-window", type=int, default=300,
                        help="自动章节的时间窗口秒数,默认 300")
    parser.add_argument("--summary", nargs="?", const="brief", choices=SUMMARY_MODES,
                        default=None, help="兼容旧参数: 只表示期望总结风格,摘要由本地 Agent 基于全文生成")
    args = parser.parse_args()

    if args.init:
        return init_config(args.config, force=args.force)

    try:
        config, config_path = load_config(args.config)
        settings = build_settings(args, config)
    except Exception as e:
        log(f"❌ 配置错误: {e}")
        return 1

    if config_path:
        log(f"⚙️  配置文件: {config_path.resolve()}")

    if args.preflight_only:
        try:
            run_preflight(settings, config_path, args.url, args.summary)
        except Exception as e:
            log(f"❌ {e}")
            return 1
        log("✅ 自检通过")
        return 0

    if not args.url:
        parser.error("缺少小宇宙 episode 链接。生成配置请用 --init。")

    errors = credential_errors(settings)
    if errors:
        log("❌ 配置缺少必要凭据:")
        for error in errors:
            log(f"   - {error}")
        return 1

    preflight_meta: EpisodeMeta | None = None
    if not args.skip_preflight:
        try:
            preflight_meta = run_preflight(settings, config_path, args.url, args.summary)
        except Exception as e:
            log(f"❌ {e}")
            return 1

    try:
        result = transcribe_episode(
            settings,
            args.url,
            preflight_meta=preflight_meta,
            output_path=Path(settings.output) if settings.output else None,
            summary_mode=args.summary,
            chapters_enabled=args.chapters,
            chapter_window=args.chapter_window,
            clean=args.clean,
        )
        print(result.output_path.resolve())
        return 0

    except Exception as e:
        log(f"\n❌ 失败: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
