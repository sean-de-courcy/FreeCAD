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

"""Model helpers for the naming dump and the naming scenarios."""

import math

import FreeCAD as App
import Part

V = App.Vector

# Object IDs of the documents from newDocument() are above this bound.
MIN_OBJECT_ID = 1000


def newDocument(name):
    """A new document whose objects all get IDs above MIN_OBJECT_ID.

    A new document starts its object IDs at a random 0..5000 (Document.cpp). The name reports
    (`Masker`) write a tag that is some object's ID as that object's name, so with a low start a
    small tag that is no object's ID (a slice's number) would read as the first objects' names
    (ops#52). A document starting below the bound is closed and created again."""
    for _ in range(100):
        doc = App.newDocument(name)
        if nextObjectId(doc) > MIN_OBJECT_ID:
            return doc
        App.closeDocument(doc.Name)
    raise RuntimeError(f"no new document with object IDs above {MIN_OBJECT_ID}")


def nextObjectId(doc):
    """The ID the document's next object gets, from a probe object added and removed again
    (removing it doesn't give its ID back)."""
    probe = doc.addObject("App::DocumentObjectGroup", "ObjectIdProbe")
    nextId = probe.ID + 1
    doc.removeObject(probe.Name)
    return nextId


def body(doc):
    return doc.addObject("PartDesign::Body", "Body")


def originFeature(body, role):
    for feature in body.Origin.OriginFeatures:
        if feature.Role == role:
            return feature
    raise ValueError(role)


def sketch(doc, name, geometry, body=None, z=0.0, placement=None):
    """A sketch of the geometry, unconstrained, placed at height z (or at `placement`)."""
    sketch = doc.addObject("Sketcher::SketchObject", name)
    if body is not None:
        body.addObject(sketch)
    sketch.Placement = placement or App.Placement(V(0, 0, z), App.Rotation())
    sketch.addGeometry(geometry, False)
    return sketch


def polyline(points):
    """Line segments through the points, open."""
    return [Part.LineSegment(V(*p, 0), V(*q, 0)) for p, q in zip(points, points[1:])]


def polygon(points):
    """Line segments through the points, closed."""
    return polyline(list(points) + [points[0]])


def rectangle(x0, y0, x1, y1):
    return polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def circle(x, y, r):
    return Part.Circle(V(x, y, 0), V(0, 0, 1), r)


def closedWire(points):
    """A closed polygon through the 3D points."""
    return Part.makePolygon([V(*p) for p in points + [points[0]]])


def feature(doc, name, shape):
    feature = doc.addObject("Part::Feature", name)
    feature.Shape = shape
    return feature


def box(doc, name, size, at=(0, 0, 0)):
    box = doc.addObject("Part::Box", name)
    box.Length, box.Width, box.Height = size
    box.Placement.Base = V(*at)
    return box


def edgesWhere(shape, test):
    """1-based indexes of the edges whose centre passes `test`, in index order."""
    return [i + 1 for i, edge in enumerate(shape.Edges) if test(edge.CenterOfMass)]


# ---------------------------------------------------------------------------------------------
# PartDesign features and sketch edits, as the scenarios use them
# ---------------------------------------------------------------------------------------------


def pad(body, profile, length, name="Pad"):
    pad = body.newObject("PartDesign::Pad", name)
    pad.Profile = profile
    pad.Length = length
    return pad


def pocketThroughAll(body, profile, name="Pocket"):
    pocket = body.newObject("PartDesign::Pocket", name)
    pocket.Profile = profile
    pocket.Type = "ThroughAll"
    return pocket


def pocket(body, profile, length, name="Pocket"):
    pocket = body.newObject("PartDesign::Pocket", name)
    pocket.Profile = profile
    pocket.Length = length
    return pocket


