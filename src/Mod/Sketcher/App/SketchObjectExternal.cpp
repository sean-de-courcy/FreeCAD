// SPDX-License-Identifier: LGPL-2.1-or-later

/****************************************************************************
 *                                                                          *
 *   Copyright (c) 2008 Jürgen Riegel <juergen.riegel@web.de>               *
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 *   FreeCAD is distributed in the hope that it will be useful, but         *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
 *   Lesser General Public License for more details.                        *
 *                                                                          *
 *   You should have received a copy of the GNU Lesser General Public       *
 *   License along with FreeCAD. If not, see                                *
 *   <https://www.gnu.org/licenses/>.                                       *
 *                                                                          *
 ***************************************************************************/

#include <algorithm>
#include <cmath>
#include <iterator>
#include <limits>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <Mod/Part/App/FCBRepAlgoAPI_Section.h>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepOffsetAPI_NormalProjection.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRep_Tool.hxx>
#include <ElCLib.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <GeomConvert.hxx>
#include <GeomConvert_BSplineCurveKnotSplitting.hxx>
#include <GeomLProp_CLProps.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_Circle.hxx>
#include <Geom_Ellipse.hxx>
#include <Geom_Hyperbola.hxx>
#include <Geom_Line.hxx>
#include <Geom_Parabola.hxx>
#include <Geom_Plane.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <gp_Ax3.hxx>
#include <gp_Circ.hxx>
#include <gp_Elips.hxx>
#include <gp_Hypr.hxx>
#include <gp_Parab.hxx>
#include <gp_Pln.hxx>

#include <boost/algorithm/string/predicate.hpp>

#include <HLRAlgo_Projector.hxx>
#include <HLRBRep_Algo.hxx>
#include <HLRBRep_HLRToShape.hxx>

#include <App/Document.h>
#include <App/ElementNamingUtils.h>
#include <App/Expression.h>
#include <App/ExpressionParser.h>
#include <App/IndexedName.h>
#include <App/MappedName.h>
#include <App/ObjectIdentifier.h>
#include <App/Datums.h>
#include <App/Part.h>
#include <App/RecomputeThread.h>
#include <App/ReferenceReport.h>
#include <Base/Console.h>
#include <Base/Tools.h>
#include <Base/Vector3D.h>
#include <Mod/Part/App/Attacher.h>
#include <Mod/Part/App/BodyBase.h>
#include <Mod/Part/App/DatumFeature.h>

#include <memory>

#include "GeoEnum.h"
#include "SketchObject.h"
#include "ExternalGeometryFacade.h"
#include <Mod/Part/App/Datums.h>


#undef DEBUG
// #define DEBUG

// clang-format off
using namespace Sketcher;
using namespace Base;

FC_LOG_LEVEL_INIT("Sketch", true, true)

namespace
{
// Sets the links to objs/subs, keeping the shadow (the mapped name) of each entry that is one of
// the current links. Without shadows the property resolves each sub again, and a missing one
// (`?Edge3`, kept since ops#72) loses its old mapped name, so the sketch can no longer tell which
// frozen geometry it gave.
void setExternalLinks(App::PropertyLinkSubList& links,
                      std::vector<App::DocumentObject*> objs,
                      std::vector<std::string> subs)
{
    const auto& oldObjs = links.getValues();
    const auto& oldSubs = links.getSubValues();
    const auto& oldShadows = links.getShadowSubs();
    std::vector<bool> used(oldObjs.size(), false);
    std::vector<App::ElementNamePair> shadows;
    shadows.reserve(objs.size());
    for (std::size_t i = 0; i < objs.size(); ++i) {
        shadows.emplace_back();
        for (std::size_t j = 0; j < oldObjs.size() && j < oldShadows.size(); ++j) {
            if (!used[j] && oldObjs[j] == objs[i] && oldSubs[j] == subs[i]) {
                used[j] = true;
                shadows.back() = oldShadows[j];
                break;
            }
        }
    }
    links.setValues(std::move(objs), std::move(subs), std::move(shadows));
}

}  // namespace

// ExternalTypes is parallel to the links by index (ops#140): a path that removes or adds links
// passes the types of the links it keeps, in their order; an entry without one is a projection.
// The types go first, since setting the links can rebuild. Entries waiting for a repair on open
// stay after the links' types.
void SketchObject::setExternalLinksAndTypes(std::vector<App::DocumentObject*> objs,
                                            std::vector<std::string> subs,
                                            std::vector<long> types)
{
    auto pending = pendingTypeRepair();
    types.resize(objs.size(), static_cast<long>(ExtType::Projection));
    types.insert(types.end(), pending.begin(), pending.end());
    Base::StateLocker lock(externalLinksWithTypes, true);
    if (ExternalTypes.getValues() != types) {
        ExternalTypes.setValues(types);
    }
    setExternalLinks(ExternalGeometry, std::move(objs), std::move(subs));
}

std::vector<long> SketchObject::pendingTypeRepair() const
{
    const auto& types = ExternalTypes.getValues();
    const auto count = ExternalGeometry.getValues().size();
    if (!externalTypeRepairPending) {
        return {};
    }
    // FreeCAD-CH (ops#287, PR 277 round 5): a link whose geometry is flagged as built from a
    // guess waits again when it is linked again, also on a list that has lost the mark (the open
    // that repaired it had no link left to wait): the list gets the mark, or the next open would
    // read every link as decided
    if (types.size() <= count) {
        return {pendingTypeRepairMark};
    }
    return {types.begin() + static_cast<std::ptrdiff_t>(count), types.end()};
}

namespace Sketcher
{
// FreeCAD-CH (ops#287, PR 277 round 8): the references whose geometry says their link waits for
// its type (TypeGuessed, TypeUndecided), a link's or a dropped link's. The flags are saved with
// the geometry, so they are what an open or an undo rebuilds the waiting links from, with or
// without the mark in the type list (fork-0.6.1 drops it, and keeps the flags)
std::set<std::string> waitingTypeRefs(const std::vector<Part::Geometry*>& geos)
{
    std::set<std::string> refs;
    for (const auto* geo : geos) {
        auto egf = ExternalGeometryFacade::getFacade(geo);
        if (!egf->getRef().empty()
            && (egf->testFlag(ExternalGeometryExtension::TypeGuessed)
                || egf->testFlag(ExternalGeometryExtension::TypeUndecided))) {
            refs.insert(egf->getRef());
        }
    }
    return refs;
}
}  // namespace Sketcher

void SketchObject::initExternalGeo() {
    std::vector<Part::Geometry *> geos;
    auto HLine = GeometryTypedFacade<Part::GeomLineSegment>::getTypedFacade();
    auto VLine = GeometryTypedFacade<Part::GeomLineSegment>::getTypedFacade();
    HLine->getTypedGeometry()->setPoints(Base::Vector3d(0,0,0),Base::Vector3d(1,0,0));
    VLine->getTypedGeometry()->setPoints(Base::Vector3d(0,0,0),Base::Vector3d(0,1,0));
    HLine->setConstruction(true);
    HLine->setId(-1);
    VLine->setConstruction(true);
    VLine->setId(-2);
    geos.push_back(HLine->getGeometry());
    geos.push_back(VLine->getGeometry());
    HLine->setOwner(false); // we have transferred the ownership to ExternalGeo
    VLine->setOwner(false); // we have transferred the ownership to ExternalGeo
    ExternalGeo.setValues(std::move(geos));
}

// clang-format on
int SketchObject::toggleExternalGeometryFlag(
    const std::vector<int>& geoIds,
    const std::vector<ExternalGeometryExtension::Flag>& flags
)
{
    if (flags.empty()) {
        return 0;
    }
    auto flag = flags.front();

    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    bool update = false;
    bool touched = false;
    auto geos = ExternalGeo.getValues();
    std::set<int> idSet(geoIds.begin(), geoIds.end());
    for (auto geoId : geoIds) {
        if (geoId > GeoEnum::RefExt || -geoId - 1 >= ExternalGeo.getSize()) {
            continue;
        }
        if (!idSet.contains(geoId)) {
            continue;
        }
        idSet.erase(geoId);
        const int idx = -geoId - 1;
        auto& geo = geos[idx];
        const auto egf = ExternalGeometryFacade::getFacade(geo);
        const bool value = !egf->testFlag(flag);
        if (!egf->getRef().empty()) {
            for (auto relatedGeoId : getRelatedGeometry(geoId)) {
                if (relatedGeoId == geoId) {
                    continue;
                }
                int relatedIndex = -relatedGeoId - 1;
                auto& relatedGeometry = geos[relatedIndex];
                relatedGeometry = relatedGeometry->clone();
                auto relatedFacade = ExternalGeometryFacade::getFacade(relatedGeometry);
                for (auto& _flag : flags) {
                    relatedFacade->setFlag(_flag, value);
                }
                idSet.erase(relatedGeoId);
            }
        }
        geo = geo->clone();
        egf->setGeometry(geo);
        for (auto& _flag : flags) {
            egf->setFlag(_flag, value);
        }
        update = update || (value || flag != ExternalGeometryExtension::Frozen);
        touched = true;
    }

    if (!touched) {
        return -1;
    }
    ExternalGeo.setValues(geos);
    if (update) {
        rebuildExternalGeometry();
    }
    return 0;
}

namespace
{
bool isIdentityFrame(const Base::Placement& frame)
{
    return frame.isIdentity(Precision::Confusion());
}
}  // namespace

// What a link reads is in its source's container: a feature's shape and a datum's placement in the
// group holding it, an element of a coordinate system with that system's placement applied
// (DatumElement::getBasePoint, getDirection), so in the system's container. Mapped into this
// sketch's container as an attachment's links are (ops#318, Attacher::linkFrame); before, it was
// read as if it were there (ops#331: another Body's edge left behind when that Body moved;
// ops#324: a sketch outside any Body). Within one container: the identity.
Base::Placement SketchObject::externalFrame(const App::DocumentObject* obj,
                                            const std::string& sub) const
{
    if (!obj) {
        return {};
    }
    if (auto lcs = dynamic_cast<const App::LocalCoordinateSystem*>(obj); lcs && !sub.empty()) {
        if (auto element = lcs->getDatumElement(sub.c_str())) {
            obj = element;
        }
    }
    if (auto element = dynamic_cast<const App::DatumElement*>(obj)) {
        if (auto lcs = element->getLCS()) {
            obj = lcs;
        }
    }
    return Attacher::AttachEngine::linkFrame(this, obj);
}

std::vector<Base::Placement> SketchObject::externalFrames() const
{
    const auto& objs = ExternalGeometry.getValues();
    const auto& subs = ExternalGeometry.getSubValues();
    std::vector<Base::Placement> frames;
    frames.reserve(objs.size());
    bool across = false;
    for (std::size_t i = 0; i < objs.size(); ++i) {
        frames.push_back(externalFrame(objs[i], i < subs.size() ? subs[i] : std::string()));
        across = across || !isIdentityFrame(frames.back());
    }
    if (!across) {
        frames.clear();
    }
    return frames;
}

bool SketchObject::externalFramesChanged(bool restored) const
{
    if (ExternalGeometry.getSize() == 0 && ExternalFrames.getSize() == 0) {
        return false;
    }
    // While it recomputes its geometry is built anew. Asked beside a recompute on another thread
    // (the GUI's poll while the worker recomputes): the walk would read in-lists and groups the
    // recompute changes; the recompute asks again itself, on its own thread (as
    // AttachExtension::linkFramesChanged)
    auto doc = getDocument();
    if (!restored
        && (isRecomputing() || !doc || doc->testStatus(App::Document::Restoring)
            || (doc->testStatus(App::Document::Recomputing)
                && !App::isRecomputingOnThisThread(doc)))) {
        return false;
    }
    auto differ = [this] {
        const auto current = externalFrames();
        const auto& built = ExternalFrames.getValues();
        if (current.size() != built.size()) {
            return true;
        }
        for (std::size_t i = 0; i < current.size(); ++i) {
            if (!current[i].isSame(built[i], Precision::Confusion())) {
                return true;
            }
        }
        return false;
    };
    // Asked from onDocumentRestored(), by a recompute running on this thread for any document, or
    // by the worker (its single-object recompute sets no status): its own question
    if (restored || App::isRecomputingOnThisThread() || App::isRecomputeWorkerThread()) {
        return differ();
    }
    // Otherwise (the GUI's Refresh poll), walk only while the async worker recomputes nothing, in
    // no document, and hold it off meanwhile: the status above is read once, set late, not set
    // for a single object, and only this document's (ops#352, as ops#337's attachment poll)
    bool changed = false;
    if (!App::runWhileRecomputeWorkerIdle([&] { changed = differ(); })) {
        return false;
    }
    return changed;
}
// clang-format off

bool SketchObject::isExternalAllowed(App::Document* pDoc, App::DocumentObject* pObj,
                                     eReasonList* rsn) const
{
    if (rsn)
        *rsn = rlAllowed;

    // Externals outside of the Document are NOT allowed
    if (this->getDocument() != pDoc) {
        if (rsn)
            *rsn = rlOtherDoc;
        return false;
    }

    // circular reference prevention
    try {
        if (!(this->testIfLinkDAGCompatible(pObj))) {
            if (rsn)
                *rsn = rlCircularReference;
            return false;
        }
    }
    catch (Base::Exception& e) {
        Base::Console().warning(
            "Probably, there is a circular reference in the document. Error: %s\n", e.what());
        return true;// prohibiting this reference won't remove the problem anyway...
    }


    // Note: Checking for the body of the support doesn't work when the support are the three base
    // planes
    Part::BodyBase* body_this = Part::BodyBase::findBodyOf(this);
    Part::BodyBase* body_obj = Part::BodyBase::findBodyOf(pObj);

    // DatumElements in an LCS, get body from the parent LCS
    if (!body_obj && pObj->isDerivedFrom<App::DatumElement>()) {
        auto* datum = static_cast<const App::DatumElement*>(pObj);
        if (auto* lcs = datum->getLCS()) {
            body_obj = Part::BodyBase::findBodyOf(lcs);
        }
    }

    App::Part* part_this = App::Part::getPartOfObject(this);
    App::Part* part_obj = App::Part::getPartOfObject(pObj);
    if (part_this == part_obj) {// either in the same part, or in the root of document
        if (!body_this) {
            return true;
        }
        else if (body_this == body_obj) {
            return true;
        }
        // FreeCAD-CH (ops#325): another Body of the same studio, at one origin
        else if (Part::BodyBase::isInOneStudio(this, pObj)) {
            return true;
        }
        else {
            if (rsn)
                *rsn = rlOtherBody;
            return false;
        }
    }
    else {
        // cross-part link. Disallow, should be done via shapebinders only
        if (rsn)
            *rsn = rlOtherPart;
        return false;
    }
}

bool SketchObject::isCarbonCopyAllowed(App::Document* pDoc, App::DocumentObject* pObj, bool& xinv,
                                       bool& yinv, eReasonList* rsn) const
{
    auto setReason = [&rsn](eReasonList reasonFromList) {
        if (rsn)
            *rsn = reasonFromList;
    };

    setReason(rlAllowed);

    std::string sketchArchType ("Sketcher::SketchObjectPython");

    // Only applicable to sketches
    if (!pObj->is<Sketcher::SketchObject>()
        && sketchArchType != pObj->getTypeId().getName()) {
        setReason(rlNotASketch);
        return false;
    }


    auto* psObj = static_cast<SketchObject*>(pObj);

    // Sketches outside of the Document are NOT allowed
    if (this->getDocument() != pDoc) {
        setReason(rlOtherDoc);
        return false;
    }

    // circular reference prevention
    try {
        if (!(this->testIfLinkDAGCompatible(pObj))) {
            setReason(rlCircularReference);
            return false;
        }
    }
    catch (Base::Exception& e) {
        Base::Console().warning(
            "Probably, there is a circular reference in the document. Error: %s\n", e.what());
        return true;// prohibiting this reference won't remove the problem anyway...
    }


    // Note: Checking for the body of the support doesn't work when the support are the three base
    // planes
    Part::BodyBase* body_this = Part::BodyBase::findBodyOf(this);
    Part::BodyBase* body_obj = Part::BodyBase::findBodyOf(pObj);
    App::Part* part_this = App::Part::getPartOfObject(this);
    App::Part* part_obj = App::Part::getPartOfObject(pObj);
    if (part_this != part_obj) {
        // cross-part relation. Disallow, should be done via shapebinders only
        setReason(rlOtherPart);
        return false;
    }

    // Hereafter assuming: either in the same part, or in the root of document. FreeCAD-CH
    // (ops#325): another Body of the same studio is like this one
    if (body_this && body_this != body_obj && !Part::BodyBase::isInOneStudio(this, pObj)) {
        if (!this->allowOtherBody) {
            setReason(rlOtherBody);
            return false;
        }
        // if the original sketch has external geometry AND it is not in this body prevent
        // link
        else if (psObj->getExternalGeometryCount() > 2) {
            setReason(rlOtherBodyWithLinks);
            return false;
        }
    }

    const Rotation& srot = psObj->Placement.getValue().getRotation();
    const Rotation& lrot = this->Placement.getValue().getRotation();

    Base::Vector3d snormal(0, 0, 1);
    Base::Vector3d sx(1, 0, 0);
    Base::Vector3d sy(0, 1, 0);
    srot.multVec(snormal, snormal);
    srot.multVec(sx, sx);
    srot.multVec(sy, sy);

    Base::Vector3d lnormal(0, 0, 1);
    Base::Vector3d lx(1, 0, 0);
    Base::Vector3d ly(0, 1, 0);
    lrot.multVec(lnormal, lnormal);
    lrot.multVec(lx, lx);
    lrot.multVec(ly, ly);

    double dot = snormal * lnormal;
    double dotx = sx * lx;
    double doty = sy * ly;

    // the planes of the sketches must be parallel
    if (!allowUnaligned && fabs(fabs(dot) - 1) > Precision::Confusion()) {
        setReason(rlNonParallel);
        return false;
    }

    // the axis must be aligned
    if (!allowUnaligned
        && ((fabs(fabs(dotx) - 1) > Precision::Confusion())
            || (fabs(fabs(doty) - 1) > Precision::Confusion()))) {
        setReason(rlAxesMisaligned);
        return false;
    }


    // the origins of the sketches must be aligned or be the same
    Base::Vector3d ddir =
        (psObj->Placement.getValue().getPosition() - this->Placement.getValue().getPosition())
            .Normalize();

    double alignment = ddir * lnormal;

    if (!allowUnaligned && (fabs(fabs(alignment) - 1) > Precision::Confusion())
        && (psObj->Placement.getValue().getPosition()
            != this->Placement.getValue().getPosition())) {
        setReason(rlOriginsMisaligned);
        return false;
    }

    xinv = allowUnaligned ? false : (fabs(dotx - 1) > Precision::Confusion());
    yinv = allowUnaligned ? false : (fabs(doty - 1) > Precision::Confusion());

    return true;
}

