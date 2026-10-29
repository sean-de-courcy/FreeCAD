// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <App/ElementFingerprint.h>

#include <clocale>
#include <locale>
#include <string>
#include <vector>

using Data::ElementFingerprint;

namespace
{

ElementFingerprint cylinderFace()
{
    ElementFingerprint fp;
    fp.type = 'F';
    fp.kind = "Cylinder";
    fp.size = 62.8318530718;
    fp.center = Base::Vector3d(0, 0, 5);
    fp.direction = Base::Vector3d(0, 0, 1);
    fp.radii = {1};
    return fp;
}

}  // namespace

TEST(ElementFingerprint, text)
{
    EXPECT_EQ(cylinderFace().toString(), "1|F|Cylinder|62.8318530718|0,0,5|0,0,1|1");

    ElementFingerprint vertex;
    vertex.type = 'V';
    vertex.kind = "Point";
    vertex.center = Base::Vector3d(-1.5, 2.25, 1e-20);
    //   noise below 1e-12 writes as 0
    EXPECT_EQ(vertex.toString(), "1|V|Point|_|-1.5,2.25,0|_|_");

    ElementFingerprint torus;
    torus.type = 'F';
    torus.kind = "Torus";
    torus.size = 1.0 / 3.0;
    torus.center = Base::Vector3d(0, 0, -0.0);
    torus.direction = Base::Vector3d(0, 0, 1);
    torus.radii = {10, 2};
    //   12 significant digits; -0 writes as 0
    EXPECT_EQ(torus.toString(), "1|F|Torus|0.333333333333|0,0,0|0,0,1|10,2");

    EXPECT_EQ(ElementFingerprint().toString(), "");
}

TEST(ElementFingerprint, roundTrip)
{
    for (const auto& text : {
             "1|F|Cylinder|62.8318530718|0,0,5|0,0,1|1",
             "1|V|Point|_|-1.5,2.25,1e-05|_|_",
             "1|E|Ellipse|12.5|1,2,3|0,0.707106781187,0.707106781187|4,2",
             "1|E|BSpline|3|1,1,1|_|_",
             "1|F|Plane|100|5,5,10|0,0,-1|_",
         }) {
        auto fp = ElementFingerprint::fromString(text);
        ASSERT_TRUE(fp.isValid()) << text;
        EXPECT_EQ(fp.toString(), text);
    }
    auto fp = ElementFingerprint::fromString("1|F|Cylinder|62.8318530718|0,0,5|0,0,1|1");
    EXPECT_EQ(fp, cylinderFace());
    EXPECT_EQ(fp.type, 'F');
    ASSERT_TRUE(fp.size.has_value());
    EXPECT_DOUBLE_EQ(*fp.size, 62.8318530718);
    ASSERT_EQ(fp.radii.size(), 1U);

    auto point = ElementFingerprint::fromString("1|V|Point|_|-1.5,2.25,1e-05|_|_");
    EXPECT_FALSE(point.size.has_value());
    EXPECT_FALSE(point.direction.has_value());
    EXPECT_TRUE(point.radii.empty());
}

TEST(ElementFingerprint, unknownOrMalformedIsNoFingerprint)
{
    for (const auto& text : {
             "",
             "3|F|Cylinder|62.8|0,0,5|0,0,1|1",   // a later version
             "1|F|Cylinder|62.8|0,0,5|0,0,1",     // a field missing
             "1|F|Cylinder|62.8|0,0,5|0,0,1|1|",  // one too many
             "1|X|Point|_|0,0,0|_|_",             // unknown type
             "1|F|Line|1|0,0,0|_|_",              // an edge kind on a face
             "1|V|Plane|_|0,0,0|_|_",
             "1|F|Plane|abc|0,0,0|0,0,1|_",    // not a number
             "1|F|Plane|1|0,0|0,0,1|_",        // two coordinates
             "1|F|Plane|1|0,0,0|0,0,1|1,2,3",  // three radii
             "1|F|Plane|1|0,0,0|0,0,1,|_",     // empty list entry
             "1|F|Plane|1.5x|0,0,0|0,0,1|_",   // trailing text
             "1|F|Plane|nan|0,0,0|0,0,1|_",
             "1|F|Plane|1|0,0,inf|0,0,1|_",
         }) {
        EXPECT_FALSE(ElementFingerprint::fromString(text).isValid()) << text;
    }
}

