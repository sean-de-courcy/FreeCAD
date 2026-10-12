// SPDX-License-Identifier: LGPL-2.1-or-later

// Parking a sketch's projections in place and putting them back (ops#131): a reorder that drops
// the sketch's feature above the projected solid removes the link and keeps the geometries, with
// their Ids and constraints, and the move back gives the link the same geometries again.

#include <gtest/gtest.h>

#include <algorithm>
#include <filesystem>

#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRep_Tool.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>

#include <App/Application.h>
#include <App/Document.h>
#include <Base/Console.h>
#include <Base/FileInfo.h>
#include <src/TempDirectory.h>
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

// A box edge along x above the sketch's plane (z > 0): it gives a projection but no
// intersection
std::string edgeAlongXAbove(App::DocumentObject* box)
{
    auto shape = Part::Feature::getTopoShape(box, Part::ShapeOption::NoFlag);
    for (const auto& name : edgesAlongX(box)) {
        auto edge = TopoDS::Edge(shape.getSubShape(name.c_str()));
        if (BRep_Tool::Pnt(TopExp::FirstVertex(edge)).Z() > tolerance) {
            return name;
        }
    }
    return {};
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

// Sets `flag` on the external geometries at `indexes` (into ExternalGeo), as the Sketcher's
// toggles write it
void setExternalFlag(Sketcher::SketchObject* sketch,
                     const std::vector<int>& indexes,
                     ExternalGeometryExtension::Flag flag)
{
    auto geos = sketch->ExternalGeo.getValues();
    for (int index : indexes) {
        geos[index] = geos[index]->clone();
        ExternalGeometryFacade::getFacade(geos[index])->setFlag(flag, true);
    }
    sketch->ExternalGeo.setValues(std::move(geos));
}

// Collects the warnings and errors sent while it lives
class WarningCollector final: public Base::ILogger
{
public:
    WarningCollector()
    {
        Base::Console().attachObserver(this);
    }
    ~WarningCollector() override
    {
        Base::Console().detachObserver(this);
    }
    WarningCollector(const WarningCollector&) = delete;
    WarningCollector(WarningCollector&&) = delete;
    WarningCollector& operator=(const WarningCollector&) = delete;
    WarningCollector& operator=(WarningCollector&&) = delete;

    void sendLog(const std::string& /*notifiername*/,
                 const std::string& msg,
                 Base::LogStyle level,
                 Base::IntendedRecipient /*recipient*/,
                 Base::ContentType /*content*/) override
    {
        if (level == Base::LogStyle::Warning) {
            warnings.push_back(msg);
        }
        else if (level == Base::LogStyle::Error) {
            errors.push_back(msg);
        }
    }
    const char* name() override
    {
        return "WarningCollector";
    }

    std::size_t count(const std::string& text) const
    {
        return static_cast<std::size_t>(
            std::count_if(warnings.begin(), warnings.end(), [&](const std::string& msg) {
                return msg.find(text) != std::string::npos;
            }));
    }

    std::vector<std::string> warnings;
    std::vector<std::string> errors;
};

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

    // Projects the box's bottom face (four geometries) and recomputes; returns their ends
    std::vector<std::pair<Base::Vector3d, Base::Vector3d>> projectFace();
    void unparkReplacesADeletedGeometry(int deleted);
    // Projects `edge` and intersects a ball's face, then saves the sketch with a type list from
    // before ops#140 whose ball can't be told (its face gone) and reopens it: the list ends in
    // the mark of a pending repair, {0, 0, -1}
    void reopenWithPendingRepair(Sketcher::SketchObject*& sketch);
};

std::vector<std::pair<Base::Vector3d, Base::Vector3d>> SketchObjectParkTest::projectFace()
{
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
    std::vector<std::pair<Base::Vector3d, Base::Vector3d>> ends;
    if (face.empty() || sketch->addExternal(box, face.c_str()) < 0) {
        return ends;
    }
    doc->recompute();
    for (int i = 0; i < sketch->ExternalGeo.getSize() - 2; ++i) {
        auto line = dynamic_cast<const Part::GeomLineSegment*>(
            sketch->getGeometry(GeoEnum::RefExt - i));
        if (!line) {
            return {};
        }
        ends.emplace_back(line->getStartPoint(), line->getEndPoint());
    }
    return ends;
}

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
    const auto before = projectFace();
    ASSERT_EQ(before.size(), 4U);
    const auto ids = sketch->externalGeometryIds(0);
    ASSERT_EQ(ids.size(), 4U);
    const std::string ref = refOf(sketch->getGeometry(GeoEnum::RefExt));
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

