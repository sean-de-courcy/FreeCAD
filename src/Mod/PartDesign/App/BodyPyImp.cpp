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


#include "Mod/PartDesign/App/Body.h"
#include "Mod/PartDesign/App/Feature.h"

// inclusion of the generated files (generated out of ItemPy.xml)
#include "BodyPy.h"
#include "BodyPy.cpp"

using namespace PartDesign;

// returns a string which represents the object e.g. when printed in python
std::string BodyPy::representation() const
{
    return {"<body object>"};
}


PyObject* BodyPy::getCustomAttributes(const char* /*attr*/) const
{
    return nullptr;
}

int BodyPy::setCustomAttributes(const char* /*attr*/, PyObject* /*obj*/)
{
    return 0;
}

PyObject* BodyPy::insertObject(PyObject* args)
{
    PyObject* featurePy;
    PyObject* targetPy;
    PyObject* afterPy = Py_False;
    if (!PyArg_ParseTuple(
            args,
            "O!O|O!",
            &(App::DocumentObjectPy::Type),
            &featurePy,
            &targetPy,
            &PyBool_Type,
            &afterPy
        )) {
        return nullptr;
    }

    App::DocumentObject* feature
        = static_cast<App::DocumentObjectPy*>(featurePy)->getDocumentObjectPtr();
    App::DocumentObject* target = nullptr;
    if (PyObject_TypeCheck(targetPy, &(App::DocumentObjectPy::Type))) {
        target = static_cast<App::DocumentObjectPy*>(targetPy)->getDocumentObjectPtr();
    }

    if (!Body::isAllowed(feature)) {
        PyErr_SetString(
            PyExc_SystemError,
            "Only PartDesign features, datum features and sketches can be inserted into a Body"
        );
        return nullptr;
    }

    bool after = Base::asBoolean(afterPy);
    Body* body = this->getBodyPtr();

    try {
        body->insertObject(feature, target, after);
    }
    catch (Base::Exception& e) {
        PyErr_SetString(PyExc_SystemError, e.what());
        return nullptr;
    }

    Py_Return;
}

namespace
{
/// The document object of a Python argument, or null for None; throws for anything else
App::DocumentObject* objectOrNone(PyObject* arg)
{
    if (arg == Py_None) {
        return nullptr;
    }
    if (PyObject_TypeCheck(arg, &(App::DocumentObjectPy::Type))) {
        return static_cast<App::DocumentObjectPy*>(arg)->getDocumentObjectPtr();
    }
    throw Base::TypeError("Expected a document object or None");
}
}  // namespace

PyObject* BodyPy::rollTo(PyObject* args)
{
    PyObject* featurePy;
    if (!PyArg_ParseTuple(args, "O", &featurePy)) {
        return nullptr;
    }
    PY_TRY
    {
        getBodyPtr()->rollTo(objectOrNone(featurePy));
        Py_Return;
    }
    PY_CATCH
}

PyObject* BodyPy::rollToEnd(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    PY_TRY
    {
        getBodyPtr()->rollToEnd();
        Py_Return;
    }
    PY_CATCH
}

PyObject* BodyPy::isRolledBack(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    return Py::new_reference_to(Py::Boolean(getBodyPtr()->isRolledBack()));
}

PyObject* BodyPy::holds(PyObject* args)
{
    PyObject* objPy;
    if (!PyArg_ParseTuple(args, "O!", &(App::DocumentObjectPy::Type), &objPy)) {
        return nullptr;
    }
    auto obj = static_cast<App::DocumentObjectPy*>(objPy)->getDocumentObjectPtr();
    return Py::new_reference_to(Py::Boolean(getBodyPtr()->holds(obj)));
}

PyObject* BodyPy::setEditRollPoint(PyObject* args)
{
    PyObject* featurePy;
    if (!PyArg_ParseTuple(args, "O", &featurePy)) {
        return nullptr;
    }
    PY_TRY
    {
        auto feature = objectOrNone(featurePy);
        if (feature && !getBodyPtr()->hasObject(feature)) {
            throw Base::ValueError("The edit roll-back point must be a member of this body");
        }
        getBodyPtr()->setEditRollPoint(feature);
        Py_Return;
    }
    PY_CATCH
}

PyObject* BodyPy::reorderObject(PyObject* args)
{
    PyObject* objectsPy;
    PyObject* targetPy;
    PyObject* afterPy = Py_True;
    if (!PyArg_ParseTuple(args, "OO|O!", &objectsPy, &targetPy, &PyBool_Type, &afterPy)) {
        return nullptr;
    }
    PY_TRY
    {
        std::vector<App::DocumentObject*> objects;
        if (PyObject_TypeCheck(objectsPy, &(App::DocumentObjectPy::Type))) {
            objects.push_back(
                static_cast<App::DocumentObjectPy*>(objectsPy)->getDocumentObjectPtr()
            );
        }
        else {
            Py::Sequence sequence(objectsPy);
            for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
                PyObject* item = (*it).ptr();
                if (!PyObject_TypeCheck(item, &(App::DocumentObjectPy::Type))) {
                    throw Base::TypeError("Expected a document object or a sequence of them");
                }
                objects.push_back(
                    static_cast<App::DocumentObjectPy*>(item)->getDocumentObjectPtr()
                );
            }
        }
        getBodyPtr()->reorderObject(objects, objectOrNone(targetPy), Base::asBoolean(afterPy));
        Py_Return;
    }
    PY_CATCH
}

Py::Object BodyPy::getVisibleFeature() const
{
    for (auto obj : getBodyPtr()->Group.getValues()) {
        if (obj->Visibility.getValue() && obj->isDerivedFrom<PartDesign::Feature>()) {
            return Py::Object(obj->getPyObject(), true);
        }
    }
    return Py::Object();
}
