// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <App/Application.h>
#include <App/ElementMap.h>
#include <App/NameTable.h>
#include <src/App/InitApplication.h>

// NOLINTBEGIN(readability-magic-numbers)


// this is a "holder" class used for simpler testing of ElementMap in the context of a class
class LessComplexPart
{
public:
    LessComplexPart(long tag,
                    const std::string& nameStr,
                    App::StringHasherRef hasher,
                    App::HistoryAlgorithm algorithm = App::HistoryAlgorithm::V2)
        : elementMapPtr(std::make_shared<Data::ElementMap>())
        , Tag(tag)
        , name(nameStr)
    {
        elementMapPtr->setHistoryAlgorithm(algorithm);
        // object also have Vertexes etc and the face count varies; but that is not important
        // here since we are not testing a real model
        // the "MappedName" is left blank for now
        Data::IndexedName face1("Face", 1);
        Data::IndexedName face2("Face", 2);
        Data::IndexedName face3("Face", 3);
        Data::IndexedName face4("Face", 4);
        Data::IndexedName face5("Face", 5);
        Data::IndexedName face6("Face", 6);
        elementMapPtr->hasher = hasher;
        elementMapPtr->setElementName(face1, Data::MappedName(face1), Tag);
        elementMapPtr->setElementName(face2, Data::MappedName(face2), Tag);
        elementMapPtr->setElementName(face3, Data::MappedName(face3), Tag);
        elementMapPtr->setElementName(face4, Data::MappedName(face4), Tag);
        elementMapPtr->setElementName(face5, Data::MappedName(face5), Tag);
        elementMapPtr->setElementName(face6, Data::MappedName(face6), Tag);
    }

    Data::ElementMapPtr elementMapPtr;
    mutable long Tag;
    Data::MappedName name;
};

class ElementMapTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        _docName = App::GetApplication().getUniqueDocumentName("test");
        App::GetApplication().newDocument(_docName.c_str(), "testUser");
        _sids = &_sid;
        _hasher = Base::Reference<App::StringHasher>(new App::StringHasher);
        ASSERT_EQ(_hasher.getRefCount(), 1);
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    std::string _docName;
    // for the tests of V1-only mechanisms: encodeElementName() and child element maps
    const App::HistoryAlgorithm _v1 {App::HistoryAlgorithm::V1};
    Data::ElementIDRefs _sid;
    QVector<App::StringIDRef>* _sids;
    App::StringHasherRef _hasher;
};

TEST_F(ElementMapTest, defaultConstruction)
{
    // Act
    Data::ElementMap elementMap = Data::ElementMap();

    // Assert
    EXPECT_EQ(elementMap.size(), 0);
}

TEST_F(ElementMapTest, setElementNameDefaults)
{
    // Arrange
    Data::ElementMap elementMap;
    Data::IndexedName element("Edge", 1);
    Data::MappedName mappedName("TEST");

    // Act
    auto resultName = elementMap.setElementName(element, mappedName, 0);
    auto mappedToElement = elementMap.find(element);

    // Assert
    EXPECT_EQ(resultName, mappedName);
    EXPECT_EQ(mappedToElement, mappedName);
}

TEST_F(ElementMapTest, setElementNameNoOverwrite)
{
    // Arrange
    Data::ElementMap elementMap;
    Data::IndexedName element("Edge", 1);
    Data::MappedName mappedName("TEST");
    Data::MappedName anotherMappedName("ANOTHERTEST");

    // Act
    auto resultName = elementMap.setElementName(element, mappedName, 0);
    auto resultName2 = elementMap.setElementName(element, anotherMappedName, 0, _sids, false);
    auto mappedToElement = elementMap.find(element);
    auto findAllResult = elementMap.findAll(element);

    // Assert
    EXPECT_EQ(resultName, mappedName);
    EXPECT_EQ(resultName2, anotherMappedName);
    EXPECT_EQ(mappedToElement, mappedName);
    EXPECT_EQ(findAllResult.size(), 2);
    EXPECT_EQ(findAllResult[0].first, mappedName);
    EXPECT_EQ(findAllResult[1].first, anotherMappedName);
}

TEST_F(ElementMapTest, setElementNameWithOverwrite)
{
    // Arrange
    Data::ElementMap elementMap;
    Data::IndexedName element("Edge", 1);
    Data::MappedName mappedName("TEST");
    Data::MappedName anotherMappedName("ANOTHERTEST");

    // Act
    auto resultName = elementMap.setElementName(element, mappedName, 0);
    auto resultName2 = elementMap.setElementName(element, anotherMappedName, 0, _sids, true);
    auto mappedToElement = elementMap.find(element);
    auto findAllResult = elementMap.findAll(element);

    // Assert
    EXPECT_EQ(resultName, mappedName);
    EXPECT_EQ(resultName2, anotherMappedName);
    EXPECT_EQ(mappedToElement, anotherMappedName);
    EXPECT_EQ(findAllResult.size(), 1);
    EXPECT_EQ(findAllResult[0].first, anotherMappedName);
}

TEST_F(ElementMapTest, setElementNameWithHashing)
{
    // Arrange
    Data::ElementMap elementMap;
    std::ostringstream ss;
    Data::IndexedName element("Edge", 1);
    Data::MappedName elementNameHolder(element);  // Will get modified by the encoder
    const Data::MappedName expectedName(element);

    // Act
    elementMap.encodeElementName(element.getType()[0], elementNameHolder, ss, nullptr, 0, nullptr, 0);
    auto resultName = elementMap.setElementName(element, elementNameHolder, 0, _sids);
    auto mappedToElement = elementMap.find(element);

    // Assert
    EXPECT_EQ(resultName, expectedName);
    EXPECT_EQ(mappedToElement, expectedName);
}

TEST_F(ElementMapTest, eraseMappedName)
{
    // Arrange
    Data::ElementMap elementMap;
    Data::IndexedName element("Edge", 1);
    Data::MappedName mappedName("TEST");
    Data::MappedName anotherMappedName("ANOTHERTEST");
    elementMap.setElementName(element, mappedName, 0);
    elementMap.setElementName(element, anotherMappedName, 0);

    // Act
    auto sizeBefore = elementMap.size();
    auto findAllBefore = elementMap.findAll(element);

    elementMap.erase(anotherMappedName);
    auto sizeAfter = elementMap.size();
    auto findAllAfter = elementMap.findAll(element);

    elementMap.erase(anotherMappedName);
    auto sizeAfterRepeat = elementMap.size();
    auto findAllAfterRepeat = elementMap.findAll(element);

    // Assert
    EXPECT_EQ(sizeBefore, 2);
    EXPECT_EQ(findAllBefore.size(), 2);
    EXPECT_EQ(findAllBefore[0].first, mappedName);
    EXPECT_EQ(findAllBefore[1].first, anotherMappedName);

    EXPECT_EQ(sizeAfter, 1);
    EXPECT_EQ(findAllAfter.size(), 1);
    EXPECT_EQ(findAllAfter[0].first, mappedName);

    EXPECT_EQ(sizeAfterRepeat, 1);
    EXPECT_EQ(findAllAfterRepeat.size(), 1);
    EXPECT_EQ(findAllAfterRepeat[0].first, mappedName);
}

TEST_F(ElementMapTest, eraseIndexedName)
{
    // Arrange
    // Create two elements, edge1 and edge2, that have two mapped names each.
    Data::ElementMap elementMap;

    Data::IndexedName element("Edge", 1);
    Data::MappedName mappedName("TEST");
    Data::MappedName anotherMappedName("ANOTHERTEST");
    elementMap.setElementName(element, mappedName, 0);
    elementMap.setElementName(element, anotherMappedName, 0);

    Data::IndexedName element2("Edge", 2);
    Data::MappedName mappedName2("TEST2");
    Data::MappedName anotherMappedName2("ANOTHERTEST2");
    elementMap.setElementName(element2, mappedName2, 0);
    elementMap.setElementName(element2, anotherMappedName2, 0);

    // Act
    auto sizeBefore = elementMap.size();
    auto findAllBefore = elementMap.findAll(element2);

    elementMap.erase(element2);
    auto sizeAfter = elementMap.size();
    auto findAllAfter = elementMap.findAll(element2);

    elementMap.erase(element2);
    auto sizeAfterRepeat = elementMap.size();
    auto findAllAfterRepeat = elementMap.findAll(element2);

    // Assert
    EXPECT_EQ(sizeBefore, 4);
    EXPECT_EQ(findAllBefore.size(), 2);
    EXPECT_EQ(findAllBefore[0].first, mappedName2);
    EXPECT_EQ(findAllBefore[1].first, anotherMappedName2);

    EXPECT_EQ(sizeAfter, 2);
    EXPECT_EQ(findAllAfter.size(), 0);

    EXPECT_EQ(sizeAfterRepeat, 2);
    EXPECT_EQ(findAllAfterRepeat.size(), 0);
}

