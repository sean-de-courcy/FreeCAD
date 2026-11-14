// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// Pieces and leftovers become parts at command time (FreeCAD-CH ops#654, P6p,
// notes/parts-design.md 10.12). A part made so is a Body with StudioMadeBy = the entry E that made
// it, a part id "<E>:<k>" and a witness (StudioPieceWitness): the element names (stored interned,
// ops#640 C2; read expanded) of the faces that
// lie on its solid of the source and on no other, in tiers. A split piece names the part it came
// from (StudioParentId) and its source is E's result there; a leftover names none and its source is
// E's tool solids that touch no part of its scope. Its first step (a piece step: E's step in it)
// takes the one solid of the source the witness selects. Records are written by commands only
// (makePieces(), in the caller's transaction), never by a recompute.

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

/// Whether body is a part P6p made: made by an entry, with a witness
PartDesignExport bool isPieceBody(const Body* body);

/// The records of one source of maker, in the document's order: the pieces of the part parentId,
/// or (parentId empty) maker's leftovers
PartDesignExport std::vector<Body*> pieceRecords(const App::DocumentObject* maker,
                                                 const std::string& parentId);

/// piece's source, in the document's frame: maker's result in the parent part (its step there, or
/// maker itself for a Body member), or maker's leftover solids; null with why
PartDesignExport Part::TopoShape pieceSource(const Body* piece, std::string* why = nullptr);

/// The witness of the solid at index (from 0) of source: "<tier> <name>" for each face name on it
/// and on no other solid, tier 1 the faces of the maker's own tool, 2 unsplit faces of base, 3
/// pieces of base's open faces (base: the part before the maker; null for a leftover)
PartDesignExport std::vector<std::string>
pieceWitness(const Part::TopoShape& source, int index, const Part::TopoShape& base);

/// Which solid of source each record holds (-1: none, with why): each record's best score unique
/// and non-zero, the tiers compared in order; two records on one solid, the strictly higher wins.
/// A split source whose solids are all held (a partial unsplit, Onshape Q14e): the others on a
/// solid are absorbed into its holder (heldBy, the holder's record index; -1: not absorbed)
struct PieceMatch
{
    std::vector<int> solids;
    std::vector<std::string> why;
    std::vector<int> heldBy;
};
PartDesignExport PieceMatch matchPieces(const Part::TopoShape& source,
                                        const std::vector<Body*>& records);

/// The solid piece holds, in the document's frame; null with why
PartDesignExport Part::TopoShape pieceShape(const Body* piece, std::string* why = nullptr);

/// owner's tool solids that touch no in-scope part's shape at its place (document frame); null
/// when there are none, or when no in-scope part has a shape yet (a New result)
PartDesignExport Part::TopoShape leftoverSolids(const App::DocumentObject* owner);

/// Why maker's result in part (several solids) leaves pieces that are no parts; empty when every
/// solid is a part's, when it has one solid, or while maker's piece command runs
PartDesignExport std::string unclaimedSplit(const App::DocumentObject* maker,
                                            const Body* part,
                                            const Part::TopoShape& result);

/// Notes on maker whether its pieces of part lost their split (the result one solid that no
/// record holds): the part is then live again after maker; and which pieces a partial unsplit
/// absorbed, as "<piece id>><holder id>" (StudioSplitLost, read by the projection after the
/// recompute)
PartDesignExport void noteSplitHeld(App::DocumentObject* maker,
                                    const Body* part,
                                    const Part::TopoShape& result);

/// Why owner's tool leaves a solid touching no scope part that is no part; empty when there is
/// none, or while owner's piece command runs (H1a, R4)
PartDesignExport std::string unclaimedLeftovers(const App::DocumentObject* owner);

/// The entry whose piece command is running (its checks pass meanwhile), or null
PartDesignExport const App::DocumentObject* piecesCommandEntry();

/// The command: recomputes, gives every solid of entry's sources that no record holds a new part,
/// deletes the records without a solid whose Body holds nothing else, reconciles, recomputes. In
/// the caller's transaction. Returns the new Bodies; false-y (empty, why set) on a refusal
PartDesignExport std::vector<Body*> makePieces(App::DocumentObject* entry, std::string* why);

/// maker leaves the history (deleted or removed): each part it made from a piece that holds
/// nothing but steps goes, with its steps; one holding Body members stays, never live
/// (StudioMakerGone), failing loudly. In the caller's transaction
PartDesignExport void releasePiecesOf(App::DocumentObject* maker);

/// The name a piece shows: the custom name (not "Part N") of the part it came from, up its
/// lineage; empty when there is none (S3)
PartDesignExport std::string pieceInheritedName(const Body* body);

}  // namespace PartDesign
