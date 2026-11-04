# SPDX-License-Identifier: LGPL-2.1-or-later

"""A beta file's history-less results on a build that names them by a verified match (MLN; FreeCAD-CH,
ops#502, PLAN decision 183 (2)): the port for beta files.

`Fixtures/BetaMapless.FCStd` was saved by a build of the beta's naming (ForkNamingRevision 15) with
`Fixtures/make_beta_mapless.py`: a Part::Box and a script's boolean with no element map, whose consumers
hold bare indices, and a script's compound with one-section IDX names; no `ElementIdNext` counter. Its
docstring describes the designed geometry. Each test opens the file in a child FreeCADCmd (the naming
migration's line is a console warning) and scores every reference by geometry: right, or loud (its
owner broken), never on another element."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import FreeCAD as App

from PartDesignTests.TestNamingDump import _freecadCmd

FIXTURE = os.path.join(os.path.dirname(__file__), "Fixtures", "BetaMapless.FCStd")
# The Compat corpus model IndexToldGroups (Compat/models_partdesign.py), saved by make_generation on
# a build of the beta's naming (revision 15): CornerBall, a sphere attached to a vertex of a Cut of
# two boxes' compound, holds a vertex name made from the boxes' IDX edge names
CORNER_FIXTURE = os.path.join(os.path.dirname(__file__), "Fixtures", "BetaIndexToldGroups.FCStd")
# A script's compound of three slabs A, B, C and a Cut of it, saved by a build of the beta's naming
# with `Fixtures/make_beta_plate_abc.py` (review pr399-r3g's G1; decision 260); its docstring
# describes the designed geometry
PLATE_FIXTURE = os.path.join(os.path.dirname(__file__), "Fixtures", "BetaPlateABC.FCStd")

MIGRATION = re.compile(
    r"(\d+) element references re-derived from their geometry after a naming change: "
    r"(\d+) moved back to their element, (\d+) broken"
)

# The child: opens the file, applies the scenario's steps, and writes for each consumer whether it
# is valid and the geometry of the element its reference names now
_CHILD = r"""
import json, os, traceback, zipfile
import FreeCAD as App
import Part
V = App.Vector
out = os.environ["BETA_MAPLESS_OUT"]

def slabs(order, xb):
    pieces = {"A": Part.makeBox(40, 30, 5), "B": Part.makeBox(40, 30, 5, V(xb, 0, 0))}
    return Part.makeCompound([pieces[k] for k in order])

def same(doc):
    # the script runs again and makes the same shapes
    doc.getObject("Plate").Shape = slabs("AB", 60)
    doc.getObject("Cutout").Shape = Part.makeBox(30, 30, 10).cut(Part.makeCylinder(5, 10, V(15, 15, 0)))

def dropB(doc):
    # the script runs again without B
    doc.getObject("Plate").Shape = slabs("A", 60)

def dropBSlotted(doc):
    # the script runs again without B, A with two through slots: 14 faces, so B's old index
    # (Face7 or later) gives one of A's faces now
    a = Part.makeBox(40, 30, 5)
    for x in (10, 25):
        a = a.cut(Part.makeBox(2, 20, 7, V(x, 5, -1)))
    doc.getObject("Plate").Shape = Part.makeCompound([a])

def bThinToCPlace(doc):
    # the script runs again: B 3 high on C's place, C moved on to x = 300 (review pr399-r3g)
    doc.getObject("Plate").Shape = Part.makeCompound(
        [Part.makeBox(40, 30, 5), Part.makeBox(40, 30, 3, V(120, 0, 0)), Part.makeBox(40, 30, 5, V(300, 0, 0))])

def solverOff(doc):
    # the reference solver off (the corpus's V2 column): the name match alone
    doc.ReferenceSolver = False
    for obj in doc.Objects:
        obj.touch()

