// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// The studio's feature list object (FreeCAD-CH ops#654): no row in the tree, nothing in 3D. The
// Features list shows its entries (S3)

#include <Gui/ViewProviderDocumentObject.h>
#include <Mod/PartDesign/PartDesignGlobal.h>

namespace PartDesignGui
{

class PartDesignGuiExport ViewProviderStudioList: public Gui::ViewProviderDocumentObject
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesignGui::ViewProviderStudioList);

public:
    ViewProviderStudioList();

    bool isShow() const override
    {
        return false;
    }
    bool canDelete(App::DocumentObject* obj) const override;
    bool onDelete(const std::vector<std::string>& subNames) override;
};

}  // namespace PartDesignGui
