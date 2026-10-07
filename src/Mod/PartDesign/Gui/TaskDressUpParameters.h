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

#pragma once

#include <Gui/DocumentObserver.h>
#include <Gui/TaskView/TaskView.h>
#include <Mod/PartDesign/App/FeatureDressUp.h>

#include "TaskFeatureParameters.h"
#include "ViewProviderDressUp.h"


class QAction;
class QWidget;

namespace Part
{
class Feature;
}

namespace PartDesignGui
{

class ReferenceField;

class TaskDressUpParameters: public TaskFeatureParameters, public Gui::SelectionObserver
{
    Q_OBJECT

public:
    TaskDressUpParameters(
        ViewProviderDressUp* DressUpView,
        bool selectEdges,
        bool selectFaces,
        QWidget* parent = nullptr
    );
    ~TaskDressUpParameters() override;

    const std::vector<std::string> getReferences() const;
    Part::Feature* getBase() const;

    void setupTransaction();

    int getTransactionID() const
    {
        return transactionID;
    }

    /// The fields show their properties again (ops#127).
    void onReferencesRepaired() override;
    void onReferenceSelectionTaken() override;
    /// The Base field, and a subclass's own (ops#150).
    std::vector<ReferenceField*> referenceFields() const override;

protected:
    /// The Base list, in place of \a placeholder in the panel's layout (ops#150): the base's
    /// edges and/or faces, written through updateFeature().
    void createBaseField(QWidget* placeholder);
    /// "Add All Edges" in the Base field's menu (Ctrl+Shift+A).
    void createAddAllEdgesAction();
    /// Base was changed in its field.
    virtual void onBaseChanged()
    {}
    void hideOnError();
    void addAllEdges();
    void updateFeature(PartDesign::DressUp* pcDressUp, const std::vector<std::string>& refs);
    /// Ends the fields' picking: a value edit (B3).
    void disarmFields();

    ViewProviderDressUp* getDressUpView() const;

protected:
    QWidget* proxy;
    ReferenceField* baseField = nullptr;
    QAction* addAllEdgesAction;

    bool allowFaces, allowEdges;
    int transactionID;

private:
    Gui::WeakPtrT<ViewProviderDressUp> DressUpView;
};

/// simulation dialog for the TaskView
class TaskDlgDressUpParameters: public TaskDlgFeatureParameters
{
    Q_OBJECT

public:
    explicit TaskDlgDressUpParameters(ViewProviderDressUp* DressUpView);
    ~TaskDlgDressUpParameters() override;

public:
    /// is called by the framework if the dialog is accepted (Ok)
    bool accept() override;
    bool reject() override;

protected:
    TaskDressUpParameters* parameter;
};

}  // namespace PartDesignGui
