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


def bendPoints(first, second, towards=False):
    """In an XZ sketch: up 30 from the square at z = 0, then 20 turned `first` degrees from +Z
    towards +X, then 20 turned `second` degrees more; drawn towards the profile if `towards`."""
    points = [(0.0, 0.0), (0.0, 30.0)]
    heading = 0.0
    for turn in (first, second):
        heading += turn
        x, z = points[-1]
        a = math.radians(heading)
        points.append((x + 20 * math.sin(a), z + 20 * math.cos(a)))
    return points[::-1] if towards else points


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

    def pipe(self, points, refine):
        profile = models.sketch(self.doc, "Profile", models.rectangle(-2, -2, 2, 2), self.body)
        path = models.sketch(self.doc, "Path", models.polyline(points), self.body, placement=XZ)
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = refine
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        return path, pipe

    def pointsOn(self, target, at):
        """A datum point on each edge and vertex of `target` lying wholly in the square at `at`"""
        points = []
        for kind in ("Edge", "Vertex"):
            for element in elementsWhere(target.Shape, kind, inSquareAt(at)):
                point = self.body.newObject("PartDesign::Point", "On" + element)
                point.AttachmentSupport = [(target, element)]
                point.MapMode = "Vertex" if kind == "Vertex" else "CenterOfMass"
                points.append(point)
        self.doc.recompute()
        self.assertEqual([p.Name for p in points if not p.isValid()], [])
        return points

    def assertGoneOrLoud(self, points, before, report):
        """Each point is invalid, warned, or where it was: none moved silently. With `report`
        False only the places count: a SubShapeBinder updates twice and its report is empty
        afterwards (ops#449)."""
        for point in points:
            if not point.isValid():
                continue
            levels = [e.get("warning_level") for e in App.getReferenceReport(point)]
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
