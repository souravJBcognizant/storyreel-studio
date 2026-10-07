"""The production plan (characters, props, scenes, shots) and how a shot becomes an LTX prompt.

A shot starts one of three ways:
  fresh    — text only; scene openers render several takes and keep the most in-character one
  continue — starts from the last frame of an earlier shot (`from`, default: the previous shot)
  anchor   — starts from a given still (`image`), e.g. the speaker's close-up keyframe

A line is delivered on camera (LTX performs it, then the speaker's cast voice is dubbed over it word by
word) or off camera (the picture shows someone listening, or no one, and the cast voice is laid over it).
`character` is who is in the frame and `speaker` who says the line; on camera they are the same person.
A plan is dubbed when every speaking character has a cast voice; older plans keep LTX's own voice.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

START_MODES = ("fresh", "continue", "anchor")
DELIVERIES = ("on", "off")


@dataclass
class Character:
    id: str
    bible: str  # look, word for word in every prompt
    voice_phrase: str  # voice, word for word in every prompt with a line
    canonical_image: Path
    voice_refs: list[Path]  # approved takes of the voice; their average is the QA reference
    head_query: str  # what the head detector looks for, e.g. "a cartoon boy's head"
    voice: Path | None = None  # cast voice: the reference every line is cloned from
    voice_text: str | None = None  # what is said in that reference
    name: str = ""  # as the cast sheets and the speaker check call them; defaults to the id, title-cased
    sheet: Path | None = None  # character sheet the speaker check recognizes them by (else canonical_image)


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
    delivery: str = "on"  # lines only: "on" camera (dubbed performance) or "off" camera (voice over the picture)
    speaker: str | None = None  # who says the line; the character in frame unless the line is off camera


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
    line_seconds: tuple[float, float] = (3.0, 8.0)  # clamp for the predicted length of shots with a line
    # How long an on-camera line's shot is: "auto" lets LTX's DurationHead decide; "voice" (dubbed plans)
    # gives it the cast voice's length plus a short lead-in and tail, so no render time goes on dead air.
    line_timing: str = "auto"

    @property
    def dubbed(self) -> bool:
        speakers = {s.speaker for s in self.shots() if s.line}
        return bool(speakers) and all(self.characters[c].voice for c in speakers if c in self.characters)

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
            voice=resolve(c["voice"]) if c.get("voice") else None,
            voice_text=c.get("voice_text"),
            name=c.get("name") or cid.replace("_", " ").title(),
            sheet=resolve(c["sheet"]) if c.get("sheet") else None,
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
                    # "off_camera": true; plans from before it was named that say "delivery": "off"
                    delivery="off" if sh.get("off_camera") else sh.get("delivery", "on"),
                    speaker=(sh.get("speaker") or sh.get("character")) if sh.get("line") else None,
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
        line_seconds=tuple(raw.get("line_seconds", (3.0, 8.0))),
        line_timing=raw.get("line_timing", "auto"),
    )
    _validate(plan)
    return plan


def _validate(plan: Plan) -> None:
    if plan.line_timing not in ("auto", "voice"):
        raise ValueError('line_timing must be "auto" or "voice"')
    if plan.line_timing == "voice" and any(s.line for s in plan.shots()) and not plan.dubbed:
        raise ValueError('line_timing "voice" needs a cast voice for every speaking character')
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
        if shot.line and not shot.speaker:
            raise ValueError(f"{shot.id}: a line needs a speaking character")
        if shot.speaker and shot.speaker not in plan.characters:
            raise ValueError(f"{shot.id}: unknown speaker {shot.speaker!r}")
        if shot.line and shot.delivery == "on" and shot.speaker != shot.character:
            raise ValueError(f"{shot.id}: an on-camera line is said by the character in frame; make it off camera or change the character")
        if not shot.line and not shot.seconds:
            raise ValueError(f"{shot.id}: silent shots need `seconds`")
        if shot.delivery not in DELIVERIES:
            raise ValueError(f'{shot.id}: for a line heard off camera set "off_camera": true; how a line is said '
                             f"({shot.delivery!r}) belongs in the action")
        if shot.line and shot.delivery == "off" and not shot.seconds:
            raise ValueError(f"{shot.id}: an off-camera line needs `seconds` for its picture")
        if shot.line and shot.delivery == "off" and not plan.dubbed:
            raise ValueError(f"{shot.id}: off-camera lines need a cast voice for every speaking character")
        seen.add(shot.id)
    for c in plan.characters.values():
        if c.voice and not c.voice.exists():
            raise ValueError(f"{c.id}: cast voice {c.voice} not found")
        if c.voice and not c.voice_text:
            raise ValueError(f"{c.id}: a cast voice needs `voice_text`, what is said in it")


def speaker_problems(plan: Plan) -> list[str]:
    """Coverage rules: the person on screen when a line is spoken must be the one saying it.

    LTX makes whoever is in the frame say the line, so an on-camera line must open on its speaker (their
    close-up keyframe) or continue a shot of that same speaker; and a shot that continues another one keeps
    its person. These are separate from _validate so older plans still load and render as they were made.
    """
    by_id = {s.id: s for s in plan.shots()}
    names = {cid: c.name for cid, c in plan.characters.items()}
    problems = []
    for shot in plan.shots():
        prev = by_id.get(shot.from_shot) if shot.start == "continue" else None
        if shot.line and shot.delivery == "on":
            who = names[shot.character]
            if shot.start == "fresh":
                problems.append(f"{shot.id}: {who}'s line is on camera but the shot has no start frame; open it on {who}'s close-up")
            if prev and prev.character != shot.character:
                problems.append(f"{shot.id}: {who}'s line continues {prev.id}, which shows {names.get(prev.character, 'no one')}; cut to {who}'s close-up instead")
        elif prev and shot.character and prev.character not in (None, shot.character):
            problems.append(f"{shot.id}: continues {prev.id}, which shows {names[prev.character]}, but this shot is about {names[shot.character]}")
    return problems


def build_prompt(plan: Plan, shot: Shot) -> str:
    scene = plan.scene(shot.scene_id)
    action = shot.action.format(**plan.props)
    if shot.line and shot.delivery == "on":
        action += f' {plan.characters[shot.speaker].voice_phrase}: "{shot.line}"'
        if plan.dubbed:
            action += " Only they speak; anyone else in view listens silently."
    elif plan.dubbed:
        # Every voice in a dubbed film is laid in afterwards, and silent shots supply the scene's ambience,
        # so nobody on screen may talk.
        action = action.rstrip() + ("" if action.rstrip().endswith((".", "!", "?")) else ".") + " No one speaks."
    opener = plan.characters[shot.character].bible if shot.character else plan.style
    parts = [f"{opener}, {scene.setting}.", action, shot.camera, f"Audio: {scene.audio}."]
    return " ".join(p.strip() for p in parts if p.strip())
