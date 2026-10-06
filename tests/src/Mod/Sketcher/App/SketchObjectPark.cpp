// SPDX-License-Identifier: LGPL-2.1-or-later

// Parking a sketch's projections in place and putting them back (ops#131): a reorder that drops
// the sketch's feature above the projected solid removes the link and keeps the geometries, with
// their Ids and constraints, and the move back gives the link the same geometries again.

#include <gtest/gtest.h>

#include <filesystem>

#include <BRep_Tool.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>

#include <App/Application.h>
#include <App/Document.h>
#include <Base/FileInfo.h>
#include <Mod/Part/App/FeaturePartBox.h>
#include <Mod/Part/App/Geometry.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Sketcher/App/ExternalGeometryFacade.h>
#include <Mod/Sketcher/App/GeoEnum.h>
#include <Mod/Sketcher/App/SketchObject.h>
#include "SketcherTestHelpers.h"

using namespace Sketcher;

namespace
{

constexpr double tolerance = 1e-7;

// The box's edges that run along x in a plane z = const: the sketch (on XY) projects each onto a
// line of the same x range
std::vector<std::string> edgesAlongX(App::DocumentObject* box)
{
    std::vector<std::string> names;
    auto shape = Part::Feature::getTopoShape(box, Part::ShapeOption::NoFlag);
    for (int i = 1; i <= static_cast<int>(shape.countSubShapes(TopAbs_EDGE)); ++i) {
        std::string name = "Edge" + std::to_string(i);
        auto edge = TopoDS::Edge(shape.getSubShape(name.c_str()));
        auto p1 = BRep_Tool::Pnt(TopExp::FirstVertex(edge));
        auto p2 = BRep_Tool::Pnt(TopExp::LastVertex(edge));
        if (std::abs(p1.Z() - p2.Z()) < tolerance && std::abs(p1.Y() - p2.Y()) < tolerance
            && std::abs(p1.X() - p2.X()) > tolerance) {
            names.push_back(name);
        }
    }
    return names;
}

// A box edge along z: the sketch (on XY) intersects it in a point
std::string edgeAlongZ(App::DocumentObject* box)
{
    auto shape = Part::Feature::getTopoShape(box, Part::ShapeOption::NoFlag);
    for (int i = 1; i <= static_cast<int>(shape.countSubShapes(TopAbs_EDGE)); ++i) {
        std::string name = "Edge" + std::to_string(i);
        auto edge = TopoDS::Edge(shape.getSubShape(name.c_str()));
        auto p1 = BRep_Tool::Pnt(TopExp::FirstVertex(edge));
        auto p2 = BRep_Tool::Pnt(TopExp::LastVertex(edge));
        if (std::abs(p1.X() - p2.X()) < tolerance && std::abs(p1.Y() - p2.Y()) < tolerance) {
            return name;
        }
    }
    return {};
}

// The ends of the box's edge, on the sketch's plane
std::pair<Base::Vector3d, Base::Vector3d> edgeEnds(App::DocumentObject* box, const std::string& name)
{
    auto shape = Part::Feature::getTopoShape(box, Part::ShapeOption::NoFlag);
    auto edge = TopoDS::Edge(shape.getSubShape(name.c_str()));
    auto p1 = BRep_Tool::Pnt(TopExp::FirstVertex(edge));
    auto p2 = BRep_Tool::Pnt(TopExp::LastVertex(edge));
    return {Base::Vector3d(p1.X(), p1.Y(), 0), Base::Vector3d(p2.X(), p2.Y(), 0)};
}

// Whether the line segment `geo` has the ends `ends`, in either direction
bool hasEnds(const Part::Geometry* geo, const std::pair<Base::Vector3d, Base::Vector3d>& ends)
{
    auto line = dynamic_cast<const Part::GeomLineSegment*>(geo);
    if (!line) {
        return false;
    }
    auto s = line->getStartPoint();
    auto e = line->getEndPoint();
    return (s.IsEqual(ends.first, tolerance) && e.IsEqual(ends.second, tolerance))
        || (s.IsEqual(ends.second, tolerance) && e.IsEqual(ends.first, tolerance));
}

std::string refOf(const Part::Geometry* geo)
{
    return ExternalGeometryFacade::getFacade(geo)->getRef();
}

long idOf(const Part::Geometry* geo)
{
    return ExternalGeometryFacade::getFacade(geo)->getId();
}

}  // namespace

