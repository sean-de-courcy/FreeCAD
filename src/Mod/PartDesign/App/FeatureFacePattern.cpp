// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD project.

/******************************************************************************
 *                                                                            *
 *   FreeCAD is free software: you can redistribute it and/or modify          *
 *   it under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1            *
 *   of the License, or (at your option) any later version.                   *
 *                                                                            *
 *   FreeCAD is distributed in the hope that it will be useful,               *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty              *
 *   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                  *
 *   See the GNU Lesser General Public License for more details.              *
 *                                                                            *
 *   You should have received a copy of the GNU Lesser General Public         *
 *   License along with FreeCAD. If not, see https://www.gnu.org/licenses     *
 *                                                                            *
 ******************************************************************************/

#include <algorithm>
#include <string>

#include <cmath>
#include <utility>

#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepTools.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Ax2.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt2d.hxx>

#include <App/Datums.h>
#include <Base/Exception.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include "DatumLine.h"
#include "DatumPlane.h"
#include "FeatureFacePattern.h"


using namespace PartDesign;

namespace
{

double volumeOf(const TopoDS_Shape& shape)
{
    if (shape.IsNull()) {
        return 0.0;
    }
    GProp_GProps props;
    BRepGProp::VolumeProperties(shape, props);
    return props.Mass();
}

/// Points of a 5 x 5 grid inside the face, with the face's outward normal at each
std::vector<std::pair<gp_Pnt, gp_Dir>> gridOn(const TopoDS_Face& face)
{
    std::vector<std::pair<gp_Pnt, gp_Dir>> points;
    BRepAdaptor_Surface surface(face);
    double u0 = 0.0;
    double u1 = 0.0;
    double v0 = 0.0;
    double v1 = 0.0;
    BRepTools::UVBounds(face, u0, u1, v0, v1);
    constexpr int steps = 6;
    for (int i = 1; i < steps; ++i) {
        for (int j = 1; j < steps; ++j) {
            const double u = u0 + (u1 - u0) * i / steps;
            const double v = v0 + (v1 - v0) * j / steps;
            BRepClass_FaceClassifier inFace(face, gp_Pnt2d(u, v), Precision::Confusion());
            if (inFace.State() != TopAbs_IN) {
                continue;
            }
            gp_Pnt point;
            gp_Vec du;
            gp_Vec dv;
            surface.D1(u, v, point, du, dv);
            gp_Vec normal = du.Crossed(dv);
            if (normal.Magnitude() < Precision::Confusion()) {
                continue;
            }
            if (face.Orientation() == TopAbs_REVERSED) {
                normal.Reverse();
            }
            points.emplace_back(point, gp_Dir(normal));
        }
    }
    return points;
}

bool isApart(const TopoDS_Shape& a, const TopoDS_Shape& b)
{
    BRepExtrema_DistShapeShape distance(a, b);
    return distance.IsDone() && distance.Value() > Precision::Confusion();
}

/// Whether the volumes overlap: their union is smaller than the sum of their volumes
bool overlap(const std::vector<TopoDS_Shape>& volumes, double tiny)
{
    if (volumes.size() < 2) {
        return false;
    }
    double sum = 0.0;
    TopTools_ListOfShape first;
    TopTools_ListOfShape rest;
    for (const TopoDS_Shape& volume : volumes) {
        sum += volumeOf(volume);
        (first.IsEmpty() ? first : rest).Append(volume);
    }
    BRepAlgoAPI_Fuse fuse;
    fuse.SetRunParallel(true);
    fuse.SetArguments(first);
    fuse.SetTools(rest);
    fuse.Build();
    if (!fuse.IsDone()) {
        throw Base::RuntimeError("Face pattern: the instances can't be compared");
    }
    return sum - volumeOf(fuse.Shape()) > std::max(tiny, 1e-7 * sum);
}

/// Where the added volume stands on the base: points just outside it across its faces that are
/// not the picked faces' (a boss's foot on the plate). The base must be under each copy's points.
struct Footing
{
    std::vector<gp_Pnt> points;

