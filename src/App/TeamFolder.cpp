// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD-CH fork (ops#640, folder sync item 2).

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <map>
#include <mutex>
#include <set>
#include <sstream>

#include <Base/Console.h>
#include <Base/FileInfo.h>
#include <Base/Parameter.h>

#include "Application.h"
#include "Document.h"
#include "DocumentObject.h"
#include "PropertyFile.h"
#include "PropertyLinks.h"
#include "PropertyStandard.h"
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

// Why `team` can't be the team folder, or an empty string (review F1, F3: a relative path would
// follow the working directory, a file is not a folder)
std::string unusable(const std::string& team)
{
    const fs::path root = Base::FileInfo::stringToPath(team);
    std::error_code error;
    if (!root.is_absolute()) {
        return "'" + team + "' is not an absolute folder path";
    }
    if (!fs::exists(root, error)) {
        return "'" + team + "' does not exist";
    }
    if (!fs::is_directory(root, error)) {
        return "'" + team + "' is not a folder";
    }
    return {};
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

namespace
{

/// Whether `path` is `root` or lies under it; both compared as the file system sees them
/// (`fs::equivalent`, so case and links don't matter), the parts of `path` that don't exist skipped
bool under(const fs::path& path, const std::string& root)
{
    if (root.empty() || path.empty()) {
        return false;
    }
    const fs::path rootPath = Base::FileInfo::stringToPath(root);
    if (!rootPath.is_absolute()) {
        return false;
    }
    std::error_code error;
    fs::path current = fs::absolute(path, error);
    if (error) {
        return false;
    }
    while (!current.empty()) {
        if (fs::equivalent(current, rootPath, error)) {
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

/// A file the other computer has too: the installation, its resources, the user's data folder
bool exempt(const fs::path& path)
{
    return under(path, Application::getResourceDir()) || under(path, Application::getHomePath())
        || under(path, Application::getUserAppDataDir());
}

std::string fileName(const fs::path& path)
{
    return Base::FileInfo::pathToString(path.filename());
}

}  // namespace

bool contains(const std::string& path)
{
    if (path.empty()) {
        return false;
    }
    return under(Base::FileInfo::stringToPath(path), folder());
}

std::vector<std::string> outsideFiles(const Document& doc, const std::string& target)
{
    std::vector<std::string> names;
    if (!contains(target)) {
        return names;
    }
    const std::string team = folder();
    auto outside = [&](const fs::path& path) {
        if (!path.is_absolute() || under(path, team) || exempt(path)) {
            return;
        }
        names.push_back(fileName(path));
    };
    // Links and expressions to other documents (the out list holds both, hidden-scope expression
    // links included): XLinks save their path relative to the document, which only reaches the
    // same file on the other computer while both lie in the team folder
    std::set<const Document*> linked;
    for (const DocumentObject* object : doc.getObjects()) {
        for (const DocumentObject* target : object->getOutList()) {
            const Document* other = target ? target->getDocument() : nullptr;
            if (other && other != &doc) {
                linked.insert(other);
            }
        }
    }
    for (const Document* other : linked) {
        const char* file = other->FileName.getValue();
        if (file && *file) {
            outside(Base::FileInfo::stringToPath(file));
        }
    }
    // File and folder paths saved as written: absolute ones name this computer's disk
    std::vector<Property*> properties;
    for (const DocumentObject* object : doc.getObjects()) {
        properties.clear();
        object->getPropertyList(properties);
        for (const Property* property : properties) {
            if (const auto* file = freecad_cast<const PropertyFile*>(property)) {
                const char* value = file->getValue();
                if (value && *value) {
                    outside(Base::FileInfo::stringToPath(value));
                }
            }
            else if (const auto* folderPath = freecad_cast<const PropertyPath*>(property)) {
                outside(folderPath->getValue());
            }
        }
    }
    std::sort(names.begin(), names.end());
    names.erase(std::unique(names.begin(), names.end()), names.end());
    return names;
}

void warnOutside(const Document& doc, const std::string& target)
{
    // The last list warned per document (by Uid), so a document warns again only when it changes
    static std::mutex mutex;
    static std::map<std::string, std::string> warned;
    const auto names = outsideFiles(doc, target);
    std::string list;
    for (const auto& name : names) {
        list += (list.empty() ? "" : ", ") + name;
    }
    const std::string key = doc.Uid.getValueStr();
    {
        std::lock_guard<std::mutex> lock(mutex);
        auto& last = warned[key];
        if (last == list) {
            return;
        }
        last = list;
    }
    if (!list.empty()) {
        Base::Console().warning("%s uses files outside the team folder (%s); the other computer "
                                "will not find them.\n",
                                fileName(Base::FileInfo::stringToPath(target)).c_str(),
                                list.c_str());
    }
}

std::string apply(const std::string& team)
{
    const std::string why = unusable(team);
    if (!why.empty()) {
        return why;
    }
    const fs::path root = Base::FileInfo::stringToPath(team);
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
    const std::string why = unusable(team);
    if (!why.empty()) {
        return "The team folder " + why + ".";
    }
    const fs::path root = Base::FileInfo::stringToPath(team);
    bool exists = false;
    bool endsInNewline = true;
    if (!hasLine(readLines(root / ".stignore", exists, endsInNewline), includeLine)) {
        return "The team folder's .stignore no longer includes .stglobalignore: backups and "
               "temporary files would sync. FreeCAD-CH restores it at its next start, or when "
               "the team folder is set again.";
    }
    const auto global = readLines(root / ".stglobalignore", exists, endsInNewline);
    for (const auto& pattern : ignorePatterns()) {
        if (!hasLine(global, pattern)) {
            return "The team folder's .stglobalignore lost the line '" + pattern
                + "'. FreeCAD-CH restores it at its next start, or when the team folder is set "
                  "again.";
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
