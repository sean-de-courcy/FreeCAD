# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prA1e-r2 (Opus, ops#524): N2's sweep on a later feature, where no up-to face is saved.

A Pad (Refine off) of a 2 x 2 square at x 0..2, y 0..2 (and a 2 x 3 rectangle at x 12..14) up to a
`Part::Feature` shell without names: a tilted plate T over x -3..1 (height 10 + (x - 1), 45
degrees), a steep plate S over x 1..1.2 down to a flat plate R at z 8 over x 1.2..20. The square's
cap lies in three pieces, on T (x 0..1, the reference C_T), S and R (x 1.2..2, C_R). A later
feature is the Tip (a SubtractiveBox on the rectangle's block, a Pocket through all along X, or a
Fillet of one of the block's vertical edges); the datums sit on the Tip.

The edit rebuilds the shell: T is moved away whole (x 27..31) and a new flat plate N at z 3 lies
under x -3..1, first in the shell (S rebuilt from z 3 up to R), so it takes T's index and the cap
piece over x 0..1 takes C_T's name. T is gone from under the profile: C_T must break; C_R stays on
R. On the Pad itself the PR breaks C_T ("off its place on its up-to face"); on a later feature it
keeps it silently: seen along the Pad's sweep (N2) the new piece overlaps the old one, and a later
feature's record has no up-to faces for the moved-alone break (integration, seeing along the old
piece's normal or the Pocket's X, breaks it).
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


class Base(Scenario):
    abstract = True
    CLASSES = ("A",)
    ISSUE = "ops#524"
    FOUND_BY = "review prA1e-r2"
    TIER = "F"
    AXES = ("M2", "E2")
    area = "sweep-later-feature"
    REFS = ("C_T", "C_R")
    SIZE = 34

    def quad(self, points):
        pts = [V(*self.s(*p)) for p in points]
        return Part.Face(Part.makePolygon(pts + pts[:1])).toNurbs().Faces[0]

    def tilted(self, dx=0.0):
        return self.quad([(-3 + dx, -10, 6), (1 + dx, -10, 10), (1 + dx, 10, 10), (-3 + dx, 10, 6)])

    def flatR(self):
        return self.quad([(1.2, -10, 8), (20, -10, 8), (20, 10, 8), (1.2, 10, 8)])

    def steep(self, z0):
        return self.quad([(1, -10, z0), (1.2, -10, 8), (1.2, 10, 8), (1, 10, z0)])

    def flatN(self):
        return self.quad([(-3, -10, 3), (1, -10, 3), (1, 10, 3), (-3, 10, 3)])

    def piece(self, name):
        tol = 1e-6 * self.scale
        if name == "C_R":
            return face(where=lambda f: (f.CenterOfMass - V(*self.s(1.6, 1, 8))).Length < tol)
        if not self.edited:
            return face(where=lambda f: (f.CenterOfMass - V(*self.s(0.5, 1, 9.5))).Length < tol)
        return BROKEN

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.body = body
        self.plates = m.feature(doc, "Plates", Part.Shell([self.tilted(), self.steep(10), self.flatR()]))
        self.profile = m.sketch(
            doc,
            "Profile",
            m.rectangle(*self.s(0, 0, 2, 2)) + m.rectangle(*self.s(12, 0, 14, 3)),
            body,
        )
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plates, ["Face1", "Face2", "Face3"])
        self.pad.Refine = False
        doc.recompute()
        tip = self.tip(doc, body)
        doc.recompute()
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(tip, self.names(tip, self.piece(name))[0])]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", lambda name=name: self.piece(name), Attached())
        body.Tip = tip

    def tip(self, doc, body):
        tip = body.newObject("PartDesign::SubtractiveBox", "Tip")
        tip.Length = tip.Width = tip.Height = self.s(0.5)
        tip.MapMode = "Deactivated"
        tip.Placement = App.Placement(V(*self.s(12.75, 1, 2)), App.Rotation())
        return tip

    def edit(self, doc):
        self.plates.Shape = Part.Shell([self.flatN(), self.steep(3), self.flatR(), self.tilted(30)])
        self.pad.UpToShape = (self.plates, ["Face1", "Face2", "Face3", "Face4"])
        self.edited = True


class TiltedPlateSwappedUnderBoxTip(Base):
    """The Tip is a SubtractiveBox (no sweep of its own)."""


