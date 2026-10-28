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
    const bool withExtent = extentMin && extentMax;
    const bool withTwins = twinCentroid && twinCount >= 2;
    std::string text = std::to_string(
        withExtent      ? VersionWithBox
            : withTwins ? VersionWithTwins
            : location  ? VersionWithLocation
                        : Version
    );
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
    if (withExtent) {
        // Version 5: the location, the extent, the twins and the outline, each field always there
        text += fieldDelimiter;
        text += vector(location);
        text += fieldDelimiter;
        text += vector(extentMin) + listDelimiter + vector(extentMax);
        text += fieldDelimiter;
        text += withTwins ? vector(twinCentroid) + listDelimiter + std::to_string(twinCount)
                          : std::string(emptyField);
        text += fieldDelimiter;
        // At most MaxOutline points (round 6: every k-th of a longer one, where round 5 wrote none)
        const auto points = thinOutline(outline);
        if (points.empty()) {
            text += emptyField;
        }
        for (std::size_t i = 0; i < points.size(); ++i) {
            if (i) {
                text += listDelimiter;
            }
            text += vector(points[i]);
        }
        // Round 6: a point inside the face, a twelfth field only when there is one
        if (inside) {
            text += fieldDelimiter;
            text += vector(inside);
        }
        return text;
    }
    if (location) {
        text += fieldDelimiter;
        text += vector(location);
    }
    else if (withTwins) {
        text += fieldDelimiter;
        text += emptyField;
    }
    if (withTwins) {
        text += fieldDelimiter;
        text += vector(twinCentroid) + listDelimiter + std::to_string(twinCount);
    }
    return text;
}

