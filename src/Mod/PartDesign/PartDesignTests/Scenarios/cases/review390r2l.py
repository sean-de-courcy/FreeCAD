# SPDX-License-Identifier: LGPL-2.1-or-later
"""Corpus cases (class A, ops#468): fork PR 390 round 2l's fix-trace review (pr390-r2l). Round 2l
(decision 241) sends an unmoved exact hit on an ordered name saved among two twins or more to
solveOwner(), and breaks it there when its saved name ends in a role (`in`/`out`) and its twins now
are another number than saved. These cases aim that stop at a reference held through a later
feature (the name's last section is no longer the crossing's), at other scales, at a redraw, at the
role traded with the count kept, and at unmoved crossings an unrelated edit leaves alone.
Model P (review390r2d's): a plate 200 x 100 x 5 (scale 3), a through pocket (Midplane) of a circle
A of radius 1 at (ax, 0.5) crossing the top front edge (y = 0, z = 5) at ax -+ 0.866. `flip` draws
the profile's front line the other way (the side role's switch point, I-A6); `move` moves A to ax1
(or deletes and draws it again with `redraw`). `later`: the datum points sit on A's crossings as
seen on a later feature: `B` (another sketch's Pocket of a circle at (102.5, 0.5)), `boss` (a Pad
of a 10 x 10 square on the top face at (50..60, 50..60)), `fillet` (a Fillet r 0.3 of the top back
edge), `binder` (a SubShapeBinder of the last feature in a second Body). `moveB` moves B by +5.
Each expectation is the crossing of circle A on the same side of A, on the edited model, else
BROKEN."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Reopens, Scenario, edge, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HALF = math.sqrt(1 - 0.5**2)


def drawnTheOtherWay(sketch, index=0):
    """Line `index` of the sketch drawn the other way, its geometry id kept."""
    geometry = sketch.Geometry
    line = geometry[index]
    start, end = V(line.StartPoint), V(line.EndPoint)
    line.StartPoint, line.EndPoint = V(1e4, 1e4, 0), V(2e4, 2e4, 0)
    line.StartPoint, line.EndPoint = end, start
    sketch.Geometry = geometry


class R2lPlate(Scenario):
    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M1", "E1", "E4", "X4:600")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2l"
    TIER = "F"
    SIZE, SCALE = 200, 3
    REFS = ("left", "right")
    ax0, ax1, bx = 198.5, 198.5 + 2 * HALF, 102.5
    later = None  # None, "B", "boss", "fillet", "binder"
    flip, redraw, move, moveB = True, False, True, False
    withB = False  # Pocket B before `later`'s feature
    bx1 = None  # where moveB takes B (default bx + 5)
    eats, eaten = (), ()  # the sides of A whose crossing B's move cuts away
    steps = ("edit",)

    def crossing(self, side):
        x = self.ax + side * HALF
        if side in self.eaten:
            return BROKEN
        return vertex(at=self.s(x, 0, 5)) if 1e-6 < x < 200 - 1e-6 else BROKEN

    def pocket(self, doc, body, name, circles):
        sketch = m.sketch(doc, "Hole" + name, circles, body)
        pocket = body.newObject("PartDesign::Pocket", "Pocket" + name)
        pocket.Profile, pocket.Type, pocket.Midplane = sketch, 1, True
        return sketch, pocket

    def backEdge(self):
        cx, cy, cz = self.s(100, 100, 5)
        length = self.s(200)
        tol = 1e-6 * max(1, self.scale)
        return edge(
            where=lambda e: (e.CenterOfMass - V(cx, cy, cz)).Length < tol
            and abs(e.Length - length) < tol
        )

    def build(self, doc):
        self.ax = self.ax0
        body = m.body(doc)
        self.profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 200, 100)), body)
        m.pad(body, self.profile, self.s(5))
        self.holeA, last = self.pocket(doc, body, "A", [m.circle(*self.s(self.ax0, 0.5, 1))])
        if self.later == "B" or self.withB:
            self.holeB, last = self.pocket(doc, body, "B", [m.circle(*self.s(self.bx, 0.5, 1))])
        elif self.later == "boss":
            square = m.sketch(doc, "Square", m.rectangle(*self.s(50, 50, 60, 60)), body,
                              z=self.s(5))
            last = m.pad(body, square, self.s(5), name="Boss")
        elif self.later == "fillet":
            doc.recompute()
            fillet = body.newObject("PartDesign::Fillet", "Fillet")
            fillet.Base = (last, self.names(last, self.backEdge()))
            fillet.Radius = self.s(0.3)
            last = fillet
        doc.recompute()
        holder = body
        if self.later in ("compound", "link"):
            holder = doc.addObject("PartDesign::Body", "Body2")
            if self.later == "compound":
                last = doc.addObject("Part::Compound", "Compound")
                last.Links = [body]
            else:
                last = doc.addObject("App::Link", "Link")
                last.LinkedObject = body
            doc.recompute()
        if self.later == "binder":
            holder = doc.addObject("PartDesign::Body", "Body2")
            binder = holder.newObject("PartDesign::SubShapeBinder", "Binder")
            binder.Support = [(last, ("",))]
            doc.recompute()
            last = binder
        for name, side in (("left", -1), ("right", 1)):
            point = holder.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(last, self.names(last, self.crossing(side))[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", lambda s=side: self.crossing(s), Attached())
        doc.recompute()

    def moveA(self, doc):
        hole = doc.getObject("HoleA")  # by name: a reopen replaces the objects
        if self.redraw:  # a new geometry id
            hole.delGeometry(0)
            hole.addGeometry(m.circle(*self.s(self.ax1, 0.5, 1)))
        else:
            hole.moveGeometry(0, 3, V(*self.s(self.ax1, 0.5, 0)), False)
        self.ax = self.ax1

    def change(self, doc):
        if self.flip:
            drawnTheOtherWay(doc.getObject("Profile"))
        if self.move:
            self.moveA(doc)
        if self.moveB:
            bx1 = self.bx + 5 if self.bx1 is None else self.bx1
            doc.getObject("HoleB").moveGeometry(0, 3, V(*self.s(bx1, 0.5, 0)), False)
            self.eaten = self.eats

    def edit(self, doc):
        self.change(doc)
        doc.recompute()

    def editInTransaction(self, doc):
        doc.UndoMode = 1
        doc.openTransaction("edit")
        self.change(doc)
        doc.recompute()
        doc.commitTransaction()

    def undoIt(self, doc):
        doc.undo()
        doc.recompute()
        self.ax = self.ax0

    def redoIt(self, doc):
        doc.redo()
        doc.recompute()
        self.ax = self.ax1


class R2lAtRightsPlaceFlipped(R2lPlate):
    """review390r2d's R2dLoneAtRightsPlaceFlipped (A from 198.5 by +1.732, flipped: the right
    crossing leaves the edge, the left one lands exactly where it was, with its role): the control,
    run at other scales. Right breaks; left follows (199.366)."""


class R2lAtRightsPlaceFlippedBesideB(R2lAtRightsPlaceFlipped):
    """As above, the points on A's crossings as Pocket B (a later feature) has them."""
    later = "B"


