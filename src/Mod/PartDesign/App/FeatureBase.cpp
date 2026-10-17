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


#include <algorithm>
#include <cmath>
#include <vector>

#include <Precision.hxx>
#include <Standard_Failure.hxx>


#include <App/Application.h>
#include <App/Document.h>
#include <App/FeaturePythonPyImp.h>
#include <App/GeoFeature.h>
#include <App/GeoFeatureGroupExtension.h>
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

// `frame` and the containers that place it, innermost first. The bound guards against a cycle in
// a broken file
std::vector<const App::DocumentObject*> framesUp(const App::DocumentObject* frame)
{
    std::vector<const App::DocumentObject*> frames;
    while (frame && frames.size() < 100 && std::ranges::find(frames, frame) == frames.end()) {
        frames.push_back(frame);
        frame = App::GeoFeatureGroupExtension::getGroupOfObject(frame);
    }
    return frames;
}

// The raw placements of `frames` below `common`, composed outermost first: a global placement
// throws while a container recomputes (Attacher.cpp, linkFrame)
Base::Placement composeBelow(
    const std::vector<const App::DocumentObject*>& frames,
    const App::DocumentObject* common
)
{
    Base::Placement composed;
    for (auto frame : frames) {
        if (frame == common) {
            break;
        }
        if (auto geo = freecad_cast<const App::GeoFeature*>(frame)) {
            composed = geo->Placement.getValue() * composed;
        }
    }
    return composed;
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

bool FeatureBase::sourceSides(Base::Placement& source, Base::Placement& owner) const
{
    auto* base = freecad_cast<App::GeoFeature*>(BaseFeature.getValue());
    if (!base) {
        return false;
    }
    // A feature of a Body is taken in its Body's frame, anything else in its own placement
    const App::DocumentObject* start = isBodyLocalFeature(base) ? Body::findBodyOf(base) : base;
    const auto sourceFrames = framesUp(start);
    const auto ownerFrames = framesUp(App::GeoFeatureGroupExtension::getGroupOfObject(this));
    const App::DocumentObject* common = nullptr;
    for (auto frame : sourceFrames) {
        if (std::ranges::find(ownerFrames, frame) != ownerFrames.end()) {
            common = frame;
            break;
        }
    }
    source = composeBelow(sourceFrames, common);
    owner = composeBelow(ownerFrames, common);
    return true;
}

std::optional<Base::Placement> FeatureBase::sourceFrame() const
{
    Base::Placement source;
    Base::Placement owner;
    if (!sourceSides(source, owner)) {
        return std::nullopt;
    }
    return owner.inverse() * source;
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
    Base::Placement source;
    Base::Placement owner;
    if (SourceFrame.getSize() == 1 && followsSource() && sourceSides(source, owner)
        && !sameFrame(source, SourceFrame[0])) {
        return 1;
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

    // The copy follows its source (FreeCAD-CH ops#322, PLAN decisions 79 and 82): when the
    // source's side moved since the last recompute, the copy moves by as much, also when its place
    // was set by hand. Moving this copy's own Body, or a container of it, moves the whole Body,
    // the copy included; a container of both moves both
    Base::Placement source;
    Base::Placement owner;
    if (sourceSides(source, owner)) {
        if (SourceFrame.getSize() != 1 || !sameFrame(source, SourceFrame[0])) {
            if (SourceFrame.getSize() == 1) {
                Placement.setValue(
                    owner.inverse() * source * SourceFrame[0].inverse() * owner
                    * Placement.getValue()
                );
            }
            SourceFrame.setValues({source});
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
