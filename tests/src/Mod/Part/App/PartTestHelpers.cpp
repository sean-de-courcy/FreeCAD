// SPDX-License-Identifier: LGPL-2.1-or-later

#include <regex>
#include "PartTestHelpers.h"

#include <BRepAdaptor_Curve.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp_Face.hxx>
#include <BRepTools.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <Precision.hxx>
#include <gp_Pnt2d.hxx>

// NOLINTBEGIN(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)

namespace PartTestHelpers
{

double getVolume(const TopoDS_Shape& shape)
{
    GProp_GProps prop;
    BRepGProp::VolumeProperties(shape, prop);
    return abs(prop.Mass());
}

double getArea(const TopoDS_Shape& shape)
{
    GProp_GProps prop;
    BRepGProp::SurfaceProperties(shape, prop);
    return abs(prop.Mass());
}

double getLength(const TopoDS_Shape& shape)
{
    GProp_GProps prop;
    BRepGProp::LinearProperties(shape, prop);
    return abs(prop.Mass());
}


void PartTestHelperClass::createTestDoc()
{
    _docName = App::GetApplication().getUniqueDocumentName("test");
    _doc = App::GetApplication().newDocument(_docName.c_str(), "testUser");
    std::array<Base::Vector3d, 6> box_origins = {
        Base::Vector3d(),                                        // First box at 0,0,0
        Base::Vector3d(0, 1, 0),                                 // Overlap with first box
        Base::Vector3d(0, 3, 0),                                 // Don't Overlap with first box
        Base::Vector3d(0, 2, 0),                                 // Touch the first box
        Base::Vector3d(0, 2 + Base::Precision::Confusion(), 0),  // Just Outside of touching
        // For the Just Inside Of Touching case, go enough that we exceed precision rounding
        Base::Vector3d(0, 2 - minimalDistance, 0)
    };

    for (unsigned i = 0; i < _boxes.size(); i++) {
        auto box = _boxes[i] = _doc->addObject<Part::Box>();  // NOLINT
        box->Length.setValue(1);
        box->Width.setValue(2);
        box->Height.setValue(3);
        box->Placement.setValue(
            Base::Placement(box_origins[i], Base::Rotation(), Base::Vector3d())
        );  // NOLINT
    }
}

std::vector<Part::FilletElement> _getFilletEdges(
    const std::vector<int>& edges,
    double startRadius,
    double endRadius
)
{
    std::vector<Part::FilletElement> filletElements;
    for (auto edge : edges) {
        Part::FilletElement fe = {edge, startRadius, endRadius};
        filletElements.push_back(fe);
    }
    return filletElements;
}


void ExecutePython(const std::vector<std::string>& python)
{
    Base::InterpreterSingleton is = Base::InterpreterSingleton();

    for (auto const& line : python) {
        is.runInteractiveString(line.c_str());
    }
}


void rectangle(double height, double width, const char* name)
{
    std::vector<std::string> rectstring {
        "import FreeCAD, Part",
        "V1 = FreeCAD.Vector(0, 0, 0)",
        boost::str(boost::format("V2 = FreeCAD.Vector(%d, 0, 0)") % height),
        boost::str(boost::format("V3 = FreeCAD.Vector(%d, %d, 0)") % height % width),
        boost::str(boost::format("V4 = FreeCAD.Vector(0, %d, 0)") % width),
        "P1 = Part.makePolygon([V1, V2, V3, V4],True)",
        "F1 = Part.Face(P1)",  // Make the face or the volume calc won't work right.
        boost::str(boost::format("Part.show(F1,'%s')") % name),
    };
    ExecutePython(rectstring);
}

std::tuple<TopoDS_Face, TopoDS_Wire, TopoDS_Edge, TopoDS_Edge, TopoDS_Edge, TopoDS_Edge> CreateRectFace(
    float len,
    float wid
)
{
    auto edge1 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(len, 0.0, 0.0)).Edge();
    auto edge2 = BRepBuilderAPI_MakeEdge(gp_Pnt(len, 0.0, 0.0), gp_Pnt(len, wid, 0.0)).Edge();
    auto edge3 = BRepBuilderAPI_MakeEdge(gp_Pnt(len, wid, 0.0), gp_Pnt(0.0, wid, 0.0)).Edge();
    auto edge4 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, wid, 0.0), gp_Pnt(0.0, 0.0, 0.0)).Edge();
    auto wire1 = BRepBuilderAPI_MakeWire({edge1, edge2, edge3, edge4}).Wire();
    auto face1 = BRepBuilderAPI_MakeFace(wire1).Face();
    return {face1, wire1, edge1, edge2, edge3, edge4};
}

