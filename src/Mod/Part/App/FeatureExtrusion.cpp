// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2008 Werner Mayer <wmayer[at]users.sourceforge.net>     *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#include <FCConfig.h>

#include <algorithm>
#include <cctype>
#include <set>

#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepLib_FindSurface.hxx>
#include <BRepPrimAPI_MakeHalfSpace.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <Bnd_Box.hxx>
#include <gp_Ax3.hxx>
#include <gp_Pln.hxx>
#include <gp_Trsf.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopTools_IndexedMapOfShape.hxx>


#include <App/Document.h>
#include <App/ElementNamingUtils.h>
#include <App/GeoFeature.h>
#include <Base/Exception.h>
#include <Base/ProgramVersion.h>
#include <Base/Tools.h>

#include "FeatureExtrusion.h"
#include "ExtrusionHelper.h"
#include "Part2DObject.h"
#include "TopoShapeOpCode.h"


using namespace Part;

PROPERTY_SOURCE(Part::Extrusion, Part::Feature)

const char* Extrusion::eDirModeStrings[] = {"Custom", "Edge", "Normal", nullptr};
const char* Extrusion::eInnerWireTaperStrings[] = {"Inverted", "SameAsOuter", nullptr};
const char* Extrusion::eEndTypeStrings[] = {"Length", "UpToFace", nullptr};

namespace
{
std::vector<std::string> MakerEnums = {"Simple", "Cheese", "Extrusion", "Bullseye", "Unified"};

const char* enumToClass(const char* mode)
{
    if (MakerEnums.at(0) == mode) {
        return "Part::FaceMakerSimple";
    }
    if (MakerEnums.at(1) == mode) {
        return "Part::FaceMakerCheese";
    }
    if (MakerEnums.at(2) == mode) {
        return "Part::FaceMakerExtrusion";
    }
    if (MakerEnums.at(3) == mode) {
        return "Part::FaceMakerBullseye";
    }
    if (MakerEnums.at(4) == mode) {
        return "Part::FaceMakerUnified";
    }

    return "Part::FaceMakerUnified";
}

const char* classToEnum(const char* type)
{
    if (strcmp(type, "Part::FaceMakerSimple") == 0) {
        return MakerEnums.at(0).c_str();
    }
    if (strcmp(type, "Part::FaceMakerCheese") == 0) {
        return MakerEnums.at(1).c_str();
    }
    if (strcmp(type, "Part::FaceMakerExtrusion") == 0) {
        return MakerEnums.at(2).c_str();
    }
    if (strcmp(type, "Part::FaceMakerBullseye") == 0) {
        return MakerEnums.at(3).c_str();
    }
    if (strcmp(type, "Part::FaceMakerUnified") == 0) {
        return MakerEnums.at(4).c_str();
    }

    return MakerEnums.at(4).c_str();
}

void restoreFaceMakerMode(Extrusion* self)
{
    const char* mode = enumToClass(self->FaceMakerMode.getValueAsString());
    const char* type = self->FaceMakerClass.getValue();
    if (strcmp(mode, type) != 0) {
        self->FaceMakerMode.setValue(classToEnum(type));
    }
}
}  // namespace

