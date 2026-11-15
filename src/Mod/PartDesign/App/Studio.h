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
 * ready, the smallest history key comes first: a member's HistoryRank where a drop or an insert
 * at the bar saved one (ops#632, notes/part-history-design.md 3.3), else its object id (the
 * creation order). A loop of links between Bodies is broken by dropping dependencies, never the
 * Group order: every member is listed once.
 */
PartDesignExport std::vector<App::DocumentObject*> studioSequence(App::Document* doc, App::Part* studio);

/** Saves order as the studio's history order: each member's HistoryRank (a hidden output float:
 * setting it touches nothing) becomes its place in order. studioSequence() gives order back as
 * long as it keeps the Group orders and the reads between Bodies
 */
PartDesignExport void saveHistoryOrder(const std::vector<App::DocumentObject*>& order);

/// Imported objects (a copy, a paste, a merged file) lose their saved HistoryRank: they are listed
/// as the newest members. Watches every document's signalImportObjects
PartDesignExport void registerHistoryImport();

/** Body::addObject()'s insert at a rolled-back bar (design 3.3): history is the studio's sequence
 * before the insert and bar the row its bar followed then (studioBarAfter() of it). feature, now
 * in its Body's Group, goes right after bar (before its Body's member after it, if that comes
 * first), and its Body's members before it that are listed later come up with it; when one of
 * them reads a row of another Body it would pass, feature goes after its Body's member before it
 * instead. The order is saved (saveHistoryOrder())
 */
PartDesignExport void saveInsertAtBar(App::Document* doc,
                                      App::Part* studio,
                                      const std::vector<App::DocumentObject*>& history,
                                      App::DocumentObject* bar,
                                      App::DocumentObject* feature);

/** Drags rows (members of one Body of the studio, rows of studioSequence()) to after the row
 * after (null: the top) in the studio's history (design 3.3), and saves the new order.
 * - Inside their Body the rows go after its last other row at or above the drop (before its first
 *   when there is none) through Body::reorderObject(): the rows alone (a feature's sketch stays
 *   where it is, as Onshape's drag, ops#640 rank 31), re-targeted, and parked when they go above
 *   what they need. A drop that puts a solid feature above a sketch or datum of its Body it uses,
 *   or one of those below it, is refused.
 * - A drop that puts a row above a member of another Body it reads, or below one that reads it, is
 *   refused with both named.
 * - With the studio rolled back, the bar stays after the row bar (hinted; null: the top), else
 *   after the row it followed (studioBarAfter()), or the row before that when that one moved:
 *   the rows' Body is rolled back to its last solid feature above the bar, so a row dropped below
 *   it is held.
 * Returns whether anything changed. Throws Base::ValueError for a refusal, before anything is
 * written. Opens no transaction and doesn't recompute
 */
PartDesignExport bool moveInStudio(App::Document* doc,
                                   App::Part* studio,
                                   const std::vector<App::DocumentObject*>& rows,
                                   App::DocumentObject* after,
                                   bool hinted = false,
                                   App::DocumentObject* bar = nullptr);

/** What member, a member of a Body, reads of the other Bodies (ops#635): their members, and those
 * Bodies whole (a Boolean's tool, a binder of a Body), by studioSequence()'s rule for a link entry,
 * directly, through objects outside the Bodies, and through the non-solid members of its own Body
 * (its sketch's support and external geometry, a datum, a binder). Not through another member.
 * With via, via[i] is the member of member's Body that reads the i-th one: member, or the sketch,
 * datum or binder it is read through (the last one on the path)
 */
PartDesignExport std::vector<App::DocumentObject*> readsOfOtherBodies(
    const App::DocumentObject* member,
    std::vector<const App::DocumentObject*>* via = nullptr
);

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
 * held. Without a hint, the row before the first one that is held or waits below the bar
 * (Body::waitsBelowBar(): a sketch or datum after its Body's bar whose users are all held), when
 * no solid lies between that one and the first held row (ops#640 rank 34). With hinted, hint
 * (the row the bar was last moved after, null: the top) is returned instead when it lies before
 * that row with no solid feature between them: what lies between is a sketch or datum its Body
 * doesn't hold either way.
 */
PartDesignExport App::DocumentObject* studioBarAfter(const std::vector<App::DocumentObject*>& sequence,
                                                     bool hinted = false,
                                                     App::DocumentObject* hint = nullptr);

}  // namespace PartDesign
