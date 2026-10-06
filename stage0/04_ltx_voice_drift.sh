#!/usr/bin/env bash
# Stage 0 / test 5 — does LTX's own voice for Elio survive real story conditions?
# Test 4 was the easy case (same scene, framing, anchor image, seed). Here every shot changes
# scene, lighting, camera distance and seed, and there is no anchor image, so his look rests on
# the bible text alone. Score afterwards with:  uv run python stage0/04_score_drift.py
#
# Run:  bash stage0/04_ltx_voice_drift.sh
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=stage0/out/ltx/drift
MODEL=models/ltx-2.5-mlx-q8
mkdir -p "$OUT"

BIBLE="A 3D animated stylized cartoon character in a warm, colorful animated-feature style. \
Elio, a cheerful young inventor with messy copper-red hair, big round green eyes, freckles, \
round brass goggles pushed up on his forehead and an oversized mustard-yellow raincoat"
VOICE="in a bright, warm, boyish voice"

declare -a NAMES=(workshop rain hill frustrated)
declare -a SEEDS=(7 13 21 99)
declare -a SHOTS=(
  "sits at a cluttered workbench in his workshop at night, lit by a warm desk lamp, close-up on his face. \
He carefully turns a tiny screwdriver and murmurs $VOICE: \"If I tighten this spring just a little more... there. Perfect.\" \
Static camera. Audio: his voice and the faint ticking of clocks."
  "runs along a rainy town street at dusk, wide shot, neon reflections on wet cobblestones, rain falling. \
He waves frantically ahead and shouts $VOICE: \"Come on, come on, the bus is leaving without me!\" \
The camera tracks alongside him. Audio: his voice, rain and distant traffic."
  "stands on a grassy hilltop under a bright blue sky, medium shot, holding a small homemade flying machine. \
He gazes at the horizon and says dreamily $VOICE: \"One day, everyone in this town is going to look up and see my machines flying.\" \
Slow push-in. Audio: his voice and a gentle breeze."
  "stands in his messy workshop in daylight, medium close-up, glaring at a sputtering contraption on the table. \
He throws down his wrench and says in frustration $VOICE: \"Why won't you fly? I followed every single step!\" \
Static camera. Audio: his voice and the contraption sputtering."
)

for i in "${!NAMES[@]}"; do
  name=${NAMES[$i]}
  /usr/bin/time -l caffeinate -dimsu \
    uv run --project ltx-2-mlx ltx-2-mlx generate --distilled \
      --model "$MODEL" -p "$BIBLE ${SHOTS[$i]}" \
      -H 512 -W 768 --auto-duration 3:8 --frame-rate 24 --seed "${SEEDS[$i]}" --low-ram \
      -o "$OUT/$name.mp4" 2>&1 | tee "$OUT/$name.log"
  ffmpeg -y -loglevel error -i "$OUT/$name.mp4" -vn -ac 1 -ar 24000 -sample_fmt s16 "$OUT/$name.wav"
  ffmpeg -y -loglevel error -i "$OUT/$name.mp4" -vf "fps=2,scale=288:-1,tile=4x2" -frames:v 1 "$OUT/${name}_contact.png"
done
echo "done: drift renders"