TEST(ElementFingerprint, localeFree)
{
    // A locale with a decimal comma changes neither writing nor reading.
    std::string previousC = std::setlocale(LC_NUMERIC, nullptr);
    std::locale previous = std::locale::global(std::locale::classic());
    bool found = false;
    for (const char* name : {"de_DE.UTF-8", "de_DE.utf8", "de_DE", "de-DE", "German_Germany.1252"}) {
        try {
            std::locale::global(std::locale(name));
            std::setlocale(LC_NUMERIC, name);
            found = true;
            break;
        }
        catch (const std::exception&) {
        }
    }
    if (!found) {
        std::locale::global(previous);
        GTEST_SKIP() << "no German locale on this machine";
    }

    const std::string text = cylinderFace().toString();
    const auto parsed = ElementFingerprint::fromString("1|E|Circle|6.28318530718|0,0,0.5|0,0,1|1.5");

    std::locale::global(previous);
    std::setlocale(LC_NUMERIC, previousC.c_str());

    EXPECT_EQ(text, "1|F|Cylinder|62.8318530718|0,0,5|0,0,1|1");
    ASSERT_TRUE(parsed.isValid());
    ASSERT_EQ(parsed.radii.size(), 1U);
    EXPECT_DOUBLE_EQ(parsed.radii[0], 1.5);
    EXPECT_DOUBLE_EQ(parsed.center->z, 0.5);
}

TEST(ElementFingerprint, numbers)
{
    EXPECT_EQ(ElementFingerprint::formatNumber(0.1 + 0.2), "0.3");
    EXPECT_EQ(ElementFingerprint::formatNumber(-0.0), "0");
    EXPECT_EQ(ElementFingerprint::formatNumber(123456789012345.0), "1.23456789012e+14");
    EXPECT_EQ(ElementFingerprint::formatNumber(1e-7), "1e-07");
    EXPECT_EQ(ElementFingerprint::formatNumber(-2.5), "-2.5");
    EXPECT_EQ(ElementFingerprint::formatNumber(1.2e-16), "0");
    EXPECT_EQ(ElementFingerprint::formatNumber(-9.9e-13), "0");
    EXPECT_EQ(ElementFingerprint::formatNumber(1e-12), "1e-12");
}

TEST(ElementFingerprint, circleLocationRoundTrip)
{
    // A circle edge carries its centre, in version 2 (Task 2 PR 7b)
    ElementFingerprint arc;
    arc.type = 'E';
    arc.kind = "Circle";
    arc.size = 5.23598775598;
    arc.center = Base::Vector3d(14.7746482928, 5, 10);
    arc.direction = Base::Vector3d(0, 0, 1);
    arc.radii = {5};
    arc.location = Base::Vector3d(10, 5, 10);
    const char* text = "2|E|Circle|5.23598775598|14.7746482928,5,10|0,0,1|5|10,5,10";
    EXPECT_EQ(arc.toString(), text);
    auto parsed = ElementFingerprint::fromString(text);
    ASSERT_TRUE(parsed.isValid());
    EXPECT_EQ(parsed, arc);

    //   everything else is still written as version 1
    EXPECT_EQ(cylinderFace().toString().substr(0, 2), "1|");

    //   version 2 only for a circle edge, and only with its eighth field
    for (const auto& bad : {
             "2|E|Line|5|0,0,0|1,0,0|_|0,0,0",
             "2|F|Circle|5|0,0,0|0,0,1|5|0,0,0",
             "2|E|Circle|5|0,0,0|0,0,1|5",
             "2|E|Circle|5|0,0,0|0,0,1|5|_",
             "2|E|Circle|5|0,0,0|0,0,1|5|1,2",
             "1|E|Circle|5|0,0,0|0,0,1|5|0,0,0",
         }) {
        EXPECT_FALSE(ElementFingerprint::fromString(bad).isValid()) << bad;
    }

    //   a version-1 circle parses, without a location
    auto old = ElementFingerprint::fromString("1|E|Circle|5|0,0,0|0,0,1|5");
    ASSERT_TRUE(old.isValid());
    EXPECT_FALSE(old.location.has_value());
}

