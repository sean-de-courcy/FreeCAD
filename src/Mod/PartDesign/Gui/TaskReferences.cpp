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

#include <algorithm>
#include <cmath>

#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QPointer>
#include <QPushButton>
#include <QTimer>
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

#include "ReferenceActions.h"
#include "TaskReferences.h"

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
        if (!sub || !sub[0] || (!type.empty() && ReferenceActions::elementType(sub) != type)) {
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

    if (owner && owner->getDocument()) {
        attachDocument(owner->getDocument());
    }
    refresh();
}

TaskReferences::~TaskReferences()
{
    stopPick();
    clearHighlight();
    display.restore();
}

bool TaskReferences::hasRows(const App::DocumentObject* obj)
{
    return obj && obj->isAttachedToDocument() && !App::referenceRows(obj).empty();
}

void TaskReferences::setCoveredProperties(std::set<std::string> properties)
{
    covered = std::move(properties);
    // The highlight of a row the panel no longer lists goes with it
    clearHighlight();
    display.restore();
    refresh();
}

void TaskReferences::refresh(bool highlightCurrent)
{
    std::string currentProperty;
    int currentIndex = -1;
    QString currentCandidate;
    if (auto row = rowOf(tree->currentItem())) {
        currentProperty = row->property;
        currentIndex = row->index;
        if (tree->currentItem()->parent()) {
            currentCandidate = tree->currentItem()->data(ReferenceColumn, CandidateRole).toString();
        }
    }

    auto obj = owner.getObject();
    rows = obj ? App::referenceRows(obj) : std::vector<App::ReferenceRow> {};
    // What the dialog's reference fields show stays there (ops#150, 3.5)
    std::erase_if(rows, [this](const App::ReferenceRow& row) {
        return covered.contains(row.property);
    });
    rowObjects.clear();
    for (const auto& row : rows) {
        rowObjects.emplace_back(row.obj);
    }

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
            for (int c = 0; c < item->childCount(); ++c) {
                if (!currentCandidate.isEmpty()
                    && item->child(c)->data(ReferenceColumn, CandidateRole).toString()
                        == currentCandidate) {
                    current = item->child(c);
                }
            }
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
    if (highlightCurrent) {
        highlight(current);
    }
}

void TaskReferences::scheduleRefresh()
{
    if (refreshPending) {
        return;
    }
    refreshPending = true;
    // Not now: the change may be one of many, or the panel's own call still running.
    QTimer::singleShot(0, this, [this]() {
        refreshPending = false;
        refresh(false);
    });
}

void TaskReferences::slotChangedObject(const App::DocumentObject& obj, const App::Property& prop)
{
    // A link the dialog wrote itself (a profile re-pick, a list edit): the rows' indexes may name
    // other slots now.
    if (&obj == owner.getObject() && prop.isDerivedFrom<App::PropertyLinkBase>()) {
        scheduleRefresh();
    }
}

void TaskReferences::slotRecomputedObject(const App::DocumentObject& obj)
{
    if (&obj == owner.getObject()) {
        scheduleRefresh();
    }
}

void TaskReferences::slotDeletedObject(const App::DocumentObject& obj)
{
    if (&obj == owner.getObject()
        || std::any_of(rows.begin(), rows.end(), [&obj](const App::ReferenceRow& row) {
               return row.obj == &obj;
           })) {
        scheduleRefresh();
    }
}

void TaskReferences::slotDeletedDocument(const App::Document& doc)
{
    if (&doc == getDocument()) {
        stopPick();
        rows.clear();
        rowObjects.clear();
        tree->clear();
        highlighted = App::SubObjectT();
        display.forget();
        detachDocument();
        updateButtons();
    }
}

int TaskReferences::rowIndexOf(const QTreeWidgetItem* item) const
{
    if (!item) {
        return -1;
    }
    bool ok = false;
    int r = item->data(ReferenceColumn, RowRole).toInt(&ok);
    if (!ok || r < 0 || r >= static_cast<int>(rows.size())) {
        return -1;
    }
    return r;
}

const App::ReferenceRow* TaskReferences::rowOf(const QTreeWidgetItem* item) const
{
    int r = rowIndexOf(item);
    return r < 0 ? nullptr : &rows[r];
}

App::DocumentObject* TaskReferences::targetOf(int r) const
{
    if (r < 0 || r >= static_cast<int>(rowObjects.size())) {
        return nullptr;
    }
    App::DocumentObject* obj = rowObjects[r].getObject();
    if (!obj || !obj->isAttachedToDocument()) {
        return nullptr;
    }
    const std::string& sub = rows[r].sub;
    const char* element = Data::findElementName(sub.c_str());
    std::string path = element ? sub.substr(0, element - sub.c_str()) : std::string();
    if (path.empty()) {
        return obj;
    }
    return obj->getSubObject(path.c_str(), nullptr, nullptr, false);
}

