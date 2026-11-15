// SPDX-License-Identifier: LGPL-2.1-or-later
// FreeCAD-CH (Onshape's sketch patterns, onshape-facts GA3-28, 28b, 28c;
// notes/sketch-patterns-design.md): making and editing a pattern's record and copies. The record
// is SketchPattern.h's; the solver's equations are Sketch::addPatternConstraint's; the delete paths
// are in SketchObject::changeConstraintAfterDeletingGeo.

#include <algorithm>
#include <cmath>
#include <memory>
#include <numbers>
#include <set>

#include <Precision.hxx>

#include <Base/Exception.h>
#include <Base/Placement.h>
#include <Base/Tools.h>
#include <Base/Rotation.h>
#include <Mod/Part/App/Geometry.h>

#include "GeometryFacade.h"
#include "SketchObject.h"
#include "SketchPattern.h"

using namespace Sketcher;

namespace
{

using Slot = PatternRecord::Slot;

bool patternable(const Part::Geometry* geo)
{
    const Base::Type type = geo->getTypeId();
    return type == Part::GeomPoint::getClassTypeId() || type == Part::GeomLineSegment::getClassTypeId()
        || type == Part::GeomCircle::getClassTypeId()
        || type == Part::GeomArcOfCircle::getClassTypeId();
}

// where a linear pattern's direction line starts (GA3-28c: the seed's centre)
Base::Vector3d centreOf(const Part::Geometry* geo)
{
    if (auto point = dynamic_cast<const Part::GeomPoint*>(geo)) {
        return point->getPoint();
    }
    if (auto line = dynamic_cast<const Part::GeomLineSegment*>(geo)) {
        return (line->getStartPoint() + line->getEndPoint()) / 2.0;
    }
    if (auto conic = dynamic_cast<const Part::GeomConic*>(geo)) {
        return conic->getCenter();
    }
    if (auto arc = dynamic_cast<const Part::GeomArcOfConic*>(geo)) {
        return arc->getCenter();
    }
    return Base::Vector3d();
}

// gives copy (same type as seed) the seed's shape, keeping its own extensions (its id, its
// construction flag)
void takeShape(Part::Geometry* copy, const Part::Geometry* seed)
{
    if (copy->getTypeId() != seed->getTypeId()) {
        throw Base::ValueError("Pattern: a copy is not of its seed's type");
    }
    if (auto point = dynamic_cast<Part::GeomPoint*>(copy)) {
        point->setPoint(static_cast<const Part::GeomPoint*>(seed)->getPoint());
    }
    else if (auto line = dynamic_cast<Part::GeomLineSegment*>(copy)) {
        auto from = static_cast<const Part::GeomLineSegment*>(seed);
        line->setPoints(from->getStartPoint(), from->getEndPoint());
    }
    else if (auto arc = dynamic_cast<Part::GeomArcOfCircle*>(copy)) {
        auto from = static_cast<const Part::GeomArcOfCircle*>(seed);
        arc->setCenter(from->getCenter());
        arc->setRadius(from->getRadius());
        double u = 0;
        double v = 0;
        from->getRange(u, v, true);
        arc->setRange(u, v, true);
    }
    else if (auto circle = dynamic_cast<Part::GeomCircle*>(copy)) {
        auto from = static_cast<const Part::GeomCircle*>(seed);
        circle->setCenter(from->getCenter());
        circle->setRadius(from->getRadius());
    }
}

struct Frame
{
    Base::Vector3d pivot;
    Base::Vector3d step1;
    Base::Vector3d step2;
};

// the pattern's frame as the geometry is now: the pivot, or the direction lines' vectors
Frame frameOf(const PatternRecord& record, const std::vector<Part::Geometry*>& geos)
{
    Frame frame;
    auto vectorOf = [&](int geoId) {
        if (geoId < 0 || geoId >= int(geos.size())) {
            return Base::Vector3d();
        }
        auto line = static_cast<const Part::GeomLineSegment*>(geos[geoId]);
        return line->getEndPoint() - line->getStartPoint();
    };
    if (record.kind == PatternRecord::Kind::Circular) {
        frame.pivot = static_cast<const Part::GeomPoint*>(geos[record.pivot])->getPoint();
    }
    else {
        frame.step1 = vectorOf(record.direction1);
        frame.step2 = vectorOf(record.direction2);
    }
    return frame;
}

// puts copy (holding its seed's shape) at its slot
void place(Part::Geometry* copy, const PatternRecord& record, const Frame& frame, const Slot& slot)
{
    if (record.kind == PatternRecord::Kind::Circular) {
        const double angle = slot[1] * record.stepAngle();
        if (angle != 0.0) {
            copy->rotate(Base::Placement(frame.pivot, Base::Rotation(Base::Vector3d(0, 0, 1), angle)));
        }
        return;
    }
    copy->translate(frame.step1 * slot[1] + frame.step2 * slot[2]);
}

}  // namespace

