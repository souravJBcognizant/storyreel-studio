#!/usr/bin/env bash
# Downloads the LTX 2.5 q8 MLX pack as soon as a Hugging Face login with license access exists.
# The repo is gated: accept the license on its HF page, then `hf auth login` once.
cd "$(dirname "$0")/.."
mkdir -p models
LOG=models/download-ltx.log
: > "$LOG"

until [ -s ~/.cache/huggingface/token ]; do sleep 10; done
echo "token found $(date '+%H:%M:%S')" >> "$LOG"

for attempt in $(seq 1 120); do
  if uvx --from 'huggingface_hub[hf_xet]' hf download dgrauet/ltx-2.5-mlx-q8 \
       --local-dir models/ltx-2.5-mlx-q8 >> "$LOG" 2>&1; then
    echo "DOWNLOAD_OK $(date '+%H:%M:%S')" >> "$LOG"
    exit 0
  fi
  echo "attempt $attempt failed (license not accepted yet, or network) — retrying in 60s" >> "$LOG"
  sleep 60
done
echo "DOWNLOAD_FAILED" >> "$LOG"
exit 1