Extrusion::Extrusion()
{
    // clang-format off
    ADD_PROPERTY_TYPE(Base, (nullptr), "Extrude", App::Prop_None,
                      "Shape to extrude");
    ADD_PROPERTY_TYPE(Dir, (Base::Vector3d(0.0, 0.0, 1.0)), "Extrude", App::Prop_None,
                      "Direction of extrusion (also magnitude, if both lengths are zero).");
    ADD_PROPERTY_TYPE(DirMode, (dmCustom), "Extrude", App::Prop_None,
                      "Sets, how Dir is updated.");
    DirMode.setEnums(eDirModeStrings);
    ADD_PROPERTY_TYPE(DirLink, (nullptr), "Extrude", App::Prop_None,
                      "Link to edge defining extrusion direction.");
    ADD_PROPERTY_TYPE(LengthFwd, (0.0), "Extrude", App::Prop_None,
                      "Length of extrusion along direction. If both LengthFwd and LengthRev are zero, magnitude of Dir is used.");
    ADD_PROPERTY_TYPE(LengthRev, (0.0), "Extrude", App::Prop_None,
                      "Length of additional extrusion, against direction.");
    ADD_PROPERTY_TYPE(Solid, (false), "Extrude", App::Prop_None,
                      "If true, extruding a wire yields a solid. If false, a shell.");
    ADD_PROPERTY_TYPE(Reversed, (false), "Extrude", App::Prop_None,
                      "Set to true to swap the direction of extrusion.");
    ADD_PROPERTY_TYPE(Symmetric, (false), "Extrude", App::Prop_None,
                      "If true, extrusion is done in both directions to a total of LengthFwd. LengthRev is ignored.");
    ADD_PROPERTY_TYPE(TaperAngle, (0.0), "Extrude", App::Prop_None,
                      "Sets the angle of slope (draft) to apply to the sides. The angle is for outward taper; negative value yields inward tapering.");
    ADD_PROPERTY_TYPE(TaperAngleRev, (0.0), "Extrude", App::Prop_None,
                      "Taper angle of reverse part of extrusion.");
    // Default for old documents. See setupObject for default for new extrusions.
    ADD_PROPERTY_TYPE(FaceMakerClass, ("Part::FaceMakerExtrusion"), "Extrude", (App::PropertyType)(App::Prop_ReadOnly | App::Prop_Hidden),
                      "If Solid is true, this sets the facemaker class to use when converting wires to faces. Otherwise, ignored.");
    ADD_PROPERTY_TYPE(FaceMakerMode, (3L), "Extrude", App::Prop_None,
                      "If Solid is true, this sets the facemaker class to use when converting wires to faces. Otherwise, ignored.");
    FaceMakerMode.setEnums(MakerEnums);
    ADD_PROPERTY_TYPE(InnerWireTaper, (static_cast<long>(InnerWireTaper::Inverted)), "Compatibility", App::Prop_Hidden,
                      "Controls taper direction for inner wires (holes).");
    InnerWireTaper.setEnums(eInnerWireTaperStrings);
    // FreeCAD-CH (ops#919, notes/surface-upto-split-919.md 4a, 4b): picked edges of Base, and a
    // surface up to a face. The defaults are the extrusion as before
    ADD_PROPERTY_TYPE(BaseEdges, (nullptr), "Extrude", App::Prop_None,
                      "The edges of Base to extrude (EdgeN of Base's shape), joined into wires. Empty: all of Base.");
    ADD_PROPERTY_TYPE(EndType, (0L), "Extrude", App::Prop_None,
                      "Length: by LengthFwd. UpToFace: a surface (Solid off) up to the plane of UpToFace.");
    EndType.setEnums(eEndTypeStrings);
    ADD_PROPERTY_TYPE(UpToFace, (nullptr), "Extrude", App::Prop_None,
                      "The planar face the surface runs up to, taken as its whole plane (EndType UpToFace).");
    UpToFace.setScope(App::LinkScope::Global);
    // clang-format on
}

short Extrusion::mustExecute() const
{
    if (Base.isTouched() || Dir.isTouched() || DirMode.isTouched() || DirLink.isTouched()
        || LengthFwd.isTouched() || LengthRev.isTouched() || Solid.isTouched()
        || Reversed.isTouched() || Symmetric.isTouched() || TaperAngle.isTouched()
        || TaperAngleRev.isTouched() || FaceMakerClass.isTouched() || InnerWireTaper.isTouched()
        || BaseEdges.isTouched() || EndType.isTouched() || UpToFace.isTouched()) {
        return 1;
    }
    return 0;
}

bool Extrusion::fetchAxisLink(
    const App::PropertyLinkSub& axisLink,
    Base::Vector3d& basepoint,
    Base::Vector3d& dir
)
{
    if (!axisLink.getValue()) {
        return false;
    }

    auto linked = axisLink.getValue();

    TopoDS_Shape axEdge;
    if (!axisLink.getSubValues().empty() && axisLink.getSubValues()[0].length() > 0) {
        axEdge = Feature::getTopoShape(
                     linked,
                     ShapeOption::NeedSubElement | ShapeOption::ResolveLink | ShapeOption::Transform,
                     axisLink.getSubValues()[0].c_str()
        )
                     .getShape();
    }
    else {
        axEdge = Feature::getShape(linked, ShapeOption::ResolveLink | ShapeOption::Transform);
    }

    if (axEdge.IsNull()) {
        throw Base::ValueError("DirLink shape is null");
    }
    if (axEdge.ShapeType() != TopAbs_EDGE) {
        throw Base::TypeError("DirLink shape is not an edge");
    }

    BRepAdaptor_Curve crv(TopoDS::Edge(axEdge));
    gp_Pnt startpoint;
    gp_Pnt endpoint;
    if (crv.GetType() == GeomAbs_Line) {
        startpoint = crv.Value(crv.FirstParameter());
        endpoint = crv.Value(crv.LastParameter());
        if (axEdge.Orientation() == TopAbs_REVERSED) {
            std::swap(startpoint, endpoint);
        }
    }
    else {
        throw Base::TypeError("DirLink edge is not a line.");
    }
    basepoint.Set(startpoint.X(), startpoint.Y(), startpoint.Z());
    gp_Vec vec = gp_Vec(startpoint, endpoint);
    dir.Set(vec.X(), vec.Y(), vec.Z());
    return true;
}

