// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Split (FreeCAD-CH ops#325, B+ Stage 1 session 4, notes/bplus-stage1-design.md 2.7)

#include "ViewProvider.h"

namespace PartDesignGui
{

class PartDesignGuiExport ViewProviderSplit: public ViewProvider
{
    Q_DECLARE_TR_FUNCTIONS(PartDesignGui::ViewProviderSplit)
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesignGui::ViewProviderSplit);

public:
    ViewProviderSplit();

    void setupContextMenu(QMenu* menu, QObject* receiver, const char* member) override;

protected:
    TaskDlgFeatureParameters* getEditDialog() override;
};

}  // namespace PartDesignGui
