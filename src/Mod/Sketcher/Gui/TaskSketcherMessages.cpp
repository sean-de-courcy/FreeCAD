// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Jürgen Riegel <juergen.riegel@web.de>              *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#include <QAction>
#include <QMenu>
#include <QCheckBox>
#include <QFrame>
#include <QToolButton>

#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/ForkKeymap.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>
#include <Mod/Sketcher/App/SketchObject.h>

#include "Command.h"
#include "TaskSketcherMessages.h"
#include "Utils.h"
#include "ViewProviderSketch.h"


// clang-format off
using namespace SketcherGui;
using namespace Gui::TaskView;
namespace sp = std::placeholders;

TaskSketcherMessages::TaskSketcherMessages(ViewProviderSketch* sketchView)
    : TaskSolverMessages(Gui::BitmapFactory().pixmap("Sketcher_Sketch"), tr("Sketch Edit"))
    , sketchView(sketchView)
{
    createSettingsButtonActions();

    // FreeCAD-CH (ops#640 polish P4): Onshape's sketch dialog checkboxes, under the solver's
    // message and in Onshape's order. Disable imprinting is the sketch's own (a property, one undo
    // step); Show constraints and Show expressions are the user's preferences, whose observer in
    // edit mode (EditModeCoinManager) redraws the sketch.
    auto* disableImprinting = new QCheckBox(tr("Disable imprinting"));
    disableImprinting->setObjectName(QStringLiteral("disableImprinting"));
    disableImprinting->setToolTip(tr("The edges of the face the sketch lies on don't split its "
        "regions"));
    disableImprinting->setChecked(sketchView->getSketchObject()->DisableImprinting.getValue());
    groupLayout()->addWidget(disableImprinting);
    connect(disableImprinting, &QCheckBox::toggled, this, [this](bool checked) {
        auto* sketch = this->sketchView->getSketchObject();
        if (sketch->DisableImprinting.getValue() == checked) {
            return;
        }
        this->sketchView->getDocument()->openCommand(QT_TRANSLATE_NOOP("Command", "Disable imprinting"));
        Gui::cmdAppObjectArgs(sketch, "DisableImprinting = %s", checked ? "True" : "False");
        this->sketchView->getDocument()->commitCommand();
        tryAutoRecomputeIfNotSolve(sketch);
    });

    // FreeCAD-CH (ops#640 polish P1): Onshape's "Show constraints"
    auto* showConstraints = new QCheckBox(tr("Show constraints"));
    showConstraints->setObjectName(QStringLiteral("showConstraints"));
    showConstraints->setToolTip(tr("Draws every constraint. Off, only the dimensions and the "
        "constraints of the curve or point under the cursor are drawn"));
    showConstraints->setChecked(ViewProviderSketch::showConstraintsPreference());
    groupLayout()->addWidget(showConstraints);
    connect(showConstraints, &QCheckBox::toggled, this, [](bool checked) {
        ViewProviderSketch::setShowConstraintsPreference(checked);
    });

    auto* showExpressions = new QCheckBox(tr("Show expressions"));
    showExpressions->setObjectName(QStringLiteral("showExpressions"));
    showExpressions->setToolTip(tr("A dimension set by an expression shows the expression "
        "instead of its value"));
    showExpressions->setChecked(ViewProviderSketch::showExpressionsPreference());
    groupLayout()->addWidget(showExpressions);
    connect(showExpressions, &QCheckBox::toggled, this, [](bool checked) {
        ViewProviderSketch::setShowExpressionsPreference(checked);
    });

    // FreeCAD-CH (ops#640 polish P1b): Onshape's "Show errors", its fourth box
    auto* showErrors = new QCheckBox(tr("Show errors"));
    showErrors->setObjectName(QStringLiteral("showErrors"));
    showErrors->setToolTip(tr("Draws the conflicting, redundant and malformed constraints"));
    showErrors->setChecked(ViewProviderSketch::showErrorsPreference());
    groupLayout()->addWidget(showErrors);
    connect(showErrors, &QCheckBox::toggled, this, [](bool checked) {
        ViewProviderSketch::setShowErrorsPreference(checked);
    });

    //NOLINTBEGIN
    connectionSetUp = sketchView->signalSetUp.connect(std::bind(
        &SketcherGui::TaskSketcherMessages::slotSetUp, this, sp::_1, sp::_2, sp::_3, sp::_4));
    //NOLINTEND
    connectionTitle = sketchView->signalSetUp.connect(
        [this](const QString& state, const QString&, const QString&, const QString&) {
            updateTitleColour(state);
        });
}

TaskSketcherMessages::~TaskSketcherMessages()
{
    connectionSetUp.disconnect();
    connectionTitle.disconnect();
}

