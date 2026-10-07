"""Pre-production state and the Claude vision helpers the agent network's tools call.

Everything the agents decide is saved as validated JSON under productions/<id>/preprod/, so each step
is durable, visible in the app (Files tab) and replayable:

  cast.json        characters (look + voice wording), props, style        ← StoryAnalyst
  screenplay.json  scenes (setting, sound) and beats with dialogue        ← Screenwriter
  voices.json      each speaking character's cast voice (voices/*.wav)    ← CastingDirector
  keyframes.json   reference sheets; per scene an establishing frame and
                   a single of every character who speaks in it          ← KeyframeArtist
  plan.json        the shot plan the render pipeline runs (storyvid.plan)  ← ShotPlanner
"""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from .vision import image_block, parse

PROJECT = Path(__file__).resolve().parents[1]
PRODUCTIONS = PROJECT / "productions"


# ------------------------------------------------------------------ schemas


class Character(BaseModel):
    id: str = Field(description="lowercase slug, e.g. 'elio'")
    name: str
    bible: str = Field(description="One sentence describing exactly how the character looks; reused word for word in every prompt")
    voice_phrase: str = Field(description="Short fixed wording for the voice, e.g. 'in a bright, warm, boyish voice'")
    head_query: str = Field(description="What a detector should look for to find their head, e.g. \"a cartoon boy's head\"")


class Cast(BaseModel):
    style: str = Field(description="Opening sentence for shots without characters, e.g. 'A 3D animated stylized cartoon scene in a warm, colorful animated-feature style'")
    characters: list[Character]
    props: dict[str, str] = Field(default_factory=dict, description="prop id → locked one-line description")


class Beat(BaseModel):
    action: str
    character: str | None = None
    line: str | None = Field(default=None, description="Dialogue, at most 10 words")
    delivery: str | None = Field(default=None, description="How it is said, e.g. 'shouts excitedly'")


class ScreenplayScene(BaseModel):
    id: str
    setting: str = Field(description="Where and when, e.g. 'in his cluttered workshop at night, lit by a warm desk lamp'")
    audio: str = Field(description="Continuous ambient sound, e.g. 'the faint ticking of clocks'; no one-off events")
    opening: str = Field(description="The opening frame of the scene: who is where, doing what, framing")
    beats: list[Beat]


class Screenplay(BaseModel):
    logline: str
    scenes: list[ScreenplayScene]


class FrameDescription(BaseModel):
    style: str
    characters: list[str] = Field(description="Every visible character described precisely: face, hair, eyes, skin, clothing, accessories")
    setting: str
    lighting: str
    framing: str


class KeyframeReview(BaseModel):
    same_character: bool = Field(description="Is every person in the frame unmistakably the character on their sheet?")
    differences: list[str] = Field(description="Visible differences from the sheets in face, hair, age, clothing or style")
    matches_scene: bool = Field(description="Does the image show the requested scene and action?")
    prop_ok: bool = Field(description="Is each prop the same object as on its prop sheet (or absent if not required)?")
    single_ok: bool = Field(default=True, description="For a single: exactly one person, face toward the camera, lips closed")
    score: int = Field(ge=1, le=10, description="Overall continuity score")
    verdict: str


# ------------------------------------------------------------------ state


def folder(pid: str) -> Path:
    d = PRODUCTIONS / pid / "preprod"
    d.mkdir(parents=True, exist_ok=True)
    return d


def production(pid: str) -> dict:
    return json.loads((PRODUCTIONS / pid / "production.json").read_text())


def first_frame(pid: str) -> Path:
    return (PROJECT / production(pid)["first_frame"]).resolve()


def save(pid: str, name: str, model: BaseModel | dict) -> Path:
    data = model.model_dump() if isinstance(model, BaseModel) else model
    f = folder(pid) / f"{name}.json"
    f.write_text(json.dumps(data, indent=2))
    return f


def load(pid: str, name: str) -> dict | None:
    f = folder(pid) / f"{name}.json"
    return json.loads(f.read_text()) if f.exists() else None


# ------------------------------------------------------------------ Claude vision


_image_block = image_block
_parse = parse


def describe_frame(path: Path) -> FrameDescription:
    return _parse(
        [
            _image_block(path),
            {"type": "text", "text": (
                "This is the opening frame of an animated short film. Describe it for a production bible: the "
                "rendering style, every character precisely enough to redraw them identically (face shape, hair, "
                "eyes, skin, clothing, accessories, apparent age), the setting, the lighting and the framing. "
                "Describe only what is visible."
            )},
        ],
        FrameDescription,
    )


def review_keyframe(sheets: dict[str, Path], props: dict[str, Path], keyframe: Path, scene: str,
                    single: str | None = None) -> KeyframeReview:  # fmt: skip
    """Claude as continuity supervisor: does the candidate match the character and prop sheets?

    `sheets` maps each character's name to their turnaround sheet; `single` names the one person a
    single (close-up) must show.
    """
    content = []
    for name, sheet in sheets.items():
        content += [{"type": "text", "text": f"Turnaround sheet of {name}:"}, _image_block(sheet)]
    for name, sheet in props.items():
        content += [{"type": "text", "text": f"Prop sheet — {name}:"}, _image_block(sheet)]
    ask = (
        f"The keyframe should show: {scene}\n"
        "You are the continuity supervisor. Judge strictly whether every person in the candidate is the character "
        "on their sheet (ignore lighting and pose; look at face shape, hair, eyes, skin, age, clothing, accessories "
        "and rendering style), whether it shows the requested scene, and whether any prop matches its prop sheet. "
        "List concrete differences."
    )
    if single:
        ask += (f" This is a single of {single}: they must be the only person in frame, face turned toward the "
                "camera at least three quarters, lips closed. Set single_ok accordingly.")  # fmt: skip
    content += [{"type": "text", "text": "Candidate keyframe:"}, _image_block(keyframe), {"type": "text", "text": ask}]
    return _parse(content, KeyframeReview)