TEST_F(ElementMapTest, findMappedName)
{
    // Arrange
    // Create two elements, edge1 and edge2, that have two mapped names each.
    Data::ElementMap elementMap;

    Data::IndexedName element("Edge", 1);
    Data::MappedName mappedName("TEST");
    Data::MappedName anotherMappedName("ANOTHERTEST");
    elementMap.setElementName(element, mappedName, 0);
    elementMap.setElementName(element, anotherMappedName, 0);

    Data::IndexedName element2("Edge", 2);
    Data::MappedName mappedName2("TEST2");
    Data::MappedName anotherMappedName2("ANOTHERTEST2");
    elementMap.setElementName(element2, mappedName2, 0);
    elementMap.setElementName(element2, anotherMappedName2, 0);

    // Act
    auto findResult = elementMap.find(mappedName);
    auto findResult2 = elementMap.find(mappedName2);

    // Assert
    EXPECT_EQ(findResult, element);
    EXPECT_EQ(findResult2, element2);
}

TEST_F(ElementMapTest, findIndexedName)
{
    // Arrange
    // Create two elements, edge1 and edge2, that have two mapped names each.
    Data::ElementMap elementMap;

    Data::IndexedName element("Edge", 1);
    Data::MappedName mappedName("TEST");
    Data::MappedName anotherMappedName("ANOTHERTEST");
    elementMap.setElementName(element, mappedName, 0);
    elementMap.setElementName(element, anotherMappedName, 0);

    Data::IndexedName element2("Edge", 2);
    Data::MappedName mappedName2("TEST2");
    Data::MappedName anotherMappedName2("ANOTHERTEST2");
    elementMap.setElementName(element2, mappedName2, 0);
    elementMap.setElementName(element2, anotherMappedName2, 0);

    // Act
    // they return the first mapped name
    auto findResult = elementMap.find(element);
    auto findResult2 = elementMap.find(element2);

    // Assert
    EXPECT_EQ(findResult, mappedName);
    EXPECT_EQ(findResult2, mappedName2);
}

TEST_F(ElementMapTest, findAll)
{
    // Arrange
    // Create two elements, edge1 and edge2, that have two mapped names each.
    Data::ElementMap elementMap;

    Data::IndexedName element("Edge", 1);
    Data::MappedName mappedName("TEST");
    Data::MappedName anotherMappedName("ANOTHERTEST");
    elementMap.setElementName(element, mappedName, 0);
    elementMap.setElementName(element, anotherMappedName, 0);

    Data::IndexedName element2("Edge", 2);
    Data::MappedName mappedName2("TEST2");
    Data::MappedName anotherMappedName2("ANOTHERTEST2");
    elementMap.setElementName(element2, mappedName2, 0);
    elementMap.setElementName(element2, anotherMappedName2, 0);

    // Act
    // they return the first mapped name
    auto findResult = elementMap.findAll(element);
    auto findResult2 = elementMap.findAll(element2);

    // Assert
    EXPECT_EQ(findResult.size(), 2);
    EXPECT_EQ(findResult[0].first, mappedName);
    EXPECT_EQ(findResult[1].first, anotherMappedName);
    EXPECT_EQ(findResult2.size(), 2);
    EXPECT_EQ(findResult2[0].first, mappedName2);
    EXPECT_EQ(findResult2[1].first, anotherMappedName2);
}

TEST_F(ElementMapTest, mimicOnePart)
{
    // Arrange
    //   pattern: new doc, create Cube
    //   for a single part, there is no "naming algo" to speak of
    std::ostringstream ss;
    auto docName = "Unnamed";
    LessComplexPart cube(1L, "Box", _hasher);

    // Act
    auto children = cube.elementMapPtr->getAll();
    ss << docName << "#" << cube.name << "."
       << cube.elementMapPtr->find(Data::IndexedName("Face", 6));

    // Assert
    EXPECT_EQ(children.size(), 6);
    EXPECT_EQ(children[0].index.toString(), "Face1");
    EXPECT_EQ(children[0].name.toString(), "Face1");
    EXPECT_EQ(children[1].index.toString(), "Face2");
    EXPECT_EQ(children[1].name.toString(), "Face2");
    EXPECT_EQ(children[2].index.toString(), "Face3");
    EXPECT_EQ(children[2].name.toString(), "Face3");
    EXPECT_EQ(children[3].index.toString(), "Face4");
    EXPECT_EQ(children[3].name.toString(), "Face4");
    EXPECT_EQ(children[4].index.toString(), "Face5");
    EXPECT_EQ(children[4].name.toString(), "Face5");
    EXPECT_EQ(children[5].index.toString(), "Face6");
    EXPECT_EQ(children[5].name.toString(), "Face6");
    EXPECT_EQ(ss.str(), "Unnamed#Box.Face6");
}

TEST_F(ElementMapTest, mimicSimpleUnionV1)
{
    // Arrange
    //   pattern: new doc, create Cube, create Cylinder, Union of both (Cube first)
    std::ostringstream ss;
    std::ostringstream finalSs;
    const char* docName = "Unnamed";

    LessComplexPart cube(1L, "Box", _hasher, _v1);
    LessComplexPart cylinder(2L, "Cylinder", _hasher, _v1);
    // Union (Fusion) operation via the Part Workbench
    LessComplexPart unionPart(3L, "Fusion", _hasher, _v1);

    // we are only going to simulate one face for testing purpose
    Data::IndexedName uface3("Face", 3);
    auto PartOp = "FUS";  // Part::OpCodes::Fuse;

    // Act
    //   act: simulate a union/fuse operation
    auto parent = cube.elementMapPtr->getAll()[5];
    Data::MappedName postfixHolder(std::string(Data::POSTFIX_MOD) + "2");
    unionPart.elementMapPtr->encodeElementName(
        postfixHolder[0],
        postfixHolder,
        ss,
        nullptr,
        unionPart.Tag,
        nullptr,
        unionPart.Tag
    );
    auto postfixStr = postfixHolder.toString() + Data::ELEMENT_MAP_PREFIX + PartOp;

    //   act: with the fuse op, name against the cube's Face6
    Data::MappedName uface3Holder(parent.index);
    // we will invoke the encoder for face 3
    unionPart.elementMapPtr->encodeElementName(
        uface3Holder[0],
        uface3Holder,
        ss,
        nullptr,
        unionPart.Tag,
        postfixStr.c_str(),
        cube.Tag
    );
    unionPart.elementMapPtr->setElementName(uface3, uface3Holder, unionPart.Tag, nullptr, true);

    // act: generate a full toponame string for testing  purposes
    finalSs << docName << "#" << unionPart.name;
    finalSs << ".";
    finalSs << Data::ELEMENT_MAP_PREFIX + unionPart.elementMapPtr->find(uface3).toString();
    finalSs << ".";
    finalSs << uface3;

    // Assert
    EXPECT_EQ(postfixStr, ":M2;FUS");
    EXPECT_EQ(unionPart.elementMapPtr->find(uface3).toString(), "Face6;:M2;FUS;:H1:8,F");
    EXPECT_EQ(finalSs.str(), "Unnamed#Fusion.;Face6;:M2;FUS;:H1:8,F.Face3");

    // explanation of "Fusion.;Face6;:M2;FUS;:H2:3,F.Face3" toponame
    // Note: every postfix is prefixed by semicolon
    // Note: the start/middle/end are separated by periods
    //
    // "Fusion" means that we are on the "Fusion" object.
    // "." we are done with the first part
    // ";Face6" means default inheritance comes from face 6 of the parent (which is a cube)
    // ";:M2" means that a Workbench op has happened. "M" is the "Mod" directory in the source tree?
    // ";FUS" means that a Fusion operation has happened. Notice the lack of a colon.
    // ";:H2" means the subtending object (cylinder) has a tag of 2
    // ":3" means the writing position is 3; literally how far into the current postfix we are
    // ",F" means are of type "F" which is short for "Face" of Face3 of Fusion.
    // "." we are done with the second part
    // "Face3" is the localized name
}

