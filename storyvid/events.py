"""Structured progress events: the pipeline appends them, the API turns them into live job progress.

One JSON object per line in `<out>/events.jsonl`. Every run starts with `run_started`; readers
only look at events after the latest one.
"""

import json
import time
from pathlib import Path

EVENTS_FILE = "events.jsonl"


class EventLog:
    def __init__(self, out: Path):
        self.path = Path(out) / EVENTS_FILE

    def emit(self, type: str, **data) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "type": type, **data}) + "\n")


def latest_run(out: Path) -> list[dict]:
    """Events of the most recent run (empty if the pipeline never ran with events)."""
    path = Path(out) / EVENTS_FILE
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # a line being written right now
        if event.get("type") == "run_started":
            events = []
        events.append(event)
    return events
