// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <App/ElementFingerprint.h>

#include <clocale>
#include <locale>
#include <numbers>
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

    //   one twin with a centroid is no twin set: written without it
    ElementFingerprint alone = cap;
    alone.twinCount = 1;
    EXPECT_EQ(alone.toString(), "1|F|BSpline|8.5|3,5.25,10|_|_");

    //   a lone order-keyed element (ops#503 D1): its count alone, `_` for the centroid
    alone.twinCentroid.reset();
    const char* loneText = "4|F|BSpline|8.5|3,5.25,10|_|_|_|_,1";
    EXPECT_EQ(alone.toString(), loneText);
    EXPECT_EQ(ElementFingerprint::fromString(loneText), alone);
    alone.twinCount = 2;
    EXPECT_EQ(alone.toString(), "1|F|BSpline|8.5|3,5.25,10|_|_");

    //   version 4 only with nine fields, a centroid and a whole number of twins of at least 2
    //   (or no centroid and 1), and the eighth field as versions 2 and 3 have it
    for (const auto& bad : {
             "4|F|BSpline|8.5|3,5.25,10|_|_|_",
             "4|F|BSpline|8.5|3,5.25,10|_|_|3,3.4,10,2",
             "4|F|BSpline|8.5|3,5.25,10|_|_|_|3,3.4,10",
             "4|F|BSpline|8.5|3,5.25,10|_|_|_|3,3.4,10,1",
             "4|F|BSpline|8.5|3,5.25,10|_|_|_|3,3.4,10,2.5",
             "4|F|BSpline|8.5|3,5.25,10|_|_|_|_",
             "4|F|BSpline|8.5|3,5.25,10|_|_|_|_,2",
             "4|F|BSpline|8.5|3,5.25,10|_|_|_|_,0",
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

    //   a lone order-keyed element (ops#503 D1): its count alone, as version 4 writes it; the
    //   record read no fingerprint at all when version 5 met D1 (PR 379 round 4's rebase)
    ElementFingerprint lone = arc;
    lone.twinCount = 1;
    const char* loneText =
        "5|E|Circle|3.14159265359|0.363380227632,1,10|0,0,1|1|1,1,10|0,0,10,1,2,10|_,1|_";
    EXPECT_EQ(lone.toString(), loneText);
    EXPECT_EQ(ElementFingerprint::fromString(loneText), lone);

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
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|_,2|_",
             "5|F|BSpline|8|0.5,4,10|_|_|_|0,0,10,1,8,10|_,0|_",
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
    // the inside point or `_`: each its owner, box, area, normal and outer wire's centre. Written
    // only with an extent
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
    plate.wireCentre = Base::Vector3d(-3, 0, 10);
    cap.upToFaces = {plate};
    const char* capText = "6|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_|_|_|"
                          "Plate001,-10,-10,10,4,10,10,191,0,0,1,-3,0,10";
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
              "Plate001,-10,-10,10,4,10,10,191,0,0,1,-3,0,10;Plate,-10,-10,10,4,10,10,191,0.6,0,0.8,-3,0,10");
    EXPECT_EQ(ElementFingerprint::fromString(twoText), cap);

    //   with the twins: a lone order-keyed element's count alone (ops#503 D1), or the twins'
    //   centroid and count, next to the faces (the rebase onto D1, review pr398-r3)
    ElementFingerprint lone = cap;
    lone.twinCount = 1;
    const std::string loneText = lone.toString();
    EXPECT_EQ(loneText,
              "6|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_,1|_|0.75,0.75,10|"
              "Plate001,-10,-10,10,4,10,10,191,0,0,1,-3,0,10;Plate,-10,-10,10,4,10,10,191,0.6,0,0.8,-3,0,10");
    EXPECT_EQ(ElementFingerprint::fromString(loneText), lone);
    ElementFingerprint twins = cap;
    twins.twinCentroid = Base::Vector3d(1.5, 1.5, 10);
    twins.twinCount = 2;
    const std::string twinsText = twins.toString();
    EXPECT_EQ(twinsText.substr(0, 2), "6|");
    EXPECT_NE(twinsText.find("|1.5,1.5,10,2|"), std::string::npos) << twinsText;
    EXPECT_EQ(ElementFingerprint::fromString(twinsText), twins);

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
             head + "Plate001,-10,-10,10,4,10,10,191,0,0,1",         // ten numbers (no wire)
             head + "Plate001,-10,-10,10,4,10,10,191,0,0,1,-3,0",    // twelve
             head + "Plate001,-10,-10,10,4,10,10,191,0,0,1,-3,0,10,1",  // fourteen
             head + "1Plate,-10,-10,10,4,10,10,191,0,0,1,-3,0,10",   // not a name
             head + ",-10,-10,10,4,10,10,191,0,0,1,-3,0,10",         // no owner
             head + "Plate001",                                      // no numbers
             head + "Plate001,_",
             head + "P,0,0,0,1,1,1,1,0,0,1,0.5,0.5,0;P,0,0,0,1,1,1,1,0,0,1,0.5,0.5,0;P,0,0,0,1,1,1,1,0,0,1,0.5,0.5,0",  // three
             head + "P,0,0,0,1,1,1,1,0,0,1,0.5,0.5,0;",  // an empty second
             // twelve fields, version 6; an edge with an inside point
             std::string("6|F|BSpline|1.75|1.18,1.18,10|_|_|_|0.5,0.5,10,2.5,2.5,10|_|_|_"),
             std::string("6|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|1,8,10|P,0,0,0,1,1,1,1,0,0,1,0.5,0.5,0"),
         }) {
        EXPECT_FALSE(ElementFingerprint::fromString(bad).isValid()) << bad;
    }
    //   an edge's, without an inside point, reads
    EXPECT_TRUE(ElementFingerprint::fromString(
                    "6|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|_|P,0,0,0,1,1,1,1,0,0,1,0.5,0.5,0"
    )
                    .isValid());
}