TEST_F(ElementMapTest, mimicOperationAgainstSelfV1)
{
    // Arrange
    //   pattern: new doc, create Cube, Mystery Op with self as target
    std::ostringstream ss;
    LessComplexPart finalPart(99L, "MysteryOp", _hasher, _v1);
    // we are only going to simulate one face for testing purpose
    Data::IndexedName uface3("Face", 3);
    auto PartOp = "MYS";
    auto ownFace6 = finalPart.elementMapPtr->getAll()[5];
    Data::MappedName uface3Holder(ownFace6.index);
    auto workbenchId = std::string(Data::POSTFIX_MOD) + "9999";

    // Act
    //   act: with the mystery op, name against its own Face6 for some reason
    Data::MappedName postfixHolder(workbenchId);
    finalPart.elementMapPtr->encodeElementName(
        postfixHolder[0],
        postfixHolder,
        ss,
        nullptr,
        finalPart.Tag,
        nullptr,
        finalPart.Tag
    );
    auto postfixStr = postfixHolder.toString() + Data::ELEMENT_MAP_PREFIX + PartOp;
    // we will invoke the encoder for face 3
    finalPart.elementMapPtr->encodeElementName(
        uface3Holder[0],
        uface3Holder,
        ss,
        nullptr,
        finalPart.Tag,
        postfixStr.c_str(),
        finalPart.Tag
    );
    // override not forced
    finalPart.elementMapPtr->setElementName(uface3, uface3Holder, finalPart.Tag, nullptr, false);

    // Assert
    EXPECT_EQ(postfixStr, ":M9999;MYS");
    EXPECT_EQ(finalPart.elementMapPtr->find(uface3).toString(), "Face3");  // override not forced
    EXPECT_EQ(uface3Holder.toString(), "Face6;:M9999;MYS;:H63:b,F");
    // explaining ";Face6;:M2;MYS;:H2:3,F" name:
    //
    // ";Face6" means default inheritance comes from face 6 of the ownFace6 (which is itself)
    // ";:M9999" means that a Workbench op happened. "M" is the "Mod" directory in the source tree?
    // ";MYS" means that a "Mystery" operation has happened. Notice the lack of a colon.
    // ";:H63" means the subtending object (cylinder) has a tag of 99 (63 in hex)
    // ":b" means the writing position is b (hex); literally how far into the current postfix we are
    // ",F" means are of type "F" which is short for "Face" of Face3 of Fusion.
}

TEST_F(ElementMapTest, hasChildElementMapTestV1)
{
    // Arrange
    Data::ElementMap::MappedChildElements child
        = {Data::IndexedName("face", 1), 2, 7, 4L, Data::ElementMapPtr(), QByteArray(""), _sid};
    std::vector<Data::ElementMap::MappedChildElements> children = {child};
    LessComplexPart cubeFull(3L, "FullBox", _hasher, _v1);
    cubeFull.elementMapPtr->addChildElements(cubeFull.Tag, children);
    //
    LessComplexPart cubeWithoutChildren(2L, "EmptyBox", _hasher, _v1);

    // Act
    bool resultFull = cubeFull.elementMapPtr->hasChildElementMap();
    bool resultWhenEmpty = cubeWithoutChildren.elementMapPtr->hasChildElementMap();

    // Assert
    EXPECT_TRUE(resultFull);
    EXPECT_FALSE(resultWhenEmpty);
}

TEST_F(ElementMapTest, hashChildMapsTestV1)
{
    // Arrange
    LessComplexPart cube(1L, "Box", _hasher, _v1);
    auto childOneName = Data::IndexedName("Ping", 1);
    Data::ElementMap::MappedChildElements childOne = {
        childOneName,
        2,
        7,
        3L,
        Data::ElementMapPtr(),
        QByteArray("abcdefghij"),  // postfix must be 10 or more bytes to invoke hasher
        _sid
    };
    std::vector<Data::ElementMap::MappedChildElements> children = {childOne};
    cube.elementMapPtr->addChildElements(cube.Tag, children);
    auto before = _hasher->getIDMap();

    // Act
    cube.elementMapPtr->hashChildMaps(cube.Tag);

    // Assert
    auto after = _hasher->getIDMap();
    EXPECT_EQ(before.size(), 0);
    EXPECT_EQ(after.size(), 1);
}

TEST_F(ElementMapTest, addAndGetChildElementsTestV1)
{
    // Arrange
    LessComplexPart cube(1L, "Box", _hasher, _v1);
    Data::ElementMap::MappedChildElements childOne = {
        Data::IndexedName("Ping", 1),
        2,
        7,
        3L,
        Data::ElementMapPtr(),
        QByteArray("abcdefghij"),  // postfix must be 10 or more bytes to invoke hasher
        _sid
    };
    Data::ElementMap::MappedChildElements childTwo
        = {Data::IndexedName("Pong", 2), 2, 7, 4L, Data::ElementMapPtr(), QByteArray("abc"), _sid};
    std::vector<Data::ElementMap::MappedChildElements> children = {childOne, childTwo};

    // Act
    cube.elementMapPtr->addChildElements(cube.Tag, children);
    auto result = cube.elementMapPtr->getChildElements();

    // Assert
    EXPECT_EQ(result.size(), 2);
    EXPECT_TRUE(std::any_of(result.begin(), result.end(), [](Data::ElementMap::MappedChildElements e) {
        return e.indexedName.toString() == "Ping1";
    }));
    EXPECT_TRUE(std::any_of(result.begin(), result.end(), [](Data::ElementMap::MappedChildElements e) {
        return e.indexedName.toString() == "Pong2";
    }));
}
TEST_F(ElementMapTest, findMappedNameIgnoresPostfixSplit)
{
    // Arrange: the same name, split between data and postfix in two ways
    Data::ElementMap elementMap;
    Data::IndexedName face1("Face", 1);
    Data::MappedName stored(Data::MappedName("Face1;_;1;"), "MKR;0;F;0;IDX,SRC;_");
    Data::MappedName lookedUp(Data::MappedName("Face1;"), "_;1;MKR;0;F;0;IDX,SRC;_");
    Data::MappedName whole("Face1;_;1;MKR;0;F;0;IDX,SRC;_");
    elementMap.setElementName(face1, stored, 1L);

    // Act & Assert
    EXPECT_EQ(elementMap.find(lookedUp), face1);
    EXPECT_EQ(elementMap.find(whole), face1);
}

// V2, the default algorithm. encodeElementName() does nothing and no child element maps are
// kept: an operation builds names with MappedName::makeEncodedSection(), and addChildElements()
// copies each child's names into the map. The expected names below are written from the V2
// grammar: sections joined by '|', each of 9 fields joined by ';' (reference IDs; linked names;
// iteration tag; op code; index; element type; duplicate count; mapper flags; connected names),
// '_' for an empty field, and '^' before each '|', ';' and ',' of a name embedded in a field.

namespace
{

// A map named like a shape without history: Face<i>;_;<tag>;MKR;0;F;0;IDX,SRC;_ for Face1-6
Data::ElementMapPtr makeUnmappedBoxMap(long tag, App::StringHasherRef hasher)
{
    auto map = std::make_shared<Data::ElementMap>();
    map->hasher = hasher;
    for (int i = 1; i <= 6; ++i) {
        Data::IndexedName face("Face", i);
        map->setElementName(
            face,
            Data::MappedName::makeUnmappedName({face.toString()}, static_cast<int>(tag), "MKR", 'F'),
            tag
        );
    }
    return map;
}

std::string faceName(int index, long tag, int duplicateCount)
{
    return "Face" + std::to_string(index) + ";_;" + std::to_string(tag) + ";MKR;0;F;"
        + std::to_string(duplicateCount) + ";IDX,SRC;_";
}

}  // namespace

