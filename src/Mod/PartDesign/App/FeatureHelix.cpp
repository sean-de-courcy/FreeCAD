// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2010 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
 *                 2020 David Österberg                                    *
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

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <BRepAdaptor_Surface.hxx>
#include <Mod/Part/App/FCBRepAlgoAPI_Common.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Cut.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Fuse.h>
#include <BRepBndLib.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <BRepFeat_SplitShape.hxx>
#include <BRepTools.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <Geom2d_Line.hxx>
#include <Geom_Surface.hxx>
#include <ShapeAnalysis_ShapeTolerance.hxx>
#include <TopExp_Explorer.hxx>
#include <gp_Dir2d.hxx>
#include <gp_Pnt2d.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepOffsetAPI_MakePipe.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <ShapeFix_ShapeTolerance.hxx>
#include <ShapeFix_Solid.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
#include <TopTools_DataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax3.hxx>

#include <Standard_Version.hxx>
#include <Base/Axis.h>
#include <Base/Exception.h>
#include <Base/Placement.h>
#include <Base/Tools.h>

#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/FaceMakerCheese.h>
#include <Mod/Part/App/KernelBudget.h>
#include <Mod/Part/App/modelRefine.h>

#include "FeatureHelix.h"
#include "App/Document.h"
#include "Mod/Part/App/TopoShapeOpCode.h"

using namespace PartDesign;

const char* Helix::ModeEnums[]
    = {"pitch-height-angle", "pitch-turns-angle", "height-turns-angle", "height-turns-growth", nullptr};

PROPERTY_SOURCE(PartDesign::Helix, PartDesign::ProfileBased)

namespace
{
// The pipe's history, plus its caps (ops#26): OCCT reports the side faces and edges generated
// from the profile's edges and vertices, but not the caps. As in a Pad, the start cap is the
// profile face (modified: it keeps the profile's name), and the end cap is the profile moved
// to the end of the sweep (projected). The caps' edges and vertices follow the profile's the
// same way, paired through the side faces and edges each profile element generated, as Pipe's
// ends are (bindEnds, ops#351). Named from the side face they bound instead, they took in the
// last turn's place among the turns (`4of5`), and a reference to the end cap's edge, the axis of
// a thread's revolved cap, was lost when the height or the pitch changed the number of turns
// (Onshape's cap follows those edits, SW7; ops#640).
struct MapperPipeCaps: Part::MapperMaker
{
    MapperPipeCaps(BRepOffsetAPI_MakePipe& pipe, const TopoDS_Shape& profile)
        : MapperMaker(pipe)
        , pipe(pipe)
        , profile(profile)
    {
        TopTools_IndexedMapOfShape startElements;
        TopTools_IndexedMapOfShape endElements;
        TopExp::MapShapes(pipe.FirstShape(), startElements);
        TopExp::MapShapes(pipe.LastShape(), endElements);
        bindCap(startElements, nullptr, starts);
        bindCap(endElements, &startElements, ends);
    }

    const std::vector<TopoDS_Shape>& modified(const TopoDS_Shape& s) const override
    {
        MapperMaker::modified(s);
        if (_res.empty() && s.IsSame(profile)) {
            _res.push_back(pipe.FirstShape());
        }
        if (const TopTools_ListOfShape* elements = starts.Seek(s)) {
            for (const TopoDS_Shape& element : *elements) {
                _res.push_back(element);
            }
        }
        return _res;
    }

    const std::vector<TopoDS_Shape>& projected(const TopoDS_Shape& s) const override
    {
        _res.clear();
        if (s.IsSame(profile)) {
            _res.push_back(pipe.LastShape());
        }
        else if (const TopTools_ListOfShape* elements = ends.Seek(s)) {
            for (const TopoDS_Shape& element : *elements) {
                _res.push_back(element);
            }
        }
        return _res;
    }

    /// Binds each edge and vertex of the profile (in its order) to the elements of one cap,
    /// \a capElements, that the side faces or edges it generated hold, leaving out \a skip's
    void bindCap(
        const TopTools_IndexedMapOfShape& capElements,
        const TopTools_IndexedMapOfShape* skip,
        TopTools_DataMapOfShapeListOfShape& bound
    )
    {
        if (profile.IsNull()) {
            return;
        }
        for (TopAbs_ShapeEnum type : {TopAbs_EDGE, TopAbs_VERTEX}) {
            TopTools_IndexedMapOfShape elements;
            TopExp::MapShapes(profile, type, elements);
            for (int i = 1; i <= elements.Extent(); ++i) {
                TopTools_IndexedMapOfShape candidates;
                for (const TopoDS_Shape& side : pipe.Generated(elements(i))) {
                    TopExp::MapShapes(side, type, candidates);
                }
                TopTools_ListOfShape found;
                for (int j = 1; j <= candidates.Extent(); ++j) {
                    if (capElements.Contains(candidates(j))
                        && !(skip && skip->Contains(candidates(j)))) {
                        found.Append(candidates(j));
                    }
                }
                if (!found.IsEmpty()) {
                    bound.Bind(elements(i), found);
                }
            }
        }
    }

    BRepOffsetAPI_MakePipe& pipe;
    TopoDS_Shape profile;
    TopTools_DataMapOfShapeListOfShape starts;
    TopTools_DataMapOfShapeListOfShape ends;
};

/// The imprint's history: the split's own, plus each cut as generated from the face it lies on
/// and each of its vertices from the helical edge it splits. Without them the cuts were elements
/// with no source, and naming those took 3.5 s at 30 turns (the split itself: 0.08 s).
struct MapperImprint: Part::MapperMaker
{
    explicit MapperImprint(BRepFeat_SplitShape& split)
        : MapperMaker(split)
    {}

    const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape& s) const override
    {
        MapperMaker::generated(s);
        if (const TopTools_ListOfShape* made = extra.Seek(s)) {
            for (const TopoDS_Shape& shape : *made) {
                _res.push_back(shape);
            }
        }
        return _res;
    }

