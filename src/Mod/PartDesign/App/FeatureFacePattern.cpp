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
#include <memory>
#include <optional>
#include <utility>

#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Defeaturing.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepTools.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <IntCurvesFace_ShapeIntersector.hxx>
#include <gp_Lin.hxx>
#include <GProp_GProps.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Pln.hxx>
#include <gp_Trsf.hxx>
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

double areaOf(const TopoDS_Shape& face)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(face, props);
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

/// Whether the copy is off the solid: its boundary apart from the solid's, and not inside it (the
/// boundaries of a copy buried in a taller step are apart too)
bool isApart(const TopoDS_Shape& copy, const TopoDS_Shape& solid)
{
    BRepExtrema_DistShapeShape distance(copy, solid);
    if (!distance.IsDone() || distance.Value() <= Precision::Confusion()) {
        return false;
    }
    TopExp_Explorer vertex(copy, TopAbs_VERTEX);
    if (!vertex.More()) {
        return true;
    }
    BRepClass3d_SolidClassifier inSolid(
        solid,
        BRep_Tool::Pnt(TopoDS::Vertex(vertex.Current())),
        Precision::Confusion()
    );
    return inSolid.State() != TopAbs_IN;
}

/// Whether two volumes meet: they touch (a shared face, edge or point) or overlap, one inside the
/// other included (their boundaries are apart then)
bool meet(const TopoDS_Shape& a, const TopoDS_Shape& b)
{
    BRepExtrema_DistShapeShape distance(a, b);
    if (!distance.IsDone() || distance.Value() <= 10 * Precision::Confusion()) {
        return true;
    }
    auto inside = [](const TopoDS_Shape& shape, const TopoDS_Shape& solid) {
        TopExp_Explorer vertex(shape, TopAbs_VERTEX);
        if (!vertex.More()) {
            return false;
        }
        BRepClass3d_SolidClassifier inSolid(
            solid,
            BRep_Tool::Pnt(TopoDS::Vertex(vertex.Current())),
            Precision::Confusion()
        );
        return inSolid.State() == TopAbs_IN;
    };
    return inside(a, b) || inside(b, a);
}

/// One instance's volumes (what it adds and what it removes) and their bounding box
struct Copy
{
    std::size_t position;
    std::vector<TopoDS_Shape> volumes;
    Bnd_Box box;
};

/// The first two instances that meet, if any (Onshape FP5, FP16: overlapping or touching instances
/// fail, PATTERN_FACE_FAILED). The volumes of one instance meet each other, which is fine
std::optional<std::pair<std::size_t, std::size_t>> meeting(std::vector<Copy>& copies)
{
    for (Copy& copy : copies) {
        for (const TopoDS_Shape& volume : copy.volumes) {
            BRepBndLib::Add(volume, copy.box);
        }
        copy.box.Enlarge(10 * Precision::Confusion());
    }
    for (std::size_t i = 0; i < copies.size(); ++i) {
        for (std::size_t j = i + 1; j < copies.size(); ++j) {
            if (copies[i].box.IsOut(copies[j].box)) {
                continue;
            }
            for (const TopoDS_Shape& a : copies[i].volumes) {
                for (const TopoDS_Shape& b : copies[j].volumes) {
                    if (meet(a, b)) {
                        return std::make_pair(copies[i].position, copies[j].position);
                    }
                }
            }
        }
    }
    return std::nullopt;
}

/// An interior point of the face and its outward normal (the middle of gridOn()'s), if any
bool interiorPoint(const TopoDS_Face& face, gp_Pnt& point, gp_Dir& normal)
{
    const auto grid = gridOn(face);
    if (grid.empty()) {
        return false;
    }
    point = grid[grid.size() / 2].first;
    normal = grid[grid.size() / 2].second;
    return true;
}

TopAbs_State stateIn(const TopoDS_Shape& solid, const gp_Pnt& point)
{
    BRepClass3d_SolidClassifier classifier(solid, point, Precision::Confusion());
    return classifier.State();
}

