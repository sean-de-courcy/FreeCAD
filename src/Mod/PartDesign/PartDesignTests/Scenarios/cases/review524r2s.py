# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prA1e-r2: resizes and moves over holes."""


import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, edge, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0


def outer(z, x0=-10, y0=-10, x1=20, y1=10):
    c = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    return Part.makePolygon(c + c[:1])


def rectFace(x0, y0, x1, y1, z):
    c = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    return Part.Face(Part.makePolygon(c + c[:1])).toNurbs().Faces[0]


def holeShell(z, hole, x1=20):
    hx0, hy0, hx1, hy1 = hole
    h = [V(hx0, hy0, z), V(hx0, hy1, z), V(hx1, hy1, z), V(hx1, hy0, z)]
    plate = (
        Part.Face(Part.Plane(V(0, 0, z), V(0, 0, 1)), [outer(z, x1=x1), Part.makePolygon(h + h[:1])])
        .toNurbs()
        .Faces[0]
    )
    return Part.Shell([plate, rectFace(hx0, hy0, hx1, hy1, z)])


class Base(Scenario):
    abstract = True
    CLASSES = ("A",)
    ISSUE = "ops#524"
    FOUND_BY = "review prA1e-r2"
    TIER = "F"
    BEFORE = {}
    AFTER = {}
    HOLE = (-1, -2, 1, 2)
    mirror = False

    def place(self, x, y):
        return face(contains=V(x, y, HEIGHT))

    def shell(self):
        return holeShell(HEIGHT, self.HOLE)

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.body = body
        self.plate = m.feature(doc, "Plate", self.shell())
        self.profile = m.sketch(doc, "Profile", self.geometry(), body)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, self.faceNames(self.plate.Shape))
        self.pad.Refine = False
        doc.recompute()
        target = self.pad
        if self.mirror:
            mirrored = doc.addObject("PartDesign::Mirrored", "Mirrored")
            mirrored.Originals = [self.pad]
            mirrored.MirrorPlane = (m.originFeature(body, "XZ_Plane"), [""])
            mirrored.Refine = False
            body.addObject(mirrored)
            doc.recompute()
            target = mirrored
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            sub = self.names(target, self.place(*self.BEFORE[name]))[0]
            point.AttachmentSupport = [(target, sub)]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = target

    @staticmethod
    def faceNames(shape):
        return ["Face%d" % (i + 1) for i in range(len(shape.Faces))]

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(*self.BEFORE[name])
            if self.AFTER[name] is None:
                return BROKEN
            return self.place(*self.AFTER[name])

        return expect

    def edit(self, doc):
        self.change(doc)
        self.edited = True




def gridShell(z, holes, x0=-10, y0=-10, x1=20, y1=10, fillZ=None):
    wires = [outer(z, x0, y0, x1, y1)]
    for hx0, hy0, hx1, hy1 in holes:
        h = [V(hx0, hy0, z), V(hx0, hy1, z), V(hx1, hy1, z), V(hx1, hy0, z)]
        wires.append(Part.makePolygon(h + h[:1]))
    plate = Part.Face(Part.Plane(V(0, 0, z), V(0, 0, 1)), wires).toNurbs().Faces[0]
    return Part.Shell([plate] + [rectFace(*hole, z if fillZ is None else fillZ) for hole in holes])





def gridShell(z, holes, x0=-10, y0=-10, x1=20, y1=10, fillZ=None):
    wires = [outer(z, x0, y0, x1, y1)]
    for hx0, hy0, hx1, hy1 in holes:
        h = [V(hx0, hy0, z), V(hx0, hy1, z), V(hx1, hy1, z), V(hx1, hy0, z)]
        wires.append(Part.makePolygon(h + h[:1]))
    plate = Part.Face(Part.Plane(V(0, 0, z), V(0, 0, 1)), wires).toNurbs().Faces[0]
    return Part.Shell([plate] + [rectFace(*hole, z if fillZ is None else fillZ) for hole in holes])