class SketchObjectParkTest: public SketchObjectTest
{
protected:
    void SetUp() override
    {
        SketchObjectTest::SetUp();
        doc = getObject()->getDocument();
        box = doc->addObject("Part::Box", "Box");
        doc->recompute();
        auto edges = edgesAlongX(box);
        ASSERT_GE(edges.size(), 2U);
        edge = edges[0];
        otherEdge = edges[1];
        verticalEdge = edgeAlongZ(box);
        ASSERT_FALSE(verticalEdge.empty());
    }

    // Projects `edge`, adds a line whose start is coincident with the projection's start and a
    // named distance from the line's end to the projection, and recomputes
    void projectWithConstraints()
    {
        ASSERT_GE(getObject()->addExternal(box, edge.c_str()), 0);
        Part::GeomLineSegment line;
        line.setPoints(Base::Vector3d(1, 1, 0), Base::Vector3d(4, 6, 0));
        lineId = getObject()->addGeometry(&line);

        auto coincident = new Sketcher::Constraint();
        coincident->Type = Sketcher::Coincident;
        coincident->First = lineId;
        coincident->FirstPos = Sketcher::PointPos::start;
        coincident->Second = GeoEnum::RefExt;
        coincident->SecondPos = Sketcher::PointPos::start;
        getObject()->addConstraint(coincident);

        auto gap = new Sketcher::Constraint();
        gap->Type = Sketcher::DistanceY;
        gap->First = GeoEnum::RefExt;
        gap->FirstPos = Sketcher::PointPos::start;
        gap->Second = lineId;
        gap->SecondPos = Sketcher::PointPos::end;
        gap->setValue(5.0);
        gap->Name = "gap";
        getObject()->addConstraint(gap);
        doc->recompute();
        ASSERT_TRUE(getObject()->isValid());
    }

    const Part::Geometry* projection()
    {
        return getObject()->getGeometry(GeoEnum::RefExt);
    }

    App::Document* doc {};
    App::DocumentObject* box {};
    std::string edge;
    std::string otherEdge;
    std::string verticalEdge;  // an intersection gives its point
    int lineId {};

    void unparkReplacesADeletedGeometry(int deleted);
};

TEST_F(SketchObjectParkTest, parkKeepsGeometryIdAndConstraints)
{
    // Arrange
    projectWithConstraints();
    auto sketch = getObject();
    const auto ends = edgeEnds(box, edge);
    const int geoCount = sketch->ExternalGeo.getSize();
    const int constraintCount = sketch->Constraints.getSize();
    const auto ids = sketch->externalGeometryIds(0);
    ASSERT_EQ(ids.size(), 1U);
    EXPECT_EQ(idOf(projection()), ids[0]);
    EXPECT_TRUE(hasEnds(projection(), ends));
    EXPECT_EQ(sketch->externalType(0), 0);

    // Act
    sketch->parkExternalGeometry({0});

    // Assert: the link is gone, the geometry stays in place without a reference
    EXPECT_EQ(sketch->ExternalGeometry.getSize(), 0);
    EXPECT_EQ(sketch->ExternalTypes.getSize(), 0);
    EXPECT_EQ(sketch->ExternalGeo.getSize(), geoCount);
    EXPECT_EQ(idOf(projection()), ids[0]);
    EXPECT_EQ(refOf(projection()), "");
    EXPECT_EQ(sketch->externalGeometryRefOf(ids[0]), std::string());
    EXPECT_TRUE(hasEnds(projection(), ends));
    EXPECT_EQ(sketch->Constraints.getSize(), constraintCount);
    EXPECT_EQ(sketch->Constraints.getValues()[1]->Name, "gap");
    EXPECT_EQ(sketch->Constraints.getValues()[1]->First, GeoEnum::RefExt);

    // A recompute keeps it as fixed geometry: not rebuilt, not missing, constraints solved
    doc->recompute();
    EXPECT_TRUE(sketch->isValid());
    EXPECT_EQ(sketch->ExternalGeo.getSize(), geoCount);
    EXPECT_EQ(idOf(projection()), ids[0]);
    EXPECT_FALSE(ExternalGeometryFacade::getFacade(projection())
                     ->testFlag(ExternalGeometryExtension::Missing));
    EXPECT_TRUE(hasEnds(projection(), ends));
    EXPECT_EQ(sketch->Constraints.getSize(), constraintCount);
    auto line = static_cast<const Part::GeomLineSegment*>(sketch->getGeometry(lineId));
    auto start = static_cast<const Part::GeomLineSegment*>(projection())->getStartPoint();
    EXPECT_TRUE(line->getStartPoint().IsEqual(start, tolerance));
}

