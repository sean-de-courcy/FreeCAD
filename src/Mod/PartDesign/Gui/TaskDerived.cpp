// SPDX-License-Identifier: LGPL-2.1-or-later

// Onshape's Derived dialog (FreeCAD-CH ops#640 round 6, PartDesign/App/Derived.h)

#include <algorithm>

#include <QCheckBox>
#include <QComboBox>
#include <QLabel>
#include <QListWidget>
#include <QSignalBlocker>
#include <QVBoxLayout>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentTabs.h>
#include <App/Part.h>
#include <Base/Exception.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/Document.h>
#include <Gui/DocumentTabBar.h>
#include <Gui/MDIView.h>
#include <Gui/TaskView/TaskView.h>
#include <Mod/Part/App/BodyBase.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/Derived.h>
#include <Mod/PartDesign/App/FeatureBase.h>

#include "TaskDerived.h"
#include "Utils.h"

using namespace PartDesignGui;

namespace
{
QString labelOf(const App::DocumentObject* obj)
{
    return QString::fromUtf8(obj->Label.getValue());
}

std::string studioCommand(App::Document* doc, App::Part* studio)
{
    return studio ? Gui::Command::getObjectCmd(studio)
                  : std::string("App.getDocument('") + doc->getName() + "')";
}
}  // namespace

bool PartDesignGui::activeStudio(App::Document* doc, App::Part*& studio)
{
    studio = nullptr;
    if (!doc) {
        return false;
    }
    PartDesign::Body* body = nullptr;
    App::Part* part = nullptr;
    if (auto view = Gui::Application::Instance->activeView();
        view && view->getGuiDocument() && view->getGuiDocument()->getDocument() == doc) {
        // FreeCAD-CH (ops#640, R6T-1): under the typed tabs, the studio of the view's tab
        const std::string tab = Gui::DocumentTabs::tabOfView(view);
        if (!tab.empty()) {
            if (tab == App::DocumentTabs::implicitName()) {
                return true;
            }
            App::DocumentObject* tabObject = doc->getObject(tab.c_str());
            App::DocumentTabs::Kind kind {};
            if (!App::DocumentTabs::isTabObject(tabObject, &kind)
                || kind != App::DocumentTabs::Kind::PartStudio) {
                return false;
            }
            studio = static_cast<App::Part*>(tabObject);
            return true;
        }
        body = view->getActiveObject<PartDesign::Body*>(PDBODYKEY);
        part = view->getActiveObject<App::Part*>(PARTKEY);
    }
    if (body) {
        return Part::BodyBase::studioOf(body, studio);
    }
    const Base::Type assembly = Base::Type::fromName("Assembly::AssemblyObject");
    if (part && part->getDocument() == doc && !(!assembly.isBad() && part->isDerivedFrom(assembly))) {
        studio = part;
    }
    return true;
}

TaskDlgDerived::TaskDlgDerived(App::Document* doc, App::Part* studio, PartDesign::FeatureBase* lead)
    : docName(doc->getName())
    , studioName(studio ? studio->getNameInDocument() : "")
    , leadName(lead ? lead->getNameInDocument() : "")
{
    setDocumentName(docName);
    setAutoCloseOnDeletedDocument(true);
    auto box = new Gui::TaskView::TaskBox(
        Gui::BitmapFactory().pixmap("PartDesign_SubShapeBinder"),
        lead ? QString::fromUtf8(lead->Label.getValue()) : tr("Derived"),
        true,
        nullptr
    );
    box->groupLayout()->addWidget(new QLabel(tr("Part Studio:"), box));
    studios = new QComboBox(box);
    studios->setObjectName(QStringLiteral("derivedStudio"));
    box->groupLayout()->addWidget(studios);
    all = new QCheckBox(tr("All parts"), box);
    all->setObjectName(QStringLiteral("derivedAll"));
    box->groupLayout()->addWidget(all);
    parts = new QListWidget(box);
    parts->setObjectName(QStringLiteral("derivedParts"));
    box->groupLayout()->addWidget(parts);
    message = new QLabel(box);
    message->setObjectName(QStringLiteral("derivedMessage"));
    message->setWordWrap(true);
    message->setStyleSheet(QStringLiteral("color: #d03030;"));
    message->hide();
    box->groupLayout()->addWidget(message);
    Content.push_back(box);

    // The other studios with parts; an edit opens on its sources' studio, with them ticked
    std::vector<std::string> ticked;
    App::Part* from = nullptr;
    bool fromKnown = false;
    for (auto member : PartDesign::derivedMembers(lead)) {
        if (auto source = PartDesign::derivedSource(member)) {
            ticked.emplace_back(source->getNameInDocument());
            if (!fromKnown) {
                fromKnown = Part::BodyBase::studioOf(Part::BodyBase::bodyOfObject(source), from);
            }
        }
    }
    int current = 0;
    for (App::Part* other : PartDesign::derivedStudios(doc)) {
        if (other == studio) {
            continue;
        }
        if (fromKnown && other == from) {
            current = studios->count();
        }
        studios->addItem(QString::fromUtf8(PartDesign::studioLabel(doc, other).c_str()));
        sourceNames.emplace_back(other ? other->getNameInDocument() : "");
    }
    studios->setCurrentIndex(current);
    fillParts(ticked);
    if (!lead) {
        // A new feature brings in every part until the user unticks some [guess]
        onAllClicked(true);
    }
    connect(studios, qOverload<int>(&QComboBox::currentIndexChanged), this, [this](int) {
        onStudioChanged();
    });
    connect(all, &QCheckBox::clicked, this, &TaskDlgDerived::onAllClicked);
    connect(parts, &QListWidget::itemChanged, this, &TaskDlgDerived::onItemChanged);
}

