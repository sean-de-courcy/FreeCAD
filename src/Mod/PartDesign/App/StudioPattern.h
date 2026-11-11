// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Patterns as studio features (FreeCAD-CH ops#655, T1-T3, notes/patterns-design.md 3.1): a
// feature pattern's tool is its instance transforms applied to its originals' tools (owners'
// tools, patterns flattened, T7a); a part pattern's tool is its source parts' shapes at its
// history point (T2); Reapply recomputes each original's tool at each instance (T3).

#include <string>
#include <vector>

#include <Mod/Part/App/TopoShape.h>
#include <Mod/PartDesign/PartDesignGlobal.h>

class gp_Trsf;

namespace App
{
class DocumentObject;
}

namespace PartDesign
{

class Body;

/// The tool pattern makes in part: its originals' tools that act on part, each moved by every
/// instance transform; null with why when an original can't be patterned
PartDesignExport Part::TopoShape studioPatternTool(
    const App::DocumentObject* pattern,
    const Body* part,
    std::string* why
);

/// The parts a feature pattern's originals act on (the pattern's scope)
PartDesignExport std::vector<Body*> studioPatternScope(const App::DocumentObject* pattern);

class FeatureAddSub;

/** Until Reapply per instance (T3; notes/parts-design.md 10.11, the coordinator's ruling on
 * work/c719/hub-cut-skeptic.md finding 3): why copies of a studio feature's tool may differ from
 * the instances Onshape computes at each place; empty when they provably agree (ops#654 slice 8).
 * step: the owner's step whose tool is copied; tool: that tool and part: the part at the
 * pattern's place, both in the pattern's frame; instances: the transforms the tool undergoes
 * there (the original left out); fromDocument: the document's frame to the pattern's.
 * Refused: Up to next (Onshape refuses it without Reapply, O10), Up to last, Up to a shape; Up to
 * face unless every instance maps the face's plane onto itself; Up to vertex unless every instance
 * keeps the end plane through the vertex; a start from a reference face, likewise; Through all
 * unless the tool removes material, is straight and every copy spans the part along its
 * direction. T3 replaces it. */
PartDesignExport std::string studioCopyRefusal(
    FeatureAddSub* step,
    const Part::TopoShape& tool,
    const Part::TopoShape& part,
    const std::vector<gp_Trsf>& instances,
    const gp_Trsf& fromDocument
);

}  // namespace PartDesign