ExtrusionParameters Extrusion::computeFinalParameters()
{
    using std::numbers::pi;

    ExtrusionParameters result;
    Base::Vector3d dir;
    switch (this->DirMode.getValue()) {
        case dmCustom:
            dir = this->Dir.getValue();
            break;
        case dmEdge: {
            bool fetched;
            Base::Vector3d base;
            fetched = fetchAxisLink(this->DirLink, base, dir);
            if (!fetched) {
                throw Base::ValueError("DirMode is set to use edge, but no edge is linked.");
            }
            this->Dir.setValue(dir);
        } break;
        case dmNormal:
            dir = calculateShapeNormal(this->Base);
            this->Dir.setValue(dir);
            break;
        default:
            throw Base::ValueError("Unexpected enum value");
    }
    if (dir.Length() < Precision::Confusion()) {
        throw Base::ValueError("Direction is zero-length");
    }
    result.dir = gp_Dir(dir.x, dir.y, dir.z);
    if (this->Reversed.getValue()) {
        result.dir.Reverse();
    }

    result.lengthFwd = this->LengthFwd.getValue();
    result.lengthRev = this->LengthRev.getValue();
    if (fabs(result.lengthFwd) < Precision::Confusion()
        && fabs(result.lengthRev) < Precision::Confusion()) {
        result.lengthFwd = dir.Length();
    }

    if (this->Symmetric.getValue()) {
        result.lengthRev = result.lengthFwd * 0.5;
        result.lengthFwd = result.lengthFwd * 0.5;
    }

    // Up to a face the lengths are unused (ops#919)
    if (EndType.getValue() == 0
        && fabs(result.lengthFwd + result.lengthRev) < Precision::Confusion()) {
        throw Base::ValueError("Total length of extrusion is zero.");
    }

    result.solid = this->Solid.getValue();

    result.taperAngleFwd = Base::toRadians(this->TaperAngle.getValue());
    if (fabs(result.taperAngleFwd) > pi * 0.5 - Precision::Angular()) {
        throw Base::ValueError(
            "Magnitude of taper angle matches or exceeds 90 degrees. That is too much."
        );
    }
    result.taperAngleRev = Base::toRadians(this->TaperAngleRev.getValue());
    if (fabs(result.taperAngleRev) > pi * 0.5 - Precision::Angular()) {
        throw Base::ValueError(
            "Magnitude of taper angle matches or exceeds 90 degrees. That is too much."
        );
    }

    result.faceMakerClass = this->FaceMakerClass.getValue();
    result.innerWireTaper = static_cast<Part::InnerWireTaper>(this->InnerWireTaper.getValue());

    return result;
}

