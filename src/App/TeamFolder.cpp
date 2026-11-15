// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD-CH fork (ops#640, folder sync item 2).

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <sstream>

#include <Base/Console.h>
#include <Base/FileInfo.h>
#include <Base/Parameter.h>

#include "Application.h"
#include "TeamFolder.h"

namespace fs = std::filesystem;

namespace App::TeamFolder
{

namespace
{

constexpr const char* includeLine = "#include .stglobalignore";

ParameterGrp::handle documentParameters()
{
    return GetApplication().GetParameterGroupByPath("User parameter:BaseApp/Preferences/Document");
}

std::string trimmed(const std::string& line)
{
    const auto first = line.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return {};
    }
    const auto last = line.find_last_not_of(" \t\r\n");
    return line.substr(first, last - first + 1);
}

// The file's lines, trimmed; `exists` says whether it could be read
std::vector<std::string> readLines(const fs::path& file, bool& exists, bool& endsInNewline)
{
    std::vector<std::string> lines;
    std::ifstream in(file, std::ios::binary);
    exists = in.is_open();
    endsInNewline = true;
    if (!exists) {
        return lines;
    }
    std::stringstream buffer;
    buffer << in.rdbuf();
    const std::string text = buffer.str();
    endsInNewline = text.empty() || text.back() == '\n';
    std::istringstream stream(text);
    std::string line;
    while (std::getline(stream, line)) {
        lines.push_back(trimmed(line));
    }
    return lines;
}

bool hasLine(const std::vector<std::string>& lines, const std::string& wanted)
{
    return std::find(lines.begin(), lines.end(), wanted) != lines.end();
}

// Appends the lines of `wanted` that `file` lacks; returns false when it can't write
bool appendMissing(const fs::path& file, const std::vector<std::string>& wanted, const char* header)
{
    bool exists = false;
    bool endsInNewline = true;
    const auto lines = readLines(file, exists, endsInNewline);
    std::vector<std::string> missing;
    for (const auto& line : wanted) {
        if (!hasLine(lines, line)) {
            missing.push_back(line);
        }
    }
    if (missing.empty()) {
        return true;
    }
    std::ofstream out(file, std::ios::binary | std::ios::app);
    if (!out) {
        return false;
    }
    if (!endsInNewline) {
        out << '\n';
    }
    if (header && (!exists || lines.empty())) {
        out << header << '\n';
    }
    for (const auto& line : missing) {
        out << line << '\n';
    }
    out.close();
    return static_cast<bool>(out);
}

class PreferenceWatcher: public ParameterGrp::ObserverType
{
public:
    void OnChange(Base::Subject<const char*>& /*caller*/, const char* reason) override
    {
        if (reason && std::string(reason) == "TeamFolder") {
            applyPreference();
        }
    }

    static void applyPreference()
    {
        const std::string path = folder();
        if (path.empty()) {
            return;
        }
        const std::string error = apply(path);
        if (!error.empty()) {
            Base::Console().warning("Team folder: %s\n", error.c_str());
        }
    }
};

}  // namespace

const std::vector<std::string>& ignorePatterns()
{
    static const std::vector<std::string> patterns {
        "(?i)*.fctmp",        // A1's temporary save file
        "(?i)*.FCBak",        // backups, "Use date and FCBak extension" on
        "(?i)*.FCStd[0-9]*",  // backups with it off: <name>.FCStd1, ... (ops#705)
        "(?d).DS_Store",
        "(?d)._*",
        "(?d)Thumbs.db",
        "(?d)desktop.ini",
    };
    return patterns;
}

std::string folder()
{
    return trimmed(documentParameters()->GetASCII("TeamFolder", ""));
}

bool contains(const std::string& path)
{
    const std::string team = folder();
    if (team.empty() || path.empty()) {
        return false;
    }
    const fs::path teamPath = Base::FileInfo::stringToPath(team);
    std::error_code error;
    fs::path current = fs::absolute(Base::FileInfo::stringToPath(path), error);
    if (error) {
        return false;
    }
    while (!current.empty()) {
        if (fs::equivalent(current, teamPath, error)) {
            return true;
        }
        const fs::path parent = current.parent_path();
        if (parent == current) {
            break;
        }
        current = parent;
    }
    return false;
}

std::string apply(const std::string& team)
{
    const fs::path root = Base::FileInfo::stringToPath(team);
    std::error_code error;
    if (!fs::is_directory(root, error)) {
        return "the folder '" + team + "' does not exist";
    }
    if (!appendMissing(root / ".stglobalignore",
                       ignorePatterns(),
                       "// FreeCAD-CH: files that stay on the computer that made them "
                       "(synced; each device's .stignore includes it)")) {
        return "could not write .stglobalignore in '" + team + "'";
    }
    if (!appendMissing(root / ".stignore", {includeLine}, nullptr)) {
        return "could not write .stignore in '" + team + "'";
    }
    return {};
}

std::string problem()
{
    const std::string team = folder();
    if (team.empty()) {
        return "The team folder is not set (Preferences, Document): backups and temporary files "
               "would sync to the other computers.";
    }
    const fs::path root = Base::FileInfo::stringToPath(team);
    std::error_code error;
    if (!fs::is_directory(root, error)) {
        return "The team folder '" + team + "' does not exist.";
    }
    bool exists = false;
    bool endsInNewline = true;
    if (!hasLine(readLines(root / ".stignore", exists, endsInNewline), includeLine)) {
        return "The team folder's .stignore no longer includes .stglobalignore: backups and "
               "temporary files would sync. Set the team folder again to restore it.";
    }
    const auto global = readLines(root / ".stglobalignore", exists, endsInNewline);
    for (const auto& pattern : ignorePatterns()) {
        if (!hasLine(global, pattern)) {
            return "The team folder's .stglobalignore lost the line '" + pattern
                + "'. Set the team folder again to restore it.";
        }
    }
    return {};
}

void watchPreference()
{
    // Never deleted, as Link's parameter observer: the parameter group outlives static destructors
    static auto* watcher = [] {
        auto* created = new PreferenceWatcher;
        documentParameters()->Attach(created);
        return created;
    }();
    (void)watcher;
    // A folder set while FreeCAD-CH was closed, or a list someone trimmed, is put right at start
    PreferenceWatcher::applyPreference();
}

}  // namespace App::TeamFolder
