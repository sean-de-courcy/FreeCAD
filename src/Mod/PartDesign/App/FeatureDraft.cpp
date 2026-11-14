// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2012 Jan Rheinländer                                    *
 *                                   <jrheinlaender@users.sourceforge.net> *
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


#include <BRepOffsetAPI_DraftAngle.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <Geom_Curve.hxx>
#include <Geom_Line.hxx>
#include <Geom_Plane.hxx>
#include <GeomAPI_IntSS.hxx>
#include <gp_Circ.hxx>
#include <gp_Dir.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>


#include <App/Datums.h>
#include <App/Document.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Tools.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/Part/App/TopoShape.h>

#include "FeatureDraft.h"
#include "DatumLine.h"
#include "DatumPlane.h"


using namespace PartDesign;


PROPERTY_SOURCE(PartDesign::Draft, PartDesign::DressUp)

const App::PropertyAngle::Constraints Draft::floatAngle
    = {-90.0, 90.0 - Base::toDegrees<double>(Precision::Angular()), 0.1};

Draft::Draft()
{
    ADD_PROPERTY(Angle, (1.5));
    Angle.setConstraints(&floatAngle);
    ADD_PROPERTY_TYPE(NeutralPlane, (nullptr), "Draft", (App::PropertyType)(App::Prop_None), "NeutralPlane");
    ADD_PROPERTY_TYPE(
        PullDirection,
        (nullptr),
        "Draft",
        (App::PropertyType)(App::Prop_None),
        "PullDirection"
    );
    ADD_PROPERTY(Reversed, (0));
}

void Draft::handleChangedPropertyType(Base::XMLReader& reader, const char* TypeName, App::Property* prop)
{
    Base::Type inputType = Base::Type::fromName(TypeName);
    if (prop == &Angle && inputType == App::PropertyFloatConstraint::getClassTypeId()) {
        App::PropertyFloatConstraint v;
        v.Restore(reader);
        Angle.setValue(v.getValue());
    }
    else {
        DressUp::handleChangedPropertyType(reader, TypeName, prop);
    }
}

short Draft::mustExecute() const
{
    if (Placement.isTouched() || Angle.isTouched() || NeutralPlane.isTouched()
        || PullDirection.isTouched() || Reversed.isTouched()) {
        return 1;
    }
    return DressUp::mustExecute();
}

