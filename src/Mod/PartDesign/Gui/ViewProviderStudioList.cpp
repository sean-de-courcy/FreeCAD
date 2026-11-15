// SPDX-License-Identifier: LGPL-2.1-or-later

// The studio's feature list object (FreeCAD-CH ops#654). Scaffolding (B1).

#include "ViewProviderStudioList.h"

using namespace PartDesignGui;

PROPERTY_SOURCE(PartDesignGui::ViewProviderStudioList, Gui::ViewProviderDocumentObject)

ViewProviderStudioList::ViewProviderStudioList()
{
    ShowInTree.setValue(false);
    Visibility.setValue(false);
}

bool ViewProviderStudioList::canDelete(App::DocumentObject* /*obj*/) const
{
    return false;
}

bool ViewProviderStudioList::onDelete(const std::vector<std::string>& /*subNames*/)
{
    // The list is the studio's history: it goes only with its studio
    return false;
}