// unpark puts a new geometry in place of a deleted one and moves the external GeoIds after it
// one on, in every constraint. With the constraint list flagged invalid (here the sketch's own
// geometry is gone) it read the list with getValues(), empty while flagged, and wrote that back:
// every constraint was gone (ops#237). The list stays flagged until the geometry is back.
TEST_F(SketchObjectParkTest, unparkWithInvalidConstraintListKeepsConstraints)
{
    // Arrange
    auto sketch = getObject();
    ASSERT_EQ(projectFace().size(), 4U);
    const auto ids = sketch->externalGeometryIds(0);
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
    const std::string sub = sketch->ExternalGeometry.getSubValues()[0];
    auto shadow = sketch->ExternalGeometry.getShadowSubs()[0];
    sketch->parkExternalGeometry({0});
    ASSERT_EQ(sketch->delExternal(0), 0);
    std::vector<Part::Geometry*> geometry;
    for (auto* geo : sketch->Geometry.getValues()) {
        geometry.push_back(geo->clone());
    }
    sketch->Geometry.setValues(std::vector<Part::Geometry*> {});
    ASSERT_TRUE(sketch->Constraints.getValues().empty());  // flagged invalid

    // Act
    int replaced = sketch->unparkExternalGeometry(box, sub, std::move(shadow), 0, ids);

    // Assert
    EXPECT_EQ(replaced, 1);
    EXPECT_TRUE(sketch->Constraints.getValues().empty());  // still flagged
    sketch->Geometry.setValues(std::move(geometry));
    const auto& constraints = sketch->Constraints.getValues();
    ASSERT_EQ(constraints.size(), 2U);
    EXPECT_EQ(constraints[0]->Second, GeoEnum::RefExt - 1);
    EXPECT_EQ(constraints[1]->Second, GeoEnum::RefExt - 3);
}

TEST_F(SketchObjectParkTest, unparkLeavesAFrozenEntryAlone)
{
    // Arrange: the face's projection frozen, parked, its third geometry deleted
    auto sketch = getObject();
    const auto before = projectFace();
    ASSERT_EQ(before.size(), 4U);
    const auto ids = sketch->externalGeometryIds(0);
    setExternalFlag(sketch, {2, 3, 4, 5}, ExternalGeometryExtension::Frozen);
    doc->recompute();
    const int geoCount = sketch->ExternalGeo.getSize();
    const std::string sub = sketch->ExternalGeometry.getSubValues()[0];
    auto shadow = sketch->ExternalGeometry.getShadowSubs()[0];
    sketch->parkExternalGeometry({0});
    ASSERT_EQ(sketch->delExternal(2), 0);

    // Act
    int replaced = sketch->unparkExternalGeometry(box, sub, std::move(shadow), 0, ids);
    doc->recompute();
    sketch->touch();
    doc->recompute();

    // Assert: the rebuild skips a frozen entry, so nothing stands in for the deleted geometry; the
    // others are where they were, on their Ids, still frozen
    EXPECT_EQ(replaced, 1);
    EXPECT_EQ(sketch->ExternalGeo.getSize(), geoCount - 1);
    const int keptAt[] = {0, 1, 3};
    for (int i = 0; i < 3; ++i) {
        auto geo = sketch->getGeometry(GeoEnum::RefExt - i);
        EXPECT_EQ(idOf(geo), ids[keptAt[i]]) << "projection " << keptAt[i];
        EXPECT_TRUE(hasEnds(geo, before[keptAt[i]])) << "projection " << keptAt[i];
        EXPECT_TRUE(ExternalGeometryFacade::getFacade(geo)->testFlag(
            ExternalGeometryExtension::Frozen));
    }
}

TEST_F(SketchObjectParkTest, unparkGivesANewGeometryTheEntrysDefiningState)
{
    // Arrange: parked, the second geometry alone made defining, the third deleted
    auto sketch = getObject();
    const auto before = projectFace();
    ASSERT_EQ(before.size(), 4U);
    const auto ids = sketch->externalGeometryIds(0);
    const std::string sub = sketch->ExternalGeometry.getSubValues()[0];
    auto shadow = sketch->ExternalGeometry.getShadowSubs()[0];
    sketch->parkExternalGeometry({0});
    setExternalFlag(sketch, {3}, ExternalGeometryExtension::Defining);
    ASSERT_EQ(sketch->delExternal(2), 0);

    // Act
    sketch->unparkExternalGeometry(box, sub, std::move(shadow), 0, ids);
    doc->recompute();

    // Assert: the new geometry is in place and not defining, as the entry isn't (one of its
    // geometries is); the second keeps its own state
    auto added = sketch->getGeometry(GeoEnum::RefExt - 2);
    EXPECT_TRUE(hasEnds(added, before[2]));
    EXPECT_FALSE(ExternalGeometryFacade::getFacade(added)->testFlag(
        ExternalGeometryExtension::Defining));
    EXPECT_TRUE(ExternalGeometryFacade::getFacade(sketch->getGeometry(GeoEnum::RefExt - 1))
                    ->testFlag(ExternalGeometryExtension::Defining));
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

void SketchObjectParkTest::reopenWithPendingRepair(Sketcher::SketchObject*& sketch)
{
    sketch = getObject();
    // a sphere of radius 10 about (0, 0, 6) crosses the sketch plane in a circle of radius 8
    auto* ball = static_cast<Part::Feature*>(doc->addObject("Part::Feature", "Ball"));
    ball->Shape.setValue(BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 6), 10).Shape());
    doc->recompute();
    ASSERT_GE(sketch->addExternal(box, edge.c_str(), false, false), 0);
    ASSERT_GE(sketch->addExternal(ball, "Face1", false, true), 0);
    doc->recompute();
    ASSERT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 1}));
    // the ball loses its face: its saved circle can't tell its type
    ball->Shape.setValue(BRepBuilderAPI_MakeVertex(gp_Pnt(0, 0, 6)).Shape());
    doc->recompute();
    // a list saved before ops#140: the ball reads a projection by index
    sketch->ExternalTypes.setValues({0, 0, 1});

    const std::string name = doc->getName();
    const std::string sketchName = sketch->getNameInDocument();
    // under the same name, which TearDown closes
    auto path = std::filesystem::temp_directory_path() / (name + ".FCStd");
    doc->saveAs(Base::FileInfo::pathToString(path).c_str());
    App::GetApplication().closeDocument(name.c_str());
    doc = App::GetApplication().openDocument(Base::FileInfo::pathToString(path).c_str());
    std::filesystem::remove(path);
    ASSERT_NE(doc, nullptr);
    ASSERT_EQ(std::string(doc->getName()), name);
    sketch = static_cast<Sketcher::SketchObject*>(doc->getObject(sketchName.c_str()));
    ASSERT_NE(sketch, nullptr);
    box = doc->getObject("Box");
    ASSERT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 0, -1}));
}

