// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#include <cmath>
#include <sstream>

#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QPointer>
#include <QPushButton>
#include <QTreeWidget>
#include <QVBoxLayout>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/ElementNamingUtils.h>
#include <Base/Exception.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>
#include <Gui/Control.h>
#include <Gui/Document.h>
#include <Gui/Selection/Selection.h>
#include <Gui/ViewProvider.h>
#include <Mod/PartDesign/App/Body.h>

#include "TaskReferences.h"
#include "ViewProviderBody.h"

using namespace PartDesignGui;

namespace
{

constexpr int RowRole = Qt::UserRole;
constexpr int CandidateRole = Qt::UserRole + 1;
constexpr int RejectedRole = Qt::UserRole + 2;

enum Column
{
    ReferenceColumn,
    StateColumn,
    ElementColumn,
    OriginalColumn,
    EvidenceColumn,
};

// The element type of an element name: `Edge` for `Edge5` or `?Edge5`.
std::string elementType(const std::string& name)
{
    std::string type;
    for (char c : name) {
        if (c == '?') {
            continue;
        }
        if (c >= '0' && c <= '9') {
            break;
        }
        type += c;
    }
    return type;
}

// The element a row holds now, or empty if it is missing.
std::string heldElement(const App::ReferenceRow& row)
{
    const char* element = Data::findElementName(row.sub.c_str());
    if (!element || !element[0] || Data::hasMissingElement(element)) {
        return {};
    }
    return element;
}

// A row with a record the user can still accept or reject.
bool hasGuess(const App::ReferenceRow& row)
{
    return !row.guessKind.empty() && row.guessKind != "rejected";
}

QString stateText(const App::ReferenceRow& row)
{
    if (row.guessKind == "rejected") {
        return TaskReferences::tr("Broken (pick rejected)");
    }
    if (row.status == "broken") {
        return TaskReferences::tr("Broken");
    }
    if (row.status == "guessed") {
        return TaskReferences::tr("Guessed");
    }
    if (row.status == "expanded") {
        return TaskReferences::tr("Split");
    }
    if (row.status == "index") {
        return TaskReferences::tr("Carried by index");
    }
    if (row.tier >= 2) {
        return TaskReferences::tr("Found by geometry (tier %1)").arg(row.tier);
    }
    return TaskReferences::tr("Resolved");
}

QString roleText(const std::string& role)
{
    if (role == "rejected") {
        return TaskReferences::tr("rejected");
    }
    if (role == "piece") {
        return TaskReferences::tr("piece");
    }
    if (role == "place") {
        return TaskReferences::tr("at its place");
    }
    if (role == "name") {
        return TaskReferences::tr("has its name");
    }
    if (role == "structural") {
        return TaskReferences::tr("same neighbours");
    }
    if (role == "geometric") {
        return TaskReferences::tr("same geometry");
    }
    if (role == "guess") {
        return TaskReferences::tr("the guess");
    }
    return QString::fromStdString(role);
}

QString distanceText(double distance)
{
    if (std::isnan(distance)) {
        return {};
    }
    return TaskReferences::tr("%1 mm from where it was").arg(distance, 0, 'g', 4);
}

// The Python string literal of an ASCII name.
std::string quoted(const std::string& name)
{
    std::string text = "'";
    for (char c : name) {
        if (c == '\'' || c == '\\') {
            text += '\\';
        }
        text += c;
    }
    return text + "'";
}

/// A re-pick's gate: elements of one type on one object.
class PickGate: public Gui::SelectionGate
{
public:
    PickGate(TaskReferences* panel, const App::DocumentObject* target, std::string type)
        : panel(panel)
        , target(target)
        , type(std::move(type))
    {}
    ~PickGate() override
    {
        if (panel) {
            panel->pickGateGone();
        }
    }

    bool allow(App::Document* /*doc*/, App::DocumentObject* obj, const char* sub) override
    {
        if (obj != target) {
            notAllowedReason = QT_TR_NOOP("Pick an element of the reference's object.");
            return false;
        }
        if (!sub || !sub[0] || (!type.empty() && elementType(sub) != type)) {
            notAllowedReason = QT_TR_NOOP("Pick an element of the reference's type.");
            return false;
        }
        return true;
    }

private:
    QPointer<TaskReferences> panel;
    const App::DocumentObject* target;
    std::string type;
};

}  // namespace

