// SPDX-License-Identifier: LGPL-2.1-or-later

/****************************************************************************
 *                                                                          *
 *   This file is part of the FreeCAD CAx development system.               *
 *                                                                          *
 *   This library is free software; you can redistribute it and/or          *
 *   modify it under the terms of the GNU Library General Public            *
 *   License as published by the Free Software Foundation; either           *
 *   version 2 of the License, or (at your option) any later version.       *
 *                                                                          *
 *   This library  is distributed in the hope that it will be useful,       *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of         *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          *
 *   GNU Library General Public License for more details.                   *
 *                                                                          *
 *   You should have received a copy of the GNU Library General Public      *
 *   License along with this library; see the file COPYING.LIB. If not,     *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,          *
 *   Suite 330, Boston, MA  02111-1307, USA                                 *
 *                                                                          *
 ****************************************************************************/

#include <algorithm>
#include <map>
#include <set>
#include <sstream>

#include <CXX/Extensions.hxx>

#include <Base/Interpreter.h>

#include "DocumentTabs.h"
#include "Document.h"
#include "DocumentObject.h"
#include "DocumentObjectPy.h"
#include "DocumentPy.h"
#include "GeoFeature.h"
#include "GeoFeatureGroupExtension.h"
#include "GroupExtension.h"
#include "Link.h"
#include "Origin.h"
#include "OriginGroupExtension.h"
#include "Part.h"
#include "VarSet.h"
#include "VarSetCopy.h"

using namespace App;
using namespace App::DocumentTabs;

