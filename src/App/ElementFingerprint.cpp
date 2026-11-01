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
constexpr char faceDelimiter = ';';
// Version 7's sides and marks (ops#526 D2)
constexpr char entryDelimiter = '/';
constexpr char markDelimiter = ':';
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

// An object's name in its document: letters, digits and underscores, not starting with a digit
// (version 6's owner of an up-to face)
bool validOwner(std::string_view name)
{
    auto alpha = [](char c) {
        return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
    };
    return !name.empty() && alpha(name.front())
        && std::all_of(name.begin(), name.end(), [&](char c) {
               return alpha(c) || (c >= '0' && c <= '9');
           });
}

// Version 6's up-to faces: one or two, each its owner and 13 numbers (box, area, normal, the
// outer wire's centre)
bool parseUpToFaces(std::string_view text, std::vector<ElementFingerprint::UpToFace>& faces)
{
    faces.clear();
    for (auto part : split(text, faceDelimiter)) {
        const auto comma = part.find(listDelimiter);
        if (comma == std::string_view::npos) {
            return false;
        }
        std::vector<double> values;
        if (!validOwner(part.substr(0, comma)) || part.substr(comma + 1) == emptyField
            || !parseList(part.substr(comma + 1), values) || values.size() != 13) {
            return false;
        }
        ElementFingerprint::UpToFace face;
        face.owner = std::string(part.substr(0, comma));
        face.boxMin = Base::Vector3d(values[0], values[1], values[2]);
        face.boxMax = Base::Vector3d(values[3], values[4], values[5]);
        face.area = values[6];
        face.normal = Base::Vector3d(values[7], values[8], values[9]);
        face.wireCentre = Base::Vector3d(values[10], values[11], values[12]);
        faces.push_back(std::move(face));
    }
    return !faces.empty() && faces.size() <= ElementFingerprint::MaxUpToFaces;
}

// A whole number, the whole text: digits with an optional minus sign.
std::optional<long> parseWhole(std::string_view text)
{
    const std::size_t start = !text.empty() && text.front() == '-' ? 1 : 0;
    if (text.size() <= start || text.size() - start > 15
        || !std::all_of(text.begin() + start, text.end(), [](char c) {
               return c >= '0' && c <= '9';
           })) {
        return std::nullopt;
    }
    return std::stol(std::string(text));
}

// Version 7's sides: `_`, or entries separated by `/`, each a unit direction or `c+`, `c-`, `c0`
bool parseSides(std::string_view text, std::vector<ElementFingerprint::Side>& sides)
{
    sides.clear();
    if (text == emptyField) {
        return true;
    }
    for (auto part : split(text, entryDelimiter)) {
        ElementFingerprint::Side side;
        if (part == "c+" || part == "c-" || part == "c0") {
            side.curve = part[1];
        }
        else {
            std::optional<Base::Vector3d> direction;
            if (!parseVector(part, direction) || !direction
                || std::abs(direction->Length() - 1.0) > 1e-6) {
                return false;
            }
            side.direction = *direction;
        }
        sides.push_back(side);
    }
    return sides.size() <= ElementFingerprint::MaxSides;
}

// Version 7's marks: `_`, or entries separated by `/`, each `<tag>:<mark>` or `<tag>:_`
bool parseMarks(std::string_view text, std::vector<ElementFingerprint::Mark>& marks)
{
    marks.clear();
    if (text == emptyField) {
        return true;
    }
    for (auto part : split(text, entryDelimiter)) {
        const auto colon = part.find(markDelimiter);
        if (colon == std::string_view::npos) {
            return false;
        }
        const auto tag = parseWhole(part.substr(0, colon));
        const auto value = part.substr(colon + 1);
        const auto mark = value == emptyField ? std::optional<long>(-1) : parseWhole(value);
        if (!tag || *tag < 0 || !mark || *mark < -1) {
            return false;
        }
        marks.push_back({*tag, *mark});
    }
    return marks.size() <= ElementFingerprint::MaxMarks;
}