TEST_F(SketchObjectParkTest, unparkGivesTheSameGeometryBack)
{
    // Arrange
    projectWithConstraints();
    auto sketch = getObject();
    const auto ids = sketch->externalGeometryIds(0);
    const std::string ref = refOf(projection());
    const std::string sub = sketch->ExternalGeometry.getSubValues()[0];
    auto shadow = sketch->ExternalGeometry.getShadowSubs()[0];
    const int geoCount = sketch->ExternalGeo.getSize();
    const int constraintCount = sketch->Constraints.getSize();
    sketch->parkExternalGeometry({0});
    doc->recompute();

    // The box grows while the projection is parked: the parked geometry doesn't follow
    auto length = static_cast<Part::Box*>(box)->Length.getValue();
    static_cast<Part::Box*>(box)->Length.setValue(length + 4);
    doc->recompute();
    const auto newEnds = edgeEnds(box, edge);
    EXPECT_FALSE(hasEnds(projection(), newEnds));

    // Act
    int replaced = sketch->unparkExternalGeometry(box, sub, std::move(shadow), 0, ids);
    doc->recompute();

    // Assert: the link is back on the same geometry, which follows the edge again
    EXPECT_EQ(replaced, 0);
    EXPECT_TRUE(sketch->isValid());
    ASSERT_EQ(sketch->ExternalGeometry.getSize(), 1);
    EXPECT_EQ(sketch->ExternalGeometry.getValues()[0], box);
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0}));
    EXPECT_EQ(sketch->ExternalGeo.getSize(), geoCount);
    EXPECT_EQ(idOf(projection()), ids[0]);
    EXPECT_EQ(refOf(projection()), ref);
    EXPECT_EQ(sketch->externalGeometryIds(0), ids);
    EXPECT_FALSE(ExternalGeometryFacade::getFacade(projection())
                     ->testFlag(ExternalGeometryExtension::Missing));
    EXPECT_TRUE(hasEnds(projection(), newEnds));
    EXPECT_EQ(sketch->Constraints.getSize(), constraintCount);
    EXPECT_EQ(sketch->Constraints.getValues()[1]->Name, "gap");
    auto line = static_cast<const Part::GeomLineSegment*>(sketch->getGeometry(lineId));
    auto start = static_cast<const Part::GeomLineSegment*>(projection())->getStartPoint();
    EXPECT_TRUE(line->getStartPoint().IsEqual(start, tolerance));
    EXPECT_NEAR(line->getEndPoint().y - start.y, 5.0, tolerance);
}