TEST(ElementFingerprint, planeExtentRoundTrip)
{
    // A planar face carries its bounding box, in version 3 (Task 2 PR 8); since version 5 (PR 366
    // round 4) it is written there
    ElementFingerprint face;
    face.type = 'F';
    face.kind = "Plane";
    face.size = 80;
    face.center = Base::Vector3d(4, 0, 5);
    face.direction = Base::Vector3d(0, -1, 0);
    face.extentMin = Base::Vector3d(0, 0, 0);
    face.extentMax = Base::Vector3d(8, 0, 10);
    const char* text = "3|F|Plane|80|4,0,5|0,-1,0|_|0,0,0,8,0,10";
    EXPECT_EQ(face.toString(), "5|F|Plane|80|4,0,5|0,-1,0|_|_|0,0,0,8,0,10|_|_");
    auto parsed = ElementFingerprint::fromString(text);
    ASSERT_TRUE(parsed.isValid());
    EXPECT_EQ(parsed, face);

    //   version 3 only for a planar face, and only with six numbers in its eighth field
    for (const auto& bad : {
             "3|E|Line|5|0,0,0|1,0,0|_|0,0,0,1,1,1",
             "3|F|Cylinder|5|0,0,0|0,0,1|2|0,0,0,1,1,1",
             "3|F|Plane|80|4,0,5|0,-1,0|_",
             "3|F|Plane|80|4,0,5|0,-1,0|_|_",
             "3|F|Plane|80|4,0,5|0,-1,0|_|0,0,0,8,0",
             "3|F|Plane|80|4,0,5|0,-1,0|_|0,0,0,8,0,10,1",
             "1|F|Plane|80|4,0,5|0,-1,0|_|0,0,0,8,0,10",
             "2|F|Plane|80|4,0,5|0,-1,0|_|0,0,0",
         }) {
        EXPECT_FALSE(ElementFingerprint::fromString(bad).isValid()) << bad;
    }

    //   a version-1 plane parses, without an extent
    auto old = ElementFingerprint::fromString("1|F|Plane|80|4,0,5|0,-1,0|_");
    ASSERT_TRUE(old.isValid());
    EXPECT_FALSE(old.extentMin.has_value());
    EXPECT_FALSE(old.extentMax.has_value());
}

TEST(ElementFingerprint, twinCentroidRoundTrip)
{
    // An ordered twin carries the centroid of its twins and their number, in version 4, with what
    // versions 2 and 3 carry in the eighth field (ops#360, PR 340 round 5)
    ElementFingerprint cap;
    cap.type = 'F';
    cap.kind = "BSpline";
    cap.size = 8.5;
    cap.center = Base::Vector3d(3, 5.25, 10);
    cap.twinCentroid = Base::Vector3d(3, 3.4, 10);
    cap.twinCount = 2;
    const char* text = "4|F|BSpline|8.5|3,5.25,10|_|_|_|3,3.4,10,2";
    EXPECT_EQ(cap.toString(), text);
    auto parsed = ElementFingerprint::fromString(text);
    ASSERT_TRUE(parsed.isValid());
    EXPECT_EQ(parsed, cap);

    ElementFingerprint plane = cap;
    plane.kind = "Plane";
    plane.direction = Base::Vector3d(0, 0, 1);
    plane.extentMin = Base::Vector3d(2, 4, 10);
    plane.extentMax = Base::Vector3d(4, 7, 10);
    plane.twinCount = 3;
    const char* planeText = "4|F|Plane|8.5|3,5.25,10|0,0,1|_|2,4,10,4,7,10|3,3.4,10,3";
    //   with its extent, written as version 5 (PR 366 round 4)
    EXPECT_EQ(plane.toString(), "5|F|Plane|8.5|3,5.25,10|0,0,1|_|_|2,4,10,4,7,10|3,3.4,10,3|_");
    EXPECT_EQ(ElementFingerprint::fromString(planeText), plane);

    ElementFingerprint arc;
    arc.type = 'E';
    arc.kind = "Circle";
    arc.size = 2;
    arc.center = Base::Vector3d(0, 1, 0);
    arc.direction = Base::Vector3d(0, 0, 1);
    arc.radii = {1.5};
    arc.location = Base::Vector3d(0, 0, 0);
    arc.twinCentroid = Base::Vector3d(0, 0.5, 0);
    arc.twinCount = 2;
    const char* arcText = "4|E|Circle|2|0,1,0|0,0,1|1.5|0,0,0|0,0.5,0,2";
    EXPECT_EQ(arc.toString(), arcText);
    EXPECT_EQ(ElementFingerprint::fromString(arcText), arc);

    //   one twin alone is no twin set: written without it
    ElementFingerprint alone = cap;
    alone.twinCount = 1;
    EXPECT_EQ(alone.toString(), "1|F|BSpline|8.5|3,5.25,10|_|_");

    //   version 4 only with nine fields, a centroid and a whole number of twins of at least 2,
    //   and the eighth field as versions 2 and 3 have it
    for (const auto& bad : {
             "4|F|BSpline|8.5|3,5.25,10|_|_|_",
             "4|F|BSpline|8.5|3,5.25,10|_|_|3,3.4,10,2",
             "4|F|BSpline|8.5|3,5.25,10|_|_|_|3,3.4,10",
             "4|F|BSpline|8.5|3,5.25,10|_|_|_|3,3.4,10,1",
             "4|F|BSpline|8.5|3,5.25,10|_|_|_|3,3.4,10,2.5",
             "4|F|BSpline|8.5|3,5.25,10|_|_|_|_",
             "4|F|BSpline|8.5|3,5.25,10|_|_|0,0,0|3,3.4,10,2",
             "4|F|Plane|8.5|3,5.25,10|0,0,1|_|0,0,0|3,3.4,10,2",
             "4|E|Line|2|0,1,0|1,0,0|_|0,0,0,1,1,1|0,0.5,0,2",
             "3|F|BSpline|8.5|3,5.25,10|_|_|_|3,3.4,10,2",
         }) {
        EXPECT_FALSE(ElementFingerprint::fromString(bad).isValid()) << bad;
    }

    //   an older record parses without it
    auto old = ElementFingerprint::fromString("1|F|BSpline|8.5|3,5.25,10|_|_");
    ASSERT_TRUE(old.isValid());
    EXPECT_FALSE(old.twinCentroid.has_value());
    EXPECT_EQ(old.twinCount, 0);
}

