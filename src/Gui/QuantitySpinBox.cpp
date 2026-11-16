/***************************************************************************
 *   Copyright (c) 2014 Werner Mayer <wmayer[at]users.sourceforge.net>     *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 51 Franklin Street,      *
 *   Fifth Floor, Boston, MA  02110-1301, USA                              *
 *                                                                         *
 ***************************************************************************/

#include <limits>
#include <QApplication>
#include <QDebug>
#include <QFocusEvent>
#include <QFontMetrics>
#include <QLineEdit>
#include <QRegularExpression>
#include <QRegularExpressionMatch>
#include <QStyle>
#include <QStyleOptionSpinBox>
#include <QPointer>
#include <QTimer>
#include <QToolTip>

#include <sstream>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/ExpressionParser.h>
#include <Base/Exception.h>
#include <Base/UnitsApi.h>
#include <Base/Tools.h>
#include <Base/UnitsSchema.h>

#include "QuantitySpinBox.h"
#include "QuantitySpinBox_p.h"
#include "Application.h"
#include "Command.h"
#include "ExpressionCompleter.h"
#include "Dialogs/DlgExpressionInput.h"
#include "Tools.h"
#include "Widgets.h"


using namespace Gui;
using namespace App;
using namespace Base;

namespace
{

// FreeCAD-CH (ops#640, rank 55): the model role of ExpressionCompleter.cpp's "New variable..." row
constexpr int newVariableRole = Qt::UserRole + 0x4E56;

/// Whether @a text has a '#' that the parser resolves as a variable, as App's rewriteVariableRefs
/// finds them: one followed by an identifier start, outside a `<<...>>` string and not after a
/// word. `#Width` has one; `Doc#Box.Length`, `#1` and `<<a #b>>` don't (as VariablesView.cpp).
bool hasVariableRef(const QString& text)
{
    auto isPart = [](QChar c) {
        return c == u'_' || c == u'@' || c.isLetterOrNumber() || c.isMark();
    };
    bool afterWord = false;
    for (qsizetype i = 0; i < text.size(); ++i) {
        QChar c = text[i];
        if (c == u' ' || c == u'\t' || c == u'\n' || c == u'\r') {
            continue;
        }
        if (c == u'<' && i + 1 < text.size() && text[i + 1] == u'<') {
            qsizetype end = text.indexOf(QStringLiteral(">>"), i + 2);
            afterWord = end >= 0;
            i = end < 0 ? i + 1 : end + 1;
            continue;
        }
        if (c == u'#' && !afterWord && i + 1 < text.size()
            && (text[i + 1] == u'_' || text[i + 1].isLetter())) {
            return true;
        }
        afterWord = isPart(c);
    }
    return false;
}

/// Whether @a text ends with a '#' that starts a variable's name being typed: not after a word
/// (`#` alone, or `2 * #`). The validator takes it as Intermediate, else the key that begins
/// `#Width` was refused and the name went into the number
bool endsWithVariableStart(const QString& text)
{
    if (!text.endsWith(u'#')) {
        return false;
    }
    qsizetype i = text.size() - 2;
    while (i >= 0 && (text[i] == u' ' || text[i] == u'\t')) {
        --i;
    }
    if (i < 0) {
        return true;
    }
    const QChar c = text[i];
    return !(c == u'_' || c == u'@' || c.isLetterOrNumber() || c.isMark());
}

/// "New variable..." from a field: the Variables panel's Add dialog with the typed name and the
/// field's value, after the event that asked for it (Std_AddVariable, VariablesView.cpp, reads
/// them from this application property).
void requestNewVariable(const QString& name, const QString& value)
{
    QTimer::singleShot(0, [name, value] {
        qApp->setProperty("FreeCADCH_NewVariable", QStringList {name, value});
        Gui::Application::Instance->commandManager().runCommandByName("Std_AddVariable");
        qApp->setProperty("FreeCADCH_NewVariable", QVariant());
    });
}

}  // namespace

namespace Gui
{

class QuantitySpinBoxPrivate
{
public:
    QuantitySpinBoxPrivate(QuantitySpinBox* q)
        : validInput(true)
        , pendingEmit(false)
        , normalize(true)
        , checkRangeInExpression(false)
        , adjustableWidth(false)
        , maxExpectedDigits(4)
        , addIconSpace(false)
        , unitValue(0)
        , maximum(std::numeric_limits<double>::max())
        , minimum(-std::numeric_limits<double>::max())
        , singleStep(1.0)
        , q_ptr(q)
    {}
    ~QuantitySpinBoxPrivate() = default;

    QString stripped(const QString& t, int* pos) const
    {
        QString text = t;
        const int s = text.size();
        text = text.trimmed();
        if (pos) {
            (*pos) -= (s - text.size());
        }
        return text;
    }

