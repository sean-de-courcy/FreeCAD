// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// The user's history operations as list edits (FreeCAD-CH ops#654, S3, notes/parts-design.md
// 3.2 and 3.5): each edits the studio's list and reconciles; the caller opens the transaction
// (one undo step). The Features list, the bar, drag, suppress, delete and rename call these.

#include <string>
#include <vector>

#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class DocumentObject;
}

namespace PartDesign
{

class Body;

/// Puts entry (an owner or a Body member) into its studio's list at index (-1: before the bar)
/// and reconciles
PartDesignExport bool studioInsert(App::DocumentObject* entry, int index, std::string* why);
/// Deletes entry from the list, and its steps; a Body member also leaves its Body (its chain
/// closes over it), else the next reconcile would adopt it again. The entry object itself is the
/// caller's to delete
PartDesignExport bool studioRemove(App::DocumentObject* entry, std::string* why);
/// Moves entry to index (a drag in the Features list)
PartDesignExport bool studioMove(App::DocumentObject* entry, int index, std::string* why);
/// Puts the bar before index (the roll-back bar; -1: at the end). anyEntry names the list: an
/// entry, the list itself, a Body of the studio, or the studio (App::Part)
PartDesignExport bool studioSetBar(App::DocumentObject* anyEntry, int index, std::string* why);
/// Sets owner's scope and reconciles (the Result row's parts)
PartDesignExport bool studioSetScope(
    App::DocumentObject* owner,
    const std::vector<Body*>& parts,
    std::string* why
);
/// Sets owner's scope to part ids (Body::StudioPartId; an id may name a part that is gone) and
/// reconciles
PartDesignExport bool studioSetScopeIds(
    App::DocumentObject* owner,
    const std::vector<std::string>& ids,
    std::string* why
);
/// Suppresses or unsuppresses entry (its steps follow). An owner without a Suppressed property
/// gets a hidden dynamic one

PartDesignExport bool studioSuppress(App::DocumentObject* entry, bool on, std::string* why);

}  // namespace PartDesign