    void bind(const TopoDS_Shape& source, const TopoDS_Shape& made)
    {
        if (TopTools_ListOfShape* list = extra.ChangeSeek(source)) {
            list->Append(made);
        }
        else {
            TopTools_ListOfShape fresh;
            fresh.Append(made);
            extra.Bind(source, fresh);
        }
    }

    TopTools_DataMapOfShapeListOfShape extra;
};

/** The sweep on a one-edge path with its side faces cut at each whole turn (ops#895), named as a
 * split of \a sweep. A sweep face spans the turns along V, the path's parameter (GeomFill: U
 * runs along the profile), so turn k is the iso-curve at k / turns of V's range: none at the
 * caps, none for a last turn shorter than a thousandth. Fused with a base whose wall it lies on,
 * a face over several turns meets the wall's cylinder over several periods, and OCCT's boolean
 * gets it wrong (5 turns: an edge tolerance of 38 mm; 10 turns: no solid); one turn per piece
 * is what the per-turn path gave. Returns a null shape when the cut doesn't give one solid
 * with each side face in as many pieces as turns.
 */
Part::TopoShape imprintTurns(const Part::TopoShape& sweep, double turns)
{
    const int cuts = static_cast<int>(std::ceil(turns - 1e-3)) - 1;
    if (cuts < 1) {
        return sweep;
    }
    // The cuts are placed, not computed: a boolean (BRepAlgoAPI_Splitter) intersecting the cuts
    // with the long faces took time in the square of the turns (40 turns: 20 s). Each side
    // face's cut k is its iso-curve at V = v_k, ending on the two helical edges it shares with
    // its neighbours, at one vertex per edge and turn that both neighbours' cuts use.
    std::vector<TopoDS_Face> sides;
    int caps = 0;
    for (TopExp_Explorer xp(sweep.getShape(), TopAbs_FACE); xp.More(); xp.Next()) {
        const TopoDS_Face& face = TopoDS::Face(xp.Current());
        if (BRepAdaptor_Surface(face, false).GetType() == GeomAbs_Plane) {
            ++caps;
        }
        else {
            sides.push_back(face);
        }
    }
    if (sides.empty() || caps != 2) {
        return {};
    }
    BRep_Builder builder;
    BRepFeat_SplitShape splitter(sweep.getShape());
    splitter.SetCheckInterior(false);
    MapperImprint history(splitter);
    // The vertex of each helical edge at each cut, made once
    std::map<std::pair<int, int>, TopoDS_Vertex> vertices;
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(sweep.getShape(), TopAbs_EDGE, edges);
    auto vertexAt = [&](const TopoDS_Edge& edge, int k, const gp_Pnt& point) {
        const std::pair<int, int> key(edges.FindIndex(edge), k);
        auto found = vertices.find(key);
        if (found == vertices.end()) {
            TopoDS_Vertex vertex;
            builder.MakeVertex(vertex, point, BRep_Tool::Tolerance(edge));
            found = vertices.emplace(key, vertex).first;
            history.bind(edge, vertex);
        }
        return found->second;
    };
    for (const TopoDS_Face& face : sides) {
        double u0 = 0;
        double u1 = 0;
        double v0 = 0;
        double v1 = 0;
        BRepTools::UVBounds(face, u0, u1, v0, v1);
        // The face's helical edges: its pcurve on the face is the iso-line U = u0 or U = u1
        TopoDS_Edge low;
        TopoDS_Edge high;
        for (TopExp_Explorer xe(face, TopAbs_EDGE); xe.More(); xe.Next()) {
            const TopoDS_Edge& edge = TopoDS::Edge(xe.Current());
            double first = 0;
            double last = 0;
            const Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(edge, face, first, last);
            if (pcurve.IsNull()) {
                return {};
            }
            const gp_Pnt2d a = pcurve->Value(first);
            const gp_Pnt2d b = pcurve->Value(last);
            const double tolerance = 1e-7 * std::max(1.0, u1 - u0);
            if (std::fabs(a.X() - b.X()) > tolerance) {
                continue;  // a cap's edge
            }
            if (std::fabs(a.X() - u0) <= tolerance && low.IsNull()) {
                low = edge;
            }
            else if (std::fabs(a.X() - u1) <= tolerance) {
                high = edge;
            }
        }
        if (low.IsNull()) {
            return {};
        }
        if (high.IsNull()) {
            high = low;  // a closed profile edge: its face's seam
        }
        TopLoc_Location location;
        const Handle(Geom_Surface) surface = BRep_Tool::Surface(face, location);
        const double tolerance = BRep_Tool::Tolerance(face);
        for (int k = 1; k <= cuts; ++k) {
            const double v = v0 + (v1 - v0) * k / turns;
            const gp_Trsf toGlobal = location.Transformation();
            TopoDS_Edge cut;
            builder.MakeEdge(cut, surface->VIso(v), location, tolerance);
            builder.UpdateEdge(
                cut,
                new Geom2d_Line(gp_Pnt2d(0.0, v), gp_Dir2d(1.0, 0.0)),
                surface,
                location,
                tolerance
            );
            builder.Range(cut, u0, u1);
            const TopoDS_Vertex first
                = vertexAt(low, k, surface->Value(u0, v).Transformed(toGlobal));
            const TopoDS_Vertex last
                = vertexAt(high, k, surface->Value(u1, v).Transformed(toGlobal));
            builder.Add(cut, first.Oriented(TopAbs_FORWARD));
            builder.Add(cut, last.Oriented(TopAbs_REVERSED));
            builder.SameParameter(cut, true);
            builder.SameRange(cut, true);
            splitter.Add(cut, face);
            history.bind(face, cut);
        }
    }
    splitter.Build();
    if (!splitter.IsDone()) {
        return {};
    }
    Part::TopoShape split(sweep.Tag, sweep.Hasher, sweep.getHistoryAlgorithm());
    split.makeShapeWithElementMap(splitter.Shape(), history, {sweep}, Part::OpCodes::Split);
    if (split.countSubShapes(TopAbs_SOLID) != 1) {
        return {};
    }
    Part::TopoShape solid = split.getSubTopoShape(TopAbs_SOLID, 1);
    if (static_cast<int>(solid.countSubShapes(TopAbs_FACE))
            != caps + static_cast<int>(sides.size()) * (cuts + 1)
        || !BRepCheck_Analyzer(solid.getShape()).IsValid()) {
        return {};
    }
    return solid;
}

