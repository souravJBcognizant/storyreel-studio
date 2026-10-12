"""Paths, environment and provider settings for the studio API.

API keys live in `<repo>/.env` (gitignored). Only whether a key is set ever leaves this module.
"""

import os
import platform
import subprocess
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT / ".env")

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

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")
CLAUDE_MODEL_ROUTINE = os.environ.get("CLAUDE_MODEL_ROUTINE", "claude-sonnet-5")
OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "")

# Cloud remains the default. A developer can opt into local providers in .env without changing code.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
VISION_PROVIDER = os.environ.get("VISION_PROVIDER", LLM_PROVIDER).strip().lower()
IMAGE_PROVIDER = os.environ.get("IMAGE_PROVIDER", "openai").strip().lower()
LOCAL_MODE = os.environ.get("LOCAL_MODE", "").strip().lower() in ("1", "true", "yes", "on")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "").strip()
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", OLLAMA_MODEL).strip()
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


def _key_set(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


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
