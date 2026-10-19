# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import math
import unittest

import FreeCAD
import Part
import Sketcher
import TestSketcherApp

from PartDesignTests.Scenarios import models

App = FreeCAD


class TestPipe(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestPipe")

    def testSimpleAdditivePipeCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.ProfileSketch = self.Doc.addObject("Sketcher::SketchObject", "ProfileSketch")
        self.Body.addObject(self.ProfileSketch)
        TestSketcherApp.CreateCircleSketch(self.ProfileSketch, (0, 0), 1)
        self.Doc.recompute()
        self.SpineSketch = self.Doc.addObject("Sketcher::SketchObject", "SpineSketch")
        self.Body.addObject(self.SpineSketch)
        self.SpineSketch.MapMode = "FlatFace"
        self.SpineSketch.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        self.SpineSketch.addGeometry(
            Part.LineSegment(App.Vector(0.0, 0.0, 0), App.Vector(0, 1, 0)), False
        )
        self.SpineSketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
        self.SpineSketch.addConstraint(Sketcher.Constraint("PointOnObject", 0, 2, -2))
        self.SpineSketch.addConstraint(Sketcher.Constraint("DistanceY", 0, 1, 0, 2, 1))
        self.Doc.recompute()
        self.AdditivePipe = self.Doc.addObject("PartDesign::AdditivePipe", "AdditivePipe")
        self.Body.addObject(self.AdditivePipe)
        self.AdditivePipe.Profile = self.ProfileSketch
        self.AdditivePipe.Spine = self.SpineSketch
        self.Doc.recompute()
        self.assertAlmostEqual(self.AdditivePipe.Shape.Volume, 3.14159265)

    def testSimpleSubtractivePipeCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.ProfileSketch = self.Doc.addObject("Sketcher::SketchObject", "ProfileSketch")
        self.Body.addObject(self.ProfileSketch)
        TestSketcherApp.CreateCircleSketch(self.ProfileSketch, (0, 0), 1)
        self.Doc.recompute()
        self.SpineSketch = self.Doc.addObject("Sketcher::SketchObject", "SpineSketch")
        self.Body.addObject(self.SpineSketch)
        self.SpineSketch.MapMode = "FlatFace"
        self.SpineSketch.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        self.SpineSketch.addGeometry(
            Part.LineSegment(App.Vector(0.0, 0.0, 0), App.Vector(0, 1, 0)), False
        )
        self.SpineSketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
        self.SpineSketch.addConstraint(Sketcher.Constraint("PointOnObject", 0, 2, -2))
        self.SpineSketch.addConstraint(Sketcher.Constraint("DistanceY", 0, 1, 0, 2, 1))
        self.Doc.recompute()
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "PadSketch")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (-5, -5), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1.0
        self.Doc.recompute()
        self.SubtractivePipe = self.Doc.addObject("PartDesign::SubtractivePipe", "SubtractivePipe")
        self.Body.addObject(self.SubtractivePipe)
        self.SubtractivePipe.Profile = self.ProfileSketch
        self.SubtractivePipe.Spine = self.SpineSketch
        self.Doc.recompute()
        self.assertAlmostEqual(self.SubtractivePipe.Shape.Volume, 100 - 3.14159265)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestPipe")
        # print ("omit closing document for debugging")


V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))


def onPlane(axis, value):
    """Whether a point lies on the plane where the coordinate `axis` (0, 1, 2) is `value`."""
    return lambda point: abs(point[axis] - value) < 1e-6


def elementsOf(shape, kind):
    return {"Face": shape.Faces, "Edge": shape.Edges, "Vertex": shape.Vertexes}[kind]


def firstName(shape, element):
    names = shape.ElementReverseMap[element]
    return names if isinstance(names, str) else names[0]


def lastSection(shape, element):
    return App.getDecodedMappedName(firstName(shape, element))[-1]


def place(element):
    return element.Point if element.ShapeType == "Vertex" else element.CenterOfMass


