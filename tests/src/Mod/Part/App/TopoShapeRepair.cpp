// SPDX-License-Identifier: LGPL-2.1-or-later

// What checkDressUp() never drops from a repair: faces outside its solids that enclose a volume
// (ops#297). Designed shapes only.

#include <gtest/gtest.h>

#include <Mod/Part/App/TopoShapeRepair.h>

#include <BRep_Builder.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <gp_Pnt.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>

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
