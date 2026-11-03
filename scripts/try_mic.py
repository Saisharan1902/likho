"""Section 2 manual check: record from your microphone for a few seconds, then transcribe.

    .venv/bin/python scripts/try_mic.py            # 5 seconds, default model
    .venv/bin/python scripts/try_mic.py 8 base     # 8 seconds, fastest model
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dictly.audio import SAMPLE_RATE, Recorder  # noqa: E402
from dictly.transcriber import transcribe  # noqa: E402

MODELS = {"turbo": "mlx-community/whisper-large-v3-turbo",
          "small": "mlx-community/whisper-small.en-mlx",
          "base": "mlx-community/whisper-base.en-mlx"}

seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 5
model = MODELS[sys.argv[2] if len(sys.argv) > 2 else "turbo"]

print(f"Loading {model} (first time downloads it)...")
transcribe(__import__("numpy").zeros(SAMPLE_RATE, dtype="float32"), model)

levels = []
rec = Recorder(on_level=levels.append)
print(f"🎙  Speak now for {seconds:.0f}s...")
rec.start()
time.sleep(seconds)
audio = rec.stop()
print(f"Captured {len(audio) / SAMPLE_RATE:.1f}s, peak level {max(levels or [0]):.2f}"
      + ("  ← very quiet: check mic permission for your terminal" if max(levels or [0]) < 0.05 else ""))

t = time.time()
text = transcribe(audio, model, language="en")
print(f"\n📝 {text!r}\n   (transcribed in {time.time() - t:.2f}s)")
