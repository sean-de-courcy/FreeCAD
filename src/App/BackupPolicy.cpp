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

#include <boost/algorithm/string/replace.hpp>
#include <boost/regex.hpp>
#include <string>

#include <Base/TimeInfo.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/FileInfo.h>
#include <Base/Interpreter.h>
#include <Base/Tools.h>
#include <Base/Writer.h>

#include "BackupPolicy.h"

#include <filesystem>
#include <system_error>
#include <thread>

#include <QByteArray>
#include <QtGlobal>
#ifdef _WIN32
# include <windows.h>
#else
# include <fcntl.h>
# include <unistd.h>
#endif

using namespace App;

// FreeCAD-CH (ops#640, slice A1, notes/files-saving-history-design.md section 3): a save writes
// its file under a temporary name, flushes it to the disk, keeps the old file by a hard link and
// puts the new one in place with one replacing rename. The document's name holds one complete
// file at every moment, the old or the new, also after a crash or a power cut.
namespace
{
void flushToDisk(const std::string& path)
{
#ifdef _WIN32
    HANDLE handle = INVALID_HANDLE_VALUE;
    // A virus scanner can hold the new file for a moment (A1 review T6)
    for (int attempt = 0;; ++attempt) {
        handle = CreateFileW(Base::FileInfo(path).toStdWString().c_str(),
                             GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                             nullptr,
                             OPEN_EXISTING,
                             FILE_ATTRIBUTE_NORMAL,
                             nullptr);
        if (handle != INVALID_HANDLE_VALUE) {
            break;
        }
        const DWORD error = GetLastError();
        if (attempt >= 10 || (error != ERROR_ACCESS_DENIED && error != ERROR_SHARING_VIOLATION)) {
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    if (handle == INVALID_HANDLE_VALUE) {
        throw Base::FileException("Cannot open the saved file to flush it", Base::FileInfo(path));
    }
    const bool flushed = FlushFileBuffers(handle) != 0;
    CloseHandle(handle);
#else
    const int fd = ::open(path.c_str(), O_RDWR);
    if (fd < 0) {
        throw Base::FileException("Cannot open the saved file to flush it", Base::FileInfo(path));
    }
# ifdef F_FULLFSYNC
    // macOS: fsync() leaves the data in the drive's cache
    bool flushed = ::fcntl(fd, F_FULLFSYNC) == 0 || ::fsync(fd) == 0;
# else
    bool flushed = ::fsync(fd) == 0;
# endif
    ::close(fd);
#endif
    if (!flushed) {
        throw Base::FileException("Cannot flush the saved file to the disk", Base::FileInfo(path));
    }
}

// Whether this thread's save has put its file in place (App::saveReplacedFile)
thread_local bool fileReplaced = false;

// One rename that replaces the target: no moment without a file under its name
void replaceFile(const std::string& source, const std::string& target)
{
#ifdef _WIN32
    const std::wstring from = Base::FileInfo(source).toStdWString();
    const std::wstring to = Base::FileInfo(target).toStdWString();
    // A virus scanner, an indexer or the sync tool can hold the target for a moment
    for (int attempt = 0;; ++attempt) {
        if (MoveFileExW(from.c_str(), to.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
            fileReplaced = true;
            return;
        }
        const DWORD error = GetLastError();
        if (attempt >= 10 || (error != ERROR_ACCESS_DENIED && error != ERROR_SHARING_VIOLATION)) {
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
#else
    if (::rename(source.c_str(), target.c_str()) == 0) {
        fileReplaced = true;
        // The rename itself on the disk
        const std::string dir = Base::FileInfo(target).dirPath();
        const int fd = ::open(dir.empty() ? "." : dir.c_str(), O_RDONLY);
        if (fd >= 0) {
            ::fsync(fd);
            ::close(fd);
        }
        return;
    }
#endif
    throw Base::FileException("Save interrupted: Cannot rename temporary file to project file",
                              Base::FileInfo(target));
}

// Keeps file under name as well, by a hard link (a copy where the filesystem has none), never
// over an existing file. The document's file stays where it is meanwhile.
bool keepFileNoErase(const Base::FileInfo& file, const std::string& name)
{
    if (name.empty() || Base::FileInfo(name).exists()) {
        return false;
    }
    const auto from = Base::FileInfo::stringToPath(file.filePath());
    const auto to = Base::FileInfo::stringToPath(name);
    std::error_code error;
    std::filesystem::create_hard_link(from, to, error);
    if (!error) {
        return true;
    }
    error.clear();
    std::filesystem::copy_file(from, to, std::filesystem::copy_options::none, error);
    return !error;
}
}  // namespace

bool App::saveReplacedFile()
{
    return fileReplaced;
}

bool App::saveFaultPoint(const char* step)
{
    static const std::string fault = qgetenv("FREECAD_CH_SAVE_FAULT").toStdString();
    if (fault.empty()) {
        return false;
    }
    const auto colon = fault.find(':');
    if (fault.compare(0, colon, step) != 0) {
        return false;
    }
    if (colon != std::string::npos && fault.compare(colon + 1, std::string::npos, "throw") == 0) {
        throw Base::FileException((std::string("Save fault injected at ") + step).c_str());
    }
    if (colon != std::string::npos && fault.compare(colon + 1, std::string::npos, "cut") == 0) {
        return true;
    }
    std::_Exit(86);
}

void BackupPolicy::setPolicy(const Policy p)
{
    policy = p;
}
void BackupPolicy::setNumberOfFiles(const int count)
{
    numberOfFiles = count;
}
void BackupPolicy::useBackupExtension(const bool on)
{
    useFCBakExtension = on;
}
void BackupPolicy::setDateFormat(const std::string& fmt)
{
    saveBackupDateFormat = fmt;
}
void BackupPolicy::apply(const std::string& sourcename, const std::string& targetname)
{
    fileReplaced = false;
    flushToDisk(sourcename);
    saveFaultPoint("flushed");
    switch (policy) {
        case Standard:
            applyStandard(sourcename, targetname);
            break;
        case TimeStamp:
            applyTimeStamp(sourcename, targetname);
            break;
    }
    saveFaultPoint("done");
}

void BackupPolicy::applyStandard(const std::string& sourcename, const std::string& targetname) const
{
    // if saving the project data succeeded rename to the actual file name
    if (Base::FileInfo fi(targetname); fi.exists()) {
        if (numberOfFiles > 0) {
            int nSuff = 0;
            std::string fn = fi.fileName();
            Base::FileInfo di(fi.dirPath());
            std::vector<Base::FileInfo> backup;
            std::vector<Base::FileInfo> files = di.getDirectoryContent();
            for (const Base::FileInfo& it : files) {
                if (std::string file = it.fileName(); file.substr(0, fn.length()) == fn) {
                    // starts with the same file name
                    std::string suf(file.substr(fn.length()));
                    if (!suf.empty()) {
                        std::string::size_type nPos = suf.find_first_not_of("0123456789");
                        if (nPos == std::string::npos) {
                            // store all backup files
                            backup.push_back(it);
                            nSuff =
                                std::max<int>(nSuff, static_cast<int>(std::atol(suf.c_str())));
                        }
                    }
                }
            }

            // FreeCAD-CH (ops#640, A1): the new backup is kept before the oldest goes, so a backup
            // that can't be kept leaves the earlier ones (A1 fix review); it then takes the
            // oldest's name, as upstream's did
            std::stringstream str;
            str << fi.filePath() << (nSuff + 1);
            fn = str.str();
            if (!keepFileNoErase(fi, fn)) {
                // The old file is never lost without its backup (A1 review): no save
                throw Base::FileException("Cannot keep the previous file as a backup: not saved",
                                          fi);
            }

            if (!backup.empty() && static_cast<int>(backup.size()) >= numberOfFiles) {
                // delete the oldest backup file we found
                Base::FileInfo del = backup.front();
                for (const Base::FileInfo& it : backup) {
                    if (it.lastModified() < del.lastModified()) {
                        del = it;
                    }
                }
                if (del.deleteFile()) {
                    std::error_code error;  // kept under its new name if this fails
                    std::filesystem::rename(Base::FileInfo::stringToPath(fn),
                                            Base::FileInfo::stringToPath(del.filePath()),
                                            error);
                }
            }
        }
        // No backups: the rename below replaces the file
    }

    if (saveFaultPoint("kept")) {
        std::error_code error;  // the temporary file lost (a virus scanner's quarantine)
        std::filesystem::remove(Base::FileInfo::stringToPath(sourcename), error);
    }
    replaceFile(sourcename, targetname);
    saveFaultPoint("replaced");
}

void BackupPolicy::applyTimeStamp(const std::string& sourcename, const std::string& targetname)
{
    Base::FileInfo fi(targetname);

    std::string fn = sourcename;
    std::string ext = fi.extension();
    std::string bn;   // full path with no extension but with "."
    std::string pbn;  // base name of the project + "."
    if (!ext.empty()) {
        bn = fi.filePath().substr(0, fi.filePath().length() - ext.length());
        pbn = fi.fileName().substr(0, fi.fileName().length() - ext.length());
    }
    else {
        bn = fi.filePath() + ".";
        pbn = fi.fileName() + ".";
    }

    bool backupManagementError = false;  // Note error and report at the end
    if (fi.exists()) {
        if (numberOfFiles > 0) {
            // replace . by - in format to avoid . between base name and extension
            boost::replace_all(saveBackupDateFormat, ".", "-");
            // FreeCAD-CH (ops#640, A1): the extra backups go after the new one is kept, so a
            // backup that can't be kept leaves the earlier ones (A1 fix review); the new one is
            // never among those removed
            std::string keptName;
            auto removeExtraBackups = [&]() {
                // Remove all extra backups
                std::string filename = fi.fileName();
                Base::FileInfo di(fi.dirPath());
                std::vector<Base::FileInfo> backup;
                std::vector<Base::FileInfo> files = di.getDirectoryContent();
                for (const Base::FileInfo& it : files) {
                    if (it.isFile() && it.fileName() != keptName) {
                        std::string file = it.fileName();
                        std::string fext = it.extension();
                        std::string fextUp = fext;
                        std::transform(fextUp.begin(),
                                       fextUp.end(),
                                       fextUp.begin(),
                                       static_cast<int (*)(int)>(toupper));
                        // re-enforcing identification of the backup file


                        // old case : the name starts with the full name of the project and
                        // follows with numbers
                        if ((startsWith(file, filename) && (file.length() > filename.length())
                             && checkDigits(file.substr(filename.length())))
                            ||
                            // .FCBak case : The bame starts with the base name of the project +
                            // "."
                            // + complement with no "." + ".FCBak"
                            ((fextUp == "FCBAK") && startsWith(file, pbn)
                             && (checkValidComplement(file, pbn, fext)))) {
                            backup.push_back(it);
                        }
                    }
                }

                if (!backup.empty() && static_cast<int>(backup.size()) >= numberOfFiles) {
                    std::sort(backup.begin(), backup.end(), fileComparisonByDate);
                    // delete the oldest backup file we found
                    // Base::FileInfo del = backup.front();
                    int nb = 0;
                    for (Base::FileInfo& it : backup) {
                        nb++;
                        if (nb >= numberOfFiles) {
                            try {
                                if (!it.deleteFile()) {
                                    backupManagementError = true;
                                    Base::Console().warning("Cannot remove backup file : %s\n",
                                                            it.fileName().c_str());
                                }
                            }
                            catch (...) {
                                backupManagementError = true;
                                Base::Console().warning("Cannot remove backup file : %s\n",
                                                        it.fileName().c_str());
                            }
                        }
                    }
                }
            };  // end remove backup

            // create a new backup file
            {
                int ext2 = 1;
                if (useFCBakExtension) {
                    std::stringstream str;
                    Base::TimeInfo ti = fi.lastModified();
                    time_t s = ti.getTime_t();
                    std::tm local_tm {};
#if defined(_WIN32)
                    localtime_s(&local_tm, &s);  // Windows
#else
                    localtime_r(&s, &local_tm);  // POSIX
#endif
                    constexpr size_t bufferLength = 128;
                    std::array<char, bufferLength> buffer {};
                    if (size_t bytes = std::strftime(buffer.data(),
                                                     bufferLength,
                                                     saveBackupDateFormat.c_str(),
                                                     &local_tm);
                        bytes == 0) {
                        // An error here is typically that we over-ran the maximum buffer length (
                        // which should be a *very* unusual condition).
                        Base::Console().error("Failed to create valid backup file name from format string:\n");
                        Base::Console().error(saveBackupDateFormat.c_str());
                        const auto knownGoodFormat {"%Y-%m-%d_%H-%M-%S"};
                        std::strftime(buffer.data(), bufferLength, knownGoodFormat, &local_tm);
                    }
                    std::string timestamp = buffer.data();

                    auto isInvalidChar = [](char ch) {
#if defined(_WIN32)
                        return std::string_view("<>:\"/\\|?*").find(ch) != std::string_view::npos;
#else
                        return ch == '/';
#endif
                    };

                    if (std::ranges::any_of(timestamp, isInvalidChar)) {
                        std::ranges::replace_if(timestamp, isInvalidChar, '-');

                        static bool warned = false;
                        if (!warned) {
                            Base::Console().warning(
                                "Backup filename contained invalid characters. "
                                "Automatically replaced with '-'. "
                                "Consider changing the date format in Preferences/Document.\n");
                            warned = true;
                        }
                    }

                    str << bn << timestamp;

                    fn = str.str();
                    bool done = false;

                    if ((fn.empty()) || (fn[fn.length() - 1] == ' ')
                        || (fn[fn.length() - 1] == '-')) {
                        if (fn[fn.length() - 1] == ' ') {
                            fn = fn.substr(0, fn.length() - 1);
                        }
                    }
                    else {
                        if (!keepFileNoErase(fi, fn + ".FCBak")) {
                            fn = fn + "-";
                        }
                        else {
                            keptName = Base::FileInfo(fn + ".FCBak").fileName();
                            done = true;
                        }
                    }

                    if (!done) {
                        while (ext2 < numberOfFiles + 10) {
                            if (keepFileNoErase(fi, fn + std::to_string(ext2) + ".FCBak")) {
                                keptName =
                                    Base::FileInfo(fn + std::to_string(ext2) + ".FCBak").fileName();
                                break;
                            }
                            ext2++;
                        }
                    }
                }
                else {
                    // changed but simpler and solves also the delay sometimes introduced by
                    // google drive
                    while (ext2 < numberOfFiles + 10) {
                        // linux just replace the file if exists, and then the existence is to
                        // be tested before rename
                        if (keepFileNoErase(fi, fi.filePath() + std::to_string(ext2))) {
                            keptName = Base::FileInfo(fi.filePath() + std::to_string(ext2)).fileName();
                            break;
                        }
                        ext2++;
                    }
                }

                if (ext2 >= numberOfFiles + 10) {
                    // The old file is never lost without its backup (A1 review): no save
                    throw Base::FileException(
                        "Cannot keep the previous file as a backup: not saved", fi);
                }
            }
            removeExtraBackups();
        }
        // No backups: the rename below replaces the file
    }

    if (saveFaultPoint("kept")) {
        std::error_code error;  // the temporary file lost (a virus scanner's quarantine)
        std::filesystem::remove(Base::FileInfo::stringToPath(sourcename), error);
    }
    replaceFile(sourcename, targetname);
    saveFaultPoint("replaced");

    if (backupManagementError) {
        throw Base::FileException(
            "Warning: Save complete, but error while managing backup history.",
            fi);
    }
}

bool BackupPolicy::fileComparisonByDate(const Base::FileInfo& i, const Base::FileInfo& j)
{
    return (i.lastModified() > j.lastModified());
}

bool BackupPolicy::startsWith(const std::string& st1, const std::string& st2) const
{
    return st1.substr(0, st2.length()) == st2;
}

bool BackupPolicy::checkValidString(const std::string& cmpl, const boost::regex& e) const
{
    boost::smatch what;
    const bool res = boost::regex_search(cmpl, what, e);
    return res;
}

bool BackupPolicy::checkValidComplement(const std::string& file,
                          const std::string& pbn,
                          const std::string& ext) const
{
    const std::string cmpl =
        file.substr(pbn.length(), file.length() - pbn.length() - ext.length() - 1);
    const boost::regex e(R"(^[^.]*$)");
    return checkValidString(cmpl, e);
}

bool BackupPolicy::checkDigits(const std::string& cmpl) const
{
    const boost::regex e(R"(^[0-9]*$)");
    return checkValidString(cmpl, e);
}

bool BackupPolicy::renameFileNoErase(Base::FileInfo fi, const std::string& newName)
{
    // linux just replaces the file if it exists, so the existence is to be tested before rename
    const Base::FileInfo nf(newName);
    if (!nf.exists()) {
        return fi.renameFile(newName.c_str());
    }
    return false;
}
