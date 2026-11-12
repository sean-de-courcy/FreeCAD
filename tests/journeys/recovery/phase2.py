"""Phase 2 of the crash-recovery walk: the restart after the kill. Watches for the recovery dialog the
way a user would see it, records what it offers, accepts it, and records what came back.

Run by driver.py as `FreeCAD.exe phase2.py` on the same FREECAD_USER_HOME as phase 1.
Writes in $WALK_OUT: offer.json (the dialog and any other modal box), recovered.json (documents open
after recovery), phase2.json (done marker).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walk_common as W  # noqa: E402

import FreeCAD as App  # noqa: E402

W.guard()

from PySide import QtCore, QtWidgets  # noqa: E402

START = time.time()
STATE = {"offer": None, "others": [], "accepted_at": None, "finished_at": None, "idle_since": None}
TIMER = None


def tree_rows(tree):
    rows = []
    headers = [tree.headerItem().text(i) for i in range(tree.columnCount())]

    def walk(item, depth):
        rows.append({"depth": depth, "cols": [item.text(i) for i in range(tree.columnCount())],
                     "tooltip": [item.toolTip(i) for i in range(tree.columnCount())]})
        for i in range(item.childCount()):
            walk(item.child(i), depth + 1)

    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i), 0)
    return headers, rows


def describe_modal(w):
    d = {"class": w.metaObject().className(), "title": w.windowTitle(), "buttons": []}
    for b in w.findChildren(QtWidgets.QAbstractButton):
        if b.isVisible():
            d["buttons"].append({"text": b.text(), "enabled": b.isEnabled()})
    labels = [l.text() for l in w.findChildren(QtWidgets.QLabel) if l.isVisible() and l.text()]
    d["labels"] = labels
    trees = w.findChildren(QtWidgets.QTreeWidget)
    if trees:
        d["headers"], d["rows"] = tree_rows(trees[0])
    return d


def is_recovery(w):
    return "DocumentRecovery" in w.metaObject().className()


def save_probe():
    """Save on a recovered document that has a file: does it go through (A2's guard vs a recovery copy)?"""
    import hashlib
    res = {}
    for name, doc in App.listDocuments().items():
        if not doc.FileName:
            res[name] = "no file name: Save would ask for one (not driven)"
            continue
        before = hashlib.sha256(open(doc.FileName, "rb").read()).hexdigest()
        try:
            doc.save()
            res[name] = "saved"
        except BaseException as e:  # noqa: BLE001
            res[name] = "refused: %r" % (e,)
        after = hashlib.sha256(open(doc.FileName, "rb").read()).hexdigest()
        res[name + " file changed"] = before != after
        res[name + " folder"] = sorted(os.listdir(os.path.dirname(doc.FileName)))
    W.write_json("save_probe.json", res)


def finish():
    W.pump(3.0)
    W.write_json("recovered.json", W.describe_all())
    save_probe()
    W.write_json("offer.json", {"offer": STATE["offer"], "others": STATE["others"],
                                "seconds_to_dialog": STATE.get("t_dialog")})
    W.write_json("phase2.json", {"done": True, "time": time.time()})
    W.log("phase2 done")
    W.hard_exit(0)


def poll():
    try:
        w = QtWidgets.QApplication.activeModalWidget()
        if w is not None and is_recovery(w):
            if STATE["offer"] is None:
                STATE["t_dialog"] = round(time.time() - START, 1)
                STATE["offer"] = describe_modal(w)
                W.log("recovery dialog seen: %d rows" % len(STATE["offer"].get("rows", [])))
                ok = w.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok)
                ok.click()  # Recover
                STATE["accepted_at"] = time.time()
                W.pump(1.0)
                STATE["after_recover"] = describe_modal(w)
            elif STATE["finished_at"] is None and time.time() - STATE["accepted_at"] > 1.0:
                ok = w.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok)
                if ok.text().replace("&", "") == "Finish":
                    STATE["after_recover"] = describe_modal(w)
                    W.write_json("after_recover.json", STATE["after_recover"])
                    STATE["finished_at"] = time.time()
                    ok.click()
                    QtCore.QTimer.singleShot(500, finish)
                    TIMER.stop()
        elif w is not None:
            d = describe_modal(w)
            STATE["others"].append(d)
            W.log("other modal: %s %s" % (d["class"], d["title"]))
            w.reject()
        else:
            # no modal widget: after startup has settled with no dialog, the restart offered nothing
            if STATE["offer"] is None and time.time() - START > float(os.environ.get("WALK_NODIALOG_WAIT", "60")):
                W.log("no recovery dialog within the wait")
                TIMER.stop()
                finish()
    except BaseException:  # noqa: BLE001
        import traceback

        W.log("EXCEPTION\n" + traceback.format_exc())
        W.write_json("error.json", {"traceback": traceback.format_exc()})
        W.hard_exit(3)


W.log("phase2 start")
TIMER = QtCore.QTimer()
TIMER.setInterval(300)
TIMER.timeout.connect(poll)
TIMER.start()
