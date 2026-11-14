// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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


#include <BRep_Tool.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepCheck_Shell.hxx>
#include <BRepCheck_Solid.hxx>
#include <BRepCheck_Status.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <Bnd_Box.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Iterator.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <Precision.hxx>
#include <ShapeFix_Solid.hxx>
#include <Standard_Failure.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Builder.hxx>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <sstream>
#include <unordered_map>
#include <set>
#include <unordered_set>
#include <vector>

#include "App/Datums.h"
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/ElementNamingUtils.h>
#include <App/ElementSolverBatch.h>
#include <App/FeaturePythonPyImp.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/RecomputeThread.h>
#include <Base/Console.h>

#include <Mod/Part/App/KernelBudget.h>
#include <Mod/Part/App/MassProperties.h>

#include "Feature.h"
#include "FailureContinuation.h"
#include "FeaturePy.h"
#include "Body.h"
#include "FeatureBase.h"
#include "FeatureBoolean.h"
#include "FeatureChamfer.h"
#include "FeatureDeletePart.h"
#include "FeatureDressUp.h"
#include "FeatureExtrude.h"
#include "FeatureFillet.h"
#include "FeatureTransformed.h"
#include "PostCondition.h"
#include "ResultCheck.h"
#include "ShapeBinder.h"
#include "StudioOwner.h"

#include <BRep_Builder.hxx>

FC_LOG_LEVEL_INIT("PartDesign", true, true)


namespace PartDesign
{

namespace
{

Base::Placement getObjectPlacement(const App::DocumentObject* object)
{
    if (!object) {
        return {};
    }

    auto placement = object->getPropertyByName<App::PropertyPlacement>("Placement");
    return placement ? placement->getValue() : Base::Placement();
}

Base::Placement getContainingGeoFeatureGroupPlacement(const App::DocumentObject* object)
{
    Base::Placement placement;
    std::set<const App::DocumentObject*> visited;
    std::vector<const App::DocumentObject*> groups;

    for (auto group = App::GeoFeatureGroupExtension::getGroupOfObject(object);
         group && visited.insert(group).second;
         group = App::GeoFeatureGroupExtension::getGroupOfObject(group)) {
        groups.push_back(group);
    }

    for (auto it = groups.rbegin(); it != groups.rend(); ++it) {
        placement = placement * getObjectPlacement(*it);
    }

    return placement;
}

Base::Placement getDisplayedObjectPlacement(const App::DocumentObject* object)
{
    return getContainingGeoFeatureGroupPlacement(object) * getObjectPlacement(object);
}

// ops#524 (PLAN decision 182, N2): the features whose Placement was set during their own
// recompute (positionByPrevious(), positionByBaseFeature(), an attachment) before the shape made
// under it. Part::Feature::onChanged() gives the old shape the new placement, and the references to
// the feature are solved in between (ops#522's window). By address: an entry left by a deleted
// feature only makes a later one at its address refuse until its first shape.
std::mutex placedAheadMutex;
std::unordered_set<const Feature*> placedAhead;
// The feature whose Placement change is being passed to its shape (its nested Shape change)
thread_local const Feature* placingShape = nullptr;

}  // namespace

bool placedAheadOfShape(const Feature* feature)
{
    std::lock_guard<std::mutex> lock(placedAheadMutex);
    return placedAhead.count(feature) > 0;
}

bool getPDRefineModelParameter()
{
    Base::Reference<ParameterGrp> hGrp = App::GetApplication()
                                             .GetUserParameter()
                                             .GetGroup("BaseApp")
                                             ->GetGroup("Preferences")
                                             ->GetGroup("Mod/PartDesign");
    return hGrp->GetBool("RefineModel", true);
}

// ------------------------------------------------------------------------------------------------

PROPERTY_SOURCE(PartDesign::Feature, Part::Feature)

Feature::Feature()
{
    ADD_PROPERTY(BaseFeature, (nullptr));
    ADD_PROPERTY_TYPE(
        _Body,
        (nullptr),
        "Base",
        (App::PropertyType)(App::Prop_ReadOnly | App::Prop_Hidden | App::Prop_Output
                            | App::Prop_Transient),
        0
    );
    ADD_PROPERTY(SuppressedShape, (TopoShape()));
    ADD_PROPERTY_TYPE(_PassedThrough,
                      (false),
                      "Base",
                      (App::PropertyType)(App::Prop_Hidden | App::Prop_ReadOnly | App::Prop_Output
                                          | App::Prop_NoRecompute),
                      "The output is the base, passed through while suppressed");
    ADD_PROPERTY_TYPE(_FailurePassedThrough,
                      (false),
                      "Base",
                      (App::PropertyType)(App::Prop_Hidden | App::Prop_ReadOnly | App::Prop_Output
                                          | App::Prop_NoRecompute),
                      "The output is the base, passed through after the last recompute failed");
    // FreeCAD-CH ops#654: studio features (StudioList.h)
    ADD_PROPERTY_TYPE(StudioScope,
                      (),
                      "Studio",
                      App::Prop_Hidden,
                      "The part ids this studio feature acts on, in order");
    ADD_PROPERTY_TYPE(StudioOwner,
                      (nullptr),
                      "Studio",
                      App::Prop_Hidden,
                      "The studio feature whose tool this step applies");
    ADD_PROPERTY_TYPE(StudioBases,
                      (nullptr),
                      "Studio",
                      App::Prop_Hidden,
                      "Each in-scope part's solid just before this studio feature (reconcile)");
    Placement.setStatus(App::Property::Hidden, true);
    BaseFeature.setStatus(App::Property::Hidden, true);

    App::SuppressibleExtension::initExtension(this);
    Part::PreviewExtension::initExtension(this);
}

namespace
{
// The words that mark the failure of Feature::recompute() below
constexpr const char* placedElsewhere = "placed elsewhere than this feature's Body";
}  // namespace

// A placer in another Body is read in its own Body's coordinates, as if it were in the feature's,
// by every path that uses it (its shape, its sketch's placement, its support face): in a Body
// placed elsewhere the feature comes out where the placer isn't (FreeCAD-CH ops#308 T4: a hole
// through two stacked Bodies cut in the wrong place; ops#325: a pattern along another Body's
// edge, a mirror plane, a draft's neutral plane). Outside every Body the same holds for its
// container, an App::Part or the document (ops#325: a pattern along an edge of a sketch at the
// document's root, in a placed Body). A binder carries them over.
bool Feature::placerElsewhere(const char** property, std::string* where) const
{
    return placerElsewhereThan(getFeatureBody(), property, where);
}

bool Feature::placerElsewhereThan(const Body* body, const char** property, std::string* where) const
{
    if (!body) {
        return false;
    }
    const auto here = body->globalPlacement();
    std::vector<App::DocumentObject*> placers;
    for (const char* name : placerProperties()) {
        auto prop = freecad_cast<App::PropertyLinkBase*>(getPropertyByName(name));
        if (!prop) {
            continue;
        }
        placers.clear();
        prop->getLinks(placers);
        for (auto obj : placers) {
            if (!obj || std::ranges::find(pendingMembers, obj) != pendingMembers.end()) {
                continue;
            }
            // Its Body; else the container that places it (an origin element's is its origin's
            // container), or the document's root (none)
            const App::DocumentObject* container = Body::findBodyOf(obj);
            if (!container) {
                container = App::GeoFeatureGroupExtension::getGroupOfObject(obj);
            }
            if (container == body) {
                continue;
            }
            auto geo = freecad_cast<const App::GeoFeature*>(container);
            const auto there = geo ? geo->globalPlacement() : Base::Placement();
            if (there.isSame(here, Precision::Confusion())) {
                continue;
            }
            if (property) {
                *property = name;
            }
            if (where) {
                if (!container) {
                    *where = "the document's root";
                }
                else if (container->isDerivedFrom<Body>()) {
                    *where = std::string("Body ") + container->Label.getValue();
                }
                else {
                    *where = container->Label.getValue();
                }
            }
            return true;
        }
    }
    return false;
}

// ---------------------------------------------------------------------------------------------
// FreeCAD-CH kernel safety S2: the check of a solid feature's result (ResultCheck.h)

namespace
{
/// What a feature's last refine in its execute started from and gave
struct RefineNote
{
    TopoDS_Shape before;
    TopoDS_Shape after;
};
thread_local std::unordered_map<const Feature*, RefineNote> refineNotes;

/// The scale of a location's transform: 1 for a placement
double scaleOf(const TopLoc_Location& location)
{
    return std::abs(location.Transformation().ScaleFactor());
}

/// The volumes of the last results that passed, newest last: the next feature's base is one. A
/// volume belongs to the shape's TShape and orientation: the base comes back under another
/// placement (the feature's own), which moves it without changing its volume
struct KnownVolume
{
    TopoDS_Shape shape;
    double volume;
};
std::mutex knownVolumesMutex;
std::deque<KnownVolume> knownVolumes;
constexpr std::size_t knownVolumesKept = 64;  // a body's chain after an edit: one per feature

bool knownVolume(const TopoDS_Shape& shape, double& volume)
{
    std::lock_guard<std::mutex> lock(knownVolumesMutex);
    for (auto it = knownVolumes.rbegin(); it != knownVolumes.rend(); ++it) {
        if (it->shape.IsPartner(shape) && it->shape.Orientation() == shape.Orientation()
            && std::abs(scaleOf(it->shape.Location()) - scaleOf(shape.Location())) <= 1e-12) {
            volume = it->volume;
            return true;
        }
    }
    return false;
}

void rememberVolume(const TopoDS_Shape& shape, double volume)
{
    std::lock_guard<std::mutex> lock(knownVolumesMutex);
    knownVolumes.push_back({shape, volume});
    while (knownVolumes.size() > knownVolumesKept) {
        knownVolumes.pop_front();
    }
}

/// The volume the faces bound: adaptive where a face carries a B-spline of many spans, whose
/// default integration is badly wrong (negative for a correct pipe along 1000 of them, ops#414)
double volumeOf(const TopoDS_Shape& shape)
{
    return Part::MassProperties::volume(shape);
}

enum class Direction
{
    None,
    Grows,
    Shrinks
};

/// What the operation does to the volume, where it says
Direction directionOf(Feature& feature)
{
    if (feature.isDerivedFrom<DressUp>()) {
        // a fillet adds or removes, as its edges are concave or convex; so does a draft
        return Direction::None;
    }
    if (auto addSub = freecad_cast<FeatureAddSub*>(&feature)) {
        switch (addSub->getBooleanOperation()) {
            case FeatureAddSub::BooleanOperation::Union:
                return Direction::Grows;
            default:
                return Direction::Shrinks;
        }
    }
    if (auto boolean = freecad_cast<Boolean*>(&feature)) {
        return strcmp(boolean->Type.getValueAsString(), "Fuse") == 0 ? Direction::Grows
                                                                      : Direction::Shrinks;
    }
    if (auto transformed = freecad_cast<Transformed*>(&feature)) {
        const auto originals = transformed->getOriginals();
        if (originals.empty()) {
            return Direction::Grows;  // the whole shape's copies are fused
        }
        bool adds = false;
        bool removes = false;
        for (auto original : originals) {
            auto addSub = freecad_cast<FeatureAddSub*>(original);
            if (!addSub || addSub->isDerivedFrom<DressUp>()) {
                return Direction::None;
            }
            (addSub->getAddSubType() == FeatureAddSub::Type::Additive ? adds : removes) = true;
        }
        if (adds != removes) {
            return adds ? Direction::Grows : Direction::Shrinks;
        }
    }
    return Direction::None;
}

/// Whether two locations are the same transform (a datum may differ where the transform doesn't)
bool sameTransform(const TopLoc_Location& a, const TopLoc_Location& b)
{
    if (a.IsEqual(b)) {
        return true;
    }
    const gp_Trsf& ta = a.Transformation();
    const gp_Trsf& tb = b.Transformation();
    for (int row = 1; row <= 3; ++row) {
        for (int col = 1; col <= 4; ++col) {
            const double tolerance = col == 4 ? 1e-9 : 1e-12;
            if (std::abs(ta.Value(row, col) - tb.Value(row, col)) > tolerance) {
                return false;
            }
        }
    }
    return true;
}

/// The volume of a shape's bounding box: the scale for "no volume"
double boxVolume(const TopoDS_Shape& shape)
{
    Bnd_Box box;
    BRepBndLib::Add(shape, box, Standard_False);
    if (box.IsVoid()) {
        return 0.0;
    }
    double x0 = 0;
    double y0 = 0;
    double z0 = 0;
    double x1 = 0;
    double y1 = 0;
    double z1 = 0;
    box.Get(x0, y0, z0, x1, y1, z1);
    return (x1 - x0) * (y1 - y0) * (z1 - z0);
}

/// The faces of a shape's solids (loose faces and shells don't count), with their placement
using FaceMap = std::unordered_multimap<const TopoDS_TShape*, TopoDS_Shape>;

void collectFaces(const TopoDS_Shape& shape, FaceMap& faces)
{
    for (TopExp_Explorer solid(shape, TopAbs_SOLID); solid.More(); solid.Next()) {
        for (TopExp_Explorer face(solid.Current(), TopAbs_FACE); face.More(); face.Next()) {
            faces.emplace(face.Current().TShape().get(), face.Current());
        }
    }
}

/// A face is unchanged where the other shape has it: the same TShape, orientation and transform
/// (PartDesign's results share their base's TShapes under other location datums)
bool containsFace(const FaceMap& faces, const TopoDS_Shape& face)
{
    auto range = faces.equal_range(face.TShape().get());
    for (auto it = range.first; it != range.second; ++it) {
        if (it->second.Orientation() == face.Orientation()
            && sameTransform(it->second.Location(), face.Location())) {
            return true;
        }
    }
    return false;
}

/// The check's work under KernelBudget::run(): exact copies only (Part::KernelBudget::exactCopy),
/// of what the feature changed, so that its cost follows the change and not the part's size
struct Check
{
    // Inputs, copies: compounds of the result's faces the base doesn't have (made), of the base's
    // the result doesn't have (removed), of the faces to check, of the result's solids it changed
    // where it has several, and the base where its volume isn't known (else a null shape)
    TopoDS_Shape made;
    TopoDS_Shape removed;
    TopoDS_Shape faces;
    TopoDS_Shape solids;
    TopoDS_Shape base;
    bool oneSolid {true};
    // Inputs and outputs
    double baseVolume {0.0};
    // Outputs
    double baseWorstSolid {0.0};  // the smallest of volume / its box's volume
    bool baseHasSolid {false};
    double change {0.0};
    double worstSolid {0.0};  // the same, over the solids it changed
    double worstSolidVolume {0.0};
    bool hasChangedSolid {false};
    int facesChecked {0};
    int facesInvalid {0};

