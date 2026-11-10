// SPDX-License-Identifier: LGPL-2.1-or-later

// Gui helpers for studio features (FreeCAD-CH ops#654): the parts live at an owner's place, and
// the owner's Result box in its extrude-family dialog (S4, notes/parts-design.md 3.5).

#include <algorithm>
#include <map>
#include <set>
#include <sstream>

#include <QComboBox>
#include <QCoreApplication>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QPointer>
#include <QSignalBlocker>
#include <QVBoxLayout>

#include <App/Document.h>
#include <App/DocumentObserver.h>
#include <App/Part.h>
#include <App/PropertyStandard.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/TaskView/TaskView.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/Feature.h>
#include <Mod/PartDesign/App/FeatureAddSub.h>
#include <Mod/PartDesign/App/FeatureSketchBased.h>
#include <Mod/PartDesign/App/Studio.h>
#include <Mod/PartDesign/App/StudioList.h>

#include "StudioGui.h"
#include "ViewProvider.h"

namespace PartDesignGui
{

namespace
{

QString trStudio(const char* text)
{
    return QCoreApplication::translate("PartDesignGui::TaskStudioResult", text);
}

/// The studio of obj: its list's, else the App::Part of its Body (null: the top level)
App::Part* studioOfEntry(const App::DocumentObject* obj, bool& ok)
{
    ok = true;
    if (const PartDesign::StudioList* list = PartDesign::StudioList::holding(obj)) {
        return list->studio();
    }
    App::Part* studio = nullptr;
    if (auto body = PartDesign::Body::findBodyOf(obj)) {
        ok = Part::BodyBase::studioOf(body, studio);
        return studio;
    }
    return App::Part::getPartOfObject(obj, /*recursive=*/true);
}

/// The Bodies of the document whose part id is one of ids
std::vector<PartDesign::Body*> bodiesWithIds(App::Document* doc, const std::vector<std::string>& ids)
{
    std::vector<PartDesign::Body*> out;
    for (auto obj : doc->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        auto body = static_cast<PartDesign::Body*>(obj);
        if (std::ranges::find(ids, PartDesign::studioPartId(body)) != ids.end()) {
            out.push_back(body);
        }
    }
    return out;
}

/// The parts owner made (a New result)
std::vector<PartDesign::Body*> partsMadeBy(const App::DocumentObject* owner)
{
    std::vector<PartDesign::Body*> out;
    if (!owner || !owner->getDocument()) {
        return out;
    }
    for (auto obj : owner->getDocument()->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        auto body = static_cast<PartDesign::Body*>(obj);
        if (body->StudioMadeBy.getValue() == owner) {
            out.push_back(body);
        }
    }
    return out;
}

/// A New result: the scope is parts owner made, and nothing else
bool isNewResult(const App::DocumentObject* owner)
{
    const auto ids = PartDesign::studioScopeIds(owner);
    if (ids.empty()) {
        return false;
    }
    const auto bodies = bodiesWithIds(owner->getDocument(), ids);
    return bodies.size() == ids.size() && std::ranges::all_of(bodies, [owner](PartDesign::Body* body) {
               return body->StudioMadeBy.getValue() == owner;
           });
}

std::string operationOf(const App::DocumentObject* owner)
{
    auto addSub = freecad_cast<const PartDesign::FeatureAddSub*>(owner);
    const char* value = addSub ? addSub->Operation.getValueAsString() : nullptr;
    return value ? value : "Union";
}

/// A Python list of strings
std::string pyList(const std::vector<std::string>& values)
{
    std::ostringstream ss;
    ss << "[";
    for (const auto& value : values) {
        std::string escaped;
        for (char c : value) {
            if (c == '\'' || c == '\\') {
                escaped += '\\';
            }
            escaped += c;
        }
        ss << "'" << escaped << "',";
    }
    ss << "]";
    return ss.str();
}

/** The owner's Result box (ops#654 S4, parts-design 3.5): New / Add / Remove / Intersect and one
 * tick per live part of the studio, the profile's own part included, any of which can be cleared
 * (report 21). Each change is a list edit (PartDesign.studioSetScopeIds, studioNewPart) in the
 * dialog's transaction; a refusal is said under the ticks and the box shows the owner as it is.
 * Operation stays the owner's: Union (Add, or New when the scope is parts it made), Subtraction
 * (Remove), Common (Intersect).
 */
class TaskStudioResult: public Gui::TaskView::TaskBox
{
public:
    explicit TaskStudioResult(ViewProvider* vp)
        : TaskBox(Gui::BitmapFactory().pixmap("PartDesign_Body"), trStudio("Result"), true, nullptr)
        , ownerT(vp->getObject())
    {
        auto* proxy = new QWidget(this);
        auto* layout = new QHBoxLayout(proxy);
        layout->setContentsMargins(0, 0, 0, 0);
        layout->addWidget(new QLabel(trStudio("Result:"), proxy));
        combo = new QComboBox(proxy);
        combo->setObjectName(QStringLiteral("resultCombo"));
        // Onshape's words and order
        combo->addItem(trStudio("New"), QStringLiteral("new"));
        combo->addItem(trStudio("Add"), QStringLiteral("add"));
        combo->addItem(trStudio("Remove"), QStringLiteral("remove"));
        combo->addItem(trStudio("Intersect"), QStringLiteral("intersect"));
        layout->addWidget(combo, 1);
        groupLayout()->addWidget(proxy);

        scopeLabel = new QLabel(trStudio("Parts:"), this);
        groupLayout()->addWidget(scopeLabel);
        ticks = new QListWidget(this);
        ticks->setObjectName(QStringLiteral("studioScopeList"));
        ticks->setToolTip(trStudio("The parts this feature acts on"));
        groupLayout()->addWidget(ticks);
        note = new QLabel(this);
        note->setObjectName(QStringLiteral("studioScopeNote"));
        note->setWordWrap(true);
        note->setVisible(false);
        groupLayout()->addWidget(note);

        if (App::DocumentObject* owner = ownerT.getObject()) {
            if (isNewResult(owner)) {
                // An edit that leaves New for Add starts from the profile's part
                scopeBeforeNew = defaultScope(owner);
            }
        }
        refresh();
        QObject::connect(combo, qOverload<int>(&QComboBox::currentIndexChanged), this, [this](int index) {
            onResultChanged(index);
        });
        QObject::connect(ticks, &QListWidget::itemChanged, this, [this](QListWidgetItem* item) {
            onTicked(item);
        });
    }

private:
    /// The profile's own part, if it is a live part at the owner's place
    std::vector<std::string> defaultScope(App::DocumentObject* owner) const
    {
        auto profileBased = freecad_cast<PartDesign::ProfileBased*>(owner);
        App::DocumentObject* profile = profileBased ? profileBased->Profile.getValue() : nullptr;
        PartDesign::Body* body = profile ? PartDesign::Body::findBodyOf(profile) : nullptr;
        const auto live = liveStudioParts(owner);
        if (body && std::ranges::find(live, body) != live.end()) {
            return {PartDesign::studioPartId(body)};
        }
        return {};
    }