TEST(ElementFingerprint, boxRoundTrip)
{
    // Every face and edge carries its bounding box, in version 5, beside a circle's centre and
    // the twins' centroid (ops#386, PR 366 round 4): a B-spline cap, an arc of a circle, a line
    ElementFingerprint cap;
    cap.type = 'F';
    cap.kind = "BSpline";
    cap.size = 8;
    cap.center = Base::Vector3d(0.5, 4, 10);
    cap.extentMin = Base::Vector3d(0, 0, 10);
    cap.extentMax = Base::Vector3d(1, 8, 10);
    const char* capText = "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|_|_";
    EXPECT_EQ(cap.toString(), capText);
    auto parsed = ElementFingerprint::fromString(capText);
    ASSERT_TRUE(parsed.isValid());
    EXPECT_EQ(parsed, cap);

    ElementFingerprint arc;
    arc.type = 'E';
    arc.kind = "Circle";
    arc.size = 3.14159265359;
    arc.center = Base::Vector3d(0.363380227632, 1, 10);
    arc.direction = Base::Vector3d(0, 0, 1);
    arc.radii = {1};
    arc.location = Base::Vector3d(1, 1, 10);
    arc.extentMin = Base::Vector3d(0, 0, 10);
    arc.extentMax = Base::Vector3d(1, 2, 10);
    const char* arcText =
        "5|E|Circle|3.14159265359|0.363380227632,1,10|0,0,1|1|1,1,10|0,0,10,1,2,10|_|_";
    EXPECT_EQ(arc.toString(), arcText);
    EXPECT_EQ(ElementFingerprint::fromString(arcText), arc);

    //   with its twins
    ElementFingerprint twin = arc;
    twin.twinCentroid = Base::Vector3d(1, 1, 10);
    twin.twinCount = 2;
    const char* twinText =
        "5|E|Circle|3.14159265359|0.363380227632,1,10|0,0,1|1|1,1,10|0,0,10,1,2,10|1,1,10,2|_";
    EXPECT_EQ(twin.toString(), twinText);
    EXPECT_EQ(ElementFingerprint::fromString(twinText), twin);

    ElementFingerprint line;
    line.type = 'E';
    line.kind = "Line";
    line.size = 2;
    line.center = Base::Vector3d(1, 8, 10);
    line.direction = Base::Vector3d(1, 0, 0);
    line.extentMin = Base::Vector3d(0, 8, 10);
    line.extentMax = Base::Vector3d(2, 8, 10);
    const char* lineText = "5|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_";
    EXPECT_EQ(line.toString(), lineText);
    EXPECT_EQ(ElementFingerprint::fromString(lineText), line);

    //   version 5 only for a face or an edge, with eleven fields (round 4's ten no longer), a
    //   centre only for a circle, six numbers in the extent, twins as version 4 has them, and an
    //   outline of whole points, two at least
    for (const auto& bad : {
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10",
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|_",
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|_|_|_",
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|_|0,0,10",
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|_|0,0,10,1,8",
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|_|0,0,10,x,8,10",
             "5|F|BSpline|8|0.5,4,10|_|_|_|_|_|_",
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8|_|_",
             "5|F|BSpline|8|0.5,4,10|_|_|0,0,0|0,0,10,1,8,10|_|_",
             "5|E|Line|2|1,8,10|1,0,0|_|0,0,0|0,8,10,2,8,10|_|_",
             "5|V|Point|_|1,8,10|_|_|_|1,8,10,1,8,10|_|_",
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|1,1,10,1|_",
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|1,1,10|_",
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|1,1,10,2.5|_",
             "4|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|_",
         }) {
        EXPECT_FALSE(ElementFingerprint::fromString(bad).isValid()) << bad;
    }

    //   a fingerprint without an extent (a degenerated edge, a vertex) keeps its old version
    ElementFingerprint bare = cap;
    bare.extentMin.reset();
    bare.extentMax.reset();
    EXPECT_EQ(bare.toString(), "1|F|BSpline|8|0.5,4,10|_|_");
}

