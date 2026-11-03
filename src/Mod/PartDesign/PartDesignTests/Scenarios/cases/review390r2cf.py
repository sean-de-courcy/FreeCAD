# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2cf (ops#468, PR 390 round 2c's T1 fix, a63dc0ce2d): a CLS twin whose offset from
the twins' centroid is kept by a trade. A disk of radius 10 padded 20 high; a through pocket (along
z) of one periodic B-spline with three lobes, mirror-symmetric about the line at thetaL degrees,
lobes at 0, thetaL and 2 thetaL (one face, so the three top-rim arcs between the lobes are the A2
twins 0of3/1of3/2of3 with MOD,ORD,CLS, numbered from the circle's seam at +x, which lies inside the
lobe at 0). The arcs A (between the lobes at 0 and thetaL) and B (between thetaL and 2 thetaL) are
mirror images, so their offsets from the three arcs' centroid are as long; C is longer. The edit
turns the cutter's B-spline inside its sketch (no Placement) clockwise by psi, the angle from A's
offset to B's (measured on the built model, about 117 degrees for thetaL 110): the seam then lies in
the lobe that was at thetaL, the numbering starts at B, and A's name 0of3 passes to B, whose offset
from the turned set's centroid is A's old offset, with A's length. The right arc for each reference
is the one the cutter carried: its middle turned by -psi (the whole set turns rigidly; no other
rigid motion maps the old set onto the new one, since C is longer than A and B)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Scenario, edge

V = App.Vector


def lobeCurve(m, thetaL, s, sigma=23.5):
    lobes = [m - thetaL, m, m + thetaL]
    pts = []
    for i in range(72):
        t = m + i * 5.0
        r = 6.0
        for c in lobes:
            d = (t - c + 180.0) % 360.0 - 180.0
            r += 6.0 * math.exp(-((d / sigma) ** 2))
        a = math.radians(t)
        pts.append(V(r * s * math.cos(a), r * s * math.sin(a), 0))
    bs = Part.BSplineCurve()
    bs.interpolate(pts, PeriodicFlag=True)
    return bs


class R2cfLobes(Scenario):
    """See the module."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M4", "E2")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2cf"
    TIER = "F"
    SIZE = 24
    SCALE = 1.0
    REFS = ("rim_a", "rim_b", "rim_c")
    R = 10.0
    H = 20.0
    thetaL = 110.0
    taller = 0.0  # the pad made taller in the same edit

    def middles(self):
        t = self.thetaL
        return {"rim_a": t / 2.0, "rim_b": t * 1.5, "rim_c": t + 180.0}

    def rimAt(self, degrees):
        s = self.scale
        a = math.radians(degrees - self.turned)
        return edge(curve="circle", contains=V(self.R * s * math.cos(a), self.R * s * math.sin(a), self.height * s))

    def arcsNow(self):
        s = self.scale
        out = []
        for e in self.pocket.Shape.Edges:
            if isinstance(e.Curve, Part.Circle) and abs(e.Curve.Radius - self.R * s) < 1e-6 * s:
                c = e.CenterOfMass
                if abs(c.z - self.height * s) < 1e-6 * s:
                    out.append(c)
        return out

    def build(self, doc):
        s = self.scale
        self.turned = 0.0
        self.height = self.H
        body = doc.addObject("PartDesign::Body", "Body")
        disk = doc.addObject("Sketcher::SketchObject", "Disk")
        body.addObject(disk)
        disk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), self.R * s), False)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = disk
        self.pad.Length = self.H * s
        self.tool = doc.addObject("Sketcher::SketchObject", "Tool")
        body.addObject(self.tool)
        self.tool.addGeometry(lobeCurve(self.thetaL, self.thetaL, s), False)
        self.tool.Placement = App.Placement(V(0, 0, 40 * s), App.Rotation())
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.tool
        self.pocket.Type = 1
        doc.recompute()
        # psi: the angle from A's offset (from the three arcs' centroid) to B's
        arcs = self.arcsNow()
        if len(arcs) != 3:
            raise RuntimeError("expected three rim arcs, got %d" % len(arcs))
        g = (arcs[0] + arcs[1] + arcs[2]) * (1.0 / 3.0)

        def nearest(deg):
            u = V(math.cos(math.radians(deg)), math.sin(math.radians(deg)), 0)
            return max(arcs, key=lambda c: (c - V(0, 0, c.z)).normalize().dot(u))

        oa = nearest(self.thetaL / 2.0) - g
        ob = nearest(self.thetaL * 1.5) - g
        self.psi = math.degrees(math.atan2(ob.y, ob.x) - math.atan2(oa.y, oa.x)) % 360.0
        for name, deg in self.middles().items():
            if name in self.REFS:
                point = body.newObject("PartDesign::Point", name)
                point.AttachmentSupport = [(self.pocket, self.names(self.pocket, self.rimAt(deg))[0])]
                point.MapMode = "CenterOfMass"
                self.ref(name, point, "AttachmentSupport", (lambda d: lambda: self.rimAt(d))(deg))
        doc.recompute()

    def edit(self, doc):
        s = self.scale
        geo = self.tool.Geometry
        g0 = geo[0]
        g0.rotate(App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), -self.psi)))
        geo[0] = g0
        self.tool.Geometry = geo
        self.turned = self.psi
        if self.taller:
            self.height = self.H + self.taller
            self.pad.Length = self.height * s
        doc.recompute()


class R2cfLobesTurned(R2cfLobes):
    __doc__ = R2cfLobes.__doc__ + " The cutter turns by psi."


class R2cfLobesTurnedTaller(R2cfLobes):
    __doc__ = R2cfLobes.__doc__ + " The cutter turns by psi and the pad goes from 20 to 24 high."
    taller = 4.0
