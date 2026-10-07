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

/// The text an object with a reference set aside by a reorder fails with (N1 3.4 b); false if
/// it has none
bool parkedReason(const App::DocumentObject* obj, std::string& why);

/// A reorder parked entries of obj's Originals (N1 3.4 b): a pattern whose Originals are all
/// parked is still a solid feature of its Body, not a MultiTransform's step
bool hasParkedOriginals(const App::DocumentObject* obj);

/// Lets the sketch editor name what a parked projection was projected from (ops#131 PR B):
/// Sketcher::parkedReference() reads the sketch's parking record through it
void registerParkedReferenceProvider();

}  // namespace PartDesign
