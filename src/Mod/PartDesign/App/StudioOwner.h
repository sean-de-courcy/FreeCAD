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

/// Whether feature runs as an owner: it skips the empty-base check and the Body-chain paths of
/// Feature::recompute()
PartDesignExport bool runsAsStudioOwner(const Feature* feature);

/// Why owner's Add tool can't be applied whole: a solid of it (a profile region) that touches no
/// in-scope part's shape at owner's place, which no step would take. Onshape makes it a new part
/// (notes/onshape-facts.md H1a); until pieces become parts (P6p) the feature fails loudly. Empty
/// when every solid touches one, or when no in-scope part has a shape yet (a New result)
PartDesignExport std::string studioAddLeftover(const App::DocumentObject* owner);

}  // namespace PartDesign