// clang-format on
int SketchObject::carbonCopy(App::DocumentObject* pObj, bool construction)
{
    using std::numbers::pi;

    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    // so far only externals to the support of the sketch and datum features
    bool xinv = false, yinv = false;

    if (!isCarbonCopyAllowed(pObj->getDocument(), pObj, xinv, yinv)) {
        return -1;
    }

    auto* psObj = static_cast<SketchObject*>(pObj);

    // FreeCAD-CH (ops#237, PR 218 review): a constraint list flagged invalid (indices beyond the
    // geometry, or geometry it wasn't checked against) reads as empty. Copied from, the copy got
    // no constraints; copied into, the write below replaced this sketch's own with the source's
    // alone. Both silently: refuse instead, before anything changes
    for (SketchObject* sketch : {this, psObj}) {
        // checked against the geometry as it is now: the flag can be stale (PR 262 review)
        sketch->Constraints.checkConstraintIndices(sketch->getHighestCurveIndex(),
                                                   -sketch->getExternalGeometryCount());
        // (an empty list is flagged too, in a sketch that hasn't had geometry or a recompute
        // yet: nothing to lose)
        if (&sketch->Constraints.getValues() != &sketch->Constraints.getValuesForce()
            && !sketch->Constraints.getValuesForce().empty()) {
            Base::Console().error(
                "Carbon copy of '%s' into '%s' refused: the constraints of '%s' are flagged "
                "invalid (they don't match its geometry). Repair that sketch first.\n",
                psObj->Label.getValue(),
                this->Label.getValue(),
                sketch->Label.getValue()
            );
            return -1;
        }
    }

    // FreeCAD-CH (ops#237, PR 262 review M1): a source link whose type an open couldn't tell (its
    // repair pending) holds the type at its index, a guess. Copied, the guess became the copy's
    // settled type, with no mark and nothing left to repair or warn: refuse instead, naming it
    if (psObj->externalTypeRepairPending) {
        for (const auto& key : psObj->externalGeoRef) {
            if (psObj->undecidedTypeKeys.count(key) != 0) {
                Base::Console().error(
                    "Carbon copy of '%s' into '%s' refused: the type of its external link %s "
                    "couldn't be told when the file was opened (a type list saved before ops#140), "
                    "so it holds a guess. Delete the link and add it again with the type it "
                    "should have, first.\n",
                    psObj->Label.getValue(),
                    this->Label.getValue(),
                    key.c_str()
                );
                return -1;
            }
        }
    }

    // FreeCAD-CH (ops#252): a source link this sketch has already refuses the copy before
    // anything changes. It was checked after the source's external geometries were written to
    // ExternalGeo, which the refusal left there without their links
    {
        const auto& objects = ExternalGeometry.getValues();
        const auto& subs = ExternalGeometry.getSubValues();
        const auto& sObjects = psObj->ExternalGeometry.getValues();
        const auto& sSubs = psObj->ExternalGeometry.getSubValues();
        if (objects.size() != subs.size() || sObjects.size() != sSubs.size()) {
            assert(0 /*counts of objects and subelements in external geometry links do not match*/);
            Base::Console().error(
                "Internal error: counts of objects and subelements in external "
                "geometry links do not match\n"
            );
            return -1;
        }
        for (size_t si = 0; si < sObjects.size(); ++si) {
            for (size_t i = 0; i < objects.size(); ++i) {
                if (objects[i] == sObjects[si] && subs[i] == sSubs[si]) {
                    Base::Console().error(
                        "Link to %s already exists in this sketch. Delete the link and try again\n",
                        sSubs[si].c_str()
                    );
                    return -1;
                }
            }
        }
    }

    // FreeCAD-CH (ops#280): an unaligned copy isn't flipped (xinv and yinv stay false), but a
    // source whose plane faces the other way still sees this sketch's own geometry mirrored
    const bool reversed = !xinv && !yinv
        && psObj->Placement.getValue().getRotation().multVec(Base::Vector3d::UnitZ)
                * this->Placement.getValue().getRotation().multVec(Base::Vector3d::UnitZ)
            < 0;

    const std::vector<Part::Geometry*>& vals = getInternalGeometry();

    const std::vector<Sketcher::Constraint*>& cvals = Constraints.getValues();

    std::vector<Part::Geometry*> newVals(vals);

    std::vector<Constraint*> newcVals(cvals);

    int nextgeoid = vals.size();

    int nextextgeoid = getExternalGeometryCount();

    const std::vector<Part::Geometry*>& svals = psObj->getInternalGeometry();

    const std::vector<Sketcher::Constraint*>& scvals = psObj->Constraints.getValues();

    newVals.reserve(vals.size() + svals.size());
    newcVals.reserve(cvals.size() + scvals.size());

    // FreeCAD-CH (ops#283): the geometry is in this sketch's own frame, so the flip mirrors about
    // its own axes there: x flips about the Y axis, y about the X axis. Before, it mirrored about
    // this sketch's position and axes in the global frame, which shifted the copy (and with this
    // sketch turned, flipped the other coordinate)
    auto applyGeometryFlipCorrection = [xinv, yinv](Part::Geometry* geoNew) {
        if (xinv) {
            geoNew->mirror(Base::Vector3d(), Base::Vector3d::UnitY);
        }
        if (yinv) {
            geoNew->mirror(Base::Vector3d(), Base::Vector3d::UnitX);
        }
    };

    std::map<int, int> extMap;
    // for a source external that copies this sketch's own geometry: the element its ref names
    // (a vertex is a point of an edge, ops#267 PR 250 review L1)
    std::map<int, std::pair<std::string, PointPos>> selfRefs;
    if (psObj->ExternalGeo.getSize() > 1) {
        int i = -1;
        auto geos = this->ExternalGeo.getValues();
        std::string myName(this->getNameInDocument());
        myName += ".";
        for (const auto& geo : psObj->ExternalGeo.getValues()) {
            if (++i < 2) {  // skip h/v axes
                continue;
            }
            else {
                auto egf = ExternalGeometryFacade::getFacade(geo);
                const auto& ref = egf->getRef();
                if (boost::starts_with(ref, myName)) {
                    int geoId;
                    PointPos posId;
                    if (this->geoIdFromShapeType(ref.c_str() + myName.size(), geoId, posId)) {
                        extMap[-i - 1] = geoId;
                        selfRefs[-i - 1] = {ref.substr(myName.size()), posId};
                        continue;
                    }
                }
            }
            auto copy = geo->copy();
            // FreeCAD-CH (PR 254 review F2): the rebuild projects a linked external here again,
            // but keeps a frozen one, one whose source is missing and one whose projection fails
            // as copied: in the source's frame, so flipped like the internal geometry
            applyGeometryFlipCorrection(copy);
            auto egf = ExternalGeometryFacade::getFacade(copy);
            egf->setId(++geoLastId);
            if (!egf->getRef().empty()) {
                auto& refs = this->externalGeoRefMap[egf->getRef()];
                refs.push_back(geoLastId);
            }
            this->externalGeoMap[geoLastId] = (int)geos.size();
            geos.push_back(copy);
            extMap[-i - 1] = -(int)geos.size();
        }
        Base::ObjectStatusLocker<App::Property::Status, App::Property> guard(
            App::Property::User3,
            &this->ExternalGeo
        );
        this->ExternalGeo.setValues(std::move(geos));
    }

    if (psObj->ExternalGeometry.getSize() > 0) {
        std::vector<DocumentObject*> Objects = ExternalGeometry.getValues();
        std::vector<std::string> SubElements = ExternalGeometry.getSubValues();

        const std::vector<DocumentObject*> originalObjects = Objects;
        const std::vector<std::string> originalSubElements = SubElements;
        const std::vector<long> originalTypes = ExternalTypes.getValues();
        std::vector<long> Types = originalTypes;
        Types.resize(Objects.size(), static_cast<long>(ExtType::Projection));

        std::vector<DocumentObject*> sObjects = psObj->ExternalGeometry.getValues();
        std::vector<std::string> sSubElements = psObj->ExternalGeometry.getSubValues();

        // (the counts and the duplicate links were checked above, before anything changed)
        int si = 0;
        for (auto& sobj : sObjects) {
            Objects.push_back(sobj);
            SubElements.push_back(sSubElements[si]);
            // the copied link keeps its type
            Types.push_back(psObj->externalType(si));

            si++;
        }

        setExternalLinksAndTypes(Objects, SubElements, Types);

        try {
            rebuildExternalGeometry();
        }
        catch (const Base::Exception& e) {
            Base::Console().error("%s\n", e.what());
            // revert to original values
            setExternalLinksAndTypes(originalObjects, originalSubElements, originalTypes);
            return -1;
        }

        solverNeedsUpdate = true;
    }

    for (const auto& geoOld : svals) {
        Part::Geometry* geoNew = geoOld->copy();
        if (xinv || yinv) {
            // corrections for flipped geometry
            applyGeometryFlipCorrection(geoNew);
        }
        generateId(geoNew);
        if (construction && !geoNew->is<Part::GeomPoint>()) {
            GeometryFacade::setConstruction(geoNew, true);
        }
        newVals.push_back(geoNew);
    }

    // FreeCAD-CH (ops#281): flipped back, each geometry's direction (the way its tangent runs,
    // which an angle at a point is measured by) is the image of the source's, or that turned
    // half a turn. One flip is a mirror: a line keeps its start and a B-spline its direction,
    // but a conic runs the other way (a sketch's conics run counterclockwise), and an arc's
    // ends swap. Two flips are a half turn, which keeps every geometry's ends and direction.
    // The axes are this sketch's own: the horizontal one runs the other way when x flips, the
    // vertical one when y flips.
    const bool mirrored = xinv != yinv;
    // FreeCAD-CH (ops#283): a copied external is projected here again, and which way a projection
    // runs can depend on the plane's normal (a circle seen edge-on becomes a line along the
    // normal ^ its axis, which runs the other way in a mirrored copy). So whether its ends are
    // the images of the source's or swapped is read from the two; when neither, its constraints
    // aren't copied. One without ends (a point, a whole conic) goes by its type. So does a source
    // external that names an edge of this sketch, whose copy is that edge itself (PR 253
    // verification finding 4: a stale one, or an arc in a mirrored copy)
    enum class Ends
    {
        Kept,
        Swapped,
        Unknown
    };
    std::map<int, Ends> externalEnds;  // by source GeoId
    if (xinv || yinv) {
        using EndPoints = std::pair<Base::Vector3d, Base::Vector3d>;
        auto endsOf = [](const Part::Geometry* geo) -> std::optional<EndPoints> {
            if (auto arc = dynamic_cast<const Part::GeomArcOfConic*>(geo)) {
                // as the solver reads them (Sketch::addArc)
                return EndPoints {arc->getStartPoint(true), arc->getEndPoint(true)};
            }
            if (auto curve = dynamic_cast<const Part::GeomBoundedCurve*>(geo)) {
                return EndPoints {curve->getStartPoint(), curve->getEndPoint()};
            }
            return std::nullopt;
        };
        // how far `here` is from where this sketch sees the source's `seen`
        auto offBy = [xinv, yinv](const Base::Vector3d& here, const Base::Vector3d& seen) {
            const double x = xinv ? -seen.x : seen.x;
            const double y = yinv ? -seen.y : seen.y;
            return std::hypot(here.x - x, here.y - y);
        };
        // FreeCAD-CH (ops#283 F3): isCarbonCopyAllowed lets the two frames be off by a small
        // angle (up to about 4.5e-4 rad), and then a point a distance r away is seen off by
        // about that angle times r. So the tolerance scales with the frames' actual angle and
        // the size of what is compared; exactly parallel frames keep 1e-6
        const Base::Rotation& srot = psObj->Placement.getValue().getRotation();
        const Base::Rotation& lrot = this->Placement.getValue().getRotation();
        double tilt = 0;  // the sine of the largest angle between an axis and its counterpart
        for (const auto& axis :
             {Base::Vector3d::UnitX, Base::Vector3d::UnitY, Base::Vector3d::UnitZ}) {
            tilt = std::max(tilt, (srot.multVec(axis) % lrot.multVec(axis)).Length());
        }
        const double apart =
            (psObj->Placement.getValue().getPosition() - this->Placement.getValue().getPosition())
                .Length();
        // the size compared: the farthest point from the origin, or the sketches' distance. A
        // projected point far below the planes can be seen off by more: refused, not guessed
        // (PR 260 review L3)
        auto toleranceFor = [&](std::initializer_list<Base::Vector3d> points) {
            double scale = apart;
            for (const auto& point : points) {
                scale = std::max(scale, std::hypot(point.x, point.y));
            }
            return std::max(1e-6, 4 * tilt * scale);
        };
        // an arc's point half way along its parameters: its ends alone don't tell it from the
        // rest of its circle drawn the other way round (PR 260 review L2)
        auto middleOf = [](const Part::Geometry* geo) -> std::optional<Base::Vector3d> {
            if (auto arc = dynamic_cast<const Part::GeomArcOfConic*>(geo)) {
                return arc->pointAtParameter(
                    (arc->getFirstParameter() + arc->getLastParameter()) / 2);
            }
            return std::nullopt;
        };
        // a circle's or an ellipse's (major, minor) radii: a circle seen from a slightly tilted
        // source is an ellipse
        auto radiiOf = [](const Part::Geometry* geo) -> std::optional<std::pair<double, double>> {
            if (auto circle = dynamic_cast<const Part::GeomCircle*>(geo)) {
                return std::pair {circle->getRadius(), circle->getRadius()};
            }
            if (auto ellipse = dynamic_cast<const Part::GeomEllipse*>(geo)) {
                return std::pair {ellipse->getMajorRadius(), ellipse->getMinorRadius()};
            }
            return std::nullopt;
        };
        // whether a whole conic here is the image of the source's: centre, radii and, for one
        // that isn't round, the major axis (PR 260 review L1 and verification L1: a stale
        // self-reference to a circle or ellipse). Self-references to edges only get here (a
        // point is a vertex)
        auto sameShape = [&](const Part::Geometry* here, const Part::Geometry* seen) {
            auto conic = dynamic_cast<const Part::GeomConic*>(here);
            auto seenConic = dynamic_cast<const Part::GeomConic*>(seen);
            if (!conic || !seenConic) {
                return false;
            }
            const auto centre = conic->getCenter();
            const auto other = seenConic->getCenter();
            const auto radii = radiiOf(here);
            const auto seenRadii = radiiOf(seen);
            const double tolerance = toleranceFor(
                {centre, other, Base::Vector3d(radii ? radii->first : 0, 0, 0)});
            if (offBy(centre, other) > tolerance) {
                return false;
            }
            if (!radii || !seenRadii) {
                return here->getTypeId() == seen->getTypeId();  // another conic: its centre
            }
            if (std::abs(radii->first - seenRadii->first) > tolerance
                || std::abs(radii->second - seenRadii->second) > tolerance) {
                return false;
            }
            if (radii->first - radii->second <= tolerance) {
                return true;  // round: no axis to compare
            }
            auto ellipse = dynamic_cast<const Part::GeomEllipse*>(here);
            auto seenEllipse = dynamic_cast<const Part::GeomEllipse*>(seen);
            if (!ellipse || !seenEllipse) {
                return true;  // one is a circle, and the radii match: round within the tolerance
            }
            auto axis = ellipse->getMajorAxisDir();
            auto seenAxis = seenEllipse->getMajorAxisDir();
            seenAxis.x = xinv ? -seenAxis.x : seenAxis.x;
            seenAxis.y = yinv ? -seenAxis.y : seenAxis.y;
            const double sine = std::abs(axis.x * seenAxis.y - axis.y * seenAxis.x)
                / std::max(1e-12, std::hypot(axis.x, axis.y) * std::hypot(seenAxis.x, seenAxis.y));
            return sine * radii->first <= tolerance;
        };
        for (const auto& [sourceId, id] : extMap) {
            const Part::Geometry* copied = nullptr;
            if (id < 0) {
                copied = this->getGeometry(id);
            }
            else if (selfRefs.at(sourceId).second == PointPos::none
                     && id < static_cast<int>(vals.size())) {
                // a source external that names this sketch's edge: its copy is that edge
                copied = vals[id];
            }
            else {
                continue;  // a vertex of this sketch (a point), or an edge it doesn't have
            }
            const Part::Geometry* source = psObj->getGeometry(sourceId);
            const auto seen = endsOf(source);
            const auto here = endsOf(copied);
            if (!seen && !here) {
                // a whole conic goes by its type. One of this sketch's own must still be what
                // the source saw (a copied external was projected again, so it is)
                if (id >= 0 && !sameShape(copied, source)) {
                    externalEnds[sourceId] = Ends::Unknown;
                }
                continue;
            }
            Ends ends = Ends::Unknown;
            if (seen && here) {
                // the clearly nearer pairing: one within half the tolerance, the other beyond it
                // (PR 260 review nit 6). A closed curve, or one shorter than the tolerance, has
                // neither: refused, never guessed. The whole edge is compared, even for a
                // constraint on an end that didn't move (PR 260 review L5)
                const double kept =
                    std::max(offBy(here->first, seen->first), offBy(here->second, seen->second));
                const double swapped =
                    std::max(offBy(here->first, seen->second), offBy(here->second, seen->first));
                const auto hereMiddle = middleOf(copied);
                const auto seenMiddle = middleOf(source);
                const double tolerance = toleranceFor(
                    {here->first,
                     here->second,
                     seen->first,
                     seen->second,
                     hereMiddle.value_or(Base::Vector3d()),
                     seenMiddle.value_or(Base::Vector3d())});
                if (kept <= tolerance / 2 && swapped > tolerance) {
                    ends = Ends::Kept;
                }
                else if (swapped <= tolerance / 2 && kept > tolerance) {
                    ends = Ends::Swapped;
                }
                // an arc: the same middle, so not the rest of its circle
                if (ends != Ends::Unknown && (hereMiddle || seenMiddle)
                    && !(hereMiddle && seenMiddle
                         && offBy(*hereMiddle, *seenMiddle) <= tolerance / 2)) {
                    ends = Ends::Unknown;
                }
            }
            externalEnds[sourceId] = ends;
        }
    }
    auto copiedEnds = [&](int geoId) -> std::optional<Ends> {
        auto found = externalEnds.find(geoId);
        if (found == externalEnds.end()) {
            return std::nullopt;
        }
        return found->second;
    };

    auto turnsRound = [&](int geoId) {  // a source GeoId
        if (geoId == GeoEnum::HAxis) {
            return xinv;
        }
        if (geoId == GeoEnum::VAxis) {
            return yinv;
        }
        if (auto ends = copiedEnds(geoId)) {
            return *ends == Ends::Swapped;
        }
        if (!mirrored || geoId == GeoEnum::GeoUndef) {
            return false;
        }
        const Part::Geometry* geo = psObj->getGeometry(geoId);
        return geo
            && (geo->isDerivedFrom<Part::GeomConic>()
                || geo->isDerivedFrom<Part::GeomArcOfConic>());
    };
    auto swapsEnds = [&](int geoId) {  // a source GeoId
        if (auto ends = copiedEnds(geoId)) {
            return *ends == Ends::Swapped;
        }
        if (!mirrored || geoId == GeoEnum::GeoUndef) {
            return false;
        }
        const Part::Geometry* geo = psObj->getGeometry(geoId);
        return geo && geo->isDerivedFrom<Part::GeomArcOfConic>();
    };

    // how the flip changes the angle a source constraint's value is: negated, and turned half a
    // turn; none for one that it leaves alone
    struct AngleFlip
    {
        bool negated;
        bool halfTurn;
    };
    auto angleFlip = [&](const Sketcher::Constraint* constr) -> std::optional<AngleFlip> {
        if (!xinv && !yinv) {
            return std::nullopt;
        }
        if (constr->Type == Sketcher::Angle) {
            if (constr->Second == GeoEnum::GeoUndef) {
                const Part::Geometry* geo = psObj->getGeometry(constr->First);
                if (!geo || !geo->is<Part::GeomLineSegment>()) {
                    // an arc's sweep: the same, however the arc turns
                    return std::nullopt;
                }
                // a line's direction, from the horizontal axis
                const bool halfTurn = turnsRound(constr->First) != turnsRound(GeoEnum::HAxis);
                return AngleFlip {mirrored, halfTurn};
            }
            // from the first's direction to the second's (at a point, or of two lines)
            return AngleFlip {mirrored, turnsRound(constr->First) != turnsRound(constr->Second)};
        }
        if ((constr->Type == Sketcher::Tangent || constr->Type == Sketcher::Perpendicular)
            && constr->getValue() != 0.0) {
            // a locked tangency or perpendicularity: the angle between the two at a point, a
            // tangency's offset by -90 degrees, which adds a half turn when it is negated
            // (AutoLockTangencyAndPerpty)
            const bool halfTurn = turnsRound(constr->First) != turnsRound(constr->Second);
            const bool offset = mirrored && constr->Type == Sketcher::Tangent;
            return AngleFlip {mirrored, halfTurn != offset};
        }
        return std::nullopt;
    };

    auto applyConstraintFlipCorrection = [&](const Sketcher::Constraint* constr,
                                             Sketcher::Constraint* newConstr) {
        if (!xinv && !yinv) {
            return;
        }

        // DistanceX, DistanceY
        if ((xinv && newConstr->Type == Sketcher::DistanceX)
            || (yinv && newConstr->Type == Sketcher::DistanceY)) {
            if (newConstr->First == newConstr->Second) {
                std::swap(newConstr->FirstPos, newConstr->SecondPos);
            }
            else {
                newConstr->setValue(-newConstr->getValue());
            }
        }

        // Angle, and a locked Tangent or Perpendicular
        if (auto flip = angleFlip(constr)) {
            double angle = newConstr->getValue();
            if (flip->negated) {
                angle = -angle;
            }
            if (flip->halfTurn) {
                angle += pi;
            }
            while (angle > pi) {
                angle -= pi * 2.0;
            }
            while (angle <= -pi) {
                angle += pi * 2.0;
            }
            if (newConstr->Type == Sketcher::Perpendicular && angle < 0) {
                // 90 or 270 degrees, as AutoLockTangencyAndPerpty writes it
                angle += pi * 2.0;
            }
            newConstr->setValue(angle);
        }
    };

    // each source constraint's index here, -1 for one that isn't copied
    std::vector<int> copiedIndex;
    copiedIndex.reserve(scvals.size());
    for (const auto& constr : scvals) {
        std::unique_ptr<Sketcher::Constraint> newConstr(constr->copy());
        const int number = static_cast<int>(&constr - scvals.data()) + 1;
        std::string refused;  // why the constraint isn't copied
        // FreeCAD-CH (ops#247): every element, not only First/Second/Third: a Group or a Text
        // holds more, and the later ones kept the source's GeoIds, naming other geometry here
        for (size_t i = 0; i < newConstr->getElementsSize() && refused.empty(); ++i) {
            const int geoId = constr->getGeoId(i);
            const PointPos pos = constr->getPosId(i);
            if ((pos == PointPos::start || pos == PointPos::end) && swapsEnds(geoId)) {
                // FreeCAD-CH (ops#281): a mirrored arc's start is the image of the source's end
                newConstr->setPosId(i, pos == PointPos::start ? PointPos::end : PointPos::start);
            }
            if (geoId >= 0) {
                newConstr->setGeoId(i, geoId + nextgeoid);
            }
            else if (geoId < -2 && geoId != GeoEnum::GeoUndef) {
                // FreeCAD-CH (ops#267): through extMap, not a linear shift: a source external that
                // copies this sketch's own edge isn't appended, so the ones after it move up
                auto mapped = extMap.find(geoId);
                if (mapped == extMap.end()) {
                    newConstr->setGeoId(i, geoId - (nextextgeoid - 2));
                    continue;
                }
                if (copiedEnds(geoId) == Ends::Unknown) {
                    const auto self = selfRefs.find(geoId);
                    const std::string copy = self == selfRefs.end()
                        ? "its copy here"
                        : "'" + std::string(this->Label.getValue()) + "' "
                            + self->second.first + ", which it copies";
                    refused = "it is on its ExternalEdge"
                        + std::to_string(GeoEnum::RefExt + 1 - geoId) + ", which doesn't match "
                        + copy + " (its ends, its middle or its size), and the copy is flipped "
                          "here";
                    break;
                }
                if (mapped->second >= 0) {
                    const auto& [element, posId] = selfRefs.at(geoId);
                    const std::string external = "ExternalEdge"
                        + std::to_string(GeoEnum::RefExt + 1 - geoId) + ", a copy of '"
                        + this->Label.getValue() + "' " + element;
                    if (mapped->second >= static_cast<int>(vals.size())) {
                        // FreeCAD-CH (PR 253 review M2): an orphaned ref (e.g. Edge9 of a
                        // sketch with three edges) names no geometry here
                        refused = "it is on " + external + ", which '" + this->Label.getValue()
                            + "' doesn't have";
                        break;
                    }
                    if (reversed) {
                        // the source sees this sketch's geometry mirrored and the copy isn't
                        // flipped back: neither the points nor the values carry over
                        refused = "it is on " + external
                            + ", which the source sees mirrored (its plane faces the other way), "
                              "and the copy isn't flipped back here";
                        break;
                    }
                    // flipped back, an edge's ends and the way it runs were read from the
                    // source's external of it (externalEnds), so the ends swap and the angles are
                    // corrected as for a copied external (PR 253 review M1, verification finding
                    // 4); a vertex is a point
                    if (posId != PointPos::none) {
                        // a vertex: the source's external is a point, named by its start; here
                        // it is that point of the edge
                        if (constr->getPosId(i) != PointPos::start) {
                            refused = "it is on " + external + " other than by its point";
                            break;
                        }
                        newConstr->setPosId(i, posId);
                    }
                    const std::string own = (posId != PointPos::none ? "vertex of Edge" : "Edge")
                        + std::to_string(mapped->second + 1);
                    Base::Console().warning(
                        "Constraint %d of '%s' is on %s: its copy here is on that %s itself.\n",
                        number,
                        psObj->Label.getValue(),
                        external.c_str(),
                        own.c_str()
                    );
                }
                newConstr->setGeoId(i, mapped->second);
            }
        }
        if (!refused.empty()) {
            Base::Console().warning(
                "Constraint %d of '%s' isn't copied to '%s': %s.\n",
                number,
                psObj->Label.getValue(),
                this->Label.getValue(),
                refused.c_str()
            );
            copiedIndex.push_back(-1);
            continue;
        }

        if (xinv || yinv) {
            // corrections for flipped constraints
            applyConstraintFlipCorrection(constr, newConstr.get());
        }

        copiedIndex.push_back(static_cast<int>(newcVals.size()));
        newcVals.push_back(newConstr.release());
    }

    // Block acceptGeometry in OnChanged to avoid unnecessary checks and updates
    {
        Base::StateLocker preventUpdate(internaltransaction, true);
        Geometry.setValues(std::move(newVals));
        this->Constraints.setValues(std::move(newcVals));
    }
    // we trigger now the update (before dealing with expressions)
    // Update geometry indices and rebuild vertexindex now via onChanged, so that
    // ViewProvider::UpdateData is triggered.
    Geometry.touch();

    auto makeCorrectedExpressionString =
        [&](const Sketcher::Constraint* constr, const std::string expr) -> std::string {
        if (!xinv && !yinv) {
            return expr;
        }

        // DistanceX, DistanceY
        if ((xinv && constr->Type == Sketcher::DistanceX)
            || (yinv && constr->Type == Sketcher::DistanceY)) {
            if (constr->First == constr->Second) {
                return expr;
            }
            else {
                return "-(" + expr + ")";
            }
        }

        // Angle, as applyConstraintFlipCorrection changes its value (ops#281)
        if (constr->Type == Sketcher::Angle) {
            auto flip = angleFlip(constr);
            if (!flip) {
                return expr;
            }
            if (flip->negated) {
                return flip->halfTurn ? "180 deg - (" + expr + ")" : "-(" + expr + ")";
            }
            return flip->halfTurn ? "(" + expr + ") + 180 deg" : expr;
        }
        return expr;
    };

    int sourceid = 0;
    for (auto it = scvals.cbegin(); it != scvals.cend(); ++it, ++sourceid) {
        // a constraint that isn't copied leaves no gap: the ones after it moved up
        const int copied = copiedIndex[sourceid];
        if (copied < 0 || !((*it)->isDimensional() && (*it)->isDriving)) {
            continue;
        }

        App::ObjectIdentifier spath;
        std::shared_ptr<App::Expression> expr;
        std::string scname = (*it)->Name;
        std::string sref;
        if (App::ExpressionParser::isTokenAnIndentifier(scname)) {
            spath = App::ObjectIdentifier(psObj->Constraints)
                << App::ObjectIdentifier::SimpleComponent(scname);
            sref = spath.getDocumentObjectName().getString() + spath.toString();
        }
        else {
            spath = psObj->Constraints.createPath(sourceid);
            sref = spath.getDocumentObjectName().getString() + std::string(1, '.') + spath.toString();
        }
        if (xinv || yinv) {
            // corrections for flipped expressions
            sref = makeCorrectedExpressionString((*it), sref);
        }
        expr = std::shared_ptr<App::Expression>(App::Expression::parse(this, sref));
        setExpression(Constraints.createPath(copied), std::move(expr));
    }

    // Solve even if `noRecomputes==false`, because recompute may fail, and leave the
    // sketch in an inconsistent state. A concrete example. If the copied sketch
    // has broken external geometry, its recomputation will fail. And because we
    // use expression for copied constraint to add dependency to the copied
    // sketch, this sketch will not be recomputed (because its dependency fails
    // to recompute).
    solve();

    return svals.size();
}

namespace
{
// Set while addExternal adds a face's or shape's edges one by one: an edge that gives nothing
// is skipped quietly, the whole add fails (loudly) only when none gives anything (ops#252)
thread_local int addingSubShapes = 0;

// Raises addingSubShapes for its scope, also when the add throws (PR 269 round 2)
struct AddingSubShapes
{
    AddingSubShapes()
    {
        ++addingSubShapes;
    }
    ~AddingSubShapes()
    {
        --addingSubShapes;
    }
    AddingSubShapes(const AddingSubShapes&) = delete;
    AddingSubShapes& operator=(const AddingSubShapes&) = delete;
};
}  // namespace

int SketchObject::addExternal(App::DocumentObject* Obj, const char* SubName, bool defining, bool intersection)
{
    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    // so far only externals to the support of the sketch and datum features
    if (!isExternalAllowed(Obj->getDocument(), Obj)) {
        return -1;
    }

    auto wholeShape = Part::Feature::getTopoShape(
        Obj,
        Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
    );
    auto shape = wholeShape.getSubTopoShape(SubName, /*silent*/ true);
    TopAbs_ShapeEnum shapeType = TopAbs_SHAPE;
    if (shape.shapeType(/*silent*/ true) != TopAbs_FACE) {
        if (shape.hasSubShape(TopAbs_FACE)) {
            shapeType = TopAbs_FACE;
        }
        else if (shape.shapeType(/*silent*/ true) != TopAbs_EDGE && shape.hasSubShape(TopAbs_EDGE)) {
            shapeType = TopAbs_EDGE;
        }
    }

    if (shapeType != TopAbs_SHAPE) {
        std::string element = Part::TopoShape::shapeName(shapeType);
        std::size_t elementNameSize = element.size();
        int geometryCount = ExternalGeometry.getSize();
        // FreeCAD-CH (PR 269 round 2): whether any sub-shape's add made geometry. Counting links
        // missed an add that only gave existing links the other kind (they become Both)
        bool added = false;

        gp_Pln sketchPlane;
        if (intersection) {
            Base::Placement Plm = Placement.getValue();
            Base::Vector3d Pos = Plm.getPosition();
            Base::Rotation Rot = Plm.getRotation();
            Base::Vector3d dN(0, 0, 1);
            Rot.multVec(dN, dN);
            Base::Vector3d dX(1, 0, 0);
            Rot.multVec(dX, dX);
            gp_Ax3 sketchAx3(
                gp_Pnt(Pos.x, Pos.y, Pos.z),
                gp_Dir(dN.x, dN.y, dN.z),
                gp_Dir(dX.x, dX.y, dX.z)
            );
            sketchPlane.SetPosition(sketchAx3);
            // the sub-shapes are in Obj's container (FreeCAD-CH ops#331)
            const Base::Placement frame = externalFrame(Obj, SubName ? SubName : "");
            if (!isIdentityFrame(frame)) {
                sketchPlane.Transform(Part::TopoShape::convert(frame.inverse().toMatrix()));
            }
        }
        for (const auto& subShape : shape.getSubShapes(shapeType)) {
            int idx = wholeShape.findShape(subShape);
            if (idx == 0) {
                continue;
            }
            if (intersection) {
                try {
                    FCBRepAlgoAPI_Section maker(subShape, sketchPlane);
                    if (!maker.IsDone() || maker.Shape().IsNull()) {
                        continue;
                    }
                }
                catch (Standard_Failure&) {
                    continue;
                }
            }
            element += std::to_string(idx);
            {
                AddingSubShapes adding;
                added = addExternal(Obj, element.c_str(), defining, intersection) >= 0 || added;
            }
            element.resize(elementNameSize);
        }
        if (!added) {
            if (addingSubShapes == 0) {
                Base::Console().error("%s gives no %s geometry in this sketch.\n",
                                      SubName,
                                      intersection ? "intersection" : "projection");
            }
            return -1;
        }
        return ExternalGeometry.getSize() > geometryCount ? geometryCount
                                                          : ExternalGeometry.getSize() - 1;
    }

    // get the actual lists of the externals
    std::vector<long> Types = ExternalTypes.getValues();
    std::vector<DocumentObject*> Objects = ExternalGeometry.getValues();
    std::vector<std::string> SubElements = ExternalGeometry.getSubValues();
    Types.resize(Objects.size(), static_cast<long>(ExtType::Projection));

    const std::vector<DocumentObject*> originalObjects = Objects;
    const std::vector<std::string> originalSubElements = SubElements;
    const std::vector<long> originalTypes = ExternalTypes.getValues();
    std::string decidedKey;  // a link waiting for its type that this add decides
    // FreeCAD-CH (ops#287, PR 277 verification 2.5): a failed add puts back which links wait and
    // the pending repair as they were. The add's rebuild can decide another waiting link whose
    // element is back; if that was the last one, it drops the repair's mark from the types. Put
    // back the links only, the mark would be lost and the next open would settle every waiting
    // link silently
    const std::set<std::string> originalUndecided = undecidedTypeKeys;
    const bool originalRepairPending = externalTypeRepairPending;
    auto revert = [&]() {
        undecidedTypeKeys = originalUndecided;
        externalTypeRepairPending = originalRepairPending;
        Base::StateLocker lock(externalLinksWithTypes, true);
        if (ExternalTypes.getValues() != originalTypes) {
            ExternalTypes.setValues(originalTypes);
        }
        setExternalLinks(ExternalGeometry, originalObjects, originalSubElements);
    };

    if (Objects.size() != SubElements.size()) {
        assert(0 /*counts of objects and subelements in external geometry links do not match*/);
        Base::Console().error(
            "Internal error: counts of objects and subelements in external "
            "geometry links do not match\n"
        );
        return -1;
    }

    bool add = true;
    for (size_t i = 0; i < Objects.size(); ++i) {
        if (!(Objects[i] == Obj && std::string(SubName) == SubElements[i])) {
            continue;
        }
        if (Types[i] == static_cast<int>(ExtType::Both)
            || (Types[i] == static_cast<int>(ExtType::Projection) && !intersection)
            || (Types[i] == static_cast<int>(ExtType::Intersection) && intersection)) {
            Base::Console().error("Link to %s already exists in this sketch.\n", SubName);
            return -1;
        }
        // The rebuild skips a frozen link: the added kind would get no geometry until the link
        // thaws, and then take the Ids (and the constraints) of the geometry it has (ops#260)
        if (i < externalGeoRef.size()) {
            auto it = externalGeoRefMap.find(externalGeoRef[i]);
            if (it != externalGeoRefMap.end()
                && std::any_of(it->second.begin(), it->second.end(), [this](long id) {
                       auto found = externalGeoMap.find(id);
                       return found != externalGeoMap.end()
                           && ExternalGeometryFacade::getFacade(ExternalGeo[found->second])
                                  ->testFlag(ExternalGeometryExtension::Frozen);
                   })) {
                Base::Console().error(
                    "Link to %s is frozen: unfreeze it before adding its %s.\n",
                    SubName,
                    intersection ? "intersection" : "projection"
                );
                return -1;
            }
        }
        // Case where projections are already there when adding intersections, or the reverse:
        // the rebuild keeps the existing geometry's Ids on it (ops#260)
        add = false;
        Types[i] = static_cast<int>(ExtType::Both);
        // the user's choice: a link waiting for its type no longer does, and its geometry is no
        // longer flagged as guessed (PR 277 review L5); a failed add below puts the key back
        if (i < externalGeoRef.size() && undecidedTypeKeys.erase(externalGeoRef[i]) != 0) {
            decidedKey = externalGeoRef[i];
        }
    }
    if (add) {
        // add the new ones
        Objects.push_back(Obj);
        SubElements.emplace_back(SubName);
        Types.push_back(static_cast<int>(intersection ? ExtType::Intersection : ExtType::Projection));

        // set the Link list.
        setExternalLinksAndTypes(Objects, SubElements, Types);
        // the user's choice too: a link dropped while it waited keeps its key while its geometry
        // remains (updateGeometryRefs), and the same element added again is that link; its type
        // is the one added, so it no longer waits (PR 277 verification 4.6). A failed add below
        // puts the key back
        if (externalGeoRef.size() == Objects.size()
            && undecidedTypeKeys.erase(externalGeoRef.back()) != 0) {
            decidedKey = externalGeoRef.back();
        }
    }
    else {
        auto pending = pendingTypeRepair();
        Types.insert(Types.end(), pending.begin(), pending.end());
        ExternalTypes.setValues(Types);
    }

    try {
        ExternalToAdd ext {Obj, std::string(SubName), defining, intersection};
        rebuildExternalGeometry(ext);
    }
    catch (const Base::Exception& e) {
        Base::Console().error("%s\n", e.what());
        // revert to original values
        revert();
        return -1;
    }

    // FreeCAD-CH (ops#252): a link, or the kind added to one, that gives no geometry is a
    // failure. A new one was dropped by the rebuild, and the index returned was another link's,
    // so the GUI committed an empty command with no message; an added kind with none made the
    // link Both with nothing of that kind. Counted by kind (PR 269 review L1): the rebuild builds
    // the link's other kind again, whose count can change too
    {
        const int kind = intersection ? 0 : 1;  // externalGeometryKind's
        std::size_t ofKind = 0;
        const auto& objects = ExternalGeometry.getValues();
        const auto& subs = ExternalGeometry.getSubValues();
        for (size_t i = 0; i < objects.size() && i < subs.size(); ++i) {
            if (objects[i] == Obj && subs[i] == SubName) {
                for (long id : externalGeometryIds(static_cast<int>(i))) {
                    ofKind += externalGeometryKind(id) == kind ? 1 : 0;
                }
                break;
            }
        }
        if (ofKind == 0) {
            if (addingSubShapes == 0) {
                Base::Console().error(
                    "Link to %s gives no %s geometry in this sketch.\n",
                    SubName,
                    intersection ? "intersection" : "projection"
                );
            }
            if (ExternalGeometry.getValues() != originalObjects
                || ExternalGeometry.getSubValues() != originalSubElements
                || ExternalTypes.getValues() != originalTypes
                || undecidedTypeKeys != originalUndecided
                || externalTypeRepairPending != originalRepairPending) {
                revert();
                // the geometry as the links and types are again
                try {
                    rebuildExternalGeometry();
                }
                catch (const Base::Exception& e) {
                    Base::Console().error("%s\n", e.what());
                }
            }
            return -1;
        }
    }
    if (!decidedKey.empty() && !add) {
        // the user chose the added kind only: the link's other kind was built from the type at
        // its index, a guess, which Both now keeps (PR 277 verification 7)
        Base::Console().warning(
            "Link to %s: its %s was built from a guessed type (a type list saved before "
            "ops#140) and is kept, with the %s added. Delete the link and add it again if its "
            "%s isn't wanted.\n",
            SubName,
            intersection ? "projection" : "intersection",
            intersection ? "intersection" : "projection",
            intersection ? "projection" : "intersection"
        );
    }

    acceptGeometry();  // This may need to be refactored into onChanged for ExternalGeometry

    solverNeedsUpdate = true;
    return ExternalGeometry.getValues().size() - 1;
}
// clang-format off

