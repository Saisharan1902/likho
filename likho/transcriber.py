"""Local speech-to-text on Apple Silicon (MLX) with two open-source engines:

- Parakeet (NVIDIA, TDT 0.6B): English, very accurate and fast; no prompt biasing.
- Whisper (OpenAI): multilingual; the dictionary is passed as a prompt to bias spellings.

Custom dictionary words are also fuzzy-corrected after recognition, which works for both engines.
"""
import difflib
import re

import numpy as np

MODELS = {
    "mlx-community/parakeet-tdt-0.6b-v2": "Parakeet v2 — English, most accurate + fastest (~1.2 GB)",
    "mlx-community/whisper-large-v3-turbo": "Whisper Large v3 Turbo — multilingual (~1.6 GB)",
    "mlx-community/whisper-small.en-mlx": "Whisper Small (English) — lighter (~480 MB)",
    "mlx-community/whisper-base.en-mlx": "Whisper Base (English) — smallest (~150 MB)",
}

# Whisper hallucinates these on silence / very short clips
_HALLUCINATIONS = {"thank you.", "thanks for watching!", "thank you for watching.", "you", "bye.", "."}

_parakeet = {}  # model id → loaded model (kept in memory)


def engine_of(model: str) -> str:
    return "parakeet" if "parakeet" in model else "whisper"


def _parakeet_model(model):
    if model not in _parakeet:
        from parakeet_mlx import from_pretrained
        _parakeet.clear()  # keep one in memory
        _parakeet[model] = from_pretrained(model)
    return _parakeet[model]


def _transcribe_parakeet(audio, model):
    import mlx.core as mx
    from parakeet_mlx.audio import get_logmel

    m = _parakeet_model(model)
    mel = get_logmel(mx.array(audio, dtype=mx.float32), m.preprocessor_config)
    return m.generate(mel)[0].text


def _transcribe_whisper(audio, model, language, dictionary):
    import mlx_whisper  # imported lazily: it's slow to import

    kwargs = {
        "path_or_hf_repo": model,
        "condition_on_previous_text": False,
        "fp16": True,
        # No temperature fallback: when unsure, Whisper retries with randomness, which takes ~6x longer
        # and turns unclear audio into confident nonsense ("BLOOD", "分 residual").
        "temperature": 0.0,
    }
    if language:
        kwargs["language"] = language
    if dictionary:
        # The initial prompt biases Whisper towards these spellings (names, jargon, product terms)
        kwargs["initial_prompt"] = "Vocabulary: " + ", ".join(dictionary) + "."
    result = mlx_whisper.transcribe(audio, **kwargs)
    # Drop segments Whisper itself flags as "probably not speech"
    kept = [s["text"] for s in result["segments"]
            if not (s["no_speech_prob"] > 0.6 and s["avg_logprob"] < -1.0)]
    return "".join(kept)


def transcribe(audio: np.ndarray, model: str, language: str = "", dictionary=()) -> str:
    audio = audio.astype(np.float32)
    if engine_of(model) == "parakeet":
        text = _transcribe_parakeet(audio, model)
    else:
        text = _transcribe_whisper(audio, model, language, dictionary)
    text = text.strip()
    if text.lower() in _HALLUCINATIONS:
        return ""
    return fix_dictionary(text, dictionary)


def warm_up(model: str):
    """Download (first run) and load the model so the first real dictation is fast."""
    t = np.linspace(0, 1, 16000, dtype=np.float32)
    transcribe(0.1 * np.sin(2 * np.pi * 220 * t), model)


def _norm(s):
    return re.sub(r"[^\w]", "", s.lower())


def fix_dictionary(text: str, dictionary, cutoff=0.8) -> str:
    """Snap near-misses to your dictionary spelling, e.g. "Ada Lovlace" → "Ada Lovelace", "kubernetis" → "Kubernetes"."""
    if not dictionary or not text:
        return text
    words = text.split()
    for term in dictionary:
        target = _norm(term)
        if len(target) < 4:
            continue  # too short to match safely
        n = len(term.split())
        # Candidate windows of the same word count, and one fewer/more (recognizers split/merge words).
        candidates = []
        for size in {n, n + 1, max(1, n - 1)}:
            for i in range(len(words) - size + 1):
                got = _norm("".join(words[i:i + size]))
                if got:
                    candidates.append((difflib.SequenceMatcher(None, got, target).ratio(), i, size))
        passing = {(i, size) for ratio, i, size in candidates if ratio >= cutoff}
        # Best matches first; a window overlapping a better one is skipped, and a window that still
        # matches without its first/last word is too wide — so "is Aishran" doesn't swallow "is".
        taken, picks = set(), []
        for ratio, i, size in sorted(candidates, reverse=True):
            span = set(range(i, i + size))
            if ratio < cutoff or span & taken or (i + 1, size - 1) in passing or (i, size - 1) in passing:
                continue
            taken |= span
            picks.append((i, size))
        for i, size in sorted(picks, reverse=True):  # right-to-left keeps indexes valid
            trail = re.search(r"[^\w]*$", words[i + size - 1]).group()  # keep punctuation after it
            words[i:i + size] = [term + trail]
    return " ".join(words)


def apply_replacements(text: str, replacements) -> str:
    for r in replacements:
        src, dst = r.get("from", "").strip(), r.get("to", "")
        if src:
            text = re.sub(r"\b" + re.escape(src) + r"\b", dst, text, flags=re.IGNORECASE)
    return text