    bool validate(QString& input, Base::Quantity& result, const App::ObjectIdentifier& path) const
    {
        Q_Q(const QuantitySpinBox);

        // Do not accept empty strings because the parser will consider
        // " unit" as "1 unit" which is not the desired behaviour (see #0004104)
        if (input.isEmpty()) {
            return false;
        }

        bool success = false;
        QString tmp = input;

        auto validateInput = [&](QString& tmp) -> QValidator::State {
            QValidator::State state;
            Base::Quantity res = validateAndInterpret(tmp, state, path);
            res.setFormat(quantity.getFormat());
            if (state == QValidator::Acceptable) {
                success = true;
                result = res;
                input = tmp;
            }
            return state;
        };

        QValidator::State state = validateInput(tmp);
        if (state == QValidator::Intermediate && q->hasExpression()) {
            // Accept the expression as it is but try to add the right unit string
            success = true;

            Base::Quantity quantity;
            double value;
            if (parseString(input, quantity, value, path)) {
                quantity.setUnit(unit);
                result = quantity;

                // Now translate the quantity into its string representation using the user-defined
                // unit system
                input = QString::fromStdString(Base::UnitsApi::schemaTranslate(result));
            }
        }

        return success;
    }
    bool parseString(
        const QString& str,
        Base::Quantity& result,
        double& value,
        const App::ObjectIdentifier& path
    ) const
    {
        App::ObjectIdentifier pathtmp = path;
        try {
            QString copy = str;
            copy.remove(locale.groupSeparator());

            // Expression parser
            std::shared_ptr<Expression> expr(
                ExpressionParser::parse(path.getDocumentObject(), copy.toUtf8().constData())
            );
            if (expr) {

                std::unique_ptr<Expression> res(expr->eval());
                NumberExpression* n = freecad_cast<NumberExpression*>(res.get());
                if (n) {
                    result = n->getQuantity();
                    value = result.getValue();
                    return true;
                }
            }
        }
        catch (Base::Exception&) {
            return false;
        }
        return false;
    }
    Base::Quantity validateAndInterpret(
        QString& input,
        QValidator::State& state,
        const App::ObjectIdentifier& path
    ) const
    {
        Base::Quantity res;
        const double max = this->maximum;
        const double min = this->minimum;

        QString copy = input;
        double value = min;
        bool ok = false;

        QChar plus = QLatin1Char('+'), minus = QLatin1Char('-');

        if (locale.negativeSign() != minus) {
            copy.replace(locale.negativeSign(), minus);
        }
        if (locale.positiveSign() != plus) {
            copy.replace(locale.positiveSign(), plus);
        }

        QString reverseUnitStr = unitStr;
        std::reverse(reverseUnitStr.begin(), reverseUnitStr.end());

        // Prep for expression parser
        // This regex matches chunks between +,-,$,^ accounting for matching parenthesis.
        QRegularExpression chunkRe(
            QStringLiteral("(?<=^|[\\+\\-])((\\((?>[^()]|(?2))*\\))|[^\\+\\-\n])*(?=$|[\\+\\-])")
        );
        QRegularExpressionMatchIterator expressionChunk = chunkRe.globalMatch(copy);
        unsigned int lengthOffset = 0;
        while (expressionChunk.hasNext()) {
            QRegularExpressionMatch matchChunk = expressionChunk.next();
            QString origionalChunk = matchChunk.captured(0);
            QString copyChunk = origionalChunk;
            std::reverse(copyChunk.begin(), copyChunk.end());

            // Reused regex patterns
            static const std::string regexUnits
                = "sAV|VC|lim|nim|im|hpm|[mf]?bl|°|ged|dar|nog|″|′|rroT[uµm]?|K[uµm]?|A[mkM]?|F["
                  "pnuµm]?|C|S[uµmkM]?|zH[kMGT]?|H[nuµm]?|mhO[kM]?|J[mk]?|Ve[kM]?|V[mk]?|hWk|sW|"
                  "lack?|N[mkM]?|g[uµmk]?|lm?|(?<=\\b|[^a-zA-Z])m[nuµmcdk]?|uoht|ni|\"|'|dy|dc|bW|"
                  "T|t|zo|ts|twc|Wk?|aP[kMG]?|is[pk]|h|G|M|tfc|tfqs|tf|s";
            static const std::string regexUnitlessFunctions
                = "soca|nisa|2nata|nata|hsoc|hnis|hnat|soc|nat|nis|pxe|gol|01gol";
            static const std::string regexConstants = "e|ip|lomm|lom";
            static const std::string regexNumber = "\\d+\\s*\\.?\\s*\\d*|\\.\\s*\\d+";

            // If expression does not contain /*() or ^, this regex will not find anything
            if (copy.contains(QLatin1Char('/')) || copy.contains(QLatin1Char('*'))
                || copy.contains(QLatin1Char('(')) || copy.contains(QLatin1Char(')'))
                || copy.contains(QLatin1Char('^'))) {
                // Find units and replace 1/2mm -> 1/2*(1mm), 1^2mm -> 1^2*(1mm)
                QRegularExpression fixUnits(
                    QString::fromStdString(
                        "(" + regexUnits + ")(\\s*\\)|(?:\\*|(?:\\)(?:(?:\\s*(?:" + regexConstants
                        + "|\\)(?:[^()]|(?R))*\\((?:" + regexUnitlessFunctions + ")|" + regexNumber
                        + "))|(?R))*\\(|(?:\\s*(?:" + regexConstants
                        + "|\\)(?:[^()]|(?R))*\\((?:" + regexUnitlessFunctions + ")|" + regexNumber
                        + "))))+(?:[\\/\\^]|(.*$))(?!(" + regexUnits + ")))"
                    )
                );
                QRegularExpressionMatch fixUnitsMatch = fixUnits.match(copyChunk);

                // 3rd capture group being filled indicates regex bailed out; no match.
                if (fixUnitsMatch.lastCapturedIndex() == 2
                    || (fixUnitsMatch.lastCapturedIndex() == 3
                        && fixUnitsMatch.captured(3).isEmpty())) {
                    QString matchUnits = fixUnitsMatch.captured(1);
                    QString matchNumbers = fixUnitsMatch.captured(2);
                    copyChunk.replace(
                        matchUnits + matchNumbers,
                        QStringLiteral(")") + matchUnits + QStringLiteral("1(*") + matchNumbers
                    );
                }
            }

            // Add default units to string if none are present
            if (!copyChunk.contains(reverseUnitStr)) {  // Fast check
                QRegularExpression unitsRe(
                    QString::fromStdString(
                        "(?<=\\b|[^a-zA-Z])(" + regexUnits
                        + ")(?=\\b|[^a-zA-Z])|°|″|′|\"|'|\\p{L}\\.\\p{L}|\\[\\p{L}"
                    )
                );

                QRegularExpressionMatch match = unitsRe.match(copyChunk);
                if (!match.hasMatch() && !copyChunk.isEmpty()) {  // If no units are found, use
                                                                  // default units
                    copyChunk.prepend(
                        QStringLiteral(")") + reverseUnitStr + QStringLiteral("1(*")
                    );  // Add units to the end of chunk *(1unit)
                }
            }

            std::reverse(copyChunk.begin(), copyChunk.end());

            copy.replace(
                matchChunk.capturedStart() + lengthOffset,
                matchChunk.capturedEnd() - matchChunk.capturedStart(),
                copyChunk
            );
            lengthOffset += copyChunk.length() - origionalChunk.length();
        }

        ok = parseString(copy, res, value, path);

        // If result does not have unit: add default unit
        if (res.isDimensionless()) {
            res.setUnit(unit);
        }

        if (!ok) {
            // input may not be finished
            state = QValidator::Intermediate;
        }
        else if (value >= min && value <= max) {
            state = QValidator::Acceptable;
        }
        else if (max == min) {  // when max and min is the same the only non-Invalid input is max
                                // (or min)
            state = QValidator::Invalid;
        }
        else {
            if ((value >= 0 && value > max) || (value < 0 && value < min)) {
                state = QValidator::Invalid;
            }
            else {
                state = QValidator::Intermediate;
            }
        }
        if (state != QValidator::Acceptable) {
            res.setValue(max > 0 ? min : max);
        }

        return res;
    }