/// A feature volume (what the picks add, or what they remove) and its faces that are not pieces of
/// the picks (notes/face-pattern-design.md, the footing): a boss's footing on the healed base (the
/// base just beyond it), a pocket's or hole's lid (air beyond it), or a boss face flush with the
/// base's own unpicked boundary (a rib's end against the plate's side). Any other face means the
/// picks can't be lifted cleanly.
struct FeatureVolume
{
    Part::TopoShape shape;
    std::vector<int> picked;  // pieces of the picks: indexes in MapShapes(shape, TopAbs_FACE)
    std::vector<int> others;  // the other faces, same indexes
    std::vector<bool> flush;  // per others
    // Points on a boss's footing (with its outward normal) or a pocket's lid (with its inward one):
    // each direction points into the base
    std::vector<std::pair<gp_Pnt, gp_Dir>> intoBase;
    bool clean = true;
};

FeatureVolume classify(
    const Part::TopoShape& shape,
    const TopoDS_Shape& base,
    const std::vector<Part::TopoShape>& picks,
    bool adds
)
{
    FeatureVolume volume;
    volume.shape = shape;
    Bnd_Box box;
    BRepBndLib::Add(shape.getShape(), box);
    const double nudge = std::max(1e-4 * std::sqrt(box.SquareExtent()), 10 * Precision::Confusion());
    auto onAPick = [&](const gp_Pnt& point) {
        const TopoDS_Vertex vertex = BRepBuilderAPI_MakeVertex(point);
        return std::ranges::any_of(picks, [&](const Part::TopoShape& pick) {
            BRepExtrema_DistShapeShape distance(vertex, pick.getShape());
            return distance.IsDone() && distance.Value() < 10 * Precision::Confusion();
        });
    };
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape.getShape(), TopAbs_FACE, faces);
    for (int i = 1; i <= faces.Extent(); ++i) {
        const TopoDS_Face& face = TopoDS::Face(faces(i));
        gp_Pnt point;
        gp_Dir normal;
        if (!interiorPoint(face, point, normal)) {
            volume.clean = false;
            continue;
        }
        if (onAPick(point)) {
            volume.picked.push_back(i);
            continue;
        }
        const TopAbs_State beyond = stateIn(base, point.Translated(gp_Vec(normal) * nudge));
        bool flush = false;
        if (!adds) {
            volume.clean = volume.clean && beyond == TopAbs_OUT;
            for (const auto& [at, outward] : gridOn(face)) {
                volume.intoBase.emplace_back(at, outward.Reversed());
            }
        }
        else if (beyond == TopAbs_IN) {
            const auto grid = gridOn(face);
            volume.intoBase.insert(volume.intoBase.end(), grid.begin(), grid.end());
        }
        else if (beyond == TopAbs_OUT && stateIn(base, point) == TopAbs_ON) {
            flush = true;
        }
        else {
            volume.clean = false;
        }
        volume.others.push_back(i);
        volume.flush.push_back(flush);
    }
    return volume;
}

/// Whether the base lies anywhere along the directions from the points (a boss over a lower part of
/// the base, or a pocket over it, rather than off it)
bool over(const std::vector<std::pair<gp_Pnt, gp_Dir>>& points, const TopoDS_Shape& base, const gp_Trsf& trsf)
{
    IntCurvesFace_ShapeIntersector intersector;
    intersector.Load(base, Precision::Confusion());
    for (const auto& [point, normal] : points) {
        intersector.Perform(gp_Lin(point.Transformed(trsf), normal.Transformed(trsf)), 0.0, Precision::Infinite());
        if (intersector.IsDone() && intersector.NbPnt() > 0) {
            return true;
        }
    }
    return false;
}

/// Defeaturing changed only the picks' neighbours: no unpicked face of the base is deleted, and each
/// one modified shares an edge with a pick (a heal reshaping a farther face would be copied)
bool liftsCleanly(const TopoDS_Shape& base, const std::vector<Part::TopoShape>& picks)
{
    BRepAlgoAPI_Defeaturing defeaturing;
    defeaturing.SetRunParallel(true);
    defeaturing.SetToFillHistory(true);
    defeaturing.SetShape(base);
    TopTools_IndexedMapOfShape pickFaces;
    TopTools_IndexedMapOfShape pickEdges;
    for (const Part::TopoShape& pick : picks) {
        defeaturing.AddFaceToRemove(pick.getShape());
        pickFaces.Add(pick.getShape());
        TopExp::MapShapes(pick.getShape(), TopAbs_EDGE, pickEdges);
    }
    defeaturing.Build();
    if (!defeaturing.IsDone()) {
        return false;
    }
    for (TopExp_Explorer xp(base, TopAbs_FACE); xp.More(); xp.Next()) {
        const TopoDS_Shape& face = xp.Current();
        if (pickFaces.Contains(face)) {
            continue;
        }
        if (defeaturing.IsDeleted(face)) {
            return false;
        }
        // The history lists rebuilt copies of unchanged faces as modified too: a face counts as
        // changed when its one image has another area, or it has several
        const TopTools_ListOfShape& images = defeaturing.Modified(face);
        if (images.IsEmpty()) {
            continue;
        }
        if (images.Extent() == 1) {
            const double area = areaOf(face);
            if (std::abs(areaOf(images.First()) - area) <= 1e-7 * std::max(area, 1.0)) {
                continue;
            }
        }
        bool nextToAPick = false;
        for (TopExp_Explorer edges(face, TopAbs_EDGE); edges.More() && !nextToAPick; edges.Next()) {
            nextToAPick = pickEdges.Contains(edges.Current());
        }
        if (!nextToAPick) {
            return false;
        }
    }
    return true;
}