// A link appended to ExternalGeometry outside the sketch while an open's type repair is pending
// (the list ends in the mark) is a projection, before the mark: read by index, the mark would be
// its type, and it would build nothing (ops#237)
TEST_F(SketchObjectParkTest, linkAppendedWhileARepairIsPendingIsAProjection)
{
    Sketcher::SketchObject* sketch {};
    reopenWithPendingRepair(sketch);
    if (HasFatalFailure()) {
        return;
    }
    ASSERT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 0, -1}));

    auto objs = sketch->ExternalGeometry.getValues();
    auto subs = sketch->ExternalGeometry.getSubValues();
    objs.push_back(box);
    subs.push_back(otherEdge);
    sketch->ExternalGeometry.setValues(objs, subs);
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 0, 0, -1}));
    doc->recompute();
    ASSERT_EQ(sketch->externalGeometryIds(2).size(), 1U);
    // it is the other edge's projection: the last external geometry, between its ends
    auto shape = Part::Feature::getTopoShape(box, Part::ShapeOption::NoFlag);
    auto other = TopoDS::Edge(shape.getSubShape(otherEdge.c_str()));
    auto p1 = BRep_Tool::Pnt(TopExp::FirstVertex(other));
    auto p2 = BRep_Tool::Pnt(TopExp::LastVertex(other));
    auto* line =
        dynamic_cast<const Part::GeomLineSegment*>(sketch->ExternalGeo.getValues().back());
    ASSERT_NE(line, nullptr);
    std::vector<Base::Vector3d> ends {line->getStartPoint(), line->getEndPoint()};
    std::vector<Base::Vector3d> expected {Base::Vector3d(p1.X(), p1.Y(), 0),
                                          Base::Vector3d(p2.X(), p2.Y(), 0)};
    auto byX = [](const Base::Vector3d& a, const Base::Vector3d& b) { return a.x < b.x; };
    std::sort(ends.begin(), ends.end(), byX);
    std::sort(expected.begin(), expected.end(), byX);
    for (std::size_t k = 0; k < 2; ++k) {
        EXPECT_TRUE(ends[k].IsEqual(expected[k], tolerance));
    }
}

// Links that change beyond an append while a repair is pending (here: reordered, then one
// appended) leave the types as they are, with a warning: which pending entry belongs to which
// link isn't known (ops#237, PR 218 review L4: untested)
TEST_F(SketchObjectParkTest, linksReorderedWhileARepairIsPendingWarn)
{
    Sketcher::SketchObject* sketch {};
    reopenWithPendingRepair(sketch);
    if (HasFatalFailure()) {
        return;
    }
    auto objs = sketch->ExternalGeometry.getValues();
    auto subs = sketch->ExternalGeometry.getSubValues();
    ASSERT_EQ(objs.size(), 2U);
    std::swap(objs[0], objs[1]);
    std::swap(subs[0], subs[1]);
    objs.push_back(box);
    subs.push_back(otherEdge);
    WarningCollector collector;
    sketch->ExternalGeometry.setValues(objs, subs);
    EXPECT_EQ(collector.count("changed beyond an append"), 1U);
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 0, -1}));
}

// A carbon copy from a sketch whose link's type an open couldn't tell is refused, naming the
// link, and changes neither sketch: copied, the guess at its index became the copy's settled type,
// with no mark and no warning (ops#237, PR 262 review M1)
TEST_F(SketchObjectParkTest, carbonCopyOfAnUndecidedLinkIsRefused)
{
    Sketcher::SketchObject* sketch {};
    reopenWithPendingRepair(sketch);
    if (HasFatalFailure()) {
        return;
    }
    auto* dest = static_cast<Sketcher::SketchObject*>(
        doc->addObject("Sketcher::SketchObject", "Dest"));
    Part::GeomLineSegment line;
    line.setPoints(Base::Vector3d(20, 0, 0), Base::Vector3d(30, 0, 0));
    ASSERT_EQ(dest->addGeometry(&line), 0);
    doc->recompute();
    const auto sourceGeo = sketch->ExternalGeo.getSize();

    WarningCollector collector;
    EXPECT_EQ(dest->carbonCopy(sketch, false), -1);
    ASSERT_EQ(collector.errors.size(), 1U);
    EXPECT_NE(collector.errors[0].find("couldn't be told"), std::string::npos)
        << collector.errors[0];
    EXPECT_NE(collector.errors[0].find("Ball."), std::string::npos) << collector.errors[0];
    EXPECT_EQ(dest->getInternalGeometry().size(), 1U);
    EXPECT_EQ(dest->ExternalGeometry.getSize(), 0);
    EXPECT_EQ(dest->ExternalGeo.getSize(), 2);
    EXPECT_EQ(dest->Constraints.getSize(), 0);
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 0, -1}));
    EXPECT_EQ(sketch->ExternalGeometry.getSize(), 2);
    EXPECT_EQ(sketch->ExternalGeo.getSize(), sourceGeo);
}