int SketchObject::delExternal(int ExtGeoId)
{
    return delExternal(std::vector<int>{ExtGeoId});
}

int SketchObject::delExternal(const std::vector<int>& ExtGeoIds)
{
    std::set<long> geoIds;
    for (int ExtGeoId : ExtGeoIds) {
        int GeoId = ExtGeoId >= 0 ? GeoEnum::RefExt - ExtGeoId : ExtGeoId;
        if (GeoId > GeoEnum::RefExt || -GeoId - 1 >= ExternalGeo.getSize())
            return -1;

        auto geo = getGeometry(GeoId);
        if (!geo)
            return -1;

        auto egf = ExternalGeometryFacade::getFacade(geo);
        geoIds.insert(egf->getId());
        if (egf->getRef().size()) {
            auto& refs = externalGeoRefMap[egf->getRef()];
            geoIds.insert(refs.begin(), refs.end());
        }
    }

    delExternalPrivate(geoIds, true);
    return 0;
}

// clang-format on
void SketchObject::delExternalPrivate(const std::set<long>& ids, bool removeRef)
{
    Base::StateLocker lock(managedoperation, true);  // no need to check input data validity as this
                                                     // is an sketchobject managed operation.

    // A constraint list flagged invalid (the geometry it was checked against is gone, e.g. during
    // a restore) stays flagged: accepting the current geometry below would bless the constraints
    // against geometry they weren't made for (ops#140).
    const bool invalidConstraints = Constraints.hasInvalidGeometry();
    Base::StateLocker keepInvalid(keepConstraintsInvalid, invalidConstraints);

    std::set<std::string> refs;
    // Must sort in reverse order so as to delete geo from back to front to
    // avoid index change
    std::set<int, std::greater<int>> geoIds;

    for (auto id : ids) {
        auto it = externalGeoMap.find(id);
        if (it == externalGeoMap.end()) {
            continue;
        }

        // PROTECTION: Never delete array index 0 or 1 (H_Axis and V_Axis)
        if (it->second < 2) {
            Base::Console().error("SketchObject::delExternal trying to remove axis, please report.\n");
            continue;
        }

        auto egf = ExternalGeometryFacade::getFacade(ExternalGeo[it->second]);
        if (removeRef && egf->getRef().size()) {
            refs.insert(egf->getRef());
        }
        geoIds.insert(-it->second - 1);
    }

    if (geoIds.empty()) {
        return;
    }

    // getValuesForce(): getValues() is empty while the list is flagged invalid (e.g. during a
    // restore or before a recompute), and writing that back would delete every constraint (ops#140)
    std::vector<Constraint*> newConstraints;
    for (const auto& cstr : Constraints.getValuesForce()) {
        // every element, not only First/Second/Third: a group constraint has more
        if (std::any_of(geoIds.begin(), geoIds.end(), [&cstr](int geoId) {
                return cstr->involvesGeoId(geoId);
            })) {
            continue;
        }
        int offset = 0;
        std::unique_ptr<Constraint> newCstr(cstr->clone());
        for (auto GeoId : geoIds) {
            GeoId += offset++;
            changeConstraintAfterDeletingGeo(newCstr.get(), GeoId);
        }
        // need to provide raw pointer because that's the only one supported by `setValues`
        newConstraints.push_back(newCstr.release());
    }

    auto geos = ExternalGeo.getValues();
    int offset = 0;
    for (auto geoId : geoIds) {
        int idx = -geoId - 1;
        geos.erase(geos.begin() + idx - offset);
        ++offset;
    }

    if (!refs.empty()) {
        std::vector<std::string> newSubs;
        std::vector<App::DocumentObject*> newObjs;
        std::vector<long> newTypes;
        const auto& subs = ExternalGeometry.getSubValues();
        const auto& objs = ExternalGeometry.getValues();
        bool touched = false;
        assert(externalGeoRef.size() == objs.size());
        assert(externalGeoRef.size() == subs.size());
        for (std::size_t i = 0; i < externalGeoRef.size(); ++i) {
            if (refs.find(externalGeoRef[i]) == refs.end()) {
                newObjs.push_back(objs[i]);
                newSubs.push_back(subs[i]);
                newTypes.push_back(externalType(static_cast<int>(i)));
            }
            else {
                touched = true;
            }
        }
        if (touched) {
            setExternalLinksAndTypes(newObjs, newSubs, newTypes);
        }
        // a deleted link no longer waits for its type: added again, it is a new link (PR 277
        // review M3). updateGeometryRefs keeps the key of a link whose geometry is still there,
        // which here goes only below (verification 3.6)
        for (const auto& ref : refs) {
            undecidedTypeKeys.erase(ref);
        }
    }

    ExternalGeo.setValues(std::move(geos));

    solverNeedsUpdate = true;
    Constraints.setValues(std::move(newConstraints));
    if (invalidConstraints) {
        rebuildVertexIndex();
        signalElementsChanged();
    }
    else {
        acceptGeometry();  // This may need to be refactored into OnChanged for ExternalGeometry.
    }
}

int SketchObject::delAllExternal()
{
    int count = 0;                      // the remaining count of the detached external geometry
    std::map<int, int> indexMap;        // the index map of the remain external geometry
    std::vector<Part::Geometry*> geos;  // the remaining external geometry
    for (int i = 0; i < ExternalGeo.getSize(); ++i) {
        auto geo = ExternalGeo[i];
        auto egf = ExternalGeometryFacade::getFacade(geo);
        if (egf->getRef().empty()) {
            indexMap[i] = count++;
        }
        geos.push_back(geo);
    }
    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    // get the actual lists of the externals
    std::vector<DocumentObject*> Objects = ExternalGeometry.getValues();
    std::vector<std::string> SubElements = ExternalGeometry.getSubValues();

    const std::vector<DocumentObject*> originalObjects = Objects;
    const std::vector<std::string> originalSubElements = SubElements;
    const std::vector<long> originalTypes = ExternalTypes.getValues();

    // a constraint list flagged invalid stays flagged, as in delExternalPrivate (ops#140)
    const bool invalidConstraints = Constraints.hasInvalidGeometry();
    Base::StateLocker keepInvalid(keepConstraintsInvalid, invalidConstraints);

    Objects.clear();
    SubElements.clear();

    // getValuesForce(): getValues() is empty while the list is flagged invalid, and writing that
    // back would delete every constraint (ops#140)
    const std::vector<Constraint*>& constraints = Constraints.getValuesForce();
    std::vector<Constraint*> newConstraints(0);

    for (const auto& constr : constraints) {
        // every element, not only First/Second/Third: a group constraint has more
        bool onExternal = false;
        for (std::size_t i = 0; i < constr->getElementsSize(); ++i) {
            int geoId = constr->getElement(i).GeoId;
            if (geoId <= GeoEnum::RefExt && geoId != GeoEnum::GeoUndef) {
                onExternal = true;
                break;
            }
        }
        if (!onExternal) {
            newConstraints.push_back(constr->clone());
        }
    }

    setExternalLinksAndTypes(Objects, SubElements, {});
    try {
        rebuildExternalGeometry();
    }
    catch (const Base::Exception& e) {
        Base::Console().error("%s\n", e.what());
        // revert to original values
        setExternalLinksAndTypes(originalObjects, originalSubElements, originalTypes);
        for (Constraint* it : newConstraints) {
            delete it;
        }
        return -1;
    }

    ExternalGeometry.setValue(0);
    // The waiting keys stay: every geometry goes back, also the linked geometry the rebuild just
    // marked missing, which the next rebuild links again; as for a link dropped from outside
    // (updateGeometryRefs), a key goes only with the last geometry naming it, and geometry built
    // from a guess waits again when it is linked again (PR 277 verification 4.8; no caller uses
    // this path)
    ExternalGeo.setValues(std::move(geos));
    solverNeedsUpdate = true;
    Constraints.setValues(std::move(newConstraints));
    if (invalidConstraints) {
        rebuildVertexIndex();
        signalElementsChanged();
    }
    else {
        acceptGeometry();  // This may need to be refactored into OnChanged for ExternalGeometry
    }
    return 0;
}
// clang-format off

int SketchObject::delConstraintsToExternal(DeleteOptions options)
{
    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    const std::vector<Constraint*>& constraints = Constraints.getValuesForce();
    std::vector<Constraint*> newConstraints(0);
    int GeoId = GeoEnum::RefExt, NullId = GeoEnum::GeoUndef;
    for (const auto& constr : constraints) {
        if (constr->First > GeoId && (constr->Second > GeoId || constr->Second == NullId)
            && (constr->Third > GeoId || constr->Third == NullId)) {
            newConstraints.push_back(constr);
        }
    }

    Constraints.setValues(std::move(newConstraints));
    Constraints.acceptGeometry(getCompleteGeometry());

    // if we do not have a recompute, the sketch must be solved to update the DoF of the solver
    if (noRecomputes && !options.testFlag(DeleteOption::NoFlag)) {
        solve(options.testFlag(DeleteOption::UpdateGeometry));
    }

    return 0;
}

// FreeCAD-CH (ops#287, PR 277 round 5): what a link's geometry tells when the link is formed
// again (its element back after the link was dropped, an unpark, an attach): whether any of it
// was built from a guessed type (TypeGuessed) or is saved geometry of a link an open couldn't
// tell (TypeUndecided, round 7), both saved with it, so that the link waits for its type again,
// and the type its kinds were built with (a projection without kinds, saved before ops#264)
struct FormedAgain
{
    bool waits = false;
    long type = static_cast<long>(ExtType::Projection);
};

static FormedAgain formedAgain(const std::vector<const Part::Geometry*>& geos);

int SketchObject::attachExternal(
        const std::vector<int> &geoIds, App::DocumentObject *Obj, const char* SubName)
{
    if (!isExternalAllowed(Obj->getDocument(), Obj))
       return -1;

    std::set<std::string> detached;
    std::set<int> idSet;
    for (int geoId : geoIds) {
        if (geoId > GeoEnum::RefExt || -geoId - 1 >= ExternalGeo.getSize())
            continue;
        auto geo = getGeometry(geoId);
        if(!geo)
            continue;
        auto egf = ExternalGeometryFacade::getFacade(geo);
        if(egf->getRef().size())
            detached.insert(egf->getRef());
        for(int id : getRelatedGeometry(geoId))
            idSet.insert(id);
    }

    auto geos = ExternalGeo.getValues();

    std::vector<DocumentObject*> Objects     = ExternalGeometry.getValues();
    auto itObj = Objects.begin();
    std::vector<std::string>     SubElements = ExternalGeometry.getSubValues();
    auto itSub = SubElements.begin();

    assert(Objects.size()==SubElements.size());
    assert(externalGeoRef.size() == Objects.size());

    std::vector<long> Types;
    // the new link gives the detached geometries, so it takes the type of the link they came from
    // (of the first, when they came from several links of different types)
    std::optional<long> attachedType;
    int entry = 0;
    for(auto &key : externalGeoRef) {
        if (*itObj == Obj  &&  *itSub == SubName){
            FC_ERR("Duplicate external element reference in " << getFullName() << ": " << key);
            return -1;
        }
        // detach old reference
        if(detached.count(key)) {
            itObj = Objects.erase(itObj);
            itSub = SubElements.erase(itSub);
            if (!attachedType) {
                attachedType = externalType(entry);
            }
        }else{
            ++itObj;
            ++itSub;
            Types.push_back(externalType(entry));
        }
        ++entry;
    }

    // add the new ones
    Objects.push_back(Obj);
    SubElements.push_back(std::string(SubName));
    Types.push_back(attachedType.value_or(static_cast<long>(ExtType::Projection)));

    // FreeCAD-CH (ops#287, PR 277 round 5): geometry built from a guessed type links the new
    // element with that guess: the new link waits for its type, as any link formed again on such
    // geometry does
    std::vector<const Part::Geometry*> attached;
    for (int geoId : idSet) {
        attached.push_back(geos[-geoId - 1]);
    }
    const bool guessed = formedAgain(attached).waits;
    if (guessed) {
        externalTypeRepairPending = true;
    }

    setExternalLinksAndTypes(Objects, SubElements, Types);
    if(externalGeoRef.size()!=Objects.size())
        return -1;

    std::string ref = externalGeoRef.back();
    if (guessed) {
        undecidedTypeKeys.insert(ref);
    }
    for(auto geoId : idSet) {
        auto &geo = geos[-geoId-1];
        geo = geo->clone();
        ExternalGeometryFacade::getFacade(geo)->setRef(ref);
        // drawn, not projected: no source edge (ops#264 e2)
        ExternalGeometryFacade::getFacade(geo)->setSource(std::string());
    }

    ExternalGeo.setValues(std::move(geos));
    rebuildExternalGeometry();
    return ExternalGeometry.getSize()-1;
}

std::vector<int> SketchObject::getRelatedGeometry(int GeoId) const {
    std::vector<int> res;
    if(GeoId>GeoEnum::RefExt || -GeoId-1>=ExternalGeo.getSize())
        return res;
    auto geo = getGeometry(GeoId);
    if(!geo)
        return res;
    const std::string &ref = ExternalGeometryFacade::getFacade(geo)->getRef();
    if(!ref.size())
       return {GeoId};
    auto iter = externalGeoRefMap.find(ref);
    if(iter == externalGeoRefMap.end())
        return {GeoId};
    for(auto id : iter->second) {
        auto it = externalGeoMap.find(id);
        if(it!=externalGeoMap.end())
            res.push_back(-it->second-1);
    }
    return res;
}

int SketchObject::syncGeometry(const std::vector<int> &geoIds) {
    bool touched = false;
    auto geos = ExternalGeo.getValues();
    std::set<int> idSet;
    for(int geoId : geoIds) {
        auto geo = getGeometry(geoId);
        if(!geo || !ExternalGeometryFacade::getFacade(geo)->testFlag(ExternalGeometryExtension::Frozen))
            continue;
        for(int gid : getRelatedGeometry(geoId))
            idSet.insert(gid);
    }
    for(int geoId : idSet) {
        if(geoId <= GeoEnum::RefExt && -geoId-1 < ExternalGeo.getSize()) {
            auto &geo = geos[-geoId-1];
            geo = geo->clone();
            ExternalGeometryFacade::getFacade(geo)->setFlag(ExternalGeometryExtension::Sync);
            touched = true;
        }
    }
    if(touched)
        ExternalGeo.setValues(std::move(geos));
    return 0;
}

namespace {

// Auxiliary Method: returns vector projection in UV space of plane
static gp_Vec2d ProjVecOnPlane_UV(const gp_Vec& V, const gp_Pln& Pl)
{
    return gp_Vec2d(V.Dot(Pl.Position().XDirection()), V.Dot(Pl.Position().YDirection()));
}

// Auxiliary Method: returns vector projection in UVN space of plane
static gp_Vec ProjVecOnPlane_UVN(const gp_Vec& V, const gp_Pln& Pl)
{
    gp_Vec2d vector = ProjVecOnPlane_UV(V, Pl);
    return gp_Vec(vector.X(), vector.Y(), 0.0);
}


// Auxiliary Method: returns point projection in UV space of plane
static gp_Vec2d ProjPointOnPlane_UV(const gp_Pnt& P, const gp_Pln& Pl)
{
    gp_Vec OP = gp_Vec(Pl.Location(), P);
    return ProjVecOnPlane_UV(OP, Pl);
}

// Auxiliary Method: returns point projection in UVN space of plane
static gp_Vec ProjPointOnPlane_UVN(const gp_Pnt& P, const gp_Pln& Pl)
{
    gp_Vec2d vec2 = ProjPointOnPlane_UV(P, Pl);
    return gp_Vec(vec2.X(), vec2.Y(), 0.0);
}

// Auxiliary Method: returns point projection in XYZ space
static gp_Pnt ProjPointOnPlane_XYZ(const gp_Pnt& P, const gp_Pln& Pl)
{
    gp_Vec positionUVN = ProjPointOnPlane_UVN(P, Pl);
    return gp_Pnt((positionUVN.X() * Pl.Position().XDirection()
                   + positionUVN.Y() * Pl.Position().YDirection() + gp_Vec(Pl.Location().XYZ()))
                      .XYZ());
}

// Auxiliary method
Part::Geometry* projectLine(const BRepAdaptor_Curve& curve, const Handle(Geom_Plane) & gPlane,
                            const Base::Placement& invPlm)
{
    double first = curve.FirstParameter();

    if (fabs(first) > 1E99) {
        // TODO: What is OCE's definition of Infinite?
        // TODO: The clean way to do this is to handle a new sketch geometry Geom::Line
        // but its a lot of work to implement...
        first = -10000;
    }

    double last = curve.LastParameter();
    if (fabs(last) > 1E99) {
        last = +10000;
    }

    gp_Pnt P1 = curve.Value(first);
    gp_Pnt P2 = curve.Value(last);

    GeomAPI_ProjectPointOnSurf proj1(P1, gPlane);
    P1 = proj1.NearestPoint();
    GeomAPI_ProjectPointOnSurf proj2(P2, gPlane);
    P2 = proj2.NearestPoint();

    Base::Vector3d p1(P1.X(), P1.Y(), P1.Z());
    Base::Vector3d p2(P2.X(), P2.Y(), P2.Z());
    invPlm.multVec(p1, p1);
    invPlm.multVec(p2, p2);

    if (Base::Distance(p1, p2) < Precision::Confusion()) {
        Base::Vector3d p = (p1 + p2) / 2;
        auto* point = new Part::GeomPoint(p);
        GeometryFacade::setConstruction(point, true);
        return point;
    }
    else {
        auto* line = new Part::GeomLineSegment();
        line->setPoints(p1, p2);
        GeometryFacade::setConstruction(line, true);
        return line;
    }
}

}  // anonymous namespace

static Part::Geometry *fitArcs(std::vector<std::unique_ptr<Part::Geometry> > &arcs,
                               const gp_Pnt &P1,
                               const gp_Pnt &P2,
                               double tol)
{
    double radius = 0.0;
    double m = 0.0;
    Base::Vector3d center;
    for (auto &geo : arcs) {
        if (auto arc = freecad_cast<Part::GeomArcOfCircle*>(geo.get())) {
            if (radius == 0.0) {
                radius = arc->getRadius();
                center = arc->getCenter();
                double f = arc->getFirstParameter();
                double l = arc->getLastParameter();
                m = (l-f)*0.5 + f; // middle parameter
            } else if (std::abs(radius - arc->getRadius()) > tol)
                return nullptr;
        } else
            return nullptr;
    }
    if (radius == 0.0) {
        return nullptr;
    }
    if (P1.SquareDistance(P2) < Precision::Confusion()) {
        auto* circle = new Part::GeomCircle();
        circle->setCenter(center);
        circle->setRadius(radius);
        return circle;
    }
    if (arcs.size() == 1) {
        auto res = arcs.front().release();
        arcs.clear();
        return res;
    }

    GeomLProp_CLProps prop(Handle(Geom_Curve)::DownCast(arcs.front()->handle()),m,0,Precision::Confusion());
    gp_Pnt midPoint = prop.Value();
    GC_MakeArcOfCircle arc(P1, midPoint, P2);
    auto* geo = new Part::GeomArcOfCircle();
    geo->setHandle(arc.Value());
    return geo;
}

// FreeCAD-CH (ops#264): marks an external geometry as its link's projection or intersection
static void setKind(Part::Geometry* geo, bool projection)
{
    auto egf = ExternalGeometryFacade::getFacade(geo);
    egf->setFlag(ExternalGeometryExtension::Projection, projection);
    egf->setFlag(ExternalGeometryExtension::Intersection, !projection);
}

// the kind setKind gave a geometry: true for a projection, false for an intersection, none for
// geometry saved before ops#264, or with both flags set (from Python: no kind to trust, PR 241
// review)
static std::optional<bool> kindOf(const Part::Geometry* geo)
{
    auto egf = ExternalGeometryFacade::getFacade(geo);
    const bool projection = egf->testFlag(ExternalGeometryExtension::Projection);
    const bool intersection = egf->testFlag(ExternalGeometryExtension::Intersection);
    if (projection == intersection) {
        return std::nullopt;
    }
    return projection;
}

static void clearKind(Part::Geometry* geo)
{
    auto egf = ExternalGeometryFacade::getFacade(geo);
    egf->setFlag(ExternalGeometryExtension::Projection, false);
    egf->setFlag(ExternalGeometryExtension::Intersection, false);
}

static FormedAgain formedAgain(const std::vector<const Part::Geometry*>& geos)
{
    FormedAgain state;
    bool projection = false;
    bool intersection = false;
    for (const auto* geo : geos) {
        auto egf = ExternalGeometryFacade::getFacade(geo);
        state.waits = state.waits || egf->testFlag(ExternalGeometryExtension::TypeGuessed)
            || egf->testFlag(ExternalGeometryExtension::TypeUndecided);
        if (auto kind = kindOf(geo)) {
            projection = projection || *kind;
            intersection = intersection || !*kind;
        }
    }
    if (projection && intersection) {
        state.type = static_cast<long>(ExtType::Both);
    }
    else if (intersection) {
        state.type = static_cast<long>(ExtType::Intersection);
    }
    return state;
}

void SketchObject::validateExternalLinks()
{
    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    std::vector<DocumentObject*> Objects = ExternalGeometry.getValues();
    std::vector<std::string> SubElements = ExternalGeometry.getSubValues();
    if (externalGeoRef.size() != Objects.size()) {
        throw Base::RuntimeError("Inconsistency with external geometries");
    }

    // the references (externalGeoRef) of the links to remove
    std::set<std::string> badRefs;

    for (int i = 0; i < int(Objects.size()); i++) {
        const App::DocumentObject* Obj = Objects[i];
        const std::string SubElement = SubElements[i];

        TopoDS_Shape refSubShape;
        try {
            if (Obj->isDerivedFrom<Part::Datum>()) {
                const auto* datum = static_cast<const Part::Datum*>(Obj);
                refSubShape = datum->getShape();
            }
            else if (Obj->isDerivedFrom<App::DatumElement>()) {
                // do nothing - shape will be calculated later during rebuild
            }
            else {
                const auto* refObj = static_cast<const Part::Feature*>(Obj);
                const Part::TopoShape& refShape = refObj->Shape.getShape();
                refSubShape = refShape.getSubShape(SubElement.c_str());
            }
            continue; // no bad link needs to be removed
        }
        catch (Base::IndexError& indexError) {
            Base::Console().warning(
                this->getFullLabel(), (indexError.getMessage() + "\n").c_str());
        }
        catch (Base::ValueError& valueError) {
            Base::Console().warning(
                this->getFullLabel(), (valueError.getMessage() + "\n").c_str());
        }
        catch (Standard_Failure&) {
        }
        catch (Base::Exception& e) {
            // e.g. a mapped name that no longer resolves (CADKernelError)
            Base::Console().warning(this->getFullLabel(), (e.getMessage() + "\n").c_str());
        }

        // A link whose element is missing keeps its frozen geometry and the constraints on it
        // until the user re-points or deletes it (ops#72); the recompute reports it. This runs
        // whenever the support isn't a Part::Feature (an origin plane too), so opening the sketch
        // must not delete them.
        auto it = externalGeoRefMap.find(externalGeoRef[i]);
        if (it != externalGeoRefMap.end()
            && std::any_of(it->second.begin(), it->second.end(), [this](long id) {
                   return externalGeoMap.count(id) != 0;
               })) {
            continue;
        }

        badRefs.insert(externalGeoRef[i]);
    }

    if (!badRefs.empty()) {
        // Remove each bad link with its own external geometry and the constraints on that
        // geometry. A link can give several geometries (a face's edges, an intersection), so the
        // link's index in ExternalGeometry is not a geometry index (ops#75).
        std::set<long> ids;
        for (const auto& ref : badRefs) {
            auto it = externalGeoRefMap.find(ref);
            if (it != externalGeoRefMap.end()) {
                ids.insert(it->second.begin(), it->second.end());
            }
        }
        // removes the geometry, the constraints on it and the links it came from
        delExternalPrivate(ids, true);

        // a bad link that had no geometry is still there
        std::vector<DocumentObject*> objs;
        std::vector<std::string> subs;
        std::vector<long> types;
        const auto& values = ExternalGeometry.getValues();
        const auto& subValues = ExternalGeometry.getSubValues();
        bool touched = false;
        for (std::size_t i = 0; i < values.size() && i < externalGeoRef.size(); ++i) {
            if (badRefs.count(externalGeoRef[i])) {
                touched = true;
                continue;
            }
            objs.push_back(values[i]);
            subs.push_back(subValues[i]);
            types.push_back(externalType(static_cast<int>(i)));
        }
        if (touched) {
            setExternalLinksAndTypes(objs, subs, types);
        }

        rebuildExternalGeometry();
        acceptGeometry();// This may need to be refactor to OnChanged for ExternalGeo
        solve(true);     // we have to update this sketch and everything depending on it.
    }
}

