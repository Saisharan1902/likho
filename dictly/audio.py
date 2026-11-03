"""Microphone capture at 16 kHz mono float32 (what speech models expect), plus clean-up before recognition.

Two things matter a lot for accuracy with push-to-talk:
- pre-roll: in "warm" mode the mic stays open and the last 0.3 s before the key press is kept, so the
  first word isn't clipped while the mic spins up (~0.17 s cold).
- post-roll: keep recording 0.3 s after release, because people let go while still finishing the last word.
"""
import threading
import time
import wave
from collections import deque

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
BLOCK = 800  # 50 ms


class Recorder:
    def __init__(self, on_level=None, warm=False, pre_roll=0.3, post_roll=0.3):
        self.on_level = on_level  # called with 0..1 loudness for the overlay waveform
        self.post_roll = post_roll
        self._ring = deque(maxlen=max(1, round(pre_roll * SAMPLE_RATE / BLOCK)))
        self._chunks = []
        self._recording = False
        self._lock = threading.Lock()
        self._stream = None
        self.warm = False
        self.set_warm(warm)

    def set_warm(self, warm):
        """Warm = mic stays open (macOS shows the orange mic dot) so recording starts instantly with pre-roll."""
        self.warm = warm
        if warm:
            self._open()
        elif not self._recording:
            self._close()

    def _open(self):
        if self._stream is None:
            self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                          blocksize=BLOCK, callback=self._callback)
            self._stream.start()

    def _close(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def start(self):
        with self._lock:
            # pre-roll only when warm; when cold the ring just holds the tail of the previous recording
            self._chunks = list(self._ring) if self.warm else []
            self._ring.clear()
            self._recording = True
        self._open()

    def _callback(self, indata, frames, time_info, status):
        mono = indata[:, 0].copy()
        with self._lock:
            if not self._recording:
                self._ring.append(mono)
                return
            self._chunks.append(mono)
        if self.on_level:
            rms = float(np.sqrt(np.mean(mono ** 2)))
            self.on_level(min(1.0, rms * 12))

    def stop(self, post_roll=True) -> np.ndarray:
        if post_roll and self.post_roll:
            time.sleep(self.post_roll)
        with self._lock:
            self._recording = False
            chunks, self._chunks = self._chunks, []
        if not self.warm:
            self._close()
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)

    def cancel(self):
        self.stop(post_roll=False)


# -- clean-up before recognition ------------------------------------------------
FRAME = 320  # 20 ms
MIN_SPEECH_SECONDS = 0.12
SPEECH_FLOOR = 0.008  # RMS below this is room noise for a laptop mic


def prepare(audio: np.ndarray, pad=0.25):
    """Trim leading/trailing silence (keeping `pad` seconds), normalise loudness.

    Returns None when there's no speech at all — Whisper invents text ("Thank you.", random words)
    when fed silence, so it's better not to run it.
    """
    n = len(audio) // FRAME
    if n == 0:
        return None
    rms = np.sqrt(np.mean(audio[: n * FRAME].reshape(n, FRAME) ** 2, axis=1))
    noise = np.percentile(rms, 10)
    # min(): when the whole clip is speech, the "noise" estimate is really speech — don't let it
    # push the threshold above the speech itself.
    threshold = max(SPEECH_FLOOR, min(noise * 3, rms.max() * 0.5), rms.max() * 0.05)
    voiced = np.flatnonzero(rms > threshold)
    if len(voiced) * FRAME / SAMPLE_RATE < MIN_SPEECH_SECONDS:
        return None
    p = int(pad * SAMPLE_RATE)
    start = max(0, voiced[0] * FRAME - p)
    end = min(len(audio), (voiced[-1] + 1) * FRAME + p)
    out = audio[start:end]
    peak = float(np.abs(out).max())
    if peak > 0:
        out = out * min(10.0, 0.7 / peak)  # bring quiet speech up, never more than 10x
    return out.astype(np.float32)


def save_wav(path, audio: np.ndarray):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def load_wav(path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