namespace
{

// Assembly and TechDraw aren't linked by App: their types by name, not kept while bad (the modules
// can load after the first call), as GeoFeatureGroupExtension.cpp does
Base::Type typeNamed(Base::Type& type, const char* name)
{
    if (type.isBad()) {
        type = Base::Type::fromName(name);
    }
    return type;
}

Base::Type assemblyType()
{
    static Base::Type type = Base::Type::BadType;
    return typeNamed(type, "Assembly::AssemblyObject");
}

Base::Type drawPageType()
{
    static Base::Type type = Base::Type::BadType;
    return typeNamed(type, "TechDraw::DrawPage");
}

bool isDerived(const DocumentObject* obj, Base::Type type)
{
    return !type.isBad() && obj->getTypeId().isDerivedFrom(type);
}

// Export leaves sketches and datums out (Part isn't linked by App either)
Base::Type sketchType()
{
    static Base::Type type = Base::Type::BadType;
    return typeNamed(type, "Part::Part2DObject");
}

Base::Type datumType()
{
    static Base::Type type = Base::Type::BadType;
    return typeNamed(type, "Part::Datum");
}

/// The registry, parsed: "order=a,b\nvariables=c,d\nimplicit=<label>"
struct Registry
{
    std::vector<std::string> order;
    std::vector<std::string> variables;
    std::string implicit;
    bool hasImplicit = false;
};

std::vector<std::string> splitNames(const std::string& text)
{
    std::vector<std::string> names;
    std::stringstream stream(text);
    std::string name;
    while (std::getline(stream, name, ',')) {
        if (!name.empty()) {
            names.push_back(name);
        }
    }
    return names;
}

std::string joinNames(const std::vector<std::string>& names)
{
    std::string text;
    for (const auto& name : names) {
        if (!text.empty()) {
            text += ',';
        }
        text += name;
    }
    return text;
}

Registry readRegistry(const Document* doc)
{
    Registry registry;
    if (!doc) {
        return registry;
    }
    const auto& values = doc->Meta.getValues();
    auto it = values.find(metaKey());
    if (it == values.end()) {
        return registry;
    }
    std::stringstream stream(it->second);
    std::string line;
    while (std::getline(stream, line)) {
        auto equal = line.find('=');
        if (equal == std::string::npos) {
            continue;
        }
        const std::string key = line.substr(0, equal);
        const std::string value = line.substr(equal + 1);
        if (key == "order") {
            registry.order = splitNames(value);
        }
        else if (key == "variables") {
            registry.variables = splitNames(value);
        }
        else if (key == "implicit") {
            registry.implicit = value;
            registry.hasImplicit = true;
        }
    }
    return registry;
}

void writeRegistry(Document* doc, const Registry& registry)
{
    // RT-5: the order keeps the names of objects that exist (and the implicit studio's "*"); a
    // tab undone meanwhile goes last on its redo
    std::vector<std::string> order;
    for (const auto& name : registry.order) {
        if (name == implicitName() || doc->getObject(name.c_str())) {
            order.push_back(name);
        }
    }
    std::string text = "order=" + joinNames(order) + "\nvariables="
        + joinNames(registry.variables);
    if (registry.hasImplicit) {
        std::string label = registry.implicit;
        std::replace(label.begin(), label.end(), '\n', ' ');
        text += "\nimplicit=" + label;
    }
    doc->Meta.setValue(metaKey(), text);
}

bool isTopLevel(const DocumentObject* obj)
{
    return !GeoFeatureGroupExtension::getGroupOfObject(obj);
}

/// A 3D object of the implicit studio at the top level
bool isImplicitContent(const DocumentObject* obj)
{
    if (!obj || !obj->isAttachedToDocument() || !isTopLevel(obj) || isTabObject(obj)) {
        return false;
    }
    if (obj->isDerivedFrom<Origin>() || obj->isDerivedFrom<DatumElement>()) {
        return false;
    }
    // A link array's elements are its link's, not top-level solids of their own (R6T-9)
    if (obj->isDerivedFrom<LinkElement>()) {
        return false;
    }
    return obj->isDerivedFrom<GeoFeature>()
        || obj->hasExtension(LinkBaseExtension::getExtensionClassTypeId());
}

void addWithChildren(
    DocumentObject* obj,
    std::vector<DocumentObject*>& list,
    std::set<DocumentObject*>& seen
)
{
    if (!obj || !seen.insert(obj).second) {
        return;
    }
    list.push_back(obj);
    if (auto group = obj->getExtensionByType<GroupExtension>(true)) {
        for (auto child : group->Group.getValues()) {
            addWithChildren(child, list, seen);
        }
    }
    if (auto originGroup = obj->getExtensionByType<OriginGroupExtension>(true)) {
        if (auto origin = originGroup->Origin.getValue()) {
            addWithChildren(origin, list, seen);
            if (auto originObj = freecad_cast<Origin*>(origin)) {
                for (auto feature : originObj->OriginFeatures.getValues()) {
                    addWithChildren(feature, list, seen);
                }
            }
        }
    }
    if (isDerived(obj, drawPageType())) {
        for (const char* name : {"Views", "Template"}) {
            auto prop = obj->getPropertyByName(name);
            if (auto links = freecad_cast<PropertyLinkList*>(prop)) {
                for (auto view : links->getValues()) {
                    addWithChildren(view, list, seen);
                }
            }
            else if (auto link = freecad_cast<PropertyLink*>(prop)) {
                addWithChildren(link->getValue(), list, seen);
            }
        }
    }
}

/// A Part Studio's part for Export: a visible Body, solid or link; a plain group's parts
void addParts(
    DocumentObject* obj,
    std::vector<DocumentObject*>& list,
    std::set<DocumentObject*>& seen
)
{
    if (!obj || !seen.insert(obj).second || obj->isDerivedFrom<Origin>()
        || obj->isDerivedFrom<DatumElement>() || isDerived(obj, sketchType())
        || isDerived(obj, datumType()) || obj->isDerivedFrom<LinkElement>()) {
        return;
    }
    const bool isLink = obj->hasExtension(LinkBaseExtension::getExtensionClassTypeId());
    if (!obj->isDerivedFrom<GeoFeature>() && !isLink) {
        if (auto group = obj->getExtensionByType<GroupExtension>(true)) {
            for (auto child : group->Group.getValues()) {
                addParts(child, list, seen);
            }
        }
        return;
    }
    if (obj->Visibility.getValue()) {
        list.push_back(obj);
    }
}

const char* kindName(Kind kind)
{
    switch (kind) {
        case Kind::PartStudio:
            return "PartStudio";
        case Kind::Assembly:
            return "Assembly";
        case Kind::Drawing:
            return "Drawing";
        case Kind::VariableStudio:
            return "VariableStudio";
    }
    return "";
}

}  // namespace

const char* DocumentTabs::metaKey()
{
    return "FreeCADCH.Tabs";
}

const char* DocumentTabs::implicitName()
{
    return "*";
}

bool DocumentTabs::isTabObject(const DocumentObject* obj, Kind* kind)
{
    if (!obj || !obj->isAttachedToDocument()) {
        return false;
    }
    Kind found {};
    if (obj->isDerivedFrom<App::Part>()) {
        if (!isTopLevel(obj)) {
            return false;
        }
        found = isDerived(obj, assemblyType()) ? Kind::Assembly : Kind::PartStudio;
    }
    else if (isDerived(obj, drawPageType())) {
        found = Kind::Drawing;
    }
    else if (isVariableStudio(obj)) {
        found = Kind::VariableStudio;
    }
    else {
        return false;
    }
    if (kind) {
        *kind = found;
    }
    return true;
}