/// Whether a boolean's volume lies within what the operation allows: a fusion holds at least the
/// larger input and at most both, a cut at most the base and at least the base less the tool, a
/// common at most the smaller input (1e-6 of the inputs' volume as the slack). The boolean's
/// failure on a long helix face added 0.43 mm3 to a fusion of a tube and a thread that only
/// touched (ops#895).
bool volumeWithinBounds(
    PartDesign::FeatureAddSub::BooleanOperation operation,
    const TopoDS_Shape& base,
    const TopoDS_Shape& tool,
    const TopoDS_Shape& result
)
{
    auto volume = [](const TopoDS_Shape& shape) {
        GProp_GProps props;
        BRepGProp::VolumeProperties(shape, props);
        return std::fabs(props.Mass());
    };
    const double b = volume(base);
    const double t = volume(tool);
    const double v = volume(result);
    const double slack = 1e-6 * (b + t) + Precision::Confusion();
    using Op = PartDesign::FeatureAddSub::BooleanOperation;
    switch (operation) {
        case Op::Union:
            return v >= std::max(b, t) - slack && v <= b + t + slack;
        case Op::Subtraction:
            return v <= b + slack && v >= b - t - slack;
        case Op::Common:
            return v <= std::min(b, t) + slack;
        default:
            return true;
    }
}

/// The largest tolerance of a shape's edges and vertices
double largestTolerance(const TopoDS_Shape& shape)
{
    if (shape.IsNull()) {
        return 0.0;
    }
    ShapeAnalysis_ShapeTolerance tolerance;
    return tolerance.Tolerance(shape, 1, TopAbs_SHAPE);
}
}  // namespace

// we purposely use not FLT_MAX because this would not be computable
const App::PropertyFloatConstraint::Constraints Helix::floatTurns
    = {Precision::Confusion(), std::numeric_limits<int>::max(), 1.0};
const App::PropertyFloatConstraint::Constraints Helix::floatTolerance
    = {0.1, std::numeric_limits<int>::max(), 1.0};
const App::PropertyAngle::Constraints Helix::floatAngle = {-89.0, 89.0, 1.0};

Helix::Helix()
{
    defineAdditive();
    auto initialMode = HelixMode::pitch_height_angle;

    const char* group = "Helix";
    ADD_PROPERTY_TYPE(
        Base,
        (Base::Vector3d(0.0, 0.0, 0.0)),
        group,
        App::Prop_ReadOnly,
        QT_TRANSLATE_NOOP(
            "App::Property",
            "The center point of the helix' start; derived from the reference axis."
        )
    );
    ADD_PROPERTY_TYPE(
        Axis,
        (Base::Vector3d(0.0, 1.0, 0.0)),
        group,
        App::Prop_ReadOnly,
        QT_TRANSLATE_NOOP("App::Property", "The helix' direction; derived from the reference axis.")
    );
    ADD_PROPERTY_TYPE(
        ReferenceAxis,
        (nullptr),
        group,
        App::Prop_None,
        QT_TRANSLATE_NOOP("App::Property", "The reference axis of the helix.")
    );
    ADD_PROPERTY_TYPE(
        Mode,
        (long(initialMode)),
        group,
        App::Prop_None,
        QT_TRANSLATE_NOOP(
            "App::Property",
            "The helix input mode specifies which properties are set by the user.\n"
            "Dependent properties are then calculated."
        )
    );
    Mode.setEnums(ModeEnums);
    ADD_PROPERTY_TYPE(
        Pitch,
        (10.0),
        group,
        App::Prop_None,
        QT_TRANSLATE_NOOP("App::Property", "The axial distance between two turns.")
    );
    ADD_PROPERTY_TYPE(
        Height,
        (30.0),
        group,
        App::Prop_None,
        QT_TRANSLATE_NOOP(
            "App::Property",
            "The height of the helix' path, not accounting for the extent of the profile."
        )
    );
    ADD_PROPERTY_TYPE(
        Turns,
        (3.0),
        group,
        App::Prop_None,
        QT_TRANSLATE_NOOP("App::Property", "The number of turns in the helix.")
    );
    Turns.setConstraints(&floatTurns);
    ADD_PROPERTY_TYPE(
        Angle,
        (0.0),
        group,
        App::Prop_None,
        QT_TRANSLATE_NOOP(
            "App::Property",
            "The angle of the cone that forms a hull around the helix.\n"
            "Non-zero values turn the helix into a conical spiral.\n"
            "Positive values make the radius grow, negative shrinks."
        )
    );
    Angle.setConstraints(&floatAngle);
    ADD_PROPERTY_TYPE(
        Growth,
        (0.0),
        group,
        App::Prop_None,
        QT_TRANSLATE_NOOP(
            "App::Property",
            "The growth of the helix' radius per turn.\n"
            "Non-zero values turn the helix into a conical spiral."
        )
    );
    ADD_PROPERTY_TYPE(
        LeftHanded,
        (false),
        group,
        App::Prop_None,
        QT_TRANSLATE_NOOP(
            "App::Property",
            "Sets the turning direction to left handed,\n"
            "i.e. counter-clockwise when moving along its axis."
        )
    );
    ADD_PROPERTY_TYPE(
        Reversed,
        (false),
        group,
        App::Prop_None,
        QT_TRANSLATE_NOOP(
            "App::Property",
            "Determines whether the helix points in the opposite direction of the axis."
        )
    );
    ADD_PROPERTY_TYPE(
        HasBeenEdited,
        (false),
        group,
        App::Prop_Hidden,
        QT_TRANSLATE_NOOP(
            "App::Property",
            "If false, the tool will propose an initial value for the pitch based on the profile "
            "bounding box,\n"
            "so that self intersection is avoided."
        )
    );
    ADD_PROPERTY_TYPE(
        Tolerance,
        (0.1),
        group,
        App::Prop_None,
        QT_TRANSLATE_NOOP("App::Property", "Fusion Tolerance for the Helix, increase if helical shape does not merge nicely with part.")
    );
    Tolerance.setConstraints(&floatTolerance);
    ADD_PROPERTY_TYPE(
        Outside,
        (false),
        group,
        App::Prop_Hidden,
        QT_TRANSLATE_NOOP("App::Property", "deprecated, do not use")
    );

    setReadWriteStatusForMode(initialMode);
}

