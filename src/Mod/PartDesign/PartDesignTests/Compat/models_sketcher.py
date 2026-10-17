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

"""The corpus's Sketcher models (FreeCAD-CH ops#323 PR B2, notes/beta-compatibility.md 3.6,
D3's Sketcher list), beyond B1's external-geometry sketch and VarSet-driven constraint. Each
sketch's geometry is drawn where its constraints put it, so the solver moves nothing: a
recompute that does move something shows in the record's geometry. Same conventions as
`models.py`."""

import math

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Compat.models import V, attachedSketch, plane
from PartDesignTests.Compat.models_part import freeSketch
from PartDesignTests.Compat.models_partdesign import newBody
from PartDesignTests.Scenarios import models as m

C = Sketcher.Constraint


def line(a, b):
    return Part.LineSegment(V(*a, 0), V(*b, 0))


def SketchConstraints(make):
    """Every common constraint kind on lines, arcs and circles, in one sketch outside a Body.

    0-4, a closed outline: A (0, 0)-(30, 0) horizontal, its start on the origin, 30 long (X);
    B (30, 0)-(30, 10) vertical, 10 long (Y); C an arc, radius 5, centre (25, 10), from B's end
    (tangent at the endpoint) round to (20, 10); D (20, 10)-(0, 10) parallel to A; E (0, 10)-
    (0, 0) perpendicular to A, 10 long (Y). 5, F: a circle at (10, 5), diameter 4 (its centre
    placed by X and Y distances). 6, G: a circle equal to F, symmetric to it about 7, H: a construction line
    x = 15 from A to D (its ends on A and D, point-on-object). 8, I: a line from (2, 2), 4 long,
    at 30 degrees. 9, J: a blocked line (24, 2)-(28, 2). 10, K: a circle, radius 3, at y 4,
    tangent to B (edge to edge): centre (27, 4). A reference (non-driving) distance: A's
    length again."""
    doc = make("SketchConstraints")
    end = (2 + 4 * math.cos(math.radians(30)), 2 + 4 * math.sin(math.radians(30)))
    sketch = freeSketch(
        doc,
        "Sketch",
        [
            line((0, 0), (30, 0)),
            line((30, 0), (30, 10)),
            Part.ArcOfCircle(Part.Circle(V(25, 10, 0), V(0, 0, 1), 5), 0, math.pi),
            line((20, 10), (0, 10)),
            line((0, 10), (0, 0)),
            m.circle(10, 5, 2),
            m.circle(20, 5, 2),
            line((15, 0), (15, 10)),
            line((2, 2), end),
            line((24, 2), (28, 2)),
            m.circle(27, 4, 3),
        ],
    )
    sketch.setConstruction(7, True)
    constraints = [
        C("Horizontal", 0),
        C("Coincident", 0, 1, -1, 1),
        C("DistanceX", 0, 1, 0, 2, 30),
        C("Coincident", 0, 2, 1, 1),
        C("Vertical", 1),
        C("DistanceY", 1, 1, 1, 2, 10),
        C("Tangent", 1, 2, 2, 1),
        C("Radius", 2, 5),
        C("Coincident", 2, 2, 3, 1),
        C("Parallel", 3, 0),
        C("Coincident", 3, 2, 4, 1),
        C("Coincident", 4, 2, 0, 1),
        C("Perpendicular", 4, 0),
        C("DistanceY", 4, 2, 4, 1, 10),
        C("Diameter", 5, 4),
        C("DistanceX", -1, 1, 5, 3, 10),
        C("DistanceY", -1, 1, 5, 3, 5),
        C("PointOnObject", 7, 1, 0),
        C("PointOnObject", 7, 2, 3),
        C("Vertical", 7),
        C("DistanceX", -1, 1, 7, 1, 15),
        C("Equal", 5, 6),
        C("Symmetric", 5, 3, 6, 3, 7),
        C("DistanceX", -1, 1, 8, 1, 2),
        C("DistanceY", -1, 1, 8, 1, 2),
        C("Distance", 8, 4),
        C("Angle", 8, math.radians(30)),
        C("Block", 9),
        C("Tangent", 10, 1),
        C("Radius", 10, 3),
        C("DistanceY", -1, 1, 10, 3, 4),
    ]
    for constraint in constraints:
        sketch.addConstraint(constraint)
    reference = sketch.addConstraint(C("DistanceX", 0, 1, 0, 2, 30))
    sketch.setDriving(reference, False)
    doc.recompute()
    checkSketch(sketch, dof=0)
    return {}


