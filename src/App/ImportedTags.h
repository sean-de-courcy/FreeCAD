// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <map>
#include <optional>
#include <string>

#include <FCGlobal.h>

namespace Data
{

/** FreeCAD-CH ops#1002 (`notes/merge-tags-1002.md`): the saved tags of imported objects.
 *
 * An import (Merge project, a copy, a paste) gives each object a new ID, while every saved name
 * and record keeps the IDs of the file. These rewrite them through `ids` (saved ID -> new ID).
 */

/// \a name, a V2 element name in full or interned form, with each section's object ID (its
/// iteration tag) that \a ids holds replaced by the ID it maps to, the sign kept, also in the names
/// its Linked Names and Connected Elements embed. A list that was sorted is sorted again: its
/// order goes by the names' bytes, the IDs' digits included. Only the sections from the last
/// boundary section (`EXT`) on are the document's; those before it, and the names they embed,
/// hold another document's IDs and are kept. An interned name comes back interned. None when
/// nothing changed, or when the name doesn't encode back to itself byte for byte (then it is no
/// V2 name this can rewrite: a V1 or hashed name is kept as it is)
AppExport std::optional<std::string> remapElementTags(const std::string& name,
                                                      const std::map<long, long>& ids);

/// remapElementTags() of the mapped element name that \a text holds: a subname or shadow name
/// (`[path.];<mapped>[.<index>]`), a key `<object>.;<mapped>`, or a bare mapped name. The text
/// around the mapped name is kept. None when \a text holds none, or nothing changed
AppExport std::optional<std::string> remapNameTags(const std::string& text,
                                                   const std::map<long, long>& ids);

/// \a text, a fingerprint's saved form, with the IDs of its marks and the keys of its sources that
/// \a ids holds rewritten, both sorted again as their writers sort them (the solver searches the
/// marks by ID). A source's key of another document (`<ID>@<document>`) is kept, and so is a
/// digest of an object's inputs (`D`): the digest folds the inputs' saved form, names included,
/// so it is not the new object's, and its old key keeps it from matching one. A marks' ID can't say
/// its document: one that \a ids holds is taken as the import's. None when nothing changed, or
/// when \a text doesn't read back to itself
AppExport std::optional<std::string> remapFingerprintIds(const std::string& text,
                                                         const std::map<long, long>& ids);

}  // namespace Data