def reopen(doc):
    # saved and opened again: what an alias left unused is in the file
    path = os.path.join(os.path.dirname(out), "reopened.FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    return App.openDocument(path)

def edit(doc):
    doc.getObject("Box").Height = 40
    # the script runs again: its pieces in the other order, B 10 mm further
    doc.getObject("Plate").Shape = slabs("BA", 70)
    # the hole 5 mm off
    doc.getObject("Cutout").Shape = Part.makeBox(30, 30, 10).cut(Part.makeCylinder(5, 10, V(10, 15, 0)))

def element(link):
    target, names = link
    name = names[0]
    if name.startswith("?") or not name:
        return {"sub": name}
    shape = target.Shape.getElement(name)
    if name.startswith("Face"):
        u, v = shape.Surface.parameter(shape.CenterOfMass)
        return {"sub": name, "centre": list(shape.CenterOfMass), "normal": list(shape.normalAt(u, v))}
    return {"sub": name, "ends": sorted(list(p.Point) for p in shape.Vertexes)}

def record(doc):
    result = {}
    if doc.getObject("DatumPlateC"):
        for name in ("DatumPlateA", "DatumPlateB", "DatumPlateC", "DatumCutA", "DatumCutB", "DatumCutC"):
            datum = doc.getObject(name)
            result[name] = dict(element(datum.AttachmentSupport[0]), valid=datum.isValid(),
                                status=datum.getStatusString())
        return result
    for name in ("DatumTop", "DatumPlateB", "DatumCutTop"):
        datum = doc.getObject(name)
        result[name] = dict(element(datum.AttachmentSupport[0]), valid=datum.isValid(),
                            status=datum.getStatusString())
    fillet = doc.getObject("BoxFillet")
    edge = "Edge%d" % fillet.Edges[0][0]
    result["BoxFillet"] = dict(element((doc.getObject("Box"), (edge,))), valid=fillet.isValid(),
                               status=fillet.getStatusString())
    result["names"] = {n: sorted(doc.getObject(n).Shape.ElementMap)[:3] for n in ("Box", "Plate", "Cutout")}
    result["aliases"] = sum("IDX" in n for n in doc.getObject("Plate").Shape.ElementMap)
    # the name a new pick of B's top gets
    top = result["DatumPlateB"]["sub"]
    result["pick"] = "" if top.startswith("?") else str(doc.getObject("Plate").Shape.getElementMappedName(top))
    return result

try:
    doc = App.openDocument(os.environ["BETA_MAPLESS_FILE"])
    opened = doc.getObject("DatumTop") or doc.getObject("DatumPlateC")
    result = {"opened": record(doc) if opened else None, "steps": []}
    for step in os.environ["BETA_MAPLESS_STEPS"].split(","):
        if step == "corner":
            for obj in doc.Objects:
                obj.touch()
            doc.recompute()
            ball = doc.getObject("CornerBall")
            result["steps"].append({"valid": ball.isValid(), "status": ball.getStatusString(),
                                    "base": list(ball.Placement.Base)})
            continue
        if step == "touch":
            for obj in doc.Objects:
                obj.touch()
        elif step == "reopen":
            doc = reopen(doc)
        else:
            {"same": same, "edit": edit, "dropB": dropB, "dropBSlotted": dropBSlotted,
             "solverOff": solverOff, "bThinToCPlace": bThinToCPlace}[step](doc)
        doc.recompute()
        result["steps"].append(record(doc))
    saved = os.path.join(os.path.dirname(out), "saved.FCStd")
    doc.saveAs(saved)
    result["counter"] = "ElementIdNext=" in zipfile.ZipFile(saved).read("Document.xml").decode()
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
except Exception:
    with open(out + ".error", "w", encoding="utf-8") as fh:
        fh.write(traceback.format_exc())
os._exit(0)
"""

UP = (0, 0, 1)


class TestBetaMapless(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="BetaMapless")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def run_child(self, steps, fixture=FIXTURE):
        """The child's record and the migration lines' (total, moved, broken)."""
        path = os.path.join(self.folder, "beta.FCStd")
        shutil.copyfile(fixture, path)
        script = os.path.join(self.folder, "child.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(_CHILD)
        out = os.path.join(self.folder, "child.json")
        env = dict(os.environ)
        env.pop("FREECAD_TEST_NAMING_REVISION_OFFSET", None)
        env.update(BETA_MAPLESS_FILE=path, BETA_MAPLESS_OUT=out, BETA_MAPLESS_STEPS=steps)
        run = subprocess.run(
            [_freecadCmd(), script],
            env=env,
            cwd=self.folder,
            timeout=600,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log = run.stdout.decode("utf-8", "replace")
        if os.path.isfile(out + ".error"):
            with open(out + ".error", encoding="utf-8") as fh:
                self.fail(fh.read() + "\n" + log)
        with open(out, encoding="utf-8") as fh:
            result = json.load(fh)
        migration = [tuple(int(n) for n in found) for found in MIGRATION.findall(log)]
        return result, migration, log

    def assertFace(self, entry, centre, normal=UP):
        self.assertTrue(entry["valid"], entry)
        self.assertLess((App.Vector(*entry["centre"]) - App.Vector(*centre)).Length, 1e-6, entry)
        self.assertLess((App.Vector(*entry["normal"]) - App.Vector(*normal)).Length, 1e-6, entry)

    def assertFilletEdge(self, entry, height):
        self.assertTrue(entry["valid"], entry)
        self.assertEqual(entry["ends"], [[10, 20, 0], [10, 20, height]], entry)

    def assertSaved(self, entry):
        """The references as the beta saved them: the designed faces and edge."""
        self.assertFace(entry["DatumTop"], (5, 10, 30))
        self.assertFace(entry["DatumPlateB"], (80, 15, 5))
        self.assertFace(entry["DatumCutTop"], centreOfTop(15, 15))
        self.assertFilletEdge(entry["BoxFillet"], 30)

    def assertMigratedCleanly(self, migration, log):
        """The naming migration ran, and moved nothing back and broke nothing."""
        self.assertTrue(migration, log)
        self.assertGreater(sum(total for total, _, _ in migration), 0, log)
        self.assertEqual([(m, b) for _, m, b in migration], [(0, 0)] * len(migration), log)

    def assertBroken(self, entry):
        self.assertFalse(entry["valid"], entry)
        self.assertTrue(entry["sub"].startswith("?"), entry)

    def assertRightOrLoud(self, entry, check, *args):
        """On its element, or its owner broken: never on another element."""
        if entry["valid"]:
            check(entry, *args)
        else:
            self.assertTrue(entry["sub"].startswith("?"), entry)

    def testOpenedAndRecomputedKeepsEveryReference(self):
        """Opened and recomputed with nothing edited: the naming migration re-derives every
        reference from its geometry onto its own element (none moved back, none broken). The box,
        recomputed, carries MLN ids from a counter that starts at 1, and the file saves the
        counter; the script's shapes, which nothing sets again, keep what the beta saved."""
        # Act
        result, migration, log = self.run_child("touch")

        # Assert
        self.assertSaved(result["opened"])
        touched = result["steps"][0]
        self.assertSaved(touched)
        self.assertMigratedCleanly(migration, log)
        names = touched["names"]
        self.assertTrue(all(";MLN;" in n and "IDX" not in n for n in names["Box"]), names)
        self.assertTrue(names["Plate"] and all("IDX" in n for n in names["Plate"]), names)
        self.assertEqual(names["Cutout"], [])
        self.assertTrue(result["counter"])

    def testScriptSetAgainKeepsItsReferencesThroughAliases(self):
        """P-beta (PLAN decision 247): after the migration, the script sets its shapes again,
        unchanged. The compound's elements are matched to the beta's and keep its IDX names as
        aliases, so the datum on B's top stays there. Set again once more, the aliases are gone
        (the references hold the MLN names now) and the datum still holds; then the edits: the
        box's references follow the match, B's top is right or loud."""
        # Act
        result, migration, log = self.run_child("touch,same,same,edit")

        # Assert
        touched, again, twice, edited = result["steps"]
        self.assertSaved(again)
        self.assertGreater(again["aliases"], 0)
        self.assertIn(";MLN;", again["pick"])
        self.assertSaved(twice)
        self.assertEqual(twice["aliases"], 0)
        self.assertFace(edited["DatumTop"], (5, 10, 40))
        self.assertFilletEdge(edited["BoxFillet"], 40)
        self.assertBroken(edited["DatumPlateB"])
        self.assertRightOrLoud(edited["DatumCutTop"], self.assertFace, centreOfTop(10, 15))
        self.assertMigratedCleanly(migration, log)

    def testScriptSetAgainInTheMigrationsRecompute(self):
        """The script sets its shapes again, unchanged, before anything was recomputed: the
        migration and the aliases in one recompute keep every reference, with nothing moved back
        (P-beta 2: an IDX-made name is no name, kept by its place without a warning)."""
        # Act
        result, migration, log = self.run_child("same")

        # Assert
        self.assertSaved(result["steps"][0])
        for name in ("DatumTop", "DatumPlateB", "DatumCutTop"):
            self.assertEqual(result["steps"][0][name]["status"], "Valid")
        self.assertMigratedCleanly(migration, log)

    def testEditedAfterTheMigrationFollowsTheMatch(self):
        """Recomputed once (the migration), then edited: the box taller, the script's slabs in the
        other order with B 10 mm further, the cutout's hole 5 mm off. The box's references follow
        the match (the top face where it went, the fillet's edge grown); the script's are right or
        loud (the beta put B's datum on A's top)."""
        # Act
        result, migration, log = self.run_child("touch,edit")

        # Assert
        touched, edited = result["steps"]
        self.assertSaved(touched)
        self.assertFace(edited["DatumTop"], (5, 10, 40))
        self.assertFilletEdge(edited["BoxFillet"], 40)
        self.assertBroken(edited["DatumPlateB"])
        self.assertRightOrLoud(edited["DatumCutTop"], self.assertFace, centreOfTop(10, 15))

    def testUnusedAliasesAreNotSavedAsNames(self):
        """The aliases given at the script's first run on this build, saved and reopened: the
        references took the MLN names in the recompute that gave the aliases, so when the script
        runs again after the reopen the aliases are dropped, the datum holds, and no IDX name is
        left in the file's names."""
        # Act
        result, migration, log = self.run_child("same,reopen,same")

        # Assert
        again, reopened, twice = result["steps"]
        self.assertSaved(again)
        self.assertSaved(reopened)
        self.assertSaved(twice)
        self.assertEqual(twice["aliases"], 0)
        self.assertEqual(twice["DatumPlateB"]["status"], "Valid")

    def testElementGoneAtTheMigrationBreaks(self):
        """The script runs again without B before anything was recomputed: B's top is gone, so the
        datum's IDX-made name, nameless in the migration (P-beta 2), finds nothing at its place
        and breaks (rule 1), never a pick of A's top."""
        # Act
        result, migration, log = self.run_child("dropB")

        # Assert
        dropped = result["steps"][0]
        self.assertBroken(dropped["DatumPlateB"])
        self.assertFace(dropped["DatumTop"], (5, 10, 30))
        self.assertFace(dropped["DatumCutTop"], centreOfTop(15, 15))

    def testMissingAliasIsNotRetakenWithoutTheSolver(self):
        """Review r3 T1: with the solver off, recomputed (the migration), then the script runs
        again without B and with two slots in A, so that B's old index gives one of A's faces. The
        datum's IDX name is missing: it keeps it and breaks, and never takes the MLN name of the
        face now at that index (the name match would then find that face, silently)."""
        # Act
        result, migration, log = self.run_child("solverOff,dropBSlotted")

        # Assert
        off, dropped = result["steps"]
        self.assertSaved(off)
        self.assertBroken(dropped["DatumPlateB"])
        self.assertFace(dropped["DatumTop"], (5, 10, 30))

    def testIndexMadeVertexNameIsKeptQuietly(self):
        """P-beta 2, recursive (decision 247): CornerBall's saved name is a Cut's vertex made from
        the boxes' IDX edges, index-made all the way down though its own section isn't IDX. The
        migration keeps it by its place with no warning, none moved back. (Without the rule: kept
        by its place with "Index reference: Vertex1 kept by its place after a naming migration",
        1 moved back.)"""
        # Act
        result, migration, log = self.run_child("corner", CORNER_FIXTURE)

        # Assert
        ball = result["steps"][0]
        self.assertTrue(ball["valid"], ball)
        self.assertEqual(ball["status"], "Valid")
        self.assertMigratedCleanly(migration, log)

    def testMemberChangedOntoAnothersPlaceIsLoud(self):
        """P1b (decision 260) on a beta file: recomputed (the migration), then the script sets B 3 high
        on C's place and C at x = 300. "B thinned and moved, C moved on" and "C thinned in place, B
        deleted, a slab appended" make the same compound, so the references to B and C break, in the
        plate and in the cut, and C's never takes the thin slab by its beta IDX name (C2 before P1b
        matched the thin slab to C by place: silent). A's plate reference stays on A's top; the cut's,
        a face the beta named from the plate's IDX edges, is right or loud (an IDX index and an MLN id
        share no source: N1 stays loud, decision 252 (1), ops#583)."""
        # Act
        result, migration, log = self.run_child("touch,bThinToCPlace", PLATE_FIXTURE)

        # Assert
        touched, edited = result["steps"]
        for opened in (result["opened"], touched):
            self.assertFace(opened["DatumPlateA"], (20, 15, 5))
            self.assertFace(opened["DatumPlateB"], (80, 15, 5))
            self.assertFace(opened["DatumPlateC"], (140, 15, 5))
            self.assertFace(opened["DatumCutA"], centreOfNotchedTop())
            self.assertFace(opened["DatumCutB"], (80, 15, 5))
            self.assertFace(opened["DatumCutC"], (140, 15, 5))
        self.assertMigratedCleanly(migration, log)
        self.assertFace(edited["DatumPlateA"], (20, 15, 5))
        self.assertRightOrLoud(edited["DatumCutA"], self.assertFace, centreOfNotchedTop())
        for name in ("DatumPlateB", "DatumPlateC", "DatumCutB", "DatumCutC"):
            with self.subTest(name=name):
                self.assertBroken(edited[name])

    def testEditedBeforeTheFirstRecomputeIsRightOrLoud(self):
        """Edited before anything was recomputed: the migration and the edit in one recompute.
        Each reference is on its element or its owner breaks, never on another element."""
        # Act
        result, migration, log = self.run_child("edit")

        # Assert
        self.assertSaved(result["opened"])
        edited = result["steps"][0]
        for name, centre in (
            ("DatumTop", (5, 10, 40)),
            ("DatumPlateB", (90, 15, 5)),
            ("DatumCutTop", centreOfTop(10, 15)),
        ):
            with self.subTest(name=name):
                self.assertRightOrLoud(edited[name], self.assertFace, centre)
        self.assertRightOrLoud(edited["BoxFillet"], self.assertFilletEdge, 40)


def centreOfTop(x, y):
    """The centre of mass of the 30 x 30 block's top face at z = 10 less the radius-5 hole at (x, y)."""
    import math

    area = 900 - math.pi * 25
    return ((15 * 900 - x * math.pi * 25) / area, (15 * 900 - y * math.pi * 25) / area, 10)


def centreOfNotchedTop():
    """The centre of mass of slab A's top face (40 x 30 at z = 5) less the notch's 5 x 5 corner."""
    area = 1200 - 25
    return ((20 * 1200 - 2.5 * 25) / area, (15 * 1200 - 2.5 * 25) / area, 5)


if __name__ == "__main__":
    unittest.main()
