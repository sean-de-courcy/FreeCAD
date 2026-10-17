// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2017 Stefan Tröger <stefantroeger@gmx.net>              *
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


#include <cmath>

#include <Precision.hxx>
#include <Standard_Failure.hxx>


#include <App/Application.h>
#include <App/Document.h>
#include <App/FeaturePythonPyImp.h>
#include <App/GeoFeature.h>
#include <Mod/Part/App/Attacher.h>
#include <Mod/Part/App/PropertyTopoShape.h>
#include "Body.h"
#include "FeatureBase.h"
#include "FeaturePy.h"

namespace PartDesign
{

namespace
{
// A feature of a Body: execute() takes its shape in that Body's coordinates, with the feature's
// own placement applied
bool isBodyLocalFeature(const App::DocumentObject* base)
{
    return base->isDerivedFrom<PartDesign::Feature>() && Body::findBodyOf(base);
}

// Whether the source's frame is where it was: positions within Precision::Confusion(), rotations
// by their quaternions' components within 1e-12, either sign. Placement::isSame takes a rotation
// as the same while |q1.q2| >= 1 - tol/2, so at Precision::Confusion() a turn below 6e-4 rad
// went unseen: the copy stayed 0.6 mm off at 1 m from the turn's axis (ops#322 review round 1).
// A reopened frame, saved with 16 digits, still compares the same
bool sameFrame(const Base::Placement& a, const Base::Placement& b)
{
    if ((a.getPosition() - b.getPosition()).Length() > Precision::Confusion()) {
        return false;
    }
    double p[4];
    double q[4];
    a.getRotation().getValue(p[0], p[1], p[2], p[3]);
    b.getRotation().getValue(q[0], q[1], q[2], q[3]);
    constexpr double tolerance = 1e-12;
    auto within = [&](double sign) {
        for (int i = 0; i < 4; ++i) {
            if (std::abs(p[i] - sign * q[i]) > tolerance) {
                return false;
            }
        }
        return true;
    };
    return within(1.0) || within(-1.0);
}
}  // namespace

PROPERTY_SOURCE(PartDesign::FeatureBase, PartDesign::Feature)

FeatureBase::FeatureBase()
{
    BaseFeature.setScope(App::LinkScope::Global);
    BaseFeature.setStatus(App::Property::Hidden, false);
    // Files saved before this property was introduced do not store a value for it.
    // During restore, default to the pre-change placement behavior for compatibility.
    // Newly created FeatureBase objects use the new behavior.
    ADD_PROPERTY_TYPE(
        UseLegacyBaseFeaturePlacement,
        (App::GetApplication().isRestoring()),
        "Compatibility",
        App::Prop_Hidden,
        "Use legacy FeatureBase source placement handling"
    );
    ADD_PROPERTY_TYPE(
        SourceFrame,
        (),
        "Base",
        (App::PropertyType)(App::Prop_Output | App::Prop_ReadOnly | App::Prop_Hidden),
        "The source's frame when the copy was last computed (FreeCAD-CH ops#322)"
    );
}

std::optional<Base::Placement> FeatureBase::sourceFrame() const
{
    auto* base = freecad_cast<App::GeoFeature*>(BaseFeature.getValue());
    if (!base) {
        return std::nullopt;
    }
    // Raw placements through the containers: a global placement throws while a container
    // recomputes (Attacher.cpp, linkFrame)
    auto frame = Attacher::AttachEngine::linkFrame(this, base);
    if (!isBodyLocalFeature(base)) {
        frame = frame * base->Placement.getValue();
    }
    return frame;
}

bool FeatureBase::followsSource() const
{
    if (UseLegacyBaseFeaturePlacement.getValue() || Suppressed.getValue()) {
        return false;
    }
    auto body = getFeatureBody();
    return !body || !body->holds(this);
}

Part::Feature* FeatureBase::getBaseObject(bool) const
{

    return nullptr;
}

short int FeatureBase::mustExecute() const
{

    if (BaseFeature.isTouched() || UseLegacyBaseFeaturePlacement.isTouched()) {
        return 1;
    }
    // The source moved: its Body, a container, or itself. Moving a Body touches neither its
    // features nor this, so it is polled here; a container moved by an expression in the middle
    // of a recompute touches this when it asks to run (ContainerMoves.h)
    if (SourceFrame.getSize() == 1 && followsSource()) {
        auto frame = sourceFrame();
        if (frame && !sameFrame(*frame, SourceFrame[0])) {
            return 1;
        }
    }

    return PartDesign::Feature::mustExecute();
}


App::DocumentObjectExecReturn* FeatureBase::execute()
{

    if (!BaseFeature.getValue()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "BaseFeature link is not set")
        );
    }

    auto* base = BaseFeature.getValue();
    if (UseLegacyBaseFeaturePlacement.getValue()) {
        auto shape = Part::Feature::getTopoShape(
            base,
            Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
        );
        if (shape.isNull()) {
            auto* shapeProperty = freecad_cast<const Part::PropertyPartShape*>(
                App::GeoFeature::getPropertyOfGeometry(base)
            );
            if (shapeProperty) {
                shape = shapeProperty->getShape();
            }
        }
        if (shape.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "BaseFeature has an empty shape")
            );
        }

        Shape.setValue(shape);
        return StdReturn;
    }

    const bool isBodyLocal = isBodyLocalFeature(base);
    const bool isPartDesignBody = base->isDerivedFrom<PartDesign::Body>();

    auto shape = isBodyLocal
        ? static_cast<Part::Feature*>(base)->Shape.getShape()
        : Part::Feature::getTopoShape(base, Part::ShapeOption::ResolveLink);
    if (shape.isNull()) {
        auto* shapeProperty = freecad_cast<const Part::PropertyPartShape*>(
            App::GeoFeature::getPropertyOfGeometry(base)
        );
        if (shapeProperty) {
            shape = shapeProperty->getShape();
        }
    }
    if (shape.isNull()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "BaseFeature has an empty shape")
        );
    }

    if (isBodyLocal || isPartDesignBody) {
        shape.transformShape(shape.getTransform(), true);
    }

    // The copy follows its source (FreeCAD-CH ops#322, PLAN decision 79), as a binder does: when
    // the source's frame moved since the last recompute, the Placement moves by as much, so the
    // copy keeps its place relative to the source, also when that place was set by hand
    if (auto frame = sourceFrame()) {
        if (SourceFrame.getSize() != 1 || !sameFrame(*frame, SourceFrame[0])) {
            if (SourceFrame.getSize() == 1) {
                Placement.setValue(*frame * SourceFrame[0].inverse() * Placement.getValue());
            }
            SourceFrame.setValues({*frame});
        }
    }
    else if (SourceFrame.getSize() != 0) {
        SourceFrame.setValues({});
    }

    Shape.setValue(shape);

    return StdReturn;
}

void FeatureBase::trySetBaseFeatureOfBody()
{
    if (auto body = getFeatureBody()) {
        if (BaseFeature.getValue() && body->BaseFeature.getValue()
            && body->BaseFeature.getValue() != BaseFeature.getValue()) {
            body->BaseFeature.setValue(BaseFeature.getValue());
        }
    }
}

void FeatureBase::onChanged(const App::Property* prop)
{

    // the BaseFeature property should track the Body BaseFeature and vice-versa
    if (prop == &BaseFeature) {
        trySetBaseFeatureOfBody();
        // Another source: the next recompute takes its frame as it is (ops#322)
        if (!isRestoring() && getDocument() && !getDocument()->isPerformingTransaction()
            && SourceFrame.getSize() != 0) {
            SourceFrame.setValues({});
        }
    }

    PartDesign::Feature::onChanged(prop);
}

void FeatureBase::onDocumentRestored()
{
    // if the base is not part of a body then show its placement property again
    auto body = getFeatureBody();
    if (!body) {
        Placement.setStatus(App::Property::Hidden, false);
    }
    PartDesign::Feature::onDocumentRestored();
}

}  // namespace PartDesign
