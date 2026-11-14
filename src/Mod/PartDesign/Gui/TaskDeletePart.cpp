// SPDX-License-Identifier: LGPL-2.1-or-later

// Onshape's Delete part dialog (FreeCAD-CH ops#640 rank 30, blind test F48)

#include <algorithm>

#include <QAction>
#include <QApplication>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QLabel>
#include <QListWidget>
#include <QPointer>
#include <QTimer>
#include <QToolButton>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObserver.h>
#include <App/Part.h>
#include <Base/Exception.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/Control.h>
#include <Gui/Document.h>
#include <Gui/MainWindow.h>
#include <Gui/TaskView/TaskView.h>
#include <Gui/Tools.h>
#include <Mod/Part/App/BodyBase.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureBoolean.h>
#include <Mod/PartDesign/App/FeatureDeletePart.h>
#include <Mod/PartDesign/App/Studio.h>

#include "TaskDeletePart.h"

using namespace PartDesignGui;

namespace
{
std::string quoted(const App::DocumentObject* obj)
{
    return std::string("'") + (obj ? obj->Label.getValue() : "?") + "'";
}

std::string studioCommand(App::Document* doc, App::Part* studio)
{
    return studio ? Gui::Command::getObjectCmd(studio)
                  : std::string("App.getDocument('") + doc->getName() + "')";
}

// The parts openFor() was asked for since the dialog was last scheduled
std::vector<App::DocumentObjectT>& pendingParts()
{
    static std::vector<App::DocumentObjectT> parts;
    return parts;
}
bool openScheduled = false;

// The list's delete key before the window's shortcuts: Std_Delete has the same key, and Qt fires
// neither of two shortcuts on one key, so the action's own shortcut never took an entry out (as
// ReferenceField's entry list, ops#652)
class KeyBeforeTheWindow: public QObject
{
public:
    KeyBeforeTheWindow(QAction* action, QObject* parent)
        : QObject(parent)
        , action(action)
    {}

    bool eventFilter(QObject* watched, QEvent* event) override
    {
        if (event->type() != QEvent::ShortcutOverride && event->type() != QEvent::KeyPress) {
            return QObject::eventFilter(watched, event);
        }
        auto ke = static_cast<QKeyEvent*>(event);  // NOLINT
        if (!action || !Gui::QtTools::matches(ke, action->shortcut())) {
            return QObject::eventFilter(watched, event);
        }
        if (event->type() == QEvent::ShortcutOverride) {
            ke->accept();
        }
        else {
            action->trigger();
        }
        return true;
    }

private:
    QPointer<QAction> action;
};
}  // namespace

TaskDlgDeletePart::TaskDlgDeletePart(App::Document* doc,
                                     const std::vector<PartDesign::Body*>& parts,
                                     PartDesign::DeletePart* feature)
    : Gui::SelectionObserver(true, Gui::ResolveMode::NoResolve)
    , docName(doc->getName())
    , featureName(feature ? feature->getNameInDocument() : "")
{
    setDocumentName(docName);
    setAutoCloseOnDeletedDocument(true);
    auto box = new Gui::TaskView::TaskBox(
        Gui::BitmapFactory().pixmap("edit-delete"),
        feature ? QString::fromUtf8(feature->Label.getValue()) : tr("Delete part"),
        true,
        nullptr
    );
    box->groupLayout()->addWidget(new QLabel(tr("Entities to delete:"), box));
    list = new QListWidget(box);
    list->setObjectName(QStringLiteral("deletePartEntities"));
    box->groupLayout()->addWidget(list);
    // Delete takes the current entry out, as the dialogs' reference fields: the platform's delete
    // key, which is Backspace on a Mac (ops#652)
    auto removeCurrent = new QAction(tr("Remove"), list);
    removeCurrent->setShortcut(Gui::QtTools::deleteKeySequence());
    removeCurrent->setShortcutContext(Qt::WidgetShortcut);
    list->addAction(removeCurrent);
    list->installEventFilter(new KeyBeforeTheWindow(removeCurrent, list));
    connect(removeCurrent, &QAction::triggered, this, [this]() {
        if (QListWidgetItem* item = list->currentItem()) {
            removeName(item->data(Qt::UserRole).toByteArray().toStdString());
        }
    });
    auto hint = new QLabel(
        tr("Pick the parts in the 3D view or the Parts list; a pick of a listed part takes it out."),
        box
    );
    hint->setWordWrap(true);
    box->groupLayout()->addWidget(hint);
    message = new QLabel(box);
    message->setObjectName(QStringLiteral("deletePartMessage"));
    message->setWordWrap(true);
    message->setStyleSheet(QStringLiteral("color: #d03030;"));
    message->hide();
    box->groupLayout()->addWidget(message);
    Content.push_back(box);

    if (feature) {
        if (PartDesign::Body* body = PartDesign::Body::findBodyOf(feature)) {
            names.emplace_back(body->getNameInDocument());
        }
    }
    addParts(parts);
    fillList();
    scheduleSync();
}

