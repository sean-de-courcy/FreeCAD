# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2c (ops#468, PLAN decisions 206 and 209): the CLS stop on twins placed on a closed
first-source edge. A pad of a closed curve (a circle of radius 10, or an ellipse of semi-axes 12 and
10) about the origin, H high, its top rim split into two arcs (A2 twins with MOD,ORD,CLS) by a groove
(a circle of radius g at (y gy, z H) in the YZ plane, pocketed through all, symmetric) or by two
through-all side notches (a double-D shaft: strips |x| >= 8). The edits are everyday ones that move
the arcs without any trade (the pad made taller, a groove widened, a fillet's radius), and the seam
moved inside the sketch (an ellipse's major axis flipped 180 degrees in the sketch: the same curve,
no Placement change, so decision 209's frame family is out of it). References: datum points at the
centre of mass of the top rim's arcs through (0, +-10, H), of a fillet's face, of the side faces'
halves; a chamfer's base."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Chamfered, Scenario, edge, face

V = App.Vector
YZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 1, 1), 120))


class R2cRim(Scenario):
    """See the module. State: H, gy, g, flip (the ellipse's major axis toward -x)."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M4", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2c"
    TIER = "F"
    SIZE = 24
    SCALE = 1.0
    REFS = ("rim_p", "rim_m")
    R = 10.0
    ea = None  # an ellipse disk of semi-axes (ea, 10) when set
    cutter = "groove"  # or "notches"
    start = dict(H=20.0, gy=0.0, g=3.0, flip=False)
    end = {}

    def covered(self, x, y):
        st = self.state
        if self.cutter == "groove":
            return abs(y - st["gy"]) <= st["g"]
        return abs(x) >= 8.0

    def rim(self, sign):
        s, st = self.scale, self.state
        if self.covered(0.0, sign * self.R):
            return BROKEN
        curve = "circle" if self.ea is None else "ellipse"
        return edge(curve=curve, contains=V(0, sign * self.R * s, st["H"] * s))

    def side(self, sign):
        s, st = self.scale, self.state
        return face(contains=V(0, sign * self.R * s, st["H"] * s / 2))

    def diskGeometry(self, flip):
        s = self.scale
        if self.ea is None:
            return Part.Circle(V(0, 0, 0), V(0, 0, 1), self.R * s)
        major = -self.ea if flip else self.ea
        return Part.Ellipse(V(major * s, 0, 0), V(0, self.R * s, 0), V(0, 0, 0))

    def apply(self):
        s, st = self.scale, self.state
        self.pad.Length = st["H"] * s
        if self.cutter == "groove":
            geo = self.tool.Geometry
            c = geo[0]
            c.Center = V(st["gy"] * s, st["H"] * s, 0)
            c.Radius = st["g"] * s
            self.tool.Geometry = geo
        if self.flipped != st["flip"]:
            gid = self.disk.getGeometryId(0)
            geo = self.disk.Geometry
            geo[0] = self.diskGeometry(st["flip"])
            self.disk.Geometry = geo
            self.disk.setGeometryId(0, gid)
            self.flipped = st["flip"]

    def build(self, doc):
        s = self.scale
        self.state = dict(self.start)
        body = doc.addObject("PartDesign::Body", "Body")
        self.body = body
        self.disk = doc.addObject("Sketcher::SketchObject", "Disk")
        body.addObject(self.disk)
        self.flipped = self.state["flip"]
        self.disk.addGeometry(self.diskGeometry(self.flipped), False)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.disk
        self.pad.Length = self.state["H"] * s
        self.tool = doc.addObject("Sketcher::SketchObject", "Tool")
        body.addObject(self.tool)
        if self.cutter == "groove":
            self.tool.Placement = YZ
            self.tool.addGeometry(Part.Circle(V(0, 20 * s, 0), V(0, 0, 1), 3 * s), False)
        else:
            for x0, x1 in ((8, 16), (-16, -8)):
                pts = [
                    V(x0 * s, -16 * s, 0),
                    V(x1 * s, -16 * s, 0),
                    V(x1 * s, 16 * s, 0),
                    V(x0 * s, 16 * s, 0),
                ]
                for i in range(4):
                    self.tool.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False)
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.tool
        self.pocket.Type = 1
        if self.cutter == "groove":
            self.pocket.SideType = "Symmetric"
        else:
            self.tool.AttachmentOffset = App.Placement(V(0, 0, 0), App.Rotation())
            self.tool.Placement = App.Placement(V(0, 0, 40 * s), App.Rotation())
        self.apply()
        doc.recompute()
        self.addRefs(doc, body)
        doc.recompute()

    def datum(self, body, name, owner, predicate, expect):
        point = body.newObject("PartDesign::Point", name)
        point.AttachmentSupport = [(owner, self.names(owner, predicate)[0])]
        point.MapMode = "CenterOfMass"
        self.ref(name, point, "AttachmentSupport", expect)

    def addRefs(self, doc, body):
        for name, sign in (("rim_p", 1), ("rim_m", -1)):
            if name in self.REFS:
                self.datum(body, name, self.pocket, self.rim(sign), (lambda k: lambda: self.rim(k))(sign))
        for name, sign in (("side_p", 1), ("side_m", -1)):
            if name in self.REFS:
                self.datum(body, name, self.pocket, self.side(sign), (lambda k: lambda: self.side(k))(sign))

    def edit(self, doc):
        self.state = dict(self.start)
        self.state.update(self.end)
        self.apply()
        doc.recompute()


# Everyday edits that move the arcs, no trade


class R2cGroovePadTaller(R2cRim):
    __doc__ = R2cRim.__doc__ + " Groove; the pad goes from 20 to 24 high."
    end = dict(H=24.0)


class R2cGrooveWider(R2cRim):
    __doc__ = R2cRim.__doc__ + " Groove; its radius goes from 3 to 4."
    end = dict(g=4.0)


class R2cDoubleDTaller(R2cRim):
    __doc__ = R2cRim.__doc__ + " Double-D (notches |x| >= 8); the pad goes from 20 to 24 high."
    cutter = "notches"
    end = dict(H=24.0)


class R2cDoubleDChamferTaller(R2cRim):
    __doc__ = R2cRim.__doc__ + " Double-D; a chamfer of 1 on the +y arc (its Base the reference); the pad goes from 20 to 24 high."
    cutter = "notches"
    REFS = ("chamfer_p", "rim_m")
    end = dict(H=24.0)

    def addRefs(self, doc, body):
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (self.pocket, self.names(self.pocket, self.rim(1)))
        chamfer.Size = 1.0 * self.scale
        self.ref("chamfer_p", chamfer, "Base", lambda: self.rim(1), Chamfered(1.0 * self.scale))
        doc.recompute()
        self.datum(body, "rim_m", chamfer, self.rim(-1), lambda: self.rim(-1))


class R2cGrooveFilletFaceRadius(R2cRim):
    __doc__ = R2cRim.__doc__ + " Groove; a fillet on the +y arc, a datum on the fillet's face; the fillet's radius goes from 0.5 to 1."
    REFS = ("fillet_face",)
    radius = 0.5

    def filletFace(self):
        s, r, h = self.scale, self.radius, self.state["H"]
        c = math.cos(math.radians(45))
        return face(contains=V(0, (10 - r + r * c) * s, (h - r + r * c) * s))

    def addRefs(self, doc, body):
        self.radius = 0.5
        self.fillet = body.newObject("PartDesign::Fillet", "Fillet")
        self.fillet.Base = (self.pocket, self.names(self.pocket, self.rim(1)))
        self.fillet.Radius = self.radius * self.scale
        doc.recompute()
        self.datum(body, "fillet_face", self.fillet, self.filletFace(), self.filletFace)

    def edit(self, doc):
        self.radius = 1.0
        self.fillet.Radius = self.radius * self.scale
        doc.recompute()


class R2cGrooveFilletFaceTaller(R2cGrooveFilletFaceRadius):
    __doc__ = R2cRim.__doc__ + " Groove; a fillet of 0.5 on the +y arc, a datum on the fillet's face; the pad goes from 20 to 24 high."
    end = dict(H=24.0)

    def edit(self, doc):
        R2cRim.edit(self, doc)


# The seam moved in the sketch: an ellipse's major axis flipped (the same curve, no Placement)


class R2cEllipseGrooveFlip(R2cRim):
    __doc__ = R2cRim.__doc__ + " Ellipse disk, groove; the ellipse's major axis flips to -x in the sketch."
    ea = 12.0
    end = dict(flip=True)


class R2cEllipseGrooveFlipShifted(R2cRim):
    __doc__ = R2cRim.__doc__ + " Ellipse disk, groove; the major axis flips and the groove goes to gy 1, g 2.5."
    ea = 12.0
    end = dict(flip=True, gy=1.0, g=2.5)


class R2cEllipseGrooveFlipTaller(R2cRim):
    __doc__ = R2cRim.__doc__ + " Ellipse disk, groove; the major axis flips and the pad goes to 24."
    ea = 12.0
    end = dict(flip=True, H=24.0)


class R2cEllipseDoubleDFlip(R2cRim):
    __doc__ = R2cRim.__doc__ + " Ellipse disk, double-D; the major axis flips. Also the side faces' halves."
    ea = 12.0
    cutter = "notches"
    REFS = ("rim_p", "rim_m", "side_p", "side_m")
    end = dict(flip=True)


class R2cEllipseDoubleDFlipTaller(R2cEllipseDoubleDFlip):
    __doc__ = R2cRim.__doc__ + " Ellipse disk, double-D; the major axis flips and the pad goes to 24."
    end = dict(flip=True, H=24.0)


class R2cCircleDoubleDSides(R2cRim):
    __doc__ = R2cRim.__doc__ + " Circle disk, double-D; the pad goes to 24. The side faces' halves too (twins on a periodic face, no CLS)."
    cutter = "notches"
    REFS = ("rim_p", "rim_m", "side_p", "side_m")
    end = dict(H=24.0)