DocumentObject* DocumentTabs::tabOf(const DocumentObject* obj)
{
    if (!obj) {
        return nullptr;
    }
    if (isTabObject(obj)) {
        return const_cast<DocumentObject*>(obj);
    }
    DocumentObject* top = nullptr;
    std::set<const DocumentObject*> seen {obj};
    auto group = GeoFeatureGroupExtension::getGroupOfObject(obj);
    while (group && seen.insert(group).second) {
        top = group;
        group = GeoFeatureGroupExtension::getGroupOfObject(group);
    }
    return top && isTabObject(top) ? top : nullptr;
}

std::string DocumentTabs::tabNameOf(const DocumentObject* obj)
{
    auto tab = tabOf(obj);
    return tab ? std::string(tab->getNameInDocument()) : std::string(implicitName());
}

bool DocumentTabs::hasImplicitStudio(const Document* doc)
{
    if (!doc) {
        return false;
    }
    // Once named or shown, it stays a tab when emptied, as Onshape keeps an empty Part Studio
    // (R6T-12); deleting the tab forgets it (removeTab())
    if (readRegistry(doc).hasImplicit) {
        return true;
    }
    bool otherStudio = false;
    for (auto obj : doc->getObjects()) {
        if (isImplicitContent(obj)) {
            return true;
        }
        Kind kind {};
        if (isTabObject(obj, &kind) && kind == Kind::PartStudio) {
            otherStudio = true;
        }
    }
    return !otherStudio;
}

std::vector<Tab> DocumentTabs::tabs(const Document* doc)
{
    std::vector<Tab> list;
    if (!doc) {
        return list;
    }
    if (hasImplicitStudio(doc)) {
        list.push_back({Kind::PartStudio, nullptr});
    }
    for (auto obj : doc->getObjects()) {
        Kind kind {};
        if (isTabObject(obj, &kind)) {
            list.push_back({kind, obj});
        }
    }
    const Registry registry = readRegistry(doc);
    std::map<std::string, std::size_t> rank;
    for (std::size_t i = 0; i < registry.order.size(); ++i) {
        rank.emplace(registry.order[i], i);
    }
    auto rankOf = [&rank](const Tab& tab) {
        auto it = rank.find(tab.name());
        return it == rank.end() ? rank.size() : it->second;
    };
    std::stable_sort(list.begin(), list.end(), [&rankOf](const Tab& a, const Tab& b) {
        return rankOf(a) < rankOf(b);
    });
    return list;
}

bool DocumentTabs::findTab(const Document* doc, const std::string& name, Tab& tab)
{
    for (const auto& candidate : tabs(doc)) {
        if (candidate.name() == name) {
            tab = candidate;
            return true;
        }
    }
    return false;
}

std::string DocumentTabs::label(const Document* doc, const Tab& tab)
{
    return tab.object ? std::string(tab.object->Label.getValue()) : implicitLabel(doc);
}

std::string DocumentTabs::implicitLabel(const Document* doc)
{
    const Registry registry = readRegistry(doc);
    if (registry.hasImplicit && !registry.implicit.empty()) {
        return registry.implicit;
    }
    // The lowest "Part Studio N" no tab object is named (R6T-7): after Std_New's App::Part "Part
    // Studio 1", an import's top-level solids are "Part Studio 2"
    std::set<std::string> labels;
    if (doc) {
        for (auto obj : doc->getObjects()) {
            if (isTabObject(obj)) {
                labels.insert(obj->Label.getValue());
            }
        }
    }
    for (int i = 1;; ++i) {
        std::string candidate = "Part Studio " + std::to_string(i);
        if (!labels.count(candidate)) {
            return candidate;
        }
    }
}

bool DocumentTabs::hasImplicitLabel(const Document* doc)
{
    return readRegistry(doc).hasImplicit;
}

void DocumentTabs::setImplicitLabel(Document* doc, const std::string& label)
{
    if (!doc) {
        return;
    }
    Registry registry = readRegistry(doc);
    registry.implicit = label;
    registry.hasImplicit = true;
    writeRegistry(doc, registry);
}