// Version 8's placements: a position and a unit quaternion, its real part not negative when
// written, so that one rotation has one text (ops#557)
std::string placementText(const Base::Placement& placement)
{
    double q0 = 0.0;
    double q1 = 0.0;
    double q2 = 0.0;
    double q3 = 1.0;
    placement.getRotation().getValue(q0, q1, q2, q3);
    if (q3 < 0.0) {
        q0 = -q0;
        q1 = -q1;
        q2 = -q2;
        q3 = -q3;
    }
    const Base::Vector3d& position = placement.getPosition();
    std::string text;
    for (double value : {position.x, position.y, position.z, q0, q1, q2, q3}) {
        if (!text.empty()) {
            text += listDelimiter;
        }
        text += ElementFingerprint::formatNumber(value);
    }
    return text;
}

bool parsePlacement(std::string_view text, Base::Placement& placement)
{
    std::vector<double> values;
    if (text == emptyField || !parseList(text, values) || values.size() != 7) {
        return false;
    }
    const double norm = std::sqrt(
        values[3] * values[3] + values[4] * values[4] + values[5] * values[5] + values[6] * values[6]
    );
    if (std::abs(norm - 1.0) > 1e-6) {
        return false;
    }
    placement = Base::Placement(
        Base::Vector3d(values[0], values[1], values[2]),
        Base::Rotation(values[3] / norm, values[4] / norm, values[5] / norm, values[6] / norm)
    );
    return true;
}

