// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015 Stefan Tröger <stefantroeger@gmx.net>              *
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


#include <algorithm>
#include <memory>

#include <QPointer>

#include <boost/algorithm/string/predicate.hpp>

#include <App/Document.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/CommandT.h>
#include <Gui/Document.h>
#include <Gui/Selection/Selection.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/PartDesign/App/FeatureLoft.h>

#include "ui_TaskLoftParameters.h"
#include "TaskLoftParameters.h"
#include "TaskSketchBasedParameters.h"

using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::TaskLoftParameters */

namespace
{
bool isSubtractiveLoft(ViewProviderLoft* view)
{
    auto* loft = view->getObject<PartDesign::Loft>();
    return loft->getAddSubType() == PartDesign::FeatureAddSub::Type::Subtractive;
}

std::string loftTaskIconName(ViewProviderLoft* view)
{
    return isSubtractiveLoft(view) ? "PartDesign_SubtractiveLoft" : "PartDesign_AdditiveLoft";
}

QString loftTaskTitle(ViewProviderLoft* view)
{
    return isSubtractiveLoft(view) ? TaskLoftParameters::tr("Subtractive Loft Parameters")
                                   : TaskLoftParameters::tr("Additive Loft Parameters");
}

// A sketch is taken whole, unless one of its points is picked: the loft takes the whole sketch for
// any other element of it (Loft::getSectionShape)
std::string sectionElement(App::DocumentObject* obj, const char* sub)
{
    std::string element = Base::Tools::isNullOrEmpty(sub) ? std::string() : std::string(sub);
    if (obj && obj->isDerivedFrom<Part::Part2DObject>() && !boost::starts_with(element, "Vertex")) {
        element.clear();
    }
    return element;
}
}  // namespace

TaskLoftParameters::TaskLoftParameters(ViewProviderLoft* LoftView, bool /*newObj*/, QWidget* parent)
    : TaskSketchBasedParameters(LoftView, parent, loftTaskIconName(LoftView), loftTaskTitle(LoftView))
    , ui(new Ui_TaskLoftParameters)
{
    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    // clang-format off
    connect(ui->checkBoxRuled, &QCheckBox::toggled,
            this, &TaskLoftParameters::onRuled);
    connect(ui->checkBoxClosed, &QCheckBox::toggled,
            this, &TaskLoftParameters::onClosed);
    connect(ui->checkBoxUpdateView, &QCheckBox::toggled,
            this, &TaskLoftParameters::onUpdateView);
    // clang-format on

    this->groupLayout()->addWidget(proxy);

    // Temporarily prevent unnecessary feature recomputes
    const auto childs = proxy->findChildren<QWidget*>();
    for (QWidget* child : childs) {
        child->blockSignals(true);
    }

    // The profile and the sections show for the edit; OK and Cancel put them back (B13)
    PartDesign::Loft* loft = LoftView->getObject<PartDesign::Loft>();
    shown.show(loft->Profile.getValue());
    for (App::DocumentObject* obj : loft->Sections.getValues()) {
        shown.show(obj);
    }

    // get options
    ui->checkBoxRuled->setChecked(loft->Ruled.getValue());
    ui->checkBoxClosed->setChecked(loft->Closed.getValue());

    // activate and de-activate dialog elements as appropriate
    for (QWidget* child : childs) {
        child->blockSignals(false);
    }

    createFields();
    updateUI();
}

TaskLoftParameters::~TaskLoftParameters() = default;