def elementsWhere(shape, kind, test):
    """The names (`Edge3`) of the shape's edges or vertices that lie wholly where `test` holds."""
    found = []
    for index, element in enumerate(elementsOf(shape, kind), 1):
        points = [element.Point] if kind == "Vertex" else element.discretize(9)
        if all(test(point) for point in points):
            found.append(f"{kind}{index}")
    return found


class TestPipeEndNames(unittest.TestCase):
    """A Pipe's start edges and vertices keep the profile's names, its end ones are the last
    section's projections (PRJ), and the edges at a bend keep their names from the side faces
    (ops#351). Before, both ends were named `UPP` from the side faces: a start edge's name then
    had the shape of the bend edge's beside it, and the solver took the one for the other."""

    def setUp(self):
        self.doc = models.newDocument("PartDesignTestPipeEndNames")
        self.doc.HistoryAlgorithm = "V2"
        self.doc.InternNames = False  # plain names as text (ops#6 Q6)
        self.body = models.body(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def sketch(self, name, geometry, **placement):
        return models.sketch(self.doc, name, geometry, self.body, **placement)

    def lPath(self):
        """Up 30 along Z, then 20 along X."""
        return self.sketch("Path", models.polyline([(0, 0), (0, 30), (20, 30)]), placement=XZ)

    def line(self, start=0, end=30):
        """Along Z from z = start to z = end."""
        return self.sketch("Path", models.polyline([(0, start), (0, end)]), placement=XZ)

    def square(self, name="Profile", half=2, z=0):
        return self.sketch(name, models.rectangle(-half, -half, half, half), z=z)

    def pipe(self, profile, spine, kind="AdditivePipe", **properties):
        pipe = self.body.newObject("PartDesign::" + kind, "Pipe")
        pipe.Profile = profile
        pipe.Spine = (spine, [])
        for name, value in properties.items():
            setattr(pipe, name, value)
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        return pipe

    def assertStartKeepsNames(self, shape, sketch, atStart, kinds=("Edge", "Vertex"), shift=V()):
        """Each edge and vertex at the start has the name of the sketch's element at its place
        (the pipe starts where the profile lies), or `shift` away from it (the start nearest the
        profile, when the profile lies inside the spine)."""
        for kind in kinds:
            own = [
                (place(element), firstName(sketch.Shape, f"{kind}{index}"))
                for index, element in enumerate(elementsOf(sketch.Shape, kind), 1)
            ]
            starts = elementsWhere(shape, kind, atStart)
            self.assertEqual(len(starts), len(own), (kind, starts))
            for element in starts:
                where = place(shape.getElement(element)) - shift
                expected = [name for at, name in own if at.isEqual(where, 1e-6)]
                self.assertEqual(len(expected), 1, (element, where))
                self.assertEqual(firstName(shape, element), expected[0], element)

    def assertEndProjects(self, shape, sketch, atEnd, kinds=("Edge", "Vertex")):
        """Each edge and vertex at the end is named as a projection (PRJ) by the pipe of one
        element of the sketch (its last section), each element once. With `atEnd` None, the end
        is whatever is named so."""
        for kind in kinds:
            own = sorted(
                firstName(sketch.Shape, f"{kind}{index}")
                for index in range(1, len(elementsOf(sketch.Shape, kind)) + 1)
            )
            if atEnd is None:
                ends = [
                    f"{kind}{index}"
                    for index in range(1, len(elementsOf(shape, kind)) + 1)
                    if "PRJ" in lastSection(shape, f"{kind}{index}")["mapperFlags"]
                ]
            else:
                ends = elementsWhere(shape, kind, atEnd)
            self.assertEqual(len(ends), len(own), (kind, ends))
            linked = []
            for element in ends:
                last = lastSection(shape, element)
                self.assertIn("PRJ", last["mapperFlags"], (element, firstName(shape, element)))
                self.assertEqual(last["opCode"], "PSH", (element, firstName(shape, element)))
                linked += last["linkedNames"]
            self.assertEqual(sorted(linked), own, kind)

    def assertNamesDistinct(self, shape):
        names = {}
        for kind in ("Face", "Edge", "Vertex"):
            for index in range(1, len(elementsOf(shape, kind)) + 1):
                names.setdefault(firstName(shape, f"{kind}{index}"), []).append(f"{kind}{index}")
        self.assertEqual([elements for elements in names.values() if len(elements) > 1], [])

    def testLPathEnds(self):
        """A square with a round hole (two wires) along an L path: both wires' start elements
        keep the sketch's names, the end ones (at x = 20) are their projections, and the edges at
        the bend (on the plane x + z = 30) keep `UPP` names."""
        path = self.lPath()
        profile = self.sketch("Profile", models.rectangle(-2, -2, 2, 2) + [models.circle(0, 0, 1)])
        pipe = self.pipe(profile, path, Transition="Right corner")
        shape = pipe.Shape
        self.assertAlmostEqual(shape.Volume, 800 - 50 * math.pi, 2)
        self.assertStartKeepsNames(shape, profile, onPlane(2, 0))
        self.assertEndProjects(shape, profile, onPlane(0, 20))
        bend = elementsWhere(shape, "Edge", lambda p: abs(p.x + p.z - 30) < 1e-6)
        self.assertTrue(bend)
        for element in bend:
            self.assertIn("UPP", lastSection(shape, element)["mapperFlags"], element)
        self.assertNamesDistinct(shape)

    def testTransitionsAndModes(self):
        """The same names under each transition and in Frenet mode, on the pipe's own solid
        (AddSubShape: "Transformed" makes an invalid one at the sharp corner, ops#370, which
        Refine reduces, and whose end isn't where the profile's would be: its end is found by
        name)."""
        cases = [
            {"Transition": "Transformed", "Refine": False},
            {"Transition": "Right corner"},
            {"Transition": "Round corner"},
            {"Transition": "Right corner", "Mode": "Frenet"},
        ]
        for properties in cases:
            with self.subTest(**properties):
                pipe = self.pipe(self.square(), self.lPath(), **properties)
                profile = pipe.Profile[0]
                self.assertStartKeepsNames(pipe.AddSubShape, profile, onPlane(2, 0))
                atEnd = None if properties["Transition"] == "Transformed" else onPlane(0, 20)
                self.assertEndProjects(pipe.AddSubShape, profile, atEnd)

    def testSpineTowardsTheProfile(self):
        """A spine drawn towards the profile (from z = 30 down to it at z = 0): the shell starts
        at z = 30, but the names stay with the elements at the profile's place, and the far end
        (z = 30) is the projection."""
        profile = self.square()
        pipe = self.pipe(profile, self.line(30, 0))
        self.assertAlmostEqual(pipe.Shape.Volume, 480)
        self.assertStartKeepsNames(pipe.Shape, profile, onPlane(2, 0))
        self.assertEndProjects(pipe.Shape, profile, onPlane(2, 30))

    def testSpineExtendedPastTheProfile(self):
        """A spine drawn towards the profile (z = 30 down to z = 0), a fillet on the start edge
        at the profile's place, then the spine extended past the profile to z = -10: the end
        nearer the profile (z = -10) keeps its names, the far end (z = 30) is the projection, and
        the fillet follows to z = -10. Before (fork PR 337 round 1), only a profile lying exactly
        on the far end swapped the ends, so the names, and the fillet, went to z = 30."""
        profile = self.square()
        path = self.line(30, 0)
        pipe = self.pipe(profile, path)
        startEdge = lambda z: lambda point: abs(point.z - z) < 1e-6 and abs(point.y + 2) < 1e-6
        edges = elementsWhere(pipe.Shape, "Edge", startEdge(0))
        self.assertEqual(len(edges), 1, edges)
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pipe, edges)
        fillet.Radius = 0.5
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())

        path.deleteAllGeometry()
        path.addGeometry(Part.LineSegment(V(0, 30, 0), V(0, -10, 0)))
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 640)
        self.assertStartKeepsNames(pipe.Shape, profile, onPlane(2, -10), shift=V(0, 0, -10))
        self.assertEndProjects(pipe.Shape, profile, onPlane(2, 30))
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(fillet.Base[1], elementsWhere(pipe.Shape, "Edge", startEdge(-10)))

    def testAuxiliarySpine(self):
        """Auxiliary mode: a straight spine with a slanted auxiliary one."""
        path = self.line()
        aux = self.sketch("Aux", models.polyline([(10, 0), (10, 30)]), placement=XZ)
        profile = self.square()
        pipe = self.pipe(profile, path, Mode="Auxiliary", AuxiliarySpine=(aux, []))
        self.assertStartKeepsNames(pipe.Shape, profile, onPlane(2, 0))
        self.assertEndProjects(pipe.Shape, profile, onPlane(2, 30))

    def testMultisectionEndProjectsTheLastSection(self):
        """Multisection: the end is the last section's projection, not the profile's."""
        profile = self.square()
        section = self.square("Section", 3, z=30)
        pipe = self.pipe(profile, self.line(), Transformation="Multisection", Sections=[section])
        self.assertStartKeepsNames(pipe.Shape, profile, onPlane(2, 0))
        self.assertEndProjects(pipe.Shape, section, onPlane(2, 30))
        self.assertNamesDistinct(pipe.Shape)

    def testPointLastSection(self):
        """A point as the last section: the apex is its projection; no edge at the end."""
        profile = self.square()
        point = self.sketch("Point", Part.Point(V(0, 0, 0)), z=30)
        pipe = self.pipe(
            profile, self.line(), Transformation="Multisection", Sections=[(point, ["Vertex1"])]
        )
        self.assertStartKeepsNames(pipe.Shape, profile, onPlane(2, 0))
        self.assertEndProjects(pipe.Shape, point, onPlane(2, 30), kinds=("Vertex",))
        self.assertEqual(elementsWhere(pipe.Shape, "Edge", onPlane(2, 30)), [])

    def testPointProfile(self):
        """A point as the profile: the apex keeps the point's name; the end projects the last
        section."""
        point = self.sketch("Point", Part.Point(V(0, 0, 0)))
        section = self.square("Section", z=30)
        pipe = self.pipe(
            (point, ["Vertex1"]), self.line(), Transformation="Multisection", Sections=[section]
        )
        self.assertStartKeepsNames(pipe.Shape, point, onPlane(2, 0), kinds=("Vertex",))
        self.assertEqual(elementsWhere(pipe.Shape, "Edge", onPlane(2, 0)), [])
        self.assertEndProjects(pipe.Shape, section, onPlane(2, 30))

    def testClosedSpine(self):
        """A circle swept around a closed spine: the shell ends where it starts, and that edge
        keeps the profile's name (no projection)."""
        spine = self.sketch("Path", models.circle(0, 0, 20), placement=XZ)
        profile = self.sketch("Profile", models.circle(20, 0, 2))
        pipe = self.pipe(profile, spine)
        shape = pipe.Shape
        self.assertAlmostEqual(shape.Volume, 2 * math.pi * 20 * math.pi * 4, 2)
        self.assertStartKeepsNames(shape, profile, onPlane(2, 0), kinds=("Edge",))
        for index in range(1, len(shape.Edges) + 1):
            self.assertNotIn("PRJ", firstName(shape, f"Edge{index}"))

    def testSubtractivePipeEnd(self):
        """A blind SubtractivePipe 5 deep into a pad: the pocket's floor edges are the profile's
        projections, through the cut."""
        models.pad(self.body, self.square("Block", 10), 10)
        profile = self.square(z=10)
        pipe = self.pipe(profile, self.line(10, 5), kind="SubtractivePipe")
        self.assertAlmostEqual(pipe.Shape.Volume, 4000 - 80)
        floor = elementsWhere(pipe.Shape, "Edge", onPlane(2, 5))
        self.assertEqual(len(floor), 4)
        for element in floor:
            name = firstName(pipe.Shape, element)
            self.assertIn("PRJ", name, element)
            self.assertIn(f"{profile.ID}", name, element)
