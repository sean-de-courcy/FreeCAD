// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// The reorder's plan and the re-target rule (ops#127, notes/reorder-rollback-design.md 2.1 and
// section 3)

#include <functional>
#include <string>
#include <vector>

namespace App
{
class DocumentObject;
}

namespace PartDesign
{

class Body;

/// Sets a feature's BaseFeature and reroutes what follows its base (Body::rerouteBase())
using RerouteBase = std::function<void(App::DocumentObject* feature, App::DocumentObject* newBase)>;

/** Body::reorderObject() (N1 2.1): moves objs (with the inputs only they use) before or after
 * target, rewires the BaseFeature chain through reroute, and keeps the Tip at its place in the
 * list. Everything is planned first and the planned dependency graph is checked for a cycle, so
 * a refusal (Base::ValueError) writes nothing.
 */
void reorderBody(Body& body,
                 const std::vector<App::DocumentObject*>& objs,
                 App::DocumentObject* target,
                 bool after,
                 const RerouteBase& reroute);

/** While one is alive on this thread, reorderBody() moves only the objects it is given: no input
 * is carried with them (its step 2). The Features list's drag (moveInStudio()): Onshape moves only
 * the dragged feature, its sketch stays where it is (FreeCAD-CH ops#640 rank 31, blind test F31)
 */
class OnlyGivenObjects
{
public:
    OnlyGivenObjects();
    ~OnlyGivenObjects();
    OnlyGivenObjects(const OnlyGivenObjects&) = delete;
    OnlyGivenObjects& operator=(const OnlyGivenObjects&) = delete;
};

/// The text an object with a reference set aside by a reorder fails with (N1 3.4 b); false if
/// it has none
bool parkedReason(const App::DocumentObject* obj, std::string& why);

/// obj holds a parking record: a reorder set a reference of it aside (N1 3.4 b)
bool hasParkedReferences(const App::DocumentObject* obj);

/// One of holders (feature, or what it reads in its Body) holds a parking record (N1 3.4 b) whose
/// reference is to a member after feature, and feature is the earliest solid that reads it (N1
/// 3.1): feature was moved above what it needs, with the inputs only it uses (ops#596: a feature
/// failing on it is parked). A record that refers to feature itself or to a member before it, or
/// on a member an earlier solid reads, doesn't count (reviews pr596-r1 and pr596s-r1:
/// StockReadsParkedSketch, the stock given a parked boss sketch's normal as its direction)
bool parkedAbove(const App::DocumentObject* feature,
                 const std::vector<const App::DocumentObject*>& holders);

/// A reorder parked entries of obj's Originals (N1 3.4 b): a pattern whose Originals are all
/// parked is still a solid feature of its Body, not a MultiTransform's step
bool hasParkedOriginals(const App::DocumentObject* obj);

/// A reorder is writing its plan (reorderBody() step 6): its bases, re-targets and parks are set
/// one by one, and the Body's chain is the plan's only when they are all written
bool reorderWriting();

/// Lets the sketch editor name what a parked projection was projected from (ops#131 PR B):
/// Sketcher::parkedReference() reads the sketch's parking record through it
void registerParkedReferenceProvider();

/// Rewrites the parked lines of imported, merged and pasted objects to name the copies of their
/// objects (ops#158): watches every document's signalImportObjects
void registerParkedImport();

}  // namespace PartDesign