def SketchCurves(make):
    """An ellipse and a B-spline (their poles and knots in the record), in a sketch on a Body's
    XY plane.

    An ellipse centred on the origin (coincident with it), major radius 10 along X, minor 5; a
    cubic B-spline through no constraint, poles (15, 0), (18, 6), (24, -4), (28, 5), (32, 0),
    knots 0, 0.5, 1 with multiplicities 4, 1, 4 (clamped)."""
    doc = make("SketchCurves")
    body = newBody(doc, "Body")
    spline = Part.BSplineCurve()
    spline.buildFromPolesMultsKnots(
        [V(15, 0, 0), V(18, 6, 0), V(24, -4, 0), V(28, 5, 0), V(32, 0, 0)],
        [4, 1, 4],
        [0, 0.5, 1],
        False,
        3,
    )
    sketch = attachedSketch(
        body,
        "Sketch",
        plane(body, "XY_Plane"),
        [Part.Ellipse(V(0, 0, 0), 10, 5), spline],
    )
    sketch.addConstraint(C("Coincident", 0, 3, -1, 1))
    doc.recompute()
    checkSketch(sketch)
    return {}


def SketchUnderConstrained(make):
    """An under-constrained sketch (DoF > 0): free geometry must stay where it was saved.

    A rectangle (2, 3)-(14, 9) whose corners are only coincident (not placed, not sized); a
    circle, radius 2.5, at (20, 6), free; a line (0, 12)-(7, 15) with a horizontal-distance
    constraint of 7 only."""
    doc = make("SketchUnderConstrained")
    sketch = freeSketch(
        doc,
        "Sketch",
        m.rectangle(2, 3, 14, 9) + [m.circle(20, 6, 2.5), line((0, 12), (7, 15))],
    )
    for i in range(4):
        sketch.addConstraint(C("Coincident", i, 2, (i + 1) % 4, 1))
    sketch.addConstraint(C("DistanceX", 5, 1, 5, 2, 7))
    doc.recompute()
    checkSketch(sketch)
    if sketch.DoF <= 0:
        raise AssertionError(f"SketchUnderConstrained: DoF {sketch.DoF}, expected more than 0")
    return {}


def SketchCarbonCopy(make):
    """A sketch on a datum plane with an attachment offset, and a carbon copy of it.

    A Body; a datum plane on its XY plane, offset 6 up; Sketch on the datum plane with an
    attachment offset (5, 5, 0) turned 30 degrees about its normal, a rectangle 0..10 x 0..4,
    padded 3; Sketch001 on the same datum plane with the same offset, a carbon copy of Sketch
    (its geometry and constraints, linked), padded 2 further up from an offset of 3 (so the two
    pads stack: 40 x 5 in all)."""
    doc = make("SketchCarbonCopy")
    body = newBody(doc, "Body")
    datum = body.newObject("PartDesign::Plane", "DatumPlane")
    datum.AttachmentSupport = [(plane(body, "XY_Plane"), "")]
    datum.MapMode = "FlatFace"
    datum.AttachmentOffset = App.Placement(V(0, 0, 6), App.Rotation())
    offset = App.Placement(V(5, 5, 0), App.Rotation(V(0, 0, 1), 30))
    sketch = attachedSketch(body, "Sketch", datum, m.rectangle(0, 0, 10, 4))
    sketch.AttachmentOffset = offset
    for i in range(4):
        sketch.addConstraint(C("Coincident", i, 2, (i + 1) % 4, 1))
    m.pad(body, sketch, 3)
    doc.recompute()
    copy = attachedSketch(body, "Sketch001", datum, [])
    copy.AttachmentOffset = App.Placement(V(5, 5, 3), App.Rotation(V(0, 0, 1), 30))
    doc.recompute()
    copy.carbonCopy("Sketch", False)
    m.pad(body, copy, 2, "Pad001")
    doc.recompute()
    checkSketch(copy)
    if len(copy.Geometry) != 4 or len(copy.Constraints) != 4:
        raise AssertionError(
            f"the carbon copy has {len(copy.Geometry)} geometries and "
            f"{len(copy.Constraints)} constraints, expected 4 and 4"
        )
    return {"volumes": {"Pad": 120, "Pad001": 200}}


def checkSketch(sketch, dof=None):
    """Raises unless the sketch solves cleanly (and, given `dof`, has that many degrees of
    freedom)."""
    if sketch.solve() != 0:
        raise AssertionError(f"{sketch.Name} doesn't solve")
    for kind in ("Conflicting", "Redundant", "PartiallyRedundant", "MalformedConstraints"):
        found = list(getattr(sketch, kind, []) or [])
        if found:
            raise AssertionError(f"{sketch.Name}: {kind} constraints {found}")
    if dof is not None and sketch.DoF != dof:
        raise AssertionError(f"{sketch.Name}: DoF {sketch.DoF}, expected {dof}")


MODELS = [SketchConstraints, SketchCurves, SketchUnderConstrained, SketchCarbonCopy]
