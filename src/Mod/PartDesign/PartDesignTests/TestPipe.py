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
import os
import re
import tempfile
import time
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


def turned(z, degrees, length):
    """In an XZ sketch: the end of a leg of `length` from (0, z), turned `degrees` from +Z
    towards +X."""
    return (length * math.sin(math.radians(degrees)), z + length * math.cos(math.radians(degrees)))


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

    def testLegNamesCarryTheSpineEdge(self):
        """The square along an L path: each side face and lateral edge is named from its spine
        edge too, so the two legs' faces of one profile edge differ only in the spine's line
        (ops#415). Named from the profile alone, they were told apart by the legs' order, and a
        segment added at the spine's start moved every reference to another leg silently
        (TestNamingScenarios' PipeLegs area)."""
        path = self.lPath()
        profile = self.square()
        # Refine off: it merges the legs' coplanar faces y = +-2
        shape = self.pipe(profile, path, Transition="Right corner", Refine=False).Shape
        # the spine's lines' names, as a source's appear inside a name (`;` escaped)
        spine = [firstName(path.Shape, f"Edge{index}").replace(";", "^;") for index in (1, 2)]
        # a source's name holds its owner's tag (the sketch's ID)
        tag = "^;_^;%d^;" % path.ID

        def leg(element):
            # the first leg runs along Z, x -2..2 and z below 28; the second along X, x past 2
            at = place(element)
            return 0 if at.x < 2 + 1e-6 and at.z < 28 - 1e-6 else 1 if at.x > 2 + 1e-6 else None

        for kind, count in (("Face", 8), ("Edge", 8)):
            sides = {}
            for index, element in enumerate(elementsOf(shape, kind), 1):
                if kind == "Edge" and not element.Curve.Direction.cross(
                    V(0, 0, 1) if leg(element) == 0 else V(1, 0, 0)
                ).Length < 1e-9:
                    continue  # not a lateral edge
                at = place(element)
                if leg(element) is None or (
                    kind == "Face" and (abs(at.z) < 1e-6 or abs(at.x - 20) < 1e-6)
                ):
                    continue  # a cap, or at the corner
                sides.setdefault(leg(element), []).append(f"{kind}{index}")
            self.assertEqual(sorted(len(v) for v in sides.values()), [count // 2] * 2, sides)
            for legIndex, elements in sides.items():
                for element in elements:
                    name = firstName(shape, element)
                    self.assertIn(tag, name, (element, name))
                    self.assertIn(spine[legIndex], name, (element, name))
            # leg B's names are leg A's with the spine's line changed (the sources sorted as
            # text, so their order may differ)
            def legless(element, line):
                name = firstName(shape, element).replace(line, "<leg>")
                found = re.match(r"(_;)(.*?)(;\d+;PSH;.*)", name)
                self.assertTrue(found, name)
                return found[1] + ",".join(sorted(found[2].split(","))) + found[3]

            self.assertEqual(
                {legless(e, spine[0]) for e in sides[0]},
                {legless(e, spine[1]) for e in sides[1]},
                kind,
            )
        self.assertNamesDistinct(shape)

    def testTransitionsAndModes(self):
        """The same names under each transition and in Frenet mode, on the pipe's own solid
        (AddSubShape). "Transformed" fails at this right angle (ops#370, TestPipeCorners); at 60
        degrees it shears the second leg, whose end isn't where the profile's would be: its end
        is found by name."""
        cases = [
            {"Transition": "Right corner"},
            {"Transition": "Round corner"},
            {"Transition": "Right corner", "Mode": "Frenet"},
        ]
        for properties in cases:
            with self.subTest(**properties):
                pipe = self.pipe(self.square(), self.lPath(), **properties)
                profile = pipe.Profile[0]
                self.assertStartKeepsNames(pipe.AddSubShape, profile, onPlane(2, 0))
                self.assertEndProjects(pipe.AddSubShape, profile, onPlane(0, 20))
        self.tearDown()
        self.setUp()
        path = self.sketch("Path", models.polyline([(0, 0), (0, 30), turned(30, 60, 20)]), placement=XZ)
        pipe = self.pipe(self.square(), path, Transition="Transformed", Refine=False)
        self.assertStartKeepsNames(pipe.AddSubShape, pipe.Profile[0], onPlane(2, 0))
        self.assertEndProjects(pipe.AddSubShape, pipe.Profile[0], None)

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
        swapped, and the fillet went to the section's cap, 30 mm away. The same with the end
        stored at creation (ops#379), and with nothing stored before the edit (a file saved
        before ops#379), where the sections decide."""
        for stored in (True, False):
            if not stored:
                self.tearDown()
                self.setUp()
            with self.subTest(stored=stored):
                profile = self.square(z=14)
                section = self.square("Section", 3, z=30)
                pipe = self.pipe(
                    profile, self.line(), Transformation="Multisection", Sections=[section]
                )
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

                if not stored:
                    pipe.SpineEnds = []
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
        z = 12, with more vertices than the profile (a circle; a square with a round hole), a
        fillet on an edge of the far cap; then the spine's end is extended to z = 60: the start
        (z = 0) keeps the profile's names, the far cap (z = 60) the section's projections, and
        the fillet follows to z = 60. Each section weighs the same
        (fork PR 337 round 3): with distances summed over a section's vertices, the square
        outweighed the profile, the ends swapped, and the fillet went to the profile's cap.
        The same with the end stored at creation (ops#379), and with nothing stored before the
        edit (a file saved before ops#379), where the sections decide."""
        cases = {
            "circle": ([models.circle(0, 0, 2)], models.rectangle(-3, -3, 3, 3)),
            "holed": (
                models.rectangle(-2, -2, 2, 2) + [models.circle(0, 0, 1)],
                models.rectangle(-3, -3, 3, 3) + models.rectangle(-1, -1, 1, 1),
            ),
        }
        runs = [(case, stored) for case in cases for stored in (True, False)]
        for number, (case, stored) in enumerate(runs):
            profileGeometry, sectionGeometry = cases[case]
            if number:
                self.tearDown()
                self.setUp()
            with self.subTest(case, stored=stored):
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

                if not stored:
                    pipe.SpineEnds = []
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

    # ops#379: which end carries the profile's names is remembered. The model: a 4x4 square at
    # height z (a 2x2 hole with `hole`), swept along a line on the Z axis, a fillet on the cap
    # edge the profile's first edge names and a sketch attached to the cap face that holds it.
    # Before, every recompute chose the end nearest the profile, so an edit that crossed the
    # spine's middle, or brought the profile or the far end to the other end, moved the names
    # and the fillet and the sketch with them, valid and silent.

    def endModel(self, start, end, z=0, hole=False, points=None, **properties):
        """The model, its spine a line from `start` to `end`, or a polyline through `points` in
        the XZ plane."""
        geometry = models.rectangle(-2, -2, 2, 2)
        if hole:
            geometry += models.rectangle(-1, -1, 1, 1)
        profile = self.sketch("Profile", geometry, z=z)
        if points:
            path = self.sketch("Path", models.polyline(points), placement=XZ)
        else:
            path = self.line(start, end)
        pipe = self.pipe(profile, path, **properties)
        g1 = firstName(profile.Shape, "Edge1")
        edges = [
            f"Edge{index}"
            for index in range(1, len(pipe.Shape.Edges) + 1)
            if firstName(pipe.Shape, f"Edge{index}") == g1
        ]
        self.assertEqual(len(edges), 1, edges)
        capZ = pipe.Shape.getElement(edges[0]).CenterOfMass.z
        caps = [
            f"Face{index}"
            for index, face in enumerate(pipe.Shape.Faces, 1)
            if abs(face.CenterOfMass.z - capZ) < 1e-6 and abs(abs(face.normalAt(0, 0).z) - 1) < 1e-9
        ]
        self.assertEqual(len(caps), 1, caps)
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pipe, edges)
        fillet.Radius = 0.3
        onCap = self.body.newObject("Sketcher::SketchObject", "OnCap")
        onCap.AttachmentSupport = [(pipe, caps[0])]
        onCap.MapMode = "FlatFace"
        onCap.addGeometry(models.circle(0, 0, 0.5), False)
        self.body.Tip = fillet
        self.doc.recompute()
        return profile, path, pipe, fillet, onCap

    def setLine(self, path, start, end):
        path.deleteAllGeometry()
        path.addGeometry(Part.LineSegment(V(0, start, 0), V(0, end, 0)))
        self.doc.recompute()

    def setPolyline(self, path, points):
        path.deleteAllGeometry()
        path.addGeometry(models.polyline(points))
        self.doc.recompute()

    def movePolyline(self, path, points):
        """Moves the ends of `path`'s lines to `points`, as dragging them does: each line keeps
        its geometry id, which a Pipe's legs are named from (ops#415)."""
        for geo, (start, end) in enumerate(zip(points, points[1:])):
            path.moveGeometry(geo, 1, V(*start, 0))
            path.moveGeometry(geo, 2, V(*end, 0))
        self.doc.recompute()

    def moveProfile(self, profile, z):
        profile.Placement = App.Placement(V(0, 0, z), App.Rotation())
        self.doc.recompute()

    def assertNamesAt(self, model, z, other):
        """Each edge of the profile names a cap edge at height `z` (the sketch's own name) and
        one at `other` (its projection, PRJ); the fillet's edge and the attached sketch lie at
        `z`."""
        profile, _, pipe, fillet, onCap = model
        for obj in (pipe, fillet, onCap):
            self.assertTrue(obj.isValid(), (obj.Name, obj.getStatusString()))
        shape = pipe.Shape
        edges = [f"Edge{index}" for index in range(1, len(shape.Edges) + 1)]
        for index in range(1, len(profile.Shape.Edges) + 1):
            name = firstName(profile.Shape, f"Edge{index}")
            own = [edge for edge in edges if firstName(shape, edge) == name]
            projected = [
                edge
                for edge in edges
                if "PRJ" in lastSection(shape, edge)["mapperFlags"]
                and name in lastSection(shape, edge)["linkedNames"]
            ]
            self.assertEqual(len(own), 1, (name, own))
            self.assertEqual(len(projected), 1, (name, projected))
            self.assertAlmostEqual(shape.getElement(own[0]).CenterOfMass.z, z, 6, name)
            self.assertAlmostEqual(shape.getElement(projected[0]).CenterOfMass.z, other, 6, name)
        self.assertEqual(len(fillet.Base[1]), 1, fillet.Base[1])
        self.assertAlmostEqual(shape.getElement(fillet.Base[1][0]).CenterOfMass.z, z, 6)
        self.assertAlmostEqual(onCap.Placement.Base.z, z, 6)

    def assertPointsAt(self, points, expected):
        self.assertEqual(len(points), len(expected), points)
        for point, at in zip(points, expected):
            self.assertTrue(point.isEqual(V(*at), 1e-9), (point, at))

    def reopen(self, *names):
        path = os.path.join(tempfile.mkdtemp(), "PipeEnds.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.body = self.doc.getObject("Body")
        return tuple(self.doc.getObject(name) for name in names)

    def testEndStaysWhenTheProfileCrossesTheMiddle(self):
        """The profile at z = 0, the spine 15 -> -15 (a tie: the start), then 16 -> -15: the
        names stay at the start (z = 16). Before, they went to z = -15."""
        model = self.endModel(15, -15)
        self.assertNamesAt(model, 15, -15)
        self.setLine(model[1], 16, -15)
        self.assertNamesAt(model, 16, -15)

    def testEndStaysWhenTheProfileSketchMoves(self):
        """The spine 0 -> 30, the profile at z = 14, moved to z = 16 (past the middle), then to
        z = 30 (the far end; the solid is the same): the names stay at z = 0, and the z = 30 cap
        keeps the projections. Before, they went to z = 30."""
        model = self.endModel(0, 30, z=14)
        self.assertNamesAt(model, 0, 30)
        self.moveProfile(model[0], 16)
        self.assertNamesAt(model, 0, 30)
        self.moveProfile(model[0], 30)
        self.assertNamesAt(model, 0, 30)

    def testEndStaysWhenTheFarEndIsShortenedToTheProfile(self):
        """The profile at z = 0, the spine 30 -> -40, then shortened to 30 -> 0: the names stay
        on the unchanged cap at z = 30, and the cap at the profile (z = 0) has the projections.
        Before, they went to z = 0."""
        model = self.endModel(30, -40)
        self.assertNamesAt(model, 30, -40)
        self.setLine(model[1], 30, 0)
        self.assertNamesAt(model, 30, 0)

    def testEndStaysWhenTheSpineIsExtendedFarPastTheProfile(self):
        """The profile at z = 0, the spine drawn towards it (30 -> 0), then extended past it to
        -10 and on to -40: the names follow the extended end, to z = -10 and z = -40. Before, the
        second extension took them to z = 30."""
        model = self.endModel(30, 0)
        self.assertNamesAt(model, 0, 30)
        self.setLine(model[1], 30, -10)
        self.assertNamesAt(model, -10, 30)
        self.setLine(model[1], 30, -40)
        self.assertNamesAt(model, -40, 30)

    def testEndFollowsAReversedSpine(self):
        """A spine redrawn the other way keeps the names where they were: 0 -> 30 redrawn
        30 -> 0 (the profile at z = 0, an end), and 10 -> -30 redrawn -30 -> 10 (the profile
        inside the spine)."""
        model = self.endModel(0, 30)
        self.setLine(model[1], 30, 0)
        self.assertNamesAt(model, 0, 30)
        self.tearDown()
        self.setUp()
        model = self.endModel(10, -30)
        self.assertNamesAt(model, 10, -30)
        self.setLine(model[1], -30, 10)
        self.assertNamesAt(model, 10, -30)

    def testHoledProfileDecidesOnce(self):
        """testEndStaysWhenTheProfileCrossesTheMiddle with a 2x2 hole: the hole's names stay with
        the outer wire's, at z = 16."""
        model = self.endModel(15, -15, hole=True)
        self.assertNamesAt(model, 15, -15)
        self.setLine(model[1], 16, -15)
        self.assertNamesAt(model, 16, -15)

    def testStoredEndSurvivesSaveAndReopen(self):
        """testEndStaysWhenTheFarEndIsShortenedToTheProfile's model saved after the edit and
        reopened, then the spine redrawn and recomputed: the names stay at z = 30. The profile
        lies on the spine's end (z = 0), so without the stored end they would go there."""
        model = self.endModel(30, -40)
        self.setLine(model[1], 30, 0)
        model = self.reopen(*(obj.Name for obj in model))
        self.assertEqual(len(model[2].SpineEnds), 2)
        self.assertNamesAt(model, 30, 0)
        self.setLine(model[1], 30, 0)
        self.assertNamesAt(model, 30, 0)

    def testNothingStoredDecidesAsBefore(self):
        """testEndStaysWhenTheFarEndIsShortenedToTheProfile with nothing stored before the
        edit, as in a file saved before ops#379: the end nearest the profile takes the names
        (z = 0), and that end is stored from then on."""
        model = self.endModel(30, -40)
        pipe = model[2]
        self.assertPointsAt(pipe.SpineEnds, [(0, 0, 30), (0, 0, -40)])
        pipe.SpineEnds = []
        self.setLine(model[1], 30, 0)
        self.assertNamesAt(model, 0, 30)
        self.assertPointsAt(pipe.SpineEnds, [(0, 0, 0), (0, 0, 30)])

    def testFileWithoutStoredEndsReopensWithItsNames(self):
        """A pipe saved with nothing stored reopens with the names it was saved with, and a
        recompute without an edit keeps them."""
        model = self.endModel(30, -40)
        model[2].SpineEnds = []
        names = dict(model[2].Shape.ElementReverseMap)
        model = self.reopen(*(obj.Name for obj in model))
        self.assertEqual(len(model[2].SpineEnds), 0)
        self.assertEqual(dict(model[2].Shape.ElementReverseMap), names)
        model[2].touch()
        self.doc.recompute()
        self.assertEqual(dict(model[2].Shape.ElementReverseMap), names)
        self.assertNamesAt(model, 30, -40)

    def testEndStaysWhenTheProfileSketchIsTurnedOver(self):
        """The spine 0 -> 30, the profile at z = 10, then its sketch turned over in place (180
        degrees about X; the solid is the same): the names stay at z = 0. The pipe's own frame
        is the profile sketch's; with the ends stored in it (fork PR 356 round 1), the turn read
        as a reversed spine and the names went to z = 30."""
        model = self.endModel(0, 30, z=10)
        self.assertNamesAt(model, 0, 30)
        model[0].Placement = App.Placement(V(0, 0, 10), App.Rotation(V(1, 0, 0), 180))
        self.doc.recompute()
        self.assertNamesAt(model, 0, 30)

    def testEndStaysWhenABaseFeatureIsInserted(self):
        """The spine drawn towards the profile (30 -> 0, the profile at z = 5), then a box 100 mm
        up made the body's base feature: the names stay at z = 0. The pipe's own frame is then
        the base feature's; with the ends stored in it (fork PR 356 round 1), the shift along the
        spine read as a reversed spine and the names went to z = 30."""
        model = self.endModel(30, 0, z=5)
        self.assertNamesAt(model, 0, 30)
        box = self.doc.addObject("Part::Box", "Box")
        box.Placement = App.Placement(V(0, 0, 100), App.Rotation())
        self.doc.recompute()
        self.body.BaseFeature = box
        self.doc.recompute()
        self.assertEqual(model[2].Placement.Base, V(0, 0, 100))
        self.assertNamesAt(model, 0, 30)

    def testEndStaysWhenATransformedPipeTurnsPastNinetyDegrees(self):
        """"Transformed" along an L drawn towards the profile (from the second leg's end down
        to the profile at z = 0), the corner turned from 80 to 120 degrees, where the pipe is
        the union of its pieces (ops#370), and back: the names stay at z = 0, and the far cap
        (z = 30 + 20 cos a) keeps the projections. Before (fork PR 356 round 1), the union named
        the spine's start, the names went to z = 20, and stayed on that end back at 80
        degrees."""

        def points(degrees):
            return [turned(30, degrees, 20), (0, 30), (0, 0)]

        def far(degrees):
            return 30 + 20 * math.cos(math.radians(degrees))

        model = self.endModel(
            None, None, points=points(80), Transition="Transformed", Refine=False
        )
        self.assertNamesAt(model, 0, far(80))
        self.setPolyline(model[1], points(120))
        self.assertNamesAt(model, 0, far(120))
        self.setPolyline(model[1], points(80))
        self.assertNamesAt(model, 0, far(80))

    def testNewTransformedPipePastNinetyDegreesNamesTheProfileEnd(self):
        """testEndStaysWhenATransformedPipeTurnsPastNinetyDegrees's L made at 120 degrees, a
        union from the start, then edited to 80 degrees: the names are at the profile's end
        (z = 0) both times, as for the one sweep. Before (fork PR 356 round 2), with nothing
        stored the union named the spine's start (z = 20) and stored that."""

        def points(degrees):
            return [turned(30, degrees, 20), (0, 30), (0, 0)]

        def far(degrees):
            return 30 + 20 * math.cos(math.radians(degrees))

        model = self.endModel(
            None, None, points=points(120), Transition="Transformed", Refine=False
        )
        self.assertNamesAt(model, 0, far(120))
        self.setPolyline(model[1], points(80))
        self.assertNamesAt(model, 0, far(80))

    # A sketch attached to each side face of the L of
    # testEndStaysWhenATransformedPipeTurnsPastNinetyDegrees (spine from the profile or towards
    # it), the corner turned across 90 degrees and back: each
    # stays on a face of its own leg. Before (fork PR 344), the union's first piece took the names
    # the one sweep gives the far leg's side faces: with the spine from the profile, the sketches
    # on the second leg went to the first leg's faces, valid and silent; drawn towards it, those
    # on the profile's leg went missing.

    def sideFaceModel(self, points):
        """"Transformed" along the polyline `points` (an XZ sketch), Refine off, the square at
        z = 0, a sketch attached to each side face (every face but the caps, which face +-Z)."""
        profile = self.square()
        path = self.sketch("Path", models.polyline(points), placement=XZ)
        pipe = self.pipe(profile, path, Transition="Transformed", Refine=False)
        sketches = []
        for index, face in enumerate(pipe.Shape.Faces, 1):
            if abs(abs(face.normalAt(0, 0).z) - 1) < 1e-9:
                continue
            sketch = self.body.newObject("Sketcher::SketchObject", f"Side{index}")
            sketch.AttachmentSupport = [(pipe, f"Face{index}")]
            sketch.MapMode = "FlatFace"
            sketches.append(sketch)
        self.doc.recompute()
        return path, pipe, sketches

    def facesOf(self, pipe, sketches, points):
        """For each sketch, the side face its face is, as (leg, edge): the leg of `points`
        (0, 1, ...) nearest the face's centre, and the square's edge it was swept from, by the
        side of the leg the centre lies on ("Transformed" keeps the square's orientation): "y"
        +-1 for the edges at y = +-2, "x" +-1 for those at x = +-2. None for an invalid sketch."""
        ends = [V(x, 0, z) for x, z in points]

        def nearest(point, i):
            along = ends[i + 1] - ends[i]
            t = max(0.0, min(1.0, (point - ends[i]).dot(along) / along.dot(along)))
            return ends[i] + along * t

        def face(point):
            leg = min(range(len(ends) - 1), key=lambda i: (point - nearest(point, i)).Length)
            offset = point - nearest(point, leg)
            if abs(offset.y) > 1:
                return leg, ("y", 1 if offset.y > 0 else -1)
            self.assertGreater(abs(offset.x), 1e-3, (point, leg))
            return leg, ("x", 1 if offset.x > 0 else -1)

        faces = []
        for sketch in sketches:
            if not sketch.isValid():
                faces.append(None)
                continue
            (support,) = sketch.AttachmentSupport[0][1]
            faces.append(face(pipe.Shape.getElement(support).CenterOfMass))
        return faces

    def alone(self, pipe, sketches):
        """For each sketch, whether its face shares its plane with no other face of the pipe"""

        def plane(face):
            normal = face.normalAt(0, 0)
            return normal, face.CenterOfMass.dot(normal)

        planes = [plane(face) for face in pipe.Shape.Faces]
        result = []
        for sketch in sketches:
            (support,) = sketch.AttachmentSupport[0][1]
            normal, offset = plane(pipe.Shape.getElement(support))
            shared = [
                (n, d)
                for n, d in planes
                if abs(abs(n.dot(normal)) - 1) < 1e-9 and abs(abs(d) - abs(offset)) < 1e-7
            ]
            result.append(len(shared) == 1)
        return result

    def assertSidesStayOnTheirLegs(self, points):
        """The L through points(degrees), made at 80 degrees and at 120 (the union), the corner
        turned to the other angle and back by moving the spine's lines (their geometry ids
        kept).
        - From 80 degrees to 120 (the one sweep to the union), each side face's sketch stays
          valid, on the face of the same leg and profile edge it was attached on.
        - From the union, the fuse has renamed (MOD) the faces it cut, those in the planes that
          the two legs share (y = +-2) past 90 degrees, and a reference to one goes missing, as
          before. A sketch on a face that shares its plane with no other face stays valid on
          its face; any sketch that stays valid is on the same leg and profile edge.
        Then the same with the spine deleted and drawn again at each angle (new geometry ids):
        the legs' names are new, so a reference may go missing (the leg that stays in place is
        found by its place), but none moves to another face (ops#415)."""
        for redraw, start, other in (
            (False, 80, 120),
            (False, 120, 80),
            (True, 80, 120),
            (True, 120, 80),
        ):
            self.tearDown()
            self.setUp()
            with self.subTest(start=start, redraw=redraw):
                path, pipe, sketches = self.sideFaceModel(points(start))
                faces = self.facesOf(pipe, sketches, points(start))
                self.assertNotIn(None, faces)
                self.assertEqual({leg for leg, side in faces}, {0, 1})
                before = start
                for degrees in (other, start):
                    kept = [sketch for sketch in sketches if sketch.isValid()]
                    alone = self.alone(pipe, kept)
                    if redraw:
                        self.setPolyline(path, points(degrees))
                    else:
                        self.movePolyline(path, points(degrees))
                    now = dict(zip(sketches, self.facesOf(pipe, sketches, points(degrees))))
                    for sketch, face in zip(sketches, faces):
                        if now[sketch] is not None:
                            self.assertEqual(now[sketch], face, (before, degrees, sketch.Name))
                    for sketch, single in zip(kept, alone):
                        if not redraw and (before < 90 or single):
                            self.assertIsNotNone(
                                now[sketch],
                                (before, degrees, sketch.Name, sketch.getStatusString()),
                            )
                    before = degrees

    def testSideFacesStayOnTheirLegsPastNinetyDegrees(self):
        """The spine from the profile: up 30, then 20 turned 80 or 120 degrees."""
        self.assertSidesStayOnTheirLegs(lambda degrees: [(0, 0), (0, 30), turned(30, degrees, 20)])

    def testSideFacesStayOnTheirLegsPastNinetyDegreesTowardsTheProfile(self):
        """The same L drawn towards the profile."""
        self.assertSidesStayOnTheirLegs(lambda degrees: [turned(30, degrees, 20), (0, 30), (0, 0)])

    def assertCapBetweenPiecesDoesNotMoveSilently(
        self, towards, refine=False, downstream=False, redraw=True
    ):
        """"Transformed" along a U, legs 30, 20 and 20 from the square at z = 0, turning 80 and
        then 20 degrees more: past 90 degrees only after the second corner, so the union's two
        pieces meet there, and the cap between them shows at that corner. A sketch on that cap
        and a datum point on each of its edges; then the first turn made 100 degrees: the pieces
        meet at the first corner. Each reference goes missing, is reported with a warning, or
        stays at the second corner (an edge of the cap, now inside a piece, where the one sweep
        has its name); none goes to the first corner's cap silently. Before (fork PR 344), the
        cap and its edges were named after their piece (PCE<n>) and the side faces, so the same
        names came out at the first corner, valid and with no warning (ops#379, round 4).
        The same for what the fuse made at the break (round 5): a datum point and a fillet on
        the crease where the pieces cut each other, points on the crease's vertices and on the
        pieces of the y = +-2 faces there. They were named from the side faces around them, the
        same at either corner, and went to the first corner's crease.
        With `refine` the pipe is refined; with `downstream` it isn't, and the references are on
        a refined Fillet after it (of a profile cap edge, away from the break). Refine merges the
        legs' faces in the planes y = +-2 into one face each, so the cap's edges there are named
        from that face and the cap, and the joint names around the break share a source at either
        corner: the solver took the first corner's at tier 1, valid and silent (fork PR 356
        round 5, finding 1), until a merged face voids such a match (ops#446, fork PR 361). The
        spine's lines are drawn again (`redraw`, new geometry ids) or moved (their ids kept,
        which the legs are named from, ops#415)."""

        def points(first):
            result = [(0, 0), (0, 30), turned(30, first, 20)]
            x, z = result[-1]
            dx, dz = turned(0, first + 20, 20)
            result.append((x + dx, z + dz))
            return result[::-1] if towards else result

        profile = self.square()
        path = self.sketch("Path", models.polyline(points(80)), placement=XZ)
        pipe = self.pipe(
            profile, path, Transition="Transformed", Refine=refine and not downstream
        )
        target = pipe
        if downstream:
            (edge,) = [
                index
                for index, edge in enumerate(pipe.Shape.Edges, 1)
                if abs(edge.CenterOfMass.z) < 1e-6 and abs(edge.CenterOfMass.x - 2) < 1e-6
            ]
            target = self.body.newObject("PartDesign::Fillet", "Downstream")
            target.Base = (pipe, [f"Edge{edge}"])
            target.Radius = 0.3
            target.Refine = True
            self.doc.recompute()
            self.assertTrue(target.isValid(), target.getStatusString())
        corners = [V(x, 0, z) for x, z in points(80)][1:-1]
        caps = [
            index
            for index, face in enumerate(target.Shape.Faces, 1)
            if abs(abs(face.normalAt(0, 0).z) - 1) < 1e-9 and face.CenterOfMass.z > 1
        ]
        self.assertEqual(len(caps), 2, caps)  # the far end's and the one between the pieces
        (between,) = [
            index
            for index in caps
            if min((target.Shape.Faces[index - 1].CenterOfMass - c).Length for c in corners) < 4
        ]
        cap = target.Shape.Faces[between - 1]
        x, z = turned(30, 80, 20)  # the second corner
        second = V(x, 0, z)
        self.assertLess((cap.CenterOfMass - second).Length, 4)

        def point(name, element, mode="CenterOfMass"):
            point = self.body.newObject("PartDesign::Point", name)
            point.AttachmentSupport = [(target, element)]
            point.MapMode = mode
            return point

        sketch = self.body.newObject("Sketcher::SketchObject", "OnCap")
        sketch.AttachmentSupport = [(target, f"Face{between}")]
        sketch.MapMode = "FlatFace"
        # What each reference is on, where: the element's centre, a point's place, a fillet's
        # round faces
        places = {
            sketch.Name: lambda: [
                target.Shape.getElement(sketch.AttachmentSupport[0][1][0]).CenterOfMass
            ]
        }
        references = [sketch]
        shape = target.Shape
        for index, edge in enumerate(shape.Edges, 1):
            if any(edge.isSame(own) for own in cap.Edges):
                references.append(point(f"OnEdge{index}", f"Edge{index}"))
        self.assertEqual(len(references), 5)
        # What the fuse made at the break (round 5): the crease where the pieces cut each other
        # and its vertices (off the cap's plane, near the corner), and the pieces of the faces
        # in the planes both legs share (y = +-2): refined, those are one face each, whose
        # centre moves with any edit
        creases = [
            index
            for index, edge in enumerate(shape.Edges, 1)
            if (edge.CenterOfMass - second).Length < 4 and abs(edge.CenterOfMass.z - z) > 1e-6
        ]
        self.assertTrue(creases)
        for index in creases:
            references.append(point(f"OnCrease{index}", f"Edge{index}"))
        # The crease proper runs across the square (along y), between the pieces' faces
        (crease,) = [
            index
            for index in creases
            if abs(shape.Edges[index - 1].tangentAt(shape.Edges[index - 1].FirstParameter).y)
            > 1 - 1e-9
        ]
        for index, vertex in enumerate(shape.Vertexes, 1):
            if (vertex.Point - second).Length < 4 and abs(vertex.Point.z - z) > 1e-6:
                references.append(point(f"OnCreaseVertex{index}", f"Vertex{index}", "Vertex"))
        planes = [
            index
            for index, face in enumerate(shape.Faces, 1)
            if abs(abs(face.normalAt(0, 0).y) - 1) < 1e-9
            and (face.CenterOfMass - second).Length < 4
        ]
        if not (refine or downstream):
            self.assertEqual(len(planes), 2, planes)
            for index in planes:
                references.append(point(f"OnPlane{index}", f"Face{index}"))
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (target, [f"Edge{crease}"])
        fillet.Radius = 0.5
        references.append(fillet)
        self.doc.recompute()
        self.assertEqual([(r.Name, r.getStatusString()) for r in references if not r.isValid()], [])

        def at(reference):
            if reference.TypeId == "PartDesign::Fillet":
                return [
                    face.CenterOfMass
                    for face in reference.Shape.Faces
                    if face.Surface.__class__.__name__ != "Plane"
                ]
            if reference.TypeId == "PartDesign::Point":
                return [reference.Placement.Base]
            return places[reference.Name]()

        if redraw:
            self.setPolyline(path, points(100))
        else:
            self.movePolyline(path, points(100))
        for feature in (pipe, target):
            self.assertTrue(feature.isValid(), feature.getStatusString())
        x, z = turned(30, 100, 20)
        second = V(x, 0, z)
        for reference in references:
            if not reference.isValid():
                continue
            levels = [entry["warning_level"] for entry in App.getReferenceReport(reference)]
            if "normal" in levels:
                continue
            # Silent ("resolved" without a warning is too): only where it was, at the second
            # corner (the cap's edges, now inside a piece)
            for place in at(reference):
                self.assertLess((place - second).Length, 4, (reference.Name, place, levels))

    def testCapBetweenPiecesDoesNotMoveSilently(self):
        """The spine from the profile."""
        self.assertCapBetweenPiecesDoesNotMoveSilently(towards=False)

    def testCapBetweenPiecesDoesNotMoveSilentlyTowardsTheProfile(self):
        """The same U drawn towards the profile."""
        self.assertCapBetweenPiecesDoesNotMoveSilently(towards=True)

    def assertCapBetweenRefinedPiecesDoesNotMoveSilently(self, **options):
        """assertCapBetweenPiecesDoesNotMoveSilently with `options`, the spine from the profile
        and towards it, its lines moved and drawn again. With the lines moved, every subtest
        fails on ops#415 round 2 (`work\\415\\r3\\probe_c.out`): a cap edge between the pieces is
        named from the one side face it bounds, so the cap at that leg's other end takes its name,
        and a crease the fuse makes resolves at tier 1 to the other corner's crease."""
        for towards in (False, True):
            for redraw in (False, True):
                self.tearDown()
                self.setUp()
                with self.subTest(towards=towards, redraw=redraw):
                    self.assertCapBetweenPiecesDoesNotMoveSilently(
                        towards, redraw=redraw, **options
                    )

    def testCapBetweenPiecesDoesNotMoveSilentlyWhenTheSpineLinesMove(self):
        """The pipe unrefined, the corner turned by moving the spine's lines (as a drag does)."""
        self.assertCapBetweenRefinedPiecesDoesNotMoveSilently()

    def testCapBetweenPiecesOfARefinedPipeDoesNotMoveSilently(self):
        """The pipe refined (refine is a new Pipe's default)."""
        self.assertCapBetweenRefinedPiecesDoesNotMoveSilently(refine=True)

    def testCapBetweenPiecesDoesNotMoveSilentlyOnARefinedFilletAfterThePipe(self):
        """The pipe unrefined, the references on a refined Fillet after it."""
        self.assertCapBetweenRefinedPiecesDoesNotMoveSilently(downstream=True)

    def testUndoAndRedoOfAnEditKeepTheirNames(self):
        """testEndStaysWhenTheProfileCrossesTheMiddle's edit in a transaction, undone and redone,
        the recompute inside the transaction or after it: the names are at the spine's start
        each time (z = 15, then z = 16)."""
        for inside in (True, False):
            if not inside:
                self.tearDown()
                self.setUp()
            with self.subTest(inside=inside):
                self.doc.UndoMode = 1
                model = self.endModel(15, -15)
                path = model[1]
                self.doc.openTransaction("Spine")
                path.deleteAllGeometry()
                path.addGeometry(Part.LineSegment(V(0, 16, 0), V(0, -15, 0)))
                if inside:
                    self.doc.recompute()
                self.doc.commitTransaction()
                self.doc.recompute()
                self.assertNamesAt(model, 16, -15)
                self.doc.undo()
                self.doc.recompute()
                self.assertNamesAt(model, 15, -15)
                self.doc.redo()
                self.doc.recompute()
                self.assertNamesAt(model, 16, -15)

    def testRecomputeKeepsStoredEndsWithinConfusion(self):
        """Stored ends within Precision::Confusion() (1e-7 mm) of the spine's, as rounding leaves
        them, aren't rewritten: a recompute that changes nothing leaves the saved file as it
        was."""
        model = self.endModel(0, 30)
        pipe = model[2]
        nudged = [point + V(0, 0, 1e-9) for point in pipe.SpineEnds]
        pipe.SpineEnds = nudged
        pipe.touch()
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertEqual(
            [(p.x, p.y, p.z) for p in pipe.SpineEnds], [(p.x, p.y, p.z) for p in nudged]
        )


SQUARE = [V(-2, -2, 0), V(2, -2, 0), V(2, 2, 0), V(-2, 2, 0)]


def extrusions(points, face=None):
    """What "Transformed" means along a polyline: the profile isn't turned at the corners, only
    moved along each segment, so the pipe is the union of its extrusions along the segments.
    `face` (default the square -2..2) lies at points[0]."""
    face = face or Part.Face(Part.makePolygon(SQUARE + SQUARE[:1]))
    parts = []
    for start, end in zip(points, points[1:]):
        part = face.copy()
        part.translate(start - points[0])
        parts.append(part.extrude(end - start))
    return parts[0].multiFuse(parts[1:]).removeSplitter() if len(parts) > 1 else parts[0]


class TestPipeCorners(unittest.TestCase):
    """ops#370 and ops#381: a Pipe at sharp spine corners. New pipes join them as "Right
    corner". "Transformed" keeps the profile's orientation across a corner, so the stretch after
    it is sheared: it fails where that stretch has no thickness (thinner than 1e-5 mm, at a
    right angle), warns within 1 degree of that, and past 90 degrees, where the profile would
    pass back through itself, the pipe is the union of the pieces between those corners. Every
    pipe's result must be a valid solid, whatever its transition. The profile is the square
    -2..2 at z = 0 in a Body, the spines sketches on XZ (a point (x, z)), unless stated."""

    def setUp(self):
        self.doc = models.newDocument("PartDesignTestPipeCorners")
        self.doc.HistoryAlgorithm = "V2"
        self.doc.InternNames = False  # plain names as text (ops#6 Q6)
        self.body = models.body(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def renew(self):
        self.tearDown()
        self.setUp()

    def spine(self, points, closed=False):
        geometry = models.polygon(points) if closed else models.polyline(points)
        return models.sketch(self.doc, "Path", geometry, self.body, placement=XZ)

    def profile(self, geometry=None):
        return models.sketch(
            self.doc, "Profile", geometry or models.rectangle(-2, -2, 2, 2), self.body
        )

    def pipe(self, spine, profile=None, **properties):
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile or self.profile()
        pipe.Spine = (spine, [])
        for name, value in properties.items():
            setattr(pipe, name, value)
        self.doc.recompute()
        return pipe

    def transformed(self, points, closed=False, profile=None, **properties):
        return self.pipe(self.spine(points, closed), profile, Transition="Transformed", **properties)

    def assertValidSolid(self, pipe):
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertEqual(len(pipe.Shape.Solids), 1)
        self.assertTrue(pipe.Shape.isValid())

    def assertFails(self, pipe, *phrases):
        self.assertFalse(pipe.isValid())
        for phrase in phrases:
            self.assertIn(phrase, pipe.getStatusString())

    def assertWarns(self, pipe, warns=True):
        if warns:
            self.assertIn("Warning", pipe.State)
            self.assertIn("nearly edge-on", pipe.getStatusString())
        else:
            self.assertNotIn("Warning", pipe.State)

    def assertSameShape(self, shape, reference):
        """The same solid: equal volumes, and the common part is all of it (to 1e-5 of it: the
        sweep approximates its surfaces as B-splines, 1.1e-6 off for a circle at 150 degrees)."""
        delta = 1e-5 * reference.Volume
        self.assertAlmostEqual(shape.Volume, reference.Volume, delta=delta)
        self.assertAlmostEqual(shape.common(reference).Volume, reference.Volume, delta=delta)

    def assertUnionOf(self, pipe, points, face=None, warns=False):
        """A valid solid, with no self-intersection the boolean check finds, equal to the
        profile's extrusions along the spine's segments, with no warning unless `warns` (None:
        either)."""
        self.assertValidSolid(pipe)
        pipe.Shape.check(True)
        self.assertSameShape(pipe.Shape, extrusions(points, face))
        if warns is not None:
            self.assertWarns(pipe, warns)

    @staticmethod
    def lPoints(degrees, first=30, second=20):
        """Up `first` along Z, then `second` turned `degrees` from +Z towards +X."""
        return [(0, 0), (0, first), turned(first, degrees, second)]

    @staticmethod
    def inSpace(points):
        return [V(x, 0, z) for x, z in points]

    # The default ----------------------------------------------------------------------------

    def testNewPipeJoinsCornersAsRightCorner(self):
        """A new pipe, nothing set, along an L: "Right corner", the full 4 x 4 section all
        along, 4 * 4 * (30 + 20)."""
        pipe = self.pipe(self.spine(self.lPoints(90)))
        self.assertEqual(pipe.Transition, "Right corner")
        self.assertValidSolid(pipe)
        self.assertAlmostEqual(pipe.Shape.Volume, 800, 6)

    # The right-angle case -------------------------------------------------------------------

    def testRightAngleFails(self):
        """Exactly 90 degrees: the second leg would have no thickness. The pipe fails, naming
        the corner. Before, the solid was invalid, and nothing said so."""
        pipe = self.transformed([(0, 0), (0, 30), (20, 30)])
        self.assertFails(pipe, "(0, 0, 30)", "no thickness", "Right corner")

    def testInsideTheBandFails(self):
        """89.9999 and 90.0001 degrees: the leg is 4 * cos = 7e-6 mm thick, under 1e-5 mm."""
        for degrees in (89.9999, 90.0001):
            with self.subTest(degrees=degrees):
                self.renew()
                self.assertFails(self.transformed(self.lPoints(degrees)), "no thickness")

    def testNearTheBandWarns(self):
        """89.999 degrees: 7e-5 mm, outside the band: the sheared pipe, 4 * 4 * 30 + 4 * 4 * 20
        * cos 89.999, with a warning (within 1 degree of the collapse)."""
        pipe = self.transformed(self.lPoints(89.999))
        self.assertValidSolid(pipe)
        self.assertAlmostEqual(
            pipe.Shape.Volume, 480 + 320 * math.cos(math.radians(89.999)), 6
        )
        self.assertWarns(pipe)

    def testTwoZsAndAClosedSquareFail(self):
        """A Z (+90, -90), a U (+90, +90) and a closed square: each fails at its first corner,
        (0, 0, 30). Before, they were invalid or had no volume."""
        cases = {
            "Z": ([(0, 0), (0, 30), (20, 30), (20, 60)], False),
            "U": ([(0, 0), (0, 30), (20, 30), (20, 0)], False),
            "square": ([(0, 0), (0, 30), (30, 30), (30, 0)], True),
        }
        for case, (points, closed) in cases.items():
            with self.subTest(case):
                self.renew()
                self.assertFails(self.transformed(points, closed), "(0, 0, 30)", "no thickness")

    # Unchanged: under 90 degrees -------------------------------------------------------------

    def testShearedUnder90DegreesUnchanged(self):
        """45 degrees, with and without Refine: the sheared pipe as before, 480 + 320 * cos 45,
        the extrusions' union, with no warning."""
        for refine in (False, True):
            with self.subTest(refine=refine):
                self.renew()
                points = self.lPoints(45)
                pipe = self.transformed(points, Refine=refine)
                self.assertValidSolid(pipe)
                self.assertAlmostEqual(pipe.Shape.Volume, 480 + 320 * math.cos(math.pi / 4), 6)
                self.assertSameShape(pipe.Shape, extrusions(self.inSpace(points)))
                self.assertWarns(pipe, False)

    def testSmoothSpineSameUnderEveryTransition(self):
        """A quarter circle of radius 20 and a circle of radius 2: no corner, so every
        transition gives the same pipe, pi * 2^2 * (pi / 2 * 20) (Pappus), with no warning."""
        for transition in ("Transformed", "Right corner", "Round corner"):
            with self.subTest(transition):
                self.renew()
                arc = Part.ArcOfCircle(Part.Circle(V(20, 0, 0), V(0, 0, 1), 20), math.pi / 2, math.pi)
                spine = models.sketch(self.doc, "Path", arc, self.body, placement=XZ)
                pipe = self.pipe(spine, self.profile(models.circle(0, 0, 2)), Transition=transition)
                self.assertValidSolid(pipe)
                self.assertAlmostEqual(pipe.Shape.Volume, 4 * math.pi * 10 * math.pi, 3)
                self.assertWarns(pipe, False)

    # The union past 90 degrees --------------------------------------------------------------

    def testPast90DegreesIsTheUnion(self):
        """120 degrees: the second leg runs back under the corner. One valid solid, the
        extrusions' union. Before, a self-intersecting solid (320) that isValid() passed."""
        points = self.lPoints(120)
        self.assertUnionOf(self.transformed(points), self.inSpace(points))

    def testJustPast90Degrees(self):
        """91 degrees: the union. 91 is the warning's edge (1 degree from the collapse), so the
        warning is tested off it: 90.5 degrees warns, 92 doesn't."""
        points = self.lPoints(91)
        self.assertUnionOf(self.transformed(points), self.inSpace(points), warns=None)
        for degrees, warns in ((90.5, True), (92, False)):
            with self.subTest(degrees=degrees):
                self.renew()
                pipe = self.transformed(self.lPoints(degrees))
                self.assertValidSolid(pipe)
                self.assertWarns(pipe, warns)

    def testCircleAt150Degrees(self):
        """A circle of radius 2 at 150 degrees: the union of its extrusions."""
        points = self.lPoints(150)
        pipe = self.transformed(points, profile=self.profile(models.circle(0, 0, 2)))
        self.assertUnionOf(pipe, self.inSpace(points), Part.Face(Part.Wire(Part.makeCircle(2))))

    def testTwoCornersPassing90Together(self):
        """Two 60 degree corners turning the same way (legs of 20): the tilt is 60, then 120,
        so only the second corner passes 90. The union."""
        points = [(0, 0), (0, 20), turned(20, 60, 20)]
        x, z = points[-1]
        points.append((x + 20 * math.sin(math.radians(120)), z + 20 * math.cos(math.radians(120))))
        self.assertUnionOf(self.transformed(points), self.inSpace(points))

    def testClosedTriangle(self):
        """An equilateral triangle, closed: tilts 0, 120 and 240 degrees. The union; before, no
        volume."""
        points = [(0, 0), (0, 30), (15 * math.sqrt(3), 15)]
        pipe = self.transformed(points, closed=True)
        self.assertUnionOf(pipe, self.inSpace(points + points[:1]))

    def testSpaceSpine(self):
        """A spine in space: up 30, then 120 degrees towards +X for 20, then that direction
        turned 90 degrees about Z for 20 more. The union."""
        leg = App.Vector(math.sin(math.radians(120)), 0, math.cos(math.radians(120))) * 20
        points = [V(0, 0, 0), V(0, 0, 30)]
        points.append(points[-1] + leg)
        points.append(points[-1] + App.Rotation(V(0, 0, 1), 90).multVec(leg))
        spine = models.feature(self.doc, "Path", Part.makePolygon(points))
        pipe = self.pipe(spine, Transition="Transformed")
        self.assertUnionOf(pipe, points)

    # Curved stretches ------------------------------------------------------------------------

    def curvedSpine(self, degrees, arc):
        """Up 30, a corner of `degrees`, then an arc of radius 10 turning `arc` degrees further
        the same way; and the arc's centre (x, z)."""
        start = math.radians(degrees)
        centre = (10 * math.cos(start), 30 - 10 * math.sin(start))  # right of the turned leg
        towards = math.radians(180 - degrees)  # from the centre to the corner, from +X
        circle = Part.Circle(V(*centre, 0), V(0, 0, 1), 10)
        geometry = models.polyline([(0, 0), (0, 30)])
        geometry.append(Part.ArcOfCircle(circle, towards - math.radians(arc), towards))
        return models.sketch(self.doc, "Path", geometry, self.body, placement=XZ), centre

    def testCurveAfterACornerPast90(self):
        """A 120 degree corner, then an arc turning 30 more: the union. Along the arc the
        profile turns with the spine, so the second piece is the square, as it lies at the
        corner, revolved 30 degrees about the arc's axis."""
        spine, (x, z) = self.curvedSpine(120, 30)
        pipe = self.pipe(spine, Transition="Transformed")
        self.assertValidSolid(pipe)
        face = Part.Face(Part.makePolygon(SQUARE + SQUARE[:1]))
        corner = face.copy()
        corner.translate(V(0, 0, 30))
        reference = face.extrude(V(0, 0, 30)).fuse(corner.revolve(V(x, 0, z), V(0, 1, 0), 30))
        self.assertSameShape(pipe.Shape, reference.removeSplitter())

    def testFoldAlongACurveFails(self):
        """A 100 degree corner, then an arc turning 40 more: the profile, nearly edge-on to the
        curve, folds over itself within the arc: the arc's axis passes through the section. No
        union fixes that: the pipe fails, naming where the arc starts. Before, an invalid
        solid."""
        pipe = self.pipe(self.curvedSpine(100, 40)[0], Transition="Transformed")
        self.assertFails(pipe, "folds", "(0, 0, 30)")

    # The result gate (ops#381) ---------------------------------------------------------------

    def multisection(self, transition, turn=0):
        """Along the L (90 degrees), to a 6 x 6 section normal to the last leg, at its end; its
        sketch turned `turn` degrees about the leg (the same square, its wire starting elsewhere)."""
        turned = App.Rotation(V(1, 0, 0), turn).multiply(App.Rotation(V(0, 1, 0), 90))
        section = models.sketch(
            self.doc,
            "Section",
            models.rectangle(-3, -3, 3, 3),
            self.body,
            placement=App.Placement(V(20, 0, 30), turned),
        )
        return self.pipe(
            self.spine(self.lPoints(90)),
            Transformation="Multisection",
            Sections=[section],
            Transition=transition,
        )

    def testMultisectionCornersNeedTransformed(self):
        """Several sections at a corner: "Right corner" gave no solid and "Round corner" an
        invalid one, silently (ops#381). Both fail now."""
        for transition in ("Right corner", "Round corner"):
            with self.subTest(transition):
                self.renew()
                self.assertFails(self.multisection(transition), "isn't a valid solid")

    def testMultisectionTransformedUnchanged(self):
        """With "Transformed" the sections join at the corner: valid, the volume integration's
        build gave (920; the sections set the orientation, no tilt test)."""
        pipe = self.multisection("Transformed")
        self.assertValidSolid(pipe)
        self.assertAlmostEqual(pipe.Shape.Volume, 920, 2)
        self.assertWarns(pipe, False)

    def testMultisectionInsideOutFails(self):
        """The same pipe with the section's sketch turned about the last leg: which corner its
        wire starts at changes OCCT's sweep. On Windows, turned 90 or 180 degrees, it gave the
        solid that macOS gives unturned (ops#396): BRepCheck passes it, its volume is -161.6, the
        boolean check finds faults, and OCCT's solid classifier took it for an outward solid, so
        round 7 accepted it. Its caps now tell its orientation, and disagree with the classifier
        or each other: the pipe fails. Every turn gives the valid 920 or fails, never another
        solid."""
        for turn in (0, 90, 180, 270):
            with self.subTest(turn=turn):
                self.renew()
                pipe = self.multisection("Transformed", turn)
                if pipe.isValid():
                    self.assertValidSolid(pipe)
                    self.assertAlmostEqual(pipe.Shape.Volume, 920, 2)
                else:
                    self.assertFails(pipe, "isn't a valid solid", "sections may twist or cross")

    def testHairpinFails(self):
        """A 170 degree hairpin: "Right corner" and "Round corner" gave invalid solids
        (ops#381). Both fail now, naming the corner."""
        for transition in ("Right corner", "Round corner"):
            with self.subTest(transition):
                self.renew()
                pipe = self.pipe(self.spine(self.lPoints(170)), Transition=transition)
                self.assertFails(pipe, "isn't a valid solid", "(0, 0, 30)")

    # Names ----------------------------------------------------------------------------------

    def testUnionNames(self):
        """The union at 120 degrees: the start cap keeps the sketch's names; the far end (on
        z = 20, the square only moved there) projects them, as the one sweep's far end does; the
        caps between the pieces (z = 30) carry neither, but are told apart as the first piece's
        back (PCB) and the second's front (PCF), named from their edges, which hold their legs'
        spine edges (ops#415; keyed by the spine vertex's index in fork PR 356 rounds 4-5, by
        the piece's before); every name is distinct, so the second leg's side
        faces aren't named as the first's. Before (fork PR 344 round 2), the first piece's end
        cap at the corner carried the one sweep's far-end name, and the far end projections of
        projections."""
        profile = self.profile()
        pipe = self.transformed(self.lPoints(120), profile=profile)
        shape = pipe.Shape
        TestPipeEndNames.assertStartKeepsNames(self, shape, profile, onPlane(2, 0))
        TestPipeEndNames.assertEndProjects(self, shape, profile, onPlane(2, 20))
        TestPipeEndNames.assertNamesDistinct(self, shape)
        farEnd = self.horizontalFaces(shape, 20)
        self.assertEqual(len(farEnd), 1, farEnd)
        corner = self.horizontalFaces(shape, 30)
        self.assertTrue(corner)
        for face in corner:
            name = firstName(shape, face)
            self.assertNotEqual(name, firstName(shape, farEnd[0]))
            self.assertIn(App.getDecodedMappedName(name)[-1]["opCode"], ("PCB", "PCF"), name)

    def horizontalFaces(self, shape, z):
        """The faces on the plane at height z."""
        return [
            f"Face{index}"
            for index, face in enumerate(shape.Faces, 1)
            if face.BoundBox.ZLength < 1e-6 and abs(face.BoundBox.ZMin - z) < 1e-6
        ]

    def testFarEndReferencesFollowAcross90Degrees(self):
        """A sketch attached to the far end of an L at 80 degrees, and a chamfer on one of its
        edges; the corner then edited to 120 degrees, which makes the pipe the union: both
        follow the far end (z = 20, x = 17.32), as they do in a one sweep. Before, they moved
        to the first piece's end cap at the corner (z = 30), valid and silent."""
        spine = self.spine(self.lPoints(80))
        pipe = self.pipe(spine, Transition="Transformed", Refine=False)
        farZ = turned(30, 80, 20)[1]
        faces = self.horizontalFaces(pipe.Shape, farZ)
        self.assertEqual(len(faces), 1, faces)
        edges = elementsWhere(
            pipe.Shape, "Edge", lambda p: abs(p.z - farZ) < 1e-6 and abs(p.y + 2) < 1e-6
        )
        self.assertEqual(len(edges), 1, edges)
        chamfer = self.body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pipe, edges)
        chamfer.Size = 0.3
        onEnd = self.body.newObject("Sketcher::SketchObject", "OnEnd")
        onEnd.AttachmentSupport = [(pipe, faces[0])]
        onEnd.MapMode = "FlatFace"
        onEnd.addGeometry(models.circle(0, 0, 0.5), False)
        self.body.Tip = chamfer
        self.doc.recompute()
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self.assertAlmostEqual(onEnd.Placement.Base.z, farZ, 6)

        models.setLines(spine, {1: ((0, 30), turned(30, 120, 20))})
        self.doc.recompute()
        self.assertValidSolid(pipe)
        x, z = turned(30, 120, 20)
        for obj in (chamfer, onEnd):
            self.assertTrue(obj.isValid(), (obj.Name, obj.getStatusString()))
            self.assertNotIn("Warning", obj.State, obj.Name)
        self.assertAlmostEqual(onEnd.Placement.Base.z, z, 6)
        support = pipe.Shape.getElement(onEnd.AttachmentSupport[0][1][0])
        self.assertAlmostEqual(support.CenterOfMass.x, x, 6)
        self.assertAlmostEqual(support.CenterOfMass.z, z, 6)
        self.assertEqual(len(chamfer.Base[1]), 1, chamfer.Base[1])
        edge = pipe.Shape.getElement(chamfer.Base[1][0])
        self.assertTrue(all(abs(p.z - z) < 1e-6 for p in edge.discretize(5)), chamfer.Base[1])

    def testProfileBehindTheStartPast90Degrees(self):
        """The profile 10 below the spine's start (z = -10), along an L at 120 degrees: the
        union of its extrusions from where it lies, 621.52. Before, the second piece's section
        was placed where it lies nearest that piece, and the pipe was 640, valid and wrong."""
        points = self.lPoints(120)
        profile = models.sketch(
            self.doc, "Profile", models.rectangle(-2, -2, 2, 2), self.body, z=-10
        )
        face = Part.Face(Part.makePolygon([p + V(0, 0, -10) for p in SQUARE + SQUARE[:1]]))
        self.assertUnionOf(self.transformed(points, profile=profile), self.inSpace(points), face)

    # Closed spines with holed profiles ------------------------------------------------------

    def testClosedSpineKeepsTheHole(self):
        """An annulus (radius 3, hole 1.5) swept around closed spines: the hole stays a hole.
        Around a circle of radius 20 ("Right corner" and "Transformed"), 2 pi 20 pi 6.75
        (Pappus); around a closed 30 x 30 square ("Right corner"; "Transformed" fails there,
        at its right angles), the annulus times the 120 mm path. Before, each closed shell was
        made a solid and fused, so the hole was filled."""
        area = math.pi * (9 - 2.25)
        for transition in ("Right corner", "Transformed"):
            with self.subTest(spine="circle", transition=transition):
                self.renew()
                spine = models.sketch(
                    self.doc, "Path", [models.circle(0, 0, 20)], self.body, placement=XZ
                )
                profile = self.profile([models.circle(20, 0, 3), models.circle(20, 0, 1.5)])
                pipe = self.pipe(spine, profile, Transition=transition)
                self.assertValidSolid(pipe)
                self.assertAlmostEqual(pipe.Shape.Volume, 2 * math.pi * 20 * area, 2)
        with self.subTest(spine="square"):
            self.renew()
            spine = self.spine([(0, 0), (0, 30), (30, 30), (30, 0)], closed=True)
            profile = self.profile([models.circle(0, 0, 3), models.circle(0, 0, 1.5)])
            pipe = self.pipe(spine, profile, Transition="Right corner")
            self.assertValidSolid(pipe)
            self.assertAlmostEqual(pipe.Shape.Volume, 120 * area, 2)

    def testClosedTriangleKeepsTheHole(self):
        """testClosedTriangle with a 2 x 2 hole in the square: the union of the holed square's
        extrusions. Before, the hole was filled."""
        points = [(0, 0), (0, 30), (15 * math.sqrt(3), 15)]
        profile = self.profile(models.rectangle(-2, -2, 2, 2) + models.rectangle(-1, -1, 1, 1))
        hole = [V(-1, -1, 0), V(1, -1, 0), V(1, 1, 0), V(-1, 1, 0)]
        face = Part.Face(
            [Part.makePolygon(SQUARE + SQUARE[:1]), Part.makePolygon(hole + hole[:1])]
        )
        pipe = self.transformed(points, closed=True, profile=profile)
        self.assertUnionOf(pipe, self.inSpace(points + points[:1]), face)

    # Folds along arcs, Fixed mode, the union's fuse ------------------------------------------

    def testFoldAlongAnArcFails(self):
        """A circle of radius 2, a 45 degree corner, then an arc of radius 2.5 turning 30 more:
        the arc's axis passes through the tilted section, so the sweep folds back over itself.
        BRepCheck passes that solid for a round profile: the pipe fails, naming the corner.
        Before, a self-intersecting solid (388.62), valid and silent."""
        start = math.radians(45)
        centre = (2.5 * math.cos(start), 30 - 2.5 * math.sin(start))
        towards = math.radians(180 - 45)
        circle = Part.Circle(V(*centre, 0), V(0, 0, 1), 2.5)
        geometry = models.polyline([(0, 0), (0, 30)])
        geometry.append(Part.ArcOfCircle(circle, towards - math.radians(30), towards))
        spine = models.sketch(self.doc, "Path", geometry, self.body, placement=XZ)
        pipe = self.pipe(spine, self.profile([models.circle(0, 0, 2)]), Transition="Transformed")
        self.assertFails(pipe, "folds", "(0, 0, 30)", "Right corner")

    def testFoldAlongACurve(self):
        """A circle of radius 2, an 85 degree corner, then a B-spline bending 40 degrees more
        over 10 mm: the tilted section folds along the curve, which BRepCheck passes. The
        section's motion sampled along the curve shows it: the pipe fails, naming where the
        curve starts. The same with a 60 degree corner and a gentle bend (30 degrees over 20 mm)
        stays valid, with no self-intersection the boolean check finds."""
        for theta, bend, length, folds in ((85, 40, 10, True), (60, 30, 20, False)):
            with self.subTest(theta=theta):
                self.renew()
                corner = V(0, 0, 30)
                points = [corner]
                for i in range(1, 9):
                    angle = math.radians(theta + bend * i / 8)
                    points.append(points[-1] + V(math.sin(angle), 0, math.cos(angle)) * length / 8)
                curve = Part.BSplineCurve()
                start = math.radians(theta)
                curve.interpolate(points, InitialTangent=V(math.sin(start), 0, math.cos(start)))
                wire = Part.Wire([Part.makeLine(V(0, 0, 0), corner), curve.toShape()])
                spine = models.feature(self.doc, "Path", wire)
                profile = self.profile([models.circle(0, 0, 2)])
                pipe = self.pipe(spine, profile, Transition="Transformed", Refine=False)
                if folds:
                    self.assertFails(pipe, "along the curve from (0, 0, 30)", "Right corner")
                else:
                    self.assertValidSolid(pipe)
                    pipe.Shape.check(True)

    def timedPipe(self, spine, profile=None, **properties):
        """The pipe, and how long its recompute took (s)."""
        start = time.perf_counter()
        pipe = self.pipe(spine, profile, **properties)
        return pipe, time.perf_counter() - start

    def testLongCurvesAreQuick(self):
        """Along a long B-spline after a corner, and along a smooth chain of B-splines, a square's
        pipe recomputes in well under 10 s (integration's build: 0.1 s), and doesn't fold. Fork
        PR 344 round 3 ran the boolean check there: 44 s and 23 s.
        - A 30 degree corner, then a B-spline through 121 points (60 mm, waving 2 mm sideways):
          the section is tilted to the curve, so its folds are looked for.
        - Four B-splines joined smoothly in space, the profile flat at the start, which the
          spine leaves at about 55 degrees (`interpolate` ignores an InitialTangent given without
          a FinalTangent): the profile's slant tilts the section, so the folds are looked for
          along all four. The volume integration gives."""
        corner = V(0, 0, 30)
        leg = V(math.sin(math.radians(30)), 0, math.cos(math.radians(30)))
        points = [
            corner + leg * (0.5 * i) + V(0, 2 * math.sin(i / 6), 0) * (i / 120) for i in range(121)
        ]
        curve = Part.BSplineCurve()
        curve.interpolate(points, InitialTangent=leg)
        spine = models.feature(
            self.doc, "Path", Part.Wire([Part.makeLine(V(0, 0, 0), corner), curve.toShape()])
        )
        pipe, seconds = self.timedPipe(spine, Transition="Transformed", Refine=False)
        self.assertValidSolid(pipe)
        self.assertLess(seconds, 10)

        self.renew()
        points = [
            V(8 * math.sin(4 * math.pi * t), 4 * math.sin(2.6 * math.pi * t), 60 * t)
            for t in (i / 24 for i in range(25))
        ]
        curve = Part.BSplineCurve()
        curve.interpolate(points, InitialTangent=V(0, 0, 1))
        first, last = curve.FirstParameter, curve.LastParameter
        cuts = [first + (last - first) * k / 4 for k in range(5)]
        spine = models.feature(
            self.doc, "Path", Part.Wire([curve.toShape(a, b) for a, b in zip(cuts, cuts[1:])])
        )
        profile = self.profile(models.rectangle(-1, -1, 1, 1))
        pipe, seconds = self.timedPipe(spine, profile, Transition="Transformed", Refine=False)
        self.assertValidSolid(pipe)
        self.assertAlmostEqual(pipe.Shape.Volume, 218.489, 3)
        self.assertLess(seconds, 10)

    def arcAfterACorner(self, degrees, tilt, radius, arc):
        """Up 30 along Z, a corner of `degrees` towards +X, then an arc of `radius` turning `arc`
        degrees further, in a plane tilted `tilt` degrees about the second leg (0: the corner's
        plane)."""
        corner = V(0, 0, 30)
        leg = V(math.sin(math.radians(degrees)), 0, math.cos(math.radians(degrees)))
        towards = App.Rotation(leg, tilt).multVec(V(0, 1, 0)).cross(leg).normalize()
        centre = corner + towards * radius

        def at(angle):
            angle = math.radians(angle)
            return centre + (towards * -math.cos(angle) + leg * math.sin(angle)) * radius

        edges = [Part.makeLine(V(0, 0, 0), corner), Part.Arc(at(0), at(arc / 2), at(arc)).toShape()]
        return models.feature(self.doc, "Path", Part.Wire(edges))

    def testBinormalModeFoldsAlongArcs(self):
        """In Binormal mode the profile turns about an arc's axis only when that is the binormal,
        so the arc's exact test doesn't hold; the sampled motion decides. A square, a 60 degree
        corner, then an arc of radius 10 turning 60 degrees in a plane tilted 45 degrees,
        binormal (0.6, 1, 0): the section folds within the arc, and the pipe fails. A 30 degree
        corner and an arc of radius 3 turning 20 degrees in that plane, binormal +Y: no fold,
        valid, as integration gives it (494.365). Round 3 accepted the first (539.40,
        self-intersecting, silently) and refused the second."""
        binormal = V(0.6, 1, 0).normalize()
        spine = self.arcAfterACorner(60, 45, 10, 60)
        pipe = self.pipe(
            spine, Transition="Transformed", Mode="Binormal", Binormal=binormal, Refine=False
        )
        self.assertFails(pipe, "folds", "arc from (0, 0, 30)", "Right corner")

        self.renew()
        spine = self.arcAfterACorner(30, 45, 3, 20)
        pipe = self.pipe(
            spine, Transition="Transformed", Mode="Binormal", Binormal=V(0, 1, 0), Refine=False
        )
        self.assertValidSolid(pipe)
        pipe.Shape.check(True)
        self.assertAlmostEqual(pipe.Shape.Volume, 494.365, 2)

    def assertFoldWarns(self, pipe, *phrases):
        """Valid, with the warning of a small fold."""
        self.assertValidSolid(pipe)
        self.assertIn("Warning", pipe.State)
        for phrase in ("folds the profile slightly", "may cross itself") + phrases:
            self.assertIn(phrase, pipe.getStatusString())

    def testSmallFoldPasses(self):
        """A circle of radius 2, a 60 degree corner, then an arc of radius 3 turning 20 degrees in
        a plane tilted 45 degrees: the section reaches 0.08 mm past the line where it turns back,
        a sliver (about 1e-3 mm^3). Valid, as integration gives it (383.571), with a warning
        naming the fold. The same with a 70 degree corner and radius 4 (0.17 mm of the circle's
        4 mm). The fold's measure alone decides, the same on every platform: round 4 left such
        folds to the boolean check, which passed the first on Windows and refused it on macOS,
        and refused the second on Windows; round 3 refused the first."""
        for degrees, radius, volume in ((60, 3, 383.571), (70, 4, None)):
            with self.subTest(degrees=degrees):
                self.renew()
                spine = self.arcAfterACorner(degrees, 45, radius, 20)
                profile = self.profile([models.circle(0, 0, 2)])
                pipe = self.pipe(spine, profile, Transition="Transformed", Refine=False)
                self.assertFoldWarns(pipe, "arc from (0, 0, 30)", "Right corner")
                if volume:
                    self.assertAlmostEqual(pipe.Shape.Volume, volume, 2)

    def kinkedSpine(self, degrees, radius, bend):
        """Up 30 along Z, a corner of `degrees` towards +X, then one B-spline through nine points:
        20 mm on, a bend of `bend` degrees further (towards +X) over the length of an arc of
        `radius`, and 20 mm on. The bend is short beside the B-spline's few pieces."""
        corner = V(0, 0, 30)
        start = math.radians(degrees)
        leg = V(math.sin(start), 0, math.cos(start))
        towards = V(math.cos(start), 0, -math.sin(start))
        points = [corner, corner + leg * 10, corner + leg * 20]
        length = radius * math.radians(bend) / 4
        for i in range(1, 5):
            angle = math.radians(bend * (i - 0.5) / 4)
            points.append(points[-1] + (leg * math.cos(angle) + towards * math.sin(angle)) * length)
        end = leg * math.cos(math.radians(bend)) + towards * math.sin(math.radians(bend))
        points += [points[-1] + end * 10, points[-1] + end * 20]
        curve = Part.BSplineCurve()
        curve.interpolate(points, InitialTangent=leg, FinalTangent=end)
        return models.feature(
            self.doc, "Path", Part.Wire([Part.makeLine(V(0, 0, 0), corner), curve.toShape()])
        )

    def testShortBendInACurveFolds(self):
        """A circle of radius 2, a 60 degree corner, then a B-spline with a bend of 10 degrees over
        0.52 mm (radius 3) inside it: the tilted section folds there, by 0.8 mm (as the same bend
        as an arc of radius 3 does). Round 4 sampled the B-spline 32 times, 1.4 mm apart, missed
        the bend and accepted the pipe (629.588). The samples are now subdivided where the section
        turns fast enough to fold. Without the corner the section stays square to the bend, which
        is wider than the profile: valid, without a warning."""
        profile = self.profile([models.circle(0, 0, 2)])
        pipe = self.pipe(self.kinkedSpine(60, 3, 10), profile, Transition="Transformed")
        self.assertFails(pipe, "folds", "along the curve from (0, 0, 30)", "Right corner")

        self.renew()
        profile = self.profile([models.circle(0, 0, 2)])
        pipe = self.pipe(self.kinkedSpine(0, 3, 10), profile, Transition="Transformed")
        self.assertValidSolid(pipe)
        self.assertNotIn("Warning", pipe.State)

    def wavySpine(self, waves, bend=True):
        """Up 30 along Z, a 60 degree corner towards +X, then one B-spline: `waves` waves of
        amplitude 1.5 and length 20 towards +X (a point every 1 mm), 20 mm straight on, a bend of
        10 degrees over the length of an arc of radius 3 (unless not `bend`), and 20 mm on. The
        waves bend the curve everywhere, but no tighter than radius 6.1; the bend, interpolated,
        to radius 2.4."""
        corner = V(0, 0, 30)
        leg = V(math.sin(math.radians(60)), 0, math.cos(math.radians(60)))
        towards = V(math.cos(math.radians(60)), 0, -math.sin(math.radians(60)))
        k = 2 * math.pi / 20
        points = [
            corner + leg * x + towards * (1.5 * (1 - math.cos(k * x)))
            for x in range(20 * waves + 1)
        ]
        on = leg + towards * (1.5 * k * math.sin(k * 20 * waves))
        on.normalize()
        side = towards - on * towards.dot(on)
        side.normalize()
        last = points[-1]
        points += [last + on * x for x in range(2, 21, 2)]
        turn = 10 if bend else 0
        length = 3 * math.radians(10) / 4
        for i in range(1, 5 if bend else 1):
            angle = math.radians(turn * (i - 0.5) / 4)
            points.append(points[-1] + (on * math.cos(angle) + side * math.sin(angle)) * length)
        end = on * math.cos(math.radians(turn)) + side * math.sin(math.radians(turn))
        last = points[-1]
        points += [last + end * x for x in range(2, 21, 2)]
        curve = Part.BSplineCurve()
        curve.interpolate(points)  # given end tangents, it overshoots into a cusp at the end
        return models.feature(
            self.doc, "Path", Part.Wire([Part.makeLine(V(0, 0, 0), corner), curve.toShape()])
        )

    def testShortBendAfterALongCurveFolds(self):
        """A circle of radius 2, a 60 degree corner, then a B-spline of 25 waves (567 mm), and at
        its end a bend of 10 degrees over 0.52 mm: the tilted section folds at the bend by about
        0.74 mm (19 % of it, by an independent check). Round 5 subdivided the samples
        in their order along the curve, up to 2048 places: the waves used them all, the bend was
        never looked at closely, and the pipe was accepted silently (4604.24). The most
        fold-prone stretches are now looked at first, and a curve the budget can't cover warns."""
        profile = self.profile([models.circle(0, 0, 2)])
        pipe = self.pipe(self.wavySpine(25), profile, Transition="Transformed", Refine=False)
        self.assertFails(pipe, "folds", "along the curve from (0, 0, 30)", "Right corner")

    def testLongCurveWithANegativeVolumeAccepted(self):
        """A circle of radius 2, a 60 degree corner, then a B-spline of 50 waves (about 1020 spans,
        1093 mm), bending no tighter than radius 6.1: no fold, a correct solid. OCCT's default
        volume integration (BRepGProp::VolumeProperties, Shape.Volume) gets faces with that many
        curved spans badly wrong, here negative (ops#414): round 6 first refused the pipe as an
        invalid solid, since the result gate took a negative volume for an inside-out solid. The
        gate now tells inside-out solids by classifying a point at infinity."""
        profile = self.profile([models.circle(0, 0, 2)])
        spine = self.wavySpine(50, bend=False)
        pipe = self.pipe(spine, profile, Transition="Transformed", Refine=False)
        self.assertValidSolid(pipe)
        curve = spine.Shape.Edges[1].Curve
        middle = curve.value((curve.FirstParameter + curve.LastParameter) / 2)
        self.assertTrue(pipe.Shape.isInside(middle, 1e-6, True))
        self.assertFalse(pipe.Shape.isInside(middle + V(0, 3, 0), 1e-6, True))

    def sBendSpine(self, degrees, bend, length):
        """Up 30 along Z, a corner of `degrees` towards +X, then one B-spline through 15 points:
        20 mm on, an S-bend over `length` (through 8 points, turning up to `bend` degrees towards
        +X and back), and 20 mm on, in the direction it had. Its net turn is nothing."""
        corner = V(0, 0, 30)
        start = math.radians(degrees)
        leg = V(math.sin(start), 0, math.cos(start))
        towards = V(math.cos(start), 0, -math.sin(start))
        points = [corner, corner + leg * 10, corner + leg * 20]
        for i in range(1, 9):
            step = i - 0.5 if i <= 4 else 8.5 - i
            angle = math.radians(bend * step / 4)
            along = leg * math.cos(angle) + towards * math.sin(angle)
            points.append(points[-1] + along * (length / 8))
        last = points[-1]
        points += [last + leg * 10, last + leg * 20]
        curve = Part.BSplineCurve()
        curve.interpolate(points, InitialTangent=leg, FinalTangent=leg)
        return models.feature(
            self.doc, "Path", Part.Wire([Part.makeLine(V(0, 0, 0), corner), curve.toShape()])
        )

    def testShortSBendFolds(self):
        """A circle of radius 2, a 75 degree corner, then a B-spline with a short S-bend inside it
        (up to 0.5 degrees over 0.05 mm, tightest radius 2.3; 1 degree over 0.07 mm, 1.6; 5 degrees
        over 0.05 mm, 0.23): the section, tilted 75 degrees, folds there wherever the curve bends
        tighter than about 7.7 (a fold of a third to a half of the section by an independent
        check). Round 5 looked at the curvature 16 times between two samples and at the turn
        between them, which is nothing: the S-bend fell between, and the pipes were accepted
        silently. A circle of radius 0.5 along the gentlest S-bend would need a bend tighter than
        1.9 to fold: valid and exact, without a warning of its own. Where OCCT's sweep would crash
        along an S-bend (testCurveWhereOCCTWouldCrashFails: macOS's numbers at 1 degree over 0.07
        mm), the pipe fails saying so before any sweep, and the fold isn't looked for."""
        for bend, length in ((0.5, 0.05), (1, 0.07), (5, 0.05)):
            with self.subTest(bend=bend, length=length):
                self.renew()
                profile = self.profile([models.circle(0, 0, 2)])
                spine = self.sBendSpine(75, bend, length)
                pipe = self.pipe(spine, profile, Transition="Transformed", Refine=False)
                if not self.wouldCrash(pipe):
                    phrases = ("folds", "along the curve from (0, 0, 30)", "Right corner")
                    self.assertFails(pipe, *phrases)

        self.renew()
        profile = self.profile([models.circle(0, 0, 0.5)])
        spine = self.sBendSpine(75, 0.5, 0.05)
        pipe = self.pipe(spine, profile, Transition="Transformed", Refine=False)
        if not self.wouldCrash(pipe):
            self.assertValidSolid(pipe)
            # The section keeps its 75-degree tilt along the B-spline: there its area normal to the
            # spine is cos(75) of the circle's. At OCCT's default caps the pipe was 20 % larger,
            # silently; at fork PR 373's (ops#448) it is exact, but OCCT still puts 2 mm on the end
            # cap's vertex, so the pipe may warn that it is loose, and of nothing else (ops#415)
            area = math.pi * 0.5**2
            expected = sum(
                edge.Length * area * (1 if i == 0 else math.cos(math.radians(75)))
                for i, edge in enumerate(spine.Shape.Edges)
            )
            self.assertAlmostEqual(pipe.Shape.Volume, expected, delta=0.01)
            if "Warning" in pipe.State:
                loose = r"Warning: The pipe's result has a tolerance of \S+ mm: its surface may be "
                loose += r"off the swept profile by up to that much"
                self.assertRegex(pipe.getStatusString(), f"^{loose}$")

    def wouldCrash(self, pipe):
        """Whether the pipe failed as OCCT's sweep would crash along its spine (ops#413), which
        depends on the platform's numbers: then the message names the place and the mode."""
        text = pipe.getStatusString()
        if "would crash" not in text:
            return False
        advice = "Smooth the curve there, split it into shorter edges, "
        self.assertFails(pipe, "OCCT's sweep would crash at (", advice, "('Fixed' isn't affected)")
        self.assertIn(f"'{pipe.Mode}' mode", text)
        return True

    def sBendAlongZ(self, bend, length):
        """A B-spline up the Z axis through 15 points: 20 mm, an S-bend over `length` (through 8
        points, turning up to `bend` degrees towards +X and back), and 20 mm more."""
        points = [V(0, 0, 0), V(0, 0, 10), V(0, 0, 20)]
        for i in range(1, 9):
            step = i - 0.5 if i <= 4 else 8.5 - i
            angle = math.radians(bend * step / 4)
            points.append(points[-1] + V(math.sin(angle), 0, math.cos(angle)) * (length / 8))
        points += [points[-1] + V(0, 0, 10), points[-1] + V(0, 0, 20)]
        curve = Part.BSplineCurve()
        curve.interpolate(points, InitialTangent=V(0, 0, 1), FinalTangent=V(0, 0, 1))
        return models.feature(self.doc, "Path", Part.Wire([curve.toShape()]))

    def testCurveWhereOCCTWouldCrashFails(self):
        """A circle of radius 2 along a B-spline with a short S-bend (sBendAlongZ), in Standard,
        Frenet and Binormal mode. Each mode's law uses OCCT's Frenet law, which, evaluated at a
        point where the curve doesn't bend, evaluates itself a little further on: at the middle of
        such an S-bend by a step too small to change the parameter, so it calls itself until the
        stack overflows (ops#413). OCCT finds that point on some of these curves and not on others,
        by the last bits of the numbers (on Windows: 13 of the 16 S-bends below in Standard mode,
        and 1 degree over 0.07 mm and 5 degrees over 0.05 mm in every mode; on macOS, 1 degree
        over 0.07 mm after testShortSBendFolds' corner too). Where it does, the pipe fails before
        any sweep, naming the place and the mode, instead of crashing FreeCAD (round 6 crashed on
        these on Windows, and on macOS in testShortSBendFolds); where it doesn't, OCCT sweeps it
        without crashing. Auxiliary mode without curvilinear equivalence (an auxiliary spine 5 mm
        to the side) holds the same law of the spine: on Windows it crashed FreeCAD on those two
        S-bends (round 7's verification), and fails the same way now, advising curvilinear
        equivalence."""
        refused = []
        everyMode = ((1, 0.07), (5, 0.05))
        for bend in (0.5, 1, 2, 5):
            for length in (0.05, 0.07, 0.105, 0.2):
                modes = ("Standard", "Frenet", "Binormal", "Auxiliary")
                for mode in modes if (bend, length) in everyMode else ("Standard",):
                    with self.subTest(bend=bend, length=length, mode=mode):
                        self.renew()
                        profile = self.profile([models.circle(0, 0, 2)])
                        spine = self.sBendAlongZ(bend, length)
                        auxiliary = {}
                        if mode == "Auxiliary":
                            aside = spine.Shape.copy()
                            aside.translate(V(5, 0, 0))
                            auxiliary = {
                                "AuxiliarySpine": (models.feature(self.doc, "Aside", aside), []),
                                "AuxiliaryCurvilinear": False,
                            }
                        pipe = self.pipe(
                            spine,
                            profile,
                            Mode=mode,
                            Binormal=V(0, 1, 0),
                            Refine=False,
                            **auxiliary,
                        )
                        if self.wouldCrash(pipe):
                            text = pipe.getStatusString()
                            if mode == "Auxiliary":
                                self.assertIn("without curvilinear equivalence", text)
                                self.assertIn("turn on 'Curvilinear equivalence'", text)
                            # At the S-bend's middle, where it turns back
                            place = re.search(r"crash at \(([^)]*)\)", text)[1]
                            x, y, z = (float(value) for value in place.split(","))
                            self.assertLess(abs(x), length)
                            self.assertEqual(y, 0)
                            self.assertAlmostEqual(z, 20 + length / 2, delta=length / 10)
                            refused.append((bend, length, mode))
        self.assertTrue(refused)

    def testFrenetFoldAdvisesAnotherMode(self):
        """Up 30, a 30 degree corner, then a B-spline waving ever wider to the side: Frenet mode
        turns the tilted square over at each place where the curve's bend reverses (60 degrees
        between two of the sweep's places 0.03 mm apart), and the pipe fails as a fold. The advice
        is another mode: a transition change was advised before, and "Round corner" crashes OCCT
        along such curves after a corner (round 7's verification)."""
        corner = V(0, 0, 30)
        leg = V(math.sin(math.radians(30)), 0, math.cos(math.radians(30)))
        points = [
            corner + leg * (0.5 * i) + V(0, 2 * math.sin(i / 6) * i / 120, 0) for i in range(121)
        ]
        curve = Part.BSplineCurve()
        curve.interpolate(points, InitialTangent=leg)
        spine = models.feature(
            self.doc, "Path", Part.Wire([Part.makeLine(V(0, 0, 0), corner), curve.toShape()])
        )
        pipe = self.pipe(spine, Transition="Transformed", Mode="Frenet", Refine=False)
        self.assertFails(pipe, "'Frenet' mode folds", "Use 'Standard' or 'Binormal' mode")
        self.assertNotIn("corner'", pipe.getStatusString())

    def testBudgetRunsOutWarns(self):
        """A circle of radius 2, a 60 degree corner, then a B-spline of 100 waves (about 2000
        mm, no tighter than radius 6.1, wavySpine without its bend): more stretches where the
        tilted section could fold than the budget of places covers. The most fold-prone ones are
        looked at first, and none folds: a valid solid, with a warning that counts the stretches
        left unchecked (round 7's verification: 297)."""
        profile = self.profile([models.circle(0, 0, 2)])
        spine = self.wavySpine(100, bend=False)
        pipe = self.pipe(spine, profile, Transition="Transformed", Refine=False)
        self.assertValidSolid(pipe)
        self.assertIn("Warning", pipe.State)
        text = pipe.getStatusString()
        self.assertIn("bends in too many places to check them all for folds", text)
        self.assertRegex(text, r"\d+ stretches where 'Transformed' could fold")

    def testProfileBeyondTheBendsCentre(self):
        """A square of side 2 centred 10 from the spine's start, along a quarter arc of radius 5
        that bends towards it: beyond the arc's centre, the profile moves backwards as the frame
        turns. The pipe's caps tell its orientation (round 8, ops#396) by how the section moves,
        not by the spine's tangent alone, which faces the other way: a valid solid, 4 * 5 * pi / 2
        by Pappus."""
        arc = Part.Arc(V(0, 0, 0), V(5 - 5 * math.sqrt(0.5), 0, 5 * math.sqrt(0.5)), V(5, 0, 5))
        spine = models.feature(self.doc, "Path", Part.Wire([arc.toShape()]))
        pipe = self.pipe(spine, self.profile(models.rectangle(9, -1, 11, 1)))
        self.assertValidSolid(pipe)
        self.assertAlmostEqual(pipe.Shape.Volume, 10 * math.pi, 3)

    def testManySmallCornersAddUp(self):
        """A circle of radius 2, up 10, then 775 corners of 0.0009 rad 0.05 mm apart (40 degrees in
        all), then a B-spline bending 40 degrees more over 1.54 mm: "Transformed" keeps the
        section's orientation at every corner, so it is tilted 40 degrees to the bend and folds
        (0.67 mm), as after one corner of 40 degrees. Round 4 counted the section as tilted only
        after a corner over 1e-3 rad, didn't look for folds and accepted it (588.80)."""
        points = [V(0, 0, 0), V(0, 0, 10)]
        angle = 0
        for _ in range(775):
            angle += 0.0009
            points.append(points[-1] + V(math.sin(angle), 0, math.cos(angle)) * 0.05)
        leg = V(math.sin(angle), 0, math.cos(angle))
        towards = V(math.cos(angle), 0, -math.sin(angle))
        bend = [points[-1]]
        step = 2.2 * math.radians(40) / 8
        for i in range(1, 9):
            turn = math.radians(40 * (i - 0.5) / 8)
            bend.append(bend[-1] + (leg * math.cos(turn) + towards * math.sin(turn)) * step)
        end = leg * math.cos(math.radians(40)) + towards * math.sin(math.radians(40))
        curve = Part.BSplineCurve()
        curve.interpolate(bend, InitialTangent=leg, FinalTangent=end)
        spine = models.feature(
            self.doc, "Path", Part.Wire(Part.makePolygon(points).Edges + [curve.toShape()])
        )
        pipe = self.pipe(spine, self.profile([models.circle(0, 0, 2)]), Transition="Transformed")
        self.assertFails(pipe, "folds", "along the curve from", "Right corner")

    def testBinormalArcFoldsAtItsEnd(self):
        """Binormal mode, binormal (-0.5, 1, 0.3), a square, a 60 degree corner, then an arc of
        radius 3 turning 60 degrees in a plane tilted 90 degrees: the section folds a little
        (about 0.02 mm) near the arc's end. Round 4's 32 samples missed it, and the pipe passed
        silently, though it crosses itself; now it warns."""
        spine = self.arcAfterACorner(60, 90, 3, 60)
        pipe = self.pipe(
            spine,
            Transition="Transformed",
            Mode="Binormal",
            Binormal=V(-0.5, 1, 0.3),
            Refine=False,
        )
        self.assertFoldWarns(pipe, "arc from (0, 0, 30)")

    def testHintsNameTheCorner(self):
        """The hint of an invalid result names the sharpest corner's angle, not "nearly 90" or
        "nearly back on itself" when it isn't. A square, a 50 degree corner, then an arc of radius
        4 turning 20 degrees in a plane tilted 45 degrees: "Transformed" leaves an invalid solid.
        A 30 degree corner, then a waving B-spline, under "Right corner": OCCT gives no solid.
        Round 4 said "a corner of nearly 90 degrees" and "a corner that turns nearly back on
        itself"."""
        pipe = self.pipe(self.arcAfterACorner(50, 45, 4, 20), Transition="Transformed")
        self.assertFails(pipe, "isn't a valid solid", "(0, 0, 30)", "Right corner")
        self.assertNotIn("nearly 90", pipe.getStatusString())

        self.renew()
        corner = V(0, 0, 30)
        leg = V(math.sin(math.radians(30)), 0, math.cos(math.radians(30)))
        points = [
            corner + leg * (0.5 * i) + V(0, 2 * math.sin(i / 6), 0) * (i / 120) for i in range(121)
        ]
        curve = Part.BSplineCurve()
        curve.interpolate(points, InitialTangent=leg)
        spine = models.feature(
            self.doc, "Path", Part.Wire([Part.makeLine(V(0, 0, 0), corner), curve.toShape()])
        )
        pipe = self.pipe(spine, Transition="Right corner", Refine=False)
        self.assertFails(pipe, "isn't a valid solid", "30 degrees", "(0, 0, 30)", "'Transformed'")
        self.assertNotIn("back on itself", pipe.getStatusString())

    def testSeparateWiresPast90Degrees(self):
        """Two squares side by side (x -5..-1 and 1..5) along an L at 120 degrees: the union of
        both squares' extrusions. Round 3 made each piece of the union one solid of both
        squares' shells, which isn't valid, and failed with a fold's message."""
        points = self.lPoints(120)
        profile = self.profile(models.rectangle(-5, -2, -1, 2) + models.rectangle(1, -2, 5, 2))
        pipe = self.transformed(points, profile=profile)
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertTrue(pipe.Shape.isValid())
        pipe.Shape.check(True)
        faces = [
            Part.Face(Part.makePolygon([V(x, y, 0) for x, y in corners]))
            for corners in (
                [(-5, -2), (-1, -2), (-1, 2), (-5, 2), (-5, -2)],
                [(1, -2), (5, -2), (5, 2), (1, 2), (1, -2)],
            )
        ]
        self.assertSameShape(pipe.Shape, extrusions(self.inSpace(points), Part.makeCompound(faces)))

    def testFixedModePast90DegreesFails(self):
        """"Fixed" mode along an L at 120 degrees: the profile keeps its orientation, and the
        second leg runs back through the first. The one sweep is a solid that BRepCheck passes,
        of volume 320 where the legs' extrusions have 621.5, with nothing in common with them.
        The pipe fails, naming the corner, with Refine on or off. Round 5 failed it only with
        Refine on, where refine left an invalid solid; since ops#389 refine keeps the unrefined
        shape then, and the pipe was Up-to-date. At 60 degrees: the legs' extrusions."""
        for transition in ("Right corner", "Transformed"):
            for refine in (False, True):
                with self.subTest(transition=transition, refine=refine):
                    self.renew()
                    spine = self.spine(self.lPoints(120))
                    pipe = self.pipe(spine, Mode="Fixed", Transition=transition, Refine=refine)
                    phrases = ("'Fixed' mode", "at (0, 0, 30)", "run back", "'Standard'")
                    self.assertFails(pipe, *phrases)

        self.renew()
        points = self.lPoints(60)
        pipe = self.pipe(self.spine(points), Mode="Fixed", Refine=False)
        self.assertValidSolid(pipe)
        self.assertSameShape(pipe.Shape, extrusions(self.inSpace(points)))

    def testUnionThatCannotFuseFails(self):
        """A circle, a 120 degree corner, then an arc of radius 10 turning 30 more: the pieces
        are valid, but OCCT can't fuse a round piece along an arc with the first. The pipe fails
        with the advice to use "Right corner", not "Null shape". If a later OCCT fuses it, the
        union must be one valid solid."""
        spine, _ = self.curvedSpine(120, 30)
        pipe = self.pipe(spine, self.profile([models.circle(0, 0, 2)]), Transition="Transformed")
        if pipe.isValid():
            self.assertValidSolid(pipe)
        else:
            self.assertFails(pipe, "can't be fused", "Right corner")
            self.assertNotIn("Null shape", pipe.getStatusString())


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
                # the last turn 20 degrees: at 30 the fourth leg would run at 90 degrees to the
                # profile, which "Transformed" refuses (fork PR 344)
                points = bendPoints(40, 20, towards, 20)
                path, pipe = self.pipe(points, True)
                x, z = bendPoints(40, 20, False, 20)[3]
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


def tubeDistance(shape, spine, radius, samples=200):
    """The largest | distance from the spine - radius | over points of the shape's lateral faces"""
    worst = 0.0
    for face in shape.Faces:
        if face.Surface.TypeId != "Part::GeomBSplineSurface":
            continue
        u0, u1, v0, v1 = face.ParameterRange
        for i in range(samples):
            v = v0 + (v1 - v0) * (i + 0.5) / samples
            for j in range(8):
                point = face.valueAt(u0 + (u1 - u0) * j / 8, v)
                worst = max(worst, abs(spine.distToShape(Part.Vertex(point))[0] - radius))
    return worst


class TestPipeAlongTiltedWaves(unittest.TestCase):
    """A Pipe in Standard mode (corrected Frenet) of a circle along ten planar waves (200 spans),
    sketched on a plane turned 45 degrees about X (ops#448). At OCCT's default degree and segments
    the approximation of the swept surface depended on the rounding noise of the orientation: the
    tube came out 1.9e-2 mm off, where the same pipe on the XZ plane is within 1e-4. The circle is
    centred on the spine's start and normal to it, so the pipe is the tube of points 2 mm from the
    spine."""

    def setUp(self):
        self.doc = models.newDocument("PartDesignTestPipeAlongTiltedWaves")
        self.body = models.body(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def pipe(self, turn):
        """The pipe along the waves, sketched on the XZ plane turned by `turn` about the origin;
        the profile's sketch is normal to the waves' start (Z, turned)"""
        points = [V(1.5 * (1 - math.cos(2 * math.pi * s / 20.0)), s, 0) for s in range(201)]
        waves = Part.BSplineCurve()
        waves.interpolate(points)
        spine = models.sketch(
            self.doc, "Waves", [waves], self.body, placement=App.Placement(V(), turn) * XZ
        )
        profile = models.sketch(
            self.doc, "Circle", [models.circle(0, 0, 2)], self.body, placement=App.Placement(V(), turn)
        )
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (spine, [])
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertTrue(pipe.Shape.isValid())
        self.assertLess(tubeDistance(pipe.Shape, spine.Shape, 2.0), 1e-4)
        return pipe

    def testTiltedWavesGiveTheTube(self):
        """The pipe on the tilted plane is the tube, with the volume of the pipe on the XZ plane
        (Shape.Volume's default integration is itself 0.3 % off on such long pipes, ops#414)"""
        control = self.pipe(App.Rotation()).Shape.Volume
        self.tearDown()
        self.setUp()
        tilted = self.pipe(App.Rotation(V(1, 0, 0), 45.0)).Shape.Volume
        self.assertAlmostEqual(tilted / control, 1.0, delta=1e-5)


class TestLoosePipeWarns(unittest.TestCase):
    """Pipes whose swept surface OCCT approximates poorly, reported only through the result's
    tolerance: the Pipe builds, with a warning naming it (ops#448, fork PR 373's review)."""

    def setUp(self):
        self.doc = models.newDocument("PartDesignTestLoosePipeWarns")
        self.body = models.body(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assertWarns(self, pipe):
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertIn("Warning", pipe.getStatusString())
        self.assertIn("pipe's result has a tolerance of", pipe.getStatusString())

    def testLongSpiral(self):
        """A circle of radius 0.5 along a 3D spiral through 1000 points (radius 10 to 30 mm,
        rising 0.05 mm a point; curvature radius at least 10 mm), Standard mode: at degree 14 it
        builds 0.43 mm off the tube with tolerances of 2 mm (at OCCT's default degree it failed to
        build). Before, the Pipe was "Valid" with no warning"""
        points = [
            V((10 + 0.02 * i) * math.cos(i * 0.05), (10 + 0.02 * i) * math.sin(i * 0.05), 0.05 * i)
            for i in range(1000)
        ]
        curve = Part.BSplineCurve()
        curve.interpolate(points)
        spine = models.feature(self.doc, "Spiral", Part.Wire([curve.toShape()]))
        start = curve.value(curve.FirstParameter)
        tangent = curve.tangent(curve.FirstParameter)[0]
        profile = models.sketch(
            self.doc,
            "Circle",
            [models.circle(0, 0, 0.5)],
            self.body,
            placement=App.Placement(start, App.Rotation(V(0, 0, 1), tangent)),
        )
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (spine, ["Edge1"])
        self.assertWarns(pipe)

    def testTwistedSquareAlongAnAuxiliarySpine(self):
        """A square of side 2 along a 50 mm line up Z, a helix of radius 5 and pitch 50 as
        curvilinear auxiliary spine (Auxiliary mode): at PartDesign's 3D tolerance of 1e-7 the
        sides are 0.11 mm off the turning square, tolerance 0.15 (0.21 at OCCT's default degree).
        Before, the Pipe was "Valid" with no warning"""
        spine = models.feature(
            self.doc, "Line", Part.Wire([Part.LineSegment(V(0, 0, 0), V(0, 0, 50)).toShape()])
        )
        helix = models.feature(self.doc, "Helix", Part.Wire([Part.makeHelix(50, 50, 5)]))
        profile = models.sketch(self.doc, "Square", models.rectangle(-1, -1, 1, 1), self.body)
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (spine, ["Edge1"])
        pipe.Mode = "Auxiliary"
        pipe.AuxiliarySpine = (helix, ["Edge1"])
        pipe.AuxiliaryCurvilinear = True
        self.assertWarns(pipe)
