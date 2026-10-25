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

    def testMultisectionProfilePastTheMiddle(self):
        """Multisection along z = 0 -> 30, the profile (4x4) at z = 14 and a section (6x6) at
        z = 30, a fillet on the start edge the profile's g1 names; then the profile moves to
        z = 16, past the spine's middle: the start (z = 0) keeps the profile's names, the end
        (z = 30) the section's projections, and the fillet stays at z = 0. Both sections decide
        which end is which (fork PR 337 round 2): with the profile's distance alone, the ends
        swapped, and the fillet went to the section's cap, 30 mm away."""
        profile = self.square(z=14)
        section = self.square("Section", 3, z=30)
        pipe = self.pipe(profile, self.line(), Transformation="Multisection", Sections=[section])
        g1 = firstName(profile.Shape, "Edge1")
        edges = [
            f"Edge{index}"
            for index in range(1, len(pipe.Shape.Edges) + 1)
            if firstName(pipe.Shape, f"Edge{index}") == g1
        ]
        self.assertEqual(len(edges), 1, edges)
        self.assertIn(edges[0], elementsWhere(pipe.Shape, "Edge", onPlane(2, 0)))
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pipe, edges)
        fillet.Radius = 0.3
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())

        profile.Placement = App.Placement(V(0, 0, 16), App.Rotation())
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        starts = elementsWhere(pipe.Shape, "Edge", onPlane(2, 0))
        own = sorted(firstName(profile.Shape, f"Edge{index}") for index in range(1, 5))
        self.assertEqual(sorted(firstName(pipe.Shape, edge) for edge in starts), own)
        self.assertEndProjects(pipe.Shape, section, onPlane(2, 30))
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertIn(fillet.Base[1][0], starts)

    def testMultisectionLastSectionWithMoreVertices(self):
        """Multisection along z = 0 -> 30, the profile at z = 0 and a 6x6 square section at
        z = 12, with more vertices than the profile (a circle; a square with a round hole, whose
        hole wire decides alone), a fillet on an edge of the far cap; then the spine's end is
        extended to z = 60: the start (z = 0) keeps the profile's names, the far cap (z = 60) the
        section's projections, and the fillet follows to z = 60. Each section weighs the same
        (fork PR 337 round 3): with distances summed over a section's vertices, the square
        outweighed the profile, the ends swapped, and the fillet went to the profile's cap."""
        cases = {
            "circle": ([models.circle(0, 0, 2)], models.rectangle(-3, -3, 3, 3)),
            "holed": (
                models.rectangle(-2, -2, 2, 2) + [models.circle(0, 0, 1)],
                models.rectangle(-3, -3, 3, 3) + models.rectangle(-1, -1, 1, 1),
            ),
        }
        for number, (case, (profileGeometry, sectionGeometry)) in enumerate(cases.items()):
            if number:
                self.tearDown()
                self.setUp()
            with self.subTest(case):
                profile = self.sketch("Profile", profileGeometry)
                section = self.sketch("Section", sectionGeometry, z=12)
                path = self.line()
                pipe = self.pipe(profile, path, Transformation="Multisection", Sections=[section])
                # The section's side at y = -3, widened past it (the sweep grows beyond z = 12)
                farEdge = lambda z: lambda p: abs(p.z - z) < 1e-6 and p.y < -4
                edges = elementsWhere(pipe.Shape, "Edge", farEdge(30))[:1]
                self.assertEqual(len(edges), 1)
                fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
                fillet.Base = (pipe, edges)
                fillet.Radius = 0.3
                self.doc.recompute()
                self.assertTrue(fillet.isValid(), fillet.getStatusString())

                path.deleteAllGeometry()
                path.addGeometry(Part.LineSegment(V(0, 0, 0), V(0, 60, 0)))
                self.doc.recompute()
                self.assertTrue(pipe.isValid(), pipe.getStatusString())
                shape = pipe.Shape
                own = {
                    firstName(profile.Shape, f"Edge{i}")
                    for i in range(1, len(profile.Shape.Edges) + 1)
                }
                starts = elementsWhere(shape, "Edge", onPlane(2, 0))
                self.assertTrue(starts)
                for element in starts:
                    name = firstName(shape, element)
                    self.assertNotIn("PRJ", name, element)
                    self.assertIn(name.split("|")[0], own, (element, name))
                sectionNames = {
                    firstName(section.Shape, f"Edge{i}")
                    for i in range(1, len(section.Shape.Edges) + 1)
                }
                ends = elementsWhere(shape, "Edge", onPlane(2, 60))
                self.assertTrue(ends)
                for element in ends:
                    last = lastSection(shape, element)
                    self.assertIn("PRJ", last["mapperFlags"], (element, firstName(shape, element)))
                    self.assertLessEqual(set(last["linkedNames"]), sectionNames, element)
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                self.assertIn(fillet.Base[1][0], elementsWhere(shape, "Edge", farEdge(60)))

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