App::Document* TaskDlgDerived::document() const
{
    return App::GetApplication().getDocument(docName.c_str());
}

App::Part* TaskDlgDerived::sourceStudio() const
{
    App::Document* doc = document();
    int row = studios->currentIndex();
    if (!doc || row < 0 || row >= static_cast<int>(sourceNames.size()) || sourceNames[row].empty()) {
        return nullptr;
    }
    return freecad_cast<App::Part*>(doc->getObject(sourceNames[row].c_str()));
}

void TaskDlgDerived::fillParts(const std::vector<std::string>& ticked)
{
    QSignalBlocker block(parts);
    parts->clear();
    App::Document* doc = document();
    if (doc && studios->currentIndex() >= 0) {
        for (auto body : PartDesign::derivableParts(doc, sourceStudio())) {
            auto item = new QListWidgetItem(labelOf(body), parts);
            item->setData(Qt::UserRole, QByteArray(body->getNameInDocument()));
            item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
            const bool on = std::ranges::find(ticked, body->getNameInDocument()) != ticked.end();
            item->setCheckState(on ? Qt::Checked : Qt::Unchecked);
        }
    }
    updateAll();
}

void TaskDlgDerived::onStudioChanged()
{
    fillParts({});
    onAllClicked(true);
}

void TaskDlgDerived::onAllClicked(bool checked)
{
    {
        QSignalBlocker block(parts);
        for (int i = 0; i < parts->count(); ++i) {
            parts->item(i)->setCheckState(checked ? Qt::Checked : Qt::Unchecked);
        }
    }
    updateAll();
}

void TaskDlgDerived::onItemChanged(QListWidgetItem*)
{
    updateAll();
}

void TaskDlgDerived::updateAll()
{
    bool every = parts->count() > 0;
    bool any = false;
    for (int i = 0; i < parts->count(); ++i) {
        const bool on = parts->item(i)->checkState() == Qt::Checked;
        every = every && on;
        any = any || on;
    }
    QSignalBlocker block(all);
    all->setChecked(every);
    if (any) {
        message->hide();
    }
}

bool TaskDlgDerived::accept()
{
    App::Document* doc = document();
    if (!doc) {
        return true;
    }
    std::string bodies;
    for (int i = 0; i < parts->count(); ++i) {
        QListWidgetItem* item = parts->item(i);
        if (item->checkState() != Qt::Checked) {
            continue;
        }
        const QByteArray name = item->data(Qt::UserRole).toByteArray();
        if (auto body = doc->getObject(name.constData())) {
            bodies += (bodies.empty() ? "" : ", ") + Gui::Command::getObjectCmd(body);
        }
    }
    if (bodies.empty()) {
        message->setText(tr("Choose the parts to derive"));
        message->show();
        return false;
    }
    App::DocumentObject* lead = leadName.empty() ? nullptr : doc->getObject(leadName.c_str());
    if (!leadName.empty() && !lead) {
        return true;  // the edited feature is gone
    }
    App::Part* studio = studioName.empty() ? nullptr
                                           : freecad_cast<App::Part*>(doc->getObject(studioName.c_str()));
    Gui::Document* gdoc = Gui::Application::Instance->getDocument(doc);
    if (!gdoc) {
        return true;
    }
    gdoc->openCommand(lead ? QT_TRANSLATE_NOOP("Command", "Edit Derived") : QT_TRANSLATE_NOOP("Command", "Derived"));
    try {
        Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
        if (lead) {
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "PartDesign.editDerived(%s, [%s])",
                Gui::Command::getObjectCmd(lead).c_str(),
                bodies.c_str()
            );
        }
        else {
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "PartDesign.makeDerived(%s, [%s])",
                studioCommand(doc, studio).c_str(),
                bodies.c_str()
            );
        }
        Gui::Command::doCommand(Gui::Command::Doc, "App.getDocument('%s').recompute()", doc->getName());
        gdoc->commitCommand();
    }
    catch (const Base::Exception& e) {
        gdoc->abortCommand();
        message->setText(QString::fromUtf8(e.what()));
        message->show();
        return false;
    }
    // With no part active, the new one is, so the Features list shows the studio it went in
    if (!lead && !PartDesignGui::getBody(false, false)) {
        const auto objects = doc->getObjects();
        for (auto it = objects.rbegin(); it != objects.rend(); ++it) {
            if (PartDesign::derivedLead(*it) == *it) {
                if (auto body = PartDesign::Body::findBodyOf(*it)) {
                    PartDesignGui::makeBodyActive(body, doc);
                }
                break;
            }
        }
    }
    return true;
}

bool TaskDlgDerived::reject()
{
    return true;
}

#include "moc_TaskDerived.cpp"