class TiltedPlateSwappedUnderXPocketTip(Base):
    """The Tip is a Pocket through all along X (its own sweep is X)."""

    def tip(self, doc, body):
        sk = body.newObject("Sketcher::SketchObject", "PocketSketch")
        sk.AttachmentSupport = [(m.originFeature(body, "YZ_Plane"), [""])]
        sk.MapMode = "FlatFace"
        sk.addGeometry(m.rectangle(*self.s(0.5, 0.5, 1.0, 1.0)), False)
        doc.recompute()
        pocket = body.newObject("PartDesign::Pocket", "Tip")
        pocket.Profile = sk
        pocket.Type = "ThroughAll"
        pocket.Midplane = True
        pocket.Refine = False
        return pocket


class TiltedPlateSwappedUnderFilletTip(Base):
    """The Tip is a Fillet of the rectangle block's vertical edge at (14, 3)."""

    def tip(self, doc, body):
        shape = self.pad.Shape
        corner = V(*self.s(14, 3, 0))
        names = [
            "Edge%d" % (i + 1)
            for i, e in enumerate(shape.Edges)
            if abs(e.Vertexes[0].Point.x - corner.x) < 1e-6 * self.scale
            and abs(e.Vertexes[0].Point.y - corner.y) < 1e-6 * self.scale
            and abs(e.Vertexes[-1].Point.x - corner.x) < 1e-6 * self.scale
            and abs(e.Vertexes[-1].Point.y - corner.y) < 1e-6 * self.scale
        ]
        fillet = body.newObject("PartDesign::Fillet", "Tip")
        fillet.Base = (self.pad, names[:1])
        fillet.Radius = self.s(0.3)
        return fillet


class TiltedPlateSwappedOnPad(Base):
    """The same edit with the datums on the Pad itself (the Tip): the moved-alone break's case."""

    def tip(self, doc, body):
        return self.pad



class SlantedPadPlateSwappedUnderBoxTip(Base):
    """All plates flat; the Pad goes along (1, 0, 1) (a custom direction) from the square x 0..2,
    y 0..2 (and the block's rectangle at x 30..32) up to two plates at z 10, A over x -20..11 and B
    over x 11..60: the cap's pieces lie on A (x 10..11, C_T) and B (x 11..12, C_R). The edit
    rebuilds the shell: a new plate N at z 3 over x -20..4 first (it takes A's index), B lowered to
    z 3 over x 4..60, and A moved away whole to x 80..111. C_T's piece is gone (A left the
    profile's sweep): it must break. Seen along Z (integration: the old piece's normal) the new
    piece on N (x 3..4) lies 7 away; seen along the sweep it overlaps."""

    SIZE = 131

    def flat(self, x0, x1, z):
        return self.quad([(x0, -10, z), (x1, -10, z), (x1, 10, z), (x0, 10, z)])

    def piece(self, name):
        tol = 1e-6 * self.scale
        if name == "C_R":
            centre = (11.5, 1, 10) if not self.edited else (4.5, 1, 3)
            return face(where=lambda f: (f.CenterOfMass - V(*self.s(*centre))).Length < tol)
        if not self.edited:
            return face(where=lambda f: (f.CenterOfMass - V(*self.s(10.5, 1, 10))).Length < tol)
        return BROKEN

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.plates = m.feature(
            doc, "Plates", Part.Shell([self.flat(-20, 11, 10), self.flat(11, 60, 10)])
        )
        self.profile = m.sketch(
            doc,
            "Profile",
            m.rectangle(*self.s(0, 0, 2, 2)) + m.rectangle(*self.s(30, 0, 32, 3)),
            body,
        )
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.UseCustomVector = True
        self.pad.Direction = V(1, 0, 1)
        self.pad.AlongSketchNormal = False
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plates, ["Face1", "Face2"])
        self.pad.Refine = False
        doc.recompute()
        tip = body.newObject("PartDesign::SubtractiveBox", "Tip")
        tip.Length = tip.Width = tip.Height = self.s(0.5)
        tip.MapMode = "Deactivated"
        tip.Placement = App.Placement(V(*self.s(30.75, 1, 1)), App.Rotation())
        doc.recompute()
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(tip, self.names(tip, self.piece(name))[0])]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", lambda name=name: self.piece(name), Attached())
        body.Tip = tip

    def edit(self, doc):
        self.plates.Shape = Part.Shell(
            [self.flat(-20, 4, 3), self.flat(4, 60, 3), self.flat(80, 111, 10)]
        )
        self.pad.UpToShape = (self.plates, ["Face1", "Face2", "Face3"])
        self.edited = True