std::optional<PatternRecord> SketchObject::getPattern(int constrId) const
{
    const auto& constraints = Constraints.getValues();
    if (constrId < 0 || constrId >= int(constraints.size())) {
        return std::nullopt;
    }
    return PatternRecord::read(*constraints[constrId]);
}

namespace
{

// the seeds' checks common to both kinds: Base::ValueError when refused
void checkSeeds(const SketchObject& sketch, const std::vector<int>& seeds)
{
    if (seeds.empty()) {
        throw Base::ValueError("Pattern: no seeds given");
    }
    if (std::set<int>(seeds.begin(), seeds.end()).size() != seeds.size()) {
        throw Base::ValueError("Pattern: a seed is given twice");
    }
    // another pattern's copies and owned geometry are that pattern's: a second pattern on them
    // would fight the first
    std::set<int> owned;
    const auto& constraints = sketch.Constraints.getValues();
    for (int i = 0; i < int(constraints.size()); ++i) {
        if (auto record = sketch.getPattern(i)) {
            owned.insert({record->pivot, record->direction1, record->direction2});
            for (const auto& [slot, copy] : record->instances) {
                owned.insert(copy);
            }
        }
    }
    for (int seed : seeds) {
        if (seed < 0 || seed > sketch.getHighestCurveIndex()) {
            throw Base::ValueError("Pattern: a seed is not the sketch's own geometry");
        }
        const Part::Geometry* geo = sketch.getGeometry(seed);
        if (!patternable(geo)) {
            throw Base::ValueError("Pattern: a seed must be a point, a line, a circle or an arc");
        }
        if (GeometryFacade::getFacade(geo)->isInternalAligned()) {
            throw Base::ValueError("Pattern: a seed is another curve's internal geometry");
        }
        if (owned.contains(seed)) {
            throw Base::ValueError("Pattern: a seed is another pattern's copy, pivot or direction");
        }
    }
}

}  // namespace

// as addCopy: one change of the geometry and one of the constraints, then the solver (by the
// caller, as for addSymmetric)
int SketchObject::addCircularPattern(
    const std::vector<int>& seeds,
    int count,
    const Base::Vector3d& pivot,
    double angle
)
{
    checkSeeds(*this, seeds);
    if (count < 1) {
        throw Base::ValueError("Pattern: the count must be at least 1");
    }
    if (!PatternRecord::withinSlotCap(seeds.size(), count, 1)) {
        throw Base::ValueError("Pattern: more than 100000 instances");
    }
    if (!std::isfinite(angle) || angle == 0.0 || std::abs(angle) > 2.0 * std::numbers::pi + 1e-9) {
        throw Base::ValueError("Pattern: the angle must be in (0, 360] degrees either way");
    }
    Base::StateLocker lock(managedoperation, true);

    std::vector<Part::Geometry*> newGeos(getInternalGeometry());
    PatternRecord record;
    record.kind = PatternRecord::Kind::Circular;
    record.seeds = seeds;
    record.count1 = count;
    record.angle = angle;

    auto owned = std::make_unique<Part::GeomPoint>(Base::Vector3d(pivot.x, pivot.y, 0));
    generateId(owned.get());
    GeometryFacade::setConstruction(owned.get(), true);
    record.pivot = int(newGeos.size());
    newGeos.push_back(owned.release());

    const Frame frame {Base::Vector3d(pivot.x, pivot.y, 0), Base::Vector3d(), Base::Vector3d()};
    for (const Slot& slot : record.slots()) {
        Part::Geometry* copy = newGeos[seeds[slot[0]]]->copy();
        generateId(copy);
        place(copy, record, frame, slot);
        record.instances[slot] = int(newGeos.size());
        newGeos.push_back(copy);
    }

    std::vector<Constraint*> newConstraints(Constraints.getValues());
    auto constr = new Constraint();
    record.write(*constr);
    newConstraints.push_back(constr);
    {
        Base::StateLocker preventUpdate(internaltransaction, true);
        Geometry.setValues(std::move(newGeos));
        Constraints.setValues(std::move(newConstraints));
    }
    Geometry.touch();
    return Constraints.getSize() - 1;
}