TaskReferences::TaskReferences(App::DocumentObject* owner, QWidget* parent)
    : TaskBox(Gui::BitmapFactory().pixmap("overlay_warning"), tr("References"), true, parent)
    , Gui::SelectionObserver(true, Gui::ResolveMode::OldStyleElement)
    , owner(owner)
{
    auto widget = new QWidget(this);
    auto layout = new QVBoxLayout(widget);
    layout->setContentsMargins(0, 0, 0, 0);

    header = new QLabel(widget);
    header->setObjectName(QStringLiteral("header"));
    header->setWordWrap(true);
    header->setTextInteractionFlags(Qt::TextSelectableByMouse);
    layout->addWidget(header);

    tree = new QTreeWidget(widget);
    tree->setObjectName(QStringLiteral("references"));
    tree->setHeaderLabels(
        {tr("Reference"), tr("State"), tr("Element"), tr("Original"), tr("Evidence")}
    );
    tree->setRootIsDecorated(true);
    tree->setUniformRowHeights(true);
    tree->header()->setStretchLastSection(true);
    layout->addWidget(tree);

    auto buttons = new QHBoxLayout();
    buttonAccept = new QPushButton(tr("Accept"), widget);
    buttonAccept->setObjectName(QStringLiteral("buttonAccept"));
    buttonAccept->setToolTip(tr("Keep the element the reference holds now; the warning goes"));
    buttonUse = new QPushButton(tr("Use this one"), widget);
    buttonUse->setObjectName(QStringLiteral("buttonUse"));
    buttonUse->setToolTip(tr("Take the selected candidate instead"));
    buttonBroken = new QPushButton(tr("Mark broken"), widget);
    buttonBroken->setObjectName(QStringLiteral("buttonBroken"));
    buttonBroken->setToolTip(
        tr("The guess is wrong and nothing listed is right: the feature fails until the "
           "reference is re-picked, and the rejected element is never picked again")
    );
    buttonPick = new QPushButton(tr("Re-pick"), widget);
    buttonPick->setObjectName(QStringLiteral("buttonPick"));
    buttonPick->setCheckable(true);
    buttonPick->setToolTip(tr("Pick the element in the 3D view"));
    buttons->addWidget(buttonAccept);
    buttons->addWidget(buttonUse);
    buttons->addWidget(buttonBroken);
    buttons->addWidget(buttonPick);
    layout->addLayout(buttons);

    message = new QLabel(widget);
    message->setObjectName(QStringLiteral("message"));
    message->setWordWrap(true);
    message->hide();
    layout->addWidget(message);

    groupLayout()->addWidget(widget);

    connect(tree, &QTreeWidget::currentItemChanged, this, &TaskReferences::onCurrentItemChanged);
    connect(buttonAccept, &QPushButton::clicked, this, [this]() { acceptCurrent(); });
    connect(buttonUse, &QPushButton::clicked, this, [this]() { useCurrent(); });
    connect(buttonBroken, &QPushButton::clicked, this, [this]() { markCurrentBroken(); });
    connect(buttonPick, &QPushButton::toggled, this, &TaskReferences::onPickToggled);

    refresh();
}

TaskReferences::~TaskReferences()
{
    stopPick();
    restoreVisibility();
}

bool TaskReferences::hasRows(const App::DocumentObject* obj)
{
    return obj && obj->isAttachedToDocument() && !App::referenceRows(obj).empty();
}