// Version 8's sources (decision 218): `_`, or entries separated by `/`, each `<key>:<placement>`
// or `L<key>:` / `P<key>:` and a point and a unit direction; a key is an ID, `@<document>` after
// it for another document's object
bool parseSources(std::string_view text, std::vector<ElementFingerprint::Source>& sources)
{
    sources.clear();
    if (text == emptyField) {
        return true;
    }
    for (auto part : split(text, entryDelimiter)) {
        const auto colon = part.find(markDelimiter);
        if (colon == std::string_view::npos || colon == 0) {
            return false;
        }
        ElementFingerprint::Source source;
        std::string_view key = part.substr(0, colon);
        if (key.front() == 'L' || key.front() == 'P' || key.front() == 'M') {
            source.locus = key.front();
            key.remove_prefix(1);
        }
        const auto at = key.find('@');
        const auto tag = parseWhole(key.substr(0, at));
        if (!tag || *tag < 0 || (at != std::string_view::npos && !validOwner(key.substr(at + 1)))) {
            return false;
        }
        source.key = std::string(key);
        const auto value = part.substr(colon + 1);
        if (source.locus) {
            std::vector<double> values;
            if (!parseList(value, values) || values.size() != 6) {
                return false;
            }
            source.point = Base::Vector3d(values[0], values[1], values[2]);
            source.direction = Base::Vector3d(values[3], values[4], values[5]);
            if (std::abs(source.direction.Length() - 1.0) > 1e-6) {
                return false;
            }
        }
        else if (!parsePlacement(value, source.placement)) {
            return false;
        }
        sources.push_back(std::move(source));
    }
    return sources.size() <= ElementFingerprint::MaxSources;
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
    // Twins with their centroid, or a lone order-keyed element's count alone (ops#503 D1)
    const bool withTwins = (twinCentroid && twinCount >= 2) || (!twinCentroid && twinCount == 1);
    const bool withUpTo = withExtent && !upToFaces.empty() && upToFaces.size() <= MaxUpToFaces
        && std::all_of(upToFaces.begin(), upToFaces.end(), [](const UpToFace& face) {
               return validOwner(face.owner);
           });
    // Version 8 for a record with its target's frame or sources (ops#557): version 7's fields,
    // the frame and the sources
    const bool withFrame = frame.has_value() || !sources.empty();
    // Version 7 for any element with sides or marks (ops#526 D2), a vertex included
    const bool withSides = !sides.empty() || !marks.empty() || withFrame;
    std::string text = std::to_string(
        withFrame        ? VersionWithFrame
            : withSides  ? VersionWithSides
            : withUpTo   ? VersionWithUpTo
            : withExtent ? VersionWithBox
            : withTwins  ? VersionWithTwins
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
    if (withExtent || withSides) {
        // Version 5: the location, the extent, the twins and the outline, each field always there
        // (version 7: `_` for an element without an extent)
        text += fieldDelimiter;
        text += vector(location);
        text += fieldDelimiter;
        text += withExtent ? vector(extentMin) + listDelimiter + vector(extentMax)
                           : std::string(emptyField);
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
        // Round 6: a point inside the face, a twelfth field only when there is one; version 6
        // always has it, `_` for none, and the up-to faces
        if (inside || withUpTo || withSides) {
            text += fieldDelimiter;
            text += vector(inside);
        }
        if (withSides && !withUpTo) {
            text += fieldDelimiter;
            text += emptyField;
        }
        if (withUpTo) {
            text += fieldDelimiter;
            for (std::size_t i = 0; i < upToFaces.size(); ++i) {
                const UpToFace& face = upToFaces[i];
                if (i) {
                    text += faceDelimiter;
                }
                text += face.owner;
                text += listDelimiter;
                text += vector(face.boxMin) + listDelimiter + vector(face.boxMax) + listDelimiter;
                text += formatNumber(face.area) + listDelimiter + vector(face.normal);
                text += listDelimiter + vector(face.wireCentre);
            }
        }
        if (withSides) {
            // Version 7: the sides, then the marks (ops#526 D2)
            text += fieldDelimiter;
            for (std::size_t i = 0; i < sides.size(); ++i) {
                if (i) {
                    text += entryDelimiter;
                }
                const Side& side = sides[i];
                text += side.curve ? std::string("c") + side.curve
                                   : vector(std::optional<Base::Vector3d>(side.direction));
            }
            if (sides.empty()) {
                text += emptyField;
            }
            text += fieldDelimiter;
            for (std::size_t i = 0; i < marks.size(); ++i) {
                if (i) {
                    text += entryDelimiter;
                }
                text += std::to_string(marks[i].tag);
                text += markDelimiter;
                text += marks[i].mark < 0 ? std::string(emptyField) : std::to_string(marks[i].mark);
            }
            if (marks.empty()) {
                text += emptyField;
            }
        }
        if (withFrame) {
            // Version 8: the frame, then the placement sources and loci (ops#557, decision 218)
            text += fieldDelimiter;
            text += frame ? placementText(*frame) : std::string(emptyField);
            text += fieldDelimiter;
            for (std::size_t i = 0; i < sources.size(); ++i) {
                const Source& source = sources[i];
                if (i) {
                    text += entryDelimiter;
                }
                if (source.locus) {
                    text += source.locus;
                }
                text += source.key;
                text += markDelimiter;
                text += source.locus
                    ? vector(source.point) + listDelimiter + vector(source.direction)
                    : placementText(source.placement);
            }
            if (sources.empty()) {
                text += emptyField;
            }
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
    // Version 5 with or without the inside point (round 6); version 6 with both fields (ops#522)
    const bool withUpTo = fields.size() == fieldCount + 6
        && fields[0] == std::to_string(VersionWithUpTo) && (fields[1] == "F" || fields[1] == "E");
    // Version 8: version 7's fields and the frame (ops#557)
    const bool withFrame = fields.size() == fieldCount + 10
        && fields[0] == std::to_string(VersionWithFrame)
        && (fields[1] == "F" || fields[1] == "E" || fields[1] == "V");
    // Version 7: version 6's fields, any of them `_`, the sides and the marks (ops#526 D2); a
    // vertex too
    const bool withSides = withFrame
        || (fields.size() == fieldCount + 8 && fields[0] == std::to_string(VersionWithSides)
            && (fields[1] == "F" || fields[1] == "E" || fields[1] == "V"));
    const bool withBox = withUpTo || withSides
        || ((fields.size() == fieldCount + 4 || fields.size() == fieldCount + 5)
            && fields[0] == std::to_string(VersionWithBox) && (fields[1] == "F" || fields[1] == "E"));
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
        // A lone order-keyed element: its count alone, 1 (ops#503 D1)
        const std::string lone = std::string(emptyField) + listDelimiter + "1";
        if (fields[8] == lone) {
            result.twinCount = 1;
        }
        else {
            std::vector<double> twins;
            if (!parseList(fields[8], twins) || twins.size() != 4 || twins[3] < 2
                || twins[3] != std::floor(twins[3]) || twins[3] > 1e6) {
                return {};
            }
            result.twinCentroid = Base::Vector3d(twins[0], twins[1], twins[2]);
            result.twinCount = static_cast<int>(twins[3]);
        }
    }
    if (withBox) {
        // A circle's centre or nothing; the extent, always; the twins or nothing
        if (!parseVector(fields[7], result.location) || (result.location && !circle)) {
            return {};
        }
        // (version 7: or `_`, a vertex's)
        std::vector<double> corners;
        if (!parseList(fields[8], corners)
            || (corners.size() != 6 && !(withSides && corners.empty()))) {
            return {};
        }
        if (!corners.empty()) {
            result.extentMin = Base::Vector3d(corners[0], corners[1], corners[2]);
            result.extentMax = Base::Vector3d(corners[3], corners[4], corners[5]);
        }
        // A lone order-keyed element: its count alone, 1, as in version 4 (ops#503 D1)
        std::vector<double> twins;
        if (fields[9] == std::string(emptyField) + listDelimiter + "1") {
            result.twinCount = 1;
        }
        else if (!parseList(fields[9], twins)) {
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
        // The inside point, a face's, when its field is there (version 6: or `_`)
        if (fields.size() >= fieldCount + 5
            && (!parseVector(fields[11], result.inside)
                || (!withUpTo && !withSides && !result.inside)
                || (result.inside && fields[1] != "F"))) {
            return {};
        }
        if (withUpTo && !parseUpToFaces(fields[12], result.upToFaces)) {
            return {};
        }
        // Version 7: the up-to faces or `_` (only an element with an extent has them), the sides
        // and the marks
        if (withSides
            && ((fields[12] != emptyField
                 && (!result.extentMin || !parseUpToFaces(fields[12], result.upToFaces)))
                || !parseSides(fields[13], result.sides) || !parseMarks(fields[14], result.marks))) {
            return {};
        }
        // Version 8: the frame or `_`, then the sources or `_` (ops#557, decision 218)
        if (withFrame) {
            if (fields[15] != emptyField) {
                Base::Placement placement;
                if (!parsePlacement(fields[15], placement)) {
                    return {};
                }
                result.frame = placement;
            }
            if (!parseSources(fields[16], result.sources)) {
                return {};
            }
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

ElementFingerprint ElementFingerprint::transformed(const Base::Placement& motion, double angle) const
{
    ElementFingerprint result = *this;
    auto move = [&](Base::Vector3d& point) {
        motion.multVec(point, point);
    };
    const Base::Rotation& rotation = motion.getRotation();
    for (auto* point : {&result.center, &result.location, &result.twinCentroid, &result.inside}) {
        if (*point) {
            move(**point);
        }
    }
    for (auto& point : result.outline) {
        move(point);
    }
    if (result.direction) {
        rotation.multVec(*result.direction, *result.direction);
        // An axis or a line direction up to its sign, as the producer writes it: the first
        // component that isn't zero positive. A plane's normal keeps its sense.
        if (type != 'F' || kind != "Plane") {
            constexpr double zero = 1e-12;
            Base::Vector3d& d = *result.direction;
            for (double c : {d.x, d.y, d.z}) {
                if (std::abs(c) > zero) {
                    if (c < 0.0) {
                        d = -d;
                    }
                    break;
                }
            }
        }
    }
    // The sides are oriented: an outward normal, an edge's direction away from a vertex
    for (auto& side : result.sides) {
        if (!side.curve) {
            rotation.multVec(side.direction, side.direction);
        }
    }
    // The box, when the rotation takes each axis onto an axis: its eight corners moved and boxed
    // again. Turned otherwise, a box is wider than the element: none.
    if (result.extentMin && result.extentMax) {
        const double cosine = std::cos(angle);
        bool permutation = true;
        for (int k = 0; k < 3; ++k) {
            const Base::Vector3d image = rotation.multVec(
                Base::Vector3d(k == 0 ? 1.0 : 0.0, k == 1 ? 1.0 : 0.0, k == 2 ? 1.0 : 0.0)
            );
            permutation = permutation
                && std::max({std::abs(image.x), std::abs(image.y), std::abs(image.z)}) >= cosine;
        }
        if (permutation) {
            const Base::Vector3d low = *result.extentMin;
            const Base::Vector3d high = *result.extentMax;
            std::optional<Base::Vector3d> newLow;
            std::optional<Base::Vector3d> newHigh;
            for (int corner = 0; corner < 8; ++corner) {
                Base::Vector3d point(
                    (corner & 1) ? high.x : low.x,
                    (corner & 2) ? high.y : low.y,
                    (corner & 4) ? high.z : low.z
                );
                move(point);
                if (!newLow) {
                    newLow = point;
                    newHigh = point;
                    continue;
                }
                newLow = Base::Vector3d(
                    std::min(newLow->x, point.x),
                    std::min(newLow->y, point.y),
                    std::min(newLow->z, point.z)
                );
                newHigh = Base::Vector3d(
                    std::max(newHigh->x, point.x),
                    std::max(newHigh->y, point.y),
                    std::max(newHigh->z, point.z)
                );
            }
            result.extentMin = newLow;
            result.extentMax = newHigh;
        }
        else {
            result.extentMin.reset();
            result.extentMax.reset();
        }
    }
    // The up-to faces are in their owners' frames; the marks have no place and stay
    result.upToFaces.clear();
    result.frame.reset();
    result.sources.clear();
    return result;
}

std::optional<Base::Placement> ElementFingerprint::rigidMotion(
    const std::vector<Source>& saved,
    const std::vector<Source>& now,
    double distance,
    double angle
)
{
    if (saved.size() != now.size()) {
        return std::nullopt;
    }
    for (std::size_t i = 0; i < saved.size(); ++i) {
        if (saved[i].key != now[i].key || saved[i].locus != now[i].locus) {
            return std::nullopt;
        }
    }
    // The rotation between two placements, as an angle
    auto turnOf = [](const Base::Rotation& rotation) {
        double q0 = 0.0;
        double q1 = 0.0;
        double q2 = 0.0;
        double q3 = 1.0;
        rotation.getValue(q0, q1, q2, q3);
        return 2.0 * std::acos(std::min(1.0, std::abs(q3)));
    };
    auto same = [&](const Base::Placement& a, const Base::Placement& b) {
        return Base::Distance(a.getPosition(), b.getPosition()) <= distance
            && turnOf(a.getRotation().inverse() * b.getRotation()) <= angle;
    };
    // The motion from the first source that moved
    Base::Placement motion;
    for (std::size_t i = 0; i < saved.size(); ++i) {
        if (!saved[i].locus && !same(saved[i].placement, now[i].placement)) {
            motion = now[i].placement * saved[i].placement.inverse();
            break;
        }
    }
    const Base::Rotation& rotation = motion.getRotation();
    // With its sense: a revolve short of a full turn, a pattern, a draft's pull or a pad's
    // direction reads it (ReviewQuarterRevolveFlipped); a mirror plane's normal has none
    auto parallel = [&](const Base::Vector3d& a, const Base::Vector3d& b, bool sense) {
        const double along = a * b;
        return std::atan2((a % b).Length(), sense ? along : std::abs(along)) <= angle;
    };
    for (std::size_t i = 0; i < saved.size(); ++i) {
        const Source& before = saved[i];
        const Source& after = now[i];
        if (!before.locus) {
            if (!same(motion * before.placement, after.placement)) {
                return std::nullopt;
            }
            continue;
        }
        // A locus stays where it was, and the motion maps it onto itself: a line's direction
        // and a point on it, a plane's normal and a point in it
        const bool sense = before.locus != 'M';
        if (Base::Distance(before.point, after.point) > distance
            || !parallel(before.direction, after.direction, sense)) {
            return std::nullopt;
        }
        const Base::Vector3d direction = rotation.multVec(before.direction);
        Base::Vector3d point;
        motion.multVec(before.point, point);
        const Base::Vector3d offset = point - before.point;
        const double off = before.locus == 'L' ? (offset % before.direction).Length()
                                               : std::abs(offset * before.direction);
        if (!parallel(direction, before.direction, sense) || off > distance) {
            return std::nullopt;
        }
    }
    return motion;
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