namespace
{
std::vector<std::string> saveAndReopen(App::Document*& doc,
                                       Sketcher::SketchObject*& sketch,
                                       App::DocumentObject*& box);

// A sketch with one projected link of `box`'s `edge`, saved with `types` and no external
// geometry but the axes, then reopened (`box` is fetched again); returns the warnings sent while
// it opened
std::vector<std::string> reopenWithoutSavedGeometry(App::Document*& doc,
                                                    Sketcher::SketchObject*& sketch,
                                                    App::DocumentObject*& box,
                                                    const std::string& edge,
                                                    const std::vector<long>& types)
{
    EXPECT_GE(sketch->addExternal(box, edge.c_str(), false, false), 0);
    doc->recompute();
    EXPECT_EQ(sketch->ExternalGeo.getSize(), 3);
    sketch->ExternalTypes.setValues(types);
    const auto& geos = sketch->ExternalGeo.getValues();
    sketch->ExternalGeo.setValues(
        std::vector<Part::Geometry*>({geos[0]->clone(), geos[1]->clone()}));
    EXPECT_EQ(sketch->ExternalGeo.getSize(), 2);
    doc->purgeTouched();
    return saveAndReopen(doc, sketch, box);
}

// Saves `doc` and opens it again under the same name (`sketch` and `box` fetched again); returns
// the warnings sent while it opened
std::vector<std::string> saveAndReopen(App::Document*& doc,
                                       Sketcher::SketchObject*& sketch,
                                       App::DocumentObject*& box)
{
    const std::string name = doc->getName();
    const std::string sketchName = sketch->getNameInDocument();
    // under the same name, which TearDown closes, in a folder of its own
    tests::TempDirectory folder("SketchObjectPark");
    auto path = folder.path() / (name + ".FCStd");
    doc->saveAs(Base::FileInfo::pathToString(path).c_str());
    App::GetApplication().closeDocument(name.c_str());
    std::vector<std::string> warnings;
    {
        WarningCollector collector;
        doc = App::GetApplication().openDocument(Base::FileInfo::pathToString(path).c_str());
        warnings = collector.warnings;
    }
    EXPECT_NE(doc, nullptr);
    if (!doc) {
        sketch = nullptr;
        return warnings;
    }
    EXPECT_EQ(std::string(doc->getName()), name);
    box = doc->getObject("Box");
    EXPECT_NE(box, nullptr);
    sketch = static_cast<Sketcher::SketchObject*>(doc->getObject(sketchName.c_str()));
    EXPECT_NE(sketch, nullptr);
    return warnings;
}

std::size_t countContaining(const std::vector<std::string>& messages, const std::string& text)
{
    return static_cast<std::size_t>(
        std::count_if(messages.begin(), messages.end(), [&](const std::string& msg) {
            return msg.find(text) != std::string::npos;
        }));
}
}  // namespace

// A type list saved before ops#140 (longer than the links) without the geometry that could
// repair it is read by index, with a warning (ops#237, PR 218 review: untested)
TEST_F(SketchObjectParkTest, oldTypeListWithoutSavedGeometryWarns)
{
    auto* sketch = getObject();
    auto warnings = reopenWithoutSavedGeometry(doc, sketch, box, edge, {1, 0});
    ASSERT_NE(sketch, nullptr);
    EXPECT_EQ(countContaining(warnings, "were saved before ops#140 without their geometry"), 1U)
        << warnings.size() << " warnings";
}

// A list that holds past the links only the mark of a pending repair is no old list (ops#237,
// PR 218 review: it said so). Without saved geometry no link can be told: each waits, with a
// warning, its projection built with the type at its index, and the mark stays through a
// recompute (PR 262 review L1: the open left no repair pending, and the next change of the links
// dropped the mark silently)
TEST_F(SketchObjectParkTest, pendingMarkWithoutSavedGeometryWaits)
{
    auto* sketch = getObject();
    auto warnings = reopenWithoutSavedGeometry(doc, sketch, box, edge, {0, -1});
    ASSERT_NE(sketch, nullptr);
    EXPECT_EQ(countContaining(warnings, "were saved before ops#140"), 0U);
    EXPECT_EQ(countContaining(warnings, "wait for a repair an earlier open left pending"), 1U)
        << warnings.size() << " warnings";
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, -1}));
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    EXPECT_TRUE(sketch->getGeometry(GeoEnum::RefExt)->is<Part::GeomLineSegment>());
    doc->recompute();
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, -1}));
    EXPECT_EQ(sketch->ExternalGeo.getSize(), 3);
}

