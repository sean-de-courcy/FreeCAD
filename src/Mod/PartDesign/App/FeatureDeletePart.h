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
    ~DeletePart() override;

    App::DocumentObjectExecReturn* execute() override;

    /// Deletes the part @p body from its bar on: a DeletePart added at the bar (Body::addObject).
    /// Refused, with the reason, for a Body with no solid feature above its bar or one already
    /// deleted there. Opens no transaction and doesn't recompute.
    static DeletePart* deletePart(Body* body);

    /** A Body of a studio left with no solid feature (the feature that made its New part deleted,
     * blind test F50): its other members (sketches, datums) go to another Body of the studio,
     * where the studio's history has them, and the Body goes with its origin, as Onshape keeps the
     * sketch, of no part, once the part is gone. The Body that takes them: the one whose member
     * the first of them reads (a sketch on its face), else the studio's first other Body. Returns
     * it, or null when nothing was done (a solid feature left, no studio, the studio's only
     * Body). Opens no transaction and doesn't recompute.
     */
    static Body* removeEmptyPart(Body* body);

    /// The DeletePart, not suppressed, at or before @p body's Tip in its Group (the part is
    /// deleted at the bar), or null
    static DeletePart* deleterOf(const Body* body);

    /// Why @p feature can't compute: it is a solid feature after a DeletePart in its Body, or it
    /// reads a part (a member of another Body, or that Body whole) that a DeletePart deleted
    /// before it in the studio's history. Empty when neither
    static std::string deleteLock(const App::DocumentObject* feature);

    /// @p why (an error's text) is deleteLock()'s: the feature failed on a deleted part
    static bool isDeleteLock(const char* why);

    /// Whether @p feature's last recompute failed on deleteLock() (a recompute clears the error
    /// texts before it asks mustExecute(), so the verdict is kept here, as the placer check keeps
    /// its own); set by Feature::recompute() and on restore
    static void setLocked(const App::DocumentObject* feature, bool locked);
    static bool wasLocked(const App::DocumentObject* feature);
};

}  // namespace PartDesign