    bool standsOn(const TopoDS_Shape& base, const gp_Trsf& trsf) const
    {
        for (gp_Pnt point : points) {
            point.Transform(trsf);
            BRepClass3d_SolidClassifier inBase(base, point, Precision::Confusion());
            if (inBase.State() != TopAbs_IN) {
                return false;
            }
        }
        return true;
    }
};

Footing footingOf(const Part::TopoShape& added, const std::vector<Part::TopoShape>& picks)
{
    Bnd_Box box;
    BRepBndLib::Add(added.getShape(), box);
    const double nudge = std::max(1e-4 * std::sqrt(box.SquareExtent()), 10 * Precision::Confusion());
    auto onAPick = [&](const gp_Pnt& point) {
        const TopoDS_Vertex vertex = BRepBuilderAPI_MakeVertex(point);
        return std::ranges::any_of(picks, [&](const Part::TopoShape& pick) {
            BRepExtrema_DistShapeShape distance(vertex, pick.getShape());
            return distance.IsDone() && distance.Value() < 10 * Precision::Confusion();
        });
    };
    Footing footing;
    for (TopExp_Explorer xp(added.getShape(), TopAbs_FACE); xp.More(); xp.Next()) {
        const auto grid = gridOn(TopoDS::Face(xp.Current()));
        if (grid.empty() || onAPick(grid[grid.size() / 2].first)) {
            continue;
        }
        for (const auto& [point, normal] : grid) {
            footing.points.push_back(point.Translated(gp_Vec(normal) * nudge));
        }
    }
    return footing;
}

}  // namespace


// ---------------------------------------------------------------------------------------------
// FacePattern
// ---------------------------------------------------------------------------------------------

PROPERTY_SOURCE(PartDesign::FacePattern, PartDesign::DressUp)

FacePattern::FacePattern() = default;

short FacePattern::mustExecute() const
{
    return DressUp::mustExecute();
}

std::vector<gp_Trsf> FacePattern::instanceTransforms()
{
    return {gp_Trsf()};
}

std::vector<std::size_t> FacePattern::skippedPositions() const
{
    return {};
}

std::vector<gp_Trsf> FacePattern::centered(
    const std::list<gp_Trsf>& transformations,
    int rows,
    int columns,
    bool centerRows,
    bool centerColumns
)
{
    std::vector<gp_Trsf> list(transformations.begin(), transformations.end());
    const int middleRow = centerRows ? (rows - 1) / 2 : 0;
    const int middleColumn = centerColumns ? (columns - 1) / 2 : 0;
    if (rows < 1 || columns < 1 || static_cast<std::size_t>(rows) * columns != list.size()
        || (middleRow == 0 && middleColumn == 0)) {
        return list;
    }
    const gp_Trsf toMiddle
        = list[static_cast<std::size_t>(middleRow) * columns + middleColumn].Inverted();
    std::vector<gp_Trsf> result(list.size());
    for (int row = 0; row < rows; ++row) {
        for (int column = 0; column < columns; ++column) {
            const auto from = static_cast<std::size_t>(row) * columns + column;
            const auto to = static_cast<std::size_t>(centeredIndex(row, middleRow)) * columns
                + centeredIndex(column, middleColumn);
            result[to] = toMiddle.Multiplied(list[from]);
        }
    }
    return result;
}

