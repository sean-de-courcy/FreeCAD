/***************************************************************************
 *   Copyright (c) 2008 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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
 **************************************************************************/


#include <Base/Interpreter.h>
#include <Base/PlacementPy.h>
#include <Base/VectorPy.h>
#include <Base/GeometryPyCXX.h>
#include <App/DocumentObjectPy.h>

#include <optional>
#include <string>
#include <vector>

// inclusion of the generated files (generated out of ViewProviderAssemblyPy.xml)
#include "ViewProviderAssemblyPy.h"
#include "ViewProviderAssemblyPy.cpp"


using namespace Gui;

// returns a string which represents the object e.g. when printed in python
std::string ViewProviderAssemblyPy::representation() const
{
    std::stringstream str;
    str << "<Assembly View provider object at " << getViewProviderAssemblyPtr() << ">";

    return str.str();
}

PyObject* ViewProviderAssemblyPy::isInEditMode(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }

    Py::Boolean val(getViewProviderAssemblyPtr()->isInEditMode());
    return Py::new_reference_to(val);
}

Py::Boolean ViewProviderAssemblyPy::getEnableMovement() const
{
    return {getViewProviderAssemblyPtr()->getEnableMovement()};
}

void ViewProviderAssemblyPy::setEnableMovement(Py::Boolean arg)
{
    getViewProviderAssemblyPtr()->setEnableMovement(arg);
}

Py::Boolean ViewProviderAssemblyPy::getMoveOnlyPreselected() const
{
    return {getViewProviderAssemblyPtr()->getMoveOnlyPreselected()};
}

void ViewProviderAssemblyPy::setMoveOnlyPreselected(Py::Boolean arg)
{
    getViewProviderAssemblyPtr()->setMoveOnlyPreselected(arg);
}

Py::Boolean ViewProviderAssemblyPy::getMoveInCommand() const
{
    return {getViewProviderAssemblyPtr()->getMoveInCommand()};
}

void ViewProviderAssemblyPy::setMoveInCommand(Py::Boolean arg)
{
    getViewProviderAssemblyPtr()->setMoveInCommand(arg);
}

Py::Boolean ViewProviderAssemblyPy::getDraggerVisibility() const
{
    return {getViewProviderAssemblyPtr()->getDraggerVisibility()};
}

void ViewProviderAssemblyPy::setDraggerVisibility(Py::Boolean arg)
{
    getViewProviderAssemblyPtr()->setDraggerVisibility(arg);
}

PyObject* ViewProviderAssemblyPy::getDragger(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    Gui::SoTransformDragger* asmDragger = getViewProviderAssemblyPtr()->getDragger();

    return Base::Interpreter().createSWIGPointerObj("pivy.coin", "SoDragger *", asmDragger, 0);
}


Py::Object ViewProviderAssemblyPy::getDraggerPlacement() const
{
    return Py::Placement(getViewProviderAssemblyPtr()->getDraggerPlacement());
}

void ViewProviderAssemblyPy::setDraggerPlacement(Py::Object arg)
{
    PyObject* p = arg.ptr();
    if (PyObject_TypeCheck(p, &(Base::PlacementPy::Type))) {
        Base::Placement* trf = static_cast<Base::PlacementPy*>(p)->getPlacementPtr();
        getViewProviderAssemblyPtr()->setDraggerPlacement(*trf);
    }
    else {
        std::string error = std::string("type must be 'Placement', not ");
        error += p->ob_type->tp_name;
        throw Py::TypeError(error);
    }
}

// FreeCAD-CH (ops#640, C8): the triad's typed moves
namespace
{
using Handle = AssemblyGui::ViewProviderAssembly::TriadHandle;
const std::vector<std::pair<Handle, const char*>>& triadHandleNames()
{
    static const std::vector<std::pair<Handle, const char*>> names {
        {Handle::None, "None"},
        {Handle::TranslateX, "TranslateX"},
        {Handle::TranslateY, "TranslateY"},
        {Handle::TranslateZ, "TranslateZ"},
        {Handle::RotateX, "RotateX"},
        {Handle::RotateY, "RotateY"},
        {Handle::RotateZ, "RotateZ"},
        {Handle::Plane, "Plane"},
    };
    return names;
}
}  // namespace

PyObject* ViewProviderAssemblyPy::getTriadHandle(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    Handle h = getViewProviderAssemblyPtr()->getTriadHandle();
    for (const auto& [handle, name] : triadHandleNames()) {
        if (handle == h) {
            return Py::new_reference_to(Py::String(name));
        }
    }
    return Py::new_reference_to(Py::String("None"));
}

PyObject* ViewProviderAssemblyPy::getTriadValue(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    return Py::new_reference_to(Py::Float(getViewProviderAssemblyPtr()->getTriadValue()));
}

