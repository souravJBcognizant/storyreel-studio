"""Saved per-shot audio choices, independent of generated plans and take caches."""

import json
from pathlib import Path

from .plan import Plan, Shot


def load_choices(out: Path) -> dict[str, str]:
    path = out / "audio-choices.json"
    return json.loads(path.read_text()) if path.exists() else {}


def audio_source(plan: Plan, shot: Shot, choices: dict[str, str]) -> str:
    if not plan.dubbed or not shot.line:
        return "original"
    return choices.get(shot.id, "cast")


def save_choice(out: Path, shot: str, source: str) -> None:
    choices = load_choices(out)
    choices[shot] = source
    write_json(out / "audio-choices.json", choices)


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def load_edit(out: Path) -> dict:
    path = out / "edit.json"
    return json.loads(path.read_text()) if path.exists() else {}
