# SPDX-License-Identifier: LGPL-2.1-or-later
"""Class D cases of ops#557: a target's Placement moves while its local shape stays, so a
reference's exact name and fingerprint (measured without the placement) agree, and the element
the name holds sits somewhere else globally.

The frame of a PartDesign feature is its Placement: the first feature's from its sketch's support
(a datum plane) or the sketch's own Placement, every later feature's copied from its base
(`ProfileBased::positionByPrevious`). Turning the first sketch turns the whole chain's frame.
The tools of later features are fixed in the body (an unattached sketch) or attached to the part
(a sketch on a face, which turns with it).

Two models. **The disk**: a Pad, 20 high, of a circle of radius 10 about the origin; a vertical
Pocket through all of an ellipse of semi-axes 14 and 6 about the origin, from z 20; both
symmetric under a half turn, so a 180-degree turn of the frame leaves the local shape and every
name byte-identical. Variants: the ellipse replaced by a square of half-side 8 (symmetric under a
quarter turn as well); a centred hole of radius 3 added (its elements are invariant under the
turn). **The box**: a Pad 20 x 10 x 10 at the origin with two holes of radius 1.5 at (5, 5) and
(15, 5) through its top face (the tool attached to the Pad, so it moves with the part): a part
without the symmetry, moved as a whole.

Expected results follow the convention of A2e's `EllipseCutDiskTurned` (review390r2b_rim.py,
decision 209) where a tool stayed in the body: **where the part's global geometry is unchanged
by the edit, every reference stays where it was globally** (nothing visible changed, so nothing
may jump). Where the part moved as one piece, a tool attached to it included, a reference
follows its element (decision 212, `notes\\naming-class-D.md` 11: the box cases, the tool on the
part). Expected results are defined by the
geometry above; no file is used. The design and its table: `notes\\naming-class-D.md` section 10.
"""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, edge, face, vertex

V = App.Vector
Z = V(0, 0, 1)
IDENTITY = App.Placement()


def turn(deg, base=V()):
    return App.Placement(base, App.Rotation(Z, deg))


class FrameMove(Scenario):
    """A part, one edit that moves the frame (`motion`, the global motion of the first feature's
    frame), and references into the last feature. Each reference is described by its element's
    kind and a point on it before the edit; the expectation keeps the point (`follow` False: the
    geometry is unchanged globally) or moves it with the frame (`follow` True)."""

    abstract = True
    area = "frame"
    CLASSES = ("D",)
    ISSUE = "ops#557"
    FOUND_BY = "designer ops#557"
    TIER = "F"
    motion = IDENTITY
    follow = False
    ELEMENTS = {}  # name -> (kind, point[, normal]); kinds: arc, line, plane, cylinder, vertex

    def where(self, pt):
        return self.motion.multVec(V(*pt)) if (self.follow and self.stepName) else V(*pt)

    def expect(self, name):
        spec = self.ELEMENTS[name]
        kind, pt = spec[0], self.where(spec[1])
        if kind == "arc":
            return edge(curve="circle", contains=pt)
        if kind == "line":
            return edge(curve="line", contains=pt)
        if kind == "plane":
            return face(surface="plane", contains=pt)
        if kind == "cylinder":
            return face(surface="cylinder", contains=pt)
        return vertex(pt)

    def consumer(self, doc, body, name, target):
        """A datum point at the element (a vertex: on it; else its centre of mass), or a sketch
        on a plane face."""
        kind = self.ELEMENTS[name][0]
        element = self.names(target, self.expect(name))[0]
        if kind == "plane":
            owner = doc.addObject("Sketcher::SketchObject", name)
            body.addObject(owner)
            owner.AttachmentSupport = [(target, element)]
            owner.MapMode = "FlatFace"
            outcome = Attached()
        else:
            owner = body.newObject("PartDesign::Point", name)
            owner.AttachmentSupport = [(target, element)]
            owner.MapMode = "Vertex" if kind == "vertex" else "CenterOfMass"
            outcome = None
        return owner, outcome

    def addRefs(self, doc, body, target):
        for name in self.REFS:
            owner, outcome = self.consumer(doc, body, name, target)
            doc.recompute()
            self.ref(name, owner, "AttachmentSupport", (lambda n=name: self.expect(n)), outcome)

    def build(self, doc):
        self.body = doc.addObject("PartDesign::Body", "Body")
        target = self.model(doc, self.body)
        doc.recompute()
        self.addRefs(doc, self.body, target)

    def edit(self, doc):
        self.move(doc)


