// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <cmath>
#include <cstdlib>
#include <set>
#include <string>
#include <utility>

#include "Mod/PartDesign/App/FeatureHole.h"

namespace
{
// the thread types of Hole::threadDescription, by their place in the table
constexpr int isoMetric = 1;
constexpr int isoMetricFine = 2;
constexpr int unc = 3;
constexpr int unf = 4;
constexpr int unef = 5;
constexpr int bsw = 8;
constexpr int bsf = 9;

// "M12x1.75": the diameter and the pitch the designation names; false: it names neither
bool parseMetric(const std::string& designation, double& diameter, double& pitch)
{
    if (designation.size() < 4 || designation[0] != 'M') {
        return false;
    }
    const std::size_t cross = designation.find('x');
    if (cross == std::string::npos) {
        return false;
    }
    char* end = nullptr;
    diameter = std::strtod(designation.c_str() + 1, &end);
    if (end != designation.c_str() + cross) {
        return false;
    }
    pitch = std::strtod(designation.c_str() + cross + 1, &end);
    return *end == '\0';
}

// "#10", "1/4", "1 3/8", "2": the diameter in mm the designation names; false: it names none
bool parseInch(const std::string& designation, double& diameter)
{
    if (designation.empty()) {
        return false;
    }
    if (designation[0] == '#') {
        // ASME B1.1: the major diameter of screw size n is 0.060 + 0.013 n inches
        char* end = nullptr;
        const double number = std::strtod(designation.c_str() + 1, &end);
        if (*end != '\0') {
            return false;
        }
        diameter = (0.060 + 0.013 * number) * 25.4;
        return true;
    }
    double inches = 0.0;
    const std::size_t space = designation.find(' ');
    std::string fraction = designation;
    if (space != std::string::npos) {
        inches = std::strtod(designation.c_str(), nullptr);
        fraction = designation.substr(space + 1);
    }
    const std::size_t slash = fraction.find('/');
    if (slash == std::string::npos) {
        inches += std::strtod(fraction.c_str(), nullptr);
    }
    else {
        const double numerator = std::strtod(fraction.c_str(), nullptr);
        const double denominator = std::strtod(fraction.c_str() + slash + 1, nullptr);
        if (denominator == 0.0) {
            return false;
        }
        inches += numerator / denominator;
    }
    diameter = inches * 25.4;
    return true;
}
}  // namespace

// ops#404: M26x1.5 held the diameter and pitch of M27x1.0, and M38x1.5 those of M39x1.5, so that
// M27x1.0 reopened as M26x1.5. The designation names the diameter and the pitch of the ISO
// metric rows; the inch rows (unified and Whitworth) name the diameter. Pipe threads (NPT, BSP)
// name the pipe's bore, not the thread, and the tyre valve designations name neither
TEST(HoleThreadTables, metricRowsAreWhatTheirDesignationsSay)
{
    for (const int type : {isoMetric, isoMetricFine}) {
        std::set<std::pair<double, double>> seen;
        for (const auto& row : PartDesign::Hole::threadDescription[type]) {
            const std::string designation = row.designation;
            double diameter = 0.0;
            double pitch = 0.0;
            ASSERT_TRUE(parseMetric(designation, diameter, pitch)) << designation;
            EXPECT_NEAR(row.diameter, diameter, 1e-9) << designation << " (type " << type << ")";
            EXPECT_NEAR(row.pitch, pitch, 1e-9) << designation << " (type " << type << ")";
            EXPECT_TRUE(seen.insert({row.diameter, row.pitch}).second)
                << designation << " repeats the diameter and pitch of an earlier row (type " << type
                << ")";
        }
    }
}

TEST(HoleThreadTables, inchRowsAreWhatTheirDesignationsSay)
{
    for (const int type : {unc, unf, unef, bsw, bsf}) {
        for (const auto& row : PartDesign::Hole::threadDescription[type]) {
            const std::string designation = row.designation;
            double diameter = 0.0;
            ASSERT_TRUE(parseInch(designation, diameter)) << designation;
            // the tables round to 0.001 mm, and BSW's 9/16 and up are rounded a little less
            EXPECT_NEAR(row.diameter, diameter, 0.01) << designation << " (type " << type << ")";
        }
    }
}
