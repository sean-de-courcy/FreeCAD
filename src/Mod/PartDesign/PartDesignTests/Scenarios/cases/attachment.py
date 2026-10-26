# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Corpus cases (ops#506): attachment to moving faces. A sketch and a datum plane follow the
faces they are attached to when the pad under them changes; a sketch on a face that goes must
break. Converted from the scenario area `attachment` (PR 1 of the corpus, the seed cases):
scaled to the user's ~600 mm, with a thin variant."""

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, X, Y, Z, face
from PartDesignTests.Scenarios import models as m


class AttachmentEdit(Scenario):
    """A rectangle (0..20 x 0..10, at scale 1) padded 10 high; a sketch attached to the right
    face and a datum plane attached to the top face. Thin: the rectangle is 0.5 deep."""

    abstract = True
    area = "attachment"
    CLASSES = ("D",)
    AXES = ("M1", "E5", "X4:600")
    ISSUE = "ops#506"
    FOUND_BY = "port"
    TIER = "G"
    SIZE = 20
    SCALE = 30
    THIN = True
    REFS = ("sketch_right_face", "datum_top_face")
    x0, y0, width, height = 0, 0, 20, 10

    @property
    def depth(self):
        return 0.5 if self.thin else 10

    def rightFace(self):
        return face("plane", normal=X, through=self.s(self.x0 + self.width, 0, 0))

    def topFace(self):
        return face("plane", normal=Z, through=self.s(0, 0, self.height))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 20, self.depth)), body)
        pad = m.pad(body, profile, self.s(10))
        doc.recompute()
        onSide = body.newObject("Sketcher::SketchObject", "OnSide")
        onSide.AttachmentSupport = [(pad, self.names(pad, self.rightFace())[0])]
        onSide.MapMode = "FlatFace"
        plane = body.newObject("PartDesign::Plane", "TopPlane")
        plane.AttachmentSupport = [(pad, self.names(pad, self.topFace())[0])]
        plane.MapMode = "FlatFace"
        self.ref("sketch_right_face", onSide, "AttachmentSupport", self.rightFace, Attached())
        self.ref("datum_top_face", plane, "AttachmentSupport", self.topFace, Attached())

    def corners(self, x0, y0, x1):
        """The profile's four lines, from (x0, y0) to (x1, y0 + depth), at scale."""
        y1 = y0 + self.depth
        points = [self.s(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        return {i: (points[i], points[(i + 1) % 4]) for i in range(4)}


class AttachLength(AttachmentEdit):
    """The pad gets longer: 10 -> 15."""

    def edit(self, doc):
        doc.Pad.Length = self.s(15)
        self.height = 15


class AttachWidth(AttachmentEdit):
    """The right side moves from x = 20 to x = 26; its line keeps its geometry ID."""

    def edit(self, doc):
        lines = self.corners(0, 0, 26)
        m.setLines(doc.Profile, {i: lines[i] for i in (0, 1, 2)})
        self.width = 26


class AttachMove(AttachmentEdit):
    """The whole rectangle moves by (5, 3); every line keeps its geometry ID."""

    def edit(self, doc):
        m.setLines(doc.Profile, self.corners(5, 3, 25))
        self.x0, self.y0 = 5, 3


class AttachProngDeleted(Scenario):
    """ops#68: a U-shaped pad, 10 high: a base (y 0..5) with two prongs (x 0..10 and 20..30) up to
    y = 20. A sketch is attached (FlatFace) to one prong's end face (y = 20). The edit deletes that
    prong from the profile, so the face is gone; the other prong's end face is coplanar and gives
    the same placement. The attacher's substitute (a related element, or the old index name)
    could rebind the sketch to it silently, which is wrong: the reference should break."""

    abstract = True
    area = "attachment"
    CLASSES = ("D",)
    AXES = ("M1", "E1", "X4:600")
    ISSUE = "ops#68"
    FOUND_BY = "port"
    TIER = "G"
    SIZE = 30
    SCALE = 20
    REFS = ("sketch_end_face",)
    U = [(0, 0), (30, 0), (30, 20), (20, 20), (20, 5), (10, 5), (10, 20), (0, 20)]
    prongX = None  # the x of the attached end face's centre
    deleted = False

    def endFace(self):
        if self.deleted:
            return BROKEN
        return face("plane", normal=Y, through=self.s(0, 20, 0), contains=self.s(self.prongX, 20, 5))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.polygon([self.s(x, y) for x, y in self.U]), body)
        pad = m.pad(body, profile, self.s(10))
        doc.recompute()
        onEnd = body.newObject("Sketcher::SketchObject", "OnEnd")
        onEnd.AttachmentSupport = [(pad, self.names(pad, self.endFace())[0])]
        onEnd.MapMode = "FlatFace"
        self.ref("sketch_end_face", onEnd, "AttachmentSupport", self.endFace, Attached())

    def line(self, a, b):
        return (self.s(*a), self.s(*b))


class AttachLeftProngDeleted(AttachProngDeleted):
    """The left prong goes: the profile becomes (0,0) (30,0) (30,20) (20,20) (20,5) (0,5)."""

    prongX = 5

    def edit(self, doc):
        m.setLines(doc.Profile, {4: self.line((20, 5), (0, 5)), 7: self.line((0, 5), (0, 0))})
        doc.Profile.delGeometries([5, 6])
        self.deleted = True


class AttachRightProngDeleted(AttachProngDeleted):
    """The right prong goes: the profile becomes (0,0) (30,0) (30,5) (10,5) (10,20) (0,20)."""

    prongX = 25

    def edit(self, doc):
        m.setLines(doc.Profile, {1: self.line((30, 0), (30, 5)), 4: self.line((30, 5), (10, 5))})
        doc.Profile.delGeometries([2, 3])
        self.deleted = True
