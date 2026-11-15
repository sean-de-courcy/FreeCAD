// SPDX-License-Identifier: LGPL-2.1-or-later

/****************************************************************************
 *   Copyright (c) 2020 Werner Mayer <wmayer[at]users.sourceforge.net>      *
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 *   FreeCAD is distributed in the hope that it will be useful, but         *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
 *   Lesser General Public License for more details.                        *
 *                                                                          *
 *   You should have received a copy of the GNU Lesser General Public       *
 *   License along with FreeCAD. If not, see                                *
 *   <https://www.gnu.org/licenses/>.                                       *
 *                                                                          *
 ***************************************************************************/

#include "FCGlobal.h"

#include <boost/regex.hpp>
#include <string>
#include <Base/FileInfo.h>

namespace App
{
// Helper class to handle different backup policies: originally a private class in Document.cpp,
// and extracted for public access to enable direct testing since the logic involved is quite
// complex.
class AppExport BackupPolicy
{
public:
    enum Policy
    {
        Standard,
        TimeStamp
    };
    void setPolicy(const Policy p);
    void setNumberOfFiles(const int count);
    void useBackupExtension(const bool on);
    void setDateFormat(const std::string& fmt);
    void apply(const std::string& sourcename, const std::string& targetname);

private:
    void applyStandard(const std::string& sourcename, const std::string& targetname) const;
    void applyTimeStamp(const std::string& sourcename, const std::string& targetname);
    static bool fileComparisonByDate(const Base::FileInfo& i, const Base::FileInfo& j);
    bool startsWith(const std::string& st1, const std::string& st2) const;
    bool checkValidString(const std::string& cmpl, const boost::regex& e) const;
    bool checkValidComplement(const std::string& file,
                              const std::string& pbn,
                              const std::string& ext) const;
    bool checkDigits(const std::string& cmpl) const;
    bool renameFileNoErase(Base::FileInfo fi, const std::string& newName);

private:
    Policy policy {Standard};
    int numberOfFiles {1};
    bool useFCBakExtension {true};
    std::string saveBackupDateFormat {"%Y%m%d-%H%M%S"};
};

/// FreeCAD-CH (ops#640, slice A1): a test's way to stop a save at one of its steps. With the
/// environment variable FREECAD_CH_SAVE_FAULT set to `<step>` the process ends there at once, as
/// if it were killed; with `<step>:throw` the save throws a Base::FileException there. The steps
/// in their order: write (the temporary file half written), written, flushed, kept (the old file
/// kept as a backup), replaced (the new file under the document's name), done. With
/// `<step>:cut` it returns true and the caller damages what it just wrote, as a short write
/// would: at `write` the stream goes bad, at `written` the temporary file loses its end, at
/// `kept` the temporary file is removed. A throw at `replaced` or `done` comes after the file is
/// in place: the save reports it as a warning and counts as done. Not exported.
bool saveFaultPoint(const char* step);

/// FreeCAD-CH (ops#640, A1 fix review 3): whether this thread's last BackupPolicy::apply put the
/// new file under the document's name (reset when apply starts). Not exported.
bool saveReplacedFile();

/// FreeCAD-CH (ops#640, slice A1): the writer mode `<copyUidMode><uuid>` that Save a Copy sets,
/// so that the copy's Document.xml holds a document id of its own (PropertyUUID::Save)
constexpr const char* copyUidMode = "CopyUid=";
}  // namespace App