std::tuple<TopoDS_Face, TopoDS_Wire, TopoDS_Wire> CreateFaceWithRoundHole(float len, float wid, float radius)
{
    auto [face1, wire1, edge1, edge2, edge3, edge4] = CreateRectFace(len, wid);
    auto circ1 = GC_MakeCircle(gp_Pnt(len / 2.0, wid / 2.0, 0), gp_Dir(0.0, 0.0, 1.0), radius).Value();
    auto edge5 = BRepBuilderAPI_MakeEdge(circ1).Edge();
    auto wire2 = BRepBuilderAPI_MakeWire(edge5).Wire();
    auto face2 = BRepBuilderAPI_MakeFace(face1, wire2).Face();
    // Beware:  somewhat counterintuitively, face2 is the sum of face1 and the area inside wire2,
    // not the difference.
    return {face2, wire1, wire2};
}

testing::AssertionResult boxesMatch(const Base::BoundBox3d& b1, const Base::BoundBox3d& b2, double prec)
{
    if (abs(b1.MinX - b2.MinX) < prec && abs(b1.MinY - b2.MinY) < prec
        && abs(b1.MinZ - b2.MinZ) < prec && abs(b1.MaxX - b2.MaxX) < prec
        && abs(b1.MaxY - b2.MaxY) < prec && abs(b1.MaxZ - b2.MaxZ) < prec) {
        return testing::AssertionSuccess();
    }
    return testing::AssertionFailure()
        << "(" << b1.MinX << "," << b1.MinY << "," << b1.MinZ << " ; "
        << "(" << b1.MaxX << "," << b1.MaxY << "," << b1.MaxZ << ") != (" << b2.MinX << ","
        << b2.MinY << "," << b2.MinZ << " ; " << b2.MaxX << "," << b2.MaxY << "," << b2.MaxZ << ")";
}

std::map<IndexedName, MappedName> elementMap(const TopoShape& shape)
{
    std::map<IndexedName, MappedName> result {};
    auto elements = shape.getElementMap();
    for (auto const& entry : elements) {
        result[entry.index] = entry.name;
    }
    return result;
}

std::string mappedElementVectorToString(std::vector<MappedElement>& elements)
{
    std::stringstream output;
    output << "{";
    for (const auto& element : elements) {
        output << "\"" << element.name.toString() << "\", ";
    }
    output << "}";
    return output.str();
}

bool matchStringsWithoutClause(std::string first, std::string second, const std::string& regex)
{
    first = std::regex_replace(first, std::regex(regex), "");
    second = std::regex_replace(second, std::regex(regex), "");
    return first == second;
}

/**
 *  Check to see if the elementMap in a shape contains all the names in a list
 *  There are some sections of the name that can vary due to random numbers or
 *  memory addresses, so we use a regex to exclude those sections while still
 *  validating that the name exists and is the correct type.
 * @param shape The Shape
 * @param names The vector of names
 * @return An assertion usable by the gtest framework
 */
testing::AssertionResult elementsMatch(const TopoShape& shape, const std::vector<std::string>& names)
{
    auto elements = shape.getElementMap();
    if (!elements.empty() || !names.empty()) {
        for (const auto& name : names) {
            if (std::find_if(
                    elements.begin(),
                    elements.end(),
                    [&, name](const Data::MappedElement& element) {
                        return matchStringsWithoutClause(
                            element.name.toString(),
                            name,
                            "(;D|;:H|;K)-?[a-fA-F0-9]+(:[0-9]+)?|(\\(.*?\\))?"
                        );
                        // ;D ;:H and ;K are the sections of an encoded name for
                        // Duplicate, Tag and a Face name in slices.  All three of these
                        // can vary from run to run or platform to platform, as they are
                        // based on either explicit random numbers or memory addresses.
                        // Thus we remove the value from comparisons and just check that
                        // they exist.  The full form could be something like ;:He59:53
                        // which is what we match and remove.  We also pull out any
                        // subexpressions wrapped in parens to keep the parse from
                        // becoming too complex.
                    }
                )
                == elements.end()) {
                return testing::AssertionFailure() << mappedElementVectorToString(elements);
            }
        }
    }
    return testing::AssertionSuccess();
}

