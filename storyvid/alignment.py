"""Match an overlay to the original recording without splicing individual words.

Speech activity locates the lead-in, tail and phrase pauses in both recordings. Word timings anchor
continuous, pitch-preserving WSOLA inside each phrase. Cuts happen only at phrase breaks, with no
independently stretched words to overlap or leave holes in otherwise continuous speech.
"""

from dataclasses import dataclass

import numpy as np
from pytsmod import wsola

SR = 24000
HOP = SR // 100  # speech activity in 10 ms frames
MARGIN = 0.02  # retain quiet consonants at the edges of detected speech
MIN_PAUSE = 0.18
MIN_ANCHOR = 0.08
MAX_RATE = 2.0


@dataclass
class Activity:
    start: float
    end: float
    pauses: list[tuple[float, float]]


def activity(wave: np.ndarray, start: float = 0.0, end: float | None = None) -> Activity:
    """Estimate speech edges above room tone; never treat a single zero crossing as a pause."""
    end = min(len(wave) / SR, end if end is not None else len(wave) / SR)
    a, b = max(0, int(start * SR)), int(end * SR)
    clip = wave[a:b]
    if len(clip) < HOP:
        raise ValueError("no usable speech in the recording")
    padded = np.pad(clip, (0, (-len(clip)) % HOP))
    rms = np.sqrt(np.mean(padded.reshape(-1, HOP) ** 2, axis=1))
    threshold = max(0.003, float(np.percentile(rms, 80)) * 0.08)
    active = rms > threshold
    voiced = np.flatnonzero(active)
    if not len(voiced):
        raise ValueError("no audible speech in the recording")
    first, last = voiced[0], voiced[-1]
    quiet = ~active[first:last + 1]
    changes = np.diff(np.r_[False, quiet, False].astype(int))
    pauses = [(start + (first + lo) / 100 + MARGIN, start + (first + hi) / 100 - MARGIN)
              for lo, hi in zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1))
              if (hi - lo) / 100 >= MIN_PAUSE]
    return Activity(max(start, start + first / 100 - MARGIN),
                    min(end, start + (last + 1) / 100 + MARGIN), pauses)


def pause_boundaries(profile: Activity, spans: list, common: list[int]) -> dict[int, tuple[float, float]]:
    """Associate each measured pause with one word boundary, allowing timestamps to include silence."""
    result = {}
    for pause in profile.pauses:
        mid = sum(pause) / 2
        candidates = [j for i, j in zip(common, common[1:])
                      if j == i + 1 and spans[i][1] - 0.1 <= mid <= spans[j][1] - 0.06]
        if candidates:
            j = min(candidates, key=lambda j: abs(mid - (spans[j - 1][1] + spans[j][0]) / 2))
            # Several quiet intervals in a word can be unvoiced consonants; keep only the longest.
            if j not in result or pause[1] - pause[0] > result[j][1] - result[j][0]:
                result[j] = pause
    return result


def matching_pauses(original: np.ndarray, target: list, length_s: float,
                    candidates: set[int]) -> dict[int, tuple[float, float]]:
    """Return punctuation boundaries that are backed by a real pause in the performance."""
    common = [i for i, span in enumerate(target) if span is not None]
    if len(common) < 2 or not candidates:
        return {}
    profile = activity(original, max(0, target[common[0]][0] - .2),
                       min(length_s, target[common[-1]][1] + .35))
    measured = pause_boundaries(profile, target, common)
    return {j: pause for j, pause in measured.items() if j in candidates}


def _boundary(spans: list, j: int) -> tuple[float, float]:
    point = (spans[j - 1][1] + spans[j][0]) / 2
    return point, point


def warp(voice: np.ndarray, points: list[tuple[float, float]], length: int) -> np.ndarray:
    """One continuous WSOLA pass, anchored to word times. Never reset the processor at each word."""
    anchors = np.rint(np.array(points).T * SR).astype(int)
    anchors[:, 0] = 0
    anchors[:, -1] = [len(voice) - 1, length - 1]
    if np.any(np.diff(anchors, axis=1) <= 0):
        raise ValueError("speech timing anchors are not monotonic")
    if np.array_equal(anchors[0], anchors[1]) and len(voice) == length:
        out = voice.copy()
    else:
        out = wsola(voice, anchors, win_size=768, syn_hop_size=192, tolerance=192).astype(np.float32)
    if len(out) != length or not np.all(np.isfinite(out)):
        raise ValueError("audio alignment produced an invalid track")
    fade = min(int(0.004 * SR), len(out) // 2)
    if fade:
        ramp = np.linspace(0, 1, fade, dtype=np.float32)
        out[:fade] *= ramp
        out[-fade:] *= ramp[::-1]
    return out


def align(voice: np.ndarray, original: np.ndarray, source: list, target: list,
          length_s: float) -> tuple[np.ndarray, list[dict]]:
    common = [i for i, (s, t) in enumerate(zip(source, target)) if s is not None and t is not None]
    if not common:
        raise ValueError("no shared speech timings")
    # Only inspect the transcript's region: later ambience must not extend the spoken line.
    src = activity(voice)  # preserve the full recording, including any word the recognizer missed
    dst = activity(original, max(0, target[common[0]][0] - .2), min(length_s, target[common[-1]][1] + .35))
    source_pauses = pause_boundaries(src, source, common)
    target_pauses = pause_boundaries(dst, target, common)
    phrases = []
    a, c, first = src.start, dst.start, 0
    for j in sorted(source_pauses.keys() | target_pauses.keys()):
        s0, s1 = source_pauses.get(j, _boundary(source, j))
        t0, t1 = target_pauses.get(j, _boundary(target, j))
        if min(s0 - a, t0 - c, src.end - s1, dst.end - t1) < MIN_ANCHOR:
            continue
        phrases.append((first, j, a, s0, c, t0))
        first, a, c = j, s1, t1
    phrases.append((first, len(source), a, src.end, c, dst.end))
    track = np.zeros(round(length_s * SR), dtype=np.float32)
    alignment = []
    for first, last, a, b, c, d in phrases:
        source_length, target_length = b - a, d - c
        rate = source_length / target_length
        if not 1 / MAX_RATE <= rate <= MAX_RATE:
            raise ValueError("the delivery is too different to sync naturally; use original audio for this shot")
        points = [(0.0, 0.0)]
        for i in common:
            # The last word uses the measured phrase end, including its full trailing consonants.
            if not first <= i < last - 1:
                continue
            x, y = source[i][1] - a, target[i][1] - c
            px, py = points[-1]
            if min(x - px, y - py, source_length - x, target_length - y) < MIN_ANCHOR:
                continue
            before = (x - px) / (y - py)
            after = (source_length - x) / (target_length - y)
            if 1 / MAX_RATE <= before <= MAX_RATE and 1 / MAX_RATE <= after <= MAX_RATE:
                points.append((x, y))
        points.append((source_length, target_length))
        sa, sb, ta, tb = (round(v * SR) for v in (a, b, c, d))
        track[ta:tb] = warp(voice[sa:sb], points, tb - ta)
        alignment.append({"words": [first, last], "source": [a, b], "placed": [c, d],
                          "anchors": [[a + x, c + y] for x, y in points], "mode": "original_audio"})
    return track, alignment