# The disk: the frame turns under the ellipse, which is fixed in the body


def crossing():
    """The ellipse's crossing of the rim in the first quadrant, at z 20."""
    y = math.sqrt(96.0 * 36.0 / 160.0)
    return (math.sqrt(100.0 - y * y), y, 20.0)


class EllipseDisk(FrameMove):
    """The disk with the ellipse pocket. References: the rim arcs at +y and -y (`rim_p`,
    `rim_m`), the +y cap (`cap_p`), the +y piece of the cylinder (`wall_p`), the +y piece of the
    bottom (`bottom_p`) and the crossing of ellipse and rim at +x +y (`cross_pp`)."""

    abstract = True
    REFS = ("rim_p", "rim_m", "cap_p", "wall_p", "bottom_p", "cross_pp")
    ELEMENTS = {
        "rim_p": ("arc", (0, 10, 20)),
        "rim_m": ("arc", (0, -10, 20)),
        "cap_p": ("plane", (0, 8, 20)),
        "wall_p": ("cylinder", (0, 10, 10)),
        "bottom_p": ("plane", (0, 8, 0)),
        "cross_pp": ("vertex", crossing()),
    }
    motion = turn(180)
    diskOn = "placement"  # or "datum": the disk's sketch attached to a datum plane
    toolOn = "body"  # or "part": the tool attached to the Pad (ObjectXY, offset 20): it moves with it

    def disk(self, doc, body):
        self.diskSketch = doc.addObject("Sketcher::SketchObject", "Disk")
        body.addObject(self.diskSketch)
        self.diskSketch.addGeometry(Part.Circle(V(0, 0, 0), Z, 10), False)
        if self.diskOn == "datum":
            self.datum = body.newObject("PartDesign::Plane", "DP")
            self.datum.MapMode = "Deactivated"
            doc.recompute()
            self.diskSketch.AttachmentSupport = [(self.datum, "")]
            self.diskSketch.MapMode = "FlatFace"
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.diskSketch
        self.pad.Length = 20
        doc.recompute()

    def toolSketch(self, doc, body, name, geometry):
        tool = doc.addObject("Sketcher::SketchObject", name)
        body.addObject(tool)
        for g in geometry:
            tool.addGeometry(g, False)
        if self.toolOn == "part":
            tool.AttachmentSupport = [(self.pad, "")]
            tool.MapMode = "ObjectXY"
            tool.AttachmentOffset = App.Placement(V(0, 0, 20), App.Rotation())
        else:
            tool.Placement = App.Placement(V(0, 0, 20), App.Rotation())
        return tool

    def pocketThrough(self, body, tool, name):
        pocket = body.newObject("PartDesign::Pocket", name)
        pocket.Profile = tool
        pocket.Type = 1
        return pocket

    def cutter(self):
        return [Part.Ellipse(V(14, 0, 0), V(0, 6, 0), V(0, 0, 0))]

    def model(self, doc, body):
        self.disk(doc, body)
        self.tool = self.toolSketch(doc, body, "Tool", self.cutter())
        self.pocket = self.pocketThrough(body, self.tool, "Pocket")
        return self.pocket

    def move(self, doc):
        if self.diskOn == "datum":
            self.datum.Placement = self.motion
        else:
            self.diskSketch.Placement = self.motion


class FrameEllipseDiskTurned(EllipseDisk):
    __doc__ = EllipseDisk.__doc__ + " The disk's sketch turns 180 degrees; the ellipse is fixed in the body (A2e's EllipseCutDiskTurned with more elements)."


