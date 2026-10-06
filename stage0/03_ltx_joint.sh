#!/usr/bin/env bash
# Stage 0 / test 4 — let LTX voice the lines itself (joint audio + video, fast distilled model).
# Same anchor image and the same voice description in every prompt; the question is whether the
# voice stays the same across separate shots and whether the words come out right.
# Score afterwards with:  uv run python stage0/03_score_joint.py
#
# Run:  bash stage0/03_ltx_joint.sh
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=stage0/out/ltx
MODEL=models/ltx-2.5-mlx-q8
REF=$OUT/character_ref.png

BIBLE="A 3D animated stylized cartoon character in a warm, colorful animated-feature style. \
Elio, a cheerful young inventor with messy copper-red hair, big round green eyes, freckles, \
round brass goggles pushed up on his forehead and an oversized mustard-yellow raincoat"
SCENE="stands on a sandy beach at golden hour, facing the camera in a medium close-up"
VOICE="in a bright, warm, boyish voice"
TAIL="Soft warm sunlight, calm ocean behind him. Static camera. Audio: only his voice and the soft sound of waves."

declare -a NAMES=(line1_nervous line2_excited line3_worried)
declare -a ACTIONS=(
  "He takes a nervous deep breath and says $VOICE: \"Okay, okay... deep breath. This is it. Three, two, one!\""
  "He throws his arms up in delight and shouts excitedly $VOICE: \"It works! It actually works! Look at it go!\""
  "He reaches out anxiously and calls out worriedly $VOICE: \"Wait, no, no, no! Come back here, please!\""
)

for i in "${!NAMES[@]}"; do
  name=${NAMES[$i]}
  PROMPT="$BIBLE, $SCENE. ${ACTIONS[$i]} $TAIL"
  # No -f: the 2.5 DurationHead picks the length from the prompt, clamped so a line is never cut short.
  /usr/bin/time -l caffeinate -dimsu \
    uv run --project ltx-2-mlx ltx-2-mlx generate --distilled \
      --model "$MODEL" -p "$PROMPT" -i "$REF" \
      -H 512 -W 768 --auto-duration 3:7 --frame-rate 24 --seed 42 --low-ram \
      -o "$OUT/joint_$name.mp4" 2>&1 | tee "$OUT/joint_$name.log"
  ffmpeg -y -loglevel error -i "$OUT/joint_$name.mp4" -vn -ac 1 -ar 24000 -sample_fmt s16 "$OUT/joint_$name.wav"
  ffmpeg -y -loglevel error -i "$OUT/joint_$name.mp4" -vf "fps=3,scale=384:-1,tile=4x3" -frames:v 1 "$OUT/joint_${name}_contact.png"
done
echo "done: joint renders"
