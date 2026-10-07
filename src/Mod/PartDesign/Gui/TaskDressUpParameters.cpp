// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2012 Jan Rheinländer                                    *
 *                                   <jrheinlaender@users.sourceforge.net> *
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
#include <QLayout>
#include <QWidget>


#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Transactions.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Tools.h>
#include <Gui/WaitCursor.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/Gui/ReferenceSelection.h>

#include "ReferenceField.h"
#include "TaskDressUpParameters.h"


FC_LOG_LEVEL_INIT("PartDesign", true, true)

using namespace PartDesignGui;
using namespace Gui;


/* TRANSLATOR PartDesignGui::TaskDressUpParameters */

TaskDressUpParameters::TaskDressUpParameters(
    ViewProviderDressUp* DressUpView,
    bool selectEdges,
    bool selectFaces,
    QWidget* parent
)
    : TaskFeatureParameters(DressUpView, parent, DressUpView->featureIcon(), DressUpView->menuName)
    , proxy(nullptr)
    , addAllEdgesAction(nullptr)
    , allowFaces(selectFaces)
    , allowEdges(selectEdges)
    , DressUpView(DressUpView)
{
    // remember initial transaction ID
    transactionID = DressUpView->getObject()->getDocument()->getBookedTransactionID();

    selectionMode = none;
}

TaskDressUpParameters::~TaskDressUpParameters()
{
    // The Base field removes its own gate; this one removes a plane or line pick's
    if (selectionMode != none) {
        Gui::Selection().rmvSelectionGate();
    }
}

void TaskDressUpParameters::setupTransaction()
{
    if (DressUpView.expired()) {
        return;
    }

    // Join a transaction booked since the dialog opened, as the transformed dialogs do: the
    // References panel books one when the dialog has none, and opening another here would commit
    // the panel's repair on its own, out of Cancel's reach (ops#130).
    int tid = DressUpView->getObject()->getDocument()->getBookedTransactionID();
    if (tid != App::NullTransaction) {
        transactionID = tid;
        return;
    }

    // open a transaction if none is active
    // where is this transaction committed - theo-vt?
    std::string n("Edit ");
    n += DressUpView->getObject()->Label.getValue();
    transactionID = DressUpView->getObject()->getDocument()->openTransaction(n.c_str());
}

void TaskDressUpParameters::createBaseField(QWidget* placeholder)
{
    ReferenceField::Options options;
    options.flags.setFlag(AllowSelection::EDGE, allowEdges);
    options.flags.setFlag(AllowSelection::FACE, allowFaces);
    options.target = [this]() -> App::DocumentObject* {
        return getBase();
    };
    if (allowEdges && allowFaces) {
        options.kinds = tr("Edges, faces");
    }
    else if (allowFaces) {
        options.kinds = tr("Faces");
    }
    else {
        options.kinds = tr("Edges");
    }
    auto write = [this](App::DocumentObject* /*target*/, const std::vector<std::string>& subs) {
        if (ViewProviderDressUp* view = getDressUpView()) {
            updateFeature(view->getObject<PartDesign::DressUp>(), subs);
        }
    };
    baseField = new ReferenceField(getObject(), "Base", options, write, proxy);
    if (QWidget* parent = placeholder->parentWidget(); parent && parent->layout()) {
        delete parent->layout()->replaceWidget(placeholder, baseField);
    }
    placeholder->hide();
    placeholder->deleteLater();

    // The panel's other pick modes end when the field arms: its gate replaces theirs
    connect(baseField, &ReferenceField::arming, this, [this]() {
        if (selectionMode != none) {
            setSelectionMode(none);
        }
    });
    connect(baseField, &ReferenceField::picked, this, [this]() { onBaseChanged(); });
}

void TaskDressUpParameters::createAddAllEdgesAction()
{
    addAllEdgesAction = new QAction(tr("Add All Edges"), this);
    addAllEdgesAction->setShortcut(QKeySequence(QStringLiteral("Ctrl+Shift+A")));
    // display shortcut behind the context menu entry
    addAllEdgesAction->setShortcutVisibleInContextMenu(true);
    addAllEdgesAction->setShortcutContext(Qt::WidgetShortcut);
    addAllEdgesAction->setStatusTip(tr("Adds all edges of the base to the list"));
    connect(addAllEdgesAction, &QAction::triggered, this, [this]() { addAllEdges(); });
    if (baseField) {
        baseField->addMenuAction(addAllEdgesAction);
    }
}

std::vector<ReferenceField*> TaskDressUpParameters::referenceFields() const
{
    if (!baseField) {
        return {};
    }
    return {baseField};
}

