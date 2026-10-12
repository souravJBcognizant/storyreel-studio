"""Multi-reference uploads, end-frame plans and editable timelines."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storyvid.api import store
from storyvid.media import Renderer
from storyvid.pipeline import Director, ShotResult, Take
from storyvid.plan import Shot, load_plan


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

    def test_missing_start_references_continue_the_previous_shot_across_scenes(self):
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({
            "title": "Continuity", "style": "Film", "characters": {}, "props": {},
            "scenes": [
                {"id": "one", "setting": "Room", "audio": "Quiet", "shots": [
                    {"id": "s1", "start": "fresh", "action": "One", "seconds": 3},
                    {"id": "s2", "start": "fresh", "action": "Two", "seconds": 3},
                ]},
                {"id": "two", "setting": "Garden", "audio": "Wind", "shots": [
                    {"id": "s3", "start": "fresh", "action": "Three", "seconds": 3},
                ]},
            ],
        }))
        shots = load_plan(plan).shots()
        self.assertEqual([(s.start, s.from_shot) for s in shots],
                         [("fresh", None), ("continue", "s1"), ("continue", "s2")])

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

    def test_continued_shot_extracts_the_previous_take_final_frame(self):
        source = self.root / "previous.mp4"
        anchor = self.root / "anchors" / "s2_from_previous.png"
        director = object.__new__(Director)
        director.out = self.root
        director.results = {
            "s1": ShotResult("s1", "scene", "fresh", "One", None,
                             [Take(0, 1, str(source), 1, False, 3)], 0, False)
        }
        shot = Shot("s2", "scene", "continue", "Two", seconds=3, from_shot="s1")
        with patch("storyvid.pipeline.last_frame", return_value=anchor) as extract:
            self.assertEqual(director._start_image(shot), anchor)
        extract.assert_called_once_with(source, anchor)


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

    def test_shot_references_can_be_added_replaced_and_removed(self):
        with patch.object(store, "PROJECT", self.root), patch.object(store, "PRODUCTIONS", self.productions):
            store.set_shot_reference("test", "s2", "start", "opening.jpg", b"first")
            first_path = self.folder / json.loads(self.plan.read_text())["scenes"][0]["shots"][1]["image"]
            self.assertTrue(first_path.exists())

            store.set_shot_reference("test", "s2", "start", "replacement.png", b"replacement")
            store.set_shot_reference("test", "s2", "end", "ending.webp", b"ending")

            raw = json.loads(self.plan.read_text())
            shot = raw["scenes"][0]["shots"][1]
            self.assertEqual(shot["start"], "anchor")
            self.assertNotIn("from", shot)
            self.assertTrue((self.folder / shot["image"]).exists())
            self.assertTrue((self.folder / shot["end_image"]).exists())
            self.assertFalse(first_path.exists())

            store.remove_shot_reference("test", "s2", "start")
            store.remove_shot_reference("test", "s2", "end")

        raw = json.loads(self.plan.read_text())
        shot = raw["scenes"][0]["shots"][1]
        self.assertEqual(shot["start"], "continue")
        self.assertEqual(shot["from"], "s1")
        self.assertNotIn("image", shot)
        self.assertNotIn("end_image", shot)
        self.assertEqual(json.loads((self.folder / "production.json").read_text())["steps"]["film"], "pending")

    def test_neighbor_take_boundaries_can_become_shot_references(self):
        out = self.folder / "out"
        out.mkdir()
        previous_video, next_video = out / "s1.mp4", out / "s3.mp4"
        previous_video.touch()
        next_video.touch()
        (out / "plan.resolved.json").write_text(json.dumps({
            "s1": {"chosen": 0, "takes": [{"path": str(previous_video)}]},
            "s3": {"chosen": 0, "takes": [{"path": str(next_video)}]},
        }))

        def extract_last(source, target):
            self.assertEqual(source, previous_video)
            target.write_bytes(b"previous-last")
            return target

        def extract_first(source, target):
            self.assertEqual(source, next_video)
            target.write_bytes(b"next-first")
            return target

        with (
            patch.object(store, "PROJECT", self.root),
            patch.object(store, "PRODUCTIONS", self.productions),
            patch.object(store, "last_frame", side_effect=extract_last),
            patch.object(store, "first_frame", side_effect=extract_first),
        ):
            store.set_neighbor_reference("test", "s2", "start")
            store.set_neighbor_reference("test", "s2", "end")

        shot = json.loads(self.plan.read_text())["scenes"][0]["shots"][1]
        self.assertEqual(shot["start"], "anchor")
        self.assertEqual((self.folder / shot["image"]).read_bytes(), b"previous-last")
        self.assertEqual((self.folder / shot["end_image"]).read_bytes(), b"next-first")


if __name__ == "__main__":
    unittest.main()