TEST_F(ElementMapTest, mimicSimpleUnionV2)
{
    // Arrange
    //   pattern: new doc, create Cube, create Cylinder, Union of both (Cube first). The union's
    //   Face3 is one of the pieces the cylinder splits the cube's Face6 into.
    std::ostringstream finalSs;
    const char* docName = "Unnamed";
    LessComplexPart cube(1L, "Box", _hasher);
    LessComplexPart unionPart(3L, "Fusion", _hasher);
    Data::IndexedName uface3("Face", 3);
    auto cubeFace6 = cube.elementMapPtr->find(Data::IndexedName("Face", 6));

    // Act
    //   a split piece keeps its source's name and appends a MOD section with the union's tag
    Data::MappedName uface3Name(
        cubeFace6.toString() + Data::NAME_SECTION_DELIMINATOR
        + Data::MappedName::makeEncodedSection(
            std::vector<std::string> {},
            std::vector<Data::MappedName> {},
            static_cast<int>(unionPart.Tag),
            "FUS",
            0,
            'F',
            0,
            {Data::MAPPER_FLAG_MODIFIED},
            std::vector<Data::MappedName> {}
        )
    );
    unionPart.elementMapPtr->setElementName(uface3, uface3Name, unionPart.Tag, nullptr, true);

    //   a full toponame string
    finalSs << docName << "#" << unionPart.name << "." << Data::ELEMENT_MAP_PREFIX
            << unionPart.elementMapPtr->find(uface3) << "." << uface3;

    // Assert
    EXPECT_EQ(cubeFace6.toString(), "Face6");
    EXPECT_EQ(uface3Name.toString(), "Face6|_;_;3;FUS;0;F;0;MOD;_");
    EXPECT_EQ(unionPart.elementMapPtr->find(uface3), uface3Name);
    EXPECT_EQ(unionPart.elementMapPtr->find(uface3Name), uface3);
    EXPECT_EQ(finalSs.str(), "Unnamed#Fusion.;Face6|_;_;3;FUS;0;F;0;MOD;_.Face3");
    // the union's other faces keep their own names
    EXPECT_EQ(unionPart.elementMapPtr->find(Data::IndexedName("Face", 6)).toString(), "Face6");
}

TEST_F(ElementMapTest, mimicOperationAgainstSelfV2)
{
    // Arrange
    //   pattern: new doc, create Cube, Mystery Op (tag 99) that gives Face6, Face3 and Face5 the
    //   same name: a piece of its own Face6, bounded by an unmapped Edge1
    LessComplexPart finalPart(99L, "MysteryOp", _hasher);
    auto& map = finalPart.elementMapPtr;
    Data::IndexedName uface3("Face", 3);
    Data::IndexedName uface5("Face", 5);
    Data::IndexedName uface6("Face", 6);
    auto edge1Name = Data::MappedName::makeUnmappedName({"Edge1"}, 99, "MYS", 'E');
    Data::MappedName pieceName(
        map->find(uface6).toString() + Data::NAME_SECTION_DELIMINATOR
        + Data::MappedName::makeEncodedSection(
            std::vector<std::string> {},
            std::vector<Data::MappedName> {},
            static_cast<int>(finalPart.Tag),
            "MYS",
            0,
            'F',
            0,
            {Data::MAPPER_FLAG_MODIFIED},
            std::vector<Data::MappedName> {edge1Name}
        )
    );

    // Act
    auto face6Name = map->setElementName(uface6, pieceName, finalPart.Tag, nullptr, true);
    //   override not forced: a name that another element has is made unique
    auto face3Name = map->setElementName(uface3, pieceName, finalPart.Tag, nullptr, false);
    auto face5Name = map->setElementName(uface5, pieceName, finalPart.Tag, nullptr, false);

    // Assert
    EXPECT_EQ(edge1Name.toString(), "Edge1;_;99;MYS;0;E;0;IDX,SRC;_");
    EXPECT_EQ(
        pieceName.toString(),
        "Face6|_;_;99;MYS;0;F;0;MOD;Edge1^;_^;99^;MYS^;0^;E^;0^;IDX^,SRC^;_"
    );
    EXPECT_EQ(face6Name, pieceName);
    // the duplicate count of the last section counts up; the escaped ';' of the connected name
    // are not field delimiters
    EXPECT_EQ(
        face3Name.toString(),
        "Face6|_;_;99;MYS;0;F;1;MOD;Edge1^;_^;99^;MYS^;0^;E^;0^;IDX^,SRC^;_"
    );
    EXPECT_EQ(
        face5Name.toString(),
        "Face6|_;_;99;MYS;0;F;2;MOD;Edge1^;_^;99^;MYS^;0^;E^;0^;IDX^,SRC^;_"
    );
    EXPECT_EQ(map->find(pieceName), uface6);
    EXPECT_EQ(map->find(face3Name), uface3);
    EXPECT_EQ(map->find(face5Name), uface5);
    // Face6's own name was overwritten; Face3 keeps its first name as well
    EXPECT_EQ(map->find(uface6), pieceName);
    EXPECT_EQ(map->find(uface3).toString(), "Face3");
    EXPECT_EQ(map->findAll(uface3).size(), 2);
}

TEST_F(ElementMapTest, addChildElementsV2)
{
    // Arrange
    //   pattern: a compound (tag 3) of a box (tag 1) and the same box again, as in an array. The
    //   compound's Face1-6 are the first copy's Face1-6, its Face7-12 the second copy's.
    auto box = makeUnmappedBoxMap(1L, _hasher);
    auto compound = std::make_shared<Data::ElementMap>();
    compound->hasher = _hasher;
    std::vector<Data::ElementMap::MappedChildElements> children = {
        {Data::IndexedName("Face", 1), 6, 0, 1L, box, QByteArray(), _sid},
        {Data::IndexedName("Face", 1), 6, 6, 1L, box, QByteArray(), _sid},
    };

    // Act
    compound->addChildElements(3L, children);

    // Assert
    //   no child maps: the names are in the compound's own map
    EXPECT_FALSE(compound->hasChildElementMap());
    EXPECT_TRUE(compound->getChildElements().empty());
    EXPECT_EQ(compound->size(), 12);
    for (int i = 1; i <= 6; ++i) {
        SCOPED_TRACE(i);
        Data::IndexedName first("Face", i);
        Data::IndexedName second("Face", i + 6);
        //   the first copy keeps the box's names
        EXPECT_EQ(compound->find(first).toString(), faceName(i, 1L, 0));
        EXPECT_EQ(compound->find(Data::MappedName(faceName(i, 1L, 0))), first);
        //   the second copy's names get duplicate count 1
        EXPECT_EQ(compound->find(second).toString(), faceName(i, 1L, 1));
        EXPECT_EQ(compound->find(Data::MappedName(faceName(i, 1L, 1))), second);
    }
    //   the box's own map is unchanged
    EXPECT_EQ(box->size(), 6);
    EXPECT_EQ(box->find(Data::IndexedName("Face", 1)).toString(), faceName(1, 1L, 0));
}

TEST_F(ElementMapTest, hashChildMapsV2)
{
    // Arrange
    auto box = makeUnmappedBoxMap(1L, _hasher);
    auto compound = std::make_shared<Data::ElementMap>();
    compound->hasher = _hasher;
    std::vector<Data::ElementMap::MappedChildElements> children = {{
        Data::IndexedName("Face", 1),
        6,
        0,
        1L,
        box,
        QByteArray("abcdefghij"),  // long enough for V1 to hash it
        _sid
    }};
    compound->addChildElements(3L, children);

    // Act
    compound->hashChildMaps(3L);

    // Assert: V2 names are not hashed
    EXPECT_EQ(_hasher->getIDMap().size(), 0);
    EXPECT_FALSE(compound->hasChildElementMap());
    for (int i = 1; i <= 6; ++i) {
        SCOPED_TRACE(i);
        EXPECT_EQ(compound->find(Data::IndexedName("Face", i)).toString(), faceName(i, 1L, 0));
    }
}

TEST_F(ElementMapTest, addChildElementsWithoutMapV2)
{
    // Arrange
    //   pattern: a compound (tag 3) of two boxes without element maps (tags 4 and 5), as in a
    //   Part::Compound of two Part::Box (ops#24). Each child element gets an unmapped name,
    //   <child indexed name>;_;<child tag>;<op>;0;F;0;IDX,SRC;_, as mapSubElement() gives the
    //   elements of a single shape without a map. The op code is the child's postfix, MKR when
    //   there is none.
    auto compound = std::make_shared<Data::ElementMap>();
    compound->hasher = _hasher;
    std::vector<Data::ElementMap::MappedChildElements> children = {
        {Data::IndexedName("Face", 1), 6, 0, 4L, Data::ElementMapPtr(), QByteArray(), _sid},
        {Data::IndexedName("Face", 1), 6, 6, 5L, Data::ElementMapPtr(), QByteArray("CMP"), _sid},
    };

    // Act
    compound->addChildElements(3L, children);

    // Assert
    EXPECT_EQ(compound->size(), 12);
    for (int i = 1; i <= 6; ++i) {
        SCOPED_TRACE(i);
        Data::IndexedName first("Face", i);
        Data::IndexedName second("Face", i + 6);
        const std::string firstName = faceName(i, 4L, 0);
        const std::string secondName =
            "Face" + std::to_string(i) + ";_;5;CMP;0;F;0;IDX,SRC;_";
        EXPECT_EQ(compound->find(first).toString(), firstName);
        EXPECT_EQ(compound->find(Data::MappedName(firstName)), first);
        EXPECT_EQ(compound->find(second).toString(), secondName);
        EXPECT_EQ(compound->find(Data::MappedName(secondName)), second);
    }
}