    QLocale locale;
    bool validInput;
    bool pendingEmit;
    bool normalize;
    bool checkRangeInExpression;
    bool adjustableWidth;
    int maxExpectedDigits;
    bool addIconSpace;
    QString validStr;
    Base::Quantity quantity;
    Base::Quantity cached;
    Base::Unit unit;
    double unitValue;
    QString unitStr;
    double maximum;
    double minimum;
    double singleStep;
    QuantitySpinBox* q_ptr;
    std::unique_ptr<Base::UnitsSchema> scheme;

    // FreeCAD-CH (ops#640, V23): text typed into a bound field that uses a variable (`#w`,
    // `#w * 2`) is bound as the field's expression when the edit ends (Enter, Tab, focus out),
    // as Onshape does: before, it was evaluated and today's value stored (or `#w * 1 mm`). A
    // `#name` that doesn't resolve keeps the field red and is never committed; the field's
    // `unresolvedVariable` property says so (for the dialog's check). Rank 55: `#` offers the
    // document's variables and, for a new name, "New variable...".
    QString variableText;   // the text typed, while it uses a variable
    QString variableError;  // why it can't be bound; empty if it can
    QPointer<ExpressionCompleter> completer;

    /// Checks @a text as the field's expression; @a result is its value. Sets variableText/Error.
    bool checkVariableText(const QString& text, const App::ObjectIdentifier& path, Base::Quantity& result)
    {
        variableText = text;
        variableError.clear();
        App::DocumentObject* owner = path.getDocumentObject();
        if (!owner) {
            variableError = QuantitySpinBox::tr("The field is not bound to a property.");
            return false;
        }
        try {
            std::shared_ptr<Expression> expr(ExpressionParser::parse(owner, text.toUtf8().constData()));
            const std::string error = owner->ExpressionEngine.validateExpression(path, expr);
            if (!error.empty()) {
                variableError = QString::fromStdString(error);
                return false;
            }
            std::unique_ptr<Expression> value(expr->eval());
            auto number = freecad_cast<NumberExpression*>(value.get());
            if (!number) {
                variableError = QuantitySpinBox::tr("The expression doesn't give a number.");
                return false;
            }
            Base::Quantity quantity = number->getQuantity();
            if (quantity.isDimensionless()) {
                quantity.setUnit(unit);
            }
            else if (quantity.getUnit() != unit) {
                variableError = QuantitySpinBox::tr("The expression's unit doesn't fit this field.");
                return false;
            }
            if (checkRangeInExpression
                && (quantity.getValue() < minimum || quantity.getValue() > maximum)) {
                variableError = QuantitySpinBox::tr("The value is out of range.");
                return false;
            }
            quantity.setFormat(this->quantity.getFormat());
            result = quantity;
            return true;
        }
        catch (const Base::Exception& e) {
            variableError = QString::fromUtf8(e.what());
        }
        catch (const std::exception& e) {
            variableError = QString::fromUtf8(e.what());
        }
        return false;
    }

    /// The field red with the reason as its tip while the variable text can't be bound.
    void showVariableState()
    {
        Q_Q(QuantitySpinBox);
        QLineEdit* edit = q->lineEdit();
        QPalette p(edit->palette());
        p.setColor(
            QPalette::Active,
            QPalette::Text,
            variableError.isEmpty() ? q->defaultPalette.color(QPalette::Text) : QColor(Qt::red)
        );
        edit->setPalette(p);
        edit->setToolTip(variableError);
        q->setProperty("unresolvedVariable", !variableText.isEmpty() && !variableError.isEmpty());
    }

    void clearVariableState()
    {
        if (variableText.isEmpty()) {
            return;
        }
        variableText.clear();
        variableError.clear();
        showVariableState();
    }

    /// Binds the field to its variable text; false if there is none or it doesn't resolve.
    bool commitVariableText()
    {
        Q_Q(QuantitySpinBox);
        if (variableText.isEmpty() || !variableError.isEmpty() || !q->isBound()) {
            return false;
        }
        std::shared_ptr<Expression> expr;
        try {
            expr = ExpressionParser::parse(
                q->getPath().getDocumentObject(),
                variableText.toUtf8().constData()
            );
        }
        catch (const Base::Exception& e) {
            variableError = QString::fromUtf8(e.what());
            showVariableState();
            return false;
        }
        if (completer && completer->popup()) {
            completer->popup()->hide();
        }
        clearVariableState();
        // As the f(x) dialog's OK: an open dialog's transaction takes it
        q->setExpression(expr);
        q->updateExpression();
        return true;
    }