short Helix::mustExecute() const
{
    if (Placement.isTouched() || ReferenceAxis.isTouched() || Axis.isTouched() || Base.isTouched()
        || Angle.isTouched()) {
        return 1;
    }
    return ProfileBased::mustExecute();
}

App::DocumentObjectExecReturn* Helix::execute()
{
    if (onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }

    // Validate and normalize parameters
    auto mode = static_cast<HelixMode>(Mode.getValue());
    if (mode == HelixMode::pitch_height_angle) {
        if (Pitch.getValue() < Precision::Confusion()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Error: Pitch too small!")
            );
        }
        if (Height.getValue() < Precision::Confusion()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Error: height too small!")
            );
        }
        Turns.setValue(Height.getValue() / Pitch.getValue());
        Growth.setValue(Pitch.getValue() * tan(Base::toRadians(Angle.getValue())));
    }
    else if (mode == HelixMode::pitch_turns_angle) {
        if (Pitch.getValue() < Precision::Confusion()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Error: pitch too small!")
            );
        }
        if (Turns.getValue() < Precision::Confusion()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Error: turns too small!")
            );
        }
        Height.setValue(Turns.getValue() * Pitch.getValue());
        Growth.setValue(Pitch.getValue() * tan(Base::toRadians(Angle.getValue())));
    }
    else if (mode == HelixMode::height_turns_angle) {
        if (Height.getValue() < Precision::Confusion()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Error: height too small!")
            );
        }
        if (Turns.getValue() < Precision::Confusion()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Error: turns too small!")
            );
        }
        Pitch.setValue(Height.getValue() / Turns.getValue());
        Growth.setValue(Pitch.getValue() * tan(Base::toRadians(Angle.getValue())));
    }
    else if (mode == HelixMode::height_turns_growth) {
        if (Turns.getValue() < Precision::Confusion()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Error: turns too small!")
            );
        }
        if ((Height.getValue() < Precision::Confusion())
            && (abs(Growth.getValue()) < Precision::Confusion()) && Turns.getValue() > 1.0) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Error: either height or growth must not be zero!")
            );
        }
        Pitch.setValue(Height.getValue() / Turns.getValue());
        if (Height.getValue() > 0) {
            Angle.setValue(
                Base::toDegrees(atan(Turns.getValue() * Growth.getValue() / Height.getValue()))
            );
        }
        else {
            // On purpose, we're doing nothing here; the else-branch is just for this comment.
            // - we don't print a warning, as for a flat spiral a zero-height is perfectly fine
            // - we don't void the angle (somehow) so that it keeps its value. This allows in
            //   interactive usage to just go back to another mode and everything keeps working
        }
    }
    else {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Error: unsupported mode")
        );
    }

    // V2 builds the helix from the profile face with its element names, so the result is named
    // (ops#26); V1 keeps upstream's raw build, which has no element map.
    const bool nameResult = getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V2;
    TopoShape profile;
    TopoDS_Shape sketchshape;  // Fixme: Should this be TopoShape here and below?
    try {
        if (nameResult) {
            profile = getTopoShapeVerifiedFace();
            sketchshape = profile.getShape();
        }
        else {
            sketchshape = getVerifiedFace();
        }
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }

    if (sketchshape.IsNull()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Error: No valid sketch or face")
        );
    }
    else {
        // TODO: currently we only allow planar faces. the reason for this is that with other faces
        // in front, we could not use the current simulate approach and build the start and end face
        // from the wires. As the shell begins always at the spine and not the profile, the
        // sketchshape cannot be used directly as front face. We would need a method to translate
        // the front shape to match the shell starting position somehow...
        TopoDS_Face face = TopoDS::Face(sketchshape);
        BRepAdaptor_Surface adapt(face);
        if (adapt.GetType() != GeomAbs_Plane) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Error: Face must be planar")
            );
        }
    }

    // if the Base property has a valid shape, fuse the AddShape into it
    TopoShape base;
    try {
        base = getBaseTopoShape();
    }
    catch (const Base::Exception&) {
        // fall back to support (for legacy features)
        base = makeTopoShape(false);
    }

    // update Axis from ReferenceAxis
    try {
        updateAxis();
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }

    try {
        this->positionByPrevious();
        TopLoc_Location invObjLoc = getInverseLocation(base);

        base.move(invObjLoc);

        TopoDS_Shape face = sketchshape;
        face.Move(invObjLoc);
        if (nameResult) {
            profile.move(invObjLoc);
            face = profile.getShape();
        }

        // One face per profile edge, as Onshape's (ops#895): the sweep runs on a one-edge path,
        // its side faces are cut at each turn for the boolean (imprintTurns()), and the pieces
        // are merged again after it. When that attempt fails (no solid, several, or a tolerance
        // the inputs don't explain), the helix is built as before: a path broken at each turn,
        // whose faces stay one per turn. V1 documents keep that build, and so does a helix of
        // more than 20 turns: naming the cut pieces of a long face costs time in the square of
        // the turns (twinOrder's projections onto the whole face: 10 turns 0.95 s, 20 turns
        // 2.4 s, 50 turns 11.7 s; the per-turn build: 0.2 to 1 s).
        const bool canImprint = nameResult && Turns.getValue() <= 20.0;
        bool fellBack = false;
        auto warn = [this](const std::string& text) {
            if (auto doc = getDocument(); doc && !SiblingOf.getValue()) {
                const char* previous = doc->getWarningDescription(this);
                doc->setWarning(
                    this,
                    previous && *previous ? std::string(previous) + "\n" + text : text
                );
            }
        };
        for (int attempt = canImprint ? 0 : 1; attempt < 2; ++attempt) {
            const bool imprint = attempt == 0;
            try {
                TopoDS_Shape result;

                // generate the helix path
                TopoDS_Shape path;
                if (!imprint && Angle.getValue() == 0.) {
                    // breaking the path at each turn prevents an OCC issue (the boolean's: see
                    // imprintTurns())
                    path = generateHelixPath();
                }
                else {
                    // don't break the path or the generated solid is invalid
                    path = generateHelixPath(1000.);
                }

                Bnd_Box bounds;
                BRepBndLib::Add(path, bounds);
                double size = sqrt(bounds.SquareExtent());
                ShapeFix_ShapeTolerance fix;
                fix.LimitTolerance(path, Precision::Confusion() * 1e-6 * size);  // needed to produce
                                                                                 // valid Pipe for
                                                                                 // very big parts
                // We introduce final part tolerance with the second call to LimitTolerance below,
                // however OCCT has a bug where the side-walls of the Pipe disappear with very large
                // (km range) pieces increasing a tiny bit of extra tolerance to the path fixes
                // this. This will in any case be less than the tolerance lower limit below, but
                // sufficient to avoid the bug

                BRepOffsetAPI_MakePipe mkPS(
                    TopoDS::Wire(path),
                    face,
                    GeomFill_Trihedron::GeomFill_IsFrenet,
                    Standard_False
                );
                result = mkPS.Shape();
                // V2: the side faces are generated from the profile's edges, the caps from its face
                TopoShape named = makeTopoShape(false);
                if (nameResult) {
                    named.makeShapeWithElementMap(
                        result,
                        MapperPipeCaps(mkPS, face),
                        {profile},
                        Part::OpCodes::Pipe
                    );
                }

                BRepClass3d_SolidClassifier SC(result);
                SC.PerformInfinitePoint(Precision::Confusion());
                if (SC.State() == TopAbs_IN) {
                    result.Reverse();
                    if (nameResult) {
                        named.setShape(result, false);  // the same sub-shapes: the names stay
                    }
                }

                fix.LimitTolerance(
                    result,
                    Precision::Confusion() * size * Tolerance.getValue()
                );  // significant precision reduction due to helical approximation - needed to
                    // allow fusion to succeed

                // try to auto-fix possible invalid result
                ShapeFix_Solid fixer;
                fixer.Init(TopoDS::Solid(result));
                if (fixer.Perform()) {
                    result = fixer.Solid();
                    if (nameResult) {
                        TopoShape fixed = makeTopoShape(false);
                        fixed.makeShapeWithElementMap(result, Part::MapperHistory(fixer), {named});
                        named = fixed;
                    }
                }

                // The boolean's tool: the sweep cut at each turn. It is also the AddSubShape,
                // which a pattern fuses with its base the same way.
                TopoShape tool = nameResult ? named : TopoShape(result);
                if (imprint) {
                    TopoShape imprinted = imprintTurns(named, Turns.getValue());
                    if (!imprinted.isNull()) {
                        tool = imprinted;
                    }
                    else if (!base.isNull()) {
                        fellBack = true;
                        continue;
                    }
                    // alone, the sweep is whole anyway: only the AddSubShape stays uncut
                }
                AddSubShape.setValue(tool);

                if (base.isNull()) {

                    if (getAddSubType() == FeatureAddSub::Type::Subtractive) {
                        return new App::DocumentObjectExecReturn(
                            QT_TRANSLATE_NOOP("Exception", "Error: There is nothing to subtract")
                        );
                    }

                    if (!isSingleSolidRuleSatisfied(result)) {
                        return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                            "Exception",
                            "Result has multiple solids: enable 'Allow Compound' in the active "
                            "body."
                        ));
                    }

                    // store shape before refinement; alone, the sweep is whole
                    if (nameResult) {
                        this->rawShape = named;
                        Shape.setValue(getSolid(named));
                    }
                    else {
                        this->rawShape = result;
                        Shape.setValue(getSolid(result));
                    }
                    return App::DocumentObject::StdReturn;
                }

                Part::TopoShape boolOp = makeTopoShape(false);
                boolOp.makeElementBoolean(
                    getBooleanMaker(),
                    {base, tool},
                    nullptr,
                    -1.0,
                    Part::ElementMapPolicy::Propagate,
                    booleanInputCheck(),
                    &booleanInputsValid
                );
                // An Intersect that shares no volume with its base leaves the base as it was,
                // healthy, with Onshape's info, as a Revolve's and an Extrude's (hands-on R7,
                // ops#640 rank 20, H3)
                if (getBooleanOperation() == BooleanOperation::Common
                    && (boolOp.isNull() || !boolOp.hasSubShape(TopAbs_SOLID))) {
                    if (imprint) {
                        // the long faces' boolean may have lost what the per-turn one finds
                        fellBack = true;
                        continue;
                    }
                    if (auto doc = getDocument(); doc && !SiblingOf.getValue()) {
                        static const std::string text = "Selected tools and targets do not intersect";
                        const char* previous = doc->getWarningDescription(this);
                        doc->setWarning(
                            this,
                            previous && *previous ? std::string(previous) + "\n" + text : text
                        );
                    }
                    this->rawShape = TopoShape();
                    Shape.setValue(base);
                    return App::DocumentObject::StdReturn;
                }

                if (!isSingleSolidRuleSatisfied(boolOp.getShape())) {
                    if (imprint) {
                        fellBack = true;
                        continue;
                    }
                    return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Result has multiple solids: enable 'Allow Compound' in the active body."
                    ));
                }

                TopoShape solid = getSolid(boolOp);
                // lets check if the result is a solid
                if (solid.isNull()) {
                    if (imprint) {
                        fellBack = true;
                        continue;
                    }
                    return new App::DocumentObjectExecReturn(
                        QT_TRANSLATE_NOOP("Exception", "Resulting shape is not a solid")
                    );
                }

                if (imprint) {
                    // the boolean's failure on a long face is a tolerance of millimetres (38 mm on
                    // a thread of 5 turns over 0.8 mm); where a thread runs out through a face, a
                    // vertex there takes 1e-3 mm for inputs of 6e-5, and the result is right
                    const double inputs = std::max(
                        largestTolerance(base.getShape()),
                        largestTolerance(tool.getShape())
                    );
                    if (largestTolerance(solid.getShape()) > 100.0 * inputs + Precision::Confusion()
                        || !volumeWithinBounds(
                            getBooleanOperation(),
                            base.getShape(),
                            tool.getShape(),
                            solid.getShape()
                        )
                        || !BRepCheck_Analyzer(solid.getShape()).IsValid()) {
                        fellBack = true;
                        continue;
                    }
                    // the turns' pieces whole again, before the refine and its rawShape
                    if (!ModelRefine::unifyAcrossSameSurface(
                            solid,
                            tool.getShape(),
                            Part::OpCodes::Refine
                        )
                        && Turns.getValue() > 1.0 + 1e-3) {
                        warn("The helix's faces stay one per turn: they could not be merged");
                    }
                }
                if (fellBack) {
                    warn("The helix's faces stay one per turn: the one-face build failed");
                }

                // store shape before refinement
                this->rawShape = solid;
                solid = refineShapeIfActive(solid);
                if (!isSingleSolidRuleSatisfied(solid.getShape())) {
                    return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Result has multiple solids: enable 'Allow Compound' in the active body."
                    ));
                }

                Shape.setValue(solid);
                return App::DocumentObject::StdReturn;
            }
            catch (const Standard_Failure&) {
                if (!imprint || Part::KernelBudget::pastDeadline()) {
                    throw;
                }
                fellBack = true;
            }
            catch (const Base::Exception&) {
                if (!imprint || Part::KernelBudget::pastDeadline()) {
                    throw;
                }
                fellBack = true;
            }
        }
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Error: the helix could not be built")
        );
    }
    catch (Standard_Failure& e) {

        if (std::string(e.GetMessageString()) == "TopoDS::Face") {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Error: Could not create face from sketch")
            );
        }
        else {
            return new App::DocumentObjectExecReturn(e.GetMessageString());
        }
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
}

