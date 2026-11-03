"""The dashboard in its own native window (an embedded web view of the local dashboard)."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

from . import macos


class _Page(QWebEnginePage):
    def __init__(self, local_url, parent):
        super().__init__(parent)
        self.local_url = local_url

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        # Only the dashboard itself loads inside the window; any other link opens in the browser.
        if url.toString().startswith(self.local_url):
            return True
        import webbrowser
        webbrowser.open(url.toString())
        return False


class DashboardWindow(QMainWindow):
    def __init__(self, url, icon: QIcon | None = None):
        super().__init__()
        self.url = url
        self.setWindowTitle("Dictly")
        if icon:
            self.setWindowIcon(icon)
        self.resize(1120, 820)
        self.setMinimumSize(420, 480)

        self.view = QWebEngineView(self)
        self.view.setPage(_Page(url, self.view))
        s = self.view.settings()
        s.setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, True)  # History → Copy
        s.setAttribute(QWebEngineSettings.JavascriptCanPaste, True)
        self.setCentralWidget(self.view)
        self._loaded = False

        QShortcut(QKeySequence.Close, self, activated=self.close)          # ⌘W
        QShortcut(QKeySequence.Refresh, self, activated=self.view.reload)  # ⌘R

    def show_and_focus(self):
        if not self._loaded:
            self.view.load(QUrl(self.url))
            self._loaded = True
        else:
            self.view.page().runJavaScript("window.refreshAll && refreshAll()")
        self.show()
        self.raise_()
        macos.activate_app()  # Dictly has no Dock icon, so bring it forward explicitly
        self.activateWindow()
