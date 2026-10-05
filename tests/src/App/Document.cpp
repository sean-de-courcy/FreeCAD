// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>
#include <gmock/gmock.h>

#include <cstdio>
#include <fstream>
#include <iterator>
#include <sstream>

#include <zipios++/zipinputstream.h>

#include "App/Application.h"
#include "App/Document.h"
#include "App/MergeDocuments.h"
#include "App/MappedName.h"
#include "App/NameTable.h"
#include "App/PropertyStandard.h"
#include "App/StringHasher.h"
#include "Base/Writer.h"
#include <src/App/InitApplication.h>

using ::testing::Eq;
using ::testing::Ne;

// NOLINTBEGIN(readability-magic-numbers)

class FakeWriter: public Base::Writer
{
    void writeFiles() override
    {}
    std::ostream& Stream() override
    {
        return std::cout;
    }
};

class DocumentTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        _docName = App::GetApplication().getUniqueDocumentName("test");
        _doc = App::GetApplication().newDocument(_docName.c_str(), "testUser");
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    App::Document* doc()
    {
        return _doc;
    }

private:
    std::string _docName;
    App::Document* _doc {};
};


TEST_F(DocumentTest, addStringHasherIndicatesUnwrittenWhenNew)
{
    // Arrange
    App::StringHasherRef hasher(new App::StringHasher);

    // Act
    auto addResult = doc()->addStringHasher(hasher);

    // Assert
    EXPECT_TRUE(addResult.first);
    EXPECT_THAT(addResult.second, Ne(-1));
}

TEST_F(DocumentTest, addStringHasherIndicatesAlreadyWritten)
{
    // Arrange
    App::StringHasherRef hasher(new App::StringHasher);
    doc()->addStringHasher(hasher);

    // Act
    auto addResult = doc()->addStringHasher(hasher);

    // Assert
    EXPECT_FALSE(addResult.first);
}

TEST_F(DocumentTest, getStringHasherGivesExpectedHasher)
{
    // Arrange
    App::StringHasherRef hasher(new App::StringHasher);
    auto pair = doc()->addStringHasher(hasher);
    int index = pair.second;

    // Act
    auto foundHasher = doc()->getStringHasher(index);

    // Assert
    EXPECT_EQ(hasher, foundHasher);
}

TEST_F(DocumentTest, importObjectsRestoresSourceStringHasher)
{
    // Arrange
    auto& app = App::GetApplication();
    const std::string sourceName = app.getUniqueDocumentName("MergeSource");
    App::Document* source = app.newDocument(sourceName.c_str(), "testUser");
    App::StringHasherRef sourceHasher = source->getStringHasher();
    ASSERT_TRUE(sourceHasher);
    sourceHasher->setSaveAll(true);
    sourceHasher->getID("persisted element name");

    const std::string path = App::Application::getTempFileName();
    ASSERT_TRUE(source->saveAs(path.c_str()));
    const std::string savedPath = source->getFileName();
    app.closeDocument(sourceName.c_str());

    std::size_t restoredStringCount = 0;
    auto connection = doc()->signalFinishImportObjects.connect(
        [this, &restoredStringCount](const std::vector<App::DocumentObject*>&) {
            App::StringHasherRef importedHasher = doc()->getStringHasher(0);
            restoredStringCount = importedHasher ? importedHasher->size() : 0;
        }
    );

    // Act
    std::ifstream stream(savedPath, std::ios::in | std::ios::binary);
    ASSERT_TRUE(stream.is_open());
    App::MergeDocuments merge(doc());
    merge.importObjects(stream);

    // Assert
    EXPECT_GT(restoredStringCount, 0);
    connection.disconnect();
    std::remove(savedPath.c_str());
}

namespace
{
// The Document.xml of an exported or saved zip.
std::string documentXml(std::istream& zip)
{
    zipios::ZipInputStream entry(zip);
    return {std::istreambuf_iterator<char>(entry), std::istreambuf_iterator<char>()};
}

App::PropertyString* addNote(App::Document* document, const char* name, const std::string& note)
{
    auto* holder = document->addObject("App::DocumentObjectGroup", name);
    auto* prop = static_cast<App::PropertyString*>(
        holder->addDynamicProperty("App::PropertyString", "Note")
    );
    prop->setValue(note);
    return prop;
}
}  // namespace