TEST(ElementFingerprint, outlineRoundTrip)
{
    // A face's and an edge's outline, the eleventh field of version 5 (PR 366 round 5): the cap's
    // four corners, the line's two ends, in their order
    ElementFingerprint cap;
    cap.type = 'F';
    cap.kind = "BSpline";
    cap.size = 8;
    cap.center = Base::Vector3d(0.5, 4, 10);
    cap.extentMin = Base::Vector3d(0, 0, 10);
    cap.extentMax = Base::Vector3d(1, 8, 10);
    cap.outline = {
        Base::Vector3d(0, 0, 10),
        Base::Vector3d(1, 0, 10),
        Base::Vector3d(1, 8, 10),
        Base::Vector3d(0, 8, 10)
    };
    const char* capText =
        "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|_|0,0,10,1,0,10,1,8,10,0,8,10";
    EXPECT_EQ(cap.toString(), capText);
    auto parsed = ElementFingerprint::fromString(capText);
    ASSERT_TRUE(parsed.isValid());
    EXPECT_EQ(parsed, cap);
    EXPECT_EQ(parsed.outline.size(), 4u);

    ElementFingerprint line;
    line.type = 'E';
    line.kind = "Line";
    line.size = 2;
    line.center = Base::Vector3d(1, 8, 10);
    line.direction = Base::Vector3d(1, 0, 0);
    line.extentMin = Base::Vector3d(0, 8, 10);
    line.extentMax = Base::Vector3d(2, 8, 10);
    line.outline = {Base::Vector3d(2, 8, 10), Base::Vector3d(0, 8, 10)};
    const char* lineText = "5|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|2,8,10,0,8,10";
    EXPECT_EQ(line.toString(), lineText);
    EXPECT_EQ(ElementFingerprint::fromString(lineText), line);

    //   an outline differs from none
    ElementFingerprint without = line;
    without.outline.clear();
    EXPECT_NE(without, line);

    //   too many points are thinned when written (round 6: every second of 257, where round 5
    //   wrote no outline), and are a malformed field when read
    ElementFingerprint crowded = line;
    crowded.outline.clear();
    for (std::size_t i = 0; i <= ElementFingerprint::MaxOutline; ++i) {
        crowded.outline.emplace_back(static_cast<double>(i), 8, 10);
    }
    auto thinned = ElementFingerprint::fromString(crowded.toString());
    ASSERT_TRUE(thinned.isValid()) << crowded.toString();
    ASSERT_EQ(thinned.outline.size(), 129u);
    EXPECT_EQ(thinned.outline[1], Base::Vector3d(2, 8, 10));
    EXPECT_EQ(thinned.outline.back(), Base::Vector3d(256, 8, 10));
    std::string text = "5|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|";
    for (std::size_t i = 0; i <= ElementFingerprint::MaxOutline; ++i) {
        text += i ? ",1,8,10" : "1,8,10";
    }
    EXPECT_FALSE(ElementFingerprint::fromString(text).isValid());
}