def bendPoints(first, second, towards=False, *more):
    """In an XZ sketch: up 30 from the square at z = 0, then 20 turned `first` degrees from +Z
    towards +X, then 20 turned `second` degrees more (and 20 more per turn in `more`); drawn
    towards the profile if `towards`."""
    points = [(0.0, 0.0), (0.0, 30.0)]
    heading = 0.0
    for turn in (first, second) + more:
        heading += turn
        x, z = points[-1]
        a = math.radians(heading)
        points.append((x + 20 * math.sin(a), z + 20 * math.cos(a)))
    return points[::-1] if towards else points


def near(at, radius):
    """Whether a point lies within `radius` of `at`."""
    return lambda p: (p - at).Length < radius


def inSquareAt(at):
    """Whether a point lies in the square's copy at the spine vertex `at` ("Transformed" only
    translates the profile)."""
    return lambda p: abs(p.z - at.z) < 1e-6 and abs(p.x - at.x) < 2 + 1e-6 and abs(p.y) < 2 + 1e-6


class TestJointsWhenABendStraightens(unittest.TestCase):
    """A refined "Transformed" pipe along a U (ops#446): the joint edges and vertices at a bend
    are named after the side faces they lie on (UPP). When the bend is made straight, refine
    merges the two legs' faces into one that keeps both names, and the joint is gone. The other
    bend's joint shares one of those faces, and its sources: tier 1 took it, 20 mm away and
    silently. Each reference at the straightened bend now goes missing, warns, or stays where it
    was, and is in its place again once the bend is turned back. The same with the pipe
    unrefined and a refined feature after it (Fillet, SubShapeBinder)."""

    def setUp(self):
        self.doc = models.newDocument("PartDesignTestPipeBends")
        self.doc.HistoryAlgorithm = "V2"
        self.doc.InternNames = False
        self.body = models.body(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def setPath(self, path, points):
        path.deleteAllGeometry()
        path.addGeometry(models.polyline(points))
        self.doc.recompute()

    def pipe(self, points, refine, transition="Transformed", circular=False):
        """A pipe of the square, or of a circle of radius 2 if `circular`, along the points"""
        geometry = [models.circle(0, 0, 2)] if circular else models.rectangle(-2, -2, 2, 2)
        profile = models.sketch(self.doc, "Profile", geometry, self.body)
        path = models.sketch(self.doc, "Path", models.polyline(points), self.body, placement=XZ)
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transition = transition
        pipe.Refine = refine
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        return path, pipe

    def pointsOn(self, target, at, where=None, kinds=("Edge", "Vertex")):
        """A datum point on each edge and vertex of `target` lying wholly in the square at `at`,
        or where `where` holds"""
        points = []
        for kind in kinds:
            for element in elementsWhere(target.Shape, kind, where or inSquareAt(at)):
                point = self.body.newObject("PartDesign::Point", "On" + element)
                point.AttachmentSupport = [(target, element)]
                point.MapMode = "Vertex" if kind == "Vertex" else "CenterOfMass"
                points.append(point)
        self.doc.recompute()
        self.assertEqual([p.Name for p in points if not p.isValid()], [])
        return points

    def assertGoneOrLoud(self, points, before, report, solved=False):
        """Each point is invalid, warned, or at its place in `before` (where it was, unless the
        pipe moved it): none is elsewhere silently. With `report`
        False only the places count: a SubShapeBinder updates twice and its report is empty
        afterwards (ops#449). With `solved`, only the points the solver re-bound count (a report
        entry): an exact name may move with its element (ops#455)."""
        for point in points:
            if not point.isValid():
                continue
            levels = [e.get("warning_level") for e in App.getReferenceReport(point)]
            if solved and not levels:
                continue
            if report and "normal" in levels:
                continue
            moved = (point.Placement.Base - before[point.Name]).Length
            self.assertLess(moved, 1e-6, (point.Name, point.AttachmentSupport, levels))

    def assertBackInPlace(self, points, before):
        for point in points:
            self.assertTrue(point.isValid(), (point.Name, point.getStatusString()))
            moved = (point.Placement.Base - before[point.Name]).Length
            self.assertLess(moved, 1e-6, (point.Name, point.AttachmentSupport))

    def straighten(self, downstream=None):
        """For each bend and spine direction: the U at 40 and 20 degrees, the points on that
        bend's joint (on the pipe, or on the refined feature after an unrefined pipe), the bend
        made straight, then turned back."""
        for bend, straight in ((1, (0, 20)), (2, (40, 0))):
            for towards in (False, True):
                with self.subTest(bend=bend, towards=towards):
                    self.tearDown()
                    self.setUp()
                    points = bendPoints(40, 20, towards)
                    path, pipe = self.pipe(points, refine=downstream is None)
                    target = pipe
                    if downstream == "Fillet":
                        # the start cap's y = +2 edge, away from both bends
                        (edge,) = elementsWhere(
                            pipe.Shape, "Edge", lambda p: abs(p.z) < 1e-6 and abs(p.y - 2) < 1e-6
                        )
                        target = self.body.newObject("PartDesign::Fillet", "Fillet")
                        target.Base = (pipe, [edge])
                        target.Radius = 0.5
                        target.Refine = True
                    elif downstream == "Binder":
                        target = self.body.newObject("PartDesign::SubShapeBinder", "Binder")
                        target.Support = [(pipe, "")]
                        target.Refine = True
                    self.doc.recompute()
                    x, z = (points[::-1] if towards else points)[bend]
                    joint = self.pointsOn(target, V(x, 0, z))
                    # refined: the y = +-2 sides are one face each, so the joint is the two
                    # edges at x = +-2 and the four vertices
                    self.assertEqual(len(joint), 6, [p.Name for p in joint])
                    before = {p.Name: V(p.Placement.Base) for p in joint}
                    self.setPath(path, bendPoints(*straight, towards))
                    self.assertGoneOrLoud(joint, before, report=downstream != "Binder")
                    self.setPath(path, points)
                    self.assertBackInPlace(joint, before)

    def testJointOfARefinedPipe(self):
        self.straighten()

    def testJointOfARefinedFilletAfterThePipe(self):
        self.straighten("Fillet")

    def testJointOfARefinedBinderOfThePipe(self):
        self.straighten("Binder")

    def holeAcrossTheJoint(self, redraw=False):
        """For each bend and spine direction: the refined pipe along the U and a refined Pocket
        (through all, midplane) of a circle of radius 0.5 centred on that bend's joint edges
        (ops#454), the points on the Pocket's edges and vertices at the joint; the bend made
        straight, then turned back. With `redraw`, the hole's circle is deleted and drawn again
        at the same place instead."""
        for bend, straight in ((1, (0, 20)), (2, (40, 0))):
            for towards in (False, True):
                with self.subTest(bend=bend, towards=towards):
                    self.tearDown()
                    self.setUp()
                    points = bendPoints(40, 20, towards)
                    path, pipe = self.pipe(points, refine=True)
                    x, z = (points[::-1] if towards else points)[bend]
                    # sketch x -> world y, sketch y -> world z, the sketch plane at world x = x
                    hole = models.sketch(
                        self.doc,
                        "Hole",
                        models.circle(0, z, 0.5),
                        self.body,
                        placement=App.Placement(V(x, 0, 0), App.Rotation(V(1, 1, 1), 120)),
                    )
                    pocket = self.body.newObject("PartDesign::Pocket", "Pocket")
                    pocket.Profile = hole
                    pocket.Type = 1  # through all
                    pocket.Midplane = True
                    pocket.Refine = True
                    self.doc.recompute()
                    self.assertTrue(pocket.isValid(), pocket.getStatusString())
                    joint = self.pointsOn(pocket, V(x, 0, z))
                    # the joint edges' four pieces beside the hole and the hole's seam; the
                    # four corners, and the hole's and the seam's vertices on the joint edges
                    self.assertEqual(len(joint), 13, [p.Name for p in joint])
                    before = {p.Name: V(p.Placement.Base) for p in joint}
                    if redraw:
                        hole.deleteAllGeometry()
                        hole.addGeometry(models.circle(0, z, 0.5), False)
                        self.doc.recompute()
                        self.assertBackInPlace(joint, before)
                        continue
                    self.setPath(path, bendPoints(*straight, towards))
                    self.assertGoneOrLoud(joint, before, report=True)
                    self.setPath(path, points)
                    self.assertBackInPlace(joint, before)

    def testHoleAcrossTheJointOfARefinedPipe(self):
        """The hole's vertices on a joint edge are named after the joint edge (a GEN section
        linking its UPP name). When the bend is made straight the joint is gone, and the seam
        vertex on the merged face shares most of their ancestry: tier 1 took it, 1 mm away and
        silently. Now they go missing or warn."""
        self.holeAcrossTheJoint()

    def testHoleAcrossTheJointStaysWhenItsCircleIsRedrawn(self):
        """The control: the hole's circle drawn again renames the cylinder and its seam, but the
        joint is there. Every point stays valid and in place."""
        self.holeAcrossTheJoint(redraw=True)

    def straightenNear(
        self, transition="Transformed", circular=False, fillet=False, count=None, solved=False
    ):
        """As straighten(), for the points on the edges and vertices lying wholly within 3 mm of
        the bend's spine vertex (fork PR 361 round 2): a Round corner's round face and the
        joints at both of its ends, or a round profile's joint circle and its seam vertex. With
        `fillet`, the pipe is unrefined and a refined Fillet of the start cap's circle is the
        target."""
        for bend, straight in ((1, (0, 20)), (2, (40, 0))):
            for towards in (False, True):
                with self.subTest(bend=bend, towards=towards):
                    self.tearDown()
                    self.setUp()
                    points = bendPoints(40, 20, towards)
                    path, pipe = self.pipe(points, not fillet, transition, circular)
                    target = pipe
                    if fillet:
                        (edge,) = elementsWhere(pipe.Shape, "Edge", lambda p: abs(p.z) < 1e-6)
                        target = self.body.newObject("PartDesign::Fillet", "Fillet")
                        target.Base = (pipe, [edge])
                        target.Radius = 0.3
                        target.Refine = True
                        self.doc.recompute()
                    x, z = (points[::-1] if towards else points)[bend]
                    joint = self.pointsOn(target, None, near(V(x, 0, z), 3))
                    if count is not None:
                        self.assertEqual(len(joint), count, [p.Name for p in joint])
                    else:
                        self.assertGreater(len(joint), 4, [p.Name for p in joint])
                    before = {p.Name: V(p.Placement.Base) for p in joint}
                    self.setPath(path, bendPoints(*straight, towards))
                    self.assertGoneOrLoud(joint, before, report=True, solved=solved)
                    self.setPath(path, points)
                    self.assertBackInPlace(joint, before)

    def testRoundCornerOfARefinedPipe(self):
        """Round corner: the round face's counter name passes to the other bend's round face
        when a bend is made straight. Its vertices then lie on faces that hold the old ones'
        names, beside one that doesn't: tier 1 must not take one of them, 20 mm away. Only the
        references the solver re-binds count: the round face's edges and vertices are named
        after the counter, and the other bend's can take their names exactly (ops#455)."""
        self.straightenNear("Round corner", solved=True)

    def testJointOfARefinedRoundPipe(self):
        """A round profile: the legs' cylinders merge into one that keeps one leg's name only.
        The joint circle and its seam vertex (count 2) go missing or warn."""
        self.straightenNear(circular=True, count=2)

    def testJointOfARefinedFilletAfterARoundPipe(self):
        self.straightenNear(circular=True, fillet=True, count=2)

    def testEndOfADroppedLegComesBack(self):
        """A refined Round corner pipe along four legs, the last one dropped and put back. Where
        the second bend's round face ends, at the third leg's start, two vertices stay where they
        are, though the round faces' counter names shift with the edit and back: points on them
        stay where they are, and are valid and there once the leg is back (fork PR 361 round 2;
        the last bend's own vertices: testLastJointOfADroppedLegStaysInPlace)."""
        points = bendPoints(40, 20, False, 30)
        path, pipe = self.pipe(points, True, "Round corner")
        start = V(points[2][0], 0, points[2][1])
        leg = V(points[3][0], 0, points[3][1]) - start
        leg.normalize()
        corners = self.pointsOn(
            pipe,
            None,
            lambda p: abs((p - start).dot(leg)) < 1e-6 and (p - start).Length < 3,
            kinds=("Vertex",),
        )
        self.assertEqual(len(corners), 2, [p.Name for p in corners])
        before = {p.Name: V(p.Placement.Base) for p in corners}
        self.setPath(path, points[:-1])
        self.assertGoneOrLoud(corners, before, report=True)
        self.setPath(path, points)
        self.assertBackInPlace(corners, before)

    def testLastJointOfADroppedLegStaysInPlace(self):
        """A refined "Transformed" pipe along four legs, the last one dropped and put back
        (ops#452). The last bend's joint vertices are named after the third and fourth legs'
        side faces; without the fourth leg they are the end cap's, in the same place. The fourth
        leg's faces are gone, and tier 1 took the previous bend's joint vertices (they share the
        third leg's faces), 20 mm away and silently. Now they stay where they are, warned at the
        same-place level, and are exact again once the leg is back. Drawn towards the profile,
        the dropped leg is the first: they break, and are back once the leg is."""
        for towards in (False, True):
            with self.subTest(towards=towards):
                self.tearDown()
                self.setUp()
                points = bendPoints(40, 20, towards, 30)
                path, pipe = self.pipe(points, True)
                x, z = bendPoints(40, 20, False, 30)[3]
                joint = self.pointsOn(pipe, V(x, 0, z), kinds=("Vertex",))
                self.assertEqual(len(joint), 4, [p.Name for p in joint])
                before = {p.Name: V(p.Placement.Base) for p in joint}
                self.setPath(path, points[1:] if towards else points[:-1])
                if not towards:
                    for point in joint:
                        levels = [e.get("warning_level") for e in App.getReferenceReport(point)]
                        self.assertTrue(point.isValid(), (point.Name, point.getStatusString()))
                        self.assertEqual(levels, ["same-place"], point.Name)
                self.assertGoneOrLoud(joint, before, report=True)
                self.setPath(path, points)
                self.assertBackInPlace(joint, before)
                self.assertEqual([p.Name for p in joint if App.getReferenceReport(p)], [])

    def testOtherRoundCornerOfARefinedPipe(self):
        """A refined Round corner pipe, one bend made straight: points on the other bend's
        round-face vertices (fork PR 361 round 3). The round faces' counter names shift with the
        edit, so a name can't tell the other bend's vertex from the straightened one's: when one
        of the old element's faces is held by no face, the merged-neighbour test empties tier 1,
        and a vertex that would have followed breaks. Each point is invalid, warned, or at its
        place moved with the pipe (the legs after the straightened joint turn about it), never
        elsewhere silently; after the turn back none is elsewhere silently, and the broken ones
        are valid and in place. Only the references the solver re-binds count after the edit
        (ops#455). Along the U, the vertices that break went to a neighbour 0.7 mm off before;
        along the S (bends 40 and -40), bend 2's round-end vertices followed correctly and break
        now. This pins the breaks: names that stay with their bend (ops#455) are to turn them
        into follows."""
        for turns in ((40, 20), (40, -40)):
            for bend in (1, 2):
                straight = (0, turns[1]) if bend == 1 else (turns[0], 0)
                for towards in (False, True):
                    with self.subTest(turns=turns, bend=bend, towards=towards):
                        self.straightenOther(turns, bend, straight, towards)

    def straightenOther(self, turns, bend, straight, towards):
        """One subtest of testOtherRoundCornerOfARefinedPipe: the pipe along `turns`, `bend`
        made `straight`, the points on the other bend's round-face vertices"""
        self.tearDown()
        self.setUp()
        points = bendPoints(*turns, towards)
        path, pipe = self.pipe(points, True, "Round corner")
        spine = bendPoints(*turns)
        other = 3 - bend
        x, z = spine[other]
        corner = self.pointsOn(pipe, None, near(V(x, 0, z), 3), kinds=("Vertex",))
        self.assertEqual(len(corner), 6, [p.Name for p in corner])
        before = {p.Name: V(p.Placement.Base) for p in corner}
        x, z = spine[bend]
        joint = V(x, 0, z)
        turn = App.Rotation(V(0, 1, 0), straight[bend - 1] - turns[bend - 1])
        moved = {
            name: joint + turn.multVec(at - joint) if other > bend else at
            for name, at in before.items()
        }
        self.setPath(path, bendPoints(*straight, towards))
        broken = [p for p in corner if not p.isValid()]
        self.assertGoneOrLoud(corner, moved, report=True, solved=True)
        self.setPath(path, points)
        self.assertGoneOrLoud(corner, before, report=True)
        self.assertBackInPlace(broken, before)


class TestBaseAfterAnInvalidPipe(unittest.TestCase):
    """FreeCAD-CH ops#310 (fix C1): a feature's boolean skips checking its base only when the base
    feature's own boolean ran with every input valid. A Pipe with the "Transformed" transition along
    an L path makes an invalid solid at the corner (ops#370); the next feature's boolean must still
    check that base and repair it, also when the Pipe is fused onto a Pad (its sweep was invalid) and
    when a suppressed feature sits in between (it passes the Pipe's result through).

    Designed model (PipeStartCapEdgeCutAway's): a 4x4 profile along (0,0)-(0,30)-(20,30) in XZ, a
    reversed 8 mm Pocket of a 2x2 square at the origin, then the square grown to 10x10. The expected
    result is the Part cut of the Pocket's base by its tool, which checks and repairs every input:
    a valid solid of that volume."""

    XZ = App.Placement(App.Vector(0, 0, 0), App.Rotation(App.Vector(1, 0, 0), 90))

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestBaseAfterAnInvalidPipe")

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def build(self, pad=None, between=None):
        """pad: (z, height) of a 20x20 Pad before the Pipe; between: "Pad" or "Pocket", a feature
        between the Pipe and the Pocket, suppressed after the first recompute"""
        doc = self.Doc
        body = models.body(doc)
        if pad:
            z, height = pad
            first = models.sketch(doc, "FirstSketch", models.rectangle(-10, -10, 10, 10), body, z=z)
            models.pad(body, first, height, name="First")
        path = models.sketch(doc, "Path", models.polyline([(0, 0), (0, 30), (20, 30)]), body, placement=self.XZ)
        profile = models.sketch(doc, "Profile", models.rectangle(-2, -2, 2, 2), body)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        base = pipe
        if between:
            sketch = models.sketch(doc, "BetweenSketch", models.rectangle(10, 10, 12, 12), body)
            make = models.pad if between == "Pad" else models.pocket
            base = make(body, sketch, 1, name="Between")
        top = pad[0] + pad[1] if pad else 0
        self.recess = models.sketch(doc, "Recess", models.rectangle(-1, -1, 1, 1), body, z=top)
        self.pocket = models.pocket(body, self.recess, 8)
        self.pocket.Reversed = True
        doc.recompute()
        if between:
            base.Suppressed = True
            doc.recompute()
        self.base = base
        return pipe

    def assertCheckedCut(self, state):
        pocket = self.pocket
        # AddSubShape is in the feature's own coordinates: the Pocket's Placement is the first
        # Pad's sketch placement when a Pad comes first
        tool = pocket.AddSubShape.copy()
        tool.Placement = pocket.Placement.multiply(tool.Placement)
        expected = self.base.Shape.cut(tool)
        self.assertTrue(expected.isValid(), state)
        self.assertTrue(pocket.isValid(), (state, pocket.getStatusString()))
        self.assertTrue(pocket.Shape.isValid(), state)
        self.assertAlmostEqual(pocket.Shape.Volume, expected.Volume, places=4, msg=state)

    def requireInvalid(self, feature):
        """The model's premise (ops#370). OCCT's sweep differs by platform: on macOS the Pipe comes
        out valid, and these tests have no invalid base to test. TestBaseAfterAnInvalidBaseFeature
        covers the suppressed feature in between with a base built invalid on purpose."""
        if feature.Shape.isValid():
            self.skipTest("the Transformed-transition Pipe is valid on this platform (ops#370)")

    def checkBeforeAndAfterTheEdit(self):
        self.assertCheckedCut("first recompute")
        models.moveRectangle(self.recess, -5, -5, 5, 5)
        self.Doc.recompute()
        self.assertCheckedCut("after the edit")

    def testPocketOnTheFirstPipe(self):
        pipe = self.build()
        self.requireInvalid(pipe)
        self.checkBeforeAndAfterTheEdit()

    def testPocketOnAPipeFusedOntoAPad(self):
        for pad in ((-5, 3), (-5, 7)):  # disjoint from the Pipe's solid, overlapping it
            with self.subTest(pad=pad):
                self.tearDown()
                self.setUp()
                pipe = self.build(pad=pad)
                self.requireInvalid(pipe)
                self.checkBeforeAndAfterTheEdit()

    def testSuppressedFeatureBetween(self):
        for between in ("Pad", "Pocket"):
            with self.subTest(between=between):
                self.tearDown()
                self.setUp()
                self.build(between=between)
                self.requireInvalid(self.base)  # the Pipe's result, passed through
                self.checkBeforeAndAfterTheEdit()


class TestBaseAfterAnInvalidBaseFeature(unittest.TestCase):
    """FreeCAD-CH ops#310 (fix C1), the same on every platform: a feature's boolean skips checking
    its base only when the base feature's own boolean ran with every input valid. A suppressed
    feature passes its base through without a boolean of its own, so the next feature must still
    check that base and repair it.

    Designed model: the Body's BaseFeature is a 20x20x10 box whose top face is reversed in its shell,
    built that way on purpose (invalid: the shell can't be oriented; fix() repairs it). Then a 2x2
    Pad or Pocket at (5, 5) on the top, suppressed after the first recompute, and a 5 mm Pocket of
    a 2x2 square at the top's centre, then the square grown to 6x6. Unrepaired, the Pocket cuts
    nothing. The expected result is the Part cut of the Pocket's base by its tool, which checks
    and repairs every input."""

    assertCheckedCut = TestBaseAfterAnInvalidPipe.assertCheckedCut

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestBaseAfterAnInvalidBaseFeature")

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    @staticmethod
    def invalidBox():
        faces = list(Part.makeBox(20, 20, 10, App.Vector(-10, -10, 0)).Faces)
        faces[5] = faces[5].reversed()  # the top face (z = 10)
        return Part.Solid(Part.Shell(faces))

    def build(self, between=None):
        doc = self.Doc
        raw = doc.addObject("Part::Feature", "Raw")
        raw.Shape = self.invalidBox()
        body = models.body(doc)
        body.BaseFeature = raw
        base = body.Group[0]
        if between:
            sketch = models.sketch(doc, "BetweenSketch", models.rectangle(5, 5, 7, 7), body, z=10)
            make = models.pad if between == "Pad" else models.pocket
            base = make(body, sketch, 1, name="Between")
        self.recess = models.sketch(doc, "Recess", models.rectangle(-1, -1, 1, 1), body, z=10)
        self.pocket = models.pocket(body, self.recess, 5)
        doc.recompute()
        if between:
            base.Suppressed = True
            doc.recompute()
        self.base = base

    def checkBeforeAndAfterTheEdit(self):
        self.assertFalse(self.base.Shape.isValid())  # the model's premise, by construction
        self.assertCheckedCut("first recompute")
        models.moveRectangle(self.recess, -3, -3, 3, 3)
        self.Doc.recompute()
        self.assertCheckedCut("after the edit")

    def testPocketOnTheBaseFeature(self):
        self.build()
        self.checkBeforeAndAfterTheEdit()

    def testSuppressedFeatureBetween(self):
        for between in ("Pad", "Pocket"):
            with self.subTest(between=between):
                self.tearDown()
                self.setUp()
                self.build(between=between)
                self.checkBeforeAndAfterTheEdit()
