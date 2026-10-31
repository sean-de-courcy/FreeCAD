# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2b (ops#468, PLAN decision 204): members placed on a closed first-source edge keep
the maker's order with ORD. A pad of a closed curve (a circle, or an ellipse) is cut by one tool
face that crosses its top rim four times, so the rim keeps two arcs that A2 makes twins
(`<k>of<n>`, MOD,ORD). The cutter is a groove (a circle in the YZ plane pocketed through all,
symmetric, along X) or a vertical pocket through all of an ellipse. The edits move the rim's seam
(the disk's sketch turned) together with moves of the disk or the cutter, so that the arcs move,
change length or swap sides while the maker's order counts from the moved seam."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Filleted, Scenario, edge, pieces

V = App.Vector
# The groove's sketch plane: sketch x -> global Y, sketch y -> global Z (the groove runs along X)
YZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 1, 1), 120))


class CutRim(Scenario):
    """A PartDesign pad, 20 high, of a closed curve about (dx, dy) turned by `turn` degrees: a
    circle of radius 10, or an ellipse of semi-axes `ea` (along its sketch x) and 10. A cutter
    splits its top rim into two arcs: `groove`, a circle of radius g at (y gy, z 20) in the YZ
    plane pocketed through all, symmetric (a groove along X); or `ellipse`, an ellipse of
    semi-axes 14 and 6 about (ex, ey) turned by `et` degrees, pocketed through all from the top.
    References (datum points at the centre of mass): `rim_p` and `rim_m`, the top rim's arcs
    through the rim's points straight above and below its centre (+y and -y); BROKEN where the
    cutter covers that point."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M4", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2b"
    TIER = "F"
    SIZE = 20
    SCALE = 1.0
    REFS = ("rim_p", "rim_m")
    R, H = 10.0, 20.0
    cutter = "groove"
    ea = None  # the disk is an ellipse of semi-axes (ea, 10) when set
    # (dx, dy, turn, gy, g, ex, ey, et)
    start = dict(dx=0.0, dy=0.0, turn=0.0, gy=0.0, g=3.0, ex=0.0, ey=0.0, et=0.0)
    end = {}

    def _state(self):
        return self.state

    def covered(self, p):
        """True if the cutter removes the top rim's point p (x, y), unscaled."""
        st = self.state
        x, y = p
        if self.cutter == "groove":
            return abs(y - st["gy"]) <= st["g"]
        c, s = math.cos(math.radians(-st["et"])), math.sin(math.radians(-st["et"]))
        u, v = x - st["ex"], y - st["ey"]
        u, v = u * c - v * s, u * s + v * c
        return (u / 14.0) ** 2 + (v / 6.0) ** 2 <= 1.0

    def rimPoint(self, sign):
        st = self.state
        # The disk's point straight above (+y) or below (-y) its centre, in the disk's own frame
        # turned: a circle's is the same point at any turn; for an ellipse disk, the turn is 0
        # or 180 in these cases, so the point is (dx, dy +- 10).
        return st["dx"], st["dy"] + sign * self.R

    def rim(self, sign):
        s = self.scale
        x, y = self.rimPoint(sign)
        if self.covered((x, y)):
            return BROKEN
        curve = "circle" if self.ea is None else "ellipse"
        return edge(curve=curve, contains=V(x * s, y * s, self.H * s))

    def expectation(self, name):
        return {"rim_p": lambda: self.rim(1), "rim_m": lambda: self.rim(-1)}[name]

    def apply(self):
        s = self.scale
        st = self.state
        self.disk.Placement = App.Placement(
            V(st["dx"] * s, st["dy"] * s, 0), App.Rotation(V(0, 0, 1), st["turn"])
        )
        geo = self.tool.Geometry
        if self.cutter == "groove":
            c = geo[0]
            c.Center = V(st["gy"] * s, self.H * s, 0)
            c.Radius = st["g"] * s
            self.tool.Geometry = geo
        else:
            self.tool.Placement = App.Placement(
                V(st["ex"] * s, st["ey"] * s, self.H * s), App.Rotation(V(0, 0, 1), st["et"])
            )

    def build(self, doc):
        s = self.scale
        self.state = dict(self.start)
        body = doc.addObject("PartDesign::Body", "Body")
        self.body = body
        self.disk = doc.addObject("Sketcher::SketchObject", "Disk")
        body.addObject(self.disk)
        if self.ea is None:
            self.disk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), self.R * s), False)
        else:
            self.disk.addGeometry(
                Part.Ellipse(V(self.ea * s, 0, 0), V(0, self.R * s, 0), V(0, 0, 0)), False
            )
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.disk
        pad.Length = self.H * s
        self.tool = doc.addObject("Sketcher::SketchObject", "Tool")
        body.addObject(self.tool)
        if self.cutter == "groove":
            self.tool.Placement = YZ
            self.tool.addGeometry(Part.Circle(V(0, self.H * s, 0), V(0, 0, 1), 3 * s), False)
        else:
            self.tool.addGeometry(Part.Ellipse(V(14 * s, 0, 0), V(0, 6 * s, 0), V(0, 0, 0)), False)
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.tool
        self.pocket.Type = 1
        if self.cutter == "groove":
            self.pocket.SideType = "Symmetric"
        self.apply()
        doc.recompute()
        self.addRefs(doc, body)
        doc.recompute()

    def addRefs(self, doc, body):
        for name in self.REFS:
            expect = self.expectation(name)
            point = body.newObject("PartDesign::Point", name)
            at = CutRim.rim(self, 1 if name == "rim_p" else -1)  # the piece through the point
            point.AttachmentSupport = [(self.pocket, self.names(self.pocket, at)[0])]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", expect)

    def edit(self, doc):
        self.edited = True
        self.state = dict(self.start)
        self.state.update(self.end)
        self.apply()
        doc.recompute()