    /// `#` completion in the field: the variables, and "New variable..." for a new name.
    void updateVariableCompleter(const QString& text)
    {
        Q_Q(QuantitySpinBox);
        if (!q->isBound() || q->hasExpression() || !text.contains(u'#')) {
            if (completer && completer->popup()) {
                completer->popup()->hide();
            }
            return;
        }
        QLineEdit* edit = q->lineEdit();
        if (!completer) {
            completer = new ExpressionCompleter(q->getPath().getDocumentObject(), q);
            completer->setWidget(edit);
            completer->setCaseSensitivity(Qt::CaseInsensitive);
            completer->setFilterMode(Qt::MatchContains);
            QObject::connect(
                completer,
                qOverload<const QModelIndex&>(&QCompleter::activated),
                q,
                [this](const QModelIndex& index) { completeVariable(index); }
            );
        }
        completer->slotUpdate(text, edit->cursorPosition());
        int start = 0;
        int end = 0;
        completer->getPrefixRange(start, end);
        // Only a `#` operand is completed here: a plain value gets no object list.
        if (!text.mid(start, end - start).startsWith(u'#') && completer->popup()) {
            completer->popup()->hide();
        }
    }

    void completeVariable(const QModelIndex& index)
    {
        Q_Q(QuantitySpinBox);
        if (!completer) {
            return;
        }
        QLineEdit* edit = q->lineEdit();
        int start = 0;
        int end = 0;
        completer->getPrefixRange(start, end);
        const QString text = edit->text();
        if (index.data(newVariableRole).toBool()) {
            QString value;
            if (!quantity.isDimensionless() || quantity.getValue() != 0.0) {
                value = QString::fromStdString(quantity.getUserString());
            }
            requestNewVariable(text.mid(start + 1, end - start - 1), value);
            return;
        }
        const QString before = text.left(start) + index.data(Qt::EditRole).toString();
        edit->setText(before + text.mid(end));
        edit->setCursorPosition(before.length());
        completer->updatePrefixEnd(before.length());
    }

    Q_DECLARE_PUBLIC(QuantitySpinBox)
};
}  // namespace Gui

QuantitySpinBox::QuantitySpinBox(QWidget* parent)
    : QAbstractSpinBox(parent)
    , ExpressionSpinBox(this)
    , d_ptr(new QuantitySpinBoxPrivate(this))
{
    d_ptr->locale = locale();
    this->setContextMenuPolicy(Qt::DefaultContextMenu);
    connect(lineEdit(), &QLineEdit::textChanged, this, &QuantitySpinBox::userInput);
    connect(this, &QuantitySpinBox::editingFinished, this, [&] { this->handlePendingEmit(true); });
    // FreeCAD-CH (ops#640, rank 55): `#` completion, on what the user types only
    connect(lineEdit(), &QLineEdit::textEdited, this, [this](const QString& text) {
        Q_D(QuantitySpinBox);
        d->updateVariableCompleter(text);
    });
}

QuantitySpinBox::~QuantitySpinBox() = default;

void QuantitySpinBox::bind(const App::ObjectIdentifier& _path)
{
    ExpressionSpinBox::bind(_path);
}

void QuantitySpinBox::showIcon()
{
    addIconSpace(true);

    adjustSize();
    iconLabel->show();
}

QString QuantitySpinBox::boundToName() const
{
    if (isBound()) {
        std::string path = getPath().toString();
        return QString::fromStdString(path);
    }
    return {};
}

/**
 * @brief Create an object identifier by name.
 *
 * An identifier is written as document#documentobject.property.subproperty1...subpropertyN
 * document# may be dropped, in this case the active document is used.
 */
void QuantitySpinBox::setBoundToByName(const QString& name)
{
    try {
        // get document
        App::Document* doc = App::GetApplication().getActiveDocument();
        QStringList list = name.split(QLatin1Char('#'));
        if (list.size() > 1) {
            doc = App::GetApplication().getDocument(list.front().toLatin1());
            list.pop_front();
        }

        if (!doc) {
            qDebug() << "No such document";
            return;
        }

        // first element is assumed to be the document name
        list = list.front().split(QLatin1Char('.'));

        // get object
        App::DocumentObject* obj = doc->getObject(list.front().toLatin1());
        if (!obj) {
            qDebug() << "No object " << list.front() << " in document";
            return;
        }
        list.pop_front();

        // the rest of the list defines the property and eventually subproperties
        App::ObjectIdentifier path(obj);
        path.setDocumentName(std::string(doc->getName()), true);
        path.setDocumentObjectName(std::string(obj->getNameInDocument()), true);

        for (const auto& it : list) {
            path << App::ObjectIdentifier::Component::SimpleComponent(it.toLatin1().constData());
        }

        if (path.getProperty()) {
            bind(path);
        }
    }
    catch (const Base::Exception& e) {
        qDebug() << e.what();
    }
}

QString Gui::QuantitySpinBox::expressionText() const
{
    try {
        if (hasExpression()) {
            return QString::fromStdString(getExpressionString());
        }
    }
    catch (const Base::Exception& e) {
        qDebug() << e.what();
    }
    return {};
}

void QuantitySpinBox::evaluateExpression()
{
    if (isBound() && getExpression()) {
        showValidExpression(Number::SetIfNumber);
    }
}

void Gui::QuantitySpinBox::setNumberExpression(App::NumberExpression* expr)
{
    Q_D(const QuantitySpinBox);
    // A result without a unit (e.g. a Sheet cell without one) is in the field's unit, as the
    // property takes it; shown bare, "24.00" stayed until the panel was reopened (ops#157)
    Base::Quantity quantity = expr->getQuantity();
    if (quantity.isDimensionless()) {
        quantity.setUnit(d->unit);
    }
    updateEdit(getUserString(quantity));
    handlePendingEmit();
}

bool QuantitySpinBox::apply(const std::string& propName)
{
    if (!ExpressionBinding::apply(propName)) {
        double dValue = value().getValue();
        return assignToProperty(propName, dValue);
    }

    return false;
}

