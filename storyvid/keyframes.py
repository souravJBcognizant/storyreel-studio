"""Consistent scenes: keyframes made with OpenAI image editing, then animated by LTX.

Every call sends reference images — the first frame, the characters' turnaround sheets and the prop
sheets — so each keyframe keeps the same people, props and look. Each scene gets coverage: an
establishing frame, and a single (close-up) of every character who speaks in it, made in the same set
and light from the establishing frame. Shots start from these frames (plan `start: "anchor"`), so the
person on screen when a line is spoken is the one saying it.

Prompts never name a character's features: the bible and the reference images carry the look.
"""

import base64
import os
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import openai
from PIL import Image

SIZE = "1536x1024"  # 3:2, the film frame
FILM_FRAME = (768, 512)
NO_TEXT = "No text, captions, labels or watermarks."


@dataclass
class ImageResult:
    path: Path
    seconds: float
    model: str
    fidelity: str | None  # "high" when the model accepted input_fidelity, else None


class KeyframeArtist:
    def __init__(self, model: str | None = None, quality: str = "high"):
        self.client = openai.OpenAI()
        self.model = model or os.environ.get("OPENAI_IMAGE_MODEL") or "gpt-image-2.5-sunburst"
        self.quality = quality
        self._fidelity_ok = True  # flips off if the model rejects input_fidelity

    # ------------------------------------------------------------ primitives

    def edit(self, refs: list[Path], prompt: str, out: Path) -> ImageResult:
        out.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        extra = {"input_fidelity": "high"} if self._fidelity_ok else {}
        try:
            result = self._edit(refs, prompt, extra)
        except openai.BadRequestError as exc:
            if not extra or "fidelity" not in str(exc).lower():
                raise
            self._fidelity_ok = False
            result, extra = self._edit(refs, prompt, {}), {}
        out.write_bytes(base64.b64decode(result.data[0].b64_json))
        return ImageResult(out, round(time.perf_counter() - t0, 1), self.model, extra.get("input_fidelity"))

    def _edit(self, refs: list[Path], prompt: str, extra: dict):
        with ExitStack() as stack:
            files = [stack.enter_context(open(p, "rb")) for p in refs]
            return self.client.images.edit(
                model=self.model, image=files, prompt=prompt, size=SIZE, quality=self.quality, **extra
            )

    def generate(self, prompt: str, out: Path) -> ImageResult:
        out.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        result = self.client.images.generate(model=self.model, prompt=prompt, size=SIZE, quality=self.quality)
        out.write_bytes(base64.b64decode(result.data[0].b64_json))
        return ImageResult(out, round(time.perf_counter() - t0, 1), self.model, None)

    # ------------------------------------------------------------ the studio's three jobs

    def character_sheet(self, canonical: Path, bible: str, out: Path) -> ImageResult:
        prompt = (
            f"Character turnaround sheet of exactly this character: {bible}. Four full-body views side by side — "
            "front, three-quarter, side profile and back — standing in a relaxed neutral pose on a plain warm grey "
            "background with soft even studio light. This one character only. Keep the face, hair, eyes, skin, "
            "build, clothing and accessories identical to how they appear in the reference image, in the same "
            f"style and rendering. {NO_TEXT}"
        )
        return self.edit([canonical], prompt, out)

    def prop_sheet(self, name: str, description: str, style_ref: Path, out: Path) -> ImageResult:
        prompt = (
            f"Prop design sheet for a film: {description}. Show this one object three times — front, side and "
            "three-quarter view — at its real-world size and proportions, on a plain warm grey background with soft "
            "even studio light. Match the style, materials and rendering of the reference image, but do not include "
            f"any character or person. {NO_TEXT}"
        )
        return self.edit([style_ref], prompt, out)

    def scene_keyframe(self, refs: list[Path], scene: str, out: Path) -> ImageResult:
        """The establishing frame: `refs` are the first frame, the sheets of everyone in it, and prop sheets."""
        prompt = (
            f"A single frame from the film, 3:2 landscape, cinematic composition: {scene} "
            "Every person is exactly the character on their turnaround sheet — keep each face, hair, age, skin, "
            "clothing and accessories identical. Every object that has a prop sheet is exactly that object. Same "
            f"style, rendering and color grading as the first reference image. {NO_TEXT}"
        )
        return self.edit(refs, prompt, out)

    def single_keyframe(self, sheet: Path, establishing: Path, props: list[Path], scene: str, out: Path) -> ImageResult:
        """A speaker's single: one character from their sheet, in the set and light of the establishing frame."""
        prompt = (
            "A single frame from the film, 3:2 landscape: a medium close-up of the person on the turnaround sheet "
            f"(first image), in the same set as the second image, with the same light and color grading: {scene} "
            "Their face is turned toward the camera, at least three quarters, lips closed. They are the only person "
            "in frame. Keep their face, hair, age, skin, clothing and accessories identical to the turnaround sheet. "
            f"Any object with a prop sheet is exactly that object. {NO_TEXT}"
        )
        return self.edit([sheet, establishing, *props], prompt, out)


def fit_frame(src: Path, dst: Path, size: tuple[int, int] = FILM_FRAME) -> Path:
    """Centre-crop to the film's 3:2 frame and resize — what LTX anchors on."""
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        target = size[0] / size[1]
        if w / h > target:
            nw = round(h * target)
            im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        elif w / h < target:
            nh = round(w / target)
            im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
        im.resize(size, Image.Resampling.LANCZOS).save(dst)
    return dst
