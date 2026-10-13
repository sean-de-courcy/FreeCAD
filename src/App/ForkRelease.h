// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <string>

#include "FCGlobal.h"

namespace App
{

class Document;

/** The fork release a file was saved by, and files of a newer release (ops#323).
 *
 * Every saved document, and every copy exportObjects() writes, carries `ForkRelease="<n>"` on its
 * `Document` element: the release number of the build that wrote it. Files without it (fork
 * previews before ops#323, FreeCAD itself) count as 0.
 *
 * A file is **newer** when it holds any marker above this build's: its `ForkRelease`, its
 * `NamingFormat`, its `NamingRevision`, or a shape's element map version token `.F<n>` or `.N<n>`.
 * Such a document opens with one console error and, in the GUI, a warning; a GUI save asks first,
 * a FreeCADCmd save warns and saves. Objects or properties the build doesn't know are dropped
 * while the file is read, so a save here loses them for good (notes/beta-compatibility.md 2.3).
 *
 * Defined in Document.cpp.
 */

/** This build's fork release: the count of fork releases, the next one included. fork-0.1.0 to
 * fork-0.6.1 are 1 to 7. The release routine bumps it in the first commit on `integration` after
 * each release tag, so a release build carries its own number and every later build a higher one.
 */
constexpr int ForkRelease = 8;

/// The `ForkRelease` \a doc was opened from, 0 for a file without one; this build's for a new
/// document and after a save to the document's own file.
AppExport int forkReleaseOf(const Document* doc);

/// Records that \a doc holds a marker above this build's (\a marker says which, e.g.
/// `NamingRevision 3`). Reported by reportNewerFormat().
AppExport void noteNewerFormat(const Document* doc, const std::string& marker);

/// Whether \a doc was opened from (or imported objects of) a newer file and hasn't been saved
/// to its own file since.
AppExport bool isNewerFormat(const Document* doc);

/// What tells that \a doc is newer: one line naming the file's release and this build's, and the
/// markers above this build's. Empty when it isn't newer.
AppExport std::string newerFormatMessage(const Document* doc);

/// True once for each newer document: whether the GUI is yet to show its warning.
AppExport bool takeNewerFormatNotice(const Document* doc);

/// Whether an element map version (`_Ver` of a saved shape) holds a fork token above this
/// build's: `.F<n>` above forkNamingRevision(), or `.N<n>` above the names form this build writes.
/// Such a shape takes no naming migration: its names are resolved as they are.
AppExport bool hasNewerForkTokens(const std::string& elementMapVersion);

}  // namespace App