# The groove: the disk moved and turned (the seam to the other side, the arcs moved)


class GrooveDiskMovedXTurned(CutRim):
    __doc__ = CutRim.__doc__ + " The disk goes to (2, 0) and turns 180 degrees."
    end = dict(dx=2.0, turn=180.0)


class GrooveDiskMovedYTurned(CutRim):
    __doc__ = CutRim.__doc__ + " The disk goes to (0, 1.5) and turns 180 degrees: the +y arc grows, the -y arc shrinks."
    end = dict(dy=1.5, turn=180.0)




class GrooveWiderDiskTurned(CutRim):
    __doc__ = CutRim.__doc__ + " The groove widens to g 4.5 and the disk turns 180 degrees."
    end = dict(g=4.5, turn=180.0)


class GrooveFilletShiftedTurned(CutRim):
    __doc__ = CutRim.__doc__ + " A fillet of radius 0.5 on the +y arc; the groove to gy 1, g 2.5 and the disk turned 180 degrees (PR 390's GrooveShiftedTurned edit)."
    REFS = ("fillet_p",)
    end = dict(gy=1.0, g=2.5, turn=180.0)

    def addRefs(self, doc, body):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (self.pocket, self.names(self.pocket, self.rim(1)))
        fillet.Radius = 0.5 * self.scale
        self.ref("fillet_p", fillet, "Base", lambda: self.rim(1), Filleted(0.5 * self.scale))


class GrooveFilletMovedYTurned(GrooveFilletShiftedTurned):
    __doc__ = GrooveFilletShiftedTurned.__doc__.replace("PR 390's GrooveShiftedTurned edit", "with the disk moved to (0, 1.5) instead of the groove")
    end = dict(dy=1.5, turn=180.0)


# An ellipse disk (a closed curve that isn't a circle) with the groove


class EllipseDiskGrooveTurned(CutRim):
    __doc__ = CutRim.__doc__ + " The disk is an ellipse of semi-axes 12 and 10; it turns 180 degrees."
    ea = 12.0
    end = dict(turn=180.0)


class EllipseDiskGrooveMovedTurned(CutRim):
    __doc__ = CutRim.__doc__ + " The disk is an ellipse of semi-axes 12 and 10; it goes to (1, 1.5) and turns 180 degrees."
    ea = 12.0
    end = dict(dx=1.0, dy=1.5, turn=180.0)


# The vertical ellipse pocket: the cutter's own seam, the disk's seam, the cutter turned


class EllipseCutDiskTurned(CutRim):
    __doc__ = CutRim.__doc__ + " Cutter: the ellipse. The disk turns 180 degrees."
    cutter = "ellipse"
    end = dict(turn=180.0)


class EllipseCutToolTurned(CutRim):
    __doc__ = CutRim.__doc__ + " Cutter: the ellipse. The ellipse turns 180 degrees (its own seam moves)."
    cutter = "ellipse"
    end = dict(et=180.0)


class EllipseCutBothTurned(CutRim):
    __doc__ = CutRim.__doc__ + " Cutter: the ellipse. Both sketches turn 180 degrees."
    cutter = "ellipse"
    end = dict(turn=180.0, et=180.0)


class EllipseCutShiftedDiskTurned(CutRim):
    __doc__ = CutRim.__doc__ + " Cutter: the ellipse, moved to (0, 1.5); the disk turns 180 degrees."
    cutter = "ellipse"
    end = dict(ey=1.5, turn=180.0)


class EllipseCutToolTurned60(CutRim):
    __doc__ = CutRim.__doc__ + " Cutter: the ellipse, turned 60 degrees: the kept arcs centre on 150 and -30 degrees, so the +y point lies on the first and the -y point on the second."
    cutter = "ellipse"
    end = dict(et=60.0)


