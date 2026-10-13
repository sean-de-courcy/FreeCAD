# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""The CI reopen gate (FreeCAD-CH ops#323, notes/beta-compatibility.md 3.3, 3.4).

Every committed generation (`gen<k>/`, saved by `make_generation.py`) is reopened by this build
and compared with the records saved with it (`<model>.oracle.json`, Part's `CompatRecord`):

1. **open:** at the open, no recompute: properties, references by geometry, shapes, names;
2. **recompute:** after touching every object and recomputing: the full record, sketches'
   degrees of freedom included, and which objects are still Touched (only those the saving build
   left so: features held below the reorder bar, which a model's roll-forward step then
   recomputes and compares, `models.ROLL_FORWARD`);
3. **round trip:** saved (in a temporary copy) and reopened: the file has this build's
   `ForkRelease`, and the record matches again;
4. (upgrades: once an upgrade registry exists, beta-compatibility.md 2.4.)

Each pass also fails on a console line that says a reference or link was lost. The **rehearsal**
runs passes 1-2 again in a FreeCADCmd with FREECAD_TEST_NAMING_REVISION_OFFSET=1, so every file
looks older and takes the full naming migration: it must move nothing back and break nothing, and
every reference and shape must stay the same (names aren't compared there).

The passes run in two child FreeCADCmd processes (the gate and the rehearsal, in parallel), so
their console lines can be read: the child marks each step on stderr (`@@COMPAT <label>`), where
the console writes too. A model of several documents (a part and an assembly) is opened both
ways: its documents in order, and its last document alone.

Locally: `FreeCADCmd -t PartDesignTests.Compat.TestCompatCorpus`. FREECAD_COMPAT_CORPUS points
the gate at another corpus folder (holding `gen<k>/` folders); FREECAD_COMPAT_REPORT receives
the records of a failing pass (by default the child's temporary folder, named in the message).
Each pass prints a `COMPAT-DRIFT` line with the largest float difference it saw, from which the
tolerances (`CompatRecord.TOLERANCE`) are calibrated on both CI platforms.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
import zipfile

import FreeCAD as App

import CompatRecord

# Size budget of the committed corpus (3.1): raising it is the coordinator's call.
GENERATION_BUDGET = 3 * 1024 * 1024
CORPUS_BUDGET = 10 * 1024 * 1024

# Console lines that say a reference or a link was lost.
BAD_LINES = (
    "missing element reference",
    "Lost link",
    "not found in document",
    "Link broken",
    "Traceback",
)

MARKER = "@@COMPAT "
MIGRATION = re.compile(
    r"Document '([^']*)': (\d+) element references re-derived from their geometry after a "
    r"naming change: (\d+) moved back to their element, (\d+) broken"
)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
# One deadline for both children (they run in parallel): well inside CI's test step limits.
CHILD_TIMEOUT = 600


def corpusFolder():
    return os.environ.get("FREECAD_COMPAT_CORPUS") or os.path.dirname(os.path.abspath(__file__))


def generations():
    """{"gen<k>": folder} of the corpus's generations: every gen<k> folder, so one that lost its
    MANIFEST fails instead of dropping out."""
    found = {}
    folder = corpusFolder()
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if re.fullmatch(r"gen\d+", name) and os.path.isdir(path):
            found[name] = path
    return found


def manifest(folder):
    with open(os.path.join(folder, "MANIFEST"), encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------------------------
# The child: opens, recomputes and saves the corpus's files
# ---------------------------------------------------------------------------------------------


def _mark(label):
    sys.stdout.flush()
    os.write(2, f"\n{MARKER}{label}\n".encode("utf-8"))


def _closeAll():
    for name in list(App.listDocuments()):
        App.closeDocument(name)


def _stem(doc):
    return os.path.splitext(os.path.basename(doc.FileName))[0]


def _documentAttribute(path, name):
    with zipfile.ZipFile(path) as z:
        xml = z.read("Document.xml").decode("utf-8", errors="replace")
    found = re.search(r"<Document [^>]*\b" + name + r'="([^"]*)"', xml)
    return found.group(1) if found else None


def buildNamingRevision(folder):
    """The naming revision this build saves (every save writes it), from a scratch file."""
    doc = App.newDocument("CompatRevisionProbe")
    try:
        path = os.path.join(folder, "revision-probe.FCStd")
        doc.saveAs(path)
        return int(_documentAttribute(path, "NamingRevision"))
    finally:
        App.closeDocument(doc.Name)


class _Step:
    """One model opened one way: its documents in a fresh copy, opened, recomputed, saved."""

    def __init__(self, label, genFolder, model, stems, order, work, report):
        self.label = label
        self.toOpen = stems if order == "ordered" else stems[-1:]
        self.folder = os.path.join(work, label.replace("/", "-"))
        self.report = report
        os.makedirs(self.folder)
        for stem in stems:
            shutil.copy2(os.path.join(genFolder, stem + ".FCStd"), self.folder)
        with open(os.path.join(genFolder, model + ".oracle.json"), encoding="utf-8") as fh:
            oracle = json.load(fh)
        # as saved (a recompute must give it) and as the saving build reopened it (an open must)
        self.saved = oracle["records"]
        deltas = oracle.get("openedDelta", {})
        self.opened = {
            stem: CompatRecord.applyDelta(record, deltas.get(stem))
            for stem, record in self.saved.items()
        }
        # After a touch-all recompute, with what the saving build left Touched: as saved, and as
        # reopened after a save (the file keeps an object's Touched state).
        self.recomputed = json.loads(json.dumps(self.saved))
        self.roundTripped = json.loads(json.dumps(self.opened))
        for stem, names in oracle.get("stillTouched", {}).items():
            for name in names:
                self.recomputed[stem]["objects"][name]["touched"] = True
                self.roundTripped[stem]["objects"][name]["touched"] = True
        self.result = {}
        from PartDesignTests.Compat import models

        self.rollForward = models.ROLL_FORWARD.get(model)

    def open(self):
        """Opens the documents in order; {stem: document} of the ones opened by name."""
        docs = {}
        for stem in self.toOpen:
            path = os.path.join(self.folder, stem + ".FCStd")
            doc = App.openDocument(path)
            docs[stem] = doc
        return docs

    def compare(self, passName, docs, expected, stage, names, touched=True):
        t0 = time.perf_counter()
        lines, drifts = [], []
        for stem, doc in docs.items():
            actual = CompatRecord.record(doc, names=names)
            found, drift = CompatRecord.compare(
                expected[stem], actual, stage, names=names, touched=touched
            )
            lines += [f"{stem}: {line}" for line in found]
            drifts.append(drift)
            if found:
                name = f"{self.label.replace('/', '-')}.{passName}.{stem}"
                base = os.path.join(self.report, name)
                CompatRecord.dump(expected[stem], base + ".expected.json")
                CompatRecord.dump(actual, base + ".actual.json")
        worst = max(drifts, key=lambda d: d["abs"]) if drifts else None
        self.result[passName] = {
            "differences": lines,
            "drift": worst,
            "compareSeconds": time.perf_counter() - t0,
        }

    def run(self, stage, names, roundTrip):
        t0 = time.perf_counter()
        _mark(self.label + "/open")
        docs = self.open()
        openSeconds = time.perf_counter() - t0
        # a forced naming migration touches what it migrates at the open
        self.compare("open", docs, self.opened, stage, names, touched=stage != "rehearsal")
        _mark(self.label + "/recompute")
        t1 = time.perf_counter()
        everything = list(App.listDocuments().values())
        for doc in everything:
            for obj in doc.Objects:
                obj.touch()
        # documents loaded through a link first, then the opened ones in their order
        opened = {d.Name for d in docs.values()}
        for doc in [d for d in everything if d.Name not in opened] + list(docs.values()):
            doc.recompute()
        recomputed = time.perf_counter()
        recomputeStage = "recompute" if stage == "open" else stage
        self.compare("recompute", docs, self.recomputed, recomputeStage, names)
        self.result["seconds"] = {"open": openSeconds, "recompute": recomputed - t1}
        if roundTrip:
            _mark(self.label + "/roundtrip")
            releases = {}
            for stem, doc in docs.items():
                doc.save()
                releases[stem] = _documentAttribute(doc.FileName, "ForkRelease")
            _closeAll()
            docs = self.open()
            self.compare("roundtrip", docs, self.roundTripped, "recompute", names)
            self.result["roundtrip"]["releases"] = releases
            if self.rollForward:
                self.rollForwardPass(docs, names)
        _mark(self.label + "/end")
        _closeAll()

    def rollForwardPass(self, docs, names):
        """Features the recompute pass can't reach (held below the reorder bar) recomputed by
        the model's step (`models.ROLL_FORWARD`), and compared with the saved record: their
        shapes as computed before the bar was rolled back. `touched` is left out (they were
        held when saved)."""
        _mark(self.label + "/rollforward")
        held = self.rollForward(docs)
        lines, drifts = [], []
        for stem, doc in docs.items():

            def only(record):
                objects = {}
                for name in held:
                    entry = dict(record["objects"][name])
                    entry.pop("touched", None)
                    objects[name] = entry
                return {"objects": objects}

            actual = only(CompatRecord.record(doc, names=names))
            found, drift = CompatRecord.compare(
                only(self.saved[stem]), actual, "recompute", names=names
            )
            lines += [f"{stem}: {line}" for line in found]
            drifts.append(drift)
        self.result["rollforward"] = {
            "differences": lines,
            "drift": max(drifts, key=lambda d: d["abs"]) if drifts else None,
            "objects": held,
        }


def childMain(outPath):
    """Runs every generation's models through the passes and writes the results as JSON.

    FREECAD_COMPAT_CHILD=gate runs the open, recompute and round-trip passes; =rehearsal runs
    open and recompute with the naming migration forced (the parent sets the test aid)."""
    kind = os.environ.get("FREECAD_COMPAT_CHILD", "gate")
    work = os.path.realpath(
        tempfile.mkdtemp(prefix=f"{kind}-", dir=os.environ.get("FREECAD_COMPAT_WORK"))
    )
    report = os.environ.get("FREECAD_COMPAT_REPORT") or work
    os.makedirs(report, exist_ok=True)
    result = {
        "kind": kind,
        "work": work,
        "report": report,
        "forkRelease": App.getForkRelease(),
        "namingRevision": buildNamingRevision(work),
        "namesSkipped": [],
        "steps": {},
    }
    for gen, genFolder in generations().items():
        try:
            info = manifest(genFolder)
        except Exception as e:
            result["steps"][gen] = {"error": f"{gen}: no readable MANIFEST ({e})"}
            continue
        names = kind == "gate" and info.get("namingRevision") == result["namingRevision"]
        if kind == "gate" and not names:
            result["namesSkipped"].append(
                f"{gen} (naming revision {info.get('namingRevision')}, this build's "
                f"{result['namingRevision']})"
            )
        stage = "open" if kind == "gate" else "rehearsal"
        for model, stems in info["models"].items():
            orders = ["ordered"]
            if kind == "gate" and len(stems) > 1:
                orders.append("alone")
            for order in orders:
                label = f"{gen}/{model}/{order}"
                step = None
                try:
                    step = _Step(label, genFolder, model, stems, order, work, report)
                    step.run(stage, names, roundTrip=kind == "gate")
                    step.result["names"] = names
                    result["steps"][label] = step.result
                    passes = [v for v in step.result.values() if isinstance(v, dict)]
                    if not any(p.get("differences") for p in passes):
                        shutil.rmtree(step.folder, ignore_errors=True)
                except Exception:
                    _mark(label + "/end")
                    partial = step.result if step else {}
                    partial["error"] = traceback.format_exc()
                    result["steps"][label] = partial
                    try:
                        _closeAll()
                    except Exception:
                        pass
    with open(outPath, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)


CHILD_SCRIPT = """\
import os, traceback
try:
    from PartDesignTests.Compat import TestCompatCorpus
    TestCompatCorpus.childMain(os.environ["FREECAD_COMPAT_CHILD_OUT"])
except Exception:
    with open(os.environ["FREECAD_COMPAT_CHILD_OUT"] + ".error", "w") as fh:
        fh.write(traceback.format_exc())
os._exit(0)
"""


# ---------------------------------------------------------------------------------------------
# The parent: starts the children, reads their results and logs
# ---------------------------------------------------------------------------------------------


def _freecadCmd():
    from PartDesignTests.TestNamingDump import _freecadCmd

    return _freecadCmd()


def segments(log):
    """{label: [console lines]} of the child's log, split at its markers."""
    out = {}
    current = None
    for line in ANSI.sub("", log).splitlines():
        if line.startswith(MARKER):
            label = line[len(MARKER) :].strip()
            current = None if label.endswith("/end") else label
            if current:
                out.setdefault(current, [])
            continue
        if current is not None and line.strip():
            out[current].append(line)
    return out


_children = None


def children():
    """{"gate": result, "rehearsal": result}, each with its log's segments under "console".
    Runs the two children once per process, in parallel."""
    global _children
    if _children is not None:
        return _children
    global _work
    _work = work = os.path.realpath(tempfile.mkdtemp(prefix="compat-gate-"))
    script = os.path.join(work, "child.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(CHILD_SCRIPT)
    runs = {}
    for kind in ("gate", "rehearsal"):
        env = dict(os.environ)
        env.pop("FREECAD_TEST_NAMING_REVISION_OFFSET", None)
        env["FREECAD_COMPAT_CORPUS"] = corpusFolder()
        env["FREECAD_COMPAT_WORK"] = work
        env["FREECAD_COMPAT_CHILD"] = kind
        if kind == "rehearsal":
            env["FREECAD_TEST_NAMING_REVISION_OFFSET"] = "1"
        out = os.path.join(work, kind + ".json")
        env["FREECAD_COMPAT_CHILD_OUT"] = out
        logPath = os.path.join(work, kind + ".log")
        log = open(logPath, "w")
        proc = subprocess.Popen(
            [_freecadCmd(), script], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=work
        )
        runs[kind] = (proc, out, log, logPath)
    _children = {}
    deadline = time.monotonic() + CHILD_TIMEOUT
    for kind, (proc, out, log, logPath) in runs.items():
        timedOut = False
        try:
            proc.wait(timeout=max(1.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            timedOut = True
        log.close()
        with open(logPath, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if os.path.isfile(out):
            with open(out, encoding="utf-8") as fh:
                result = json.load(fh)
        else:
            error = out + ".error"
            if os.path.isfile(error):
                reason = open(error).read()
            else:
                markers = [l for l in text.splitlines() if l.startswith(MARKER)]
                last = markers[-1][len(MARKER) :] if markers else "before the first model"
                how = f"timed out after {CHILD_TIMEOUT} s" if timedOut else "crashed"
                reason = f"{how} (exit {proc.returncode}) in step {last} (log {logPath})"
            result = {"ERROR": reason}
        result["console"] = segments(text)
        result["log"] = logPath
        result["fullLog"] = text
        _children[kind] = result
    return _children


_work = None


def _badLines(lines):
    return [line for line in lines if any(bad in line for bad in BAD_LINES)]


def _allClean():
    """Whether both children ran and every step passed (then the temporary folder goes)."""
    for result in (_children or {}).values():
        if "ERROR" in result:
            return False
        for label, step in result["steps"].items():
            if "error" in step:
                return False
            for passName, found in step.items():
                if isinstance(found, dict) and found.get("differences"):
                    return False
                if _badLines(result["console"].get(f"{label}/{passName}", [])):
                    return False
    return True


def tearDownModule():
    if _work and _allClean() and not os.environ.get("FREECAD_COMPAT_KEEP"):
        shutil.rmtree(_work, ignore_errors=True)


def _printDrift(kind, passName, steps):
    worst = None
    for label, step in steps.items():
        drift = (step.get(passName) or {}).get("drift")
        if drift and (worst is None or drift["abs"] > worst[1]["abs"]):
            worst = (label, drift)
    if worst:
        label, drift = worst
        print(
            f"COMPAT-DRIFT {sys.platform} {kind} {passName}: abs={drift['abs']:.3e} "
            f"rel={drift['rel']:.3e} at {label} {drift['where']}"
        )


class TestCompatCorpus(unittest.TestCase):
    """The CI reopen gate: every committed generation reopens unchanged (module docstring)."""

    def child(self, kind):
        result = children()[kind]
        self.assertNotIn("ERROR", result, f"{kind} child: {result.get('ERROR')}")
        self.assertTrue(result["steps"], f"{kind} child ran no model ({result['log']})")
        return result

    def checkPass(self, kind, passName, optional=False):
        """Fails for each step whose pass differs or logged a lost reference. `optional`: only
        the steps that ran the pass (returns how many did)."""
        result = self.child(kind)
        _printDrift(kind, passName, result["steps"])
        ran = 0
        for label, step in result["steps"].items():
            if optional and "error" not in step and passName not in step:
                continue
            ran += 1
            with self.subTest(model=label, passName=passName):
                self.assertNotIn("error", step, f"{label}: {step.get('error')}")
                found = step.get(passName)
                self.assertIsNotNone(found, f"{label}: no {passName} pass")
                problems = list(found["differences"])
                problems += [
                    f"console: {line}"
                    for line in _badLines(result["console"].get(f"{label}/{passName}", []))
                ]
                if problems:
                    self.fail(
                        f"{label}, {passName}: {len(problems)} differences (records in "
                        f"{result['report']}, log {result['log']}):\n" + "\n".join(problems)
                    )
        return ran

    def testGenerationsAreIntact(self):
        """Every gen<k> folder has a MANIFEST; its files are exactly the ones of its models, byte
        for byte (3.5): a committed file or record is never edited, and no model drops out."""
        gens = generations()
        self.assertTrue(gens, f"no generation in {corpusFolder()}")
        for gen, folder in gens.items():
            self.assertTrue(os.path.isfile(os.path.join(folder, "MANIFEST")), f"{gen}: no MANIFEST")
            info = manifest(folder)
            self.assertTrue(info["models"], f"{gen}: no model in its MANIFEST")
            listed = set(info["files"]) | {"MANIFEST"}
            present = {f for f in os.listdir(folder) if not f.startswith(".")}
            self.assertEqual(present, listed, f"{gen}: files not in its MANIFEST, or missing")
            for fileName, digest in info["files"].items():
                with open(os.path.join(folder, fileName), "rb") as fh:
                    actual = hashlib.sha256(fh.read()).hexdigest()
                self.assertEqual(actual, digest, f"{gen}/{fileName} changed since it was saved")
            ofModels = set()
            for model, stems in info["models"].items():
                ofModels |= {s + ".FCStd" for s in stems} | {model + ".oracle.json"}
            self.assertEqual(
                set(info["files"]), ofModels, f"{gen}: listed files and its models' files differ"
            )

    def testConsoleSegments(self):
        """The child's log is split at its markers, and a lost reference's line is found in its
        step's segment (the console checks of every pass rely on it)."""
        log = (
            "start\n"
            f"\n{MARKER}gen0/A/ordered/open\n"
            "\x1b[1;33m<PropertyLinks> PropertyLinks.cpp(1131): A#Fillet.Base missing element "
            "reference A#Pad ;Edge2\x1b[0m\n"
            f"\n{MARKER}gen0/A/ordered/recompute\n"
            f"\n{MARKER}gen0/A/ordered/end\n"
            "between steps\n"
        )
        found = segments(log)
        self.assertEqual(sorted(found), ["gen0/A/ordered/open", "gen0/A/ordered/recompute"])
        self.assertEqual(len(_badLines(found["gen0/A/ordered/open"])), 1)
        self.assertEqual(found["gen0/A/ordered/recompute"], [])

    def testSizeBudget(self):
        """A generation stays under 3 MB, the corpus under 10 MB (3.1)."""
        total = 0
        for gen, folder in generations().items():
            size = sum(os.path.getsize(os.path.join(folder, f)) for f in os.listdir(folder))
            total += size
            self.assertLess(size, GENERATION_BUDGET, f"{gen} is {size} bytes")
        self.assertLess(total, CORPUS_BUDGET, f"the corpus is {total} bytes")

    def testOpen(self):
        """Pass 1: at the open, before any recompute, every record matches."""
        self.checkPass("gate", "open")
        for skipped in self.child("gate").get("namesSkipped", []):
            print(f"COMPAT-NAMES not compared in {skipped}")

    def testRollForward(self):
        """Features held below the reorder bar (the recompute pass leaves them Touched), rolled
        forward and recomputed, match their saved record."""
        ran = self.checkPass("gate", "rollforward", optional=True)
        self.assertGreater(ran, 0, "no model rolled forward (models.ROLL_FORWARD)")

    def testRecompute(self):
        """Pass 2: after touching every object and recomputing, every record matches."""
        self.checkPass("gate", "recompute")

    def testRoundTrip(self):
        """Pass 3: saved by this build and reopened, the file has this build's release and its
        record matches."""
        self.checkPass("gate", "roundtrip")
        result = self.child("gate")
        for label, step in result["steps"].items():
            releases = (step.get("roundtrip") or {}).get("releases", {})
            for stem, release in releases.items():
                self.assertEqual(
                    release, str(result["forkRelease"]), f"{label}: {stem} saved ForkRelease"
                )

    def testRehearsalOpen(self):
        """Rehearsal, pass 1: with the naming revision raised, every file opens as before."""
        self.checkPass("rehearsal", "open")

    def testRehearsalRecompute(self):
        """Rehearsal, pass 2: the forced naming migration moves nothing back and breaks nothing,
        and every reference and shape stays the same."""
        self.checkPass("rehearsal", "recompute")
        result = self.child("rehearsal")
        self.assertIn(
            "FREECAD_TEST_NAMING_REVISION_OFFSET=1", result["fullLog"], "the test aid wasn't on"
        )
        migrated = 0
        for label, lines in result["console"].items():
            for line in lines:
                found = MIGRATION.search(line)
                if not found:
                    continue
                total, moved, broken = (int(found.group(i)) for i in (2, 3, 4))
                migrated += total
                with self.subTest(step=label):
                    self.assertEqual((moved, broken), (0, 0), f"{label}: {line}")
        self.assertGreater(migrated, 0, "the rehearsal migrated no reference")

    def testTimings(self):
        """Not a check: prints the passes' times (3.7) as COMPAT-TIME lines."""
        for kind in ("gate", "rehearsal"):
            result = self.child(kind)
            opened = sum(s.get("seconds", {}).get("open", 0) for s in result["steps"].values())
            recomputed = sum(
                s.get("seconds", {}).get("recompute", 0) for s in result["steps"].values()
            )
            print(
                f"COMPAT-TIME {sys.platform} {kind}: {len(result['steps'])} steps, open "
                f"{opened:.2f} s, recompute {recomputed:.2f} s"
            )
