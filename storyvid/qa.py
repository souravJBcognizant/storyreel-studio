"""Continuity QA: did the shot say the right words, in the right voice, with the right face?

- word_error_rate: Whisper transcript vs the scripted line
- VoiceScorer:     speaker similarity (resemblyzer; Qwen3-TTS's encoder optional — it scores
                   every voice 0.97+, so it can't gate anything)
- CharacterScorer: finds the character's head (OWLv2, open-vocabulary detection) and compares
                   it with the canonical look (DINOv2 embeddings). Works on stylized characters,
                   where real-face models like InsightFace don't; on photoreal faces it can't tell
                   people apart, so it only ranks takes there.
- check_speaker:   Claude, shown the cast sheets and four frames, says who is visibly talking —
                   the check that the person on screen is the one saying the line.
"""

import re
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf
from pydantic import BaseModel, Field

from .vision import frame_block, image_block, parse, text_block

SR = 24000
QWEN_ENCODER_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
DETECTOR_MODEL = "google/owlv2-base-patch16-ensemble"
EMBEDDER_MODEL = "facebook/dinov2-base"


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.ravel(a), np.ravel(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def centroid(embs: list[np.ndarray]) -> np.ndarray:
    return np.mean([np.ravel(e) / np.linalg.norm(e) for e in embs], axis=0)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def word_error_rate(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
            prev, d[j] = d[j], cur
    return d[len(h)] / len(r)


class VoiceScorer:
    def __init__(self, qwen_model=None, with_qwen: bool = True):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # webrtcvad still imports the deprecated pkg_resources
            from resemblyzer import VoiceEncoder, preprocess_wav
        self._preprocess = preprocess_wav
        self._resemblyzer = VoiceEncoder(device="cpu", verbose=False)
        if with_qwen and qwen_model is None:
            from mlx_audio.tts.utils import load_model

            qwen_model = load_model(QWEN_ENCODER_MODEL)
        self._qwen = qwen_model if with_qwen else None

    def embed(self, path: Path) -> dict[str, np.ndarray]:
        wav, sr = sf.read(path, dtype="float32")
        if sr != SR:
            raise ValueError(f"{path}: expected {SR} Hz, got {sr}")
        emb = {"resemblyzer": self._resemblyzer.embed_utterance(self._preprocess(Path(path)))}
        if self._qwen is not None:
            import mlx.core as mx

            emb["qwen_spk"] = np.array(self._qwen.extract_speaker_embedding(mx.array(wav), sr=SR))
        return emb

    def score(self, ref: Path, clips: list[Path]) -> dict[str, dict[str, float]]:
        ref_emb = self.embed(ref)
        out = {}
        for clip in clips:
            emb = self.embed(clip)
            out[Path(clip).stem] = {k: round(cosine(ref_emb[k], emb[k]), 3) for k in ref_emb}
        return out


class CharacterScorer:
    """Head crop → DINOv2 embedding. `query` names what to find, e.g. "a cartoon boy's head"."""

    def __init__(self, min_box_score: float = 0.15):
        import torch
        from transformers import AutoImageProcessor, AutoModel, Owlv2ForObjectDetection, Owlv2Processor

        self._torch = torch
        self.min_box_score = min_box_score
        self._det_proc = Owlv2Processor.from_pretrained(DETECTOR_MODEL)
        self._det = Owlv2ForObjectDetection.from_pretrained(DETECTOR_MODEL).eval()
        self._emb_proc = AutoImageProcessor.from_pretrained(EMBEDDER_MODEL)
        self._emb = AutoModel.from_pretrained(EMBEDDER_MODEL).eval()

    def locate(self, image, query: str) -> tuple[tuple[float, float, float, float], float] | None:
        """Best-scoring head box (x0, y0, x1, y1) in image pixels and its score; None if not found."""
        torch = self._torch
        inputs = self._det_proc(text=[[query]], images=image, return_tensors="pt")
        with torch.no_grad():
            outputs = self._det(**inputs)
        side = max(image.size)  # OWLv2 pads to a square, so boxes are in padded-square pixels
        result = self._det_proc.post_process_grounded_object_detection(
            outputs=outputs, threshold=self.min_box_score, target_sizes=torch.tensor([[side, side]])
        )[0]
        if len(result["scores"]) == 0:
            return None
        best = int(result["scores"].argmax())
        w, h = image.size
        x0, y0, x1, y1 = result["boxes"][best].tolist()
        return (max(0, x0), max(0, y0), min(w, x1), min(h, y1)), float(result["scores"][best])

    def crop(self, image, query: str):
        """Best head, padded 15% so hair and accessories stay in; (None, 0.0) if not found."""
        found = self.locate(image, query)
        if found is None:
            return None, 0.0
        (x0, y0, x1, y1), score = found
        pad_x, pad_y = 0.15 * (x1 - x0), 0.15 * (y1 - y0)
        w, h = image.size
        box = (max(0, x0 - pad_x), max(0, y0 - pad_y), min(w, x1 + pad_x), min(h, y1 + pad_y))
        return image.crop(box), score

    def embed(self, image) -> np.ndarray:
        torch = self._torch
        inputs = self._emb_proc(images=image, return_tensors="pt")
        with torch.no_grad():
            return self._emb(**inputs).pooler_output[0].numpy()

    def embed_character(self, image, query: str):
        """Embedding of the character's head crop, or None when no head is found."""
        head, _ = self.crop(image, query)
        return None if head is None else self.embed(head)


def nearest_character(emb: np.ndarray, refs: dict[str, np.ndarray]) -> tuple[str, float, float]:
    """Which cast member a head looks most like: (character id, similarity, margin over the runner-up)."""
    scored = sorted(((cosine(emb, r), cid) for cid, r in refs.items() if r is not None), reverse=True)
    if not scored:
        return "", 0.0, 0.0
    best, cid = scored[0]
    return cid, best, best - (scored[1][0] if len(scored) > 1 else 0.0)


def lip_sync(video: Path, audio: Path, boxes: list[tuple[float, tuple[float, float, float, float]]], size: tuple[int, int], fps: int = 24) -> float | None:
    """How well the speaker's mouth movement follows the speech: correlation in [-1, 1], None if unmeasurable.

    `boxes` are (time s, head box) detections of the speaker in frames of `size`. Mouth movement is the
    frame-to-frame change in the lower middle of the head box minus the change in its upper part, which
    cancels camera moves and head turns; it is correlated with the speech loudness, frame by frame.
    """
    import subprocess

    if len(boxes) < 2:
        return None
    w, h = size
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf", f"fps={fps},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout  # fmt: skip
    frames_ = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)
    times = np.array([t for t, _ in boxes])
    mouth, upper = [], []
    for i in range(1, len(frames_)):
        x0, y0, x1, y1 = boxes[int(np.abs(times - i / fps).argmin())][1]
        bw, bh = x1 - x0, y1 - y0
        if bw < 12 or bh < 12:
            mouth.append(0.0), upper.append(0.0)
            continue
        m = (slice(int(y0 + 0.62 * bh), int(y0 + 0.95 * bh)), slice(int(x0 + 0.25 * bw), int(x0 + 0.75 * bw)))
        u = (slice(int(y0 + 0.15 * bh), int(y0 + 0.45 * bh)), slice(int(x0 + 0.25 * bw), int(x0 + 0.75 * bw)))
        mouth.append(float(np.abs(frames_[i][m] - frames_[i - 1][m]).mean()))
        upper.append(float(np.abs(frames_[i][u] - frames_[i - 1][u]).mean()))
    motion = np.clip(np.array(mouth) - np.array(upper), 0, None)
    wav, sr = sf.read(audio, dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    hop = sr // fps
    loud = np.array([np.sqrt(np.mean(wav[k * hop:(k + 1) * hop] ** 2)) if k * hop < len(wav) else 0.0 for k in range(1, len(frames_))])
    if motion.std() < 1e-6 or loud.std() < 1e-6:
        return None
    return float(np.corrcoef(motion, loud)[0, 1])


class SpeakerCheck(BaseModel):
    who_is_talking: str = Field(description="Name of the cast member whose mouth is visibly speaking, or 'nobody', or 'unclear'")
    speaker_visible: bool = Field(description="Is the named person (the one saying the line, or for an off-screen line the one listening) in these frames?")
    speaker_is_talking: bool = Field(description="Is that person's mouth visibly forming words across the frames?")
    someone_else_talking: bool = Field(description="Is anyone other than the person saying the line visibly speaking?")
    confidence: int = Field(ge=1, le=5)
    note: str


def check_speaker(video: Path, span: tuple[float, float], cast: dict[str, Path], line: str, speaker: str | None,
                  in_frame: str | None = None) -> SpeakerCheck:  # fmt: skip
    """Who is visibly speaking while `line` is heard, judged from four frames across `span` (seconds).

    `cast` maps each name to their character sheet. `speaker` is who says the line on camera; None means it
    is heard off screen, so nobody in the frames should be talking, and `in_frame` (if any) is who the
    picture shows listening.
    """
    content = []
    for name, sheet in cast.items():
        content += [text_block(f"Cast member {name}:"), image_block(sheet)]
    a, b = span
    if speaker:
        content.append(text_block(f'Four frames from one shot, in order, taken while this line is spoken: "{line}"'))
    else:
        content.append(text_block(f'Four frames from one shot, in order. Over them, this line is heard from someone off screen: "{line}"'))
    content += [frame_block(video, a + (b - a) * k / 3) for k in range(4)]
    if speaker:
        content.append(text_block(f"The line belongs to {speaker}. Who, if anyone, is visibly speaking in these frames "
                                  "(mouth moving between frames)? Judge faces, hair and clothing against the cast sheets."))  # fmt: skip
    elif in_frame:
        content.append(text_block(f"{in_frame} should be in these frames, listening, and no one in them should be speaking. "
                                  f"Is {in_frame} in the frames? Who, if anyone, is visibly speaking (mouth moving between "
                                  f"frames)? Answer speaker_is_talking for {in_frame}, and someone_else_talking for anyone "
                                  "else. Judge faces, hair and clothing against the cast sheets."))  # fmt: skip
    else:
        content.append(text_block("No one in these frames should be speaking. Who, if anyone, is visibly speaking "
                                  "(mouth moving between frames)? Judge faces, hair and clothing against the cast sheets. "
                                  "Answer speaker_visible and speaker_is_talking as false."))  # fmt: skip
    return parse(content, SpeakerCheck)
