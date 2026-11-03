"""Accuracy work — pre/post-roll capture, silence gating, trimming, dictionary correction, Parakeet engine."""
import subprocess
import time

import numpy as np
import pytest

from dictly.audio import SAMPLE_RATE, Recorder, load_wav, prepare
from dictly.transcriber import fix_dictionary, transcribe


def tone(seconds, amp=0.3):
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amp * np.sin(2 * np.pi * 300 * t)).astype(np.float32)


def silence(seconds, amp=0.0005):
    return (np.random.default_rng(0).standard_normal(int(seconds * SAMPLE_RATE)) * amp).astype(np.float32)


# -- recorder (no real mic: feed the audio callback directly) ---------------------
@pytest.fixture
def rec(monkeypatch):
    monkeypatch.setattr(Recorder, "_open", lambda self: None)
    monkeypatch.setattr(Recorder, "_close", lambda self: None)
    return Recorder(warm=True, pre_roll=0.3, post_roll=0.05)


def feed(rec, value, blocks):
    for _ in range(blocks):
        rec._callback(np.full((800, 1), value, dtype=np.float32), 800, None, None)


def test_pre_roll_keeps_audio_from_before_the_key_press(rec):
    feed(rec, 0.1, 20)      # 1 s of audio before pressing: only the last 0.3 s is kept
    rec.start()
    feed(rec, 0.5, 10)      # 0.5 s while held
    audio = rec.stop()
    assert len(audio) == int(0.8 * SAMPLE_RATE)
    assert np.allclose(audio[:4800], 0.1) and np.allclose(audio[4800:], 0.5)


def test_post_roll_waits_before_stopping(rec):
    rec.start()
    t = time.monotonic()
    rec.stop()
    assert time.monotonic() - t >= 0.05
    t = time.monotonic()
    rec.cancel()  # cancel doesn't wait
    assert time.monotonic() - t < 0.05


def test_cold_mic_has_no_pre_roll(monkeypatch):
    monkeypatch.setattr(Recorder, "_open", lambda self: None)
    monkeypatch.setattr(Recorder, "_close", lambda self: None)
    r = Recorder(warm=False, post_roll=0)
    feed(r, 0.1, 10)
    r.start()
    feed(r, 0.5, 2)
    assert len(r.stop()) == 1600


# -- prepare(): silence gate, trim, normalise -------------------------------------
def test_silence_and_room_noise_are_rejected():
    assert prepare(np.zeros(SAMPLE_RATE * 2, dtype=np.float32)) is None
    assert prepare(silence(2, amp=0.002)) is None          # like the "BLOOD" / "分 residual" clips


def test_speech_is_trimmed_with_padding_and_normalised():
    audio = np.concatenate([silence(1.0), tone(0.5, amp=0.1), silence(1.0)])
    out = prepare(audio, pad=0.25)
    assert abs(len(out) / SAMPLE_RATE - 1.0) < 0.05        # 0.5 s speech + 2 × 0.25 s padding
    assert 0.6 < np.abs(out).max() <= 0.71                 # quiet speech brought up


def test_gain_is_capped():
    out = prepare(tone(0.5, amp=0.02))
    assert np.abs(out).max() <= 0.2 + 1e-6                 # at most 10x


# -- dictionary correction --------------------------------------------------------
@pytest.mark.parametrize("heard,expected", [
    ("My name is Ada Lovelase.", "My name is Ada Lovelace."),
    ("My name is Adalovlace.", "My name is Ada Lovelace."),
    ("My name is Dalovelace.", "My name is Ada Lovelace."),
    ("the kubernetis cluster", "the Kubernetes cluster"),
    ("call priya tomorrow", "call Priya tomorrow"),
    ("I say sure", "I say sure"),                          # no false positives on normal words
    ("prior to that", "prior to that"),
])
def test_fix_dictionary(heard, expected):
    assert fix_dictionary(heard, ["Ada Lovelace", "Kubernetes", "Priya"]) == expected


# -- engines on real (synthesized) speech -----------------------------------------
@pytest.fixture(scope="module")
def sentence(tmp_path_factory):
    path = tmp_path_factory.mktemp("say") / "s.wav"
    subprocess.run(["say", "-o", str(path), "--data-format=LEI16@16000",
                    "Please push the latest changes to GitHub tonight."], check=True)
    return load_wav(path)


@pytest.mark.parametrize("model", ["mlx-community/parakeet-tdt-0.6b-v2", "mlx-community/whisper-base.en-mlx"])
def test_engines_transcribe(model, sentence):
    text = transcribe(prepare(sentence), model, "en").lower()
    assert "push" in text and "changes" in text and "tonight" in text
