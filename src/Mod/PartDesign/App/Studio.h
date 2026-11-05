// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// The studio's feature list and its one roll-back bar (FreeCAD-CH ops#602, B+ Stage 2,
// notes/features-dock-design.md sections 3-5). A studio is an App::Part holding Bodies, or the
// document's top level (Part::BodyBase::studioOf())

#include <vector>

#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class Document;
class DocumentObject;
class Part;
}  // namespace App

namespace PartDesign
{

class Body;

/// The Bodies of studio (null: the document's top level), in the document's order
PartDesignExport std::vector<Body*> studioBodies(App::Document* doc, App::Part* studio);

/** The members of every Body of the studio (each Body's Group, without a MultiTransform's steps),
 * in one order: a member comes after the members of other Bodies it reads (directly, through
 * objects outside the Bodies, or through a subname path; reading a whole Body reads its last
 * solid feature) and after the members before it in its own Body's Group. Among the members
 * ready, the smallest object id (the creation order) comes first. A loop of links between Bodies
 * is broken by dropping dependencies, never the Group order: every member is listed once.
 * Nothing is saved.
 */
PartDesignExport std::vector<App::DocumentObject*> studioSequence(App::Document* doc, App::Part* studio);

/** Moves every Body's bar after its last solid feature at or above member in studioSequence(),
 * or to its top when it has none; member null: every Body to its top. Throws Base::ValueError
 * for a member not in the sequence. Opens no transaction and doesn't recompute.
 */
PartDesignExport void rollStudioTo(App::Document* doc, App::Part* studio, App::DocumentObject* member);

/// Moves every Body's bar to its end (Body::rollToEnd())
PartDesignExport void rollStudioToEnd(App::Document* doc, App::Part* studio);

/// Some Body of the studio is rolled back (Body::isRolledBack())
PartDesignExport bool isStudioRolledBack(App::Document* doc, App::Part* studio);

/** The row the studio's bar follows in sequence (studioSequence()): the row before the first one
 * its Body holds (Body::holds()), null when that is the first row, the last row when none is
 * held. With hinted, hint (the row the bar was last moved after, null: the top) is returned
 * instead when it lies before that row with no solid feature between them: what lies between is
 * a sketch or datum its Body doesn't hold either way.
 */
PartDesignExport App::DocumentObject* studioBarAfter(const std::vector<App::DocumentObject*>& sequence,
                                                     bool hinted = false,
                                                     App::DocumentObject* hint = nullptr);

}  // namespace PartDesign