void TaskLoftParameters::createFields()
{
    App::DocumentObjectT loftT(getObject());
    auto isShape = [](App::DocumentObject* obj, std::string& why) {
        if (!obj || !obj->isDerivedFrom<Part::Feature>()) {
            why = QT_TR_NOOP("Pick a sketch, a sketch point or a face.");
            return false;
        }
        return true;
    };

    // The profile: one sketch, sketch point or face (Q8 (a): its own field, above the sections)
    ReferenceField::Options profile;
    profile.kind = ReferenceField::Kind::SingleElement;
    profile.acceptOnly = true;
    profile.noDependents = true;
    profile.removable = false;
    profile.label = tr("Profile");
    profile.kinds = tr("A sketch, a sketch point or a face");
    profile.accept = [loftT, isShape](App::DocumentObject* obj, const char*, std::string& why) {
        if (!isShape(obj, why)) {
            return false;
        }
        auto loft = freecad_cast<PartDesign::Loft*>(loftT.getObject());
        if (loft && std::ranges::find(loft->Sections.getValues(), obj) != loft->Sections.getValues().end()) {
            why = QT_TR_NOOP("This is a section of the loft: the profile can't be one too.");
            return false;
        }
        return true;
    };
    profile.resolve = [](const Gui::SelectionChanges& msg,
                         App::DocumentObject*& obj,
                         std::vector<std::string>& subs) {
        subs.clear();
        if (std::string element = sectionElement(obj, msg.pSubName); !element.empty()) {
            subs.push_back(element);
        }
        return obj != nullptr;
    };
    auto profileSelf = std::make_shared<QPointer<ReferenceField>>();
    auto writeProfile = [this, profileSelf](App::DocumentObject* obj, const std::vector<std::string>& subs) {
        if (*profileSelf) {
            (*profileSelf)->assign(obj, subs);
        }
        shown.show(obj);
        recomputeFeature();
    };
    profileField = new ReferenceField(getObject(), "Profile", profile, writeProfile, proxy);
    *profileSelf = profileField;
    profileField->takePlaceOf(ui->profileFieldPlaceholder);

    // The sections, in the loft's order (B8, B11, B12, B21)
    ReferenceField::Options sections;
    sections.kind = ReferenceField::Kind::Sections;
    sections.noDependents = true;
    sections.label = tr("Sections");
    sections.kinds = tr("Sketches, sketch points or faces");
    sections.accept = [loftT, isShape](App::DocumentObject* obj, const char*, std::string& why) {
        if (!isShape(obj, why)) {
            return false;
        }
        auto loft = freecad_cast<PartDesign::Loft*>(loftT.getObject());
        if (loft && obj == loft->Profile.getValue()) {
            why = QT_TR_NOOP("This is the loft's profile: it can't be a section too.");
            return false;
        }
        return true;
    };
    auto sectionsSelf = std::make_shared<QPointer<ReferenceField>>();
    auto writeSections = [this, sectionsSelf](const std::vector<App::PropertyLinkSubList::SubSet>& list) {
        if (*sectionsSelf) {
            (*sectionsSelf)->assign(list);
        }
        for (const auto& section : list) {
            shown.show(section.first);
        }
        recomputeFeature();
        updateUI();
    };
    sectionsField = new ReferenceField(
        getObject(),
        "Sections",
        sections,
        ReferenceField::SectionsWriter(writeSections),
        proxy
    );
    *sectionsSelf = sectionsField;
    sectionsField->takePlaceOf(ui->sectionsFieldPlaceholder);
}

std::vector<ReferenceField*> TaskLoftParameters::referenceFields() const
{
    return {profileField, sectionsField};
}

void TaskLoftParameters::restoreVisibility()
{
    shown.restore();
}

void TaskLoftParameters::updateUI()
{
    // we must assure the changed loft is kept visible on section changes,
    // see https://forum.freecad.org/viewtopic.php?f=3&t=63252
    auto loft = getObject<PartDesign::Loft>();
    if (loft) {
        auto view = getViewObject();
        view->makeTemporaryVisible(!loft->Sections.getValues().empty());
    }
}

void TaskLoftParameters::onSelectionChanged(const Gui::SelectionChanges& /*msg*/)
{
    // The fields take the picks
}

void TaskLoftParameters::changeEvent(QEvent* /*e*/)
{}

void TaskLoftParameters::onClosed(bool val)
{
    if (auto loft = getObject<PartDesign::Loft>()) {
        loft->Closed.setValue(val);
        recomputeFeature();
    }
}

void TaskLoftParameters::onRuled(bool val)
{
    if (auto loft = getObject<PartDesign::Loft>()) {
        loft->Ruled.setValue(val);
        recomputeFeature();
    }
}


//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgLoftParameters::TaskDlgLoftParameters(ViewProviderLoft* LoftView, bool newObj)
    : TaskDlgSketchBasedParameters(LoftView)
{
    assert(LoftView);
    parameter = new TaskLoftParameters(LoftView, newObj);

    Content.push_back(parameter);
    Content.push_back(preview);
}

TaskDlgLoftParameters::~TaskDlgLoftParameters() = default;

bool TaskDlgLoftParameters::accept()
{
    if (auto loft = getObject<PartDesign::Loft>()) {
        // First verify that the loft can be built and then hide the sections as otherwise
        // they will remain hidden if the loft's recompute fails
        if (TaskDlgSketchBasedParameters::accept()) {
            // What the edit showed goes back as it was (a section taken out of the list
            // included), then the profile and the sections are hidden, as OK always did
            parameter->restoreVisibility();
            Gui::cmdAppObjectHide(loft->Profile.getValue());
            for (App::DocumentObject* obj : loft->Sections.getValues()) {
                Gui::cmdAppObjectHide(obj);
            }

            return true;
        }
    }

    return false;
}

//==== calls from the TaskView ===============================================================


#include "moc_TaskLoftParameters.cpp"
