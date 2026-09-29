// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <src/App/InitApplication.h>
#include <Mod/Part/App/FeatureMirroring.h>

#include "PartTestHelpers.h"

using namespace PartTestHelpers;

// NOLINTBEGIN(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
class FeatureMirroringTest: public ::testing::Test, public PartTestHelperClass
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        createTestDoc();
        _mirror = _doc->addObject<Part::Mirroring>();
        _mirror->Source.setValue(_boxes[0]);
        _mirror->Base.setValue(1, 0, 0);
        _mirror->execute();
    }

    void TearDown() override
    {}

    Part::Mirroring* _mirror = nullptr;  // NOLINT Can't be private in a test framework
};

TEST_F(FeatureMirroringTest, testXMirror)
{
    // Arrange
    Base::BoundBox3d bb = _mirror->Shape.getShape().getBoundBox();
    // Assert size and position
    EXPECT_EQ(getVolume(_mirror->Shape.getShape().getShape()), 6);
    // Mirrored it around X from 0,0,0 -> 1,2,3  to  0,0,-3 -> 1,2,0
    EXPECT_TRUE(boxesMatch(bb, Base::BoundBox3d(0, 0, -3, 1, 2, 0)));
    // Assert correct element Map
    //   the box has no names: each mirrored element gets its source element's unmapped name
    //   under the box's tag, op MIR. Mirroring adds no section of its own.
    const auto& shape = _mirror->Shape.getShape();
    auto boxTag = _boxes[0]->getID();
    EXPECT_EQ(
        unmappedName("Edge3", boxTag, "MIR").toString(),
        "Edge3;_;" + std::to_string(boxTag) + ";MIR;0;E;0;IDX,SRC;_"
    );
    EXPECT_EQ(shape.getElementMapSize(), 26);
    for (const char* type : {"Vertex", "Edge", "Face"}) {
        for (int index = 1; index <= static_cast<int>(shape.countSubElements(type)); ++index) {
            auto element = std::string(type) + std::to_string(index);
            EXPECT_TRUE(
                elementHasNames(shape, element.c_str(), {unmappedName(element, boxTag, "MIR")})
            );
        }
    }
}

TEST_F(FeatureMirroringTest, testYMirrorWithExistingElementMap)
{
    // Arrange
    Part::Fuse* _fuse = nullptr;  // NOLINT Can't be private in a test framework
    _fuse = _doc->addObject<Part::Fuse>();
    _fuse->Base.setValue(_boxes[0]);
    _fuse->Tool.setValue(_boxes[1]);
    _fuse->Refine.setValue(false);
    // Act
    _fuse->execute();
    _mirror->Source.setValue(_fuse);
    _mirror->Base.setValue(0, 1, 0);  // Y Axis
    Part::TopoShape ts = _fuse->Shape.getValue();
    double volume = getVolume(ts.getShape());
    Base::BoundBox3d bb = _mirror->Shape.getShape().getBoundBox();
    // Assert size and position
    EXPECT_EQ(getVolume(_mirror->Shape.getShape().getShape()), volume);
    // Mirrored it around X from 0,0,0 -> 1,2,3  to  0,0,-3 -> 1,2,0
    EXPECT_TRUE(boxesMatch(bb, Base::BoundBox3d(0, 0, -3, 1, 3, 0)));
    // Assert correct element Map
    //   a mirror keeps its source's names as they are: every element has the fused shape's names
    //   for the same element, and nothing else
    EXPECT_TRUE(allElementsNamed(_fuse->Shape.getShape()));
    EXPECT_TRUE(sameNamesPerElement(_mirror->Shape.getShape(), _fuse->Shape.getShape()));
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