void Helix::updateAxis()
{
    App::DocumentObject* pcReferenceAxis = ReferenceAxis.getValue();
    const std::vector<std::string>& subReferenceAxis = ReferenceAxis.getSubValues();
    Base::Vector3d base;
    Base::Vector3d dir;
    getAxis(pcReferenceAxis, subReferenceAxis, base, dir, ForbiddenAxis::NoCheck);

    Base.setValue(base.x, base.y, base.z);
    Axis.setValue(dir.x, dir.y, dir.z);
}

TopoDS_Shape Helix::generateHelixPath(double breakAtTurn)
{
    double turns = Turns.getValue();
    double height = Height.getValue();
    bool leftHanded = LeftHanded.getValue();
    bool reversed = Reversed.getValue();
    double angle = Angle.getValue();
    double growth = Growth.getValue();

    if (fabs(angle) < Precision::Confusion()) {
        angle = 0.0;
    }

    // get revolve axis
    Base::Vector3d baseVector = Base.getValue();
    gp_Pnt pnt(baseVector.x, baseVector.y, baseVector.z);
    Base::Vector3d axisVector = Axis.getValue();
    gp_Dir dir(axisVector.x, axisVector.y, axisVector.z);

    Base::Vector3d normal = getProfileNormal();
    Base::Vector3d start = axisVector.Cross(normal);  // pointing towards the desired helix start point.

    // if our axis is (nearly) aligned with the profile's normal, we're only interested in the
    // "twist" of the helix. The actual starting point, and thus the radius, isn't important as long
    // as it's somewhere in the profile's plane: an arbitrary vector perpendicular to the normal.
    if (start.IsNull()) {
        auto hopefullyNotParallel = Base::Vector3d(1.0, 2.0, 3.0);
        start = normal.Cross(hopefullyNotParallel);
        if (start.IsNull()) {
            // bad luck
            hopefullyNotParallel = Base::Vector3d(3.0, 2.0, 1.0);
            start = normal.Cross(hopefullyNotParallel);
        }
    }

    gp_Dir dir_start(start.x, start.y, start.z);

    // Find out in what quadrant relative to the axis the profile is located, and the exact position.
    Base::Vector3d profileCenter = getProfileCenterPoint();

    // The factor of 100 below ensures that profile size is small compared to the curvature of the
    // helix. This improves the issue reported in
    // https://forum.freecad.org/viewtopic.php?f=10&t=65048
    double axisOffset = 100.0 * (profileCenter * start - baseVector * start);
    double radius = std::fabs(axisOffset);
    bool turned = axisOffset < 0;
    // since the factor does not only change the radius but also the path position, we must shift
    // its offset back using the square of the factor
    double startOffset = 10000.0
        * std::fabs((angle <= 0. ? 1. : 0.) * (profileCenter * axisVector) - baseVector * axisVector);

    if (radius < Precision::Confusion()) {
        // in this case ensure that axis is not in the sketch plane
        if (fabs(axisVector * normal) < Precision::Confusion()) {
            throw Base::ValueError("Error: Result is self intersecting");
        }
        radius = 1000.0;  // fallback to radius 1000
    }

    bool growthMode = std::string(Mode.getValueAsString()).find("growth") != std::string::npos;
    double radiusTop;
    if (growthMode) {
        radiusTop = radius + turns * growth;
    }
    else {
        radiusTop = radius + height * tan(Base::toRadians(angle));
    }

    // build the helix path
    TopoDS_Shape path
        = TopoShape().makeSpiralHelix(radius, radiusTop, height, turns, breakAtTurn, leftHanded);

    /*
     * The helix wire is created with the axis coinciding with z-axis and the start point at
     * (radius, 0, 0) We want to move it so that the axis becomes aligned with "dir" and "pnt", we
     * also want (radius,0,0) to map to the sketch plane.
     */

    gp_Pnt origo(0.0, 0.0, 0.0);
    gp_Dir dir_axis1(0.0, 0.0, 1.0);  // pointing along the helix axis, as created.
    gp_Dir dir_axis2(1.0, 0.0, 0.0);  // pointing towards the helix start point, as created.
    gp_Trsf mov;

    if (abs(startOffset) > 0) {  // translate the helix so that the starting point aligns with the
                                 // profile
        mov.SetTranslation(startOffset * gp_Vec(dir_axis1));
        TopLoc_Location loc(mov);
        path.Move(loc);
    }

    // because of the radius factor we used above, we must reverse after the
    // startOffset movement (that brings the path back to the desired position)
    if (reversed) {
        mov.SetRotation(gp_Ax1(origo, dir_axis2), std::numbers::pi);
        TopLoc_Location loc(mov);
        path.Move(loc);
    }

    if (turned) {  // turn the helix so that the starting point aligns with the profile
        mov.SetRotation(gp_Ax1(origo, dir_axis1), std::numbers::pi);
        TopLoc_Location loc(mov);
        path.Move(loc);
    }

    gp_Ax3 sourceCS(origo, dir_axis1, dir_axis2);
    gp_Ax3 targetCS(pnt, dir, dir_start);

    mov.SetTransformation(sourceCS, targetCS);
    TopLoc_Location loc(mov);
    path.Move(loc.Inverted());

    TopLoc_Location invObjLoc = this->getLocation().Inverted();
    path.Move(invObjLoc);

    return path;
}

