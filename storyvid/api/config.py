"""Paths, environment and provider settings for the studio API.

API keys live in `<repo>/.env` (gitignored). Only whether a key is set ever leaves this module.
The Settings page may update the managed values and reload them without restarting the API.
"""

import json
import os
import platform
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException
from dotenv import dotenv_values, load_dotenv

PROJECT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT / ".env"
MANAGED_ENV = (
    "LOCAL_MODE", "LLM_PROVIDER", "VISION_PROVIDER", "IMAGE_PROVIDER",
    "ANTHROPIC_API_KEY", "CLAUDE_MODEL", "CLAUDE_MODEL_ROUTINE",
    "OPENAI_API_KEY", "OPENAI_IMAGE_MODEL",
    "OLLAMA_BASE_URL", "OLLAMA_MODEL", "OLLAMA_TIMEOUT_SECONDS", "OLLAMA_VISION_MODEL",
)
_EXTERNAL_ENV = {key: os.environ.get(key) for key in MANAGED_ENV}
load_dotenv(ENV_FILE)

PRODUCTIONS = PROJECT / "productions"
CACHE = PROJECT / ".cache"
MODEL_DIR = PROJECT / "models" / "ltx-2.5-mlx-q8"
RUNTIME_DIR = PROJECT / "ltx-2-mlx"

# Everything the file browser and media endpoint may serve.
FILE_ROOTS = {
    "productions": PRODUCTIONS,
    "stage0": PROJECT / "stage0" / "out",
    "stage1": PROJECT / "stage1" / "out",
}

def _refresh_constants() -> None:
    global CLAUDE_MODEL, CLAUDE_MODEL_ROUTINE, OPENAI_IMAGE_MODEL
    global LLM_PROVIDER, VISION_PROVIDER, IMAGE_PROVIDER, LOCAL_MODE
    global OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_VISION_MODEL
    global LOCAL_IMAGE_BASE_URL, LOCAL_IMAGE_API_KEY, LOCAL_IMAGE_MODEL
    global LLM_MODEL, LLM_MODEL_ROUTINE, VISION_MODEL, IMAGE_MODEL
    global LLM_ENGINE, VISION_ENGINE, IMAGE_ENGINE

    CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5").strip() or "claude-opus-5"
    CLAUDE_MODEL_ROUTINE = os.environ.get("CLAUDE_MODEL_ROUTINE", "claude-sonnet-5").strip() or "claude-sonnet-5"
    OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "").strip()
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
    VISION_PROVIDER = os.environ.get("VISION_PROVIDER", LLM_PROVIDER).strip().lower()
    IMAGE_PROVIDER = os.environ.get("IMAGE_PROVIDER", "openai").strip().lower()
    LOCAL_MODE = os.environ.get("LOCAL_MODE", "").strip().lower() in ("1", "true", "yes", "on")
    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "").strip()
    OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "").strip()
    LOCAL_IMAGE_BASE_URL = os.environ.get("LOCAL_IMAGE_BASE_URL", "").rstrip("/")
    LOCAL_IMAGE_API_KEY = os.environ.get("LOCAL_IMAGE_API_KEY", "local")
    LOCAL_IMAGE_MODEL = os.environ.get("LOCAL_IMAGE_MODEL", "").strip()
    LLM_MODEL = OLLAMA_MODEL if LLM_PROVIDER == "ollama" else CLAUDE_MODEL
    LLM_MODEL_ROUTINE = OLLAMA_MODEL if LLM_PROVIDER == "ollama" else CLAUDE_MODEL_ROUTINE
    VISION_MODEL = OLLAMA_VISION_MODEL if VISION_PROVIDER == "ollama" else CLAUDE_MODEL
    IMAGE_MODEL = LOCAL_IMAGE_MODEL if IMAGE_PROVIDER == "local" else OPENAI_IMAGE_MODEL
    LLM_ENGINE = "ollama" if LLM_PROVIDER == "ollama" else "claude"
    VISION_ENGINE = "ollama" if VISION_PROVIDER == "ollama" else "claude"
    IMAGE_ENGINE = "local" if IMAGE_PROVIDER == "local" else "openai"


