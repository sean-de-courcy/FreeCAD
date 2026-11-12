// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// A Transform studio feature's steps (FreeCAD-CH ops#655, notes/transform-design.md): Onshape's
// Transform (move, rotate, copy part). The owner is a Python feature (TransformFeature.py) that
// computes its motion into "StudioTransform"; its steps are FeatureApply steps that hand their work
// here, so no header of the studio changes.

#include <string>

#include <Mod/Part/App/TopoShape.h>
#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class DocumentObject;
}

namespace PartDesign
{

class Body;

/// A Transform studio feature: an owner with the motion it computes ("StudioTransform", a
/// placement in the document's frame) and its "MakeCopy" tick
PartDesignExport bool isStudioTransform(const App::DocumentObject* owner);

/// The result of owner's step in body, in body's frame with its location (the step's Placement):
/// - a part the owner made (Copy part): its source's solid at the owner's place moved, with new
///   names under tag; nothing may come before it
/// - a picked part, MakeCopy off: base moved (its location only: geometry and names are base's)
/// - a picked part, MakeCopy on: base as it is (the source stays)
/// A part whose shape is a sheet or a wire body moves and copies as a solid does (ops#678): with
/// base null (the caller's base is solids only), the step's previous feature's shape is taken.
/// Null with why when it can't be made.
PartDesignExport Part::TopoShape studioTransformStep(
    const App::DocumentObject* owner,
    const Body* body,
    const Part::TopoShape& base,
    long tag,
    std::string* why
);

}  // namespace PartDesign