void QuantitySpinBox::resizeEvent(QResizeEvent* event)
{
    QAbstractSpinBox::resizeEvent(event);
    resizeWidget();
}

void Gui::QuantitySpinBox::keyPressEvent(QKeyEvent* event)
{
    Q_D(QuantitySpinBox);

    const auto isEnter = event->key() == Qt::Key_Enter || event->key() == Qt::Key_Return;

    // FreeCAD-CH (ops#640, V23): Enter binds a variable text; an unresolved one stays red and
    // Enter goes no further than the field
    if (isEnter && !d->variableText.isEmpty()) {
        if (!d->commitVariableText()) {
            event->accept();
            return;
        }
        QAbstractSpinBox::keyPressEvent(event);
        returnPressed();
        return;
    }

    if (d->normalize && isEnter && !isNormalized()) {
        // ensure that input is up to date
        handlePendingEmit();

        normalize();
        return;
    }

    if (!handleKeyEvent(event->text())) {
        QAbstractSpinBox::keyPressEvent(event);
    }

    if (isEnter) {
        returnPressed();
    }
}

void Gui::QuantitySpinBox::paintEvent(QPaintEvent*)
{
    QStyleOptionSpinBox opt;
    initStyleOption(&opt);
    drawControl(opt);
}

void QuantitySpinBox::updateText(const Quantity& quant)
{
    Q_D(QuantitySpinBox);

    double dFactor;
    QString txt = getUserString(quant, dFactor, d->unitStr);
    d->unitValue = quant.getValue() / dFactor;
    updateEdit(txt);
    handlePendingEmit();
}

void QuantitySpinBox::updateEdit(const QString& text)
{
    Q_D(QuantitySpinBox);
    QLineEdit* edit = lineEdit();

    int cursor = edit->cursorPosition();
    int selStart = edit->selectionStart();
    int selLen = edit->selectionLength();

    // setText resets cursor/selection so save it and restore it
    edit->setText(text);

    int maxPos = qMax(0, edit->displayText().size() - d->unitStr.size());

    int newCursor = qBound(0, cursor, maxPos);

    if (selLen > 0) {
        int newStart = qBound(0, selStart, maxPos);
        int newLen = qBound(0, selLen, maxPos - newStart);
        edit->setSelection(newStart, newLen);
    }
    else {
        edit->setCursorPosition(newCursor);
    }
}

void QuantitySpinBox::validateInput()
{
    Q_D(QuantitySpinBox);

    QValidator::State state;
    QString text = lineEdit()->text();
    const App::ObjectIdentifier& path = getPath();
    d->validateAndInterpret(text, state, path);
    if (state != QValidator::Acceptable) {
        updateEdit(d->validStr);
    }

    handlePendingEmit();
}

Base::Quantity QuantitySpinBox::value() const
{
    Q_D(const QuantitySpinBox);
    return d->quantity;
}

double QuantitySpinBox::rawValue() const
{
    Q_D(const QuantitySpinBox);
    return d->quantity.getValue();
}

void QuantitySpinBox::normalize()
{
    // this does not really change the value, only the representation
    QSignalBlocker blocker(this);

    Q_D(const QuantitySpinBox);
    return setValue(d->quantity);
}

bool QuantitySpinBox::isNormalized()
{
    Q_D(const QuantitySpinBox);

    // check if the input is exactly the same as the normalized string
    if (d->validStr.toStdString() == d->quantity.getUserString()) {
        return true;
    }

    // check if the input is simplified to a solution or if further calculation
    // has to be done

    try {
        auto expr = ExpressionParser::parse(
            getPath().getDocumentObject(),
            d->validStr.toUtf8().constData()
        );

        // plain numbers
        if (freecad_cast<NumberExpression*>(expr.get())) {
            return true;
        }

        auto operatorExpr = freecad_cast<OperatorExpression*>(expr.get());
        if (!operatorExpr) {
            return false;
        }

        if (operatorExpr->getOperator() == OperatorExpression::UNIT
            && freecad_cast<UnitExpression*>(operatorExpr->getRight())
            && freecad_cast<NumberExpression*>(operatorExpr->getLeft())) {
            // numbers without sign but with unit
            return true;
        }

        if ((operatorExpr->getOperator() != OperatorExpression::NEG
             && operatorExpr->getOperator() != OperatorExpression::POS)) {
            return false;
        }

        // numbers with positive or negative sign without unit
        if (freecad_cast<NumberExpression*>(operatorExpr->getLeft())) {
            return true;
        }

        auto innerOperatorExpr = freecad_cast<OperatorExpression*>(operatorExpr->getLeft());
        if (!innerOperatorExpr) {
            return false;
        }

        if (innerOperatorExpr->getOperator() != OperatorExpression::UNIT) {
            return false;
        }
        if (!freecad_cast<UnitExpression*>(innerOperatorExpr->getRight())) {
            return false;
        }

        // numbers with positive or negative sign and unit
        auto left = innerOperatorExpr->getLeft();
        if (freecad_cast<NumberExpression*>(left)) {
            return true;
        }
        auto leftOp = freecad_cast<OperatorExpression*>(left);
        if (leftOp
            && (leftOp->getOperator() == OperatorExpression::NEG
                || leftOp->getOperator() == OperatorExpression::POS)
            && freecad_cast<NumberExpression*>(leftOp->getLeft())) {
            return true;
        }
    }
    catch (const Base::Exception&) {
        // The exception is intentionally ignored here and should be handled,
        // when the value is assigned
        return false;
    }
    return false;
}

void QuantitySpinBox::setValue(const Base::Quantity& value)
{
    Q_D(QuantitySpinBox);
    d->quantity = value;
    // check limits
    if (d->quantity.getValue() > d->maximum) {
        d->quantity.setValue(d->maximum);
    }
    if (d->quantity.getValue() < d->minimum) {
        d->quantity.setValue(d->minimum);
    }

    d->unit = value.getUnit();

    updateText(value);
}