_refresh_constants()


def _key_set(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def _editable() -> dict:
    try:
        timeout = int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "600") or 600)
    except ValueError:
        timeout = 600
    return {
        "anthropic_key_set": _key_set("ANTHROPIC_API_KEY"),
        "openai_key_set": _key_set("OPENAI_API_KEY"),
        "claude_model": CLAUDE_MODEL,
        "claude_routine_model": CLAUDE_MODEL_ROUTINE,
        "openai_image_model": OPENAI_IMAGE_MODEL,
        "ollama_base_url": OLLAMA_BASE_URL,
        "ollama_model": OLLAMA_MODEL,
        "ollama_timeout_seconds": timeout,
        "ollama_vision_model": OLLAMA_VISION_MODEL,
    }


def _env_line(key: str, value: str) -> str:
    return f"{key}={json.dumps(value, ensure_ascii=False)}"


def _write_env(updates: dict[str, str]) -> None:
    """Update active managed assignments while preserving comments and unrelated settings."""
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else [
        "# Storyreel Studio settings. This file stays on this computer and is ignored by Git.",
    ]
    assignment = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=")
    written: set[str] = set()
    output: list[str] = []
    for line in lines:
        match = assignment.match(line)
        key = match.group(1) if match else None
        if key not in updates:
            output.append(line)
        elif key not in written:
            output.append(_env_line(key, updates[key]))
            written.add(key)
    missing = [key for key in updates if key not in written]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# Managed by the Storyreel Studio Settings page")
        output.extend(_env_line(key, updates[key]) for key in missing)
    tmp = ENV_FILE.with_name(".env.tmp")
    tmp.write_text("\n".join(output).rstrip() + "\n")
    tmp.chmod(ENV_FILE.stat().st_mode & 0o777 if ENV_FILE.exists() else 0o600)
    tmp.replace(ENV_FILE)


def reload_settings() -> dict:
    """Reload the managed .env values into this API process and future job subprocesses."""
    values = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
    for key in MANAGED_ENV:
        value = values.get(key)
        if value is not None:
            os.environ[key] = value
        elif _EXTERNAL_ENV[key] is not None:
            os.environ[key] = _EXTERNAL_ENV[key] or ""
        else:
            os.environ.pop(key, None)
    _refresh_constants()
    return settings()


def save_settings(values: dict) -> dict:
    """Validate an editable profile, persist it to .env, and activate it for subsequent work."""
    mode = values.get("mode")
    if mode not in ("full", "local"):
        raise HTTPException(422, "choose Online or Local Ollama mode")

    def clean(name: str, default: str = "") -> str:
        value = str(values.get(name, default)).strip()
        if "\n" in value or "\r" in value or len(value) > 1000:
            raise HTTPException(422, f"{name.replace('_', ' ')} is invalid")
        return value

    ollama_model = clean("ollama_model")
    ollama_url = clean("ollama_base_url", "http://127.0.0.1:11434").rstrip("/")
    if mode == "local" and not ollama_model:
        raise HTTPException(422, "choose an installed Ollama model before switching to local mode")
    parsed = urlparse(ollama_url)
    if not parsed.scheme in ("http", "https") or not parsed.netloc:
        raise HTTPException(422, "Ollama base URL must be an http:// or https:// address")
    timeout = values.get("ollama_timeout_seconds", 600)
    if not isinstance(timeout, int) or not 10 <= timeout <= 3600:
        raise HTTPException(422, "Ollama timeout must be between 10 and 3,600 seconds")

    updates = {
        "LOCAL_MODE": "true" if mode == "local" else "false",
        "LLM_PROVIDER": "ollama" if mode == "local" else "anthropic",
        "VISION_PROVIDER": "ollama" if mode == "local" else "anthropic",
        "IMAGE_PROVIDER": "local" if mode == "local" else "openai",
        "CLAUDE_MODEL": clean("claude_model", "claude-opus-5") or "claude-opus-5",
        "CLAUDE_MODEL_ROUTINE": clean("claude_routine_model", "claude-sonnet-5") or "claude-sonnet-5",
        "OPENAI_IMAGE_MODEL": clean("openai_image_model"),
        "OLLAMA_BASE_URL": ollama_url,
        "OLLAMA_MODEL": ollama_model,
        "OLLAMA_TIMEOUT_SECONDS": str(timeout),
        "OLLAMA_VISION_MODEL": clean("ollama_vision_model"),
    }
    for field, key in (("anthropic_api_key", "ANTHROPIC_API_KEY"), ("openai_api_key", "OPENAI_API_KEY")):
        if values.get(f"clear_{field}"):
            updates[key] = ""
        elif values.get(field) is not None:
            updates[key] = clean(field)
    _write_env(updates)
    return reload_settings()


