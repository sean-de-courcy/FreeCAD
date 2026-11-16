// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>
#include <gmock/gmock.h>

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>

#include <zipios++/zipinputstream.h>

#include "App/Application.h"
#include "App/Document.h"
#include "App/DocumentObjectGroup.h"
#include "App/Expression.h"
#include "App/FeatureTest.h"
#include "App/Link.h"
#include "App/ObjectIdentifier.h"
#include "App/ForkRelease.h"
#include "App/NamingRevision.h"
#include "App/MergeDocuments.h"
#include "App/MappedName.h"
#include "App/NameTable.h"
#include "App/PropertyStandard.h"
#include "App/RecomputeContinuation.h"
#include "App/StringHasher.h"
#include "Base/Console.h"
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

// The space-separated words of the first attribute `name` of xml; none if it has none
std::set<std::string> attributeWords(const std::string& xml, const std::string& name)
{
    const std::string start = ' ' + name + "=\"";
    const auto begin = xml.find(start);
    if (begin == std::string::npos) {
        return {};
    }
    std::istringstream words(
        xml.substr(begin + start.size(), xml.find('"', begin + start.size()) - begin - start.size()));
    return {std::istream_iterator<std::string>(words), std::istream_iterator<std::string>()};
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

// ------------------------------------------------------------------------------------------------
// The fork release stamp and newer files (ops#323). Opening saved files with edited markers is
// tested in Python (parttests/ForkReleaseTest.py).

namespace
{
// Counts the console errors that hold `text` while it is attached
class ErrorCounter final: public Base::ILogger
{
public:
    explicit ErrorCounter(std::string text)
        : _text(std::move(text))
    {
        Base::Console().attachObserver(this);
    }
    ~ErrorCounter() override
    {
        Base::Console().detachObserver(this);
    }
    ErrorCounter(const ErrorCounter&) = delete;
    ErrorCounter(ErrorCounter&&) = delete;
    ErrorCounter& operator=(const ErrorCounter&) = delete;
    ErrorCounter& operator=(ErrorCounter&&) = delete;

    void sendLog(
        const std::string& /*notifiername*/,
        const std::string& msg,
        Base::LogStyle level,
        Base::IntendedRecipient /*recipient*/,
        Base::ContentType /*content*/
    ) override
    {
        if (level == Base::LogStyle::Error && msg.find(_text) != std::string::npos) {
            ++count;
        }
    }
    const char* name() override
    {
        return "ErrorCounter";
    }

    int count = 0;

private:
    std::string _text;
};
}  // namespace

TEST_F(DocumentTest, saveAndExportWriteTheForkRelease)
{
    addNote(doc(), "Stamped", "Pad.Face1");
    const std::set<std::string> release {std::to_string(App::ForkRelease)};
    EXPECT_EQ(App::forkReleaseOf(doc()), App::ForkRelease);
    EXPECT_FALSE(App::isNewerFormat(doc()));

    std::stringstream exported;
    doc()->exportObjects({doc()->getObject("Stamped")}, exported);
    EXPECT_EQ(attributeWords(documentXml(exported), "ForkRelease"), release);

    const std::string path = App::Application::getTempFileName();
    ASSERT_TRUE(doc()->saveAs(path.c_str()));
    std::ifstream file(doc()->getFileName(), std::ios::in | std::ios::binary);
    ASSERT_TRUE(file.is_open());
    EXPECT_EQ(attributeWords(documentXml(file), "ForkRelease"), release);
    EXPECT_EQ(App::forkReleaseOf(doc()), App::ForkRelease);
    file.close();
    std::remove(doc()->getFileName());
}

TEST_F(DocumentTest, importOfANewerCopyMakesTheDocumentNewer)
{
    // Arrange: a copy whose ForkRelease is above this build's
    addNote(doc(), "Copied", "Pad.Face1");
    std::stringstream exported;
    doc()->exportObjects({doc()->getObject("Copied")}, exported);
    std::string xml = documentXml(exported);
    const std::string stamp = "ForkRelease=\"" + std::to_string(App::ForkRelease) + "\"";
    const auto at = xml.find(stamp);
    ASSERT_NE(at, std::string::npos);
    const std::string newer = std::to_string(App::ForkRelease + 1);
    xml.replace(at, stamp.size(), "ForkRelease=\"" + newer + "\"");
    std::stringstream copy;
    {
        Base::ZipWriter writer(copy);
        writer.putNextEntry("Document.xml");
        writer.Stream() << xml;
    }
    auto& app = App::GetApplication();
    const std::string name = app.getUniqueDocumentName("NewerTarget");
    App::Document* target = app.newDocument(name.c_str(), "testUser");

    // Act
    ErrorCounter errors("ForkRelease " + newer);
    App::MergeDocuments(target).importObjects(copy);

    // Assert: one console error; the document keeps its own release, and only it is newer
    EXPECT_EQ(errors.count, 1);
    EXPECT_TRUE(App::isNewerFormat(target));
    EXPECT_NE(App::newerFormatMessage(target).find("ForkRelease " + newer), std::string::npos);
    EXPECT_EQ(App::forkReleaseOf(target), App::ForkRelease);
    EXPECT_TRUE(App::takeNewerFormatNotice(target));
    EXPECT_FALSE(App::takeNewerFormatNotice(target)) << "the GUI warns once";
    EXPECT_FALSE(App::isNewerFormat(doc()));
    app.closeDocument(name.c_str());
}

TEST_F(DocumentTest, newerForkTokensAreThoseAboveTheBuilds)
{
    const int revision = App::forkNamingRevision();
    auto version = [](int f, int n) {
        return "15.70200.1.5.F" + std::to_string(f) + ".N" + std::to_string(n);
    };
    EXPECT_FALSE(App::hasNewerForkTokens(version(revision, 2)));
    EXPECT_FALSE(App::hasNewerForkTokens(version(revision - 1, 2)));
    EXPECT_FALSE(App::hasNewerForkTokens("15.70200.1.5.F" + std::to_string(revision)));
    EXPECT_FALSE(App::hasNewerForkTokens("15.70200.1.5"));
    EXPECT_FALSE(App::hasNewerForkTokens("15.70200.1.5.X1"));
    EXPECT_FALSE(App::hasNewerForkTokens(""));
    EXPECT_TRUE(App::hasNewerForkTokens(version(revision + 1, 2)));
    EXPECT_TRUE(App::hasNewerForkTokens(version(revision, 3)));
    EXPECT_TRUE(App::hasNewerForkTokens("15.70200.1.5.F" + std::to_string(revision + 10)));
    // More digits than an int holds: newer, never an overflow (PR 293 review)
    EXPECT_TRUE(App::hasNewerForkTokens("15.70200.1.5.F99999999999.N2"));
    EXPECT_TRUE(App::hasNewerForkTokens("15.70200.1.5.F1.N4294967298"));
}

// ------------------------------------------------------------------------------------------------
// The recompute's continuation rule (ops#126): a failed object the rule claims doesn't stop the
// recompute; its dependants are run, failed or skipped as the rule decides.

namespace
{

bool startsWith(const App::DocumentObject* obj, const char* prefix)
{
    return std::string(obj->getNameInDocument()).starts_with(prefix);
}

/// Continues after objects named Member* and Fail*; decides by the dependant's name: Fail* fails
/// with "Failed by rule", anything else runs. Holds objects named Held*. Counts afterFailure() per
/// object.
class NameRule: public App::RecomputeContinuation
{
public:
    bool continuesAfter(const App::DocumentObject* failed) const override
    {
        return startsWith(failed, "Member") || startsWith(failed, "Fail");
    }

    App::AfterInputFailure decide(const App::DocumentObject* /*failed*/,
                                  const App::DocumentObject* dependant,
                                  std::string& why) const override
    {
        if (startsWith(dependant, "Fail")) {
            why = "Failed by rule";
            return App::AfterInputFailure::Fail;
        }
        return App::AfterInputFailure::Run;
    }

    bool holds(const App::DocumentObject* obj) const override
    {
        return startsWith(obj, "Held");
    }

    void afterFailure(App::DocumentObject* failed) const override
    {
        ++afterFailures[failed->getNameInDocument()];
    }

    mutable std::map<std::string, int> afterFailures;
};

}  // namespace

namespace
{
// For each object of each import into `doc` while it lives, in order: whether its source is
// `doc` itself (importedWithin), as the import's slots see it
struct WithinRecorder
{
    explicit WithinRecorder(App::Document* doc)
        : connection(doc->signalImportObjects.connect(
              [doc, this](const std::vector<App::DocumentObject*>& objs, Base::XMLReader&) {
                  for (auto obj : objs) {
                      auto source = App::importedSource(obj);
                      within.push_back(source && App::importedWithin(*source, *doc));
                  }
              }))
    {}
    ~WithinRecorder()
    {
        connection.disconnect();
    }
    WithinRecorder(const WithinRecorder&) = delete;
    WithinRecorder& operator=(const WithinRecorder&) = delete;
    fastsignals::connection connection;
    std::vector<bool> within;
};
}  // namespace

// A copy is from the document it is pasted into only when it is that document, by UUID: the
// clipboard can outlive its document, and a new document can take that name (ops#171 A)
TEST_F(DocumentTest, importedWithinGoesByTheDocumentsUuid)
{
    auto& app = App::GetApplication();
    const std::string name = app.getUniqueDocumentName("CopySource");
    App::Document* source = app.newDocument(name.c_str(), "testUser");
    source->addObject("App::DocumentObjectGroup", "Copied");
    std::stringstream copied;
    source->exportObjects({source->getObject("Copied")}, copied);
    EXPECT_NE(documentXml(copied).find(std::string("SourceDocument=\"") + source->Uid.getValueStr()
                                       + "\""),
              std::string::npos);

    {
        WithinRecorder recorder(source);
        copied.clear();
        copied.seekg(0);
        App::MergeDocuments(source).importObjects(copied);
        EXPECT_EQ(recorder.within, std::vector<bool>({true}));
    }
    app.closeDocument(name.c_str());

    // another document under the same name
    App::Document* sameName = app.newDocument(name.c_str(), "testUser");
    ASSERT_EQ(std::string(sameName->getName()), name);
    {
        WithinRecorder recorder(sameName);
        copied.clear();
        copied.seekg(0);
        App::MergeDocuments(sameName).importObjects(copied);
        EXPECT_EQ(recorder.within, std::vector<bool>({false}));
    }
    app.closeDocument(name.c_str());
}

// A copy made by a build with SourceDocument only (before SourceDocuments, PR 275) still goes by
// it: its objects are within the document they came from, and not within another
TEST_F(DocumentTest, importedWithinReadsACopyWithSourceDocumentOnly)
{
    auto& app = App::GetApplication();
    const std::string name = app.getUniqueDocumentName("OldCopyTarget");
    App::Document* other = app.newDocument(name.c_str(), "testUser");
    doc()->addObject("App::DocumentObjectGroup", "Copied");
    std::stringstream exported;
    doc()->exportObjects({doc()->getObject("Copied")}, exported);
    std::string xml = documentXml(exported);
    const std::string attribute = " SourceDocuments=\"";
    const auto begin = xml.find(attribute);
    ASSERT_NE(begin, std::string::npos);
    xml.erase(begin, xml.find('"', begin + attribute.size()) + 1 - begin);
    ASSERT_EQ(xml.find("SourceDocuments="), std::string::npos);
    ASSERT_NE(xml.find("SourceDocument=\"" + doc()->Uid.getValueStr() + "\""), std::string::npos);
    std::stringstream old;
    {
        Base::ZipWriter writer(old);
        writer.putNextEntry("Document.xml");
        writer.Stream() << xml;
    }

    for (auto [into, within] : {std::pair {doc(), true}, std::pair {other, false}}) {
        WithinRecorder recorder(into);
        old.clear();
        old.seekg(0);
        App::MergeDocuments(into).importObjects(old);
        EXPECT_EQ(recorder.within, std::vector<bool>({within})) << into->getName();
    }
    app.closeDocument(name.c_str());
}

// An import run from inside another import into the same document leaves the outer one's
// sources in place (ops#171 C: it cleared them)
TEST_F(DocumentTest, nestedImportKeepsTheOuterImportsSources)
{
    doc()->addObject("App::DocumentObjectGroup", "Outer");
    doc()->addObject("App::DocumentObjectGroup", "Inner");
    std::stringstream outer;
    std::stringstream inner;
    doc()->exportObjects({doc()->getObject("Outer")}, outer);
    doc()->exportObjects({doc()->getObject("Inner")}, inner);

    std::optional<App::ImportedSource> after;
    bool nested = false;
    auto connection = doc()->signalImportObjects.connect(
        [&](const std::vector<App::DocumentObject*>& objs, Base::XMLReader&) {
            if (nested || objs.empty()) {
                return;
            }
            nested = true;
            App::MergeDocuments(doc()).importObjects(inner);
            after = App::importedSource(objs.front());
        });
    App::MergeDocuments(doc()).importObjects(outer);
    connection.disconnect();

    ASSERT_TRUE(nested);
    ASSERT_TRUE(after.has_value());
    EXPECT_EQ(after->name.substr(0, after->name.find('@')), "Outer");
    EXPECT_TRUE(App::importedWithin(*after, *doc()));
}

// The source of a copy is the objects' own document, not the one that exports them: copyObject
// exports from the destination (PR 266 review H1). Objects of several documents have none, so
// none of them counts as copied within the document they are pasted into
TEST_F(DocumentTest, importedWithinGoesByTheObjectsDocument)
{
    auto& app = App::GetApplication();
    const std::string name = app.getUniqueDocumentName("CopyTarget");
    App::Document* other = app.newDocument(name.c_str(), "testUser");
    auto* copied = doc()->addObject("App::DocumentObjectGroup", "Copied");
    auto* local = other->addObject("App::DocumentObjectGroup", "Local");
    {
        WithinRecorder recorder(other);
        other->copyObject({copied});
        EXPECT_EQ(recorder.within, std::vector<bool>({false}));
    }

    std::stringstream exported;
    other->exportObjects({copied}, exported);
    EXPECT_NE(documentXml(exported).find("SourceDocument=\"" + doc()->Uid.getValueStr() + "\""),
              std::string::npos);

    // a mixed list names each object's document (SourceDocuments), and has no SourceDocument
    // (ops#171 B1, PR 266 verification L1)
    std::stringstream mixed;
    other->exportObjects({local, copied}, mixed);
    const std::string xml = documentXml(mixed);
    EXPECT_EQ(xml.find("SourceDocument="), std::string::npos);
    EXPECT_EQ(attributeWords(xml, "SourceDocuments"),
              std::set<std::string>(
                  {std::string(other->getName()) + ':' + other->Uid.getValueStr(),
                   std::string(doc()->getName()) + ':' + doc()->Uid.getValueStr()}));
    {
        // Local is other's own: within it (the list had no document before); Copied is doc()'s
        WithinRecorder recorder(other);
        mixed.clear();
        mixed.seekg(0);
        App::MergeDocuments(other).importObjects(mixed);
        EXPECT_EQ(recorder.within, std::vector<bool>({true, false}));
    }
    app.closeDocument(name.c_str());
}

// Two open documents can share a UUID (a Save As, saveCopy or file copy opened beside its
// original): a copy from one isn't from the other (PR 266 review M1)
TEST_F(DocumentTest, importedWithinTellsDocumentsWithOneUuidApart)
{
    auto& app = App::GetApplication();
    const std::string name = app.getUniqueDocumentName("Twin");
    App::Document* twin = app.newDocument(name.c_str(), "testUser");
    // the transient directory goes by the UUID and the file name: with the same file name the
    // document would take another UUID
    twin->FileName.setValue((std::filesystem::temp_directory_path() / (name + ".FCStd")).string());
    twin->Uid.setValue(doc()->Uid.getValue());
    ASSERT_EQ(twin->Uid.getValueStr(), doc()->Uid.getValueStr());

    doc()->addObject("App::DocumentObjectGroup", "Copied");
    std::stringstream copied;
    doc()->exportObjects({doc()->getObject("Copied")}, copied);
    {
        WithinRecorder recorder(twin);
        App::MergeDocuments(twin).importObjects(copied);
        EXPECT_EQ(recorder.within, std::vector<bool>({false}));
    }
    {
        WithinRecorder recorder(doc());
        copied.clear();
        copied.seekg(0);
        App::MergeDocuments(doc()).importObjects(copied);
        EXPECT_EQ(recorder.within, std::vector<bool>({true}));
    }
    app.closeDocument(name.c_str());
}

// FreeCAD-CH (ops#654 10.15): what an observer of signalBecameStable writes after a recompute
// outside any transaction goes into the last undo step, which keeps its id and its place
class StableStepTest: public DocumentTest
{
protected:
    void TearDown() override
    {
        _observer.disconnect();
        DocumentTest::TearDown();
    }

    /// At the next signalBecameStable, an observer adds the object name, once. Groups: their
    /// recompute writes no input (a FeatureTest's does)
    void addOnStable(const char* name)
    {
        _observer = doc()->signalBecameStable.connect([this, made = std::string(name)](
                                                          const App::Document&
                                                      ) {
            if (!_added) {
                _added = true;
                doc()->addObject("App::DocumentObjectGroup", made.c_str());
            }
        });
    }

    App::DocumentObject* addInStep(const char* step, const char* name)
    {
        doc()->openTransaction(step);
        auto obj = doc()->addObject("App::DocumentObjectGroup", name);
        doc()->recompute();
        doc()->commitTransaction();
        return obj;
    }

private:
    fastsignals::scoped_connection _observer;
    bool _added = false;
};

TEST_F(StableStepTest, anObserverWriteAfterACommitJoinsTheLastStep)
{
    auto a = addInStep("add", "A");
    const int id = doc()->getTransactionID(true, 0);
    ASSERT_EQ(doc()->getAvailableUndos(), 1);
    addOnStable("W");
    a->touch();
    doc()->recompute();
    ASSERT_NE(doc()->getObject("W"), nullptr);
    EXPECT_EQ(doc()->getAvailableUndos(), 1);
    EXPECT_EQ(doc()->getTransactionID(true, 0), id);
    EXPECT_EQ(doc()->getAvailableUndoNames(), std::vector<std::string>({"add"}));
    EXPECT_FALSE(doc()->hasPendingTransaction());
    EXPECT_TRUE(doc()->undo());
    EXPECT_EQ(doc()->getObject("W"), nullptr);
    EXPECT_EQ(doc()->getObject("A"), nullptr);
    EXPECT_TRUE(doc()->redo());
    EXPECT_NE(doc()->getObject("W"), nullptr);
    EXPECT_NE(doc()->getObject("A"), nullptr);
}

TEST_F(StableStepTest, aRecomputeWithNoWriteLeavesTheStepsAsTheyWere)
{
    addInStep("first", "A");
    auto b = addInStep("second", "B");
    const int first = doc()->getTransactionID(true, 1);
    const int second = doc()->getTransactionID(true, 0);
    b->touch();
    doc()->recompute();
    EXPECT_EQ(doc()->getAvailableUndos(), 2);
    EXPECT_EQ(doc()->getTransactionID(true, 0), second);
    EXPECT_EQ(doc()->getTransactionID(true, 1), first);
    EXPECT_EQ(doc()->getAvailableRedos(), 0);
    EXPECT_FALSE(doc()->hasPendingTransaction());
    EXPECT_TRUE(doc()->undo());
    EXPECT_EQ(doc()->getObject("B"), nullptr);
    EXPECT_NE(doc()->getObject("A"), nullptr);
}

TEST_F(StableStepTest, aWriteWithRedoNonEmptyClearsRedo)
{
    addInStep("first", "A");
    addInStep("second", "B");
    ASSERT_TRUE(doc()->undo());
    ASSERT_EQ(doc()->getAvailableRedos(), 1);
    addOnStable("W");
    doc()->getObject("A")->touch();
    doc()->recompute();
    ASSERT_NE(doc()->getObject("W"), nullptr);
    EXPECT_EQ(doc()->getAvailableRedos(), 0);
    EXPECT_EQ(doc()->getAvailableUndos(), 1);
    EXPECT_FALSE(doc()->redo());
}

TEST_F(StableStepTest, aBookedRecomputeMakesNoStepOfItsOwn)
{
    auto a = addInStep("add", "A");
    addOnStable("W");
    App::GetApplication().setActiveDocument(doc());
    App::GetApplication().setActiveTransaction(App::TransactionName {.name = "Recompute"});
    a->touch();
    doc()->recompute();
    App::GetApplication().closeActiveTransaction();
    ASSERT_NE(doc()->getObject("W"), nullptr);
    EXPECT_EQ(doc()->getAvailableUndoNames(), std::vector<std::string>({"add"}));
    EXPECT_TRUE(doc()->undo());
    EXPECT_EQ(doc()->getObject("W"), nullptr);
}

class RecomputeContinuationTest: public DocumentTest
{
protected:
    void SetUp() override
    {
        DocumentTest::SetUp();
        _rule = std::make_shared<NameRule>();
    }

    void TearDown() override
    {
        App::setRecomputeContinuation(nullptr);
        DocumentTest::TearDown();
    }

    void installRule()
    {
        App::setRecomputeContinuation(_rule);
    }

    NameRule& rule()
    {
        return *_rule;
    }

    App::FeatureTest* add(const char* name, App::DocumentObject* source = nullptr)
    {
        auto obj = static_cast<App::FeatureTest*>(doc()->addObject("App::FeatureTest", name));
        obj->Source1.setValue(source);
        return obj;
    }

    App::FeatureTest* addFailing(const char* name, App::DocumentObject* source = nullptr)
    {
        auto obj = add(name, source);
        obj->ExceptionType.setValue(2);  // throws Base::RuntimeError
        return obj;
    }

private:
    std::shared_ptr<NameRule> _rule;
};

TEST_F(RecomputeContinuationTest, withoutRuleAFailureFailsItsDependantsNamingTheirInput)
{
    // Arrange
    auto member = addFailing("Member");
    auto dependant = add("Dependant", member);
    auto later = add("Later", dependant);

    // Act
    int count = doc()->recompute();

    // Assert: none runs; each fails naming its direct input (ops#579). The failure stays touched;
    // its dependants, stopped and judged, are left with nothing pending (round 8, J13: Onshape has
    // no needs-recompute state)
    EXPECT_EQ(count, 3);
    EXPECT_TRUE(member->isError());
    EXPECT_TRUE(member->isTouched());
    for (auto [obj, text] : {std::pair {dependant, "Source1 links to 'Member', which has an error"},
                             std::pair {later, "Source1 links to 'Dependant', which has an error"}}) {
        EXPECT_EQ(obj->ExecCount.getValue(), 0);
        EXPECT_TRUE(obj->isError());
        EXPECT_FALSE(obj->isTouched());
        ASSERT_NE(doc()->getErrorDescription(obj), nullptr);
        EXPECT_STREQ(doc()->getErrorDescription(obj), text);
    }

    // And they run again when what stopped them is repaired: its recompute enforces its in-list
    member->ExceptionType.setValue(0);
    doc()->recompute();
    for (auto obj : {member, dependant, later}) {
        EXPECT_TRUE(obj->isValid()) << obj->getNameInDocument();
    }
    EXPECT_EQ(dependant->ExecCount.getValue(), 1);
    EXPECT_EQ(later->ExecCount.getValue(), 1);
}

TEST_F(RecomputeContinuationTest, anUnclaimedFailureFailsItsDependants)
{
    // Arrange
    installRule();
    auto other = addFailing("Other");
    auto dependant = add("Dependant", other);

    // Act
    doc()->recompute();

    // Assert: the rule doesn't claim Other, so its dependant fails naming it (ops#579), and is left
    // with nothing pending (round 8, J13)
    EXPECT_TRUE(other->isError());
    EXPECT_TRUE(other->isTouched());
    EXPECT_EQ(dependant->ExecCount.getValue(), 0);
    EXPECT_TRUE(dependant->isError());
    EXPECT_FALSE(dependant->isTouched());
    ASSERT_NE(doc()->getErrorDescription(dependant), nullptr);
    EXPECT_STREQ(doc()->getErrorDescription(dependant),
                 "Source1 links to 'Other', which has an error");
    EXPECT_EQ(rule().afterFailures.count("Other"), 0U);
    EXPECT_EQ(rule().afterFailures.count("Dependant"), 0U);
}

TEST_F(RecomputeContinuationTest, aFailedDependantStaysFailedThenRecoversWithItsInput)
{
    // Arrange
    auto other = addFailing("Other");
    auto dependant = add("Dependant", other);
    doc()->recompute();

    // Act: nothing changed
    doc()->recompute();

    // Assert: the input fails again, and so does the dependant, without running
    EXPECT_TRUE(dependant->isError());
    EXPECT_EQ(dependant->ExecCount.getValue(), 0);

    // Act: the input is repaired
    other->ExceptionType.setValue(0);
    doc()->recompute();

    // Assert: the dependant runs and its error goes
    EXPECT_TRUE(other->isValid());
    EXPECT_TRUE(dependant->isValid());
    EXPECT_FALSE(dependant->isTouched());
    EXPECT_EQ(dependant->ExecCount.getValue(), 1);
    EXPECT_EQ(doc()->getErrorDescription(dependant), nullptr);
}

TEST_F(RecomputeContinuationTest, anExpressionOnAFailureNamesTheObject)
{
    // Arrange
    auto other = addFailing("Other");
    auto dependant = add("Dependant");
    dependant->setExpression(
        App::ObjectIdentifier(dependant->Integer),
        std::shared_ptr<App::Expression>(App::Expression::parse(dependant, "Other.Integer")));

    // Act
    doc()->recompute();

    // Assert
    EXPECT_TRUE(other->isError());
    EXPECT_EQ(dependant->ExecCount.getValue(), 0);
    EXPECT_TRUE(dependant->isError());
    ASSERT_NE(doc()->getErrorDescription(dependant), nullptr);
    EXPECT_STREQ(doc()->getErrorDescription(dependant), "'Other' has an error");

    // Act: repaired, with the property the expression reads unchanged
    other->ExceptionType.setValue(0);
    doc()->recompute();

    // Assert: it runs all the same (a fine-grained recompute enforces by changed property only)
    EXPECT_TRUE(other->isValid());
    EXPECT_TRUE(dependant->isValid());
    EXPECT_EQ(dependant->ExecCount.getValue(), 1);
}

TEST_F(RecomputeContinuationTest, aContainerOfAFailureIsNotFailed)
{
    // Arrange
    auto other = addFailing("Other");
    auto folder = static_cast<App::DocumentObjectGroup*>(
        doc()->addObject("App::DocumentObjectGroup", "Folder"));
    folder->addObject(other);

    // Act
    doc()->recompute();

    // Assert: its Group isn't an input (ops#579)
    EXPECT_TRUE(other->isError());
    EXPECT_FALSE(folder->isError());
    EXPECT_EQ(doc()->getErrorDescription(folder), nullptr);
}

TEST_F(RecomputeContinuationTest, aReaderOfAContainerOfAFailureFailsNamingIt)
{
    // Arrange: readers of a folder holding the failure: whole, through a subname path, through a
    // Link to the folder
    installRule();
    auto other = addFailing("Other");
    auto folder = static_cast<App::DocumentObjectGroup*>(
        doc()->addObject("App::DocumentObjectGroup", "Folder"));
    folder->addObject(other);
    auto whole = add("Whole", folder);
    auto path = add("Path");
    path->LinkSub.setValue(folder, std::vector<std::string> {"Other."});
    auto link = static_cast<App::Link*>(doc()->addObject("App::Link", "FolderLink"));
    link->LinkedObject.setValue(folder);
    auto viaLink = add("ViaLink", link);

    // Act
    doc()->recompute();

    // Assert: the folder itself isn't failed (decision 250 (5)); every reader is (decision 253)
    EXPECT_FALSE(folder->isError());
    for (auto [obj, text] :
         {std::pair<App::DocumentObject*, const char*> {
              whole, "Source1 links to 'Folder', and 'Other' in it has an error"},
          {path, "LinkSub links to 'Folder', and 'Other' in it has an error"},
          // A Link to a group lists its children itself (_ChildCache): a direct input
          {link, "_ChildCache links to 'Other', which has an error"},
          {viaLink, "Source1 links to 'FolderLink', which has an error"}}) {
        EXPECT_TRUE(obj->isError()) << obj->getNameInDocument();
        ASSERT_NE(doc()->getErrorDescription(obj), nullptr) << obj->getNameInDocument();
        EXPECT_STREQ(doc()->getErrorDescription(obj), text);
    }
    EXPECT_EQ(whole->ExecCount.getValue(), 0);

    // Act: repaired
    other->ExceptionType.setValue(0);
    doc()->recompute();

    // Assert
    for (App::DocumentObject* obj : {static_cast<App::DocumentObject*>(whole),
                                     static_cast<App::DocumentObject*>(path),
                                     static_cast<App::DocumentObject*>(link),
                                     static_cast<App::DocumentObject*>(viaLink)}) {
        EXPECT_TRUE(obj->isValid()) << obj->getNameInDocument();
    }
    EXPECT_EQ(whole->ExecCount.getValue(), 1);
}

TEST_F(RecomputeContinuationTest, aReaderInAnotherDocumentOfAContainerOfAFailureFailsAtOnce)
{
    // Arrange
    auto& app = App::GetApplication();
    const std::string otherName = app.getUniqueDocumentName("OtherDocument");
    App::Document* other = app.newDocument(otherName.c_str(), "testUser");
    const std::string path = App::Application::getTempFileName() + ".FCStd";
    const std::string otherPath = App::Application::getTempFileName() + ".FCStd";
    ASSERT_TRUE(doc()->saveAs(path.c_str()));
    ASSERT_TRUE(other->saveAs(otherPath.c_str()));
    auto input = add("Input");
    auto folder = static_cast<App::DocumentObjectGroup*>(
        doc()->addObject("App::DocumentObjectGroup", "Folder"));
    folder->addObject(input);
    // An App::Link refuses a group in another document (its _ChildCache): a plain XLink reads it
    auto link = other->addObject("App::FeatureTest", "Reader");
    auto watched = static_cast<App::PropertyXLink*>(
        link->addDynamicProperty("App::PropertyXLink", "Watched"));
    watched->setValue(folder);
    doc()->recompute();
    other->recompute();
    ASSERT_TRUE(link->isValid());

    // Act: only the input's document recomputes
    input->ExceptionType.setValue(2);
    doc()->recompute();

    // Assert: the folder isn't failed; the Link reading it fails at once in its own document
    EXPECT_FALSE(folder->isError());
    EXPECT_TRUE(link->isError());
    EXPECT_TRUE(link->isTouched());
    ASSERT_NE(other->getErrorDescription(link), nullptr);
    EXPECT_STREQ(other->getErrorDescription(link),
                 "Watched links to 'Folder', and 'Input' in it has an error");

    // Act: repaired, then the other document recomputes
    input->ExceptionType.setValue(0);
    doc()->recompute();
    other->recompute();

    // Assert
    EXPECT_TRUE(link->isValid());
    EXPECT_EQ(other->getErrorDescription(link), nullptr);

    app.closeDocument(otherName.c_str());
    std::remove(path.c_str());
    std::remove(otherPath.c_str());
}

TEST_F(RecomputeContinuationTest, aHeldDependantOfAFailureIsNotFailed)
{
    // Arrange
    installRule();
    auto other = addFailing("Other");
    auto held = add("HeldDependant", other);

    // Act
    doc()->recompute();

    // Assert: held, so neither run nor judged
    EXPECT_TRUE(other->isError());
    EXPECT_EQ(held->ExecCount.getValue(), 0);
    EXPECT_FALSE(held->isError());
    EXPECT_TRUE(held->isTouched());
}

TEST_F(RecomputeContinuationTest, aDependantInAnotherDocumentFailsAtOnceAndRecovers)
{
    // Arrange: a Link in another document to a failing object; both documents saved, as a link
    // across documents needs
    auto& app = App::GetApplication();
    const std::string otherName = app.getUniqueDocumentName("OtherDocument");
    App::Document* other = app.newDocument(otherName.c_str(), "testUser");
    const std::string path = App::Application::getTempFileName() + ".FCStd";
    const std::string otherPath = App::Application::getTempFileName() + ".FCStd";
    ASSERT_TRUE(doc()->saveAs(path.c_str()));
    ASSERT_TRUE(other->saveAs(otherPath.c_str()));
    auto input = add("Input");
    auto link = static_cast<App::Link*>(other->addObject("App::Link", "Reader"));
    link->LinkedObject.setValue(input);
    doc()->recompute();
    other->recompute();
    ASSERT_TRUE(link->isValid());

    // Act: only the input's document recomputes
    input->ExceptionType.setValue(2);
    doc()->recompute();

    // Assert: the Link fails at once, in its own document, and is left touched for its document
    EXPECT_TRUE(input->isError());
    EXPECT_TRUE(link->isError());
    EXPECT_TRUE(link->isTouched());
    ASSERT_NE(other->getErrorDescription(link), nullptr);
    EXPECT_STREQ(other->getErrorDescription(link),
                 "LinkedObject links to 'Input', which has an error");

    // Act: its document recomputes, the input still failing
    other->recompute();

    // Assert: judged again, it still fails
    EXPECT_TRUE(link->isError());
    ASSERT_NE(other->getErrorDescription(link), nullptr);

    // Act: the input is repaired in its document, then the other recomputes
    input->ExceptionType.setValue(0);
    doc()->recompute();
    EXPECT_TRUE(link->isTouched());
    other->recompute();

    // Assert
    EXPECT_TRUE(input->isValid());
    EXPECT_TRUE(link->isValid());
    EXPECT_EQ(other->getErrorDescription(link), nullptr);

    app.closeDocument(otherName.c_str());
    std::remove(path.c_str());
    std::remove(otherPath.c_str());
}

TEST_F(RecomputeContinuationTest, aClaimedFailureRunsItsDependants)
{
    // Arrange
    installRule();
    auto member = addFailing("Member");
    auto dependant = add("Dependant", member);
    auto later = add("Later", dependant);

    // Act
    doc()->recompute();

    // Assert: the failure keeps its error, is purged, and the chain after it ran
    EXPECT_TRUE(member->isError());
    EXPECT_FALSE(member->isTouched());
    EXPECT_NE(doc()->getErrorDescription(member), nullptr);
    EXPECT_EQ(rule().afterFailures["Member"], 1);
    EXPECT_EQ(dependant->ExecCount.getValue(), 1);
    EXPECT_TRUE(dependant->isValid());
    EXPECT_EQ(later->ExecCount.getValue(), 1);
}

TEST_F(RecomputeContinuationTest, aFailVerdictFailsTheDependantWithoutRunningIt)
{
    // Arrange
    installRule();
    auto member = addFailing("Member");
    auto failed = add("FailDependant", member);
    auto later = add("Later", failed);

    // Act
    doc()->recompute();

    // Assert
    EXPECT_EQ(failed->ExecCount.getValue(), 0);
    EXPECT_TRUE(failed->isError());
    ASSERT_NE(doc()->getErrorDescription(failed), nullptr);
    EXPECT_STREQ(doc()->getErrorDescription(failed), "Failed by rule");
    EXPECT_EQ(rule().afterFailures["FailDependant"], 1);
    EXPECT_EQ(later->ExecCount.getValue(), 1);
}

TEST_F(RecomputeContinuationTest, aContinuedFailureIsNotRerunAndKeepsItsText)
{
    // Arrange
    installRule();
    auto member = addFailing("Member");
    auto dependant = add("Dependant", member);
    doc()->recompute();
    ASSERT_NE(doc()->getErrorDescription(member), nullptr);
    std::string text = doc()->getErrorDescription(member);

    // Act
    int count = doc()->recompute();

    // Assert
    EXPECT_EQ(count, 0);
    EXPECT_TRUE(member->isError());
    ASSERT_NE(doc()->getErrorDescription(member), nullptr);
    EXPECT_EQ(text, doc()->getErrorDescription(member));
    EXPECT_EQ(rule().afterFailures["Member"], 1);
    EXPECT_EQ(dependant->ExecCount.getValue(), 1);
}

TEST_F(RecomputeContinuationTest, aDependantTouchedLaterIsStillJudged)
{
    // Arrange
    installRule();
    auto member = addFailing("Member");
    auto failed = add("FailDependant");
    doc()->recompute();
    ASSERT_TRUE(failed->isValid());

    // Act: link it to the failure that is no longer touched
    failed->Source1.setValue(member);
    doc()->recompute();

    // Assert
    EXPECT_TRUE(failed->isError());
    EXPECT_EQ(failed->ExecCount.getValue(), 1);
}

TEST_F(RecomputeContinuationTest, aRepairedFailureRunsAgainAndClearsTheError)
{
    // Arrange
    installRule();
    auto member = addFailing("Member");
    auto dependant = add("Dependant", member);
    doc()->recompute();

    // Act
    member->ExceptionType.setValue(0);
    doc()->recompute();

    // Assert
    EXPECT_TRUE(member->isValid());
    EXPECT_EQ(doc()->getErrorDescription(member), nullptr);
    EXPECT_EQ(member->ExecCount.getValue(), 1);
    EXPECT_EQ(dependant->ExecCount.getValue(), 2);
}

TEST_F(RecomputeContinuationTest, aCarriedTextOfARemovedObjectIsDropped)
{
    // Arrange
    installRule();
    addFailing("Member");
    auto other = add("Other");
    doc()->recompute();

    // Act
    doc()->removeObject("Member");
    other->touch();
    doc()->recompute();

    // Assert: nothing left of it, and the document still recomputes
    EXPECT_EQ(doc()->getObject("Member"), nullptr);
    EXPECT_TRUE(other->isValid());
    EXPECT_EQ(other->ExecCount.getValue(), 2);
}

TEST_F(RecomputeContinuationTest, recomputeFeatureCallsAfterFailure)
{
    // Arrange
    installRule();
    auto member = addFailing("Member");

    // Act
    bool valid = doc()->recomputeFeature(member);

    // Assert
    EXPECT_FALSE(valid);
    EXPECT_TRUE(member->isError());
    EXPECT_EQ(rule().afterFailures["Member"], 1);
}

// NOLINTEND(readability-magic-numbers)