TEST(ElementFingerprint, thinOutline)
{
    // At most MaxOutline points (PR 366 round 6): every k-th, in order, k the least that fits
    std::vector<Base::Vector3d> points;
    for (std::size_t i = 0; i < ElementFingerprint::MaxOutline; ++i) {
        points.emplace_back(static_cast<double>(i), 0, 0);
    }
    EXPECT_EQ(ElementFingerprint::thinOutline(points), points);
    for (std::size_t i = points.size(); i < 3 * ElementFingerprint::MaxOutline + 1; ++i) {
        points.emplace_back(static_cast<double>(i), 0, 0);
    }
    const auto thinned = ElementFingerprint::thinOutline(points);
    ASSERT_EQ(thinned.size(), 193u);
    for (std::size_t i = 0; i < thinned.size(); ++i) {
        EXPECT_EQ(thinned[i], points[4 * i]);
    }
}

TEST(ElementFingerprint, insideRoundTrip)
{
    // A face's point inside it, version 5's twelfth field (PR 366 round 6), written only when
    // there is one; read back, and a malformed field, an edge's or an empty one, gives none
    ElementFingerprint cap;
    cap.type = 'F';
    cap.kind = "BSpline";
    cap.size = 1.75;
    cap.center = Base::Vector3d(1.18, 1.18, 10);
    cap.extentMin = Base::Vector3d(0.5, 0.5, 10);
    cap.extentMax = Base::Vector3d(2.5, 2.5, 10);
    cap.inside = Base::Vector3d(0.75, 0.75, 10);
    const char* capText
        = "5|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_|_|0.75,0.75,10";
    EXPECT_EQ(cap.toString(), capText);
    auto parsed = ElementFingerprint::fromString(capText);
    ASSERT_TRUE(parsed.isValid());
    EXPECT_EQ(parsed, cap);

    //   a point differs from none
    ElementFingerprint without = cap;
    without.inside.reset();
    EXPECT_NE(without, cap);
    EXPECT_EQ(without.toString(), "5|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_|_");

    for (const char* bad :
         {"5|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_|_|_",
          "5|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_|_|0.75,0.75",
          "5|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_|_|0.75,0.75,10|_",
          "5|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|1,8,10"}) {
        EXPECT_FALSE(ElementFingerprint::fromString(bad).isValid()) << bad;
    }
}