    void refresh()
    {
        App::DocumentObject* owner = ownerT.getObject();
        if (!owner) {
            return;
        }
        updating = true;
        const bool isNew = isNewResult(owner);
        const std::string op = operationOf(owner);
        int index = 1;
        if (isNew) {
            index = 0;
        }
        else if (op == "Subtraction") {
            index = 2;
        }
        else if (op == "Common") {
            index = 3;
        }
        {
            QSignalBlocker block(combo);
            combo->setCurrentIndex(index);
        }
        const auto ids = PartDesign::studioScopeIds(owner);
        {
            QSignalBlocker block(ticks);
            ticks->clear();
            for (PartDesign::Body* body : liveStudioParts(owner)) {
                const std::string id = PartDesign::studioPartId(body);
                auto item = new QListWidgetItem(QString::fromUtf8(body->Label.getValue()), ticks);
                item->setData(Qt::UserRole, QString::fromStdString(id));
                item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsUserCheckable);
                item->setCheckState(
                    std::ranges::find(ids, id) != ids.end() ? Qt::Checked : Qt::Unchecked
                );
            }
        }
        scopeLabel->setVisible(!isNew);
        ticks->setVisible(!isNew);
        QString text = refusal;
        if (text.isEmpty() && !isNew && PartDesign::studioScopeOf(owner).empty()) {
            // Onshape's words for an empty merge scope
            text = trStudio("No merge scope selected");
        }
        note->setText(text);
        note->setStyleSheet(text.isEmpty() ? QString() : QStringLiteral("color: #d32f2f;"));
        note->setVisible(!text.isEmpty());
        updating = false;
    }

