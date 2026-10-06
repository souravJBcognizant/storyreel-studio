# Stage 0 results

Machine: Apple M4 Max, 64 GB, macOS 26 (Darwin 25.5). Date: 2026-10-06.

## Test 1 — voice consistency (Qwen3-TTS via mlx-audio 0.5.8) — PASS

Design once with `Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16`, clone every line with
`Qwen3-TTS-12Hz-1.7B-Base-bf16` from the same `voice_ref.wav`, seed 1234.
Files: `stage0/out/tts/`.

| Clip | Audio | Gen time | Peak mem | resemblyzer vs ref | Whisper heard the right words |
|---|---|---|---|---|---|
| voice_ref (designed) | 8.4 s | 2.3 s | 8.4 GB | — | yes |
| line1_nervous (clone) | 5.5 s | 3.0 s | 8.9 GB | **0.845** | yes |
| line2_excited (clone) | 3.5 s | 1.3 s | 8.5 GB | **0.836** | yes |
| line3_worried (clone) | 2.9 s | 1.0 s | 9.1 GB | **0.869** | yes |
| control: same description, re-designed | 6.4 s | 1.8 s | 8.2 GB | 0.710 | yes |
| control: different voice | 4.6 s | 1.3 s | 7.6 GB | 0.710 | yes |

Findings:
- Clones score 0.84–0.87 against the reference and both controls score 0.71, so a
  **QA gate around 0.78** separates them on this sample (only 3 positives, so recheck in Stage 1).
- **Re-designing the voice per line drifts as far as a completely different voice** (0.71).
  This confirms "design once, clone from the fixed file" as the rule.
- Qwen3-TTS's own speaker encoder scores everything 0.97–0.98, controls included, so it
  cannot tell voices apart. Use resemblyzer as the gate, not the Qwen encoder.
- **Deterministic**: two runs with the same seed gave bit-identical audio, so renders can
  be cached by input hash.
- Fast: about 0.3× real time, under 10 GB peak. Voice is not the bottleneck.
- Median pitch of the reference is about 200 Hz, high for "young adult male", so it may
  read as boyish. **Human listen: approved as Elio's voice.**

## Test 2 — LTX 2.5 text-to-video (distilled, q8, `--low-ram`) — PASS

`dgrauet/ltx-2-mlx` @ `bfa5755`, pack `dgrauet/ltx-2.5-mlx-q8` (75 GB download), 768×512, 97 frames
(4.0 s) at 24 fps, seed 42. Files: `stage0/out/ltx/t2v_character.mp4`, `character_ref.png`, `t2v_contact.png`.

| Phase | Time |
|---|---|
| Load Gemma 4 text encoder | 17.9 s |
| Encode prompt | 8.0 s |
| Stage 1: 8 steps, half-res (1248 video tokens) | ~37 s (4.6 s/step) |
| Stage 2: 3 refine steps, full-res (4992 tokens) | ~55 s (18.3 s/step) |
| Decode video + audio | 9.9 s |
| **Total** | **131 s** for a 4 s clip (about 33× real time) |

Peak Metal memory 27.4 GB, reached during the VAE decode (untiled; budget 32 GB). No swap pressure.

Look: the character matches the bible text closely (copper hair, green eyes, freckles,
brass goggles, yellow raincoat, beach at golden hour, static medium close-up), and his
identity holds across all 8 sampled frames. He reads as a child of about 8–10 rather than a
young adult, which fits the approved voice.

## Test 3 — LTX 2.5 audio-to-video with image anchor — renders; lip-sync needs a human watch