class FrameEllipseDiskTurned90(EllipseDisk):
    """The disk with the ellipse pocket; the disk's sketch turns 90 degrees, so the local shape
    changes (the ellipse is not symmetric under it) and the names move: not an exact hit (the
    control for the non-exact frame family of `notes\\pr366-r9.md`). The disk's seam lands on the
    +y arc and splits it, so the points sit at 80 and 260 degrees."""

    ELEMENTS = dict(
        EllipseDisk.ELEMENTS,
        rim_p=("arc", (10 * math.cos(math.radians(80)), 10 * math.sin(math.radians(80)), 20)),
        rim_m=("arc", (10 * math.cos(math.radians(260)), 10 * math.sin(math.radians(260)), 20)),
        wall_p=("cylinder", (10 * math.cos(math.radians(80)), 10 * math.sin(math.radians(80)), 10)),
    )
    motion = turn(90)


class FrameEllipseDatumTurned(EllipseDisk):
    __doc__ = EllipseDisk.__doc__ + " The disk's sketch is attached to a datum plane, which turns 180 degrees; the ellipse is fixed in the body."
    diskOn = "datum"


class FrameEllipseDiskTurnedToolOnPart(EllipseDisk):
    __doc__ = EllipseDisk.__doc__ + " The ellipse's sketch is attached to the Pad (ObjectXY, offset 20), so it turns with the part; the disk's sketch turns 180 degrees. The part turned as one piece, so the references follow it (decision 212, which supersedes decision 209's convention here)."
    toolOn = "part"
    follow = True


class FrameDiskHoleTurned(EllipseDisk):
    """The disk with a centred hole of radius 3 (the Pocket `Hole`, its sketch fixed in the
    body) and no ellipse. The disk's sketch turns 180 degrees: every element is invariant under
    the turn (`hole_rim`, `hole_wall`, `top`, `outer_wall`), the hole's seam vertex at (3, 0, 20)
    stays globally (`hole_seam`, the tool is fixed) and the disk's seam vertex at (10, 0, 20)
    turns with the disk's sketch to (-10, 0, 20) (`disk_seam`): nothing is at its old place, so
    the reference follows it."""

    REFS = ("hole_rim", "hole_wall", "top", "outer_wall", "hole_seam", "disk_seam")
    ELEMENTS = {
        "hole_rim": ("arc", (3, 0, 20)),
        "hole_wall": ("cylinder", (3, 0, 10)),
        "top": ("plane", (0, 6, 20)),
        "outer_wall": ("cylinder", (0, 10, 10)),
        "hole_seam": ("vertex", (3, 0, 20)),
        "disk_seam": ("vertex", (10, 0, 20)),
    }

    def cutter(self):
        return [Part.Circle(V(0, 0, 0), Z, 3)]

    def where(self, pt):
        if self.stepName and tuple(pt) == self.ELEMENTS["disk_seam"][1]:
            return self.motion.multVec(V(*pt))
        return EllipseDisk.where(self, pt)


class SquareDisk(EllipseDisk):
    """The disk with a square pocket of half-side 8 (its corners outside the disk): four rim
    arcs, four walls, four caps. References: the +x wall (`wall_px`, a sketch on it), the
    crossing of the +x wall and the rim at +y (`cross_pp`), the -y rim arc (`rim_m`), the -y cap
    (`cap_m`), the +x wall's top edge (`edge_px`) and the disk's seam vertex at (10, 0, 20)
    (`seam`), which turns with the disk's sketch: nothing is at its old place, and the
    reference follows it."""

    abstract = True
    REFS = ("wall_px", "cross_pp", "rim_m", "cap_m", "edge_px", "seam")
    ELEMENTS = {
        "wall_px": ("plane", (8, 0, 10)),
        "cross_pp": ("vertex", (8, 6, 20)),
        "rim_m": ("arc", (0, -10, 20)),
        "cap_m": ("plane", (0, -9, 20)),
        "edge_px": ("line", (8, 0, 20)),
        "seam": ("vertex", (10, 0, 20)),
    }

    def cutter(self):
        a = 8
        pts = [V(-a, -a, 0), V(a, -a, 0), V(a, a, 0), V(-a, a, 0), V(-a, -a, 0)]
        return [Part.LineSegment(pts[i], pts[i + 1]) for i in range(4)]

    def where(self, pt):
        if self.stepName and tuple(pt) == self.ELEMENTS["seam"][1]:
            return self.motion.multVec(V(*pt))
        return EllipseDisk.where(self, pt)