void TaskDressUpParameters::disarmBaseField()
{
    if (baseField) {
        baseField->setArmed(false);
    }
}

void TaskDressUpParameters::addAllEdges()
{
    if (DressUpView.expired()) {
        return;
    }

    PartDesign::DressUp* pcDressUp = DressUpView->getObject<PartDesign::DressUp>();
    App::DocumentObject* base = pcDressUp->Base.getValue();
    if (!base) {
        return;
    }
    int count = Part::Feature::getTopoShape(
                    base,
                    Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
    )
                    .countSubShapes(TopAbs_EDGE);
    const auto oldStyle = pcDressUp->Base.getSubValues(false);
    // The entries there stay as stored (their records with them); the missing edges follow
    auto subValues = pcDressUp->Base.getSubValues();
    std::size_t len = subValues.size();
    for (int i = 0; i < count; ++i) {
        std::string name = "Edge" + std::to_string(i + 1);
        if (std::ranges::find(oldStyle, name) == oldStyle.end()) {
            subValues.push_back(name);
        }
    }
    if (subValues.size() == len) {
        return;
    }
    // Through the field: one step of its undo, and the list shows them (B5)
    if (baseField) {
        baseField->replaceEntries(subValues);
        return;
    }
    try {
        setupTransaction();
        pcDressUp->Base.setValue(base, subValues);
        pcDressUp->recomputeFeature();
        hideOnError();
    }
    catch (Base::Exception& e) {
        e.reportException();
    }
    onBaseChanged();
}

void TaskDressUpParameters::updateFeature(
    PartDesign::DressUp* pcDressUp,
    const std::vector<std::string>& refs
)
{
    setupTransaction();
    // Through the field, the entries it keeps keep their guess and rejection records
    if (baseField) {
        baseField->assign(pcDressUp->Base.getValue(), refs);
    }
    else {
        pcDressUp->Base.setValue(pcDressUp->Base.getValue(), refs);
    }
    pcDressUp->recomputeFeature();
    hideOnError();
}

const std::vector<std::string> TaskDressUpParameters::getReferences() const
{
    PartDesign::DressUp* pcDressUp = DressUpView->getObject<PartDesign::DressUp>();
    std::vector<std::string> result = pcDressUp->Base.getSubValues();
    return result;
}

void TaskDressUpParameters::hideOnError()
{
    App::DocumentObject* dressup = DressUpView->getObject();
    DressUpView->setErrorState(dressup->isError());
}

ViewProviderDressUp* TaskDressUpParameters::getDressUpView() const
{
    return DressUpView.expired() ? nullptr : DressUpView.get();
}

Part::Feature* TaskDressUpParameters::getBase() const
{
    if (ViewProviderDressUp* vp = getDressUpView()) {
        auto dressUp = vp->getObject<PartDesign::DressUp>();
        // Unlikely but this may throw an exception in case we are started to edit an object which
        // base feature was deleted. This exception will be likely unhandled inside the dialog and
        // pass upper. But an error message inside the report view is better than a SEGFAULT.
        // Generally this situation should be prevented in ViewProviderDressUp::setEdit()
        return dressUp->getBaseObject();
    }

    return nullptr;
}

void TaskDressUpParameters::setSelectionMode(selectionModes mode)
{
    if (DressUpView.expired()) {
        return;
    }
    // A value edit or another pick mode ends the field's picking too (B3)
    disarmBaseField();
    const bool wasPicking = selectionMode != none;
    selectionMode = mode;
    setButtons(mode);
    // Its gate goes with it (B3, B4); the Base field's stays
    if (mode == none && wasPicking) {
        DressUpView->highlightReferences(false);
        Gui::Selection().rmvSelectionGate();
    }
    Gui::Selection().clearSelection();
}

void TaskDressUpParameters::onReferencesRepaired()
{
    if (baseField) {
        baseField->reload();
    }
}

void TaskDressUpParameters::onReferenceSelectionTaken()
{
    disarmBaseField();
    if (selectionMode != none) {
        setSelectionMode(none);
    }
}

