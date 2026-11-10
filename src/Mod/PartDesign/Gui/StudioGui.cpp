// SPDX-License-Identifier: LGPL-2.1-or-later

// Gui helpers for studio features (FreeCAD-CH ops#654). Scaffolding (B1).

#include <Mod/PartDesign/App/Body.h>

#include "StudioGui.h"

namespace PartDesignGui
{

std::vector<PartDesign::Body*> liveStudioParts(const App::DocumentObject* /*at*/)
{
    return {};  // P6a
}

bool rollStudioToOwner(App::DocumentObject* /*owner*/, std::string* why)
{
    if (why) {
        *why = "not yet (S4)";
    }
    return false;
}

void endStudioOwnerRollBack(App::DocumentObject* /*owner*/)
{}

}  // namespace PartDesignGui
