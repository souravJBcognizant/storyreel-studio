# Storyreel Studio

Turn a first frame and a story into a short animated film, on a Mac.

- **The UI** (React, `web/`): create productions, watch the pipeline run live, approve key moments, play the
  film and browse every file the studio made.
- **The engine** (Python, `storyvid/`): renders shots locally with LTX-2.5 (MLX), checks every take for words,
  voice, identity and continuity, re-renders what fails, and cuts the film.
- **Jobs**: renders run as durable background processes, one at a time. They survive restarts of the app,
  can be cancelled, and resume from cache.
- **Agents** (next step): a neuro-san network will plan films from the story. Claude does the important
  reasoning and OpenAI generates the consistent scene keyframes. The UI already shows these stages.

## Setup

Requirements: Apple Silicon Mac (64 GB recommended), [uv](https://docs.astral.sh/uv/), Node 20+, ffmpeg.

```bash
uv sync                                      # Python env (engine + API)
(cd web && npm install)                      # React app

# LTX runtime, pinned to the commit the pipeline was validated on
git clone https://github.com/dgrauet/ltx-2-mlx.git ltx-2-mlx
(cd ltx-2-mlx && git checkout bfa5755 && uv sync --all-extras)

# LTX-2.5 q8 weights (~75 GB, gated): accept the license at
# https://huggingface.co/dgrauet/ltx-2.5-mlx-q8, run `hf auth login`, then:
scripts/fetch_ltx.sh
```

API keys go in `.env` (gitignored; see `.env.example`):

| Variable | Used for |
|---|---|
| `ANTHROPIC_API_KEY` | Claude: story analysis, planning, keyframe review |
| `CLAUDE_MODEL` / `CLAUDE_MODEL_ROUTINE` | Default `claude-opus-5` / `claude-sonnet-5` |
| `OPENAI_API_KEY`, `OPENAI_IMAGE_MODEL` | OpenAI image generation for sheets and keyframes |

Restart the API after editing `.env`. The Settings page shows whether each key is set, never the key itself.

## Run

```bash
scripts/dev.sh        # API on :8787 + UI on http://localhost:5288 (hot reload)
```

Or as a single app: `(cd web && npm run build)` and then
`uv run uvicorn storyvid.api.app:app --port 8787`, and open http://localhost:8787.

## Layout

| Path | What |
|---|---|
| `storyvid/pipeline.py` | The Director: takes → QA → retry → pick → cut (`python -m storyvid.pipeline plan.json --out DIR`) |
| `storyvid/plan.py` | Production plan format and prompt building |
| `storyvid/qa.py` | Word error rate, voice similarity (resemblyzer), character identity (OWLv2 + DINOv2) |
| `storyvid/api/` | FastAPI: productions, jobs, files, media streaming |
| `web/` | The studio UI |
| `stage0/`, `stage1/` | The experiments that validated the approach (`results.md`, `review.md`) |
| `productions/` | Your productions, created by the app (gitignored) |

## License note

LTX-2.x weights are under the LTX-2.x Community License. Organizations with $10M or more in annual revenue may
use them free only for non-commercial evaluation in a development environment; production use needs a paid
license from Lightricks. Generated videos must be disclosed as machine-generated when shared. Every film this
app cuts carries an AI-generated note in its metadata.