namespace
{
// After Body::insertObject, BaseFeature is the inserted feature and Base still names the feature
// before it (ops#82). The panel shows, highlights and selects on BaseFeature's shape, so Base
// moves there: each reference is resolved as the dress-up resolves it (its mapped name on
// BaseFeature's shape) and replaced by that element's index. A reference without a mapped name,
// one that resolves to nothing, or two that resolve to the same element leave Base as it is
// (ops#84). Returns whether Base moved.
bool moveBaseToBaseFeature(PartDesign::DressUp* dressUp)
{
    App::DocumentObject* base = dressUp->Base.getValue();
    App::DocumentObject* baseFeature = dressUp->BaseFeature.getValue();
    if (!base || !baseFeature || base == baseFeature) {
        return false;
    }
    Part::TopoShape shape = dressUp->getBaseTopoShape(/* silent = */ true);
    const auto& shadows = dressUp->Base.getShadowSubs();
    if (shape.isNull() || shadows.empty()) {
        return false;
    }
    std::vector<std::string> subs;
    for (const auto& shadow : shadows) {
        if (shadow.newName.empty()) {
            return false;
        }
        TopoDS_Shape element;
        try {
            element = shape.getSubShape(shadow.newName.c_str(), /* silent = */ true);
        }
        catch (...) {
        }
        int index = element.IsNull() ? 0 : shape.findShape(element);
        if (index <= 0) {
            return false;
        }
        std::string sub = Part::TopoShape::shapeName(element.ShapeType()) + std::to_string(index);
        if (std::ranges::find(subs, sub) != subs.end()) {
            return false;
        }
        subs.push_back(std::move(sub));
    }

    // Inside the panel's transaction, so Cancel restores Base
    App::Document* doc = dressUp->getDocument();
    if (doc->getBookedTransactionID() == App::NullTransaction && !doc->hasPendingTransaction()) {
        doc->openTransaction(std::string("Edit ") + dressUp->Label.getValue());
    }
    dressUp->Base.setValue(baseFeature, subs);
    return true;
}
}  // namespace

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgDressUpParameters::TaskDlgDressUpParameters(ViewProviderDressUp* DressUpView)
    : TaskDlgFeatureParameters(DressUpView)
    , parameter(nullptr)
{
    assert(DressUpView);
    auto pcDressUp = DressUpView->getObject<PartDesign::DressUp>();
    auto base = pcDressUp->Base.getValue();
    std::vector<std::string> newSubList;
    bool changed = false;
    auto& shadowSubs = pcDressUp->Base.getShadowSubs();
    for (auto& shadowSub : shadowSubs) {
        auto displayName = shadowSub.oldName;
        // If there is a missing tag on the shadow sub, take a guess at a new name. Not with the
        // reference solver on (ops#7, Task 2 PR 5): it resolved what it could, and a reference
        // it left broken stays broken until the user picks another element (ops#66).
        if (boost::starts_with(shadowSub.oldName, Data::MISSING_PREFIX)
            && !pcDressUp->Base.inSolverDocument()) {
            Part::Feature::guessNewLink(displayName, base, shadowSub.newName.c_str());
            changed = true;
        }
        newSubList.emplace_back(displayName);
    }
    if (changed) {
        pcDressUp->Base.setValue(base, newSubList);
        pcDressUp->recomputeFeature(false);
    }
    moveBaseToBaseFeature(pcDressUp);
}

TaskDlgDressUpParameters::~TaskDlgDressUpParameters() = default;

//==== calls from the TaskView ===============================================================

bool TaskDlgDressUpParameters::accept()
{
    getViewObject<ViewProviderDressUp>()->highlightReferences(false);
    std::vector<std::string> refs = parameter->getReferences();
    // Base's own object: the references are its element names (ops#84)
    auto dressUp = getObject<PartDesign::DressUp>();
    App::DocumentObject* base = dressUp->Base.getValue();
    if (!base) {
        base = parameter->getBase();
    }
    // Written only when the dialog changed it: written again with plain names, Base would drop
    // what it keeps per reference, a guess record or a missing element of a partly resolved
    // dress-up among them, without a warning (ops#127).
    if (base == dressUp->Base.getValue()
        && (refs == dressUp->Base.getSubValues(true)
            || refs == dressUp->Base.getSubValues(false))) {
        return TaskDlgFeatureParameters::accept();
    }
    std::stringstream str;
    str << Gui::Command::getObjectCmd(getObject()) << ".Base = ("
        << Gui::Command::getObjectCmd(base) << ",[";
    for (const auto& ref : refs) {
        str << "\"" << ref << "\",";
    }
    str << "])";
    Gui::Command::runCommand(Gui::Command::Doc, str.str().c_str());
    return TaskDlgFeatureParameters::accept();
}

bool TaskDlgDressUpParameters::reject()
{
    getViewObject<ViewProviderDressUp>()->highlightReferences(false);
    return TaskDlgFeatureParameters::reject();
}

#include "moc_TaskDressUpParameters.cpp"
