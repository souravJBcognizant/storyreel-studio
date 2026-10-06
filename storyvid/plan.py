"""The production plan (characters, props, scenes, shots) and how a shot becomes an LTX prompt.

A shot starts one of three ways:
  fresh    — text only; scene openers render several takes and keep the most in-character one
  continue — starts from the last frame of an earlier shot (`from`, default: the previous shot)
  anchor   — starts from a given still (`image`), e.g. the character's canonical frame
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

START_MODES = ("fresh", "continue", "anchor")


@dataclass
class Character:
    id: str
    bible: str  # look, word for word in every prompt
    voice_phrase: str  # voice, word for word in every prompt with a line
    canonical_image: Path
    voice_refs: list[Path]  # approved takes of the voice; their average is the QA reference
    head_query: str  # what the head detector looks for, e.g. "a cartoon boy's head"


@dataclass
class Shot:
    id: str
    scene_id: str
    start: str
    action: str
    camera: str = ""
    line: str | None = None
    seconds: float | None = None  # silent shots; lines let the DurationHead decide
    image: Path | None = None
    from_shot: str | None = None
    character: str | None = None  # None: no character in frame (prop or landscape shot)
    identity_check: bool = True  # off when the character is too small to judge
    takes: int = 1


@dataclass
class Scene:
    id: str
    setting: str
    audio: str
    shots: list[Shot] = field(default_factory=list)


@dataclass
class Plan:
    title: str
    fps: int
    width: int
    height: int
    style: str  # opening sentence for shots without a character
    characters: dict[str, Character]
    props: dict[str, str]
    scenes: list[Scene]

    def shots(self) -> list[Shot]:
        return [shot for scene in self.scenes for shot in scene.shots]

    def scene(self, scene_id: str) -> Scene:
        return next(s for s in self.scenes if s.id == scene_id)


def load_plan(path: Path) -> Plan:
    path = Path(path)
    root = path.parent
    raw = json.loads(path.read_text())

    def resolve(p: str) -> Path:
        q = Path(p).expanduser()
        return q if q.is_absolute() else (root / q).resolve()

    characters = {
        cid: Character(
            id=cid,
            bible=c["bible"],
            voice_phrase=c["voice_phrase"],
            canonical_image=resolve(c["canonical_image"]),
            voice_refs=[resolve(v) for v in c["voice_refs"]],
            head_query=c["head_query"],
        )
        for cid, c in raw["characters"].items()
    }
    scenes = []
    for s in raw["scenes"]:
        scene = Scene(id=s["id"], setting=s["setting"], audio=s["audio"])
        for i, sh in enumerate(s["shots"]):
            start = sh.get("start", "fresh")
            scene.shots.append(
                Shot(
                    id=sh["id"],
                    scene_id=scene.id,
                    start=start,
                    action=sh["action"],
                    camera=sh.get("camera", ""),
                    line=sh.get("line"),
                    seconds=sh.get("seconds"),
                    image=resolve(sh["image"]) if sh.get("image") else None,
                    from_shot=sh.get("from") or (scene.shots[i - 1].id if start == "continue" and i > 0 else None),
                    character=sh.get("character"),
                    identity_check=sh.get("identity_check", True),
                    takes=sh.get("takes", 3 if (i == 0 and start == "fresh" and sh.get("character")) else 1),
                )
            )
        scenes.append(scene)
    plan = Plan(
        title=raw["title"],
        fps=raw.get("fps", 24),
        width=raw.get("width", 768),
        height=raw.get("height", 512),
        style=raw["style"],
        characters=characters,
        props=raw.get("props", {}),
        scenes=scenes,
    )
    _validate(plan)
    return plan


def _validate(plan: Plan) -> None:
    seen: set[str] = set()
    for shot in plan.shots():
        if shot.id in seen:
            raise ValueError(f"duplicate shot id {shot.id}")
        if shot.start not in START_MODES:
            raise ValueError(f"{shot.id}: start must be one of {START_MODES}")
        if shot.start == "continue" and shot.from_shot not in seen:
            raise ValueError(f"{shot.id}: continues from {shot.from_shot!r}, which is not an earlier shot")
        if shot.start == "anchor" and not (shot.image and shot.image.exists()):
            raise ValueError(f"{shot.id}: anchor image {shot.image} not found")
        if shot.character and shot.character not in plan.characters:
            raise ValueError(f"{shot.id}: unknown character {shot.character!r}")
        if shot.line and not shot.character:
            raise ValueError(f"{shot.id}: a line needs a speaking character")
        if not shot.line and not shot.seconds:
            raise ValueError(f"{shot.id}: silent shots need `seconds`")
        seen.add(shot.id)


def build_prompt(plan: Plan, shot: Shot) -> str:
    scene = plan.scene(shot.scene_id)
    action = shot.action.format(**plan.props)
    if shot.line:
        action += f' {plan.characters[shot.character].voice_phrase}: "{shot.line}"'
    opener = plan.characters[shot.character].bible if shot.character else plan.style
    parts = [f"{opener}, {scene.setting}.", action, shot.camera, f"Audio: {scene.audio}."]
    return " ".join(p.strip() for p in parts if p.strip())