testing::AssertionResult allElementsMatch(const TopoShape& shape, const std::vector<std::string>& names)
{
    auto elements = shape.getElementMap();
    if (elements.size() != names.size()) {
        return testing::AssertionFailure() << elements.size() << " != " << names.size()
                                           << " elements: " << mappedElementVectorToString(elements);
    }
    return elementsMatch(shape, names);
}

MappedName unmappedName(const std::string& element, long tag, const char* op, int duplicate)
{
    return MappedName(MappedName::makeEncodedSection(
        std::vector<std::string> {element},
        std::vector<MappedName> {},
        static_cast<int>(tag),
        op,
        0,
        element[0],
        duplicate,
        {MAPPER_FLAG_INDEX, MAPPER_FLAG_SOURCE},
        std::vector<MappedName> {}
    ));
}

MappedName linkingName(
    const std::vector<MappedName>& linkedNames,
    long tag,
    const char* op,
    char type,
    const char* flag,
    int index
)
{
    std::vector<MappedName> sortedLinkedNames = linkedNames;
    std::sort(sortedLinkedNames.begin(), sortedLinkedNames.end());
    sortedLinkedNames.erase(
        std::unique(sortedLinkedNames.begin(), sortedLinkedNames.end()),
        sortedLinkedNames.end()
    );
    return MappedName(MappedName::makeEncodedSection(
        std::vector<std::string> {},
        sortedLinkedNames,
        static_cast<int>(tag),
        op,
        index,
        type,
        0,
        {flag},
        std::vector<MappedName> {}
    ));
}

MappedName upperName(
    const TopoShape& shape,
    const std::string& element,
    long tag,
    const char* op,
    int index
)
{
    std::vector<MappedName> upperNames;
    auto subShape = shape.getSubShape(element.c_str());
    auto linkNames = [&](TopAbs_ShapeEnum upperType, const char* upperTypeName) {
        for (int upper : shape.findAncestors(subShape, upperType)) {
            auto name = shape.getMappedName(IndexedName::fromConst(upperTypeName, upper));
            if (name && std::ranges::find(upperNames, name) == upperNames.end()) {
                upperNames.push_back(name);
            }
        }
    };
    linkNames(TopAbs_FACE, "Face");
    if (upperNames.empty() && subShape.ShapeType() == TopAbs_VERTEX) {
        linkNames(TopAbs_EDGE, "Edge");
    }
    return linkingName(upperNames, tag, op, element[0], MAPPER_FLAG_UPPER, index);
}

testing::AssertionResult upperNamed(
    const TopoShape& shape,
    const char* type,
    long tag,
    const char* op
)
{
    std::map<std::vector<std::string>, int> used;
    for (int index = 1; index <= static_cast<int>(shape.countSubElements(type)); ++index) {
        auto element = std::string(type) + std::to_string(index);
        auto linkedNames = lastSection(upperName(shape, element, tag, op)).linkedNames;
        auto result = elementHasNames(
            shape,
            element.c_str(),
            {upperName(shape, element, tag, op, used[linkedNames]++)}
        );
        if (!result) {
            return result;
        }
    }
    return testing::AssertionSuccess();
}

bool liesOn(const TopoDS_Shape& shape, const TopoDS_Shape& on)
{
    auto isOn = [&](const TopoDS_Shape& part) {
        BRepExtrema_DistShapeShape distance(part, on);
        return distance.IsDone() && distance.Value() < Base::Precision::Confusion();
    };
    if (shape.ShapeType() == TopAbs_VERTEX) {
        return isOn(shape);
    }
    // its vertices, and for an edge its middle, for a face a point inside it
    for (TopExp_Explorer explorer(shape, TopAbs_VERTEX); explorer.More(); explorer.Next()) {
        if (!isOn(explorer.Current())) {
            return false;
        }
    }
    gp_Pnt inside;
    if (shape.ShapeType() == TopAbs_EDGE) {
        BRepAdaptor_Curve curve(TopoDS::Edge(shape));
        inside = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2);
    }
    else {
        BRepGProp_Face face(TopoDS::Face(shape));
        double u1, u2, v1, v2;  // NOLINT
        face.Bounds(u1, u2, v1, v2);
        BRepClass_FaceClassifier classifier;
        // a point inside the face: the first point of a coarse grid that the face contains
        bool found = false;
        for (int i = 1; i < 8 && !found; ++i) {
            for (int j = 1; j < 8 && !found; ++j) {
                double u = u1 + (u2 - u1) * i / 8;
                double v = v1 + (v2 - v1) * j / 8;
                classifier.Perform(TopoDS::Face(shape), gp_Pnt2d(u, v), Precision::Confusion());
                if (classifier.State() == TopAbs_IN) {
                    gp_Vec normal;
                    face.Normal(u, v, inside, normal);
                    found = true;
                }
            }
        }
        if (!found) {
            return false;
        }
    }
    return isOn(BRepBuilderAPI_MakeVertex(inside).Vertex());
}

