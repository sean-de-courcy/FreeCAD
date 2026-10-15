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


#include <algorithm>

#include <Precision.hxx>

#include <App/Datums.h>
#include <App/Document.h>
#include <App/GeoFeature.h>
#include <App/GroupExtension.h>
#include <App/Link.h>
#include <App/Part.h>

#include "BodyBase.h"
#include "BodyBasePy.h"


namespace Part
{

PROPERTY_SOURCE_WITH_EXTENSIONS(Part::BodyBase, Part::Feature)

BodyBase::BodyBase()
{
    ADD_PROPERTY(Tip, (nullptr));
    Tip.setScope(App::LinkScope::Child);

    ADD_PROPERTY(BaseFeature, (nullptr));

    App::OriginGroupExtension::initExtension(this);
}

BodyBase* BodyBase::findBodyOf(const App::DocumentObject* f)
{
    App::Document* doc = f->getDocument();
    if (doc) {
        std::vector<App::DocumentObject*> bodies = doc->getObjectsOfType(BodyBase::getClassTypeId());
        for (auto it : bodies) {
            BodyBase* body = static_cast<BodyBase*>(it);
            if (body->hasObject(f)) {
                return body;
            }
        }
    }

    return nullptr;
}

namespace
{
// Assembly::AssemblyObject derives from App::Part; looked up by name, as Part doesn't link the
// Assembly module. A bad type isn't kept: the module can load after the first pick (ops#325)
Base::Type assemblyType()
{
    static Base::Type type = Base::Type::BadType;
    if (type.isBad()) {
        type = Base::Type::fromName("Assembly::AssemblyObject");
    }
    return type;
}

// A link of any kind: an App::Link, a link array or its element, an App::LinkGroup, or anything
// else whose linked object is another (ops#325)
bool isLinkType(const App::DocumentObject* obj)
{
    return obj->getLinkedObject(false) != obj
        || obj->hasExtension(App::LinkBaseExtension::getExtensionClassTypeId());
}

// Whether a link shows @p body, a container holding it, its Origin or one of their features: a
// pick through it would ignore the link's placement, and a selection gate sees only the resolved
// object (ops#325). Any link-type user counts, whatever it resolves to: a sub-link (Studio, "B.")
// sits in the Studio's in-list and resolves to B, a LinkGroup holding B resolves to itself.
bool isShownThroughALink(const BodyBase* body)
{
    std::vector<const App::DocumentObject*> shown {body};
    // every group holding it, up to the top: App::Part and plain groups alike
    // (GroupExtension::getGroupOfObject() finds plain groups only)
    for (std::size_t i = 0; i < shown.size(); ++i) {
        for (auto user : shown[i]->getInList()) {
            auto group = user ? user->getExtensionByType<App::GroupExtension>(true) : nullptr;
            if (group && group->hasObject(shown[i])
                && std::find(shown.begin(), shown.end(), user) == shown.end()) {
                shown.push_back(user);
            }
        }
    }
    for (auto member : body->Group.getValues()) {
        shown.push_back(member);
    }
    if (auto origin = freecad_cast<App::LocalCoordinateSystem*>(body->Origin.getValue())) {
        shown.push_back(origin);
        for (auto feature : origin->OriginFeatures.getValues()) {
            shown.push_back(feature);
        }
    }
    for (auto obj : shown) {
        if (!obj) {
            continue;
        }
        for (auto user : obj->getInList()) {
            if (user && user != obj && isLinkType(user)) {
                return true;
            }
        }
    }
    return false;
}
}  // namespace

BodyBase* BodyBase::bodyOfObject(const App::DocumentObject* obj)
{
    if (!obj) {
        return nullptr;
    }
    if (obj->isDerivedFrom<BodyBase>()) {
        return const_cast<BodyBase*>(static_cast<const BodyBase*>(obj));
    }
    if (auto body = findBodyOf(obj)) {
        return body;
    }
    // An origin plane or axis: the Body of its origin
    if (auto datum = freecad_cast<const App::DatumElement*>(obj)) {
        if (auto lcs = datum->getLCS()) {
            for (auto parent : lcs->getInList()) {
                auto body = freecad_cast<BodyBase*>(parent);
                if (body && body->Origin.getValue() == lcs) {
                    return body;
                }
            }
        }
    }
    return nullptr;
}

bool BodyBase::studioOf(const BodyBase* body, App::Part*& studio)
{
    studio = nullptr;
    if (!body) {
        return false;
    }
    studio = App::Part::getPartOfObject(body, /*recursive=*/true);
    const Base::Type assembly = assemblyType();
    return !(studio && !assembly.isBad() && studio->isDerivedFrom(assembly));
}

bool BodyBase::isInOneStudio(const App::DocumentObject* owner, const App::DocumentObject* target)
{
    if (!owner || !target || !owner->getDocument()
        || owner->getDocument() != target->getDocument()) {
        return false;
    }
    BodyBase* ownerBody = bodyOfObject(owner);
    BodyBase* targetBody = bodyOfObject(target);
    if (!ownerBody || !targetBody) {
        return false;
    }
    if (ownerBody == targetBody) {
        return true;
    }
    // Another Body itself (picked whole, shown as its Tip): the link would depend on all of it,
    // features that use the owner included, a cycle (ops#325). Its features are linked instead
    if (target == targetBody) {
        return false;
    }
    return areStudioSiblings(ownerBody, targetBody);
}

bool BodyBase::areStudioSiblings(const BodyBase* one, const BodyBase* other)
{
    App::Part* oneStudio = nullptr;
    App::Part* otherStudio = nullptr;
    if (!one || !other || one == other || !one->getDocument()
        || one->getDocument() != other->getDocument() || !studioOf(one, oneStudio)
        || !studioOf(other, otherStudio) || oneStudio != otherStudio) {
        return false;
    }
    // Bodies placed apart don't share an origin: every reader takes the target's geometry in the
    // owner's frame, so the reference would land elsewhere, silently. Until the one-origin check
    // (session 1b), such a pick goes through the copy, which places it right (ops#325)
    try {
        if (!App::GeoFeature::getGlobalPlacement(one)
                 .isSame(App::GeoFeature::getGlobalPlacement(other), Precision::Confusion())) {
            return false;
        }
    }
    catch (const Base::Exception&) {
        // A container recomputing has no global placement yet: not known to be one origin
        return false;
    }
    return !isShownThroughALink(other);
}

bool BodyBase::isStudioPick(
    const App::DocumentObject* owner,
    const App::DocumentObject* topParent,
    const char* subname
)
{
    if (!topParent) {
        return false;
    }
    std::vector<App::DocumentObject*> path {const_cast<App::DocumentObject*>(topParent)};
    if (subname && *subname) {
        path = topParent->getSubObjectList(subname);
        if (path.empty()) {
            return false;
        }
    }
    for (auto obj : path) {
        if (!obj || isLinkType(obj)) {
            return false;
        }
    }
    return isInOneStudio(owner, path.back());
}

App::DocumentObject* BodyBase::studioOriginFeature(
    const App::DocumentObject* owner,
    const App::DocumentObject* feature
)
{
    auto datum = freecad_cast<const App::DatumElement*>(feature);
    BodyBase* ownerBody = bodyOfObject(owner);
    BodyBase* featureBody = bodyOfObject(feature);
    if (!datum || !datum->getLCS() || !ownerBody || !featureBody
        || !areStudioSiblings(ownerBody, featureBody)) {
        return nullptr;
    }
    auto origin = freecad_cast<App::LocalCoordinateSystem*>(ownerBody->Origin.getValue());
    if (!origin || datum->getLCS() != featureBody->Origin.getValue()) {
        return nullptr;
    }
    try {
        return origin->getDatumElement(datum->Role.getValue());
    }
    catch (const Base::Exception&) {
        return nullptr;
    }
}

bool BodyBase::isAfter(const App::DocumentObject* feature, const App::DocumentObject* target) const
{
    assert(feature);

    if (feature == target) {
        return false;
    }

    if (!target || target == BaseFeature.getValue()) {
        return hasObject(feature);
    }

    const std::vector<App::DocumentObject*>& features = Group.getValues();
    const auto featureIt = std::ranges::find(features, feature);
    const auto targetIt = std::ranges::find(features, target);

    return featureIt == features.end() ? false : featureIt > targetIt;
}

void BodyBase::onBeforeChange(const App::Property* prop)
{

    // Tip can't point outside the body, hence no base feature tip
    /*// If we are changing the base feature and tip point to it reset it
    if ( prop == &BaseFeature && BaseFeature.getValue() == Tip.getValue() && BaseFeature.getValue()
    ) { Tip.setValue( nullptr );
    }*/
    Part::Feature::onBeforeChange(prop);
}

void BodyBase::onChanged(const App::Property* prop)
{
    // Tip can't point outside the body, hence no base feature tip
    /*// If the tip is zero and we are adding a base feature to the body set it to be the tip
    if ( prop == &BaseFeature && !Tip.getValue() && BaseFeature.getValue() ) {
        Tip.setValue( BaseFeature.getValue () );
    }*/
    Part::Feature::onChanged(prop);
}

void BodyBase::handleChangedPropertyName(Base::XMLReader& reader, const char* TypeName, const char* PropName)
{
    // The App::PropertyLinkList property was Model in the past (#0002642)
    Base::Type type = Base::Type::fromName(TypeName);
    if (Group.getClassTypeId() == type && strcmp(PropName, "Model") == 0) {
        Group.Restore(reader);
    }
    else {
        Part::Feature::handleChangedPropertyName(reader, TypeName, PropName);
    }
}

PyObject* BodyBase::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new BodyBasePy(this), true);
    }
    return Py::new_reference_to(PythonObject);
}

}  // namespace Part
