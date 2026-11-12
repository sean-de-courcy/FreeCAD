"""Shared helpers of the crash-recovery walk (ops#640 A3). Imported by phase1.py and phase2.py inside FreeCAD.

The walk (walk.sh -> driver.py): phase 1 builds a designed document in the GUI, lets the auto-recovery
timer write its snapshot, and the driver kills the FreeCAD process by its PID (no shutdown code runs).
Phase 2 starts FreeCAD again on the same FREECAD_USER_HOME, drives the recovery dialog and writes what
came back. Every record is a JSON file in $WALK_OUT.
"""
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def out_dir():
    return os.environ["WALK_OUT"]


def case():
    return os.environ["WALK_CASE"]


def log(msg):
    with open(os.path.join(out_dir(), "walk.log"), "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))


def write_json(name, data):
    with open(os.path.join(out_dir(), name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)


def hard_exit(code):
    """TerminateProcess on ourselves: no teardown, no Save prompt, user.cfg not written."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k.TerminateProcess(k.GetCurrentProcess(), code)
    os._exit(code)


def guard():
    """Refuse to run on anything but the walk's own scratch home (CLAUDE.md: never the real settings)."""
    import FreeCAD as App

    home = os.environ.get("FREECAD_USER_HOME", "")
    cfg = os.path.normcase(os.path.abspath(App.getUserConfigDir()))
    want = os.path.normcase(os.path.abspath(home)) if home else ""
    appdata = os.path.normcase(os.environ.get("APPDATA", "<none>"))
    if not home or cfg != want or cfg.startswith(appdata) or "a3-home" not in cfg:
        with open(os.path.join(out_dir(), "guard-refused.txt"), "w") as f:
            f.write("config dir %s, home %s\n" % (cfg, home))
        hard_exit(2)


def tab_objects(doc):
    """Top-level tab objects of a document: Part Studios and Assemblies are top-level App::Part, a
    Variable Studio and a Drawing are their own objects (App/DocumentTabs.cpp isTabObject)."""
    res = []
    for o in doc.Objects:
        if o.TypeId == "App::Part" and not o.InList:
            res.append(o)
        elif o.TypeId.startswith("Spreadsheet::") or "Variable" in o.TypeId or o.TypeId.startswith("TechDraw::DrawPage"):
            res.append(o)
    return res


def describe_doc(doc):
    """What a document holds that the user would check: tabs, features, values, shapes."""
    import FreeCAD as App

    d = {"label": doc.Label, "file": doc.FileName, "uid": getattr(doc, "Uid", ""), "objects": {}}
    try:
        import FreeCADGui as Gui

        d["activeTab"] = Gui.DocumentTabs.activeTab(doc)
        gd = Gui.getDocument(doc.Name)
        d["modified"] = bool(gd.Modified)
    except Exception as e:  # noqa: BLE001
        d["activeTabError"] = repr(e)
    d["tabs"] = sorted(o.Name for o in tab_objects(doc))
    for o in doc.Objects:
        e = {"type": o.TypeId, "label": o.Label}
        for prop in ("Length", "Radius", "Size", "Type", "Occurrences"):
            if hasattr(o, prop):
                try:
                    v = getattr(o, prop)
                    e[prop] = v.Value if hasattr(v, "Value") else (v if isinstance(v, (int, float, str)) else str(v))
                except Exception:  # noqa: BLE001
                    pass
        sh = getattr(o, "Shape", None)
        if sh is not None and not sh.isNull():
            try:
                e["volume"] = round(sh.Volume, 6)
                e["faces"] = len(sh.Faces)
            except Exception:  # noqa: BLE001
                pass
        e["state"] = list(o.State)
        d["objects"][o.Name] = e
    return d


def describe_all():
    import FreeCAD as App

    return {name: describe_doc(doc) for name, doc in sorted(App.listDocuments().items())}


def pump(seconds):
    from PySide import QtCore, QtWidgets

    end = time.time() + seconds
    while time.time() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.02)


def run_later(fn, delay_ms):
    """Run fn from the event loop once startup is done, writing any traceback to walk.log."""
    from PySide import QtCore

    def wrapped():
        try:
            fn()
        except BaseException:  # noqa: BLE001
            log("EXCEPTION\n" + traceback.format_exc())
            write_json("error.json", {"traceback": traceback.format_exc()})
            hard_exit(3)

    QtCore.QTimer.singleShot(delay_ms, wrapped)


def snapshot_files(temp_dir):
    """The recovery files under the cache: {relative path: size}."""
    res = {}
    for root, _dirs, files in os.walk(temp_dir):
        for f in files:
            p = os.path.join(root, f)
            res[os.path.relpath(p, temp_dir)] = os.path.getsize(p)
    return res
