#!/usr/bin/env bash
# Stage 0 / test 3 — the riskiest one: character image + TTS line -> lip-synced clip (LTX 2.5 a2v).
# Needs test 1 (stage0/out/tts/line2_excited.wav) and test 2 (stage0/out/ltx/character_ref.png).
#
# Run:  bash stage0/02_ltx_a2v.sh
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=stage0/out/ltx
MODEL=models/ltx-2.5-mlx-q8
AUDIO=stage0/out/tts/line2_excited.wav
REF=$OUT/character_ref.png
LINE="It works! It actually works! Look at it go!"

BIBLE="A 3D animated stylized cartoon character in a warm, colorful animated-feature style. \
Elio, a cheerful young inventor with messy copper-red hair, big round green eyes, freckles, \
round brass goggles pushed up on his forehead and an oversized mustard-yellow raincoat"

# The prompt should describe what the audio contains — a2v sync quality depends on it.
PROMPT="$BIBLE, stands on a sandy beach at golden hour, facing the camera in a medium close-up. \
He throws his arms up in delight and shouts excitedly to the camera: \"$LINE\" \
Soft warm sunlight, calm ocean behind him. Static camera."

# Clip length = lead-in + line + tail, rounded up to LTX's 8k+1 frame grid at 24 fps.
# a2v needs audio covering the whole clip, so pad the line with silence to fit — never cut it.
# The lead-in also lets the still anchor frame settle before he starts talking.
LEAD_MS=250
TAIL_S=0.25
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$AUDIO")
FRAMES=$(python3 -c "import math; n=math.ceil(($DUR+$LEAD_MS/1000+$TAIL_S)*24); print(8*math.ceil((n-1)/8)+1)")
CLIP_S=$(python3 -c "print($FRAMES/24 + 0.05)")
PADDED=$OUT/line2_padded.wav
ffmpeg -y -loglevel error -i "$AUDIO" -af "adelay=${LEAD_MS}:all=1,apad=whole_dur=${CLIP_S}" \
  -ac 1 -ar 24000 -sample_fmt s16 "$PADDED"
echo "audio ${DUR}s -> ${FRAMES} frames, padded audio ${CLIP_S}s"

/usr/bin/time -l caffeinate -dimsu \
  uv run --project ltx-2-mlx ltx-2-mlx a2v \
    --model "$MODEL" -p "$PROMPT" --audio "$PADDED" -i "$REF" \
    -H 512 -W 768 -f "$FRAMES" --frame-rate 24 --seed 42 --low-ram \
    -o "$OUT/a2v_line2.mp4" 2>&1 | tee "$OUT/a2v_line2.log"

# a2v's output audio is a VAE reconstruction — put the TTS audio back (the same padded file, so sync holds).
ffmpeg -y -loglevel error -i "$OUT/a2v_line2.mp4" -i "$PADDED" -map 0:v -map 1:a \
  -c:v copy -c:a aac -b:a 192k -af apad -shortest "$OUT/a2v_line2_final.mp4"
ffmpeg -y -loglevel error -i "$OUT/a2v_line2.mp4" -vf "fps=4,scale=384:-1,tile=4x3" -frames:v 1 "$OUT/a2v_contact.png"
echo "done: $OUT/a2v_line2_final.mp4"