namespace
{
const char* typeAbove(const std::string& type)
{
    return type == "Vertex" ? "Edge" : "Face";
}
}  // namespace

MappedName lowerName(const TopoShape& shape, const std::string& face, long tag, const char* op)
{
    std::vector<MappedName> edgeNames;
    auto outerWire = BRepTools::OuterWire(TopoDS::Face(shape.getSubShape(face.c_str())));
    for (TopExp_Explorer explorer(outerWire, TopAbs_EDGE); explorer.More(); explorer.Next()) {
        auto edge = shape.findShape(explorer.Current());
        auto name = shape.getMappedName(IndexedName::fromConst("Edge", edge));
        if (name && std::ranges::find(edgeNames, name) == edgeNames.end()) {
            edgeNames.push_back(name);
        }
    }
    return linkingName(edgeNames, tag, op, 'F', MAPPER_FLAG_LOWER);
}

namespace
{
// the input elements of this type that the shape lies on, without the one it is
std::vector<std::pair<long, std::string>> inputElementsUnder(
    const TopoDS_Shape& shape,
    const std::string& type,
    const std::vector<std::pair<long, TopoShape>>& inputs
)
{
    std::vector<std::pair<long, std::string>> under;
    for (const auto& [tag, input] : inputs) {
        auto count = static_cast<int>(input.countSubElements(type.c_str()));
        for (int index = 1; index <= count; ++index) {
            auto inputElement = type + std::to_string(index);
            auto inputShape = input.getSubShape(inputElement.c_str());
            if (!shape.IsSame(inputShape) && liesOn(shape, inputShape)) {
                under.emplace_back(tag, inputElement);
            }
        }
    }
    return under;
}

testing::AssertionResult isPieceOf(
    const MappedName& name,
    const MappedName& source,
    long tag,
    const char* op,
    char type
)
{
    auto text = name.toString();
    auto prefix = source.toString() + NAME_SECTION_DELIMINATOR;
    auto section = lastSection(name);
    bool oneMoreSection = text.starts_with(prefix)
        && text.find(NAME_SECTION_DELIMINATOR, prefix.size()) == std::string::npos;
    if (oneMoreSection && section.iterationTag == std::to_string(tag) && section.opCode == op
        && section.elementType == type
        && section.mapperFlags == std::vector<std::string> {MAPPER_FLAG_MODIFIED}) {
        return testing::AssertionSuccess();
    }
    return testing::AssertionFailure() << text << " is not a piece of " << source.toString();
}
}  // namespace