    // The faces it made and those it removed, reversed: they close up into one surface (the
    // unchanged faces cancel), whose divergence integral is the volume's change
    TopoDS_Compound cycle() const
    {
        BRep_Builder builder;
        TopoDS_Compound cycle;
        builder.MakeCompound(cycle);
        for (TopoDS_Iterator it(made); it.More(); it.Next()) {
            builder.Add(cycle, it.Value());
        }
        for (TopoDS_Iterator it(removed); it.More(); it.Next()) {
            builder.Add(cycle, it.Value().Reversed());
        }
        return cycle;
    }

    // The change by the adaptive integration, whatever needsAdaptive() says. The change is a small
    // difference of the changed faces' terms, which are as large as those faces are far from
    // OCCT's reference point: where a fuse re-trims whole thread flanks and the wall (terms of
    // 7e4 mm^3), the default fixed-point rule put a correct +0.168 at -0.224 (ops#640 replica,
    // rb30). Slower: run only where the default's change would refuse the result
    double preciseChange() const
    {
        return Part::MassProperties::volume(cycle(), true);
    }

    void run()
    {
        const bool anyMade = TopoDS_Iterator(made).More();
        change = volumeOf(cycle());

        if (!base.IsNull()) {
            baseVolume = 0.0;
            for (TopExp_Explorer it(base, TopAbs_SOLID); it.More(); it.Next()) {
                const double volume = volumeOf(it.Current());
                const double ratio = volume / std::max(boxVolume(it.Current()), 1e-300);
                baseWorstSolid = baseHasSolid ? std::min(baseWorstSolid, ratio) : ratio;
                baseHasSolid = true;
                baseVolume += volume;
            }
        }

        // The solids it changed. One solid: the base's volume and the change give it, against the
        // box of the faces it made (a part's change no larger than it, the box no larger than the
        // part's: a small change to a sound part is far from "no volume", a collapse isn't)
        auto judge = [this](double volume, double box) {
            const double ratio = volume / std::max(box, 1e-300);
            if (!hasChangedSolid || ratio < worstSolid) {
                worstSolid = ratio;
                worstSolidVolume = volume;
            }
            hasChangedSolid = true;
        };
        if (oneSolid) {
            if (anyMade) {
                judge(baseVolume + change, boxVolume(made));
            }
        }
        else {
            for (TopoDS_Iterator it(solids); it.More(); it.Next()) {
                judge(volumeOf(it.Value()), boxVolume(it.Value()));
            }
        }

        for (TopoDS_Iterator it(faces); it.More(); it.Next()) {
            ++facesChecked;
            if (!Part::KernelBudget::checkValid(it.Value())) {
                ++facesInvalid;
            }
        }
    }
};

bool checkingResults()
{
    return App::GetApplication()
        .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/PartDesign")
        ->GetBool("CheckResults", true);
}

std::string number(double value)
{
    std::ostringstream text;
    text.precision(8);
    text << value;
    return text.str();
}

const char* notBuilt = ": the feature is not built";

/// Empty when the result passes, else what is wrong. \a lastVouched: the result this feature's
/// last recompute vouched for; the same result again needs no check.  whole: set when it passes
/// with every face of the result checked (a feature with no base, kernel-9)
std::string checkResult(
    Feature& feature,
    bool inputsValid,
    const TopoDS_Shape& lastVouched,
    bool& whole,
    PostCondition::Observed& observed
)
{
    whole = false;
    TopoDS_Shape result = feature.Shape.getShape().getShape();
    if (result.IsNull() || TopExp_Explorer(result, TopAbs_SOLID).More() == Standard_False) {
        // An additive feature never takes the part away: OCCT's fuse can return an empty
        // compound without an error (a groove's end wall revolved about its own edge, kernel-10)
        auto addSub = dynamic_cast<FeatureAddSub*>(&feature);
        if (addSub && addSub->getAddSubType() == FeatureAddSub::Type::Additive) {
            TopoDS_Shape base = feature.getBaseTopoShape(true).getShape();
            if (!base.IsNull() && TopExp_Explorer(base, TopAbs_SOLID).More()) {
                return std::string("The geometry kernel lost the part: the result has no solid")
                    + notBuilt;
            }
        }
        return {};
    }
    if (inputsValid && !lastVouched.IsNull() && result.IsEqual(lastVouched)) {
        return {};
    }
    TopoDS_Shape base = feature.getBaseTopoShape(true).getShape();

    TopoDS_Shape checked = result;
    if (auto note = refineNotes.find(&feature); note != refineNotes.end()) {
        // The refine rebuilds faces it doesn't merge: the shape it started from has the base's
        const RefineNote& refine = note->second;
        if (!refine.before.IsNull() && refine.after.TShape() == result.TShape()) {
            checked = refine.before.Moved(result.Location() * refine.after.Location().Inverted());
        }
        else if (!refine.before.IsNull()) {
            // The solid taken out of the refine's result (getSolid): the one solid before it
            auto onlySolid = [](const TopoDS_Shape& shape) {
                TopoDS_Shape found;
                int count = 0;
                for (TopExp_Explorer it(shape, TopAbs_SOLID); it.More(); it.Next(), ++count) {
                    found = it.Current();
                }
                return count == 1 ? found : TopoDS_Shape();
            };
            const TopoDS_Shape after = onlySolid(refine.after);
            const TopoDS_Shape before = onlySolid(refine.before);
            if (!after.IsNull() && !before.IsNull() && after.TShape() == result.TShape()) {
                checked = before.Moved(result.Location() * after.Location().Inverted());
            }
        }
        refineNotes.erase(note);
    }

    // What changed, from the topology alone (the TShapes, orientations and locations, which the
    // redraw's meshing doesn't touch), on this thread: about a microsecond per face
    FaceMap baseFaces;
    FaceMap resultFaces;
    if (!base.IsNull()) {
        collectFaces(base, baseFaces);
    }
    collectFaces(checked, resultFaces);
    // Where the base may have been repaired, every face is checked and the base's volume says
    // nothing about the result's (the repair changed it). A base the feature vouches for
    // (booleanInputCheck() Tools) was valid and is not repaired: only a tool was, the base's
    // faces and volume are the result's starting point, and the diff and its direction check
    // apply (kernel-6, debt (a)). An invalid base nobody vouches for (an imported one) still
    // gets no direction check. (A dress-up has no boolean: its flag says nothing)
    const bool allFaces = !inputsValid && !base.IsNull() && !feature.isDerivedFrom<DressUp>()
        && feature.booleanInputCheck() == Part::BooleanInputCheck::All;
    BRep_Builder builder;
    TopoDS_Compound made;
    TopoDS_Compound removed;
    TopoDS_Compound faces;
    TopoDS_Compound solids;
    builder.MakeCompound(made);
    builder.MakeCompound(removed);
    builder.MakeCompound(faces);
    builder.MakeCompound(solids);
    TopTools_IndexedMapOfShape changed;
    for (const auto& [tshape, face] : resultFaces) {
        if (!containsFace(baseFaces, face)) {
            builder.Add(made, face);
            changed.Add(face);
        }
    }
    for (const auto& [tshape, face] : baseFaces) {
        if (!containsFace(resultFaces, face)) {
            builder.Add(removed, face);
        }
    }
    // The post-conditions read the same diff (PostCondition.h, report-only)
    observed.fresh = true;
    observed.base = base;
    observed.checked = checked;
    observed.made = made;
    const bool roundsOrChamfers = feature.isDerivedFrom<Fillet>() || feature.isDerivedFrom<Chamfer>();
    // A fillet's and a chamfer's whole result is checked where they are built
    if (!roundsOrChamfers) {
        for (const auto& [tshape, face] : resultFaces) {
            if (allFaces || changed.Contains(face)) {
                builder.Add(faces, face);
            }
        }
    }
    int solidCount = 0;
    for (TopExp_Explorer it(checked, TopAbs_SOLID); it.More(); it.Next()) {
        ++solidCount;
    }
    std::string shellProblem;
    for (TopExp_Explorer solid(checked, TopAbs_SOLID); solid.More(); solid.Next()) {
        bool touchedSolid = false;
        for (TopExp_Explorer it(solid.Current(), TopAbs_SHELL); it.More(); it.Next()) {
            bool touched = allFaces;
            for (TopExp_Explorer face(it.Current(), TopAbs_FACE); face.More() && !touched;
                 face.Next()) {
                touched = changed.Contains(face.Current());
            }
            if (!touched) {
                continue;
            }
            touchedSolid = true;
            // The shell's checks read its topology (and seams' pcurves): here, not on a copy
            if (!roundsOrChamfers && shellProblem.empty()) {
                BRepCheck_Shell shell(TopoDS::Shell(it.Current()));
                if (shell.Closed() != BRepCheck_NoError) {
                    shellProblem = "a shell is open";
                }
                else if (!Part::KernelBudget::orientedConsistently(
                             shell, TopoDS::Shell(it.Current()))) {
                    shellProblem = "a shell's faces are not oriented consistently";
                }
            }
        }
        if (touchedSolid && solidCount > 1 && !allFaces) {
            builder.Add(solids, solid.Current());
        }
    }

    auto check = std::make_shared<Check>();
    check->oneSolid = solidCount == 1 && !allFaces;
    if (allFaces) {
        // Each solid's volume on its own: the base's says nothing here
        for (TopExp_Explorer it(checked, TopAbs_SOLID); it.More(); it.Next()) {
            builder.Add(solids, it.Current());
        }
    }
    double baseVolume = 0.0;
    const bool baseVolumeKnown = base.IsNull() || knownVolume(base, baseVolume);
    check->baseVolume = baseVolume;
    // Exact copies of all in one, so that the TShapes they share stay shared, and an abandoned
    // check reads nothing the document changes (the pass-through's redraw meshes the base's shapes)
    {
        TopoDS_Compound all;
        builder.MakeCompound(all);
        builder.Add(all, made);
        builder.Add(all, removed);
        builder.Add(all, faces);
        builder.Add(all, solids);
        if (!baseVolumeKnown) {
            builder.Add(all, base);
        }
        const TopoDS_Shape copied = Part::KernelBudget::exactCopy(all);
        TopoDS_Iterator copies(copied);
        check->made = copies.Value();
        copies.Next();
        check->removed = copies.Value();
        copies.Next();
        check->faces = copies.Value();
        copies.Next();
        check->solids = copies.Value();
        copies.Next();
        if (copies.More()) {
            check->base = copies.Value();
        }
    }
    // Stopped by the limit, the feature fails: an unchecked result never passes (kernel layer
    // step 2; it was skipped with a warning, kernel-4)
    if (!Part::KernelBudget::runOptional("The check of the result", [check](const Message_ProgressRange&) {
            check->run();
        })) {
        return "The check of the result did not finish: the feature took longer than "
            + number(Part::KernelBudget::limit())
            + " s, the time limit for one feature's geometry (Part preference GeometryTimeLimit)"
            + notBuilt;
    }

    const double before = check->baseVolume;
    double after = check->baseVolume + check->change;
    // A solid of no volume: of less than a billionth of its own bounding box
    constexpr double noVolume = 1e-9;
    if (check->baseHasSolid && check->baseWorstSolid <= noVolume) {
        std::string baseName = "its base";
        if (auto object = feature.getBaseObject(true)) {
            baseName = std::string("its base (") + object->Label.getValue() + ")";
        }
        return "The part this feature starts from, " + baseName
            + ", is a solid with no volume or turned inside out" + notBuilt;
    }
    const double scale = std::max({1.0, std::abs(before), std::abs(after)});
    if (check->hasChangedSolid && check->worstSolid <= noVolume) {
        return "The geometry kernel built a solid with no volume or turned inside out (volume "
            + number(check->worstSolidVolume) + ")" + notBuilt;
    }
    const double tolerance = 1e-5 * scale;
    if (!base.IsNull() && !allFaces) {
        const Direction direction = directionOf(feature);
        auto wrongWay = [&](double change) {
            return (direction == Direction::Grows && change < -tolerance)
                || (direction == Direction::Shrinks && change > tolerance);
        };
        // Refused only by the adaptive integration's change: the default's can be off by more than
        // the tolerance (preciseChange()). Stopped by the limit, the default's change stands
        if (wrongWay(check->change)) {
            auto precise = std::make_shared<double>(check->change);
            if (Part::KernelBudget::runOptional(
                    "The check of the result's volume",
                    [check, precise](const Message_ProgressRange&) {
                        *precise = check->preciseChange();
                    }
                )) {
                check->change = *precise;
                after = check->baseVolume + check->change;
            }
        }
        switch (direction) {
            case Direction::Grows:
                if (check->change < -tolerance) {
                    return "The geometry kernel's result is wrong: adding material made the part "
                           "smaller (volume "
                        + number(before) + " to " + number(after) + ")" + notBuilt;
                }
                break;
            case Direction::Shrinks:
                if (check->change > tolerance) {
                    return "The geometry kernel's result is wrong: removing material made the part "
                           "larger (volume "
                        + number(before) + " to " + number(after) + ")" + notBuilt;
                }
                break;
            case Direction::None:
                break;
        }
    }
    if (check->facesInvalid > 0) {
        return "The geometry kernel built an invalid shape: " + std::to_string(check->facesInvalid)
            + " of the " + std::to_string(check->facesChecked)
            + (allFaces ? " faces" : " faces it made or changed") + " fail the shape check"
            + notBuilt;
    }
    if (!shellProblem.empty()) {
        return "The geometry kernel built an invalid shape: " + shellProblem + notBuilt;
    }
    if (!allFaces) {
        rememberVolume(result, after);
    }
    if (!base.IsNull() && !allFaces) {
        observed.volumeKnown = true;
        observed.change = check->change;
        observed.after = after;
    }
    whole = base.IsNull() && !roundsOrChamfers && checked.IsEqual(result);
    return {};
}
}  // namespace

void ResultCheck::noteRefine(const Feature* feature, const TopoDS_Shape& before, const TopoDS_Shape& after)
{
    // Only a recompute's own refines are read; a preview's would stay (one per feature) until then
    if (feature && feature->isRecomputing()) {
        refineNotes[feature] = {before, after};
    }
}

void ResultCheck::stopIfPastTheLimit(const char* step)
{
    Part::KernelBudget::stopIfPastDeadline(step);
}

App::DocumentObjectExecReturn* Feature::recompute()
{
    failedElsewhere = false;
    DeletePart::setLocked(this, false);
    booleanInputsValid = false;
    // The result this recompute may find again: then its check has nothing new to read
    const TopoDS_Shape lastVouched = vouchedShape;
    vouchedShape.Nullify();
    // Held by the Body's roll-back bar (ops#127): not run on any path (also obj.recompute()); it
    // stays touched and runs when the bar passes it
    if (auto body = getFeatureBody(); body && body->holds(this)) {
        return App::DocumentObject::StdReturn;
    }

    setMaterialToBodyMaterial();

    if (Suppressed.getValue()) {
        if (auto doc = getDocument()) {
            doc->clearWarning(this);  // it computes nothing of its own (ops#127)
        }
        // Before the shape: setting it solves the references to it, which judge by this state
        // (ops#549 PS)
        if (!_PassedThrough.getValue()) {
            _PassedThrough.setValue(true);
        }
        setFailurePassedThrough(false);
        // FreeCAD-CH ops#654 S2: an owner's shape stays empty, never its in-scope parts
        Shape.setValue(runsAsStudioOwner(this) ? TopoShape() : getBaseTopoShape(true));
        updateSuppressedShape();
        return App::DocumentObject::StdReturn;
    }

    SuppressedShape.setValue(TopoShape());
    // The output is the feature's own from here: a failure's pass-through, written after this
    // recompute if it fails, sets its own state then (ops#549 PT)
    if (_PassedThrough.getValue()) {
        _PassedThrough.setValue(false);
    }
    setFailurePassedThrough(false);

    // Its Body is merged into another part, at an earlier feature (FreeCAD-CH ops#325, design
    // 2.6): it doesn't reach the Merge. Checked here, as every path that adds or moves a solid
    // (a command, Python, a reorder, undo) ends here
    if (std::string why = Boolean::mergeLock(this); !why.empty()) {
        return new App::DocumentObjectExecReturn(why, this);
    }
    // After a Delete part in its Body, or reading a part deleted before it (ops#635)
    std::string lock = DeletePart::deleteLock(this);
    DeletePart::setLocked(this, !lock.empty());
    if (!lock.empty()) {
        return new App::DocumentObjectExecReturn(lock, this);
    }

    const char* placer = nullptr;
    std::string where;
    if (placerElsewhere(&placer, &where)) {
        failedElsewhere = true;
        return new App::DocumentObjectExecReturn(
            std::string(placer) + " of this feature is in " + where + ", " + placedElsewhere
                + ": bind it with a Sub-Shape Binder",
            this
        );
    }

    // In a Body, an input in error fails the feature before it runs; the recompute's continuation
    // rule then passes its base shape through (ops#126). getFeatureBody() is the rule's own
    // membership test for a feature (FailureContinuation.cpp, bodyOf())
    if (getFeatureBody()) {
        std::string why;
        if (inputInError(this, why)) {
            // FreeCAD-CH (ops#640 round 8, J13): failed without running, as a document's stop
            // (Document::recompute()): nothing is pending, and it runs again when its input does
            purgeTouched();
            return new App::DocumentObjectExecReturn(why, this);
        }
    }
    refineNotes.erase(this);
    // The feature's execute and the check of its result share one deadline (kernel safety S1)
    Part::KernelBudget::Scope budget;
    auto ret = Part::Feature::recompute();
    bool checkedWhole = false;
    // FreeCAD-CH kernel safety S2: a result the kernel got wrong fails here, at its feature. A
    // BaseFeature builds nothing: the first feature on it checks the base it passes on
    if (ret == App::DocumentObject::StdReturn && getFeatureBody() && Body::isSolidFeature(this)
        && !isDerivedFrom<FeatureBase>() && checkingResults()) {
        std::string why;
        PostCondition::Observed observed;
        try {
            ResultCheck::stopIfPastTheLimit("The check of the result");
            why = checkResult(*this, booleanInputsValid, lastVouched, checkedWhole, observed);
        }
        catch (const Base::Exception& e) {
            why = e.what();
        }
        catch (const Standard_Failure& e) {
            why = std::string("The check of the result failed: ") + e.GetMessageString();
        }
        if (!why.empty()) {
            ret = new App::DocumentObjectExecReturn(why, this);
        }
        else if (PostCondition::enabled()) {
            // Report-only: logged, never thrown, the result unchanged
            PostCondition::report(*this, observed);
        }
    }
    // A call the limit or Esc stopped fails the feature, whatever its code made of it (kernel-4)
    if (const std::string fired = budget.fired(); !fired.empty()) {
        delete ret;
        ret = new App::DocumentObjectExecReturn(fired, this);
    }
    refineNotes.erase(this);
    // A result with every face checked, of a feature with no base, is vouched for as one made from
    // valid inputs is: the next feature's boolean doesn't check it again (kernel-9: a plate's two
    // faces with thousands of holes, checked once here, then again in the next cut's input check)
    if (ret == App::DocumentObject::StdReturn && (booleanInputsValid || checkedWhole)) {
        vouchedShape = Shape.getShape().getShape();
    }
    else if (ret != App::DocumentObject::StdReturn
             && (getFeatureBody() || runsAsStudioOwner(this))) {
        // FreeCAD-CH (ops#640 round 8, J13): it ran and failed, as Onshape's red feature: nothing
        // is pending (a recompute would fail it again); it runs again when an input changes. A
        // studio owner too (ops#654 S2)
        purgeTouched();
    }
    return ret;
}

App::DocumentObjectExecReturn* Feature::recomputePreview()
{
    updatePreviewShape();

    return StdReturn;
}

void Feature::setMaterialToBodyMaterial()
{
    auto body = getFeatureBody();
    if (body) {
        // Ensure the part has the same material as the body
        auto feature = dynamic_cast<Part::Feature*>(body);
        if (feature) {
            copyMaterial(feature);
        }
    }
}

void Feature::updateSuppressedShape()
{
    TopoShape res = makeTopoShape(false);
    TopoShape shape = Shape.getShape();
    shape.setPlacement(Base::Placement());
    std::vector<TopoShape> generated;
    if (!shape.isNull()) {
        unsigned count = shape.countSubShapes(TopAbs_FACE);
        for (unsigned i = 1; i <= count; ++i) {
            Data::MappedName mapped = shape.getMappedName(Data::IndexedName::fromConst("Face", i));
            if (mapped && shape.isElementGenerated(mapped)) {
                generated.push_back(shape.getSubTopoShape(TopAbs_FACE, i));
            }
        }
    }
    if (!generated.empty()) {
        res.makeElementCompound(generated);
        res.setPlacement(Placement.getValue());
    }
    SuppressedShape.setValue(res);
}

short Feature::mustExecute() const
{
    if (BaseFeature.isTouched()) {
        return 1;
    }
    // Moving another Body touches neither what this feature reads of it nor this feature: run
    // when the Bodies come apart, and again after that failure once they agree, also in a
    // reopened file (the error is saved with it), so the error clears (ops#308 F5). Only on that
    // failure: any other reran on every recompute (R2-2), and so did this one while the Bodies
    // stayed apart. Not when suppressed or held: then recompute() doesn't fail, and nothing
    // would ever settle (F6). No Body::onChanged(Placement) hook: a moved Body is itself touched,
    // so the next recompute asks here (ops#325); a container moved by an expression in the
    // middle of a recompute touches this when it asks to run (ContainerMoves.h, ops#342)
    if (!Suppressed.getValue() && !placerProperties().empty()) {
        auto moved = [this] {
            auto body = getFeatureBody();
            return body && !body->holds(this)
                && placerElsewhere() != (failedElsewhere && isError());
        };
        // The walk reads in-lists, groups and placements a recompute on another thread changes.
        // A recompute's own question (on this thread for any document, or the worker's) walks;
        // the GUI's Refresh poll walks only while the async worker recomputes nothing, in no
        // document, and holds it off meanwhile, else answers as if nothing moved (ops#352, as
        // ops#337's attachment poll)
        bool run = false;
        if (App::isRecomputingOnThisThread() || App::isRecomputeWorkerThread()) {
            run = moved();
        }
        else {
            App::runWhileRecomputeWorkerIdle([&] { run = moved(); });
        }
        if (run) {
            return 1;
        }
    }
    // A Delete part dragged across Bodies, rolled past, deleted or suppressed touches neither
    // this feature nor what it reads: run when its lock comes or goes (ops#635), as above
    if (!Suppressed.getValue()) {
        auto relocked = [this] {
            auto body = getFeatureBody();
            if (!body || body->holds(this)) {
                return false;
            }
            return DeletePart::deleteLock(this).empty() == (DeletePart::wasLocked(this) && isError());
        };
        bool run = false;
        if (App::isRecomputingOnThisThread() || App::isRecomputeWorkerThread()) {
            run = relocked();
        }
        else {
            App::runWhileRecomputeWorkerIdle([&] { run = relocked(); });
        }
        if (run) {
            return 1;
        }
    }
    return Part::Feature::mustExecute();
}

void Feature::onDocumentRestored()
{
    // The error and its text are restored with the document, before this
    const char* why = isError() ? getDocument()->getErrorDescription(this) : nullptr;
    failedElsewhere = why && std::strstr(why, placedElsewhere);
    DeletePart::setLocked(this, DeletePart::isDeleteLock(why));
    Part::Feature::onDocumentRestored();
}

TopoShape Feature::makeResultShape(const TopoShape& base) const
{
    if (getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V1) {
        return TopoShape(base.Tag, base.Hasher, base.getHistoryAlgorithm());
    }
    return makeTopoShape(false);
}

TopoShape Feature::getSolid(const TopoShape& shape) const
{
    if (shape.isNull()) {
        throw Part::NullShapeException("Null shape 1");
    }

    // If single solid rule is not enforced  we simply return the shape as is
    if (singleSolidRuleMode() != Feature::SingleSolidRuleMode::Enforced) {
        return shape;
    }

    int count = shape.countSubShapes(TopAbs_SOLID);
    if (count) {
        auto res = shape.getSubTopoShape(TopAbs_SOLID, 1);
        res.fixSolidOrientation();
        return res;
    }

    return shape;
}

void Feature::onBaseFeatureRerouted(
    App::DocumentObject* /*oldBase*/,
    App::DocumentObject* /*newBase*/,
    bool /*reorder*/
)
{}

namespace
{

// The relink in a reference solver document (ops#7, Task 2 PR 6): the link moves to the new base
// with every reference marked missing, keeping its old mapped name (the shadow) and its saved
// fingerprint, and the solver then resolves them against the new base. An index name never
// carries over from one shape to another: a reference is found exactly by its name (a 1:1
// modified element keeps its incoming name, so an edge the old base only trimmed is the new
// base's full edge), by the solver's evidence, or it breaks with its candidates reported.
// Without the solver (ops#285) the references are found by their name only, as upstream's
// missing references are. Returns false, leaving the link as it is, if a reference has no mapped
// name or a sub-object path, as the name match does.
bool relinkAsMissing(
    App::PropertyLinkSub& link,
    const Part::TopoShape& oldShape,
    App::DocumentObject* newBase,
    bool solver
)
{
    const auto& oldSubs = link.getSubValues();
    const auto& oldShadows = link.getShadowSubs();
    std::vector<std::string> subs;
    std::vector<App::PropertyLinkBase::ShadowSub> shadows;
    for (std::size_t i = 0; i < oldSubs.size(); ++i) {
        const auto& sub = oldSubs[i];
        if (sub.empty()) {
            subs.emplace_back();
            shadows.emplace_back();
            continue;
        }
        if (Data::findElementName(sub.c_str()) != sub.c_str()) {
            return false;
        }
        std::string mapped;
        std::string index;
        if (i < oldShadows.size()) {
            mapped = App::bareMappedName(oldShadows[i].newName);
            const char* element = Data::findElementName(oldShadows[i].oldName.c_str());
            index = element ? element : "";
            if (Data::hasMissingElement(index.c_str())) {
                index.erase(0, std::strlen(Data::MISSING_PREFIX));
            }
        }
        if (mapped.empty() || index.empty()) {
            Data::MappedElement element = oldShape.getElementName(sub.c_str());
            mapped = element.name.toString();
            index = element.index ? element.index.toString() : std::string();
        }
        if (mapped.empty() || index.empty()) {
            return false;
        }
        std::string missing = Data::MISSING_PREFIX + index;
        subs.push_back(missing);
        shadows.emplace_back(
            Data::ComplexGeoData::elementMapPrefix() + mapped + "." + index,
            missing
        );
    }
    link.setValue(newBase, std::move(subs), std::move(shadows));
    // A new base that hasn't computed yet (insert at the roll-back bar, ops#127): its first shape
    // solves the references, since a missing reference is solved on every update of its target
    auto newFeature = freecad_cast<Part::Feature*>(newBase);
    if (newFeature && !newFeature->Shape.getShape().isNull()) {
        // A throw would leave a reorder half-written (fork PR 270 review, L4), as in Rule::solve
        try {
            if (solver) {
                App::solveElementReferences(newBase, {&link}, false, true);
            }
            else {
                link.updateElementReference(newBase, false, true);
            }
        }
        catch (Base::Exception& e) {
            FC_ERR(link.getFullName() << ": " << e.what());
        }
    }
    return true;
}

/// Whether obj comes after the link's owner in the owner's Body: a reorder moved it below
bool comesAfterOwner(const App::PropertyLinkSub& link, const App::DocumentObject* obj)
{
    auto owner = freecad_cast<App::DocumentObject*>(link.getContainer());
    auto body = owner ? Body::findBodyOf(owner) : nullptr;
    if (!body) {
        return false;
    }
    const auto& group = body->Group.getValues();
    auto ownerIt = std::ranges::find(group, owner);
    auto objIt = std::ranges::find(group, obj);
    return ownerIt != group.end() && objIt != group.end() && objIt > ownerIt;
}

// The relink without the solver (upstream's): every reference must match exactly one element of
// the new base by its name (V2) or its geometry (V1), or the link is left as it is. A name that
// matches several elements (a face the new base split in two) is no match: taking the first was
// a silent guess (fork PR 282 review, F3; ops#79's policy for the loose pass)
bool relinkByName(
    App::PropertyLinkSub& link,
    Part::Feature* oldFeature,
    Part::Feature* newFeature
)
{
    const auto& oldShape = oldFeature->Shape.getShape();
    const auto& newShape = newFeature->Shape.getShape();
    if (newShape.isNull()) {
        return false;
    }

    const auto& oldSubs = link.getSubValues();
    std::vector<std::string> newSubs;
    newSubs.reserve(oldSubs.size());

    const App::HistoryAlgorithm& selectedHistoryAlgorithm = oldFeature->getSelectedHistoryAlgorithm();

    for (const auto& sub : oldSubs) {
        if (sub.empty()) {
            newSubs.emplace_back();
            continue;
        }

        Data::MappedElement subMappedElement = oldShape.getElementName(sub.c_str());

        if (!subMappedElement.index) {
            return false;
        }

        std::pair<TopAbs_ShapeEnum, int> subDecodedIndexedName = Part::TopoShape::shapeTypeAndIndex(
            subMappedElement.index
        );
        if (subDecodedIndexedName.second <= 0) {
            return false;
        }

        auto oldSubShape = oldShape.getSubTopoShape(
            subDecodedIndexedName.first,
            subDecodedIndexedName.second,
            true
        );

        if (oldSubShape.isNull()) {
            return false;
        }

        std::vector<std::string> names;

        if (selectedHistoryAlgorithm == App::HistoryAlgorithm::V1) {
            auto matches = newShape.findSubShapesWithSharedVertex(
                oldSubShape,
                &names,
                Data::SearchOption::CheckGeometry
            );

            if (matches.size() != 1) {
                return false;
            }
        }
        else if (selectedHistoryAlgorithm == App::HistoryAlgorithm::V2) {
            std::vector<Data::MappedElement> foundNames
                = Part::Feature::findSimilarNames(subMappedElement.name, newShape);

            if (foundNames.size() == 1) {
                names.push_back(foundNames.front().name.toString());
            }
        }

        if (names.size() != 1) {
            return false;
        }

        newSubs.push_back(names.front());
    }

    link.setValue(newFeature, std::move(newSubs));
    return true;
}

}  // namespace

bool Feature::relinkToMatchingSubelements(
    App::PropertyLinkSub& link,
    App::DocumentObject* oldBase,
    App::DocumentObject* newBase,
    bool reorder
)
{
    if (!oldBase || link.getValue() != oldBase) {
        return false;
    }
    // A reorder that moved the old base below the owner (ops#285): left there, the link would
    // make a dependency cycle, which the reorder's cycle check doesn't see because it plans this
    // link on the new base (N1 3.5).
    const bool cycle = comesAfterOwner(link, oldBase);
    // Any other reorder (ops#291, PLAN decision 50): left on the old base, an earlier object, the
    // link would point at an object no longer before the owner in the chain, which a re-pick can't
    // tell from a link that works. A link left on an earlier object by an insert at the bar (N1
    // 2.2, decision 48) stays as it is.
    const bool follow = cycle || reorder;

    auto oldFeature = freecad_cast<Part::Feature*>(oldBase);
    auto newFeature = freecad_cast<Part::Feature*>(newBase);
    const Part::TopoShape oldShape = oldFeature ? oldFeature->Shape.getShape() : Part::TopoShape();
    const bool solver = link.inSolverDocument();
    if (newFeature && !oldShape.isNull()) {
        if (solver) {
            // Also onto a new base without a shape yet (ops#127, N1 2.2)
            if (relinkAsMissing(link, oldShape, newBase, true)) {
                return true;
            }
        }
        else if (relinkByName(link, oldFeature, newFeature)) {
            return true;
        }
    }
    // A solver document's relink above needs the old base's shape: from an old base without one
    // (a feature that never computed) the names come from the link's shadows here too, or the link
    // stays on an object no longer before the owner (fork PR 282 round 2 verification, A)
    if (newFeature && follow && (!solver || oldShape.isNull())) {
        if (relinkAsMissing(link, oldShape, newBase, solver)) {
            // With its references missing; also from an old base without a shape (one that
            // failed), the names coming from the link's shadows (fork PR 282 review, F2). In a
            // reorder the new base still has its shape from before the reorder, which can hold
            // the owner's own result (a fillet's faces where its edge was): the name is looked up
            // again when the new base recomputes, and a reference found then resolves (an edge
            // the new base leaves alone); one that isn't makes the owner fail until it is
            // re-picked, its error naming the reference (a log line here: review F6)
            FC_LOG(link.getFullName() << ": moved by a reorder to " << newBase->getFullName());
            return true;
        }
    }
    // A solver document keeps its link outside a cycle, as before ops#291 (fork PR 282 review,
    // F1): its relink above fails only on a reference without a name to carry
    if (!cycle && (!follow || solver)) {
        return false;
    }
    // No new base (the owner is now the first solid), or a reference without a name to carry
    // (none in its shadow, and the old base has no shape to read it from): the link is cleared,
    // so the owner fails until it is re-picked (fork PR 270 review, M1 and L3)
    std::string subs;
    for (const auto& sub : link.getSubValues()) {
        subs += (subs.empty() ? "" : ", ") + sub;
    }
    FC_WARN(
        link.getFullName() << ": cleared its link to " << oldBase->getFullName() << " (" << subs
                           << (cycle ? "), which a reorder moved below it"
                                     : "), whose references a reorder couldn't carry")
    );
    link.setValue(nullptr);
    // A dress-up's BaseFeature follows its Base, so the clear has just nulled the BaseFeature the
    // reroute set: put the new base back, or the owner is off the chain and a re-pick doesn't
    // mend it (fork PR 270 round 1 verification)
    auto owner = freecad_cast<Feature*>(link.getContainer());
    if (newBase && owner && !owner->BaseFeature.getValue()) {
        owner->BaseFeature.setValue(newBase);
    }
    return true;
}

void Feature::onChanged(const App::Property* prop)
{
    if (!this->isRestoring() && this->getDocument()
        && !this->getDocument()->isPerformingTransaction()) {
        // Setting BaseFeature doesn't reorder the Body (ops#77). Upstream had a reorder here that
        // never ran: it looked the base's index up into the feature's. Turned on, it would have
        // fired for nearly every new feature (the sketch between a feature and its base counts in
        // Group), and Body::insertObject would have listed the base twice.
        if (prop == &ShapeMaterial) {
            auto body = Body::findBodyOf(this);
            if (body) {
                if (body->ShapeMaterial.getValue().getUUID() != ShapeMaterial.getValue().getUUID()) {
                    body->ShapeMaterial.setValue(ShapeMaterial.getValue());
                }
            }
        }
        else if (prop == &Suppressed) {
            if (Suppressed.getValue()) {
                SuppressedPlacement = Placement.getValue();
                updateSuppressedShape();
            }
            else {
                Placement.setValue(SuppressedPlacement);
                SuppressedPlacement = Base::Placement();
            }
        }
    }
    // ops#524: a Placement set while recomputing runs ahead of the shape until the next shape
    // made (placedAheadOfShape()); the shape's own transform, set from it, isn't one
    if (prop == &Placement && isRecomputing()) {
        std::lock_guard<std::mutex> lock(placedAheadMutex);
        placedAhead.insert(this);
    }
    else if (prop == &Shape && placingShape != this) {
        std::lock_guard<std::mutex> lock(placedAheadMutex);
        placedAhead.erase(this);
    }
    const Feature* outer = placingShape;
    if (prop == &Placement) {
        placingShape = this;
    }
    try {
        Part::Feature::onChanged(prop);
    }
    catch (...) {
        placingShape = outer;
        throw;
    }
    placingShape = outer;
}

int Feature::countSolids(const TopoDS_Shape& shape, TopAbs_ShapeEnum type)
{
    int result = 0;
    if (shape.IsNull()) {
        return result;
    }
    TopExp_Explorer xp;
    xp.Init(shape, type);
    for (; xp.More(); xp.Next()) {
        result++;
    }
    return result;
}

TopoShape Feature::fixSolids(const TopoShape& solids)
{
    if (solids.isNull()) {
        return solids;
    }

    std::vector<TopoDS_Solid> fixSolids;

    TopExp_Explorer xp;
    xp.Init(solids.getShape(), TopAbs_SOLID);
    for (; xp.More(); xp.Next()) {
        TopoDS_Solid solid = TopoDS::Solid(xp.Current());
        BRepCheck_Solid bs(solid);
        if (bs.IsStatusOnShape(solid)) {
            const auto& listOfStatus = bs.StatusOnShape(solid);
            if (listOfStatus.Contains(BRepCheck_EnclosedRegion)) {
                fixSolids.emplace_back(solid);
            }
        }
    }

    if (fixSolids.empty()) {
        return solids;
    }

    TopoDS_Compound comp;
    TopoDS_Builder bb;
    bb.MakeCompound(comp);
    for (const TopoDS_Solid& it : fixSolids) {
        ShapeFix_Solid fix(it);
        fix.Perform();
        bb.Add(comp, fix.Solid());
    }

    TopoShape fixShape = makeTopoShape(comp);
    return fixShape;
}

bool Feature::isSingleSolidRuleSatisfied(const TopoDS_Shape& shape, TopAbs_ShapeEnum type)
{
    if (singleSolidRuleMode() == Feature::SingleSolidRuleMode::Disabled) {
        return true;
    }

    int solidCount = countSolids(shape, type);

    return solidCount <= 1;
}


Feature::SingleSolidRuleMode Feature::singleSolidRuleMode() const
{
    auto body = getFeatureBody();

    // When the feature is not part of an body (which should not happen) let's stay with the default
    if (!body) {
        // FreeCAD-CH ops#654 S2: an owner's tool may have several solids (one per region); its
        // steps keep each part one solid (FeatureApply)
        return runsAsStudioOwner(this) ? SingleSolidRuleMode::Disabled
                                       : SingleSolidRuleMode::Enforced;
    }

    auto areCompoundSolidsAllowed = body->AllowCompound.getValue();

    return areCompoundSolidsAllowed ? SingleSolidRuleMode::Disabled : SingleSolidRuleMode::Enforced;
}

const gp_Pnt Feature::getPointFromFace(const TopoDS_Face& f)
{
    if (!f.Infinite()) {
        TopExp_Explorer exp;
        exp.Init(f, TopAbs_VERTEX);
        if (exp.More()) {
            return BRep_Tool::Pnt(TopoDS::Vertex(exp.Current()));
        }
        // Else try the other method
    }

    // TODO: Other method, e.g. intersect X,Y,Z axis with the (unlimited?) face?
    // Or get a "corner" point if the face is limited?
    throw Base::NotImplementedError("getPointFromFace(): Not implemented yet for this case");
}

Part::Feature* Feature::getBaseObject(bool silent) const
{
    App::DocumentObject* BaseLink = BaseFeature.getValue();
    Part::Feature* BaseObject = nullptr;
    const char* err = nullptr;

    if (BaseLink) {
        if (BaseLink->isDerivedFrom<Part::Feature>()) {
            BaseObject = static_cast<Part::Feature*>(BaseLink);
        }
        if (!BaseObject) {
            err = "No base feature linked";
        }
    }
    else {
        err = "Base property not set";
    }

    // If the function not in silent mode throw the exception describing the error
    if (!silent && err) {
        throw Base::RuntimeError(err);
    }

    return BaseObject;
}

const TopoDS_Shape& Feature::getBaseShape() const
{
    const Part::Feature* BaseObject = getBaseObject();

    if (!BaseObject) {
        throw Base::ValueError("Base feature's shape is not defined");
    }

    if (BaseObject->isDerivedFrom<PartDesign::ShapeBinder>()
        || BaseObject->isDerivedFrom<PartDesign::SubShapeBinder>()) {
        throw Base::ValueError("Base shape of shape binder cannot be used");
    }

    const TopoDS_Shape& result = BaseObject->Shape.getValue();
    if (result.IsNull()) {
        throw Base::ValueError("Base feature's shape is invalid");
    }
    TopExp_Explorer xp(result, TopAbs_SOLID);
    if (!xp.More()) {
        throw Base::ValueError("Base feature's shape is not a solid");
    }

    return result;
}

Part::TopoShape Feature::getBaseTopoShape(bool silent) const
{
    Part::TopoShape result = makeTopoShape(false);

    // FreeCAD-CH ops#654 S2: an owner's base is its in-scope parts at its place in the history
    // (Through all, the Up-to modes, the preview), one compound child per part, in its
    // container's frame as a Body member's base is in its Body's
    if (runsAsStudioOwner(this)) {
        Part::TopoShape scope = studioScopeBaseAt(this);
        if (scope.isNull()) {
            if (!silent) {
                throw Base::ValueError(
                    "No part in this studio feature's scope has a solid before it"
                );
            }
            return result;
        }
        const Base::Placement container = globalPlacement() * Placement.getValue().inverse();
        scope.transformShape(container.inverse().toMatrix(), false, true);
        return scope;
    }

    const Part::Feature* BaseObject = getBaseObject(silent);
    if (!BaseObject) {
        return result;
    }

    if (BaseObject != BaseFeature.getValue()) {
        if (BaseObject->isDerivedFrom<PartDesign::ShapeBinder>()
            || BaseObject->isDerivedFrom<PartDesign::SubShapeBinder>()) {
            if (silent) {
                return result;
            }
            throw Base::ValueError("Base shape of shape binder cannot be used");
        }
    }

    result = BaseObject->Shape.getShape();
    if (!silent) {
        if (result.isNull()) {
            throw Base::ValueError("Base feature's TopoShape is invalid");
        }
        if (!result.hasSubShape(TopAbs_SOLID)) {
            throw Base::ValueError("Base feature's shape is not a solid");
        }
    }
    else if (!result.hasSubShape(TopAbs_SOLID)) {
        result.setShape(TopoDS_Shape());
    }
    return result;
}

namespace
{
/// Whether two locations are the same transform: the translations within Confusion, the rotation
/// parts within Angular
bool isSameTransform(const TopLoc_Location& a, const TopLoc_Location& b)
{
    const gp_Trsf& ta = a.Transformation();
    const gp_Trsf& tb = b.Transformation();
    for (int row = 1; row <= 3; ++row) {
        for (int col = 1; col <= 4; ++col) {
            const double tolerance = col == 4 ? Precision::Confusion() : Precision::Angular();
            if (std::abs(ta.Value(row, col) - tb.Value(row, col)) > tolerance) {
                return false;
            }
        }
    }
    return true;
}
}  // namespace

TopLoc_Location Feature::getInverseLocation(const TopoShape& base) const
{
    TopLoc_Location location = getLocation();
    if (!base.isNull() && isSameTransform(base.getShape().Location(), location)) {
        return base.getShape().Location().Inverted();
    }
    return location.Inverted();
}

Part::BooleanInputCheck Feature::booleanInputCheck() const
{
    // Evidence, not the feature's type: the base is vouched for only while its Shape is the one
    // its own boolean made from inputs that were all valid as given. A boolean of valid inputs
    // can still give an invalid output; upstream checks no input at all.
    const auto base = freecad_cast<const Feature*>(getBaseObject(true));
    if (base && base->isValid() && !base->vouchedShape.IsNull()
        && base->Shape.getShape().getShape().IsPartner(base->vouchedShape)) {
        return Part::BooleanInputCheck::Tools;
    }
    return Part::BooleanInputCheck::All;
}

Part::TopoShape Feature::getTopoShapeInLocalCoordinates(const App::DocumentObject* object) const
{
    if (!object) {
        return {};
    }

    auto body = getFeatureBody();
    const bool isSameBodyFeature = body && object->isDerivedFrom<PartDesign::Feature>()
        && PartDesign::Body::findBodyOf(object) == body;

    if (isSameBodyFeature) {
        return static_cast<const Part::Feature*>(object)->Shape.getShape();
    }

    Part::ShapeOptions options = Part::ShapeOption::ResolveLink;
    if (!body) {
        return Part::Feature::getTopoShape(object, options | Part::ShapeOption::Transform);
    }

    Base::Matrix4D shapePlacement;
    auto shape = Part::Feature::getTopoShape(object, options, nullptr, &shapePlacement);
    if (!shape.isNull()) {
        Base::Matrix4D placement = getDisplayedObjectPlacement(body).inverse().toMatrix();
        placement *= getDisplayedObjectPlacement(object).toMatrix();
        placement *= shapePlacement;
        shape.transformShape(placement, false, true);
    }
    return shape;
}

void Feature::getGeneratedShapes(
    std::vector<int>& faces,
    std::vector<int>& edges,
    std::vector<int>& vertices
) const
{
    static const auto addAllSubShapesToSet = [](const Part::TopoShape& shape,
                                                const Part::TopoShape& face,
                                                TopAbs_ShapeEnum type,
                                                std::set<int>& set) {
        for (auto& subShape : face.getSubShapes(type)) {
            if (int subShapeId = shape.findShape(subShape); subShapeId > 0) {
                set.insert(subShapeId);
            }
        }
    };

    Part::TopoShape shape = Shape.getShape();

    std::set<int> edgeSet;
    std::set<int> vertexSet;

    int count = shape.countSubShapes(TopAbs_FACE);

    for (int faceId = 1; faceId <= count; ++faceId) {
        if (Data::MappedName mapped = shape.getMappedName(Data::IndexedName::fromConst("Face", faceId));
            shape.isElementGenerated(mapped)) {
            faces.push_back(faceId);

            Part::TopoShape face = shape.getSubTopoShape(TopAbs_FACE, faceId);

            addAllSubShapesToSet(shape, face, TopAbs_EDGE, edgeSet);
            addAllSubShapesToSet(shape, face, TopAbs_VERTEX, vertexSet);
        }
    }

    std::ranges::copy(edgeSet, std::back_inserter(edges));
    std::ranges::copy(vertexSet, std::back_inserter(vertices));
}

void Feature::updatePreviewShape()
{
    // no-op
}

PyObject* Feature::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new FeaturePy(this), true);
    }
    return Py::new_reference_to(PythonObject);
}

