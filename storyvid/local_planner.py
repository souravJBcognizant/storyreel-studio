"""Reliable structured pre-production for small local Ollama models.

Small models can reason about a story but often stop after describing the tool call they should make.
This runner keeps the same validated tools and durable files as the agent network while asking Ollama
for one constrained JSON artifact at a time: cast, screenplay, voices, then shots.
"""

import json
import os
import re
from typing import Callable

from ollama import Client

from agents.coded_tools.storyreel.tools import CastVoice, SaveCast, SavePlan, SaveScreenplay

from . import preprod

Emit = Callable[..., None]


VOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["description", "text"],
}


def normalize_screenplay(data: dict, cast: dict, *, allow_dialogue: bool = True) -> None:
    """Repair predictable small-model slips before the strict screenplay validator runs."""
    cast_ids = [character["id"] for character in cast.get("characters", [])]
    used: set[str] = set()
    for i, scene in enumerate(data.get("scenes", []), 1):
        slug = "".join(ch if ch.isalnum() else "_" for ch in scene.get("id", "").lower()).strip("_") or f"scene_{i}"
        while slug in used:
            slug += f"_{i}"
        scene["id"] = slug
        used.add(slug)
        for beat in scene.get("beats", []):
            if not allow_dialogue:
                beat["line"] = None
                beat["delivery"] = None
                continue
            if beat.get("line") and not beat.get("character"):
                if len(cast_ids) == 1:
                    beat["character"] = cast_ids[0]
                else:
                    # A crowd chant, song or other ensemble sound has no single cast voice to clone. Keep the
                    # visual action (which usually already describes it) and treat the quoted text as ambience.
                    beat["line"] = None
                    beat["delivery"] = None