void TaskReferences::refresh()
{
    std::string currentProperty;
    int currentIndex = -1;
    if (auto row = rowOf(tree->currentItem())) {
        currentProperty = row->property;
        currentIndex = row->index;
    }

    auto obj = owner.getObject();
    rows = obj ? App::referenceRows(obj) : std::vector<App::ReferenceRow> {};

    QTreeWidgetItem* current = nullptr;
    QSignalBlocker block(tree);
    tree->clear();
    for (std::size_t r = 0; r < rows.size(); ++r) {
        const auto& row = rows[r];
        auto item = new QTreeWidgetItem(tree);
        item->setData(ReferenceColumn, RowRole, static_cast<int>(r));
        item->setText(ReferenceColumn,
                      QStringLiteral("%1[%2]").arg(QString::fromStdString(row.property)).arg(row.index));
        item->setText(StateColumn, stateText(row));
        const char* element = Data::findElementName(row.sub.c_str());
        item->setText(ElementColumn, QString::fromUtf8(element ? element : row.sub.c_str()));
        item->setText(OriginalColumn, QString::fromStdString(row.originalIndex));
        item->setText(EvidenceColumn,
                      QString::fromStdString(row.headline.empty() ? row.evidence : row.headline));
        item->setToolTip(EvidenceColumn, item->text(EvidenceColumn));
        // The alternatives of a guess, or the candidates of a break, in rank order.
        auto addChild = [&](const std::string& index, const std::string& role, double distance) {
            auto child = new QTreeWidgetItem(item);
            child->setData(ReferenceColumn, RowRole, static_cast<int>(r));
            child->setData(ReferenceColumn, CandidateRole, QString::fromStdString(index));
            child->setData(ReferenceColumn, RejectedRole, role == "rejected");
            child->setText(StateColumn, roleText(role));
            child->setText(ElementColumn, QString::fromStdString(index));
            child->setText(EvidenceColumn, distanceText(distance));
            if (role == "rejected") {
                child->setDisabled(true);
            }
        };
        if (!row.alternatives.empty()) {
            for (const auto& alternative : row.alternatives) {
                addChild(alternative.index, alternative.role, alternative.distance);
            }
        }
        else {
            for (const auto& candidate : row.candidates) {
                addChild(candidate.index, candidate.role, candidate.distance);
            }
        }
        item->setExpanded(true);
        if (row.property == currentProperty && row.index == currentIndex) {
            current = item;
        }
    }
    for (int c = 0; c < tree->columnCount(); ++c) {
        tree->resizeColumnToContents(c);
    }
    if (!current && tree->topLevelItemCount() > 0) {
        current = tree->topLevelItem(0);
    }
    tree->setCurrentItem(current);
    block.unblock();

    QString text;
    if (!obj) {
        text = tr("The object was deleted.");
    }
    else if (rows.empty()) {
        text = tr("All references of %1 resolve.").arg(QString::fromUtf8(obj->Label.getValue()));
    }
    else {
        text = QStringLiteral("<b>%1</b>: %2").arg(
            QString::fromUtf8(obj->Label.getValue()).toHtmlEscaped(),
            QString::fromUtf8(obj->getStatusString()).toHtmlEscaped()
        );
    }
    header->setText(text);
    updateButtons();
    highlight(current);
}

const App::ReferenceRow* TaskReferences::rowOf(const QTreeWidgetItem* item) const
{
    if (!item) {
        return nullptr;
    }
    bool ok = false;
    int r = item->data(ReferenceColumn, RowRole).toInt(&ok);
    if (!ok || r < 0 || r >= static_cast<int>(rows.size())) {
        return nullptr;
    }
    return &rows[r];
}

App::DocumentObject* TaskReferences::targetOf(const App::ReferenceRow& row) const
{
    if (!row.obj || !row.obj->isAttachedToDocument()) {
        return nullptr;
    }
    const char* element = Data::findElementName(row.sub.c_str());
    std::string path = element ? row.sub.substr(0, element - row.sub.c_str()) : std::string();
    if (path.empty()) {
        return row.obj;
    }
    return row.obj->getSubObject(path.c_str(), nullptr, nullptr, false);
}

void TaskReferences::updateButtons()
{
    const QTreeWidgetItem* item = tree->currentItem();
    const App::ReferenceRow* row = rowOf(item);
    const bool isCandidate = item && item->parent();
    const bool guess = row && hasGuess(*row);
    buttonAccept->setEnabled(!picking && guess && !heldElement(*row).empty());
    buttonUse->setEnabled(!picking && isCandidate && !item->data(ReferenceColumn, RejectedRole).toBool());
    buttonBroken->setEnabled(!picking && guess);
    buttonPick->setEnabled(row && targetOf(*row));
    tree->setEnabled(!picking);
}

void TaskReferences::showMessage(const QString& text, bool error)
{
    message->setText(text);
    message->setStyleSheet(error ? QStringLiteral("color: red;") : QString());
    message->setVisible(!text.isEmpty());
}

void TaskReferences::onCurrentItemChanged()
{
    updateButtons();
    highlight(tree->currentItem());
}

void TaskReferences::highlight(const QTreeWidgetItem* item)
{
    if (picking) {
        return;
    }
    Base::StateLocker lock(selecting, true);
    Gui::Selection().clearSelection();
    const App::ReferenceRow* row = rowOf(item);
    App::DocumentObject* target = row ? targetOf(*row) : nullptr;
    if (!target) {
        restoreVisibility();  // nothing left to show
        return;
    }
    std::string element = item->parent()
        ? item->data(ReferenceColumn, CandidateRole).toString().toStdString()
        : heldElement(*row);
    showTarget(target);
    if (!element.empty()) {
        Gui::Selection().addSelection(
            target->getDocument()->getName(),
            target->getNameInDocument(),
            element.c_str()
        );
    }
}

