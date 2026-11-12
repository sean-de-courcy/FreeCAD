// SPDX-License-Identifier: LGPL-2.1-or-later
// FreeCAD-CH (Onshape's sketch patterns): see SketchPattern.h.

#include <cmath>
#include <numbers>
#include <string>

#include "nlohmann/json.hpp"

#include "Constraint.h"
#include "SketchPattern.h"

using namespace Sketcher;

namespace
{
constexpr double fullTurn = 2.0 * std::numbers::pi;
}

bool PatternRecord::isPattern(const Constraint* constr)
{
    return constr && constr->Type == Pattern;
}

std::vector<PatternRecord::Slot> PatternRecord::slots() const
{
    std::vector<Slot> result;
    for (int i = 0; i < int(seeds.size()); ++i) {
        if (kind == Kind::Circular) {
            for (int k = 1; k < count1; ++k) {
                result.push_back({i, k, 0});
            }
            continue;
        }
        for (int a = 0; a < count1; ++a) {
            for (int b = 0; b < count2; ++b) {
                if (a != 0 || b != 0) {
                    result.push_back({i, a, b});
                }
            }
        }
    }
    return result;
}

bool PatternRecord::isFullCircle() const
{
    return std::abs(std::abs(angle) - fullTurn) < 1e-9;
}

double PatternRecord::stepAngle() const
{
    if (isFullCircle()) {
        return angle / count1;
    }
    return count1 > 1 ? angle / (count1 - 1) : 0.0;
}

std::optional<PatternRecord> PatternRecord::read(const Constraint& constr)
{
    if (constr.Type != Pattern) {
        return std::nullopt;
    }
    PatternRecord record;
    int seedCount = 0;
    try {
        const auto j = nlohmann::json::parse(constr.MetaData);
        const std::string kind = j.at("pattern").get<std::string>();
        if (kind == "circular") {
            record.kind = Kind::Circular;
        }
        else if (kind == "linear") {
            record.kind = Kind::Linear;
        }
        else {
            return std::nullopt;
        }
        seedCount = j.at("seeds").get<int>();
        record.count1 = j.at("count1").get<int>();
        record.count2 = j.at("count2").get<int>();
    }
    catch (...) {
        return std::nullopt;
    }
    // a circular pattern has one direction; the counts bound the table (a malformed record never
    // asks for millions of slots)
    if (seedCount < 1 || record.count1 < 1 || record.count2 < 1
        || (record.kind == Kind::Circular && record.count2 != 1)
        || double(seedCount) * record.count1 * record.count2 > 100000.0) {
        return std::nullopt;
    }
    const size_t header = seedCount + (record.kind == Kind::Circular ? 1 : 2);
    const size_t perSeed = record.kind == Kind::Circular ? record.count1 - 1
                                                         : record.count1 * record.count2 - 1;
    if (constr.getElementsSize() < header + seedCount * perSeed) {
        return std::nullopt;
    }
    for (int i = 0; i < seedCount; ++i) {
        record.seeds.push_back(constr.getGeoId(i));
    }
    if (record.kind == Kind::Circular) {
        record.pivot = constr.getGeoId(seedCount);
        record.angle = constr.getValue();
    }
    else {
        record.direction1 = constr.getGeoId(seedCount);
        record.direction2 = constr.getGeoId(seedCount + 1);
    }
    size_t index = header;
    for (const Slot& slot : record.slots()) {
        record.instances[slot] = constr.getGeoId(index++);
    }
    return record;
}

void PatternRecord::write(Constraint& constr) const
{
    constr.Type = Pattern;
    constr.truncateElements(0);
    for (int seed : seeds) {
        constr.addElement(GeoElementId(seed, PointPos::none));
    }
    if (kind == Kind::Circular) {
        constr.addElement(GeoElementId(pivot, PointPos::start));
    }
    else {
        constr.addElement(GeoElementId(direction1, PointPos::none));
        constr.addElement(GeoElementId(direction2, PointPos::none));
    }
    for (const Slot& slot : slots()) {
        auto it = instances.find(slot);
        constr.addElement(
            GeoElementId(it == instances.end() ? int(GeoEnum::GeoUndef) : it->second, PointPos::none)
        );
    }
    // as every constraint, at least First, Second and Third
    while (constr.getElementsSize() < 3) {
        constr.addElement(GeoElementId(GeoEnum::GeoUndef, PointPos::none));
    }
    nlohmann::json j;
    j["pattern"] = kind == Kind::Circular ? "circular" : "linear";
    j["seeds"] = int(seeds.size());
    j["count1"] = count1;
    j["count2"] = count2;
    constr.MetaData = j.dump();
    constr.setValue(kind == Kind::Circular ? angle : 0.0);
}
