"""Stage 3 / test 3 — the new pre-production tools, called directly (no LLM), on a scratch production.

Casts two voices (local Qwen), makes one single keyframe (OpenAI + Claude review), and saves a good and a
bad shot plan through SavePlan. The scratch production lives in stage3/tooltest/, outside productions/,
so the studio app never lists it.

Run:  uv run python stage3/03_tools_check.py [--keyframe]
"""

import json
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from storyvid import preprod  # noqa: E402
from storyvid.api import store  # noqa: E402

SCRATCH = ROOT / "stage3" / "tooltest"
preprod.PRODUCTIONS = store.PRODUCTIONS = SCRATCH  # module globals the tools read at call time
from agents.coded_tools.storyreel import tools  # noqa: E402

PID = "tooltest"
SRC = ROOT / "productions" / "the-infinity-palette"
V = SRC / "tests" / "voice_first"


def call(tool, **args) -> dict:
    return json.loads(tool().invoke(args, {"production_id": PID}))


def setup() -> None:
    shutil.rmtree(SCRATCH, ignore_errors=True)
    pre = SCRATCH / PID / "preprod"
    (pre / "refs").mkdir(parents=True)
    prod = json.loads((SRC / "production.json").read_text())
    prod.update(id=PID, title="Tool check", plan=None)
    (SCRATCH / PID / "production.json").write_text(json.dumps(prod, indent=2))
    cast = json.loads((SRC / "preprod" / "cast.json").read_text())
    cast["characters"] = [c for c in cast["characters"] if c["id"] in ("andie_navaro", "celeste_cartwright")]
    cast["props"] = {"infinity_palette": cast["props"]["infinity_palette"]}
    (pre / "cast.json").write_text(json.dumps(cast, indent=2))
    play = {"logline": "A test.", "scenes": [{
        "id": "studio", "setting": "Andie's makeup studio, late afternoon", "audio": "Low room tone",
        "opening": "Andie shows Celeste the palette.", "beats": [
            {"action": "Andie holds up the palette."},
            {"action": "Andie, proud", "character": "andie_navaro", "line": "I built it myself. Every shade, every formula."},
            {"action": "Celeste, appraising", "character": "celeste_cartwright", "line": "Clever girl. This could be worth a fortune."},
        ]}]}  # fmt: skip
    (pre / "screenplay.json").write_text(json.dumps(play, indent=2))
    rel = lambda p: str(p.relative_to(ROOT))  # noqa: E731
    kf = {"sheets": {c: rel(SRC / "preprod" / "refs" / f"{c}_sheet.png") for c in ("andie_navaro", "celeste_cartwright")},
          "props": {"infinity_palette": rel(SRC / "preprod" / "refs" / "infinity_palette_prop.png")},
          "scenes": {"studio": {"chosen": 1, "candidates": [{"n": 1, "frame": rel(SRC / "preprod" / "refs" / "kf_studio_v2_frame.png")}],
                                "singles": {"andie_navaro": {"chosen": 1, "candidates": [{"n": 1, "frame": rel(V / "andie_closeup.png")}]}}}}}  # fmt: skip
    (pre / "keyframes.json").write_text(json.dumps(kf, indent=2))
    store.set_step(PID, "plan", "running")


def race_check() -> None:
    """Ten ChooseKeyframe calls at once, as Claude issues them: every choice must survive."""
    from concurrent.futures import ThreadPoolExecutor

    state = preprod.load(PID, "keyframes")
    frame = state["scenes"]["studio"]["candidates"][0]["frame"]
    for i in range(10):
        state["scenes"][f"scene{i}"] = {"chosen": None, "candidates": [{"n": 1, "frame": frame}], "singles": {}}
    preprod.save(PID, "keyframes", state)
    with ThreadPoolExecutor(10) as pool:
        list(pool.map(lambda i: call(tools.ChooseKeyframe, scene_id=f"scene{i}", candidate=1), range(10)))
    kept = sum(1 for i in range(10) if preprod.load(PID, "keyframes")["scenes"][f"scene{i}"]["chosen"] == 1)
    print(f"race check: {kept}/10 parallel choices kept")