class Resize(Base):
    """A plate (z = 10, x -10..20, y -10..10) with holes, each filled, and a rectangle profile over
    them; the profile is resized. A: the plate's one piece (holey), which the resize keeps."""

    abstract = True
    area = "resize-over-holes"
    AXES = ("M5", "E1")
    HOLES = ((-1, -1, 1, 1),)
    RECT = (-5, -3, 5, 3)
    NEW = (-5, -3, 6, 3)
    REFS = ("A",)
    BEFORE = {"A": (-4, -2.5)}
    AFTER = {"A": (-4, -2.5)}

    def shell(self):
        return gridShell(HEIGHT, self.HOLES)

    def geometry(self):
        return m.rectangle(*self.RECT)

    def change(self, doc):
        m.moveRectangle(self.profile, *self.NEW)


class ResizeRight(Resize):
    """One 2 x 2 hole under the middle of x -5..5, y -3..3; the right edge moves +1."""
    abstract = False


class ResizeRightPlus2(Resize):
    abstract = False
    NEW = (-5, -3, 7, 3)


class ResizeRightBigHole(Resize):
    abstract = False
    HOLES = ((-3, -2, 3, 2),)
    RECT = (-6, -3.5, 6, 3.5)
    NEW = (-6, -3.5, 7, 3.5)
    BEFORE = {"A": (-5.5, 0)}
    AFTER = {"A": (-5.5, 0)}


class ResizeRightScale4m(Resize):
    """The same at ~x40 (a 4 m plate)."""
    abstract = False
    HOLES = ((-40, -40, 40, 40),)
    RECT = (-200, -120, 200, 120)
    NEW = (-200, -120, 240, 120)
    BEFORE = {"A": (-150, -100)}
    AFTER = {"A": (-150, -100)}

    def shell(self):
        return gridShell(HEIGHT, self.HOLES, -400, -400, 800, 400)


class ResizeLeft(Resize):
    """Control: the left edge moves -1 (kept on both)."""
    abstract = False
    NEW = (-6, -3, 5, 3)


class ResizeUp(Resize):
    """Control: the top edge moves +1 (kept on both)."""
    abstract = False
    NEW = (-5, -3, 5, 4)


def slide(name, dx, dy, holes=((-1, -1, 1, 1),), rect=(-5, -3, 5, 3)):
    x0, y0, x1, y1 = rect
    attrs = dict(abstract=False, HOLES=holes, RECT=rect, NEW=(x0 + dx, y0 + dy, x1 + dx, y1 + dy),
                 BEFORE={"A": (0, y0 + 0.5 if y0 > -3.5 else -3.2)}, AFTER={"A": (0, y0 + 0.5 if y0 > -3.5 else -3.2)},
                 __doc__="slide by (%s, %s)" % (dx, dy))
    return type(name, (Resize,), attrs)


SlideA = slide("SlideA", 0.3, 0)
SlideB = slide("SlideB", 0.5, 0.5)
SlideC = slide("SlideC", -0.5, 0.2)
SlideD = slide("SlideD", 1.0, 0)
SlideE = slide("SlideE", 0, 1.0)
SlideF = slide("SlideF", 2.0, 0)
SlideG = slide("SlideG", 0.2, -0.4)
SlideH = slide("SlideH", -1.0, -1.0)
SlideTwo = slide("SlideTwo", 0.5, 0.3, holes=((-3, -1, -1, 1), (1, -1, 3, 1)))
SlideTwoB = slide("SlideTwoB", 1.0, 0.0, holes=((-3, -1, -1, 1), (1, -1, 3, 1)))
SlideSq = slide("SlideSq", 0.7, 0.0, holes=((-1, -1, 1, 1),), rect=(-4, -4, 4, 4))
SlideSqB = slide("SlideSqB", 0.0, 0.7, holes=((-1, -1, 1, 1),), rect=(-4, -4, 4, 4))
