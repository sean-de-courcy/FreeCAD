// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>
#include "src/App/InitApplication.h"

#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <optional>

#include <App/Application.h>
#include <App/Document.h>
#include <App/MappedName.h>
#include <App/NameTable.h>
#include "Mod/Part/App/PartFeature.h"
#include "Mod/PartDesign/App/Body.h"
#include "Mod/PartDesign/App/ShapeBinder.h"
#include "Mod/PartDesign/App/FeaturePipe.h"
#include "Mod/Sketcher/App/SketchObject.h"
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepGProp.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <GProp_GProps.hxx>

// The process's memory, for memoryHeld()
#if defined(_WIN32)
# ifndef NOMINMAX
#  define NOMINMAX
# endif
# include <windows.h>
# include <psapi.h>
#elif defined(__linux__)
# include <unistd.h>
#endif

// NOLINTBEGIN(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)

// Uncomment the line below to save temporary test-generated documents
// #define PIPE_SAVE_TEST_FCSTD 1

// from tests/src/Mod/Part/App/TopoShapeExpansion.cpp
double getVolume(const TopoDS_Shape& shape)
{
    GProp_GProps prop;
    BRepGProp::VolumeProperties(shape, prop);
    return abs(prop.Mass());
}

class FeaturePipeTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        docName_ = App::GetApplication().getUniqueDocumentName("testname");
        doc_ = App::GetApplication().newDocument(docName_.c_str(), "testlabel");
        body_ = doc_->addObject<PartDesign::Body>();

        sketch_circle_ = doc_->addObject<Sketcher::SketchObject>("circle");

        // Attach the sketch to body origin
        // reference: tests/src/Mod/Part/Attacher.cpp
        body_->addObject(sketch_circle_);
        sketch_circle_->MapReversed.setValue(false);
        auto origin = body_->getObject("Origin");
        sketch_circle_->AttachmentOffset.setValue(
            Base::Placement(Base::Vector3d(0, 0, 0), Base::Rotation())
        );
        sketch_circle_->AttachmentSupport.setValue(origin, std::vector<std::string> {"XY_Plane."});
        sketch_circle_->MapPathParameter.setValue(0.0);
        sketch_circle_->MapMode.setValue("FlatFace");

        //
        // Create a fully constrained circle sketch

        // first create the circle geometry
        Part::GeomCircle circle;
        Base::Vector3d coordsCenter(0.0, 0.0, 0.0);
        double radius = 1.0;
        circle.setCenter(coordsCenter);
        circle.setRadius(radius);

        // add circle geometry to sketch
        sketch_circle_->addGeometry(&circle);

        // New scope for constraints.  This allows to use the same
        // temporary variable names as the line sketch below
        {
            auto coincident = Sketcher::Constraint();
            coincident.Type = Sketcher::ConstraintType::Coincident;
            coincident.First = 0;
            coincident.FirstPos = Sketcher::PointPos::mid;
            coincident.Second = -1;
            coincident.SecondPos = Sketcher::PointPos::start;
            sketch_circle_->addConstraint(&coincident);

            auto diameter = Sketcher::Constraint();
            diameter.Type = Sketcher::ConstraintType::Diameter;
            diameter.First = 0;
            diameter.setValue(1.0);
            sketch_circle_->addConstraint(&diameter);
        }

        auto obj = std::vector<std::pair<int, long>> {{0, 1}};
        sketch_circle_->setGeometryIds(obj);

        try {
            sketch_circle_->solve();
        }
        catch (const Base::Exception& e) {
            FAIL() << e.what();
        }

        doc_->recompute();

#ifdef PIPE_SAVE_TEST_FCSTD
        {
            auto p = std::filesystem::temp_directory_path();
            doc_->saveAs((p / "FeaturePipeTest-circle.FCStd").c_str());
        }