class FrameSquareDiskTurnedToolFixed(SquareDisk):
    __doc__ = SquareDisk.__doc__ + " The disk's sketch turns 180 degrees; the square is fixed in the body. The square's lines keep their ids, so in the frame the walls' names turn with the square: the names' elements moved locally (not an exact hit; the control)."


class FrameSquareDiskTurnedToolOnPart180(SquareDisk):
    __doc__ = SquareDisk.__doc__ + " The square's sketch is attached to the Pad (ObjectXY, offset 20), so it turns with the part; the disk's sketch turns 180 degrees: local shape and names identical; the part turned as one piece, so the references follow it (decision 212)."
    toolOn = "part"
    follow = True


class FrameSquareDiskTurnedToolOnPart90(SquareDisk):
    __doc__ = SquareDisk.__doc__ + " As FrameSquareDiskTurnedToolOnPart180 with a 90-degree turn (the square is symmetric under it too; the seam lands on the +y arc)."
    toolOn = "part"
    follow = True
    motion = turn(90)


# The box: the part moves with its frame (the holes' sketch is on its top face)


class Box(FrameMove):
    """The box with two holes. References into the Pocket: the first hole's rim and wall
    (`hole1_rim`, `hole1_wall`), the top face and the x 0 end (`top`, `end_x0`, sketches), the
    top edge along y 0 (`edge_y0`), the origin corner and the corner above it (`corner_000`,
    `corner_top`). The edit moves the base sketch's Placement (`motion`): the part moves as a
    whole and every element with it."""

    abstract = True
    follow = True
    REFS = ("hole1_rim", "hole1_wall", "top", "end_x0", "edge_y0", "corner_000", "corner_top")
    ELEMENTS = {
        "hole1_rim": ("arc", (6.5, 5, 10)),
        "hole1_wall": ("cylinder", (6.5, 5, 5)),
        "top": ("plane", (10, 1, 10)),
        "end_x0": ("plane", (0, 5, 5)),
        "edge_y0": ("line", (10, 0, 10)),
        "corner_000": ("vertex", (0, 0, 0)),
        "corner_top": ("vertex", (0, 0, 10)),
    }

    def model(self, doc, body):
        self.base = doc.addObject("Sketcher::SketchObject", "Base")
        body.addObject(self.base)
        pts = [V(0, 0, 0), V(20, 0, 0), V(20, 10, 0), V(0, 10, 0), V(0, 0, 0)]
        for i in range(4):
            self.base.addGeometry(Part.LineSegment(pts[i], pts[i + 1]), False)
        self.block = body.newObject("PartDesign::Pad", "Block")
        self.block.Profile = self.base
        self.block.Length = 10
        doc.recompute()
        self.holes = doc.addObject("Sketcher::SketchObject", "Holes")
        body.addObject(self.holes)
        self.holes.addGeometry(Part.Circle(V(5, 5, 0), Z, 1.5), False)
        self.holes.addGeometry(Part.Circle(V(15, 5, 0), Z, 1.5), False)
        self.holes.AttachmentSupport = [(self.block, "")]
        self.holes.MapMode = "ObjectXY"
        self.holes.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.holes
        self.pocket.Type = 1
        return self.pocket

    def move(self, doc):
        self.base.Placement = self.motion


class FrameBoxMovedTurned(Box):
    __doc__ = Box.__doc__ + " The box goes to (3, 4) and turns 30 degrees: no element of the moved part is where another was."
    motion = App.Placement(V(3, 4, 0), App.Rotation(Z, 30))


class FrameBoxRaisedByHeight(Box):
    __doc__ = Box.__doc__ + " The box rises by its own height, 10: its bottom is where its top was, with the other sides."
    motion = App.Placement(V(0, 0, 10), App.Rotation())


class FrameBoxShiftedByPitch(Box):
    __doc__ = Box.__doc__ + " The box shifts by the holes' pitch, 10, along -x: the second hole is where the first was."
    motion = App.Placement(V(-10, 0, 0), App.Rotation())


class FrameBoxTurnedAboutCentre(Box):
    __doc__ = Box.__doc__.replace("the part moves as a\n    whole and every element with it", "the box turns 180 degrees about its own centre, which maps it onto itself (the holes trade places): the part turned as one piece, so the references follow it (decision 212)")
    motion = App.Placement(V(20, 10, 0), App.Rotation(Z, 180))