namespace {

void adjustParameterRange(const TopoDS_Edge &edge,
                                 Handle(Geom_Plane) gPlane,
                                 const gp_Trsf &mov,
                                 Handle(Geom_Curve) curve,
                                 double &firstParameter,
                                 double &lastParameter)
{
    // This function is to deal with the ambiguity of trimming a periodic
    // curve, e.g. given two points on a circle, whether to get the upper or
    // lower arc. Because projection orientation may swap the first and last
    // parameter of the original curve.
    //
    // We project the middle point of the original curve to the projected curve
    // to decide whether to flip the parameters.

    Handle(Geom_Curve) origCurve = BRepAdaptor_Curve(edge).Curve().Curve();

    // GeomAPI_ProjectPointOnCurve will project a point to an untransformed
    // curve, so make sure to obtain the point on an untransformed edge.
    auto e = edge.Located(TopLoc_Location());

    gp_Pnt firstPoint = BRep_Tool::Pnt(TopExp::FirstVertex(TopoDS::Edge(e)));
    double f = GeomAPI_ProjectPointOnCurve(firstPoint, origCurve).LowerDistanceParameter();

    gp_Pnt lastPoint = BRep_Tool::Pnt(TopExp::LastVertex(TopoDS::Edge(e)));
    double l = GeomAPI_ProjectPointOnCurve(lastPoint, origCurve).LowerDistanceParameter();

    auto adjustPeriodic = [](Handle(Geom_Curve) curve, double &f, double &l) {
        // Copied from Geom_TrimmedCurve::setTrim()
        if (curve->IsPeriodic()) {
            Standard_Real Udeb = curve->FirstParameter();
            Standard_Real Ufin = curve->LastParameter();
            // set f in the range Udeb , Ufin
            // set l in the range f , f + Period()
            ElCLib::AdjustPeriodic(Udeb, Ufin,
                    std::min(std::abs(f-l)/2,Precision::PConfusion()),
                    f, l);
        }
    };

    // Adjust for periodic curve to deal with orientation
    adjustPeriodic(origCurve, f, l);

    // Obtain the middle parameter in order to get the mid point of the arc
    double m = (l - f) * 0.5 + f;
    GeomLProp_CLProps prop(origCurve,m,0,Precision::Confusion());
    gp_Pnt midPoint = prop.Value();

    // Transform all three points to the world coordinate
    auto trsf = edge.Location().Transformation();
    midPoint.Transform(trsf);
    firstPoint.Transform(trsf);
    lastPoint.Transform(trsf);

    // Project the points to the sketch plane. Note the coordinates are still
    // in world coordinate system.
    gp_Pnt pm = GeomAPI_ProjectPointOnSurf(midPoint, gPlane).NearestPoint();
    gp_Pnt pf = GeomAPI_ProjectPointOnSurf(firstPoint, gPlane).NearestPoint();
    gp_Pnt pl = GeomAPI_ProjectPointOnSurf(lastPoint, gPlane).NearestPoint();

    // Transform the projected points to sketch plane local coordinates
    pm.Transform(mov);
    pf.Transform(mov);
    pl.Transform(mov);

    // Obtain the corresponding parameters for those points in the projected curve
    double f2 = GeomAPI_ProjectPointOnCurve(pf, curve).LowerDistanceParameter();
    double l2 = GeomAPI_ProjectPointOnCurve(pl, curve).LowerDistanceParameter();
    double m2 = GeomAPI_ProjectPointOnCurve(pm, curve).LowerDistanceParameter();

    firstParameter = f2;
    lastParameter = l2;

    adjustPeriodic(curve, f2, l2);
    adjustPeriodic(curve, f2, m2);
    // If the middle point is out of range, it means we need to choose the
    // other half of the arc.
    if (m2 > l2){
        std::swap(firstParameter, lastParameter);
    }
}

void processEdge2(TopoDS_Edge& projEdge, std::vector<std::unique_ptr<Part::Geometry>>& geos)
{
    BRepAdaptor_Curve projCurve(projEdge);
    if (projCurve.GetType() == GeomAbs_Line) {
        gp_Pnt P1 = projCurve.Value(projCurve.FirstParameter());
        gp_Pnt P2 = projCurve.Value(projCurve.LastParameter());
        Base::Vector3d p1(P1.X(), P1.Y(), P1.Z());
        Base::Vector3d p2(P2.X(), P2.Y(), P2.Z());

        if (Base::Distance(p1, p2) < Precision::Confusion()) {
            Base::Vector3d p = (p1 + p2) / 2;
            auto* point = new Part::GeomPoint(p);
            GeometryFacade::setConstruction(point, true);
            geos.emplace_back(point);
        }
        else {
            auto* line = new Part::GeomLineSegment();
            line->setPoints(p1, p2);
            GeometryFacade::setConstruction(line, true);
            geos.emplace_back(line);
        }
    }
    else if (projCurve.GetType() == GeomAbs_Circle) {
        gp_Circ c = projCurve.Circle();
        gp_Pnt p = c.Location();
        gp_Pnt P1 = projCurve.Value(projCurve.FirstParameter());
        gp_Pnt P2 = projCurve.Value(projCurve.LastParameter());

        if (P1.SquareDistance(P2) < Precision::Confusion()) {
            auto* circle = new Part::GeomCircle();
            circle->setRadius(c.Radius());
            circle->setCenter(Base::Vector3d(p.X(), p.Y(), p.Z()));

            GeometryFacade::setConstruction(circle, true);
            geos.emplace_back(circle);
        }
        else {
            auto* arc = new Part::GeomArcOfCircle();
            Handle(Geom_Curve) curve = new Geom_Circle(c);
            Handle(Geom_TrimmedCurve) tCurve = new Geom_TrimmedCurve(curve,
                    projCurve.FirstParameter(),
                    projCurve.LastParameter());
            arc->setHandle(tCurve);
            GeometryFacade::setConstruction(arc, true);
            geos.emplace_back(arc);
        }
    }
    else if (projCurve.GetType() == GeomAbs_BSplineCurve) {
        // Unfortunately, a normal projection of a circle can also give
        // a Bspline Split the spline into arcs
        GeomConvert_BSplineCurveKnotSplitting bSplineSplitter(projCurve.BSpline(), 2);
        auto* bspline = new Part::GeomBSplineCurve(projCurve.BSpline());
        GeometryFacade::setConstruction(bspline, true);
        geos.emplace_back(bspline);
    }
    else if (projCurve.GetType() == GeomAbs_Hyperbola) {
        gp_Hypr e = projCurve.Hyperbola();
        gp_Pnt p = e.Location();
        gp_Pnt P1 = projCurve.Value(projCurve.FirstParameter());
        gp_Pnt P2 = projCurve.Value(projCurve.LastParameter());

        gp_Dir normal = e.Axis().Direction();
        gp_Dir xdir = e.XAxis().Direction();
        gp_Ax2 xdirref(p, normal);

        if (P1.SquareDistance(P2) < Precision::Confusion()) {
            auto* hyperbola = new Part::GeomHyperbola();
            hyperbola->setMajorRadius(e.MajorRadius());
            hyperbola->setMinorRadius(e.MinorRadius());
            hyperbola->setCenter(Base::Vector3d(p.X(), p.Y(), p.Z()));
            hyperbola->setAngleXU(-xdir.AngleWithRef(xdirref.XDirection(), normal));
            GeometryFacade::setConstruction(hyperbola, true);
            geos.emplace_back(hyperbola);
        }
        else {
            auto* aoh = new Part::GeomArcOfHyperbola();
            Handle(Geom_Curve) curve = new Geom_Hyperbola(e);
            Handle(Geom_TrimmedCurve) tCurve = new Geom_TrimmedCurve(curve,
                    projCurve.FirstParameter(),
                    projCurve.LastParameter());
            aoh->setHandle(tCurve);
            GeometryFacade::setConstruction(aoh, true);
            geos.emplace_back(aoh);
        }
    }
    else if (projCurve.GetType() == GeomAbs_Parabola) {
        gp_Parab e = projCurve.Parabola();
        gp_Pnt p = e.Location();
        gp_Pnt P1 = projCurve.Value(projCurve.FirstParameter());
        gp_Pnt P2 = projCurve.Value(projCurve.LastParameter());

        gp_Dir normal = e.Axis().Direction();
        gp_Dir xdir = e.XAxis().Direction();
        gp_Ax2 xdirref(p, normal);

        if (P1.SquareDistance(P2) < Precision::Confusion()) {
            auto* parabola = new Part::GeomParabola();
            parabola->setFocal(e.Focal());
            parabola->setCenter(Base::Vector3d(p.X(), p.Y(), p.Z()));
            parabola->setAngleXU(-xdir.AngleWithRef(xdirref.XDirection(), normal));
            GeometryFacade::setConstruction(parabola, true);
            geos.emplace_back(parabola);
        }
        else {
            auto* aop = new Part::GeomArcOfParabola();
            Handle(Geom_Curve) curve = new Geom_Parabola(e);
            Handle(Geom_TrimmedCurve) tCurve = new Geom_TrimmedCurve(curve,
                    projCurve.FirstParameter(),
                    projCurve.LastParameter());
            aop->setHandle(tCurve);
            GeometryFacade::setConstruction(aop, true);
            geos.emplace_back(aop);
        }
    }
    else if (projCurve.GetType() == GeomAbs_Ellipse) {
        gp_Elips e = projCurve.Ellipse();
        gp_Pnt p = e.Location();
        gp_Pnt P1 = projCurve.Value(projCurve.FirstParameter());
        gp_Pnt P2 = projCurve.Value(projCurve.LastParameter());

        gp_Dir normal = gp_Dir(0, 0, 1);
        gp_Ax2 xdirref(p, normal);

        if (P1.SquareDistance(P2) < Precision::Confusion()) {
            auto* ellipse = new Part::GeomEllipse();
            Handle(Geom_Ellipse) curve = new Geom_Ellipse(e);
            ellipse->setHandle(curve);
            GeometryFacade::setConstruction(ellipse, true);
            geos.emplace_back(ellipse);
        }
        else {
            auto* aoe = new Part::GeomArcOfEllipse();
            Handle(Geom_Curve) curve = new Geom_Ellipse(e);
            Handle(Geom_TrimmedCurve) tCurve = new Geom_TrimmedCurve(curve,
                    projCurve.FirstParameter(),
                    projCurve.LastParameter());
            aoe->setHandle(tCurve);
            GeometryFacade::setConstruction(aoe, true);
            geos.emplace_back(aoe);
        }
    }
    else if (projCurve.GetType() == GeomAbs_BezierCurve) {
        Handle(Geom_BSplineCurve) hBSpline = GeomConvert::CurveToBSplineCurve(projCurve.Bezier());
        auto* bspline = new Part::GeomBSplineCurve(hBSpline);
        GeometryFacade::setConstruction(bspline, true);
        geos.emplace_back(bspline);
    }
    else if (projCurve.GetType() == GeomAbs_OffsetCurve) {
        Handle(Geom_BSplineCurve) hBSpline = GeomConvert::CurveToBSplineCurve(projCurve.OffsetCurve());
        auto* bspline = new Part::GeomBSplineCurve(hBSpline);
        GeometryFacade::setConstruction(bspline, true);
        geos.emplace_back(bspline);
    }
    else {
        throw Base::NotImplementedError("Not yet supported geometry for external geometry");
    }
}

void processEdge(const TopoDS_Edge& edge,
                 std::vector<std::unique_ptr<Part::Geometry>>& geos,
                 const Handle(Geom_Plane)& gPlane,
                 const Base::Placement& invPlm,
                 const gp_Trsf& mov,
                 const gp_Pln& sketchPlane,
                 const Base::Rotation& invRot,
                 gp_Ax3& sketchAx3,
                 TopoDS_Shape& aProjFace)
{
    using std::numbers::pi;

    BRepAdaptor_Curve curve(edge);
    if (curve.GetType() == GeomAbs_Line) {
        geos.emplace_back(projectLine(curve, gPlane, invPlm));
    }
    else if (curve.GetType() == GeomAbs_Circle) {
        auto isFullCircle = [](const BRepAdaptor_Curve& curve) {
            double f = curve.FirstParameter();
            double l = curve.LastParameter();
            gp_Circ c;
            c.SetRadius(1.0);
            // for a full circle this is ~ 0.0
            double diff = std::abs(l - f - c.Length());
            return diff < gp::Resolution();
        };

        gp_Dir vec1 = sketchPlane.Axis().Direction();
        gp_Dir vec2 = curve.Circle().Axis().Direction();

        // start point of arc of circle
        gp_Pnt beg = curve.Value(curve.FirstParameter());
        // end point of arc of circle
        gp_Pnt end = curve.Value(curve.LastParameter());

        if (vec1.IsParallel(vec2, Precision::Confusion())) {
            gp_Circ circle = curve.Circle();
            gp_Pnt cnt = circle.Location();

            GeomAPI_ProjectPointOnSurf proj(cnt, gPlane);
            cnt = proj.NearestPoint();
            circle.SetLocation(cnt);
            cnt.Transform(mov);
            circle.Transform(mov);

            if (beg.SquareDistance(end) < Precision::Confusion()) {
                auto* gCircle = new Part::GeomCircle();
                gCircle->setRadius(circle.Radius());
                gCircle->setCenter(Base::Vector3d(cnt.X(), cnt.Y(), cnt.Z()));

                GeometryFacade::setConstruction(gCircle, true);
                geos.emplace_back(gCircle);
            }
            else {
                auto* gArc = new Part::GeomArcOfCircle();
                Handle(Geom_Curve) hCircle = new Geom_Circle(circle);
                Handle(Geom_TrimmedCurve) tCurve = new Geom_TrimmedCurve(
                    hCircle, curve.FirstParameter(), curve.LastParameter());
                gArc->setHandle(tCurve);
                GeometryFacade::setConstruction(gArc, true);
                geos.emplace_back(gArc);
            }
        }
        else {
            // creates an ellipse or a segment
            gp_Circ origCircle = curve.Circle();

            if (vec1.IsNormal(vec2, Precision::Angular())) {
                // circle's normal vector in plane:
                // projection is a line
                // define center by projection
                gp_Pnt cnt = origCircle.Location();
                GeomAPI_ProjectPointOnSurf proj(cnt, gPlane);
                cnt = proj.NearestPoint();

                gp_Dir dirOrientation {vec1 ^ vec2};
                gp_Dir dirLine(dirOrientation);

                auto* projectedSegment = new Part::GeomLineSegment();
                Geom_Line ligne(cnt, dirLine);// helper object to compute end points
                gp_Pnt P1, P2;                // end points of the segment, OCC style

                ligne.D0(-origCircle.Radius(), P1);
                ligne.D0(origCircle.Radius(), P2);

                if (!curve.IsClosed()) {// arc of circle
                    double alpha =
                        dirOrientation.AngleWithRef(curve.Circle().XAxis().Direction(),
                            curve.Circle().Axis().Direction());

                    double baseAngle = curve.FirstParameter();

                    int tours = 0;
                    double startAngle = baseAngle + alpha;
                    // bring startAngle back in [-pi/2 , 3pi/2[
                    while (startAngle < -pi / 2.0 && tours < 10) {
                        startAngle = baseAngle + ++tours * 2.0 * pi + alpha;
                    }
                    while (startAngle >= 3.0 * pi / 2.0 && tours > -10) {
                        startAngle = baseAngle + --tours * 2.0 * pi + alpha;
                    }

                    // apply same offset to end angle
                    double endAngle = curve.LastParameter() + startAngle - baseAngle;

                    if (startAngle <= 0.0) {
                        if (endAngle <= 0.0) {
                            P1 = ProjPointOnPlane_XYZ(beg, sketchPlane);
                            P2 = ProjPointOnPlane_XYZ(end, sketchPlane);
                        }
                        else {
                            if (endAngle <= fabs(startAngle)) {
                                // P2 = P2 already defined
                                P1 = ProjPointOnPlane_XYZ(beg, sketchPlane);
                            }
                            else if (endAngle < pi) {
                                // P2 = P2, already defined
                                P1 = ProjPointOnPlane_XYZ(end, sketchPlane);
                            }
                            else {
                                // P1 = P1, already defined
                                // P2 = P2, already defined
                            }
                        }
                    }
                    else if (startAngle < pi) {
                        if (endAngle < pi) {
                            P1 = ProjPointOnPlane_XYZ(beg, sketchPlane);
                            P2 = ProjPointOnPlane_XYZ(end, sketchPlane);
                        }
                        else if (endAngle < 2.0 * pi - startAngle) {
                            P2 = ProjPointOnPlane_XYZ(beg, sketchPlane);
                            // P1 = P1, already defined
                        }
                        else if (endAngle < 2.0 * pi) {
                            P2 = ProjPointOnPlane_XYZ(end, sketchPlane);
                            // P1 = P1, already defined
                        }
                        else {
                            // P1 = P1, already defined
                            // P2 = P2, already defined
                        }
                    }
                    else {
                        if (endAngle < 2 * pi) {
                            P1 = ProjPointOnPlane_XYZ(beg, sketchPlane);
                            P2 = ProjPointOnPlane_XYZ(end, sketchPlane);
                        }
                        else if (endAngle < 4 * pi - startAngle) {
                            P1 = ProjPointOnPlane_XYZ(beg, sketchPlane);
                            // P2 = P2, already defined
                        }
                        else if (endAngle < 3 * pi) {
                            // P1 = P1, already defined
                            P2 = ProjPointOnPlane_XYZ(end, sketchPlane);
                        }
                        else {
                            // P1 = P1, already defined
                            // P2 = P2, already defined
                        }
                    }
                }

                Base::Vector3d p1(P1.X(), P1.Y(), P1.Z());// ends of segment FCAD style
                Base::Vector3d p2(P2.X(), P2.Y(), P2.Z());
                invPlm.multVec(p1, p1);
                invPlm.multVec(p2, p2);

                projectedSegment->setPoints(p1, p2);
                GeometryFacade::setConstruction(projectedSegment, true);
                geos.emplace_back(projectedSegment);
            }
            else {// general case, full circle or arc of circle
                gp_Pnt cnt = origCircle.Location();
                GeomAPI_ProjectPointOnSurf proj(cnt, gPlane);
                // projection of circle center on sketch plane, 3D space
                cnt = proj.NearestPoint();
                // converting to FCAD style vector
                Base::Vector3d p(cnt.X(), cnt.Y(), cnt.Z());
                // transforming towards sketch's (x,y) coordinates
                invPlm.multVec(p, p);


                gp_Vec vecMajorAxis = vec1 ^ vec2;// major axis in 3D space

                double minorRadius;// TODO use data type of vectors around...
                double cosTheta;
                // cos of angle between the two planes, assuming vectirs are normalized
                // to 1
                cosTheta = fabs(vec1.Dot(vec2));
                minorRadius = origCircle.Radius() * cosTheta;

                // maj axis into FCAD style vector
                Base::Vector3d vectorMajorAxis(
                    vecMajorAxis.X(), vecMajorAxis.Y(), vecMajorAxis.Z());
                // transforming to sketch's (x,y) coordinates
                invRot.multVec(vectorMajorAxis, vectorMajorAxis);
                // back to OCC
                vecMajorAxis.SetXYZ(
                    gp_XYZ(vectorMajorAxis[0], vectorMajorAxis[1], vectorMajorAxis[2]));

                // NB: force normal of ellipse to be normal of sketch's plane.
                gp_Ax2 refFrameEllipse(
                    gp_Pnt(gp_XYZ(p[0], p[1], p[2])), gp_Vec(0, 0, 1), vecMajorAxis);

                gp_Elips elipsDest;
                elipsDest.SetPosition(refFrameEllipse);
                elipsDest.SetMajorRadius(origCircle.Radius());
                elipsDest.SetMinorRadius(minorRadius);

                Handle(Geom_Ellipse) projCurve = new Geom_Ellipse(elipsDest);

                if (isFullCircle(curve)) {
                    // projection is an ellipse
                    auto* ellipse = new Part::GeomEllipse();
                    ellipse->setHandle(projCurve);
                    GeometryFacade::setConstruction(ellipse, true);
                    geos.emplace_back(ellipse);
                }
                else {
                    // projection is an arc of ellipse
                    auto* aoe = new Part::GeomArcOfEllipse();
                    double firstParam, lastParam;
                    // adjust the parameter range to get the correct arc
                    adjustParameterRange(edge, gPlane, mov, projCurve, firstParam, lastParam);

                    Handle(Geom_TrimmedCurve) trimmedCurve = new Geom_TrimmedCurve(projCurve, firstParam, lastParam);
                    aoe->setHandle(trimmedCurve);
                    GeometryFacade::setConstruction(aoe, true);
                    geos.emplace_back(aoe);
                }
            }
        }
    }
    else if (curve.GetType() == GeomAbs_Ellipse) {

        gp_Pnt P1 = curve.Value(curve.FirstParameter());
        gp_Pnt P2 = curve.Value(curve.LastParameter());
        gp_Elips elipsOrig = curve.Ellipse();
        gp_Elips elipsDest;
        gp_Pnt origCenter = elipsOrig.Location();
        gp_Pnt destCenter = ProjPointOnPlane_UVN(origCenter, sketchPlane).XYZ();

        gp_Dir origAxisMajorDir = elipsOrig.XAxis().Direction();
        gp_Vec origAxisMajor = elipsOrig.MajorRadius() * gp_Vec(origAxisMajorDir);
        gp_Dir origAxisMinorDir = elipsOrig.YAxis().Direction();
        gp_Vec origAxisMinor = elipsOrig.MinorRadius() * gp_Vec(origAxisMinorDir);

        // Here, it used to be a test for parallel direction between the sketchplane and
        // the elipsOrig, in which the original ellipse would be copied and translated
        // to the new position. The problem with that approach is that for the sketcher
        // the normal vector is always (0,0,1). If the original ellipse was not on the
        // XY plane, the copy will not be either. Then, the dimensions would be wrong
        // because of the different major axis direction (which is not projected on the
        // XY plane). So here, we default to the more general ellipse construction
        // algorithm.
        //
        // Doing that solves:
        // https://forum.freecad.org/viewtopic.php?f=3&t=55284#p477522

        // GENERAL ELLIPSE CONSTRUCTION ALGORITHM
        //
        // look for major axis of projected ellipse
        //
        // t is the parameter along the origin ellipse
        //   OM(t) = origCenter
        //           + majorRadius * cos(t) * origAxisMajorDir
        //           + minorRadius * sin(t) * origAxisMinorDir
        gp_Vec2d PA = ProjVecOnPlane_UV(origAxisMajor, sketchPlane);
        gp_Vec2d PB = ProjVecOnPlane_UV(origAxisMinor, sketchPlane);
        double t_max = 0.0;
        const double dPAPB = PA.SquareMagnitude() - PB.SquareMagnitude();

        // For dPAPB=0 it's a circle where we use t_max=0
        if (std::fabs(dPAPB) > std::numeric_limits<double>::epsilon()) {
            t_max = 2.0 * PA.Dot(PB) / (PA.SquareMagnitude() - PB.SquareMagnitude());
            t_max = 0.5 * atan(t_max);// gives new major axis is most cases, but not all
        }
        double t_min = t_max + 0.5 * pi;

        // ON_max = OM(t_max) gives the point, which projected on the sketch plane,
        //     becomes the apoapse of the projected ellipse.
        gp_Vec ON_max = origAxisMajor * cos(t_max) + origAxisMinor * sin(t_max);
        gp_Vec ON_min = origAxisMajor * cos(t_min) + origAxisMinor * sin(t_min);
        gp_Vec destAxisMajor = ProjVecOnPlane_UVN(ON_max, sketchPlane);
        gp_Vec destAxisMinor = ProjVecOnPlane_UVN(ON_min, sketchPlane);

        double RDest = destAxisMajor.Magnitude();
        double rDest = destAxisMinor.Magnitude();

        if (RDest < rDest) {
            double rTmp = rDest;
            rDest = RDest;
            RDest = rTmp;
            gp_Vec axisTmp = destAxisMajor;
            destAxisMajor = destAxisMinor;
            destAxisMinor = axisTmp;
        }

        double sens = sketchAx3.Direction().Dot(elipsOrig.Position().Direction());
        int flip = sens > 0.0 ? 1.0 : -1.0;
        gp_Ax2 destCurveAx2(destCenter, gp_Dir(0, 0, flip), gp_Dir(destAxisMajor));

        // projection is a circle
        if ((RDest - rDest) < (double)Precision::Confusion()) {
            Handle(Geom_Circle) projCurve = new Geom_Circle(destCurveAx2, 0.5 * (rDest + RDest));
            if (P1.SquareDistance(P2) < Precision::Confusion()) {
                auto* circle = new Part::GeomCircle();
                circle->setHandle(projCurve);
                GeometryFacade::setConstruction(circle, true);
                geos.emplace_back(circle);
            }
            else {
                auto* arc = new Part::GeomArcOfCircle();
                double firstParam, lastParam;
                adjustParameterRange(edge, gPlane, mov, projCurve, firstParam, lastParam);
                Handle(Geom_TrimmedCurve) tCurve = new Geom_TrimmedCurve(projCurve, firstParam, lastParam);
                arc->setHandle(tCurve);
                GeometryFacade::setConstruction(arc, true);
                geos.emplace_back(arc);
            }
        }
        else {
            if (sketchPlane.Position().Direction().IsNormal(
                elipsOrig.Position().Direction(), Precision::Angular())) {
                gp_Vec start = gp_Vec(destCenter.XYZ()) + destAxisMajor;
                gp_Vec end = gp_Vec(destCenter.XYZ()) - destAxisMajor;

                auto* projectedSegment = new Part::GeomLineSegment();
                projectedSegment->setPoints(
                    Base::Vector3d(start.X(), start.Y(), start.Z()),
                    Base::Vector3d(end.X(), end.Y(), end.Z()));
                GeometryFacade::setConstruction(projectedSegment, true);
                geos.emplace_back(projectedSegment);
            }
            else {

                elipsDest.SetPosition(destCurveAx2);
                elipsDest.SetMajorRadius(destAxisMajor.Magnitude());
                elipsDest.SetMinorRadius(destAxisMinor.Magnitude());

                Handle(Geom_Ellipse) projCurve = new Geom_Ellipse(elipsDest);

                if (P1.SquareDistance(P2) < Precision::Confusion()) {
                    auto* ellipse = new Part::GeomEllipse();
                    ellipse->setHandle(projCurve);
                    GeometryFacade::setConstruction(ellipse, true);
                    geos.emplace_back(ellipse);
                }
                else {
                    auto* aoe = new Part::GeomArcOfEllipse();
                    double firstParam, lastParam;
                    adjustParameterRange(edge, gPlane, mov, projCurve, firstParam, lastParam);

                    Handle(Geom_TrimmedCurve) tCurve = new Geom_TrimmedCurve(projCurve, firstParam, lastParam);
                    aoe->setHandle(tCurve);
                    GeometryFacade::setConstruction(aoe, true);
                    geos.emplace_back(aoe);
                }
            }
        }
    }
    else {
        gp_Pln plane;
        auto shape = Part::TopoShape(edge);
        bool planar = shape.findPlane(plane);

        // Check if the edge is planar and plane is perpendicular to the projection plane
        if (planar && plane.Axis().IsNormal(sketchPlane.Axis(), Precision::Angular())) {
            // Project an edge to a line. Only works if the edge is planar and its plane is
            // perpendicular to the projection plane. OCC has trouble handling
            // BSpline projection to a straight line. Although it does correctly projects
            // the line including extreme bounds (not always a case), it will produce a BSpline with degree
            // more than one.
            //
            // The work around here is to use an aligned bounding box of the edge to get
            // the projection of the extremum points to construct the projected line.

            // First, transform the shape to the projection plane local coordinates.
            shape.setPlacement(invPlm * shape.getPlacement());

            // Align the z axis of the edge plane to the y axis of the projection
            // plane,  so that the extreme bound will be a line in the x axis direction
            // of the projection plane.
            double angle = plane.Axis().Direction().Angle(sketchPlane.YAxis().Direction());

            gp_Trsf trsf;
            if (fabs(angle) > Precision::Angular()) {
                trsf.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(0, 0, 1)), angle);
                shape.move(trsf);
            }

            // Make a copy to work around OCC circular edge transformation bug
            shape = shape.makeElementCopy();

            // Obtain the bounding box (precise version!) and move the extreme points back
            // to the original location
            auto bbox = shape.getBoundBoxOptimal();
            if (!bbox.IsValid()){
                throw Base::CADKernelError("Invalid bounding box");
            }

            gp_Pnt p1(bbox.MinX, bbox.MinY, 0);
            gp_Pnt p2(bbox.MaxX, bbox.MaxY, 0);
            if (fabs(angle) > Precision::Angular()) {
                trsf.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(0, 0, 1)), -angle);
                p1.Transform(trsf);
                p2.Transform(trsf);
            }

            // The bounding box has no expansion in Y direction.
            // Due to possible rounding errors force the same y
            // value for both points. This fixes issue 25720
            Base::Vector3d P1(p1.X(), (p1.Y() + p2.Y()) / 2.0, 0);
            Base::Vector3d P2(p2.X(), (p1.Y() + p2.Y()) / 2.0, 0);

            // check for degenerated case when the line is collapsed to a point
            if (p1.SquareDistance(p2) < Precision::SquareConfusion()) {
                auto* point = new Part::GeomPoint((P1 + P2) / 2);
                GeometryFacade::setConstruction(point, true);
                geos.emplace_back(point);
            }
            else {
                auto* projectedSegment = new Part::GeomLineSegment();
                projectedSegment->setPoints(P1, P2);
                GeometryFacade::setConstruction(projectedSegment, true);
                geos.emplace_back(projectedSegment);
            }
        }
        else {
            try {
                Part::TopoShape projShape;
                // Projection of the edge on parallel plane to the sketch plane is edge itself
                // all we need to do is match coordinate systems
                // for some reason OCC doesn't like to project a planar B-Spline to a plane parallel to it
                if (planar && plane.Axis().Direction().IsParallel(sketchPlane.Axis().Direction(), Precision::Confusion())) {
                    TopoDS_Edge projEdge = edge;

                    // We need to trim the curve in case we are projecting a B-Spline segment
                    if(curve.GetType() == GeomAbs_BSplineCurve){
                        double Param1 = curve.FirstParameter();
                        double Param2 = curve.LastParameter();

                        if (Param1 > Param2){
                            std::swap(Param1, Param2);
                        }

                        // trim curve in case we are projecting a segment
                        auto bsplineCurve = curve.BSpline();
                        if(Param2 - Param1 > Precision::Confusion()){
                            bsplineCurve->Segment(Param1, Param2);
                            projEdge = BRepBuilderAPI_MakeEdge(bsplineCurve).Edge();
                        }
                    }

                    projShape.setShape(projEdge);

                    // We can't use gp_Pln::Distance() because we need to
                    // know which side the plane is regarding the sketch
                    const gp_Pnt& aP = sketchPlane.Location();
                    const gp_Pnt& aLoc = plane.Location ();
                    const gp_Dir& aDir = plane.Axis().Direction();
                    double d = (aDir.X() * (aP.X() - aLoc.X()) +
                            aDir.Y() * (aP.Y() - aLoc.Y()) +
                            aDir.Z() * (aP.Z() - aLoc.Z()));

                    gp_Trsf trsf;
                    trsf.SetTranslation(gp_Vec(aDir) * d);
                    projShape.transformShape(Part::TopoShape::convert(trsf), /*copy*/false);
                } else {
                    // When planes not parallel or perpendicular, or edge is not planar
                    // normal projection is working just fine
                    BRepOffsetAPI_NormalProjection mkProj(aProjFace);
                    mkProj.Add(edge);
                    mkProj.Build();

                    projShape.setShape(mkProj.Projection());
                }
                if (!projShape.isNull() && projShape.hasSubShape(TopAbs_EDGE)) {
                    for (auto &e : projShape.getSubTopoShapes(TopAbs_EDGE)) {
                        // Transform copy of the edge to the sketch plane local coordinates
                        e.transformShape(invPlm.toMatrix(), /*copy*/true, /*checkScale*/true);
                        TopoDS_Edge projEdge = TopoDS::Edge(e.getShape());
                        processEdge2(projEdge, geos);
                    }
                }
            }
            catch (Standard_Failure& e) {
                throw Base::CADKernelError(e.GetMessageString());
            }
        }
    }
}