class EllipseCutToolTurned60DiskTurned(CutRim):
    __doc__ = EllipseCutToolTurned60.__doc__ + " The disk turns 180 degrees as well."
    cutter = "ellipse"
    end = dict(et=60.0, turn=180.0)


class EllipseCutToolTurned80(CutRim):
    __doc__ = CutRim.__doc__ + " Cutter: the ellipse, turned 80 degrees: the kept arcs centre on 170 and -10 degrees, and the cutter covers the +y and -y points (both references break)."
    cutter = "ellipse"
    end = dict(et=80.0)


class EllipseCutToolTurned80DiskTurned(CutRim):
    __doc__ = EllipseCutToolTurned80.__doc__ + " The disk turns 180 degrees as well."
    cutter = "ellipse"
    end = dict(et=80.0, turn=180.0)


# The seam lands on a kept arc and splits it (the disk turned 45 or 135 degrees), or leaves it


class SeamSplitsRim(CutRim):
    """As CutRim; where the disk's seam lies on a kept arc, that arc is two pieces, and the
    reference expects both (pieces): the rim's pieces on the +y (or -y) side of the cutter (the
    groove's centre gy, or the ellipse's ey; its turn is 0 in these cases)."""

    abstract = True

    def cutterY(self):
        return self.state["gy"] if self.cutter == "groove" else self.state["ey"]

    def rim(self, sign):
        s = self.scale
        if not getattr(self, "edited", False):
            return CutRim.rim(self, sign)  # before the edit: the piece the reference holds
        x, y = self.rimPoint(sign)
        if self.covered((x, y)):
            return BROKEN
        st = self.state
        H = self.H * s
        return pieces(
            edge(
                curve="circle",
                where=lambda e: abs(e.BoundBox.ZMin - H) < 1e-6 * max(1, H)
                and abs(e.BoundBox.ZMax - H) < 1e-6 * max(1, H)
                and sign * (e.CenterOfMass.y - self.cutterY() * s) > 0,
            )
        )


class GrooveDiskTurned45(SeamSplitsRim):
    __doc__ = SeamSplitsRim.__doc__ + " Cutter: the groove. The disk turns 45 degrees: the seam goes onto the +y arc."
    end = dict(turn=45.0)


class GrooveDiskTurned225(SeamSplitsRim):
    __doc__ = SeamSplitsRim.__doc__ + " Cutter: the groove. The disk turns 225 degrees: the seam goes onto the -y arc."
    end = dict(turn=225.0)


class GrooveDiskTurnedBackFrom45(SeamSplitsRim):
    __doc__ = SeamSplitsRim.__doc__ + " Cutter: the groove. Built with the disk turned 45 degrees (the +y arc in two pieces); the disk turns back to 0 (one arc each side, twins)."
    start = dict(CutRim.start, turn=45.0)
    end = dict(turn=0.0)


class GrooveDiskTurnedBackFrom45To180(SeamSplitsRim):
    __doc__ = SeamSplitsRim.__doc__ + " Cutter: the groove. Built with the disk turned 45 degrees; the disk turns to 180."
    start = dict(CutRim.start, turn=45.0)
    end = dict(turn=180.0)


class EllipseCutDiskTurned45(SeamSplitsRim):
    __doc__ = SeamSplitsRim.__doc__ + " Cutter: the ellipse. The disk turns 45 degrees: the seam goes onto the +y arc."
    cutter = "ellipse"
    end = dict(turn=45.0)


class EllipseCutDiskTurned135(SeamSplitsRim):
    __doc__ = SeamSplitsRim.__doc__ + " Cutter: the ellipse. The disk turns 135 degrees."
    cutter = "ellipse"
    end = dict(turn=135.0)


class EllipseCutDiskTurnedBackFrom45(SeamSplitsRim):
    __doc__ = SeamSplitsRim.__doc__ + " Cutter: the ellipse. Built with the disk turned 45 degrees; it turns back to 0."
    cutter = "ellipse"
    start = dict(CutRim.start, turn=45.0)
    end = dict(turn=0.0)


class EllipseCutDiskTurnedFrom45To225(SeamSplitsRim):
    __doc__ = SeamSplitsRim.__doc__ + " Cutter: the ellipse. Built with the disk turned 45 degrees (+y arc in two); turned to 225 (-y arc in two)."
    cutter = "ellipse"
    start = dict(CutRim.start, turn=45.0)
    end = dict(turn=225.0)


class GrooveDiskMovedFarTurned(SeamSplitsRim):
    __doc__ = SeamSplitsRim.__doc__ + " Cutter: the groove. The disk goes to (0, -4) and turns 180 degrees: the +y arc is a short one above y 3, the -y arc most of the rim, split by the seam at (-10, -4) into pieces of about 1 and 32 (at scale 1)."
    end = dict(dy=-4.0, turn=180.0)