TaskDlgDeletePart::~TaskDlgDeletePart() = default;

void TaskDlgDeletePart::openFor(PartDesign::Body* body)
{
    if (!body || !body->isAttachedToDocument()) {
        return;
    }
    pendingParts().emplace_back(body);
    if (openScheduled) {
        return;
    }
    openScheduled = true;
    QTimer::singleShot(0, qApp, []() {
        openScheduled = false;
        std::vector<App::DocumentObjectT> asked;
        asked.swap(pendingParts());
        std::vector<PartDesign::Body*> bodies;
        App::Document* doc = nullptr;
        for (const auto& objT : asked) {
            auto body = freecad_cast<PartDesign::Body*>(objT.getObject());
            if (body && (!doc || body->getDocument() == doc)) {
                doc = body->getDocument();
                bodies.push_back(body);
            }
        }
        if (!doc) {
            return;
        }
        Gui::TaskView::TaskDialog* active = Gui::Control().activeDialog();
        if (auto dialog = qobject_cast<TaskDlgDeletePart*>(active)) {
            dialog->addParts(bodies);
            return;
        }
        if (active) {
            Gui::getMainWindow()->showMessage(
                QApplication::translate("PartDesignGui::TaskDlgDeletePart",
                                        "Delete part: finish the open dialog first"),
                5000
            );
            return;
        }
        Gui::Control().showDialog(new TaskDlgDeletePart(doc, bodies));
    });
}

App::Document* TaskDlgDeletePart::document() const
{
    return App::GetApplication().getDocument(docName.c_str());
}

PartDesign::DeletePart* TaskDlgDeletePart::edited() const
{
    App::Document* doc = document();
    if (!doc || featureName.empty()) {
        return nullptr;
    }
    return freecad_cast<PartDesign::DeletePart*>(doc->getObject(featureName.c_str()));
}

std::string TaskDlgDeletePart::refusal(const PartDesign::Body* body) const
{
    App::Document* doc = document();
    if (!body || body->getDocument() != doc) {
        return "The part is in another document";
    }
    App::Part* studio = nullptr;
    if (!Part::BodyBase::studioOf(body, studio)) {
        return quoted(body) + " is in no part studio";
    }
    // One part studio: the edited row's, or the first listed part's
    const PartDesign::Body* first = nullptr;
    if (auto feature = edited()) {
        first = PartDesign::Body::findBodyOf(feature);
    }
    if (!first && !names.empty()) {
        first = freecad_cast<PartDesign::Body*>(doc->getObject(names.front().c_str()));
    }
    App::Part* firstStudio = nullptr;
    if (first && first != body
        && (!Part::BodyBase::studioOf(first, firstStudio) || firstStudio != studio)) {
        return quoted(body) + " is in another part studio";
    }
    PartDesign::DeletePart* deleter = PartDesign::DeletePart::deleterOf(body);
    if (deleter && deleter == edited()) {
        return {};
    }
    if (deleter) {
        return quoted(body) + " is deleted already, by " + quoted(deleter);
    }
    if (!body->Tip.getValue()) {
        return quoted(body) + " has no solid feature above its bar, so it is no part";
    }
    if (auto merge = PartDesign::Boolean::mergeOf(body)) {
        return quoted(body) + " is merged by " + quoted(merge)
            + "; delete the Merge first, or delete the part it is merged into";
    }
    return {};
}

