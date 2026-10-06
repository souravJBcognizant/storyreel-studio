#!/usr/bin/env bash
# Stage 0 / test 2 — does LTX 2.5 (q8, MLX) render on this Mac, and how fast / how much memory?
# Renders the character "look-dev" clip; a still from it becomes the image anchor for test 3.
#
# Run:  bash stage0/01_ltx_t2v.sh
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=stage0/out/ltx
MODEL=models/ltx-2.5-mlx-q8
mkdir -p "$OUT"

# The character bible text — reused word for word in every prompt for this character.
BIBLE="A 3D animated stylized cartoon character in a warm, colorful animated-feature style. \
Elio, a cheerful young inventor with messy copper-red hair, big round green eyes, freckles, \
round brass goggles pushed up on his forehead and an oversized mustard-yellow raincoat"

PROMPT="$BIBLE, stands on a sandy beach at golden hour, facing the camera in a medium close-up. \
He smiles, blinks and glances around curiously, shifting his weight slightly. Soft warm sunlight, \
a gentle sea breeze moves his hair, calm ocean behind him. Static camera."

/usr/bin/time -l caffeinate -dimsu \
  uv run --project ltx-2-mlx ltx-2-mlx generate --distilled \
    --model "$MODEL" -p "$PROMPT" \
    -H 512 -W 768 -f 97 --frame-rate 24 --seed 42 --low-ram \
    -o "$OUT/t2v_character.mp4" 2>&1 | tee "$OUT/t2v_character.log"

# Character reference still (1 s in, past any first-frame artifacts) + a contact sheet to inspect.
ffmpeg -y -loglevel error -ss 1 -i "$OUT/t2v_character.mp4" -frames:v 1 "$OUT/character_ref.png"
ffmpeg -y -loglevel error -i "$OUT/t2v_character.mp4" -vf "fps=2,scale=384:-1,tile=4x2" -frames:v 1 "$OUT/t2v_contact.png"
echo "done: $OUT/t2v_character.mp4  $OUT/character_ref.png"
