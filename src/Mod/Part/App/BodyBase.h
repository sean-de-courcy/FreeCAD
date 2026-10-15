// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2010 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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

#include <App/PropertyStandard.h>
#include <App/OriginGroupExtension.h>

#include <Mod/Part/PartGlobal.h>

#include "PartFeature.h"

namespace App
{
class Part;
}

namespace Part
{
/** Base class of all body objects in FreeCAD
 * A body is used, e.g. in PartDesign, to aggregate
 * some modeling features to one shape. As long as not
 * in edit or active on a workbench, the body shows only the
 * resulting shape to the outside (Tip link).
 */
class PartExport BodyBase: public Part::Feature, public App::OriginGroupExtension
{
    PROPERTY_HEADER_WITH_EXTENSIONS(Part::BodyBase);

public:
    BodyBase();

    /**
     * The final feature of the body it is associated with.
     * Note: tip may either point to the BaseFeature or to some feature inside the Group list.
     */
    App::PropertyLink Tip;

    /**
     * A base object of the body, serves as a base object for the first feature of the body.
     * A Part::Feature link to make bodies be able based upon non-PartDesign Features.
     */
    App::PropertyLink BaseFeature;

    /// Returns all Group objects prepanded by BaseFeature (if any)
    std::vector<App::DocumentObject*> getFullModel()
    {
        std::vector<App::DocumentObject*> rv;
        if (BaseFeature.getValue()) {
            rv.push_back(BaseFeature.getValue());
        }
        std::copy(Group.getValues().begin(), Group.getValues().end(), std::back_inserter(rv));
        return rv;
    }

    /// Return true if the feature belongs to the body and is located after the target
    bool isAfter(const App::DocumentObject* feature, const App::DocumentObject* target) const;

    /**
     * Return the body which this feature belongs too, or NULL.
     * Note: Normally each PartDesign feature belongs to a single body,
     *       But if a body is based on the feature it also will be return...
     *       But there are could be more features based on the same body.
     * TODO introduce a findBodiesOf() if needed (2015-08-04, Fat-Zer)
     */
    static BodyBase* findBodyOf(const App::DocumentObject* f);

    /// The Body of @p obj: @p obj itself, the Body holding it, or the Body of its origin feature
    static BodyBase* bodyOfObject(const App::DocumentObject* obj);

    /** The studio of @p body (ops#325, B+): the App::Part that holds it, or the document's top
     * level (@p studio null). The Bodies of one studio share one origin, so they may reference
     * each other directly. An Assembly is not a studio (its joints move Bodies).
     * @return false when @p body has no studio: null, or placed directly in an Assembly
     */
    static bool studioOf(const BodyBase* body, App::Part*& studio);

    /** True when @p owner may link @p target directly, with no binder or copy: both are in one
     * Body, or @p target is in a studio sibling of @p owner's Body (areStudioSiblings()). Another
     * Body itself is refused: a link to it would depend on all of it
     */
    static bool isInOneStudio(const App::DocumentObject* owner, const App::DocumentObject* target);

    /** Two Bodies of one studio (ops#325) placed alike (one origin), @p other shown by no link
     * (neither it, a container holding it, nor one of its features)
     */
    static bool areStudioSiblings(const BodyBase* one, const BodyBase* other);

    /** isInOneStudio() for a pick: @p subname is the path from @p topParent to the picked object.
     * A path through an App::Link is refused: the reference would ignore the Link's placement.
     */
    static bool isStudioPick(
        const App::DocumentObject* owner,
        const App::DocumentObject* topParent,
        const char* subname
    );

    /** The origin feature of @p owner's Body that stands for @p feature, an origin feature of
     * another Body of the same studio: the same plane or axis under one origin (ops#325).
     * @return null when @p feature is no such origin feature
     */
    static App::DocumentObject* studioOriginFeature(
        const App::DocumentObject* owner,
        const App::DocumentObject* feature
    );
    PyObject* getPyObject() override;

protected:
    /// If BaseFeature is getting changed and Tip points to it reset the Tip
    void onBeforeChange(const App::Property* prop) override;
    /// If BaseFeature is set and Tip is null set the Tip to it
    void onChanged(const App::Property* prop) override;
    void handleChangedPropertyName(
        Base::XMLReader& reader,
        const char* TypeName,
        const char* PropName
    ) override;
};

}  // namespace Part
