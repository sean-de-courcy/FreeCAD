# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD as App
import Part

import unittest


class TopoShapeAssertions:

    def assertAttrEqual(self, toposhape, attr_value_list, msg=None):
        for attr, value in attr_value_list:
            result = toposhape.__getattribute__(attr)  # Look up each attribute by string name
            if result.__str__() != value.__str__():
                if msg == None:
                    msg = (f"TopoShape {attr} is incorrect:  {result} should be {value}",)
                raise AssertionError(msg)

    def assertAttrAlmostEqual(self, toposhape, attr_value_list, places=5, msg=None):
        range = 1 / 10**places
        for attr, value in attr_value_list:
            result = toposhape.__getattribute__(attr)  # Look up each attribute by string name
            if abs(result - value) > range:
                if msg == None:
                    msg = f"TopoShape {attr} is incorrect:  {result} should be {value}"
                raise AssertionError(msg)

    def assertAttrCount(self, toposhape, attr_value_list, msg=None):
        for attr, value in attr_value_list:
            result = toposhape.__getattribute__(attr)  # Look up each attribute by string name
            if len(result) != value:
                if msg == None:
                    msg = f"TopoShape {attr} is incorrect:  {result} should have {value} elements"
                raise AssertionError(msg)

    def assertKeysInMap(self, map, keys, msg=None):
        for key in keys:
            if not key in map:
                if msg == None:
                    msg = f"Key {key} not found in map:  {map}"
                raise AssertionError(msg)

    def assertAllElementsMapped(self, shape, msg=None):
        """Every face, edge and vertex of the shape has a mapped name. How many names an
        element has is an implementation detail of the naming algorithm, so tests don't
        count them."""
        reverse_map = shape.ElementReverseMap
        unmapped = [
            f"{kind}{index}"
            for kind, elements in (
                ("Face", shape.Faces),
                ("Edge", shape.Edges),
                ("Vertex", shape.Vertexes),
            )
            for index in range(1, len(elements) + 1)
            if f"{kind}{index}" not in reverse_map
        ]
        if unmapped:
            if msg == None:
                msg = f"Elements without a mapped name: {unmapped}"
            raise AssertionError(msg)

    def assertBounds(self, shape, bounds, msg=None, precision=App.Base.Precision.confusion() * 100):
        shape_bounds = shape.BoundBox
        shape_bounds_max = App.BoundBox(shape_bounds)
        shape_bounds_max.enlarge(precision)
        bounds_max = App.BoundBox(bounds)
        bounds_max.enlarge(precision)
        if not (shape_bounds_max.isInside(bounds) and bounds_max.isInside(shape_bounds)):
            if msg == None:
                msg = f"Bounds {shape_bounds} doesn't match {bounds}"
            raise AssertionError(msg)


def makeSquareFace():
    """A face that Python code makes from a square wire (tag 11, no element map).

    V2 names: the edges and vertices keep the wire's unmapped names
    ('Edge1;_;11;MKR;0;E;0;IDX,SRC;_'), and the face is new, with the untagged name
    '_;<its edge names>;0;FAC;0;F;0;LOW,NDU;_'. Tag 0 means "not yet tagged": the object or
    shape that takes the face gives it its own tag.
    """
    wire = Part.makePolygon(
        [
            App.Vector(0, 0, 0),
            App.Vector(10, 0, 0),
            App.Vector(10, 10, 0),
            App.Vector(0, 10, 0),
            App.Vector(0, 0, 0),
        ]
    )
    wire.Tag = 11
    return Part.makeFace([wire], "Part::FaceMakerBullseye")


def squareFaceName(face, tag):
    """The square face's name with the given tag, from the names of its edges."""
    return App.makeEncodedSection(
        linkedNames=[face.ElementReverseMap[f"Edge{index}"] for index in range(1, 5)],
        iterationTag=str(tag),
        opCode="FAC",
        elementType="F",
        mapperFlags=["LOW", "NDU"],
    )


class SquareFaceFeature:
    """Proxy of a Part::FeaturePython whose shape is makeSquareFace()."""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        obj.Shape = makeSquareFace()


def makeFeatureInputs(doc):
    """Input objects for the features of makeFeature, by name."""
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 10
    shifted = doc.addObject("Part::Box", "Shifted")
    shifted.Length = shifted.Width = shifted.Height = 10
    shifted.Placement.Base = App.Vector(5, 5, 5)
    plane = doc.addObject("Part::Plane", "Plane")
    plane.Length = plane.Width = 10
    bottom = doc.addObject("Part::Circle", "Bottom")
    bottom.Radius = 5
    top = doc.addObject("Part::Circle", "Top")
    top.Radius = 3
    top.Placement.Base = App.Vector(0, 0, 10)
    spine = doc.addObject("Part::Line", "Spine")
    spine.X2, spine.Y2, spine.Z2 = 0, 0, 10
    near = doc.addObject("Part::Line", "Near")
    near.X2 = 10
    far = doc.addObject("Part::Line", "Far")
    far.X1, far.Y1 = 0, 10
    far.X2, far.Y2, far.Z2 = 10, 10, 5
    prism = doc.addObject("Part::Extrusion", "Prism")
    prism.Base = plane
    prism.DirMode = "Custom"
    prism.Dir = App.Vector(0, 0, 1)
    prism.LengthFwd = 5
    prism.Solid = True
    return {
        "box": box,
        "shifted": shifted,
        "plane": plane,
        "bottom": bottom,
        "top": top,
        "spine": spine,
        "near": near,
        "far": far,
        "prism": prism,
    }


# Part features and the op code of the sections their own operation adds. None: it adds none in
# these models (a mirror keeps its input's names), or, for the tapered extrusion, it had the right
# tag already.
FEATURE_OP_CODES = {
    "Part::Offset": "OFS",
    "Part::Offset2D": "OFF",
    "Part::Thickness": "THK",
    "Part::RuledSurface": "RSF",
    "Part::Loft": "LFT",
    "Part::Sweep": "SWP",
    "Part::Revolution": "RVL",
    "Part::Fillet": "FLT",
    "Part::Mirroring": None,
    "Part::MultiCommon": "CMN",
    "Part::Compound": None,
    "Part::Extrusion": None,
}


def makeFeature(doc, inputs, featureType, name):
    """A feature of the given type on the inputs of makeFeatureInputs."""
    feature = doc.addObject(featureType, name)
    if featureType == "Part::Offset":
        feature.Source = inputs["box"]
        feature.Value = 1
    elif featureType == "Part::Offset2D":
        feature.Source = inputs["plane"]
        feature.Value = 1
    elif featureType == "Part::Thickness":
        feature.Faces = (inputs["box"], ["Face6"])
        feature.Value = 1
    elif featureType == "Part::RuledSurface":
        feature.Curve1 = (inputs["near"], ["Edge1"])
        feature.Curve2 = (inputs["far"], ["Edge1"])
    elif featureType == "Part::Loft":
        feature.Sections = [inputs["bottom"], inputs["top"]]
    elif featureType == "Part::Sweep":
        feature.Sections = [inputs["bottom"]]
        feature.Spine = (inputs["spine"], ["Edge1"])
    elif featureType == "Part::Revolution":
        feature.Source = inputs["plane"]
        feature.Axis = App.Vector(0, 1, 0)
        feature.Angle = 90
    elif featureType == "Part::Fillet":
        feature.Base = inputs["box"]
        feature.Edges = [(1, 1.0, 1.0)]
    elif featureType == "Part::Mirroring":
        feature.Source = inputs["prism"]
        feature.Normal = App.Vector(1, 0, 0)
    elif featureType == "Part::MultiCommon":
        feature.Shapes = [inputs["box"], inputs["shifted"]]
    elif featureType == "Part::Compound":
        feature.Links = [inputs["box"], inputs["plane"]]
    elif featureType == "Part::Extrusion":
        # tapered, so it lofts through ExtrusionHelper::makeElementDraft
        feature.Base = inputs["plane"]
        feature.DirMode = "Custom"
        feature.Dir = App.Vector(0, 0, 1)
        feature.LengthFwd = 5
        feature.Solid = True
        feature.TaperAngle = 10
    return feature


def decodedSections(mappedName):
    """Every section of a V2 name, with the sections of the names it links to."""
    for section in App.getDecodedMappedName(mappedName):
        yield section
        for linkedName in section["linkedNames"]:
            yield from decodedSections(linkedName)