App::DocumentObjectExecReturn* FacePattern::execute()
{
    if (onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }

    Part::TopoShape baseShape;
    try {
        baseShape = getBaseTopoShape();
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    baseShape.locate(TopLoc_Location());

    std::vector<Part::TopoShape> faces;
    try {
        faces = getFaces(baseShape);  // fails on a missing face (ops#60)
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    this->positionByBaseFeature();
    if (faces.empty()) {
        // Onshape: "Faces to pattern" is required
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Face pattern: pick the faces to pattern")
        );
    }

    std::vector<gp_Trsf> transforms;
    std::vector<std::size_t> skipped;
    try {
        transforms = instanceTransforms();
        skipped = skippedPositions();
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    catch (Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }

    try {
        // The feature volume: the base without the picked faces' boss, pocket or hole, healed;
        // what the faces add (the base minus that) and what they remove (that minus the base)
        Part::TopoShape without = makeTopoShape(false);
        without.makeElementDefeaturing(baseShape, faces);
        if (without.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Face pattern: the picked faces can't be removed from the part")
            );
        }
        const double scale = std::max(volumeOf(baseShape.getShape()), 1.0);
        const double tiny = 1e-9 * scale;
        Part::TopoShape add = baseShape.makeElementCut(without);
        Part::TopoShape sub = without.makeElementCut(baseShape);
        const bool adds = volumeOf(add.getShape()) > tiny;
        const bool subs = volumeOf(sub.getShape()) > tiny;
        if (!adds && !subs) {
            // Onshape: PATTERN_FACE_FAILED (a boss's top alone), PATTERN_NOT_ON_BODY (its sides)
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Face pattern: the picked faces don't bound a boss, pocket or hole: pick all of its faces"
            ));
        }
        const Footing footing = adds ? footingOf(add, faces) : Footing();

        const bool nameInstances = getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V2;
        std::vector<Part::TopoShape> addCopies {baseShape};
        std::vector<Part::TopoShape> subCopies;
        std::vector<TopoDS_Shape> checked;  // the seed's and the kept copies' volumes
        if (adds) {
            checked.push_back(add.getShape());
        }
        if (subs) {
            checked.push_back(sub.getShape());
        }
        for (std::size_t position = 1; position < transforms.size(); ++position) {
            if (std::ranges::find(skipped, position) != skipped.end()) {
                continue;
            }
            const gp_Trsf& trsf = transforms[position];
            auto copyOf = [&](const Part::TopoShape& volume) {
                Part::TopoShape copy = makeTopoShape(false);
                copy.makeElementTransform(volume, trsf);
                if (nameInstances) {
                    copy.appendElementSection(getID(), Part::OpCodes::Transformed, std::to_string(position));
                }
                return copy;
            };
            // Onshape (FP4): an instance entirely off the part is dropped silently
            Part::TopoShape addCopy = adds ? copyOf(add) : Part::TopoShape();
            Part::TopoShape subCopy = subs ? copyOf(sub) : Part::TopoShape();
            const bool addOff = adds && isApart(addCopy.getShape(), baseShape.getShape());
            const bool subOff = subs && isApart(subCopy.getShape(), baseShape.getShape());
            if ((!adds || addOff) && (!subs || subOff)) {
                continue;
            }
            // Onshape stretches a boss partly off the part down to meet it (FP4, 11720); a copy
            // can't, so that stops here (decision 150)
            if (adds && !addOff && !footing.standsOn(baseShape.getShape(), trsf)) {
                std::string text = "Face pattern: instance " + std::to_string(position + 1)
                    + " is partly off the part";
                return new App::DocumentObjectExecReturn(text.c_str());
            }
            if (adds && !addOff) {
                addCopies.push_back(addCopy);
                checked.push_back(addCopy.getShape());
            }
            if (subs && !subOff) {
                subCopies.push_back(subCopy);
                checked.push_back(subCopy.getShape());
            }
        }
        // Onshape (FP5): overlapping instances fail, PATTERN_FACE_FAILED; touching is fine
        if (overlap(checked, tiny)) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Face pattern: instances overlap")
            );
        }

        Part::TopoShape result = baseShape;
        if (addCopies.size() > 1) {
            result = makeTopoShape(false);
            result.makeElementFuse(addCopies);
        }
        if (!subCopies.empty()) {
            std::vector<Part::TopoShape> cut {result};
            cut.insert(cut.end(), subCopies.begin(), subCopies.end());
            result = makeTopoShape(false);
            result.makeElementCut(cut);
        }
        if (result.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Face pattern: result is null")
            );
        }
        this->rawShape = result;
        result = refineShapeIfActive(result);
        if (countSolids(result.getShape()) != 1) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Face pattern: the result is not a single solid")
            );
        }
        this->Shape.setValue(getSolid(result));
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    catch (Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }
    return App::DocumentObject::StdReturn;
}


// ---------------------------------------------------------------------------------------------
// FaceLinearPattern
// ---------------------------------------------------------------------------------------------

PROPERTY_SOURCE_WITH_EXTENSIONS(PartDesign::FaceLinearPattern, PartDesign::FacePattern)

FaceLinearPattern::FaceLinearPattern()
{
    Part::LinearPatternExtension::initExtension(this);
    ADD_PROPERTY_TYPE(
        Centered,
        (false),
        "Direction 1",
        App::Prop_None,
        "The instances run both ways from the original, which is the middle one"
    );
    ADD_PROPERTY_TYPE(
        Centered2,
        (false),
        "Direction 2",
        App::Prop_None,
        "The instances run both ways from the original in the second direction"
    );
    ADD_PROPERTY_TYPE(
        SkippedInstances,
        (),
        "Skip",
        App::Prop_None,
        "Instances not made: (i, j) index pairs, flattened, counted from 0 at the negative end of "
        "each direction"
    );
}

