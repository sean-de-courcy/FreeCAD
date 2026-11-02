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

"""Corpus cases (ops#516, class E): sketches attached FlatFace to twin pieces of a Pad's cap.

A Pad (Refine off) of a disc of radius 3 at (3, 3) up to a `Part::Feature` shell at z = 10: a plate
with an elliptic hole (a = 4, b = 1, centre (3, 3)) and the hole's fill, as `shell_twins.py`'s
`TiltedTwins`. The far cap is cut into twin pieces above (T) and below (Bo) the hole, told apart
only by their order, and the fill's piece. A sketch is attached FlatFace to each twin, and a datum
point (centre of mass) to T beside them. The edit turns the ellipse about its centre: past 45
degrees the twins trade names.

Expected (decision 121): each reference holds its old piece turned with the hole, the smaller
turn's reading; at 90 degrees the two readings tie and the reference breaks.

The twins are coplanar, so a FlatFace sketch has the same placement on either. Holding the other
twin after a trade is `equivalent` here; at the tie the sketch must still break. D1 found the
sketch kept silently on the traded name where the datum breaks (ops#516; fork PR 379 round 2)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0  # the shell's height (the far end of the pad)
CENTRE = (3.0, 3.0)  # the disc's and the hole's


def ellipseShell(z, rot=0.0):
    """A plate x -10..20, y -10..10 with an elliptic hole (a 4, b 1) turned by `rot` degrees about
    its centre, and the hole's fill, at height z."""
    c = [V(-10, -10, z), V(20, -10, z), V(20, 10, z), V(-10, 10, z)]
    edge_ = Part.Ellipse(V(CENTRE[0], CENTRE[1], z), 4, 1).toShape()
    if rot:
        edge_.rotate(V(CENTRE[0], CENTRE[1], z), V(0, 0, 1), rot)
    hole = Part.Face(Part.Wire([edge_]))
    plate = Part.Face(Part.makePolygon(c + c[:1])).cut(hole).Faces[0].toNurbs().Faces[0]
    return Part.Shell([plate, hole.toNurbs().Faces[0]])


def turned(x, y, degrees):
    a = math.radians(degrees)
    dx, dy = x - CENTRE[0], y - CENTRE[1]
    return (CENTRE[0] + dx * math.cos(a) - dy * math.sin(a), CENTRE[1] + dx * math.sin(a) + dy * math.cos(a))


class TwinSketch(Scenario):
    """The model and its edit; a subclass sets the turn (`TURN`, degrees)."""

    abstract = True
    area = "attachment"
    CLASSES = ("E", "A")
    AXES = ("M5", "E7")
    ISSUE = "ops#516"
    FOUND_BY = "review pr379-r2"
    TIER = "F"
    REFS = ("sketch_top", "sketch_bottom", "datum_top")
    # each reference's twin: a point inside it before the edit (2.5 above or below the centre)
    SPOTS = {"sketch_top": (3.0, 5.5), "sketch_bottom": (3.0, 0.5), "datum_top": (3.0, 5.5)}
    TURN = 0.0

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.plate = m.feature(doc, "Plate", ellipseShell(HEIGHT))
        profile = m.sketch(doc, "Profile", [m.circle(CENTRE[0], CENTRE[1], 3)], body)
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = profile
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.plate, ["Face1", "Face2"])
        self.pad.Refine = False
        doc.recompute()
        for name in self.REFS:
            if name.startswith("sketch"):
                owner = body.newObject("Sketcher::SketchObject", name)
                mode = "FlatFace"
            else:
                owner = body.newObject("PartDesign::Point", name)
                mode = "CenterOfMass"
            owner.AttachmentSupport = [(self.pad, self.names(self.pad, self.at(*self.SPOTS[name]))[0])]
            owner.MapMode = mode
            self.ref(name, owner, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = self.pad

    @staticmethod
    def at(x, y):
        return face(contains=V(x, y, HEIGHT))

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.at(*self.SPOTS[name])
            if abs(abs(self.TURN) - 90.0) < 1e-9:
                return BROKEN
            return self.at(*turned(*self.SPOTS[name], self.TURN))

        return expect

    def edit(self, doc):
        self.plate.Shape = ellipseShell(HEIGHT, rot=self.TURN)
        self.pad.UpToShape = (self.plate, ["Face1", "Face2"])
        self.edited = True


class TwinSketchTurned30(TwinSketch):
    """Turned 30 degrees: no trade, every reference keeps its piece (a control)."""

    TURN = 30.0


class TwinSketchTurned60(TwinSketch):
    """Turned 60 degrees: the twins trade names; each reference holds its old piece turned."""

    TIER = "G"
    TURN = 60.0


class TwinSketchTurned80(TwinSketch):
    """Turned 80 degrees: as 60, nearer the tie."""

    TURN = 80.0


class TwinSketchTurned90(TwinSketch):
    """Turned 90 degrees: the readings +90 and -90 tie, so every reference breaks (decision 121),
    the sketches too, though either twin gives them the same placement."""

    TIER = "G"
    TURN = 90.0