Base::Vector3d Extrusion::calculateShapeNormal(const App::PropertyLink& shapeLink)
{
    App::DocumentObject* docobj = nullptr;
    Base::Matrix4D mat;
    TopoDS_Shape sh = Feature::getShape(
        shapeLink.getValue(),
        ShapeOption::ResolveLink | ShapeOption::Transform,
        nullptr,
        &mat,
        &docobj
    );

    if (!docobj) {
        throw Base::ValueError("calculateShapeNormal: link is empty");
    }

    // special case for sketches and the like: no matter what shape they have, use their local Z axis.
    if (docobj->isDerivedFrom<Part::Part2DObject>()) {
        Base::Vector3d OZ(0.0, 0.0, 1.0);
        Base::Vector3d result;
        Base::Rotation(mat).multVec(OZ, result);
        return result;
    }

    if (sh.IsNull()) {
        throw NullShapeException(
            "calculateShapeNormal: link points to a valid object, but its shape is null."
        );
    }

    // find plane
    BRepLib_FindSurface planeFinder(sh, -1, /*OnlyPlane=*/true);
    if (!planeFinder.Found()) {
        throw Base::ValueError("Can't find normal direction, because the shape is not on a plane.");
    }

    // find plane normal and return result.
    GeomAdaptor_Surface surf(planeFinder.Surface());
    gp_Dir normal = surf.Plane().Axis().Direction();

    // now we know the plane. But if there are faces, the
    // plane normal direction is not dependent on face orientation (because findPlane only uses
    // edges). let's fix that.
    TopExp_Explorer ex(sh, TopAbs_FACE);
    if (ex.More()) {
        BRepAdaptor_Surface surf(TopoDS::Face(ex.Current()));
        normal = surf.Plane().Axis().Direction();
        if (ex.Current().Orientation() == TopAbs_REVERSED) {
            normal.Reverse();
        }
    }

    return Base::Vector3d(normal.X(), normal.Y(), normal.Z());
}

void Extrusion::extrudeShape(TopoShape& result, const TopoShape& source, const ExtrusionParameters& params)
{
    gp_Vec vec = gp_Vec(params.dir).Multiplied(params.lengthFwd + params.lengthRev);  // total vector
                                                                                      // of extrusion

    // #0000910: Circles Extrude Only Surfaces, thus use BRepBuilderAPI_Copy
    TopoShape myShape(source.makeElementCopy());
    myShape.Tag = result.Tag;

    if (std::fabs(params.taperAngleFwd) >= Precision::Angular()
        || std::fabs(params.taperAngleRev) >= Precision::Angular()) {
        // Tapered extrusion!
#if defined(__GNUC__) && defined(FC_OS_LINUX)
        Base::SignalException se;
#endif
        std::vector<TopoShape> drafts;
        ExtrusionHelper::makeElementDraft(params, myShape, drafts, result.Hasher);
        if (drafts.empty()) {
            throw Standard_Failure("Drafting shape failed");
        }
        else {
            result.makeElementCompound(
                drafts,
                0,
                TopoShape::SingleShapeCompoundCreationPolicy::returnShape
            );
        }
    }
    else {
        // Regular (non-tapered) extrusion!
        if (source.isNull()) {
            throw Standard_Failure("Cannot extrude empty shape");
        }

        // apply reverse part of extrusion by shifting the source shape
        if (fabs(params.lengthRev) > Precision::Confusion()) {
            gp_Trsf mov;
            mov.SetTranslation(gp_Vec(params.dir) * (-params.lengthRev));
            myShape = myShape.makeElementTransform(mov);
        }

        // make faces from wires
        if (params.solid) {
            // test if we need to make faces from wires. If there are faces - we don't.
            if (!myShape.hasSubShape(TopAbs_FACE)) {
                if (!myShape.Hasher) {
                    myShape.Hasher = result.Hasher;
                }
                myShape = myShape.makeElementFace(nullptr, params.faceMakerClass.c_str());
            }
        }

        // extrude!
        result.makeElementPrism(myShape, vec);
    }
}

namespace
{
std::string objectLabel(const App::DocumentObject* obj)
{
    return obj ? obj->Label.getValue() : "None";
}

/// The name of an edge of a shape, "Edge<n>": the only names BaseEdges takes. A sketch's
/// "edge<n>" (its geometry index) and "ExternalEdge<n>" are other numberings (ops#919 4a)
bool isShapeEdgeName(const std::string& name)
{
    if (name.size() <= 4 || name.compare(0, 4, "Edge") != 0) {
        return false;
    }
    return std::all_of(name.begin() + 4, name.end(), [](unsigned char c) {
        return std::isdigit(c) != 0;
    });
}

/// Where @p obj's containers place it: its global placement without its own
Base::Placement containerPlacement(const App::DocumentObject* obj)
{
    auto geo = freecad_cast<const App::GeoFeature*>(obj);
    if (!geo) {
        return {};
    }
    return App::GeoFeature::getGlobalPlacement(obj) * geo->Placement.getValue().inverse();
}

/// Whether some point of @p edges is the end of more than two of them: such edges branch and
/// make no sheet that one wire would
bool branches(const std::vector<TopoShape>& edges)
{
    std::vector<gp_Pnt> ends;
    for (const auto& edge : edges) {
        TopoDS_Vertex first;
        TopoDS_Vertex last;
        TopExp::Vertices(TopoDS::Edge(edge.getShape()), first, last);
        if (first.IsNull() || last.IsNull()) {
            continue;
        }
        ends.push_back(BRep_Tool::Pnt(first));
        ends.push_back(BRep_Tool::Pnt(last));
    }
    for (const auto& point : ends) {
        int count = 0;
        for (const auto& other : ends) {
            if (point.Distance(other) <= Precision::Confusion()) {
                ++count;
            }
        }
        if (count > 2) {
            return true;
        }
    }
    return false;
}
}  // namespace