// ops#287 (PR 262 verification L1): the link waiting above has its projection built with the
// type at its index. Saved with that geometry and opened again, the geometry counted as evidence
// of the type: the open settled the guess and dropped the mark, silently, and a carbon copy then
// took the guess as the link's type. The geometry is marked as built from a guess, so the link
// stays undecided, the open says so again, and a carbon copy from it is still refused
TEST_F(SketchObjectParkTest, guessedGeometryLeavesTheLinkUndecidedOnALaterOpen)
{
    auto* sketch = getObject();
    reopenWithoutSavedGeometry(doc, sketch, box, edge, {0, -1});
    ASSERT_NE(sketch, nullptr);
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    EXPECT_TRUE(ExternalGeometryFacade::getFacade(sketch->getGeometry(GeoEnum::RefExt))
                    ->testFlag(ExternalGeometryExtension::TypeGuessed));
    doc->recompute();

    auto warnings = saveAndReopen(doc, sketch, box);
    ASSERT_NE(sketch, nullptr);
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, -1}));
    EXPECT_EQ(countContaining(warnings, "its type is still undecided"), 1U)
        << warnings.size() << " warnings";
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    EXPECT_TRUE(ExternalGeometryFacade::getFacade(sketch->getGeometry(GeoEnum::RefExt))
                    ->testFlag(ExternalGeometryExtension::TypeGuessed));

    auto* dest = static_cast<Sketcher::SketchObject*>(
        doc->addObject("Sketcher::SketchObject", "Dest"));
    WarningCollector collector;
    EXPECT_EQ(dest->carbonCopy(sketch, false), -1);
    ASSERT_EQ(collector.errors.size(), 1U);
    EXPECT_NE(collector.errors[0].find("Delete the link and add it again"), std::string::npos)
        << collector.errors[0];
}

// A decided link's geometry isn't marked as guessed: a link added as usual, and the edge's link
// once the repair above decided it from its saved line (ops#287)
TEST_F(SketchObjectParkTest, decidedGeometryIsNotMarkedGuessed)
{
    Sketcher::SketchObject* sketch {};
    reopenWithPendingRepair(sketch);
    if (HasFatalFailure()) {
        return;
    }
    doc->recompute();
    EXPECT_FALSE(ExternalGeometryFacade::getFacade(sketch->getGeometry(GeoEnum::RefExt))
                     ->testFlag(ExternalGeometryExtension::TypeGuessed));
    ASSERT_GE(sketch->addExternal(box, otherEdge.c_str(), false, false), 0);
    doc->recompute();
    EXPECT_FALSE(ExternalGeometryFacade::getFacade(sketch->getGeometry(GeoEnum::RefExt - 2))
                     ->testFlag(ExternalGeometryExtension::TypeGuessed));
}

// A carbon copy from a sketch whose repair is still pending, but whose undecided link (the ball)
// was deleted, goes ahead: only a current undecided link refuses it (ops#287, PR 262
// verification nit)
TEST_F(SketchObjectParkTest, carbonCopyAfterTheUndecidedLinkIsDeleted)
{
    Sketcher::SketchObject* sketch {};
    reopenWithPendingRepair(sketch);
    if (HasFatalFailure()) {
        return;
    }
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 4);
    ASSERT_EQ(sketch->delExternal(GeoEnum::RefExt - 1), 0);
    doc->recompute();
    ASSERT_EQ(sketch->ExternalGeometry.getSize(), 1);
    auto* dest = static_cast<Sketcher::SketchObject*>(
        doc->addObject("Sketcher::SketchObject", "Dest"));
    EXPECT_GE(dest->carbonCopy(sketch, false), 0);
    EXPECT_EQ(dest->ExternalGeometry.getSize(), 1);
}

namespace
{
bool typeGuessed(const Sketcher::SketchObject* sketch, int geoId)
{
    return ExternalGeometryFacade::getFacade(sketch->getGeometry(geoId))
        ->testFlag(ExternalGeometryExtension::TypeGuessed);
}

// A carbon copy of `sketch` into a new sketch of its document: the result, and the errors
std::pair<int, std::vector<std::string>> carbonCopyOf(App::Document* doc,
                                                      Sketcher::SketchObject* sketch)
{
    auto* dest = static_cast<Sketcher::SketchObject*>(
        doc->addObject("Sketcher::SketchObject", "Dest"));
    WarningCollector collector;
    const int result = dest->carbonCopy(sketch, false);
    return {result, collector.errors};
}
}  // namespace

// PR 277 review H1: an undo marks undecided only the links whose saved geometry is missing or
// absent (onUndoRedoFinished); a link whose geometry was built from a guess still waits after
// one: its flag stays through the next recompute, a carbon copy is still refused, and the next
// open still says its type is undecided
TEST_F(SketchObjectParkTest, guessedLinkStaysUndecidedThroughAnUndo)
{
    auto* sketch = getObject();
    reopenWithoutSavedGeometry(doc, sketch, box, edge, {0, -1});
    ASSERT_NE(sketch, nullptr);
    doc->recompute();
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    ASSERT_TRUE(typeGuessed(sketch, GeoEnum::RefExt));
    doc->openTransaction("Line");
    Part::GeomLineSegment line;
    line.setPoints(Base::Vector3d(20, 0, 0), Base::Vector3d(30, 0, 0));
    ASSERT_GE(sketch->addGeometry(&line), 0);
    doc->commitTransaction();
    ASSERT_TRUE(doc->undo());
    doc->recompute();

    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    EXPECT_TRUE(typeGuessed(sketch, GeoEnum::RefExt));
    EXPECT_EQ(carbonCopyOf(doc, sketch).first, -1);
    auto warnings = saveAndReopen(doc, sketch, box);
    ASSERT_NE(sketch, nullptr);
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, -1}));
    EXPECT_EQ(countContaining(warnings, "its type is still undecided"), 1U)
        << warnings.size() << " warnings";
}

