// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <array>
#include <bit>
#include <cmath>
#include <cstdint>

#include "Mod/Sketcher/App/planegcs/GCS.h"

class SystemTest: public GCS::System
{
public:
    size_t getNumberOfConstraints(int tagID = -1)
    {
        return _getNumberOfConstraints(tagID);
    }
};

class GCSTest: public ::testing::Test
{
protected:
    void SetUp() override
    {
        _system = std::make_unique<SystemTest>();
    }

    void TearDown() override
    {
        _system.reset();
    }

    SystemTest* System()
    {
        return _system.get();
    }

private:
    std::unique_ptr<SystemTest> _system;
};

TEST_F(GCSTest, clearConstraints)  // NOLINT
{
    // Arrange
    const size_t numConstraints {100};
    for (size_t i = 0; i < numConstraints; ++i) {
        System()->addConstraint(new GCS::Constraint());
    }
    ASSERT_EQ(numConstraints, System()->getNumberOfConstraints());

    // Act
    System()->clear();

    // Assert
    EXPECT_EQ(0, System()->getNumberOfConstraints());
}

// FreeCAD-CH (ops#940): a solve must not depend on where its parameters live in memory. The
// parameters of a sketch are separate heap allocations, so their address order changes from
// process to process. The solver used to order the Jacobian's columns by address
// (SubSystem::initialize, System::solve(A, B)) and to take the start value of a reduced equality
// from the last address (SubSystem::redirectParams), so the same sketch gave different bits, and
// sometimes a different solution, in every process.
namespace
{

// A quadrilateral p0 p1 p2 p3 with sides 10, 7, 9, 6 and the diagonal p0 p2 of 11; its side p3 p0
// is vertical (an Equal of x0 and x3, which the solver reduces to one unknown), so only a
// translation is left free. Every point starts off its place, and x0 and x3 start apart. The
// parameters are stored forward or reversed in memory; the order given to the solver is the same.
// With a drag, p2 is pulled towards (5, 5) by a temporary constraint, as Sketch::movePoint does,
// and the solve takes the two-subsystem path.
struct Quad
{
    std::array<double, 8> store {};
    bool reversed = false;

    double* param(int i)
    {
        return &store[reversed ? 7 - i : i];
    }
};

struct QuadResult
{
    int status = -1;
    std::array<double, 8> values {};
};

QuadResult solveQuad(bool reversed, bool drag)
{
    static const std::array<double, 8> start {0.3, 0.1, 9.2, 1.4, 12.5, 7.9, -0.4, 6.6};
    Quad quad;
    quad.reversed = reversed;
    for (int i = 0; i < 8; ++i) {
        *quad.param(i) = start[i];
    }
    std::array<GCS::Point, 4> pts;
    for (int i = 0; i < 4; ++i) {
        pts[i] = GCS::Point(quad.param(2 * i), quad.param(2 * i + 1));
    }
    double d01 = 10, d12 = 7, d23 = 9, d30 = 6, d02 = 11;
    double targetX = 5, targetY = 5;
    GCS::Point target(&targetX, &targetY);

    GCS::System system;
    system.addConstraintP2PDistance(pts[0], pts[1], &d01, 1);
    system.addConstraintP2PDistance(pts[1], pts[2], &d12, 2);
    system.addConstraintP2PDistance(pts[2], pts[3], &d23, 3);
    system.addConstraintP2PDistance(pts[3], pts[0], &d30, 4);
    system.addConstraintP2PDistance(pts[0], pts[2], &d02, 5);
    system.addConstraintEqual(pts[0].x, pts[3].x, 6);
    if (drag) {
        system.addConstraintP2PCoincident(pts[2], target, GCS::DefaultTemporaryConstraint);
    }
    GCS::VEC_pD params;
    for (int i = 0; i < 8; ++i) {
        params.push_back(quad.param(i));
    }
    system.declareUnknowns(params);
    system.initSolution();
    QuadResult result;
    result.status = system.solve(true, GCS::DogLeg);
    if (result.status == GCS::Success) {
        system.applySolution();
    }
    for (int i = 0; i < 8; ++i) {
        result.values[i] = *quad.param(i);
    }
    return result;
}

double distance(const std::array<double, 8>& v, int a, int b)
{
    return std::hypot(v[2 * a] - v[2 * b], v[2 * a + 1] - v[2 * b + 1]);
}

void expectSolvedQuad(const QuadResult& r)
{
    ASSERT_EQ(r.status, GCS::Success);
    const auto& v = r.values;
    EXPECT_NEAR(distance(v, 0, 1), 10, 1e-9);
    EXPECT_NEAR(distance(v, 1, 2), 7, 1e-9);
    EXPECT_NEAR(distance(v, 2, 3), 9, 1e-9);
    EXPECT_NEAR(distance(v, 3, 0), 6, 1e-9);
    EXPECT_NEAR(distance(v, 0, 2), 11, 1e-9);
    EXPECT_NEAR(v[0], v[6], 1e-9);
}

void expectSameBits(const QuadResult& a, const QuadResult& b)
{
    EXPECT_EQ(a.status, b.status);
    for (int i = 0; i < 8; ++i) {
        EXPECT_EQ(std::bit_cast<std::uint64_t>(a.values[i]), std::bit_cast<std::uint64_t>(b.values[i]))
            << "parameter " << i << ": " << a.values[i] << " forward, " << b.values[i] << " reversed";
    }
}

}  // namespace

TEST_F(GCSTest, solveDoesNotDependOnParameterAddresses)  // NOLINT
{
    QuadResult forward = solveQuad(false, false);
    QuadResult reversed = solveQuad(true, false);
    expectSolvedQuad(forward);
    expectSolvedQuad(reversed);
    expectSameBits(forward, reversed);
}

TEST_F(GCSTest, dragSolveDoesNotDependOnParameterAddresses)  // NOLINT
{
    QuadResult forward = solveQuad(false, true);
    QuadResult reversed = solveQuad(true, true);
    expectSolvedQuad(forward);
    expectSolvedQuad(reversed);
    expectSameBits(forward, reversed);
}