class R2lAtLeftsPlaceFlippedBesideB(R2lAtRightsPlaceFlippedBesideB):
    """The start of the edge: A from 1.5 by -1.732, on Pocket B. Left breaks; right follows."""
    ax0, ax1 = 1.5, 1.5 - 2 * HALF


class R2lAtRightsPlaceFlippedBoss(R2lAtRightsPlaceFlipped):
    """The points on a later Pad's shape (a boss on the top face, far from the edge)."""
    later = "boss"


class R2lAtRightsPlaceFlippedFillet(R2lAtRightsPlaceFlipped):
    """The points on a later Fillet's shape (the top back edge filleted)."""
    later = "fillet"


class R2lAtRightsPlaceFlippedBinder(R2lAtRightsPlaceFlipped):
    """The points in a second Body, on a SubShapeBinder of Pocket A."""
    later = "binder"


class R2lAtRightsPlaceFlippedRedrawn(R2lAtRightsPlaceFlipped):
    """A deleted and drawn again at its new place, flipped."""
    AXES = ("M1", "E1", "E2", "E4", "X4:600")
    redraw = True


class R2lFlipMovedOneSpacing(R2lPlate):
    """Both crossings stay: A from 100 by +1.732, flipped. The left crossing lands exactly where
    the right one was, with the right one's role; their count kept. Each point follows its side of
    A: left at 100.866, right at 102.598."""
    ax0, ax1 = 100.0, 100.0 + 2 * HALF


class R2lFlipMovedOneSpacingBack(R2lFlipMovedOneSpacing):
    """A from 100 by -1.732: the right crossing lands where the left one was, with its role."""
    ax1 = 100.0 - 2 * HALF


class R2lMoveBOnlyBinder(R2lPlate):
    """Controls for the new trigger on unmoved crossings: B moved by +5, A and the edge left alone;
    the points in a second Body on a SubShapeBinder of Pocket B. Each stays on its crossing."""
    AXES = ("M1", "E1", "X4:600")
    ax0 = ax1 = 100.0
    later, withB, flip, move, moveB = "binder", True, False, False, True


class R2lMoveBOnlyBesideB(R2lMoveBOnlyBinder):
    """As above, the points on Pocket B itself."""
    later = "B"


class R2lAtRightsPlaceFlippedBinderOfB(R2lAtRightsPlaceFlippedBinder):
    """The silent edit (A from 198.5 by +1.732, flipped) on a binder of Pocket B."""
    withB = True


class R2lReopenThenAtRightsPlaceFlipped(Reopens, R2lAtRightsPlaceFlipped):
    """Saved, closed and opened, then the silent edit."""
    steps = ("reopen", "edit")


