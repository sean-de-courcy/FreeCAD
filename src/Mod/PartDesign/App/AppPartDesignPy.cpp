// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2008 Jürgen Riegel <juergen.riegel@web.de>              *
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


#include <App/Document.h>
#include <App/DocumentPy.h>
#include <App/DocumentObjectPy.h>
#include <App/Part.h>
#include <Base/GeometryPyCXX.h>
#include <Base/Interpreter.h>
#include <Base/VectorPy.h>
#include <Base/Tools.h>
#include <Mod/Part/App/BodyBase.h>

#include "Body.h"
#include "Derived.h"
#include "FeatureBase.h"
#include "FeatureBoolean.h"
#include "FeatureDeletePart.h"
#include "FeatureSketchBased.h"
#include "FeatureSplit.h"
#include "Studio.h"


namespace PartDesign
{
// FreeCAD-CH (ops#640 round 5): Body.cpp's New part rule (no header names it)
PartDesignExport std::string newPartRefusal(const App::DocumentObject* feature, bool ignoreMerge);

class Module: public Py::ExtensionModule<Module>
{
public:
    Module()
        : Py::ExtensionModule<Module>("_PartDesign")
    {
        add_varargs_method("makeFilletArc", &Module::makeFilletArc, "makeFilletArc(...) -- Fillet arc.");
        add_varargs_method(
            "studioOf",
            &Module::studioOf,
            "studioOf(obj) -- The studio of obj's Body: its App::Part, the document at the top "
            "level, or None (no Body, or a Body placed directly in an Assembly)."
        );
        add_varargs_method(
            "isStudioPick",
            &Module::isStudioPick,
            "isStudioPick(owner, obj, subname='') -- Whether owner may link the pick obj/subname "
            "directly: one Body, or two Bodies of one studio, and no App::Link on the path."
        );
        add_varargs_method(
            "isStudioProfile",
            &Module::isStudioProfile,
            "isStudioProfile(owner, obj, subname='') -- Whether the pick may be the Profile of "
            "owner (a profile feature, or the Body of a new one) across Bodies of one studio."
        );
        add_varargs_method(
            "newPartFrom",
            &Module::newPartFrom,
            "newPartFrom(feature) -- Moves feature, its Profile sketch if nothing that stays uses "
            "it, and the later features of its Body that work on its own material (in order), into "
            "a new Body placed as the old one, in the same container; its Merge goes first. The "
            "features that stay close their chain over it. Refused (newPartRefusal) when a feature "
            "can't be told apart. Returns the new Body; no recompute."
        );
        add_varargs_method(
            "newPartRefusal",
            &Module::newPartRefusal,
            "newPartRefusal(feature, ignoreMerge=False) -- Why newPartFrom(feature) would refuse, or "
            "'' when it is allowed. With ignoreMerge, the feature's Merge counts as gone."
        );
        add_varargs_method(
            "addToPart",
            &Module::addToPart,
            "addToPart(feature, body) -- newPartFrom the other way: moves feature, the only member "
            "of its Body besides its Profile sketch, into body, another part of its studio, where "
            "the studio's history has it, and removes the empty Body. Returns body; no recompute."
        );
        add_varargs_method(
            "addToPartRefusal",
            &Module::addToPartRefusal,
            "addToPartRefusal(feature, body) -- Why addToPart(feature, body) would refuse, or '' "
            "when it is allowed."
        );
        add_varargs_method(
            "deletePart",
            &Module::deletePart,
            "deletePart(body) -- Deletes the part body from its bar on, as Onshape's Delete part: a "
            "DeletePart feature at the bar, its Tip, whose shape is empty. Its features stay; "
            "rolling above it, or deleting it, brings the part back. Returns it; no recompute."
        );
        add_varargs_method(
            "makeSiblings",
            &Module::makeSiblings,
            "makeSiblings(feature, bodies) -- Makes the siblings of the subtractive feature the "
            "ones in bodies, other parts of its studio: one feature of its type per Body, on its "
            "profile, its parameters bound to it by expression and its links copied. Adds the "
            "missing ones, deletes the others, copies the links again. Returns them; no recompute."
        );
        add_varargs_method(
            "siblingsOf",
            &Module::siblingsOf,
            "siblingsOf(feature) -- The siblings that follow feature."
        );
        add_varargs_method(
            "unlinkSibling",
            &Module::unlinkSibling,
            "unlinkSibling(sibling) -- Makes the sibling independent: its expressions on its "
            "primary and its SiblingOf are cleared, its values stay."
        );
        add_varargs_method(
            "makeMerge",
            &Module::makeMerge,
            "makeMerge(at, bodies) -- Merges the bodies, other parts of the studio, into the part "
            "of at: a solid feature (the Merge goes right after it) or a Body (at its Tip). The "
            "Merge is a Fuse of their last solid features; each merged Body gets MergedInto and is "
            "hidden. Returns the Merge; no recompute."
        );
        add_varargs_method(
            "setMergeScope",
            &Module::setMergeScope,
            "setMergeScope(feature, bodies) -- The merge scope of the solid feature (Onshape's "
            "Extrude): bodies, other parts of the studio, are merged right after it, and the parts "
            "it merged that aren't in bodies are parts again. Changes the Merge after it in place, "
            "makes one, or with no bodies deletes it; the Merge is accepted. Returns the Merge or "
            "None; no recompute."
        );
        add_varargs_method(
            "mergeAfter",
            &Module::mergeAfter,
            "mergeAfter(feature) -- The Merge right after the solid feature, based on it, or None."
        );
        add_varargs_method(
            "consumerOf",
            &Module::consumerOf,
            "consumerOf(body) -- The Boolean that consumes the part body, one of its tools (Keep "
            "tools off, in effect, not a Merge, the tool not one a Union left separate), or None."
        );
        add_varargs_method(
            "split",
            &Module::split,
            "split(body, tool, side='Front') -- Splits the part body by the plane tool: an origin "
            "plane, a datum plane, or (feature, 'FaceN') for a planar face. A Split at its end "
            "keeps side (Front: where the plane's normal points, or Back); a new part placed as "
            "body gets the other side, from a Split that follows the first. Returns the new "
            "Body; no recompute."
        );
        add_varargs_method(
            "studioOriginFeature",
            &Module::studioOriginFeature,
            "studioOriginFeature(owner, feature) -- owner's own origin feature standing for "
            "feature, an origin feature of another Body of the studio, or None."
        );
        add_varargs_method(
            "studioSequence",
            &Module::studioSequence,
            "studioSequence(studio) -- The features of every Body of the studio (a document: its "
            "top level, or an App::Part) in history order: after what they read in other Bodies "
            "and after their Body's earlier members, the oldest first where that leaves a choice."
        );
        add_varargs_method(
            "rollStudioTo",
            &Module::rollStudioTo,
            "rollStudioTo(studio, feature) -- Moves the bar of every Body of the studio after its "
            "last solid feature at or above feature in studioSequence (None: to its top). No "
            "transaction, no recompute."
        );
        add_varargs_method(
            "rollStudioToEnd",
            &Module::rollStudioToEnd,
            "rollStudioToEnd(studio) -- Moves the bar of every Body of the studio to its end."
        );
        add_varargs_method(
            "isStudioRolledBack",
            &Module::isStudioRolledBack,
            "isStudioRolledBack(studio) -- Whether some Body of the studio is rolled back."
        );
        add_varargs_method(
            "studioBarAfter",
            &Module::studioBarAfter,
            "studioBarAfter(studio[, hint]) -- The feature of studioSequence the studio's bar "
            "follows (None: the top): the row before the first one that is held or waits below "
            "the bar (a sketch or datum after its Body's bar whose users are all held). hint, "
            "the feature (None: the top) the bar was last moved after, is kept when only "
            "sketches and datums lie between."
        );
        add_varargs_method(
            "moveInStudio",
            &Module::moveInStudio,
            "moveInStudio(studio, features, after[, bar]) -- Drags features (one, or several of "
            "one Body) to after the feature after (None: the top) in the studio's history and "
            "saves the order: inside their Body through reorderObject (the park), across Bodies "
            "refused where a read between Bodies would break. With the studio rolled back, the bar "
            "stays after bar (None: the top; default: the feature it follows). Returns whether "
            "anything changed. No transaction, no recompute."
        );
        // FreeCAD-CH (ops#640 round 6): Onshape's Derived inside one document (Derived.h)
        add_varargs_method(
            "derivedStudios",
            &Module::derivedStudios,
            "derivedStudios(doc) -- The studios of doc that hold a part to derive: the document "
            "(its top level, Part Studio 1) when it has one, then its App::Parts."
        );
        add_varargs_method(
            "studioLabel",
            &Module::studioLabel,
            "studioLabel(studio) -- A studio's name: an App::Part's Label, Part Studio 1 for a "
            "document (its top level)."
        );
        add_varargs_method(
            "derivableParts",
            &Module::derivableParts,
            "derivableParts(studio) -- The parts of the studio a Derived feature can bring in: its "
            "Bodies with a shape that no Delete part deleted."
        );
        add_varargs_method(
            "makeDerived",
            &Module::makeDerived,
            "makeDerived(studio, bodies) -- A Derived feature in the studio (a document: its top "
            "level) of bodies, parts of one other studio: per part a Body built on a binder of it. "
            "Returns the lead, whose row stands for the feature. No transaction, no recompute."
        );
        add_varargs_method(
            "editDerived",
            &Module::editDerived,
            "editDerived(lead, bodies) -- The Derived feature brings in bodies instead. Returns the "
            "lead after the edit. No transaction, no recompute."
        );
        add_varargs_method(
            "deleteDerivedParts",
            &Module::deleteDerivedParts,
            "deleteDerivedParts(lead) -- Removes what the Derived feature made besides lead: its "
            "other members, the binders, the Bodies left empty (lead's too: lead is then in no "
            "Body, for the caller to remove). No transaction, no recompute."
        );
        add_varargs_method(
            "derivedLead",
            &Module::derivedLead,
            "derivedLead(obj) -- The lead of obj's Derived feature, or None."
        );
        add_varargs_method(
            "derivedMembers",
            &Module::derivedMembers,
            "derivedMembers(lead) -- The members of the Derived feature, lead last."
        );
        add_varargs_method(
            "derivedSource",
            &Module::derivedSource,
            "derivedSource(member) -- The part a Derived feature's member copies, or None when it "
            "is missing."
        );
        initialize("This module is the PartDesign module.");  // register with Python
    }

private:
    // A deleted object, or one no longer in a document, raises ReferenceError
    static App::DocumentObject* objectArg(PyObject* obj)
    {
        auto pyObj = static_cast<App::DocumentObjectPy*>(obj);
        // PyObjectBase's isValid(): DocumentObjectPy hides it with the Python method
        App::DocumentObject* object =
            pyObj->Base::PyObjectBase::isValid() ? pyObj->getDocumentObjectPtr() : nullptr;
        if (!object || !object->isAttachedToDocument() || !object->getDocument()) {
            PyErr_SetString(PyExc_ReferenceError, "The object is deleted or not in a document");
            throw Py::Exception();
        }
        return object;
    }