// this function calculates self intersection safe pitch based on the profile bounding box.
double Helix::safePitch()
{
    Base::Vector3d axisVec = Axis.getValue();
    Base::Vector3d startVec = axisVec.Cross(getProfileNormal());  // pointing towards the helix
                                                                  // start point
    HelixMode mode = static_cast<HelixMode>(Mode.getValue());
    double growthValue = Growth.getValue();
    double turnsValue = Turns.getValue();

    // handle case if axis is orthogonal to profile
    // since startVec.IsNull() fails sometimes, for e.g. (0.0, 0.0, -0.0)
    // we take the precision into account
    if (startVec.Length() < Precision::Confusion()) {
        // when not in growth mode any pitch > 0 is safe
        if (mode != HelixMode::height_turns_growth) {
            return Precision::Confusion();
        }
        // if growth is not zero, there will in many cases be intersections
        // when the turn is >= 1, thus return an 'infinite' pitch
        // Note: The resulting helix body is in this case often garbage since
        // the OCC algorithm to create the helix fails.
        // Nevertheless, the result is a valid body so it should be valuable for users
        // to get this correct warning anyway.
        else {
            if (abs(turnsValue) >= 1.0 && abs(growthValue) > 0.0) {
                return Precision::Infinite();
            }
        }
    }

    double angle = Base::toRadians(Angle.getValue());
    gp_Dir direction(axisVec.x, axisVec.y, axisVec.z);
    gp_Dir directionStart(startVec.x, startVec.y, startVec.z);
    TopoDS_Shape sketchshape = getVerifiedFace();
    Bnd_Box boundingBox;
    BRepBndLib::Add(sketchshape, boundingBox);

    // get boundary and dimensions of boundingBox
    double Xmin, Ymin, Zmin, Xmax, Ymax, Zmax;
    boundingBox.Get(Xmin, Ymin, Zmin, Xmax, Ymax, Zmax);
    double X = Xmax - Xmin, Y = Ymax - Ymin, Z = Zmax - Zmin;
    gp_Vec boundingBoxVec(X, Y, Z);

    // Below is an approximation because since we take the bounding box it is
    // impossible to calculate it precisely. For example a circle has as bounding
    // box a square and thus results in a larger pitch than really necessary

    // minimal safe pitch if the angle or growth is 0
    double pitch0 = boundingBoxVec * direction;

    if (mode == HelixMode::height_turns_growth) {
        // if the distance perpendicular to axisVec
        // between two turns is larger than the bounding box size in this direction
        // the minimal necessary pitch is zero
        if (abs(growthValue) > abs(boundingBoxVec * directionStart)) {
            return 0.0;
        }
        else {
            // if less than one turn, every pitch is safe
            // Note: at the moment helices with a growth end with a plane
            // whose normal is the final direction of the helix path.
            // In case this might be changed in future, also 1.0 turn would be safe.
            if (turnsValue < 1.0) {
                return 0.0;
            }
            else {
                return pitch0;
            }
        }
    }
    else {
        // if the angle is so large that the distance perpendicular to axisVec
        // between two turns is larger than the bounding box size in this direction
        // the pitch can be smaller than pitch0
        if (tan(abs(angle)) * pitch0 > abs(boundingBoxVec * directionStart)) {
            return abs(boundingBoxVec * directionStart) / tan(abs(angle));
        }
        else {
            return pitch0;
        }
    }
}