gp_Dir FaceLinearPattern::getDirectionFromProperty(const App::PropertyLinkSub& dirProp) const
{
    // As LinearPattern: datums are placed in the document, the result in the base's frame
    App::DocumentObject* refObject = dirProp.getValue();
    if (!refObject) {
        throw Base::ValueError("No direction reference specified");
    }
    const TopLoc_Location invObjLoc = this->getLocation().Inverted();
    if (auto* plane = freecad_cast<PartDesign::Plane*>(refObject)) {
        Base::Vector3d d = plane->getNormal();
        gp_Dir dir(d.x, d.y, d.z);
        dir.Transform(invObjLoc.Transformation());
        return dir;
    }
    if (auto* line = freecad_cast<PartDesign::Line*>(refObject)) {
        Base::Vector3d d = line->getDirection();
        gp_Dir dir(d.x, d.y, d.z);
        dir.Transform(invObjLoc.Transformation());
        return dir;
    }
    if (auto* feature = freecad_cast<Part::Feature*>(refObject)) {
        const auto& subs = dirProp.getSubValues();
        if (!subs.empty() && subs[0].compare(0, 4, "Face") == 0) {
            TopoDS_Shape ref
                = feature->Shape.getShape().getSubShape(subs[0].c_str(), /*silent=*/true);
            if (!ref.IsNull() && ref.ShapeType() == TopAbs_FACE) {
                BRepAdaptor_Surface adapt(TopoDS::Face(ref));
                if (adapt.GetType() == GeomAbs_Cylinder) {
                    gp_Dir dir = adapt.Cylinder().Axis().Direction();
                    dir.Transform(invObjLoc.Transformation());
                    return dir;
                }
            }
        }
    }
    return Part::LinearPatternExtension::getDirectionFromProperty(dirProp);
}

std::vector<gp_Trsf> FaceLinearPattern::instanceTransforms()
{
    const int first = std::max(static_cast<int>(Occurrences.getValue()), 1);
    const int second = std::max(static_cast<int>(Occurrences2.getValue()), 1);
    return centered(calculateTransformations(), first, second, Centered.getValue(), Centered2.getValue());
}

std::vector<std::size_t> FaceLinearPattern::skippedPositions() const
{
    const int first = std::max(static_cast<int>(Occurrences.getValue()), 1);
    const int second = std::max(static_cast<int>(Occurrences2.getValue()), 1);
    const int middle = Centered.getValue() ? (first - 1) / 2 : 0;
    const int middle2 = Centered2.getValue() ? (second - 1) / 2 : 0;
    const auto& pairs = SkippedInstances.getValues();
    std::vector<std::size_t> positions;
    for (std::size_t k = 0; k + 1 < pairs.size(); k += 2) {
        const long i = pairs[k];
        const long j = pairs[k + 1];
        if (i < 0 || i >= first || j < 0 || j >= second) {
            continue;
        }
        const auto position = static_cast<std::size_t>(centeredIndex(static_cast<int>(i), middle))
                * static_cast<std::size_t>(second)
            + static_cast<std::size_t>(centeredIndex(static_cast<int>(j), middle2));
        if (position != 0) {
            positions.push_back(position);
        }
    }
    return positions;
}


// ---------------------------------------------------------------------------------------------
// FacePolarPattern
// ---------------------------------------------------------------------------------------------

PROPERTY_SOURCE_WITH_EXTENSIONS(PartDesign::FacePolarPattern, PartDesign::FacePattern)

FacePolarPattern::FacePolarPattern()
{
    Part::PolarPatternExtension::initExtension(this);
    ADD_PROPERTY_TYPE(
        Centered,
        (false),
        "PolarPattern",
        App::Prop_None,
        "The instances run both ways from the original, which is the middle one"
    );
    ADD_PROPERTY_TYPE(
        SkippedInstances,
        (),
        "Skip",
        App::Prop_None,
        "Instances not made: indexes counted from 0 at the first instance"
    );
}

