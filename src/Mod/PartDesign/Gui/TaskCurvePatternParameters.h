// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                               *
 *                                                                            *
 *   This file is part of the FreeCAD CAx development system.                 *
 *                                                                            *
 *   This library is free software; you can redistribute it and/or            *
 *   modify it under the terms of the GNU Library General Public              *
 *   License as published by the Free Software Foundation; either             *
 *   version 2 of the License, or (at your option) any later version.         *
 *                                                                            *
 *   This library  is distributed in the hope that it will be useful,         *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of           *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            *
 *   GNU Library General Public License for more details.                     *
 *                                                                            *
 *   You should have received a copy of the GNU Library General Public        *
 *   License along with this library; see the file COPYING.LIB. If not,       *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,            *
 *   Suite 330, Boston, MA  02111-1307, USA                                   *
 *                                                                            *
 ******************************************************************************/

#pragma once

#include <memory>

#include "TaskTransformedParameters.h"

class QTimer;
class Ui_TaskCurvePatternParameters;

namespace PartDesignGui
{

class ReferenceField;

/// The Curve pattern's panel (FreeCAD-CH ops#655, T6): the path, the instance count, the
/// orientation, Reverse direction and Skip instances. Not a MultiTransform step
class TaskCurvePatternParameters: public TaskTransformedParameters
{
    Q_OBJECT

public:
    explicit TaskCurvePatternParameters(ViewProviderTransformed* TransformedView, QWidget* parent = nullptr);
    ~TaskCurvePatternParameters() override;

    void apply() override;
    void onReferencesRepaired() override;
    std::vector<ReferenceField*> pathFields() const;

private Q_SLOTS:
    void onUpdateView(bool on) override;

private:
    void setupParameterUI(QWidget* widget) override;
    void retranslateParameterUI(QWidget* widget) override;
    void updateUI();
    void kickUpdateViewTimer() const;

    std::unique_ptr<Ui_TaskCurvePatternParameters> ui;
    ReferenceField* pathField = nullptr;
    QTimer* updateViewTimer = nullptr;
};

/// The Curve pattern's dialog
class TaskDlgCurvePatternParameters: public TaskDlgTransformedParameters
{
    Q_OBJECT

public:
    explicit TaskDlgCurvePatternParameters(ViewProviderTransformed* CurvePatternView);

protected:
    std::vector<ReferenceField*> panelFields() override;
};

}  // namespace PartDesignGui