void QuantitySpinBox::setValue(double value)
{
    Q_D(QuantitySpinBox);

    Base::QuantityFormat currentformat = d->quantity.getFormat();
    auto quantity = Base::Quantity(value, d->unit);
    quantity.setFormat(currentformat);

    setValue(quantity);
}

bool QuantitySpinBox::autoNormalize() const
{
    Q_D(const QuantitySpinBox);
    return d->normalize;
}

void QuantitySpinBox::setAutoNormalize(bool normalize)
{
    Q_D(QuantitySpinBox);
    d->normalize = normalize;
}

bool QuantitySpinBox::autoAdjustWidth() const
{
    Q_D(const QuantitySpinBox);
    return d->adjustableWidth;
}

void QuantitySpinBox::setAutoAdjustWidth(bool adjust)
{
    Q_D(QuantitySpinBox);
    d->adjustableWidth = adjust;
}

bool QuantitySpinBox::isIconSpaceAdded() const
{
    Q_D(const QuantitySpinBox);
    return d->addIconSpace;
}

void QuantitySpinBox::addIconSpace(bool addIconSpace)
{
    Q_D(QuantitySpinBox);
    d->addIconSpace = addIconSpace;
}

int QuantitySpinBox::getMaxExpectedDigits()
{
    Q_D(const QuantitySpinBox);
    return d->maxExpectedDigits;
}

void QuantitySpinBox::setMaxExpectedDigits(int digits)
{
    Q_D(QuantitySpinBox);
    d->maxExpectedDigits = digits;
}

bool QuantitySpinBox::hasValidInput() const
{
    Q_D(const QuantitySpinBox);
    return d->validInput;
}

// Gets called after call of 'validateAndInterpret'
void QuantitySpinBox::userInput(const QString& text)
{
    Q_D(QuantitySpinBox);
    d->pendingEmit = true;

    // FreeCAD-CH (ops#640, V23): a text using a variable is the field's expression to be; its
    // value previews as any value does
    if (isBound() && !hasExpression() && hasVariableRef(text)) {
        Base::Quantity res;
        d->validInput = d->checkVariableText(text, getPath(), res);
        d->showVariableState();
        if (d->validInput) {
            d->cached = res;
            if (keyboardTracking()) {
                handlePendingEmit(false);
            }
        }
        return;
    }
    d->clearVariableState();

    QString tmp = text;
    Base::Quantity res;
    const App::ObjectIdentifier& path = getPath();
    if (d->validate(tmp, res, path)) {
        d->validStr = tmp;
        d->validInput = true;
    }
    else {
        d->validInput = false;

        // only emit signal to reset EditableDatumLabel if the input is truly empty or has
        // no meaningful number don't emit for partially typed numbers like "71." which are
        // temporarily invalid
        const QString trimmedText = text.trimmed();
        static const QRegularExpression partialNumberRegex(QStringLiteral(R"([+-]?(\d+)?(\.,\d*)?)"));
        if (trimmedText.isEmpty() || !trimmedText.contains(partialNumberRegex)) {
            // we have to emit here signal explicitly as validator will not pass
            // this value further but we want to check it to disable isSet flag if
            // it has been set previously
            Q_EMIT valueChanged(d->quantity.getValue());
        }
        return;
    }

    if (keyboardTracking()) {
        d->cached = res;
        handlePendingEmit(false);
    }
    else {
        d->cached = res;
    }
}

void QuantitySpinBox::openFormulaDialog()
{
    Q_ASSERT(isBound());

    Q_D(const QuantitySpinBox);
    auto box = new Gui::Dialog::DlgExpressionInput(getPath(), getExpression(), d->unit, this);
    if (d->checkRangeInExpression) {
        box->setRange(d->minimum, d->maximum);
    }
    QObject::connect(box, &Gui::Dialog::DlgExpressionInput::finished, [this, box]() {
        if (box->result() == QDialog::Accepted) {
            setExpression(box->getExpression());
        }
        else if (box->discardedFormula()) {
            setExpression(std::shared_ptr<Expression>());
        }

        updateExpression();
        box->deleteLater();
        Q_EMIT showFormulaDialog(false);
    });
    box->show();

    QPoint pos = mapToGlobal(QPoint(0, 0));
    box->move(pos - box->expressionPosition());
    Gui::adjustDialogPosition(box);

    Q_EMIT showFormulaDialog(true);
}

void QuantitySpinBox::handlePendingEmit(bool updateUnit /* = true */)
{
    updateFromCache(true, updateUnit);
}

void QuantitySpinBox::updateFromCache(bool notify, bool updateUnit /* = true */)
{
    Q_D(QuantitySpinBox);
    if (d->pendingEmit) {
        double factor;
        const Base::Quantity& res = d->cached;
        auto tmpUnit(d->unitStr);
        QString text = getUserString(res, factor, updateUnit ? d->unitStr : tmpUnit);
        d->unitValue = res.getValue() / factor;
        d->quantity = res;

        // signaling
        if (notify) {
            d->pendingEmit = false;
            Q_EMIT valueChanged(res);
            Q_EMIT valueChanged(res.getValue());
            Q_EMIT textChanged(text);
        }
    }
}

Base::Unit QuantitySpinBox::unit() const
{
    Q_D(const QuantitySpinBox);
    return d->unit;
}

void QuantitySpinBox::setUnit(const Base::Unit& unit)
{
    Q_D(QuantitySpinBox);

    d->unit = unit;
    d->quantity.setUnit(unit);
    updateText(d->quantity);
}

void QuantitySpinBox::setUnitText(const QString& str)
{
    try {
        Base::Quantity quant = Base::Quantity::parse(str.toStdString());
        setUnit(quant.getUnit());
    }
    catch (const Base::ParserError&) {
    }
}

QString QuantitySpinBox::unitText()
{
    Q_D(QuantitySpinBox);
    return d->unitStr;
}

double QuantitySpinBox::singleStep() const
{
    Q_D(const QuantitySpinBox);
    return d->singleStep;
}