TEST_F(ElementMapTest, setElementNameDuplicateCountsV2)
{
    // Arrange
    //   a single-section name, as a shape without history has (ops#55): the same name set on
    //   Face1-4 without overwrite, then a name that already carries duplicate count 2
    auto map = std::make_shared<Data::ElementMap>();
    map->hasher = _hasher;
    const Data::MappedName name(faceName(6, 7L, 0));

    // Act
    std::vector<Data::MappedName> stored;
    for (int i = 1; i <= 4; ++i) {
        stored.push_back(map->setElementName(Data::IndexedName("Face", i), name, 7L));
    }
    auto fromCount2 =
        map->setElementName(Data::IndexedName("Face", 5), Data::MappedName(faceName(6, 7L, 2)), 7L);

    // Assert
    //   every retry writes the duplicate count field and keeps the op code, whatever the count
    for (int i = 1; i <= 4; ++i) {
        SCOPED_TRACE(i);
        EXPECT_EQ(stored[i - 1].toString(), faceName(6, 7L, i - 1));
        EXPECT_EQ(map->find(Data::IndexedName("Face", i)), stored[i - 1]);
        EXPECT_EQ(map->find(stored[i - 1]), Data::IndexedName("Face", i));
    }
    //   a name that carries a count starts after it: 2 is Face3's, 3 is Face4's
    EXPECT_EQ(fromCount2.toString(), faceName(6, 7L, 4));
    EXPECT_EQ(map->find(fromCount2), Data::IndexedName("Face", 5));
}

TEST_F(ElementMapTest, addChildElementsPatternInstancesV2)
{
    // Arrange
    //   pattern: PartDesign's Transformed copies an original once per instance with
    //   makeElementTransform(..., Data::indexSuffix(k)): op "" for instance 2, "_2" for
    //   instance 3, "_3" for instance 4 (indexSuffix() gives nothing below 2). copyElementMap()
    //   passes that op as each child's postfix (ops#55). Four copies of Face1-6 of a box (tag 1):
    //   instance 1 (the support, as the original's own copy) and instances 2-4.
    const std::vector<QByteArray> postfixes = {QByteArray(), QByteArray(""), "_2", "_3"};
    auto instances = [&](const Data::ElementMapPtr& box) {
        std::vector<Data::ElementMap::MappedChildElements> children;
        for (int k = 0; k < 4; ++k) {
            children.push_back(
                {Data::IndexedName("Face", 1), 6, 6 * k, 1L, box, postfixes[k], _sid}
            );
        }
        return children;
    };
    auto fromMapless = std::make_shared<Data::ElementMap>();
    fromMapless->hasher = _hasher;
    auto fromMapped = std::make_shared<Data::ElementMap>();
    fromMapped->hasher = _hasher;

    // Act
    //   an original without a map (an additive primitive that is the body's first feature)
    fromMapless->addChildElements(3L, instances(Data::ElementMapPtr()));
    //   an original with a map (a Pad, or a primitive on a base)
    fromMapped->addChildElements(3L, instances(makeUnmappedBoxMap(1L, _hasher)));

    // Assert
    auto face = [](int k, int i) { return Data::IndexedName("Face", 6 * k + i); };
    for (int i = 1; i <= 6; ++i) {
        SCOPED_TRACE(i);
        const std::string rest = ";0;F;0;IDX,SRC;_";
        const std::string head = "Face" + std::to_string(i) + ";_;1;";
        //   without a map, each instance's postfix is its op code (MKR when empty): instances 1
        //   and 2 have the same name and are told apart by the duplicate count, instances 3 and 4
        //   by their op codes "_2" and "_3", each with duplicate count 0
        EXPECT_EQ(fromMapless->find(face(0, i)).toString(), faceName(i, 1L, 0));
        EXPECT_EQ(fromMapless->find(face(1, i)).toString(), faceName(i, 1L, 1));
        EXPECT_EQ(fromMapless->find(face(2, i)).toString(), head + "_2" + rest);
        EXPECT_EQ(fromMapless->find(face(3, i)).toString(), head + "_3" + rest);
        //   with a map, the postfix is not used: every instance keeps the original's name, told
        //   apart by the duplicate count 0-3
        for (int k = 0; k < 4; ++k) {
            EXPECT_EQ(fromMapped->find(face(k, i)).toString(), faceName(i, 1L, k));
        }
    }
    EXPECT_EQ(fromMapless->size(), 24);
    EXPECT_EQ(fromMapped->size(), 24);
}

TEST_F(ElementMapTest, addChildElementsPartlyMappedV2)
{
    // Arrange
    //   pattern: a shape (tag 3) takes a copy of a shape with the same tag, as copyElementMap()
    //   does (child tag 0 = the master's tag), whose map names only Face1 and Face2 of its 6 faces
    //   (tag 9, from an earlier operation). Face1-2 keep their names; Face3-6 get unmapped names
    //   with the master's tag, as mapSubElement() names an element without a name (ops#24).
    auto part = std::make_shared<Data::ElementMap>();
    part->hasher = _hasher;
    for (int i = 1; i <= 2; ++i) {
        part->setElementName(Data::IndexedName("Face", i), Data::MappedName(faceName(i, 9L, 0)), 9L);
    }
    auto copy = std::make_shared<Data::ElementMap>();
    copy->hasher = _hasher;
    std::vector<Data::ElementMap::MappedChildElements> children = {
        {Data::IndexedName("Face", 1), 6, 0, 0L, part, QByteArray(), _sid},
    };

    // Act
    copy->addChildElements(3L, children);

    // Assert
    EXPECT_EQ(copy->size(), 6);
    for (int i = 1; i <= 6; ++i) {
        SCOPED_TRACE(i);
        Data::IndexedName face("Face", i);
        const std::string expected = i <= 2 ? faceName(i, 9L, 0) : faceName(i, 3L, 0);
        EXPECT_EQ(copy->find(face).toString(), expected);
        EXPECT_EQ(copy->findAll(face).size(), 1);
    }
}

TEST_F(ElementMapTest, retagElementMapV2)
{
    // Arrange
    //   pattern: two objects (tags 21 and 22) get the same shape, built without a tag, as when
    //   Python code builds a face from a wire (tag 7) and several objects take it. The face is new
    //   (last section's tag 0, not yet tagged); its edge keeps the wire's name. Retagging gives
    //   the untagged last section the object's tag and leaves every other name as it is.
    const App::HistoryAlgorithm v2 {App::HistoryAlgorithm::V2};
    Data::IndexedName edge1("Edge", 1);
    Data::IndexedName face1("Face", 1);
    auto edgeName = Data::MappedName::makeUnmappedName({"Edge1"}, 7, "RTG", 'E');
    auto faceNameWithTag = [&](int tag) {
        return Data::MappedName::makeEncodedSection(
            std::vector<std::string> {},
            std::vector<Data::MappedName> {edgeName},
            tag,
            "RTG",
            0,
            'F',
            0,
            {Data::MAPPER_FLAG_GENERATED},
            std::vector<Data::MappedName> {}
        );
    };
    const std::string untagged = faceNameWithTag(0);
    auto makeMap = [&]() {
        auto map = std::make_shared<Data::ElementMap>();
        map->setHistoryAlgorithm(v2);
        map->hasher = _hasher;
        map->setElementName(edge1, edgeName, 0);
        map->setElementName(face1, Data::MappedName(untagged), 0);
        return map;
    };
    auto first = makeMap();
    auto second = makeMap();

    // Act
    first->retagElementMap(21);
    second->retagElementMap(22);
    //   a tagged section is not retagged again
    first->retagElementMap(23);

    // Assert
    EXPECT_EQ(edgeName.toString(), "Edge1;_;7;RTG;0;E;0;IDX,SRC;_");
    EXPECT_EQ(untagged, "_;Edge1^;_^;7^;RTG^;0^;E^;0^;IDX^,SRC^;_;0;RTG;0;F;0;GEN;_");
    const std::string tagged21 = "_;Edge1^;_^;7^;RTG^;0^;E^;0^;IDX^,SRC^;_;21;RTG;0;F;0;GEN;_";
    const std::string tagged22 = "_;Edge1^;_^;7^;RTG^;0^;E^;0^;IDX^,SRC^;_;22;RTG;0;F;0;GEN;_";
    EXPECT_EQ(first->find(face1).toString(), tagged21);
    EXPECT_EQ(first->find(Data::MappedName(tagged21)), face1);
    EXPECT_EQ(first->find(Data::MappedName(untagged)), Data::IndexedName());
    //   the second object's face gets its own tag, not the first object's
    EXPECT_EQ(second->find(face1).toString(), tagged22);
    EXPECT_EQ(second->find(Data::MappedName(tagged22)), face1);
    //   the edge is the wire's, not new: it keeps its name
    EXPECT_EQ(first->find(edge1), edgeName);
    EXPECT_EQ(second->find(edge1), edgeName);
    //   the untagged string still decodes as untagged: retagging changes no shared decoding
    const auto& decoded = Data::MappedName::getDecodedMappedName(untagged);
    ASSERT_EQ(decoded.size(), 1);
    EXPECT_EQ(decoded.back().iterationTag, "0");
}