TEST(ElementFingerprint, upToFacesRoundTrip)
{
    // ops#522 (PLAN decision 168): a far piece's up-to faces, version 6's thirteenth field, after
    // the inside point or `_`: each its owner, box, area and normal. Written only with an extent
    // and one or two faces; read back, and a malformed field gives no fingerprint
    ElementFingerprint cap;
    cap.type = 'F';
    cap.kind = "BSpline";
    cap.size = 1.75;
    cap.center = Base::Vector3d(1.18, 1.18, 10);
    cap.extentMin = Base::Vector3d(0.5, 0.5, 10);
    cap.extentMax = Base::Vector3d(2.5, 2.5, 10);
    ElementFingerprint::UpToFace plate;
    plate.owner = "Plate001";
    plate.boxMin = Base::Vector3d(-10, -10, 10);
    plate.boxMax = Base::Vector3d(4, 10, 10);
    plate.area = 191;
    plate.normal = Base::Vector3d(0, 0, 1);
    cap.upToFaces = {plate};
    const char* capText = "6|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_|_|_|"
                          "Plate001,-10,-10,10,4,10,10,191,0,0,1";
    EXPECT_EQ(cap.toString(), capText);
    auto parsed = ElementFingerprint::fromString(capText);
    ASSERT_TRUE(parsed.isValid());
    EXPECT_EQ(parsed, cap);

    //   with the inside point, and two faces (an edge piece on a seam has two)
    cap.inside = Base::Vector3d(0.75, 0.75, 10);
    ElementFingerprint::UpToFace other = plate;
    other.owner = "Plate";
    other.normal = Base::Vector3d(0.6, 0, 0.8);
    cap.upToFaces = {plate, other};
    const std::string twoText = cap.toString();
    EXPECT_EQ(twoText,
              "6|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_|_|0.75,0.75,10|"
              "Plate001,-10,-10,10,4,10,10,191,0,0,1;Plate,-10,-10,10,4,10,10,191,0.6,0,0.8");
    EXPECT_EQ(ElementFingerprint::fromString(twoText), cap);

    //   the faces differ from none, which is version 5 as before
    ElementFingerprint without = cap;
    without.upToFaces.clear();
    EXPECT_NE(without, cap);
    EXPECT_EQ(without.toString().substr(0, 2), "5|");
    //   an owner that isn't an object's name, or more than two faces, writes version 5
    ElementFingerprint badOwner = cap;
    badOwner.upToFaces[0].owner = "Plate|1";
    EXPECT_EQ(badOwner.toString().substr(0, 2), "5|");
    ElementFingerprint three = cap;
    three.upToFaces.push_back(plate);
    EXPECT_EQ(three.toString().substr(0, 2), "5|");

    const std::string head = "6|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_|_|_|";
    for (const std::string& bad : {
             head,                                                   // no face
             head + "_",                                             // none
             head + "Plate001,-10,-10,10,4,10,10,191,0,0",           // nine numbers
             head + "Plate001,-10,-10,10,4,10,10,191,0,0,1,2",       // eleven
             head + "1Plate,-10,-10,10,4,10,10,191,0,0,1",           // not a name
             head + ",-10,-10,10,4,10,10,191,0,0,1",                 // no owner
             head + "Plate001",                                      // no numbers
             head + "Plate001,_",
             head + "P,0,0,0,1,1,1,1,0,0,1;P,0,0,0,1,1,1,1,0,0,1;P,0,0,0,1,1,1,1,0,0,1",  // three
             head + "P,0,0,0,1,1,1,1,0,0,1;",                        // an empty second
             // twelve fields, version 6; an edge with an inside point
             std::string("6|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_|_|_"),
             std::string("6|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|1,8,10|P,0,0,0,1,1,1,1,0,0,1"),
         }) {
        EXPECT_FALSE(ElementFingerprint::fromString(bad).isValid()) << bad;
    }
    //   an edge's, without an inside point, reads
    EXPECT_TRUE(ElementFingerprint::fromString(
                    "6|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|_|P,0,0,0,1,1,1,1,0,0,1"
    )
                    .isValid());
}

TEST(ElementFingerprint, convexOutline)
{
    // The hull of points seen along a normal (PR 366 round 5): an L's corners and a point inside
    // give the L's convex corners, in order round it; points on a side between two others drop
    const std::vector<Base::Vector3d> points {
        Base::Vector3d(0, 0, 5),
        Base::Vector3d(1, 0, 5),
        Base::Vector3d(2, 0, 5),
        Base::Vector3d(2, 1, 5),
        Base::Vector3d(1, 1, 5),
        Base::Vector3d(1, 2, 5),
        Base::Vector3d(0, 2, 5),
        Base::Vector3d(0.5, 0.5, 5)
    };
    const auto hull = ElementFingerprint::convexOutline(points, Base::Vector3d(0, 0, 1));
    ASSERT_EQ(hull.size(), 5u);
    const std::vector<Base::Vector3d> corners {
        Base::Vector3d(0, 0, 5),
        Base::Vector3d(2, 0, 5),
        Base::Vector3d(2, 1, 5),
        Base::Vector3d(1, 2, 5),
        Base::Vector3d(0, 2, 5)
    };
    for (const auto& corner : corners) {
        EXPECT_EQ(std::count(hull.begin(), hull.end(), corner), 1) << corner.x << "," << corner.y;
    }
    //   in order round it: each turn the same way
    double turns = 0.0;
    for (std::size_t i = 0; i < hull.size(); ++i) {
        const auto& a = hull[i];
        const auto& b = hull[(i + 1) % hull.size()];
        const auto& c = hull[(i + 2) % hull.size()];
        const double turn = ((b - a) % (c - b)).z;
        EXPECT_NE(turn, 0.0);
        turns += turn > 0.0 ? 1.0 : -1.0;
    }
    EXPECT_EQ(std::abs(turns), static_cast<double>(hull.size()));

    //   seen from the side, the same points are a row: its two ends
    const auto row = ElementFingerprint::convexOutline(points, Base::Vector3d(0, 1, 0));
    ASSERT_EQ(row.size(), 2u);
    //   no normal, or no points, gives nothing
    EXPECT_TRUE(ElementFingerprint::convexOutline(points, Base::Vector3d()).empty());
    EXPECT_TRUE(ElementFingerprint::convexOutline({}, Base::Vector3d(0, 0, 1)).empty());
}
