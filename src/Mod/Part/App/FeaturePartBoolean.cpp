// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2007 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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

#include <FCConfig.h>

#include <memory>

#include <Mod/Part/App/FCBRepAlgoAPI_BooleanOperation.h>
#include <BRepCheck_Analyzer.hxx>
#include <gp_Mat.hxx>
#include <gp_Trsf.hxx>
#include <Standard_Failure.hxx>
#include <TopLoc_Location.hxx>

#include <App/Application.h>
#include <Base/Exception.h>
#include <Base/Parameter.h>
#include <Base/ProgramVersion.h>

#include "FeaturePartBoolean.h"
#include "TopoShapeOpCode.h"
#include "modelRefine.h"


using namespace Part;

namespace Part
{
void throwIfInvalidIfCheckModel(const TopoDS_Shape& shape)
{
    Base::Reference<ParameterGrp> hGrp = App::GetApplication()
                                             .GetUserParameter()
                                             .GetGroup("BaseApp")
                                             ->GetGroup("Preferences")
                                             ->GetGroup("Mod/Part/Boolean");

    if (hGrp->GetBool("CheckModel", true)) {
        BRepCheck_Analyzer aChecker(shape);
        if (!aChecker.IsValid()) {
            throw Base::RuntimeError("Resulting shape is invalid");
        }
    }
}

bool getRefineModelParameter()
{
    Base::Reference<ParameterGrp> hGrp = App::GetApplication()
                                             .GetUserParameter()
                                             .GetGroup("BaseApp")
                                             ->GetGroup("Preferences")
                                             ->GetGroup("Mod/Part/Boolean");
    return hGrp->GetBool("RefineModel", true);
}

}  // namespace Part

namespace
{
/// Whether trsf is exactly the identity, whatever its form: a zero Placement gives one
bool isExactIdentity(const gp_Trsf& trsf)
{
    if (trsf.Form() == gp_Identity) {
        return true;
    }
    if (trsf.ScaleFactor() != 1.0 || trsf.TranslationPart().SquareModulus() != 0.0) {
        return false;
    }
    const gp_Mat& matrix = trsf.HVectorialPart();
    for (int row = 1; row <= 3; ++row) {
        for (int col = 1; col <= 3; ++col) {
            if (matrix.Value(row, col) != (row == col ? 1.0 : 0.0)) {
                return false;
            }
        }
    }
    return true;
}

/**
 * A boolean input in global coordinates, its location replaced rather than composed (ops#310).
 * getTopoShape() moves the stored shape, whose location is already its Placement, by a new datum
 * for an identity Placement, and the boolean keeps that location on every sub-shape it leaves
 * untouched: along a chain of Part::Cut the locations grew by two datums per cut, and every query
 * on those sub-shapes walked them. An identity becomes no location; anything else one datum.
 */
TopoShape getBooleanInput(const App::DocumentObject* obj)
{
    TopoShape shape = Feature::getTopoShape(obj, ShapeOption::ResolveLink | ShapeOption::Transform);
    if (!shape.isNull()) {
        const gp_Trsf trsf = shape.getShape().Location().Transformation();
        shape.locate(isExactIdentity(trsf) ? TopLoc_Location() : TopLoc_Location(trsf));
    }
    return shape;
}
}  // namespace

PROPERTY_SOURCE_ABSTRACT(Part::Boolean, Part::Feature)


Boolean::Boolean()
{
    ADD_PROPERTY(Base, (nullptr));
    ADD_PROPERTY(Tool, (nullptr));
    ADD_PROPERTY_TYPE(
        History,
        (ShapeHistory()),
        "Boolean",
        (App::PropertyType)(App::Prop_Output | App::Prop_Transient | App::Prop_Hidden),
        "Shape history"
    );
    History.setSize(0);

    ADD_PROPERTY_TYPE(
        Refine,
        (0),
        "Boolean",
        (App::PropertyType)(App::Prop_None),
        "Refine shape (clean up redundant edges) after this boolean operation"
    );

    this->Refine.setValue(getRefineModelParameter());
}

short Boolean::mustExecute() const
{
    if (Base.getValue() && Tool.getValue()) {
        if (Base.isTouched()) {
            return 1;
        }
        if (Tool.isTouched()) {
            return 1;
        }
    }
    return 0;
}

const char* Boolean::opCode() const
{
    return Part::OpCodes::Boolean;
}

App::DocumentObjectExecReturn* Boolean::execute()
{
    try {
#if defined(__GNUC__) && defined(FC_OS_LINUX)
        Base::SignalException se;
#endif
        auto base = Base.getValue();
        auto tool = Tool.getValue();

        if (!base || !tool) {
            return new App::DocumentObjectExecReturn("Linked object is not a Part object");
        }
        std::vector<TopoShape> shapes;
        shapes.reserve(2);
        // Now, let's get the TopoDS_Shape
        shapes.push_back(getBooleanInput(Base.getValue()));
        auto BaseShape = shapes[0].getShape();
        if (BaseShape.IsNull()) {
            throw NullShapeException("Base shape is null");
        }
        shapes.push_back(getBooleanInput(Tool.getValue()));
        auto ToolShape = shapes[1].getShape();
        if (ToolShape.IsNull()) {
            throw NullShapeException("Tool shape is null");
        }

        std::unique_ptr<BRepAlgoAPI_BooleanOperation> mkBool(makeOperation(BaseShape, ToolShape));
        if (!mkBool->IsDone()) {
            std::stringstream error;
            error << "Boolean operation failed";
            if (BaseShape.ShapeType() != TopAbs_SOLID) {
                error << std::endl << base->Label.getValue() << " is not a solid";
            }
            if (ToolShape.ShapeType() != TopAbs_SOLID) {
                error << std::endl << tool->Label.getValue() << " is not a solid";
            }
            return new App::DocumentObjectExecReturn(error.str());
        }
        TopoDS_Shape resShape = mkBool->Shape();
        if (resShape.IsNull()) {
            return new App::DocumentObjectExecReturn("Resulting shape is null");
        }

        throwIfInvalidIfCheckModel(resShape);

        TopoShape res = makeTopoShape(0, false);
        res.makeElementShape(*mkBool, shapes, opCode());
        if (this->Refine.getValue()) {
            res = res.makeElementRefine();
        }
        this->Shape.setValue(res);
        copyMaterial(base);
        return Part::Feature::execute();
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    catch (...) {
        return new App::DocumentObjectExecReturn(
            "A fatal error occurred when running boolean operation"
        );
    }
}

void Boolean::Restore(Base::XMLReader& reader)
{
    ExtensionContainer::Restore(reader);

    // The Refine property was added in FreeCAD 0.17, so any file before that will not have it set.
    // For these files, the appropriate default value is false.
    if (Base::getVersion(reader.ProgramVersion) < Base::Version::v0_17) {
        Refine.setValue(false);
    }
}