// PR 277 review M3: the advice works. A link waiting for its type, deleted and added again,
// is a new link: its geometry isn't flagged, a carbon copy goes ahead, and the next open says
// nothing about it (the deleted link's key no longer waits)
TEST_F(SketchObjectParkTest, guessedLinkDeletedAndAddedAgainIsDecided)
{
    auto* sketch = getObject();
    reopenWithoutSavedGeometry(doc, sketch, box, edge, {0, -1});
    ASSERT_NE(sketch, nullptr);
    doc->recompute();
    ASSERT_EQ(sketch->delExternal(0), 0);
    doc->recompute();
    ASSERT_EQ(sketch->ExternalGeometry.getSize(), 0);
    ASSERT_GE(sketch->addExternal(box, edge.c_str(), false, false), 0);
    doc->recompute();

    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    EXPECT_FALSE(typeGuessed(sketch, GeoEnum::RefExt));
    auto [copied, errors] = carbonCopyOf(doc, sketch);
    EXPECT_GE(copied, 0) << (errors.empty() ? "" : errors[0]);
    auto warnings = saveAndReopen(doc, sketch, box);
    ASSERT_NE(sketch, nullptr);
    EXPECT_EQ(countContaining(warnings, "undecided"), 0U) << warnings.size() << " warnings";
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0}));
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    EXPECT_FALSE(typeGuessed(sketch, GeoEnum::RefExt));
}

// PR 277 review L5: the other kind added to a link waiting for its type makes it Both, the
// user's choice: it no longer waits, and its geometry isn't flagged
TEST_F(SketchObjectParkTest, guessedLinkGivenBothKindsIsDecided)
{
    auto* sketch = getObject();
    reopenWithoutSavedGeometry(doc, sketch, box, verticalEdge, {0, -1});
    ASSERT_NE(sketch, nullptr);
    doc->recompute();
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    ASSERT_TRUE(typeGuessed(sketch, GeoEnum::RefExt));
    std::vector<std::string> warnings;
    {
        WarningCollector collector;
        ASSERT_GE(sketch->addExternal(box, verticalEdge.c_str(), false, true), 0);
        warnings = collector.warnings;
    }
    doc->recompute();

    // the projection was the guess, kept: the add says so, naming the link (PR 277
    // verification 7)
    ASSERT_EQ(countContaining(warnings, "its projection was built from a guessed type"), 1U)
        << warnings.size() << " warnings";
    EXPECT_EQ(countContaining(warnings, verticalEdge), 1U);
    ASSERT_EQ(sketch->ExternalGeometry.getSize(), 1);
    EXPECT_EQ(sketch->ExternalTypes.getValues()[0], static_cast<long>(ExtType::Both));
    ASSERT_GT(sketch->ExternalGeo.getSize(), 3);
    for (int geoId = GeoEnum::RefExt; -geoId <= sketch->ExternalGeo.getSize(); --geoId) {
        EXPECT_FALSE(typeGuessed(sketch, geoId)) << geoId;
    }
    auto [copied, errors] = carbonCopyOf(doc, sketch);
    EXPECT_GE(copied, 0) << (errors.empty() ? "" : errors[0]);
}

namespace
{
// A link of the box's edge above the sketch's plane, its projection built with the type at its
// index and flagged, then its intersection added in a transaction, as the GUI does: the edge
// gives none, so the add fails, and the GUI commits the transaction anyway
void failedAddOfTheOtherKind(App::Document*& doc,
                             Sketcher::SketchObject*& sketch,
                             App::DocumentObject*& box,
                             const std::string& edge)
{
    reopenWithoutSavedGeometry(doc, sketch, box, edge, {0, -1});
    ASSERT_NE(sketch, nullptr);
    doc->recompute();
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    ASSERT_TRUE(typeGuessed(sketch, GeoEnum::RefExt));
    doc->openTransaction("Intersection");
    EXPECT_EQ(sketch->addExternal(box, edge.c_str(), false, true), -1);
    doc->commitTransaction();
    doc->recompute();
}
}  // namespace

// PR 277 verification 5: a failed add of the other kind to a link waiting for its type ran a
// rebuild with the link's key taken out, which cleared the flag; the revert put the key back but
// not the flag, so the next open settled the guess silently. The flag survives the failed add:
// the link still waits, a carbon copy is refused, and the next open says its type is undecided
TEST_F(SketchObjectParkTest, guessedLinkStaysUndecidedAfterAFailedAddOfTheOtherKind)
{
    auto* sketch = getObject();
    const auto above = edgeAlongXAbove(box);
    ASSERT_FALSE(above.empty());
    failedAddOfTheOtherKind(doc, sketch, box, above);
    if (HasFatalFailure()) {
        return;
    }

    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, -1}));
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    EXPECT_TRUE(typeGuessed(sketch, GeoEnum::RefExt));
    EXPECT_EQ(carbonCopyOf(doc, sketch).first, -1);
    auto warnings = saveAndReopen(doc, sketch, box);
    ASSERT_NE(sketch, nullptr);
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, -1}));
    EXPECT_EQ(countContaining(warnings, "its type is still undecided"), 1U)
        << warnings.size() << " warnings";
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    EXPECT_TRUE(typeGuessed(sketch, GeoEnum::RefExt));
}

