// SPDX-License-Identifier: LGPL-2.1-or-later

// Owners outside every Body (FreeCAD-CH ops#654, S2). Scaffolding (B1).

#include "Body.h"
#include "Feature.h"
#include "StudioOwner.h"

namespace PartDesign
{

Part::TopoShape studioBaseAt(const App::DocumentObject* /*owner*/, const Body* /*part*/)
{
    return {};  // S2
}

Part::TopoShape studioScopeBaseAt(const App::DocumentObject* /*owner*/)
{
    return {};  // S2
}

bool runsAsStudioOwner(const Feature* /*feature*/)
{
    return false;  // S2
}

}  // namespace PartDesign