// this function proposes pitch and height
void Helix::proposeParameters(bool force)
{
    if (force || !HasBeenEdited.getValue()) {
        TopoDS_Shape sketchshape = getVerifiedFace();
        Bnd_Box bb;
        BRepBndLib::Add(sketchshape, bb);
        bb.SetGap(0.0);
        double pitch = 1.1 * sqrt(bb.SquareExtent());

        Pitch.setValue(pitch);
        Height.setValue(pitch * 3.0);
        HasBeenEdited.setValue(true);
    }
}

Base::Vector3d Helix::getProfileCenterPoint()
{
    TopoDS_Shape profileshape;
    profileshape = getVerifiedFace();
    Bnd_Box box;
    BRepBndLib::Add(profileshape, box);
    box.SetGap(0.0);
    double xmin, ymin, zmin, xmax, ymax, zmax;
    box.Get(xmin, ymin, zmin, xmax, ymax, zmax);
    return Base::Vector3d(0.5 * (xmin + xmax), 0.5 * (ymin + ymax), 0.5 * (zmin + zmax));
}

void Helix::handleChangedPropertyType(Base::XMLReader& reader, const char* TypeName, App::Property* prop)
{
    // property Turns had the App::PropertyFloat and was changed to App::PropertyFloatConstraint
    if (prop == &Turns && strcmp(TypeName, "App::PropertyFloat") == 0) {
        App::PropertyFloat TurnsProperty;
        // restore the PropertyFloat to be able to set its value
        TurnsProperty.Restore(reader);
        Turns.setValue(TurnsProperty.getValue());
    }
    // property Growth had the App::PropertyLength and was changed to App::PropertyDistance
    else if (prop == &Growth && strcmp(TypeName, "App::PropertyLength") == 0) {
        App::PropertyLength GrowthProperty;
        // restore the PropertyLength to be able to set its value
        GrowthProperty.Restore(reader);
        Growth.setValue(GrowthProperty.getValue());
    }
    else {
        ProfileBased::handleChangedPropertyType(reader, TypeName, prop);
    }
}

