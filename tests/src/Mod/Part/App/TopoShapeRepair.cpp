// SPDX-License-Identifier: LGPL-2.1-or-later

// What checkDressUp() never drops from a repair: faces outside its solids that enclose a volume
// (ops#297). Designed shapes only.

#include <gtest/gtest.h>

#include <cmath>
#include <string>
#include <utility>

#include "src/App/InitApplication.h"
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeRepair.h>

#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRep_Builder.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRep_Tool.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <gp.hxx>
#include <gp_Ax2.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>

namespace
{

// A square face in the plane z = 0, open on its own
TopoDS_Face square(double x)
{
    BRepBuilderAPI_MakePolygon polygon(
        gp_Pnt(x, 0, 0),
        gp_Pnt(x + 10, 0, 0),
        gp_Pnt(x + 10, 10, 0),
        gp_Pnt(x, 10, 0),
        true
    );
    return BRepBuilderAPI_MakeFace(polygon.Wire()).Face();
}

TopoDS_Shape box(double x)
{
    return BRepPrimAPI_MakeBox(gp_Pnt(x, 0, 0), 10, 10, 10).Shape();
}

TopoDS_Shape shellOf(const TopoDS_Shape& solid)
{
    return TopExp_Explorer(solid, TopAbs_SHELL).Current();
}

TopoDS_Compound compound(std::initializer_list<TopoDS_Shape> shapes)
{
    TopoDS_Compound res;
    BRep_Builder builder;
    builder.MakeCompound(res);
    for (const auto& shape : shapes) {
        builder.Add(res, shape);
    }
    return res;
}

}  // namespace

TEST(TopoShapeRepair, solidAloneEnclosesNothingOutside)
{
    EXPECT_FALSE(Part::enclosesOutsideSolids(box(0)));
    EXPECT_FALSE(Part::enclosesOutsideSolids(compound({box(0), box(20)})));
}

TEST(TopoShapeRepair, openFaceBesideTheSolidEnclosesNothing)
{
    // The fin, moved out of the solid by ShapeFix
    EXPECT_FALSE(Part::enclosesOutsideSolids(compound({box(0), square(20)})));
    // An open shell of five faces of a box
    TopoDS_Compound fiveFaces;
    BRep_Builder builder;
    builder.MakeCompound(fiveFaces);
    TopExp_Explorer it(box(20), TopAbs_FACE);
    for (it.Next(); it.More(); it.Next()) {
        builder.Add(fiveFaces, it.Current());
    }
    EXPECT_FALSE(Part::enclosesOutsideSolids(compound({box(0), fiveFaces})));
}

TEST(TopoShapeRepair, closedShellBesideAnOpenFaceEncloses)
{
    // Taken together the faces outside have the open face's free edges; the shell alone is closed
    EXPECT_TRUE(Part::enclosesOutsideSolids(compound({box(0), shellOf(box(20)), square(40)})));
    EXPECT_TRUE(Part::enclosesOutsideSolids(compound({box(0), square(40), shellOf(box(20))})));
}

TEST(TopoShapeRepair, closedFacesBesideAnOpenFaceEnclose)
{
    // A box's six faces outside any shell, and a sphere's single face
    TopoDS_Compound sixFaces;
    BRep_Builder builder;
    builder.MakeCompound(sixFaces);
    for (TopExp_Explorer it(box(20), TopAbs_FACE); it.More(); it.Next()) {
        builder.Add(sixFaces, it.Current());
    }
    EXPECT_TRUE(Part::enclosesOutsideSolids(compound({box(0), sixFaces, square(40)})));
    const auto sphere = BRepPrimAPI_MakeSphere(gp_Pnt(60, 0, 0), 5).Shape();
    const auto sphereFace = TopExp_Explorer(sphere, TopAbs_FACE).Current();
    EXPECT_TRUE(Part::enclosesOutsideSolids(compound({box(0), sphereFace, square(40)})));
}

class CheckDressUpTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }
};

TEST_F(CheckDressUpTest, internalFacesOfAValidResultOnAnInvalidBaseStay)
{
    // A box holding a square inside it on purpose, in a shell oriented INTERNAL: an open shell
    // that is no defect. On an invalid base (a vertex 0.01 off its edges) the valid result is
    // kept as it is; the repair would drop the square with the shell (PR 314 review, item 5)
    gp_Trsf halfway;
    halfway.SetTranslation(gp_Vec(0, 0, 5));
    TopoDS_Shape inside = BRepBuilderAPI_Transform(square(0), halfway, true).Shape();
    BRep_Builder builder;
    TopoDS_Shell internal;
    builder.MakeShell(internal);
    builder.Add(internal, inside);
    internal.Orientation(TopAbs_INTERNAL);
    TopoDS_Solid solid;
    builder.MakeSolid(solid);
    builder.Add(solid, shellOf(box(0)));
    builder.Add(solid, internal);
    Part::TopoShape result(solid, 1L);
    ASSERT_TRUE(result.isValid());
    ASSERT_EQ(result.countSubShapes(TopAbs_FACE), 7U);

    TopoDS_Shape base = box(0);
    TopoDS_Vertex corner = TopoDS::Vertex(TopExp_Explorer(base, TopAbs_VERTEX).Current());
    gp_Pnt off = BRep_Tool::Pnt(corner).Translated(gp_Vec(0.01, 0, 0));
    builder.UpdateVertex(corner, off, 1e-7);
    Part::TopoShape invalidBase(base, 1L);
    ASSERT_FALSE(invalidBase.isValid());

    EXPECT_TRUE(Part::checkDressUp(result, invalidBase));
    EXPECT_EQ(result.countSubShapes(TopAbs_FACE), 7U);
    EXPECT_EQ(result.countSubShapes(TopAbs_SHELL), 2U);
}

TEST_F(CheckDressUpTest, aChangedVoidBesideAVoidRemovedWithItsMaterialStays)
{
    // The base: the 10 mm box with a 2 mm void A and a 4 x 0.5 x 0.5 void B under its front top
    // edge. The result, made by Booleans: the box less the wedge z > 7 + y (a chamfer of 3, which
    // removes B), with A 0.5 lower, as if the dress-up had rounded A's top edges. A is changed,
    // not lost, and holds material of the result where it was; only the lost B is checked, and
    // its space holds none (PR 341 review)
    const auto cut = [](const TopoDS_Shape& a, const TopoDS_Shape& b) {
        return BRepAlgoAPI_Cut(a, b).Shape();
    };
    const TopoDS_Shape voidA = BRepPrimAPI_MakeBox(gp_Pnt(4, 4, 2), 2, 2, 2).Shape();
    const TopoDS_Shape voidB = BRepPrimAPI_MakeBox(gp_Pnt(3, 0.2, 9.3), 4, 0.5, 0.5).Shape();
    Part::TopoShape base(cut(cut(box(0), voidA), voidB), 1L);
    BRepBuilderAPI_MakePolygon
        triangle(gp_Pnt(-1, -1, 6), gp_Pnt(-1, 4, 11), gp_Pnt(-1, -1, 11), true);
    const TopoDS_Shape wedge
        = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(triangle.Wire()).Face(), gp_Vec(12, 0, 0))
              .Shape();
    const TopoDS_Shape lowerA = BRepPrimAPI_MakeBox(gp_Pnt(4, 4, 2), 2, 2, 1.5).Shape();
    Part::TopoShape result(cut(cut(box(0), wedge), lowerA), 1L);
    ASSERT_TRUE(result.isValid());
    ASSERT_EQ(base.countSubShapes(TopAbs_SHELL), 3U);
    ASSERT_EQ(result.countSubShapes(TopAbs_SHELL), 2U);

    EXPECT_TRUE(Part::checkDressUp(result, base));
    EXPECT_EQ(result.countSubShapes(TopAbs_SHELL), 2U);
}