void TaskDlgDeletePart::addParts(const std::vector<PartDesign::Body*>& parts)
{
    QStringList refused;
    for (PartDesign::Body* body : parts) {
        if (!body || std::ranges::find(names, body->getNameInDocument()) != names.end()) {
            continue;
        }
        const std::string why = refusal(body);
        if (!why.empty()) {
            refused << QString::fromUtf8(why.c_str());
            continue;
        }
        names.emplace_back(body->getNameInDocument());
    }
    fillList();
    scheduleSync();
    if (!refused.isEmpty()) {
        showMessage(refused.join(QLatin1Char('\n')));
    }
}

void TaskDlgDeletePart::toggle(PartDesign::Body* body)
{
    if (!body) {
        return;
    }
    if (std::ranges::find(names, body->getNameInDocument()) != names.end()) {
        removeName(body->getNameInDocument());
        return;
    }
    message->hide();
    addParts({body});
}

void TaskDlgDeletePart::removeName(const std::string& name)
{
    std::erase(names, name);
    message->hide();
    fillList();
    scheduleSync();
}

void TaskDlgDeletePart::fillList()
{
    list->clear();
    App::Document* doc = document();
    if (!doc) {
        return;
    }
    std::erase_if(names, [doc](const std::string& name) { return !doc->getObject(name.c_str()); });
    for (const std::string& name : names) {
        App::DocumentObject* body = doc->getObject(name.c_str());
        auto item = new QListWidgetItem(QString::fromUtf8(body->Label.getValue()), list);
        item->setData(Qt::UserRole, QByteArray(name.c_str()));
        // The x after the entry's text, as the reference fields' (ops#640 rank 26)
        auto row = new QWidget(list);
        auto layout = new QHBoxLayout(row);
        layout->setContentsMargins(0, 0, 2, 0);
        layout->addStretch();
        auto remove = new QToolButton(row);
        remove->setObjectName(QStringLiteral("removeEntity"));
        remove->setText(QStringLiteral("x"));
        remove->setToolTip(tr("Remove %1").arg(item->text()));
        remove->setAutoRaise(true);
        layout->addWidget(remove);
        list->setItemWidget(item, row);
        connect(remove, &QToolButton::clicked, this, [this, name]() {
            // after the click: the list is filled again
            QTimer::singleShot(0, this, [this, name]() { removeName(name); });
        });
    }
}

void TaskDlgDeletePart::scheduleSync()
{
    if (syncPending) {
        return;
    }
    syncPending = true;
    QPointer<TaskDlgDeletePart> self(this);
    QTimer::singleShot(0, this, [self]() {
        if (!self) {
            return;
        }
        self->syncPending = false;
        App::Document* doc = self->document();
        if (!doc) {
            return;
        }
        self->syncing = true;
        Gui::Selection().clearSelection(doc->getName());
        for (const std::string& name : self->names) {
            if (doc->getObject(name.c_str())) {
                Gui::Selection().addSelection(doc->getName(), name.c_str());
            }
        }
        self->syncing = false;
    });
}

void TaskDlgDeletePart::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    if (syncing || msg.Type != Gui::SelectionChanges::AddSelection) {
        return;
    }
    App::Document* doc = document();
    if (!doc || !msg.pDocName || docName != msg.pDocName || !msg.pObjectName) {
        return;
    }
    App::DocumentObject* top = doc->getObject(msg.pObjectName);
    if (!top) {
        return;
    }
    // The part the pick belongs to: the last Body on its path, else the Body of what it picked
    std::vector<App::DocumentObject*> path = top->getSubObjectList(msg.pSubName ? msg.pSubName : "");
    PartDesign::Body* body = nullptr;
    for (App::DocumentObject* obj : path) {
        if (auto each = freecad_cast<PartDesign::Body*>(obj)) {
            body = each;
        }
    }
    if (!body && !path.empty()) {
        body = PartDesign::Body::findBodyOf(path.back());
    }
    if (!body) {
        showMessage(tr("Pick a part"));
        scheduleSync();
        return;
    }
    toggle(body);
}