std::vector<TopoDS_Shape> projectShape(const TopoDS_Shape& inShape, const gp_Ax3& viewAxis)
{
    std::vector<TopoDS_Shape> res;
    Handle(HLRBRep_Algo) brep_hlr;
    try {
        brep_hlr = new HLRBRep_Algo();
        brep_hlr->Add(inShape);

        gp_Trsf aTrsf;
        aTrsf.SetTransformation(viewAxis);
        HLRAlgo_Projector projector(aTrsf, false, 1);

        brep_hlr->Projector(projector);
        brep_hlr->Update();
        brep_hlr->Hide();
    }
    catch (const Standard_Failure& e) {
        Base::Console().error("GO::projectShape - OCC error - %s - while projecting shape\n",
            e.GetMessageString());
        throw Base::RuntimeError("SketchObject::projectShape - OCC error");
    }
    catch (...) {
        throw Base::RuntimeError("SketchObject::projectShape - unknown error");
    }

    try {
        HLRBRep_HLRToShape hlrToShape(brep_hlr);
        if (!hlrToShape.VCompound().IsNull()) {
            //TopAbs_COMPOUND to TopAbs_EDGE
            res.push_back(hlrToShape.VCompound());
        }

        if (!hlrToShape.Rg1LineVCompound().IsNull()) {
            res.push_back(hlrToShape.Rg1LineVCompound());
        }

        if (!hlrToShape.OutLineVCompound().IsNull()) {
            res.push_back(hlrToShape.OutLineVCompound());
        }

        if (!hlrToShape.IsoLineVCompound().IsNull()) {
            res.push_back(hlrToShape.IsoLineVCompound());
        }

        if (!hlrToShape.HCompound().IsNull()) {
            res.push_back(hlrToShape.HCompound());
        }

        if (!hlrToShape.Rg1LineHCompound().IsNull()) {
            res.push_back(hlrToShape.Rg1LineHCompound());
        }

        if (!hlrToShape.OutLineHCompound().IsNull()) {
            res.push_back(hlrToShape.OutLineHCompound());
        }

        if (!hlrToShape.IsoLineHCompound().IsNull()) {
            res.push_back(hlrToShape.IsoLineHCompound());
        }
    }
    catch (const Standard_Failure&) {
        throw Base::RuntimeError(
            "SketchObject::projectShape - OCC error occurred while extracting edges");
    }
    catch (...) {
        throw Base::RuntimeError(
            "SketchObject::projectShape - unknown error occurred while extracting edges");
    }

    return res;
}

void processFace (const Rotation& invRot,
                  const Placement& invPlm,
                  const gp_Trsf& mov,
                  const gp_Pln& sketchPlane,
                  const Handle(Geom_Plane)& gPlane,
                  gp_Ax3& sketchAx3,
                  TopoDS_Shape& aProjFace,
                  std::vector<std::unique_ptr<Part::Geometry>>& geos,
                  TopoDS_Shape& refSubShape,
                  const std::vector<std::string>& edgeSources)
{
    const TopoDS_Face& face = TopoDS::Face(refSubShape);
    BRepAdaptor_Surface surface(face);
    if (surface.GetType() == GeomAbs_Plane) {
        // Check that the plane is perpendicular to the sketch plane
        Geom_Plane plane = surface.Plane();
        gp_Dir dnormal = plane.Axis().Direction();
        gp_Dir snormal = sketchPlane.Axis().Direction();

        // Extract all edges from the face
        TopExp_Explorer edgeExp;
        std::size_t n = 0;
        for (edgeExp.Init(face, TopAbs_EDGE); edgeExp.More(); edgeExp.Next(), ++n) {
            TopoDS_Edge edge = TopoDS::Edge(edgeExp.Current());
            // Process each edge
            const std::size_t first = geos.size();
            processEdge(edge, geos, gPlane, invPlm, mov, sketchPlane, invRot, sketchAx3, aProjFace);
            // FreeCAD-CH (ops#264 e2): each geometry records the edge it came from (the
            // explorer's order on the unmoved face, which the names were read in)
            if (n < edgeSources.size()) {
                for (std::size_t k = first; k < geos.size(); ++k) {
                    ExternalGeometryFacade::getFacade(geos[k].get())->setSource(edgeSources[n]);
                }
            }
        }

        if (fabs(dnormal.Angle(snormal) - std::numbers::pi/2) < Precision::Confusion()) {
            // The face is normal to the sketch plane
            // We don't want to keep the projection of all the edges of the face.
            // We need a single line that goes from min to max of all the projections.
            bool initialized = false;
            Vector3d start, end;
            // Lambda to determine if a point should replace start or end
            auto updateExtremes = [&](const Vector3d& point) {
                if ((point - start).Length() < (point - end).Length()) {
                    // `point` is closer to `start` than `end`, check if it's further out than `start`
                    if ((point - end).Length() > (end - start).Length()) {
                        start = point;
                    }
                }
                else {
                    // `point` is closer to `end`, check if it's further out than `end`
                    if ((point - start).Length() > (end - start).Length()) {
                        end = point;
                    }
                }
            };
            for (auto& geo : geos) {
                auto* line = dynamic_cast<Part::GeomLineSegment*>(geo.get());
                if (!line) {
                    // The face being normal to the sketch, we should have
                    // only lines. This is just a fail-safe in case there's a
                    // straight bspline or something like this.
                    continue;
                }
                if (!initialized) {
                    start = line->getStartPoint();
                    end = line->getEndPoint();
                    initialized = true;
                    continue;
                }

                updateExtremes(line->getStartPoint());
                updateExtremes(line->getEndPoint());
            }
            if (initialized) {
                auto* unifiedLine = new Part::GeomLineSegment();
                unifiedLine->setPoints(start, end);
                geos.clear(); // Clear other segments
                geos.emplace_back(unifiedLine);
            }
            else {
                // In case we have not initialized, perhaps the projections were
                // only straight bsplines.
                // Then we use the old method that will give a line with 20000 length:
                // Get vector that is normal to both sketch plane normal and plane normal.
                // This is the line's direction
                gp_Dir lnormal = dnormal.Crossed(snormal);
                BRepBuilderAPI_MakeEdge builder(gp_Lin(plane.Location(), lnormal));
                builder.Build();
                if (builder.IsDone()) {
                    const TopoDS_Edge& edge = TopoDS::Edge(builder.Shape());
                    BRepAdaptor_Curve curve(edge);
                    if (curve.GetType() == GeomAbs_Line) {
                        geos.emplace_back(projectLine(curve, gPlane, invPlm));
                    }
                }
            }
        }
    }
    else {
        std::vector<TopoDS_Shape> res = projectShape(face, sketchAx3);
        for (auto& resShape : res) {
            TopExp_Explorer explorer(resShape, TopAbs_EDGE);
            while (explorer.More()) {
                TopoDS_Edge projEdge = TopoDS::Edge(explorer.Current());
                processEdge2(projEdge, geos);
                explorer.Next();
            }
        }
    }
}

// the error of a sketch whose external geometry lost its element (ops#72), or whose link no
// longer gives a geometry with constraints on it (ops#264 e2); defined below
std::string missingReferenceMessage(
    const App::Document* doc,
    const std::vector<std::pair<std::string, std::vector<std::size_t>>>& missingRefs,
    const std::vector<std::pair<std::string, std::vector<std::size_t>>>& lostRefs,
    const std::vector<App::DocumentObject*>& objects,
    const std::vector<std::string>& subElements,
    const std::vector<std::string>& keys);
std::string referenceText(const App::Document* doc,
                          const std::string& ref,
                          const std::vector<std::size_t>& indexes,
                          const std::vector<App::DocumentObject*>& objects,
                          const std::vector<std::string>& subElements,
                          const std::vector<std::string>& keys,
                          bool lost = false);

}  // anonymous namespace

namespace
{
// The type a link had, from its saved geometries alone, where only one type gives them (ops#140):
// saved geometries that are all points came from an intersection when the element is a face (its
// projection gives curves) or an edge with two or more distinct points (an edge's projection is
// one curve or one point; a line through the plane gives one point either way, and both types
// give two points at the same place).
std::optional<long> typeFromSavedGeometry(const std::string& sub,
                                          const std::vector<const Part::Geometry*>& saved)
{
    if (saved.empty() || !std::all_of(saved.begin(), saved.end(), [](const Part::Geometry* geo) {
            return geo->is<Part::GeomPoint>();
        })) {
        return std::nullopt;
    }
    // the element type is the last one named: a missing element reads "?Edge3", a mapped one
    // ends in its old name
    auto face = sub.rfind("Face");
    auto edge = sub.rfind("Edge");
    if (face != std::string::npos && (edge == std::string::npos || face > edge)) {
        return static_cast<long>(ExtType::Intersection);
    }
    if (edge == std::string::npos || saved.size() < 2) {
        return std::nullopt;
    }
    for (std::size_t i = 0; i < saved.size(); ++i) {
        for (std::size_t j = i + 1; j < saved.size(); ++j) {
            auto a = static_cast<const Part::GeomPoint*>(saved[i])->getPoint();
            auto b = static_cast<const Part::GeomPoint*>(saved[j])->getPoint();
            if (Base::Distance(a, b) < Precision::Confusion()) {
                return std::nullopt;
            }
        }
    }
    return static_cast<long>(ExtType::Intersection);
}

// How far a built geometry lies from a saved one of the same kind (ops#140): for points their
// distance; for full circles and ellipses the distance of the centres plus the radii's
// differences (and for ellipses how far the turn of the major axis moves the curve), which
// doesn't depend on where their parameter starts; for other curves the largest distance of a
// point sampled on one from the other, both ways, each to the nearer of the foot and the ends.
double distanceFromSaved(const Part::Geometry* geo, const Part::Geometry* saved)
{
    if (auto* point = freecad_cast<const Part::GeomPoint*>(geo)) {
        return Base::Distance(point->getPoint(),
                              static_cast<const Part::GeomPoint*>(saved)->getPoint());
    }
    if (auto* circle = freecad_cast<const Part::GeomCircle*>(geo)) {
        auto* other = static_cast<const Part::GeomCircle*>(saved);
        return Base::Distance(circle->getCenter(), other->getCenter())
            + std::abs(circle->getRadius() - other->getRadius());
    }
    if (auto* ellipse = freecad_cast<const Part::GeomEllipse*>(geo)) {
        auto* other = static_cast<const Part::GeomEllipse*>(saved);
        // and how far turning the major axis moves the curve, about (a - b) sin(angle): nothing
        // for a near-circular ellipse, whose axis direction is noise (ops#237). The axis has no
        // sense, so the angle is at most a quarter turn.
        double angle = ellipse->getMajorAxisDir().GetAngle(other->getMajorAxisDir());
        angle = std::min(angle, std::numbers::pi - angle);
        const double eccentricity =
            std::max(ellipse->getMajorRadius() - ellipse->getMinorRadius(),
                     other->getMajorRadius() - other->getMinorRadius());
        return Base::Distance(ellipse->getCenter(), other->getCenter())
            + std::abs(ellipse->getMajorRadius() - other->getMajorRadius())
            + std::abs(ellipse->getMinorRadius() - other->getMinorRadius())
            + eccentricity * std::sin(angle);
    }
    auto* curve = freecad_cast<const Part::GeomCurve*>(geo);
    auto* savedCurve = freecad_cast<const Part::GeomCurve*>(saved);
    if (!curve || !savedCurve) {
        return std::numeric_limits<double>::infinity();
    }
    // the largest distance of a point of `from` from the curve `to`
    auto oneWay = [](const Part::GeomCurve* from, const Part::GeomCurve* to) {
        constexpr int samples = 8;
        const double first = from->getFirstParameter();
        const double last = from->getLastParameter();
        const double toFirst = to->getFirstParameter();
        const double toLast = to->getLastParameter();
        double distance = 0.0;
        for (int k = 0; k <= samples; ++k) {
            const auto p = from->pointAtParameter(first + (last - first) * k / samples);
            double u = 0.0;
            if (!to->closestParameter(p, u)) {
                return std::numeric_limits<double>::infinity();
            }
            // closestParameter() gives an orthogonal foot when there is one, which on an arc
            // over half a turn can be the far side; an end can be nearer
            const double nearest = std::min({Base::Distance(p, to->pointAtParameter(u)),
                                             Base::Distance(p, to->pointAtParameter(toFirst)),
                                             Base::Distance(p, to->pointAtParameter(toLast))});
            distance = std::max(distance, nearest);
        }
        return distance;
    };
    return std::max(oneWay(curve, savedCurve), oneWay(savedCurve, curve));
}

// "0", "0 and 1", "0, 1 and 2": the types, for a warning
std::string typeList(const std::vector<long>& types)
{
    std::string text;
    for (std::size_t k = 0; k < types.size(); ++k) {
        if (k > 0) {
            text += k + 1 == types.size() ? " and " : ", ";
        }
        text += std::to_string(types[k]);
    }
    return text;
}

// How far apart two geometries of the same type lie, for pairing a link's geometries (ops#264
// e2): lines by their supporting lines (each end of one from the other's line), only where they
// overlap (a chamfer shortens its neighbours, so their ends move); arcs of circles by centre and
// radius, only where they overlap; anything else as distanceFromSaved() compares it
double placeDistance(const Part::Geometry* a, const Part::Geometry* b, double tolerance)
{
    constexpr double apart = std::numeric_limits<double>::infinity();
    if (auto* line = freecad_cast<const Part::GeomLineSegment*>(a)) {
        auto* other = static_cast<const Part::GeomLineSegment*>(b);
        const auto a0 = line->getStartPoint();
        const auto b0 = other->getStartPoint();
        const auto b1 = other->getEndPoint();
        const auto along = line->getEndPoint() - a0;
        const auto otherAlong = b1 - b0;
        if (along.Length() < tolerance || otherAlong.Length() < tolerance) {
            return apart;
        }
        const double distance = std::max({b0.DistanceToLine(a0, along),
                                          b1.DistanceToLine(a0, along),
                                          a0.DistanceToLine(b0, otherAlong),
                                          line->getEndPoint().DistanceToLine(b0, otherAlong)});
        auto unit = along;
        unit.Normalize();
        const double s0 = (b0 - a0) * unit;
        const double s1 = (b1 - a0) * unit;
        const double overlap =
            std::min(along.Length(), std::max(s0, s1)) - std::max(0.0, std::min(s0, s1));
        return overlap > tolerance ? distance : apart;
    }
    if (auto* arc = freecad_cast<const Part::GeomArcOfCircle*>(a)) {
        auto* other = static_cast<const Part::GeomArcOfCircle*>(b);
        // the middle of one on the other
        auto onOther = [tolerance](const Part::GeomArcOfCircle* from,
                                   const Part::GeomArcOfCircle* to) {
            const auto middle =
                from->pointAtParameter((from->getFirstParameter() + from->getLastParameter()) / 2);
            double u = 0.0;
            return to->closestParameter(middle, u)
                && Base::Distance(middle, to->pointAtParameter(u)) <= tolerance;
        };
        if (!onOther(arc, other) && !onOther(other, arc)) {
            return apart;
        }
        return Base::Distance(arc->getCenter(), other->getCenter())
            + std::abs(arc->getRadius() - other->getRadius());
    }
    // other open curves (B-splines and arcs of conics, many of them from a face projected through
    // hidden lines) only with the same ends, either way round: distanceFromSaved() samples both
    // curves, too slow to try every pair of a large link
    if (auto* curve = freecad_cast<const Part::GeomBoundedCurve*>(a)) {
        auto* other = static_cast<const Part::GeomBoundedCurve*>(b);
        const auto a0 = curve->getStartPoint();
        const auto a1 = curve->getEndPoint();
        const auto b0 = other->getStartPoint();
        const auto b1 = other->getEndPoint();
        const bool same =
            Base::Distance(a0, b0) <= tolerance && Base::Distance(a1, b1) <= tolerance;
        const bool reversed =
            Base::Distance(a0, b1) <= tolerance && Base::Distance(a1, b0) <= tolerance;
        if (!same && !reversed) {
            return apart;
        }
    }
    return distanceFromSaved(a, b);
}

// FreeCAD-CH (ops#264 e2, class E's E1; I-R2): which of a link's old geometries of one kind each
// new one continues, as an index into `olds` (-1: none, it is new). Before, the k-th new one took
// the k-th old Id, and a constraint followed whatever edge came k-th now (a corner cut before it
// moved it to the next edge, silently). In turn:
// - one geometry before and after, of the same type: the link's reference names it (and its
//   resolution carries any warning);
// - the same type at the same place: within half the tolerance, and every other candidate either
//   way beyond it (as carbon copy pairs, PR 260);
// - among those at the same place with several candidates within the tolerance (collinear
//   pieces, coincident curves), the source edge's mapped name (Source), unique on both sides. A
//   name alone is no evidence: the Sketcher gives a line drawn again the Id, and so the name, of
//   a deleted line whose ends were in the same places (SketchObject::generateId), which is the
//   edge on the other side when the lines between were reversed (fork PR 384's review, round 1);
// - by position, only where the link's order is evidence: the same count and types in the same
//   order, the link's reference resolved by history this recompute (`byHistory`: exactly, or by
//   the solver at tier 0-1 without a guess; a face found by its place may be a redrawn profile,
//   whose edges come in another order, review CC1), and every pair made above at equal
//   positions.
// An old geometry left over is the caller's: it goes, or breaks where constraints are on it.
std::vector<int> pairGeometries(const std::vector<const Part::Geometry*>& olds,
                                const std::vector<const Part::Geometry*>& news,
                                bool byHistory)
{
    std::vector<int> taken(news.size(), -1);
    std::vector<bool> used(olds.size(), false);
    auto sameType = [&](std::size_t j, std::size_t k) {
        return olds[j] && olds[j]->getTypeId() == news[k]->getTypeId();
    };
    auto match = [&](std::size_t j, std::size_t k) {
        taken[k] = static_cast<int>(j);
        used[j] = true;
    };
    if (olds.size() == 1 && news.size() == 1) {
        if (sameType(0, 0)) {
            match(0, 0);
        }
        return taken;
    }

    constexpr double tolerance = 10 * Precision::Confusion();
    std::vector<std::vector<double>> distance(
        olds.size(),
        std::vector<double>(news.size(), std::numeric_limits<double>::infinity()));
    for (std::size_t j = 0; j < olds.size(); ++j) {
        for (std::size_t k = 0; k < news.size(); ++k) {
            if (sameType(j, k)) {
                distance[j][k] = placeDistance(olds[j], news[k], tolerance);
            }
        }
    }
    std::vector<std::pair<std::size_t, std::size_t>> agreed;
    for (std::size_t j = 0; j < olds.size(); ++j) {
        for (std::size_t k = 0; k < news.size(); ++k) {
            if (distance[j][k] > tolerance / 2) {
                continue;
            }
            bool clear = true;
            for (std::size_t other = 0; other < news.size() && clear; ++other) {
                clear = other == k || distance[j][other] > tolerance;
            }
            for (std::size_t other = 0; other < olds.size() && clear; ++other) {
                clear = other == j || distance[other][k] > tolerance;
            }
            if (clear) {
                agreed.emplace_back(j, k);
            }
        }
    }
    for (const auto& [j, k] : agreed) {
        match(j, k);
    }

    auto sourceOf = [](const Part::Geometry* geo) {
        return geo ? ExternalGeometryFacade::getFacade(geo)->getSource() : std::string();
    };
    std::map<std::string, std::vector<std::size_t>> oldSources;
    std::map<std::string, std::vector<std::size_t>> newSources;
    for (std::size_t j = 0; j < olds.size(); ++j) {
        if (auto source = sourceOf(olds[j]); !source.empty() && !used[j]) {
            oldSources[source].push_back(j);
        }
    }
    for (std::size_t k = 0; k < news.size(); ++k) {
        if (auto source = sourceOf(news[k]); !source.empty() && taken[k] < 0) {
            newSources[source].push_back(k);
        }
    }
    for (const auto& [source, ks] : newSources) {
        auto it = oldSources.find(source);
        if (ks.size() == 1 && it != oldSources.end() && it->second.size() == 1
            && distance[it->second.front()][ks.front()] <= tolerance / 2) {
            match(it->second.front(), ks.front());
        }
    }

    if (!byHistory || olds.size() != news.size()) {
        return taken;
    }
    for (std::size_t k = 0; k < news.size(); ++k) {
        if (!sameType(k, k) || (taken[k] >= 0 && taken[k] != static_cast<int>(k))) {
            return taken;
        }
    }
    for (std::size_t k = 0; k < news.size(); ++k) {
        if (taken[k] < 0 && !used[k]) {
            match(k, k);
        }
    }
    return taken;
}
}  // namespace

