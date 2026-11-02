# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review props549-r1 (ops#549, fix/549-pass-through-veto @ d1947bf0bf): a failed feature's
pass-through after the document is saved and opened again, and records retaken on a pass-through.

The models are those of `failure_pass_through.py` (copied: a case imports only harness and models):
- the ring: a square 4 x 4 at the origin padded 1 down (`Plate`); an additive Pipe `Sweep` sweeps
  the Plate's top face round a closed rectangle 30 x 20 in the XZ plane ("Right corner"). The
  Pipe's outer corner (-2, -2, -2) is named by the square sketch's bare vertex name, which the
  Plate's corner (2, 2, 0) carries too (C1). `Lug`: a Pad (0, 0)-(1, 1) from z = 0 up 25 after the
  Sweep (it computes with the Sweep failed: it stands in the Plate);
- the slab: a block 20 x 10 x 10 and a Pad `Boss` 0.1 high on its whole top (C2: the block's top
  is a face of the same size 0.1 below); a Pad `Cap` (16, 2)-(19, 8), 3 high, after it.
The failure: the Sweep's spine relinked to an empty sketch, or the Boss's length 0.

`reopenPlain` saves, closes and opens the document without touching its objects, as FreeCAD's
File > Open does (the harness's `Reopens` touches every object, which re-runs the failed feature).
The failed feature is restored in error (`Invalid="1"`), not touched (a claimed failure is purged).
"""

import os
import shutil
import tempfile

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
X, Y, Z = V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)


class ReviewBase(Scenario):
    abstract = True
    area = "failure pass-through"
    CLASSES = ("D",)
    ISSUE = "ops#549"
    FOUND_BY = "review props549-r1"
    TIER = "F"

    def reopenPlain(self, doc):
        self.folder = tempfile.mkdtemp(prefix="NamingScenario")
        path = os.path.join(self.folder, doc.Name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        doc = App.openDocument(path)
        if doc.Name not in self.documents:
            self.documents.append(doc.Name)
        if hasattr(doc, "ReferenceSolver"):
            doc.ReferenceSolver = self.solver
        self.doc = doc
        self.reloaded(doc)

    def reloaded(self, doc):
        pass

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)

    def datumPoint(self, name, target, predicate):
        point = self.body.newObject("PartDesign::Point", name)
        point.AttachmentSupport = [(target, self.names(target, predicate))]
        point.MapMode = "Vertex"
        return point

    def datumPlane(self, name, target, predicate):
        plane = self.body.newObject("PartDesign::Plane", name)
        plane.AttachmentSupport = [(target, self.names(target, predicate))]
        plane.MapMode = "FlatFace"
        return plane


class RingBase(ReviewBase):
    abstract = True
    half = 2

    def pipeCorner(self):
        return vertex((-self.half, -self.half, -self.half))

    def plateCorner(self):
        return vertex((self.half, self.half, 0))

    def buildRing(self, doc):
        self.body = m.body(doc)
        a = self.half
        self.spine = m.sketch(
            doc,
            "Spine",
            m.polygon([(0, 0), (0, 20), (30, 20), (30, 0)]),
            self.body,
            placement=App.Placement(V(), App.Rotation(X, 90)),
        )
        square = m.sketch(doc, "Square", m.rectangle(-a, -a, a, a), self.body)
        plate = m.pad(self.body, square, 1, "Plate")
        plate.Reversed = True
        doc.recompute()
        top = [
            f"Face{i}"
            for i, f in enumerate(plate.Shape.Faces, 1)
            if abs(f.CenterOfMass.z) < 1e-6 and abs(f.normalAt(0, 0).z) > 0.99
        ]
        self.sweep = self.body.newObject("PartDesign::AdditivePipe", "Sweep")
        self.sweep.Profile = (plate, top)
        self.sweep.Spine = (self.spine, [])
        self.sweep.Transition = "Right corner"
        self.sweep.Refine = False
        doc.recompute()
        if not self.sweep.isValid():
            raise RuntimeError(f"the sweep is invalid: {self.sweep.getStatusString()}")

    def failSweep(self, doc):
        empty = doc.getObject("NoSpine") or m.sketch(doc, "NoSpine", [], self.body)
        self.sweep.Spine = (empty, [])

    def fixSweep(self, doc):
        self.sweep.Spine = (self.spine, [])

    def reloaded(self, doc):
        self.body = doc.getObject("Body")
        self.sweep = doc.getObject("Sweep")
        self.spine = doc.getObject("Spine")
        self.lug = doc.getObject("Lug")


class RingFailedReopenLugLonger(RingBase):
    """C1 through a valid Pad after the failed Pipe, across a save and reopen. A datum on the
    Lug's vertex at the Pipe's corner (-2, -2, -2), whose name is the square's bare vertex name.
    `fail`: the spine relinked to an empty sketch, the Sweep fails and passes the Plate through;
    `reopenPlain`: saved and opened (the Sweep restored in error, not run again); `lugLonger`: the
    Lug 26 long (the Lug runs, the Sweep doesn't); `fix`: the spine back.
    Right: the datum breaks while the Sweep fails (the Pipe's corner isn't on the Lug's shape; the
    Plate's corner (2, 2, 0) that carries the same name is another element) and holds the Pipe's
    corner again at `fix`."""

    REFS = ("corner_point",)
    steps = ("fail", "reopenPlain", "lugLonger", "fix")

    def corner(self):
        return self.pipeCorner() if self.stepName == "fix" else BROKEN

    def build(self, doc):
        self.buildRing(doc)
        lugSketch = m.sketch(doc, "LugSketch", m.rectangle(0, 0, 1, 1), self.body)
        self.lug = m.pad(self.body, lugSketch, 25, "Lug")
        self.lug.Refine = False
        doc.recompute()
        point = self.datumPoint("CornerPoint", self.lug, self.pipeCorner())
        doc.recompute()
        self.ref(
            "corner_point",
            point,
            "AttachmentSupport",
            lambda: self.corner() if self.stepName else self.pipeCorner(),
            Attached(),
        )

    def fail(self, doc):
        self.failSweep(doc)

    def lugLonger(self, doc):
        self.lug.Length = 26

    def fix(self, doc):
        self.fixSweep(doc)


class RingFailedLugLonger(RingFailedReopenLugLonger):
    """Control: as RingFailedReopenLugLonger without the reopen (the in-memory pass-through state
    holds)."""

    steps = ("fail", "lugLonger", "fix")


class SlabFailedReopenCapTaller(ReviewBase):
    """C2 through a valid Pad after the failed Boss, across a save and reopen. A block 20 x 10 x 10,
    a Pad `Boss` 0.1 high on its whole top, a Pad `Cap` (16, 2)-(19, 8) 3 high after it; a datum
    plane on the Cap's face at the Boss's top (z = 10.1). `fail`: the Boss 0 long (fails, passes
    the block through); `reopenPlain`; `capTaller`: the Cap 4 high (the Cap runs, the Boss
    doesn't); `fix`: the Boss 0.1 again.
    Right: the plane breaks while the Boss fails (the block's top 0.1 below, the same size, is
    another face) and holds the Boss's top at `fix`."""

    REFS = ("slab_top_plane",)
    steps = ("fail", "reopenPlain", "capTaller", "fix")

    def slabTop(self):
        return face("plane", normal=Z, contains=(10, 5, 10.1))

    def expected(self):
        if self.stepName in (None, "fix"):
            return self.slabTop()
        return BROKEN

    def build(self, doc):
        self.body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, 20, 10), self.body)
        block = m.pad(self.body, base, 10, "Block")
        block.Refine = False
        slab = m.sketch(doc, "BossSketch", m.rectangle(0, 0, 20, 10), self.body, z=10)
        self.boss = m.pad(self.body, slab, 0.1, "Boss")
        self.boss.Refine = False
        cap = m.sketch(doc, "CapSketch", m.rectangle(16, 2, 19, 8), self.body, z=10)
        self.cap = m.pad(self.body, cap, 3, "Cap")
        self.cap.Refine = False
        doc.recompute()
        plane = self.datumPlane("SlabPlane", self.cap, self.slabTop())
        doc.recompute()
        self.ref("slab_top_plane", plane, "AttachmentSupport", self.expected, Attached())

    def reloaded(self, doc):
        self.body = doc.getObject("Body")
        self.boss = doc.getObject("Boss")
        self.cap = doc.getObject("Cap")

    def fail(self, doc):
        self.boss.Length = 0

    def capTaller(self, doc):
        self.cap.Length = 4

    def fix(self, doc):
        self.boss.Length = 0.1


class SlabFailedCapTaller(SlabFailedReopenCapTaller):
    """Control: as SlabFailedReopenCapTaller without the reopen."""

    steps = ("fail", "capTaller", "fix")


class RingSuppressedAttachThenFailsBack(RingBase):
    """PS's flag through a failure: a datum taken on the Plate's corner (2, 2, 0) while the Sweep
    is suppressed (its record flags the Sweep `:s`). `unsFails`: the Sweep unsuppressed with its
    spine relinked to an empty sketch in one recompute: it fails and passes the Plate through, the
    datum holds the Plate's corner (at its place); `fix`: the spine back, the Pipe absorbs the
    Plate's corner. Right at `fix`: broken (the corner is gone; the bare name gives the Pipe's
    corner at (-2, -2, -2), elsewhere), as RingSweepSuppressedAttachNew's `uns`."""

    REFS = ("new_point",)
    steps = ("unsFails", "fix")

    def expected(self):
        return BROKEN if self.stepName == "fix" else self.plateCorner()

    def build(self, doc):
        self.buildRing(doc)
        self.sweep.Suppressed = True
        doc.recompute()
        point = self.datumPoint("NewPoint", self.sweep, self.plateCorner())
        doc.recompute()
        self.ref("new_point", point, "AttachmentSupport", self.expected, Attached())

    def unsFails(self, doc):
        self.failSweep(doc)
        self.sweep.Suppressed = False

    def fix(self, doc):
        self.fixSweep(doc)


class RingFailedAttachThenFix(RingBase):
    """A datum taken on the Plate's corner (2, 2, 0) while the Sweep has failed (its output the
    Plate); `fix`: the spine back, the Pipe absorbs the corner. Right: broken (C1 reversed)."""

    REFS = ("new_point",)
    steps = ("fix",)

    def expected(self):
        return BROKEN if self.stepName == "fix" else self.plateCorner()

    def build(self, doc):
        self.buildRing(doc)
        self.failSweep(doc)
        doc.recompute()
        point = self.datumPoint("NewPoint", self.sweep, self.plateCorner())
        doc.recompute()
        self.ref("new_point", point, "AttachmentSupport", self.expected, Attached())

    def fix(self, doc):
        self.fixSweep(doc)
