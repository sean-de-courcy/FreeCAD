// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Pieces become parts at command time (FreeCAD-CH ops#654, P6p, notes/parts-design.md 3.3):
// a feature whose result in a part has several solids writes a piece record per new part into
// the list, in the command's transaction. A piece is told by a recorded topological witness
// (element names of the piece), never by a geometric rule or an index (requirement 3).

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

/// The witness of one piece: mapped element names that only that piece carries
struct PieceWitness
{
    std::vector<std::string> names;
};

/// The pieces of shape (its solids), each with its witness; empty witnesses where no name tells
/// a piece apart (the caller refuses then)
PartDesignExport std::vector<std::pair<Part::TopoShape, PieceWitness>>
piecesOf(const Part::TopoShape& shape);

/// The solid of shape that witness names, or null (loud: the piece has gone)
PartDesignExport Part::TopoShape pieceByWitness(
    const Part::TopoShape& shape,
    const PieceWitness& witness,
    std::string* why = nullptr
);

/// Splits step's part into parts: the first piece stays, each other gets a new Body whose first
/// step takes it. In the caller's transaction; reconciles. Returns the new Bodies (P6p)
PartDesignExport std::vector<Body*> makePiecesParts(App::DocumentObject* step, std::string* why);

}  // namespace PartDesign