    /// Runs the Python edits in the dialog's transaction; false with refusal set
    bool run(const std::vector<std::string>& commands)
    {
        refusal.clear();
        try {
            Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
            for (const auto& command : commands) {
                Gui::Command::doCommand(Gui::Command::Doc, "%s", command.c_str());
            }
            return true;
        }
        catch (const Base::Exception& e) {
            refusal = QString::fromUtf8(e.what());
        }
        catch (const std::exception& e) {
            refusal = QString::fromUtf8(e.what());
        }
        return false;
    }

    /// The owner computes its tool again, and a New part's step its solid (the other parts are
    /// rolled back before the owner while the dialog is open)
    void recompute()
    {
        auto owner = freecad_cast<PartDesign::Feature*>(ownerT.getObject());
        if (!owner) {
            return;
        }
        try {
            owner->recomputeFeature();
            owner->recomputePreview();
            for (PartDesign::Body* body : partsMadeBy(owner)) {
                if (auto step = PartDesign::StudioList::stepOf(owner, body)) {
                    step->recomputeFeature();
                }
            }
        }
        catch (const Base::Exception& e) {
            e.reportException();
        }
    }

    void onResultChanged(int index)
    {
        App::DocumentObject* owner = ownerT.getObject();
        if (updating || !owner) {
            return;
        }
        const std::string ownerCmd = Gui::Command::getObjectCmd(owner);
        const bool wasNew = isNewResult(owner);
        std::vector<std::string> commands;
        if (index == 0) {
            if (wasNew) {
                return;
            }
            scopeBeforeNew = PartDesign::studioScopeIds(owner);
            commands.push_back("PartDesign.studioSetScopeIds(" + ownerCmd + ", [])");
            commands.push_back("PartDesign.studioNewPart(" + ownerCmd + ")");
        }
        else {
            const char* ops[] = {"Union", "Union", "Subtraction", "Common"};
            commands.push_back(ownerCmd + ".Operation = '" + ops[index] + "'");
            if (!wasNew) {
                // The steps take the operation from the owner at reconcile
                commands.push_back(
                    "PartDesign.studioSetScopeIds(" + ownerCmd + ", "
                    + pyList(PartDesign::studioScopeIds(owner)) + ")"
                );
            }
            else {
                // Back to the parts it had, the made part goes
                std::vector<std::string> ids;
                const auto live = liveStudioParts(owner);
                for (const auto& id : scopeBeforeNew) {
                    for (auto body : live) {
                        if (PartDesign::studioPartId(body) == id) {
                            ids.push_back(id);
                        }
                    }
                }
                if (ids.empty()) {
                    ids = defaultScope(owner);
                }
                commands.push_back("PartDesign.studioSetScopeIds(" + ownerCmd + ", " + pyList(ids) + ")");
                for (PartDesign::Body* body : partsMadeBy(owner)) {
                    const std::string bodyCmd = Gui::Command::getObjectCmd(body);
                    commands.push_back(bodyCmd + ".removeObjectsFromDocument()");
                    commands.push_back(
                        std::string("App.getDocument('") + owner->getDocument()->getName()
                        + "').removeObject('"
                        + body->getNameInDocument() + "')"
                    );
                }
            }
        }
        run(commands);
        recompute();
        refresh();
    }