PyObject* ViewProviderAssemblyPy::getTriadPlacement(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    return Py::new_reference_to(Py::Placement(getViewProviderAssemblyPtr()->getTriadPlacement()));
}

PyObject* ViewProviderAssemblyPy::applyTriadValue(PyObject* args)
{
    const char* text = nullptr;
    if (!PyArg_ParseTuple(args, "s", &text)) {
        return nullptr;
    }
    bool ok = getViewProviderAssemblyPtr()->applyTriadValue(text);
    return Py::new_reference_to(Py::Boolean(ok));
}

PyObject* ViewProviderAssemblyPy::isTriadBoxOpen(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    return Py::new_reference_to(Py::Boolean(getViewProviderAssemblyPtr()->isTriadBoxOpen()));
}

PyObject* ViewProviderAssemblyPy::closeTriadBox(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }
    getViewProviderAssemblyPtr()->closeTriadBox();
    Py_Return;
}

PyObject* ViewProviderAssemblyPy::dragTriad(PyObject* args)
{
    const char* name = nullptr;
    PyObject* plc = nullptr;
    if (!PyArg_ParseTuple(args, "sO!", &name, &(Base::PlacementPy::Type), &plc)) {
        return nullptr;
    }
    std::optional<Handle> handle;
    for (const auto& [h, n] : triadHandleNames()) {
        if (std::string(n) == name) {
            handle = h;
        }
    }
    if (!handle) {
        PyErr_Format(PyExc_ValueError, "unknown triad handle '%s'", name);
        return nullptr;
    }
    auto* vp = getViewProviderAssemblyPtr();
    if (!vp->getDraggerVisibility()) {
        PyErr_SetString(PyExc_RuntimeError, "the triad is not shown");
        return nullptr;
    }
    vp->beginTriadDrag(*handle);
    vp->moveTriadTo(*static_cast<Base::PlacementPy*>(plc)->getPlacementPtr());
    vp->endTriadDrag();
    Py_Return;
}

PyObject* ViewProviderAssemblyPy::moveTriadOriginTo(PyObject* args)
{
    PyObject* pnt = nullptr;
    const char* subName = nullptr;
    if (!PyArg_ParseTuple(args, "O!|s", &(Base::VectorPy::Type), &pnt, &subName)) {
        return nullptr;
    }
    auto* vp = getViewProviderAssemblyPtr();
    if (!vp->getDraggerVisibility()) {
        PyErr_SetString(PyExc_RuntimeError, "the triad is not shown");
        return nullptr;
    }
    Base::Vector3d point = *static_cast<Base::VectorPy*>(pnt)->getVectorPtr();
    if (subName && *subName) {
        point = vp->triadOriginPick(vp->getObject(), subName, point);
    }
    vp->moveTriadOriginTo(point);
    Py_Return;
}

PyObject* ViewProviderAssemblyPy::getCustomAttributes(const char* /*attr*/) const
{
    return nullptr;
}

int ViewProviderAssemblyPy::setCustomAttributes(const char* /*attr*/, PyObject* /*obj*/)
{
    return 0;
}

PyObject* ViewProviderAssemblyPy::isolateComponents(PyObject* args)
{
    PyObject* pyList = nullptr;
    int modeInt = 0;
    if (!PyArg_ParseTuple(args, "Oi", &pyList, &modeInt)) {
        return nullptr;
    }

    if (!PySequence_Check(pyList)) {
        PyErr_SetString(PyExc_TypeError, "First argument must be a sequence of DocumentObjects");
        return nullptr;
    }

    if (modeInt < 0 || modeInt > 2) {
        PyErr_SetString(PyExc_ValueError, "Mode must be an integer between 0 and 2");
        return nullptr;
    }

    std::set<App::DocumentObject*> partsSet;
    Py_ssize_t size = PySequence_Size(pyList);
    for (Py_ssize_t i = 0; i < size; ++i) {
        PyObject* item = PySequence_GetItem(pyList, i);
        if (item && PyObject_TypeCheck(item, &(App::DocumentObjectPy::Type))) {
            auto* pyObj = static_cast<App::DocumentObjectPy*>(item);
            App::DocumentObject* docObj = pyObj->getDocumentObjectPtr();
            if (docObj) {
                partsSet.insert(docObj);
            }
        }
        Py_XDECREF(item);
    }

    auto mode = static_cast<ViewProviderAssembly::IsolateMode>(modeInt);
    getViewProviderAssemblyPtr()->isolateComponents(partsSet, mode);

    Py_DECREF(Py_None);
    return Py_None;
}

PyObject* ViewProviderAssemblyPy::clearIsolate(PyObject* args)
{
    if (!PyArg_ParseTuple(args, "")) {
        return nullptr;
    }

    getViewProviderAssemblyPtr()->clearIsolate();
    return Py::new_reference_to(Py::None());
}