int SketchObject::addLinearPattern(
    const std::vector<int>& seeds,
    int count1,
    const Base::Vector3d& direction1,
    int count2,
    const Base::Vector3d& direction2
)
{
    checkSeeds(*this, seeds);
    if (count1 < 1 || count2 < 1) {
        throw Base::ValueError("Pattern: the counts must be at least 1");
    }
    if (!PatternRecord::withinSlotCap(seeds.size(), count1, count2)) {
        throw Base::ValueError("Pattern: more than 100000 instances");
    }
    const Base::Vector3d step1(direction1.x, direction1.y, 0);
    if (step1.Length() < Precision::Confusion()) {
        throw Base::ValueError("Pattern: the first direction has no length");
    }
    Base::Vector3d step2(direction2.x, direction2.y, 0);
    if (step2.Length() < Precision::Confusion()) {
        step2 = Base::Vector3d(-step1.y, step1.x, 0);  // a quarter turn counterclockwise
    }
    Base::StateLocker lock(managedoperation, true);

    std::vector<Part::Geometry*> newGeos(getInternalGeometry());
    PatternRecord record;
    record.kind = PatternRecord::Kind::Linear;
    record.seeds = seeds;
    record.count1 = count1;
    record.count2 = count2;

    const Base::Vector3d origin = centreOf(newGeos[seeds.front()]);
    auto addDirection = [&](const Base::Vector3d& step) {
        auto line = std::make_unique<Part::GeomLineSegment>();
        line->setPoints(origin, origin + step);
        generateId(line.get());
        GeometryFacade::setConstruction(line.get(), true);
        newGeos.push_back(line.release());
        return int(newGeos.size()) - 1;
    };
    record.direction1 = addDirection(step1);
    if (count2 > 1) {
        record.direction2 = addDirection(step2);
    }

    const Frame frame {Base::Vector3d(), step1, step2};
    for (const Slot& slot : record.slots()) {
        Part::Geometry* copy = newGeos[seeds[slot[0]]]->copy();
        generateId(copy);
        place(copy, record, frame, slot);
        record.instances[slot] = int(newGeos.size());
        newGeos.push_back(copy);
    }

    std::vector<Constraint*> newConstraints(Constraints.getValues());
    auto constr = new Constraint();
    record.write(*constr);
    newConstraints.push_back(constr);
    {
        Base::StateLocker preventUpdate(internaltransaction, true);
        Geometry.setValues(std::move(newGeos));
        Constraints.setValues(std::move(newConstraints));
    }
    Geometry.touch();
    return Constraints.getSize() - 1;
}