#endif
        //
        // Create fully constrained line sketch
        // - define the sketch attachment
        // - create the line geometry
        // - add the line geometry to the sketch
        // - add constraints to the sketch

        sketch_line_ = doc_->addObject<Sketcher::SketchObject>("line");

        // Attach the sketch to body origin, reference: tests/src/Mod/Part/Attacher.cpp
        body_->addObject(sketch_line_);
        sketch_line_->MapReversed.setValue(false);
        sketch_line_->AttachmentSupport.setValue(origin, std::vector<std::string> {"XZ_Plane."});
        sketch_line_->MapPathParameter.setValue(0.0);
        sketch_line_->MapMode.setValue("FlatFace");

        Part::GeomLineSegment line;
        Base::Vector3d p1(0.0, 0.0, 0.0);
        Base::Vector3d p2(0.0, 1.0, 0.0);
        line.setPoints(p1, p2);
        sketch_line_->addGeometry(&line);

        {
            auto distance = Sketcher::Constraint();
            distance.Type = Sketcher::ConstraintType::Distance;
            distance.First = 0;
            distance.setValue(1);
            sketch_line_->addConstraint(&distance);

            auto vertical = Sketcher::Constraint();
            vertical.Type = Sketcher::ConstraintType::Vertical;
            vertical.First = 0;
            sketch_line_->addConstraint(&vertical);

            auto coincident = Sketcher::Constraint();
            coincident.Type = Sketcher::ConstraintType::Coincident;
            coincident.First = 0;
            coincident.FirstPos = Sketcher::PointPos::start;
            coincident.Second = -1;
            coincident.SecondPos = Sketcher::PointPos::start;
            sketch_line_->addConstraint(&coincident);
        }
        doc_->recompute();
        sketch_line_->solve();

#ifdef PIPE_SAVE_TEST_FCSTD
        {
            auto p = std::filesystem::temp_directory_path();
            doc_->saveAs((p / "FeaturePipeTest-circle-line.FCStd").c_str());
        }
#endif

        ASSERT_TRUE(sketch_circle_->FullyConstrained.getValue());
        ASSERT_TRUE(sketch_line_->FullyConstrained.getValue());
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(docName_.c_str());
    }

    // NOLINTBEGIN(cppcoreguidelines-non-private-member-variables-in-classes)

    App::Document* doc_ = nullptr;
    std::string docName_;
    Sketcher::SketchObject* sketch_circle_ = nullptr;
    Sketcher::SketchObject* sketch_line_ = nullptr;
    PartDesign::Body* body_ = nullptr;
    PartDesign::ShapeBinder* binder_circle_ = nullptr;
    PartDesign::ShapeBinder* binder_line_ = nullptr;

    // Volume of a cylinder is
    // V = pi * r^2 * h
    // calculated for the values in this unit test
    static constexpr double volume_expected_ = M_PI * 0.5 * 0.5 * 1;

    // NOLINTEND(cppcoreguidelines-non-private-member-variables-in-classes)
};

TEST_F(FeaturePipeTest, SketchProfileSketchSpine)
{
    auto pipe = doc_->addObject<PartDesign::AdditivePipe>("pipe");
    body_->addObject(pipe);

    pipe->Spine.setValue(sketch_line_);
    pipe->Profile.setValue(sketch_circle_);
    doc_->recompute();
#ifdef PIPE_SAVE_TEST_FCSTD
    {
        auto p = std::filesystem::temp_directory_path();
        doc_->saveAs((p / "FeaturePipeTest-SketchProfileSketchSpine.FCStd").c_str());
    }
#endif

    auto shape = pipe->Shape.getShape().getShape();
    auto volume_measured = getVolume(shape);
    ASSERT_NEAR(volume_expected_, volume_measured, 0.001);
}

TEST_F(FeaturePipeTest, SketchProfileBinderSpine)
{
    auto binderspine = doc_->addObject<PartDesign::SubShapeBinder>("bind-spine");
    binderspine->Shape.setValue(sketch_line_->Shape.getShape());
    body_->addObject(binderspine);

    auto pipe = doc_->addObject<PartDesign::AdditivePipe>("pipe");
    body_->addObject(pipe);

    pipe->Spine.setValue(binderspine);
    pipe->Profile.setValue(sketch_circle_);
    doc_->recompute();
#ifdef PIPE_SAVE_TEST_FCSTD
    {
        auto p = std::filesystem::temp_directory_path();
        doc_->saveAs((p / "FeaturePipeTest-SketchProfileBinderSpine.FCStd").c_str());
    }
#endif

    auto shape = pipe->Shape.getShape().getShape();
    auto volume_measured = getVolume(shape);
    ASSERT_NEAR(volume_expected_, volume_measured, 0.001);
}

namespace
{
/// The solid that a square of side 2 centred at (x, 0, 0), square to Z, sweeps along \a spine
/// (Standard mode), turned outward by its volume's sign (exact enough for these shapes), and the
/// sections where the sweep starts and ends
struct SweptSquare
{
    TopoDS_Shape solid;
    std::vector<TopoDS_Shape> starts;
    std::vector<TopoDS_Shape> ends;
};

SweptSquare sweepSquare(const TopoDS_Wire& spine, double x)
{
    BRepBuilderAPI_MakePolygon square(
        gp_Pnt(x - 1, -1, 0),
        gp_Pnt(x + 1, -1, 0),
        gp_Pnt(x + 1, 1, 0),
        gp_Pnt(x - 1, 1, 0),
        true
    );
    BRepOffsetAPI_MakePipeShell sweep(spine);
    sweep.Add(square.Wire());
    sweep.Build();
    sweep.MakeSolid();
    TopoDS_Shape solid = sweep.Shape();
    GProp_GProps properties;
    BRepGProp::VolumeProperties(solid, properties);
    if (properties.Mass() < 0) {
        solid.Reverse();
    }
    return {solid, {sweep.FirstShape()}, {sweep.LastShape()}};
}
}  // namespace

