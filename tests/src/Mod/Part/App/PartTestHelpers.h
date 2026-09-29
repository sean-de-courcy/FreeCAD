// SPDX-License-Identifier: LGPL-2.1-or-later

#include <functional>
#include <set>
#include <gtest/gtest.h>
#include <boost/format.hpp>
#include <App/Application.h>
#include <App/Document.h>
#include "Base/Interpreter.h"
#include <Base/Precision.h>
#include "Mod/Part/App/FeaturePartBox.h"
#include "Mod/Part/App/FeaturePartFuse.h"
#include "Mod/Part/App/FeatureFillet.h"
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <GC_MakeCircle.hxx>
#include <TopoDS.hxx>
#include <TopExp_Explorer.hxx>

namespace PartTestHelpers
{

using namespace Data;
using namespace Part;

double getVolume(const TopoDS_Shape& shape);

double getArea(const TopoDS_Shape& shape);

double getLength(const TopoDS_Shape& shape);

std::vector<Part::FilletElement> _getFilletEdges(
    const std::vector<int>& edges,
    double startRadius,
    double endRadius
);

class PartTestHelperClass
{
public:
    App::Document* _doc;
    std::string _docName;
    std::array<Part::Box*, 6> _boxes;  // NOLINT magic number
    void createTestDoc();
};

const double minimalDistance = Base::Precision::Confusion() * 1000;

void executePython(const std::vector<std::string>& python);

void rectangle(double height, double width, const char* name);

std::tuple<TopoDS_Face, TopoDS_Wire, TopoDS_Edge, TopoDS_Edge, TopoDS_Edge, TopoDS_Edge> CreateRectFace(
    float len = 2.0,
    float wid = 3.0
);

std::tuple<TopoDS_Face, TopoDS_Wire, TopoDS_Wire> CreateFaceWithRoundHole(
    float len = 2.0,
    float wid = 3.0,
    float radius = 1.0
);

testing::AssertionResult boxesMatch(
    const Base::BoundBox3d& b1,
    const Base::BoundBox3d& b2,
    double prec = 1e-05
);  // NOLINT

std::map<IndexedName, MappedName> elementMap(const TopoShape& shape);

/**
 * Checks that all the names occur in the shape's element map.  Map can contain additional names
 * @param shape The Shape
 * @param names The Names
 * @return A test result, suitable for display by the gtest framework
 */
testing::AssertionResult elementsMatch(const TopoShape& shape, const std::vector<std::string>& names);

/**
 * Checks that all the names occur in the shape's element map and that there are no additional names
 * @param shape The Shape
 * @param names The Names
 * @return A test result, suitable for display by the gtest framework
 */
testing::AssertionResult allElementsMatch(const TopoShape& shape, const std::vector<std::string>& names);

/**
 * The V2 name of an element taken from a shape without a name for it: its indexed name, the
 * shape's tag and the op, flags IDX and SRC. E.g. "Edge3;_;2;FUS;0;E;0;IDX,SRC;_"
 * @param element The element's indexed name in the shape it comes from, e.g. "Edge3"
 * @param tag The tag of the shape it comes from
 * @param op The op code of the operation that named it; MKR where the operation passed none
 * @param duplicate The duplicate count, for a name that another element of the map had first
 */
MappedName unmappedName(
    const std::string& element,
    long tag,
    const char* op = "MKR",
    int duplicate = 0
);

/**
 * A V2 name of one section that links other names, as an operation writes it for an element it
 * made from them, e.g. a generated face: "_;<linked names>;<tag>;<op>;<index>;<type>;0;<flag>;_"
 * @param linkedNames The names it links, in any order: the name holds them as a set, sorted by
 * bytes and each once (ops#19)
 * @param tag The tag of the operation's result
 * @param op The operation's op code
 * @param type 'V', 'E' or 'F'
 * @param flag GEN, UPP, LOW, PRJ, ...
 * @param index The index that tells apart elements with the same links
 */
MappedName linkingName(
    const std::vector<MappedName>& linkedNames,
    long tag,
    const char* op,
    char type,
    const char* flag,
    int index = 0
);

/**
 * The V2 name an operation gives an element that has no history of its own: UPP, linking the
 * names of the faces it bounds (sorted by bytes, each once)
 * @param shape The result of the operation
 * @param element "Edge3", "Vertex2", ...
 * @param tag The tag of the result
 * @param op The operation's op code
 * @param index The index that tells apart elements bounding the same faces
 */
MappedName upperName(
    const TopoShape& shape,
    const std::string& element,
    long tag,
    const char* op,
    int index = 0
);

/**
 * Checks that every element of this type has exactly its UPP name (upperName()); the index of
 * each is the number of elements of the type before it that bound the same faces
 */
testing::AssertionResult upperNamed(
    const TopoShape& shape,
    const char* type,
    long tag,
    const char* op
);

/**
 * The V2 name an operation gives a face that has no history of its own and no named upper
 * elements: LOW, linking the names of its outer wire's edges (sorted by bytes, each once)
 */
MappedName lowerName(const TopoShape& shape, const std::string& face, long tag, const char* op);

/**
 * Checks the names a boolean of shapes without names gives the elements of its result, from where
 * each element lies:
 * - the same element as an input's: that element's unmapped name, without the op (MKR);
 * - on one element of the same type of an input (trimmed or rebuilt): that element's unmapped
 *   name with the op; or, if that element was split into pieces, that name with a MOD section
 *   (the result's tag and the op) appended;
 * - a face on a face of each of two inputs: no history of its own, so LOW (lowerName());
 * - else where elements of the type above (faces for an edge, edges for a vertex) of two inputs
 *   meet: generated (GEN) from their unmapped names with the op (sorted by bytes).
 * @param result The boolean's result, whose tag its own sections carry
 * @param inputs The inputs, in order: tag and shape
 * @param op The boolean's op code
 */
testing::AssertionResult namedAsBoolean(
    const TopoShape& result,
    const std::vector<std::pair<long, TopoShape>>& inputs,
    const char* op
);

/**
 * Checks that the last section of every V2 name of the shape has its element's type
 */
testing::AssertionResult namesHaveTheirElementsType(const TopoShape& shape);

/**
 * Whether the shape lies on the other: its vertices, and a point inside an edge or a face, are on
 * the other shape
 */
bool liesOn(const TopoDS_Shape& shape, const TopoDS_Shape& on);

/**
 * Checks that every vertex, edge and face of the shape has at least one mapped name
 */
testing::AssertionResult allElementsNamed(const TopoShape& shape);

/**
 * Checks that the shape's element has exactly these mapped names, in any order
 */
testing::AssertionResult elementHasNames(
    const TopoShape& shape,
    const char* element,
    const std::vector<MappedName>& names
);

/**
 * Checks that every element of each shape has the same mapped names as the same element of the
 * other shape, e.g. a copy that keeps its source's names
 */
testing::AssertionResult sameNamesPerElement(const TopoShape& shape, const TopoShape& other);

/**
 * The indexed name of the shape's only element of this type whose center of mass is at the point,
 * e.g. "Face3"; empty if there is none or more than one
 * @param shape The Shape
 * @param type "Vertex", "Edge" or "Face"
 * @param center The point
 */
std::string elementAt(const TopoShape& shape, const char* type, const Base::Vector3d& center);

/**
 * The indexed name of the shape's only element of this type whose center of mass passes the
 * test, e.g. "Face3"; empty if there is none or more than one
 */
std::string elementWhere(
    const TopoShape& shape,
    const char* type,
    const std::function<bool(const Base::Vector3d&)>& isAt
);

/**
 * The last section of a V2 mapped name, i.e. the one the last operation added
 */
DecodedMappedSection lastSection(const MappedName& name);

/**
 * Checks, for every name of the shape that is an unmapped name (one section, flag IDX), that the
 * source shape with its tag has that element and that it is the same element as the one named
 * @param shape The Shape
 * @param sources The shapes its names may come from, by tag
 */
testing::AssertionResult unmappedNamesNameTheirElements(
    const TopoShape& shape,
    const std::map<long, TopoShape>& sources
);

/**
 *
 * @return  Two raw shape cubes without element maps
 */
std::pair<TopoDS_Shape, TopoDS_Shape> CreateTwoCubes();

/**
 *
 * @return  Two TopoShape cubes with elementMaps
 */
std::pair<TopoShape, TopoShape> CreateTwoTopoShapeCubes();
}  // namespace PartTestHelpers