def isOwnSection(section, opCode):
    """Whether a decoded section is one the operation with the op code added. An unchanged
    input element referenced by its index (IDX) keeps the input's tag, whatever the op."""
    return section["opCode"] == opCode and "IDX" not in section["mapperFlags"]


def ownSectionNames(shape, opCode):
    """The shape's mapped names that have a section the operation with the op code added."""
    return {
        name
        for name in shape.ElementMap
        if any(isOwnSection(section, opCode) for section in decodedSections(name))
    }


class TopoShapeTest(unittest.TestCase, TopoShapeAssertions):
    def setUp(self):
        """Create a document and some TopoShapes of various types"""
        self.doc = App.newDocument("TopoShape")
        # self.box = Part.makeBox(1, 2, 2)
        # Part.show(self.box, "Box1")
        # self.box2 = Part.makeBox(2, 1, 2)
        # Part.show(self.box2, "Box2")
        # Even on LS3 these boxes have no element maps.
        self.doc.addObject("Part::Box", "Box1")
        self.doc.Box1.Length = 1
        self.doc.Box1.Width = 2
        self.doc.Box1.Height = 2
        self.doc.addObject("Part::Box", "Box2")
        self.doc.Box2.Length = 2
        self.doc.Box2.Width = 1
        self.doc.Box2.Height = 2
        self.doc.addObject("Part::Cylinder", "Cylinder1")
        self.doc.Cylinder1.Radius = 0.5
        self.doc.Cylinder1.Height = 2
        self.doc.Cylinder1.Angle = 360
        self.doc.addObject("Part::Compound", "Compound1")
        self.doc.Compound1.Links = [self.doc.Box1, self.doc.Box2]

        self.doc.recompute()
        self.box = self.doc.Box1.Shape
        self.box2 = self.doc.Box2.Shape

    def tearDown(self):
        App.closeDocument("TopoShape")

    def testTopoShapeBox(self):
        # Arrange our test TopoShape
        box2_toposhape = self.doc.Box2.Shape
        # Arrange list of attributes and values to string match
        attr_value_list = [
            ["BoundBox", App.BoundBox(0, 0, 0, 2, 1, 2)],
            ["CenterOfGravity", App.Vector(1, 0.5, 1)],
            ["CenterOfMass", App.Vector(1, 0.5, 1)],
            ["CompSolids", []],
            ["Compounds", []],
            [
                "Content",
                "<ElementMap/>\n",
            ],  # Our element map is empty, or there would be more here.
            ["ElementMap", {}],
            ["ElementReverseMap", {}],
            ["Hasher", None],
            [
                "MatrixOfInertia",
                App.Matrix(1.66667, 0, 0, 0, 0, 2.66667, 0, 0, 0, 0, 1.66667, 0, 0, 0, 0, 1),
            ],
            ["Module", "Part"],
            ["Orientation", "Forward"],
            # ['OuterShell', {}],    # Todo: Could verify that a Shell Object is returned
            ["Placement", App.Placement()],
            [
                "PrincipalProperties",
                {
                    "SymmetryAxis": True,
                    "SymmetryPoint": False,
                    "Moments": (
                        2.666666666666666,
                        1.666666666666667,
                        1.666666666666667,
                    ),
                    "FirstAxisOfInertia": App.Vector(0.0, 1.0, 0.0),
                    "SecondAxisOfInertia": App.Vector(0.0, 0.0, 1.0),
                    "ThirdAxisOfInertia": App.Vector(1.0, 0.0, 0.0),
                    "RadiusOfGyration": (
                        0.816496580927726,
                        0.6454972243679029,
                        0.6454972243679029,
                    ),
                },
            ],
            ["ShapeType", "Solid"],
            [
                "StaticMoments",
                (3.999999999999999, 1.9999999999999996, 3.999999999999999),
            ],
            # ['Tag', 0],    # Gonna vary, so can't really assert, except maybe != 0?
            ["TypeId", "Part::TopoShape"],
        ]
        # Assert all the expected values match when converted to strings.
        self.assertAttrEqual(box2_toposhape, attr_value_list)

        # Arrange list of attributes and values to match within 5 decimal places
        attr_value_list = [
            ["Area", 16.0],
            ["ElementMapSize", 0],
            ["Length", 40.0],  # Sum of all edges of each face, so some redundancy.
            ["Mass", 4.0],
            # ['MemSize', 13824],  # Platform variations in this size.
            ["Volume", 4.0],
        ]
        # Assert all the expected values match
        self.assertAttrAlmostEqual(box2_toposhape, attr_value_list, 5)

        # Arrange list of attributes to check list lengths
        attr_value_list = [
            ["Edges", 12],
            ["Faces", 6],
            ["Shells", 1],
            ["Solids", 1],
            ["SubShapes", 1],
            ["Vertexes", 8],
            ["Wires", 6],
        ]
        # Assert all the expected values match
        self.assertAttrCount(box2_toposhape, attr_value_list)

    def testTopoShapeElementMap(self):
        """Tests TopoShape elementMap"""
        # Arrange
        # Act No elementMaps exist in base shapes until we perform an operation.
        compound1 = Part.Compound([self.doc.Objects[-1].Shape, self.doc.Objects[-2].Shape])
        self.doc.addObject("Part::Compound", "Compound")
        self.doc.Compound.Links = [
            App.activeDocument().Box1,
            App.activeDocument().Box2,
        ]
        self.doc.recompute()
        compound2 = self.doc.Compound.Shape
        # Assert elementMap
        # Todo: This should contain something as soon as the Python interface
        #  for Part.Compound TNP exists
        # self.assertAllElementsMapped(compound1)
        # 2 cubes of 26 elements each: 6 Faces, 12 Edges, 8 Vertexes
        self.assertAllElementsMapped(compound2)
        # Assert Shape
        self.assertBounds(compound2, App.BoundBox(0, 0, 0, 2, 2, 2))

    def testPartCompoundOfUnmappedShapesNames(self):
        """In V2, each element of a Part::Compound of two boxes (no element maps) is named as
        an unmapped element of its box: '<box element>;_;<box ID>;MKR;0;<type>;0;IDX,SRC;_'.
        The second box's elements follow the first box's (ops#24)."""
        doc = App.newDocument("CompoundOfBoxes")
        try:
            doc.HistoryAlgorithm = "V2"
            box1 = doc.addObject("Part::Box", "Box1")
            box2 = doc.addObject("Part::Box", "Box2")
            box2.Placement.Base = App.Vector(2, 0, 0)
            compound = doc.addObject("Part::Compound", "Compound")
            compound.Links = [box1, box2]
            doc.recompute()
            shape = compound.Shape
            reverse_map = shape.ElementReverseMap
            for kind, count in (("Face", 6), ("Edge", 12), ("Vertex", 8)):
                for offset, box in ((0, box1), (count, box2)):
                    for index in range(1, count + 1):
                        with self.subTest(element=f"{kind}{offset + index}"):
                            expected = App.makeEncodedSection(
                                referenceIDs=[f"{kind}{index}"],
                                iterationTag=str(box.ID),
                                opCode="MKR",
                                elementType=kind[0],
                                mapperFlags=["IDX", "SRC"],
                            )
                            self.assertEqual(reverse_map.get(f"{kind}{offset + index}"), expected)
        finally:
            App.closeDocument(doc.Name)

    def testPartCommon(self):
        # Arrange
        self.doc.addObject("Part::MultiCommon", "Common")
        self.doc.Common.Shapes = [self.doc.Box1, self.doc.Box2]
        # Act
        self.doc.recompute()
        common1 = self.doc.Common.Shape
        # Assert elementMap
        self.assertKeysInMap(
            common1.ElementReverseMap,
            [
                "Edge1",
                "Edge2",
                "Edge3",
                "Edge4",
                "Edge5",
                "Edge6",
                "Edge7",
                "Edge8",
                "Edge9",
                "Edge10",
                "Edge11",
                "Edge12",
                "Face1",
                "Face2",
                "Face3",
                "Face4",
                "Face5",
                "Face6",
                "Vertex1",
                "Vertex2",
                "Vertex3",
                "Vertex4",
                "Vertex5",
                "Vertex6",
                "Vertex7",
                "Vertex8",
            ],
        )
        # Assert Shape
        self.assertBounds(common1, App.BoundBox(0, 0, 0, 1, 1, 2))

    def testPartCut(self):
        # Arrange
        self.doc.addObject("Part::Cut", "Cut")
        self.doc.Cut.Base = self.doc.Box1
        self.doc.Cut.Tool = self.doc.Box2
        # Act
        self.doc.recompute()
        cut1 = self.doc.Cut.Shape
        # Assert elementMap
        self.assertKeysInMap(
            cut1.ElementReverseMap,
            [
                "Edge1",
                "Edge2",
                "Edge3",
                "Edge4",
                "Edge5",
                "Edge6",
                "Edge7",
                "Edge8",
                "Edge9",
                "Edge10",
                "Edge11",
                "Edge12",
                "Face1",
                "Face2",
                "Face3",
                "Face4",
                "Face5",
                "Face6",
                "Vertex1",
                "Vertex2",
                "Vertex3",
                "Vertex4",
                "Vertex5",
                "Vertex6",
                "Vertex7",
                "Vertex8",
            ],
        )
        # Assert Shape
        self.assertBounds(cut1, App.BoundBox(0, 1, 0, 1, 2, 2))

    def testPartFuse(self):
        # Arrange
        self.doc.addObject("Part::Fuse", "Fuse")
        self.doc.Fuse.Refine = False
        self.doc.Fuse.Base = self.doc.Box1
        self.doc.Fuse.Tool = self.doc.Box2
        # Act
        self.doc.recompute()
        fuse1 = self.doc.Fuse.Shape
        # Assert elementMap
        self.assertAllElementsMapped(fuse1)
        self.doc.Fuse.Refine = True
        self.doc.recompute()
        fuse2 = self.doc.Fuse.Shape
        self.assertAllElementsMapped(fuse2)
        # Refined, the shape is an extruded L, with 8 Faces, 12 Vertexes, 18 Edges
        self.assertAttrCount(fuse2, [["Faces", 8], ["Edges", 18], ["Vertexes", 12]])
        # Assert Shape
        self.assertBounds(fuse1, App.BoundBox(0, 0, 0, 2, 2, 2))
        self.assertBounds(fuse2, App.BoundBox(0, 0, 0, 2, 2, 2))

    def testAppPartMakeCompound(self):
        # This doesn't do element maps.
        # compound1 = Part.Compound([self.doc.Box1.Shape, self.doc.Box2.Shape])
        # Act
        compound1 = Part.makeCompound([self.doc.Box1.Shape, self.doc.Box2.Shape])
        # Assert elementMap
        self.assertAllElementsMapped(compound1)
        # Assert Shape
        self.assertBounds(compound1, App.BoundBox(0, 0, 0, 2, 2, 2))

    def testAppPartMakeShell(self):
        # Act
        shell1 = Part.makeShell(self.doc.Box1.Shape.Faces)
        # Assert elementMap
        self.assertEqual(shell1.ElementMapSize, 26)
        # Assert Shape
        self.assertBounds(shell1, App.BoundBox(0, 0, 0, 1, 2, 2))

    def testAppPartMakeFace(self):
        # Act
        face1 = Part.makeFace(self.doc.Box1.Shape.Faces[0], "Part::FaceMakerCheese")
        # Assert elementMap
        self.assertEqual(face1.ElementMapSize, 10)
        # Assert Shape
        self.assertBounds(face1, App.BoundBox(0, 0, 0, 0, 2, 2))

    def testAppPartmakeFilledFace(self):
        face1 = Part.makeFilledFace(self.doc.Box1.Shape.Faces[3].Edges)
        # Assert elementMap
        self.assertEqual(face1.ElementMapSize, 9)
        # Assert Shape
        self.assertBounds(face1, App.BoundBox(-0.05, 2, -0.1, 1.05, 2, 2.1))

    def testAppPartMakeSolid(self):
        # Act
        solid1 = Part.makeSolid(self.doc.Box1.Shape.Shells[0])
        # Assert elementMap
        self.assertEqual(solid1.ElementMapSize, 26)
        # Assert Shape
        self.assertBounds(solid1, App.BoundBox(0, 0, 0, 1, 2, 2))

    def testAppPartMakeRuled(self):
        # Act
        surface1 = Part.makeRuledSurface(*self.doc.Box1.Shape.Edges[3:5])
        # Assert elementMap
        self.assertEqual(surface1.ElementMapSize, 9)
        # Assert Shape
        self.assertBounds(surface1, App.BoundBox(0, 0, 0, 1, 2, 2))

    def testAppPartMakeShellFromWires(self):
        # Arrange
        wire1 = self.doc.Box1.Shape.Wires[0]  # .copy() Todo: prints 2 gen/mod warn because
        wire2 = self.doc.Box1.Shape.Wires[1]  # Todo: copy() isn't TNP yet.  Fix when it is.
        # Act
        shell1 = Part.makeShellFromWires([wire1, wire2])
        # Assert elementMap
        self.assertEqual(shell1.ElementMapSize, 24)
        # Assert Shape
        self.assertBounds(shell1, App.BoundBox(0, 0, 0, 1, 2, 2))

    def testAppPartMakeSweepSurface(self):
        # Arrange
        circle = Part.makeCircle(5, App.Vector(0, 0, 0))
        path = Part.makeLine(App.Vector(), App.Vector(0, 0, 10))
        Part.show(circle, "Circle")  # Trigger the elementMapping
        Part.show(path, "Path")  # Trigger the elementMapping
        del circle
        # Act
        surface1 = Part.makeSweepSurface(self.doc.Path.Shape, self.doc.Circle.Shape, 0.001, 0)
        Part.show(surface1, "Sweep")
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(surface1.ElementMapSize, 6)
        self.assertBounds(surface1, App.BoundBox(-5, -5, 0, 5, 5, 10), precision=2)
        del surface1

    def testAppPartMakeLoft(self):
        # Act
        solid1 = Part.makeLoft(self.doc.Box1.Shape.Wires[0:2])
        # Assert elementMap
        self.assertEqual(solid1.ElementMapSize, 24)
        # Assert Shape
        self.assertBounds(solid1, App.BoundBox(0, 0, 0, 1, 2, 2))

    def testAppPartMakeSplitShape(self):
        # Todo: Refine this test after all TNP code in place to eliminate warnings.
        # Arrange
        edge1 = self.doc.Box1.Shape.Faces[0].Edges[0].translated(App.Vector(0, 0.5, 0))
        face1 = self.doc.Box1.Shape.Faces[0]
        # Act
        solids1 = Part.makeSplitShape(face1, [(edge1, face1)])
        # Assert elementMap
        self.assertEqual(len(solids1), 2)
        self.assertEqual(len(solids1[0]), 1)
        self.assertEqual(solids1[0][0].ElementMapSize, 9)
        self.assertEqual(solids1[1][0].ElementMapSize, 9)
        # Assert Shape
        self.assertBounds(solids1[0][0], App.BoundBox(0, 0.5, 0, 0, 2, 2))
        self.assertBounds(solids1[1][0], App.BoundBox(0, 0.5, 0, 0, 2, 2))

    def testTopoShapePyInit(self):
        # Arrange
        self.doc.addObject("Part::Compound", "Compound")
        self.doc.Compound.Links = [
            App.activeDocument().Box1,
            App.activeDocument().Box2,
        ]
        self.doc.recompute()
        compound = self.doc.Compound.Shape
        # Act
        new_toposhape = Part.Shape(compound)
        new_empty_toposhape = Part.Shape()
        # Assert elementMap
        self.assertAllElementsMapped(compound)
        self.assertAllElementsMapped(new_toposhape)

    def testTopoShapeCopy(self):
        # Arrange
        self.doc.addObject("Part::Compound", "Compound")
        self.doc.Compound.Links = [
            App.activeDocument().Box1,
            App.activeDocument().Box2,
        ]
        self.doc.recompute()
        compound = self.doc.Compound.Shape
        # Act
        compound_copy = compound.copy()
        # Assert elementMap
        self.assertAllElementsMapped(compound)
        self.assertAllElementsMapped(compound_copy)

    def testTopoShapeCleaned(self):
        # Arrange
        self.doc.addObject("Part::Compound", "Compound")
        self.doc.Compound.Links = [
            App.activeDocument().Box1,
            App.activeDocument().Box2,
        ]
        self.doc.recompute()
        compound = self.doc.Compound.Shape
        # Act
        compound_cleaned = compound.cleaned()
        # Assert elementMap
        self.assertAllElementsMapped(compound)
        self.assertAllElementsMapped(compound_cleaned)

    def testTopoShapeCopyWithoutElementMap(self):
        # Arrange
        self.doc.addObject("Part::Compound", "Compound")
        self.doc.Compound.Links = [
            App.activeDocument().Box1,
            App.activeDocument().Box2,
        ]
        self.doc.recompute()
        compound = self.doc.Compound.Shape
        # Act
        compound_plain = compound.copy(noElementMap=True)
        # Assert elementMap
        self.assertAllElementsMapped(compound)
        self.assertEqual(compound_plain.ElementMapSize, 0)

    def testTopoShapeMakeFaceWithoutElementMap(self):
        # Act
        face = Part.makeFace(
            self.doc.Box1.Shape.Faces[0],
            "Part::FaceMakerCheese",
            noElementMap=True,
        )
        # Assert elementMap
        self.assertEqual(face.ElementMapSize, 0)

    def testTopoShapeReplaceShape(self):
        # Arrange
        self.doc.addObject("Part::Compound", "Compound")
        self.doc.Compound.Links = [
            App.activeDocument().Box1,
            App.activeDocument().Box2,
        ]
        self.doc.recompute()
        compound = self.doc.Compound.Shape
        # Act
        compound_replaced = compound.replaceShape(
            [(App.activeDocument().Box2.Shape, App.activeDocument().Box1.Shape)]
        )
        # Assert elementMap
        self.assertAllElementsMapped(compound)
        self.assertAllElementsMapped(compound_replaced)

    def testTopoShapeRemoveShape(self):
        # Arrange
        self.doc.addObject("Part::Compound", "Compound")
        self.doc.Compound.Links = [
            App.activeDocument().Box1,
            App.activeDocument().Box2,
        ]
        self.doc.recompute()
        compound = self.doc.Compound.Shape
        # Act
        compound_removed = compound.removeShape([App.ActiveDocument.Box2.Shape])
        # Assert elementMap
        self.assertAllElementsMapped(compound)
        self.assertAllElementsMapped(compound_removed)

    def testTopoShapeExtrude(self):
        # Arrange
        face = self.doc.Box1.Shape.Faces[0]
        # Act
        extrude = face.extrude(App.Vector(2, 0, 0))
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(extrude.ElementMapSize, 26)

    def testPartExtrusionOfUnmappedFace(self):
        """Every element of a Part::Extrusion of a face without an element map (a Part::Plane)
        is named. In V2 the top face, a moved copy of the base face, is named as its
        projection (PRJ), like a Pad's top face (ops#28)."""
        for algorithm in ("V1", "V2"):
            with self.subTest(algorithm=algorithm):
                doc = App.newDocument("ExtrusionOfPlane")
                try:
                    doc.HistoryAlgorithm = algorithm
                    plane = doc.addObject("Part::Plane", "Plane")
                    plane.Length = plane.Width = 10
                    extrusion = doc.addObject("Part::Extrusion", "Extrusion")
                    extrusion.Base = plane
                    extrusion.Dir = App.Vector(0, 0, 1)
                    extrusion.LengthFwd = 10
                    doc.recompute()
                    shape = extrusion.Shape
                    self.assertAttrCount(shape, [("Faces", 6), ("Edges", 12), ("Vertexes", 8)])
                    self.assertAllElementsMapped(shape)
                    if algorithm != "V2":
                        continue
                    top = [
                        f"Face{index}"
                        for index, face in enumerate(shape.Faces, 1)
                        if isinstance(face.Surface, Part.Plane)
                        and face.normalAt(0, 0).isEqual(App.Vector(0, 0, 1), 1e-7)
                        and abs(face.CenterOfMass.z - 10) < 1e-7
                    ]
                    self.assertEqual(len(top), 1)
                    # The plane's face has no name of its own, so the linked name is the
                    # unmapped name of the extrusion's input face.
                    base = App.makeEncodedSection(
                        referenceIDs=["Face1"],
                        iterationTag=str(extrusion.ID),
                        opCode="XTR",
                        elementType="F",
                        mapperFlags=["IDX", "SRC"],
                    )
                    expected = App.makeEncodedSection(
                        linkedNames=[base],
                        iterationTag=str(extrusion.ID),
                        opCode="XTR",
                        elementType="F",
                        mapperFlags=["PRJ"],
                    )
                    self.assertEqual(shape.ElementReverseMap[top[0]], expected)
                finally:
                    App.closeDocument(doc.Name)

    def testSplitPiecesAndAncestors(self):
        """A slot cut across a box's top face splits it in two. In V2 both pieces are the top
        face's incoming name followed by a MOD section, so App.isPieceOf finds them, and their
        ancestor sets hold that name (ops#7, the solver's structural evidence)."""
        doc = App.newDocument("SplitPieces")
        try:
            doc.HistoryAlgorithm = "V2"
            box = doc.addObject("Part::Box", "Box")
            slot = doc.addObject("Part::Box", "Slot")
            slot.Length = 2
            slot.Width = 12
            slot.Height = 6
            slot.Placement.Base = App.Vector(4, -1, 5)
            cut = doc.addObject("Part::Cut", "Cut")
            cut.Base = box
            cut.Tool = slot
            doc.recompute()

            def facesAt(shape, z):
                return [
                    f"Face{index}"
                    for index, face in enumerate(shape.Faces, 1)
                    if abs(face.CenterOfMass.z - z) < 1e-7
                ]

            boxTop = facesAt(box.Shape, 10)
            self.assertEqual(len(boxTop), 1)
            names = [cut.Shape.ElementReverseMap[name] for name in facesAt(cut.Shape, 10)]
            self.assertEqual(len(names), 2)
            # the box has no element map: the incoming name is its top face's unmapped name
            prefix = names[0].split("|")[0]
            self.assertTrue(prefix.startswith(boxTop[0] + ";"), prefix)
            for name in names:
                self.assertTrue(App.isPieceOf(name, prefix), name)
                self.assertIn(prefix, App.getNameAncestors(name))
            self.assertFalse(App.isPieceOf(names[0], names[1]))
            self.assertFalse(App.isPieceOf(names[1], names[0]))
            self.assertFalse(App.isPieceOf(prefix, names[0]))
            # the bottom face is unchanged: not a piece of the top face
            (bottom,) = facesAt(cut.Shape, 0)
            self.assertFalse(App.isPieceOf(cut.Shape.ElementReverseMap[bottom], prefix))
            # an ancestor set is sorted and holds the name itself
            ancestors = App.getNameAncestors(names[0])
            self.assertEqual(ancestors, sorted(ancestors))
            self.assertIn(names[0], ancestors)
        finally:
            App.closeDocument(doc.Name)

    def testInternedNamesExpandToV2(self):
        """The name table (ops#6, Task 1 PR 3): every V2 name of a fillet cut by a slot, interned,
        expands back to itself byte for byte and decodes to as many sections. Nothing interns
        names in FreeCAD yet, so the shapes keep their plain names."""
        doc = App.newDocument("InternedNames")
        try:
            doc.HistoryAlgorithm = "V2"
            box = doc.addObject("Part::Box", "Box")
            fillet = doc.addObject("Part::Fillet", "Fillet")
            fillet.Base = box
            fillet.Edges = [(1, 1.0, 1.0), (2, 1.0, 1.0)]
            slot = doc.addObject("Part::Box", "Slot")
            slot.Length = 2
            slot.Width = 12
            slot.Height = 6
            slot.Placement.Base = App.Vector(4, -1, 5)
            cut = doc.addObject("Part::Cut", "Cut")
            cut.Base = fillet
            cut.Tool = slot
            doc.recompute()

            names = list(cut.Shape.ElementMap)
            self.assertGreater(len(names), 20)
            self.assertTrue(any("^" in name for name in names))  # embedded names
            self.assertTrue(any("|" in name.replace("^|", "") for name in names))  # pieces
            for name in names:
                interned = App.internMappedName(name)
                self.assertNotIn("^", interned, name)
                self.assertLessEqual(len(interned), len(name))
                self.assertEqual(App.expandMappedName(interned), name)
                self.assertEqual(App.internMappedName(interned), interned)
                self.assertEqual(
                    len(App.getDecodedMappedName(interned)), len(App.getDecodedMappedName(name))
                )
            self.assertEqual(sorted(cut.Shape.ElementMap), sorted(names))  # unchanged

            # a node: its ID, its entry and its depth
            deepest = max(names, key=len)
            nodeId = App.getMappedNameId(deepest)
            self.assertEqual(len(nodeId), 13)
            content, depth = App.getNameTableEntry(nodeId)
            self.assertEqual(content, App.internMappedName(deepest))
            self.assertEqual(App.getNameTableEntry("~" + nodeId), (content, depth))
            self.assertGreaterEqual(depth, 2)
            self.assertEqual(App.expandMappedName("~" + nodeId), deepest)
            self.assertIsNone(App.getNameTableEntry("0123456789abc"))
            with self.assertRaises(ValueError):
                App.getNameTableEntry("not an id")
        finally:
            App.closeDocument(doc.Name)

    def testTopoShapeRevolve(self):
        # Arrange
        face = self.doc.Box1.Shape.Faces[0]
        # Act
        face.revolve(App.Vector(), App.Vector(1, 0, 0), 45)
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(face.ElementMapSize, 9)

    def testTopoShapeFuse(self):
        # Act
        fused = self.doc.Box1.Shape.fuse(self.doc.Box2.Shape)
        self.doc.recompute()
        # Assert elementMap
        self.assertAllElementsMapped(fused)

    def testTopoShapeFuseWithoutElementMap(self):
        # Act
        fused = self.doc.Box1.Shape.fuse(self.doc.Box2.Shape, noElementMap=True)
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(fused.ElementMapSize, 0)

    def testTopoShapeMultiFuse(self):
        # Act
        fused = self.doc.Box1.Shape.multiFuse([self.doc.Box2.Shape])
        self.doc.recompute()
        # Assert elementMap
        self.assertAllElementsMapped(fused)

    def testTopoShapeMultiFuseWithoutElementMap(self):
        # Act
        fused = self.doc.Box1.Shape.multiFuse([self.doc.Box2.Shape], noElementMap=True)
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(fused.ElementMapSize, 0)

    def testTopoShapeCommon(self):
        # Act
        common = self.doc.Box1.Shape.common(self.doc.Box2.Shape)
        self.doc.recompute()
        # Assert elementMap
        self.assertAllElementsMapped(common)
        self.assertAttrCount(common, [["Faces", 6], ["Edges", 12], ["Vertexes", 8]])

    def testTopoShapeSection(self):
        # Act
        section = self.doc.Box1.Shape.Faces[0].section(self.doc.Box2.Shape.Faces[3])
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(section.ElementMapSize, 3)

    def testTopoShapeSlice(self):
        # Act
        slice = self.doc.Box1.Shape.slice(App.Vector(10, 10, 0), 1)
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(len(slice), 1)
        self.assertEqual(slice[0].ElementMapSize, 8)

    def testTopoShapeSlices(self):
        # Act
        slices = self.doc.Box1.Shape.Faces[0].slices(App.Vector(10, 10, 0), [1, 2])
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(slices.ElementMapSize, 6)

    def testTopoShapeCut(self):
        # Act
        cut = self.doc.Box1.Shape.cut(self.doc.Box2.Shape)
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(cut.ElementMapSize, 26)

    def testTopoShapeGeneralFuse(self):
        # Act
        fuse = self.doc.Box1.Shape.generalFuse([self.doc.Box2.Shape])
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(len(fuse), 2)
        self.assertAllElementsMapped(fuse[0])

    def testTopoShapeChildShapes(self):
        # Act
        childShapes = self.doc.Box1.Shape.childShapes()
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(len(childShapes), 1)
        self.assertEqual(childShapes[0].ElementMapSize, 26)

    def testTopoShapeMirror(self):
        # Act
        mirror = self.doc.Box1.Shape.mirror(App.Vector(), App.Vector(1, 0, 0))
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(mirror.ElementMapSize, 26)

    def testTopoShapeMirrorWithPlacement(self):
        """Test that mirror() produces identical results regardless of how the
        shape is positioned - via direct coordinates or via Placement.
        Regression test for GitHub issue #20834.

        The bug was: when a shape has a non-identity Location (Placement),
        the mirror result was incorrect because the placement was being
        double-applied in makeElementMirror().
        """
        # Create two identical boxes at the same visual location using different methods:
        # Method 1: Box geometry positioned directly at (0, 30, 0), identity Placement
        box_direct = Part.makeBox(10, 20, 30, App.Vector(0, 30, 0))

        # Method 2: Box geometry at origin, then moved via Placement
        box_placed = Part.makeBox(10, 20, 30)
        box_placed.Placement = App.Placement(App.Vector(0, 30, 0), App.Rotation())

        # Verify both boxes appear at the same location
        self.assertAlmostEqual(box_direct.BoundBox.XMin, box_placed.BoundBox.XMin, places=5)
        self.assertAlmostEqual(box_direct.BoundBox.YMin, box_placed.BoundBox.YMin, places=5)
        self.assertAlmostEqual(box_direct.BoundBox.ZMin, box_placed.BoundBox.ZMin, places=5)

        # Mirror both across the XZ plane (Y=0)
        # A point (x, y, z) mirrors to (x, -y, z)
        # So box at Y=30..50 should mirror to Y=-50..-30
        mirror_direct = box_direct.mirror(App.Vector(), App.Vector(0, 1, 0))
        mirror_placed = box_placed.mirror(App.Vector(), App.Vector(0, 1, 0))

        # The mirrored shapes should have identical bounding boxes
        self.assertAlmostEqual(
            mirror_direct.BoundBox.XMin,
            mirror_placed.BoundBox.XMin,
            places=5,
            msg="Mirror with Placement produced different XMin",
        )
        self.assertAlmostEqual(
            mirror_direct.BoundBox.YMin,
            mirror_placed.BoundBox.YMin,
            places=5,
            msg="Mirror with Placement produced different YMin",
        )
        self.assertAlmostEqual(
            mirror_direct.BoundBox.ZMin,
            mirror_placed.BoundBox.ZMin,
            places=5,
            msg="Mirror with Placement produced different ZMin",
        )
        self.assertAlmostEqual(
            mirror_direct.BoundBox.XMax,
            mirror_placed.BoundBox.XMax,
            places=5,
            msg="Mirror with Placement produced different XMax",
        )
        self.assertAlmostEqual(
            mirror_direct.BoundBox.YMax,
            mirror_placed.BoundBox.YMax,
            places=5,
            msg="Mirror with Placement produced different YMax",
        )
        self.assertAlmostEqual(
            mirror_direct.BoundBox.ZMax,
            mirror_placed.BoundBox.ZMax,
            places=5,
            msg="Mirror with Placement produced different ZMax",
        )

        # Verify the expected mirror result: Y=30..50 mirrors to Y=-50..-30
        self.assertAlmostEqual(mirror_direct.BoundBox.YMin, -50.0, places=5)
        self.assertAlmostEqual(mirror_direct.BoundBox.YMax, -30.0, places=5)

    def testTopoShapeScale(self):
        # Act
        scale = self.doc.Box1.Shape.scaled(2)
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(scale.ElementMapSize, 26)

    def testTopoShapeMakeFillet(self):
        # Act
        fillet = self.doc.Box1.Shape.makeFillet(0.1, self.doc.Box1.Shape.Faces[0].Edges)
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(fillet.ElementMapSize, 42)

    def testTopoShapeMakeChamfer(self):
        # Act
        chamfer = self.doc.Box1.Shape.makeChamfer(0.1, self.doc.Box1.Shape.Faces[0].Edges)
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(chamfer.ElementMapSize, 42)

    def testTopoShapeMakeThickness(self):
        # Act
        thickness = self.doc.Box1.Shape.makeThickness(self.doc.Box1.Shape.Faces[0:2], 0.1, 0.0001)
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(thickness.ElementMapSize, 74)

    def testTopoShapeMakeOffsetShape(self):
        # Act
        offset = self.doc.Box1.Shape.Faces[0].makeOffset(1)
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(offset.ElementMapSize, 17)

    def testTopoShapeOffset2D(self):
        # Act
        offset = self.doc.Box1.Shape.Faces[0].makeOffset2D(1)
        self.doc.recompute()
        # Assert elementMap
        self.assertEqual(offset.ElementMapSize, 17)

    def testTopoShapeRemoveSplitter(self):
        # Act
        fused = self.doc.Box1.Shape.fuse(self.doc.Box2.Shape)
        removed = fused.removeSplitter()
        self.doc.recompute()
        # Assert elementMap
        self.assertAllElementsMapped(removed)
        # An extruded L: 8 Faces, 18 Edges, 12 Vertexes
        self.assertAttrCount(removed, [["Faces", 8], ["Edges", 18], ["Vertexes", 12]])

    def testTopoShapeCompSolid(self):
        # Act
        compSolid = Part.CompSolid([self.doc.Box1.Shape, self.doc.Box2.Shape])  # list of subobjects
        box1ts = self.doc.Box1.Shape
        compSolid.add(box1ts.Solids[0])
        # Assert elementMap
        self.assertEqual(compSolid.ElementMapSize, 78)

    def testTopoShapeFaceOffset(self):
        # Arrange
        box_toposhape = self.doc.Box1.Shape
        # Act
        offset = box_toposhape.Faces[0].makeOffset(2.0)
        # Assert elementMap
        self.assertEqual(box_toposhape.Faces[0].ElementMapSize, 9)  # 1 Face, 4 Edges, 4 Vertexes
        self.assertEqual(offset.ElementMapSize, 17)  # 1 Face, 8 Edges, 8 Vertexes

    # Todo:  makeEvolved doesn't work right, probably due to missing c++ code.
    # def testTopoShapeFaceEvolve(self):
    #     # Arrange
    #     box_toposhape = self.doc.Box1.Shape
    #     # Act
    #     evolved = box_toposhape.Faces[0].makeEvolved(self.doc.Box1.Shape.Wires[1])  # 2,3,4,5 bad
    #     # Assert elementMap
    #     self.assertEqual(box_toposhape.Faces[0].ElementMapSize, 9)  # 1 Face, 4 Edges, 4 Vertexes
    #     self.assertEqual(evolved.ElementMapSize, 0)  # Todo: This can't be correct.

    def testTopoShapePart(self):
        # Arrange
        box1ts = self.doc.Box1.Shape
        face1 = box1ts.Faces[0]
        box1ts2 = box1ts.copy()
        # Act
        face2 = box1ts.getElement("Face2")
        indexed_name = box1ts.findSubShape(face1)
        faces1 = box1ts.findSubShapesWithSharedVertex(face2)
        subshapes1 = box1ts.getChildShapes("Solid1")
        # box1ts.clearCache()   # Todo: no apparent way to see a result at this level
        # Assert
        self.assertTrue(face2.isSame(box1ts.Faces[1]))
        self.assertEqual(indexed_name[0], "Face")
        self.assertEqual(indexed_name[1], 1)
        self.assertEqual(len(faces1), 1)
        self.assertTrue(faces1[0].isSame(box1ts.Faces[1]))
        self.assertEqual(len(subshapes1), 1)
        self.assertTrue(subshapes1[0].isSame(box1ts.Solids[0]))

    def testTopoShapeMapSubElement(self):
        # Arrange
        box = Part.makeBox(1, 2, 3)
        # face = box.Faces[0]   # Do not do this.  Need the subelement call each usage.
        # Assert everything empty
        self.assertEqual(box.ElementMapSize, 0)
        self.assertEqual(box.Faces[0].ElementMapSize, 0)
        # Act
        box.mapSubElement(box.Faces[0])
        # Assert elementMaps created
        self.assertEqual(box.ElementMapSize, 9)  # 1 Face, 4 Edges, 4 Vertexes
        self.assertEqual(box.Faces[0].ElementMapSize, 9)

    def testTopoShapeGetElementHistory(self):
        """Every element of a fuse of two boxes without element maps has a history: (the box's
        tag, the box element's name, intermediate names). In V2 the history comes from the
        name's sections (ops#27), and the box's element is where the fuse's element came from:
        the centre of one lies on the other (a piece or a generated element lies on its source,
        an element the fuse's refine merged holds the source). In V1 the original can be a
        mapped name the box doesn't have, so only the tag is checked."""

        def centre(sub):
            return sub.Point if sub.ShapeType == "Vertex" else sub.CenterOfMass

        def onEachOther(a, b):
            return any(
                other.distToShape(Part.Vertex(centre(one)))[0] < 1e-7
                for one, other in ((a, b), (b, a))
            )

        for algorithm in ("V1", "V2"):
            with self.subTest(algorithm=algorithm):
                doc = App.newDocument("GetElementHistory")
                try:
                    doc.HistoryAlgorithm = algorithm
                    boxes = {}
                    for name, length, width in (("Box1", 1, 2), ("Box2", 2, 1)):
                        box = doc.addObject("Part::Box", name)
                        box.Length, box.Width, box.Height = length, width, 2
                        boxes[box.ID] = box
                    fuse = doc.addObject("Part::Fuse", "Fuse")
                    fuse.Base, fuse.Tool = boxes.values()
                    doc.recompute()
                    shape = fuse.Shape
                    count = 0
                    for kind in ("Vertex", "Edge", "Face"):
                        for index in range(1, shape.countElement(kind) + 1):
                            element = f"{kind}{index}"
                            names = shape.ElementReverseMap[element]
                            name = names if isinstance(names, str) else names[0]
                            # Act
                            history = shape.getElementHistory(name)
                            # Assert
                            self.assertIsNotNone(history, f"No history for {element}: {name}")
                            tag, original, intermediates = history
                            self.assertIn(tag, boxes, f"{element}: {history}")
                            self.assertIsInstance(intermediates, list)
                            count += 1
                            if algorithm != "V2":
                                continue
                            source = boxes[tag].Shape.getElement(original)
                            sub = shape.getElement(element)
                            self.assertTrue(
                                onEachOther(sub, source), f"{element} apart from {original}"
                            )
                    self.assertEqual(count, 38)
                    # The feature's history of a vertex ends at the box it came from
                    feature = fuse.getElementHistory("Vertex1")
                    self.assertEqual(len(feature), 2, feature)
                    self.assertIs(feature[0][0], fuse)
                    self.assertIn(feature[-1][0].ID, boxes)
                    self.assertEqual(feature[-1][1], shape.getElementHistory(feature[0][1])[1])
                finally:
                    App.closeDocument(doc.Name)

    # Todo:  Still broken, still can't find parms that consistently work to test this.
    #           However, the results with an empty elementMap are consistent with making the
    #           same calls on LS3.  So what this method is supposed to do remains a mystery;
    #           So far, it just wipes out the elementMap and returns the Toposhape.
    # def testTopoShapeMapShapes(self):
    #     self.doc.addObject("Part::Fuse", "Fuse")
    #     self.doc.Fuse.Base = self.doc.Box1
    #     self.doc.Fuse.Tool = self.doc.Box2
    #     # Act
    #     self.doc.recompute()
    #     fuse1 = self.doc.Fuse.Shape
    #     res = fuse1.copy()  # Make it mutable
    #     self.assertEqual(res.ElementMapSize,58)
    #     result = res.mapShapes([(fuse1, fuse1.Faces[0])], []) #[(res, res.Vertexes[0])])
    #     self.assertEqual(res.ElementMapSize,9)
    #     # result2 = fuse1.copy().mapShapes([],[(fuse1, fuse1.Edges[0]),(fuse1, fuse1.Edges[1])])
    #     self.assertEqual(fuse1.ElementMapSize,58) #
    #     self.assertEqual(fuse1.Faces[0].ElementMapSize,9)
    #     self.assertEqual(result.ElementMapSize,9)
    #     self.assertEqual(result.Faces[0].ElementMapSize,0)
    #     self.assertEqual(result2.ElementMapSize,9)
    #     self.assertEqual(result2.Faces[0].ElementMapSize,0)

    def testPartCompoundCut1(self):
        # Arrange
        self.doc.addObject("Part::Cut", "Cut")
        self.doc.Cut.Base = self.doc.Cylinder1
        self.doc.Cut.Tool = self.doc.Compound1
        # Act
        self.doc.recompute()
        cut1 = self.doc.Cut.Shape
        # Assert elementMap
        refkeys = [
            "Vertex6",
            "Vertex5",
            "Edge7",
            "Edge8",
            "Edge9",
            "Edge5",
            "Edge6",
            "Face4",
            "Face2",
            "Edge1",
            "Vertex4",
            "Edge4",
            "Vertex3",
            "Edge2",
            "Edge3",
            "Face1",
            "Face5",
            "Face3",
            "Vertex1",
            "Vertex2",
        ]
        self.assertKeysInMap(cut1.ElementReverseMap, refkeys)
        self.assertEqual(len(cut1.ElementReverseMap.keys()), len(refkeys))
        # Assert Volume
        self.assertAlmostEqual(cut1.Volume, self.doc.Cylinder1.Shape.Volume * (3 / 4))

    def testPartCompoundCut2(self):
        # Arrange
        self.doc.addObject("Part::Cut", "Cut")
        self.doc.Cut.Base = self.doc.Compound1
        self.doc.Cut.Tool = self.doc.Cylinder1
        self.doc.Cut.Refine = False
        # Act
        self.doc.recompute()
        cut1 = self.doc.Cut.Shape
        # Assert elementMap
        self.assertAllElementsMapped(cut1)
        # Assert Volume: each box loses the quarter of the cylinder inside it
        quarterCylinder = self.doc.Cylinder1.Shape.Volume / 4
        self.assertAlmostEqual(
            cut1.Volume,
            self.doc.Box1.Shape.Volume + self.doc.Box2.Shape.Volume - 2 * quarterCylinder,
        )

    def testPartFaceOfSketchesNamesV2(self):
        """Part::Face of a sketch with a hole, and of two sketches: every element is named, the
        edges and vertices keep the sketches' names, and each face gets a FAC name under the
        feature's tag (ops#33). Before, Part::Face had no element map."""
        import Sketcher

        def rectangle(sketch, x0, y0, x1, y1):
            points = [App.Vector(x0, y0, 0), App.Vector(x1, y0, 0)]
            points += [App.Vector(x1, y1, 0), App.Vector(x0, y1, 0)]
            first = sketch.GeometryCount
            for i in range(4):
                sketch.addGeometry(Part.LineSegment(points[i], points[(i + 1) % 4]))
            for i in range(4):
                sketch.addConstraint(
                    Sketcher.Constraint("Coincident", first + i, 2, first + (i + 1) % 4, 1)
                )

        def names(shape, kinds=("Face", "Edge", "Vertex")):
            """{element: [its names]}"""
            reverse = shape.ElementReverseMap
            elements = {"Face": shape.Faces, "Edge": shape.Edges, "Vertex": shape.Vertexes}
            result = {}
            for kind in kinds:
                for index in range(1, len(elements[kind]) + 1):
                    value = reverse.get(f"{kind}{index}", [])
                    result[f"{kind}{index}"] = [value] if isinstance(value, str) else list(value)
            return result

        doc = App.newDocument("PartFaceNames")
        try:
            doc.HistoryAlgorithm = "V2"
            holed = doc.addObject("Sketcher::SketchObject", "Holed")
            rectangle(holed, 0, 0, 10, 10)
            rectangle(holed, 3, 3, 6, 6)
            other = doc.addObject("Sketcher::SketchObject", "Other")
            rectangle(other, 20, 0, 25, 5)
            face = doc.addObject("Part::Face", "Face")
            face.Sources = [holed]
            faces = doc.addObject("Part::Face", "Faces")
            faces.Sources = [holed, other]
            doc.recompute()
            sketchNames = set()
            for sketch in (holed, other):
                for elementNames in names(sketch.Shape, ("Edge", "Vertex")).values():
                    sketchNames.update(elementNames)
            for feature, count in ((face, 1), (faces, 2)):
                shape = feature.Shape
                self.assertEqual(len(shape.Faces), count)
                self.assertAllElementsMapped(shape)
                elementNames = names(shape)
                firsts = [n[0] for n in elementNames.values()]
                self.assertEqual(len(set(firsts)), len(firsts), "names are distinct")
                for element, elementList in elementNames.items():
                    if element.startswith("Face"):
                        self.assertIn(f";{feature.ID};FAC;", elementList[0], element)
                    else:
                        self.assertTrue(set(elementList) & sketchNames, (element, elementList))
        finally:
            App.closeDocument(doc.Name)

    def testCreateCompound(self):
        box = Part.makeBox(1, 1, 1)
        comp = Part.Compound()
        self.assertTrue(comp.isNull())
        comp.add(box.Vertex1)
        self.assertFalse(comp.isNull())

    def testCreateShell(self):
        box = Part.makeBox(1, 1, 1)
        shell = Part.Shell()
        self.assertTrue(shell.isNull())
        shell.add(box.Face1)
        self.assertFalse(shell.isNull())

    def testCreateCompSolid(self):
        box = Part.makeBox(1, 1, 1)
        solid = Part.CompSolid()
        self.assertTrue(solid.isNull())
        solid.add(box)
        self.assertFalse(solid.isNull())

    def testRetagKeepsOtherShapesNames(self):
        """Retagging one shape's untagged names changes no other shape's names (ops#16)."""
        # Arrange
        untagged = makeSquareFace()
        untaggedName = untagged.ElementReverseMap["Face1"]
        self.assertEqual(untaggedName, squareFaceName(untagged, 0))
        # Act: two faces of the same geometry get tags 21 and 22. Part.Shape(shape, tag=...)
        # retags a shape that has another tag.
        tagged = []
        for tag in (21, 22):
            face = makeSquareFace()
            face.Tag = 7
            tagged.append(Part.Shape(face, tag=tag))
        # Assert
        for shape, tag in zip(tagged, (21, 22)):
            self.assertEqual(shape.Tag, tag)
            self.assertEqual(shape.ElementReverseMap["Face1"], squareFaceName(untagged, tag))
            for index in range(1, 5):
                self.assertEqual(
                    shape.ElementReverseMap[f"Edge{index}"],
                    untagged.ElementReverseMap[f"Edge{index}"],
                )
        # the untagged name still decodes as untagged
        self.assertEqual(App.getDecodedMappedName(untaggedName)[-1]["iterationTag"], "0")

    def testRetagKeepsTheSourceShapesNames(self):
        """Retagging a shape made from another changes only the new shape's names: Part.Shape()
        copies share the element map of the shape they are made from (ops#34)."""
        # Arrange
        face = makeSquareFace()
        face.Tag = 7
        untaggedNames = dict(face.ElementReverseMap)
        self.assertEqual(untaggedNames["Face1"], squareFaceName(face, 0))
        # Act: two shapes are made from the same face, with tags 21 and 22
        tagged = [Part.Shape(face, tag=tag) for tag in (21, 22)]
        # Assert
        for shape, tag in zip(tagged, (21, 22)):
            self.assertEqual(shape.ElementReverseMap["Face1"], squareFaceName(face, tag))
        # the face they were made from keeps every name, the face's untagged one included
        self.assertEqual(dict(face.ElementReverseMap), untaggedNames)
        self.assertEqual(face.ElementMap[untaggedNames["Face1"]], "Face1")

    def testRetagTagsEveryNameOfAnElement(self):
        """Retagging gives the tag to every untagged name of an element, not only its first.
        Fusing two touching extrusions of Python-made faces names the elements where they meet
        from both, so those elements have two new, untagged names (ops#38)."""

        def untaggedNamesByElement(shape):
            names = {}
            for element, elementNames in shape.ElementReverseMap.items():
                if isinstance(elementNames, str):
                    elementNames = [elementNames]
                untagged = [
                    name
                    for name in elementNames
                    if App.getDecodedMappedName(name)[-1]["iterationTag"] == "0"
                ]
                if untagged:
                    names[element] = untagged
            return names

        # Arrange
        height = App.Vector(0, 0, 10)
        left = makeSquareFace().extrude(height)
        right = makeSquareFace().translated(App.Vector(10, 0, 0)).extrude(height)
        fused = left.fuse(right)
        fused.Tag = 7
        untagged = untaggedNamesByElement(fused)
        twiceNamed = {element: names for element, names in untagged.items() if len(names) > 1}
        self.assertTrue(twiceNamed, "no element has two untagged names")
        # Act: two shapes are made from the fused one, with tags 21 and 22
        tagged = [Part.Shape(fused, tag=tag) for tag in (21, 22)]
        # Assert
        for shape, tag in zip(tagged, (21, 22)):
            with self.subTest(tag=tag):
                self.assertEqual(untaggedNamesByElement(shape), {})
                for element, names in twiceNamed.items():
                    newNames = shape.ElementReverseMap[element]
                    self.assertEqual(len(newNames), len(names))
                    for name in newNames:
                        self.assertEqual(
                            App.getDecodedMappedName(name)[-1]["iterationTag"], str(tag)
                        )
                        self.assertEqual(shape.ElementMap[name], element)
        # the two shapes share none of these names
        for element in twiceNamed:
            self.assertTrue(
                set(tagged[0].ElementReverseMap[element]).isdisjoint(
                    tagged[1].ElementReverseMap[element]
                )
            )
        # the fused shape keeps its untagged names
        self.assertEqual(untaggedNamesByElement(fused), untagged)

    def testFeaturePythonShapeTagged(self):
        """A Python feature's new elements carry the feature's tag, on every recompute and in
        every feature that makes the same shape (ops#16)."""
        # Arrange
        features = []
        for name in ("SquareFace1", "SquareFace2"):
            feature = self.doc.addObject("Part::FeaturePython", name)
            SquareFaceFeature(feature)
            features.append(feature)
        untagged = makeSquareFace()
        for recompute in (1, 2):
            # Act
            for feature in features:
                feature.touch()
            self.doc.recompute()
            # Assert
            for feature in features:
                with self.subTest(recompute=recompute, feature=feature.Name):
                    shape = feature.Shape
                    self.assertEqual(shape.Tag, feature.ID)
                    self.assertEqual(
                        shape.ElementReverseMap["Face1"], squareFaceName(untagged, feature.ID)
                    )
                    # the edges are the wire's, not new: they keep its names
                    for index in range(1, 5):
                        self.assertEqual(
                            shape.ElementReverseMap[f"Edge{index}"],
                            untagged.ElementReverseMap[f"Edge{index}"],
                        )

    def testV1SketchExtrusionFaceNames(self):
        """In a V1 document, every face of an extrusion of a rectangle sketch has a V1 face name
        (element type F), and the two end faces are named from the sketch's face (FAC). The end
        faces were misnamed while element maps ran V2 rules in V1 documents (ops#17)."""
        import re
        import Sketcher

        # Arrange
        doc = App.newDocument("V1SketchExtrusion")
        try:
            doc.HistoryAlgorithm = "V1"
            sketch = doc.addObject("Sketcher::SketchObject", "Sketch")
            corners = [
                App.Vector(0, 0, 0),
                App.Vector(10, 0, 0),
                App.Vector(10, 6, 0),
                App.Vector(0, 6, 0),
            ]
            for index in range(4):
                sketch.addGeometry(Part.LineSegment(corners[index], corners[(index + 1) % 4]))
            for index in range(4):
                sketch.addConstraint(
                    Sketcher.Constraint("Coincident", index, 2, (index + 1) % 4, 1)
                )
            extrusion = doc.addObject("Part::Extrusion", "Extrusion")
            extrusion.Base = sketch
            extrusion.Dir = App.Vector(0, 0, 4)
            extrusion.Solid = True

            # Act
            doc.recompute()

            # Assert
            shape = extrusion.Shape
            table = shape.Hasher.Table

            def decoded(name):
                # V1 names hash long parts: spell out each "#<hex id>" from the hasher's table
                return re.sub(
                    r"#([0-9a-f]+)",
                    lambda m: "{" + decoded(table.get(int(m.group(1), 16), m.group(0)[1:])) + "}",
                    name,
                )

            self.assertEqual(len(shape.Faces), 6)
            for index, face in enumerate(shape.Faces, 1):
                name = decoded(shape.ElementReverseMap[f"Face{index}"])
                with self.subTest(face=index, name=name):
                    self.assertTrue(name.endswith(",F"))
                    # the end faces are the planes z = 0 and z = 4
                    if abs(face.CenterOfMass.z) < 1e-7 or abs(face.CenterOfMass.z - 4) < 1e-7:
                        self.assertIn(";FAC;", name)
        finally:
            App.closeDocument(doc.Name)

    def testV2FeatureSectionsCarryOwnID(self):
        """In V2, the sections a Part feature's own operation adds carry the feature's ID,
        not an input's, so two identical features on the same inputs name their new
        elements differently. Names copied from the inputs keep the inputs' tags (ops#32)."""
        # Arrange
        doc = App.newDocument("V2FeatureSections")
        try:
            doc.HistoryAlgorithm = "V2"
            inputs = makeFeatureInputs(doc)
            features = {
                featureType: [
                    makeFeature(doc, inputs, featureType, f"{featureType[6:]}{index}")
                    for index in (1, 2)
                ]
                for featureType, opCode in FEATURE_OP_CODES.items()
                if opCode
            }

            # Act
            doc.recompute()

            # Assert
            for featureType, (first, second) in features.items():
                opCode = FEATURE_OP_CODES[featureType]
                with self.subTest(feature=featureType):
                    self.assertFalse(first.Shape.isNull())
                    ownNames = []
                    for feature in (first, second):
                        names = ownSectionNames(feature.Shape, opCode)
                        self.assertTrue(names, f"{feature.Name} has no {opCode} section")
                        tags = {
                            section["iterationTag"]
                            for name in names
                            for section in decodedSections(name)
                            if isOwnSection(section, opCode)
                        }
                        self.assertEqual(tags, {str(feature.ID)})
                        ownNames.append(names)
                    self.assertEqual(len(ownNames[0]), len(ownNames[1]))
                    self.assertTrue(ownNames[0].isdisjoint(ownNames[1]))
        finally:
            App.closeDocument(doc.Name)

    def testV1FeatureNamesAreV1(self):
        """In a V1 document, Part features name their results in V1 grammar only. They
        built their results with the V2 default of TopoShape (ops#30)."""
        import re

        # Arrange
        doc = App.newDocument("V1FeatureNames")
        try:
            doc.HistoryAlgorithm = "V1"
            inputs = makeFeatureInputs(doc)
            features = [
                makeFeature(doc, inputs, featureType, featureType[6:])
                for featureType in FEATURE_OP_CODES
            ]

            # Act
            doc.recompute()

            # Assert
            for feature in features:
                with self.subTest(feature=feature.TypeId):
                    shape = feature.Shape
                    self.assertFalse(shape.isNull())
                    self.assertGreater(shape.ElementMapSize, 0)
                    table = shape.Hasher.Table if shape.Hasher else {}

                    def decoded(name):
                        # spell out each hashed part "#<hex id>" from the hasher's table
                        return re.sub(
                            r"#([0-9a-f]+)",
                            lambda m: "{"
                            + decoded(table.get(int(m.group(1), 16), m.group(0)[1:]))
                            + "}",
                            name,
                        )

                    # a V2 section ends in ";_" (no connected names), e.g.
                    # 'Edge1;_;<tag>;MKR;0;E;0;IDX,SRC;_'
                    v2Names = [
                        name
                        for name in map(decoded, shape.ElementMap)
                        if re.search(r";_(;|}|$)", name)
                    ]
                    self.assertEqual(v2Names, [])
        finally:
            App.closeDocument(doc.Name)

    def assertMirrorOfPlacedSourceKeepsNames(self, algorithm):
        """A Part::Mirroring names each element of its result the same whether or not its
        source has a Placement: moving the source moves the mirror, it doesn't rename it."""
        # Arrange
        doc = App.newDocument(f"MirrorPlacedSource{algorithm}")
        try:
            doc.HistoryAlgorithm = algorithm
            inputs = makeFeatureInputs(doc)
            mirror = makeFeature(doc, inputs, "Part::Mirroring", "Mirror")
            doc.recompute()
            before = mirror.Shape.ElementReverseMap
            boundBefore = mirror.Shape.BoundBox

            # Act
            inputs["prism"].Placement = App.Placement(
                App.Vector(20, 5, 0), App.Rotation(App.Vector(0, 0, 1), 30)
            )
            doc.recompute()

            # Assert
            shape = mirror.Shape
            self.assertTrue(mirror.isValid())
            # the mirror followed its source (Normal +X through the origin)
            self.assertLess(shape.BoundBox.XMax, boundBefore.XMin)
            after = shape.ElementReverseMap
            for kind, elements in (
                ("Face", shape.Faces),
                ("Edge", shape.Edges),
                ("Vertex", shape.Vertexes),
            ):
                for index in range(1, len(elements) + 1):
                    element = f"{kind}{index}"
                    with self.subTest(element=element):
                        self.assertIn(element, after)
                        self.assertEqual(after[element], before[element])
        finally:
            App.closeDocument(doc.Name)

    def testV1MirrorOfPlacedSourceKeepsNames(self):
        """ops#39, V1: a mirror of a source with a Placement had no element names."""
        self.assertMirrorOfPlacedSourceKeepsNames("V1")

    def testV2MirrorOfPlacedSourceKeepsNames(self):
        """ops#39, V2: a mirror of a source with a Placement had no element names."""
        self.assertMirrorOfPlacedSourceKeepsNames("V2")