void TaskReferences::showTarget(App::DocumentObject* target)
{
    if (shownTarget.getObject() == target) {
        return;
    }
    restoreVisibility();
    Gui::ViewProvider* vp = Gui::Application::Instance->getViewProvider(target);
    if (!vp || vp->isShow()) {
        return;
    }
    // In a body only one solid shows: hide it while its predecessor is shown.
    if (auto body = PartDesign::Body::findBodyOf(target)) {
        auto bodyVp = Gui::Application::Instance->getViewProvider<ViewProviderBody>(body);
        if (Gui::ViewProvider* shown = bodyVp ? bodyVp->getShownViewProvider() : nullptr) {
            if (auto shownVp = freecad_cast<Gui::ViewProviderDocumentObject*>(shown)) {
                hiddenFeature = shownVp->getObject();
                shown->hide();
            }
        }
    }
    vp->show();
    shownTarget = target;
}

void TaskReferences::restoreVisibility()
{
    if (auto target = shownTarget.getObject()) {
        if (auto vp = Gui::Application::Instance->getViewProvider(target)) {
            vp->hide();
        }
    }
    if (auto feature = hiddenFeature.getObject()) {
        if (auto vp = Gui::Application::Instance->getViewProvider(feature)) {
            vp->show();
        }
    }
    shownTarget = App::DocumentObjectT();
    hiddenFeature = App::DocumentObjectT();
}

bool TaskReferences::run(const std::string& command)
{
    auto obj = owner.getObject();
    if (!obj) {
        return false;
    }
    showMessage(QString(), false);
    // In the caller's transaction; one of its own when there is none (a feature's dialog opened
    // without one): Cancel undoes it either way.
    App::Document* doc = obj->getDocument();
    if (!doc->hasPendingTransaction() && doc->getBookedTransactionID() == App::NullTransaction) {
        doc->openTransaction(QT_TRANSLATE_NOOP("Command", "Repair references"));
    }
    bool done = true;
    try {
        Gui::Command::runCommand(Gui::Command::Doc, command.c_str());
    }
    catch (const Base::Exception& e) {
        showMessage(QString::fromUtf8(e.what()), true);
        done = false;
    }
    if (done) {
        try {
            Gui::cmdAppDocument(obj->getDocument(), "recompute()");
        }
        catch (const Base::Exception& e) {
            e.reportException();
        }
    }
    refresh();
    if (done) {
        Q_EMIT referencesChanged();
    }
    return done;
}

bool TaskReferences::acceptCurrent()
{
    const App::ReferenceRow* row = rowOf(tree->currentItem());
    if (!row || !hasGuess(*row)) {
        return false;
    }
    std::ostringstream str;
    str << "App.acceptReference(" << Gui::Command::getObjectCmd(owner.getObject()) << ", "
        << quoted(row->property) << ", " << row->index << ")";
    return run(str.str());
}

bool TaskReferences::useCurrent()
{
    const QTreeWidgetItem* item = tree->currentItem();
    const App::ReferenceRow* row = rowOf(item);
    if (!row || !item->parent() || item->data(ReferenceColumn, RejectedRole).toBool()) {
        return false;
    }
    std::string candidate = item->data(ReferenceColumn, CandidateRole).toString().toStdString();
    std::ostringstream str;
    str << "App.repairReference(" << Gui::Command::getObjectCmd(owner.getObject()) << ", "
        << quoted(row->property) << ", " << row->index << ", " << quoted(candidate) << ")";
    return run(str.str());
}

bool TaskReferences::markCurrentBroken()
{
    const App::ReferenceRow* row = rowOf(tree->currentItem());
    if (!row || !hasGuess(*row)) {
        return false;
    }
    std::ostringstream str;
    str << "App.markReferenceBroken(" << Gui::Command::getObjectCmd(owner.getObject()) << ", "
        << quoted(row->property) << ", " << row->index << ")";
    return run(str.str());
}

