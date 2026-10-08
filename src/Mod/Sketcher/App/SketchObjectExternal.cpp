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
#include <Base/Console.h>
#include <Base/Tools.h>
#include <Base/Vector3D.h>
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
    if (!externalTypeRepairPending || types.size() <= count) {
        return {};
    }
    return {types.begin() + static_cast<std::ptrdiff_t>(count), types.end()};
}

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

    // Hereafter assuming: either in the same part, or in the root of document
    if (body_this && body_this != body_obj) {
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

    const std::vector<Part::Geometry*>& vals = getInternalGeometry();

    const std::vector<Sketcher::Constraint*>& cvals = Constraints.getValues();

    std::vector<Part::Geometry*> newVals(vals);

    std::vector<Constraint*> newcVals(cvals);

    int nextgeoid = vals.size();

    int nextextgeoid = getExternalGeometryCount();

    int nextcid = cvals.size();

    const std::vector<Part::Geometry*>& svals = psObj->getInternalGeometry();

    const std::vector<Sketcher::Constraint*>& scvals = psObj->Constraints.getValues();

    newVals.reserve(vals.size() + svals.size());
    newcVals.reserve(cvals.size() + scvals.size());

    const Base::Vector3d& origin = this->Placement.getValue().getPosition();
    const Base::Rotation& rotation = this->Placement.getValue().getRotation();
    const Base::Vector3d axisH = rotation.multVec(Base::Vector3d::UnitX);
    const Base::Vector3d axisV = rotation.multVec(Base::Vector3d::UnitY);

    std::map<int, int> extMap;
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
                        continue;
                    }
                }
            }
            auto copy = geo->copy();
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

        if (Objects.size() != SubElements.size() || sObjects.size() != sSubElements.size()) {
            assert(0 /*counts of objects and subelements in external geometry links do not match*/);
            Base::Console().error(
                "Internal error: counts of objects and subelements in external "
                "geometry links do not match\n"
            );
            return -1;
        }

        int si = 0;
        for (auto& sobj : sObjects) {
            int i = 0;
            for (auto& obj : Objects) {
                if (obj == sobj && SubElements[i] == sSubElements[si]) {
                    Base::Console().error(
                        "Link to %s already exists in this sketch. Delete the link and try again\n",
                        sSubElements[si].c_str()
                    );
                    return -1;
                }

                i++;
            }

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

    auto applyGeometryFlipCorrection = [xinv, yinv, origin, axisV, axisH](Part::Geometry* geoNew) {
        if (!xinv && !yinv) {
            return;
        }

        if (xinv) {
            geoNew->mirror(origin, axisV);
        }
        if (yinv) {
            geoNew->mirror(origin, axisH);
        }
    };

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

    auto applyConstraintFlipCorrection = [xinv, yinv](Sketcher::Constraint* newConstr) {
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

        // Angle
        if (newConstr->Type == Sketcher::Angle) {
            auto normalizeAngle = [](double angleDeg) {
                while (angleDeg > pi) {
                    angleDeg -= pi * 2.0;
                }
                while (angleDeg <= -pi) {
                    angleDeg += pi * 2.0;
                }
                return angleDeg;
            };

            if (xinv && yinv) {  // rotation 180 degrees around normal axis
                if (newConstr->First == -1 || newConstr->Second == -1 || newConstr->First == -2
                    || newConstr->Second == -2 || newConstr->Second == GeoEnum::GeoUndef) {
                    // angle to horizontal or vertical axis
                    newConstr->setValue(normalizeAngle(newConstr->getValue() + pi));
                }
                else {
                    // angle between two sketch entities
                    // do nothing
                }
            }
            else if (xinv) {  // rotation 180 degrees around vertical axis
                if (newConstr->First == -1 || newConstr->Second == -1
                    || newConstr->Second == GeoEnum::GeoUndef) {
                    // angle to horizontal axis
                    newConstr->setValue(normalizeAngle(pi - newConstr->getValue()));
                }
                else {
                    // angle between two sketch entities or angle to vertical axis
                    newConstr->setValue(normalizeAngle(-newConstr->getValue()));
                }
            }
            else if (yinv) {  // rotation 180 degrees around horizontal axis
                if (newConstr->First == -2 || newConstr->Second == -2) {
                    // angle to vertical axis
                    newConstr->setValue(normalizeAngle(pi - newConstr->getValue()));
                }
                else {
                    // angle between two sketch entities or angle to horizontal axis
                    newConstr->setValue(normalizeAngle(-newConstr->getValue()));
                }
            }
        }
    };

    for (const auto& constr : scvals) {
        Sketcher::Constraint* newConstr = constr->copy();
        if (constr->First >= 0) {
            newConstr->First += nextgeoid;
        }
        if (constr->Second >= 0) {
            newConstr->Second += nextgeoid;
        }
        if (constr->Third >= 0) {
            newConstr->Third += nextgeoid;
        }

        if (constr->First < -2 && constr->First != GeoEnum::GeoUndef) {
            newConstr->First -= (nextextgeoid - 2);
        }
        if (constr->Second < -2 && constr->Second != GeoEnum::GeoUndef) {
            newConstr->Second -= (nextextgeoid - 2);
        }
        if (constr->Third < -2 && constr->Third != GeoEnum::GeoUndef) {
            newConstr->Third -= (nextextgeoid - 2);
        }

        if (xinv || yinv) {
            // corrections for flipped constraints
            applyConstraintFlipCorrection(newConstr);
        }

        newcVals.push_back(newConstr);
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
        [xinv, yinv](const Sketcher::Constraint* constr, const std::string expr) -> std::string {
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

        // Angle
        if (constr->Type == Sketcher::Angle) {
            if (xinv && yinv) {  // rotation 180 degrees around normal axis
                if (constr->First == -1 || constr->Second == -1 || constr->First == -2
                    || constr->Second == -2 || constr->Second == GeoEnum::GeoUndef) {
                    // angle to horizontal or vertical axis
                    return "(" + expr + ") + 180 deg";
                }
                else {
                    // angle between two sketch entities
                    // do nothing
                    return expr;
                }
            }
            else if (xinv) {  // rotation 180 degrees around vertical axis
                if (constr->First == -1 || constr->Second == -1
                    || constr->Second == GeoEnum::GeoUndef) {
                    // angle to horizontal axis
                    return "180 deg - (" + expr + ")";
                }
                else {
                    // angle between two sketch entities or angle to vertical axis
                    return "-(" + expr + ")";
                }
            }
            else if (yinv) {  // rotation 180 degrees around horizontal axis
                if (constr->First == -2 || constr->Second == -2) {
                    // angle to vertical axis
                    return "180 deg - (" + expr + ")";
                }
                else {
                    // angle between two sketch entities or angle to horizontal axis
                    return "-(" + expr + ")";
                }
            }
        }
        return expr;
    };

    int sourceid = 0;
    for (auto it = scvals.cbegin(); it != scvals.cend(); ++it, ++nextcid, ++sourceid) {
        if (!((*it)->isDimensional() && (*it)->isDriving)) {
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
        setExpression(Constraints.createPath(nextcid), std::move(expr));
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
            addExternal(Obj, element.c_str(), defining, intersection);
            element.resize(elementNameSize);
        }
        if (ExternalGeometry.getSize() == geometryCount) {
            return -1;
        }
        return geometryCount;
    }

    // get the actual lists of the externals
    std::vector<long> Types = ExternalTypes.getValues();
    std::vector<DocumentObject*> Objects = ExternalGeometry.getValues();
    std::vector<std::string> SubElements = ExternalGeometry.getSubValues();
    Types.resize(Objects.size(), static_cast<long>(ExtType::Projection));

    const std::vector<DocumentObject*> originalObjects = Objects;
    const std::vector<std::string> originalSubElements = SubElements;
    const std::vector<long> originalTypes = ExternalTypes.getValues();

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
        // Case where projections are already there when adding intersections.
        add = false;
        Types[i] = static_cast<int>(ExtType::Both);
    }
    if (add) {
        // add the new ones
        Objects.push_back(Obj);
        SubElements.emplace_back(SubName);
        Types.push_back(static_cast<int>(intersection ? ExtType::Intersection : ExtType::Projection));

        // set the Link list.
        setExternalLinksAndTypes(Objects, SubElements, Types);
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
        setExternalLinksAndTypes(originalObjects, originalSubElements, originalTypes);
        return -1;
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

    setExternalLinksAndTypes(Objects, SubElements, Types);
    if(externalGeoRef.size()!=Objects.size())
        return -1;

    std::string ref = externalGeoRef.back();
    for(auto geoId : idSet) {
        auto &geo = geos[-geoId-1];
        geo = geo->clone();
        ExternalGeometryFacade::getFacade(geo)->setRef(ref);
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
                  TopoDS_Shape& refSubShape)
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
        for (edgeExp.Init(face, TopAbs_EDGE); edgeExp.More(); edgeExp.Next()) {
            TopoDS_Edge edge = TopoDS::Edge(edgeExp.Current());
            // Process each edge
            processEdge(edge, geos, gPlane, invPlm, mov, sketchPlane, invRot, sketchAx3, aProjFace);
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

// the error of a sketch whose external geometry lost its element (ops#72); defined below
std::string missingReferenceMessage(
    const App::Document* doc,
    const std::vector<std::pair<std::string, std::vector<std::size_t>>>& missingRefs,
    const std::vector<App::DocumentObject*>& objects,
    const std::vector<std::string>& subElements,
    const std::vector<std::string>& keys);

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
            const double near = std::min({Base::Distance(p, to->pointAtParameter(u)),
                                          Base::Distance(p, to->pointAtParameter(toFirst)),
                                          Base::Distance(p, to->pointAtParameter(toLast))});
            distance = std::max(distance, near);
        }
        return distance;
    };
    return std::max(oneWay(curve, savedCurve), oneWay(savedCurve, curve));
}

