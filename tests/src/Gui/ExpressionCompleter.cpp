// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QTest>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Expression.h>
#include <App/ObjectIdentifier.h>
#include <App/PropertyUnits.h>
#include <Base/Quantity.h>
#include <src/App/InitApplication.h>

#include "Gui/ExpressionCompleter.h"

// Designed checks of the expression completer (ops#152): a document with an owner object and a
// VarSet, and a second document with its own VarSet. The rows a user is offered are read the way
// the popup reads them, through QCompleter's completion model, after typing into an
// ExpressionLineEdit bound to the owner.

class ExpressionCompleterTest: public QObject
{
    Q_OBJECT

public:
    ExpressionCompleterTest()
    {
        tests::initApplication();
    }

private Q_SLOTS:

    void init()
    {
        mainName = App::GetApplication().getUniqueDocumentName("CompleterMain");
        mainDoc = App::GetApplication().newDocument(mainName.c_str(), mainName.c_str());
        owner = mainDoc->addObject("App::FeatureTest", "Owner");
        auto varSet = mainDoc->addObject("App::VarSet", "VarSet");
        varSet->Label.setValue("Variables");
        addLength(varSet, "Width", 20.0);
        addLength(varSet, "Depth", 30.0);

        otherName = App::GetApplication().getUniqueDocumentName("CompleterOther");
        otherDoc = App::GetApplication().newDocument(otherName.c_str(), otherName.c_str());
        auto otherSet = otherDoc->addObject("App::VarSet", "VarSet");
        otherSet->Label.setValue("OtherVars");
        addLength(otherSet, "Height", 12.0);

        App::GetApplication().setActiveDocument(mainDoc);
        edit = std::make_unique<Gui::ExpressionLineEdit>();
        edit->setDocumentObject(owner);
    }

    void cleanup()
    {
        edit.reset();
        App::GetApplication().closeDocument(otherName.c_str());
        App::GetApplication().closeDocument(mainName.c_str());
    }

    // `Doc#` offers that document's objects, by internal name and by quoted label.
    void documentHashListsItsObjects()
    {
        const QString prefix = QString::fromStdString(otherName) + QLatin1Char('#');
        const QStringList rows = typeAndList(prefix);
        QCOMPARE(
            rows,
            QStringList(
                {prefix + QStringLiteral("VarSet."), prefix + QStringLiteral("<<OtherVars>>.")}
            )
        );
    }

    // `Obj.` offers that object's properties, the VarSet's variables among them.
    void objectDotListsItsProperties()
    {
        const QStringList rows = typeAndList(QStringLiteral("VarSet."));
        QVERIFY2(rows.contains(QStringLiteral("VarSet.Width")), qPrintable(rows.join(u' ')));
        QVERIFY2(rows.contains(QStringLiteral("VarSet.Depth")), qPrintable(rows.join(u' ')));
        QVERIFY2(!rows.contains(QStringLiteral("VarSet.Height")), qPrintable(rows.join(u' ')));
        for (const auto& row : rows) {
            QVERIFY2(row.startsWith(QStringLiteral("VarSet.")), qPrintable(row));
        }
    }

    // `<<Label>>.` reaches the same properties through the object's label.
    void labelDotListsItsProperties()
    {
        const QStringList rows = typeAndList(QStringLiteral("<<Variables>>."));
        QVERIFY2(rows.contains(QStringLiteral("<<Variables>>.Width")), qPrintable(rows.join(u' ')));
    }

    // A plain word is matched fuzzily against every object's user properties.
    void plainWordFindsAVariable()
    {
        const QStringList rows = typeAndList(QStringLiteral("Wid"));
        QVERIFY2(rows.contains(QStringLiteral("VarSet.Width")), qPrintable(rows.join(u' ')));
    }

    // Accepting a `Doc#` row puts the object's path into the text.
    void acceptingADocumentRowInsertsThePath()
    {
        const QString prefix = QString::fromStdString(otherName) + QLatin1Char('#');
        const QString wanted = prefix + QStringLiteral("VarSet.");
        QVERIFY(typeAndList(prefix).contains(wanted));
        edit->slotCompleteTextSelected(wanted);
        QCOMPARE(edit->text(), wanted);
    }

