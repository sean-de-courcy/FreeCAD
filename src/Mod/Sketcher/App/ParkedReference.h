// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// A sketch's projections parked in place by a reorder (FreeCAD-CH ops#131): the geometry stays,
// its link is set aside in the owner's record, which PartDesign writes and reads. The sketch
// editor asks through this hook what a geometry was projected from, without knowing the record.

#include <functional>
#include <string>

#include <Mod/Sketcher/SketcherGlobal.h>

namespace Sketcher
{

class SketchObject;

/// "<object>.<element>" the external geometry with this Id was projected from while it is parked;
/// empty when it isn't parked
using ParkedReferenceProvider =
    std::function<std::string(const SketchObject& sketch, long geometryId)>;

/// Set by the module that parks projections (PartDesign)
SketcherExport void setParkedReferenceProvider(ParkedReferenceProvider provider);

/// What the external geometry GeoId (< 0) of sketch was projected from, when a reorder parked it:
/// "<object>.<element>"; empty when it isn't parked, or without a provider
SketcherExport std::string parkedReference(const SketchObject& sketch, int GeoId);

}  // namespace Sketcher
