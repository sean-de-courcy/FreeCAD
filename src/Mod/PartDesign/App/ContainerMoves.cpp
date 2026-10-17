// SPDX-License-Identifier: LGPL-2.1-or-later

// A container moved in the middle of a recompute (ops#342, notes/studio-gates.md "ops#342")

#include <map>
#include <set>
#include <utility>
#include <vector>

#include <App/Application.h>
#include <App/Datums.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/OriginGroupExtension.h>
#include <App/PropertyGeo.h>
#include <Base/Placement.h>

#include "ContainerMoves.h"

namespace PartDesign
{

namespace
{
struct Watch
{
    fastsignals::connection recomputed;
    // Each container's Placement when it last recomputed, by its document and ID: the signal
    // also reports other documents' objects, and an ID is never reused after a delete. One that
    // recomputes in place moves nothing, and the walk is skipped
    std::map<std::pair<const App::Document*, long>, Base::Placement> placements;
};
std::map<const App::Document*, Watch> watches;

// What the container places: its members, theirs, and its origin's elements
void collectMembers(App::DocumentObject* container, std::set<App::DocumentObject*>& members)
{
    if (auto originGroup = container->getExtensionByType<App::OriginGroupExtension>(true)) {
        if (auto origin = freecad_cast<App::LocalCoordinateSystem*>(originGroup->Origin.getValue())) {
            members.insert(origin);
            for (auto element : origin->OriginFeatures.getValues()) {
                members.insert(element);
            }
        }
    }
    if (auto group = container->getExtensionByType<App::GroupExtension>(true)) {
        for (auto member : group->Group.getValues()) {
            if (member && members.insert(member).second) {
                collectMembers(member, members);
            }
        }
    }
}

void containerRecomputed(const App::Document* doc, const App::DocumentObject& recomputed)
{
    if (!recomputed.hasExtension(App::GeoFeatureGroupExtension::getExtensionClassTypeId())
        || !recomputed.getNameInDocument() || doc->testStatus(App::Document::Restoring)
        || doc->isPerformingTransaction()) {
        return;
    }
    auto placement
        = freecad_cast<App::PropertyPlacement*>(recomputed.getPropertyByName("Placement"));
    auto it = watches.find(doc);
    if (!placement || it == watches.end()) {
        return;
    }
    auto [last, added] = it->second.placements.try_emplace(
        std::make_pair(recomputed.getDocument(), recomputed.getID()),
        placement->getValue()
    );
    if (!added && last->second == placement->getValue()) {
        return;
    }
    last->second = placement->getValue();

    auto container = const_cast<App::DocumentObject*>(&recomputed);
    std::set<App::DocumentObject*> members;
    collectMembers(container, members);
    std::set<App::DocumentObject*> readers(members.begin(), members.end());
    for (auto member : members) {
        for (auto reader : member->getInList()) {
            readers.insert(reader);
        }
    }
    readers.erase(container);
    // Only those whose own poll sees the move: the rest computed the same either way, and one
    // touched for nothing would run again in the second pass
    std::vector<App::DocumentObject*> moved;
    for (auto reader : readers) {
        if (reader->isAttachedToDocument() && !reader->isTouched() && reader->mustExecute() > 0) {
            moved.push_back(reader);
        }
    }
    for (auto reader : moved) {
        reader->touch();
    }
}

void watch(const App::Document& doc)
{
    auto document = &doc;
    auto& watched = watches[document];
    if (!watched.recomputed.connected()) {
        watched.recomputed = const_cast<App::Document&>(doc).signalRecomputedObject.connect(
            [document](const App::DocumentObject& recomputed) {
                containerRecomputed(document, recomputed);
            }
        );
    }
}
}  // namespace

void registerContainerMoves()
{
    static bool registered = false;
    if (registered) {
        return;
    }
    registered = true;
    App::GetApplication().signalNewDocument.connect(
        [](const App::Document& doc, bool) { watch(doc); }
    );
    App::GetApplication().signalDeleteDocument.connect([](const App::Document& gone) {
        auto it = watches.find(&gone);
        if (it != watches.end()) {
            it->second.recomputed.disconnect();
            watches.erase(it);
        }
    });
    for (auto doc : App::GetApplication().getDocuments()) {
        watch(*doc);
    }
}

}  // namespace PartDesign