TopoShape Extrusion::baseShape() const
{
    App::DocumentObject* link = Base.getValue();
    const std::vector<std::string>& subs = BaseEdges.getSubValues();
    App::DocumentObject* edgesOf = BaseEdges.getValue();
    if (!edgesOf && subs.empty()) {
        return Feature::getTopoShape(link, ShapeOption::ResolveLink | ShapeOption::Transform);
    }
    // FreeCAD-CH (ops#919 4a): picked edges of Base, by their names in Base's shape. The link
    // keeps each name's mapped name, so an edit that renumbers the edges is followed
    if (edgesOf != link) {
        throw Base::ValueError(
            "BaseEdges names edges of " + objectLabel(edgesOf) + ", not of Base ("
            + objectLabel(link) + ")"
        );
    }
    if (subs.empty()) {
        return Feature::getTopoShape(link, ShapeOption::ResolveLink | ShapeOption::Transform);
    }
    std::set<std::string> seen;
    std::vector<TopoShape> edges;
    for (const auto& sub : subs) {
        const std::string name = Data::oldElementName(Data::findElementName(sub.c_str()));
        if (Data::hasMissingElement(sub.c_str())) {
            throw Base::ValueError(
                "Missing element in BaseEdges: " + objectLabel(link) + "." + name
            );
        }
        if (!isShapeEdgeName(name)) {
            throw Base::ValueError(
                "BaseEdges takes the edges of " + objectLabel(link) + "'s shape (EdgeN), not "
                + name
            );
        }
        if (!seen.insert(name).second) {
            throw Base::ValueError("BaseEdges names " + name + " twice");
        }
        TopoShape edge = Feature::getTopoShape(
            link,
            ShapeOption::NeedSubElement | ShapeOption::ResolveLink | ShapeOption::Transform,
            sub.c_str()
        );
        if (edge.isNull() || edge.getShape().ShapeType() != TopAbs_EDGE) {
            throw Base::ValueError(
                "Missing element in BaseEdges: " + objectLabel(link) + "." + name
            );
        }
        edges.push_back(edge);
    }
    if (branches(edges)) {
        throw Base::ValueError(
            "BaseEdges of " + objectLabel(link) + " branch: more than two meet at a point"
        );
    }
    TopoShape wires = makeTopoShape(0L);
    wires.makeElementWires(edges);
    if (wires.isNull()) {
        throw Base::ValueError("BaseEdges of " + objectLabel(link) + " make no wire");
    }
    return wires;
}

