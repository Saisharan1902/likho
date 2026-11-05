"""Compare speech models on YOUR voice.

    .venv/bin/python scripts/bench.py record           # read ~12 sentences aloud (press Enter to start/stop each)
    .venv/bin/python scripts/bench.py run              # accuracy (WER) + speed for every model on those clips
    .venv/bin/python scripts/bench.py run --raw        # same, without trimming/normalising (to see what prepare() buys)
    .venv/bin/python scripts/bench.py history          # side-by-side outputs on your past dictations (data/audio)

Clips are stored in data/bench/. Lower WER = better (0% = every word right).
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from likho.audio import SAMPLE_RATE, Recorder, load_wav, prepare, save_wav  # noqa: E402
from likho.config import DATA_DIR, Config  # noqa: E402
from likho.transcriber import MODELS, transcribe, warm_up  # noqa: E402

BENCH = DATA_DIR / "bench"
SENTENCES = [
    "Hi, how are you doing today?",
    "My name is Ada Lovelace and I'm building a dictation app.",
    "Can you send me the deck before the standup tomorrow?",
    "Let's meet on Wednesday at three thirty in the afternoon.",
    "Push the latest changes to GitHub and open a pull request.",
    "The Kubernetes cluster ran out of memory last night.",
    "Add a retry with exponential backoff to the upload function.",
    "Thanks!",
    "I think we should, no wait, let's do it on Friday instead.",
    "Order two coffees, one with oat milk and one black.",
    "Remind me to call Priya about the PostgreSQL migration.",
    "Stop.",
]


def words(s):
    s = s.lower().replace("-", " ")
    return re.sub(r"[^\w\s']", "", s).split()


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)], len(r)


def record():
    BENCH.mkdir(parents=True, exist_ok=True)
    rec = Recorder(warm=True)
    time.sleep(0.5)
    refs = {}
    print("Read each sentence naturally, like you would when dictating.\n")
    for i, s in enumerate(SENTENCES, 1):
        input(f"[{i}/{len(SENTENCES)}] Press Enter, then say:  “{s}”")
        rec.start()
        input("   🎙  recording… press Enter when done")
        audio = rec.stop()
        save_wav(BENCH / f"{i:02}.wav", audio)
        refs[f"{i:02}.wav"] = s
        print(f"   saved {len(audio) / SAMPLE_RATE:.1f}s")
    (BENCH / "refs.json").write_text(json.dumps(refs, indent=2))
    print(f"\nDone. Now run:  .venv/bin/python scripts/bench.py run")


def run(models, raw, dictionary):
    refs = json.loads((BENCH / "refs.json").read_text())
    clips = {name: load_wav(BENCH / name) for name in refs}
    summary = []
    for model in models:
        print(f"\n=== {model}")
        warm_up(model)
        errs = total = 0
        secs = 0.0
        for name, ref in refs.items():
            audio = clips[name] if raw else prepare(clips[name])
            t = time.monotonic()
            hyp = transcribe(audio, model, "en", dictionary) if audio is not None else ""
            secs += time.monotonic() - t
            e, n = wer(ref, hyp)
            errs, total = errs + e, total + n
            print(f"  {'✓' if e == 0 else '✗'} {name}  {hyp!r}" + ("" if e == 0 else f"   ← {ref!r}"))
        summary.append((model, errs / total, secs / len(refs)))
    print("\n  WER     avg time   model")
    for model, w, s in sorted(summary, key=lambda x: x[1]):
        print(f"  {w:5.1%}   {s:5.2f}s    {model}")


def history(models):
    files = sorted((DATA_DIR / "audio").glob("*.wav"), key=lambda p: int(p.stem))
    if not files:
        sys.exit("No recordings in data/audio yet.")
    out = {}
    for model in models:
        warm_up(model)
        for f in files:
            audio = prepare(load_wav(f))
            t = time.monotonic()
            text = transcribe(audio, model, "en") if audio is not None else "∅ (no speech)"
            out.setdefault(f.name, []).append((model.split("/")[-1], text, time.monotonic() - t))
    for name, rows in out.items():
        print(f"\n{name}")
        for model, text, secs in rows:
            print(f"   {model:28} {secs:4.2f}s  {text}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["record", "run", "history"])
    ap.add_argument("--models", nargs="*", default=list(MODELS)[:2], help="model ids (default: Parakeet + Whisper turbo)")
    ap.add_argument("--raw", action="store_true", help="skip trimming/normalising")
    ap.add_argument("--no-dict", action="store_true", help="ignore your custom dictionary")
    a = ap.parse_args()
    if a.mode == "record":
        record()
    elif a.mode == "run":
        run(a.models, a.raw, [] if a.no_dict else Config()["dictionary"])
    else:
        history(a.models)
