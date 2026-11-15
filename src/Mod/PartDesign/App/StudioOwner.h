// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// A studio feature (owner) computing its tool outside every Body (FreeCAD-CH ops#654, S2,
// notes/parts-design.md 10.1 "(b) on the build"): the guards an owner needs in code written for
// features in a Body, as free functions so that slices change no header.

#include <string>
#include <vector>

#include <Mod/Part/App/TopoShape.h>
#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class DocumentObject;
}

namespace PartDesign
{

class Body;
class Feature;

/// The shape of part at owner's place in the history: the Tip of its chain just before owner's
/// step (its base), in the document's frame; null when part has nothing there
PartDesignExport Part::TopoShape studioBaseAt(const App::DocumentObject* owner, const Body* part);

/// The in-scope parts' shapes at owner's place, fused into one compound (Through all and the
/// Up-to modes), in the document's frame
PartDesignExport Part::TopoShape studioScopeBaseAt(const App::DocumentObject* owner);

/// The last solid feature of part before owner's place in the studio's list that has a solid (a
/// failed one contributes nothing): the part as it is at owner (FreeCAD-CH ops#846); null when
/// owner is in no list or part has nothing there
PartDesignExport const Part::Feature* studioPartSolidBefore(
    const App::DocumentObject* owner,
    const Body* part
);

/// A whole link of owner to a part of its studio (linked: the Body, or a solid feature of it),
/// read at owner's place: the shape of studioPartSolidBefore() with its Body's placement, as
/// the Body's own shape has it. isPart says whether linked is such a link; null with isPart when the part has no
/// solid before owner (notes/owner-upto-face.md)
PartDesignExport Part::TopoShape studioPartShapeAt(
    const App::DocumentObject* owner,
    const App::DocumentObject* linked,
    bool& isPart
);

/// An owner's link to one element of a solid feature of a studio part (linked, element), read at
/// owner's place (FreeCAD-CH ops#848, Onshape UT5: an up-to face is read as it is at the feature,
/// so a face a later-inserted Draft tilts is followed): the element as the part's last solid
/// before owner has it, traced by name from linked. Null when owner is no studio owner, linked is
/// that last solid or no solid of a studio part, or the element can't be traced there: the
/// caller then reads linked itself, as before. A face that became several faces there on
/// different surfaces (one piece of a split tilted) is null with why: no piece is the face
PartDesignExport Part::TopoShape studioElementAt(
    const App::DocumentObject* owner,
    const App::DocumentObject* linked,
    const std::string& element,
    std::string* why = nullptr
);

/// Whether prop is an up-to link (UpToFace/2, UpToShape/2) that names parts of a studio whole: every
/// entry without an element, on a Body or a solid feature of one, of a reader outside every Body. Such a link is read at the
/// reader's place whatever it names (studioPartShapeAt()) and reconcile re-targets it, so it is no
/// read of the feature it names (a reorder, a kept step)
PartDesignExport bool studioWholePartLink(const App::Property* prop);

/// Before step (of body) is removed: the up-to links that name the part whole through it
/// (studioWholePartLink()) go to the part's solid before it, else to the Body, which reconcile
/// writes to the part's last solid before the reader. Removing the step would clear them
PartDesignExport void studioReleaseWholePartLinks(App::DocumentObject* step, Body* body);

/// Why owner can't compute on its links: one names a part it changes itself (the Body), its own
/// step there, or a solid of that part after its step, each a dependency cycle through its step
/// (ops#846). Empty when there is none
PartDesignExport std::string studioLinkAhead(const Feature* owner);

/// Whether feature runs as an owner: it skips the empty-base check and the Body-chain paths of
/// Feature::recompute()
PartDesignExport bool runsAsStudioOwner(const Feature* feature);

/// Why owner's Add tool can't be applied whole: a solid of it (a profile region) that touches no
/// in-scope part's shape at owner's place, which no step would take. Onshape makes it a new part
/// (notes/onshape-facts.md H1a); until pieces become parts (P6p) the feature fails loudly. Empty
/// when every solid touches one, or when no in-scope part has a shape yet (a New result)
PartDesignExport std::string studioAddLeftover(const App::DocumentObject* owner);

}  // namespace PartDesign