void QuantitySpinBox::setSingleStep(double value)
{
    Q_D(QuantitySpinBox);

    if (value >= 0) {
        d->singleStep = value;
    }
}

double QuantitySpinBox::minimum() const
{
    Q_D(const QuantitySpinBox);
    return d->minimum;
}

void QuantitySpinBox::setMinimum(double minimum)
{
    Q_D(QuantitySpinBox);
    d->minimum = minimum;
}

double QuantitySpinBox::maximum() const
{
    Q_D(const QuantitySpinBox);
    return d->maximum;
}

void QuantitySpinBox::setMaximum(double maximum)
{
    Q_D(QuantitySpinBox);
    d->maximum = maximum;
}

void QuantitySpinBox::setRange(double minimum, double maximum)
{
    Q_D(QuantitySpinBox);
    d->minimum = minimum;
    d->maximum = maximum;
}

void QuantitySpinBox::checkRangeInExpression(bool on)
{
    Q_D(QuantitySpinBox);
    d->checkRangeInExpression = on;
}

bool QuantitySpinBox::isCheckedRangeInExpresion() const
{
    Q_D(const QuantitySpinBox);
    return d->checkRangeInExpression;
}


int QuantitySpinBox::decimals() const
{
    Q_D(const QuantitySpinBox);
    return d->quantity.getFormat().getPrecision();
}

void QuantitySpinBox::setDecimals(int v)
{
    Q_D(QuantitySpinBox);
    Base::QuantityFormat f = d->quantity.getFormat();
    f.setPrecision(v);
    d->quantity.setFormat(f);
    updateText(d->quantity);
}

void QuantitySpinBox::setSchema(const int s)
{
    Q_D(QuantitySpinBox);
    d->scheme = Base::UnitsApi::createSchema(s);
    updateText(d->quantity);
}

void QuantitySpinBox::clearSchema()
{
    Q_D(QuantitySpinBox);
    d->scheme = nullptr;
    updateText(d->quantity);
}

QString QuantitySpinBox::getUserString(const Base::Quantity& val, double& factor, QString& unitString) const
{
    Q_D(const QuantitySpinBox);
    std::string unitStr;
    const std::string str = d->scheme ? val.getUserString(d->scheme.get(), factor, unitStr)
                                      : val.getUserString(factor, unitStr);
    unitString = QString::fromStdString(unitStr);
    return QString::fromStdString(str);
}

QString QuantitySpinBox::getUserString(const Base::Quantity& val) const
{
    Q_D(const QuantitySpinBox);
    std::string str;
    if (d->scheme) {
        double factor;
        std::string unitString;
        str = val.getUserString(d->scheme.get(), factor, unitString);
    }
    else {
        str = val.getUserString();
    }
    return QString::fromStdString(str);
}

void QuantitySpinBox::setExpression(std::shared_ptr<Expression> expr)
{
    ExpressionSpinBox::setExpression(expr);
}

QAbstractSpinBox::StepEnabled QuantitySpinBox::stepEnabled() const
{
    Q_D(const QuantitySpinBox);
    if (isReadOnly() /* || !d->validInput*/) {
        return StepNone;
    }
    if (wrapping()) {
        return StepEnabled(StepUpEnabled | StepDownEnabled);
    }
    StepEnabled ret = StepNone;
    if (d->quantity.getValue() < d->maximum) {
        ret |= StepUpEnabled;
    }
    if (d->quantity.getValue() > d->minimum) {
        ret |= StepDownEnabled;
    }
    return ret;
}

void QuantitySpinBox::stepBy(int steps)
{
    Q_D(QuantitySpinBox);
    updateFromCache(false);

    double step = d->singleStep * steps;
    double val = d->unitValue + step;
    if (val > d->maximum) {
        val = d->maximum;
    }
    else if (val < d->minimum) {
        val = d->minimum;
    }

    Quantity quant(val, d->unitStr.toStdString());
    quant.setFormat(d->quantity.getFormat());
    updateText(quant);
    updateFromCache(true);
    update();
    selectNumber();
}

QSize QuantitySpinBox::sizeForText(const QString& txt) const
{
    const QFontMetrics fm(fontMetrics());
    int h = lineEdit()->sizeHint().height();
    int w = QtTools::horizontalAdvance(fm, txt);

    w += 2;  // cursor blinking space
    w += iconHeight;

    QStyleOptionSpinBox opt;
    initStyleOption(&opt);
    QSize hint(w, h);
    QSize size = style()->sizeFromContents(QStyle::CT_SpinBox, &opt, hint, this);
    return size;
}

QSize QuantitySpinBox::sizeHint() const
{
    Q_D(const QuantitySpinBox);
    auto le = lineEdit();
    if (le && d->adjustableWidth) {
        // limit number of typed characters to keep unit visible
        le->setMaxLength(getMaxStrLength(d->maxExpectedDigits));
    }
    return sizeHintForDigits(d->maxExpectedDigits);
}

QSize QuantitySpinBox::sizeHintForDigits(int digits) const
{
    Q_D(const QuantitySpinBox);
    ensurePolished();

    const int maxLen = getMaxStrLength(digits);
    int length = maxLen;

    if (d->adjustableWidth) {
        int currenLen = qMax(lineEdit()->text().length(), 4);
        length = currenLen < maxLen ? currenLen : maxLen;
    }

    QString longestString = QStringLiteral("8").repeated(length);

    const QFontMetrics fm(fontMetrics());
    int w = qMax(0, QtTools::horizontalAdvance(fm, longestString));
    w += 4;  // cursor blinking space
    if (d->addIconSpace) {
        w += iconHeight;
    }
    QStyleOptionSpinBox opt;
    initStyleOption(&opt);
    QSize hint(w, lineEdit()->sizeHint().height());

    QSize size = style()->sizeFromContents(QStyle::CT_SpinBox, &opt, hint, this);
    return size;
}