TEST_F(ElementMapTest, copyV2)
{
    // Arrange
    //   pattern: a face with two names (the second with a string ID) and an edge with one; the
    //   face's first name is new and untagged (last section's tag 0).
    Data::IndexedName edge1("Edge", 1);
    Data::IndexedName face1("Face", 1);
    auto edgeName = Data::MappedName::makeUnmappedName({"Edge1"}, 7, "RTG", 'E');
    auto faceNameWithTag = [&](int tag) {
        return Data::MappedName(Data::MappedName::makeEncodedSection(
            std::vector<std::string> {},
            std::vector<Data::MappedName> {edgeName},
            tag,
            "RTG",
            0,
            'F',
            0,
            {Data::MAPPER_FLAG_GENERATED},
            std::vector<Data::MappedName> {}
        ));
    };
    Data::MappedName otherFaceName("OTHER");
    Data::ElementIDRefs sids {_hasher->getID("SID")};
    auto map = std::make_shared<Data::ElementMap>();
    map->hasher = _hasher;
    map->setElementName(edge1, edgeName, 0);
    map->setElementName(face1, faceNameWithTag(0), 0);
    map->setElementName(face1, otherFaceName, 0, &sids, false);

    // Act
    auto copy = map->copy();
    copy->retagElementMap(21);

    // Assert
    //   the copy has every name and string ID; its untagged name has the copy's tag
    EXPECT_EQ(copy->getHistoryAlgorithm(), App::HistoryAlgorithm::V2);
    EXPECT_EQ(copy->hasher, _hasher);
    EXPECT_EQ(copy->size(), 3);
    auto copyNames = copy->findAll(face1);
    ASSERT_EQ(copyNames.size(), 2);
    EXPECT_EQ(copyNames[0].first, faceNameWithTag(21));
    EXPECT_EQ(copyNames[1].first, otherFaceName);
    EXPECT_EQ(copyNames[1].second, sids);
    EXPECT_EQ(copy->find(faceNameWithTag(21)), face1);
    EXPECT_EQ(copy->find(otherFaceName), face1);
    EXPECT_EQ(copy->find(edgeName), edge1);
    //   the map it was copied from is unchanged
    auto names = map->findAll(face1);
    ASSERT_EQ(names.size(), 2);
    EXPECT_EQ(names[0].first, faceNameWithTag(0));
    EXPECT_EQ(names[1].first, otherFaceName);
    EXPECT_EQ(map->find(faceNameWithTag(0)), face1);
    EXPECT_EQ(map->find(faceNameWithTag(21)), Data::IndexedName());
}

TEST_F(ElementMapTest, retagElementMapLaterNamesV2)
{
    // Arrange
    //   pattern: a face with two new, untagged names (last section's tag 0), one from each of two
    //   edges, as when an element is named from two sources. The second name is kept in the first
    //   name's chain (setElementName with overwrite false), not in the element's own entry.
    Data::IndexedName edge1("Edge", 1);
    Data::IndexedName edge2("Edge", 2);
    Data::IndexedName face1("Face", 1);
    auto edge1Name = Data::MappedName::makeUnmappedName({"Edge1"}, 7, "RTG", 'E');
    auto edge2Name = Data::MappedName::makeUnmappedName({"Edge2"}, 8, "RTG", 'E');
    auto faceNameWithTag = [&](const Data::MappedName& edgeName, int tag) {
        return Data::MappedName(Data::MappedName::makeEncodedSection(
            std::vector<std::string> {},
            std::vector<Data::MappedName> {edgeName},
            tag,
            "RTG",
            0,
            'F',
            0,
            {Data::MAPPER_FLAG_GENERATED},
            std::vector<Data::MappedName> {}
        ));
    };
    auto map = std::make_shared<Data::ElementMap>();
    map->setHistoryAlgorithm(App::HistoryAlgorithm::V2);
    map->hasher = _hasher;
    map->setElementName(edge1, edge1Name, 0);
    map->setElementName(edge2, edge2Name, 0);
    map->setElementName(face1, faceNameWithTag(edge1Name, 0), 0);
    map->setElementName(face1, faceNameWithTag(edge2Name, 0), 0, nullptr, false);
    ASSERT_EQ(map->findAll(face1).size(), 2);

    // Act
    map->retagElementMap(21);

    // Assert
    //   both names carry the tag, and each finds the face
    auto names = map->findAll(face1);
    ASSERT_EQ(names.size(), 2);
    EXPECT_EQ(names[0].first, faceNameWithTag(edge1Name, 21));
    EXPECT_EQ(names[1].first, faceNameWithTag(edge2Name, 21));
    EXPECT_EQ(map->find(faceNameWithTag(edge1Name, 21)), face1);
    EXPECT_EQ(map->find(faceNameWithTag(edge2Name, 21)), face1);
    //   the untagged names are gone
    EXPECT_EQ(map->find(faceNameWithTag(edge1Name, 0)), Data::IndexedName());
    EXPECT_EQ(map->find(faceNameWithTag(edge2Name, 0)), Data::IndexedName());
    EXPECT_EQ(map->size(), 4);
    //   the edges keep their names
    EXPECT_EQ(map->find(edge1), edge1Name);
    EXPECT_EQ(map->find(edge2), edge2Name);
}