void Helix::onChanged(const App::Property* prop)
{
    if (prop == &Mode) {
        // Depending on the mode, the derived properties are set read-only
        auto inputMode = static_cast<HelixMode>(Mode.getValue());
        setReadWriteStatusForMode(inputMode);
    }

    // Reflect Operation property value to deprectated Outside
    // by the new value: with every operation allowed (ops#640 rank 20) an Add set straight to
    // Intersect was still additive here, and the restore made it a Remove
    if (prop == &Operation) {
        const char* operation = Operation.getValueAsString();
        if (operation && strcmp(operation, "Union") != 0) {
            Outside.setValue(strcmp(operation, "Common") == 0);
        }
    }

    ProfileBased::onChanged(prop);
}

void Helix::onDocumentRestored()
{
    // Reflect deprecated Outside property value to Operation
    if (addSubType == Type::Subtractive) {
        Operation.setValue(Outside.getValue() ? "Common" : "Subtraction");
    }

    ProfileBased::onDocumentRestored();
}

void Helix::setReadWriteStatusForMode(HelixMode inputMode)
{
    switch (inputMode) {
        case HelixMode::pitch_height_angle:
            // primary input:
            Pitch.setStatus(App::Property::ReadOnly, false);
            Height.setStatus(App::Property::ReadOnly, false);
            Angle.setStatus(App::Property::ReadOnly, false);
            // derived props:
            Turns.setStatus(App::Property::ReadOnly, true);
            Growth.setStatus(App::Property::ReadOnly, true);
            break;

        case HelixMode::pitch_turns_angle:
            // primary input:
            Pitch.setStatus(App::Property::ReadOnly, false);
            Turns.setStatus(App::Property::ReadOnly, false);
            Angle.setStatus(App::Property::ReadOnly, false);
            // derived props:
            Height.setStatus(App::Property::ReadOnly, true);
            Growth.setStatus(App::Property::ReadOnly, true);
            break;

        case HelixMode::height_turns_angle:
            // primary input:
            Height.setStatus(App::Property::ReadOnly, false);
            Turns.setStatus(App::Property::ReadOnly, false);
            Angle.setStatus(App::Property::ReadOnly, false);
            // derived props:
            Pitch.setStatus(App::Property::ReadOnly, true);
            Growth.setStatus(App::Property::ReadOnly, true);
            break;

        case HelixMode::height_turns_growth:
            // primary input:
            Height.setStatus(App::Property::ReadOnly, false);
            Turns.setStatus(App::Property::ReadOnly, false);
            Growth.setStatus(App::Property::ReadOnly, false);
            // derived props:
            Pitch.setStatus(App::Property::ReadOnly, true);
            Angle.setStatus(App::Property::ReadOnly, true);
            break;

        default:
            Pitch.setStatus(App::Property::ReadOnly, false);
            Height.setStatus(App::Property::ReadOnly, false);
            Turns.setStatus(App::Property::ReadOnly, false);
            Angle.setStatus(App::Property::ReadOnly, false);
            Growth.setStatus(App::Property::ReadOnly, false);
            break;
    }
}

PROPERTY_SOURCE(PartDesign::AdditiveHelix, PartDesign::Helix)
AdditiveHelix::AdditiveHelix()
{
    defineAdditive();
    // New / Add / Remove / Intersect on one Helix (FreeCAD-CH ops#640 rank 20)
    allowAllOperations();
}

PROPERTY_SOURCE(PartDesign::SubtractiveHelix, PartDesign::Helix)
SubtractiveHelix::SubtractiveHelix()
{
    defineSubtractive();
    allowAllOperations();
}