TEST_F(SketchObjectParkTest, parkOneOfTwoKeepsTheOther)
{
    // Arrange: two projections; the second's link keeps its shadow when the first is parked
    projectWithConstraints();
    auto sketch = getObject();
    ASSERT_GE(sketch->addExternal(box, verticalEdge.c_str(), false, true), 0);
    doc->recompute();
    ASSERT_EQ(sketch->ExternalGeometry.getSize(), 2);
    const auto firstIds = sketch->externalGeometryIds(0);
    const auto secondIds = sketch->externalGeometryIds(1);
    ASSERT_FALSE(secondIds.empty());
    EXPECT_EQ(sketch->externalType(1), 1);
    const auto secondShadow = sketch->ExternalGeometry.getShadowSubs()[1];
    const auto secondRef = sketch->externalGeometryRefOf(secondIds[0]);
    const int geoCount = sketch->ExternalGeo.getSize();

    // Act
    sketch->parkExternalGeometry({0});

    // Assert
    ASSERT_EQ(sketch->ExternalGeometry.getSize(), 1);
    EXPECT_EQ(sketch->ExternalGeometry.getSubValues()[0], verticalEdge);
    EXPECT_EQ(sketch->ExternalGeometry.getShadowSubs()[0], secondShadow);
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({1}));
    EXPECT_EQ(sketch->externalGeometryIds(0), secondIds);
    EXPECT_EQ(sketch->externalGeometryRefOf(secondIds[0]), secondRef);
    EXPECT_EQ(sketch->externalGeometryRefOf(firstIds[0]), std::string());
    doc->recompute();
    EXPECT_TRUE(sketch->isValid());
    EXPECT_EQ(sketch->ExternalGeo.getSize(), geoCount);
    EXPECT_EQ(sketch->externalGeometryIds(0), secondIds);
}

TEST_F(SketchObjectParkTest, unparkKeepsTheTypes)
{
    // Arrange: an intersection, parked; then a projection added while it is parked
    auto sketch = getObject();
    ASSERT_GE(sketch->addExternal(box, verticalEdge.c_str(), false, true), 0);
    doc->recompute();
    const auto ids = sketch->externalGeometryIds(0);
    ASSERT_EQ(ids.size(), 1U);
    const std::string sub = sketch->ExternalGeometry.getSubValues()[0];
    auto shadow = sketch->ExternalGeometry.getShadowSubs()[0];
    sketch->parkExternalGeometry({0});
    ASSERT_GE(sketch->addExternal(box, otherEdge.c_str()), 0);
    doc->recompute();
    ASSERT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0}));

    // Act
    sketch->unparkExternalGeometry(box, sub, std::move(shadow), 1, ids);
    doc->recompute();

    // Assert
    EXPECT_TRUE(sketch->isValid());
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 1}));
    EXPECT_EQ(sketch->externalGeometryIds(1), ids);
    EXPECT_TRUE(sketch->getGeometry(GeoEnum::RefExt)->is<Part::GeomPoint>());
}

