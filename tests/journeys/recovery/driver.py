"""Driver of the crash-recovery walk (ops#640 A3). Run by walk.sh inside the checkout's pixi environment.

usage: python driver.py <FreeCAD.exe> <out base> [case ...]      cases: tabs unnamed steps saved (default: all)

Per case: a fresh FREECAD_USER_HOME (seeded with the Onshape pack's AutoSaveTimeout, scaled by
WALK_TIMEOUT_MIN, default 1 minute where the pack has 5), phase1.py builds the document and waits for the
recovery snapshot, this driver kills that FreeCAD.exe by its PID (TerminateProcess: the process runs no
shutdown code, the lock file is released by the OS), phase2.py restarts FreeCAD on the same home and drives
the recovery dialog. report.md in the out base compares what came back with what was there.
Environment: WALK_ONSCREEN=1 shows the windows (default offscreen), OPS_SCRIPTS the ops repo's scripts folder
(for the settings-folder guard).
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OPS_SCRIPTS = os.environ.get("OPS_SCRIPTS", "C:/CustomFreeCAD/scripts")
CASES = ["tabs", "unnamed", "steps", "saved", "early"]
PHASE_TIMEOUT = 420


def freecad_count():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-Process FreeCAD -ErrorAction SilentlyContinue | Measure-Object).Count"],
                         capture_output=True, text=True).stdout.strip()
    return int(out or 0)


def guard(home):
    r = subprocess.run([sys.executable, os.path.join(OPS_SCRIPTS, "userhome_guard.py"), home])
    if r.returncode != 0:
        sys.exit("driver: userhome_guard refused %s" % home)


def seed_cfg(home):
    minutes = os.environ.get("WALK_TIMEOUT_MIN", "1")
    with open(os.path.join(home, "user.cfg"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n<FCParameters>\n'
                '  <FCParamGroup Name="Root">\n    <FCParamGroup Name="BaseApp">\n'
                '      <FCParamGroup Name="Preferences">\n        <FCParamGroup Name="Document">\n'
                '          <FCInt Name="AutoSaveTimeout" Value="%s"/>\n        </FCParamGroup>\n'
                '      </FCParamGroup>\n    </FCParamGroup>\n  </FCParamGroup>\n</FCParameters>\n' % minutes)


def launch(exe, script, env, log):
    return subprocess.Popen([exe, script], env=env, stdin=subprocess.DEVNULL,
                            stdout=open(log, "w"), stderr=subprocess.STDOUT)


def wait_file(path, proc, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(path):
            return True
        if proc.poll() is not None:
            return os.path.exists(path)
        time.sleep(1)
    return False


def run_case(exe, base, case):
    cdir = os.path.join(base, case)
    home = os.path.join(cdir, "home")
    out = os.path.join(cdir, "out")
    shutil.rmtree(cdir, ignore_errors=True)
    os.makedirs(home)
    os.makedirs(out)
    guard(home)
    seed_cfg(home)
    env = dict(os.environ)
    env.update({"FREECAD_USER_HOME": home, "WALK_CASE": case, "WALK_OUT": out})
    if not os.environ.get("WALK_ONSCREEN"):
        env["QT_QPA_PLATFORM"] = "offscreen"
    res = {"case": case}
    if freecad_count() >= 3:
        sys.exit("driver: three FreeCAD.exe already run; the machine's limit is four (notes/session-rules.md)")

    p1 = launch(exe, os.path.join(HERE, "phase1.py"), env, os.path.join(out, "phase1.stdout.txt"))
    res["pid1"] = p1.pid
    ok = wait_file(os.path.join(out, "ready.json"), p1, PHASE_TIMEOUT)
    res["phase1_ready"] = ok
    res["phase1_exit_before_kill"] = p1.poll()
    if p1.poll() is None:
        p1.kill()  # TerminateProcess on this PID only: the crash
        p1.wait()
    res["phase1_exit"] = p1.returncode
    if not ok:
        return res
    time.sleep(2)
    temp = os.path.join(home, "temp")
    res["temp_after_kill"] = sorted(os.listdir(temp)) if os.path.isdir(temp) else []

    p2 = launch(exe, os.path.join(HERE, "phase2.py"), env, os.path.join(out, "phase2.stdout.txt"))
    res["pid2"] = p2.pid
    res["phase2_done"] = wait_file(os.path.join(out, "phase2.json"), p2, PHASE_TIMEOUT)
    if p2.poll() is None:
        p2.kill()
        p2.wait()
    res["phase2_exit"] = p2.returncode
    res["temp_after_recovery"] = sorted(os.listdir(temp)) if os.path.isdir(temp) else []
    return res


def load(out, name):
    p = os.path.join(out, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


KEYS = ("type", "label", "Length", "Radius", "Size", "Type", "Occurrences", "volume", "faces")


def diff_docs(expected, actual):
    """Lines saying what differs between two {doc: description} maps (documents matched by label)."""
    lines = []
    by_label = {d["label"]: d for d in actual.values()}
    for name, e in expected.items():
        a = by_label.get(e["label"])
        if a is None and len(actual) == 1 and len(expected) == 1:
            a = list(actual.values())[0]
        if a is None:
            lines.append("document %r did not come back" % e["label"])
            continue
        if a["label"] != e["label"]:
            lines.append("label %r came back as %r" % (e["label"], a["label"]))
        if a["tabs"] != e["tabs"]:
            lines.append("tabs %s came back as %s" % (e["tabs"], a["tabs"]))
        if a.get("activeTab") != e.get("activeTab"):
            lines.append("active tab %r came back as %r" % (e.get("activeTab"), a.get("activeTab")))
        for oname, eo in e["objects"].items():
            ao = a["objects"].get(oname)
            if ao is None:
                lines.append("object %s (%s) is missing" % (oname, eo["type"]))
                continue
            for k in KEYS:
                if eo.get(k) != ao.get(k):
                    lines.append("%s.%s: %r came back as %r" % (oname, k, eo.get(k), ao.get(k)))
        for oname in a["objects"]:
            if oname not in e["objects"]:
                lines.append("extra object %s (%s)" % (oname, a["objects"][oname]["type"]))
    return lines


def report(base, results):
    md = ["# Crash recovery walk", "", "Run: %s" % os.path.basename(base), ""]
    for res in results:
        case = res["case"]
        out = os.path.join(base, case, "out")
        md.append("## %s" % case)
        md.append("")
        if not res.get("phase1_ready"):
            err = load(out, "error.json")
            md.append("phase 1 never became ready (exit %s): %s" % (res.get("phase1_exit"),
                                                                    (err or {}).get("traceback", "see walk.log")))
            md.append("")
            continue
        offer = load(out, "offer.json") or {}
        o = offer.get("offer")
        md.append("- killed pid %s; recovery files before the kill: %s" % (res["pid1"], list((load(out, "files.json") or {}).keys())))
        md.append("- temp folder after the kill: %s" % res.get("temp_after_kill"))
        if o is None:
            md.append("- **the restart offered nothing** (no recovery dialog); other boxes: %s" % [x["title"] for x in offer.get("others", [])])
        else:
            md.append("- the restart offered a dialog %r after %s s: %s" % (o["title"], offer.get("seconds_to_dialog"),
                                                                           [r["cols"] for r in o.get("rows", [])]))
        md.append("- other boxes: %s" % [(x["class"], x["title"]) for x in offer.get("others", [])])
        rec = load(out, "recovered.json")
        snap = load(out, "at_snapshot.json")
        kill = load(out, "at_kill.json")
        if rec is not None:
            md.append("- documents open after recovery: %s" % [(d["label"], d["file"], d.get("modified")) for d in rec.values()])
            md.append("- against the state at the snapshot: %s" % (diff_docs(snap, rec) or "same"))
            md.append("- against the state at the kill: %s" % (diff_docs(kill, rec) or "same"))
        sp = load(out, "save_probe.json")
        if sp:
            md.append("- Save on the recovered document: %s" % sp)
        disk = load(out, "disk_before.json")
        if disk:
            import hashlib
            now = hashlib.sha256(open(disk["path"], "rb").read()).hexdigest() if os.path.exists(disk["path"]) else None
            md.append("- the saved file on disk: %s" % ("unchanged" if now == disk["sha"] else "CHANGED or missing"))
        md.append("- temp folder after recovery: %s" % res.get("temp_after_recovery"))
        md.append("- exits: phase 1 %s, phase 2 %s" % (res.get("phase1_exit"), res.get("phase2_exit")))
        md.append("")
    path = os.path.join(base, "report.md")
    open(path, "w", encoding="utf-8").write("\n".join(md) + "\n")
    return path


def main():
    exe, base = sys.argv[1], sys.argv[2]
    cases = sys.argv[3:] or CASES
    os.makedirs(base, exist_ok=True)
    results = []
    for case in cases:
        print("== case", case, flush=True)
        res = run_case(exe, base, case)
        results.append(res)
        json.dump(res, open(os.path.join(base, case + ".run.json"), "w"), indent=1)
        print(res, flush=True)
    print("report:", report(base, results))


main()