// The entry that marks a type list whose repair on open couldn't tell every link's type: the next
// open repairs only the links that are still undecided (ops#140). No type has this value.
constexpr long pendingTypeRepairMark = -1;

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
    const bool openRepair = typesOnly && Types.size() > linkCount;
    if (typesOnly && !openRepair) {
        return;
    }
    const bool laterOpen = openRepair
        && std::find(Types.begin() + static_cast<std::ptrdiff_t>(linkCount), Types.end(),
                     pendingTypeRepairMark)
            != Types.end();
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
                auto it = std::find(keys.begin(), keys.begin() + linkCount, ref);
                if (it != keys.begin() + linkCount) {
                    auto index = static_cast<std::size_t>(it - keys.begin());
                    if (Objects[index] == obj && SubElements[index] != elementName.oldName
                        && !ExternalGeometry.inSolverDocument()) {
                        SubElements[index] = elementName.oldName;
                        relinked.insert(index);
                    }
                    continue;
                }
                Objects.push_back(obj);
                SubElements.push_back(elementName.oldName);
                keys.push_back(ref);
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

    std::set<std::string> refSet;
    // We use a vector here to keep the order (roughly) the same as ExternalGeometry
    std::vector<std::vector<std::unique_ptr<Part::Geometry> > > newGeos;
    newGeos.reserve(Objects.size());
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

            if (projection && !refSubShape.IsNull()) {
                switch (refSubShape.ShapeType()) {
                case TopAbs_FACE: {
                    processFace(invRot, invPlm, mov, sketchPlane, gPlane, sketchAx3, aProjFace, geos, refSubShape);
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
            int projSize = geos.size();

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
                // circle/arc.
                if (refSubShape.ShapeType() == TopAbs_FACE && geos.size() > 1) {
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
                        if (auto geo = fitArcs(geos, P1, P2, ArcFitTolerance.getValue())) {
                            geos.clear();
                            geos.emplace_back(geo);
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
        };

        std::vector<const Part::Geometry*> saved;
        bool savedMissing = false;
        if (openRepair || !undecidedTypeKeys.empty()) {
            for (long id : externalGeoRefMap[key]) {
                auto it = externalGeoMap.find(id);
                if (it != externalGeoMap.end()) {
                    saved.push_back(ExternalGeo[it->second]);
                    savedMissing = savedMissing
                        || ExternalGeometryFacade::getFacade(ExternalGeo[it->second])
                               ->testFlag(ExternalGeometryExtension::Missing);
                }
            }
        }
        const bool repairThis = openRepair
            ? (!laterOpen || saved.empty() || savedMissing)
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
            auto matchSaved = [&](long type) -> std::pair<Match, double> {
                setType(type);
                geos.clear();
                try {
                    build();
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
            if (!saved.empty() && hasSource) {
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
            else if (auto type = typeFromSavedGeometry(SubElement, saved)) {
                Types[i] = *type;
            }
            else {
                decided = false;
                undecided = true;
                if (typesOnly) {
                    undecidedTypeKeys.insert(key);
                    FC_WARN("External link " << key << " in " << getFullName()
                            << ": its type can't be told from a type list saved before ops#140;"
                            << " it keeps type " << indexType);
                }
            }
            if (decided && !typesOnly) {
                undecidedTypeKeys.erase(key);
                typesRepaired = true;
            }
            setType(Types[i]);
            geos.clear();
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
        newGeos.push_back(std::move(geos));
    }

    if (typesOnly) {
        Types.resize(linkCount);
        externalTypeRepairPending = undecided;
        if (undecided) {
            Types.push_back(pendingTypeRepairMark);
        }
        ExternalTypes.setValues(Types);
        return;
    }

    // allocate unique geometry id
    for(auto &geos : newGeos) {
        auto egf = ExternalGeometryFacade::getFacade(geos.front().get());
        auto &refs = externalGeoRefMap[egf->getRef()];
        while(refs.size() < geos.size())
            refs.push_back(++geoLastId);

        // In case a projection reduces output geometries, delete them
        std::set<long> geoIds;
        geoIds.insert(refs.begin()+geos.size(),refs.end());

        // Sync id and ref of the new geometries
        int i = 0;
        for(auto &geo : geos)
            GeometryFacade::setId(geo.get(), refs[i++]);

        delExternalPrivate(geoIds,false);
    }

    auto geoms = ExternalGeo.getValues();

    // now update the geometries
    for(auto &geos : newGeos) {
        if (geos.empty()) {
            continue;
        }

        // Get the reference key for this group of geometries. All geos in this vector share the same ref.
        const std::string& key = ExternalGeometryFacade::getFacade(geos.front().get())->getRef();
        auto itKey = linkIsDefiningMap.find(key);
        bool hasLinkState = itKey != linkIsDefiningMap.end();
        bool isLinkDefining = hasLinkState ? itKey->second : false;

        for(auto &geo : geos) {
            auto it = externalGeoMap.find(GeometryFacade::getId(geo.get()));
            if(it == externalGeoMap.end()) {
                // This is a new geometries.
                // Set its defining state based on the inferred state of its parent link.
                if (hasLinkState) {
                    ExternalGeometryFacade::getFacade(geo.get())->setFlag(ExternalGeometryExtension::Defining, isLinkDefining);
                }
                geoms.push_back(geo.release());
                continue;
            }
            // This is an existing geometry. Update it while keeping the old flags
            ExternalGeometryFacade::copyFlags(geoms[it->second], geo.get());
            geoms[it->second] = geo.release();
        }
    }

    // Check for any missing references
    bool hasError = false;
    // the missing references, in order, with the indexes of their geometries in geoms
    std::vector<std::pair<std::string, std::vector<std::size_t>>> missingRefs;
    for (std::size_t index = 0; index < geoms.size(); ++index) {
        auto egf = ExternalGeometryFacade::getFacade(geoms[index]);
        egf->setFlag(ExternalGeometryExtension::Sync,false);
        if(egf->getRef().empty())
            continue;
        if(!refSet.count(egf->getRef())) {
            FC_ERR( "External geometry " << getFullName() << ".e" << egf->getId()
                    << " missing reference: " << egf->getRef());
            hasError = true;
            egf->setFlag(ExternalGeometryExtension::Missing,true);
            const std::string& ref = egf->getRef();
            auto it = std::find_if(missingRefs.begin(), missingRefs.end(), [&](const auto& entry) {
                return entry.first == ref;
            });
            if (it == missingRefs.end()) {
                it = missingRefs.emplace(missingRefs.end(), ref, std::vector<std::size_t> {});
            }
            it->second.push_back(index);
        } else {
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

    solverNeedsUpdate=true;
    if (!keepConstraintsInvalid) {
        Constraints.acceptGeometry(getCompleteGeometry());
    }

    if (hasError && this->isRecomputing()) {
        throw Base::RuntimeError(
            missingReferenceMessage(getDocument(), missingRefs, Objects, SubElements, keys));
    }
}

namespace
{
std::string missingReferenceMessage(
    const App::Document* doc,
    const std::vector<std::pair<std::string, std::vector<std::size_t>>>& missingRefs,
    const std::vector<App::DocumentObject*>& objects,
    const std::vector<std::string>& subElements,
    const std::vector<std::string>& keys)
{
    // Names each missing reference as the user sees it, Label.Element, with the external
    // geometry it gave (ExternalEdgeN, as the sketcher selects it; the first two are the axes)
    std::string message = missingRefs.size() == 1 ? "Missing external geometry reference: "
                                                  : "Missing external geometry references: ";
    bool first = true;
    for (const auto& [ref, indexes] : missingRefs) {
        if (!first) {
            message += "; ";
        }
        first = false;

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

        message += " (";
        for (std::size_t i = 0; i < indexes.size(); ++i) {
            message += (i ? ", " : "") + std::string("ExternalEdge")
                + std::to_string(static_cast<long>(indexes[i]) - 1);
        }
        message += ")";
    }
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
    // externalGeoRefMap lists a key's Ids in the order of ExternalGeo, which is the order the
    // rebuild gives them to the projections
    auto it = externalGeoRefMap.find(externalGeoRef[entry]);
    if (it == externalGeoRefMap.end()) {
        return {};
    }
    return it->second;
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
    ExternalGeometry.setValues(std::move(objs), std::move(subs), std::move(shadows));
    ExternalTypes.setValues(types);
}

int SketchObject::unparkExternalGeometry(App::DocumentObject* obj,
                                         const std::string& sub,
                                         App::PropertyLinkBase::ShadowSub&& shadow,
                                         int type,
                                         const std::vector<long>& ids)
{
    auto objs = ExternalGeometry.getValues();
    auto subs = ExternalGeometry.getSubValues();
    auto shadows = ExternalGeometry.getShadowSubs();
    if (!obj || !canRetargetExternalGeometry() || subs.size() != objs.size()
        || shadows.size() != objs.size()) {
        throw Base::RuntimeError("unparkExternalGeometry: the projections are out of step with "
                                 "the links");
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
        Base::StateLocker lock(externalLinksWithTypes, true);
        ExternalGeometry.setValues(std::move(objs), std::move(subs), std::move(shadows));
        ExternalTypes.setValues(types);
    }
    if (externalGeoRef.size() != ExternalGeometry.getValues().size()) {
        throw Base::RuntimeError("unparkExternalGeometry: the link was not added");
    }
    const std::string key = externalGeoRef.back();

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
            egf->setFlag(ExternalGeometryExtension::Defining, defining);
            egf->setFlag(ExternalGeometryExtension::Frozen, false);
            egf->setFlag(ExternalGeometryExtension::Sync, false);
            egf->setFlag(ExternalGeometryExtension::Missing, false);
            egf->setFlag(ExternalGeometryExtension::Detached, false);
            geos.insert(geos.begin() + at, placeholder);
            inserted.push_back(at);
            previous = at;
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
