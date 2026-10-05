"""Non-blocking GitHub release check with direct download and repository links."""

import json

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)

from .. import __version__
from ..updates import LATEST_RELEASE_API, LATEST_RELEASE_URL, REPOSITORY_URL, release_status


class UpdateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BlenderQueue Updates")
        self.setMinimumWidth(480)
        self._reply = None
        self._closing = False
        self.manager = QNetworkAccessManager(self)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"BlenderQueue {__version__}"))
        self.status = QLabel("Checking GitHub for the latest release…")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        hint = QLabel("Download the latest installer or portable build from GitHub. "
                      "Close BlenderQueue before installing the update.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.download = QPushButton("Download Latest Release")
        self.download.setObjectName("Primary")
        self.download.clicked.connect(lambda: self._open(LATEST_RELEASE_URL))
        row.addWidget(self.download)
        repository = QPushButton("GitHub Repository")
        repository.clicked.connect(lambda: self._open(REPOSITORY_URL))
        row.addWidget(repository)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.check_button = QPushButton("Check Again")
        self.check_button.clicked.connect(self.check)
        row.addWidget(self.check_button)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)
        QTimer.singleShot(0, self.check)

    def check(self):
        if self._reply is not None or self._closing:
            return
        self.check_button.setEnabled(False)
        self.status.setText("Checking GitHub for the latest release…")
        request = QNetworkRequest(QUrl(LATEST_RELEASE_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"BlenderQueue/{__version__}".encode("ascii"))
        request.setTransferTimeout(10000)
        self._reply = self.manager.get(request)
        self._reply.finished.connect(self._finished)

    def _finished(self):
        reply = self._reply
        if reply is None:
            return
        self._reply = None
        try:
            if self._closing:
                return
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            if status == 404:
                self.status.setText("No public release was found. Open the GitHub repository "
                                    "for the latest source and available downloads.")
            elif reply.error() != QNetworkReply.NoError:
                self.status.setText("Could not check for updates: " + reply.errorString()
                                    + ". You can still open the release or repository links.")
            else:
                try:
                    release = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    if not isinstance(release, dict):
                        raise ValueError("Unexpected release response.")
                    self.status.setText(release_status(release, __version__))
                except (ValueError, UnicodeError) as exc:
                    self.status.setText(f"Could not read the release information: {exc}")
            self.check_button.setEnabled(True)
        finally:
            reply.deleteLater()

    def _open(self, url):
        if not QDesktopServices.openUrl(QUrl(url)):
            self.status.setText("Could not open a browser. Visit " + url)

    def done(self, result):
        self._closing = True
        if self._reply is not None:
            self._reply.abort()
        super().done(result)