/// The faces a boolean made of the face of one of its inputs (none if it deleted it)
void piecesOf(BRepAlgoAPI_BooleanOperation* op, const TopoDS_Shape& face, TopTools_ListOfShape& pieces)
{
    if (!op) {
        pieces.Append(face);
        return;
    }
    if (op->IsDeleted(face)) {
        return;
    }
    const TopTools_ListOfShape& modified = op->Modified(face);
    if (modified.IsEmpty()) {
        pieces.Append(face);
        return;
    }
    for (const TopoDS_Shape& piece : modified) {
        pieces.Append(piece);
    }
}

/// Whether a pocket copy's picked face lies wholly beside the solid (Onshape FP19): the face is planar
/// and the whole solid lies on the copy's side of its plane. The copy then runs off the part's edge
/// there and cuts what it meets, a notch open at that end. A face with part of the solid beyond its
/// plane (a floor under a thinner ledge, FP15's rule) is not beside it
bool besideThe(const TopoDS_Shape& solid, const TopoDS_Face& face)
{
    if (BRepAdaptor_Surface(face).GetType() != GeomAbs_Plane) {
        return false;
    }
    gp_Pnt point;
    gp_Dir outward;
    if (!interiorPoint(face, point, outward)) {
        return false;
    }
    // In the frame with the face's plane at z 0 and its outward normal along +z, the solid's top
    gp_Trsf toPlane;
    toPlane.SetTransformation(gp_Ax3(point, outward));
    Bnd_Box box;
    BRepBndLib::AddOptimal(solid.Moved(TopLoc_Location(toPlane)), box, false, false);
    if (box.IsVoid()) {
        return false;
    }
    double x0 = 0.0;
    double y0 = 0.0;
    double z0 = 0.0;
    double x1 = 0.0;
    double y1 = 0.0;
    double z1 = 0.0;
    box.Get(x0, y0, z0, x1, y1, z1);
    return z1 <= 10 * Precision::Confusion();
}

