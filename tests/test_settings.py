"""Editable provider profiles persist safely and take effect without restarting the API."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values

from storyvid.api import agentnet, config, store
from storyvid.vision import vision_model


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env_file = Path(self.temp.name) / ".env"
        self.original = {key: os.environ.get(key) for key in config.MANAGED_ENV}

    def tearDown(self):
        for key, value in self.original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config._refresh_constants()
        agentnet.network.cache_clear()

    @staticmethod
    def payload(mode: str = "local") -> dict:
        return {
            "mode": mode,
            "claude_model": "claude-main",
            "claude_routine_model": "claude-routine",
            "openai_image_model": "image-main",
            "ollama_base_url": "http://127.0.0.1:11434",
            "ollama_model": "qwen3:4b",
            "ollama_timeout_seconds": 420,
            "ollama_vision_model": "",
        }

    def test_local_profile_preserves_keys_comments_and_unrelated_values(self):
        self.env_file.write_text(
            "# keep this note\nCUSTOM_SETTING=untouched\n"
            "ANTHROPIC_API_KEY=existing-anthropic-secret\nOPENAI_API_KEY=existing-openai-secret\n"
        )
        with patch.object(config, "ENV_FILE", self.env_file):
            result = config.save_settings(self.payload())

        saved = dotenv_values(self.env_file)
        self.assertEqual(saved["CUSTOM_SETTING"], "untouched")
        self.assertEqual(saved["ANTHROPIC_API_KEY"], "existing-anthropic-secret")
        self.assertEqual(saved["OPENAI_API_KEY"], "existing-openai-secret")
        self.assertEqual(saved["LLM_PROVIDER"], "ollama")
        self.assertEqual(saved["LOCAL_MODE"], "true")
        self.assertIn("# keep this note", self.env_file.read_text())
        self.assertEqual(result["mode"], "local")
        self.assertNotIn("existing-anthropic-secret", json.dumps(result))
        self.assertNotIn("existing-openai-secret", json.dumps(result))
        self.assertEqual(store._stages()[1]["engine"], "ollama")

    def test_online_profile_can_replace_and_remove_keys(self):
        self.env_file.write_text("ANTHROPIC_API_KEY=old-one\nOPENAI_API_KEY=old-two\n")
        payload = self.payload("full") | {
            "anthropic_api_key": "replacement-secret",
            "clear_openai_api_key": True,
        }
        with patch.object(config, "ENV_FILE", self.env_file):
            result = config.save_settings(payload)

        saved = dotenv_values(self.env_file)
        self.assertEqual(saved["ANTHROPIC_API_KEY"], "replacement-secret")
        self.assertEqual(saved["OPENAI_API_KEY"], "")
        self.assertEqual(saved["LLM_PROVIDER"], "anthropic")
        self.assertEqual(result["mode"], "full")
        self.assertTrue(result["editable"]["anthropic_key_set"])
        self.assertFalse(result["editable"]["openai_key_set"])
        self.assertNotIn("replacement-secret", json.dumps(result))
        self.assertEqual(store._stages()[1]["engine"], "claude")

    def test_local_profile_requires_a_model(self):
        payload = self.payload() | {"ollama_model": ""}
        with patch.object(config, "ENV_FILE", self.env_file), self.assertRaisesRegex(Exception, "installed Ollama model"):
            config.save_settings(payload)

    def test_local_vision_is_opt_in(self):
        with patch.dict(os.environ, {"VISION_PROVIDER": "ollama", "OLLAMA_MODEL": "text-only"}, clear=False):
            os.environ.pop("OLLAMA_VISION_MODEL", None)
            self.assertEqual(vision_model(), "")


if __name__ == "__main__":
    unittest.main()
