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


#pragma once

#include <map>
#include <string>

#include <App/PropertyLinks.h>
#include <App/PropertyUnits.h>
#include <App/DocumentObserver.h>
#include <App/FeaturePython.h>
#include <Mod/Part/App/DatumFeature.h>
#include <Mod/PartDesign/PartDesignGlobal.h>
#include "FeatureRefine.h"

namespace PartDesign
{

/* This feature is not really a classical datum. It is a fully defined shape and not
 * infinite geometry like a plane and a line. Also it is not calculated by references and hence
 * is not "attached" to anything. Furthermore real shapes must be visualized. This makes it hard
 * to reuse the existing datum infrastructure and a special handling for this type is
 * created.
 */
// TODO Add better documentation (2015-09-11, Fat-Zer)

class PartDesignExport ShapeBinder: public Part::Feature
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::ShapeBinder);

public:
    ShapeBinder();
    ~ShapeBinder() override;

    App::PropertyLinkSubListGlobal Support;
    App::PropertyBool TraceSupport;

    static void getFilteredReferences(
        const App::PropertyLinkSubList* prop,
        App::GeoFeature*& object,
        std::vector<std::string>& subobjects
    );
    /// What getFilteredReferences would leave out of prop's references, by objects' labels
    /// (ops#251, ops#266)
    struct Dropped
    {
        enum class Kind
        {
            None,           ///< it keeps them all
            NoPartFeature,  ///< no Part feature or datum: `names` are the objects linked
            OtherObjects,   ///< `object` is kept; `names` are the other objects
            Mixed,          ///< `object` whole and by its elements, `names`
            DatumElements   ///< `object` is a datum, bound whole; `names` are its elements
        };
        Kind kind = Kind::None;
        std::string object;
        std::vector<std::string> names;
        /// The English text; the GUI translates its own
        std::string message() const;
    };
    static Dropped findDroppedReferences(const App::PropertyLinkSubList* prop);
    /// Why getFilteredReferences would leave some of prop's references out (more than one
    /// object, or an object both whole and by its elements), or empty when it keeps them all
    /// (ops#251)
    static std::string droppedReferences(const App::PropertyLinkSubList* prop)
    {
        return findDroppedReferences(prop).message();
    }
    static Part::TopoShape buildShapeFromReferences(App::GeoFeature* obj, std::vector<std::string> subs);
    /// Whether two placements are the same within round-off: the position within
    /// Precision::Confusion, the angle between the rotations within Precision::Angular (from the
    /// vector part of their difference, the sine of half the angle, which stays exact near zero;
    /// Rotation::isSame's tolerance on the quaternions' scalar product let about 0.036 degrees
    /// through: PR 227 verification)
    static bool samePlace(const Base::Placement& a, const Base::Placement& b);

    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderShapeBinder";
    }

protected:
    Part::TopoShape updatedShape() const;
    bool hasPlacementChanged() const;
    /// The global placements of the support's container and of this binder's (identity at the
    /// root), which TraceSupport maps between; false without a support
    bool containerFrames(Base::Placement& sourceCS, Base::Placement& targetCS) const;
    void handleChangedPropertyType(
        Base::XMLReader& reader,
        const char* TypeName,
        App::Property* prop
    ) override;
    short int mustExecute() const override;
    App::DocumentObjectExecReturn* execute() override;
    void onChanged(const App::Property* prop) override;

private:
    void slotChangedObject(const App::DocumentObject& Obj, const App::Property& Prop);
    void followChangedObject(const App::DocumentObject& Obj, const App::Property& Prop);
    void onSettingDocument() override;

    using Connection = fastsignals::connection;
    Connection connectDocumentChangedObject;
    // the container frames of the last traced execute (FreeCAD-CH ops#244), not saved
    Base::Placement tracedSourceCS;
    Base::Placement tracedTargetCS;
    bool traced = false;
};

class PartDesignExport SubShapeBinder: public Part::Feature
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::SubShapeBinder);

public:
    using inherited = Part::Feature;

    SubShapeBinder();
    ~SubShapeBinder() override;

    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderSubShapeBinder";
    }

    void setLinks(std::map<App::DocumentObject*, std::vector<std::string>>&& values, bool reset = false);

    App::PropertyXLinkSubList Support;
    App::PropertyBool ClaimChildren;
    App::PropertyBool Relative;
    App::PropertyBool Fuse;
    App::PropertyBool MakeFace;
    App::PropertyEnumeration BindMode;
    App::PropertyBool PartialLoad;
    App::PropertyXLink Context;
    App::PropertyInteger _Version;
    App::PropertyEnumeration BindCopyOnChange;
    App::PropertyBool Refine;
    // FreeCAD-CH (ops#319): a Distance, not a Float, so an expression with a length works.
    App::PropertyDistance Offset;
    App::PropertyEnumeration OffsetJoinType;
    App::PropertyBool OffsetFill;
    App::PropertyBool OffsetOpenResult;
    App::PropertyBool OffsetIntersection;

    enum UpdateOption
    {
        UpdateNone = 0,
        UpdateInit = 1,
        UpdateForced = 2,
    };
    void update(UpdateOption options = UpdateNone);

    int canLoadPartial() const override
    {
        return PartialLoad.getValue() ? 1 : 0;
    }

    bool canLinkProperties() const override
    {
        return false;
    }

    App::DocumentObject* getSubObject(
        const char* subname,
        PyObject** pyObj = nullptr,
        Base::Matrix4D* mat = nullptr,
        bool transform = true,
        int depth = 0
    ) const override;

    /// Fails on a support that depends on this binder, before anything else (FreeCAD-CH ops#308 T2)
    App::DocumentObjectExecReturn* recompute() override;
    /// Also when a support's mapping into the binder changed, e.g. its Body in another document
    /// moved (FreeCAD-CH ops#308 R2-1)
    short mustExecute() const override;

protected:
    App::DocumentObjectExecReturn* execute() override;
    void onChanged(const App::Property* prop) override;

    void handleChangedPropertyType(
        Base::XMLReader& reader,
        const char* TypeName,
        App::Property* prop
    ) override;

    void onDocumentRestored() override;
    void setupObject() override;

    void setupCopyOnChange();
    void checkCopyOnChange(const App::Property& prop);
    void clearCopiedObjects();

    void checkPropertyStatus();

    void collapseGeoChildren();

    void slotRecomputedObject(const App::DocumentObject& Obj);

    using Connection = fastsignals::scoped_connection;
    Connection connRecomputedObj;
    App::Document* contextDoc = nullptr;

    std::vector<Connection> copyOnChangeConns;
    bool hasCopyOnChange = true;

    App::PropertyXLinkSub _CopiedLink;
    std::vector<App::DocumentObjectT> _CopiedObjs;

private:
    App::DocumentObject* resolveParent(std::string& parentSub) const;
    std::map<const App::DocumentObject*, Base::Matrix4D> supportMatrices(
        App::DocumentObject* parent,
        const std::string& parentSub,
        bool report
    ) const;
    std::string cacheName(const App::DocumentObject* obj) const;

    // The matrices the last update() mapped the supports with, by cache name; not saved, so
    // mustExecute() reads the Cache_ properties before the first update (FreeCAD-CH ops#308)
    std::map<std::string, Base::Matrix4D> lastMats;
};

using SubShapeBinderPython = App::FeaturePythonT<SubShapeBinder>;

}  // namespace PartDesign
