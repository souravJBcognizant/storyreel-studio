# Stage 1 review — "Elio's First Flight"

Run: `uv run python -m storyvid.pipeline stage1/plan.json --out stage1/out/elio`
Result: `stage1/out/elio/final.mp4`, 30.9 s, 8 shots / 3 scenes. Numbers: `stage1/out/elio/report.md`.

## What worked

- **End to end with no manual steps**: 13 renders in 34.4 min wall time (33.2 min of LTX), all 8 shots
  passed their gates, and the cut came out with fades, a trimmed duplicate frame on continued shots, and an
  AI-disclosure tag in the file metadata.
- **Dialogue**: 4/4 lines word-perfect. Voice 0.80–0.88 on the chosen takes.
- **The retry loop paid off**: w2 take 1 failed voice (0.728); the retry passed (0.796).
- **Take selection matches the eye**: w1 take 1 had his hood up (identity 0.59) and was rejected in favour
  of take 2 (0.75).
- **Within-scene continuity**: continued shots score 0.83–0.89 against the shot they continue, and look
  continuous. The b2 → b3 (cutaway to the machine) → b4 edit reads naturally.
- **Pace**: about 67 s of wall time per second of film (34.4 min for 30.9 s), so a 2-minute film is about 2.2 h.

## What didn't

1. **Elio's look changes between scenes.** The anchored beach scene has the canonical look (fluffy hair,
   slimmer face). The text-only workshop and cliff openers both drift to spikier hair and a rounder face.
   Within each scene he is consistent.
2. **The flying machine is a different object in every scene**: a small wooden frame in the workshop, a large
   boxy canvas contraption on the beach (so big in b1 it covers his face), and another design in b3.
   Nothing checks prop consistency yet.
3. **Soft lines are fragile for the voice**: 3 of 5 takes of the two "softly" lines failed the voice gate
   (0.66–0.73), while every energetic line passed first time. Either LTX's voice really shifts when he
   speaks softly, or quiet speech plus breeze fools the scorer. Needs a human listen:
   `contact/` and `takes/c1_t0_*.mp4` (passed) vs `takes/c1_t1_*.mp4` and `takes/c1_t2_*.mp4` (failed).
4. **c2 isn't the silhouette the plan asked for**: Elio is front-lit facing the camera in front of the sun.

## Options for the next iteration

- **Keyframe-first (recommended)**: make each scene opener's first frame as a still with an image-editing
  model, from the canonical Elio frame plus a canonical prop image ("Elio at his workbench at night, holding
  this machine"), then animate it with LTX i2v (anchor mode). This fixes both the look drift and the prop
  drift, and lets the plan choose the opening pose. It costs one more model to download (an Apache-2.0
  candidate: Qwen-Image-Edit) and a speed test on this Mac.
- **Character LoRA** (`ltx-trainer-mlx`): locks the look inside LTX itself, but needs 20–50 consistent images
  in varied scenes to train on, which keyframe-first would produce. So it comes after, if at all.
- **Cheap fixes now**: a prop check (second detector query against a canonical prop crop), and a "speaking
  softly in his bright, warm, boyish voice" wording test for soft lines.