std::vector<std::string> DocumentTabs::order(const Document* doc)
{
    return readRegistry(doc).order;
}

void DocumentTabs::setOrder(Document* doc, const std::vector<std::string>& names)
{
    if (!doc) {
        return;
    }
    Registry registry = readRegistry(doc);
    registry.order = names;
    writeRegistry(doc, registry);
}

void DocumentTabs::placeAfter(Document* doc, const std::string& name, const std::string& after)
{
    std::vector<std::string> names;
    for (const auto& tab : tabs(doc)) {
        if (tab.name() != name) {
            names.push_back(tab.name());
        }
    }
    auto it = std::find(names.begin(), names.end(), after);
    names.insert(it == names.end() ? it : it + 1, name);
    setOrder(doc, names);
}

bool DocumentTabs::isVariableStudio(const DocumentObject* obj)
{
    if (!obj || !obj->isAttachedToDocument() || obj->getTypeId() != VarSet::getClassTypeId()) {
        return false;
    }
    const Registry registry = readRegistry(obj->getDocument());
    return std::find(registry.variables.begin(), registry.variables.end(), obj->getNameInDocument())
        != registry.variables.end();
}

void DocumentTabs::setVariableStudio(DocumentObject* varSet, bool marked)
{
    if (!varSet || !varSet->isAttachedToDocument()
        || varSet->getTypeId() != VarSet::getClassTypeId()) {
        throw Base::TypeError("A Variable Studio is an App::VarSet");
    }
    Registry registry = readRegistry(varSet->getDocument());
    const std::string name = varSet->getNameInDocument();
    auto it = std::find(registry.variables.begin(), registry.variables.end(), name);
    if (marked && it == registry.variables.end()) {
        registry.variables.push_back(name);
    }
    else if (!marked && it != registry.variables.end()) {
        registry.variables.erase(it);
    }
    else {
        return;
    }
    writeRegistry(varSet->getDocument(), registry);
}

std::vector<DocumentObject*> DocumentTabs::variableReferences(const DocumentObject* studio)
{
    // FreeCAD-CH ops#721: the list is kept on the copies (Studio, StudioPosition), so that it is
    // undoable and a deleted copy leaves nothing behind
    std::vector<DocumentObject*> result;
    if (!isVariableStudio(studio)) {
        return result;
    }
    const std::string name = studio->getNameInDocument();
    for (auto* obj : studio->getDocument()->getObjects()) {
        auto copy = freecad_cast<VarSetCopy*>(obj);
        if (copy && copy->isAttached() && name == copy->Studio.getValue()
            && copy->StudioID.getValue() == studio->getID()) {
            result.push_back(copy);
        }
    }
    std::stable_sort(result.begin(), result.end(), [](DocumentObject* a, DocumentObject* b) {
        return static_cast<VarSetCopy*>(a)->StudioPosition.getValue()
            < static_cast<VarSetCopy*>(b)->StudioPosition.getValue();
    });
    return result;
}

DocumentObject* DocumentTabs::studioOf(const DocumentObject* obj)
{
    auto copy = freecad_cast<const VarSetCopy*>(obj);
    if (!copy || !copy->isAttachedToDocument() || !copy->isAttached()) {
        return nullptr;
    }
    const char* name = copy->Studio.getValue();
    if (!name || !*name) {
        return nullptr;
    }
    DocumentObject* studio = copy->getDocument()->getObject(name);
    // the name may be a later object's, reusing a deleted studio's name: the ID tells
    return isVariableStudio(studio) && studio->getID() == copy->StudioID.getValue() ? studio
                                                                                   : nullptr;
}

std::string DocumentTabs::nextLabel(const Document* doc, const std::string& base)
{
    std::set<std::string> labels;
    for (const auto& tab : tabs(doc)) {
        labels.insert(label(doc, tab));
    }
    for (int i = 1;; ++i) {
        std::string candidate = base + " " + std::to_string(i);
        if (!labels.count(candidate)) {
            return candidate;
        }
    }
}

std::vector<DocumentObject*> DocumentTabs::members(const Document* doc, const Tab& tab)
{
    std::vector<DocumentObject*> list;
    std::set<DocumentObject*> seen;
    if (tab.object) {
        addWithChildren(tab.object, list, seen);
        return list;
    }
    if (!doc) {
        return list;
    }
    for (auto obj : doc->getObjects()) {
        if (isImplicitContent(obj)) {
            addWithChildren(obj, list, seen);
        }
    }
    return list;
}

