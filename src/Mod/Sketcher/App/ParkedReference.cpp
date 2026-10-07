// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ExternalGeometryFacade.h"
#include "ParkedReference.h"
#include "SketchObject.h"

namespace Sketcher
{

namespace
{
ParkedReferenceProvider& provider()
{
    static ParkedReferenceProvider instance;
    return instance;
}
}  // namespace

void setParkedReferenceProvider(ParkedReferenceProvider p)
{
    provider() = std::move(p);
}

std::string parkedReference(const SketchObject& sketch, int GeoId)
{
    if (GeoId > GeoEnum::RefExt || !provider()) {
        return {};
    }
    auto geo = sketch.getGeometry(GeoId);
    if (!geo) {
        return {};
    }
    auto egf = ExternalGeometryFacade::getFacade(geo);
    // A parked geometry has no reference; one with a reference is linked or missing
    if (!egf->getRef().empty()) {
        return {};
    }
    return provider()(sketch, egf->getId());
}

}  // namespace Sketcher
