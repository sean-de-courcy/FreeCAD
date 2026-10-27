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

"""Corpus cases (ops#504, class E, E1; the review's redraw cases f and g, `notes/naming-class-E.md`
5.1): a Sketcher link to a whole face, after the profile is deleted and drawn again larger.

Ports `ExternalFaceRedrawCentred|circle_on_x0|V2s` and `ExternalFaceRedrawCentred|circle_on_y0|V2s`
(`corpus/predicted/E.json`, probe `work/504-review/probe_e1.py` cases f and g).

The model: a 20 x 20 square (the lines front y = 0, right x = 20, back y = 20, left x = 0) padded
10 high. Two sketches at z = 0 each project the pad's top face (one link, four projected lines). In
`OnX` a circle (r 1) has its centre on the projected left line (PointOnObject, x = 0); in `OnY`
another has its centre on the projected front line (y = 0). The edit deletes the square's lines and
draws a 24 x 24 square centred where the old one was (from the corner (-2, 22), the other way
round): the top face is the same face in the same place, found by its place, and every edge's line
moved by 2 mm. The left edge is now at x = -2 and the front edge at y = -2.

The expectation: the reference holds the top face (the face is the right one) and the circle stays
on the projected line of the edge it was on (the left, the front: x = -2, y = -2), or the sketch
fails loudly (`OwnOrBroken`). The design's choice (E1, CC1) is the loud break: the face found by
geometry gives no evidence of which new edge is which old edge, so no positional pairing. Today the
k-th new line takes the k-th old line's Id: the row predicts the circle on the left edge ends on the
left edge by luck (`correct`) and the circle on the front edge ends on the back edge, 22 mm from
where it was, silently (`wrong`); the verdicts of a run are in the ledger. The face link is a live
guess by place: `harness.guessVerdict` takes the loud break of `OwnOrBroken` for a right answer
(it scored it `guessed-wrong` until fork PR 387 round 2), so E1's break reads `broken`."""

import Sketcher

from PartDesignTests.Scenarios.harness import (
    Outcome,
    OwnOrBroken,
    Scenario,
    Z,
    face,
)
from PartDesignTests.Scenarios import models as m

TOL = 1e-6


def lineOn(sketch, axis, value):
    """The GeoId of the sketch's one projected line on axis = value."""
    found = [
        -i - 1
        for i, g in enumerate(sketch.ExternalGeo)
        if i >= 2
        and hasattr(g, "StartPoint")
        and abs(getattr(g.StartPoint, axis) - value) < TOL
        and abs(getattr(g.EndPoint, axis) - value) < TOL
    ]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} projected lines on {axis} = {value}")
    return found[0]


class CircleOnItsSourceEdge(Outcome):
    """The sketch computes, its PointOnObject constraint names a projected line on axis = value
    (`on` before the edit, `after` after it) and the circle's centre lies on that line."""

    def __init__(self, on, after):
        self.on, self.after = on, after

    def compare(self, scenario, consumer, target, expectation):
        axis, value = self.on if scenario.stepName is None else self.after
        constraint = [c for c in consumer.Constraints if c.Type == "PointOnObject"][0]
        line = consumer.ExternalGeo[-constraint.Second - 1]
        ends = (line.StartPoint, line.EndPoint)
        if not all(abs(getattr(p, axis) - value) < TOL for p in ends):
            return False, f"the constraint is on the projected line {ends[0]} - {ends[1]}"
        centre = consumer.Geometry[constraint.First].Center
        if abs(getattr(centre, axis) - value) > TOL:
            return False, f"the circle's centre is at {centre}"
        return True, ""


class ExternalFaceRedrawCentred(Scenario):
    """The 20 x 20 square redrawn 24 x 24 and centred (the module's docstring)."""

    area = "sketch_face_redraw"
    CLASSES = ("E",)
    AXES = ("M8", "E5")
    ISSUE = "ops#504"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("circle_on_x0", "circle_on_y0")

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def expected(self):
        return OwnOrBroken(self.topFace())

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 20), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        top = self.names(pad, self.topFace())[0]
        for name, ref, axis, value, centre in (
            ("OnX", "circle_on_x0", "x", 0, (0, 5)),
            ("OnY", "circle_on_y0", "y", 0, (5, 0)),
        ):
            sketch = m.sketch(doc, name, [], body)
            sketch.addExternal(pad.Name, top)
            doc.recompute()
            circle = sketch.addGeometry(m.circle(*centre, 1), False)
            sketch.addConstraint(
                Sketcher.Constraint("PointOnObject", circle, 3, lineOn(sketch, axis, value))
            )
            sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
            self.ref(
                ref,
                sketch,
                "ExternalGeometry",
                self.expected,
                CircleOnItsSourceEdge((axis, value), (axis, -2)),
            )

    def edit(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(-2, 22), (22, 22), (22, -2), (-2, -2)]), False)