gp_Ax2 FacePolarPattern::getRotation() const
{
    // As PolarPattern: a datum line is placed in the document, the axis in the base's frame
    App::DocumentObject* refObject = Axis.getValue();
    if (auto* line = freecad_cast<PartDesign::Line*>(refObject)) {
        Base::Vector3d base = line->getBasePoint();
        gp_Pnt axbase(base.x, base.y, base.z);
        Base::Vector3d dir = line->getDirection();
        gp_Dir axdir(dir.x, dir.y, dir.z);
        TopLoc_Location invObjLoc = this->getLocation().Inverted();
        axbase.Transform(invObjLoc.Transformation());
        axdir.Transform(invObjLoc.Transformation());
        gp_Ax2 axis(axbase, axdir);
        if (Reversed.getValue()) {
            axis.SetDirection(axis.Direction().Reversed());
        }
        return axis;
    }
    return Part::PolarPatternExtension::getRotation();
}

std::vector<gp_Trsf> FacePolarPattern::instanceTransforms()
{
    const int count = std::max(static_cast<int>(Occurrences.getValue()), 1);
    return centered(calculateTransformations(), count, 1, Centered.getValue(), false);
}

std::vector<std::size_t> FacePolarPattern::skippedPositions() const
{
    const int count = std::max(static_cast<int>(Occurrences.getValue()), 1);
    const int middle = Centered.getValue() ? (count - 1) / 2 : 0;
    std::vector<std::size_t> positions;
    for (long index : SkippedInstances.getValues()) {
        if (index < 0 || index >= count) {
            continue;
        }
        const auto position = static_cast<std::size_t>(centeredIndex(static_cast<int>(index), middle));
        if (position != 0) {
            positions.push_back(position);
        }
    }
    return positions;
}


// ---------------------------------------------------------------------------------------------
// FaceMirrored
// ---------------------------------------------------------------------------------------------

PROPERTY_SOURCE(PartDesign::FaceMirrored, PartDesign::FacePattern)

FaceMirrored::FaceMirrored()
{
    ADD_PROPERTY_TYPE(MirrorPlane, (nullptr), "Mirrored", App::Prop_None, "Mirror plane");
}

std::vector<gp_Trsf> FaceMirrored::instanceTransforms()
{
    App::DocumentObject* refObject = MirrorPlane.getValue();
    if (!refObject) {
        throw Base::ValueError("No mirror plane reference specified");
    }
    gp_Pnt axbase;
    gp_Dir axdir;
    if (auto* plane = freecad_cast<PartDesign::Plane*>(refObject)) {
        Base::Vector3d base = plane->getBasePoint();
        Base::Vector3d dir = plane->getNormal();
        axbase = gp_Pnt(base.x, base.y, base.z);
        axdir = gp_Dir(dir.x, dir.y, dir.z);
    }
    else if (auto* plane = freecad_cast<App::Plane*>(refObject)) {
        Base::Vector3d base = plane->getBasePoint();
        Base::Vector3d dir = plane->getDirection();
        axbase = gp_Pnt(base.x, base.y, base.z);
        axdir = gp_Dir(dir.x, dir.y, dir.z);
    }
    else if (auto* feature = freecad_cast<Part::Feature*>(refObject)) {
        const auto& subs = MirrorPlane.getSubValues();
        if (subs.empty() || subs[0].empty()) {
            throw Base::ValueError("No mirror plane reference specified");
        }
        TopoDS_Shape ref = feature->Shape.getShape().getSubShape(subs[0].c_str(), /*silent=*/true);
        if (ref.IsNull() || ref.ShapeType() != TopAbs_FACE) {
            throw Base::ValueError("Mirror plane reference must be a planar face");
        }
        BRepAdaptor_Surface adapt(TopoDS::Face(ref));
        if (adapt.GetType() != GeomAbs_Plane) {
            throw Base::TypeError("Mirror face must be planar");
        }
        axbase = adapt.Plane().Location();
        axdir = adapt.Plane().Axis().Direction();
    }
    else {
        throw Base::ValueError("Mirror plane reference must be a face or a datum or origin plane");
    }
    const TopLoc_Location invObjLoc = this->getLocation().Inverted();
    axbase.Transform(invObjLoc.Transformation());
    axdir.Transform(invObjLoc.Transformation());
    gp_Trsf mirror;
    mirror.SetMirror(gp_Ax2(axbase, axdir));
    return {gp_Trsf(), mirror};
}