std::vector<DocumentObject*> DocumentTabs::dependents(const Document* doc, const Tab& tab)
{
    const auto list = members(doc, tab);
    const std::set<DocumentObject*> inside(list.begin(), list.end());
    std::vector<DocumentObject*> users;
    std::set<DocumentObject*> seen;
    for (auto obj : list) {
        for (auto user : obj->getInList()) {
            if (user && !inside.count(user) && seen.insert(user).second) {
                users.push_back(user);
            }
        }
    }
    return users;
}

void DocumentTabs::removeTab(Document* doc, const Tab& tab)
{
    if (!doc) {
        return;
    }
    std::vector<std::string> roots;
    if (tab.object) {
        roots.emplace_back(tab.object->getNameInDocument());
    }
    else {
        for (auto obj : doc->getObjects()) {
            if (isImplicitContent(obj)) {
                roots.emplace_back(obj->getNameInDocument());
            }
        }
    }
    for (const auto& name : roots) {
        auto obj = doc->getObject(name.c_str());
        if (!obj) {
            continue;  // removed with an earlier one
        }
        if (auto group = obj->getExtensionByType<GroupExtension>(true)) {
            group->removeObjectsFromDocument();
        }
        if (doc->getObject(name.c_str())) {
            doc->removeObject(name.c_str());
        }
    }
    if (!tab.object) {
        // The implicit studio's tab goes with its contents (hasImplicitStudio()); forgotten after
        // the deletes, which may store its label (the GUI keeps a shown studio emptied, F6-2)
        Registry registry = readRegistry(doc);
        if (registry.hasImplicit) {
            registry.hasImplicit = false;
            registry.implicit.clear();
            writeRegistry(doc, registry);
        }
    }
}

std::string DocumentTabs::duplicateRefusal(const Document* doc, const Tab& tab)
{
    const std::string name = label(doc, tab);
    if (!tab.object) {
        // The implicit studio (an older file's top level): no object to copy as a tab
        return name
            + " is the document's top level (a file made before tabs): it can't be duplicated";
    }
    if (tab.kind == Kind::Drawing || tab.kind == Kind::VariableStudio) {
        return std::string("A ") + (tab.kind == Kind::Drawing ? "Drawing" : "Variable Studio")
            + " can't be duplicated yet";
    }
    if (tab.kind == Kind::Assembly) {
        return {};  // its links keep pointing at the same studios
    }
    // A Part Studio copies alone: what it uses from outside (a Derived source, another studio's
    // binder) would stay shared with the original. Onshape copies the reference [guess]; refusing
    // is the loud boundary. A VarSet (a Variable Studio) is shared by every tab
    const auto list = members(doc, tab);
    const std::set<DocumentObject*> inside(list.begin(), list.end());
    for (auto obj : list) {
        for (auto used : obj->getOutList()) {
            if (!used || inside.count(used) || used->isDerivedFrom<VarSet>()) {
                continue;
            }
            std::string where;
            Tab other {};
            if (used->isAttachedToDocument()
                && findTab(used->getDocument(), tabNameOf(used), other)) {
                where = " (" + label(used->getDocument(), other) + ")";
            }
            return name + " uses " + used->Label.getValue() + where
                + ", which is outside it: it can't be duplicated";
        }
    }
    return {};
}

std::string DocumentTabs::duplicateLabel(const Document* doc, const Tab& tab)
{
    std::set<std::string> labels;
    for (const auto& other : tabs(doc)) {
        labels.insert(label(doc, other));
    }
    const std::string base = label(doc, tab);
    for (int i = 1;; ++i) {
        std::string candidate = base + " (" + std::to_string(i) + ")";
        if (!labels.count(candidate)) {
            return candidate;
        }
    }
}

DocumentObject* DocumentTabs::duplicate(Document* doc, const Tab& tab)
{
    if (!doc) {
        throw Base::RuntimeError("No document");
    }
    const std::string refusal = duplicateRefusal(doc, tab);
    if (!refusal.empty()) {
        throw Base::RuntimeError(refusal);
    }
    const std::string copyLabel = duplicateLabel(doc, tab);
    const std::string original = tab.name();
    const Base::Type type = tab.object->getTypeId();
    // The tab object first (members()), then what it holds: one copy, its links remapped to
    // the copies, links to what isn't copied (a VarSet, an assembly's studios) kept
    const auto list = members(doc, tab);
    const auto copies = doc->copyObject(list, false, false);
    DocumentObject* copy = nullptr;
    if (copies.size() == list.size()) {
        copy = copies.front();
    }
    else {
        for (auto candidate : copies) {
            if (candidate && candidate->getTypeId() == type && isTabObject(candidate)) {
                copy = candidate;
                break;
            }
        }
    }
    if (!copy || !copy->isAttachedToDocument()) {
        throw Base::RuntimeError("The copy of " + label(doc, tab) + " failed");
    }
    copy->Label.setValue(copyLabel);
    placeAfter(doc, copy->getNameInDocument(), original);
    return copy;
}