void TaskReferences::updateButtons()
{
    const QTreeWidgetItem* item = tree->currentItem();
    const App::ReferenceRow* row = rowOf(item);
    const bool isCandidate = item && item->parent();
    const bool guess = row && ReferenceActions::hasGuess(*row);
    buttonAccept->setEnabled(!picking && guess && !ReferenceActions::heldElement(*row).empty());
    buttonUse->setEnabled(!picking && isCandidate && !item->data(ReferenceColumn, RejectedRole).toBool());
    buttonBroken->setEnabled(!picking && guess);
    buttonPick->setEnabled(row && targetOf(rowIndexOf(item)));
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

void TaskReferences::changeSelection(const std::function<void()>& change)
{
    // The dialog's selection modes end, and its other panels don't hear of the change: they would
    // take the panel's element for a pick of their own and write their link with it (ops#127).
    Q_EMIT selectionTaken();
    std::vector<Gui::SelectionObserver*> blocked;
    if (Gui::TaskView::TaskDialog* dlg = Gui::Control().activeDialog()) {
        const auto& content = dlg->getDialogContent();
        if (std::find(content.begin(), content.end(), this) != content.end()) {
            auto block = [&](QObject* object) {
                auto observer = dynamic_cast<Gui::SelectionObserver*>(object);
                if (observer && observer != this && !observer->isSelectionBlocked()) {
                    observer->blockSelection(true);
                    blocked.push_back(observer);
                }
            };
            for (QWidget* wgt : content) {
                block(wgt);
                for (QWidget* child : wgt->findChildren<QWidget*>()) {
                    block(child);
                }
            }
        }
    }
    struct Unblock
    {
        std::vector<Gui::SelectionObserver*>& observers;
        ~Unblock()
        {
            for (auto observer : observers) {
                observer->blockSelection(false);
            }
        }
    } unblock {blocked};
    Base::StateLocker lock(selecting, true);
    change();
}

void TaskReferences::highlight(const QTreeWidgetItem* item)
{
    if (picking) {
        return;
    }
    const int r = rowIndexOf(item);
    App::DocumentObject* target = targetOf(r);
    std::string element;
    if (target) {
        element = item->parent()
            ? item->data(ReferenceColumn, CandidateRole).toString().toStdString()
            : ReferenceActions::heldElement(rows[r]);
    }
    changeSelection([&]() {
        Gui::Selection().clearSelection();
        highlighted = App::SubObjectT();
        if (!target) {
            display.restore();  // nothing left to show
            return;
        }
        display.show(target);
        if (!element.empty()) {
            Gui::Selection().addSelection(
                target->getDocument()->getName(),
                target->getNameInDocument(),
                element.c_str()
            );
            highlighted = App::SubObjectT(target, element.c_str());
        }
    });
}

void TaskReferences::clearHighlight()
{
    App::SubObjectT element = highlighted;
    highlighted = App::SubObjectT();
    if (!element.getObject()) {
        return;
    }
    const std::string& sub = element.getSubName();
    if (Gui::Selection().isSelected(element.getDocumentName().c_str(),
                                    element.getObjectName().c_str(),
                                    sub.c_str(),
                                    Gui::ResolveMode::NoResolve)) {
        Base::StateLocker lock(selecting, true);
        Gui::Selection().rmvSelection(element.getDocumentName().c_str(),
                                      element.getObjectName().c_str(),
                                      sub.c_str());
    }
}

bool TaskReferences::run(const std::string& command)
{
    auto obj = owner.getObject();
    if (!obj) {
        return false;
    }
    showMessage(QString(), false);
    QString error;
    bool done = ReferenceActions::run(obj, command, &error);
    if (!done && !error.isEmpty()) {
        showMessage(error, true);
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
    if (!row || !ReferenceActions::hasGuess(*row)) {
        return false;
    }
    return run(ReferenceActions::acceptCommand(owner.getObject(), row->property, row->index));
}

bool TaskReferences::useCurrent()
{
    const QTreeWidgetItem* item = tree->currentItem();
    const App::ReferenceRow* row = rowOf(item);
    if (!row || !item->parent() || item->data(ReferenceColumn, RejectedRole).toBool()) {
        return false;
    }
    std::string candidate = item->data(ReferenceColumn, CandidateRole).toString().toStdString();
    return run(
        ReferenceActions::useCommand(owner.getObject(), row->property, row->index, candidate)
    );
}

bool TaskReferences::markCurrentBroken()
{
    const App::ReferenceRow* row = rowOf(tree->currentItem());
    if (!row || !ReferenceActions::hasGuess(*row)) {
        return false;
    }
    return run(ReferenceActions::markBrokenCommand(owner.getObject(), row->property, row->index));
}

bool TaskReferences::startPick()
{
    if (picking) {
        return true;
    }
    const App::ReferenceRow* row = rowOf(tree->currentItem());
    App::DocumentObject* target = targetOf(rowIndexOf(tree->currentItem()));
    if (!target) {
        QSignalBlocker block(buttonPick);
        buttonPick->setChecked(false);
        return false;
    }
    std::string type = ReferenceActions::subElementType(row->originalIndex);
    if (type.empty()) {
        type = ReferenceActions::subElementType(row->sub);
    }
    pickProperty = row->property;
    pickIndex = row->index;
    // Other selection modes of the dialog end first: they would remove this one's gate.
    changeSelection([this, target]() {
        display.show(target);
        Gui::Selection().clearSelection();
        highlighted = App::SubObjectT();
    });
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
    highlighted = App::SubObjectT(picked, element.c_str());
    std::string command = ReferenceActions::repickCommand(obj, property, index, element);
    // After this notification: selection changes made inside it (the highlight after the call)
    // reach the observers only once it is over, when the dialog's panels hear them again.
    QTimer::singleShot(0, this, [this, command]() { run(command); });
}

/*********************************************************************
 *                            Task Dialog                            *
 *********************************************************************/

TaskDlgReferences::TaskDlgReferences(App::DocumentObject* owner)
    : document(owner->getDocument())
    , references(new TaskReferences(owner))
{
    // The dialog belongs to the owner's document and closes with it.
    setDocumentName(owner->getDocument()->getName());
    setAutoCloseOnDeletedDocument(true);
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
    App::DocumentObject* obj = selection.front().pObject;
    Gui::Control().showDialog(new TaskDlgReferences(obj), obj->getDocument());
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