void SketchObject::rebuildExternalGeometry(std::optional<ExternalToAdd> extToAdd, bool typesOnly)
{
    Base::StateLocker lock(managedoperation, true); // no need to check input data validity as this is an sketchobject managed operation.

    fixMissingAxisInExternalGeo();

    // Remember which way the projected lines currently run. Signed constraints record which side
    // of a line their subject sits on, and that side is expressed relative to the line direction,
    // so a projection that comes back reversed would otherwise drag the sketch to the other side.
    std::map<long, Base::Vector3d> previousLineDirections;
    for (const auto& geo : ExternalGeo.getValues()) {
        if (auto* line = freecad_cast<const Part::GeomLineSegment*>(geo)) {
            previousLineDirections[GeometryFacade::getId(geo)] =
                line->getEndPoint() - line->getStartPoint();
        }
    }

    // Analyze the state of existing external geometries to infer the desired state for new ones.
    // If any geometry from a source link is "defining", we'll treat the whole link as "defining".
    std::map<std::string, bool> linkIsDefiningMap;
    for (const auto& geo : ExternalGeo.getValues()) {
        auto egf = ExternalGeometryFacade::getFacade(geo);
        if (!egf->getRef().empty()) {
            bool isDefining = egf->testFlag(ExternalGeometryExtension::Defining);
            if (linkIsDefiningMap.find(egf->getRef()) == linkIsDefiningMap.end()) {
                linkIsDefiningMap[egf->getRef()] = isDefining;
            }
            else {
                linkIsDefiningMap[egf->getRef()] = linkIsDefiningMap[egf->getRef()] && isDefining;
            }
        }
    }

    // get the actual lists of the externals
    auto Types       = ExternalTypes.getValues();
    auto Objects     = ExternalGeometry.getValues();
    auto SubElements = ExternalGeometry.getSubValues();
    if (externalGeoRef.size() != Objects.size()) {
        throw Base::RuntimeError("Inconsistency with external geometries");
    }
    auto keys = externalGeoRef;
    const std::size_t linkCount = Objects.size();
    // A type list longer than the links was saved before ops#140, when deleting a link left its
    // type behind: the types after it belong to other links. On open (typesOnly) each link takes
    // the type that gives back its saved geometries (below). Only then, and later only for a link
    // the open couldn't decide whose geometry is still the saved one (flagged Missing): otherwise
    // the saved geometry is the one before an edit of the source, which a correct type no longer
    // gives. An open of a list that ends in the mark an earlier open left repairs only the links
    // that are still undecided (missing or without saved geometry), not the ones decided then.
    // FreeCAD-CH (PR 277 round 8): so does a list without the mark whose saved geometry says a
    // link waits (flagged as built from a guess or undecided): saved by fork-0.6.1, which doesn't
    // know the flags, settled such links to the type at their index and dropped the mark. It
    // repairs only those links (flagsOnly)
    const std::set<std::string> flaggedWaiting =
        typesOnly ? waitingTypeRefs(ExternalGeo.getValues()) : std::set<std::string> {};
    const bool openRepair = typesOnly && (Types.size() > linkCount || !flaggedWaiting.empty());
    const bool flagsOnly = openRepair && Types.size() <= linkCount;
    // On open (typesOnly) a link whose geometry was saved before ops#264 also gets its kinds
    // (below, ops#269)
    const bool kindless = std::any_of(ExternalGeo.getValues().begin(),
                                      ExternalGeo.getValues().end(),
                                      [](const Part::Geometry* geo) {
                                          return !ExternalGeometryFacade::getFacade(geo)
                                                      ->getRef()
                                                      .empty()
                                              && !kindOf(geo);
                                      });
    if (typesOnly && !openRepair && !kindless) {
        return;
    }
    // the kinds found on open for saved geometry without them, by index in ExternalGeo
    std::map<std::size_t, bool> savedKinds;
    // the indexes in ExternalGeo of saved geometry an open leaves undecided: flagged undecided
    // (TypeUndecided), so a later open repairs the link again (verification 3.8) and the link
    // waits through a freeze, a park or a drop, which clear a missing mark (PR 277 verification
    // 5.1, round 7), while the geometry is still matched as evidence of the type
    std::set<std::size_t> savedUndecided;
    // those whose element is absent, marked missing as well, so the rebuild that finds the
    // element again matches them (verification 4.7)
    std::set<std::size_t> savedAbsent;
    // and saved geometry flagged undecided whose link the open has now decided
    std::set<std::size_t> savedDecided;
    // the keys of the links the open decided whose saved geometry waited
    std::set<std::string> decidedOnOpen;
    const bool laterOpen = flagsOnly
        || (openRepair
            && std::find(Types.begin() + static_cast<std::ptrdiff_t>(linkCount), Types.end(),
                         pendingTypeRepairMark)
                != Types.end());
    if (openRepair) {
        undecidedTypeKeys.clear();
    }
    bool typesRepaired = false;  // a full rebuild decided an undecided link's type
    // links whose sub-element is set again below, because their element is back (ops#72)
    std::set<std::size_t> relinked;

    // re-check for any missing geometry element. The code here has a side
    // effect that the linked external geometry will continue to work even if
    // ExternalGeometry is wiped out.
    std::set<std::string> rechecked;
    // the types of the links added back below, by index in Objects: the type their geometry was
    // built with, not the Projection default (an Intersection link came back a projection;
    // PR 277 verification 4.9)
    std::map<std::size_t, long> relinkedTypes;
    for(auto &geo : ExternalGeo.getValues()) {
        auto egf = ExternalGeometryFacade::getFacade(geo);
        if(egf->getRef().size() && egf->testFlag(ExternalGeometryExtension::Missing)) {
            const std::string &ref = egf->getRef();
            if (!rechecked.insert(ref).second) {
                continue;
            }
            auto pos = ref.find('.');
            if(pos == std::string::npos)
                continue;
            std::string objName = ref.substr(0,pos);
            auto obj = getDocument()->getObject(objName.c_str());
            if(!obj)
                continue;
            App::ElementNamePair elementName;
            App::GeoFeature::resolveElement(obj,ref.c_str()+pos+1,elementName);
            if(elementName.oldName.size()
                    && !App::GeoFeature::hasMissingElement(elementName.oldName.c_str()))
            {
                // A missing reference keeps its link (ops#72): point that link at the element
                // again. In a solver document the solver decides (it may have broken a reference
                // whose name still exists, ops#7), and App.repairReference re-points it. A link
                // dropped by an older version is added back.
                std::vector<const Part::Geometry*> named;
                for (const auto* other : ExternalGeo.getValues()) {
                    if (ExternalGeometryFacade::getFacade(other)->getRef() == ref) {
                        named.push_back(other);
                    }
                }
                const auto state = formedAgain(named);
                // FreeCAD-CH (ops#287, PR 277 round 5): the flag saved with the geometry, not the
                // key set in memory (which an undo, a reopen or a drop of the link lost), says
                // whether the link still waits for its type: built from a guess, it waits again,
                // its geometry stays flagged and the type list keeps the mark
                auto waitAgain = [&]() {
                    if (state.waits && !typesOnly) {
                        undecidedTypeKeys.insert(ref);
                        externalTypeRepairPending = true;
                    }
                };
                auto it = std::find(keys.begin(), keys.begin() + linkCount, ref);
                if (it != keys.begin() + linkCount) {
                    auto index = static_cast<std::size_t>(it - keys.begin());
                    if (Objects[index] == obj) {
                        if (SubElements[index] != elementName.oldName
                            && !ExternalGeometry.inSolverDocument()) {
                            SubElements[index] = elementName.oldName;
                            relinked.insert(index);
                        }
                        // its spelling changed or not: the flags say whether it waits, also when
                        // it was linked again from outside (PR 277 verification 6.1). The link
                        // being added is the user's choice of type: it no longer waits
                        if (!(extToAdd && extToAdd->obj == obj
                              && extToAdd->subname == SubElements[index])) {
                            waitAgain();
                        }
                    }
                    continue;
                }
                Objects.push_back(obj);
                SubElements.push_back(elementName.oldName);
                keys.push_back(ref);
                relinkedTypes[Objects.size() - 1] = state.type;
                waitAgain();
            }
        }
    }

    Base::Placement Plm = Placement.getValue();
    Base::Vector3d Pos = Plm.getPosition();
    Base::Rotation Rot = Plm.getRotation();
    Base::Rotation invRot = Rot.inverse();
    Base::Vector3d dN(0, 0, 1);
    Rot.multVec(dN, dN);
    Base::Vector3d dX(1, 0, 0);
    Rot.multVec(dX, dX);

    Base::Placement invPlm = Plm.inverse();
    Base::Matrix4D invMat = invPlm.toMatrix();
    gp_Trsf mov;
    mov.SetValues(invMat[0][0],
                  invMat[0][1],
                  invMat[0][2],
                  invMat[0][3],
                  invMat[1][0],
                  invMat[1][1],
                  invMat[1][2],
                  invMat[1][3],
                  invMat[2][0],
                  invMat[2][1],
                  invMat[2][2],
                  invMat[2][3]);

    gp_Ax3 sketchAx3(
        gp_Pnt(Pos.x, Pos.y, Pos.z), gp_Dir(dN.x, dN.y, dN.z), gp_Dir(dX.x, dX.y, dX.z));
    gp_Pln sketchPlane(sketchAx3);

    Handle(Geom_Plane) gPlane = new Geom_Plane(sketchPlane);
    BRepBuilderAPI_MakeFace mkFace(sketchPlane);
    TopoDS_Shape aProjFace = mkFace.Shape();

    // the entries after the links are no link's type
    if (Types.size() > linkCount) {
        Types.resize(linkCount);
    }
    bool undecided = false;
    Types.resize(Objects.size(), static_cast<long>(ExtType::Projection));
    for (const auto& [index, type] : relinkedTypes) {
        Types[index] = type;
    }

    std::set<std::string> refSet;
    // We use a vector here to keep the order (roughly) the same as ExternalGeometry
    std::vector<std::vector<std::unique_ptr<Part::Geometry> > > newGeos;
    newGeos.reserve(Objects.size());
    // for each entry of newGeos, the projections that go before the link's existing geometry:
    // those of a projection added to an intersection link (ops#260)
    std::vector<std::size_t> addedProjections;
    // for each entry of newGeos, how many of its geometries are the projection's (ops#264)
    std::vector<std::size_t> projSizes;
    // and its link's index in ExternalGeometry (ops#264 e2)
    std::vector<int> linkIndexes;
    // the key of the link that is being added to, whose new geometries keep the flags it gives
    std::string createdKey;
    for (int i=0; i < int(Objects.size()); i++) {
        const App::DocumentObject *Obj=Objects[i];
        const std::string &SubElement=SubElements[i];
        const std::string &key = keys[i];

        bool beingCreated = false;
        if (extToAdd) {
            beingCreated = extToAdd->obj == Obj && extToAdd->subname == SubElement;
        }

        bool projection = Types[i] == (int)ExtType::Projection || Types[i] == (int)ExtType::Both;
        bool intersection = Types[i] == (int)ExtType::Intersection || Types[i] == (int)ExtType::Both;

        // Skip frozen geometries
        bool frozen = false;
        bool sync = false;
        for(auto id : externalGeoRefMap[key]) {
            auto it = externalGeoMap.find(id);
            if(it != externalGeoMap.end()) {
                auto egf = ExternalGeometryFacade::getFacade(ExternalGeo[it->second]);
                if(egf->testFlag(ExternalGeometryExtension::Frozen)) {
                    frozen = true;
                }
                if (egf->testFlag(ExternalGeometryExtension::Sync)) {
                    sync = true;
                }
            }
        }
        // a frozen link, and one without its source, still get their type repaired below
        const bool keepFrozen = frozen && !sync;
        const bool hasSource = Obj && Obj->getNameInDocument();

        std::vector<std::unique_ptr<Part::Geometry> > geos;
        std::size_t projSize = 0;  // how many of geos the projection gave

        auto importVertex = [&](const TopoDS_Shape& refSubShape) {
            gp_Pnt P = BRep_Tool::Pnt(TopoDS::Vertex(refSubShape));
            GeomAPI_ProjectPointOnSurf proj(P, gPlane);
            P = proj.NearestPoint();
            Base::Vector3d p(P.X(), P.Y(), P.Z());
            invPlm.multVec(p, p);

            auto* point = new Part::GeomPoint(p);
            GeometryFacade::setConstruction(point, true);
            geos.emplace_back(point);
        };

        // builds the link's geometries into geos, as `projection` and `intersection` say
        auto build = [&]() {
            TopoDS_Shape refSubShape;
            // a face's edges' mapped names, in the face's order (ops#264 e2)
            std::vector<std::string> edgeSources;

            // Handles LCS ,resolve to actual datum object
            const App::DocumentObject* resolvedObj = Obj;
            if (Obj->isDerivedFrom<App::LocalCoordinateSystem>() && !SubElement.empty()) {
                auto* lcs = static_cast<const App::LocalCoordinateSystem*>(Obj);
                // get the datum element by name
                App::DatumElement* datum = lcs->getDatumElement(SubElement.c_str());
                if (datum) {
                    resolvedObj = datum;
                }
            }

            if (auto* datum = freecad_cast<const Part::Datum*>(resolvedObj)) {
                refSubShape = datum->getShape();
            }
            else if (auto* refObj = freecad_cast<const Part::Feature*>(resolvedObj)) {
                const Part::TopoShape& refShape = refObj->Shape.getShape();
                refSubShape = refShape.getSubShape(SubElement.c_str());
                // FreeCAD-CH (ops#264 e2): the shape drops the names; read them here, on the
                // unmoved shape, so a projected face's geometries can be paired by their source
                if (!refSubShape.IsNull() && refSubShape.ShapeType() == TopAbs_FACE) {
                    for (TopExp_Explorer exp(refSubShape, TopAbs_EDGE); exp.More(); exp.Next()) {
                        const int index = refShape.findShape(exp.Current());
                        const auto mapped = index > 0
                            ? refShape.getMappedName(Data::IndexedName::fromConst("Edge", index))
                            : Data::MappedName();
                        edgeSources.push_back(mapped ? mapped.toString() : std::string());
                    }
                }
            }
            else if (auto* pl = freecad_cast<const App::Plane*>(resolvedObj)) {
                Base::Vector3d base = pl->getBasePoint();
                Base::Vector3d normal = pl->getDirection();
                gp_Pln plane(gp_Pnt(base.x, base.y, base.z), gp_Dir(normal.x, normal.y, normal.z));
                BRepBuilderAPI_MakeFace fBuilder(plane);
                if (!fBuilder.IsDone())
                    throw Base::RuntimeError(
                        "Sketcher: addExternal(): Failed to build face from App::Plane");

                TopoDS_Face f = TopoDS::Face(fBuilder.Shape());
                refSubShape = f;
            }
            else if (auto* line = freecad_cast<const Part::DatumLine*>(resolvedObj)) {
                Base::Placement plm = line->Placement.getValue();
                Base::Vector3d base = plm.getPosition();
                Base::Vector3d dir = line->getDirection();
                gp_Lin l(gp_Pnt(base.x, base.y, base.z), gp_Dir(dir.x, dir.y, dir.z));
                BRepBuilderAPI_MakeEdge eBuilder(l);
                if (!eBuilder.IsDone()) {
                    throw Base::RuntimeError(
                        "Sketcher: addExternal(): Failed to build edge from Part::DatumLine");
                }

                TopoDS_Edge e = TopoDS::Edge(eBuilder.Shape());
                refSubShape = e;
            }
            else if (auto* point = freecad_cast<const Part::DatumPoint*>(resolvedObj)) {
                Base::Placement plm = point->Placement.getValue();
                Base::Vector3d base = plm.getPosition();
                gp_Pnt p(base.x, base.y, base.z);
                BRepBuilderAPI_MakeVertex eBuilder(p);
                if (!eBuilder.IsDone()) {
                    throw Base::RuntimeError(
                        "Sketcher: addExternal(): Failed to build vertex from Part::DatumPoint");
                }

                TopoDS_Vertex v = TopoDS::Vertex(eBuilder.Shape());
                refSubShape = v;
            }
            else if (auto* line = freecad_cast<const App::Line*>(resolvedObj)) {
                Base::Vector3d base = line->getBasePoint();
                Base::Vector3d dir = line->getDirection();
                gp_Lin l(gp_Pnt(base.x, base.y, base.z), gp_Dir(dir.x, dir.y, dir.z));
                BRepBuilderAPI_MakeEdge eBuilder(l);
                if (!eBuilder.IsDone()) {
                    throw Base::RuntimeError(
                        "Sketcher: addExternal(): Failed to build edge from App::Line");
                }

                TopoDS_Edge e = TopoDS::Edge(eBuilder.Shape());
                refSubShape = e;
            }
            else if (auto* point = freecad_cast<const App::Point*>(resolvedObj)) {
                Base::Vector3d base = point->getBasePoint();
                gp_Pnt p(base.x, base.y, base.z);
                BRepBuilderAPI_MakeVertex eBuilder(p);
                if (!eBuilder.IsDone()) {
                    throw Base::RuntimeError(
                        "Sketcher: addExternal(): Failed to build vertex from App::Point");
                }

                TopoDS_Vertex v = TopoDS::Vertex(eBuilder.Shape());
                refSubShape = v;
            }
            else {
                throw Base::TypeError(
                    "Datum feature type is not yet supported as external geometry for a sketch");
            }

            // read in its source's container: into this sketch's (FreeCAD-CH ops#331)
            if (!refSubShape.IsNull()) {
                const Base::Placement frame = externalFrame(Obj, SubElement);
                if (!isIdentityFrame(frame)) {
                    refSubShape = refSubShape.Moved(
                        TopLoc_Location(Part::TopoShape::convert(frame.toMatrix())));
                }
            }

            if (projection && !refSubShape.IsNull()) {
                switch (refSubShape.ShapeType()) {
                case TopAbs_FACE: {
                    processFace(invRot, invPlm, mov, sketchPlane, gPlane, sketchAx3, aProjFace, geos,
                                refSubShape, edgeSources);
                } break;
                case TopAbs_EDGE: {
                    const TopoDS_Edge& edge = TopoDS::Edge(refSubShape);
                    processEdge(edge, geos, gPlane, invPlm, mov, sketchPlane, invRot, sketchAx3, aProjFace);
                } break;
                case TopAbs_VERTEX: {
                    importVertex(refSubShape);
                } break;
                default:
                    throw Base::TypeError("Unknown type of geometry");
                    break;
                }
                if (beingCreated && !extToAdd->intersection) {
                    // We are adding the projections, so we need to initialize those
                    for (auto& geo : geos) {
                        auto egf = ExternalGeometryFacade::getFacade(geo.get());
                        egf->setFlag(ExternalGeometryExtension::Defining, extToAdd->defining);
                    }
                }
            }
            projSize = geos.size();

            if (intersection && !refSubShape.IsNull()) {
                FCBRepAlgoAPI_Section maker(refSubShape, sketchPlane);
                maker.Approximation(Standard_True);
                if (!maker.IsDone())
                    FC_THROWM(Base::CADKernelError, "Failed to get intersection");
                Part::TopoShape intersectionShape(maker.Shape());
                auto edges = intersectionShape.getSubTopoShapes(TopAbs_EDGE);
                for (const auto& s : edges) {
                    TopoDS_Edge edge = TopoDS::Edge(s.getShape());
                    processEdge(edge, geos, gPlane, invPlm, mov, sketchPlane, invRot, sketchAx3, aProjFace);
                }
                // Section of some face (e.g. sphere) produce more than one arcs
                // from the same circle. So we try to fit the arcs with a single
                // circle/arc. FreeCAD-CH (ops#264): only the section's, not a Both link's
                // projection before them.
                if (refSubShape.ShapeType() == TopAbs_FACE && geos.size() > projSize + 1) {
                    auto wires = Part::TopoShape().makeElementWires(edges);
                    if (wires.countSubShapes(TopAbs_WIRE) == 1) {
                        TopoDS_Vertex firstVertex, lastVertex;
                        BRepTools_WireExplorer exp(TopoDS::Wire(wires.getSubShape(TopAbs_WIRE, 1)));
                        firstVertex = exp.CurrentVertex();
                        while (!exp.More())
                            exp.Next();
                        lastVertex = exp.CurrentVertex();
                        gp_Pnt P1 = BRep_Tool::Pnt(firstVertex);
                        gp_Pnt P2 = BRep_Tool::Pnt(lastVertex);
                        std::vector<std::unique_ptr<Part::Geometry>> sections;
                        std::move(geos.begin() + static_cast<std::ptrdiff_t>(projSize),
                                  geos.end(), std::back_inserter(sections));
                        geos.resize(projSize);
                        if (auto geo = fitArcs(sections, P1, P2, ArcFitTolerance.getValue())) {
                            geos.emplace_back(geo);
                        }
                        else {
                            std::move(sections.begin(), sections.end(), std::back_inserter(geos));
                        }
                    }
                }
                for (const auto& s : intersectionShape.getSubShapes(TopAbs_VERTEX, TopAbs_EDGE)) {
                    importVertex(s);
                }

                if (beingCreated && extToAdd->intersection) {
                    // We are adding the projections, so we need to initialize those
                    for (size_t i = projSize; i < geos.size(); ++i) {
                        auto egf = ExternalGeometryFacade::getFacade(geos[i].get());
                        egf->setFlag(ExternalGeometryExtension::Defining, extToAdd->defining);
                    }
                }
            }
            // each geometry's kind, which the Ids are handed out by (ops#264)
            for (std::size_t k = 0; k < geos.size(); ++k) {
                setKind(geos[k].get(), k < projSize);
            }
        };

        std::vector<const Part::Geometry*> saved;
        bool savedMissing = false;
        // FreeCAD-CH (ops#287): saved geometry built from a guess (TypeGuessed) gives back the
        // guess, whichever type the link has: it decides nothing, and the link stays undecided
        bool savedGuessed = false;
        // and saved geometry an earlier open couldn't tell (TypeUndecided, round 7): the link
        // still waits, and its geometry is evidence
        bool savedWaits = false;
        if (openRepair || !undecidedTypeKeys.empty()) {
            for (long id : externalGeoRefMap[key]) {
                auto it = externalGeoMap.find(id);
                if (it != externalGeoMap.end()) {
                    saved.push_back(ExternalGeo[it->second]);
                    auto egf = ExternalGeometryFacade::getFacade(ExternalGeo[it->second]);
                    savedMissing = savedMissing || egf->testFlag(ExternalGeometryExtension::Missing);
                    savedGuessed =
                        savedGuessed || egf->testFlag(ExternalGeometryExtension::TypeGuessed);
                    savedWaits =
                        savedWaits || egf->testFlag(ExternalGeometryExtension::TypeUndecided);
                }
            }
            // in build order: geometry added to a kind since goes after the link's other
            // geometry in ExternalGeo (ops#264)
            std::stable_partition(saved.begin(), saved.end(), [](const Part::Geometry* geo) {
                return kindOf(geo) != std::optional<bool>(false);
            });
        }
        const bool repairThis = openRepair
            ? (flagsOnly ? (savedGuessed || savedWaits)
                         : (!laterOpen || saved.empty() || savedMissing || savedGuessed
                            || savedWaits))
            : (undecidedTypeKeys.count(key) != 0 && savedMissing);
        if (repairThis) {
            auto setType = [&](long type) {
                projection = type == (int)ExtType::Projection || type == (int)ExtType::Both;
                intersection = type == (int)ExtType::Intersection || type == (int)ExtType::Both;
            };
            enum class Match
            {
                None,
                Kinds,  // the same number of geometries of the same kinds: the Ids map one to one
                Exact   // and each is the saved one, within tolerance
            };
            // the match, and for the same kinds how far the built geometry is from the saved one
            bool built = false;  // a type gave geometry: the element is there
            auto matchSaved = [&](long type) -> std::pair<Match, double> {
                setType(type);
                geos.clear();
                try {
                    build();
                    built = built || !geos.empty();
                    if (!std::equal(geos.begin(), geos.end(), saved.begin(), saved.end(),
                                    [](const auto& geo, const Part::Geometry* old) {
                                        return geo->getTypeId() == old->getTypeId();
                                    })) {
                        return {Match::None, 0.0};
                    }
                    bool same = std::equal(geos.begin(), geos.end(), saved.begin(),
                                           [](const auto& geo, const Part::Geometry* old) {
                                               return geo->isSame(*old,
                                                                  Precision::Confusion(),
                                                                  Precision::Angular());
                                           });
                    if (same) {
                        return {Match::Exact, 0.0};
                    }
                    double distance = 0.0;
                    for (std::size_t k = 0; k < geos.size(); ++k) {
                        distance = std::max(distance, distanceFromSaved(geos[k].get(), saved[k]));
                    }
                    return {Match::Kinds, distance};
                }
                catch (...) {
                    return {Match::None, 0.0};
                }
            };
            const long indexType = Types[i];
            std::vector<long> exact;
            std::vector<std::pair<long, double>> kinds;
            if (!saved.empty() && hasSource && !savedGuessed) {
                for (auto type : {ExtType::Projection, ExtType::Intersection, ExtType::Both}) {
                    auto [match, distance] = matchSaved(static_cast<long>(type));
                    switch (match) {
                        case Match::Exact:
                            exact.push_back(static_cast<long>(type));
                            break;
                        case Match::Kinds:
                            kinds.emplace_back(static_cast<long>(type), distance);
                            break;
                        case Match::None:
                            break;
                    }
                }
            }
            bool decided = true;
            if (!exact.empty()) {
                // the type at the link's index when it is among them, else the first
                Types[i] = std::find(exact.begin(), exact.end(), indexType) != exact.end()
                    ? indexType
                    : exact.front();
                if (exact.size() > 1) {
                    FC_WARN("External link " << key << " in " << getFullName() << ": types "
                            << typeList(exact) << " all give its saved geometry; it takes type "
                            << Types[i]);
                }
            }
            else if (!kinds.empty()) {
                // the closest to the saved geometry (arcs fitted to a tolerance, approximated
                // B-splines or another OCCT version can miss it); the index type on a tie
                double best = std::numeric_limits<double>::infinity();
                for (const auto& kind : kinds) {
                    best = std::min(best, kind.second);
                }
                std::vector<long> closest;
                for (const auto& kind : kinds) {
                    if (kind.second <= best + Precision::Confusion()) {
                        closest.push_back(kind.first);
                    }
                }
                Types[i] = std::find(closest.begin(), closest.end(), indexType) != closest.end()
                    ? indexType
                    : closest.front();
                if (closest.size() > 1) {
                    FC_WARN("External link " << key << " in " << getFullName()
                            << ": no type gives its saved geometry exactly; types "
                            << typeList(closest) << " are equally close to it; it takes type "
                            << Types[i]);
                }
                else {
                    FC_WARN("External link " << key << " in " << getFullName()
                            << ": no type gives its saved geometry exactly, only the same kinds;"
                            << " it takes the closest, type " << Types[i]);
                }
            }
            else if (auto type = savedGuessed ? std::nullopt
                                              : typeFromSavedGeometry(SubElement, saved)) {
                Types[i] = *type;
            }
            else {
                decided = false;
                undecided = true;
                if (typesOnly) {
                    undecidedTypeKeys.insert(key);
                    // saved geometry left as it is (no full rebuild on open) would look decided
                    // on the next open if the file is saved before a rebuild: present, not
                    // missing, unflagged, it keeps the index type and drops the mark, silently.
                    // So would geometry marked missing alone once a freeze, a park or a drop
                    // cleared the mark (round 7). Flagged undecided, also when it is missing,
                    // and marked missing when the element is absent (no type built it)
                    if (!saved.empty() && !savedGuessed) {
                        for (long id : externalGeoRefMap[key]) {
                            auto it = externalGeoMap.find(id);
                            if (it != externalGeoMap.end()) {
                                savedUndecided.insert(it->second);
                                if (!built && !savedMissing) {
                                    savedAbsent.insert(it->second);
                                }
                            }
                        }
                    }
                    if (savedGuessed) {
                        FC_WARN("External link " << key << " in " << getFullName()
                                << ": its type is still undecided (a type list saved before"
                                << " ops#140); its saved geometry was built with the type at its"
                                << " index, type " << indexType << ", which it keeps. Delete the"
                                << " link and add it again to settle its type");
                    }
                    else {
                        FC_WARN("External link " << key << " in " << getFullName()
                                << ": its type can't be told from a type list saved before"
                                << " ops#140; it keeps type " << indexType);
                    }
                }
                else if (built && !savedGuessed) {
                    // FreeCAD-CH (ops#237): the element is back, but no type gives the saved
                    // geometry: built with the type at its index, the link's saved geometry is
                    // replaced, and nothing could tell its type any more. Geometry built from a
                    // guess was no evidence to begin with: the link goes on waiting (PR 277
                    // verification 5.1)
                    FC_WARN("External link " << key << " in " << getFullName()
                            << ": its element is back, but no type gives its saved geometry, so"
                            << " its type can't be told from a type list saved before ops#140;"
                            << " it takes type " << indexType
                            << ", the type at its index, which can be another link's");
                    undecidedTypeKeys.erase(key);
                    typesRepaired = true;
                }
            }
            if (decided && !typesOnly) {
                undecidedTypeKeys.erase(key);
                typesRepaired = true;
            }
            // decided on open: its saved geometry no longer waits (a full rebuild clears the flag
            // of the geometry of a link that no longer waits, below). Only a link's: the open
            // keeps neither a dropped link it linked again above nor its type, so the next
            // rebuild forms that link again, and its flags say it waits (verification 6.2)
            if (decided && typesOnly && savedWaits && static_cast<std::size_t>(i) < linkCount) {
                decidedOnOpen.insert(key);
                for (long id : externalGeoRefMap[key]) {
                    auto it = externalGeoMap.find(id);
                    if (it != externalGeoMap.end()) {
                        savedDecided.insert(it->second);
                    }
                }
            }
            setType(Types[i]);
            geos.clear();
        }
        // FreeCAD-CH (ops#278): a frozen link too, before it is skipped below: once unfrozen or
        // resynced its rebuild hands the Ids out by kind as well
        if (typesOnly && hasSource) {
            // FreeCAD-CH (ops#269): geometry saved before ops#264 has no kinds, and its first
            // rebuild would give its Ids by position across them: a Both link whose projection
            // and intersection change in number at an equal total, or a type changed before that
            // rebuild, would move constraints silently. The saved type, built now, tells them
            // when it gives the saved geometry's number and types, in the Ids' order.
            std::vector<std::size_t> savedIndices;
            bool noKinds = true;
            for (long id : externalGeoRefMap[key]) {
                auto it = externalGeoMap.find(id);
                if (it != externalGeoMap.end()) {
                    savedIndices.push_back(static_cast<std::size_t>(it->second));
                    noKinds = noKinds && !kindOf(ExternalGeo[it->second]);
                }
            }
            if (!savedIndices.empty() && noKinds) {
                geos.clear();
                bool same = false;
                try {
                    build();
                    same = std::equal(geos.begin(), geos.end(), savedIndices.begin(),
                                      savedIndices.end(),
                                      [&](const auto& geo, std::size_t index) {
                                          return geo->getTypeId()
                                              == ExternalGeo[static_cast<int>(index)]->getTypeId();
                                      });
                    // A Both link's split between the kinds can move at the same types (a
                    // stale saved shape: two projections and a section saved, one and two
                    // built), so each built geometry must be its saved one too (PR 251 review
                    // M1). A link of one kind has its kind whatever the shapes.
                    if (same && projection && intersection) {
                        const double tolerance =
                            std::max(Precision::Confusion(), ArcFitTolerance.getValue());
                        for (std::size_t k = 0; k < geos.size() && same; ++k) {
                            const auto* saved = ExternalGeo[static_cast<int>(savedIndices[k])];
                            same = geos[k]->isSame(*saved,
                                                   Precision::Confusion(),
                                                   Precision::Angular())
                                || distanceFromSaved(geos[k].get(), saved) <= tolerance;
                        }
                    }
                }
                catch (...) {
                    same = false;
                }
                if (same) {
                    for (std::size_t k = 0; k < savedIndices.size(); ++k) {
                        savedKinds[savedIndices[k]] = k < projSize;
                    }
                }
                else {
                    FC_WARN("External link " << key << " in " << getFullName()
                            << ": its geometry was saved without recording which was projected "
                               "and which intersections, and its type no longer gives the same "
                               "geometries; at its next rebuild"
                            << (keepFrozen ? " (once it is unfrozen)" : "")
                            << " the Ids go by position: check the constraints on it");
                }
                geos.clear();
            }
        }
        if (keepFrozen) {
            refSet.insert(key);
            continue;
        }
        if (!hasSource || typesOnly) {
            continue;
        }

        try {
            build();
        } catch (Base::Exception &e) {
            FC_ERR("Failed to project external geometry in "
                   << getFullName() << ": " << key << std::endl << e.what());
            continue;
        } catch (Standard_Failure &e) {
            FC_ERR("Failed to project external geometry in "
                   << getFullName() << ": " << key << std::endl << e.GetMessageString());
            continue;
        } catch (std::exception &e) {
            FC_ERR("Failed to project external geometry in "
                   << getFullName() << ": " << key << std::endl << e.what());
            continue;
        } catch (...) {
            FC_ERR("Failed to project external geometry in "
                   << getFullName() << ": " << key << std::endl << "Unknown exception");
            continue;
        }
        if (geos.empty()) {
            continue;
        }

        if(!refSet.emplace(key).second) {
            FC_WARN("Duplicated external reference in " << getFullName() << ": " << key);
            continue;
        }

        for (auto& geo : geos) {
            ExternalGeometryFacade::getFacade(geo.get())->setRef(key);
        }
        // A projection added to an intersection link (the reverse appends the intersection after
        // the projection, in build order already)
        const bool projectionAdded = beingCreated && !extToAdd->intersection && intersection;
        addedProjections.push_back(projectionAdded ? projSize : 0);
        projSizes.push_back(projSize);
        linkIndexes.push_back(i);
        if (beingCreated) {
            createdKey = key;
        }
        newGeos.push_back(std::move(geos));
    }

    if (typesOnly) {
        if (openRepair) {
            // each link whose saved geometry waits and that the open didn't decide waits, a
            // dropped link's too (its geometry remains): formed again, it is matched with that
            // geometry, and its flags aren't cleared as if it were decided (verification 6.1)
            for (const auto& ref : flaggedWaiting) {
                if (decidedOnOpen.count(ref) == 0) {
                    undecidedTypeKeys.insert(ref);
                    undecided = true;
                }
            }
            Types.resize(linkCount);
            externalTypeRepairPending = undecided;
            if (undecided) {
                Types.push_back(pendingTypeRepairMark);
            }
            ExternalTypes.setValues(Types);
        }
        if (!savedKinds.empty() || !savedUndecided.empty() || !savedAbsent.empty()
            || !savedDecided.empty()) {
            std::vector<Part::Geometry*> geos(ExternalGeo.getValues());
            std::set<std::size_t> cloned;
            auto own = [&](std::size_t index) {
                if (cloned.insert(index).second) {
                    geos[index] = geos[index]->clone();
                }
                return geos[index];
            };
            for (const auto& [index, projection] : savedKinds) {
                setKind(own(index), projection);
            }
            for (std::size_t index : savedUndecided) {
                ExternalGeometryFacade::getFacade(own(index))
                    ->setFlag(ExternalGeometryExtension::TypeUndecided, true);
            }
            for (std::size_t index : savedDecided) {
                ExternalGeometryFacade::getFacade(own(index))
                    ->setFlag(ExternalGeometryExtension::TypeUndecided, false);
            }
            for (std::size_t index : savedAbsent) {
                ExternalGeometryFacade::getFacade(own(index))
                    ->setFlag(ExternalGeometryExtension::Missing, true);
            }
            ExternalGeo.setValues(std::move(geos));
        }
        return;
    }

    // The constraints on the geometries with these Ids, which the rebuild deletes, as the
    // constraint list names them (its name, or ConstraintN; PR 241 review L2)
    auto constraintsOn = [&](const std::set<long>& ids) {
        std::set<int> geoIds;
        for (long id : ids) {
            auto it = externalGeoMap.find(id);
            if (it != externalGeoMap.end()) {
                geoIds.insert(-static_cast<int>(it->second) - 1);
            }
        }
        std::vector<std::string> names;
        const auto& constraints = Constraints.getValuesForce();
        for (std::size_t i = 0; i < constraints.size(); ++i) {
            for (int e = 0; constraints[i]->hasElement(e); ++e) {
                if (geoIds.count(constraints[i]->getGeoId(e)) != 0) {
                    names.push_back(constraints[i]->Name.empty()
                                        ? "Constraint" + std::to_string(i + 1)
                                        : constraints[i]->Name);
                    break;
                }
            }
        }
        return names;
    };

    // FreeCAD-CH (ops#264 e2): whether link `index`'s reference resolved by history this
    // recompute: exactly (no report entry), or by the solver at tier 0-1 without a guess record.
    // A face found by geometry (tiers 2-3, a guess, a place keep) may be a redrawn profile: the
    // order of its edges is no evidence (review CC1). A link added back after an older version
    // dropped it has no entry of its own.
    auto resolvedByHistory = [&](int index) {
        if (index < 0 || static_cast<std::size_t>(index) >= linkCount) {
            return false;
        }
        const auto* entry = App::ReferenceReport::find(&ExternalGeometry, index);
        return !entry
            || (entry->status == App::ReferenceReport::Status::Resolved && entry->tier >= 0
                && entry->tier <= 1);
    };
    // the Ids of old geometry without a counterpart that carries constraints: kept where it is,
    // flagged missing, and the sketch fails naming it; its constraints never move to another
    // geometry (ops#264 e2, I-R2)
    std::set<long> lostIds;
    // the entries of newGeos whose Ids were paired by source, place or position (ops#264 e2): their
    // geometries take their slots in build order (below)
    std::vector<bool> pairedLinks(newGeos.size(), false);

    // allocate unique geometry id
    for (std::size_t n = 0; n < newGeos.size(); ++n) {
        auto& geos = newGeos[n];
        const std::string key = ExternalGeometryFacade::getFacade(geos.front().get())->getRef();
        auto &refs = externalGeoRefMap[key];
        const std::size_t projCount = projSizes[n];

        // FreeCAD-CH (ops#264): the Ids go per kind, the projection's to the projection and the
        // intersection's to the intersection, so a Both link whose projection changes in number,
        // or a type written from Python, doesn't move constraints from one kind to the other.
        // Within a kind they go by source, place, then position (pairGeometries(), ops#264 e2).
        // Geometry saved before has no kind: such a link gets its Ids by position, as before,
        // once, and has kinds from then on.
        std::vector<long> projectionIds;
        std::vector<long> intersectionIds;
        bool byKind = !refs.empty();
        for (long id : refs) {
            auto it = externalGeoMap.find(id);
            auto kind = it != externalGeoMap.end() ? kindOf(ExternalGeo[it->second])
                                                   : std::optional<bool>();
            if (!kind) {
                byKind = false;
                break;
            }
            (*kind ? projectionIds : intersectionIds).push_back(id);
        }

        std::set<long> geoIds;  // the Ids no new geometry takes, whose geometry goes
        if (byKind) {
            const bool byHistory = resolvedByHistory(linkIndexes[n]);
            // a kind the link's type no longer builds (a type written from Python, Both to
            // Intersection) goes with its constraints, as before, with the warning below: the
            // user's edit, not its source's, took it away (PR 241)
            const long type = Types[linkIndexes[n]];
            const bool projected = type == static_cast<long>(ExtType::Projection)
                || type == static_cast<long>(ExtType::Both);
            const bool intersected = type == static_cast<long>(ExtType::Intersection)
                || type == static_cast<long>(ExtType::Both);
            auto handOut = [&](const std::vector<long>& ids,
                               std::size_t begin,
                               std::size_t end,
                               bool built) {
                std::vector<const Part::Geometry*> olds;
                for (long id : ids) {
                    auto it = externalGeoMap.find(id);
                    olds.push_back(it != externalGeoMap.end() ? ExternalGeo[it->second] : nullptr);
                }
                std::vector<const Part::Geometry*> news;
                for (std::size_t g = begin; g < end; ++g) {
                    news.push_back(geos[g].get());
                }
                const auto taken = pairGeometries(olds, news, byHistory);
                std::vector<bool> kept(ids.size(), false);
                for (std::size_t k = 0; k < news.size(); ++k) {
                    if (taken[k] >= 0) {
                        kept[taken[k]] = true;
                    }
                    GeometryFacade::setId(geos[begin + k].get(),
                                          taken[k] >= 0 ? ids[taken[k]] : ++geoLastId);
                }
                for (std::size_t j = 0; j < ids.size(); ++j) {
                    if (!kept[j]) {
                        (!built || constraintsOn({ids[j]}).empty() ? geoIds : lostIds)
                            .insert(ids[j]);
                    }
                }
            };
            handOut(projectionIds, 0, projCount, projected);
            handOut(intersectionIds, projCount, geos.size(), intersected);
            // new geometry goes where the build gives it, a projection added to an intersection
            // link before it too (ops#260), below
            addedProjections[n] = 0;
            pairedLinks[n] = true;
            refs.clear();
            for (const auto& geo : geos) {
                refs.push_back(GeometryFacade::getId(geo.get()));
            }
        }
        else {
            const std::size_t oldCount = refs.size();
            if (addedProjections[n] > 0 && !refs.empty()) {
                // The link's Ids are its intersection's, which the build gives after the
                // projection: the projection takes new Ids before them, so the constraints on the
                // intersection stay there (ops#260)
                std::vector<long> ids;
                while (ids.size() < addedProjections[n]) {
                    ids.push_back(++geoLastId);
                }
                refs.insert(refs.begin(), ids.begin(), ids.end());
            }
            else {
                addedProjections[n] = 0;  // a new link: its geometries are appended in build order
                // Whatever the link's type now: a type written before the first rebuild of
                // geometry saved without kinds (Both to Intersection) isn't seen here, and the
                // Ids go by position across the kinds (PR 241 review M1). Such geometry gets its
                // kinds on open (ops#269), so this is one whose saved type no longer gave it
                // there (with a warning), or one frozen or without its source then.
                // a link of one kind (ops#269) only says that its Ids went by position
                if (oldCount != 0 && oldCount != geos.size()) {
                    FC_WARN("External link " << key << " in " << getFullName() << " gives "
                            << geos.size() << " geometries instead of " << oldCount
                            << (projCount == 0 || projCount == geos.size()
                                    ? ", and they took its Ids by position"
                                    : ", and its saved geometry doesn't record which were "
                                      "projected and which intersections")
                            << ": check the constraints on it");
                }
            }
            while(refs.size() < geos.size())
                refs.push_back(++geoLastId);

            // In case a projection reduces output geometries, delete them
            geoIds.insert(refs.begin()+geos.size(),refs.end());

            // Sync id and ref of the new geometries
            int i = 0;
            for(auto &geo : geos)
                GeometryFacade::setId(geo.get(), refs[i++]);
        }

        // A link that gives fewer geometries than before deletes the others with their
        // constraints, which isn't silent any more (ops#264)
        if (const auto names = constraintsOn(geoIds); !names.empty()) {
            std::string list;
            for (const auto& name : names) {
                list += (list.empty() ? "" : ", ") + name;
            }
            FC_WARN("External link " << key << " in " << getFullName() << " gives fewer geometries "
                    "than before: " << names.size() << " constraint(s) on the geometry it no "
                    "longer gives are deleted (" << list << ")");
        }
        delExternalPrivate(geoIds,false);
    }

    auto geoms = ExternalGeo.getValues();

    // now update the geometries
    // projections added to an intersection link, each with the Id of the geometry it goes before;
    // and a paired link's new geometries (ops#264 e2)
    std::vector<std::pair<long, std::vector<Part::Geometry*>>> projectionsBefore;
    // the slots of geometries a paired link's build order moved: old index -> new (ops#264 e2)
    std::map<int, int> movedSlots;
    for (std::size_t n = 0; n < newGeos.size(); ++n) {
        auto& geos = newGeos[n];
        if (geos.empty()) {
            continue;
        }

        // Get the reference key for this group of geometries. All geos in this vector share the same ref.
        const std::string& key = ExternalGeometryFacade::getFacade(geos.front().get())->getRef();
        auto itKey = linkIsDefiningMap.find(key);
        // the link being added to keeps the Defining flag the add gives its new geometries
        bool hasLinkState = itKey != linkIsDefiningMap.end() && key != createdKey;
        bool isLinkDefining = hasLinkState ? itKey->second : false;
        // the link still waits for its type (ops#287)
        const bool guessed = externalTypeRepairPending && undecidedTypeKeys.count(key) != 0;

        const std::size_t before = addedProjections[n];
        std::vector<Part::Geometry*>* front = nullptr;  // where this link's added projections go
        if (before > 0 && before < geos.size()) {
            projectionsBefore.emplace_back(GeometryFacade::getId(geos[before].get()),
                                           std::vector<Part::Geometry*> {});
            front = &projectionsBefore.back().second;
        }
        // FreeCAD-CH (ops#264 e2): a link whose Ids were paired by source or place keeps its
        // geometry in build order in ExternalGeo, as the Ids by position did (externalGeoRefMap,
        // and so the next pairing by position, reads that order): the geometries that keep an Id
        // take those Ids' slots in build order, and each new one goes before the next of them
        // (or at the end, after them all). A lost geometry keeps its slot.
        std::vector<int> slots;
        std::vector<long> anchors(geos.size(), 0);  // a new geometry goes before this Id (0: end)
        if (pairedLinks[n]) {
            long next = 0;
            for (std::size_t k = geos.size(); k-- > 0;) {
                const long id = GeometryFacade::getId(geos[k].get());
                auto it = externalGeoMap.find(id);
                if (it != externalGeoMap.end()) {
                    slots.push_back(it->second);
                    next = id;
                }
                else {
                    anchors[k] = next;
                }
            }
            std::sort(slots.begin(), slots.end());
        }
        std::size_t nextSlot = 0;
        std::vector<Part::Geometry*>* group = nullptr;  // the new ones going before `groupAnchor`
        long groupAnchor = 0;
        for (std::size_t k = 0; k < geos.size(); ++k) {
            auto& geo = geos[k];
            auto it = externalGeoMap.find(GeometryFacade::getId(geo.get()));
            if(it == externalGeoMap.end()) {
                // This is a new geometries.
                // Set its defining state based on the inferred state of its parent link.
                if (hasLinkState) {
                    ExternalGeometryFacade::getFacade(geo.get())->setFlag(ExternalGeometryExtension::Defining, isLinkDefining);
                }
                // FreeCAD-CH (ops#287): built from the type at its index while the link waits
                // for its type: saved, it mustn't count as evidence of the type on a later open
                ExternalGeometryFacade::getFacade(geo.get())
                    ->setFlag(ExternalGeometryExtension::TypeGuessed, guessed);
                if (front && k < before) {
                    front->push_back(geo.release());
                }
                else if (anchors[k] != 0) {
                    if (!group || groupAnchor != anchors[k]) {
                        projectionsBefore.emplace_back(anchors[k], std::vector<Part::Geometry*> {});
                        group = &projectionsBefore.back().second;
                        groupAnchor = anchors[k];
                    }
                    group->push_back(geo.release());
                }
                else {
                    geoms.push_back(geo.release());
                }
                continue;
            }
            const int from = it->second;
            const int to = pairedLinks[n] ? slots[nextSlot++] : from;
            if (to != from) {
                movedSlots[from] = to;
            }
            // This is an existing geometry. Update it while keeping the old flags, but the kind
            // the build gave (ops#264; geometry saved before has none). The old one is read from
            // ExternalGeo: its slot in geoms may hold another geometry of the link by now
            const auto kind = kindOf(geo.get());
            ExternalGeometryFacade::copyFlags(ExternalGeo[from], geo.get());
            if (kind) {
                setKind(geo.get(), *kind);
            }
            // rebuilt, it has the content of the type it was built with: while the link waits,
            // that is the type at its index, a guess, so it is flagged as the new geometry is
            // (geometry the build doesn't reach, e.g. missing, keeps its flags); a decided link's
            // geometry no longer counts as guessed (ops#287). A rebuild in a failed add of the
            // other kind runs with the link's key taken out, and the revert's rebuild flags it
            // again (PR 277 verification 5)
            ExternalGeometryFacade::getFacade(geo.get())
                ->setFlag(ExternalGeometryExtension::TypeGuessed, guessed);
            geoms[to] = geo.release();
        }
    }
    // externalGeoRefMap is rebuilt from ExternalGeo's order, which must be the build order: the
    // added projections go right before the link's first existing geometry, and the external
    // GeoIds of the constraints at or after each move one on (ops#260)
    std::vector<int> inserted;  // the indexes the projections took, in turn
    for (auto& [anchor, projections] : projectionsBefore) {
        auto at = std::find_if(geoms.begin(), geoms.end(), [anchor = anchor](const Part::Geometry* geo) {
            return GeometryFacade::getId(geo) == anchor;
        });
        for (auto* geo : projections) {
            at = geoms.insert(at, geo) + 1;
            inserted.push_back(static_cast<int>(at - geoms.begin()) - 1);
        }
    }

    // Check for any missing references
    bool hasError = false;
    // the missing references, in order, with the indexes of their geometries in geoms
    std::vector<std::pair<std::string, std::vector<std::size_t>>> missingRefs;
    // and the links whose lost geometries (above) are flagged missing, alike (ops#264 e2)
    std::vector<std::pair<std::string, std::vector<std::size_t>>> lostRefs;
    auto addIndex = [](auto& refs, const std::string& ref, std::size_t index) {
        auto it = std::find_if(refs.begin(), refs.end(), [&](const auto& entry) {
            return entry.first == ref;
        });
        if (it == refs.end()) {
            it = refs.emplace(refs.end(), ref, std::vector<std::size_t> {});
        }
        it->second.push_back(index);
    };
    for (std::size_t index = 0; index < geoms.size(); ++index) {
        auto egf = ExternalGeometryFacade::getFacade(geoms[index]);
        egf->setFlag(ExternalGeometryExtension::Sync,false);
        if(egf->getRef().empty())
            continue;
        // FreeCAD-CH (ops#287, PR 277 round 7): the geometry of a link that still waits says so
        // when it is saved: geometry the rebuild didn't reach (frozen, missing, a dropped link's)
        // is flagged undecided and stays evidence, geometry built from the guess is flagged as
        // guessed instead (above). Once a link's type is decided its geometry no longer waits; a
        // dropped link's keeps its flag until the link is formed again. The key set is the flags'
        // (round 8): the paths that rebuild it from scratch (an open, an undo, a failed open) put
        // back every key whose geometry is flagged, so only a decision takes a key out
        if (externalTypeRepairPending && undecidedTypeKeys.count(egf->getRef()) != 0) {
            egf->setFlag(ExternalGeometryExtension::TypeUndecided,
                         !egf->testFlag(ExternalGeometryExtension::TypeGuessed));
        }
        else if (std::find(keys.begin(), keys.end(), egf->getRef()) != keys.end()) {
            egf->setFlag(ExternalGeometryExtension::TypeUndecided, false);
        }
        if(!refSet.count(egf->getRef())) {
            FC_ERR( "External geometry " << getFullName() << ".e" << egf->getId()
                    << " missing reference: " << egf->getRef());
            hasError = true;
            egf->setFlag(ExternalGeometryExtension::Missing,true);
            addIndex(missingRefs, egf->getRef(), index);
        }
        else if (lostIds.count(egf->getId()) != 0) {
            FC_ERR("External geometry " << getFullName() << ".e" << egf->getId()
                   << " lost its source in " << egf->getRef());
            hasError = true;
            egf->setFlag(ExternalGeometryExtension::Missing, true);
            addIndex(lostRefs, egf->getRef(), index);
        }
        else {
            egf->setFlag(ExternalGeometryExtension::Missing,false);
        }
    }

    std::set<int> reversedGeoIds;
    for (std::size_t index = 0; index < geoms.size(); ++index) {
        auto* line = freecad_cast<const Part::GeomLineSegment*>(geoms[index]);
        if (!line) {
            continue;
        }
        auto previous = previousLineDirections.find(GeometryFacade::getId(geoms[index]));
        if (previous != previousLineDirections.end()
            && (line->getEndPoint() - line->getStartPoint()).Dot(previous->second) < 0.0) {
            reversedGeoIds.insert(-static_cast<int>(index) - 1);
        }
    }

    ExternalGeo.setValues(std::move(geoms));
    if (!inserted.empty() || !movedSlots.empty()) {
        // getValuesForce(): getValues() is empty while the list is flagged invalid, and writing
        // that back would delete every constraint (as in unparkExternalGeometry)
        std::vector<Constraint*> constraints;
        for (const auto& cstr : Constraints.getValuesForce()) {
            auto shifted = cstr->clone();
            // the geometries a paired link's build order moved, first (ops#264 e2)
            for (int i = 0; shifted->hasElement(i); ++i) {
                const int given = shifted->getGeoId(i);
                auto moved = given <= GeoEnum::RefExt && given != GeoEnum::GeoUndef
                    ? movedSlots.find(-given - 1)
                    : movedSlots.end();
                if (moved != movedSlots.end()) {
                    shifted->setGeoId(i, -moved->second - 1);
                }
            }
            for (int at : inserted) {
                const int geoId = -at - 1;
                for (int i = 0; shifted->hasElement(i); ++i) {
                    const int given = shifted->getGeoId(i);
                    if (given <= geoId && given != GeoEnum::GeoUndef) {
                        shifted->setGeoId(i, given - 1);
                    }
                }
            }
            constraints.push_back(shifted);
        }
        Constraints.setValues(std::move(constraints));
    }
    rebuildVertexIndex();

    reorientConstraintsOnReversedGeometry(reversedGeoIds);

    // clean up geometry reference. A link whose geometry is missing stays, so the sketch keeps
    // depending on its source and reports the missing element on every recompute until the user
    // re-points or deletes it (ops#72). A link that gave no geometry and had none is dropped.
    auto isMissing = [&](const std::string& ref) {
        return std::any_of(missingRefs.begin(), missingRefs.end(), [&](const auto& entry) {
            return entry.first == ref;
        });
    };
    {
        std::vector<App::DocumentObject*> newObjects;
        std::vector<std::string> newSubElements;
        std::vector<long> newTypes;
        bool linksChanged = !relinked.empty();
        for (std::size_t index = 0; index < keys.size(); ++index) {
            bool isLink = index < linkCount;
            bool kept = refSet.count(keys[index]) != 0
                || (isLink && isMissing(keys[index]) && Objects[index]
                    && Objects[index]->isAttachedToDocument());
            if (!kept) {
                linksChanged = linksChanged || isLink;
                continue;
            }
            linksChanged = linksChanged || !isLink;
            newObjects.push_back(Objects[index]);
            newSubElements.push_back(SubElements[index]);
            newTypes.push_back(Types[index]);
        }
        if (typesRepaired) {
            // the mark goes with the last undecided link
            externalTypeRepairPending = externalTypeRepairPending && !undecidedTypeKeys.empty();
        }
        if (linksChanged) {
            // a relinked entry has a new sub, so it gets no shadow and is resolved again
            setExternalLinksAndTypes(newObjects, newSubElements, newTypes);
        }
        else if (typesRepaired) {
            auto pending = pendingTypeRepair();
            newTypes.insert(newTypes.end(), pending.begin(), pending.end());
            ExternalTypes.setValues(newTypes);
        }
    }

    // the frames the geometry was built with, for mustExecute() (ops#331)
    {
        auto frames = externalFrames();
        if (frames != ExternalFrames.getValues()) {
            ExternalFrames.setValues(std::move(frames));
        }
    }

    solverNeedsUpdate=true;
    if (!keepConstraintsInvalid) {
        Constraints.acceptGeometry(getCompleteGeometry());
    }

    if (hasError && this->isRecomputing()) {
        throw Base::RuntimeError(
            missingReferenceMessage(getDocument(), missingRefs, lostRefs, Objects, SubElements,
                                    keys));
    }
}