    // FreeCAD-CH (ops#325): the studio predicates, for the tests and for scripts
    Py::Object studioOf(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        App::DocumentObject* obj = objectArg(pObj);
        App::Part* studio = nullptr;
        if (!Part::BodyBase::studioOf(Part::BodyBase::bodyOfObject(obj), studio)) {
            return Py::None();
        }
        if (studio) {
            return Py::asObject(studio->getPyObject());
        }
        return Py::asObject(obj->getDocument()->getPyObject());
    }

    Py::Object isStudioPick(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pObj;
        const char* subname = "";
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!|s",
                &(App::DocumentObjectPy::Type),
                &pOwner,
                &(App::DocumentObjectPy::Type),
                &pObj,
                &subname
            )) {
            throw Py::Exception();
        }
        return Py::Boolean(
            Part::BodyBase::isStudioPick(objectArg(pOwner), objectArg(pObj), subname)
        );
    }

    // FreeCAD-CH (ops#325 2a): New part
    Py::Object newPartFrom(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        try {
            return Py::asObject(Body::newPartFrom(objectArg(pObj))->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#640 round 5): newPartFrom's rule, for the dialog's rows and the tests
    Py::Object newPartRefusal(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pIgnore = Py_False;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!|O!",
                &(App::DocumentObjectPy::Type),
                &pObj,
                &PyBool_Type,
                &pIgnore
            )) {
            throw Py::Exception();
        }
        try {
            return Py::String(PartDesign::newPartRefusal(objectArg(pObj), pIgnore == Py_True));
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#640): Add to part, New part the other way
    Py::Object addToPart(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pBody;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!",
                &(App::DocumentObjectPy::Type),
                &pObj,
                &(App::DocumentObjectPy::Type),
                &pBody
            )) {
            throw Py::Exception();
        }
        auto body = freecad_cast<Body*>(objectArg(pBody));
        if (!body) {
            PyErr_SetString(PyExc_TypeError, "Expected a PartDesign Body");
            throw Py::Exception();
        }
        try {
            return Py::asObject(Body::addToPart(objectArg(pObj), body)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#640): addToPart's rule, for the dialog's rows and the tests
    Py::Object addToPartRefusal(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pBody;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!",
                &(App::DocumentObjectPy::Type),
                &pObj,
                &(App::DocumentObjectPy::Type),
                &pBody
            )) {
            throw Py::Exception();
        }
        auto body = freecad_cast<Body*>(objectArg(pBody));
        if (!body) {
            PyErr_SetString(PyExc_TypeError, "Expected a PartDesign Body");
            throw Py::Exception();
        }
        try {
            return Py::String(Body::addToPartRefusal(objectArg(pObj), body));
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#635): Delete part
    Py::Object deletePart(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        auto body = freecad_cast<Body*>(objectArg(pObj));
        if (!body) {
            PyErr_SetString(PyExc_TypeError, "Expected a PartDesign Body");
            throw Py::Exception();
        }
        try {
            return Py::asObject(DeletePart::deletePart(body)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#325 3a): one cut through several parts
    static FeatureAddSub* addSubArg(PyObject* obj)
    {
        auto feature = freecad_cast<FeatureAddSub*>(objectArg(obj));
        if (!feature) {
            PyErr_SetString(PyExc_TypeError, "Expected an additive or subtractive feature");
            throw Py::Exception();
        }
        return feature;
    }

    static Py::List objectList(const auto& objects)
    {
        Py::List list;
        for (auto obj : objects) {
            list.append(Py::asObject(obj->getPyObject()));
        }
        return list;
    }

    static std::vector<App::DocumentObject*> objectsArg(PyObject* objects)
    {
        std::vector<App::DocumentObject*> result;
        Py::Sequence sequence(objects);
        for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
            PyObject* item = (*it).ptr();
            if (!PyObject_TypeCheck(item, &(App::DocumentObjectPy::Type))) {
                PyErr_SetString(PyExc_TypeError, "Expected a sequence of bodies");
                throw Py::Exception();
            }
            result.push_back(objectArg(item));
        }
        return result;
    }

    Py::Object makeSiblings(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "O!O", &(App::DocumentObjectPy::Type), &pObj, &pBodies)) {
            throw Py::Exception();
        }
        FeatureAddSub* feature = addSubArg(pObj);
        std::vector<App::DocumentObject*> bodies = objectsArg(pBodies);
        try {
            return objectList(FeatureAddSub::makeSiblings(feature, bodies));
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#325 3b): Merge
    Py::Object makeMerge(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "O!O", &(App::DocumentObjectPy::Type), &pObj, &pBodies)) {
            throw Py::Exception();
        }
        App::DocumentObject* at = objectArg(pObj);
        std::vector<App::DocumentObject*> bodies = objectsArg(pBodies);
        try {
            return Py::asObject(Boolean::makeMerge(at, bodies)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#640 rank 1): the merge scope
    Py::Object setMergeScope(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "O!O", &(App::DocumentObjectPy::Type), &pObj, &pBodies)) {
            throw Py::Exception();
        }
        App::DocumentObject* feature = objectArg(pObj);
        std::vector<App::DocumentObject*> bodies = objectsArg(pBodies);
        try {
            Boolean* merge = Boolean::setMergeScope(feature, bodies);
            return merge ? Py::asObject(merge->getPyObject()) : Py::None();
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    Py::Object mergeAfter(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        Boolean* merge = Boolean::mergeAfter(objectArg(pObj));
        return merge ? Py::asObject(merge->getPyObject()) : Py::None();
    }

    // FreeCAD-CH (ops#640 rank 28): a part a Boolean consumed
    Py::Object consumerOf(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        Boolean* boolean = Boolean::consumerOf(objectArg(pObj));
        return boolean ? Py::asObject(boolean->getPyObject()) : Py::None();
    }

    // FreeCAD-CH (ops#325 4): Split
    Py::Object split(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pTool;
        const char* side = "Front";
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O|s",
                &(App::DocumentObjectPy::Type),
                &pObj,
                &pTool,
                &side
            )) {
            throw Py::Exception();
        }
        App::DocumentObject* body = objectArg(pObj);
        App::DocumentObject* tool = nullptr;
        std::vector<std::string> subs;
        if (PyObject_TypeCheck(pTool, &(App::DocumentObjectPy::Type))) {
            tool = objectArg(pTool);
        }
        else if (PyTuple_Check(pTool) && PyTuple_Size(pTool) == 2
                 && PyObject_TypeCheck(
                     PyTuple_GetItem(pTool, 0),
                     &(App::DocumentObjectPy::Type)
                 )) {
            tool = objectArg(PyTuple_GetItem(pTool, 0));
            Py::Object sub(PyTuple_GetItem(pTool, 1));
            if (sub.isString()) {
                subs.push_back(Py::String(sub).as_std_string());
            }
            else {
                Py::Sequence sequence(sub);
                for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
                    subs.push_back(Py::String(*it).as_std_string());
                }
            }
        }
        else {
            PyErr_SetString(PyExc_TypeError, "Expected a plane, or (feature, 'FaceN')");
            throw Py::Exception();
        }
        try {
            return Py::asObject(Split::makeSplit(body, tool, subs, side)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    Py::Object siblingsOf(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        return objectList(addSubArg(pObj)->getSiblings());
    }

    Py::Object unlinkSibling(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        addSubArg(pObj)->unlinkSibling();
        return Py::None();
    }

    Py::Object isStudioProfile(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pObj;
        const char* subname = "";
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!|s",
                &(App::DocumentObjectPy::Type),
                &pOwner,
                &(App::DocumentObjectPy::Type),
                &pObj,
                &subname
            )) {
            throw Py::Exception();
        }
        return Py::Boolean(
            ProfileBased::isStudioProfile(objectArg(pOwner), objectArg(pObj), subname)
        );
    }

    Py::Object studioOriginFeature(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pObj;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!",
                &(App::DocumentObjectPy::Type),
                &pOwner,
                &(App::DocumentObjectPy::Type),
                &pObj
            )) {
            throw Py::Exception();
        }
        auto feature = Part::BodyBase::studioOriginFeature(objectArg(pOwner), objectArg(pObj));
        if (!feature) {
            return Py::None();
        }
        return Py::asObject(feature->getPyObject());
    }

    // FreeCAD-CH (ops#602): the studio's feature list and bar. The studio is a document (its
    // top level) or an App::Part
    static void studioArg(PyObject* obj, App::Document*& doc, App::Part*& studio)
    {
        studio = nullptr;
        if (PyObject_TypeCheck(obj, &(App::DocumentPy::Type))) {
            doc = static_cast<App::DocumentPy*>(obj)->getDocumentPtr();
            if (!doc) {
                PyErr_SetString(PyExc_ReferenceError, "The document is closed");
                throw Py::Exception();
            }
            return;
        }
        if (PyObject_TypeCheck(obj, &(App::DocumentObjectPy::Type))) {
            studio = freecad_cast<App::Part*>(objectArg(obj));
            if (studio) {
                doc = studio->getDocument();
                return;
            }
        }
        PyErr_SetString(PyExc_TypeError, "Expected a document or an App::Part");
        throw Py::Exception();
    }

    Py::Object studioSequence(const Py::Tuple& args)
    {
        PyObject* pStudio;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pStudio)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        return objectList(PartDesign::studioSequence(doc, studio));
    }

    Py::Object rollStudioTo(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pStudio, &pObj)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        App::DocumentObject* member = nullptr;
        if (pObj != Py_None) {
            if (!PyObject_TypeCheck(pObj, &(App::DocumentObjectPy::Type))) {
                PyErr_SetString(PyExc_TypeError, "Expected a feature or None");
                throw Py::Exception();
            }
            member = objectArg(pObj);
        }
        try {
            PartDesign::rollStudioTo(doc, studio, member);
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
        return Py::None();
    }

    Py::Object rollStudioToEnd(const Py::Tuple& args)
    {
        PyObject* pStudio;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pStudio)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        PartDesign::rollStudioToEnd(doc, studio);
        return Py::None();
    }

    Py::Object isStudioRolledBack(const Py::Tuple& args)
    {
        PyObject* pStudio;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pStudio)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        return Py::Boolean(PartDesign::isStudioRolledBack(doc, studio));
    }

    Py::Object studioBarAfter(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pHint = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O|O", &pStudio, &pHint)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        App::DocumentObject* hint = nullptr;
        if (pHint && pHint != Py_None) {
            if (!PyObject_TypeCheck(pHint, &(App::DocumentObjectPy::Type))) {
                PyErr_SetString(PyExc_TypeError, "Expected a feature or None");
                throw Py::Exception();
            }
            hint = objectArg(pHint);
        }
        auto after =
            PartDesign::studioBarAfter(PartDesign::studioSequence(doc, studio), pHint != nullptr, hint);
        if (!after) {
            return Py::None();
        }
        return Py::asObject(after->getPyObject());
    }

    // A feature, None, or (with none) a missing argument
    static App::DocumentObject* featureOrNone(PyObject* obj)
    {
        if (!obj || obj == Py_None) {
            return nullptr;
        }
        if (!PyObject_TypeCheck(obj, &(App::DocumentObjectPy::Type))) {
            PyErr_SetString(PyExc_TypeError, "Expected a feature or None");
            throw Py::Exception();
        }
        return objectArg(obj);
    }

    Py::Object moveInStudio(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pRows;
        PyObject* pAfter;
        PyObject* pBar = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "OOO|O", &pStudio, &pRows, &pAfter, &pBar)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        std::vector<App::DocumentObject*> rows;
        if (PyObject_TypeCheck(pRows, &(App::DocumentObjectPy::Type))) {
            rows.push_back(objectArg(pRows));
        }
        else if (PySequence_Check(pRows)) {
            Py::Sequence sequence(pRows);
            for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
                if (!PyObject_TypeCheck((*it).ptr(), &(App::DocumentObjectPy::Type))) {
                    PyErr_SetString(PyExc_TypeError, "Expected a feature or a sequence of features");
                    throw Py::Exception();
                }
                rows.push_back(objectArg((*it).ptr()));
            }
        }
        else {
            PyErr_SetString(PyExc_TypeError, "Expected a feature or a sequence of features");
            throw Py::Exception();
        }
        App::DocumentObject* after = featureOrNone(pAfter);
        App::DocumentObject* bar = featureOrNone(pBar);
        try {
            return Py::Boolean(PartDesign::moveInStudio(doc, studio, rows, after, pBar != nullptr, bar));
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#640 round 6): Derived (Derived.h)
    static PyObject* studioObject(App::Document* doc, App::Part* studio)
    {
        return studio ? studio->getPyObject() : doc->getPyObject();
    }

    static PartDesign::FeatureBase* derivedArg(PyObject* obj)
    {
        auto lead = freecad_cast<PartDesign::FeatureBase*>(objectArg(obj));
        if (!lead || !PartDesign::isDerived(lead)) {
            PyErr_SetString(PyExc_TypeError, "Expected a Derived feature");
            throw Py::Exception();
        }
        return lead;
    }

    static std::vector<Body*> bodiesArg(PyObject* objects)
    {
        std::vector<Body*> bodies;
        for (auto obj : objectsArg(objects)) {
            auto body = freecad_cast<Body*>(obj);
            if (!body) {
                PyErr_SetString(PyExc_TypeError, "Expected a sequence of bodies");
                throw Py::Exception();
            }
            bodies.push_back(body);
        }
        return bodies;
    }

    Py::Object derivedStudios(const Py::Tuple& args)
    {
        PyObject* pDoc;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pDoc)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pDoc, doc, studio);
        Py::List list;
        for (auto part : PartDesign::derivedStudios(doc)) {
            list.append(Py::asObject(studioObject(doc, part)));
        }
        return list;
    }

    Py::Object studioLabel(const Py::Tuple& args)
    {
        PyObject* pStudio;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pStudio)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        return Py::String(PartDesign::studioLabel(studio));
    }

    Py::Object derivableParts(const Py::Tuple& args)
    {
        PyObject* pStudio;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pStudio)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        return objectList(PartDesign::derivableParts(doc, studio));
    }

    Py::Object makeDerived(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pStudio, &pBodies)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        std::vector<Body*> bodies = bodiesArg(pBodies);
        try {
            return Py::asObject(PartDesign::makeDerived(doc, studio, bodies)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    Py::Object editDerived(const Py::Tuple& args)
    {
        PyObject* pLead;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "O!O", &(App::DocumentObjectPy::Type), &pLead, &pBodies)) {
            throw Py::Exception();
        }
        PartDesign::FeatureBase* lead = derivedArg(pLead);
        std::vector<Body*> bodies = bodiesArg(pBodies);
        try {
            return Py::asObject(PartDesign::editDerived(lead, bodies)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    Py::Object deleteDerivedParts(const Py::Tuple& args)
    {
        PyObject* pLead;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pLead)) {
            throw Py::Exception();
        }
        PartDesign::deleteDerivedParts(derivedArg(pLead));
        return Py::None();
    }

    Py::Object derivedLead(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        auto lead = PartDesign::derivedLead(objectArg(pObj));
        if (!lead) {
            return Py::None();
        }
        return Py::asObject(lead->getPyObject());
    }

    Py::Object derivedMembers(const Py::Tuple& args)
    {
        PyObject* pLead;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pLead)) {
            throw Py::Exception();
        }
        return objectList(PartDesign::derivedMembers(derivedArg(pLead)));
    }

    Py::Object derivedSource(const Py::Tuple& args)
    {
        PyObject* pMember;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pMember)) {
            throw Py::Exception();
        }
        auto source = PartDesign::derivedSource(derivedArg(pMember));
        if (!source) {
            return Py::None();
        }
        return Py::asObject(source->getPyObject());
    }

    Py::Object makeFilletArc(const Py::Tuple& args)
    {
        PyObject* pM1;
        PyObject* pP;
        PyObject* pQ;
        PyObject* pN;
        double r2;
        int ccw;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!O!O!di",
                &(Base::VectorPy::Type),
                &pM1,
                &(Base::VectorPy::Type),
                &pP,
                &(Base::VectorPy::Type),
                &pQ,
                &(Base::VectorPy::Type),
                &pN,
                &r2,
                &ccw
            )) {
            throw Py::Exception();
        }

        Base::Vector3d M1 = Py::Vector(pM1, false).toVector();
        Base::Vector3d P = Py::Vector(pP, false).toVector();
        Base::Vector3d Q = Py::Vector(pQ, false).toVector();
        Base::Vector3d N = Py::Vector(pN, false).toVector();

        Base::Vector3d u = Q - P;
        Base::Vector3d v = P - M1;
        Base::Vector3d b;
        if (ccw) {
            b = u % N;
        }
        else {
            b = N % u;
        }
        b.Normalize();

        double uu = u * u;
        double uv = u * v;
        double r1 = v.Length();

        // distinguish between internal and external fillets
        r2 *= Base::sgn(uv);

        double cc = 2.0 * r2 * (b * v - r1);
        double d = uv * uv - uu * cc;
        if (d < 0) {
            throw Py::RuntimeError("Unable to calculate intersection points");
        }

        double t;
        double t1 = (-uv + sqrt(d)) / uu;
        double t2 = (-uv - sqrt(d)) / uu;

        if (fabs(t1) < fabs(t2)) {
            t = t1;
        }
        else {
            t = t2;
        }

        Base::Vector3d M2 = P + (u * t) + (b * r2);
        Base::Vector3d S1 = (r2 * M1 + r1 * M2) / (r1 + r2);
        Base::Vector3d S2 = M2 - (b * r2);

        Py::Tuple tuple(3);
        tuple.setItem(0, Py::Vector(S1));
        tuple.setItem(1, Py::Vector(S2));
        tuple.setItem(2, Py::Vector(M2));

        return tuple;
    }
};

PyObject* initModule()
{
    return Base::Interpreter().addModule(new Module);
}

}  // namespace PartDesign
