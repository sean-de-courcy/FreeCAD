// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD-CH fork (ops#640, folder sync item 2).

#pragma once

#include <string>
#include <vector>

#include "FCGlobal.h"

namespace App
{

class Document;

/// FreeCAD-CH (ops#640, folder sync item 2; notes/folder-sync.md section 3, design A4): the company
/// folder that Syncthing keeps the same on every computer. One preference,
/// `User parameter:BaseApp/Preferences/Document/TeamFolder`, holds its path. Setting it writes the
/// shared ignore list `.stglobalignore` into the folder and makes the folder's own `.stignore`
/// include it, so the temporary save files and the backups stay on the computer that made them.
/// Documents saved inside the folder keep at least `backupsKept` local backups.
namespace TeamFolder
{

/// The number of local backups a document inside the team folder keeps at least.
constexpr int backupsKept = 5;

/// The patterns of `.stglobalignore`, in Syncthing's syntax: `(?i)` matches regardless of case
/// (Linux too), `(?d)` lets Syncthing delete system litter that would block removing a folder.
AppExport const std::vector<std::string>& ignorePatterns();

/// The folder from the preference, or an empty string when it is not set.
AppExport std::string folder();

/// Whether `path` (a file or a folder that exists, or a file whose folder exists) lies inside the
/// team folder. False when the folder is not set.
AppExport bool contains(const std::string& path);

/// The files a document saved as `target` uses that lie outside the team folder, as file names,
/// sorted and without repeats (FreeCAD-CH, folder sync item 3): the files of the documents its
/// links and expressions reach, and the absolute paths in its `PropertyFile` and `PropertyPath`
/// values. Paths under the installation, its resources and the user's data folder are exempt.
/// Empty when `target` is not inside the team folder. Links to documents that are not open
/// (broken links, already shown in the tree) are not seen.
AppExport std::vector<std::string> outsideFiles(const Document& doc, const std::string& target);

/// Warns in the report view when `outsideFiles` is not empty, once per document until the list
/// changes. Called by every save.
void warnOutside(const Document& doc, const std::string& target);

/// Writes the ignore list into `folder`: adds each missing pattern to `.stglobalignore` and the
/// line `#include .stglobalignore` to `.stignore` when it is missing (lines already there, the
/// user's own included, are kept). Returns an empty string, or what went wrong.
AppExport std::string apply(const std::string& folder);

/// What is wrong with the team folder setup, in one sentence, or an empty string: the folder is
/// not set, does not exist, or its `.stignore` / `.stglobalignore` lost a line `apply` writes.
AppExport std::string problem();

/// Applies the preference now and again each time it changes. Called once at start.
void watchPreference();

}  // namespace TeamFolder
}  // namespace App
