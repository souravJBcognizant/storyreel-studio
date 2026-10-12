"""Audio regressions: preserve continuous speech and honor persisted sources in a real MP4."""

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from storyvid import soundtrack
from storyvid.dub import DUB_VERSION, SR, Dub, Dubber, DubError, _stretch, phrase_texts, punctuation_boundaries
from storyvid.edit import load_choices, save_choice, write_json
from storyvid.media import duration, ffmpeg
from storyvid.pipeline import Director, ShotResult, Take
from storyvid.plan import Character, Plan, Scene, Shot


def tone(hz, seconds, sr=SR):
    return (0.2 * np.sin(2 * np.pi * hz * np.arange(round(seconds * sr)) / sr)).astype(np.float32)


class ContinuousDubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.voice = self.root / "voice.wav"
        sf.write(self.voice, tone(230, 1.2), SR, subtype="FLOAT")
        self.dubber = Dubber(None, self.root)
        self.dubber.timings = Mock(return_value=[("one", 0, .4), ("two", .4, .8), ("three", .8, 1.2)])

    def test_word_timing_gaps_do_not_break_up_continuous_speech(self):
        # Old per-word alignment would insert 200–400 ms holes and/or overlap neighbors.
        performance = [("one", 0, .15), ("two", .55, .8), ("three", 1.1, 1.2)]
        result = self.dubber.dub(performance, self.voice, "one two three", 2, original_audio=self.voice)
        active = result.track[200:round(1.2 * SR) - 200]
        windows = active[:len(active) // 240 * 240].reshape(-1, 240)
        self.assertTrue(np.all(np.sqrt(np.mean(windows ** 2, axis=1)) > .1))
        self.assertLess(np.max(np.abs(result.track)), .21)  # no summed/overlapping syllables
        self.assertEqual(len(result.track), 2 * SR)

    def test_missing_timestamp_does_not_drop_a_spoken_word(self):
        performance = [("one", .1, .3), ("two", .3, .6), ("four", .9, 1.3)]
        self.dubber.timings.return_value = [("one", 0, .3), ("two", .3, .6), ("three", .6, .9), ("four", .9, 1.2)]
        original = self.root / "original.wav"
        sf.write(original, np.pad(tone(230, 1.2), (round(.1 * SR), round(.7 * SR))), SR)
        result = self.dubber.dub(performance, self.voice, "one two three four", 2, original_audio=original)
        self.assertEqual(result.words_found, 3)
        # All 1.2 seconds of the recording survive, including the unmatched middle word.
        voiced = result.track[round(.15 * SR):round(1.25 * SR)].reshape(-1, SR // 100)
        self.assertTrue(np.all(np.sqrt(np.mean(voiced ** 2, axis=1)) > .08))

    def test_invalid_and_outside_timings_fail_cleanly(self):
        for span in [("one", 1, 1), ("one", -1, .2), ("one", 9, 10), ("one", 0, float("nan"))]:
            with self.subTest(span=span), self.assertRaises(DubError):
                self.dubber.dub([span], self.voice, "one", 2, original_audio=self.voice)

    def test_matches_original_lead_in_and_pause_without_dropping_tail(self):
        source = np.concatenate([np.zeros(round(.75 * SR)), tone(250, 1), np.zeros(round(.5 * SR)), tone(430, 1)])
        original = np.concatenate([np.zeros(round(.1 * SR)), tone(250, .9), np.zeros(round(.8 * SR)), tone(430, 1.2), np.zeros(round(.3 * SR))])
        sf.write(self.voice, source, SR)
        reference = self.root / "original.wav"
        sf.write(reference, original, SR)
        self.dubber.timings.return_value = [("one", 0, 1.75), ("two", 2.25, 3.25)]
        result = self.dubber.dub([("one", 0, 1), ("two", 1.8, 3)], self.voice, "one two", 3.3, original_audio=reference)
        voiced = np.flatnonzero(np.abs(result.track) > .02) / SR
        self.assertAlmostEqual(voiced[0], .1, delta=.03)
        self.assertAlmostEqual(voiced[-1], 3, delta=.03)
        self.assertLess(np.max(np.abs(result.track[round(1.05 * SR):round(1.75 * SR)])), .002)
        self.assertEqual(len(result.alignment), 2)
        self.assertEqual(len(result.track), round(3.3 * SR))

    def test_local_word_timing_changes_without_breaking_the_phrase(self):
        sf.write(self.voice, np.concatenate([tone(250, .6), tone(430, .6)]), SR)
        reference = self.root / "original.wav"
        sf.write(reference, np.concatenate([tone(250, .84), tone(430, .36)]), SR)
        self.dubber.timings.return_value = [("one", 0, .6), ("two", .6, 1.2)]
        result = self.dubber.dub([("one", 0, .84), ("two", .84, 1.2)], self.voice, "one two", 1.2, original_audio=reference)
        for begin, end, expected in [(.65, .78, 250), (.93, 1.1, 430)]:
            x = result.track[round(begin * SR):round(end * SR)]
            hz = np.argmax(np.abs(np.fft.rfft(x))) * SR / len(x)
            self.assertAlmostEqual(hz, expected, delta=10)
        frames = result.track[480:-480].reshape(-1, 240)
        self.assertGreater(np.min(np.sqrt(np.mean(frames ** 2, axis=1))), .08)

    def test_word_timing_cache_invalidates_when_recording_changes(self):
        dubber = Dubber(Mock(), self.root)
        with patch("storyvid.dub.listen", return_value=("one", [("one", 0, 1.2)])) as recognize:
            dubber.timings(self.voice)
            Dubber(Mock(), self.root).timings(self.voice)  # new process reuses the durable cache
            self.assertEqual(recognize.call_count, 1)
            sf.write(self.voice, tone(400, 1), SR)
            dubber.timings(self.voice)
            self.assertEqual(recognize.call_count, 2)

    def test_directed_line_keeps_words_and_passes_the_delivery_prompt(self):
        target = self.root / "voice" / "directed.wav"

        def generate(prompt, line, out, seed):
            self.assertIn("Calm and warm", prompt)
            self.assertIn("more hesitant", prompt.lower())
            self.assertEqual(line, "The scripted words")
            out.parent.mkdir(parents=True, exist_ok=True)
            sf.write(out, tone(220, 1), SR)
            return out

        with patch("storyvid.casting.Casting.design", side_effect=generate) as design:
            made = self.dubber.directed_line("Calm and warm", "The scripted words", "More hesitant")
        self.assertTrue(made.exists())
        self.assertEqual(design.call_count, 1)

    def test_strong_punctuation_makes_phrase_candidates(self):
        line = "The results... the results scale... I'm sorry."
        boundaries = punctuation_boundaries(line)
        self.assertEqual(boundaries, [2, 5])
        self.assertEqual(phrase_texts(line, boundaries),
                         ["The results...", "the results scale...", "I'm sorry."])

    def test_only_original_pauses_confirm_punctuation_boundaries(self):
        # There is a real pause after "home" but continuous speech before "tonight".
        original = self.root / "original.wav"
        wave = np.concatenate([tone(220, .5), np.zeros(round(.45 * SR)), tone(330, 1.)])
        sf.write(original, wave, SR)
        performance = [("home", 0, .5), ("alone", .95, 1.45), ("tonight", 1.45, 1.95)]
        self.assertEqual(self.dubber.phrase_boundaries("Home. Alone. Tonight.", performance, original, 1.95), [1])

    def test_confirmed_phrases_are_generated_separately_and_joined_with_silence(self):
        calls = []

        def generate(phrase, index):
            calls.append(phrase)
            path = self.root / f"phrase-{index}.wav"
            sf.write(path, tone(220 + index * 20, .4), SR, subtype="FLOAT")
            return path

        made = self.dubber._phrase_line("line", "Home. Alone. Tonight.", [1, 2], generate, b"test")
        audio, _ = sf.read(made, dtype="float32")
        self.assertEqual(calls, ["Home.", "Alone.", "Tonight."])
        self.assertLess(np.max(np.abs(audio[round(.41 * SR):round(.66 * SR)])), 1e-6)
        self.assertEqual(json.loads(made.with_suffix(".phrases.json").read_text())["boundaries"], [1, 2])

    def test_short_off_camera_clip_keeps_last_word(self):
        result = self.dubber.lay_over(self.voice, 1.2)
        self.assertGreater(np.max(np.abs(result.track[-1000:-200])), .19)
        self.assertEqual(len(result.track), round(1.2 * SR))
        with self.assertRaises(DubError):
            self.dubber.lay_over(self.voice, .5)

    def test_stretch_keeps_audible_tail_and_exact_length(self):
        x = tone(310, 1.2)
        for seconds in (1., 1.2, 1.5):
            with self.subTest(seconds=seconds):
                y = _stretch(x, seconds)
                self.assertEqual(len(y), round(seconds * SR))
                self.assertGreater(np.sqrt(np.mean(y[-1000:-200] ** 2)), .05)


class ExportAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "out"
        self.out.mkdir()
        self.video = self.out / "take.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x64:r=24:d=3",
               "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=3",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(self.video))
        sf.write(self.video.with_suffix(".dub.wav"), tone(880, 3), SR)
        self.shot = Shot("s1", "scene", "fresh", "A person speaks", line="Hello there", character="a", speaker="a")
        character = Character("a", "A person", "Clear voice", self.root / "ref.png", [], "person",
                              voice=self.root / "voice.wav", voice_text="Reference")
        self.plan = Plan("Test", 24, 64, 64, "Film", {"a": character}, {}, [Scene("scene", "Room", "Quiet", [self.shot])])
        take = Take(0, 1, str(self.video), 1, True, 3, dub=str(self.video), dub_version=DUB_VERSION, speech=[1., 2.])
        result = ShotResult("s1", "scene", "fresh", "Prompt", None, [take], 0, False)
        write_json(self.out / "plan.resolved.json", {"s1": asdict(result)})

    def export(self):
        # Neither audio source needs a model when the dub is already current.
        with patch("storyvid.pipeline.Renderer", side_effect=AssertionError("must not render")), \
             patch("storyvid.pipeline.Dubber", side_effect=AssertionError("must reuse current dub")):
            Director(self.plan, self.out, assemble_only=True).export()
        audio = soundtrack.decode(self.out / "final.mp4")
        middle = audio[48000:72000]
        return np.argmax(np.abs(np.fft.rfft(middle))) * 48000 / len(middle)

    def test_persisted_original_reaches_export_and_can_switch_back(self):
        from storyvid.api.store import _film

        save_choice(self.out, "s1", "original")
        self.assertEqual(load_choices(self.out), {"s1": "original"})
        self.assertAlmostEqual(self.export(), 220, delta=4)
        self.assertAlmostEqual(duration(self.out / "final.mp4"), 3, delta=.06)
        save_choice(self.out, "s1", "cast")
        resolved = json.loads((self.out / "plan.resolved.json").read_text())
        self.assertTrue(_film(self.out, self.plan, resolved)["audio_pending"])
        self.assertAlmostEqual(self.export(), 880, delta=4)
        self.assertFalse(_film(self.out, self.plan, resolved)["audio_pending"])
        manifest = json.loads((self.out / "edit.json").read_text())
        self.assertEqual(manifest["audio_sources"], {"s1": "cast"})
        self.assertAlmostEqual(manifest["markers"][-1]["end"], duration(self.out / "final.mp4"), delta=.06)

    def test_failed_rebuild_keeps_previous_download(self):
        save_choice(self.out, "s1", "original")
        previous = self.out / "final.mp4"
        previous.write_bytes(b"previous export")
        with patch("storyvid.pipeline.assemble", side_effect=RuntimeError("encoding failed")):
            with self.assertRaisesRegex(RuntimeError, "encoding failed"):
                Director(self.plan, self.out, assemble_only=True).export()
        self.assertEqual(previous.read_bytes(), b"previous export")
        self.assertFalse((self.out / "edit.json").exists())

    def test_old_overlay_is_realigned_during_export_without_rendering_video(self):
        data = json.loads((self.out / "plan.resolved.json").read_text())
        data["s1"]["takes"][0].update(dub_version=2, performance=[("hello", 0, 1.5), ("there", 1.5, 3)])
        write_json(self.out / "plan.resolved.json", data)
        voice = self.root / "voice.wav"
        sf.write(voice, tone(880, 3), SR)
        dubber = Dubber(None, self.root)
        dubber.timings = Mock(return_value=[("hello", 0, 1.5), ("there", 1.5, 3)])
        with patch("storyvid.pipeline.Renderer", side_effect=AssertionError("must not render")), \
             patch("storyvid.pipeline.Dubber", return_value=dubber), \
             patch.object(Director, "_cast_line", return_value=voice):
            Director(self.plan, self.out, assemble_only=True).export()
        take = json.loads((self.out / "plan.resolved.json").read_text())["s1"]["takes"][0]
        self.assertEqual(take["dub_version"], DUB_VERSION)
        self.assertEqual(take["dub_words"], "2/2")
        self.assertTrue(self.video.with_suffix(".dub.alignment.json").exists())
        audio = soundtrack.decode(self.out / "final.mp4")[48000:72000]
        self.assertAlmostEqual(np.argmax(np.abs(np.fft.rfft(audio))) * 48000 / len(audio), 880, delta=4)

    def test_unsyncable_overlay_does_not_silently_replace_previous_film(self):
        director = Director(self.plan, self.out, assemble_only=True)
        take = director.results["s1"].takes[0]
        take.dub_version = 2
        take.performance = [("hello", 0, 1.5), ("there", 1.5, 3)]
        director.dubber = Mock()
        director.dubber.dub.side_effect = DubError("not enough usable timings")
        previous = self.out / "final.mp4"
        previous.write_bytes(b"previous export")
        with patch.object(director, "_cast_line", return_value=self.root / "voice.wav"):
            with self.assertRaisesRegex(DubError, "Choose original audio"):
                director.export()
        director.dubber.lay_over.assert_not_called()
        self.assertEqual(previous.read_bytes(), b"previous export")

    def test_review_fallback_is_not_marked_as_aligned(self):
        director = Director(self.plan, self.out, assemble_only=True)
        director.dubber = Mock()
        director.dubber.dub.side_effect = DubError("not enough usable timings")
        director.dubber.lay_over.return_value = Dubber(None, self.root).lay_over(self.video.with_suffix(".dub.wav"), 3)
        take = director.results["s1"].takes[0]
        director._dub(self.shot, take, self.root / "voice.wav", [])
        self.assertNotEqual(take.dub_version, DUB_VERSION)
        self.assertTrue(any("not enough usable timings" in failure for failure in take.failures))

    def test_overlay_edit_uses_the_prompt_and_keeps_the_script(self):
        director = Director(self.plan, self.out, assemble_only=True)
        take = director.results["s1"].takes[0]
        take.performance = [("hello", 0, 1.4), ("there", 1.4, 2.8)]
        director.dubber = Mock()
        director.dubber.phrase_boundaries.return_value = []
        director.dubber.directed_line.return_value = self.video.with_suffix(".dub.wav")
        with patch.object(director, "_dub") as align, patch.object(director, "_finish_edit") as finish:
            director.edit_overlay("s1", "Quiet and hesitant")
        director.dubber.directed_line.assert_called_once_with("Clear voice", "Hello there", "Quiet and hesitant", [])
        align.assert_called_once()
        finish.assert_called_once()
        self.assertEqual(take.audio_prompt, "Quiet and hesitant")

    def test_clip_edit_appends_and_selects_the_generated_take(self):
        director = Director(self.plan, self.out, assemble_only=True)
        old = director.results["s1"]
        new_take = Take(1, 99, str(self.video), 1, True, 3, edit_prompt="Smaller gesture")
        generated = ShotResult("s1", "scene", "fresh", "new prompt", None, [new_take], 1, False)
        with patch.object(director, "shoot", return_value=generated) as shoot, \
             patch.object(director, "_finish_edit") as finish:
            director.edit_clip("s1", "Smaller gesture")
        shoot.assert_called_once_with(self.shot, direction="Smaller gesture", start_index=1)
        finish.assert_called_once()
        self.assertEqual(len(old.takes), 2)
        self.assertEqual(old.chosen, 1)
        self.assertEqual(old.prompt, "new prompt")

    def test_original_in_mixed_film_does_not_get_a_second_voice(self):
        second = Shot("s2", "scene", "fresh", "A reply", line="Hello again", character="a", speaker="a")
        self.plan.scenes[0].shots.append(second)
        data = json.loads((self.out / "plan.resolved.json").read_text())
        data["s2"] = {**data["s1"], "shot": "s2"}
        write_json(self.out / "plan.resolved.json", data)
        save_choice(self.out, "s1", "original")
        self.assertAlmostEqual(self.export(), 220, delta=4)
        audio = soundtrack.decode(self.out / "final.mp4")
        x = audio[4 * 48000:round(4.5 * 48000)]
        hz = np.argmax(np.abs(np.fft.rfft(x))) * 48000 / len(x)
        self.assertAlmostEqual(hz, 880, delta=4)

    def test_original_dialogue_is_not_reduced_to_ambience_level(self):
        bed = soundtrack.Placed("scene", self.video, 0, 1, 0, bed_source=True)
        original = soundtrack.Placed("scene", self.video, 1, 1, 0, original_dialogue=True)
        mix = np.zeros(2 * soundtrack.SR, dtype=np.float32)
        quiet = np.full(soundtrack.SR, .001, dtype=np.float32)
        loud = np.full(soundtrack.SR, .1, dtype=np.float32)
        with patch("storyvid.soundtrack.decode", return_value=quiet), \
             patch("storyvid.soundtrack._own_sound", side_effect=[quiet, loud]):
            soundtrack._scene(mix, [bed, original], last=True)
        self.assertAlmostEqual(float(mix[round(1.5 * soundtrack.SR)]), .1, places=5)


class AudioChoiceApiTests(unittest.TestCase):
    def setUp(self):
        from storyvid.api import app, jobs, store
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        prod = root / "productions" / "test"
        out = prod / "out"
        out.mkdir(parents=True)
        self.out = out
        plan = prod / "plan.json"
        (prod / "voice.wav").touch()
        plan.write_text(json.dumps({"title": "Test", "style": "Film", "characters": {"a": {
            "bible": "Person", "voice_phrase": "Calm", "canonical_image": "ref.png", "voice_refs": [],
            "head_query": "person", "voice": "voice.wav", "voice_text": "Reference"}}, "scenes": [
            {"id": "scene", "setting": "Room", "audio": "Quiet", "shots": [
                {"id": "s1", "action": "Talks", "line": "Hello", "character": "a"}]}]}))
        (prod / "production.json").write_text(json.dumps({"id": "test", "plan": str(plan), "out": str(out)}))
        write_json(out / "plan.resolved.json", {"s1": {"chosen": 0, "takes": [{"path": str(out / "take.mp4")}]}})
        (out / "take.mp4").touch()
        for target, value in (("storyvid.api.store.PRODUCTIONS", root / "productions"),
                              ("storyvid.api.jobs.PRODUCTIONS", root / "productions"),
                              ("storyvid.api.jobs.PROJECT", root)):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        manager = jobs.JobManager()
        p = patch.object(app, "jobs", manager)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(store, "detail", return_value={"ok": True})
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(app.app)
        self.addCleanup(self.client.close)

    def test_save_validate_and_block_changes_during_export(self):
        url = "/api/productions/test/shots/s1/audio"
        self.assertEqual(self.client.put(url, json={"source": "original"}).status_code, 200)
        self.assertEqual(load_choices(self.out)["s1"], "original")
        self.assertEqual(self.client.put(url, json={"source": "invalid"}).status_code, 422)
        self.assertEqual(self.client.put(url.replace("s1", "missing"), json={"source": "original"}).status_code, 404)
        self.assertEqual(self.client.post("/api/productions/test/shots/s1/regenerate", json={"prompt": "x"}).status_code, 422)
        clip = self.client.post("/api/productions/test/shots/s1/regenerate", json={"prompt": "Use a smaller gesture"})
        self.assertEqual(clip.status_code, 200, clip.text)
        self.assertEqual(clip.json()["kind"], "clip")
        self.assertEqual(clip.json()["shot"], "s1")
        self.assertEqual(clip.json()["prompt"], "Use a smaller gesture")
        self.client.post(f"/api/jobs/{clip.json()['id']}/cancel")
        overlay = self.client.post("/api/productions/test/shots/s1/regenerate-overlay", json={"prompt": "Speak more softly"})
        self.assertEqual(overlay.status_code, 200, overlay.text)
        self.assertEqual(overlay.json()["kind"], "overlay")
        self.client.post(f"/api/jobs/{overlay.json()['id']}/cancel")
        response = self.client.post("/api/productions/test/jobs?kind=export")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["kind"], "export")
        self.assertEqual(self.client.put(url, json={"source": "cast"}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