def main() -> None:
    setup()
    if "--race" in sys.argv:
        race_check()
        return
    print("ReadProduction:", call(tools.ReadProduction)["already_made"])
    for cid, desc, text in [
        ("andie_navaro", "A warm, clear, low-pitched female voice of a woman in her early thirties, natural American English, grounded and sincere, at a calm pace.",
         "I mix every shade by hand in my little studio, and when a color finally comes out right, it feels like magic."),
        ("celeste_cartwright", "A smooth, measured, cultured female voice of an elegant woman in her late fifties, polished American English, slow and controlled, with quiet authority.",
         "In this business, darling, ideas are cheap. What matters is who owns them, and who has the patience to wait."),
        ("celeste_cartwright", "A warm, clear, low-pitched female voice of a woman in her early thirties, natural American English, grounded and sincere, at a calm pace.",
         "I mix every shade by hand in my little studio, and when a color finally comes out right, it feels like magic."),
    ]:  # the third deliberately copies Andie's voice: it must be refused as too alike
        r = call(tools.CastVoice, character_id=cid, description=desc, text=text)
        print(f"CastVoice {cid}: ok={r.get('ok')} seconds={r.get('seconds')} likeness={r.get('likeness')} problems={r.get('problems') or r.get('error')}")
    print("voice step:", store._read(PID)["steps"].get("voice"), "| chosen:", {c: v["chosen"] for c, v in call(tools.ReadVoices).items()})

    if "--keyframe" in sys.argv:
        r = call(tools.MakeKeyframes, frames=[{"scene_id": "studio", "character_id": "celeste_cartwright",
                 "description": "Celeste turns the Infinity Palette in her hands with a cool, appraising half smile."}])  # fmt: skip
        for x in r.get("results", []):
            print(f"MakeKeyframes: {x['frame']} review score {x['review']['score']} same={x['review']['same_character']} single_ok={x['review']['single_ok']} → {x['advice']}")
        print("errors:", r.get("errors"))
        if r.get("results"):
            print("ChooseKeyframe:", call(tools.ChooseKeyframe, scene_id="studio", character_id="celeste_cartwright", candidate=r["results"][0]["n"]))
    else:  # without a fresh image, reuse the close-up made in test 1
        state = preprod.load(PID, "keyframes")
        state["scenes"]["studio"]["singles"]["celeste_cartwright"] = {"chosen": 1, "candidates": [{"n": 1, "frame": str((V / "celeste_closeup.png").relative_to(ROOT))}]}
        preprod.save(PID, "keyframes", state)

    good = [{"id": "studio", "shots": [
        {"id": "s1", "start": "establishing", "action": "Andie holds up the {infinity_palette}.", "seconds": 4, "camera": "Static."},
        {"id": "s2", "start": "single", "character": "andie_navaro", "action": "Andie says proudly", "line": "I built it myself. Every shade, every formula."},
        {"id": "s3", "start": "single", "character": "celeste_cartwright", "action": "Celeste says coolly", "line": "Clever girl. This could be worth a fortune."},
        {"id": "s4", "start": "continue", "from": "s2", "character": "andie_navaro", "delivery": "off", "speaker": "celeste_cartwright",
         "action": "Andie listens.", "line": "Think it over, darling.", "seconds": 3},
    ]}]  # fmt: skip
    r = call(tools.SavePlan, scenes=good)
    print("SavePlan (good):", r)
    plan = json.loads((SCRATCH / PID / "preprod" / "plan.json").read_text()) if r.get("ok") else None
    if plan:
        print("  characters:", {c: {k: v for k, v in d.items() if k in ("name", "sheet", "voice", "voice_text")} for c, d in plan["characters"].items()})
        print("  shot starts:", [(s["id"], s["start"], s.get("image", "")[-30:]) for s in plan["scenes"][0]["shots"]])
    bad = json.loads(json.dumps(good))
    bad[0]["shots"][2].update(start="continue")  # Celeste's line continuing Andie's shot
    print("SavePlan (speaker rule):", call(tools.SavePlan, scenes=bad))
    bad = json.loads(json.dumps(good))
    bad[0]["shots"].append({"id": "s5", "start": "fresh", "character": "andie_navaro", "action": "Andie smiles.", "seconds": 3})
    print("SavePlan (fresh character):", call(tools.SavePlan, scenes=bad))


if __name__ == "__main__":
    main()
