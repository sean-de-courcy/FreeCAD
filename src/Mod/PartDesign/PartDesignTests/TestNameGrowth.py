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

"""The full form of an element name must not multiply with each split of its element
(FreeCAD-CH, ops#640).

A piece of a split face is named `<the face's name before>|...;MOD;<marks>`, the marks being the
names of the neighbours that tell the pieces apart. An edge that a dress-up leaves on the face is
named from the face as it was then. Taken as a mark, it writes the face's history out again in the
piece's name: with one such edge per split the full form grew 2.62 times per split (17.8 MB after
12 splits of one face in this model; 0.5 GB for one face of a real part after seven).

The model (designed, no file): a plate whose top face is split ROUNDS times. Each round cuts a
ring-shaped groove into the top face (an island: the face is split into the outside and the
island) and, in the chamfered variant, chamfers the groove's outer rim, which leaves an edge on the
top face that is named from that face.

Expected, by construction: the chamfer's edge says nothing about the outside piece that its own
name before doesn't say, so the chamfered model's top-face name is no longer than a small multiple
of the unchamfered model's, where every mark is a name of the plate or of a groove (the names there
grow by one section per round). Lengths are measured in full form without writing a name out: the
name table's references are walked with a memo.
"""

import re
import unittest

import FreeCAD as App
import Part
import Sketcher

ROUNDS = 8
PLATE_HEIGHT = 10.0
PITCH = 20.0
REF = re.compile(r"~([0-9a-v]{13})")


def fullLength(name, memo):
    """The length of the full form of the interned name `name`, without its escapes"""

    def node(nameId):
        if nameId not in memo:
            entry = App.getNameTableEntry(nameId)
            memo[nameId] = body(entry[0]) if entry else 14
        return memo[nameId]

    def body(text):
        return len(REF.sub("", text)) + sum(node(nameId) for nameId in REF.findall(text))

    return body(name)


class TestNameGrowth(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("NameGrowth")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def sketch(self, body, name, z, make):
        sketch = body.newObject("Sketcher::SketchObject", name)
        plane = [o for o in body.Origin.OriginFeatures if o.Role == "XY_Plane"][0]
        sketch.AttachmentSupport = (plane, [""])
        sketch.MapMode = "FlatFace"
        sketch.AttachmentOffset = App.Placement(App.Vector(0, 0, z), App.Rotation())
        make(sketch)
        return sketch

    def topFace(self, shape):
        """The index of the largest face in the plate's top plane: the outside piece"""
        tops = [
            i
            for i, f in enumerate(shape.Faces)
            if abs(f.BoundBox.ZMin - PLATE_HEIGHT) < 1e-6 and abs(f.BoundBox.ZMax - PLATE_HEIGHT) < 1e-6
        ]
        return max(tops, key=lambda i: shape.Faces[i].Area)

    def build(self, chamfered):
        """The plate after ROUNDS grooves: (the body, the top face's full name length per round)"""
        doc = self.doc
        body = doc.addObject("PartDesign::Body", "Chamfered" if chamfered else "Plain")
        width = PITCH * (ROUNDS + 1)

        def rectangle(sketch):
            p = [App.Vector(0, 0), App.Vector(width, 0), App.Vector(width, 40), App.Vector(0, 40)]
            for i in range(4):
                sketch.addGeometry(Part.LineSegment(p[i], p[(i + 1) % 4]))
            for i in range(4):
                sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))

        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.sketch(body, "Base", 0, rectangle)
        pad.Length = PLATE_HEIGHT
        doc.recompute()
        memo = {}
        lengths = []
        for k in range(1, ROUNDS + 1):

            def ring(sketch, k=k):
                for radius in (4, 2):
                    sketch.addGeometry(
                        Part.Circle(App.Vector(PITCH * k, 20, 0), App.Vector(0, 0, 1), radius)
                    )

            cut = body.newObject("PartDesign::Pocket", "Cut%d" % k)
            cut.Profile = self.sketch(body, "Ring%d" % k, PLATE_HEIGHT, ring)
            cut.Length = 2
            doc.recompute()
            self.assertTrue(cut.isValid(), cut.getStatusString())
            if chamfered:
                shape = cut.Shape
                rim = [
                    "Edge%d" % (i + 1)
                    for i, e in enumerate(shape.Edges)
                    if hasattr(e.Curve, "Radius")
                    and abs(e.Curve.Radius - 4) < 1e-6
                    and abs(e.Curve.Center.z - PLATE_HEIGHT) < 1e-6
                    and abs(e.Curve.Center.x - PITCH * k) < 1e-6
                ]
                self.assertEqual(len(rim), 1, "the groove's outer rim on the top face")
                chamfer = body.newObject("PartDesign::Chamfer", "Chamfer%d" % k)
                chamfer.Base = (cut, rim)
                chamfer.Size = 0.3
                doc.recompute()
                self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
            shape = body.Tip.Shape
            name = shape.ElementReverseMap["Face%d" % (self.topFace(shape) + 1)]
            names = name if isinstance(name, (list, tuple)) else [name]
            lengths.append(max(fullLength(n, memo) for n in names))
        return body, lengths

    def testASplitFaceNameDoesNotMultiplyPerSplit(self):
        """A face split again and again after a dress-up on it: its name grows by a section per
        split, as without the dress-ups, not by a factor"""
        _, plain = self.build(False)
        body, chamfered = self.build(True)
        # the unchamfered model's steps: each round adds one section holding the marks
        self.assertLess(plain[-1], 2 * ROUNDS * plain[0], plain)
        # the chamfers add no history to the name (before: 379602 against 3017 at 8 rounds)
        self.assertLess(chamfered[-1], 2 * plain[-1], (chamfered, plain))
        # and the last step is far from the old factor of 2.62
        self.assertLess(chamfered[-1], 1.5 * chamfered[-2], chamfered)

    def testThePiecesOfASplitFaceKeepNamesOfTheirOwn(self):
        """The outside piece and every island are told apart: no two faces share a name, and
        every face has one"""
        body, _ = self.build(True)
        shape = body.Tip.Shape
        reverse = shape.ElementReverseMap
        seen = {}
        for i in range(1, len(shape.Faces) + 1):
            key = "Face%d" % i
            self.assertIn(key, reverse, "a face without a name")
            name = reverse[key]
            for n in name if isinstance(name, (list, tuple)) else [name]:
                self.assertNotIn(n, seen, "%s and %s share a name" % (key, seen.get(n)))
                seen[n] = key
        # the islands: one per round, each a disc of radius 2 in the top plane
        islands = [
            f
            for f in shape.Faces
            if abs(f.BoundBox.ZMin - PLATE_HEIGHT) < 1e-6
            and abs(f.BoundBox.ZMax - PLATE_HEIGHT) < 1e-6
            and abs(f.BoundBox.XLength - 4) < 1e-6
        ]
        self.assertEqual(len(islands), ROUNDS)
