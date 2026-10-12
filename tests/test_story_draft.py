"""AI-invented story mode and its honest text-only fallback."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from storyvid import story_draft
from storyvid.api import store


def jpeg(color: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(out, format="JPEG")
    return out.getvalue()


class StoryDraftTests(unittest.TestCase):
    def test_vision_story_receives_ordered_images(self):
        seen = {}

        def generate(content, schema):
            seen["content"] = content
            self.assertIs(schema, story_draft.StoryDraft)
            return story_draft.StoryDraft(title="The Long Way Home", story="A traveler follows a changing light across the city and discovers that the final destination was waiting beside an old friend.")

        refs = [("opening", "one.jpg", jpeg("red")), ("guide", "two.jpg", jpeg("green")), ("ending", "three.jpg", jpeg("blue"))]
        with patch.object(story_draft, "vision_configured", return_value=True), patch.object(story_draft, "vision_parse", side_effect=generate):
            result = story_draft.generate_story("Make it surprising.", 30, refs)

        labels = [block["text"] for block in seen["content"] if block["type"] == "text"]
        self.assertEqual(labels[:3], ["Opening reference:", "Guide 1 reference:", "Final reference:"])
        self.assertTrue(result.used_images)

    def test_text_only_mode_is_explicit(self):
        draft = story_draft.StoryDraft(title="A Small Surprise", story="A quiet visitor notices a forgotten token, follows its trail, and returns it just as the day ends in an unexpected reunion.")
        with patch.object(story_draft, "vision_configured", return_value=False), patch.object(story_draft, "_text_story", return_value=draft) as generate:
            result = story_draft.generate_story("Generate an interesting story.", 30, [("opening", "one.jpg", b"unused")])

        self.assertFalse(result.used_images)
        self.assertIn("cannot inspect images", result.note)
        self.assertIn("text-only model", generate.call_args.args[0])

    def test_production_records_ai_story_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(store, "PROJECT", root), patch.object(store, "PRODUCTIONS", root / "productions"):
                prod = store.create(
                    "Made by AI", "A complete generated story long enough to save.", "open.jpg", b"open", 30,
                    story_mode="ai", story_prompt="Generate an interesting story.", story_uses_images=False,
                    story_note="The model could not inspect images.",
                )
        self.assertEqual(prod["story_mode"], "ai")
        self.assertEqual(prod["story_prompt"], "Generate an interesting story.")
        self.assertFalse(prod["story_uses_images"])


if __name__ == "__main__":
    unittest.main()