ElementFingerprint ElementFingerprint::fromString(std::string_view text)
{
    auto fields = split(text, fieldDelimiter);
    const bool circle = fields.size() > 2 && fields[1] == "E" && fields[2] == "Circle";
    const bool plane = fields.size() > 2 && fields[1] == "F" && fields[2] == "Plane";
    const bool withLocation = fields.size() == fieldCount + 1
        && fields[0] == std::to_string(VersionWithLocation) && circle;
    const bool withExtent = fields.size() == fieldCount + 1
        && fields[0] == std::to_string(VersionWithExtent) && plane;
    const bool withTwins = fields.size() == fieldCount + 2
        && fields[0] == std::to_string(VersionWithTwins);
    // Version 5 with or without the inside point (round 6)
    const bool withBox = (fields.size() == fieldCount + 4 || fields.size() == fieldCount + 5)
        && fields[0] == std::to_string(VersionWithBox) && (fields[1] == "F" || fields[1] == "E");
    if (!withLocation && !withExtent && !withTwins && !withBox
        && (fields.size() != fieldCount || fields[0] != std::to_string(Version))) {
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
    if (withExtent) {
        std::vector<double> corners;
        if (!parseList(fields[7], corners) || corners.size() != 6) {
            return {};
        }
        result.extentMin = Base::Vector3d(corners[0], corners[1], corners[2]);
        result.extentMax = Base::Vector3d(corners[3], corners[4], corners[5]);
    }
    if (withTwins) {
        // The eighth field holds a circle's centre or a plane's extent, as in versions 2 and 3,
        // or nothing.
        std::vector<double> extra;
        if (!parseList(fields[7], extra)) {
            return {};
        }
        if (extra.size() == 3 && circle) {
            result.location = Base::Vector3d(extra[0], extra[1], extra[2]);
        }
        else if (extra.size() == 6 && plane) {
            result.extentMin = Base::Vector3d(extra[0], extra[1], extra[2]);
            result.extentMax = Base::Vector3d(extra[3], extra[4], extra[5]);
        }
        else if (!extra.empty()) {
            return {};
        }
        std::vector<double> twins;
        if (!parseList(fields[8], twins) || twins.size() != 4 || twins[3] < 2
            || twins[3] != std::floor(twins[3]) || twins[3] > 1e6) {
            return {};
        }
        result.twinCentroid = Base::Vector3d(twins[0], twins[1], twins[2]);
        result.twinCount = static_cast<int>(twins[3]);
    }
    if (withBox) {
        // A circle's centre or nothing; the extent, always; the twins or nothing
        if (!parseVector(fields[7], result.location) || (result.location && !circle)) {
            return {};
        }
        std::vector<double> corners;
        if (!parseList(fields[8], corners) || corners.size() != 6) {
            return {};
        }
        result.extentMin = Base::Vector3d(corners[0], corners[1], corners[2]);
        result.extentMax = Base::Vector3d(corners[3], corners[4], corners[5]);
        std::vector<double> twins;
        if (!parseList(fields[9], twins)) {
            return {};
        }
        if (!twins.empty()) {
            if (twins.size() != 4 || twins[3] < 2 || twins[3] != std::floor(twins[3])
                || twins[3] > 1e6) {
                return {};
            }
            result.twinCentroid = Base::Vector3d(twins[0], twins[1], twins[2]);
            result.twinCount = static_cast<int>(twins[3]);
        }
        // The outline: whole points, at least two of them
        std::vector<double> points;
        if (!parseList(fields[10], points) || points.size() % 3 != 0 || points.size() == 3
            || points.size() > 3 * MaxOutline) {
            return {};
        }
        for (std::size_t i = 0; i < points.size(); i += 3) {
            result.outline.emplace_back(points[i], points[i + 1], points[i + 2]);
        }
        // The inside point, a face's, when its field is there
        if (fields.size() == fieldCount + 5
            && (fields[1] != "F" || !parseVector(fields[11], result.inside) || !result.inside)) {
            return {};
        }
    }
    result.type = fields[1][0];
    return result;
}

std::vector<Base::Vector3d> ElementFingerprint::thinOutline(const std::vector<Base::Vector3d>& points)
{
    if (points.size() <= MaxOutline) {
        return points;
    }
    const std::size_t step = (points.size() + MaxOutline - 1) / MaxOutline;
    std::vector<Base::Vector3d> kept;
    for (std::size_t i = 0; i < points.size(); i += step) {
        kept.push_back(points[i]);
    }
    return kept;
}

std::vector<Base::Vector3d> ElementFingerprint::convexOutline(
    const std::vector<Base::Vector3d>& points,
    const Base::Vector3d& normal
)
{
    // Two axes across the normal, and each point's place on them; the monotone chain's hull
    Base::Vector3d n = normal;
    if (n.Length() <= 0.0 || points.empty()) {
        return {};
    }
    n.Normalize();
    Base::Vector3d u = std::abs(n.x) < 0.9 ? Base::Vector3d(1, 0, 0) % n
                                           : Base::Vector3d(0, 1, 0) % n;
    u.Normalize();
    const Base::Vector3d v = n % u;
    struct Place
    {
        double x;
        double y;
        std::size_t index;
    };
    std::vector<Place> places;
    places.reserve(points.size());
    for (std::size_t i = 0; i < points.size(); ++i) {
        places.push_back({points[i] * u, points[i] * v, i});
    }
    std::sort(places.begin(), places.end(), [](const Place& a, const Place& b) {
        return a.x < b.x || (a.x == b.x && a.y < b.y);
    });
    auto turn = [](const Place& o, const Place& a, const Place& b) {
        return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    };
    std::vector<Place> hull(2 * places.size());
    std::size_t k = 0;
    for (const auto& place : places) {
        while (k >= 2 && turn(hull[k - 2], hull[k - 1], place) <= 0.0) {
            --k;
        }
        hull[k++] = place;
    }
    for (std::size_t i = places.size() - 1, lower = k + 1; i > 0; --i) {
        while (k >= lower && turn(hull[k - 2], hull[k - 1], places[i - 1]) <= 0.0) {
            --k;
        }
        hull[k++] = places[i - 1];
    }
    // The chain ends where it began
    hull.resize(k > 1 ? k - 1 : k);
    std::vector<Base::Vector3d> result;
    result.reserve(hull.size());
    for (const auto& place : hull) {
        result.push_back(points[place.index]);
    }
    return result;
}

}  // namespace Data
