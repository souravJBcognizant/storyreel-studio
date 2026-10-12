import unittest

from storyvid.local_planner import normalize_screenplay


class LocalPlannerRepairTests(unittest.TestCase):
    def test_speakerless_ensemble_line_becomes_ambience(self):
        screenplay = {"scenes": [{"id": "Crowd Scene", "beats": [{
            "action": "The whole crowd raises its scarves and chants.",
            "character": None,
            "line": "Together!",
            "delivery": "in unison",
        }]}]}
        cast = {"characters": [{"id": "one"}, {"id": "two"}]}
        normalize_screenplay(screenplay, cast)
        beat = screenplay["scenes"][0]["beats"][0]
        self.assertEqual(screenplay["scenes"][0]["id"], "crowd_scene")
        self.assertIsNone(beat["line"])
        self.assertIsNone(beat["delivery"])

    def test_speakerless_line_uses_the_only_cast_member(self):
        screenplay = {"scenes": [{"id": "Room", "beats": [{"action": "A greeting", "line": "Hello"}]}]}
        normalize_screenplay(screenplay, {"characters": [{"id": "leila"}]})
        self.assertEqual(screenplay["scenes"][0]["beats"][0]["character"], "leila")

    def test_explicit_silent_direction_removes_all_dialogue(self):
        screenplay = {"scenes": [{"id": "Crowd", "beats": [{
            "action": "The family cheers.", "character": "leila", "line": "We did it!", "delivery": "joyful"
        }]}]}
        normalize_screenplay(screenplay, {"characters": [{"id": "leila"}]}, allow_dialogue=False)
        beat = screenplay["scenes"][0]["beats"][0]
        self.assertIsNone(beat["line"])
        self.assertIsNone(beat["delivery"])


if __name__ == "__main__":
    unittest.main()