namespace
{
std::string missingReferenceMessage(
    const App::Document* doc,
    const std::vector<std::pair<std::string, std::vector<std::size_t>>>& missingRefs,
    const std::vector<std::pair<std::string, std::vector<std::size_t>>>& lostRefs,
    const std::vector<App::DocumentObject*>& objects,
    const std::vector<std::string>& subElements,
    const std::vector<std::string>& keys)
{
    // Names each missing reference as the user sees it, Label.Element, with the external
    // geometry it gave (ExternalEdgeN, as the sketcher selects it; the first two are the axes)
    std::string message;
    if (!missingRefs.empty()) {
        message = missingRefs.size() == 1 ? "Missing external geometry reference: "
                                          : "Missing external geometry references: ";
    }
    // FreeCAD-CH (ops#264 e2): and each link whose element is there but no longer gives the
    // geometry the constraints are on (pairGeometries() found no counterpart)
    if (!lostRefs.empty()) {
        message += (message.empty() ? "" : "; ") + std::string("External geometry lost: ");
    }
    bool first = true;
    for (const auto& [ref, indexes] : missingRefs) {
        if (!first) {
            message += "; ";
        }
        first = false;
        message += referenceText(doc, ref, indexes, objects, subElements, keys);
    }
    first = true;
    for (const auto& [ref, indexes] : lostRefs) {
        if (!first) {
            message += "; ";
        }
        first = false;
        message += referenceText(doc, ref, indexes, objects, subElements, keys, true);
    }
    return message;
}

// "Label.Element (ExternalEdgeN, ...)", or for lost geometry "Label.Element no longer gives
// ExternalEdgeN, ... (...)"
std::string referenceText(const App::Document* doc,
                          const std::string& ref,
                          const std::vector<std::size_t>& indexes,
                          const std::vector<App::DocumentObject*>& objects,
                          const std::vector<std::string>& subElements,
                          const std::vector<std::string>& keys,
                          bool lost)
{
    std::string message;
    std::string source;
    std::string element;
    auto it = std::find(keys.begin(), keys.end(), ref);
    if (it != keys.end() && objects[it - keys.begin()]) {
        const auto* obj = objects[it - keys.begin()];
        source = obj->Label.getValue();
        element = Data::oldElementName(subElements[it - keys.begin()].c_str());
    }
    else {
        // a link dropped by an older version: only the geometry's reference is left
        auto pos = ref.find('.');
        std::string objName = ref.substr(0, pos);
        auto obj = doc ? doc->getObject(objName.c_str()) : nullptr;
        source = obj ? obj->Label.getValue() : objName;
        if (pos != std::string::npos) {
            element = Data::oldElementName(ref.c_str() + pos + 1);
        }
    }
    if (boost::starts_with(element, Data::MISSING_PREFIX)) {
        element.erase(0, std::strlen(Data::MISSING_PREFIX));
    }
    message += source;
    if (!element.empty()) {
        message += "." + element;
    }

    message += lost ? " no longer gives " : " (";
    for (std::size_t i = 0; i < indexes.size(); ++i) {
        message += (i ? ", " : "") + std::string("ExternalEdge")
            + std::to_string(static_cast<long>(indexes[i]) - 1);
    }
    message += lost ? (indexes.size() == 1
                           ? " (its source edge is gone; its constraints stay on it)"
                           : " (their source edges are gone; their constraints stay on them)")
                    : ")";
    return message;
}
}  // namespace

