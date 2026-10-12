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
            "studioOriginFeature",
            &Module::studioOriginFeature,
            "studioOriginFeature(owner, feature) -- owner's own origin feature standing for "
            "feature, an origin feature of another Body of the studio, or None."
        );
        initialize("This module is the PartDesign module.");  // register with Python
    }

private:
    static App::DocumentObject* objectArg(PyObject* obj)
    {
        return static_cast<App::DocumentObjectPy*>(obj)->getDocumentObjectPtr();
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
