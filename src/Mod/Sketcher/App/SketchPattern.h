// SPDX-License-Identifier: LGPL-2.1-or-later
// FreeCAD-CH (Onshape's sketch patterns, notes/sketch-patterns-design.md): the record of one
// circular or linear sketch pattern, stored in one Sketcher::Constraint of type Pattern.
//
// The constraint's elements are
//   the seeds (GeoId, PointPos::none), one per seed,
//   then the pivot point (circular: GeoId, PointPos::start) or the two direction lines (linear:
//   GeoId, PointPos::none; the second is GeoUndef while the second count is 1 and none was made),
//   then the instance table: one element per slot, the copy's GeoId or GeoUndef for an empty slot
//   (a deleted copy), in the order of slots().
// MetaData holds {"pattern": "circular" | "linear", "seeds": n, "count1": c1, "count2": c2}, and
// Value is a circular pattern's total angle in radians (2 pi: the copies spread evenly over the
// full turn, step 2 pi / c1; less: over the angle from the seed to the last copy, step angle /
// (c1 - 1)). A linear pattern's spacing is its direction lines' lengths and directions: the copy at
// slot (i, a, b) is seed i moved by a (E1 - S1) + b (E2 - S2).

#pragma once

#include <array>
#include <map>
#include <optional>
#include <vector>

#include "GeoEnum.h"

namespace Sketcher
{

class Constraint;

struct SketcherExport PatternRecord
{
    enum class Kind
    {
        Circular,
        Linear
    };
    /// (seed index, index along direction 1, index along direction 2); circular: (i, k, 0)
    using Slot = std::array<int, 3>;

    Kind kind {Kind::Circular};
    std::vector<int> seeds;
    int pivot {GeoEnum::GeoUndef};
    int direction1 {GeoEnum::GeoUndef};
    int direction2 {GeoEnum::GeoUndef};
    int count1 {1};
    int count2 {1};
    double angle {0.0};
    /// every slot of the counts, with its copy's GeoId or GeoUndef (an empty slot)
    std::map<Slot, int> instances;

    static bool isPattern(const Constraint* constr);
    /// the record of a Pattern constraint; nullopt for any other or a malformed one
    static std::optional<PatternRecord> read(const Constraint& constr);
    /// writes this record into constr: its type, elements, MetaData and Value
    void write(Constraint& constr) const;

    /// the slots of the counts, in the table's order (no seed slot (i, 0, 0))
    std::vector<Slot> slots() const;
    bool isFullCircle() const;
    /// the angle between neighbouring instances of a circular pattern
    double stepAngle() const;
};

}  // namespace Sketcher
