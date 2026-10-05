import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from blenderqueue.models import Job, Status
from blenderqueue.store import AppSettings, load_queue, save_queue
from blenderqueue.ui.main_window import MainWindow
from blenderqueue.ui.visibility_panel import NODE_ROLE, VisibilityPanel


def key(name):
    return json.dumps([name, ""])


def fixture_job():
    def collection(name, objects=(), children=()):
        return {"name": name, "key": key(name), "hide_render": False,
                "objects": [key(obj) for obj in objects], "children": list(children)}

    nested = collection("Nested", ["Child"])
    root = collection("Scene Collection", children=[
        collection("Set", ["Parent", "Child"], [nested]),
        collection("Alternate", children=[nested]),
    ])
    flags = {}

    def visit(node, path):
        flags[json.dumps(path)] = {"exclude": False, "holdout": False, "indirect_only": False}
        for child in node["children"]:
            visit(child, path + [child["key"]])

    visit(root, [])
    data = {"root": root, "objects": {
        key("Parent"): {"name": "Parent", "type": "EMPTY", "hide_render": False, "parent": ""},
        key("Child"): {"name": "Child", "type": "MESH", "hide_render": False, "parent": key("Parent")},
    }, "view_layers": [{"name": name, "use": True, "collections": copy.deepcopy(flags)}
                       for name in ("Beauty", "Shadow")]}
    return Job(name="Fixture", info={"active_scene": "Scene", "scenes": [
        {"name": "Scene", "visibility": data}]})


class VisibilityModelTests(unittest.TestCase):
    def test_old_queue_has_no_visibility_overrides(self):
        job = Job.from_dict({"name": "Old job", "blend_path": "old.blend"})
        self.assertFalse(job.visibility_enabled)
        self.assertEqual(job.render_config()["visibility"], {})

    def test_persistence_duplicate_and_master_toggle(self):
        job = fixture_job()
        job.visibility_enabled = True
        job.visibility = {"Scene": {"objects": {key("Child"): {"hide_render": True}}}}
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "roundtrip.bqueue")
            save_queue(path, [job])
            restored = load_queue(path)[0]
        self.assertEqual(restored.visibility, job.visibility)
        self.assertEqual(restored.info, job.info)
        self.assertEqual(restored.render_config()["visibility"], job.visibility)
        clone = restored.duplicate()
        clone.visibility["Scene"]["objects"][key("Child")]["hide_render"] = False
        self.assertTrue(restored.visibility["Scene"]["objects"][key("Child")]["hide_render"])
        restored.visibility_enabled = False
        self.assertEqual(restored.render_config()["visibility"], {})
        self.assertTrue(restored.visibility)

    def test_disabled_scene_group_uses_active_scene(self):
        job = fixture_job()
        job.use_overrides = True
        job.group("scene").values["scene"] = "Another scene"
        self.assertEqual(job.selected_scene(), "Scene")
        job.group("scene").enabled = True
        self.assertEqual(job.selected_scene(), "Another scene")


class VisibilityPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.job = fixture_job()
        self.panel = VisibilityPanel()
        self.panel.set_job(self.job)
        self.panel.master.click()

    def tearDown(self):
        self.panel.deleteLater()
        self.app.processEvents()

    def rows(self, name):
        return [item for item in self.panel._items if item.text(0) == name]

    def test_parenting_and_linked_object_controls(self):
        parent = self.rows("Parent")[0]
        parent.setCheckState(1, Qt.Unchecked)
        child = next(item for item in self.rows("Child") if item.parent() == parent)
        self.assertEqual(child.text(5), "Enabled")
        child.setCheckState(1, Qt.Unchecked)
        self.assertEqual(len(self.rows("Child")), 3)
        self.assertTrue(all(item.checkState(1) == Qt.Unchecked for item in self.rows("Child")))
        self.assertTrue(self.job.render_config()["visibility"]["Scene"]["objects"][key("Child")]["hide_render"])

    def test_nested_collection_and_layer_restrictions(self):
        self.rows("Set")[0].setCheckState(1, Qt.Unchecked)
        nested = self.rows("Nested")
        self.assertEqual(nested[0].text(5), "Hidden by collection")
        self.assertEqual(nested[1].text(5), "Enabled")
        nested[1].setCheckState(2, Qt.Unchecked)
        self.assertEqual(nested[1].text(5), "Excluded")
        self.panel.layer_box.setCurrentText("Shadow")
        self.assertEqual(self.rows("Nested")[1].checkState(2), Qt.Checked)
        self.panel.layer_use.click()
        self.assertEqual(self.rows("Alternate")[0].text(5), "Layer disabled")
        self.panel.layer_box.setCurrentText("Beauty")
        self.assertTrue(self.panel.layer_use.isChecked())
        self.assertEqual(self.rows("Nested")[1].checkState(2), Qt.Unchecked)

    def test_reset_master_and_job_isolation(self):
        self.rows("Child")[0].setCheckState(1, Qt.Unchecked)
        before = copy.deepcopy(self.job.visibility)
        self.panel.master.click()
        self.assertEqual(self.rows("Child")[0].checkState(1), Qt.Checked)
        self.assertEqual(self.job.visibility, before)
        self.panel.master.click()
        second = fixture_job()
        self.panel.set_job(second)
        self.assertEqual(self.rows("Child")[0].checkState(1), Qt.Checked)
        self.panel.set_job(self.job)
        self.assertEqual(self.rows("Child")[0].checkState(1), Qt.Unchecked)
        self.panel.reset_button.click()
        self.assertEqual(self.job.visibility, {})

    def test_running_job_cannot_change_visibility(self):
        self.job.status = Status.RUNNING
        self.panel.set_job(self.job, read_only=True)
        self.assertFalse(self.panel.master.isEnabled())
        self.assertFalse(self.panel.layer_use.isEnabled())
        item = self.rows("Child")[0]
        self.assertFalse(item.flags() & Qt.ItemIsUserCheckable)
        item.setCheckState(1, Qt.Unchecked)
        self.panel._on_master(False)
        self.panel._reset_scene()
        self.assertEqual(self.job.visibility, {})

    def test_search_keeps_parent_chain_and_collection_contents(self):
        self.panel.search.setText("Nested")
        self.assertFalse(self.rows("Set")[0].isHidden())
        self.assertFalse(self.rows("Nested")[0].child(0).isHidden())
        self.assertTrue(self.rows("Parent")[0].isHidden())
        self.panel.search.clear()
        self.assertTrue(all(not item.isHidden() for item in self.panel._items))

    def test_refresh_can_upgrade_old_inspection(self):
        self.panel.set_job(Job(info={"scenes": [{"name": "Old"}]}))
        self.assertFalse(self.panel.master.isEnabled())
        requests = []
        self.panel.inspectRequested.connect(lambda: requests.append(True))
        self.panel.refresh_button.click()
        self.assertEqual(requests, [True])

    def test_main_window_binds_and_saves_visibility(self):
        with patch.object(MainWindow, "_first_run"), patch("blenderqueue.store.load_settings", return_value=AppSettings()), patch.object(MainWindow, "autosave") as save:
            window = MainWindow()
            window.jobs = [self.job]
            window.refresh_list()
            window.queue_view.select_ids([self.job.id])
            index = window.detail.indexOf(window.visibility_panel)
            self.assertEqual(window.detail.tabText(index), "Per Job Visibility")
            self.assertTrue(window.act_updates.isEnabled())
            save.reset_mock()
            child = next(item for item in window.visibility_panel._items if item.text(0) == "Child")
            child.setCheckState(1, Qt.Unchecked)
            self.assertTrue(save.called)
            self.job.status = Status.RUNNING
            window._show_details(self.job)
            self.assertFalse(window.visibility_panel.master.isEnabled())
            window.deleteLater()
            self.app.processEvents()

    def test_copy_settings_includes_independent_visibility_and_skips_running_job(self):
        self.rows("Child")[0].setCheckState(1, Qt.Unchecked)
        target, running = fixture_job(), fixture_job()
        running.status = Status.RUNNING
        with patch.object(MainWindow, "_first_run"), patch("blenderqueue.store.load_settings", return_value=AppSettings()), patch.object(MainWindow, "autosave"):
            window = MainWindow()
            window.jobs = [self.job, target, running]
            with patch.object(window, "selected_jobs", return_value=window.jobs):
                window.copy_overrides()
            self.assertEqual(target.visibility, self.job.visibility)
            self.assertTrue(target.visibility_enabled)
            self.assertEqual(running.visibility, {})
            target.visibility["Scene"]["objects"][key("Child")]["hide_render"] = False
            self.assertTrue(self.job.visibility["Scene"]["objects"][key("Child")]["hide_render"])
            window.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