class R2lAtRightsPlaceFlippedUndoRedo(R2lAtRightsPlaceFlipped):
    """The silent edit in one transaction, undone (each point back on its crossing as built), then
    redone (right breaks; left follows)."""
    steps = ("editInTransaction", "undoIt", "redoIt")


class R2lAtRightsPlaceFlippedThenUndo(R2lAtRightsPlaceFlipped):
    """The silent edit in one transaction, then undone: each point back on its crossing."""
    steps = ("editInTransaction", "undoIt")


class R2lCopy(R2lPlate):
    """The points on a copy of A's crossings: `copy` "pattern" (a LinearPattern of Pocket A, 2
    occurrences 20 apart: the copy at ax + 20) or "mirror" (Mirrored across the YZ plane, the plate
    -100..100: the copy at -ax). `left` and `right` name the copy's crossings by A's side they copy.
    Expectations: the copy of A's crossing on that side, on the edited model, else BROKEN."""

    abstract = True
    copy = "pattern"
    lo, hi = 0.0, 200.0

    def copyX(self, x):
        return x + 20.0 if self.copy == "pattern" else -x

    def crossing(self, side):
        x = self.ax + side * HALF
        if not (self.lo + 1e-6 < x < self.hi - 1e-6):
            return BROKEN
        x = self.copyX(x)
        return vertex(at=self.s(x, 0, 5)) if self.lo + 1e-6 < x < self.hi - 1e-6 else BROKEN

    def build(self, doc):
        self.ax = self.ax0
        body = m.body(doc)
        self.profile = m.sketch(doc, "Profile", m.rectangle(*self.s(self.lo, 0, self.hi, 100)), body)
        m.pad(body, self.profile, self.s(5))
        _, last = self.pocket(doc, body, "A", [m.circle(*self.s(self.ax0, 0.5, 1))])
        if self.copy == "pattern":
            copy = doc.addObject("PartDesign::LinearPattern", "LinearPattern")
            copy.Originals = [last]
            copy.Direction = (m.originFeature(body, "X_Axis"), [""])
            copy.Mode = "Spacing"
            copy.Offset = self.s(20)
            copy.Occurrences = 2
        else:
            copy = doc.addObject("PartDesign::Mirrored", "Mirrored")
            copy.Originals = [last]
            copy.MirrorPlane = (m.originFeature(body, "YZ_Plane"), [""])
        body.addObject(copy)
        doc.recompute()
        for name, side in (("left", -1), ("right", 1)):
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(copy, self.names(copy, self.crossing(side))[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", lambda s=side: self.crossing(s), Attached())
        doc.recompute()


class R2lPatternCopyAtRightsPlaceFlipped(R2lCopy):
    """A at 178.5, its pattern copy at 198.5; A moved +1.732 and flipped: the copy's right crossing
    leaves the edge, its left one lands exactly where the copy's right one was, with its role (A's
    own crossings both stay). Right breaks; left follows (199.366)."""
    ax0, ax1 = 178.5, 178.5 + 2 * HALF


class R2lMirrorCopyAtLeftsPlaceFlipped(R2lCopy):
    """The plate -100..100, A at 98.5 mirrored to -98.5; A moved +1.732 and flipped: A's right
    crossing and the copy of it leave the edge, the copy of A's left crossing lands exactly where
    the copy of A's right one was (-99.366). `right` breaks; `left` follows."""
    copy, lo, hi = "mirror", -100.0, 100.0
    ax0, ax1 = 98.5, 98.5 + 2 * HALF


class R2lLaterPocketEatsLeftCrossing(R2lPlate):
    """A at 100; Pocket B (a circle r 1, after A) moved from (110, 0.5) to (98.9, 0.5), over A's
    left crossing (99.134) and clear of its right one (100.866); the points on Pocket B. Left
    breaks (its crossing is cut away); right stays (unmoved, its twin gone: 2 -> 1)."""
    AXES = ("M1", "E1", "X4:600")
    ax0 = ax1 = 100.0
    bx, bx1 = 110.0, 98.9
    later, flip, move, moveB, eats = "B", False, False, True, (-1,)


class R2lMoveBOnlyCompound(R2lMoveBOnlyBinder):
    """The control's points in a second Body on a Part Compound of the first Body (child-mapped
    elements): B moved by +5, A left alone. Each stays on its crossing."""
    later = "compound"


class R2lMoveBOnlyLink(R2lMoveBOnlyBinder):
    """As above, on an App::Link to the first Body."""
    later = "link"


class R2lAtRightsPlaceFlippedCompound(R2lAtRightsPlaceFlipped):
    """The silent edit, the points on a Part Compound of the Body."""
    later = "compound"


class R2lAtRightsPlaceFlippedLink(R2lAtRightsPlaceFlipped):
    """The silent edit, the points on an App::Link to the Body."""
    later = "link"