// A face gives four geometries, and a line has its ends on the second's and the fourth's start;
// parked, the geometry at `deleted` (0 or 2) is deleted, then the entry is put back. The deleted
// one comes back as new geometry at its own place in the projection order, the others on their
// Ids, and the line's constraints on the same geometries; this lasts through two more rebuilds and
// a save and reopen, which rebuild the order of the Ids from ExternalGeo.
void SketchObjectParkTest::unparkReplacesADeletedGeometry(int deleted)
{
    // Arrange
    auto sketch = getObject();
    std::string face;
    auto shape = Part::Feature::getTopoShape(box, Part::ShapeOption::NoFlag);
    for (int i = 1; i <= static_cast<int>(shape.countSubShapes(TopAbs_FACE)) && face.empty(); ++i) {
        std::string name = "Face" + std::to_string(i);
        Base::BoundBox3d bb = shape.getSubTopoShape(name.c_str()).getBoundBox();
        if (bb.LengthZ() < tolerance) {
            face = name;
        }
    }
    ASSERT_FALSE(face.empty());
    ASSERT_GE(sketch->addExternal(box, face.c_str()), 0);
    doc->recompute();
    const auto ids = sketch->externalGeometryIds(0);
    ASSERT_EQ(ids.size(), 4U);
    const std::string ref = refOf(sketch->getGeometry(GeoEnum::RefExt));
    std::vector<std::pair<Base::Vector3d, Base::Vector3d>> before;
    for (int i = 0; i < 4; ++i) {
        auto line = dynamic_cast<const Part::GeomLineSegment*>(
            sketch->getGeometry(GeoEnum::RefExt - i));
        ASSERT_NE(line, nullptr);
        before.emplace_back(line->getStartPoint(), line->getEndPoint());
    }
    Part::GeomLineSegment segment;
    segment.setPoints(Base::Vector3d(1, 1, 0), Base::Vector3d(4, 6, 0));
    const int line = sketch->addGeometry(&segment);
    for (int edge : {1, 3}) {
        auto coincident = new Sketcher::Constraint();
        coincident->Type = Sketcher::Coincident;
        coincident->First = line;
        coincident->FirstPos = edge == 1 ? Sketcher::PointPos::start : Sketcher::PointPos::end;
        coincident->Second = GeoEnum::RefExt - edge;
        coincident->SecondPos = Sketcher::PointPos::start;
        sketch->addConstraint(coincident);
    }
    doc->recompute();
    ASSERT_TRUE(sketch->isValid());
    const int geoCount = sketch->ExternalGeo.getSize();
    const std::string sub = sketch->ExternalGeometry.getSubValues()[0];
    auto shadow = sketch->ExternalGeometry.getShadowSubs()[0];
    sketch->parkExternalGeometry({0});
    // Deleting a geometry without a reference deletes only that one
    ASSERT_EQ(sketch->delExternal(deleted), 0);
    EXPECT_EQ(sketch->ExternalGeo.getSize(), geoCount - 1);
    EXPECT_FALSE(sketch->externalGeometryRefOf(ids[deleted]).has_value());

    // Act
    int replaced = sketch->unparkExternalGeometry(box, sub, std::move(shadow), 0, ids);
    doc->recompute();

    // Assert: each projection at its own place, the kept ones on their Ids, the line's ends on the
    // second's and the fourth's start
    EXPECT_EQ(replaced, 1);
    auto expected = ids;
    expected[deleted] = idOf(sketch->getGeometry(GeoEnum::RefExt - deleted));
    EXPECT_EQ(std::count(ids.begin(), ids.end(), expected[deleted]), 0);
    auto expectInPlace = [&](Sketcher::SketchObject* sketch) {
        EXPECT_TRUE(sketch->isValid());
        EXPECT_EQ(sketch->ExternalGeo.getSize(), geoCount);
        EXPECT_EQ(sketch->externalGeometryIds(0), expected);
        for (int i = 0; i < 4; ++i) {
            auto geo = sketch->getGeometry(GeoEnum::RefExt - i);
            EXPECT_EQ(idOf(geo), expected[i]) << "projection " << i;
            EXPECT_EQ(refOf(geo), ref) << "projection " << i;
            EXPECT_TRUE(hasEnds(geo, before[i])) << "projection " << i;
        }
        const auto& constraints = sketch->Constraints.getValues();
        ASSERT_EQ(constraints.size(), 2U);
        EXPECT_EQ(constraints[0]->Second, GeoEnum::RefExt - 1);
        EXPECT_EQ(constraints[1]->Second, GeoEnum::RefExt - 3);
        auto segment = static_cast<const Part::GeomLineSegment*>(sketch->getGeometry(line));
        EXPECT_TRUE(segment->getStartPoint().IsEqual(before[1].first, tolerance));
        EXPECT_TRUE(segment->getEndPoint().IsEqual(before[3].first, tolerance));
    };
    expectInPlace(sketch);
    for (int i = 0; i < 2; ++i) {
        sketch->touch();
        doc->recompute();
        expectInPlace(sketch);
    }

    // and through a save and reopen (under the same name, which TearDown closes)
    const std::string name = doc->getName();
    const std::string sketchName = sketch->getNameInDocument();
    auto path = std::filesystem::temp_directory_path() / (name + ".FCStd");
    doc->saveAs(Base::FileInfo::pathToString(path).c_str());
    App::GetApplication().closeDocument(name.c_str());
    doc = App::GetApplication().openDocument(Base::FileInfo::pathToString(path).c_str());
    ASSERT_NE(doc, nullptr);
    ASSERT_EQ(std::string(doc->getName()), name);
    sketch = static_cast<Sketcher::SketchObject*>(doc->getObject(sketchName.c_str()));
    ASSERT_NE(sketch, nullptr);
    sketch->touch();
    doc->recompute();
    expectInPlace(sketch);
    std::filesystem::remove(path);
}

