import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication

from blenderqueue.updates import LATEST_RELEASE_URL, REPOSITORY_URL, release_status
from blenderqueue.ui.update_dialog import UpdateDialog


class Reply(QObject):
    finished = Signal()

    def __init__(self, status=200, data=None, error=QNetworkReply.NoError):
        super().__init__()
        self.status = status
        self.data = {"tag_name": "v2.0.0"} if data is None else data
        self.problem = error
        self.aborted = False

    def attribute(self, _):
        return self.status

    def error(self):
        return self.problem

    def errorString(self):
        return "Network unavailable"

    def readAll(self):
        return json.dumps(self.data).encode()

    def abort(self):
        self.aborted = True
        self.finished.emit()


class UpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_version_comparison_is_numeric(self):
        self.assertIn("Update available", release_status({"tag_name": "v1.10.0"}, "1.9.0"))
        self.assertIn("up to date", release_status({"tag_name": "v1.0.0"}, "1.0.0"))
        self.assertIn("newer than", release_status({"tag_name": "v1.0.0"}, "1.1.0"))
        self.assertIn("Latest published", release_status({"tag_name": "nightly"}, "1.0.0"))
        with self.assertRaises(ValueError):
            release_status({}, "1.0.0")

    def dialog(self, reply):
        with patch("blenderqueue.ui.update_dialog.QNetworkAccessManager.get", return_value=reply):
            dialog = UpdateDialog()
            self.app.processEvents()
        return dialog

    def test_success_and_download_link(self):
        reply = Reply()
        dialog = self.dialog(reply)
        self.assertFalse(dialog.check_button.isEnabled())
        reply.finished.emit()
        self.assertIn("Update available", dialog.status.text())
        self.assertTrue(dialog.check_button.isEnabled())
        with patch("blenderqueue.ui.update_dialog.QDesktopServices.openUrl", return_value=True) as open_url:
            dialog.download.click()
            self.assertEqual(open_url.call_args.args[0].toString(), LATEST_RELEASE_URL)
            dialog._open(REPOSITORY_URL)
            self.assertEqual(open_url.call_args.args[0].toString(), REPOSITORY_URL)
        dialog.reject()
        dialog.deleteLater()

    def test_failures_remain_usable(self):
        for reply, expected in [
            (Reply(status=404, error=QNetworkReply.ContentNotFoundError), "No public release"),
            (Reply(status=0, error=QNetworkReply.TimeoutError), "Could not check"),
            (Reply(data=[]), "Could not read"),
        ]:
            dialog = self.dialog(reply)
            reply.finished.emit()
            self.assertIn(expected, dialog.status.text())
            self.assertTrue(dialog.download.isEnabled())
            self.assertTrue(dialog.check_button.isEnabled())
            dialog.reject()
            dialog.deleteLater()

    def test_close_aborts_pending_request(self):
        reply = Reply()
        dialog = self.dialog(reply)
        dialog.reject()
        self.assertTrue(reply.aborted)
        self.assertIsNone(dialog._reply)
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
