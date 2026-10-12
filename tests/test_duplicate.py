"""A production can be used as an independent starting point."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storyvid.api import store
from storyvid.plan import load_plan


class DuplicateProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.productions = self.root / "productions"
        self.source = self.productions / "original"
        (self.source / "inputs").mkdir(parents=True)
        (self.source / "preprod").mkdir()
        (self.source / "out" / "takes").mkdir(parents=True)
        (self.source / "jobs").mkdir()
        (self.source / "inputs" / "first.png").write_bytes(b"frame")
        take = self.source / "out" / "takes" / "s1.mp4"
        take.write_bytes(b"video")
        plan = self.source / "preprod" / "plan.json"
        plan.write_text(json.dumps({
            "title": "Original", "style": "Film", "characters": {}, "props": {},
            "scenes": [{"id": "scene", "setting": "Room", "audio": "Quiet", "shots": [
                {"id": "s1", "start": "anchor", "image": "../inputs/first.png", "action": "Hold", "seconds": 3}
            ]}],
        }))
        (self.source / "out" / "plan.resolved.json").write_text(json.dumps({
            "s1": {"chosen": 0, "takes": [{"path": str(take)}]}
        }))
        (self.source / "jobs" / "old.json").write_text("{}")
        (self.source / "production.json").write_text(json.dumps({
            "id": "original", "title": "Original", "created": 1, "updated": 1, "source": "Uploaded",
            "story": "An original story long enough to be useful.",
            "first_frame": "productions/original/inputs/first.png",
            "reference_images": [{"role": "opening", "name": "first.png", "path": "productions/original/inputs/first.png"}],
            "plan": "productions/original/preprod/plan.json", "out": "productions/original/out",
            "target_seconds": 30, "steps": {"story": "done", "plan": "done", "render": "done", "assemble": "done", "film": "done"},
        }))

    def test_duplicate_remaps_paths_and_keeps_source_independent(self):
        with patch.object(store, "PROJECT", self.root), patch.object(store, "PRODUCTIONS", self.productions):
            cloned = store.duplicate("original", "A Different Cut")

        target = self.productions / "a-different-cut"
        self.assertEqual(cloned["id"], "a-different-cut")
        self.assertEqual(cloned["source_production"], "original")
        self.assertEqual(cloned["first_frame"], "productions/a-different-cut/inputs/first.png")
        self.assertFalse((target / "jobs").exists())
        self.assertTrue((target / "out" / "takes" / "s1.mp4").exists())
        copied_plan = load_plan(target / "preprod" / "plan.json")
        self.assertEqual(copied_plan.title, "A Different Cut")
        self.assertEqual(copied_plan.shots()[0].image, (target / "inputs" / "first.png").resolve())
        resolved = json.loads((target / "out" / "plan.resolved.json").read_text())
        self.assertEqual(Path(resolved["s1"]["takes"][0]["path"]), target / "out" / "takes" / "s1.mp4")

        (target / "inputs" / "first.png").write_bytes(b"changed")
        self.assertEqual((self.source / "inputs" / "first.png").read_bytes(), b"frame")

    def test_startup_removes_only_the_broken_legacy_demo_registration(self):
        legacy = self.productions / "elios-first-flight"
        legacy.mkdir()
        (legacy / "production.json").write_text(json.dumps({
            "id": "elios-first-flight", "source": "Stage 1 test (hand-written plan)"
        }))
        with patch.object(store, "PRODUCTIONS", self.productions):
            store.cleanup_legacy_import()
        self.assertFalse(legacy.exists())

        legacy.mkdir()
        (legacy / "production.json").write_text(json.dumps({
            "id": "elios-first-flight", "source": "Uploaded"
        }))
        with patch.object(store, "PRODUCTIONS", self.productions):
            store.cleanup_legacy_import()
        self.assertTrue(legacy.exists())


if __name__ == "__main__":
    unittest.main()
