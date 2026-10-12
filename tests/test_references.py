"""Multi-reference uploads, end-frame plans and editable timelines."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storyvid.api import store
from storyvid.media import Renderer
from storyvid.plan import load_plan


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_create_keeps_ordered_opening_guides_and_ending(self):
        productions = self.root / "productions"
        with patch.object(store, "PROJECT", self.root), patch.object(store, "PRODUCTIONS", productions):
            prod = store.create("References", "A story long enough for this test production.", "open.jpg", b"open", 30,
                                guide_frames=[("one.png", b"one"), ("two.webp", b"two")],
                                final_frame=("end.jpg", b"end"))
        self.assertEqual([r["role"] for r in prod["reference_images"]], ["opening", "guide", "guide", "ending"])
        self.assertEqual([Path(r["path"]).name for r in prod["reference_images"]],
                         ["first_frame.jpg", "guide_01.png", "guide_02.webp", "final_frame.jpg"])

    def test_plan_loads_and_validates_an_end_frame(self):
        end = self.root / "end.png"
        end.write_bytes(b"image")
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({
            "title": "End", "style": "Film", "characters": {}, "props": {},
            "scenes": [{"id": "one", "setting": "Room", "audio": "Quiet", "shots": [
                {"id": "s1", "start": "fresh", "action": "Hold", "seconds": 3, "end_image": "end.png"}
            ]}],
        }))
        self.assertEqual(load_plan(plan).shots()[0].end_image, end.resolve())

    def test_cache_key_includes_the_final_reference(self):
        renderer = object.__new__(Renderer)
        renderer.width, renderer.height, renderer.fps = 768, 512, 24
        renderer.auto_duration = "3:8"
        renderer.model_dir = Path("model")
        renderer.runtime_rev = "abc"
        start, end1, end2 = (self.root / name for name in ("start.png", "end1.png", "end2.png"))
        start.write_bytes(b"start")
        end1.write_bytes(b"one")
        end2.write_bytes(b"two")
        self.assertNotEqual(renderer.cache_key("prompt", 1, 97, start, end1),
                            renderer.cache_key("prompt", 1, 97, start, end2))


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.productions = self.root / "productions"
        self.folder = self.productions / "test"
        self.folder.mkdir(parents=True)
        self.plan = self.folder / "plan.json"
        self.plan.write_text(json.dumps({
            "title": "Timeline", "style": "Film", "characters": {}, "props": {},
            "scenes": [{"id": "scene", "setting": "Room", "audio": "Quiet", "shots": [
                {"id": "s1", "start": "fresh", "action": "One", "seconds": 3},
                {"id": "s2", "start": "continue", "from": "s1", "action": "Two", "seconds": 3},
                {"id": "s3", "start": "fresh", "action": "Three", "seconds": 3},
            ]}],
        }))
        (self.folder / "production.json").write_text(json.dumps({
            "id": "test", "plan": "productions/test/plan.json", "out": "productions/test/out",
            "updated": 0, "steps": {"render": "done", "assemble": "done", "film": "done"},
        }))

    def test_reorder_repairs_a_continuation_and_marks_film_stale(self):
        with patch.object(store, "PROJECT", self.root), patch.object(store, "PRODUCTIONS", self.productions):
            store.reorder_shots("test", "scene", ["s2", "s1", "s3"])
        raw = json.loads(self.plan.read_text())
        self.assertEqual([s["id"] for s in raw["scenes"][0]["shots"]], ["s2", "s1", "s3"])
        self.assertEqual(raw["scenes"][0]["shots"][0]["start"], "fresh")
        self.assertEqual(json.loads((self.folder / "production.json").read_text())["steps"]["film"], "pending")

    def test_delete_removes_a_shot_from_the_timeline(self):
        with patch.object(store, "PROJECT", self.root), patch.object(store, "PRODUCTIONS", self.productions):
            store.delete_shot("test", "s2")
        self.assertEqual([s["id"] for s in json.loads(self.plan.read_text())["scenes"][0]["shots"]], ["s1", "s3"])


if __name__ == "__main__":
    unittest.main()
