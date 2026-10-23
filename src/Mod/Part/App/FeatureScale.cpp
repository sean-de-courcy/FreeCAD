// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2023 Wanderer Fan <wandererfan@gmail.com>               *
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

#include <BRepBuilderAPI_GTransform.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <gp_Pnt.hxx>
#include <gp_GTrsf.hxx>
#include <gp_Trsf.hxx>
#include <Precision.hxx>


#include <Base/Exception.h>

#include "FeatureScale.h"
#include "TopoShapeOpCode.h"

using namespace Part;

PROPERTY_SOURCE(Part::Scale, Part::Feature)

Scale::Scale()
{
    ADD_PROPERTY_TYPE(Base, (nullptr), "Scale", App::Prop_None, "Shape to scale");
    ADD_PROPERTY_TYPE(Uniform, (true), "Scale", App::Prop_None, "If true, scale equally in all directions");
    ADD_PROPERTY_TYPE(
        UniformScale,
        (1.0),
        "Scale",
        App::Prop_None,
        "Uniform scale factor - 1.0 means no scaling"
    );
    ADD_PROPERTY_TYPE(
        XScale,
        (1.0),
        "Scale",
        App::Prop_None,
        "Scale factor in X-direction - 1.0 means no scaling"
    );
    ADD_PROPERTY_TYPE(
        YScale,
        (1.0),
        "Scale",
        App::Prop_None,
        "Scale factor in Y-direction - 1.0 means no scaling"
    );
    ADD_PROPERTY_TYPE(
        ZScale,
        (1.0),
        "Scale",
        App::Prop_None,
        "Scale factor in Z-direction - 1.0 means no scaling"
    );
}

short Scale::mustExecute() const
{
    if (Base.isTouched() || Uniform.isTouched() || UniformScale.isTouched() || XScale.isTouched()
        || YScale.isTouched() || ZScale.isTouched()) {
        return 1;
    }
    return 0;
}

Scale::ScaleParameters Scale::computeFinalParameters()
{
    Scale::ScaleParameters result;
    result.uniform = Uniform.getValue();
    result.uniformScale = UniformScale.getValue();
    result.XScale = XScale.getValue();
    result.YScale = YScale.getValue();
    result.ZScale = ZScale.getValue();

    return result;
}

TopoShape Scale::scaleShape(const TopoShape& source, const Scale::ScaleParameters& params)
{
    TopoShape result;

    if (params.uniform) {
        result = uniformScale(source, params.uniformScale);
        return result;
    }

    return nonuniformScale(source, params);
}

TopoShape Scale::uniformScale(const TopoShape& source, const double& factor)
{
    //    Base::Console().message("FS::uniformScale()\n");
    // With the source's element map, here and in nonuniformScale(): a bare shape left references
    // to the result going by index (ops#453)
    TopoShape transTopo;
    try {
        gp_Trsf scaleTransform;
        scaleTransform.SetScale(gp_Pnt(0, 0, 0), factor);

        transTopo = TopoShape(source).makeElementTransform(scaleTransform, nullptr, CopyType::copy);
    }
    catch (...) {
        return {};
    }
    return transTopo;
}

TopoShape Scale::nonuniformScale(const TopoShape& source, const Scale::ScaleParameters& params)
{
    //    Base::Console().message("FS::nonuniformScale()\n");
    Base::Matrix4D matScale;
    matScale.scale(params.XScale, params.YScale, params.ZScale);

    // this copy step seems to eliminate Part.OCCError: gp_GTrsf::Trsf() - non-orthogonal GTrsf
    // which may to be related to the tessellation of the input shape.  See Github issue #9651
    // for more detail.
    TopoShape copied = source.makeElementCopy();
    TopoShape transTopo;
    try {
        transTopo = copied.makeElementGTransform(matScale, nullptr, CopyType::copy);
    }
    catch (...) {
        Base::Console().warning("FeatureScale failed on nonuniform scale\n");
        return transTopo;
    }
    return transTopo;
}

App::DocumentObjectExecReturn* Scale::execute()
{
    //    Base::Console().message("FS::execute()\n");
    App::DocumentObject* link = Base.getValue();
    if (!link) {
        return new App::DocumentObjectExecReturn("No object linked");
    }

    try {
        Scale::ScaleParameters params = computeFinalParameters();
        TopoShape result = scaleShape(
            Feature::getTopoShape(link, ShapeOption::ResolveLink | ShapeOption::Transform),
            params
        );
        // The result is a copy of the source with the source's names. In V2 they get a copy
        // section with this feature's ID (CPY;1), as a second side's do (FeatureExtrude.cpp):
        // otherwise a shape holding the source and the copy, or two Scales of one source, told
        // them apart only by the duplicate counter, which follows the inputs' order (ops#453).
        // A source without an element map (a primitive) is named first, as setValue() names it.
        // Part::Reverse does the same (PartFeatures.cpp).
        if (!result.isNull() && result.getHistoryAlgorithm() == App::HistoryAlgorithm::V2) {
            if (!result.getElementMapSize() && result.Tag && result.Tag != getID()) {
                result.reTagElementMap(getID(), result.Hasher, nullptr);
            }
            result.appendElementSection(getID(), OpCodes::Copy, "1");
        }
        this->Shape.setValue(result);
        return App::DocumentObject::StdReturn;
    }
    catch (Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }
}
