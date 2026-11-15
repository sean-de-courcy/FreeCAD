// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD-CH fork (ops#640, folder sync item 6, design A's B5).

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>

#include <QByteArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSysInfo>
#include <QString>
#include <QtGlobal>

#ifdef FC_OS_WIN32
# ifndef NOMINMAX
#  define NOMINMAX
# endif
# ifndef WIN32_LEAN_AND_MEAN
#  define WIN32_LEAN_AND_MEAN
# endif
# include <windows.h>
#else
# include <cerrno>
# include <csignal>
# include <sys/types.h>
# include <unistd.h>
#endif

#include <Base/Console.h>
#include <Base/FileInfo.h>
#include <Base/Parameter.h>

#include "Application.h"
#include "Document.h"
#include "DocumentPresence.h"
#include "TeamFolder.h"

namespace fs = std::filesystem;

namespace App::DocumentPresence
{

namespace
{

// The marker each open document of this process has written, by document
std::map<const Document*, std::string>& written()
{
    static std::map<const Document*, std::string> markers;
    return markers;
}

long long now()
{
    using namespace std::chrono;
    return duration_cast<seconds>(system_clock::now().time_since_epoch()).count();
}

long long ownPid()
{
#ifdef FC_OS_WIN32
    return static_cast<long long>(GetCurrentProcessId());
#else
    return static_cast<long long>(getpid());
#endif
}

bool processAlive(long long pid)
{
    if (pid <= 0) {
        return false;
    }
#ifdef FC_OS_WIN32
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, static_cast<DWORD>(pid));
    if (!process) {
        // Access denied means it exists (another user's process); anything else means it is gone
        return GetLastError() == ERROR_ACCESS_DENIED;
    }
    DWORD code = 0;
    const bool alive = GetExitCodeProcess(process, &code) && code == STILL_ACTIVE;
    CloseHandle(process);
    return alive;
#else
    return kill(static_cast<pid_t>(pid), 0) == 0 || errno == EPERM;
#endif
}

// Who has the document open: the preferences' author, else the system's user name (as A1 saves)
std::string userName()
{
    std::string author = GetApplication()
                             .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Document")
                             ->GetASCII("prefAuthor", "");
    if (!author.empty()) {
        return author;
    }
#ifdef FC_OS_WIN32
    return qEnvironmentVariable("USERNAME").toStdString();
#else
    QString name = qEnvironmentVariable("USER");
    if (name.isEmpty()) {
        name = qEnvironmentVariable("LOGNAME");
    }
    return name.toStdString();
#endif
}

std::string lowered(std::string text)
{
    std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return text;
}

// The document's path relative to the team folder, with '/', or empty when it is not inside
std::string relativeName(const std::string& documentPath)
{
    if (documentPath.empty() || !TeamFolder::contains(documentPath)) {
        return {};
    }
    std::error_code error;
    const fs::path team = fs::weakly_canonical(Base::FileInfo::stringToPath(TeamFolder::folder()), error);
    if (error) {
        return {};
    }
    const fs::path file = fs::weakly_canonical(Base::FileInfo::stringToPath(documentPath), error);
    if (error) {
        return {};
    }
    const fs::path relative = file.lexically_relative(team);
    if (relative.empty() || *relative.begin() == "..") {
        return {};
    }
    std::string name = Base::FileInfo::pathToString(relative);
    std::replace(name.begin(), name.end(), '\\', '/');
    return name;
}

// A stable short code for a name (FNV-1a), so one document's markers have one file name prefix
std::string shortCode(const std::string& text)
{
    std::uint32_t hash = 2166136261U;
    for (unsigned char c : text) {
        hash ^= c;
        hash *= 16777619U;
    }
    char buffer[9];
    std::snprintf(buffer, sizeof(buffer), "%08x", hash);
    return buffer;
}

std::string safeForFileName(const std::string& text)
{
    std::string result;
    for (unsigned char c : text) {
        result += (std::isalnum(c) || c == '-' || c == '_') ? static_cast<char>(c) : '_';
    }
    return result.empty() ? std::string("_") : result;
}

bool readMarker(const fs::path& path, Marker& marker)
{
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        return false;
    }
    std::stringstream buffer;
    buffer << in.rdbuf();
    const std::string text = buffer.str();
    const QJsonDocument json = QJsonDocument::fromJson(QByteArray(text.data(), static_cast<int>(text.size())));
    if (!json.isObject()) {
        return false;
    }
    const QJsonObject object = json.object();
    marker.file = object.value(QLatin1String("file")).toString().toStdString();
    marker.user = object.value(QLatin1String("user")).toString().toStdString();
    marker.host = object.value(QLatin1String("host")).toString().toStdString();
    marker.pid = static_cast<long long>(object.value(QLatin1String("pid")).toDouble());
    marker.time = static_cast<long long>(object.value(QLatin1String("time")).toDouble());
    marker.path = Base::FileInfo::pathToString(path);
    return !marker.file.empty() && !marker.host.empty();
}

void removeFile(const std::string& path)
{
    std::error_code error;
    fs::remove(Base::FileInfo::stringToPath(path), error);
}