std::vector<DocumentObject*> DocumentTabs::exportObjects(const Document* doc, const Tab& tab)
{
    std::vector<DocumentObject*> list;
    std::set<DocumentObject*> seen;
    if (tab.kind == Kind::Assembly && tab.object) {
        list.push_back(tab.object);
        return list;
    }
    if (tab.kind != Kind::PartStudio || !doc) {
        return list;
    }
    if (tab.object) {
        if (auto group = tab.object->getExtensionByType<GroupExtension>(true)) {
            for (auto child : group->Group.getValues()) {
                addParts(child, list, seen);
            }
        }
        return list;
    }
    for (auto obj : doc->getObjects()) {
        if (isImplicitContent(obj)) {
            addParts(obj, list, seen);
        }
    }
    return list;
}

void DocumentTabs::exportTab(
    const Document* doc,
    const Tab& tab,
    const std::string& path,
    const char* module
)
{
    const auto objects = exportObjects(doc, tab);
    if (objects.empty()) {
        throw Base::RuntimeError(
            tab.kind == Kind::PartStudio || tab.kind == Kind::Assembly
                ? label(doc, tab) + " has no visible part to export"
                : std::string("Only a Part Studio or an Assembly exports to STEP")
        );
    }
    Base::PyGILStateLocker lock;
    try {
        PyObject* imported = PyImport_ImportModule(module ? module : "Import");
        if (!imported) {
            throw Py::Exception();
        }
        Py::Module writer(imported, true);
        Py::Callable exporter(writer.getAttr("export"));
        Py::List list;
        for (auto obj : objects) {
            list.append(Py::asObject(obj->getPyObject()));
        }
        Py::Tuple args(2);
        args.setItem(0, list);
        args.setItem(1, Py::String(path));
        Py::Dict kwds;
        kwds.setItem("exportHidden", Py::False());
        exporter.apply(args, kwds);
    }
    catch (Py::Exception&) {
        Base::PyException error;
        throw error;
    }
}

// -- Python: FreeCAD.DocumentTabs ---------------------------------------------------------------

