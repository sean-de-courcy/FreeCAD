// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Delete part (FreeCAD-CH ops#635, notes/part-history-design.md 3.2)

#include <string>

#include "Feature.h"

namespace PartDesign
{

class Body;

/** Onshape's Delete part: a feature in the history that deletes its Body's part from its place on.
 *
 * It sits in the deleted Body at the bar, as its Tip, and makes the empty shape, so the Body is
 * empty and valid. The features before it stay; rolling the bar above it, deleting it or undo
 * brings the part back. A solid feature after it in its Body, and a feature of another Body that
 * reads the deleted part and comes after it in the studio's history, fail (deleteLock()).
 */
class PartDesignExport DeletePart: public PartDesign::Feature
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::DeletePart);

public:
    DeletePart();

    App::DocumentObjectExecReturn* execute() override;

    /// Deletes the part @p body from its bar on: a DeletePart added at the bar (Body::addObject).
    /// Refused, with the reason, for a Body with no solid feature above its bar or one already
    /// deleted there. Opens no transaction and doesn't recompute.
    static DeletePart* deletePart(Body* body);

    /// The DeletePart that is @p body's Tip (the part is deleted at the bar), or null
    static DeletePart* deleterOf(const Body* body);

    /// Why @p feature can't compute: it is a solid feature after a DeletePart in its Body, or it
    /// reads a part (a member of another Body, or that Body whole) that a DeletePart deleted
    /// before it in the studio's history. Empty when neither
    static std::string deleteLock(const App::DocumentObject* feature);
};

}  // namespace PartDesign
