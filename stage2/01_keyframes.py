"""Stage 2 / test 1 — can OpenAI image editing keep Elio (and his machine) consistent across scenes?

From the canonical frame: a character turnaround sheet and a prop sheet, then the two scene openers that
drifted in Stage 1 (the workshop at night and the cliff at sunset). Each image is scored against the
canonical look with the same head-crop identity check the pipeline uses.

Stage 1 baselines (video, text-only openers): workshop w1 0.753, cliff c1 0.784; anchored beach b1 0.857.

Run:  uv run python stage2/01_keyframes.py
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

from storyvid.keyframes import KeyframeArtist, fit_frame
from storyvid.qa import CharacterScorer, cosine

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
OUT = ROOT / "productions" / "keyframe-test" / "refs"
CANONICAL = ROOT / "stage0" / "out" / "ltx" / "character_ref.png"
HEAD = "a cartoon boy's head"

BIBLE = (
    "Elio, a cheerful young inventor with messy copper-red hair, big round green eyes, freckles, round brass "
    "goggles pushed up on his forehead and an oversized mustard-yellow raincoat"
)
MACHINE = "a small homemade flying machine made of brass and wood, with patched canvas wings and a single wooden propeller"
SCENES = {
    "workshop": (
        "Elio sits at his cluttered workbench in his workshop at night, lit by a warm desk lamp, tools and blueprints "
        "everywhere, holding the little flying machine up into the lamplight with both hands and gazing at it with "
        "shining eyes. Medium close-up at his eye level."
    ),
    "cliff": (
        "Elio stands at the edge of a grassy cliff top overlooking the sea at sunset, the sky glowing orange and pink, "
        "shading his eyes with one hand as he smiles up at the tiny flying machine circling high above the water. "
        "Medium shot."
    ),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    artist = KeyframeArtist()
    log = {"model": artist.model, "quality": artist.quality, "images": {}}

    sheet = artist.character_sheet(CANONICAL, BIBLE, OUT / "elio_sheet.png")
    print(f"character sheet: {sheet.seconds}s (input_fidelity={sheet.fidelity})", flush=True)
    prop = artist.prop_sheet("machine", MACHINE, CANONICAL, OUT / "machine_sheet.png")
    print(f"prop sheet: {prop.seconds}s", flush=True)
    log["images"] |= {"elio_sheet": sheet.seconds, "machine_sheet": prop.seconds}

    refs = [CANONICAL, sheet.path, prop.path]
    for name, scene in SCENES.items():
        kf = artist.scene_keyframe(refs, scene, OUT / f"kf_{name}.png")
        fit_frame(kf.path, OUT / f"kf_{name}_frame.png")
        log["images"][f"kf_{name}"] = kf.seconds
        print(f"keyframe {name}: {kf.seconds}s", flush=True)

    scorer = CharacterScorer()
    with Image.open(CANONICAL) as im:
        ref = scorer.embed_character(im.convert("RGB"), HEAD)
    scores = {}
    for name in ["elio_sheet", "kf_workshop_frame", "kf_cliff_frame"]:
        with Image.open(OUT / f"{name}.png") as im:
            emb = scorer.embed_character(im.convert("RGB"), HEAD)
        scores[name] = None if emb is None else round(cosine(ref, emb), 3)
    log["identity_vs_canonical"] = scores
    (OUT / "report.json").write_text(json.dumps(log, indent=2))
    print(json.dumps(log, indent=2))


if __name__ == "__main__":
    main()