bool Feature::isDatum(const App::DocumentObject* feature)
{
    return feature->isDerivedFrom<App::DatumElement>() || feature->isDerivedFrom<Part::Datum>();
}

gp_Pln Feature::makePlnFromPlane(const App::DocumentObject* obj)
{
    const App::GeoFeature* plane = static_cast<const App::GeoFeature*>(obj);
    if (!plane) {
        throw Base::ValueError("Feature: Null object");
    }

    // In the body's coordinates: a datum element is placed in its coordinate system, the body's
    // Origin (at identity unless set from Python) or a coordinate system placed in the body
    // (ops#198). Not the global placement, which adds the body's own
    Base::Placement placement = plane->Placement.getValue();
    if (auto element = dynamic_cast<const App::DatumElement*>(obj)) {
        if (auto lcs = element->getLCS()) {
            placement = lcs->Placement.getValue() * placement;
        }
    }
    Base::Vector3d pos = placement.getPosition();
    Base::Rotation rot = placement.getRotation();
    Base::Vector3d normal(0, 0, 1);
    rot.multVec(normal, normal);
    return gp_Pln(gp_Pnt(pos.x, pos.y, pos.z), gp_Dir(normal.x, normal.y, normal.z));
}

// TODO: Toponaming April 2024 Deprecated in favor of TopoShape method.  Remove when possible.
TopoDS_Shape Feature::makeShapeFromPlane(const App::DocumentObject* obj)
{
    BRepBuilderAPI_MakeFace builder(makePlnFromPlane(obj));
    if (!builder.IsDone()) {
        throw Base::CADKernelError("Feature: Could not create shape from base plane");
    }

    return builder.Shape();
}