void SketchObject::setPatternCount(int constrId, int count1, int count2)
{
    auto old = getPattern(constrId);
    // a record read from a file may name geometry out of range or of the wrong type
    if (old && !evaluateConstraint(Constraints.getValues()[constrId])) {
        throw Base::ValueError("Pattern: the pattern's record is malformed");
    }
    if (!old) {
        throw Base::ValueError("Pattern: the constraint is not a pattern");
    }
    if (count2 <= 0) {
        count2 = old->count2;
    }
    if (count1 < 1 || (old->kind == PatternRecord::Kind::Circular && count2 != 1)) {
        throw Base::ValueError(
            "Pattern: the counts must be at least 1 (a circular pattern has one count)"
        );
    }
    if (!PatternRecord::withinSlotCap(old->seeds.size(), count1, count2)) {
        throw Base::ValueError("Pattern: more than 100000 instances");
    }
    Base::StateLocker lock(managedoperation, true);

    std::vector<Part::Geometry*> newGeos(getInternalGeometry());
    PatternRecord record = *old;
    record.count1 = count1;
    record.count2 = count2;
    record.instances.clear();

    if (record.kind == PatternRecord::Kind::Linear && count2 > 1
        && record.direction2 == GeoEnum::GeoUndef) {
        // the second direction, first needed now: the first's turned a quarter counterclockwise
        auto first = static_cast<const Part::GeomLineSegment*>(newGeos[record.direction1]);
        const Base::Vector3d start = first->getStartPoint();
        const Base::Vector3d step = first->getEndPoint() - start;
        auto line = std::make_unique<Part::GeomLineSegment>();
        line->setPoints(start, start + Base::Vector3d(-step.y, step.x, 0));
        generateId(line.get());
        GeometryFacade::setConstruction(line.get(), true);
        record.direction2 = int(newGeos.size());
        newGeos.push_back(line.release());
    }

    const Frame frame = frameOf(record, newGeos);
    for (const Slot& slot : record.slots()) {
        auto it = old->instances.find(slot);
        if (it != old->instances.end()) {
            record.instances[slot] = it->second;  // kept, a copy or an empty slot
            if (it->second == GeoEnum::GeoUndef) {
                continue;
            }
            Part::Geometry* copy = newGeos[it->second]->clone();
            takeShape(copy, newGeos[record.seeds[slot[0]]]);
            place(copy, record, frame, slot);
            newGeos[it->second] = copy;
            continue;
        }
        Part::Geometry* copy = newGeos[record.seeds[slot[0]]]->copy();
        generateId(copy);
        place(copy, record, frame, slot);
        record.instances[slot] = int(newGeos.size());
        newGeos.push_back(copy);
    }
    std::vector<int> dropped;
    for (const auto& [slot, copy] : old->instances) {
        if (copy != GeoEnum::GeoUndef && !record.instances.contains(slot)) {
            dropped.push_back(copy);
        }
    }

    std::vector<Constraint*> newConstraints(Constraints.getValues());
    Constraint* constr = newConstraints[constrId]->clone();  // its tag kept: the same constraint
    record.write(*constr);
    newConstraints[constrId] = constr;
    {
        Base::StateLocker preventUpdate(internaltransaction, true);
        Geometry.setValues(std::move(newGeos));
        Constraints.setValues(std::move(newConstraints));
    }
    if (!dropped.empty()) {
        // the record no longer names them: the deletion renumbers it with the rest
        delGeometriesExclusiveList(dropped, DeleteOption::NoSolve);
    }
    Geometry.touch();
}

void SketchObject::setPatternAngle(int constrId, double angle)
{
    auto old = getPattern(constrId);
    // a record read from a file may name geometry out of range or of the wrong type
    if (old && !evaluateConstraint(Constraints.getValues()[constrId])) {
        throw Base::ValueError("Pattern: the pattern's record is malformed");
    }
    if (!old || old->kind != PatternRecord::Kind::Circular) {
        throw Base::ValueError("Pattern: the constraint is not a circular pattern");
    }
    if (!std::isfinite(angle) || angle == 0.0 || std::abs(angle) > 2.0 * std::numbers::pi + 1e-9) {
        throw Base::ValueError("Pattern: the angle must be in (0, 360] degrees either way");
    }
    Base::StateLocker lock(managedoperation, true);

    std::vector<Part::Geometry*> newGeos(getInternalGeometry());
    PatternRecord record = *old;
    record.angle = angle;
    const Frame frame = frameOf(record, newGeos);
    for (const auto& [slot, copyId] : record.instances) {
        if (copyId == GeoEnum::GeoUndef) {
            continue;
        }
        Part::Geometry* copy = newGeos[copyId]->clone();
        takeShape(copy, newGeos[record.seeds[slot[0]]]);
        place(copy, record, frame, slot);
        newGeos[copyId] = copy;
    }
    std::vector<Constraint*> newConstraints(Constraints.getValues());
    Constraint* constr = newConstraints[constrId]->clone();
    record.write(*constr);
    newConstraints[constrId] = constr;
    {
        Base::StateLocker preventUpdate(internaltransaction, true);
        Geometry.setValues(std::move(newGeos));
        Constraints.setValues(std::move(newConstraints));
    }
    Geometry.touch();
}
