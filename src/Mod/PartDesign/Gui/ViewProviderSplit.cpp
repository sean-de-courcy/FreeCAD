// SPDX-License-Identifier: LGPL-2.1-or-later

// Split (FreeCAD-CH ops#325, B+ Stage 1 session 4, notes/bplus-stage1-design.md 2.7)

#include <QMenu>

#include "TaskSplitParameters.h"
#include "ViewProviderSplit.h"

using namespace PartDesignGui;

PROPERTY_SOURCE(PartDesignGui::ViewProviderSplit, PartDesignGui::ViewProvider)

ViewProviderSplit::ViewProviderSplit()
{
    sPixmap = "PartDesign_Boolean.svg";
}

void ViewProviderSplit::setupContextMenu(QMenu* menu, QObject* receiver, const char* member)
{
    addDefaultAction(menu, QObject::tr("Edit Split"));
    PartDesignGui::ViewProvider::setupContextMenu(menu, receiver, member);
}

TaskDlgFeatureParameters* ViewProviderSplit::getEditDialog()
{
    return new TaskDlgSplitParameters(this);
}