TEST_F(SketchObjectParkTest, unparkReplacesADeletedGeometry)
{
    unparkReplacesADeletedGeometry(0);
}

TEST_F(SketchObjectParkTest, unparkReplacesADeletedMiddleGeometry)
{
    unparkReplacesADeletedGeometry(2);
}

TEST_F(SketchObjectParkTest, parkUndoesAndRedoes)
{
    // Arrange
    projectWithConstraints();
    auto sketch = getObject();
    const auto ids = sketch->externalGeometryIds(0);
    const std::string ref = refOf(projection());

    // Act
    doc->openTransaction("Park");
    sketch->parkExternalGeometry({0});
    doc->commitTransaction();
    doc->undo();
    doc->recompute();

    // Assert: undo brings the link, the reference and the type back
    EXPECT_TRUE(sketch->isValid());
    ASSERT_EQ(sketch->ExternalGeometry.getSize(), 1);
    EXPECT_EQ(sketch->ExternalTypes.getSize(), 1);
    EXPECT_EQ(refOf(projection()), ref);
    EXPECT_EQ(sketch->externalGeometryIds(0), ids);

    // and redo parks again
    doc->redo();
    doc->recompute();
    EXPECT_TRUE(sketch->isValid());
    EXPECT_EQ(sketch->ExternalGeometry.getSize(), 0);
    EXPECT_EQ(sketch->ExternalTypes.getSize(), 0);
    EXPECT_EQ(refOf(projection()), "");
    EXPECT_EQ(idOf(projection()), ids[0]);
}

TEST_F(SketchObjectParkTest, parkRefusesAnUnknownEntry)
{
    // Arrange
    projectWithConstraints();
    auto sketch = getObject();

    // Act and assert: nothing is written
    EXPECT_THROW(sketch->parkExternalGeometry({1}), Base::IndexError);
    EXPECT_EQ(sketch->ExternalGeometry.getSize(), 1);
    EXPECT_NE(refOf(projection()), "");
}

TEST_F(SketchObjectParkTest, markMissingFlagsTheParkedGeometry)
{
    // Arrange: parked, then its object is gone
    projectWithConstraints();
    auto sketch = getObject();
    const auto ids = sketch->externalGeometryIds(0);
    const std::string ref = refOf(projection());
    const int geoCount = sketch->ExternalGeo.getSize();
    const int constraintCount = sketch->Constraints.getSize();
    sketch->parkExternalGeometry({0});
    doc->recompute();
    ASSERT_TRUE(sketch->isValid());

    // Act
    int marked = sketch->markExternalGeometryMissing(ids, ref);
    doc->recompute();

    // Assert: a missing reference, kept with its constraints, and the sketch fails naming it
    EXPECT_EQ(marked, 1);
    EXPECT_FALSE(sketch->isValid());
    EXPECT_EQ(sketch->ExternalGeo.getSize(), geoCount);
    EXPECT_EQ(refOf(projection()), ref);
    EXPECT_TRUE(ExternalGeometryFacade::getFacade(projection())
                    ->testFlag(ExternalGeometryExtension::Missing));
    EXPECT_EQ(sketch->Constraints.getSize(), constraintCount);
    EXPECT_NE(std::string(sketch->getStatusString()).find("Box"), std::string::npos);
    // A geometry that has a reference isn't touched
    EXPECT_EQ(sketch->markExternalGeometryMissing(ids, "Other.Edge1"), 0);
    EXPECT_EQ(refOf(projection()), ref);
}
