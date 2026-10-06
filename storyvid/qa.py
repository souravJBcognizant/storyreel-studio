"""Continuity QA: did the shot say the right words, in the right voice, with the right face?

- word_error_rate: Whisper transcript vs the scripted line
- VoiceScorer:     speaker similarity (resemblyzer; Qwen3-TTS's encoder optional — it scores
                   every voice 0.97+, so it can't gate anything)
- CharacterScorer: finds the character's head (OWLv2, open-vocabulary detection) and compares
                   it with the canonical look (DINOv2 embeddings). Works on stylized characters,
                   where real-face models like InsightFace don't.
"""

import re
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf

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

    def crop(self, image, query: str):
        """Best-scoring head box, padded 15% so hair and goggles stay in; None if not found."""
        torch = self._torch
        inputs = self._det_proc(text=[[query]], images=image, return_tensors="pt")
        with torch.no_grad():
            outputs = self._det(**inputs)
        side = max(image.size)  # OWLv2 pads to a square, so boxes are in padded-square pixels
        result = self._det_proc.post_process_grounded_object_detection(
            outputs=outputs, threshold=self.min_box_score, target_sizes=torch.tensor([[side, side]])
        )[0]
        if len(result["scores"]) == 0:
            return None, 0.0
        best = int(result["scores"].argmax())
        x0, y0, x1, y1 = result["boxes"][best].tolist()
        pad_x, pad_y = 0.15 * (x1 - x0), 0.15 * (y1 - y0)
        w, h = image.size
        box = (max(0, x0 - pad_x), max(0, y0 - pad_y), min(w, x1 + pad_x), min(h, y1 + pad_y))
        return image.crop(box), float(result["scores"][best])

    def embed(self, image) -> np.ndarray:
        torch = self._torch
        inputs = self._emb_proc(images=image, return_tensors="pt")
        with torch.no_grad():
            return self._emb(**inputs).pooler_output[0].numpy()

    def embed_character(self, image, query: str):
        """Embedding of the character's head crop, or None when no head is found."""
        head, _ = self.crop(image, query)
        return None if head is None else self.embed(head)