void TaskSketcherMessages::updateTitleColour(const QString& state)
{
    // The box's title is the header's one tool button (QSint's TaskHeader holds the title and
    // the fold arrow, a label)
    QToolButton* title = nullptr;
    for (auto* frame : findChildren<QFrame*>()) {
        if (QLatin1String(frame->metaObject()->className()) == QLatin1String("QSint::TaskHeader")) {
            title = frame->findChild<QToolButton*>();
            break;
        }
    }
    if (!title) {
        return;
    }
    const bool failed = state == QStringLiteral("conflicting_constraints")
        || state == QStringLiteral("malformed_constraints")
        || sketchView->getSketchObject()->getLastSolvedAroundConflict();
    // Onshape's error title red (#AA252D, PL3a and PL4c, as the feature dialogs' title); the FreeCAD
    // keymap keeps the scheme's colour
    title->setStyleSheet(Gui::ForkKeymap::isOnshape() && failed
                             ? QStringLiteral("color: #AA252D;")
                             : QString());
}

void TaskSketcherMessages::updateToolTip(const QString& link)
{
    if (link == QStringLiteral("#conflicting")) {
        setLinkTooltip(tr("Selects these conflicting constraints"));
    }
    else if (link == QStringLiteral("#redundant")) {
        setLinkTooltip(tr("Selects these redundant constraints"));
    }
    else if (link == QStringLiteral("#dofs")) {
        setLinkTooltip(tr("The sketch has unconstrained elements giving rise to those "
            "Degrees Of Freedom. Selects these unconstrained elements."));
    }
    else if (link == QStringLiteral("#malformed")) {
        setLinkTooltip(tr("Selects these malformed constraints"));
    }
    else if (link == QStringLiteral("#closestmatches")) {  // FreeCAD-CH (ops#644)
        setLinkTooltip(tr("Each missing reference takes its closest match, in one undo step. "
                          "Repair References, in the sketch's menu in the tree, lists every "
                          "candidate."));
    }
    else if (link == QStringLiteral("#partiallyredundant")) {
        setLinkTooltip(
            tr("Some constraints in combination are partially redundant. Selects these "
               "partially redundant constraints."));
    }
}

void TaskSketcherMessages::onLabelStatusLinkClicked(const QString& str)
{
    if (str == QStringLiteral("#conflicting")) {
        Gui::Application::Instance->commandManager().runCommandByName("Sketcher_SelectConflictingConstraints");
    }
    else if (str == QStringLiteral("#redundant")) {
        Gui::Application::Instance->commandManager().runCommandByName("Sketcher_SelectRedundantConstraints");
    }
    else if (str == QStringLiteral("#dofs")) {
        Gui::Application::Instance->commandManager().runCommandByName("Sketcher_SelectElementsWithDoFs");
    }
    else if (str == QStringLiteral("#malformed")) {
        Gui::Application::Instance->commandManager().runCommandByName("Sketcher_SelectMalformedConstraints");
    }
    else if (str == QStringLiteral("#closestmatches")) {  // FreeCAD-CH (ops#644)
        Gui::Application::Instance->commandManager().runCommandByName("Sketcher_UseClosestReferenceMatches");
    }
    else if (str == QStringLiteral("#partiallyredundant")) {
        Gui::Application::Instance->commandManager().runCommandByName("Sketcher_SelectPartiallyRedundantConstraints");
    }
}

void TaskSketcherMessages::createSettingsButtonActions()
{
    QToolButton* btn = getSettingsButton();
    btn->show();

    // Set Auto Update in the 'Manual Update' button menu.
    ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/Sketcher");
    bool state = hGrp->GetBool("AutoRecompute", false);

    sketchView->getSketchObject()->noRecomputes = !state;

    auto* autoUpdateAction = new QWidgetAction(this);
    auto* containerWidget = new QWidget();
    auto* layout = new QGridLayout(containerWidget);
    auto* checkbox = new QCheckBox(tr("Auto-update"));
    checkbox->setToolTip(tr("Executes a recomputation of active document after every sketch action"));
    checkbox->setChecked(state);
    layout->addWidget(checkbox, 0, 0, 1, 2);
    containerWidget->setLayout(layout);
    autoUpdateAction->setDefaultWidget(containerWidget);

    connect(checkbox, &QCheckBox::toggled, this, [this](bool checked) {
        ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
            "User parameter:BaseApp/Preferences/Mod/Sketcher");
        hGrp->SetBool("AutoRecompute", checked);
        sketchView->getSketchObject()->noRecomputes = !checked;
    });

    auto* gridAction = new GridSpaceAction(this);
    auto* snapAction = new SnapSpaceAction(this);
    auto* renderingAction = new RenderingOrderAction(this);

    QMenu* myMenu = new QMenu(this);
    myMenu->addAction(autoUpdateAction);
    myMenu->addSeparator();
    myMenu->addAction(gridAction);
    myMenu->addSeparator();
    myMenu->addAction(snapAction);
    myMenu->addSeparator();
    myMenu->addAction(renderingAction);
    btn->setMenu(myMenu);

    QObject::connect(myMenu, &QMenu::aboutToShow, [gridAction, snapAction, renderingAction]() {
        gridAction->updateWidget();
        snapAction->updateWidget(true);
        renderingAction->updateWidget();
    });

    QObject::connect(btn, &QToolButton::clicked, btn, &QToolButton::showMenu);
}

#include "moc_TaskSketcherMessages.cpp"
// clang-format on
