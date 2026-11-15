// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD-CH fork (ops#640, folder sync item 6, design A's B5).

#pragma once

#include <string>
#include <vector>

#include <FCGlobal.h>

namespace App
{

class Document;

/// FreeCAD-CH (ops#640, folder sync item 6; notes/folder-sync.md section 3, design A's B5):
/// "Ward has this open on the Mac". Each open document inside the team folder has one small file
/// per computer and process in `<team folder>/.fcch/open/`, synced like the documents (`.fcch` is
/// not in the ignore list). It names the document (relative to the team folder), the user, the
/// computer, the process and the time, which a heartbeat refreshes every minute. A marker under a
/// three minutes old time from another computer or another process means someone else has the
/// document open. A courtesy, not a lock: markers arrive seconds late, and the save guard (A2)
/// still settles two saves. Nothing here is part of a saved document.
namespace DocumentPresence
{

/// How often the GUI refreshes this process's markers.
constexpr int heartbeatSeconds = 60;
/// A marker younger than this counts as open.
constexpr int freshSeconds = 180;

struct Marker
{
    std::string file;  ///< the document, relative to the team folder, with '/'
    std::string user;
    std::string host;
    long long pid = 0;
    long long time = 0;  ///< seconds since 1970 (UTC), the last heartbeat
    std::string path;    ///< the marker file itself
};

/// The folder holding the markers for `documentPath`, or an empty string when the document is not
/// inside the team folder (or no team folder is set).
AppExport std::string markerFolder(const std::string& documentPath);

/// The fresh markers of other computers or processes for `documentPath` (a file name; it need not
/// be open). Removes, on the way, this computer's markers whose process is gone.
AppExport std::vector<Marker> others(const std::string& documentPath);

/// "Ward has this document open on WARD-MAC" (one sentence for one or more markers).
AppExport std::string describe(const std::vector<Marker>& markers);

/// Writes or refreshes this process's marker of every open document inside the team folder and
/// removes the ones of documents closed, moved out or saved under another name.
AppExport void refresh();

/// Removes this process's marker of `document`, if any.
AppExport void remove(const Document& document);

/// The marker this process keeps for `document`, or an empty string.
AppExport std::string ownMarker(const Document& document);

/// This computer's name, as written in the markers.
AppExport std::string hostName();

/// Connects to the document signals (open, save, close). Called once at start.
void start();

}  // namespace DocumentPresence
}  // namespace App