Input: `character_ref.png` (frame-0 anchor) + `line2_excited.wav` ("It works! It actually works!
Look at it go!", 3.52 s) padded with 0.25 s lead-in and tail silence to 97 frames (4.04 s).
Files: `stage0/out/ltx/a2v_line2_final.mp4` (TTS audio remuxed), `a2v_line2.mp4` (model audio), `a2v_contact.png`.

| Phase | Time |
|---|---|
| Gemma load + encode | 15 s |
| Stage 1: 30 steps × 4 passes (CFG + STG + audio guidance), dev model | ~14.3 min (~28 s/step) |
| Stage 2: 3 refine steps, full-res | ~1.5 min (30.4 s/step) |
| Decode | ~10 s |
| **Total** | **992 s (16.5 min)** for a 4 s clip (about 245× real time) |

Peak Metal memory 28.1 GB.

Look (12 frames over the first 3 s): frame 0 matches the anchor; during the silent lead-in
he winds up, then throws both arms up as prompted, with the mouth opening and changing shape
through the line. Identity holds throughout (hair, goggles, eyes, freckles, coat). Whether the
mouth shapes land on the syllables can't be judged from stills.

Bug found and fixed: a2v refuses audio shorter than the clip, and the 8k+1 frame grid always
rounds up. The rule is to pad lines with silence to the clip length (never cut), and to remux
the **same padded file** so sync holds.

## Test 4 — LTX voices the lines itself (joint audio + video, distilled i2v) — PASS (easy case)

Same anchor image (`character_ref.png`), same scene, same seed (42), the same voice phrase
("in a bright, warm, boyish voice") in every prompt, and duration chosen by the 2.5 DurationHead.
Files: `stage0/out/ltx/joint_*.mp4`, `joint_report.json`, `joint_all_contact.png`.

| | TTS clone → a2v (tests 1+3) | LTX joint (test 4) |
|---|---|---|
| Words right (Whisper WER) | 3/3 (0.00) | 3/3 (0.00) |
| Voice similarity across the 3 shots (min / mean) | 0.766 / 0.806 | 0.746 / 0.809 |
| Similarity to the Qwen-designed `voice_ref.wav` | 0.84–0.87 | 0.47–0.59 (a different voice: LTX's own Elio) |
| Render time per dialogue shot | ~992 s | 142–216 s (3.0–5.3 s clips) |
| User's ear | — | **"LTX's own sound is far better"** |

Identity holds in all three shots, and the acting matches each line (nervous, arms-up excited,
reaching out worried). One fast-motion frame in line 2 is smeared.
Caveat: this is the easiest case for voice consistency (same scene, framing, anchor and seed). Test 5 varies all of them.

## Test 5 — LTX's Elio voice across different scenes, seeds and framing (t2v, no anchor) — PASS for voice

Four shots: workshop at night (close-up), rainy street at dusk (tracking), sunny hilltop (push-in),
frustrated in the workshop by day. Seeds 7/13/21/99, the same voice phrase, no anchor image.
Reference = average of the three test-4 beach takes. Files: `stage0/out/ltx/drift/`.

| Shot | Length | Render | Words (WER) | Voice vs LTX-Elio ref |
|---|---|---|---|---|
| workshop | 5.7 s | 228 s | 0.00 | **0.896** |
| rain | 3.0 s | 154 s | 0.00 | **0.850** |
| hill | 5.7 s | 250 s | 0.00 | **0.851** |
| frustrated | 4.0 s | 170 s | 0.00 | **0.872** |
| *calibration: Qwen Elio voice (different boy)* | | | | 0.56–0.57 |
| *calibration: Qwen elderly woman / redesign* | | | | 0.66–0.67 |

- **The voice holds** across scene, lighting, camera and seed changes: 0.85–0.90 for Elio, ≤ 0.67 for
  every other voice. A **0.78 gate** separates them cleanly.
- **Words**: 7/7 LTX-voiced lines perfect so far (lines of 3–6 s).
- **Visual identity without an anchor is "same costume, slightly different actor"**: copper hair, brass
  goggles, green eyes and yellow coat hold, but face shape, nose and hair style (fluffy vs spiky)
  vary between shots. Within a shot identity is stable. Cross-scene visual identity is the next
  problem to solve (per-scene anchor frames, last-frame chaining, then a character LoRA).

## Cost model for planning (measured, 768×512, 24 fps)

- Fast shot (distilled t2v/i2v): ~131 s per 4 s shot.
- Lip-synced dialogue shot (a2v): ~992 s per 4 s shot, about 7.6× a fast shot.
- Untested speed-ups for a2v: `--stg-scale 0` (4→3 passes), `--stage1-steps 20`, `LTX2_COMPUTE_DTYPE=float16`.