TEST(ElementFingerprint, sidesAndMarksRoundTrip)
{
    // ops#526 D2: version 7, version 6's fields with `_` where empty, the sides and the marks.
    // An edge with its two faces' normals and the marks of two objects, one without IDs
    ElementFingerprint rim;
    rim.type = 'E';
    rim.kind = "Line";
    rim.size = 2;
    rim.center = Base::Vector3d(1, 8, 10);
    rim.direction = Base::Vector3d(1, 0, 0);
    rim.extentMin = Base::Vector3d(0, 8, 10);
    rim.extentMax = Base::Vector3d(2, 8, 10);
    rim.outline = {Base::Vector3d(0, 8, 10), Base::Vector3d(2, 8, 10)};
    ElementFingerprint::Side top;
    top.direction = Base::Vector3d(0, 0, 1);
    ElementFingerprint::Side front;
    front.direction = Base::Vector3d(0, -1, 0);
    rim.sides = {top, front};
    rim.marks = {{12, 16}, {14, -1}};
    const char* rimText = "7|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|0,8,10,2,8,10|_|_|"
                          "0,0,1/0,-1,0|12:16/14:_";
    EXPECT_EQ(rim.toString(), rimText);
    auto parsed = ElementFingerprint::fromString(rimText);
    ASSERT_TRUE(parsed.isValid());
    EXPECT_EQ(parsed, rim);

    //   a curved edge's curved sides, the twins and the up-to faces kept (PR 398's field)
    ElementFingerprint circle = rim;
    circle.kind = "Circle";
    circle.direction = Base::Vector3d(0, 0, 1);
    circle.radii = {3};
    circle.location = Base::Vector3d(1, 5, 10);
    ElementFingerprint::Side hole;
    hole.curve = '+';
    ElementFingerprint::Side tangent;
    tangent.curve = '0';
    circle.sides = {hole, tangent, top};
    circle.twinCount = 1;
    ElementFingerprint::UpToFace plate;
    plate.owner = "Plate";
    plate.boxMin = Base::Vector3d(-10, -10, 10);
    plate.boxMax = Base::Vector3d(4, 10, 10);
    plate.area = 191;
    plate.normal = Base::Vector3d(0, 0, 1);
    plate.wireCentre = Base::Vector3d(-3, 0, 10);
    circle.upToFaces = {plate};
    const std::string circleText = circle.toString();
    EXPECT_EQ(circleText,
              "7|E|Circle|2|1,8,10|0,0,1|3|1,5,10|0,8,10,2,8,10|_,1|0,8,10,2,8,10|_|"
              "Plate,-10,-10,10,4,10,10,191,0,0,1,-3,0,10|c+/c0/0,0,1|12:16/14:_");
    EXPECT_EQ(ElementFingerprint::fromString(circleText), circle);

    //   a vertex: no box, no outline (version 5 never wrote one); its edges' directions
    ElementFingerprint corner;
    corner.type = 'V';
    corner.kind = "Point";
    corner.center = Base::Vector3d(0, 8, 10);
    ElementFingerprint::Side along;
    along.direction = Base::Vector3d(1, 0, 0);
    ElementFingerprint::Side down;
    down.direction = Base::Vector3d(0, 0, -1);
    corner.sides = {along, down};
    corner.marks = {{12, 16}};
    const char* cornerText = "7|V|Point|_|0,8,10|_|_|_|_|_|_|_|_|1,0,0/0,0,-1|12:16";
    EXPECT_EQ(corner.toString(), cornerText);
    EXPECT_EQ(ElementFingerprint::fromString(cornerText), corner);

    //   a plane's record: no sides, its marks; the pool's fingerprint of a plane: no version 7
    ElementFingerprint face;
    face.type = 'F';
    face.kind = "Plane";
    face.size = 4;
    face.center = Base::Vector3d(1, 1, 10);
    face.direction = Base::Vector3d(0, 0, 1);
    face.extentMin = Base::Vector3d(0, 0, 10);
    face.extentMax = Base::Vector3d(2, 2, 10);
    EXPECT_EQ(face.toString().substr(0, 2), "5|");
    face.marks = {{3, -1}};
    const std::string faceText = face.toString();
    EXPECT_EQ(faceText, "7|F|Plane|4|1,1,10|0,0,1|_|_|0,0,10,2,2,10|_|_|_|_|_|3:_");
    EXPECT_EQ(ElementFingerprint::fromString(faceText), face);

    //   versions 5 and 6 still read, without sides or marks
    auto five = ElementFingerprint::fromString("5|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_");
    ASSERT_TRUE(five.isValid());
    EXPECT_TRUE(five.sides.empty());
    EXPECT_TRUE(five.marks.empty());

    //   malformed
    for (const std::string bad : {
             std::string("7|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|_|_|0,0,1"),  // 14 fields
             std::string("7|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|_|_|0,0,2|_"),  // not unit
             std::string("7|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|_|_|c1|_"),
             std::string("7|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|_|_|_|12"),
             std::string("7|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|_|_|_|12:x"),
             std::string("7|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|_|_|_|-2:3"),
             std::string("7|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|_|_|_|1:2/"),
             std::string("7|V|Point|_|0,8,10|_|_|_|_|_|_|_|Plate,-10,-10,10,4,10,10,191,0,0,1,-3,0,10|_|_"),
             std::string("7|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|_|1,8,10|_|_|_"),  // inside
         }) {
        EXPECT_FALSE(ElementFingerprint::fromString(bad).isValid()) << bad;
    }
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

TEST(ElementFingerprint, frameRoundTrip)
{
    // ops#557: version 8, version 7's fields and the frame the record was measured in. The
    // rotation's real part is written not negative: q and -q are one rotation
    ElementFingerprint rim;
    rim.type = 'E';
    rim.kind = "Line";
    rim.size = 2;
    rim.center = Base::Vector3d(1, 8, 10);
    rim.direction = Base::Vector3d(1, 0, 0);
    rim.extentMin = Base::Vector3d(0, 8, 10);
    rim.extentMax = Base::Vector3d(2, 8, 10);
    rim.outline = {Base::Vector3d(0, 8, 10), Base::Vector3d(2, 8, 10)};
    ElementFingerprint::Side top;
    top.direction = Base::Vector3d(0, 0, 1);
    ElementFingerprint::Side front;
    front.direction = Base::Vector3d(0, -1, 0);
    rim.sides = {top, front};
    rim.marks = {{12, 16}, {14, -1}};
    rim.frame = Base::Placement(Base::Vector3d(0, 0, 5), Base::Rotation(0, 0, -0.6, -0.8));
    const char* rimText = "8|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|0,8,10,2,8,10|_|_|"
                          "0,0,1/0,-1,0|12:16/14:_|0,0,5,0,0,0.6,0.8|_";
    EXPECT_EQ(rim.toString(), rimText);
    auto parsed = ElementFingerprint::fromString(rimText);
    ASSERT_TRUE(parsed.isValid());
    ASSERT_TRUE(parsed.frame.has_value());
    EXPECT_EQ(parsed, rim);

    //   7 -> 8 -> 7: without the frame, version 7's text again, read as it was
    auto seven = parsed;
    seven.frame.reset();
    const char* sevenText = "7|E|Line|2|1,8,10|1,0,0|_|_|0,8,10,2,8,10|_|0,8,10,2,8,10|_|_|"
                            "0,0,1/0,-1,0|12:16/14:_";
    EXPECT_EQ(seven.toString(), sevenText);
    EXPECT_EQ(ElementFingerprint::fromString(sevenText), seven);
    EXPECT_NE(seven, rim);

    //   a frame alone: version 7's fields `_` where empty, then the frame (a plane's record)
    ElementFingerprint face;
    face.type = 'F';
    face.kind = "Plane";
    face.size = 4;
    face.center = Base::Vector3d(1, 1, 10);
    face.direction = Base::Vector3d(0, 0, 1);
    face.extentMin = Base::Vector3d(0, 0, 10);
    face.extentMax = Base::Vector3d(2, 2, 10);
    face.frame = Base::Placement();
    const std::string faceText = face.toString();
    EXPECT_EQ(faceText, "8|F|Plane|4|1,1,10|0,0,1|_|_|0,0,10,2,2,10|_|_|_|_|_|_|0,0,0,0,0,0,1|_");
    EXPECT_EQ(ElementFingerprint::fromString(faceText), face);

    //   `_` for no frame is read; six numbers, or a quaternion that isn't a unit, are no
    //   fingerprint; the sixteenth and seventeenth fields only with version 8
    const std::string fields = "|F|Plane|4|1,1,10|0,0,1|_|_|0,0,10,2,2,10|_|_|_|_|_|_|";
    const auto none = ElementFingerprint::fromString("8" + fields + "_|_");
    ASSERT_TRUE(none.isValid());
    EXPECT_FALSE(none.frame.has_value());
    EXPECT_FALSE(ElementFingerprint::fromString("8" + fields + "0,0,0,0,0,0|_").isValid());
    EXPECT_FALSE(ElementFingerprint::fromString("8" + fields + "0,0,0,0,0,0,2|_").isValid());
    EXPECT_FALSE(ElementFingerprint::fromString("7" + fields + "0,0,0,0,0,0,1|_").isValid());
}

TEST(ElementFingerprint, transformed)
{
    // ops#557: a record moved to its old global place in another frame. A half turn about z
    // with a lift of 20
    ElementFingerprint rim;
    rim.type = 'E';
    rim.kind = "Line";
    rim.size = 2;
    rim.center = Base::Vector3d(1, 8, 10);
    rim.direction = Base::Vector3d(1, 0, 0);
    rim.extentMin = Base::Vector3d(0, 8, 10);
    rim.extentMax = Base::Vector3d(2, 8, 10);
    rim.outline = {Base::Vector3d(0, 8, 10), Base::Vector3d(2, 8, 10)};
    rim.twinCentroid = Base::Vector3d(1, 0, 10);
    rim.twinCount = 2;
    ElementFingerprint::Side top;
    top.direction = Base::Vector3d(0, 0, 1);
    ElementFingerprint::Side front;
    front.direction = Base::Vector3d(0, -1, 0);
    ElementFingerprint::Side curved;
    curved.curve = '+';
    rim.sides = {top, front, curved};
    rim.marks = {{12, 16}};
    rim.frame = Base::Placement(Base::Vector3d(0, 0, 5), Base::Rotation());
    const Base::Placement half(
        Base::Vector3d(0, 0, 20),
        Base::Rotation(Base::Vector3d(0, 0, 1), std::numbers::pi)
    );
    const auto moved = rim.transformed(half, 1e-6);
    ASSERT_TRUE(moved.isValid());
    EXPECT_TRUE(moved.center->IsEqual(Base::Vector3d(-1, -8, 30), 1e-9));
    EXPECT_TRUE(moved.twinCentroid->IsEqual(Base::Vector3d(-1, 0, 30), 1e-9));
    EXPECT_EQ(moved.twinCount, 2);
    //   a line's direction up to its sign, as the producer writes it: (-1, 0, 0) is (1, 0, 0)
    EXPECT_TRUE(moved.direction->IsEqual(Base::Vector3d(1, 0, 0), 1e-9));
    //   the sides keep their sense, a curved side its sign
    ASSERT_EQ(moved.sides.size(), 3u);
    EXPECT_TRUE(moved.sides[0].direction.IsEqual(Base::Vector3d(0, 0, 1), 1e-9));
    EXPECT_TRUE(moved.sides[1].direction.IsEqual(Base::Vector3d(0, 1, 0), 1e-9));
    EXPECT_EQ(moved.sides[2].curve, '+');
    //   a half turn takes each axis onto an axis: the box moved
    ASSERT_TRUE(moved.extentMin && moved.extentMax);
    EXPECT_TRUE(moved.extentMin->IsEqual(Base::Vector3d(-2, -8, 30), 1e-9));
    EXPECT_TRUE(moved.extentMax->IsEqual(Base::Vector3d(0, -8, 30), 1e-9));
    ASSERT_EQ(moved.outline.size(), 2u);
    EXPECT_TRUE(moved.outline[0].IsEqual(Base::Vector3d(0, -8, 30), 1e-9));
    EXPECT_TRUE(moved.outline[1].IsEqual(Base::Vector3d(-2, -8, 30), 1e-9));
    //   the size, the kind and the marks as they were (no place); no frame (another frame)
    EXPECT_EQ(moved.size, rim.size);
    EXPECT_EQ(moved.kind, rim.kind);
    EXPECT_EQ(moved.marks, rim.marks);
    EXPECT_FALSE(moved.frame.has_value());

    //   a plane's normal keeps its sense: a half turn about x takes up to down
    ElementFingerprint face;
    face.type = 'F';
    face.kind = "Plane";
    face.size = 4;
    face.center = Base::Vector3d(1, 1, 10);
    face.direction = Base::Vector3d(0, 0, 1);
    face.extentMin = Base::Vector3d(0, 0, 10);
    face.extentMax = Base::Vector3d(2, 2, 10);
    const Base::Placement over(
        Base::Vector3d(),
        Base::Rotation(Base::Vector3d(1, 0, 0), std::numbers::pi)
    );
    const auto flipped = face.transformed(over, 1e-6);
    EXPECT_TRUE(flipped.direction->IsEqual(Base::Vector3d(0, 0, -1), 1e-9));
    EXPECT_TRUE(flipped.center->IsEqual(Base::Vector3d(1, -1, -10), 1e-9));
    EXPECT_TRUE(flipped.extentMin->IsEqual(Base::Vector3d(0, -2, -10), 1e-9));
    EXPECT_TRUE(flipped.extentMax->IsEqual(Base::Vector3d(2, 0, -10), 1e-9));

    //   37 degrees about z: a turned box is wider than the element, so it goes; the outline is
    //   moved point by point, and the inverse motion gives the places back
    const double angle = 37.0 * std::numbers::pi / 180.0;
    const Base::Placement slant(Base::Vector3d(3, 4, 0), Base::Rotation(Base::Vector3d(0, 0, 1), angle));
    const auto slanted = rim.transformed(slant, 1e-6);
    EXPECT_FALSE(slanted.extentMin.has_value());
    EXPECT_FALSE(slanted.extentMax.has_value());
    const Base::Vector3d centre(
        3 + std::cos(angle) - 8 * std::sin(angle),
        4 + std::sin(angle) + 8 * std::cos(angle),
        10
    );
    EXPECT_TRUE(slanted.center->IsEqual(centre, 1e-9));
    const Base::Vector3d along(std::cos(angle), std::sin(angle), 0);
    EXPECT_TRUE(slanted.direction->IsEqual(along, 1e-9));
    const auto back = slanted.transformed(slant.inverse(), 1e-6);
    EXPECT_TRUE(back.center->IsEqual(*rim.center, 1e-9));
    EXPECT_TRUE(back.outline[1].IsEqual(rim.outline[1], 1e-9));
    EXPECT_TRUE(back.sides[1].direction.IsEqual(front.direction, 1e-9));
}

namespace
{

ElementFingerprint::Source placed(const std::string& key, const Base::Placement& placement)
{
    ElementFingerprint::Source source;
    source.key = key;
    source.placement = placement;
    return source;
}

ElementFingerprint::Source locus(char kind, const std::string& key, Base::Vector3d direction)
{
    ElementFingerprint::Source source;
    source.locus = kind;
    source.key = key;
    source.direction = direction;
    return source;
}

}  // namespace

TEST(ElementFingerprint, sourcesRoundTrip)
{
    // Decision 218: version 8's seventeenth field, the chain's placement sources and loci, sorted
    // as the record keeps them: sources by key, then loci
    ElementFingerprint face;
    face.type = 'F';
    face.kind = "Plane";
    face.size = 4;
    face.center = Base::Vector3d(1, 1, 10);
    face.direction = Base::Vector3d(0, 0, 1);
    face.extentMin = Base::Vector3d(0, 0, 10);
    face.extentMax = Base::Vector3d(2, 2, 10);
    face.sources = {
        placed("12", Base::Placement(Base::Vector3d(0, 0, 5), Base::Rotation())),
        placed("7@Other", Base::Placement()),
        locus('L', "3", Base::Vector3d(0, 0, 1)),
        locus('P', "4", Base::Vector3d(0, 1, 0))
    };
    const std::string text = face.toString();
    EXPECT_EQ(
        text,
        "8|F|Plane|4|1,1,10|0,0,1|_|_|0,0,10,2,2,10|_|_|_|_|_|_|_|"
        "12:0,0,5,0,0,0,1/7@Other:0,0,0,0,0,0,1/L3:0,0,0,0,0,1/P4:0,0,0,0,1,0"
    );
    const auto parsed = ElementFingerprint::fromString(text);
    ASSERT_TRUE(parsed.isValid());
    EXPECT_EQ(parsed, face);
    //   a key without a number, a document name that isn't one, a locus of five numbers or one
    //   without a unit direction: no fingerprint
    const std::string fields = "8|F|Plane|4|1,1,10|0,0,1|_|_|0,0,10,2,2,10|_|_|_|_|_|_|_|";
    EXPECT_FALSE(ElementFingerprint::fromString(fields + "x:0,0,0,0,0,0,1").isValid());
    EXPECT_FALSE(ElementFingerprint::fromString(fields + "7@1doc:0,0,0,0,0,0,1").isValid());
    EXPECT_FALSE(ElementFingerprint::fromString(fields + "L3:0,0,0,0,0").isValid());
    EXPECT_FALSE(ElementFingerprint::fromString(fields + "L3:0,0,0,0,0,2").isValid());
    //   a mirror plane's locus reads back as one
    const auto mirrored = ElementFingerprint::fromString(fields + "M4:0,0,0,0,1,0");
    ASSERT_TRUE(mirrored.isValid());
    ASSERT_EQ(mirrored.sources.size(), 1U);
    EXPECT_EQ(mirrored.sources.front().locus, 'M');
    EXPECT_EQ(ElementFingerprint::fromString(mirrored.toString()), mirrored);
    //   moved to another frame, the sources go with the frame
    EXPECT_TRUE(face.transformed(Base::Placement(), 1e-6).sources.empty());
}

TEST(ElementFingerprint, rigidMotion)
{
    // Decision 218: one motion takes every source to its place now. Two sketches turned 180
    // degrees about (10, 5, 0) together
    const double tolerance = 1e-7;
    const double angle = 1e-6;
    const Base::Placement turn = Base::Placement(Base::Vector3d(10, 5, 0), Base::Rotation())
        * Base::Placement(Base::Vector3d(), Base::Rotation(Base::Vector3d(0, 0, 1), std::numbers::pi))
        * Base::Placement(Base::Vector3d(-10, -5, 0), Base::Rotation());
    const Base::Placement base(Base::Vector3d(0, 0, 0), Base::Rotation());
    const Base::Placement holes(Base::Vector3d(0, 0, 10), Base::Rotation());
    const std::vector<ElementFingerprint::Source> saved {placed("1", base), placed("2", holes)};
    const std::vector<ElementFingerprint::Source> turned {
        placed("1", turn * base),
        placed("2", turn * holes)
    };
    const auto motion = ElementFingerprint::rigidMotion(saved, turned, tolerance, angle);
    ASSERT_TRUE(motion.has_value());
    EXPECT_TRUE(motion->getPosition().IsEqual(turn.getPosition(), 1e-9));
    EXPECT_TRUE(motion->getRotation().isSame(turn.getRotation(), 1e-9));

    //   nothing moved: the identity
    const auto still = ElementFingerprint::rigidMotion(saved, saved, tolerance, angle);
    ASSERT_TRUE(still.has_value());
    EXPECT_TRUE(still->getPosition().IsEqual(Base::Vector3d(), 1e-12));

    //   one left behind (the tool fixed in the body), a source added: not one piece
    const std::vector<ElementFingerprint::Source> behind {placed("1", turn * base), placed("2", holes)};
    EXPECT_FALSE(ElementFingerprint::rigidMotion(saved, behind, tolerance, angle).has_value());
    auto added = turned;
    added.push_back(placed("3", Base::Placement()));
    EXPECT_FALSE(ElementFingerprint::rigidMotion(saved, added, tolerance, angle).has_value());

    //   a locus the motion maps onto itself (a line along z through the turn's centre) keeps it
    //   rigid; one it moves (the Body's z axis, a revolve's axis) doesn't (11.9 F1)
    auto through = locus('L', "9", Base::Vector3d(0, 0, 1));
    through.point = Base::Vector3d(10, 5, 0);
    auto savedThrough = saved;
    savedThrough.push_back(through);
    auto turnedThrough = turned;
    turnedThrough.push_back(through);
    EXPECT_TRUE(
        ElementFingerprint::rigidMotion(savedThrough, turnedThrough, tolerance, angle).has_value()
    );
    auto origin = locus('L', "9", Base::Vector3d(0, 0, 1));
    auto savedOrigin = saved;
    savedOrigin.push_back(origin);
    auto turnedOrigin = turned;
    turnedOrigin.push_back(origin);
    EXPECT_FALSE(
        ElementFingerprint::rigidMotion(savedOrigin, turnedOrigin, tolerance, angle).has_value()
    );
    //   a plane turned in itself stays: the XY plane under the turn about z
    auto plane = locus('P', "8", Base::Vector3d(0, 0, 1));
    auto savedPlane = saved;
    savedPlane.push_back(plane);
    auto turnedPlane = turned;
    turnedPlane.push_back(plane);
    EXPECT_TRUE(ElementFingerprint::rigidMotion(savedPlane, turnedPlane, tolerance, angle).has_value());

    //   a half turn about x maps the z axis onto itself reversed: a revolve or a draft's pull
    //   reads the sense, not rigid (ReviewQuarterRevolveFlipped); the XY plane as a mirror plane
    //   has no sense and stays, as a pull's plane it doesn't
    const Base::Placement flip(
        Base::Vector3d(),
        Base::Rotation(Base::Vector3d(1, 0, 0), std::numbers::pi)
    );
    const std::vector<ElementFingerprint::Source> flipped {
        placed("1", flip * base),
        placed("2", flip * holes)
    };
    auto with = [](std::vector<ElementFingerprint::Source> sources,
                   const ElementFingerprint::Source& extra) {
        sources.push_back(extra);
        return sources;
    };
    const auto axis = locus('L', "9", Base::Vector3d(0, 0, 1));
    const auto mirror = locus('M', "8", Base::Vector3d(0, 0, 1));
    ASSERT_TRUE(ElementFingerprint::rigidMotion(saved, flipped, tolerance, angle).has_value());
    const auto axisFlipped =
        ElementFingerprint::rigidMotion(with(saved, axis), with(flipped, axis), tolerance, angle);
    EXPECT_FALSE(axisFlipped.has_value());
    const auto planeFlipped =
        ElementFingerprint::rigidMotion(with(saved, plane), with(flipped, plane), tolerance, angle);
    EXPECT_FALSE(planeFlipped.has_value());
    const auto mirrorFlipped =
        ElementFingerprint::rigidMotion(with(saved, mirror), with(flipped, mirror), tolerance, angle);
    EXPECT_TRUE(mirrorFlipped.has_value());
}