// The caps of a pipe tell which way its solid faces, without OCCT's solid classifier (ops#396):
// along a line, both caps face out of the outward solid and into the reversed one
TEST(PipeCapsFacing, StraightPipe)
{
    const TopoDS_Wire spine = BRepBuilderAPI_MakeWire(
                                  BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(0, 0, 10)).Edge()
    )
                                  .Wire();
    const SweptSquare swept = sweepSquare(spine, 0);
    const PartDesign::PipeCapFacing outward
        = PartDesign::pipeCapsFacing(swept.solid, spine, swept.starts, swept.ends, true);
    EXPECT_EQ(outward.outward, 2);
    EXPECT_EQ(outward.inward, 0);
    const PartDesign::PipeCapFacing inward
        = PartDesign::pipeCapsFacing(swept.solid.Reversed(), spine, swept.starts, swept.ends, true);
    EXPECT_EQ(inward.outward, 0);
    EXPECT_EQ(inward.inward, 2);
    // Without the sections, no cap is found
    const PartDesign::PipeCapFacing none = PartDesign::pipeCapsFacing(swept.solid, spine, {}, {}, true);
    EXPECT_EQ(none.outward + none.inward, 0);
}

// A profile beyond the centre of the spine's bend (an arc of radius 5 about (5, 0, 0), the square
// centred 10 from the spine's start) moves backwards as the frame turns: its start cap faces along
// the spine's tangent, yet out of the solid. The spine's tangent alone gets both caps wrong.
TEST(PipeCapsFacing, ProfileBeyondTheBendsCentre)
{
    const Handle(Geom_TrimmedCurve)
        arc = GC_MakeArcOfCircle(gp_Pnt(0, 0, 0), gp_Vec(0, 0, 1), gp_Pnt(5, 0, 5)).Value();
    const TopoDS_Wire spine = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(arc).Edge()).Wire();
    const SweptSquare swept = sweepSquare(spine, 10);
    // Pappus: the square's area 4 turned a quarter turn at 5 from the axis
    GProp_GProps properties;
    BRepGProp::VolumeProperties(swept.solid, properties);
    EXPECT_NEAR(properties.Mass(), 4 * 5 * M_PI / 2, 1e-3);
    const PartDesign::PipeCapFacing turning
        = PartDesign::pipeCapsFacing(swept.solid, spine, swept.starts, swept.ends, true);
    EXPECT_EQ(turning.outward, 2);
    EXPECT_EQ(turning.inward, 0);
    const PartDesign::PipeCapFacing tangentOnly
        = PartDesign::pipeCapsFacing(swept.solid, spine, swept.starts, swept.ends, false);
    EXPECT_EQ(tangentOnly.inward, 2);
}

namespace
{
/// Two names whose full form is at least \a atLeast bytes long while the name table holds them
/// in two nodes a level: each level's two names link both names of the level below, so the full
/// form more than doubles per level. A split face's name grows so when a dress-up's edge on it
/// is named from the face (`notes\name-growth.md`); built here directly, since the writer no
/// longer makes such names by that road.
std::pair<std::string, std::string> namesLongInFull(std::size_t atLeast)
{
    Data::NameTable& table = Data::NameTable::instance();
    auto section = [](const std::vector<std::string>& linked, const char* op) {
        return Data::MappedName::makeEncodedSection(
            std::vector<std::string> {},
            linked,
            std::string("7"),
            op,
            std::string("0"),
            'E',
            std::string("0"),
            std::vector<std::string> {Data::MAPPER_FLAG_MODIFIED},
            std::vector<std::string> {}
        );
    };
    std::string one = section({"g1"}, "TSA");
    std::string other = section({"g2"}, "TSB");
    while (table.toPlain(one).size() < atLeast) {
        const std::string refOne = Data::NameTable::makeRef(*table.internName(one));
        const std::string refOther = Data::NameTable::makeRef(*table.internName(other));
        one = section({refOne, refOther}, "TSA");
        other = section({refOther, refOne}, "TSB");
    }
    return {one, other};
}

/// The memory the process holds, in bytes, where the system tells
std::optional<std::uint64_t> memoryHeld()
{
#if defined(_WIN32)
    PROCESS_MEMORY_COUNTERS_EX counters {};
    if (GetProcessMemoryInfo(
            GetCurrentProcess(),
            reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&counters),  // NOLINT
            sizeof(counters)
        )) {
        return counters.PrivateUsage;
    }
    return std::nullopt;
#elif defined(__linux__)
    std::ifstream statm("/proc/self/statm");
    // In pages: the program's size, what of it is in memory, and what of that is backed by files
    // (code first touched by the second pipe isn't memory the names keep)
    std::uint64_t total = 0;
    std::uint64_t resident = 0;
    std::uint64_t shared = 0;
    if (statm >> total >> resident >> shared && resident >= shared) {
        return (resident - shared) * static_cast<std::uint64_t>(sysconf(_SC_PAGESIZE));
    }
    return std::nullopt;
#else
    return std::nullopt;
#endif
}
}  // namespace