def moveRectangle(sketch, x0, y0, x1, y1, first=0):
    """Moves the rectangle drawn by `rectangle()` at geometry `first` to new corners; its lines
    keep their geometry IDs."""
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    setLines(sketch, {first + i: (corners[i], corners[(i + 1) % 4]) for i in range(4)})


def setLines(sketch, lines):
    """Moves the end points of line geometries {index: ((x0, y0), (x1, y1))}. The lines keep their
    geometry IDs, as when a user drags or re-dimensions them."""
    geometry = sketch.Geometry
    for index, (start, end) in lines.items():
        line, start, end = geometry[index], V(*start, 0), V(*end, 0)
        if (start - line.EndPoint).Length < 1e-9:  # moving the start first would give a point
            line.EndPoint = end
            line.StartPoint = start
        else:
            line.StartPoint = start
            line.EndPoint = end
    sketch.Geometry = geometry


def rotationFromAxes(x, y):
    """The rotation whose local X and Y axes are the given global directions."""
    x, y = V(*x), V(*y)
    z = x.cross(y)
    matrix = App.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, 0, 0, 0, 1)
    return App.Rotation(matrix)


# ---------------------------------------------------------------------------------------------
# A disc with two flats, and a notch in its right arc (the continuation of arcs, ops#7, Task 2
# PR 7b)
# ---------------------------------------------------------------------------------------------

DISC_CENTER, DISC_RADIUS = (10, 5), 5
# Half the angle of the disc's right arc: its ends are on the chords y = 1 and y = 9.
DISC_HALF_ANGLE = math.asin(4 / 5)


def discCircle(radius=DISC_RADIUS):
    return Part.Circle(V(*DISC_CENTER, 0), V(0, 0, 1), radius)


def onDisc(radius, degrees):
    """The point at `radius` from the disc's centre, `degrees` from +X."""
    a = math.radians(degrees)
    return V(DISC_CENTER[0] + radius * math.cos(a), DISC_CENTER[1] + radius * math.sin(a), 0)


def twoFlatDisc():
    """A circle, centre (10, 5), radius 5, cut by the chords y = 1 and y = 9: geometry 0 is the
    right arc (about -53..53 degrees), 1 the top flat, 2 the left arc, 3 the bottom flat."""
    a = DISC_HALF_ANGLE
    return [
        Part.ArcOfCircle(discCircle(), -a, a),
        Part.LineSegment(V(13, 9, 0), V(7, 9, 0)),
        Part.ArcOfCircle(discCircle(), math.pi - a, math.pi + a),
        Part.LineSegment(V(7, 1, 0), V(13, 1, 0)),
    ]


def notchDiscArc(sketch):
    """Cuts a notch into the right arc of `twoFlatDisc()`: the arc ends at -10 degrees (its
    geometry ID kept), lines go in to radius 3 and out again, with a concentric arc of radius 3
    between them (the notch's floor), and a new arc from 10 degrees to the arc's old end."""
    geometry = sketch.Geometry
    geometry[0].setParameterRange(-DISC_HALF_ANGLE, math.radians(-10))
    sketch.Geometry = geometry
    sketch.addGeometry(
        [
            Part.LineSegment(onDisc(DISC_RADIUS, -10), onDisc(3, -10)),
            Part.ArcOfCircle(discCircle(3), math.radians(-10), math.radians(10)),
            Part.LineSegment(onDisc(3, 10), onDisc(DISC_RADIUS, 10)),
            Part.ArcOfCircle(discCircle(), math.radians(10), DISC_HALF_ANGLE),
        ],
        False,
    )


def fillDiscNotch(sketch):
    """Undoes `notchDiscArc()`: its four geometries deleted, the right arc whole again."""
    for geoId in reversed(range(4, sketch.GeometryCount)):
        sketch.delGeometry(geoId)
    geometry = sketch.Geometry
    geometry[0].setParameterRange(-DISC_HALF_ANGLE, DISC_HALF_ANGLE)
    sketch.Geometry = geometry