TopoShape Feature::makeTopoShapeFromPlane(const App::DocumentObject* obj)
{
    BRepBuilderAPI_MakeFace builder(makePlnFromPlane(obj));
    if (!builder.IsDone()) {
        throw Base::CADKernelError("Feature: Could not create shape from base plane");
    }

    return Feature::makeTopoShape(obj, builder.Shape(), 0, false);
}

Body* Feature::getFeatureBody() const
{

    auto body = freecad_cast<Body*>(_Body.getValue());
    if (body) {
        return body;
    }

    auto list = getInList();
    for (auto in : list) {
        if (in->isDerivedFrom<Body>() &&                // is Body?
            static_cast<Body*>(in)->hasObject(this)) {  // is part of this Body?

            return static_cast<Body*>(in);
        }
    }

    return nullptr;
}

App::DocumentObject* Feature::getSubObject(
    const char* subname,
    PyObject** pyObj,
    Base::Matrix4D* pmat,
    bool transform,
    int depth
) const
{
    if (subname && subname != Data::findElementName(subname)) {
        const char* dot = strchr(subname, '.');
        if (dot) {
            auto body = PartDesign::Body::findBodyOf(this);
            if (body) {
                auto feat = body->Group.findUsingMap(std::string(subname, dot));
                if (feat) {
                    Base::Matrix4D _mat;
                    if (!transform) {
                        // Normally the parent object is supposed to transform
                        // the sub-object using its own placement. So, if no
                        // transform is requested, (i.e. no parent
                        // transformation), we just need to NOT apply the
                        // transformation.
                        //
                        // But PartDesign features (including sketch) are
                        // supposed to be contained inside a body. It makes
                        // little sense to transform its sub-object. So if 'no
                        // transform' is requested, we need to actively apply
                        // an inverse transform.
                        _mat = Placement.getValue().inverse().toMatrix();
                        if (pmat) {
                            *pmat *= _mat;
                        }
                        else {
                            pmat = &_mat;
                        }
                    }
                    return feat->getSubObject(dot + 1, pyObj, pmat, true, depth + 1);
                }
            }
        }
    }
    return Part::Feature::getSubObject(subname, pyObj, pmat, transform, depth);
}


}  // namespace PartDesign

namespace App
{
/// @cond DOXERR
PROPERTY_SOURCE_TEMPLATE(PartDesign::FeaturePython, PartDesign::Feature)
template<>
const char* PartDesign::FeaturePython::getViewProviderName() const
{
    return "PartDesignGui::ViewProviderPython";
}
template<>
PyObject* PartDesign::FeaturePython::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new FeaturePythonPyT<PartDesign::FeaturePy>(this), true);
    }
    return Py::new_reference_to(PythonObject);
}
/// @endcond

// explicit template instantiation
template class PartDesignExport FeaturePythonT<PartDesign::Feature>;
}  // namespace App
