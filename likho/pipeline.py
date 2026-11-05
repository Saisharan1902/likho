"""What happens to a finished recording: transcribe → replacements → (AI cleanup) → paste → save.

No UI code here, so it can be tested end-to-end with synthetic audio.
"""
import time
import traceback

from . import config, llm
from .audio import SAMPLE_RATE, prepare, save_wav
from .overlay import DONE, ERROR, IDLE, TRANSCRIBING
from .transcriber import apply_replacements, transcribe

MIN_SECONDS = 0.4  # shorter = accidental tap, ignore it


def log(msg):
    """Diagnostics for ~/Library/Logs/Likho.log — counts and timings only, never what you said."""
    print(f"[dictation] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def default_output(text, mode):
    from . import macos
    how = macos.insert_text(text + " " if mode != "copy" else text, mode)  # trailing space between dictations
    log(f"inserted via {how}")
    return how != "blocked"


class Pipeline:
    def __init__(self, cfg, db, output=default_output, on_state=lambda s: None, on_status=lambda **kw: None):
        self.cfg, self.db = cfg, db
        self.output, self.on_state, self.on_status = output, on_state, on_status

    def handle(self, audio, app_name=None, released_at=None):
        """Returns the saved history row, or None if nothing was typed.

        released_at: time.monotonic() when the key was let go, to record the delay you actually feel.
        """
        released_at = released_at or time.monotonic()
        duration = len(audio) / SAMPLE_RATE
        speech = prepare(audio) if duration >= MIN_SECONDS else None
        if speech is None:
            reason = "too short" if duration < MIN_SECONDS else "no speech detected"
            log(f"dropped {duration:.1f}s recording: {reason}")
            self.on_state(IDLE)  # accidental tap or no speech — don't let the model invent words
            return None
        self.on_state(TRANSCRIBING)
        try:
            cfg = self.cfg.all()
            t0 = time.monotonic()
            raw = transcribe(speech, cfg["model"], cfg["language"], cfg["dictionary"])
            transcribe_sec = time.monotonic() - t0
            if not raw:
                log(f"dropped {duration:.1f}s recording: model heard no words")
                self.on_state(IDLE)  # silence
                return None
            log(f"{duration:.1f}s audio ({len(speech) / SAMPLE_RATE:.1f}s after trimming) → "
                f"{len(raw.split())} words in {transcribe_sec:.2f}s, app={app_name!r}")

            text = apply_replacements(raw, cfg["replacements"])
            ai_used, ai_sec = False, None
            if cfg["ai_enabled"] and len(text.split()) >= llm.MIN_WORDS and (
                    cfg["ai_mode"] == "always" or llm.needs_cleanup(text)):
                t1 = time.monotonic()
                try:
                    text = llm.cleanup(text, cfg, app_name) or text
                    ai_used = True
                    self.on_status(error=None)
                except Exception as e:  # AI down / misconfigured: still type the raw text
                    self.on_status(error=f"AI cleanup failed ({type(e).__name__}) — typed raw text")
                ai_sec = round(time.monotonic() - t1, 2)

            pasted = self.output(text, cfg["paste_mode"]) is not False
            total_sec = round(time.monotonic() - released_at, 2)
            row_id = self.db.add(raw_text=raw, final_text=text, duration_sec=round(duration, 2),
                                 transcribe_sec=round(transcribe_sec, 2), word_count=len(text.split()),
                                 app_name=app_name, model=cfg["model"], ai_used=int(ai_used),
                                 ai_sec=ai_sec, total_sec=total_sec)
            if cfg["save_audio"]:
                path = config.AUDIO_DIR / f"{row_id}.wav"
                save_wav(path, audio)
                self.db.set_audio(row_id, str(path))
            if not pasted:  # Accessibility is off: the text is on the clipboard instead
                self.on_status(error="Can't type into apps — turn on Accessibility for Likho. "
                                     "Your text was copied: press ⌘V")
                self.on_state(ERROR)
            else:
                self.on_state(DONE)
            return self.db.get(row_id)
        except Exception:
            traceback.print_exc()
            self.on_state(ERROR)
            return None
