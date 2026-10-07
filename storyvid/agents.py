"""Runs the storyreel agent network (neuro-san, in-process) for one production.

The studio's job runner starts this as its own process, so pre-production gets the same treatment as
renders: durable, cancellable and visible in the app. Every message the agents exchange is appended to
productions/<id>/preprod/events.jsonl for the Activity tab.

Run:  python -m storyvid.agents preprod <production_id>
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

PROJECT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT / ".env")
os.chdir(PROJECT)  # neuro-san resolves AGENT_TOOL_PATH as a module path from here
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("AGENT_MANIFEST_FILE", "agents/registries/manifest.hocon")
os.environ.setdefault("AGENT_TOOL_PATH", "agents.coded_tools")  # a module path; a file path needs PYTHONPATH set

from neuro_san.client.agent_session_factory import AgentSessionFactory  # noqa: E402
from neuro_san.client.streaming_input_processor import StreamingInputProcessor  # noqa: E402

from . import preprod  # noqa: E402

NETWORK = "storyreel"
BRIEF = (
    "Run pre-production for this film: analyse the story and first frame, write the screenplay, cast the "
    "voices, make the reference sheets and each scene's coverage keyframes, and save a validated shot plan."
)


# neuro-san message types (MAXIMAL filter): 2 = input to an agent, 4 = an agent's answer,
# 100 = framework notes (delegations, tool start/end, token usage), 103 = a result returned to the caller,
# 101 = the front man's final answer. Type 1 (each agent's instructions) is skipped.
INPUT, ANSWER, FRAMEWORK, FINAL, RESULT = 2, 4, 100, 101, 103


def _clip(value, n: int = 2000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= n else text[:n] + "…"


def _images(output) -> list[dict] | None:
    """Image paths (and review scores) in a tool's JSON output; the output itself is clipped in the trace."""
    try:
        out = json.loads(output) if isinstance(output, str) else output
    except (TypeError, ValueError):
        return None
    if not isinstance(out, dict):
        return None
    found = [{"path": out[k], "score": (out.get("review") or {}).get("score")} for k in ("frame", "sheet", "prop_sheet") if isinstance(out.get(k), str)]
    found += [{"path": p} for p in (out.get("made") or {}).values() if isinstance(p, str)]
    found += [{"path": r["frame"], "score": (r.get("review") or {}).get("score")} for r in out.get("results") or [] if isinstance(r, dict) and isinstance(r.get("frame"), str)]
    return found or None


def trace_event(message: dict) -> dict | None:
    """One streamed neuro-san message → one compact trace event for the Agents view (or None to skip)."""
    chain = [o.get("tool", "?") for o in message.get("origin") or []]
    path = ".".join(chain)
    kind_of = message.get("type")
    structure = message.get("structure") or {}
    text = message.get("text") or ""
    base = {"path": path, "agent": chain[-1] if chain else None}
    if kind_of == INPUT:
        return {**base, "kind": "input", "text": _clip(text)}
    if kind_of == ANSWER:
        return {**base, "kind": "answer", "text": _clip(text, 6000)}
    if kind_of == RESULT:
        return {**base, "kind": "result", "text": _clip(text)}
    if kind_of == FINAL:
        return {**base, "kind": "final", "text": _clip(text, 6000)}
    if kind_of == FRAMEWORK:
        if structure.get("invoking_start"):
            return {**base, "kind": "invoke", "target": structure.get("invoked_agent_name"), "params": _clip(structure.get("params", {}))}
        if structure.get("tool_start"):
            args = {k: v for k, v in (structure.get("tool_args") or {}).items() if k not in ("origin", "origin_str", "progress_reporter")}
            return {**base, "kind": "tool_start", "caller": chain[-2] if len(chain) > 1 else None, "params": _clip(args)}
        if structure.get("tool_end"):
            output = structure.get("tool_output", "")
            return {**base, "kind": "tool_end", "caller": chain[-2] if len(chain) > 1 else None,
                    "ok": not structure.get("tool_error"), "output": _clip(output, 4000), "images": _images(output)}
        if "total_tokens" in structure:
            return {**base, "kind": "usage", "tokens": structure.get("total_tokens"), "cost": structure.get("total_cost")}
    return None


def run_preprod(pid: str) -> str:
    events = preprod.folder(pid) / "events.jsonl"

    def emit(event: str, **data) -> None:
        with open(events, "a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "type": event, **data}, ensure_ascii=False) + "\n")

    emit("run_started", network=NETWORK)
    session = AgentSessionFactory().create_session("direct", NETWORK)
    processor = StreamingInputProcessor(session=session)
    messages = processor.get_message_processor()
    request = processor.formulate_chat_request(
        BRIEF, sly_data={"production_id": pid}, chat_filter={"chat_filter_type": "MAXIMAL"}
    )
    for chat_response in session.streaming_chat(request):
        message = chat_response.get("response", {})
        messages.process_message(message, chat_response.get("type"))
        trace = trace_event(message)
        if trace:
            emit("trace", **trace)
            if trace["kind"] in ("invoke", "tool_start", "answer"):
                label = trace.get("target") or trace["path"]
                print(f"{time.strftime('%H:%M:%S')} {trace['kind']:10s} {label}", flush=True)
    answer = messages.get_compiled_answer() or ""
    (preprod.folder(pid) / "director_summary.md").write_text(answer)
    emit("run_finished", summary=answer[:6000])
    return answer


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("task", choices=["preprod"])
    ap.add_argument("production")
    args = ap.parse_args()
    try:
        print(run_preprod(args.production))
    except Exception as exc:
        with open(preprod.folder(args.production) / "events.jsonl", "a") as f:
            f.write(json.dumps({"t": time.time(), "type": "run_failed", "error": f"{type(exc).__name__}: {exc}"}) + "\n")
        raise


if __name__ == "__main__":
    main()