    // G8 (ops#152): `#` at an operand's start offers the current document's variables, and only
    // those: the other document's `Height` isn't one.
    void hashListsTheDocumentsVariables()
    {
        QStringList rows = typeAndList(QStringLiteral("#"));
        rows.sort();
        QCOMPARE(rows, QStringList({QStringLiteral("#Depth"), QStringLiteral("#Width")}));
    }

    // G8: `#Wi` offers `Width`, shown with its value and source.
    void hashPartialNameOffersTheVariable()
    {
        QCOMPARE(typeAndList(QStringLiteral("#Wi")), QStringList({QStringLiteral("#Width")}));
        const QString shown = QStringLiteral("Width  ") + userString(20.0)
            + QStringLiteral("  (Variables)");
        QCOMPARE(shownRows(), QStringList({shown}));
    }

    // G8: accepting the row gives `#Width`, after an operator too.
    void acceptingAVariableInsertsTheHashName()
    {
        QCOMPARE(typeAndList(QStringLiteral("2 * #Wi")), QStringList({QStringLiteral("#Width")}));
        edit->slotCompleteTextSelected(QStringLiteral("#Width"));
        QCOMPARE(edit->text(), QStringLiteral("2 * #Width"));
    }

    // G8: a name held by two VarSets completes to each one's full path, since `#Width` would be
    // an error; each row names its source.
    void ambiguousNameCompletesToFullPaths()
    {
        auto more = mainDoc->addObject("App::VarSet", "VarSet001");
        more->Label.setValue("More");
        addLength(more, "Width", 5.0);

        QCOMPARE(
            typeAndList(QStringLiteral("#Wi")),
            QStringList({QStringLiteral("VarSet.Width"), QStringLiteral("VarSet001.Width")})
        );
        QCOMPARE(
            shownRows(),
            QStringList(
                {QStringLiteral("Width  ") + userString(20.0) + QStringLiteral("  (Variables)"),
                 QStringLiteral("Width  ") + userString(5.0) + QStringLiteral("  (More)")}
            )
        );
        edit->slotCompleteTextSelected(QStringLiteral("VarSet.Width"));
        QCOMPARE(edit->text(), QStringLiteral("VarSet.Width"));
    }

    // A VarSet that depends on the bound object isn't offered: using it would make a cycle.
    void holderDependingOnTheOwnerIsLeftOut()
    {
        auto varSet = mainDoc->getObject("VarSet");
        varSet->setExpression(
            App::ObjectIdentifier::parse(varSet, "Depth"),
            App::ExpressionPtr(App::Expression::parse(varSet, "Owner.Float * 1 mm"))
        );
        edit->setDocumentObject(owner);
        QCOMPARE(typeAndList(QStringLiteral("#")), QStringList());
    }

private:
    static void addLength(App::DocumentObject* obj, const char* name, double value)
    {
        auto prop = obj->addDynamicProperty("App::PropertyLength", name);
        static_cast<App::PropertyLength*>(prop)->setValue(value);
    }

    // A length as the property editor shows it, e.g. "20.00 mm" with the default schema.
    static QString userString(double millimetres)
    {
        return QString::fromStdString(Base::Quantity(millimetres, "mm").getUserString());
    }

    // The text of each row the popup shows, in its order.
    QStringList shownRows() const
    {
        auto model = edit->getCompleter()->completionModel();
        QStringList rows;
        for (int row = 0; row < model->rowCount(); ++row) {
            rows << model->index(row, 0).data(Qt::DisplayRole).toString();
        }
        return rows;
    }

    // Types `text` into the empty line edit key by key, as a user would, and returns the full
    // path of every row the completer then offers, in the popup's order.
    QStringList typeAndList(const QString& text)
    {
        edit->clear();
        QTest::keyClicks(edit.get(), text);
        if (edit->text() != text) {
            return {QStringLiteral("typed text is ") + edit->text()};
        }
        auto completer = edit->getCompleter();
        QStringList rows;
        for (int row = 0; completer->setCurrentRow(row); ++row) {
            rows << completer->currentCompletion();
        }
        return rows;
    }

    std::string mainName;
    std::string otherName;
    App::Document* mainDoc = nullptr;
    App::Document* otherDoc = nullptr;
    App::DocumentObject* owner = nullptr;
    std::unique_ptr<Gui::ExpressionLineEdit> edit;
};

QTEST_MAIN(ExpressionCompleterTest)

#include "ExpressionCompleter.moc"
