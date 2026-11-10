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

}  // namespace PartDesign
