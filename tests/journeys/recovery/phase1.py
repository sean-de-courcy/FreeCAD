"""Phase 1 of the crash-recovery walk: build one designed document in the GUI, wait for the
auto-recovery snapshot, then idle until the driver kills this process by its PID.

Run by driver.py as `FreeCAD.exe phase1.py` with WALK_CASE (tabs | unnamed | steps | saved) and WALK_OUT.
Writes in $WALK_OUT: at_snapshot.json (the state the snapshot should hold), at_kill.json (the state at
the moment of the kill), files.json (the recovery files), ready.json (the driver's signal to kill).
"""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk_common as W  # noqa: E402

import FreeCAD as App  # noqa: E402

W.guard()


def gui():
    import FreeCADGui as Gui

    return Gui


def step(doc, label, fn):
    """One accepted step on the undo line: a transaction around fn, then a recompute."""
    doc.openTransaction(label)
    fn()
    doc.recompute()
    doc.commitTransaction()
    W.pump(0.4)
    W.log("step %s" % label)


def pad_in(doc, container, name, w, h, length):
    import Part

    V = App.Vector
    body = doc.addObject("PartDesign::Body", name + "Body")
    if container is not None:
        container.addObject(body)
    sk = body.newObject("Sketcher::SketchObject", name + "Sketch")
    xy = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
    sk.AttachmentSupport = [(xy, "")]
    sk.MapMode = "FlatFace"
    pts = [V(0, 0, 0), V(w, 0, 0), V(w, h, 0), V(0, h, 0)]
    for i in range(4):
        sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    pad = body.newObject("PartDesign::Pad", name + "Pad")
    pad.Profile = sk
    pad.Length = length
    return body, sk, pad


import Sketcher  # noqa: E402


def new_tab(doc, kind):
    tabs = gui().DocumentTabs
    gui().setActiveDocument(doc.Name)
    name = tabs.create(doc, kind)
    W.pump(0.5)
    W.log("tab created: %s %s" % (kind, name))
    return doc.getObject(name)


def wait_snapshot(doc, since):
    """Block (pumping events) until the auto-recovery timer has written a snapshot of `doc` newer
    than `since`; returns the recovery directory's file list."""
    tdir = doc.TransientDir
    deadline = time.time() + float(os.environ.get("WALK_SNAPSHOT_WAIT", "240"))
    while time.time() < deadline:
        W.pump(1.0)
        f = os.path.join(tdir, "fc_recovery_file.fcstd")
        x = os.path.join(tdir, "fc_recovery_file.xml")
        if os.path.exists(f) and os.path.exists(x) and os.path.getmtime(f) > since:
            W.pump(1.0)
            size = os.path.getsize(f)
            time.sleep(0.5)
            if os.path.getsize(f) == size:
                return W.snapshot_files(tdir)
    raise RuntimeError("no recovery snapshot for %s within the wait (transient dir %s)" % (doc.Name, tdir))


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def build_tabs():
    doc = App.newDocument("TabsDoc")
    W.pump(1.0)
    gui().setActiveDocument(doc.Name)
    step(doc, "Pad implicit", lambda: pad_in(doc, None, "A", 20, 10, 10))
    t2 = new_tab(doc, "PartStudio")
    step(doc, "Pad studio 2", lambda: pad_in(doc, t2, "B", 30, 15, 20))
    t3 = new_tab(doc, "PartStudio")
    step(doc, "Pad studio 3", lambda: pad_in(doc, t3, "C", 5, 5, 3))
    new_tab(doc, "VariableStudio")
    gui().DocumentTabs.switchTo(doc, t2.Name)
    W.pump(0.5)
    return [doc]


def build_unnamed():
    doc = App.newDocument("Unnamed")
    W.pump(1.0)
    gui().setActiveDocument(doc.Name)
    step(doc, "Pad", lambda: pad_in(doc, None, "A", 20, 10, 5))
    return [doc]


def build_early():
    """Killed before the auto-recovery timer has ever fired: nothing was written."""
    doc = App.newDocument("EarlyDoc")
    W.pump(1.0)
    gui().setActiveDocument(doc.Name)
    step(doc, "Pad", lambda: pad_in(doc, None, "A", 20, 10, 5))
    return [doc]


def build_steps():
    """Saved, then steps A (kept by the snapshot) and, after it, step B (the last seconds)."""
    doc = App.newDocument("StepsDoc")
    W.pump(1.0)
    gui().setActiveDocument(doc.Name)
    step(doc, "Pad", lambda: pad_in(doc, None, "A", 20, 10, 10))
    path = os.path.join(W.out_dir(), "steps.FCStd")
    doc.saveAs(path)
    return [doc]


def build_saved():
    doc = App.newDocument("SavedDoc")
    W.pump(1.0)
    gui().setActiveDocument(doc.Name)
    step(doc, "Pad", lambda: pad_in(doc, None, "A", 20, 10, 10))
    path = os.path.join(W.out_dir(), "saved.FCStd")
    doc.saveAs(path)
    return [doc]


def main():
    case = W.case()
    W.log("phase1 %s start" % case)
    docs = {"tabs": build_tabs, "unnamed": build_unnamed, "steps": build_steps, "saved": build_saved, "early": build_early}[case]()
    doc = docs[0]
    saved_path = doc.FileName
    if saved_path:
        W.write_json("disk_before.json", {"path": saved_path, "sha": sha(saved_path), "mtime": os.path.getmtime(saved_path)})
    t_edit = time.time()
    # the edits made after the save
    if case == "steps":
        pad = doc.getObject("APad")
        step(doc, "Length 15", lambda: setattr(pad, "Length", 15))
        t2 = new_tab(doc, "PartStudio")
        step(doc, "Pad studio 2", lambda: pad_in(doc, t2, "B", 8, 8, 8))
        # a step taken and undone: it must not come back
        step(doc, "Length 30", lambda: setattr(pad, "Length", 30))
        doc.undo()
        doc.recompute()
        W.pump(0.5)
        t_edit = time.time()
    elif case == "saved":
        pad = doc.getObject("APad")
        step(doc, "Length 42", lambda: setattr(pad, "Length", 42))
        step(doc, "Pad two", lambda: pad_in(doc, None, "D", 4, 4, 4))
        t_edit = time.time()
    W.log("edits done, waiting for the snapshot")
    if case == "early":
        W.pump(5.0)
        files = W.snapshot_files(doc.TransientDir)
    else:
        files = wait_snapshot(doc, t_edit)
    W.write_json("files.json", files)
    W.write_json("at_snapshot.json", W.describe_all())
    W.log("snapshot seen")
    if case == "steps":
        # the last seconds: a step after the snapshot, which a crash loses
        pad = doc.getObject("APad")
        step(doc, "Length 99", lambda: setattr(pad, "Length", 99))
    W.write_json("at_kill.json", W.describe_all())
    W.write_json("ready.json", {"pid": os.getpid(), "time": time.time()})
    W.log("ready to be killed")
    while True:  # the driver kills us; nothing here ever exits
        W.pump(1.0)


W.run_later(main, 4000)