// A Pipe keys each corner of its spine by the names of the two edges there. Written out in full
// to be keyed, a name of megabytes cost seconds a megabyte and stayed in the decoder's cache for
// the process's life; a real document's names reach half a gigabyte, and its Pipe never ended
// (ops#640, `notes\pipe-corner-names-memory.md`). The names are keyed from the name table's
// nodes instead: a spine of two edges with such names costs what a spine of one edge costs (which
// has no corner, and never read its names), and keeps no memory.
TEST_F(FeaturePipeTest, aCornerBetweenEdgesWithLongNamesCostsWhatNoCornerCosts)
{
    doc_->InternNames.setValue(true);
    const std::size_t longName = 8'000'000;
    const auto [nameOne, nameOther] = namesLongInFull(longName);
    auto spine = doc_->addObject<Part::Feature>("spine");
    const TopoDS_Edge first = BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(0, 0, 5)).Edge();
    const TopoDS_Edge second = BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 5), gp_Pnt(0, 2, 10)).Edge();
    Part::TopoShape wire(spine->getID());
    wire.setInternNames(true);
    wire.setShape(BRepBuilderAPI_MakeWire(first, second).Wire());
    wire.setElementName(
        Data::IndexedName::fromConst("Edge", 1),
        Data::MappedName(nameOne),
        spine->getID()
    );
    wire.setElementName(
        Data::IndexedName::fromConst("Edge", 2),
        Data::MappedName(nameOther),
        spine->getID()
    );
    spine->Shape.setValue(wire);
    // The spine's edges have the long names
    for (const char* edge : {"Edge1", "Edge2"}) {
        const auto names = spine->Shape.getShape().getElementMappedNames(
            Data::IndexedName(edge)
        );
        ASSERT_EQ(names.size(), 1) << edge;
        ASSERT_GE(Data::NameTable::instance().toPlain(names.front().first.toString()).size(), longName)
            << edge;
    }

    // The seconds a pipe of the circle along \a edges of the spine takes, the pipe valid
    auto secondsAlong = [&](const std::vector<std::string>& edges, double volumeAtLeast) {
        auto pipe = doc_->addObject<PartDesign::AdditivePipe>("pipe");
        body_->addObject(pipe);
        pipe->Profile.setValue(sketch_circle_);
        pipe->Spine.setValue(spine, edges);
        const auto start = std::chrono::steady_clock::now();
        doc_->recompute();
        const std::chrono::duration<double> taken = std::chrono::steady_clock::now() - start;
        EXPECT_TRUE(pipe->isValid()) << pipe->getStatusString();
        EXPECT_GT(getVolume(pipe->Shape.getShape().getShape()), volumeAtLeast);
        doc_->removeObject(pipe->getNameInDocument());
        return taken.count();
    };
    // The circle's area, pi / 4, along 5, and along 5 and the square root of 29
    const double withoutCorner = secondsAlong({"Edge1"}, 3.9);
    const std::optional<std::uint64_t> before = memoryHeld();
    const double withCorner = secondsAlong({"Edge1", "Edge2"}, 7.5);
    const std::optional<std::uint64_t> after = memoryHeld();
    // Written out, the two names took 8 s and kept 71 MB
    EXPECT_LT(withCorner, withoutCorner + 1.5);
    if (before && after) {
        EXPECT_LT(*after, *before + 32'000'000);
        std::cout << "memory kept: " << static_cast<double>(*after) - static_cast<double>(*before)
                  << " bytes" << std::endl;
    }
    std::cout << "seconds without a corner " << withoutCorner << ", with one " << withCorner
              << std::endl;
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