    void onTicked(QListWidgetItem* item)
    {
        App::DocumentObject* owner = ownerT.getObject();
        if (updating || !owner || !item) {
            return;
        }
        const std::string id = item->data(Qt::UserRole).toString().toStdString();
        const bool on = item->checkState() == Qt::Checked;
        auto ids = PartDesign::studioScopeIds(owner);
        auto at = std::ranges::find(ids, id);
        if (on && at == ids.end()) {
            ids.push_back(id);
        }
        else if (!on && at != ids.end()) {
            ids.erase(at);
        }
        else {
            return;
        }
        run({"PartDesign.studioSetScopeIds(" + Gui::Command::getObjectCmd(owner) + ", "
             + pyList(ids) + ")"});
        recompute();
        // After the itemChanged signal: the list is rebuilt
        QPointer<QListWidget> list(ticks);
        QMetaObject::invokeMethod(
            this,
            [this, list]() {
                if (list) {
                    refresh();
                }
            },
            Qt::QueuedConnection
        );
    }

    App::DocumentObjectT ownerT;
    QComboBox* combo = nullptr;
    QLabel* scopeLabel = nullptr;
    QListWidget* ticks = nullptr;
    QLabel* note = nullptr;
    QString refusal;
    std::vector<std::string> scopeBeforeNew;
    bool updating = false;
};

}  // namespace

std::vector<PartDesign::Body*> liveStudioParts(const App::DocumentObject* at)
{
    std::vector<PartDesign::Body*> out;
    if (!at || !at->getDocument()) {
        return out;
    }
    bool ok = true;
    App::Part* studio = studioOfEntry(at, ok);
    if (!ok) {
        return out;
    }
    // Places in the list (as the App's scope resolution reads them): a part made by an entry at
    // or after at's place isn't there yet; a part merged into another isn't a part any more
    std::map<const App::DocumentObject*, int> positions;
    int index = -1;
    if (const PartDesign::StudioList* list = PartDesign::StudioList::holding(at)) {
        const auto& entries = list->Entries.getValues();
        for (std::size_t i = 0; i < entries.size(); ++i) {
            positions.emplace(entries[i], static_cast<int>(i));
            if (entries[i] == at) {
                index = static_cast<int>(i);
            }
        }
        if (index < 0) {
            index = static_cast<int>(entries.size());
        }
    }
    for (PartDesign::Body* body : PartDesign::studioBodies(at->getDocument(), studio)) {
        auto merged = freecad_cast<App::PropertyLink*>(body->getPropertyByName("MergedInto"));
        if (merged && merged->getValue()) {
            continue;
        }
        if (App::DocumentObject* madeBy = body->StudioMadeBy.getValue()) {
            if (madeBy == at) {
                continue;
            }
            auto it = positions.find(madeBy);
            if (index >= 0 && it != positions.end() && it->second > index) {
                continue;
            }
        }
        out.push_back(body);
    }
    return out;
}

bool rollStudioToOwner(App::DocumentObject* /*owner*/, std::string* why)
{
    // The roll-back of an owner's dialog is the Bodies' own edit roll-back
    // (ViewProviderBody::onInEdit, studioOwnerEditPointFor)
    if (why) {
        *why = "the Bodies roll back with the owner's edit";
    }
    return false;
}

void endStudioOwnerRollBack(App::DocumentObject* /*owner*/)
{}

QWidget* makeStudioResultBox(ViewProvider* vp)
{
    if (!vp || !PartDesign::isStudioOwner(vp->getObject())) {
        return nullptr;
    }
    return new TaskStudioResult(vp);
}

}  // namespace PartDesignGui