void TaskDlgDeletePart::showMessage(const QString& text)
{
    message->setText(text);
    message->show();
}

bool TaskDlgDeletePart::accept()
{
    App::Document* doc = document();
    Gui::Document* gdoc = doc ? Gui::Application::Instance->getDocument(doc) : nullptr;
    if (!gdoc) {
        return true;
    }
    std::vector<PartDesign::Body*> bodies;
    for (const std::string& name : names) {
        if (auto body = freecad_cast<PartDesign::Body*>(doc->getObject(name.c_str()))) {
            bodies.push_back(body);
        }
    }
    if (bodies.empty()) {
        showMessage(tr("Pick the parts to delete"));
        return false;
    }
    PartDesign::DeletePart* feature = edited();
    if (!featureName.empty() && !feature) {
        return true;  // the edited row is gone
    }
    PartDesign::Body* own = feature ? PartDesign::Body::findBodyOf(feature) : nullptr;
    const bool keep = own && std::ranges::find(bodies, own) != bodies.end();
    std::erase(bodies, own);
    if (feature && keep && bodies.empty()) {
        Gui::Selection().clearSelection(doc->getName());
        return true;  // nothing changed: no step, as Cancel
    }
    App::Part* studio = nullptr;
    Part::BodyBase::studioOf(bodies.empty() ? own : bodies.front(), studio);
    const std::string studioCmd = studioCommand(doc, studio);

    gdoc->openCommand(feature ? QT_TRANSLATE_NOOP("Command", "Edit Delete part")
                              : QT_TRANSLATE_NOOP("Command", "Delete part"));
    try {
        Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
        // An edit deletes the parts added at its own row's place in history: the studio is
        // rolled there for the inserts (Body::addObject's insert at the bar), then back
        const bool roll = feature && !bodies.empty();
        const bool wasRolledBack = roll && PartDesign::isStudioRolledBack(doc, studio);
        std::string barCmd = "None";
        if (wasRolledBack) {
            if (App::DocumentObject* bar = PartDesign::studioBarAfter(PartDesign::studioSequence(doc, studio))) {
                barCmd = Gui::Command::getObjectCmd(bar);
            }
        }
        if (roll) {
            Gui::Command::doCommand(Gui::Command::Doc,
                                    "PartDesign.rollStudioTo(%s, %s)",
                                    studioCmd.c_str(),
                                    Gui::Command::getObjectCmd(feature).c_str());
        }
        for (PartDesign::Body* body : bodies) {
            Gui::Command::doCommand(Gui::Command::Doc,
                                    "PartDesign.deletePart(%s)",
                                    Gui::Command::getObjectCmd(body).c_str());
        }
        if (roll && !wasRolledBack) {
            Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.rollStudioToEnd(%s)", studioCmd.c_str());
        }
        else if (roll) {
            Gui::Command::doCommand(Gui::Command::Doc,
                                    "PartDesign.rollStudioTo(%s, %s)",
                                    studioCmd.c_str(),
                                    barCmd.c_str());
        }
        // Its part taken out: the row goes, and the part is back (as deleting the row)
        if (feature && !keep) {
            const std::string name = feature->getNameInDocument();
            Gui::Command::doCommand(Gui::Command::Doc,
                                    "%s.removeObject(%s)",
                                    Gui::Command::getObjectCmd(own).c_str(),
                                    Gui::Command::getObjectCmd(feature).c_str());
            Gui::Command::doCommand(Gui::Command::Doc,
                                    "App.getDocument('%s').removeObject('%s')",
                                    doc->getName(),
                                    name.c_str());
        }
        Gui::Command::doCommand(Gui::Command::Doc, "App.getDocument('%s').recompute()", doc->getName());
        gdoc->commitCommand();
    }
    catch (const Base::Exception& e) {
        gdoc->abortCommand();
        showMessage(QString::fromUtf8(e.what()));
        return false;
    }
    Gui::Selection().clearSelection(doc->getName());
    return true;
}

bool TaskDlgDeletePart::reject()
{
    if (App::Document* doc = document()) {
        Gui::Selection().clearSelection(doc->getName());
    }
    return true;
}

#include "moc_TaskDeletePart.cpp"