int QuantitySpinBox::getMaxStrLength(int digits) const
{
    // Calculates the length of the longest string allowed
    Q_D(const QuantitySpinBox);
    ensurePolished();
    QString unit = QString::fromStdString(d->unit.getString());
    int decimals = App::GetApplication()
                       .GetUserParameter()
                       .GetGroup("BaseApp/Preferences/Units")
                       ->GetInt("Decimals", 2);
    return digits + 1 /*separator*/ + decimals + 1 /*space*/ + unit.length();
}

void QuantitySpinBox::showEvent(QShowEvent* event)
{
    Q_D(QuantitySpinBox);

    QAbstractSpinBox::showEvent(event);

    bool selected = lineEdit()->hasSelectedText();
    updateText(d->quantity);
    if (selected) {
        selectNumber();
    }
}

void QuantitySpinBox::hideEvent(QHideEvent* event)
{
    handlePendingEmit();
    QAbstractSpinBox::hideEvent(event);
}

void QuantitySpinBox::closeEvent(QCloseEvent* event)
{
    handlePendingEmit();
    QAbstractSpinBox::closeEvent(event);
}

bool QuantitySpinBox::event(QEvent* event)
{
    // FreeCAD-CH (ops#640, rank 55): back from the Add dialog, a `#name` it made resolves now
    if (event->type() == QEvent::WindowActivate) {
        Q_D(QuantitySpinBox);
        if (!d->variableText.isEmpty() && !d->variableError.isEmpty()) {
            userInput(lineEdit()->text());
        }
    }
    return QAbstractSpinBox::event(event);
}

void QuantitySpinBox::focusInEvent(QFocusEvent* event)
{
    bool hasSel = lineEdit()->hasSelectedText();
    QAbstractSpinBox::focusInEvent(event);

    if (event->reason() == Qt::TabFocusReason || event->reason() == Qt::BacktabFocusReason
        || event->reason() == Qt::ShortcutFocusReason) {

        if (isBound() && getExpression() && lineEdit()->isReadOnly()) {
            auto helpEvent = new QHelpEvent(
                QEvent::ToolTip,
                QPoint(0, rect().height()),
                mapToGlobal(QPoint(0, rect().height()))
            );
            QApplication::postEvent(this, helpEvent);
            lineEdit()->setSelection(0, 0);
        }
        else {
            if (!hasSel) {
                selectNumber();
            }
        }
    }
}

void QuantitySpinBox::focusOutEvent(QFocusEvent* event)
{
    Q_D(QuantitySpinBox);

    // FreeCAD-CH (ops#640, V23): leaving the field binds a variable text; an unresolved one
    // stays as typed, red. Not for a popup (the `#` list) or another window (the Add dialog).
    if (!d->variableText.isEmpty()) {
        if (event->reason() != Qt::PopupFocusReason
            && event->reason() != Qt::ActiveWindowFocusReason) {
            d->commitVariableText();
        }
        if (!d->variableText.isEmpty()) {
            QToolTip::hideText();
            QAbstractSpinBox::focusOutEvent(event);
            return;
        }
    }
    // The `#` list opening on a lone `#` takes the focus too (a popup): the `#` begun stays, not
    // validated back to the last value (the next keys went into the number)
    if (event->reason() == Qt::PopupFocusReason && isBound() && !hasExpression()
        && endsWithVariableStart(lineEdit()->text())) {
        QToolTip::hideText();
        QAbstractSpinBox::focusOutEvent(event);
        return;
    }

    validateInput();

    if (d->normalize) {
        normalize();
    }

    QToolTip::hideText();
    QAbstractSpinBox::focusOutEvent(event);
}

void QuantitySpinBox::clear()
{
    QAbstractSpinBox::clear();
}

void QuantitySpinBox::selectNumber()
{
    QString expr = QStringLiteral("^([%1%2]?[0-9\\%3]*)\\%4?([0-9]+(%5[%1%2]?[0-9]+)?)")
                       .arg(locale().negativeSign())
                       .arg(locale().positiveSign())
                       .arg(locale().groupSeparator())
                       .arg(locale().decimalPoint())
                       .arg(locale().exponential());
    auto rmatch = QRegularExpression(expr).match(lineEdit()->text());
    if (rmatch.hasMatch()) {
        lineEdit()->setSelection(0, rmatch.capturedLength());
    }
}

QString QuantitySpinBox::textFromValue(const Base::Quantity& value) const
{
    QString str = getUserString(value);
    if (qAbs(value.getValue()) >= 1000.0) {
        str.remove(locale().groupSeparator());
    }
    return str;
}

Base::Quantity QuantitySpinBox::valueFromText(const QString& text) const
{
    Q_D(const QuantitySpinBox);

    QString copy = text;
    QValidator::State state = QValidator::Acceptable;
    const App::ObjectIdentifier& path = getPath();
    Base::Quantity quant = d->validateAndInterpret(copy, state, path);
    if (state != QValidator::Acceptable) {
        fixup(copy);
        quant = d->validateAndInterpret(copy, state, path);
    }

    return quant;
}

QValidator::State QuantitySpinBox::validate(QString& text, int& pos) const
{
    Q_D(const QuantitySpinBox);
    Q_UNUSED(pos)

    // FreeCAD-CH (ops#640, V23): a text using a variable is judged by userInput, whatever value
    // it has: a value outside the range must not refuse the key that completes `#name`, nor
    // the '#' that begins it
    if (isBound() && !hasExpression() && (hasVariableRef(text) || endsWithVariableStart(text))) {
        return QValidator::Intermediate;
    }

    QValidator::State state;
    const App::ObjectIdentifier& path = getPath();
    d->validateAndInterpret(text, state, path);
    return state;
}

void QuantitySpinBox::fixup(QString& input) const
{
    input.remove(locale().groupSeparator());
}


#include "moc_QuantitySpinBox.cpp"
#include "moc_QuantitySpinBox_p.cpp"
