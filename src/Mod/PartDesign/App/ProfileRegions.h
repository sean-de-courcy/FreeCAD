// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// A sketch's profile as Onshape's regions (FreeCAD-CH, feat/profile-regions;
// notes/profile-regions.md). A sketch's regions are the bounded faces of the arrangement of its
// solid curves (Sketcher's InternalShape, which also takes the model edges in its plane). A
// feature takes one region, several, or the whole sketch; the whole sketch is every region of the
// sketch's own curves except those enclosed by curves touching the outer boundary of all the
// regions nowhere (Onshape's filterInnerLoops), and adjacent regions make one face.

#include <string>
#include <vector>

#include <Mod/Part/App/TopoShape.h>
#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class DocumentObject;
}

namespace PartDesign
{

/// Onshape's whole-sketch profile of a sketch
class PartDesignExport WholeSketchRegions
{
public:
    /// profile: the profile object (a sketch, or a link to one); wires: its shape, as
    /// ProfileBased reads it (Transform), which the faces are made from when needed
    WholeSketchRegions(const App::DocumentObject* profile, const Part::TopoShape& wires);

    /// The sketch's loops are disjoint and simple, and no region lies in a hole's hole: the loops'
    /// face maker (FaceMakerBullseye on the closed wires) gives the same faces, with the element
    /// names files saved before have
    bool sameAsLoops() const
    {
        return simple;
    }

    /// Whether faces made otherwise are this profile: as many faces, the same area
    bool matches(const Part::TopoShape& faces) const;

    /// The regions kept, adjacent ones merged, in the coordinates of wires; null when no region
    /// is kept
    Part::TopoShape faces() const;

private:
    Part::TopoShape wires;
    bool simple = false;
    std::size_t keptCount = 0;
    double keptArea = 0;
};

/// Picked regions of a sketch ("InternalFace<n>"), as faces read one by one (faces, in subs'
/// order): those that share a side merged into one face, as Onshape extrudes several regions.
/// Returns faces as they are when no two share a side or the picks aren't a sketch's regions.
PartDesignExport Part::TopoShape mergeAdjacentRegions(
    const App::DocumentObject* profile,
    const std::vector<std::string>& subs,
    const Part::TopoShape& faces
);

/// Whether subs pick regions of a sketch ("InternalFace<n>")
PartDesignExport bool picksRegions(const std::vector<std::string>& subs);

/// The wires of faces, face by face (a section made of regions)
PartDesignExport Part::TopoShape wiresOfFaces(const Part::TopoShape& faces);

/// A section's loops in the order a loft pairs them: the outer loops first, then the holes (a
/// loop inside an odd number of the others), each in its own order. Sections whose loops come
/// from regions (outer wire first) and from the sketch's own order (any order) then pair outer to
/// outer and hole to hole. holes: the number of holes.
PartDesignExport std::vector<Part::TopoShape> outerLoopsFirst(
    const std::vector<Part::TopoShape>& wires,
    std::size_t* holes = nullptr
);

/// The message of a section (loft, multi-section pipe) whose whole sketch gives more than one
/// region (or holes) in another order than its own
inline constexpr const char* SectionRegionsMessage
    = "A section's sketch has overlapping, touching or nested loops that give more than one "
      "region, or a region with more than one hole: pick one region of it per section";

}  // namespace PartDesign