testing::AssertionResult namedAsBoolean(
    const TopoShape& result,
    const std::vector<std::pair<long, TopoShape>>& inputs,
    const char* op
)
{
    for (const std::string type : {"Face", "Edge", "Vertex"}) {
        auto count = static_cast<int>(result.countSubElements(type.c_str()));
        for (int index = 1; index <= count; ++index) {
            auto element = type + std::to_string(index);
            auto shape = result.getSubShape(element.c_str());
            auto has = [&](const MappedName& expected) {
                return elementHasNames(result, element.c_str(), {expected});
            };
            testing::AssertionResult check = testing::AssertionFailure();
            auto same = std::ranges::find_if(inputs, [&](const auto& input) {
                return input.second.findShape(shape) > 0;
            });
            auto under = inputElementsUnder(shape, type, inputs);
            if (same != inputs.end()) {
                // the same element as an input's
                auto found = same->second.findShape(shape);
                check = has(unmappedName(type + std::to_string(found), same->first));
            }
            else if (under.size() == 1) {
                // trimmed or rebuilt: the only element on that input element, or one of its pieces
                const auto& [tag, inputElement] = under.front();
                auto source = unmappedName(inputElement, tag, op);
                auto input = std::ranges::find(inputs, tag, &std::pair<long, TopoShape>::first);
                auto inputShape = input->second.getSubShape(inputElement.c_str());
                int pieces = 0;
                for (int other = 1; other <= count; ++other) {
                    auto otherShape = result.getSubShape((type + std::to_string(other)).c_str());
                    pieces += liesOn(otherShape, inputShape) ? 1 : 0;
                }
                auto names = result.getElementMappedNames(IndexedName(element.c_str()));
                if (pieces == 1) {
                    check = has(source);
                }
                else if (names.size() == 1) {
                    check = isPieceOf(names.front().first, source, result.Tag, op, type[0]);
                }
                else {
                    check << element << " has " << names.size() << " names";
                }
            }
            else if (under.size() == 2 && type == "Face") {
                // a piece of a face of each of two inputs: no history of its own
                check = has(lowerName(result, element, result.Tag, op));
            }
            else if (under.empty() && type != "Face") {
                // made where elements of the type above of two inputs meet
                const char* above = typeAbove(type);
                std::vector<MappedName> meeting;
                for (const auto& [tag, inputElement] : inputElementsUnder(shape, above, inputs)) {
                    meeting.push_back(unmappedName(inputElement, tag, op));
                }
                if (meeting.size() == 2) {
                    check = has(
                        linkingName(meeting, result.Tag, op, type[0], MAPPER_FLAG_GENERATED)
                    );
                }
                else {
                    check << element << " lies on " << meeting.size() << " " << above
                          << "s of the inputs";
                }
            }
            else {
                check << element << " lies on " << under.size() << " " << type << "s of the inputs";
            }
            if (!check) {
                return check;
            }
        }
    }
    return testing::AssertionSuccess();
}

testing::AssertionResult namesHaveTheirElementsType(const TopoShape& shape)
{
    for (const auto& entry : shape.getElementMap()) {
        if (lastSection(entry.name).elementType != entry.index.getType()[0]) {
            return testing::AssertionFailure()
                << entry.index.toString() << " = " << entry.name.toString();
        }
    }
    return testing::AssertionSuccess();
}

testing::AssertionResult allElementsNamed(const TopoShape& shape)
{
    std::vector<std::string> unnamed;
    for (const char* type : {"Vertex", "Edge", "Face"}) {
        auto count = static_cast<int>(shape.countSubElements(type));
        for (int index = 1; index <= count; ++index) {
            IndexedName element(type, index);
            if (!shape.getMappedName(element)) {
                unnamed.push_back(element.toString());
            }
        }
    }
    if (unnamed.empty()) {
        return testing::AssertionSuccess();
    }
    auto failure = testing::AssertionFailure() << unnamed.size() << " unnamed:";
    for (const auto& element : unnamed) {
        failure << " " << element;
    }
    return failure;
}

namespace
{
std::vector<std::string> sortedNames(const TopoShape& shape, const IndexedName& element)
{
    std::vector<std::string> names;
    for (const auto& name : shape.getElementMappedNames(element)) {
        names.push_back(name.first.toString());
    }
    std::ranges::sort(names);
    return names;
}

std::string joined(const std::vector<std::string>& names)
{
    std::string result = "{";
    for (const auto& name : names) {
        result += "\n  \"" + name + "\"";
    }
    return result + "}";
}
}  // namespace

testing::AssertionResult elementHasNames(
    const TopoShape& shape,
    const char* element,
    const std::vector<MappedName>& names
)
{
    std::vector<std::string> expected;
    for (const auto& name : names) {
        expected.push_back(name.toString());
    }
    std::ranges::sort(expected);
    auto actual = sortedNames(shape, IndexedName(element));
    if (actual == expected) {
        return testing::AssertionSuccess();
    }
    return testing::AssertionFailure()
        << element << " has " << joined(actual) << "\nexpected " << joined(expected);
}

testing::AssertionResult sameNamesPerElement(const TopoShape& shape, const TopoShape& other)
{
    for (const char* type : {"Vertex", "Edge", "Face"}) {
        auto count = shape.countSubElements(type);
        if (count != other.countSubElements(type)) {
            return testing::AssertionFailure()
                << type << " count " << count << " != " << other.countSubElements(type);
        }
        for (int index = 1; index <= static_cast<int>(count); ++index) {
            IndexedName element(type, index);
            auto names = sortedNames(shape, element);
            auto otherNames = sortedNames(other, element);
            if (names != otherNames) {
                return testing::AssertionFailure() << element.toString() << " has " << joined(names)
                                                   << "\nthe other has " << joined(otherNames);
            }
        }
    }
    return testing::AssertionSuccess();
}