// A block 20 mm with a blind pocket 10 x 1.5 x 15 open at the top (x 5..15, y 5..6.5, floor
// z 5), and the floor's concave edge along the wall y 5: a round of 2 on it is wider than the
// floor, so its strip runs onto the opposite wall y 6.5. Returns the base and that edge
std::pair<Part::TopoShape, Part::TopoShape> narrowPocket()
{
    const TopoDS_Shape block = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 20, 20, 20).Shape();
    const TopoDS_Shape pocket = BRepPrimAPI_MakeBox(gp_Pnt(5, 5, 5), 10, 1.5, 15).Shape();
    const TopoDS_Shape base = BRepAlgoAPI_Cut(block, pocket).Shape();
    TopoDS_Shape edge;
    for (TopExp_Explorer it(base, TopAbs_EDGE); it.More(); it.Next()) {
        TopoDS_Vertex first;
        TopoDS_Vertex last;
        TopExp::Vertices(TopoDS::Edge(it.Current()), first, last);
        const gp_Pnt a = BRep_Tool::Pnt(first);
        const gp_Pnt b = BRep_Tool::Pnt(last);
        if (std::abs(a.Y() - 5) < 1e-9 && std::abs(b.Y() - 5) < 1e-9 && std::abs(a.Z() - 5) < 1e-9
            && std::abs(b.Z() - 5) < 1e-9 && std::abs(std::abs(a.X() - b.X()) - 10) < 1e-9) {
            edge = it.Current();
        }
    }
    return {Part::TopoShape(base, 1L), Part::TopoShape(edge)};
}

TEST_F(CheckDressUpTest, aRoundClippedByTheOppositeWallFillsNothing)
{
    // The round of 2 as Onshape clips it by the wall its strip reaches (ops#640, Case Base #46):
    // the corner y 5..6.5, z 5..7 less the round's cylinder. It lies on the opposite wall, beside
    // the floor across a concave edge, within the round's reach: no recess is filled. Without the
    // size, the check can't bound it and refuses it
    const auto [base, edge] = narrowPocket();
    ASSERT_FALSE(edge.isNull());
    const TopoDS_Shape corner = BRepPrimAPI_MakeBox(gp_Pnt(5, 5, 5), 10, 1.5, 2).Shape();
    const TopoDS_Shape cylinder
        = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(4, 7, 7), gp::DX()), 2, 12).Shape();
    const TopoDS_Shape round = BRepAlgoAPI_Cut(corner, cylinder).Shape();
    Part::TopoShape result(BRepAlgoAPI_Fuse(base.getShape(), round).Shape(), 1L);
    ASSERT_TRUE(result.isValid());

    EXPECT_EQ(Part::filledPocket(result, base, {edge}, 2.0), "");
    EXPECT_NE(Part::filledPocket(result, base, {edge}), "");
}

TEST_F(CheckDressUpTest, aBlindPocketFilledWholeFillsARecess)
{
    // The same pocket filled whole up to its top, as OCCT fills a recess whose opening it covers
    // (ops#393): the fill lies on the opposite wall beside the floor too, but reaches 15 up it,
    // past the round's reach (PR review r2 of the clip, the blind pocket)
    const auto [base, edge] = narrowPocket();
    ASSERT_FALSE(edge.isNull());
    const TopoDS_Shape fill = BRepPrimAPI_MakeBox(gp_Pnt(5, 5, 5), 10, 1.5, 15).Shape();
    Part::TopoShape result(BRepAlgoAPI_Fuse(base.getShape(), fill).Shape(), 1L);
    ASSERT_TRUE(result.isValid());

    const std::string why = Part::filledPocket(result, base, {edge}, 2.0);
    EXPECT_EQ(why.rfind("fills a recess of the base next to Edge", 0), 0U) << why;
}
