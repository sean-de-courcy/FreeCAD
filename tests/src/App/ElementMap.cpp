// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <App/Application.h>
#include <App/ElementMap.h>
#include <src/App/InitApplication.h>

// NOLINTBEGIN(readability-magic-numbers)


// this is a "holder" class used for simpler testing of ElementMap in the context of a class
class LessComplexPart
{
public:
    LessComplexPart(long tag,
                    const std::string& nameStr,
                    App::StringHasherRef hasher,
                    const App::HistoryAlgorithm* algorithm = nullptr)
        : elementMapPtr(std::make_shared<Data::ElementMap>())
        , Tag(tag)
        , name(nameStr)
    {
        // nullptr means the default algorithm (V2)
        elementMapPtr->syncHistoryAlgorithm(algorithm);
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

    LessComplexPart cube(1L, "Box", _hasher, &_v1);
    LessComplexPart cylinder(2L, "Cylinder", _hasher, &_v1);
    // Union (Fusion) operation via the Part Workbench
    LessComplexPart unionPart(3L, "Fusion", _hasher, &_v1);

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
    LessComplexPart finalPart(99L, "MysteryOp", _hasher, &_v1);
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
    LessComplexPart cubeFull(3L, "FullBox", _hasher, &_v1);
    cubeFull.elementMapPtr->addChildElements(cubeFull.Tag, children);
    //
    LessComplexPart cubeWithoutChildren(2L, "EmptyBox", _hasher, &_v1);

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
    LessComplexPart cube(1L, "Box", _hasher, &_v1);
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
    LessComplexPart cube(1L, "Box", _hasher, &_v1);
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
    //   Part::Compound of two Part::Box. Each child element should get an unmapped name,
    //   <child indexed name>;_;<child tag>;<op>;0;F;0;IDX,SRC;_, as mapSubElement() gives the
    //   elements of a single shape without a map. The op code is left open. Known failure: ops#24.
    auto compound = std::make_shared<Data::ElementMap>();
    compound->hasher = _hasher;
    std::vector<Data::ElementMap::MappedChildElements> children = {
        {Data::IndexedName("Face", 1), 6, 0, 4L, Data::ElementMapPtr(), QByteArray(), _sid},
        {Data::IndexedName("Face", 1), 6, 6, 5L, Data::ElementMapPtr(), QByteArray(), _sid},
    };

    // Act
    compound->addChildElements(3L, children);

    // Assert
    const std::string tail = ";0;F;0;IDX,SRC;_";
    for (int i = 1; i <= 12; ++i) {
        SCOPED_TRACE(i);
        const int childIndex = i <= 6 ? i : i - 6;
        const long childTag = i <= 6 ? 4L : 5L;
        const std::string name = compound->find(Data::IndexedName("Face", i)).toString();
        const std::string head =
            "Face" + std::to_string(childIndex) + ";_;" + std::to_string(childTag) + ";";
        EXPECT_EQ(name.substr(0, head.size()), head);
        EXPECT_TRUE(name.size() >= tail.size() && name.substr(name.size() - tail.size()) == tail)
            << name;
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
        map->syncHistoryAlgorithm(&v2);
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

// NOLINTEND(readability-magic-numbers)