TEST_F(DocumentTest, exportObjectsCarriesTheEntriesOfInternedNames)
{
    // Arrange: an object whose XML holds an interned name (ops#6), and one whose XML holds none
    using Strings = std::vector<std::string>;
    auto& table = Data::NameTable::instance();
    std::string edge = Data::MappedName::makeEncodedSection(
        Strings {"Edge1"},
        Strings {},
        "5",
        "FLT",
        "0",
        'E',
        "0",
        Strings {"IDX"},
        Strings {}
    );
    std::string face = Data::MappedName::makeEncodedSection(
        Strings {},
        Strings {edge},
        "7",
        "FLT",
        "0",
        'F',
        "0",
        Strings {"GEN"},
        Strings {}
    );
    std::string interned = table.toInterned(face);
    auto edgeId = table.internName(edge);
    ASSERT_TRUE(edgeId);
    std::string note = "Pad.;" + interned + ".Face1";
    addNote(doc(), "Holder", note);
    addNote(doc(), "Plain", "Pad.Face1");

    // Act
    std::stringstream withName;
    doc()->exportObjects({doc()->getObject("Holder")}, withName);
    std::stringstream plain;
    doc()->exportObjects({doc()->getObject("Plain")}, plain);
    std::string xml = documentXml(withName);
    std::string plainXml = documentXml(plain);

    // Assert: the table, before the objects, with the edge's entry (its content, at index 0: the
    // file has no IDs, ops#6 T2); none for the plain one. The XML keeps the hash form.
    EXPECT_NE(xml.find("NamingFormat=\"2\""), std::string::npos) << xml;
    auto tableAt = xml.find("<NameTable count=\"1\">");
    ASSERT_NE(tableAt, std::string::npos) << xml;
    EXPECT_LT(tableAt, xml.find("<Objects"));
    EXPECT_NE(xml.find("NameTableStart v2 1\n" + *table.lookup(*edgeId) + '\n'), std::string::npos)
        << xml;
    EXPECT_EQ(xml.find(edgeId->toBase32() + ' '), std::string::npos) << xml;
    EXPECT_NE(xml.find(interned), std::string::npos) << xml;
    EXPECT_EQ(plainXml.find("NamingFormat"), std::string::npos);
    EXPECT_EQ(plainXml.find("<NameTable"), std::string::npos);

    // and it imports with the name as it was
    auto& app = App::GetApplication();
    const std::string targetName = app.getUniqueDocumentName("ImportTarget");
    App::Document* target = app.newDocument(targetName.c_str(), "testUser");
    withName.clear();
    withName.seekg(0);
    App::MergeDocuments merge(target);
    auto objects = merge.importObjects(withName);
    ASSERT_EQ(objects.size(), 1U);
    auto* imported = dynamic_cast<App::PropertyString*>(objects[0]->getPropertyByName("Note"));
    ASSERT_NE(imported, nullptr);
    EXPECT_EQ(imported->getStrValue(), note);
    app.closeDocument(targetName.c_str());
}

TEST_F(DocumentTest, saveAndExportCarryTheEntriesOfTheSourcesNames)
{
    // Arrange: an interned name that only a source gives (as a GUI document gives its view
    // providers' states, which GuiDocument.xml holds after the table, ops#97), for one object
    using Strings = std::vector<std::string>;
    auto& table = Data::NameTable::instance();
    std::string edge = Data::MappedName::makeEncodedSection(
        Strings {"Edge2"},
        Strings {},
        "5",
        "SRC",
        "0",
        'E',
        "0",
        Strings {"IDX"},
        Strings {}
    );
    std::string face = Data::MappedName::makeEncodedSection(
        Strings {},
        Strings {edge},
        "7",
        "SRC",
        "0",
        'F',
        "0",
        Strings {"GEN"},
        Strings {}
    );
    std::string interned = table.toInterned(face);
    auto edgeId = table.internName(edge);
    ASSERT_TRUE(edgeId);
    std::string state = "Pad.;" + interned + ".Face1";
    addNote(doc(), "Holder", "Pad.Face1");
    addNote(doc(), "Other", "Pad.Face1");
    Strings asked;
    auto key = Data::NameRefCollector::addSource(
        [&](const App::DocumentObject& obj, Data::NameRefCollector& collector) {
            asked.emplace_back(obj.getNameInDocument());
            if (asked.back() == "Holder") {
                collector.add(state);
            }
        }
    );

    // Act
    std::stringstream exported;
    doc()->exportObjects({doc()->getObject("Other"), doc()->getObject("Holder")}, exported);
    const std::string path = App::Application::getTempFileName();
    bool saved = doc()->saveAs(path.c_str());
    Data::NameRefCollector::removeSource(key);
    std::stringstream withoutSource;
    doc()->exportObjects({doc()->getObject("Holder")}, withoutSource);

    // Assert: both files hold the edge's entry, which nothing in their XML refers to; the
    // sources are asked object by object, in the order saved
    ASSERT_TRUE(saved);
    std::ifstream file(doc()->getFileName(), std::ios::in | std::ios::binary);
    ASSERT_TRUE(file.is_open());
    for (const std::string& xml : {documentXml(exported), documentXml(file)}) {
        EXPECT_NE(xml.find("<NameTable count=\"1\">"), std::string::npos) << xml;
        std::string entries = "NameTableStart v2 1\n" + *table.lookup(*edgeId) + '\n';
        EXPECT_NE(xml.find(entries), std::string::npos) << xml;
        EXPECT_EQ(xml.find(interned), std::string::npos) << xml;
    }
    EXPECT_EQ(asked, (Strings {"Other", "Holder", "Holder", "Other"}));
    EXPECT_EQ(documentXml(withoutSource).find("<NameTable"), std::string::npos);
    file.close();
    std::remove(doc()->getFileName());
}

// NOLINTEND(readability-magic-numbers)