// The history of synthetic V2 names (ops#27): the shape's own tag is 7, its inputs' are 3 and 5.
TEST_F(ElementMapTest, getElementHistoryV2)
{
    // Arrange
    auto section = [](const std::vector<std::string>& refs,
                      const std::vector<Data::MappedName>& linked,
                      int tag,
                      const char* op,
                      char type,
                      const std::vector<std::string>& flags) {
        return Data::MappedName(
            Data::MappedName::makeEncodedSection(refs, linked, tag, op, 0, type, 0, flags, {}));
    };
    auto join = [](const Data::MappedName& prefix, const Data::MappedName& last) {
        return Data::MappedName(prefix.toString() + Data::NAME_SECTION_DELIMINATOR
                                + last.toString());
    };
    constexpr long ownTag = 7;
    Data::ElementMap map;
    struct Result
    {
        long tag;
        std::string original;
        std::vector<std::string> history;
    };
    auto historyOf = [&](const Data::MappedName& name, long masterTag = 7) {
        Data::MappedName original;
        std::vector<Data::MappedName> history;
        Result result {map.getElementHistory(name, masterTag, &original, &history), "", {}};
        result.original = original.toString();
        for (const auto& step : history) {
            result.history.push_back(step.toString());
        }
        return result;
    };
    // a face of map-less input 5 (by index), and an edge input 3 made
    auto boxFace = section({"Face6"}, {}, 5, "FUS", 'F', {"IDX", "SRC"});
    auto inputEdge = section({}, {boxFace}, 3, "FLT", 'E', {"GEN"});
    // what this shape made: a piece of the box face, an edge from two faces, a face named after
    // its edges, and a piece of that face
    auto piece = join(boxFace, section({}, {}, 7, "FUS", 'F', {"MOD"}));
    auto generated = section({}, {inputEdge, boxFace}, 7, "FUS", 'E', {"GEN"});
    auto lower = section({}, {inputEdge}, 7, "FUS", 'F', {"LOW"});
    auto lowerPiece = join(lower, section({}, {}, 7, "FUS", 'F', {"MOD"}));
    auto generatedFromPiece = section({}, {lowerPiece}, 7, "FUS", 'E', {"GEN"});
    auto partner = section({}, {inputEdge}, 7, "FUS", 'E', {"PRJ"});

    // Act and assert
    //   an input's element left unchanged: that input, under the same name
    auto result = historyOf(inputEdge);
    EXPECT_EQ(result.tag, 3);
    EXPECT_EQ(result.original, inputEdge.toString());
    EXPECT_TRUE(result.history.empty());
    //   with the element map prefix
    result = historyOf(
        Data::MappedName(std::string(Data::ELEMENT_MAP_PREFIX) + inputEdge.toString()));
    EXPECT_EQ(result.tag, 3);
    EXPECT_EQ(result.original, inputEdge.toString());
    //   an element of a map-less input: its index name there
    result = historyOf(boxFace);
    EXPECT_EQ(result.tag, 5);
    EXPECT_EQ(result.original, "Face6");
    EXPECT_TRUE(result.history.empty());
    //   a split piece: the element it was split from, through its name before the split
    result = historyOf(piece);
    EXPECT_EQ(result.tag, 5);
    EXPECT_EQ(result.original, "Face6");
    EXPECT_EQ(result.history, std::vector<std::string> {boxFace.toString()});
    //   a generated element: its first linked name
    result = historyOf(generated);
    EXPECT_EQ(result.tag, 3);
    EXPECT_EQ(result.original, inputEdge.toString());
    EXPECT_TRUE(result.history.empty());
    //   a partner (PRJ): the input element
    result = historyOf(partner);
    EXPECT_EQ(result.tag, 3);
    EXPECT_EQ(result.original, inputEdge.toString());
    //   named after its edges: nothing it was made from
    result = historyOf(lower);
    EXPECT_EQ(result.tag, 0);
    EXPECT_EQ(result.original, lower.toString());
    EXPECT_TRUE(result.history.empty());
    //   a piece of such a face: this shape's own face, as V1 gives the master tag
    result = historyOf(lowerPiece);
    EXPECT_EQ(result.tag, ownTag);
    EXPECT_EQ(result.original, lower.toString());
    EXPECT_TRUE(result.history.empty());
    //   two steps of this shape: the intermediate name is in the history
    result = historyOf(generatedFromPiece);
    EXPECT_EQ(result.tag, ownTag);
    EXPECT_EQ(result.original, lower.toString());
    EXPECT_EQ(result.history, std::vector<std::string> {lowerPiece.toString()});
    //   in the input's own shape, the input's element has nothing earlier
    result = historyOf(boxFace, 5);
    EXPECT_EQ(result.tag, 0);
    //   in input 3's shape, its edge goes back to the box face it was made from
    result = historyOf(inputEdge, 3);
    EXPECT_EQ(result.tag, 5);
    EXPECT_EQ(result.original, "Face6");
    EXPECT_EQ(result.history, std::vector<std::string> {boxFace.toString()});
    //   an untagged shape's own untagged steps: no tag to give
    auto untagged = join(section({"Face1"}, {}, 0, "FUS", 'F', {"IDX", "SRC"}),
                         section({}, {}, 0, "FUS", 'F', {"MOD"}));
    result = historyOf(untagged, 0);
    EXPECT_EQ(result.tag, 0);
    //   not a V2 name
    result = historyOf(Data::MappedName("Edge1"));
    EXPECT_EQ(result.tag, 0);
    EXPECT_EQ(result.original, "Edge1");
    //   V1 names keep V1's history
    result = historyOf(Data::MappedName("Edge1;:H5,E"));
    EXPECT_EQ(result.tag, 5);
    EXPECT_EQ(result.original, "Edge1");
    EXPECT_TRUE(result.history.empty());
    result = historyOf(Data::MappedName("Edge1;:H5,E;:M;FUS;:H7:7,E"));
    EXPECT_EQ(result.tag, 5);
    EXPECT_EQ(result.original, "Edge1");
    EXPECT_EQ(result.history, std::vector<std::string> {"Edge1;:H5,E"});
}

// Interned maps (ops#6, Task 1 PR 4). Nothing in FreeCAD sets the flag yet.
namespace
{

std::string encodedSection(
    const std::vector<std::string>& linked,
    long tag,
    const char* op,
    char type,
    const std::vector<std::string>& flags,
    const std::vector<std::string>& connected
)
{
    return Data::MappedName::makeEncodedSection(
        std::vector<std::string> {},
        linked,
        std::to_string(tag),
        op,
        "0",
        type,
        "0",
        flags,
        connected
    );
}

// The worked example of notes/naming-v2.md: a box edge, a fillet face on it, an edge bounded by
// that face (UPP), and a split piece of the face; the piece's last section is tagged pieceTag.
struct InternExample
{
    explicit InternExample(long pieceTag = 23)
        : piece(face + "|" + encodedSection({}, pieceTag, "CUT", 'F', {"MOD"}, {upper}))
    {}

    std::string edge = Data::MappedName::makeUnmappedName({"Edge1"}, 5, "FLT", 'E').toString();
    std::string face = encodedSection({edge}, 7, "FLT", 'F', {"GEN"}, {});
    std::string upper = encodedSection({face}, 9, "CUT", 'E', {"UPP"}, {});
    std::string piece;
};

std::string lastDuplicateCount(const Data::MappedName& name)
{
    const auto& decoded = name.getDecodedMappedName();
    return decoded.empty() ? std::string() : decoded.back().duplicateCount;
}

}  // namespace

TEST_F(ElementMapTest, internedAndPlainMapsGiveTheSameNamesV2)
{
    // Arrange
    //   the same names, in full and interned form, into a plain and an interned map; Face2-4 and
    //   Edge1-3 get one name each in either form, so the duplicate counts must agree too
    auto& table = Data::NameTable::instance();
    InternExample example;
    const std::vector<std::pair<Data::IndexedName, std::string>> inputs {
        {Data::IndexedName("Face", 1), example.face},
        {Data::IndexedName("Face", 2), example.piece},
        {Data::IndexedName("Face", 3), table.toInterned(example.piece)},
        {Data::IndexedName("Face", 4), example.piece},
        {Data::IndexedName("Edge", 1), table.toInterned(example.upper)},
        {Data::IndexedName("Edge", 2), example.upper},
        {Data::IndexedName("Edge", 3), example.upper},
        {Data::IndexedName("Edge", 4), example.edge},
    };
    auto plain = std::make_shared<Data::ElementMap>();
    plain->hasher = _hasher;
    auto interned = std::make_shared<Data::ElementMap>();
    interned->hasher = _hasher;
    interned->setInterned(true);

    // Act
    std::vector<Data::MappedName> plainNames;
    std::vector<Data::MappedName> internedNames;
    for (const auto& [element, name] : inputs) {
        plainNames.push_back(plain->setElementName(element, Data::MappedName(name), 23));
        internedNames.push_back(interned->setElementName(element, Data::MappedName(name), 23));
    }

    // Assert
    EXPECT_FALSE(plain->isInterned());
    EXPECT_TRUE(interned->isInterned());
    for (std::size_t i = 0; i < inputs.size(); ++i) {
        SCOPED_TRACE(i);
        const auto& element = inputs[i].first;
        std::string plainName = plainNames[i].toString();
        std::string internedName = internedNames[i].toString();
        EXPECT_EQ(plainName.find(Data::NameTable::Marker), std::string::npos) << plainName;
        EXPECT_EQ(internedName.find('^'), std::string::npos) << internedName;
        EXPECT_EQ(table.toPlain(internedName), plainName);
        EXPECT_EQ(plain->find(element), plainNames[i]);
        EXPECT_EQ(interned->find(element), internedNames[i]);
        EXPECT_EQ(interned->find(internedNames[i]), element);
        EXPECT_EQ(lastDuplicateCount(internedNames[i]), lastDuplicateCount(plainNames[i]));
    }
    //   the duplicates are counted across forms
    EXPECT_EQ(lastDuplicateCount(plainNames[1]), "0");
    EXPECT_EQ(lastDuplicateCount(plainNames[2]), "1");
    EXPECT_EQ(lastDuplicateCount(plainNames[3]), "2");
    EXPECT_EQ(lastDuplicateCount(plainNames[6]), "2");
    //   a name without embedded names is the same in both maps
    EXPECT_EQ(internedNames[7].toString(), example.edge);
    EXPECT_EQ(interned->getAll().size(), plain->getAll().size());
}

