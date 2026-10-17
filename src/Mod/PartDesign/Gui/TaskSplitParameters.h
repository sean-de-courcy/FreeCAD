// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// The Split panel (FreeCAD-CH ops#325, B+ Stage 1 session 4, notes/bplus-stage1-design.md 2.7)

#include "TaskFeatureParameters.h"

class QCheckBox;
class QLabel;

namespace PartDesignGui
{

/** Which side of the plane stays with the part, and a Flip. In the new half's Split the panel
 * says which Split it follows, and the Flip is the original's to make.
 */
class TaskSplitParameters: public TaskFeatureParameters
{
    Q_OBJECT

public:
    explicit TaskSplitParameters(ViewProvider* vp, QWidget* parent = nullptr);

    void apply() override;

private:
    void onFlip(bool flipped);
    void updateText();

    QLabel* plane;
    QLabel* sides;
    QCheckBox* flip;
};

class TaskDlgSplitParameters: public TaskDlgFeatureParameters
{
    Q_OBJECT

public:
    explicit TaskDlgSplitParameters(ViewProvider* vp);
};

}  // namespace PartDesignGui