std::string elementWhere(
    const TopoShape& shape,
    const char* type,
    const std::function<bool(const Base::Vector3d&)>& isAt
)
{
    std::string found;
    auto count = static_cast<int>(shape.countSubElements(type));
    for (int index = 1; index <= count; ++index) {
        auto name = std::string(type) + std::to_string(index);
        auto element = shape.getSubShape(name.c_str());
        gp_Pnt point;
        if (element.ShapeType() == TopAbs_VERTEX) {
            point = BRep_Tool::Pnt(TopoDS::Vertex(element));
        }
        else {
            GProp_GProps props;
            if (element.ShapeType() == TopAbs_EDGE) {
                BRepGProp::LinearProperties(element, props);
            }
            else {
                BRepGProp::SurfaceProperties(element, props);
            }
            point = props.CentreOfMass();
        }
        if (isAt(Base::Vector3d(point.X(), point.Y(), point.Z()))) {
            if (!found.empty()) {
                return {};
            }
            found = name;
        }
    }
    return found;
}

std::string elementAt(const TopoShape& shape, const char* type, const Base::Vector3d& center)
{
    return elementWhere(shape, type, [&](const Base::Vector3d& point) {
        return Base::Distance(point, center) < Base::Precision::Confusion();
    });
}

DecodedMappedSection lastSection(const MappedName& name)
{
    const auto& sections = MappedName::getDecodedMappedName(name.toString());
    return sections.empty() ? DecodedMappedSection {} : sections.back();
}

testing::AssertionResult unmappedNamesNameTheirElements(
    const TopoShape& shape,
    const std::map<long, TopoShape>& sources
)
{
    for (const auto& entry : shape.getElementMap()) {
        const auto& sections = MappedName::getDecodedMappedName(entry.name.toString());
        if (sections.size() != 1 || !sections.front().hasMapperFlag(MAPPER_FLAG_INDEX)) {
            continue;
        }
        const auto& section = sections.front();
        auto source = sources.find(std::stol(section.iterationTag));
        if (source == sources.end() || section.referenceIDs.size() != 1) {
            return testing::AssertionFailure()
                << entry.index.toString() << " = " << entry.name.toString() << ": no such source";
        }
        const auto& sourceElement = section.referenceIDs.front();
        auto sourceShape = source->second.getSubShape(sourceElement.c_str(), true);
        auto element = shape.getSubShape(entry.index.toString().c_str(), true);
        if (sourceShape.IsNull() || !element.IsSame(sourceShape)) {
            return testing::AssertionFailure()
                << entry.index.toString() << " = " << entry.name.toString()
                << ", but it is not the source's " << sourceElement;
        }
    }
    return testing::AssertionSuccess();
}

std::pair<TopoDS_Shape, TopoDS_Shape> CreateTwoCubes()
{
    auto boxMaker1 = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0);
    boxMaker1.Build();
    auto box1 = boxMaker1.Shape();

    auto boxMaker2 = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0);
    boxMaker2.Build();
    auto box2 = boxMaker2.Shape();
    auto transform = gp_Trsf();
    transform.SetTranslation(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0));
    box2.Location(TopLoc_Location(transform));

    return {box1, box2};
}

std::pair<TopoShape, TopoShape> CreateTwoTopoShapeCubes()
{
    auto [box1, box2] = CreateTwoCubes();
    std::vector<TopoShape> vec;
    long tag = 1L;
    for (TopExp_Explorer exp(box1, TopAbs_FACE); exp.More(); exp.Next()) {
        vec.emplace_back(TopoShape(exp.Current(), tag++));
    }
    TopoShape box1ts;
    box1ts.makeElementCompound(vec);
    box1ts.Tag = tag++;
    vec.clear();
    for (TopExp_Explorer exp(box2, TopAbs_FACE); exp.More(); exp.Next()) {
        vec.emplace_back(TopoShape(exp.Current(), tag++));
    }
    TopoShape box2ts;
    box2ts.Tag = tag++;
    box2ts.makeElementCompound(vec);

    return {box1ts, box2ts};
}

}  // namespace PartTestHelpers

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
