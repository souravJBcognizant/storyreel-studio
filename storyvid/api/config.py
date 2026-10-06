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
        "providers": {
            "anthropic": {
                "configured": _key_set("ANTHROPIC_API_KEY"),
                "env_var": "ANTHROPIC_API_KEY",
                "model": CLAUDE_MODEL,
                "routine_model": CLAUDE_MODEL_ROUTINE,
                "role": "Story analysis, planning, keyframe review, problem solving",
            },
            "openai": {
                "configured": _key_set("OPENAI_API_KEY"),
                "env_var": "OPENAI_API_KEY",
                "model": OPENAI_IMAGE_MODEL or None,
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