// PR 277 verification 2.5: two links wait for their types after an open, the box edge's
// (its saved line built from a guess) and the ball's (its saved circle missing). The ball gets
// its face back, and the box edge's intersection is added, which fails: the add's rebuild
// decides the ball from its saved circle, and with the box edge's key taken out that was the last
// waiting link, so the rebuild dropped the repair's mark. The revert put back only the box
// edge's key and the links' types: the mark and the ball's key stayed lost, both links were
// rebuilt unflagged, the ball from the type at its index, and the next open settled both
// silently. The revert puts back which links wait and the mark: both still wait, and the next
// open says so for each
TEST_F(SketchObjectParkTest, failedAddOfTheOtherKindKeepsEveryLinkWaiting)
{
    auto* sketch = getObject();
    const auto above = edgeAlongXAbove(box);
    ASSERT_FALSE(above.empty());
    // a sphere of radius 10 about (0, 0, 6) crosses the sketch plane in a circle of radius 8
    auto* ball = static_cast<Part::Feature*>(doc->addObject("Part::Feature", "Ball"));
    ball->Shape.setValue(BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 6), 10).Shape());
    doc->recompute();
    ASSERT_GE(sketch->addExternal(box, above.c_str(), false, false), 0);
    ASSERT_GE(sketch->addExternal(ball, "Face1", false, true), 0);
    doc->recompute();
    ASSERT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 1}));
    // the ball loses its face: its saved circle is missing and can't tell its type
    ball->Shape.setValue(BRepBuilderAPI_MakeVertex(gp_Pnt(0, 0, 6)).Shape());
    doc->recompute();
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 4);
    // the box edge's line as an earlier open saved it, built from a guess
    setExternalFlag(sketch, {2}, ExternalGeometryExtension::TypeGuessed);
    ASSERT_TRUE(typeGuessed(sketch, GeoEnum::RefExt));
    ASSERT_FALSE(typeGuessed(sketch, GeoEnum::RefExt - 1));
    // a list saved before ops#140: the ball reads a projection by index
    sketch->ExternalTypes.setValues({0, 0, 1});
    saveAndReopen(doc, sketch, box);
    ASSERT_NE(sketch, nullptr);
    ball = static_cast<Part::Feature*>(doc->getObject("Ball"));
    ASSERT_NE(ball, nullptr);
    ASSERT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 0, -1}));
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 4);
    ASSERT_TRUE(ExternalGeometryFacade::getFacade(sketch->getGeometry(GeoEnum::RefExt - 1))
                    ->testFlag(ExternalGeometryExtension::Missing));
    ball->Shape.setValue(BRepPrimAPI_MakeSphere(gp_Pnt(0, 0, 6), 10).Shape());

    doc->openTransaction("Intersection");
    EXPECT_EQ(sketch->addExternal(box, above.c_str(), false, true), -1);
    doc->commitTransaction();
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 0, -1}));
    doc->recompute();

    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 0, -1}));
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 4);
    EXPECT_TRUE(typeGuessed(sketch, GeoEnum::RefExt));
    EXPECT_TRUE(typeGuessed(sketch, GeoEnum::RefExt - 1));
    EXPECT_EQ(carbonCopyOf(doc, sketch).first, -1);
    auto warnings = saveAndReopen(doc, sketch, box);
    ASSERT_NE(sketch, nullptr);
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, 0, -1}));
    EXPECT_EQ(countContaining(warnings, "its type is still undecided"), 2U)
        << warnings.size() << " warnings";
}

// The same failed add, undone: the undo marks the link undecided again from its flag (H1), so
// it still waits and the next open says so (PR 277 verification 5)
TEST_F(SketchObjectParkTest, guessedLinkStaysUndecidedWhenAFailedAddIsUndone)
{
    auto* sketch = getObject();
    const auto above = edgeAlongXAbove(box);
    ASSERT_FALSE(above.empty());
    failedAddOfTheOtherKind(doc, sketch, box, above);
    if (HasFatalFailure()) {
        return;
    }
    ASSERT_TRUE(doc->undo());
    doc->recompute();

    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    EXPECT_TRUE(typeGuessed(sketch, GeoEnum::RefExt));
    EXPECT_EQ(carbonCopyOf(doc, sketch).first, -1);
    auto warnings = saveAndReopen(doc, sketch, box);
    ASSERT_NE(sketch, nullptr);
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, -1}));
    EXPECT_EQ(countContaining(warnings, "its type is still undecided"), 1U)
        << warnings.size() << " warnings";
}

