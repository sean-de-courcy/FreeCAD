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
