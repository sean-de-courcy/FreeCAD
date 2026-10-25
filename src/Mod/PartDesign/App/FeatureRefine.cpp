// SPDX-License-Identifier: LGPL-2.1-or-later
/****************************************************************************
 *                                                                          *
 *   Copyright (c) 2024 <bgbsww@gmail.com>                                  *
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 *   FreeCAD is distributed in the hope that it will be useful, but         *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
 *   Lesser General Public License for more details.                        *
 *                                                                          *
 *   You should have received a copy of the GNU Lesser General Public       *
 *   License along with FreeCAD. If not, see                                *
 *   <https://www.gnu.org/licenses/>.                                       *
 *                                                                          *
 ***************************************************************************/

#include <BRepAdaptor_Surface.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <Standard_Failure.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>

#include <App/Application.h>
#include <App/Document.h>
#include <App/FeaturePythonPyImp.h>
#include <Base/Exception.h>
#include <Base/Parameter.h>
#include <Mod/Part/App/modelRefine.h>

#include "FeatureRefine.h"
#include "FeaturePy.h"


using namespace PartDesign;

namespace PartDesign
{
PROPERTY_SOURCE(PartDesign::FeatureRefine, PartDesign::Feature)
const App::PropertyFloatConstraint::Constraints floatFuzzy = {-1.0, 1.0, 0.0001};

FeatureRefine::FeatureRefine()
{
    ADD_PROPERTY_TYPE(
        Refine,
        (false),
        "Part Design",
        (App::PropertyType)(App::Prop_None),
        "Refine shape (clean up redundant edges) after operations"
    );
    ADD_PROPERTY_TYPE(
        FuzzyTolerance,
        (0.0),
        "Part Design",
        (App::PropertyType)(App::Prop_None),
        "Fuzzy tolerance:\n"
        "If value > 0: use the value\n"
        "If value = 0: leave default value\n"
        "If value < 0: determine value"
    );
    FuzzyTolerance.setConstraints(&floatFuzzy);


    // init Refine property
    Base::Reference<ParameterGrp> hGrp = App::GetApplication()
                                             .GetUserParameter()
                                             .GetGroup("BaseApp")
                                             ->GetGroup("Preferences")
                                             ->GetGroup("Mod/PartDesign");
    this->Refine.setValue(hGrp->GetBool("RefineModel", true));
}

bool FeatureRefine::onlyHaveRefined()
{
    if (!Refine.isTouched()) {
        return false;
    }
    if (rawShape.isNull()) {
        return false;
    }
    std::vector<App::Property*> propList;
    getPropertyList(propList);
    for (auto prop : propList) {
        if (prop != &Refine
            /*&& prop != &SuppressedShape*/
            && prop->isTouched()) {
            return false;
        }
    }
    TopoShape result = refineShapeIfActive(rawShape);
    Shape.setValue(result);
    return true;
}

bool FeatureRefine::freeFormFacesValid(const TopoShape& shape)
{
    for (TopExp_Explorer it(shape.getShape(), TopAbs_FACE); it.More(); it.Next()) {
        const auto& face = TopoDS::Face(it.Current());
        switch (BRepAdaptor_Surface(face, false).GetType()) {
            case GeomAbs_Plane:
            case GeomAbs_Cylinder:
            case GeomAbs_Cone:
            case GeomAbs_Sphere:
            case GeomAbs_Torus:
                continue;
            default:
                if (!BRepCheck_Analyzer(face).IsValid()) {
                    return false;
                }
        }
    }
    return true;
}

TopoShape FeatureRefine::refineShapeIfActive(
    const TopoShape& oldShape,
    const RefineErrorPolicy onError
) const
{
    if (!this->Refine.getValue()) {
        return oldShape;
    }
    TopoShape shape(oldShape);
    try {
        TopoShape refinedShape = shape.makeElementRefine();
        // Only a refine that merges faces has its result checked here: the check reads the whole
        // shape (BRepCheck_Analyzer), about a third of a 40-feature body's recompute when it ran
        // after every refine (ops#389).
        const bool merged = refinedShape.countSubShapes(TopAbs_FACE)
            != oldShape.countSubShapes(TopAbs_FACE);
        if (!merged) {
            // A refine that merges no face still rebuilds its faces (nearly always all of them), and
            // a rebuilt free-form face can come out invalid (a degenerate ellipsoid's B-spline face,
            // ops#474). Those faces are checked; if one is invalid, the next feature checks this
            // result instead of vouching for it (ops#310). Elementary faces (planes, cylinders,
            // ...) are not checked, so a refined Pocket chain costs nothing more
            if (booleanInputsValid && !freeFormFacesValid(refinedShape)) {
                booleanInputsValid = false;
            }
            return refinedShape;
        }
        if (refinedShape.isValid()) {
            return refinedShape;
        }
        if (!oldShape.isValid()) {
            booleanInputsValid = false;
            return refinedShape;
        }
        if (onError == RefineErrorPolicy::Raise) {
            throw Base::RuntimeError("Refine produced an invalid shape");
        }
        // A warning on the feature (ops#389), which the recompute also reports: it computes, but
        // its result is unrefined although Refine is on.
        const std::string text = "Refine produced an invalid shape; the unrefined shape is kept";
        if (auto doc = getDocument()) {
            // once, although a feature may refine more than once in one execute
            const std::string previous = doc->getWarningDescription(this)
                ? doc->getWarningDescription(this)
                : "";
            if (previous.find(text) == std::string::npos) {
                doc->setWarning(
                    const_cast<FeatureRefine*>(this),
                    previous.empty() ? text : previous + "\n" + text
                );
            }
        }
        return oldShape;
    }
    catch (Standard_Failure& err) {
        if (onError == RefineErrorPolicy::Warn) {
            Base::Console().warning(fmt::format("Refine failed: {}", err.GetMessageString()).c_str());
        }
        else {
            throw;
        }
    }
    return oldShape;
}

}  // namespace PartDesign


namespace App
{
/// @cond DOXERR
PROPERTY_SOURCE_TEMPLATE(PartDesign::FeatureRefinePython, PartDesign::FeatureRefine)
template<>
const char* PartDesign::FeatureRefinePython::getViewProviderName() const
{
    return "PartDesignGui::ViewProviderPython";
}
template<>
PyObject* PartDesign::FeatureRefinePython::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new FeaturePythonPyT<PartDesign::FeaturePy>(this), true);
    }
    return Py::new_reference_to(PythonObject);
}
/// @endcond

// explicit template instantiation
template class PartDesignExport FeaturePythonT<PartDesign::FeatureRefine>;
}  // namespace App