// A redo, as the undo above (H1): the link whose geometry was built from a guess still waits
// after an edit is undone and redone (PR 277 verification 11)
TEST_F(SketchObjectParkTest, guessedLinkStaysUndecidedThroughARedo)
{
    auto* sketch = getObject();
    reopenWithoutSavedGeometry(doc, sketch, box, edge, {0, -1});
    ASSERT_NE(sketch, nullptr);
    doc->recompute();
    ASSERT_TRUE(typeGuessed(sketch, GeoEnum::RefExt));
    doc->openTransaction("Line");
    Part::GeomLineSegment line;
    line.setPoints(Base::Vector3d(20, 0, 0), Base::Vector3d(30, 0, 0));
    ASSERT_GE(sketch->addGeometry(&line), 0);
    doc->commitTransaction();
    doc->recompute();
    ASSERT_TRUE(doc->undo());
    doc->recompute();
    ASSERT_TRUE(doc->redo());
    doc->recompute();

    EXPECT_EQ(sketch->Geometry.getSize(), 1);
    ASSERT_EQ(sketch->ExternalGeo.getSize(), 3);
    EXPECT_TRUE(typeGuessed(sketch, GeoEnum::RefExt));
    EXPECT_EQ(carbonCopyOf(doc, sketch).first, -1);
    auto warnings = saveAndReopen(doc, sketch, box);
    ASSERT_NE(sketch, nullptr);
    EXPECT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({0, -1}));
    EXPECT_EQ(countContaining(warnings, "its type is still undecided"), 1U)
        << warnings.size() << " warnings";
}

// PR 277 review: the flag goes through the XML of a copy. The sketch pasted into its document
// keeps its geometry flagged and the mark, its link waits there too, and a carbon copy from the
// copy is refused
TEST_F(SketchObjectParkTest, guessedLinkStaysUndecidedInAPastedCopy)
{
    auto* sketch = getObject();
    reopenWithoutSavedGeometry(doc, sketch, box, edge, {0, -1});
    ASSERT_NE(sketch, nullptr);
    doc->recompute();
    std::vector<std::string> warnings;
    std::vector<App::DocumentObject*> copies;
    {
        WarningCollector collector;
        copies = doc->copyObject({sketch}, false);
        warnings = collector.warnings;
    }
    ASSERT_EQ(copies.size(), 1U);
    auto* copy = dynamic_cast<Sketcher::SketchObject*>(copies[0]);
    ASSERT_NE(copy, nullptr);
    doc->recompute();

    EXPECT_EQ(copy->ExternalTypes.getValues(), std::vector<long>({0, -1}));
    ASSERT_EQ(copy->ExternalGeo.getSize(), 3);
    EXPECT_TRUE(typeGuessed(copy, GeoEnum::RefExt));
    EXPECT_EQ(countContaining(warnings, "its type is still undecided"), 1U)
        << warnings.size() << " warnings";
    EXPECT_EQ(carbonCopyOf(doc, copy).first, -1);
}

// ops#278: a Both entry put back on geometry without kinds (parked before ops#264, when parking
// kept none) has its Ids split between projection and intersection by position at its next
// rebuild, which moves constraints if the split moved while it was parked: unparking says so
TEST_F(SketchObjectParkTest, unparkOfABothEntryWithoutKindsWarns)
{
    // Arrange: a rod from (0, 0, -5) to (10, 0, 5) linked Both: its projection is the line
    // (0, 0)-(10, 0), its intersection the point (5, 0)
    auto sketch = getObject();
    auto rod = static_cast<Part::Feature*>(doc->addObject("Part::Feature", "Rod"));
    rod->Shape.setValue(BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, -5), gp_Pnt(10, 0, 5)).Edge());
    doc->recompute();
    ASSERT_GE(sketch->addExternal(rod, "Edge1"), 0);
    ASSERT_GE(sketch->addExternal(rod, "Edge1", false, true), 0);
    doc->recompute();
    ASSERT_EQ(sketch->ExternalTypes.getValues(), std::vector<long>({2}));
    const auto ids = sketch->externalGeometryIds(0);
    ASSERT_EQ(ids.size(), 2U);
    EXPECT_EQ(sketch->externalGeometryKind(ids[0]), 1);
    EXPECT_EQ(sketch->externalGeometryKind(ids[1]), 0);
    auto parkAndPutBack = [&]() {
        const std::string sub = sketch->ExternalGeometry.getSubValues()[0];
        auto shadow = sketch->ExternalGeometry.getShadowSubs()[0];
        sketch->parkExternalGeometry({0});
        WarningCollector collector;
        EXPECT_EQ(sketch->unparkExternalGeometry(rod, sub, std::move(shadow), 2, ids), 0);
        const std::size_t warned = collector.count("put back from where it was set aside");
        doc->recompute();
        EXPECT_EQ(sketch->externalGeometryIds(0), ids);
        return warned;
    };

    // Act and assert: with its kinds (parked since ops#264), no warning
    EXPECT_EQ(parkAndPutBack(), 0U);

    // without them, as a file saved before ops#264 has its parked geometry: a warning
    auto geos = sketch->ExternalGeo.getValues();
    for (auto& geo : geos) {
        if (refOf(geo).empty()) {
            continue;
        }
        geo = geo->clone();
        auto egf = ExternalGeometryFacade::getFacade(geo);
        egf->setFlag(ExternalGeometryExtension::Projection, false);
        egf->setFlag(ExternalGeometryExtension::Intersection, false);
    }
    sketch->ExternalGeo.setValues(std::move(geos));
    ASSERT_EQ(sketch->externalGeometryKind(ids[0]), -1);
    EXPECT_EQ(parkAndPutBack(), 1U);
}