void SketchObject::fixMissingAxisInExternalGeo()
{
    //Make sure the H/V axis are still in ExternalGeo. See 27693
    bool corrupted = false;
    if (ExternalGeo.getSize() < 2) {
        corrupted = true;
    }
    else {
        auto gf0 = GeometryFacade::getFacade(ExternalGeo[0]);
        auto gf1 = GeometryFacade::getFacade(ExternalGeo[1]);
        if (gf0->getId() != -1 || gf1->getId() != -2) {
            corrupted = true;
        }
    }
    if (corrupted) {
        initExternalGeo();
    }
}

void SketchObject::fixExternalGeometry(const std::vector<int> &geoIds) {
    std::set<int> idSet(geoIds.begin(),geoIds.end());
    auto geos = ExternalGeo.getValues();
    auto objs = ExternalGeometry.getValues();
    auto subs = ExternalGeometry.getSubValues();
    bool touched = false;
    for(int i=2;i<(int)geos.size();++i) {
        auto &geo = geos[i];
        auto egf = ExternalGeometryFacade::getFacade(geo);
        int GeoId = -i-1;
        if(egf->getRef().empty()
                || !egf->testFlag(ExternalGeometryExtension::Missing)
                || (idSet.size() && !idSet.count(GeoId)))
            continue;
        std::string ref = egf->getRef();
        auto pos = ref.find('.');
        if(pos == std::string::npos) {
            FC_ERR("Invalid geometry reference " << ref);
            continue;
        }
        std::string objName = ref.substr(0,pos);
        auto obj = getDocument()->getObject(objName.c_str());
        if(!obj) {
            FC_ERR("Cannot find object in reference " << ref);
            continue;
        }

        auto elements = Part::Feature::getRelatedElements(obj,ref.c_str()+pos+1);
        if(!elements.size()) {
            FC_ERR("No related reference found for " << ref);
            continue;
        }

        geo = geo->clone();
        egf->setGeometry(geo);
        egf->setFlag(ExternalGeometryExtension::Missing,false);
        ref = objName + "." + Data::ComplexGeoData::elementMapPrefix();
        // The name in the shape's form (interned or full, ops#97), as the link's shadow will
        // hold it: updateGeometryRefs() keys the geometry by the shadow's name.
        auto mapped = Part::Feature::getTopoShape(obj, Part::ShapeOption::ResolveLink)
                          .getMappedName(elements.front().index);
        (mapped ? mapped : elements.front().name).appendToBuffer(ref);
        egf->setRef(ref);
        egf->setSource(std::string());  // linked anew (ops#264 e2)
        objs.push_back(obj);
        subs.emplace_back();
        elements.front().index.appendToStringBuffer(subs.back());
        touched = true;
    }

    if(touched) {
        // the links added above are projections; the others keep their types. A missing
        // intersection comes back as a projection: the missing geometry doesn't keep its link's
        // type (nothing in the fork calls this; ops#237)
        auto types = ExternalTypes.getValues();
        types.resize(ExternalGeometry.getSize(), static_cast<long>(ExtType::Projection));
        ExternalGeo.setValues(geos);
        setExternalLinksAndTypes(objs, subs, types);
        rebuildExternalGeometry();
    }
}

void SketchObject::retargetExternalGeometry(const std::vector<App::DocumentObject*>& objs,
                                            const std::vector<std::string>& subs,
                                            std::vector<App::PropertyLinkBase::ShadowSub>&& shadows)
{
    // The keys of the external geometry name the entry's object (`<object>.<mapped name>`): with
    // updateGeoRef set, updateGeometryRefs() maps each entry's old key to its new one by index, so
    // the projections and the constraints on them stay (ops#127)
    if (objs.size() != subs.size() || objs.size() != shadows.size()
        || externalGeoRef.size() != ExternalGeometry.getValues().size()
        || objs.size() != externalGeoRef.size()) {
        throw Base::ValueError("retargetExternalGeometry: the entries must keep their count");
    }
    updateGeoRef = true;
    ExternalGeometry.setValues(objs, subs, std::move(shadows));
    updateGeoRef = false;
}

bool SketchObject::canRetargetExternalGeometry() const
{
    return externalGeoRef.size() == ExternalGeometry.getValues().size();
}

std::vector<long> SketchObject::externalGeometryIds(int entry) const
{
    if (entry < 0 || entry >= static_cast<int>(externalGeoRef.size())) {
        return {};
    }
    // externalGeoRefMap lists a key's Ids in the order of ExternalGeo: within a kind, the order
    // the rebuild gives them out (geometry a kind gains later goes after the link's other kind,
    // ops#264)
    auto it = externalGeoRefMap.find(externalGeoRef[entry]);
    if (it == externalGeoRefMap.end()) {
        return {};
    }
    return it->second;
}

int SketchObject::externalGeometryKind(long id) const
{
    auto it = externalGeoMap.find(id);
    if (it == externalGeoMap.end() || it->second < 0 || it->second >= ExternalGeo.getSize()) {
        return -1;
    }
    const auto kind = kindOf(ExternalGeo[it->second]);
    return kind ? static_cast<int>(*kind) : -1;
}

int SketchObject::externalType(int entry) const
{
    // ExternalTypes is parallel to the links by index (ops#140; a file saved before can hold a
    // longer list until its repair): the type an entry gets is the one at its index, as the
    // rebuild reads it
    const auto& types = ExternalTypes.getValues();
    if (entry < 0 || entry >= static_cast<int>(types.size())) {
        return static_cast<int>(ExtType::Projection);
    }
    return static_cast<int>(types[entry]);
}

bool SketchObject::externalTypeUndecided(int entry) const
{
    if (entry < 0 || entry >= static_cast<int>(externalGeoRef.size())) {
        return false;
    }
    const std::string& key = externalGeoRef[entry];
    if (externalTypeRepairPending && undecidedTypeKeys.count(key) != 0) {
        return true;
    }
    auto ids = externalGeoRefMap.find(key);
    if (ids == externalGeoRefMap.end()) {
        return false;
    }
    return std::any_of(ids->second.begin(), ids->second.end(), [this](long id) {
        auto it = externalGeoMap.find(id);
        return it != externalGeoMap.end() && it->second >= 0 && it->second < ExternalGeo.getSize()
            && (ExternalGeometryFacade::getFacade(ExternalGeo[it->second])
                    ->testFlag(ExternalGeometryExtension::TypeGuessed)
                || ExternalGeometryFacade::getFacade(ExternalGeo[it->second])
                       ->testFlag(ExternalGeometryExtension::TypeUndecided));
    });
}

std::optional<std::string> SketchObject::externalGeometryRefOf(long id) const
{
    auto it = externalGeoMap.find(id);
    if (it == externalGeoMap.end() || it->second < 0 || it->second >= ExternalGeo.getSize()) {
        return std::nullopt;
    }
    return ExternalGeometryFacade::getFacade(ExternalGeo[it->second])->getRef();
}

void SketchObject::parkExternalGeometry(const std::vector<int>& entries)
{
    auto objs = ExternalGeometry.getValues();
    auto subs = ExternalGeometry.getSubValues();
    auto shadows = ExternalGeometry.getShadowSubs();
    if (!canRetargetExternalGeometry() || subs.size() != objs.size()
        || shadows.size() != objs.size()) {
        throw Base::RuntimeError("parkExternalGeometry: the projections are out of step with "
                                 "the links");
    }
    std::set<int> parked;
    for (int entry : entries) {
        if (entry < 0 || entry >= static_cast<int>(objs.size())) {
            throw Base::IndexError("parkExternalGeometry: no such entry");
        }
        parked.insert(entry);
    }
    if (parked.empty()) {
        return;
    }

    // The geometries lose their reference and stay where they are: the rebuild skips a geometry
    // without one, the solver keeps it fixed, and its Id, GeoId and constraints don't change
    auto geos = ExternalGeo.getValues();
    for (int entry : parked) {
        // a link that waits for its type takes that along on its geometry, which no longer
        // names its key (ops#287, PR 277 verification 5.1)
        const bool undecided = externalTypeUndecided(entry);
        for (long id : externalGeometryIds(entry)) {
            auto it = externalGeoMap.find(id);
            if (it == externalGeoMap.end()) {
                continue;
            }
            auto& geo = geos[it->second];
            geo = geo->clone();
            auto egf = ExternalGeometryFacade::getFacade(geo);
            egf->setRef(std::string());
            egf->setFlag(ExternalGeometryExtension::Missing, false);
            if (undecided && !egf->testFlag(ExternalGeometryExtension::TypeGuessed)) {
                egf->setFlag(ExternalGeometryExtension::TypeUndecided, true);
            }
        }
    }

    auto types = ExternalTypes.getValues();
    for (auto it = parked.rbegin(); it != parked.rend(); ++it) {
        objs.erase(objs.begin() + *it);
        subs.erase(subs.begin() + *it);
        shadows.erase(shadows.begin() + *it);
        if (*it < static_cast<int>(types.size())) {
            types.erase(types.begin() + *it);
        }
    }

    ExternalGeo.setValues(std::move(geos));
    Base::StateLocker lock(externalLinksWithTypes, true);
    // the types first, as in setExternalLinksAndTypes: the links' change is signalled with the
    // two in step for observers (ops#237, PR 262 review L3)
    ExternalTypes.setValues(types);
    ExternalGeometry.setValues(std::move(objs), std::move(subs), std::move(shadows));
}

int SketchObject::unparkExternalGeometry(App::DocumentObject* obj,
                                         const std::string& sub,
                                         App::PropertyLinkBase::ShadowSub&& shadow,
                                         int type,
                                         const std::vector<long>& ids,
                                         const std::vector<int>& kinds,
                                         bool typeGuessed)
{
    auto objs = ExternalGeometry.getValues();
    auto subs = ExternalGeometry.getSubValues();
    auto shadows = ExternalGeometry.getShadowSubs();
    if (!obj || !canRetargetExternalGeometry() || subs.size() != objs.size()
        || shadows.size() != objs.size()) {
        throw Base::RuntimeError("unparkExternalGeometry: the projections are out of step with "
                                 "the links");
    }

    // FreeCAD-CH (ops#287, PR 277 round 5): parked geometry built from a guessed type
    // (TypeGuessed) puts back a link that still waits for its type, whatever `type` is (the
    // type at its index when it was parked, a guess): its key waits again and the type list
    // keeps the mark, or the rebuild would clear the flag and the next open settle the guess.
    // Parking dropped the key with the link's last referenced geometry (verification 4.4). So does
    // `typeGuessed`, the parked record's word: when every parked geometry was deleted while
    // parked, nothing else tells it (verification 5.2)
    std::vector<const Part::Geometry*> parkedGeos;
    for (long id : ids) {
        auto it = externalGeoMap.find(id);
        if (it != externalGeoMap.end()
            && ExternalGeometryFacade::getFacade(ExternalGeo[it->second])->getRef().empty()) {
            parkedGeos.push_back(ExternalGeo[it->second]);
        }
    }
    const bool guessed = typeGuessed || formedAgain(parkedGeos).waits;
    if (guessed) {
        externalTypeRepairPending = true;
    }

    // The entry's type goes at its index, before the entries waiting for a repair on open
    auto pending = pendingTypeRepair();
    auto types = ExternalTypes.getValues();
    types.resize(objs.size(), static_cast<long>(ExtType::Projection));
    types.push_back(type);
    types.insert(types.end(), pending.begin(), pending.end());

    objs.push_back(obj);
    subs.push_back(sub);
    shadows.push_back(std::move(shadow));
    {
        // the types first, as in setExternalLinksAndTypes: the links' change is signalled with
        // the two in step for observers (ops#237)
        Base::StateLocker lock(externalLinksWithTypes, true);
        ExternalTypes.setValues(types);
        ExternalGeometry.setValues(std::move(objs), std::move(subs), std::move(shadows));
    }
    if (externalGeoRef.size() != ExternalGeometry.getValues().size()) {
        throw Base::RuntimeError("unparkExternalGeometry: the link was not added");
    }
    const std::string key = externalGeoRef.back();
    if (guessed) {
        undecidedTypeKeys.insert(key);
    }

    // Give the free geometries the entry's key, then set the key's Ids in the recorded order: the
    // rebuild gives projection n to the n-th Id, and an Id it doesn't find becomes new geometry
    auto geos = ExternalGeo.getValues();
    std::vector<long> refs;
    std::vector<bool> kept;
    refs.reserve(ids.size());
    kept.reserve(ids.size());
    int replaced = 0;
    for (long id : ids) {
        auto it = externalGeoMap.find(id);
        if (it != externalGeoMap.end()
            && ExternalGeometryFacade::getFacade(geos[it->second])->getRef().empty()) {
            auto& geo = geos[it->second];
            geo = geo->clone();
            ExternalGeometryFacade::getFacade(geo)->setRef(key);
            refs.push_back(id);
            kept.push_back(true);
        }
        else {
            refs.push_back(++geoLastId);
            kept.push_back(false);
            ++replaced;
        }
    }

    // externalGeoRefMap lists a key's Ids in ExternalGeo's order whenever it is rebuilt from
    // ExternalGeo (onExternalGeoChanged: every rebuild's write, undo, reopen), so a new Id must sit
    // at its place in the projection order, not be appended after the kept ones: a placeholder
    // with the new Id goes right after the entry's previous geometry (or before its next kept one),
    // and the rebuild replaces it with the projection. When none is kept, the rebuild appends all
    // of them in order, which is that order already. A frozen entry gets none: the rebuild skips
    // the whole entry while one of its geometries is frozen, so a placeholder would stay a copy of
    // its neighbour; the deleted projection stays gone, as the freeze says.
    bool frozen = false;
    bool defining = true;  // the entry's state, as the rebuild infers it for a new geometry
    for (std::size_t n = 0; n < refs.size(); ++n) {
        if (kept[n]) {
            auto egf = ExternalGeometryFacade::getFacade(geos[externalGeoMap[refs[n]]]);
            frozen = frozen || egf->testFlag(ExternalGeometryExtension::Frozen);
            defining = defining && egf->testFlag(ExternalGeometryExtension::Defining);
        }
    }
    std::vector<int> inserted;  // the ExternalGeo indexes the placeholders took, in turn
    bool unknownKind = false;   // a placeholder whose kind wasn't recorded
    if (replaced > 0 && replaced < static_cast<int>(ids.size()) && !frozen) {
        auto indexOf = [&geos](long id) {
            for (std::size_t i = 0; i < geos.size(); ++i) {
                if (GeometryFacade::getId(geos[i]) == id) {
                    return static_cast<int>(i);
                }
            }
            return -1;
        };
        int previous = -1;  // the index of the entry's previous geometry
        for (std::size_t n = 0; n < refs.size(); ++n) {
            if (kept[n]) {
                previous = indexOf(refs[n]);
                continue;
            }
            int model = previous;  // a kept geometry of the entry, which the placeholder copies
            if (model < 0) {
                auto next = std::find(kept.begin() + n, kept.end(), true);
                model = indexOf(refs[next - kept.begin()]);
            }
            if (model < 0) {
                continue;  // not expected: a kept Id is in ExternalGeo
            }
            const int at = previous >= 0 ? previous + 1 : model;
            auto placeholder = geos[model]->copy();
            GeometryFacade::setId(placeholder, refs[n]);
            // The rebuild keeps the placeholder's flags on the projection: give it the entry's
            auto egf = ExternalGeometryFacade::getFacade(placeholder);
            egf->setRef(key);
            // a copy of another geometry: not from that one's source edge (ops#264 e2)
            egf->setSource(std::string());
            egf->setFlag(ExternalGeometryExtension::Defining, defining);
            egf->setFlag(ExternalGeometryExtension::Frozen, false);
            egf->setFlag(ExternalGeometryExtension::Sync, false);
            egf->setFlag(ExternalGeometryExtension::Missing, false);
            egf->setFlag(ExternalGeometryExtension::Detached, false);
            // and the kind its Id had when the entry was parked, not its model's: the rebuild
            // hands the Ids out per kind, so a placeholder of the other kind would take that
            // kind's Id, and the constraints would move to another geometry (PR 241 review H1)
            const int kind = n < kinds.size() ? kinds[n] : -1;
            if (kind >= 0) {
                setKind(placeholder, kind == 1);
            }
            else {
                clearKind(placeholder);
                unknownKind = true;
            }
            geos.insert(geos.begin() + at, placeholder);
            inserted.push_back(at);
            previous = at;
        }
    }

    // A kind not recorded (a parked line written before PR 241's round 1): the entry's geometries
    // lose their kinds, so the rebuild gives the Ids by position, as before ops#264. Parked
    // geometry has no reference, so no rebuild gave it a kind since it was parked: from such a
    // line it has none, and ExternalGeo holds it in build order already
    if (unknownKind) {
        for (std::size_t n = 0; n < refs.size(); ++n) {
            if (!kept[n]) {
                continue;
            }
            for (auto& geo : geos) {
                if (GeometryFacade::getId(geo) == refs[n]) {
                    clearKind(geo);
                    break;
                }
            }
        }
    }

    // FreeCAD-CH (ops#278): kept geometry without a kind (also parked before ops#264, when parking
    // kept none) splits a Both entry's Ids between its projection and its intersections by
    // position: a split that moved while the entry was parked moves constraints
    if (type == static_cast<int>(ExtType::Both)) {
        bool kindless = false;
        for (std::size_t n = 0; n < refs.size() && !kindless; ++n) {
            if (!kept[n]) {
                continue;
            }
            for (const auto* geo : geos) {
                if (GeometryFacade::getId(geo) == refs[n]) {
                    kindless = !kindOf(geo);
                    break;
                }
            }
        }
        if (kindless) {
            FC_WARN("External link " << key << " in " << getFullName()
                    << ": its geometry, put back from where it was set aside, doesn't record "
                       "which was projected and which intersections; at its next rebuild the "
                       "Ids go by position: check the constraints on it");
        }
    }

    if (inserted.empty()) {
        ExternalGeo.setValues(std::move(geos));
    }
    else {
        // The reverse of delExternalPrivate: each external GeoId at or after an inserted index
        // moves one on, so every constraint stays on its geometry. getValuesForce(): getValues()
        // is empty while the list is flagged invalid, and writing that back would delete every
        // constraint; a flagged list stays flagged (ops#140, ops#237)
        const bool invalidConstraints = Constraints.hasInvalidGeometry();
        std::vector<Constraint*> constraints;
        for (const auto& cstr : Constraints.getValuesForce()) {
            auto shifted = cstr->clone();
            for (int at : inserted) {
                const int geoId = -at - 1;
                for (int i = 0; shifted->hasElement(i); ++i) {
                    const int given = shifted->getGeoId(i);
                    if (given <= geoId && given != GeoEnum::GeoUndef) {
                        shifted->setGeoId(i, given - 1);
                    }
                }
            }
            constraints.push_back(shifted);
        }
        Base::StateLocker lock(managedoperation, true);
        ExternalGeo.setValues(std::move(geos));
        solverNeedsUpdate = true;
        Constraints.setValues(std::move(constraints));
        if (invalidConstraints) {
            rebuildVertexIndex();
            signalElementsChanged();
        }
        else {
            acceptGeometry();
        }
    }
    externalGeoRefMap[key] = std::move(refs);
    return replaced;
}

int SketchObject::markExternalGeometryMissing(const std::vector<long>& ids, const std::string& ref)
{
    if (ref.empty()) {
        return 0;
    }
    auto geos = ExternalGeo.getValues();
    int marked = 0;
    for (long id : ids) {
        auto it = externalGeoMap.find(id);
        if (it == externalGeoMap.end()
            || !ExternalGeometryFacade::getFacade(geos[it->second])->getRef().empty()) {
            continue;
        }
        auto& geo = geos[it->second];
        geo = geo->clone();
        ExternalGeometryFacade::getFacade(geo)->setRef(ref);
        ExternalGeometryFacade::getFacade(geo)->setSource(std::string());  // (ops#264 e2)
        ++marked;
    }
    if (marked) {
        ExternalGeo.setValues(std::move(geos));
        touch();
    }
    return marked;
}

void SketchObject::updateGeometryRefs()
{
    const auto &objs = ExternalGeometry.getValues();
    const auto &subs = ExternalGeometry.getSubValues();
    const auto &shadows = ExternalGeometry.getShadowSubs();
    assert(subs.size() == shadows.size());
    std::vector<std::string> originalRefs;
    std::map<std::string,std::string> refMap;
    if (updateGeoRef) {
        assert(externalGeoRef.size() == objs.size());
        updateGeoRef = false;
        originalRefs = std::move(externalGeoRef);
    }
    externalGeoRef.clear();
    std::unordered_map<std::string, int> legacyMap;
    for (int i=0;i<(int)objs.size();++i) {
        auto obj = objs[i];
        const std::string& sub = shadows[i].newName.empty() ? subs[i] : shadows[i].newName;
        externalGeoRef.emplace_back(obj->getNameInDocument());
        auto &key = externalGeoRef.back();
        key += '.';

        legacyMap[key + Data::oldElementName(sub.c_str())] = i;

        if (!obj->isDerivedFrom<Part::Datum>()) {
            key += Data::newElementName(sub.c_str());
        }
        if (!originalRefs.empty() && originalRefs[i] != key) {
            refMap[originalRefs[i]] = key;
        }
    }
    // a renamed link still undecided since the open stays undecided under its new key (ops#140)
    std::set<std::string> renamedUndecided;
    for (const auto& v : refMap) {
        if (undecidedTypeKeys.erase(v.first) != 0) {
            renamedUndecided.insert(v.second);
        }
    }
    undecidedTypeKeys.insert(renamedUndecided.begin(), renamedUndecided.end());
    // a link that is gone with its geometry (delExternal) no longer waits: added again, it is a
    // new link, built with the type it is added with (PR 277 review M3: the key stayed, so the new
    // link was flagged as guessed). A link dropped from ExternalGeometry by other means (Python,
    // its source replaced by an object of the same name) still has its geometry, which the next
    // rebuilds mark missing and then link again: it keeps waiting, or it would come back built
    // from the type at its index, unflagged, and the next open would settle it (verification 3.6)
    std::set<std::string> geometryRefs;
    for (auto geo : ExternalGeo.getValues()) {
        const auto& ref = ExternalGeometryFacade::getFacade(geo)->getRef();
        if (!ref.empty()) {
            geometryRefs.insert(ref);
        }
    }
    for (auto it = undecidedTypeKeys.begin(); it != undecidedTypeKeys.end();) {
        if (std::find(externalGeoRef.begin(), externalGeoRef.end(), *it) == externalGeoRef.end()
            && geometryRefs.count(*it) == 0) {
            it = undecidedTypeKeys.erase(it);
        }
        else {
            ++it;
        }
    }
    bool touched = false;
    auto geos = ExternalGeo.getValues();
    if (!refMap.empty()) {
        for(auto &v : refMap) {
            auto it = externalGeoRefMap.find(v.first);
            if (it == externalGeoRefMap.end()) {
                continue;
            }
            for (long id : it->second) {
                auto iter = externalGeoMap.find(id);
                if (iter != externalGeoMap.end()) {
                    auto &geo = geos[iter->second];
                    geo = geo->clone();
                    auto egf = ExternalGeometryFacade::getFacade(geo);
                    // NOLINTNEXTLINE
                    FC_LOG(getFullName() << " ref change on ExternalEdge" << iter->second - 1 << ' '
                           << egf->getRef() << " -> " << v.second);
                    egf->setRef(v.second);
                    touched = true;
                }
            }
        }

        if (touched) {
            ExternalGeo.setValues(std::move(geos));
        }
        return;
    }

    // `refMap` is empty from here

    for (auto geo : geos) {
        auto egf = ExternalGeometryFacade::getFacade(geo);
        if (egf->getRefIndex() >= 0) {
            if (egf->getRefIndex() < (int)externalGeoRef.size()
                && egf->getRef() != externalGeoRef[egf->getRefIndex()]) {
                touched = true;
                egf->setRef(externalGeoRef[egf->getRefIndex()]);
            }
            egf->setRefIndex(-1);
            continue;
        }

        if (egf->getId() < 0 && !egf->getRef().empty()) {
            // NOLINTNEXTLINE
            FC_ERR("External geometry reference corrupted in " << getFullName()
                   << " Please check.");
            // This could happen if someone saved the sketch containing
            // external geometries using some rogue releases during the
            // migration period. As a remedy, We re-initiate the
            // external geometry here to trigger rebuild later, with
            // call to rebuildExternalGeometry()
            initExternalGeo();
            return;
        }

        auto it = legacyMap.find(egf->getRef());
        if (it == legacyMap.end() || egf->getRef() == externalGeoRef[it->second]) {
            continue;
        }

        if (getDocument() && !getDocument()->isPerformingTransaction()) {
            // FIXME: this is a bug. Find out when and why does this happen
            //
            // Amendment: maybe the original bug is because of not handling external geometry
            // changes during undo/redo, which should be considered as normal. So warning
            // only if not undo/redo.
            //
            // NOLINTNEXTLINE
            FC_WARN("Update legacy external reference "
                    << egf->getRef() << " -> " << externalGeoRef[it->second] << " in "
                    << getFullName());
        }
        else {
            // NOLINTNEXTLINE
            FC_LOG("Update undo/redo external reference "
                   << egf->getRef() << " -> " << externalGeoRef[it->second] << " in "
                   << getFullName());
        }
        touched = true;
        egf->setRef(externalGeoRef[it->second]);
    }

    if (touched) {
        ExternalGeo.setValues(std::move(geos));
    }
}

std::string SketchObject::getGeometryReference(int GeoId) const {
    auto geo = getGeometry(GeoId);
    if (!geo) {
        return {};
    }
    auto egf = ExternalGeometryFacade::getFacade(geo);
    if (egf->getRef().empty()) {
        return {};
    }

    const std::string &ref = egf->getRef();

    if (egf->testFlag(ExternalGeometryExtension::Missing)) {
        return std::string("? ") + ref;
    }

    auto pos = ref.find('.');
    if (pos == std::string::npos) {
        return ref;
    }
    std::string objName = ref.substr(0, pos);
    auto obj = getDocument()->getObject(objName.c_str());
    if (!obj) {
        return ref;
    }

    App::ElementNamePair elementName;
    App::GeoFeature::resolveElement(obj, ref.c_str() + pos + 1, elementName);
    if (!elementName.oldName.empty()) {
        return objName + "." + elementName.oldName;
    }
    return ref;
}
// clang-format on