void Extrusion::extrudeUpToFace(TopoShape& result, const TopoShape& profile, ExtrusionParameters params)
{
    // FreeCAD-CH (ops#919 4b): a surface, one way, from the profile
    if (Solid.getValue()) {
        throw Base::ValueError("EndType UpToFace makes a surface: set Solid to false");
    }
    if (Symmetric.getValue()) {
        throw Base::ValueError("EndType UpToFace runs one way: set Symmetric to false");
    }
    if (std::fabs(params.taperAngleFwd) >= Precision::Angular()
        || std::fabs(params.taperAngleRev) >= Precision::Angular()) {
        throw Base::ValueError("EndType UpToFace takes no taper: set TaperAngle and TaperAngleRev to 0");
    }
    if (std::fabs(LengthRev.getValue()) > Precision::Confusion()) {
        throw Base::ValueError("EndType UpToFace runs from the profile: set LengthRev to 0");
    }
    App::DocumentObject* target = UpToFace.getValue();
    if (!target) {
        throw Base::ValueError("EndType is UpToFace, but UpToFace links no face");
    }
    const std::vector<std::string>& subs = UpToFace.getSubValues();
    if (subs.size() > 1) {
        throw Base::ValueError("UpToFace takes one face");
    }
    const std::string sub = subs.empty() ? std::string() : subs.front();
    const std::string element = Data::oldElementName(Data::findElementName(sub.c_str()));
    const std::string name = objectLabel(target) + (sub.empty() ? "" : "." + element);
    if (Data::hasMissingElement(sub.c_str())) {
        throw Base::ValueError("Missing element in UpToFace: " + name);
    }
    TopoShape face = sub.empty()
        ? Feature::getTopoShape(target, ShapeOption::ResolveLink | ShapeOption::Transform)
        : Feature::getTopoShape(
              target,
              ShapeOption::NeedSubElement | ShapeOption::ResolveLink | ShapeOption::Transform,
              sub.c_str()
          );
    if (sub.empty() && !face.isNull() && face.countSubShapes(TopAbs_FACE) == 1
        && face.countSubShapes(TopAbs_SOLID) == 0) {
        face = face.getSubTopoShape(TopAbs_FACE, 1);
    }
    if (face.isNull() || face.getShape().ShapeType() != TopAbs_FACE) {
        throw Base::ValueError("UpToFace: " + name + " isn't a face");
    }
    // The target's place in the document, in this object's frame: the extrusion sits beside
    // the part whose face it runs to, and a part's features are placed by their Body
    const Base::Placement frame = containerPlacement(this).inverse() * containerPlacement(target);
    if (!frame.isIdentity()) {
        face.transformShape(frame.toMatrix(), false, true);
    }
    BRepAdaptor_Surface surface(TopoDS::Face(face.getShape()));
    if (surface.GetType() != GeomAbs_Plane) {
        throw Base::ValueError(
            "UpToFace: " + name + " isn't planar: a surface runs up to a planar face"
        );
    }
    const gp_Pln plane = surface.Plane();
    const gp_Dir normal = plane.Axis().Direction();
    const double along = gp_Vec(params.dir).Dot(gp_Vec(normal));
    const std::string notAhead = "UpToFace: " + name
        + " is not ahead of the profile in the extrude's direction";
    if (std::fabs(along) < Precision::Angular()) {
        throw Base::ValueError(notAhead);
    }
    // The profile's signed distances to the plane: a point at z runs -z / along to it
    gp_Trsf toPlane;
    toPlane.SetTransformation(gp_Ax3(plane.Position()));
    BRepBuilderAPI_Transform moved(profile.getShape(), toPlane, /*copy=*/true);
    Bnd_Box box;
    BRepBndLib::AddOptimal(moved.Shape(), box, /*useTriangulation=*/false, /*useShapeTolerance=*/false);
    if (box.IsVoid()) {
        throw Standard_Failure("Cannot extrude empty shape");
    }
    double xMin, yMin, zMin, xMax, yMax, zMax;
    box.Get(xMin, yMin, zMin, xMax, yMax, zMax);
    const double tMin = std::min(-zMin / along, -zMax / along);
    const double tMax = std::max(-zMin / along, -zMax / along);
    // Every point of the profile meets the plane ahead of it (Onshape: EXTRUDE_FAILED, SU4)
    if (tMin <= Precision::Confusion()) {
        throw Base::ValueError(notAhead);
    }
    params.lengthRev = 0.0;
    params.solid = false;
    // A profile parallel to the plane: the blind sheet of that length, its names included
    if (tMax - tMin <= Precision::Confusion()) {
        params.lengthFwd = 0.5 * (tMin + tMax);
        extrudeShape(result, profile, params);
        return;
    }
    // A slanted plane: the sheet run past the plane everywhere, kept on the profile's side
    params.lengthFwd = tMax + std::max(1.0, tMax);
    TopoShape prism = makeTopoShape(getID());
    extrudeShape(prism, profile, params);
    const gp_Pnt inside = plane.Location().Translated(gp_Vec(normal) * (along > 0.0 ? -1.0 : 1.0));
    BRepBuilderAPI_MakeFace planeFace(plane);
    BRepPrimAPI_MakeHalfSpace space(planeFace.Face(), inside);
    TopoShape spaceShape = makeTopoShape(-getID());
    spaceShape.setShape(space.Solid());
    spaceShape.Tag = -getID();
    result.makeElementBoolean(Part::OpCodes::Common, {prism, spaceShape});
    if (result.isNull() || !result.hasSubShape(TopAbs_FACE)) {
        throw Base::ValueError("Could not extrude up to " + name);
    }
}