App::DocumentObjectExecReturn* Draft::execute()
{
    // Get parameters
    // Base shape
    Part::TopoShape TopShape;
    try {
        TopShape = getBaseTopoShape();
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }

    // Faces where draft should be applied
    // Note: Cannot be const reference currently because of BRepOffsetAPI_DraftAngle::Remove() bug,
    // see below
    std::vector<std::string> SubVals = Base.getSubValuesStartsWith("Face");

    // create an untransformed copy of the base shape
    Part::TopoShape baseShape(TopShape);
    baseShape.locate(TopLoc_Location());
    // getFaces fails on a missing face, which SubVals doesn't list ("?Face3"): before the copy
    // below, which would take a draft whose faces are all missing for one with none (ops#60)
    std::vector<TopoShape> faces;
    try {
        faces = getFaces(baseShape);
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }

    // If no element is selected, then we use a copy of previous feature.
    if (SubVals.empty()) {
        this->positionByBaseFeature();
        this->Shape.setValue(TopShape);
        return App::DocumentObject::StdReturn;
    }

    // The neutral plane is picked, never guessed: with none the draft fails, as Onshape's does
    // ("Select a neutral plane."), and the dialog's field shows red (FreeCAD-CH ops#640, rank 17)
    App::DocumentObject* refPlane = NeutralPlane.getValue();
    if (!refPlane) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Select a neutral plane.")
        );
    }

    // Draft angle
    double angle = Base::toRadians(Angle.getValue());

    // Pull direction
    gp_Dir pullDirection;
    App::DocumentObject* refDirection = PullDirection.getValue();
    if (refDirection) {
        if (refDirection->isDerivedFrom<PartDesign::Line>()) {
            PartDesign::Line* line = static_cast<PartDesign::Line*>(refDirection);
            Base::Vector3d d = line->getDirection();
            pullDirection = gp_Dir(d.x, d.y, d.z);
        }
        else if (refDirection->isDerivedFrom<App::Line>()) {
            App::Line* line = static_cast<App::Line*>(refDirection);
            Base::Vector3d d = line->getDirection();
            pullDirection = gp_Dir(d.x, d.y, d.z);
        }
        else if (refDirection->isDerivedFrom<Part::Feature>()) {
            std::vector<std::string> subStrings = PullDirection.getSubValues();
            if (subStrings.empty() || subStrings[0].empty()) {
                throw Base::ValueError("No pull direction reference specified");
            }

            Part::Feature* refFeature = static_cast<Part::Feature*>(refDirection);
            Part::TopoShape refShape = refFeature->Shape.getShape();
            TopoDS_Shape ref = refShape.getSubShape(subStrings[0].c_str());

            if (ref.ShapeType() == TopAbs_EDGE) {
                TopoDS_Edge refEdge = TopoDS::Edge(ref);
                if (refEdge.IsNull()) {
                    throw Base::ValueError("Failed to extract pull direction reference edge");
                }
                BRepAdaptor_Curve adapt(refEdge);
                if (adapt.GetType() != GeomAbs_Line) {
                    throw Base::TypeError("Pull direction reference edge must be linear");
                }

                pullDirection = adapt.Line().Direction();
            }
            else {
                throw Base::TypeError("Pull direction reference must be an edge or a datum line");
            }
        }
        else {
            throw Base::TypeError(
                "Pull direction reference must be an edge of a feature or a datum line"
            );
        }

        TopLoc_Location invObjLoc = this->getLocation().Inverted();
        pullDirection.Transform(invObjLoc.Transformation());
    }

    // Neutral plane
    gp_Pln neutralPlane;
    {
        if (refPlane->isDerivedFrom<PartDesign::Plane>()) {
            PartDesign::Plane* plane = static_cast<PartDesign::Plane*>(refPlane);
            Base::Vector3d b = plane->getBasePoint();
            Base::Vector3d n = plane->getNormal();
            neutralPlane = gp_Pln(gp_Pnt(b.x, b.y, b.z), gp_Dir(n.x, n.y, n.z));
        }
        else if (
            refPlane->isDerivedFrom<App::Plane>() || refPlane->isDerivedFrom<Part::Part2DObject>()
        ) {
            neutralPlane = Feature::makePlnFromPlane(refPlane);
        }
        else if (refPlane->isDerivedFrom<Part::Feature>()) {
            std::vector<std::string> subStrings = NeutralPlane.getSubValues();
            if (subStrings.empty() || subStrings[0].empty()) {
                throw Base::ValueError("No neutral plane reference specified");
            }

            Part::Feature* refFeature = static_cast<Part::Feature*>(refPlane);
            Part::TopoShape refShape = refFeature->Shape.getShape();
            TopoDS_Shape ref = refShape.getSubShape(subStrings[0].c_str());

            if (ref.ShapeType() == TopAbs_FACE) {
                TopoDS_Face refFace = TopoDS::Face(ref);
                if (refFace.IsNull()) {
                    throw Base::ValueError("Failed to extract neutral plane reference face");
                }
                BRepAdaptor_Surface adapt(refFace);
                if (adapt.GetType() != GeomAbs_Plane) {
                    throw Base::TypeError("Neutral plane reference face must be planar");
                }

                neutralPlane = adapt.Plane();
            }
            else if (ref.ShapeType() == TopAbs_EDGE) {
                if (refDirection) {
                    // Create neutral plane through edge normal to pull direction
                    TopoDS_Edge refEdge = TopoDS::Edge(ref);
                    if (refEdge.IsNull()) {
                        throw Base::ValueError("Failed to extract neutral plane reference edge");
                    }
                    BRepAdaptor_Curve c(refEdge);
                    if (c.GetType() != GeomAbs_Line) {
                        throw Base::TypeError("Neutral plane reference edge must be linear");
                    }
                    double a = c.Line().Angle(gp_Lin(c.Value(c.FirstParameter()), pullDirection));
                    if (std::fabs(a - std::numbers::pi / 2) > Precision::Confusion()) {
                        throw Base::ValueError(
                            "Neutral plane reference edge must be normal to pull direction"
                        );
                    }
                    neutralPlane = gp_Pln(c.Value(c.FirstParameter()), pullDirection);
                }
                else {
                    throw Base::TypeError(
                        "Neutral plane reference can only be an edge if pull direction is defined"
                    );
                }
            }
            else {
                throw Base::TypeError("Neutral plane reference must be a face");
            }
        }
        else {
            throw Base::TypeError("Neutral plane reference must be face of a feature or a datum plane");
        }

        TopLoc_Location invObjLoc = this->getLocation().Inverted();
        neutralPlane.Transform(invObjLoc.Transformation());
    }

    if (!refDirection) {
        // Choose pull direction normal to neutral plane
        pullDirection = neutralPlane.Axis().Direction();
    }

    // Reversed pull direction
    bool reversed = Reversed.getValue();
    if (reversed) {
        angle *= -1.0;
    }

    computeProps = {pullDirection, neutralPlane};

    this->positionByBaseFeature();
    try {
        TopoShape shape = makeTopoShape();
        shape.makeElementDraft(baseShape, faces, pullDirection, angle, neutralPlane, reversed);

        if (shape.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Resulting shape is null")
            );
        }

        if (!isSingleSolidRuleSatisfied(shape.getShape())) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Result has multiple solids: enable 'Allow Compound' in the active body."
            ));
        }

        this->Shape.setValue(getSolid(shape));
        return App::DocumentObject::StdReturn;
    }
    catch (Standard_Failure& e) {

        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }
}