class LocalPlanner:
    def __init__(self, pid: str, emit: Emit):
        self.pid = pid
        self.emit = emit
        self.prod = preprod.production(pid)
        self.client = Client(host=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
        self.model = os.environ["OLLAMA_MODEL"]

    def _event(self, kind: str, step: str, text: str = "") -> None:
        self.emit("trace", path=f"LocalPlanner.{step}", agent=step, kind=kind, text=text)

    def _dialogue_allowed(self) -> bool:
        direction = self.prod.get("story_prompt") or ""
        return not re.search(r"\b(?:no|without)\s+(?:spoken\s+)?(?:dialogue|speech|speaking|voices?)\b", direction, re.I)

    def _ask(self, step: str, schema: dict, prompt: str) -> dict:
        self._event("input", step, prompt[:1200])
        response = self.client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a concise film pre-production planner. Follow the JSON schema exactly. Use only facts in the supplied written story; you cannot see uploaded images."},
                {"role": "user", "content": prompt},
            ],
            format=schema,
            options={"temperature": 0, "num_ctx": 32768, "num_predict": 8192},
            think=False,
        )
        data = json.loads(response.message.content)
        self._event("answer", step, json.dumps(data, ensure_ascii=False)[:6000])
        return data

    def _save(self, step: str, tool, key: str | None, schema: dict, prompt: str) -> dict:
        feedback = ""
        for _ in range(3):
            data = self._ask(step, schema, prompt + feedback)
            if key == "cast":
                for character in data.get("characters", []):
                    character["bible"] = re.sub(r"\s*Voice_phrase\s*:.*$", "", character.get("bible", ""), flags=re.I).strip()
                    phrase = character.get("voice_phrase", "")
                    if "voice" not in phrase.lower() or len(phrase.split()) > 12:
                        character["voice_phrase"] = "in a warm, clear, mature voice"
            if key == "screenplay":
                cast = preprod.load(self.pid, "cast") or {"characters": []}
                normalize_screenplay(data, cast, allow_dialogue=self._dialogue_allowed())
                desired = max(1, round(self.prod["target_seconds"] / 4))
                scenes = data.get("scenes", [])
                if scenes:
                    protagonist = cast["characters"][0]["name"] if cast["characters"] else "The subject"
                    fillers = [
                        f"{protagonist} takes in the surroundings as the light shifts subtly.",
                        "The camera lingers on a quiet detail in the setting while the atmosphere continues.",
                        f"{protagonist} pauses for a reflective beat before the final moment.",
                    ]
                    while sum(len(scene.get("beats", [])) for scene in scenes) < desired:
                        beats = scenes[-1].setdefault("beats", [])
                        beat = {"action": fillers[(desired - len(beats)) % len(fillers)],
                                "character": None, "line": None, "delivery": None}
                        beats.insert(max(1, len(beats) - 1), beat)
            self._event("tool_start", step, f"Validating {key or 'plan'}")
            try:
                result = tool.run(self.pid, {key: data} if key else data)
            except Exception as exc:
                result = {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"]}
            self.emit("trace", path=f"LocalPlanner.{step}", agent=step, kind="tool_end",
                      output=json.dumps(result, ensure_ascii=False)[:4000], ok=result.get("ok", False))
            if result.get("ok"):
                return data
            feedback = "\nYour previous JSON was rejected. Return a complete corrected replacement. Errors: " + json.dumps(result)
        raise RuntimeError(f"{step} could not produce valid {key or 'plan'}: {result}")

    def run(self) -> str:
        story = self.prod["story"]
        target = self.prod["target_seconds"]
        cast = preprod.load(self.pid, "cast")
        if not cast:
            cast = self._save(
                "StoryAnalyst", SaveCast(), "cast", preprod.Cast.model_json_schema(),
                f"""Create the cast bible for this {target}-second film from the written story below.
Use one practical photorealistic cinematic style. Include only story characters. Each character bible is one
40-70 word sentence covering face, hair, apparent age, clothing and signature accessories. Clothing belongs
in the bible, not props. voice_phrase is short and neutral. Use at most three recurring physical props.
Story:\n{story}""",
            )
        play = preprod.load(self.pid, "screenplay")
        screenplay_changed = False
        if play:
            before = json.dumps(play, sort_keys=True)
            normalize_screenplay(play, cast, allow_dialogue=self._dialogue_allowed())
            if json.dumps(play, sort_keys=True) != before:
                preprod.save(self.pid, "screenplay", play)
                screenplay_changed = True
            checked = SaveScreenplay().run(self.pid, {"screenplay": play})
            if not checked.get("ok"):
                play = None
        if not play:
            beats = max(5, round(target / 4))
            play = self._save(
                "Screenwriter", SaveScreenplay(), "screenplay", preprod.Screenplay.model_json_schema(),
                f"""Write a screenplay for this film using exactly the character ids in the cast. Use exactly 1
or 2 scenes and about {beats} beats TOTAL, not per scene. Scene ids are lowercase slugs. The first beat of every
scene is silent: line, character and delivery are null. Preserve important story dialogue word for word exactly
once, with at most 10 words per line. Most beats are silent actions. Actions create a clear visual progression.
Cast:\n{json.dumps(cast)}\nStory:\n{story}""",
            )
            screenplay_changed = True

        speakers = list(dict.fromkeys(
            beat["character"] for scene in play["scenes"] for beat in scene["beats"]
            if beat.get("line") and beat.get("character")
        ))
        voices = preprod.load(self.pid, "voices") or {}
        cast_by_id = {c["id"]: c for c in cast["characters"]}
        for cid in speakers:
            if (voices.get(cid) or {}).get("chosen"):
                continue
            spec = self._ask(
                "CastingDirector", VOICE_SCHEMA,
                f"""Design a voice for {json.dumps(cast_by_id[cid])}. The description must specify gender,
apparent age, pitch, timbre, natural accent, pace and manner. The reference text must be 18-24 ordinary words,
not screenplay dialogue, without shouting or whispering.""",
            )
            if not 18 <= len(spec["text"].split()) <= 26:
                spec["text"] = ("This moment feels full of possibility, and I am grateful to be here, "
                                "listening carefully as the world changes around us.")
            result = None
            for attempt in range(2):
                self._event("tool_start", "CastingDirector", f"Casting {cid}")
                result = CastVoice().run(self.pid, {"character_id": cid, **spec})
                self.emit("trace", path="LocalPlanner.CastingDirector", agent="CastingDirector", kind="tool_end",
                          output=json.dumps(result, ensure_ascii=False), ok=result.get("ok", False))
                if result.get("ok"):
                    break
                # The speech model's pace varies. A deliberately longer retry remains a natural reference.
                spec["text"] = ("Standing here in the gentle light, I can hear the world moving around me, and I feel "
                                "quietly thankful for every surprising turn in this beautiful journey today.")
            if not result or not result.get("ok"):
                raise RuntimeError(f"voice casting failed for {cid}: {(result or {}).get('problems')}")
            voices = preprod.load(self.pid, "voices") or {}

        if not preprod.load(self.pid, "plan") or screenplay_changed:
            plan_scenes = []
            for scene in play["scenes"]:
                shots = []
                for i, beat in enumerate(scene["beats"], 1):
                    character = beat.get("character")
                    line = beat.get("line")
                    start = "continue" if shots else "fresh"
                    shot = {
                        "id": f"{scene['id'][:8]}_{i}", "start": start, "action": beat["action"],
                        "camera": ("Wide establishing shot. Static camera." if i == 1 else
                                   "Medium close-up. Slow push-in." if line else "Medium shot. Gentle camera move."),
                        "character": character, "delivery": "on", "identity_check": bool(character and i != 1),
                        "takes": 1,
                    }
                    if line:
                        shot.update(line=line, speaker=character)
                    else:
                        shot["seconds"] = 4
                    shots.append(shot)
                plan_scenes.append({"id": scene["id"], "shots": shots})
            self._event("tool_start", "ShotPlanner", "Building a validated shot timeline")
            result = SavePlan().run(self.pid, {"scenes": plan_scenes})
            self.emit("trace", path="LocalPlanner.ShotPlanner", agent="ShotPlanner", kind="tool_end",
                      output=json.dumps(result, ensure_ascii=False), ok=result.get("ok", False))
            if not result.get("ok"):
                raise RuntimeError(f"deterministic local shot plan was rejected: {result}")
        plan = preprod.load(self.pid, "plan")
        shot_count = sum(len(s["shots"]) for s in plan["scenes"])
        from .api import store

        store.set_step(self.pid, "plan", "awaiting_approval")
        store.set_step(self.pid, "keyframes", "skipped")
        if not speakers:
            store.set_step(self.pid, "voice", "skipped")
        summary = f"Local planning complete: {len(cast['characters'])} character(s), {len(play['scenes'])} scene(s), {shot_count} shots, and {len(speakers)} cast voice(s)."
        self._event("answer", "LocalPlanner", summary)
        return summary


def run_local_preprod(pid: str, emit: Emit) -> str:
    return LocalPlanner(pid, emit).run()