/// Whether the face continues a face of the base it touches: on the same surface, facing the same way
bool continuesAFaceOf(const TopoDS_Face& piece, const TopoDS_Shape& base)
{
    gp_Pnt point;
    gp_Dir normal;
    if (!interiorPoint(piece, point, normal)) {
        return false;
    }
    const double tol = 10 * Precision::Confusion();
    for (TopExp_Explorer xp(base, TopAbs_FACE); xp.More(); xp.Next()) {
        const TopoDS_Face& face = TopoDS::Face(xp.Current());
        BRepExtrema_DistShapeShape touching(piece, face);
        if (!touching.IsDone() || touching.Value() > tol) {
            continue;
        }
        GeomAPI_ProjectPointOnSurf onSurface(point, BRep_Tool::Surface(face));
        if (onSurface.NbPoints() == 0 || onSurface.LowerDistance() > tol) {
            continue;
        }
        double u = 0.0;
        double v = 0.0;
        onSurface.LowerDistanceParameters(u, v);
        BRepAdaptor_Surface surface(face);
        gp_Pnt at;
        gp_Vec du;
        gp_Vec dv;
        surface.D1(u, v, at, du, dv);
        gp_Vec faceNormal = du.Crossed(dv);
        if (faceNormal.Magnitude() < Precision::Confusion()) {
            continue;
        }
        if (face.Orientation() == TopAbs_REVERSED) {
            faceNormal.Reverse();
        }
        if (gp_Dir(faceNormal).Dot(normal) > 0.999) {
            return true;
        }
    }
    return false;
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

    // Onshape (FP7) patterns each part's picks in that part; for now one part only (the parts hub's
    // T1a owns patterns across parts)
    {
        TopTools_IndexedMapOfShape solids;
        TopExp::MapShapes(baseShape.getShape(), TopAbs_SOLID, solids);
        if (solids.Extent() > 1) {
            int part = 0;
            for (int k = 1; k <= solids.Extent(); ++k) {
                TopTools_IndexedMapOfShape solidFaces;
                TopExp::MapShapes(solids(k), TopAbs_FACE, solidFaces);
                for (const Part::TopoShape& face : faces) {
                    if (!solidFaces.Contains(face.getShape())) {
                        continue;
                    }
                    if (part != 0 && part != k) {
                        return new App::DocumentObjectExecReturn(
                            QT_TRANSLATE_NOOP("Exception", "Face pattern: pick faces of one part")
                        );
                    }
                    part = k;
                }
            }
        }
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
        const TopoDS_Shape& base = baseShape.getShape();
        // The volumes' unpicked faces, each a footing, a lid or flush; and defeaturing changed only
        // the picks' neighbours. Else a heal that reshaped another face would be copied everywhere
        const FeatureVolume added = classify(add, base, faces, true);
        const FeatureVolume removed = classify(sub, base, faces, false);
        if ((adds && !added.clean) || (subs && !removed.clean) || !liftsCleanly(base, faces)) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Face pattern: the picked faces can't be lifted cleanly from the part"
            ));
        }

        const bool nameInstances = getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V2;
        auto failAt = [](std::size_t position, const char* what) {
            const std::string text = "Face pattern: instance " + std::to_string(position + 1) + " " + what;
            return new App::DocumentObjectExecReturn(text.c_str());
        };
        struct Kept
        {
            std::size_t position;
            int added;    // in addCopies, or -1
            int removed;  // in subCopies, or -1
        };
        std::vector<Kept> kept;
        std::vector<Part::TopoShape> addCopies {baseShape};
        std::vector<Part::TopoShape> subCopies;
        std::vector<Copy> checked {{0, {}, {}}};  // the seed's and the kept copies' volumes
        if (adds) {
            checked[0].volumes.push_back(add.getShape());
        }
        if (subs) {
            checked[0].volumes.push_back(sub.getShape());
        }
        for (std::size_t position = 1; position < transforms.size(); ++position) {
            if (std::ranges::find(skipped, position) != skipped.end()) {
                continue;
            }
            const gp_Trsf& trsf = transforms[position];
            // The op index is the pattern's index (the seed is 0, as Onshape's CP8), so a dropped
            // or skipped instance renames none of the others
            auto copyOf = [&](const Part::TopoShape& volume) {
                Part::TopoShape copy = makeTopoShape(false);
                copy.makeElementTransform(volume, trsf);
                if (nameInstances) {
                    copy.appendElementSection(getID(), Part::OpCodes::Transformed, std::to_string(position));
                }
                return copy;
            };
            // Apart from the base: dropped silently (Onshape FP4), unless a boss hovers over a
            // lower part of it, which Onshape stretches down and a copy can't (FP6, debt; decision
            // 150), or a pocket lies over it, which Onshape fails (FP15)
            Part::TopoShape addCopy = adds ? copyOf(add) : Part::TopoShape();
            Part::TopoShape subCopy = subs ? copyOf(sub) : Part::TopoShape();
            const bool addKept = adds && !isApart(addCopy.getShape(), base);
            const bool subKept = subs && !isApart(subCopy.getShape(), base);
            if (adds && !addKept && over(added.intoBase, base, trsf)) {
                return failAt(position, "stands over the part, not on it");
            }
            if (subs && !subKept && over(removed.intoBase, base, trsf)) {
                return failAt(position, "lies over the part, not in it");
            }
            if (adds && subs && addKept != subKept) {
                return failAt(position, "is partly off the part");
            }
            if (!addKept && !subKept) {
                continue;
            }
            Kept instance {position, -1, -1};
            Copy volumes {position, {}, {}};
            if (addKept) {
                instance.added = static_cast<int>(addCopies.size());
                addCopies.push_back(addCopy);
                volumes.volumes.push_back(addCopy.getShape());
            }
            if (subKept) {
                instance.removed = static_cast<int>(subCopies.size());
                subCopies.push_back(subCopy);
                volumes.volumes.push_back(subCopy.getShape());
            }
            kept.push_back(instance);
            checked.push_back(std::move(volumes));
        }
        // Onshape (FP5, FP16): instances that overlap or touch, the seed included, fail
        if (const auto pair = meeting(checked)) {
            const std::string other
                = "touches or overlaps instance " + std::to_string(pair->first + 1);
            return failAt(pair->second, other.c_str());
        }

        // Each copy must sit as the seed does: after the booleans, no face of the result comes
        // from a copy's unpicked face, but a flush face continuing a face of the base. Else the
        // copy hovers, overhangs, is buried, or leaves a pocket closed (a void) or a bore wall bare
        std::unique_ptr<BRepAlgoAPI_Fuse> fuse;
        TopoDS_Shape fused = base;
        if (addCopies.size() > 1) {
            TopTools_ListOfShape arguments;
            TopTools_ListOfShape tools;
            arguments.Append(base);
            for (std::size_t k = 1; k < addCopies.size(); ++k) {
                tools.Append(addCopies[k].getShape());
            }
            fuse = std::make_unique<BRepAlgoAPI_Fuse>();
            fuse->SetArguments(arguments);
            fuse->SetTools(tools);
            fuse->SetToFillHistory(true);
            fuse->Build();
            if (!fuse->IsDone()) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Face pattern: the instances can't be added")
                );
            }
            fused = fuse->Shape();
        }
        std::unique_ptr<BRepAlgoAPI_Cut> cut;
        if (!subCopies.empty()) {
            TopTools_ListOfShape arguments;
            TopTools_ListOfShape tools;
            arguments.Append(fused);
            for (const Part::TopoShape& copy : subCopies) {
                tools.Append(copy.getShape());
            }
            cut = std::make_unique<BRepAlgoAPI_Cut>();
            cut->SetArguments(arguments);
            cut->SetTools(tools);
            cut->SetToFillHistory(true);
            cut->Build();
            if (!cut->IsDone()) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Face pattern: the instances can't be cut")
                );
            }
        }
        // And each picked face's image is in each instance's result (Onshape FP15, FP17): else the
        // copy is buried in a taller step (a no-op), or a blind pocket breaks through a thinner one.
        // A pocket's pick lying wholly beside the part is the exception (FP19)
        auto piecesInResult = [&](const TopoDS_Shape& face, bool added) {
            TopTools_ListOfShape afterFuse;
            if (added) {
                piecesOf(fuse.get(), face, afterFuse);
            }
            else {
                afterFuse.Append(face);
            }
            TopTools_ListOfShape pieces;
            for (const TopoDS_Shape& piece : afterFuse) {
                piecesOf(cut.get(), piece, pieces);
            }
            return pieces;
        };
        for (const Kept& instance : kept) {
            if (instance.added >= 0) {
                TopTools_IndexedMapOfShape copyFaces;
                TopExp::MapShapes(addCopies[instance.added].getShape(), TopAbs_FACE, copyFaces);
                for (int index : added.picked) {
                    if (piecesInResult(copyFaces(index), true).IsEmpty()) {
                        return failAt(
                            instance.position,
                            "has a picked face missing: it doesn't stand out of the part"
                        );
                    }
                }
                for (std::size_t j = 0; j < added.others.size(); ++j) {
                    const TopTools_ListOfShape pieces
                        = piecesInResult(copyFaces(added.others[j]), true);
                    for (const TopoDS_Shape& piece : pieces) {
                        if (!added.flush[j] || !continuesAFaceOf(TopoDS::Face(piece), base)) {
                            return failAt(instance.position, "doesn't sit on the part as the original does");
                        }
                    }
                }
            }
            if (instance.removed >= 0) {
                TopTools_IndexedMapOfShape copyFaces;
                TopExp::MapShapes(subCopies[instance.removed].getShape(), TopAbs_FACE, copyFaces);
                for (int index : removed.picked) {
                    // A pick whose copy lies wholly beside the part leaves the cut open there:
                    // Onshape cuts what the copy meets (FP19)
                    if (piecesInResult(copyFaces(index), false).IsEmpty()
                        && !besideThe(fused, TopoDS::Face(copyFaces(index)))) {
                        return failAt(
                            instance.position,
                            "has a picked face missing: it doesn't cut into the part as the original "
                            "does"
                        );
                    }
                }
                for (int index : removed.others) {
                    if (!piecesInResult(copyFaces(index), false).IsEmpty()) {
                        return failAt(instance.position, "doesn't open onto the part as the original does");
                    }
                }
            }
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
