// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ElementFingerprint.h"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <locale>
#include <sstream>

namespace Data
{

namespace
{

constexpr char fieldDelimiter = '|';
constexpr char listDelimiter = ',';
constexpr const char* emptyField = "_";
constexpr int fieldCount = 7;

std::vector<std::string_view> split(std::string_view text, char delimiter)
{
    std::vector<std::string_view> parts;
    std::size_t start = 0;
    while (true) {
        auto end = text.find(delimiter, start);
        if (end == std::string_view::npos) {
            parts.push_back(text.substr(start));
            return parts;
        }
        parts.push_back(text.substr(start, end - start));
        start = end + 1;
    }
}

// A number in the classic locale; the whole text must be the number.
std::optional<double> parseNumber(std::string_view text)
{
    if (text.empty()) {
        return std::nullopt;
    }
    std::istringstream stream {std::string(text)};
    stream.imbue(std::locale::classic());
    double value = 0.0;
    stream >> value;
    if (stream.fail() || !stream.eof() || !std::isfinite(value)) {
        return std::nullopt;
    }
    return value;
}

// A list of numbers, or nothing for `_`. Fails (returns false) on a malformed list.
bool parseList(std::string_view text, std::vector<double>& values)
{
    values.clear();
    if (text == emptyField) {
        return true;
    }
    for (auto part : split(text, listDelimiter)) {
        auto value = parseNumber(part);
        if (!value) {
            return false;
        }
        values.push_back(*value);
    }
    return true;
}

bool parseVector(std::string_view text, std::optional<Base::Vector3d>& vector)
{
    std::vector<double> values;
    if (!parseList(text, values)) {
        return false;
    }
    if (values.empty()) {
        vector.reset();
        return true;
    }
    if (values.size() != 3) {
        return false;
    }
    vector = Base::Vector3d(values[0], values[1], values[2]);
    return true;
}

bool validKind(char type, std::string_view kind)
{
    static const std::vector<std::string_view> faces {
        "Plane", "Cylinder", "Cone", "Sphere", "Torus", "Revolution",
        "Extrusion", "Bezier", "BSpline", "Offset", "Other"};
    static const std::vector<std::string_view> edges {
        "Line", "Circle", "Ellipse", "Hyperbola", "Parabola", "Bezier", "BSpline", "Offset", "Other"};
    const auto& list = type == 'F' ? faces : edges;
    if (type == 'V') {
        return kind == "Point";
    }
    return std::find(list.begin(), list.end(), kind) != list.end();
}

}  // namespace

std::string ElementFingerprint::formatNumber(double value)
{
    // Numerical noise (|value| < 1e-12, far below any modelling tolerance) and -0 write as 0, so
    // that noise that differs between platforms doesn't reach the text.
    constexpr double noise = 1e-12;
    if (std::abs(value) < noise) {
        value = 0.0;
    }
    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    stream << std::setprecision(12) << value;
    return stream.str();
}

std::string ElementFingerprint::toString() const
{
    if (!isValid()) {
        return {};
    }
    auto vector = [](const std::optional<Base::Vector3d>& v) {
        if (!v) {
            return std::string(emptyField);
        }
        return formatNumber(v->x) + listDelimiter + formatNumber(v->y) + listDelimiter
            + formatNumber(v->z);
    };
    std::string text = std::to_string(location ? VersionWithLocation : Version);
    text += fieldDelimiter;
    text += type;
    text += fieldDelimiter;
    text += kind.empty() ? std::string(emptyField) : kind;
    text += fieldDelimiter;
    text += size ? formatNumber(*size) : std::string(emptyField);
    text += fieldDelimiter;
    text += vector(center);
    text += fieldDelimiter;
    text += vector(direction);
    text += fieldDelimiter;
    if (radii.empty()) {
        text += emptyField;
    }
    for (std::size_t i = 0; i < radii.size(); ++i) {
        if (i) {
            text += listDelimiter;
        }
        text += formatNumber(radii[i]);
    }
    if (location) {
        text += fieldDelimiter;
        text += vector(location);
    }
    return text;
}

ElementFingerprint ElementFingerprint::fromString(std::string_view text)
{
    auto fields = split(text, fieldDelimiter);
    const bool withLocation = fields.size() == fieldCount + 1
        && fields[0] == std::to_string(VersionWithLocation) && fields[1] == "E"
        && fields[2] == "Circle";
    if (!withLocation && (fields.size() != fieldCount || fields[0] != std::to_string(Version))) {
        return {};
    }
    ElementFingerprint result;
    if (fields[1].size() != 1 || (fields[1][0] != 'F' && fields[1][0] != 'E' && fields[1][0] != 'V')
        || !validKind(fields[1][0], fields[2])) {
        return {};
    }
    result.kind = std::string(fields[2]);
    if (fields[3] != emptyField) {
        result.size = parseNumber(fields[3]);
        if (!result.size) {
            return {};
        }
    }
    if (!parseVector(fields[4], result.center) || !parseVector(fields[5], result.direction)
        || !parseList(fields[6], result.radii) || result.radii.size() > 2) {
        return {};
    }
    if (withLocation && (!parseVector(fields[7], result.location) || !result.location)) {
        return {};
    }
    result.type = fields[1][0];
    return result;
}

}  // namespace Data