// Writes the marker through a temporary `.fctmp` (which the ignore list keeps off the sync) and
// one rename, so the other computer never reads half a marker
bool writeMarker(const std::string& path, const std::string& relative)
{
    QJsonObject object;
    object.insert(QLatin1String("file"), QString::fromStdString(relative));
    object.insert(QLatin1String("user"), QString::fromStdString(userName()));
    object.insert(QLatin1String("host"), QString::fromStdString(hostName()));
    object.insert(QLatin1String("pid"), static_cast<double>(ownPid()));
    object.insert(QLatin1String("time"), static_cast<double>(now()));
    object.insert(QLatin1String("app"), QLatin1String("FreeCAD-CH"));
    const QByteArray text = QJsonDocument(object).toJson(QJsonDocument::Compact);

    const fs::path target = Base::FileInfo::stringToPath(path);
    std::error_code error;
    fs::create_directories(target.parent_path(), error);
    fs::path temporary = target;
    temporary += ".fctmp";
    {
        std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
        if (!out) {
            return false;
        }
        out.write(text.constData(), text.size());
        if (!out) {
            return false;
        }
    }
    fs::rename(temporary, target, error);
    if (error) {
        fs::remove(temporary, error);
        return false;
    }
    return true;
}

std::string markerPathFor(const std::string& documentPath)
{
    const std::string folder = markerFolder(documentPath);
    if (folder.empty()) {
        return {};
    }
    const std::string relative = relativeName(documentPath);
    const fs::path stem = Base::FileInfo::stringToPath(documentPath).stem();
    const std::string name = safeForFileName(Base::FileInfo::pathToString(stem)) + "-"
        + shortCode(lowered(relative)) + "-" + safeForFileName(hostName()) + "-"
        + std::to_string(ownPid()) + ".json";
    return Base::FileInfo::pathToString(Base::FileInfo::stringToPath(folder) / Base::FileInfo::stringToPath(name));
}

void update(const Document& document)
{
    auto& markers = written();
    const std::string file = document.FileName.getValue();
    const bool exists = !file.empty() && Base::FileInfo(file).exists();
    const std::string path = exists ? markerPathFor(file) : std::string();
    auto it = markers.find(&document);
    if (it != markers.end() && it->second != path) {
        removeFile(it->second);
        markers.erase(it);
    }
    if (path.empty()) {
        return;
    }
    if (writeMarker(path, relativeName(file))) {
        markers[&document] = path;
    }
    else {
        Base::Console().log("Presence: could not write %s\n", path.c_str());
    }
}

}  // namespace

std::string hostName()
{
    std::string name = QSysInfo::machineHostName().toStdString();
    return name.empty() ? std::string("unknown") : name;
}

std::string markerFolder(const std::string& documentPath)
{
    if (relativeName(documentPath).empty()) {
        return {};
    }
    const fs::path folder = Base::FileInfo::stringToPath(TeamFolder::folder()) / ".fcch" / "open";
    return Base::FileInfo::pathToString(folder);
}

std::vector<Marker> others(const std::string& documentPath)
{
    std::vector<Marker> result;
    const std::string folder = markerFolder(documentPath);
    if (folder.empty()) {
        return result;
    }
    const std::string relative = lowered(relativeName(documentPath));
    const std::string host = lowered(hostName());
    const long long pid = ownPid();
    const long long current = now();

    std::error_code error;
    fs::directory_iterator it(Base::FileInfo::stringToPath(folder), error);
    if (error) {
        return result;
    }
    for (const auto& entry : it) {
        if (!entry.is_regular_file(error) || entry.path().extension() != ".json") {
            continue;
        }
        Marker marker;
        if (!readMarker(entry.path(), marker)) {
            continue;
        }
        const bool thisHost = lowered(marker.host) == host;
        if (thisHost && marker.pid != pid && !processAlive(marker.pid)) {
            // Left by a FreeCAD on this computer that crashed or was killed
            removeFile(marker.path);
            continue;
        }
        if (lowered(marker.file) != relative || (thisHost && marker.pid == pid)) {
            continue;
        }
        if (current - marker.time < freshSeconds) {
            result.push_back(marker);
        }
    }
    std::sort(result.begin(), result.end(), [](const Marker& a, const Marker& b) {
        return a.time > b.time;
    });
    return result;
}

std::string describe(const std::vector<Marker>& markers)
{
    if (markers.empty()) {
        return {};
    }
    const std::string own = lowered(hostName());
    std::string text;
    for (std::size_t i = 0; i < markers.size(); ++i) {
        const Marker& marker = markers[i];
        if (i > 0) {
            text += i + 1 == markers.size() ? " and " : ", ";
        }
        const std::string user = marker.user.empty() ? std::string("Someone") : marker.user;
        if (lowered(marker.host) == own) {
            text += user + " (another FreeCAD on this computer)";
        }
        else {
            text += user + " on " + marker.host;
        }
    }
    return text + (markers.size() == 1 ? " has" : " have") + " this document open";
}

void refresh()
{
    auto& markers = written();
    std::vector<const Document*> open;
    for (Document* document : GetApplication().getDocuments()) {
        open.push_back(document);
        update(*document);
    }
    for (auto it = markers.begin(); it != markers.end();) {
        if (std::find(open.begin(), open.end(), it->first) == open.end()) {
            removeFile(it->second);
            it = markers.erase(it);
        }
        else {
            ++it;
        }
    }
}

void remove(const Document& document)
{
    auto& markers = written();
    auto it = markers.find(&document);
    if (it != markers.end()) {
        removeFile(it->second);
        markers.erase(it);
    }
}

std::string ownMarker(const Document& document)
{
    auto& markers = written();
    auto it = markers.find(&document);
    return it == markers.end() ? std::string() : it->second;
}

void start()
{
    Application& app = GetApplication();
    app.signalFinishRestoreDocument.connect([](const Document& document) { update(document); });
    app.signalFinishSaveDocument.connect([](const Document& document, const std::string&) {
        update(document);
    });
    app.signalDeleteDocument.connect([](const Document& document) { remove(document); });
}

}  // namespace App::DocumentPresence
