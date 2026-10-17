// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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

#include "FeatureRefine.h"

#include <QCoreApplication>

/// Base class of all additive features in PartDesign
namespace PartDesign
{

class PartDesignExport FeatureAddSub: public PartDesign::FeatureRefine
{
    Q_DECLARE_TR_FUNCTIONS(PartDesign::FeatureAddSub)
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::FeatureAddSub);

public:
    enum class Type
    {
        Additive = 0,
        Subtractive
    };

    enum class BooleanOperation
    {
        Union = 0,
        Subtraction,
        Common
    };

    FeatureAddSub();

    void onChanged(const App::Property*) override;

    Type getAddSubType();
    BooleanOperation getBooleanOperation();
    const char* getBooleanMaker() const;

    short mustExecute() const override;
    /// Warns when a Common removed whole solids of the base (FreeCAD-CH ops#308 T3)
    App::DocumentObjectExecReturn* recompute() override;

    virtual void getAddSubShape(Part::TopoShape& addShape, Part::TopoShape& subShape);

    void updatePreviewShape() override;

    /** @name Siblings (FreeCAD-CH ops#325, B+ Stage 1 3a)
     * One cut through several parts of a studio: the primary in the active part, and in each
     * other part a sibling of the same type on the same profile. A sibling's parameters follow
     * the primary by expression, its links are copies, and SiblingOf names the primary without a
     * dependency, so a failed primary doesn't fail it (notes/bplus-stage1-design.md 2.4).
     */
    //@{
    /// Makes @p primary's siblings the ones in @p bodies: adds the missing ones, deletes the
    /// others (refused while something else uses one), and copies the links to every one again.
    /// Returns the siblings in the order of @p bodies; no recompute.
    static std::vector<FeatureAddSub*> makeSiblings(
        FeatureAddSub* primary,
        const std::vector<App::DocumentObject*>& bodies
    );
    /// The siblings of this feature, in document order
    std::vector<FeatureAddSub*> getSiblings() const;
    /// Ends this sibling's following: its expressions on the primary and SiblingOf are cleared
    void unlinkSibling();
    /// What keeps @p sibling's sibling from being deleted (a user besides its Body's chain), or
    /// null
    static App::DocumentObject* siblingUser(const FeatureAddSub* sibling);
    /// Whether @p tool and @p part touch: bounding boxes, then the distance (FreeCAD-CH ops#325)
    static bool shapesTouch(const TopoDS_Shape& tool, const TopoDS_Shape& part);
    //@}

    Part::PropertyPartShape AddSubShape;

    App::PropertyEnumeration Operation;
    /// The primary this feature follows (Hidden scope: no dependency); empty unless a sibling
    App::PropertyLinkHidden SiblingOf;

protected:
    Type addSubType {Type::Additive};
    BooleanOperation booleanOperation {BooleanOperation::Union};
    void defineAdditive();
    void defineSubtractive();

private:
    /// Why this sibling's copied links aren't its primary's, or empty
    std::string outOfStep() const;
    /// Warns when this sibling's tool doesn't touch its part
    void warnIfMissing();
};

using FeatureAddSubPython = App::FeaturePythonT<FeatureAddSub>;

class FeatureAdditivePython: public FeatureAddSubPython
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::FeatureAdditivePython);

public:
    FeatureAdditivePython();
    ~FeatureAdditivePython() override;
};

class FeatureSubtractivePython: public FeatureAddSubPython
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::FeatureSubtractivePython);

public:
    FeatureSubtractivePython();
    ~FeatureSubtractivePython() override;
};

}  // namespace PartDesign
