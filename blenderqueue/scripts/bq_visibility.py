"""Inspect and apply per-job render visibility inside Blender."""

import json


def datablock_key(block):
    library = getattr(block, "library", None)
    return json.dumps([block.name, library.filepath if library else ""])


def path_key(path):
    return json.dumps(path)


def describe_visibility(scene):
    objects = {}

    def collection_node(collection):
        members = []
        for obj in sorted(collection.objects, key=lambda o: o.name.casefold()):
            key = datablock_key(obj)
            members.append(key)
            objects[key] = {
                "name": obj.name, "type": obj.type,
                "parent": datablock_key(obj.parent) if obj.parent else "",
                "hide_render": bool(obj.hide_render),
                "library": obj.library.filepath if obj.library else "",
                "instance_collection": (obj.instance_collection.name
                                        if obj.instance_collection else ""),
            }
        return {
            "key": datablock_key(collection), "name": collection.name,
            "hide_render": bool(collection.hide_render),
            "library": collection.library.filepath if collection.library else "",
            "objects": members,
            "children": [collection_node(c) for c in sorted(
                collection.children, key=lambda c: c.name.casefold())],
        }

    root = collection_node(scene.collection)
    layers = []
    for layer in scene.view_layers:
        collections = {}

        def visit(node, path):
            collections[path_key(path)] = {
                "exclude": bool(node.exclude), "holdout": bool(node.holdout),
                "indirect_only": bool(node.indirect_only),
            }
            for child in node.children:
                visit(child, path + [datablock_key(child.collection)])

        visit(layer.layer_collection, [])
        layers.append({"name": layer.name, "use": bool(layer.use),
                       "collections": collections})
    return {"root": root, "objects": objects, "view_layers": layers}


def apply_visibility(scene, overrides, emit):
    """Set only explicit overrides; preserve all other saved file settings."""
    if not overrides:
        return

    def assign(owner, field, value, label):
        if not isinstance(value, bool):
            emit("skip", key="visibility", msg="Invalid visibility value for " + label)
            return
        try:
            setattr(owner, field, value)
            if field == "hide_render" and getattr(owner, "animation_data", None):
                # Keyframes/NLA are evaluated again at every frame. A constant
                # driver pins this one job override without muting a potentially
                # shared Action or changing the original .blend on disk.
                curve = owner.driver_add(field)
                curve.mute = False
                driver = curve.driver
                driver.type = "SCRIPTED"
                for variable in list(driver.variables):
                    driver.variables.remove(variable)
                driver.expression = "True" if value else "False"
        except Exception as exc:
            emit("skip", key="visibility", msg="%s: %s" % (label, exc))

    collections, objects = {}, {}

    def collect(node):
        collections[datablock_key(node)] = node
        for obj in node.objects:
            objects[datablock_key(obj)] = obj
        for child in node.children:
            collect(child)

    collect(scene.collection)
    for kind, blocks in (("collections", collections), ("objects", objects)):
        for key, values in overrides.get(kind, {}).items():
            block = blocks.get(key)
            if block is None:
                emit("skip", key="visibility", msg="Missing %s entry %s" % (kind, key))
            elif "hide_render" in values:
                assign(block, "hide_render", values["hide_render"], block.name)

    for name, values in overrides.get("view_layers", {}).items():
        layer = scene.view_layers.get(name)
        if layer is None:
            emit("skip", key="visibility", msg="Missing view layer " + name)
            continue
        if "use" in values:
            assign(layer, "use", values["use"], name)
        nodes = {}

        def collect_layer(node, path):
            nodes[path_key(path)] = node
            for child in node.children:
                collect_layer(child, path + [datablock_key(child.collection)])

        collect_layer(layer.layer_collection, [])
        for key, flags in values.get("collections", {}).items():
            node = nodes.get(key)
            if node is None:
                emit("skip", key="visibility", msg="Missing collection in layer " + name)
                continue
            for flag in ("exclude", "holdout", "indirect_only"):
                if flag in flags:
                    assign(node, flag, flags[flag], name + " / " + node.name)
    emit("info", msg="Applied per-job visibility for scene '%s'" % scene.name)
