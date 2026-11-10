// SPDX-License-Identifier: LGPL-2.1-or-later

// Pieces become parts at command time (FreeCAD-CH ops#654, P6p). Scaffolding (B1).

#include "Body.h"
#include "Pieces.h"

namespace PartDesign
{

std::vector<std::pair<Part::TopoShape, PieceWitness>> piecesOf(const Part::TopoShape& /*shape*/)
{
    return {};  // P6p
}

Part::TopoShape pieceByWitness(
    const Part::TopoShape& /*shape*/,
    const PieceWitness& /*witness*/,
    std::string* why
)
{
    if (why) {
        *why = "not yet (P6p)";
    }
    return {};
}

std::vector<Body*> makePiecesParts(App::DocumentObject* /*step*/, std::string* why)
{
    if (why) {
        *why = "not yet (P6p)";
    }
    return {};
}

}  // namespace PartDesign