App::DocumentObjectExecReturn* Extrusion::execute()
{
    App::DocumentObject* link = Base.getValue();
    if (!link) {
        return new App::DocumentObjectExecReturn("No object linked");
    }

    try {
        ExtrusionParameters params = computeFinalParameters();
        TopoShape result = makeTopoShape(getID());

        const TopoShape source = baseShape();
        if (EndType.getValue() == 1) {
            extrudeUpToFace(result, source, params);
        }
        else {
            extrudeShape(result, source, params);
        }
        this->Shape.setValue(result);
        return App::DocumentObject::StdReturn;
    }
    catch (Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }
}

//----------------------------------------------------------------

TYPESYSTEM_SOURCE(Part::FaceMakerExtrusion, Part::FaceMakerCheese)

std::string FaceMakerExtrusion::getUserFriendlyName() const
{
    return {tr("Part Extrude facemaker").toStdString()};
}

std::string FaceMakerExtrusion::getBriefExplanation() const
{
    return {tr("Supports making faces with holes, does not support nesting.").toStdString()};
}

#if OCC_VERSION_HEX >= 0x070600
void FaceMakerExtrusion::Build(const Message_ProgressRange&)
#else
void FaceMakerExtrusion::Build()
#endif
{
    this->NotDone();
    this->myGenerated.Clear();
    this->myShapesToReturn.clear();
    this->myShape = TopoDS_Shape();
    TopoDS_Shape inputShape;
    if (mySourceShapes.empty()) {
        throw Base::ValueError("No input shapes!");
    }
    if (mySourceShapes.size() == 1) {
        inputShape = mySourceShapes[0].getShape();
    }
    else {
        TopoDS_Builder builder;
        TopoDS_Compound cmp;
        builder.MakeCompound(cmp);
        for (const auto& sh : mySourceShapes) {
            builder.Add(cmp, sh.getShape());
        }
        inputShape = cmp;
    }

    std::vector<TopoDS_Wire> wires;
    TopTools_IndexedMapOfShape mapOfWires;
    TopExp::MapShapes(inputShape, TopAbs_WIRE, mapOfWires);

    // if there are no wires then check also for edges
    if (mapOfWires.IsEmpty()) {
        TopTools_IndexedMapOfShape mapOfEdges;
        TopExp::MapShapes(inputShape, TopAbs_EDGE, mapOfEdges);
        for (int i = 1; i <= mapOfEdges.Extent(); i++) {
            BRepBuilderAPI_MakeWire mkWire(TopoDS::Edge(mapOfEdges.FindKey(i)));
            wires.push_back(mkWire.Wire());
        }
    }
    else {
        wires.reserve(mapOfWires.Extent());
        for (int i = 1; i <= mapOfWires.Extent(); i++) {
            wires.push_back(TopoDS::Wire(mapOfWires.FindKey(i)));
        }
    }

    if (!wires.empty()) {
        TopoDS_Shape res = FaceMakerCheese::makeFace(wires);
        if (!res.IsNull()) {
            this->myShape = res;
        }
    }
    postBuild();
}

void Part::Extrusion::setupObject()
{
    Part::Feature::setupObject();
    // default for newly created features
    this->FaceMakerMode.setValue(MakerEnums.at(4).c_str());
    this->FaceMakerClass.setValue("Part::FaceMakerUnified");
}

void Extrusion::onDocumentRestored()
{
    restoreFaceMakerMode(this);
}

void Extrusion::Restore(Base::XMLReader& reader)
{
    Part::Feature::Restore(reader);

    // for 1.0 the inner wire taper was not inverted due to a bug
    if (Base::getVersion(reader.ProgramVersion) == Base::Version::v1_0) {
        InnerWireTaper.setValue(static_cast<long>(Part::InnerWireTaper::SameAsOuter));
    }
}

void Part::Extrusion::onChanged(const App::Property* prop)
{
    if (prop == &FaceMakerMode) {
        if (!isRestoring()) {
            FaceMakerClass.setValue(enumToClass(FaceMakerMode.getValueAsString()));
        }
    }

    Part::Feature::onChanged(prop);
}
