"""Section 5 — the floating pill. Runs Qt off-screen, so no window appears."""
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from likho import overlay  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _settle(app, pill, frames=40):
    for _ in range(frames):
        pill._animate()
    app.processEvents()


def _ink_pixels(pill):
    img = QImage(pill.size(), QImage.Format_ARGB32)
    img.fill(0)
    pill.render(img)
    return sum(1 for x in range(0, img.width(), 2) for y in range(0, img.height(), 2) if img.pixelColor(x, y).alpha())


def test_state_from_background_thread(app):
    pill = overlay.Pill()
    t = threading.Thread(target=pill.set_state, args=(overlay.RECORDING,))
    t.start()
    t.join()
    app.processEvents()  # delivers the queued signal on the GUI thread
    assert pill.state == overlay.RECORDING


def test_capsule_grows_while_recording_and_waveform_follows_level(app):
    pill = overlay.Pill()
    _settle(app, pill)
    idle_area = _ink_pixels(pill)

    pill.set_state(overlay.RECORDING)
    app.processEvents()
    for _ in range(30):
        pill.set_level(0.9)
        pill._animate()
    assert round(pill._w) == overlay.SIZES[overlay.RECORDING][0]
    assert max(pill._levels) == pytest.approx(0.9)
    assert _ink_pixels(pill) > idle_area * 3


def test_done_reverts_to_idle(app):
    pill = overlay.Pill()
    pill.set_state(overlay.DONE)
    app.processEvents()
    assert pill._revert.isActive()
    pill._revert.timeout.emit()
    assert pill.state == overlay.IDLE


def test_idle_animation_stops_to_save_cpu(app):
    pill = overlay.Pill()
    _settle(app, pill)
    assert not pill._tick.isActive()


@pytest.mark.parametrize("state", [overlay.IDLE, overlay.RECORDING, overlay.LOCKED, overlay.TRANSCRIBING,
                                   overlay.DONE, overlay.ERROR])
def test_every_state_renders(app, state):
    pill = overlay.Pill()
    pill.set_state(state)
    app.processEvents()
    _settle(app, pill)
    assert _ink_pixels(pill) > 0