TEST_F(ElementMapTest, retagInternedMapKeepsThePrefixV2)
{
    // Arrange
    //   a split piece whose last section isn't tagged yet, and a face that is
    auto& table = Data::NameTable::instance();
    InternExample untagged(0);
    InternExample tagged(31);
    Data::IndexedName face1("Face", 1);
    Data::IndexedName face2("Face", 2);
    auto makeMap = [&](bool internNames) {
        auto map = std::make_shared<Data::ElementMap>();
        map->hasher = _hasher;
        map->setInterned(internNames);
        map->setElementName(face1, Data::MappedName(untagged.piece), 0);
        map->setElementName(face2, Data::MappedName(untagged.face), 0);
        return map;
    };
    auto plain = makeMap(false);
    auto interned = makeMap(true);
    std::string before = interned->find(face1).toString();

    // Act
    plain->retagElementMap(31);
    interned->retagElementMap(31);

    // Assert
    std::string after = interned->find(face1).toString();
    std::size_t bar = Data::NameTable::lastTopLevelBar(after);
    ASSERT_NE(bar, std::string::npos);
    //   the prefix `~<ID>` and the Connected Name's `~<ID>` are kept, only the tag changes
    EXPECT_EQ(after.substr(0, bar), before.substr(0, bar));
    EXPECT_TRUE(Data::NameTable::parseRef(after.substr(0, bar)));
    EXPECT_EQ(after.substr(after.rfind(';')), before.substr(before.rfind(';')));
    EXPECT_NE(after.find(";31;CUT;"), std::string::npos) << after;
    EXPECT_EQ(after, table.toInterned(tagged.piece));
    //   the same as retagging the plain map
    EXPECT_EQ(plain->find(face1).toString(), tagged.piece);
    EXPECT_EQ(table.toPlain(after), tagged.piece);
    EXPECT_EQ(interned->find(Data::MappedName(after)), face1);
    EXPECT_EQ(interned->find(Data::MappedName(before)), Data::IndexedName());
    //   a tagged last section isn't retagged
    EXPECT_EQ(plain->find(face2).toString(), untagged.face);
    EXPECT_EQ(table.toPlain(interned->find(face2).toString()), untagged.face);
}

TEST_F(ElementMapTest, internedFlagIsCopiedAndIgnoredInV1)
{
    // Arrange
    InternExample example;
    auto map = std::make_shared<Data::ElementMap>();
    map->hasher = _hasher;
    map->setInterned(true);
    auto v1 = std::make_shared<Data::ElementMap>();
    v1->setHistoryAlgorithm(_v1);
    v1->hasher = _hasher;
    v1->setInterned(true);

    // Act
    auto copied = map->copy();
    auto stored = v1->setElementName(Data::IndexedName("Face", 1), Data::MappedName(example.face), 1);

    // Assert
    EXPECT_TRUE(copied->isInterned());
    EXPECT_FALSE(std::make_shared<Data::ElementMap>()->isInterned());
    EXPECT_EQ(stored.toString(), example.face);  // V1 names are never interned
}

TEST_F(ElementMapTest, namesAreFoundInEitherFormV2)
{
    // ops#6, Task 1 PR 6: a reference made before the document's InternNames changed holds the
    // other form; the lookup finds its element all the same
    // Arrange
    auto& table = Data::NameTable::instance();
    InternExample example;
    const std::string internedPiece = table.toInterned(example.piece);
    auto plain = std::make_shared<Data::ElementMap>();
    plain->hasher = _hasher;
    auto interned = std::make_shared<Data::ElementMap>();
    interned->hasher = _hasher;
    interned->setInterned(true);
    const Data::IndexedName element("Face", 3);
    plain->setElementName(element, Data::MappedName(example.piece), 23);
    interned->setElementName(element, Data::MappedName(example.piece), 23);

    // Act
    auto plainByInterned = plain->find(Data::MappedName(internedPiece));
    auto internedByPlain = interned->find(Data::MappedName(example.piece));
    auto internedByInterned = interned->find(Data::MappedName(internedPiece));
    auto missing = interned->find(Data::MappedName(example.upper));

    // Assert
    EXPECT_NE(internedPiece, example.piece);
    EXPECT_EQ(plainByInterned, element);
    EXPECT_EQ(internedByPlain, element);
    EXPECT_EQ(internedByInterned, element);
    EXPECT_FALSE(missing);
}

TEST_F(ElementMapTest, namesAreFoundInAMixedMapV2)
{
    // ops#97: a map can hold names in the other form than its flag's, e.g. names stored before
    // the flag was set (a map restored before its document's form was applied). A lookup finds
    // them in either form all the same.
    // Arrange
    auto& table = Data::NameTable::instance();
    InternExample example;
    const std::string internedPiece = table.toInterned(example.piece);
    const Data::IndexedName element("Face", 3);
    auto flaggedInterned = std::make_shared<Data::ElementMap>();  // plain names, interned flag
    flaggedInterned->hasher = _hasher;
    flaggedInterned->setElementName(element, Data::MappedName(example.piece), 23);
    flaggedInterned->setInterned(true);
    auto flaggedPlain = std::make_shared<Data::ElementMap>();  // interned names, plain flag
    flaggedPlain->hasher = _hasher;
    flaggedPlain->setInterned(true);
    flaggedPlain->setElementName(element, Data::MappedName(example.piece), 23);
    flaggedPlain->setInterned(false);

    // Act and assert
    EXPECT_EQ(flaggedInterned->find(Data::MappedName(example.piece)), element);
    EXPECT_EQ(flaggedInterned->find(Data::MappedName(internedPiece)), element);
    EXPECT_EQ(flaggedPlain->find(Data::MappedName(internedPiece)), element);
    EXPECT_EQ(flaggedPlain->find(Data::MappedName(example.piece)), element);
    EXPECT_FALSE(flaggedInterned->find(Data::MappedName(example.upper)));
    EXPECT_FALSE(flaggedPlain->find(Data::MappedName(example.upper)));
}

TEST_F(ElementMapTest, beforeSaveCollectsTheReferencesV2)
{
    // ops#6, Task 1 PR 7: while a document saves, its maps hand the references in their names to
    // the active collector, so the file can hold the entries
    // Arrange
    auto& table = Data::NameTable::instance();
    InternExample example;
    auto plain = std::make_shared<Data::ElementMap>();
    plain->hasher = _hasher;
    auto interned = std::make_shared<Data::ElementMap>();
    interned->hasher = _hasher;
    interned->setInterned(true);
    for (const auto& map : {plain, interned}) {
        map->setElementName(Data::IndexedName("Face", 1), Data::MappedName(example.piece), 23);
        map->setElementName(Data::IndexedName("Face", 2), Data::MappedName(example.face), 7);
        map->setElementName(Data::IndexedName("Edge", 1), Data::MappedName(example.edge), 5);
    }
    std::set<Data::NameId> expected;
    for (const auto& name : {table.toInterned(example.piece), table.toInterned(example.face)}) {
        for (std::size_t pos = name.find('~'); pos != std::string::npos;
             pos = name.find('~', pos + 1)) {
            expected.insert(*Data::NameTable::parseRef(name.substr(pos, Data::NameTable::RefLength)));
        }
    }
    ASSERT_EQ(expected.size(), 3U);  // the piece's prefix (the face), its upper edge, the face's edge

    // Act
    plain->beforeSave(_hasher);  // no collector: nothing to do
    Data::NameRefCollector plainCollector;
    plain->beforeSave(_hasher);
    Data::NameRefCollector internedCollector;
    interned->beforeSave(_hasher);

    // Assert
    EXPECT_TRUE(plainCollector.refs().empty());
    EXPECT_EQ(internedCollector.refs(), expected);
    //   and the entries close over them: the upper edge's content refers to the face again
    EXPECT_EQ(internedCollector.entries(table).size(), 3U);
}

// NOLINTEND(readability-magic-numbers)
