"""Invent a production title and story from ordered reference images and a short direction."""

import base64
import io
import json
import os
from dataclasses import dataclass

import anthropic
from ollama import Client
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from .vision import FALLBACK_BETA, parse as vision_parse, vision_configured, vision_provider


class StoryDraft(BaseModel):
    title: str = Field(min_length=2, max_length=80, description="A memorable film title, without quotation marks")
    story: str = Field(
        min_length=40,
        max_length=5000,
        description="One self-contained prose paragraph describing the complete short-film story",
    )


@dataclass(frozen=True)
class GeneratedStory:
    title: str
    story: str
    used_images: bool
    note: str


def _image_block(name: str, data: bytes) -> dict:
    """Resize an upload before sending it to a vision model, keeping requests predictable."""
    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((1280, 1280))
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=86, optimize=True)
    except Exception as exc:
        raise RuntimeError(f"Could not prepare {name!r} for story generation: {exc}") from exc
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(out.getvalue()).decode(),
        },
    }


def _brief(direction: str, target_seconds: int, image_count: int, can_see: bool) -> str:
    words = max(55, min(360, round(target_seconds * 1.2)))
    image_instruction = (
        "Treat the supplied images as chronological visual anchors. Preserve the visible people, clothing, "
        "locations and important objects, and invent a compelling progression that naturally connects them."
        if can_see else
        f"There are {image_count} ordered reference images, but this text-only model cannot inspect them. Invent "
        "a visually adaptable story whose protagonist and setting can remain consistent across those anchors."
    )
    return f"""Create an original story for an approximately {target_seconds}-second short film.
Creative direction from the user: {direction.strip()}

{image_instruction}
Choose the title, protagonist, dramatic situation, emotional turn and ending yourself. The result must be
filmable as a clear sequence of visible actions, not an essay or a list. Do not mention prompts, uploads,
reference images, cameras or production instructions. Avoid ungrounded claims about the real identity or private
life of any person shown. Aim for about {words} words in one prose paragraph. Dialogue is optional and must be
brief. Return only the requested structured title and story."""


def _text_story(prompt: str) -> StoryDraft:
    provider = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
    if provider == "ollama":
        model = os.environ.get("OLLAMA_MODEL", "").strip()
        if not model:
            raise RuntimeError("LLM_PROVIDER=ollama needs OLLAMA_MODEL in .env")
        client = Client(host=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": "You create concise, visual short-film stories and obey the JSON schema exactly."},
                {"role": "user", "content": prompt},
            ],
            format=StoryDraft.model_json_schema(),
            options={"temperature": 0.7, "num_ctx": 16384, "num_predict": 2048},
            think=False,
        )
        try:
            return StoryDraft.model_validate(json.loads(response.message.content))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Ollama returned an invalid story: {response.message.content[:800]}") from exc
    if provider != "anthropic":
        raise RuntimeError(f"Unsupported LLM_PROVIDER={provider!r}; use 'anthropic' or 'ollama'")
    response = anthropic.Anthropic().beta.messages.parse(
        model=os.environ.get("CLAUDE_MODEL", "claude-opus-5"),
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
        output_format=StoryDraft,
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined: {getattr(response.stop_details, 'explanation', '')}")
    return response.parsed_output


def generate_story(
    direction: str,
    target_seconds: int,
    references: list[tuple[str, str, bytes]],
) -> GeneratedStory:
    """Generate from images when configured; a local text-only setup falls back transparently."""
    if not direction.strip():
        direction = "Generate an interesting story."
    can_see = vision_configured()
    prompt = _brief(direction, target_seconds, len(references), can_see)
    if can_see:
        content: list[dict] = []
        for index, (role, name, data) in enumerate(references, 1):
            label = "Opening" if role == "opening" else "Final" if role == "ending" else f"Guide {index - 1}"
            content += [{"type": "text", "text": f"{label} reference:"}, _image_block(name, data)]
        content.append({"type": "text", "text": prompt})
        try:
            draft = vision_parse(content, StoryDraft)
            return GeneratedStory(draft.title.strip(), draft.story.strip(), True,
                                  f"Story invented from {len(references)} ordered reference image(s).")
        except RuntimeError:
            # A local text model is sometimes configured as the default vision model even though it cannot
            # accept images. Keep laptop-only creation useful, but never pretend it inspected the pictures.
            if vision_provider() != "ollama":
                raise
    draft = _text_story(_brief(direction, target_seconds, len(references), False))
    return GeneratedStory(
        draft.title.strip(), draft.story.strip(), False,
        "Story invented from the direction only; the configured model cannot inspect images. "
        "The uploads will still guide the rendered shots.",
    )
