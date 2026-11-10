// SPDX-License-Identifier: LGPL-2.1-or-later

// Patterns as studio features (FreeCAD-CH ops#655, T1-T3). Scaffolding (B1).

#include "Body.h"
#include "StudioPattern.h"

namespace PartDesign
{

Part::TopoShape studioPatternTool(
    const App::DocumentObject* /*pattern*/,
    const Body* /*part*/,
    std::string* why
)
{
    if (why) {
        *why = "not yet (T1)";
    }
    return {};
}

std::vector<Body*> studioPatternScope(const App::DocumentObject* /*pattern*/)
{
    return {};  // T1
}

}  // namespace PartDesign