bool TaskReferences::startPick()
{
    if (picking) {
        return true;
    }
    const App::ReferenceRow* row = rowOf(tree->currentItem());
    App::DocumentObject* target = row ? targetOf(*row) : nullptr;
    if (!target) {
        QSignalBlocker block(buttonPick);
        buttonPick->setChecked(false);
        return false;
    }
    std::string type = elementType(row->originalIndex.empty() ? row->sub : row->originalIndex);
    if (type.empty()) {
        const char* element = Data::findElementName(row->sub.c_str());
        type = elementType(element ? element : "");
    }
    // Other selection modes of the dialog end first: they would remove this one's gate.
    Q_EMIT pickStarted();
    pickProperty = row->property;
    pickIndex = row->index;
    showTarget(target);
    {
        Base::StateLocker lock(selecting, true);
        Gui::Selection().clearSelection();
    }
    picking = true;
    Gui::Selection().addSelectionGate(new PickGate(this, target, type));
    {
        QSignalBlocker block(buttonPick);
        buttonPick->setChecked(true);
    }
    showMessage(tr("Pick the %1 for %2[%3] in the 3D view.")
                    .arg(QString::fromStdString(type).toLower(),
                         QString::fromStdString(pickProperty))
                    .arg(pickIndex),
                false);
    updateButtons();
    return true;
}

void TaskReferences::stopPick()
{
    if (!picking) {
        return;
    }
    // The gate's destructor calls pickGateGone().
    Gui::Selection().rmvSelectionGate();
    pickGateGone();
}

void TaskReferences::pickGateGone()
{
    if (!picking) {
        return;
    }
    picking = false;
    {
        QSignalBlocker block(buttonPick);
        buttonPick->setChecked(false);
    }
    showMessage(QString(), false);
    updateButtons();
}

void TaskReferences::onPickToggled(bool checked)
{
    if (checked) {
        startPick();
    }
    else {
        stopPick();
    }
}

void TaskReferences::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    if (!picking || selecting || msg.Type != Gui::SelectionChanges::AddSelection) {
        return;
    }
    auto obj = owner.getObject();
    App::DocumentObject* picked = msg.Object.getObject();
    if (!obj || !picked || !msg.pSubName || !msg.pSubName[0]) {
        return;
    }
    std::string element = msg.pSubName;
    std::string property = pickProperty;
    int index = pickIndex;
    stopPick();
    std::ostringstream str;
    str << "App.repairReference(" << Gui::Command::getObjectCmd(obj) << ", " << quoted(property)
        << ", " << index << ", " << quoted(element) << ", True)";
    run(str.str());
}

/*********************************************************************
 *                            Task Dialog                            *
 *********************************************************************/

TaskDlgReferences::TaskDlgReferences(App::DocumentObject* owner)
    : document(owner->getDocument())
    , references(new TaskReferences(owner))
{
    owner->getDocument()->openTransaction(QT_TRANSLATE_NOOP("Command", "Repair references"));
    Content.push_back(references);
}

TaskDlgReferences::~TaskDlgReferences() = default;

bool TaskDlgReferences::accept()
{
    references->stopPick();
    if (auto doc = document.getDocument()) {
        doc->commitTransaction();
    }
    return true;
}

bool TaskDlgReferences::reject()
{
    references->stopPick();
    if (auto doc = document.getDocument()) {
        doc->abortTransaction();
        Gui::cmdAppDocument(doc, "recompute()");
    }
    return true;
}

/*********************************************************************
 *                              Command                              *
 *********************************************************************/

DEF_STD_CMD_A(CmdPartDesignRepairReferences)

CmdPartDesignRepairReferences::CmdPartDesignRepairReferences()
    : Command("PartDesign_RepairReferences")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Repair References…");
    sToolTipText = QT_TR_NOOP(
        "Lists the guessed and broken references of the selected object, to accept, replace or "
        "re-pick them"
    );
    sWhatsThis = "PartDesign_RepairReferences";
    sStatusTip = sToolTipText;
    sPixmap = "overlay_warning";
}

void CmdPartDesignRepairReferences::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    auto selection = getSelection().getSelection();
    if (selection.size() != 1 || !selection.front().pObject) {
        return;
    }
    Gui::Control().showDialog(new TaskDlgReferences(selection.front().pObject));
}

bool CmdPartDesignRepairReferences::isActive()
{
    if (Gui::Control().activeDialog()) {
        return false;
    }
    auto selection = Gui::Selection().getSelection();
    return selection.size() == 1 && TaskReferences::hasRows(selection.front().pObject);
}

void CreatePartDesignReferenceCommands()
{
    Gui::Application::Instance->commandManager().addCommand(new CmdPartDesignRepairReferences());
}

#include "moc_TaskReferences.cpp"
