# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2 (ops#468): a disk (a pad of a circle) with a round groove across its top face.
The groove splits the top face and its rim circle into two pieces each, modified-stage twins
(`<k>of<n>`, MOD,ORD), and makes vertexes where the rim crosses the groove (roles `in`/`out`, or
generated twins). The edits move or widen the groove until one side's pieces vanish, turn the disk
(the rim's seam moves), or compose these."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Scenario, edge, face, vertex

V = App.Vector
# The groove's sketch plane: sketch x -> global Y, sketch y -> global Z (the groove runs along X)
YZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 1, 1), 120))


class GroovedDisk(Scenario):
    """A PartDesign pad of a circle of radius 10 about the origin, 20 high; a pocket through all
    (symmetric) of a circle of radius `g` centred at (y `gy`, z 20) in the YZ plane: a groove
    along X across the top face. References (datum points, centre of mass or vertex): `top_p` and
    `top_m`, the top face's pieces at y > 0 and y < 0; `rim_p` and `rim_m`, the rim circle's
    pieces at y > 0 and y < 0; `lo_xp`, the vertex where the rim crosses the groove's lower side
    (y = gy - g) at x > 0. A piece is BROKEN where the groove covers all of it."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M4", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2"
    TIER = "F"
    SIZE = 20
    SCALE = 1.0
    REFS = ("top_p", "top_m", "rim_p", "rim_m", "lo_xp")
    R, H = 10.0, 20.0
    start = (0.0, 3.0, 0.0)  # (gy, g, the disk sketch's turn in degrees)
    end = (0.0, 3.0, 0.0)

    def _sides(self):
        gy, g, _ = self.state
        return gy - g, gy + g  # the groove's extent in y on the top face

    def top(self, sign):
        s = self.scale
        lo, hi = self._sides()
        if sign > 0:
            if hi >= self.R:
                return BROKEN
            y = (hi + self.R) / 2
        else:
            if lo <= -self.R:
                return BROKEN
            y = (lo - self.R) / 2
        return face(normal=V(0, 0, 1), through=V(0, 0, self.H * s), contains=V(0, y * s, self.H * s))

    def rim(self, sign):
        s = self.scale
        lo, hi = self._sides()
        if (sign > 0 and hi >= self.R) or (sign < 0 and lo <= -self.R):
            return BROKEN
        return edge(curve="circle", contains=V(0, sign * self.R * s, self.H * s))

    def crossing(self):
        s = self.scale
        lo, _ = self._sides()
        if abs(lo) >= self.R:
            return BROKEN
        return vertex(V(math.sqrt(self.R**2 - lo**2) * s, lo * s, self.H * s))

    def expectation(self, name):
        return {
            "top_p": lambda: self.top(1),
            "top_m": lambda: self.top(-1),
            "rim_p": lambda: self.rim(1),
            "rim_m": lambda: self.rim(-1),
            "lo_xp": self.crossing,
        }[name]

    def setGroove(self):
        s = self.scale
        gy, g, turn = self.state
        geo = self.groove.Geometry
        c = geo[0]
        c.Center = V(gy * s, self.H * s, 0)
        c.Radius = g * s
        self.groove.Geometry = geo
        self.disk.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), turn))

    def build(self, doc):
        s = self.scale
        self.state = self.start
        body = doc.addObject("PartDesign::Body", "Body")
        self.disk = doc.addObject("Sketcher::SketchObject", "Disk")
        body.addObject(self.disk)
        self.disk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), self.R * s), False)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.disk
        pad.Length = self.H * s
        self.groove = doc.addObject("Sketcher::SketchObject", "Groove")
        body.addObject(self.groove)
        self.groove.Placement = YZ
        self.groove.addGeometry(Part.Circle(V(0, self.H * s, 0), V(0, 0, 1), 3 * s), False)
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.groove
        self.pocket.Type = 1
        self.pocket.SideType = "Symmetric"
        self.setGroove()
        doc.recompute()
        for name in self.REFS:
            expect = self.expectation(name)
            point = body.newObject("PartDesign::Point", name)
            point.AttachmentSupport = [(self.pocket, self.names(self.pocket, expect())[0])]
            point.MapMode = "Vertex" if name == "lo_xp" else "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", expect)
        doc.recompute()

    def edit(self, doc):
        self.state = self.end
        self.setGroove()
        doc.recompute()


class GrooveCoversTheTopSide(GroovedDisk):
    __doc__ = GroovedDisk.__doc__ + " The groove goes to gy 6.6, g 3.6 (y 3..10.2): the y > 0 pieces vanish, one top piece and the rim's arc (split at its seam) are left."
    end = (6.6, 3.6, 0.0)


class GrooveCoversTheBottomSide(GroovedDisk):
    __doc__ = GroovedDisk.__doc__ + " The groove goes to gy -6.6, g 3.6 (y -10.2..-3): the y < 0 pieces vanish."
    end = (-6.6, 3.6, 0.0)


class GrooveCoversTheTopSideTurned(GroovedDisk):
    __doc__ = GroovedDisk.__doc__ + " As GrooveCoversTheTopSide, and the disk's sketch turned 180 degrees (the rim's seam to x < 0)."
    end = (6.6, 3.6, 180.0)


class GrooveShiftedTurned(GroovedDisk):
    __doc__ = GroovedDisk.__doc__ + " A composed edit: the disk's sketch turned 180 degrees (the seam into the groove), the groove to gy 1, g 2.5: every piece stays."
    end = (1.0, 2.5, 180.0)


class GrooveShiftedFar(GroovedDisk):
    __doc__ = GroovedDisk.__doc__ + " The groove goes to gy 5, g 2 (y 3..7): both top pieces stay, the y > 0 one a sliver; the y > 0 rim arc is the part above y 7."
    end = (5.0, 2.0, 0.0)


class GrooveFromTheTopSide(GroovedDisk):
    __doc__ = GroovedDisk.__doc__ + " The reverse of GrooveCoversTheTopSide: from gy 6.6, g 3.6 (one top piece) back to gy 0, g 3 (two)."
    start = (6.6, 3.6, 0.0)
    end = (0.0, 3.0, 0.0)
    REFS = ("lo_xp",)


class GrooveTurnedOnly(GroovedDisk):
    __doc__ = GroovedDisk.__doc__ + " The disk's sketch turned 180 degrees alone: nothing moves, the rim's seam goes from (10, 0) to (-10, 0) (both inside the groove)."
    end = (0.0, 3.0, 180.0)


class GrooveShiftedOnly(GroovedDisk):
    __doc__ = GroovedDisk.__doc__ + " The groove alone to gy 1, g 2.5: every piece stays and moves a little."
    end = (1.0, 2.5, 0.0)


class GrooveShiftedTurned170(GroovedDisk):
    __doc__ = GroovedDisk.__doc__ + " GrooveShiftedTurned with a turn of 170 degrees: the seam stays inside the groove (y -1.5..3.5 at x < 0)."
    end = (1.0, 2.5, 170.0)


class GrooveShiftedTurnedSmall(GroovedDisk):
    __doc__ = GroovedDisk.__doc__ + " The groove to gy 0.2, g 2.9 and the disk turned 180 degrees: the pieces move by a fraction of a millimetre."
    end = (0.2, 2.9, 180.0)