namespace
{

Document* documentArg(PyObject* arg)
{
    if (!PyObject_TypeCheck(arg, &DocumentPy::Type)) {
        throw Py::TypeError("expected a document");
    }
    return static_cast<DocumentPy*>(arg)->getDocumentPtr();
}

DocumentObject* objectArg(PyObject* arg)
{
    if (!PyObject_TypeCheck(arg, &DocumentObjectPy::Type)) {
        throw Py::TypeError("expected a document object");
    }
    return static_cast<DocumentObjectPy*>(arg)->getDocumentObjectPtr();
}

Tab tabArg(Document* doc, const char* name)
{
    Tab tab {};
    if (!findTab(doc, name, tab)) {
        throw Py::ValueError(std::string("no tab named ") + name);
    }
    return tab;
}

Py::List objectList(const std::vector<DocumentObject*>& objects)
{
    Py::List list;
    for (auto obj : objects) {
        list.append(Py::asObject(obj->getPyObject()));
    }
    return list;
}

class Module: public Py::ExtensionModule<Module>  // NOLINT
{
public:
    Module()
        : Py::ExtensionModule<Module>("DocumentTabs")
    {
        add_varargs_method(
            "tabs",
            &Module::pyTabs,
            "tabs(doc) -> [(name, kind, label)]: the document's typed tabs in order; name '*' is\n"
            "the implicit Part Studio (the top level)"
        );
        add_varargs_method(
            "tabOf",
            &Module::pyTabOf,
            "tabOf(obj) -> the name of the tab holding obj"
        );
        add_varargs_method("hasImplicitStudio", &Module::pyHasImplicit, "hasImplicitStudio(doc)");
        add_varargs_method(
            "label",
            &Module::pyLabel,
            "label(doc, name) -> the tab's name in the bar"
        );
        add_varargs_method(
            "setImplicitLabel",
            &Module::pySetImplicitLabel,
            "setImplicitLabel(doc, label)"
        );
        add_varargs_method("order", &Module::pyOrder, "order(doc) -> the stored order");
        add_varargs_method("setOrder", &Module::pySetOrder, "setOrder(doc, [names])");
        add_varargs_method("placeAfter", &Module::pyPlaceAfter, "placeAfter(doc, name, after)");
        add_varargs_method(
            "isVariableStudio",
            &Module::pyIsVariableStudio,
            "isVariableStudio(obj)"
        );
        add_varargs_method(
            "setVariableStudio",
            &Module::pySetVariableStudio,
            "setVariableStudio(varset, marked=True)"
        );
        add_varargs_method(
            "variableReferences",
            &Module::pyVariableReferences,
            "variableReferences(studio) -> [copies]: the studio's reference list, in order"
        );
        add_varargs_method(
            "studioOf",
            &Module::pyStudioOf,
            "studioOf(copy) -> the Variable Studio whose reference list holds the copy, or None"
        );
        add_varargs_method("nextLabel", &Module::pyNextLabel, "nextLabel(doc, base) -> '<base> N'");
        add_varargs_method(
            "members",
            &Module::pyMembers,
            "members(doc, name) -> what a delete removes"
        );
        add_varargs_method(
            "dependents",
            &Module::pyDependents,
            "dependents(doc, name) -> objects outside the tab using it"
        );
        add_varargs_method("removeTab", &Module::pyRemoveTab, "removeTab(doc, name)");
        add_varargs_method(
            "duplicateRefusal",
            &Module::pyDuplicateRefusal,
            "duplicateRefusal(doc, name) -> why the tab can't be duplicated, '' when it can"
        );
        add_varargs_method(
            "duplicateLabel",
            &Module::pyDuplicateLabel,
            "duplicateLabel(doc, name) -> the label a copy gets, '<label> (N)'"
        );
        add_varargs_method(
            "duplicate",
            &Module::pyDuplicate,
            "duplicate(doc, name) -> the copy's tab name: a copy right of it, not linked to it\n"
            "(in the caller's transaction); RuntimeError with the refusal"
        );
        add_varargs_method(
            "exportObjects",
            &Module::pyExportObjects,
            "exportObjects(doc, name) -> what Export writes: a studio's visible parts, an\n"
            "assembly"
        );
        add_varargs_method(
            "exportTab",
            &Module::pyExportTab,
            "exportTab(doc, name, path, module='Import'): the tab to STEP through\n"
            "module.export"
        );
        add_varargs_method(
            "metaKey",
            &Module::pyMetaKey,
            "metaKey() -> the Meta key of the registry"
        );
        initialize("Onshape's typed tabs of a document (FreeCAD-CH)");
    }

private:
    Py::Object pyTabs(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pyDoc)) {
            throw Py::Exception();
        }
        Document* doc = documentArg(pyDoc);
        Py::List list;
        for (const auto& tab : tabs(doc)) {
            Py::Tuple item(3);
            item.setItem(0, Py::String(tab.name()));
            item.setItem(1, Py::String(kindName(tab.kind)));
            item.setItem(2, Py::String(label(doc, tab)));
            list.append(item);
        }
        return list;
    }
    Py::Object pyTabOf(const Py::Tuple& args)
    {
        PyObject* pyObj = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pyObj)) {
            throw Py::Exception();
        }
        return Py::String(tabNameOf(objectArg(pyObj)));
    }
    Py::Object pyHasImplicit(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pyDoc)) {
            throw Py::Exception();
        }
        return Py::Boolean(hasImplicitStudio(documentArg(pyDoc)));
    }
    Py::Object pyLabel(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &name)) {
            throw Py::Exception();
        }
        Document* doc = documentArg(pyDoc);
        return Py::String(label(doc, tabArg(doc, name)));
    }
    Py::Object pySetImplicitLabel(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* text = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &text)) {
            throw Py::Exception();
        }
        setImplicitLabel(documentArg(pyDoc), text);
        return Py::None();
    }
    Py::Object pyOrder(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pyDoc)) {
            throw Py::Exception();
        }
        Py::List list;
        for (const auto& name : order(documentArg(pyDoc))) {
            list.append(Py::String(name));
        }
        return list;
    }
    Py::Object pySetOrder(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        PyObject* pyNames = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pyDoc, &pyNames)) {
            throw Py::Exception();
        }
        std::vector<std::string> names;
        Py::Sequence sequence(pyNames);
        for (const auto& item : sequence) {
            names.push_back(Py::String(item).as_std_string("utf-8"));
        }
        setOrder(documentArg(pyDoc), names);
        return Py::None();
    }
    Py::Object pyPlaceAfter(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        const char* after = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Oss", &pyDoc, &name, &after)) {
            throw Py::Exception();
        }
        placeAfter(documentArg(pyDoc), name, after);
        return Py::None();
    }
    Py::Object pyIsVariableStudio(const Py::Tuple& args)
    {
        PyObject* pyObj = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pyObj)) {
            throw Py::Exception();
        }
        return Py::Boolean(isVariableStudio(objectArg(pyObj)));
    }
    Py::Object pySetVariableStudio(const Py::Tuple& args)
    {
        PyObject* pyObj = nullptr;
        PyObject* marked = Py_True;
        if (!PyArg_ParseTuple(args.ptr(), "O|O!", &pyObj, &PyBool_Type, &marked)) {
            throw Py::Exception();
        }
        try {
            setVariableStudio(objectArg(pyObj), marked == Py_True);
        }
        catch (const Base::Exception& e) {
            throw Py::TypeError(e.what());
        }
        return Py::None();
    }
    Py::Object pyVariableReferences(const Py::Tuple& args)
    {
        PyObject* pyObj = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pyObj)) {
            throw Py::Exception();
        }
        return objectList(variableReferences(objectArg(pyObj)));
    }
    Py::Object pyStudioOf(const Py::Tuple& args)
    {
        PyObject* pyObj = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pyObj)) {
            throw Py::Exception();
        }
        DocumentObject* studio = studioOf(objectArg(pyObj));
        if (!studio) {
            return Py::None();
        }
        return Py::asObject(studio->getPyObject());
    }
    Py::Object pyNextLabel(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* base = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &base)) {
            throw Py::Exception();
        }
        return Py::String(nextLabel(documentArg(pyDoc), base));
    }
    Py::Object pyMembers(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &name)) {
            throw Py::Exception();
        }
        Document* doc = documentArg(pyDoc);
        return objectList(members(doc, tabArg(doc, name)));
    }
    Py::Object pyDependents(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &name)) {
            throw Py::Exception();
        }
        Document* doc = documentArg(pyDoc);
        return objectList(dependents(doc, tabArg(doc, name)));
    }
    Py::Object pyRemoveTab(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &name)) {
            throw Py::Exception();
        }
        Document* doc = documentArg(pyDoc);
        removeTab(doc, tabArg(doc, name));
        return Py::None();
    }
    Py::Object pyDuplicateRefusal(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &name)) {
            throw Py::Exception();
        }
        Document* doc = documentArg(pyDoc);
        return Py::String(duplicateRefusal(doc, tabArg(doc, name)));
    }
    Py::Object pyDuplicateLabel(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &name)) {
            throw Py::Exception();
        }
        Document* doc = documentArg(pyDoc);
        return Py::String(duplicateLabel(doc, tabArg(doc, name)));
    }
    Py::Object pyDuplicate(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &name)) {
            throw Py::Exception();
        }
        Document* doc = documentArg(pyDoc);
        const Tab tab = tabArg(doc, name);
        try {
            return Py::String(duplicate(doc, tab)->getNameInDocument());
        }
        catch (const Base::Exception& e) {
            throw Py::RuntimeError(e.what());
        }
    }
    Py::Object pyExportObjects(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &name)) {
            throw Py::Exception();
        }
        Document* doc = documentArg(pyDoc);
        return objectList(exportObjects(doc, tabArg(doc, name)));
    }
    Py::Object pyExportTab(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        char* path = nullptr;
        const char* module = "Import";
        if (!PyArg_ParseTuple(args.ptr(), "Oset|s", &pyDoc, &name, "utf-8", &path, &module)) {
            throw Py::Exception();
        }
        const std::string file(path);
        PyMem_Free(path);
        Document* doc = documentArg(pyDoc);
        try {
            exportTab(doc, tabArg(doc, name), file, module);
        }
        catch (const Base::Exception& e) {
            throw Py::RuntimeError(e.what());
        }
        return Py::None();
    }
    Py::Object pyMetaKey(const Py::Tuple& /*args*/)
    {
        return Py::String(metaKey());
    }
};

}  // namespace

PyObject* DocumentTabs::initModule()
{
    return Base::Interpreter().addModule(new Module);
}