@lru_cache(maxsize=1)
def machine() -> dict:
    def sysctl(key: str) -> str:
        return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True).stdout.strip()

    mem = sysctl("hw.memsize")
    return {
        "chip": sysctl("machdep.cpu.brand_string") or platform.processor(),
        "memory_gb": round(int(mem) / 2**30) if mem.isdigit() else None,
        "os": f"macOS {platform.mac_ver()[0]}" if platform.mac_ver()[0] else platform.platform(),
    }


def settings() -> dict:
    pack = sorted(MODEL_DIR.glob("*.safetensors")) if MODEL_DIR.exists() else []
    rev = subprocess.run(["git", "-C", str(RUNTIME_DIR), "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()  # fmt: skip
    return {
        "mode": "local" if LOCAL_MODE else "full",
        "editable": _editable(),
        "providers": {
            "language": {
                "name": "Ollama" if LLM_PROVIDER == "ollama" else "Claude",
                "provider": LLM_PROVIDER,
                "configured": bool(OLLAMA_MODEL) if LLM_PROVIDER == "ollama" else _key_set("ANTHROPIC_API_KEY"),
                "env_var": "OLLAMA_MODEL" if LLM_PROVIDER == "ollama" else "ANTHROPIC_API_KEY",
                "model": LLM_MODEL,
                "routine_model": LLM_MODEL_ROUTINE,
                "role": "Story analysis, screenplay, shot planning and problem solving",
            },
            "vision": {
                "name": "Ollama" if VISION_PROVIDER == "ollama" else "Claude",
                "provider": VISION_PROVIDER,
                "configured": bool(OLLAMA_VISION_MODEL) if VISION_PROVIDER == "ollama" else _key_set("ANTHROPIC_API_KEY"),
                "env_var": "OLLAMA_VISION_MODEL" if VISION_PROVIDER == "ollama" else "ANTHROPIC_API_KEY",
                "model": VISION_MODEL or None,
                "role": "First-frame analysis, keyframe review and speaker checks",
            },
            "images": {
                "name": "Local image service" if IMAGE_PROVIDER == "local" else "OpenAI",
                "provider": IMAGE_PROVIDER,
                "configured": bool(LOCAL_IMAGE_BASE_URL and LOCAL_IMAGE_MODEL) if IMAGE_PROVIDER == "local" else _key_set("OPENAI_API_KEY"),
                "env_var": "LOCAL_IMAGE_BASE_URL and LOCAL_IMAGE_MODEL" if IMAGE_PROVIDER == "local" else "OPENAI_API_KEY",
                "model": IMAGE_MODEL or None,
                "role": "Character sheets, prop sheets and consistent scene keyframes",
            },
        },
        "engine": {
            "name": "LTX-2.5 (MLX, q8)",
            "runtime": "dgrauet/ltx-2-mlx",
            "runtime_rev": rev or None,
            "model_present": bool(pack),
            "model_gb": round(sum(p.stat().st_size for p in pack) / 1e9, 1),
        },
        "machine": machine(),
    }
