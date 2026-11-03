"""Section 3 — AI cleanup: prompt, reply guards, providers (Anthropic SDK mocked, no real calls)."""
import types

import pytest

from dictly import llm
from dictly.config import DEFAULTS

RAW = "um so can you send me the uh report by friday no wait thursday"


def cfg(**kw):
    c = dict(DEFAULTS, ai_enabled=True)
    c.update(kw)
    return c


@pytest.mark.parametrize("reply,expected", [
    ("Can you send me the report by Thursday?", "Can you send me the report by Thursday?"),
    ("Here's the cleaned text: Can you send me the report by Thursday?", "Can you send me the report by Thursday?"),
    ("Sure! Here is the cleaned-up text:\nCan you send me the report by Thursday?",
     "Can you send me the report by Thursday?"),
    ('"Can you send me the report by Thursday?"', "Can you send me the report by Thursday?"),
    ("<dictation>Can you send me the report by Thursday?</dictation>", "Can you send me the report by Thursday?"),
    ("```\nCan you send me the report by Thursday?\n```", "Can you send me the report by Thursday?"),
])
def test_wrappers_are_stripped(reply, expected):
    assert llm._sanitize(reply, RAW) == expected


@pytest.mark.parametrize("reply", [
    "",
    # the model answered instead of cleaning up
    "Sure! I'd be happy to help you send the report. To send it by Thursday, open your email client, attach the "
    "file, address it to the recipient and click send. Let me know if you need anything else!",
    "Thursday.",  # collapsed into a summary
])
def test_bad_replies_are_rejected(reply):
    with pytest.raises(ValueError):
        llm._sanitize(reply, RAW)


def test_lists_are_allowed_to_grow_a_bit():
    raw = "the three things are first fix the login bug second update the docs and third ship it"
    out = "The three things are:\n1. Fix the login bug\n2. Update the docs\n3. Ship it"
    assert llm._sanitize(out, raw) == out


def test_short_dictation_skips_the_ai(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: pytest.fail("should not call the AI"))
    assert llm.cleanup("Thanks!", cfg()) == "Thanks!"


def test_prompt_has_examples_app_context_and_delimits_the_text():
    system, user = llm.build_messages(RAW, cfg(), app_name="Slack")
    assert "Examples" in system and "<dictation>" in system
    assert user.endswith(f"<dictation>{RAW}</dictation>") and "Slack" in user


# -- Anthropic provider (fake SDK client) ---------------------------------------------
class FakeAnthropic:
    calls = []
    reply = "Can you send me the report by Thursday?"
    stop_reason = "end_turn"

    def __init__(self, **kw):
        FakeAnthropic.init = kw
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        FakeAnthropic.calls.append(kw)
        return types.SimpleNamespace(
            stop_reason=FakeAnthropic.stop_reason,
            content=[types.SimpleNamespace(type="thinking", thinking=""),
                     types.SimpleNamespace(type="text", text=FakeAnthropic.reply)])


@pytest.fixture
def fake_anthropic(monkeypatch):
    import anthropic
    FakeAnthropic.calls, FakeAnthropic.stop_reason = [], "end_turn"
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    return FakeAnthropic


def test_anthropic_request(fake_anthropic):
    out = llm.cleanup(RAW, cfg(ai_provider="anthropic", ai_model="claude-opus-5-5", ai_api_key="sk-test"))
    assert out == "Can you send me the report by Thursday?"
    call = fake_anthropic.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["output_config"] == {"effort": "low"}
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["messages"][0]["content"].endswith("</dictation>")
    assert fake_anthropic.init["api_key"] == "sk-test" and fake_anthropic.init["max_retries"] == 0


def test_anthropic_haiku_has_no_fallbacks_and_empty_key_uses_env(fake_anthropic):
    llm.cleanup(RAW, cfg(ai_provider="anthropic", ai_model="claude-haiku-5-5", ai_api_key=""))
    assert "fallbacks" not in fake_anthropic.calls[0] and fake_anthropic.init["api_key"] is None


def test_anthropic_refusal_raises_so_raw_text_is_typed(fake_anthropic):
    fake_anthropic.stop_reason = "refusal"
    with pytest.raises(RuntimeError):
        llm.cleanup(RAW, cfg(ai_provider="anthropic"))


def test_prewarm_only_for_enabled_ollama(monkeypatch):
    started = []
    monkeypatch.setattr(llm.threading, "Thread", lambda target, daemon: types.SimpleNamespace(
        start=lambda: started.append(True)))
    llm.prewarm(cfg(ai_enabled=False))
    llm.prewarm(cfg(ai_provider="openai"))
    assert started == []
    llm.prewarm(cfg(ai_provider="ollama"))
    assert started == [True]


def test_ollama_uses_native_api_with_keep_alive():
    """Ollama's OpenAI-compatible endpoint resets keep_alive to 5 min, unloading the model between dictations."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"message": {"role": "assistant", "content": "Can you send me the report by Thursday?"}})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(out.encode())

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        out = llm.cleanup(RAW, cfg(ai_provider="ollama", ai_base_url=f"http://127.0.0.1:{srv.server_port}/v1"))
    finally:
        srv.shutdown()
    assert out == "Can you send me the report by Thursday?"
    assert seen["path"] == "/api/chat"
    assert seen["body"]["keep_alive"] == llm.KEEP_ALIVE and seen["body"]["stream"] is False


@pytest.mark.parametrize("text,expected", [
    ("Um, so I think we should meet on Friday.", True),
    ("Send it to John, no wait, to Sarah.", True),
    ("The meeting is at 3, I mean 4.", True),
    ("Can you review the the PR?", True),
    ("So, like, we should ship it.", True),
    ("First install Ollama, then pull the model.", True),
    ("I think I would use two heaps here, ordered by eligibility time.", False),
    ("I like this design a lot.", False),          # "like" as a real word
    ("Can you send me the report by Thursday?", False),
])
def test_smart_mode_detects_what_needs_cleanup(text, expected):
    assert llm.needs_cleanup(text) is expected
