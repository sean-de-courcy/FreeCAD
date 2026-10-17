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
#include <App/DocumentObjectPy.h>
#include <App/Part.h>
#include <Base/GeometryPyCXX.h>
#include <Base/Interpreter.h>
#include <Base/VectorPy.h>
#include <Base/Tools.h>
#include <Mod/Part/App/BodyBase.h>

#include "Body.h"
#include "FeatureSketchBased.h"


namespace PartDesign
{
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
            "newPartFrom(feature) -- Moves feature, its Body's Tip that nothing else uses, and its "
            "Profile sketch if nothing else uses it, into a new Body placed as the old one, in the "
            "same container. Returns the new Body; no recompute."
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
            "studioOriginFeature",
            &Module::studioOriginFeature,
            "studioOriginFeature(owner, feature) -- owner's own origin feature standing for "
            "feature, an origin feature of another Body of the studio, or None."
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

    Py::Object makeSiblings(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "O!O", &(App::DocumentObjectPy::Type), &pObj, &pBodies)) {
            throw Py::Exception();
        }
        FeatureAddSub* feature = addSubArg(pObj);
        std::vector<App::DocumentObject*> bodies;
        Py::Sequence sequence(pBodies);
        for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
            PyObject* item = (*it).ptr();
            if (!PyObject_TypeCheck(item, &(App::DocumentObjectPy::Type))) {
                PyErr_SetString(PyExc_TypeError, "Expected a sequence of bodies");
                throw Py::Exception();
            }
            bodies.push_back(objectArg(item));
        }
        try {
            return objectList(FeatureAddSub::makeSiblings(feature, bodies));
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
