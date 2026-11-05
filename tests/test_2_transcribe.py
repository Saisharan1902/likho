"""Section 2 — speech-to-text. Uses macOS `say` to synthesize speech, so no microphone is needed.

The first run downloads the small Whisper "base.en" model (~150 MB) from Hugging Face.
"""
import subprocess
import wave

import numpy as np
import pytest

from likho.audio import save_wav
from likho.transcriber import apply_replacements, transcribe

TEST_MODEL = "mlx-community/whisper-base.en-mlx"


def _say(tmp_path, text) -> np.ndarray:
    path = tmp_path / "speech.wav"
    subprocess.run(["say", "-o", str(path), "--data-format=LEI16@16000", text], check=True)
    with wave.open(str(path)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768


def test_transcribes_speech(tmp_path):
    audio = _say(tmp_path, "Hello, this is a test of local dictation on my Mac.")
    text = transcribe(audio, TEST_MODEL, language="en").lower()
    assert "test" in text and "dictation" in text


def test_silence_gives_empty_text():
    assert transcribe(np.zeros(16000, dtype=np.float32), TEST_MODEL, language="en") == ""


def test_wav_roundtrip(tmp_path):
    audio = np.sin(np.linspace(0, 100, 16000)).astype(np.float32) * 0.5
    save_wav(tmp_path / "x.wav", audio)
    with wave.open(str(tmp_path / "x.wav")) as w:
        assert w.getframerate() == 16000 and w.getnframes() == 16000


@pytest.mark.parametrize("text,expected", [
    ("send it to my email", "send it to ada@example.com"),
    ("My Email please", "ada@example.com please"),
    ("emails are fine", "emails are fine"),  # whole words only
])
def test_replacements(text, expected):
    assert apply_replacements(text, [{"from": "my email", "to": "ada@example.com"}]) == expected
