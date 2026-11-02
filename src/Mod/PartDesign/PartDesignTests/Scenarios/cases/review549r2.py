# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review props549-r2 (ops#549, fix/549-pass-through-veto @ 5c9e399e89): the failure's pass-through
state saved as `_FailurePassedThrough` (c86c909237), across undo, redo and reopens.

The models are review549r1.py's (copied: a case imports only harness and models):
- the slab: a block 20 x 10 x 10, a Pad `Boss` `rise` high on its whole top (C2: the block's top is
  a face of the same size `rise` below), a Pad `Cap` (16, 2)-(19, 8) 3 high after it; a datum plane
  on the Cap's face at the Boss's top;
- the ring: a square 4 x 4 padded 1 down (`Plate`), an additive Pipe `Sweep` of its top face round a
  closed rectangle (C1: the Pipe's outer corner (-2, -2, -2) is named by the square's bare vertex
  name, which the Plate's corner (2, 2, 0) carries too), a Pad `Lug` (0, 0)-(1, 1) 25 high after
  it; a datum point on the Lug at the Pipe's corner.
The failure: the Boss 0 long, or the Sweep's spine relinked to an empty sketch.
"""

import os
import shutil
import tempfile

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
X, Y, Z = V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)


class R2Base(Scenario):
    abstract = True
    area = "failure pass-through"
    CLASSES = ("D",)
    AXES = ()
    ISSUE = "ops#549"
    FOUND_BY = "review props549-r2"
    TIER = "F"
    brokenSteps = ()

    def reopenPlain(self, doc):
        """Saved, closed and opened as File > Open does: nothing touched."""
        if not getattr(self, "folder", None):
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

    def reopenPlain2(self, doc):
        self.reopenPlain(doc)

    def reloaded(self, doc):
        pass

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", "") or "", ignore_errors=True)

    def transaction(self, doc, name, action):
        doc.UndoMode = 1
        doc.openTransaction(name)
        action()
        doc.recompute()
        doc.commitTransaction()

    def undo(self, doc):
        doc.undo()

    def redo(self, doc):
        doc.redo()


class SlabBase(R2Base):
    abstract = True
    REFS = ("slab_top_plane",)
    k = 1.0  # the scale
    rise = 0.1

    def slabTop(self):
        k = self.k
        return face("plane", normal=Z, contains=(10 * k, 5 * k, 10 * k + self.rise))

    def expected(self):
        return BROKEN if self.stepName in self.brokenSteps else self.slabTop()

    def build(self, doc):
        k = self.k
        self.body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, 20 * k, 10 * k), self.body)
        block = m.pad(self.body, base, 10 * k, "Block")
        block.Refine = False
        slab = m.sketch(doc, "BossSketch", m.rectangle(0, 0, 20 * k, 10 * k), self.body, z=10 * k)
        self.boss = m.pad(self.body, slab, self.rise, "Boss")
        self.boss.Refine = False
        cap = m.sketch(
            doc, "CapSketch", m.rectangle(16 * k, 2 * k, 19 * k, 8 * k), self.body, z=10 * k
        )
        self.cap = m.pad(self.body, cap, 3 * k, "Cap")
        self.cap.Refine = False
        doc.recompute()
        plane = self.body.newObject("PartDesign::Plane", "SlabPlane")
        plane.AttachmentSupport = [(self.cap, self.names(self.cap, self.slabTop()))]
        plane.MapMode = "FlatFace"
        doc.recompute()
        self.ref("slab_top_plane", plane, "AttachmentSupport", self.expected, Attached())

    def reloaded(self, doc):
        self.body = doc.getObject("Body")
        self.boss = doc.getObject("Boss")
        self.cap = doc.getObject("Cap")

    def fail(self, doc):
        self.boss.Length = 0

    def fix(self, doc):
        self.boss.Length = self.rise

    def capTaller(self, doc):
        self.cap.Length = 4 * self.k

    def capTaller5(self, doc):
        self.cap.Length = 5 * self.k

    def failT(self, doc):
        self.transaction(doc, "fail", lambda: self.fail(doc))

    def fixT(self, doc):
        self.transaction(doc, "fix", lambda: self.fix(doc))


class SlabFailUndoRedo(SlabBase):
    """C2 through the Cap: the Boss fails in a transaction (recomputed in it), the transaction is
    undone (the Boss 0.1 again: the plane holds the Boss's top) and redone (the Boss fails again:
    broken), then the Cap 4 high and the Boss fixed."""

    steps = ("failT", "undo", "redo", "capTaller", "fix")
    brokenSteps = ("failT", "redo", "capTaller")


class SlabFailReopenFixUndo(SlabBase):
    """C2: the Boss fails; saved and opened (File > Open); fixed in a transaction (holds); the fix
    undone (the Boss fails again: broken); the Cap 4 high (broken); the Boss fixed."""

    steps = ("fail", "reopenPlain", "fixT", "undo", "capTaller", "fix")
    brokenSteps = ("fail", "reopenPlain", "undo", "capTaller")


class SlabFailReopenTwice(SlabBase):
    """C2: the Boss fails; saved and opened; the Cap 4 high (the Boss not run); saved and opened
    again; the Cap 5 high; the Boss fixed. Broken until the fix."""

    steps = ("fail", "reopenPlain", "capTaller", "reopenPlain2", "capTaller5", "fix")
    brokenSteps = ("fail", "reopenPlain", "capTaller", "reopenPlain2", "capTaller5")


class SlabFailReopenTwice4m(SlabFailReopenTwice):
    """SlabFailReopenTwice at 4 m (k = 200), the Boss 1 mm high."""

    k = 200.0
    rise = 1.0


class SlabStaleUndo(SlabBase):
    """C2: the Boss fails; its length set back to 0.1 outside any transaction, and in one
    transaction the Cap 4 high and a recompute (the Boss runs, holds); the transaction undone (the
    Boss's shape and pass-through state go back to the failure's, its length stays 0.1); the Cap 5
    high. Right: the Boss's top (its length is 0.1) or broken; never the block's top."""

    steps = ("fail", "fixOutsideCapT", "undo", "capTaller5")
    brokenSteps = ("fail",)

    def fixOutsideCapT(self, doc):
        self.boss.Length = self.rise
        self.transaction(doc, "cap", lambda: self.capTaller(doc))


class RingBase(R2Base):
    abstract = True
    REFS = ("corner_point",)
    half = 2

    def pipeCorner(self):
        return vertex((-self.half, -self.half, -self.half))

    def expected(self):
        return BROKEN if self.stepName in self.brokenSteps else self.pipeCorner()

    def build(self, doc):
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
        lugSketch = m.sketch(doc, "LugSketch", m.rectangle(0, 0, 1, 1), self.body)
        self.lug = m.pad(self.body, lugSketch, 25, "Lug")
        self.lug.Refine = False
        doc.recompute()
        point = self.body.newObject("PartDesign::Point", "CornerPoint")
        point.AttachmentSupport = [(self.lug, self.names(self.lug, self.pipeCorner()))]
        point.MapMode = "Vertex"
        doc.recompute()
        self.ref("corner_point", point, "AttachmentSupport", self.expected, Attached())

    def reloaded(self, doc):
        self.body = doc.getObject("Body")
        self.sweep = doc.getObject("Sweep")
        self.spine = doc.getObject("Spine")
        self.lug = doc.getObject("Lug")

    def fail(self, doc):
        empty = doc.getObject("NoSpine") or m.sketch(doc, "NoSpine", [], self.body)
        self.sweep.Spine = (empty, [])

    def fix(self, doc):
        self.sweep.Spine = (self.spine, [])

    def lugLonger(self, doc):
        self.lug.Length = 26

    def failT(self, doc):
        self.transaction(doc, "fail", lambda: self.fail(doc))

    def fixT(self, doc):
        self.transaction(doc, "fix", lambda: self.fix(doc))


class RingFailUndoRedo(RingBase):
    """C1 through the Lug: the Sweep fails in a transaction; undone (holds the Pipe's corner);
    redone (broken); the Lug 26 long (broken); the Sweep fixed (holds)."""

    steps = ("failT", "undo", "redo", "lugLonger", "fix")
    brokenSteps = ("failT", "redo", "lugLonger")


class RingFailReopenFixUndo(RingBase):
    """C1: the Sweep fails; saved and opened; fixed in a transaction (holds); the fix undone
    (broken); the Lug 26 long (broken); fixed (holds)."""

    steps = ("fail", "reopenPlain", "fixT", "undo", "lugLonger", "fix")
    brokenSteps = ("fail", "reopenPlain", "undo", "lugLonger")
