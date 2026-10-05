"""A per-job outliner with collection and view-layer render restrictions."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMenu, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import theme

NODE_ROLE = Qt.UserRole
FIELDS = {1: ("hide_render", True), 2: ("exclude", True),
          3: ("holdout", False), 4: ("indirect_only", False)}
ICONS = {"MESH": "mesh", "CAMERA": "camera", "LIGHT": "light",
         "CURVE": "path", "CURVES": "path", "ARMATURE": "armature",
         "EMPTY": "empty", "VOLUME": "mesh", "FONT": "rename"}


class VisibilityPanel(QWidget):
    changed = Signal()
    inspectRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._job = None
        self._scene = ""
        self._data = {}
        self._loading = False
        self._read_only = False
        self._items = []
        self._context = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.master = QCheckBox("Override visibility for this job")
        self.master.toggled.connect(self._on_master)
        layout.addWidget(self.master)

        self.scene_label = QLabel()
        self.scene_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.scene_label)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setObjectName("Hint")
        layout.addWidget(self.notice)

        row = QHBoxLayout()
        row.addWidget(QLabel("View layer"))
        self.layer_box = QComboBox()
        self.layer_box.currentIndexChanged.connect(lambda _: self._rebuild())
        row.addWidget(self.layer_box, 1)
        self.layer_use = QCheckBox("Render this layer")
        self.layer_use.toggled.connect(self._on_layer_use)
        row.addWidget(self.layer_use)
        layout.addLayout(row)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search collections and objects…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        row.addWidget(self.search, 1)
        self.refresh_button = QPushButton("Read File")
        self.refresh_button.setIcon(theme.icon("refresh"))
        self.refresh_button.clicked.connect(lambda: self.inspectRequested.emit())
        row.addWidget(self.refresh_button)
        layout.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(("Collection / Object", "Render", "Include", "Holdout",
                                   "Indirect", "State in this layer"))
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(18)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setMinimumSectionSize(54)
        self.tree.setColumnWidth(0, 250)
        for column in range(1, 5):
            self.tree.header().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.tree.setColumnWidth(5, 170)
        tips = {
            1: "Allow this object or collection to render in every view layer. "
               "A hidden or excluded parent collection still hides its contents.",
            2: "Include this collection in the selected view layer.",
            3: "Use this collection as a holdout mask in this view layer.",
            4: "Only contribute indirect lighting in this view layer (Cycles).",
            5: "Collection restrictions for this occurrence. Objects linked in other "
               "collections can still render there. Camera framing, ray visibility, "
               "modifiers, animation and material transparency can also affect the result.",
        }
        for column, tip in tips.items():
            self.tree.headerItem().setToolTip(column, tip)
        layout.addWidget(self.tree, 1)

        row = QHBoxLayout()
        expand = QPushButton("Expand All")
        expand.clicked.connect(self.tree.expandAll)
        row.addWidget(expand)
        collapse = QPushButton("Collapse All")
        collapse.clicked.connect(self.tree.collapseAll)
        row.addWidget(collapse)
        row.addStretch(1)
        self.reset_button = QPushButton("Reset Scene")
        self.reset_button.setToolTip("Use this scene's saved visibility for this job again.")
        self.reset_button.clicked.connect(self._reset_scene)
        row.addWidget(self.reset_button)
        layout.addLayout(row)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("Hint")
        layout.addWidget(self.summary)
        self.set_job(None)

    def _editable(self):
        return bool(self._job and self._job.visibility_enabled and self._data
                    and not self._read_only and not self._job.is_locked)

    def set_job(self, job, read_only=False):
        old_layer = self.layer_box.currentText()
        context = (job.id, job.selected_scene()) if job else None
        same = context == self._context
        self._loading = True
        self._job = job
        self._read_only = read_only
        self._scene = job.selected_scene() if job else ""
        scene = job.scene_info() if job else {}
        # Match Blender's active scene fallback for uninspected/renamed choices.
        self._scene = scene.get("name", self._scene)
        self._data = scene.get("visibility") or {}
        self.master.setChecked(bool(job and job.visibility_enabled))
        self.master.setEnabled(bool(job and self._data and not read_only))
        self.refresh_button.setEnabled(bool(job and not read_only))
        self.scene_label.setText("Scene: " + self._scene if job else "No job selected")
        self.scene_label.setToolTip("Choose the render scene in Render Settings → Scene and Camera.")
        self.layer_box.clear()
        for layer in self._data.get("view_layers", []):
            self.layer_box.addItem(layer["name"])
        if same and self.layer_box.findText(old_layer) >= 0:
            self.layer_box.setCurrentText(old_layer)
        self.layer_box.setEnabled(bool(self._data))
        if read_only:
            message = "This job is rendering. Visibility is locked until it finishes."
        elif job and not self._data:
            message = "Read File to load this job's collection and object hierarchy."
        else:
            message = ("Render and Include must both be on for a collection to render. "
                       "Hidden parent collections affect their contents. Bold controls are job overrides.")
        self.notice.setText(message)
        self._loading = False
        self._rebuild(preserve=same)
        self._context = context

    def _layer(self):
        return next((layer for layer in self._data.get("view_layers", [])
                     if layer["name"] == self.layer_box.currentText()), {})

    def _overrides(self):
        if self._job and self._job.visibility_enabled:
            return self._job.visibility.get(self._scene, {})
        return {}

    def _layer_overrides(self):
        return self._overrides().get("view_layers", {}).get(self.layer_box.currentText(), {})

    def _layer_use_value(self):
        use = self._layer().get("use", True)
        if self._job and self._job.use_overrides:
            group = self._job.group("scene")
            if (group.enabled and group.values.get("use_single_view_layer")
                    and group.values.get("view_layer") in
                    [layer["name"] for layer in self._data.get("view_layers", [])]):
                use = group.values["view_layer"] == self.layer_box.currentText()
        return self._layer_overrides().get("use", use)

    def _rebuild(self, preserve=True):
        if self._loading:
            return
        expanded = {item.data(0, NODE_ROLE)["occurrence"] for item in self._items
                    if item.isExpanded()} if preserve else set()
        had_items = bool(self._items) and preserve
        self._loading = True
        self.tree.clear()
        self._items = []
        root = self._data.get("root")
        if root:
            self._add_collection(self.tree, root, [], root=True)
        for item in self._items:
            meta = item.data(0, NODE_ROLE)
            item.setExpanded(meta["occurrence"] in expanded if had_items
                             else meta["kind"] == "collections" and len(meta["path"]) < 2)
        self._loading = False
        self._refresh_states()
        self._filter(self.search.text())

    def _add_item(self, parent, name, meta, icon):
        item = QTreeWidgetItem(parent, [name])
        item.setData(0, NODE_ROLE, meta)
        item.setIcon(0, theme.icon(icon, theme.ACCENT if meta["kind"] == "collections"
                                   else theme.TEXT_DIM, 16))
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if self._editable():
            flags |= Qt.ItemIsUserCheckable
        item.setFlags(flags)
        self._items.append(item)
        return item

    def _add_collection(self, parent, node, path, root=False):
        meta = {"kind": "collections", "key": node["key"], "path": path,
                "root": root, "saved": node, "occurrence": json.dumps([path])}
        item = self._add_item(parent, "Scene Collection" if root else node["name"], meta, "folder")
        item.setToolTip(0, node.get("library") or "Collection: " + node["name"])
        for child in node.get("children", []):
            self._add_collection(item, child, path + [child["key"]])

        objects = self._data.get("objects", {})
        members = set(node.get("objects", []))
        children = {}
        for key in node.get("objects", []):
            obj = objects.get(key, {})
            parent_key = obj.get("parent") if obj.get("parent") in members else ""
            children.setdefault(parent_key, []).append(key)

        def add_objects(holder, parent_key, ancestry):
            for key in children.get(parent_key, []):
                if key in ancestry or key not in objects:
                    continue
                obj = objects[key]
                data = {"kind": "objects", "key": key, "path": path, "root": False,
                        "saved": obj, "occurrence": json.dumps([path, key])}
                row = self._add_item(holder, obj["name"], data, ICONS.get(obj["type"], "file"))
                detail = obj["type"].replace("_", " ").title()
                if obj.get("instance_collection"):
                    detail += " · Instance of " + obj["instance_collection"]
                if obj.get("library"):
                    detail += "\nLibrary: " + obj["library"]
                row.setToolTip(0, detail)
                add_objects(row, key, ancestry | {key})

        add_objects(item, "", set())

    def _value(self, meta, column):
        field, _ = FIELDS[column]
        if column == 1:
            saved = meta["saved"].get(field, False)
            overrides = self._overrides().get(meta["kind"], {}).get(meta["key"], {})
        else:
            key = json.dumps(meta["path"])
            saved = self._layer().get("collections", {}).get(key, {}).get(field, False)
            overrides = self._layer_overrides().get("collections", {}).get(key, {})
        return overrides.get(field, saved), field in overrides

    def _refresh_states(self):
        self._loading = True
        self.layer_use.setChecked(self._layer_use_value())
        self.layer_use.setEnabled(self._editable())
        self.reset_button.setEnabled(bool(self._job and not self._read_only
                                          and not self._job.is_locked
                                          and self._job.visibility.get(self._scene)))
        restrictions = {}
        for item in self._items:
            meta = item.data(0, NODE_ROLE)
            columns = () if meta["root"] else ((1,) if meta["kind"] == "objects" else FIELDS)
            for column in columns:
                value, overridden = self._value(meta, column)
                inverse = FIELDS[column][1]
                item.setCheckState(column, Qt.Checked if bool(value) != inverse else Qt.Unchecked)
                font = item.font(column)
                font.setBold(overridden)
                item.setFont(column, font)
                item.setToolTip(column, self.tree.headerItem().toolTip(column)
                                + ("\nOverridden for this job." if overridden else "\nUsing file setting."))
            path = tuple(meta["path"])
            if meta["root"]:
                state = "" if self._layer_use_value() else "Layer disabled"
            elif meta["kind"] == "collections":
                state = restrictions.get(path[:-1], "")
                if state not in ("Layer disabled", "Excluded", "Hidden by collection"):
                    if self._value(meta, 2)[0]:
                        state = "Excluded"
                    elif self._value(meta, 1)[0]:
                        state = "Hidden by collection"
                    elif not state and self._value(meta, 3)[0]:
                        state = "Holdout"
                    elif not state and self._value(meta, 4)[0]:
                        state = "Indirect only"
            else:
                # Object parenting does not inherit hide_render in Blender.
                state = "Render off" if self._value(meta, 1)[0] else restrictions.get(path, "")
            if meta["kind"] == "collections":
                restrictions[path] = state
            item.setText(5, state or "Enabled")
            item.setToolTip(5, self.tree.headerItem().toolTip(5))
            item.setForeground(0, QColor(theme.TEXT_DIM if state else theme.TEXT))
        count = sum(len(flags) for kind in ("objects", "collections")
                    for flags in self._overrides().get(kind, {}).values())
        for layer in self._overrides().get("view_layers", {}).values():
            count += int("use" in layer) + sum(len(flags) for flags in layer.get("collections", {}).values())
        self.summary.setText(f"{count} visibility override(s) in this scene. "
                             "Right-click rows to show, hide, or restore file settings. "
                             "Render controls apply independently of Render Settings overrides.")
        self._loading = False

    def _store_value(self, meta, column, value):
        scene = self._job.visibility.setdefault(self._scene, {})
        if column == 1:
            target = scene.setdefault(meta["kind"], {}).setdefault(meta["key"], {})
        else:
            layer = scene.setdefault("view_layers", {}).setdefault(self.layer_box.currentText(), {})
            target = layer.setdefault("collections", {}).setdefault(json.dumps(meta["path"]), {})
        target[FIELDS[column][0]] = value

    def _on_item_changed(self, item, column):
        if self._loading or not self._editable() or column not in FIELDS:
            return
        meta = item.data(0, NODE_ROLE)
        if meta["root"] or (meta["kind"] == "objects" and column != 1):
            return
        checked = item.checkState(column) == Qt.Checked
        self._store_value(meta, column, not checked if FIELDS[column][1] else checked)
        self._refresh_states()  # synchronize other occurrences of linked datablocks
        self.changed.emit()

    def _on_master(self, checked):
        if self._loading or not self._job or self._read_only or self._job.is_locked:
            return
        self._job.visibility_enabled = checked
        self._rebuild()
        self.changed.emit()

    def _on_layer_use(self, checked):
        if self._loading or not self._editable():
            return
        scene = self._job.visibility.setdefault(self._scene, {})
        scene.setdefault("view_layers", {}).setdefault(self.layer_box.currentText(), {})["use"] = checked
        self._refresh_states()
        self.changed.emit()

    def _reset_scene(self):
        if not self._job or self._read_only or self._job.is_locked:
            return
        self._job.visibility.pop(self._scene, None)
        self._refresh_states()
        self.changed.emit()

    def _edit_selection(self, visible=None):
        if not self._editable():
            return
        for item in self.tree.selectedItems():
            meta = item.data(0, NODE_ROLE)
            if meta["root"]:
                continue
            if visible is not None:
                self._store_value(meta, 1, not visible)
            else:
                scene = self._job.visibility.get(self._scene, {})
                scene.get(meta["kind"], {}).pop(meta["key"], None)
                if meta["kind"] == "collections":
                    layer = scene.get("view_layers", {}).get(self.layer_box.currentText(), {})
                    layer.get("collections", {}).pop(json.dumps(meta["path"]), None)
        self._refresh_states()
        self.changed.emit()

    def _context_menu(self, point):
        if not self._editable() or not self.tree.selectedItems():
            return
        menu = QMenu(self)
        menu.addAction("Show in Render", lambda: self._edit_selection(True))
        menu.addAction("Hide in Render", lambda: self._edit_selection(False))
        menu.addSeparator()
        menu.addAction("Use File Settings for Selected", lambda: self._edit_selection())
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def _filter(self, text):
        needle = text.strip().casefold()

        def visit(item, ancestor_match=False):
            match = bool(needle and needle in item.text(0).casefold())
            found = False
            for index in range(item.childCount()):
                found = visit(item.child(index), ancestor_match or match) or found
            visible = not needle or match or ancestor_match or found
            item.setHidden(not visible)
            if needle and found:
                item.setExpanded(True)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))
