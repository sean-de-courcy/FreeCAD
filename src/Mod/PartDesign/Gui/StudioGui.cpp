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
#include <Mod/PartDesign/App/FeatureBoolean.h>
#include <Mod/PartDesign/App/FeatureSketchBased.h>
#include <Mod/PartDesign/App/Studio.h>
#include <Mod/PartDesign/App/StudioList.h>

#include "StudioGui.h"
#include "ViewProvider.h"

namespace PartDesign
{
// App/StudioList.cpp (FreeCAD-CH ops#654 P5, P6a; declared where used)
PartDesignExport std::vector<Body*> studioLivePartsAt(const StudioList* list, int index);
PartDesignExport void studioBooleanParts(const App::DocumentObject* owner,
                                         std::vector<Body*>& steps,
                                         std::vector<Body*>& tools,
                                         std::vector<Body*>& both);
}  // namespace PartDesign

namespace PartDesignGui
{

QString studioPartName(const PartDesign::Body* body);
QString studioPartNameAt(const PartDesign::Body* body, const App::DocumentObject* at);

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
                auto item = new QListWidgetItem(studioPartNameAt(body, owner), ticks);
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

/** A Boolean studio feature's parts (ops#654 P5, Onshape O3): Targets and Tools, one tick per part
 * live at its place (P6a: never a consumed or merged-away part), as Onshape's fields; Union has
 * Tools only, merged into the first ticked. Each change is a list edit
 * (PartDesign.studioSetScopeIds / studioSetToolIds) in the dialog's transaction; why the Boolean
 * fails is said under the ticks, in red.
 */
class StudioBooleanBox: public QWidget
{
public:
    explicit StudioBooleanBox(App::DocumentObject* owner)
        : ownerT(owner)
    {
        setObjectName(QStringLiteral("studioBooleanBox"));
        auto* layout = new QVBoxLayout(this);
        layout->setContentsMargins(0, 0, 0, 0);
        targetsLabel = new QLabel(trStudio("Targets:"), this);
        layout->addWidget(targetsLabel);
        targets = new QListWidget(this);
        targets->setObjectName(QStringLiteral("studioTargetList"));
        targets->setToolTip(trStudio("The parts the tools are subtracted from"));
        layout->addWidget(targets);
        toolsLabel = new QLabel(trStudio("Tools:"), this);
        layout->addWidget(toolsLabel);
        tools = new QListWidget(this);
        tools->setObjectName(QStringLiteral("studioToolList"));
        layout->addWidget(tools);
        note = new QLabel(this);
        note->setObjectName(QStringLiteral("studioBooleanNote"));
        note->setWordWrap(true);
        layout->addWidget(note);
        refresh();
        QObject::connect(targets, &QListWidget::itemChanged, this, [this](QListWidgetItem* item) {
            onTicked(item, false);
        });
        QObject::connect(tools, &QListWidget::itemChanged, this, [this](QListWidgetItem* item) {
            onTicked(item, true);
        });
    }

    void refresh()
    {
        auto owner = freecad_cast<PartDesign::Boolean*>(ownerT.getObject());
        if (!owner) {
            return;
        }
        updating = true;
        const bool fuse = std::string(owner->Type.getValueAsString()) == "Fuse";
        const auto live = liveStudioParts(owner);
        auto fill = [&live, owner](QListWidget* list, const std::vector<std::string>& ids) {
            QSignalBlocker block(list);
            list->clear();
            for (PartDesign::Body* body : live) {
                const std::string id = PartDesign::studioPartId(body);
                auto item = new QListWidgetItem(studioPartNameAt(body, owner), list);
                item->setData(Qt::UserRole, QString::fromStdString(id));
                item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsUserCheckable);
                item->setCheckState(
                    std::ranges::find(ids, id) != ids.end() ? Qt::Checked : Qt::Unchecked
                );
            }
        };
        fill(targets, PartDesign::studioScopeIds(owner));
        fill(tools, owner->StudioTools.getValues());
        targetsLabel->setVisible(!fuse);
        targets->setVisible(!fuse);
        tools->setToolTip(fuse ? trStudio("The parts merged, into the first one ticked")
                               : trStudio("The parts subtracted from the targets"));
        QString text = refusal;
        if (text.isEmpty() && owner->isError()) {
            text = QString::fromUtf8(owner->getStatusString());
        }
        if (text.isEmpty()) {
            for (auto step : PartDesign::StudioList::stepsOf(owner)) {
                if (step->isError()) {
                    text = QString::fromUtf8(step->getStatusString());
                    break;
                }
            }
        }
        std::vector<PartDesign::Body*> steps;
        std::vector<PartDesign::Body*> toolParts;
        std::vector<PartDesign::Body*> both;
        PartDesign::studioBooleanParts(owner, steps, toolParts, both);
        QString info;
        if (fuse && !steps.empty()) {
            info = trStudio("Merged into %1").arg(studioPartNameAt(steps.front(), owner));
        }
        note->setText(text.isEmpty() ? info : text);
        note->setStyleSheet(text.isEmpty() ? QString() : QStringLiteral("color: #d32f2f;"));
        note->setVisible(!note->text().isEmpty());
        updating = false;
    }

    /// Runs the Python edits in the dialog's transaction, then computes the Boolean again
    void run(const std::vector<std::string>& commands)
    {
        refusal.clear();
        try {
            Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
            for (const auto& command : commands) {
                Gui::Command::doCommand(Gui::Command::Doc, "%s", command.c_str());
            }
        }
        catch (const Base::Exception& e) {
            refusal = QString::fromUtf8(e.what());
        }
        if (auto owner = freecad_cast<PartDesign::Feature*>(ownerT.getObject())) {
            try {
                owner->recomputeFeature();
            }
            catch (const Base::Exception& e) {
                e.reportException();
            }
        }
        // After the signal that called it: the lists are rebuilt
        QPointer<StudioBooleanBox> self(this);
        QMetaObject::invokeMethod(
            this,
            [self]() {
                if (self) {
                    self->refresh();
                }
            },
            Qt::QueuedConnection
        );
    }

    /// Type (Fuse, Cut, Common) and Keep tools set; a Union lists its targets first among its
    /// tools, and a Subtract takes the first of a Union's parts as its target
    void setType(const std::string& type)
    {
        auto owner = freecad_cast<PartDesign::Boolean*>(ownerT.getObject());
        if (!owner) {
            return;
        }
        const std::string cmd = Gui::Command::getObjectCmd(owner);
        auto scope = PartDesign::studioScopeIds(owner);
        auto toolIds = owner->StudioTools.getValues();
        const bool wasFuse = std::string(owner->Type.getValueAsString()) == "Fuse";
        std::vector<std::string> commands {cmd + ".Type = '" + type + "'"};
        if (type == "Fuse" && !wasFuse) {
            for (const auto& id : toolIds) {
                if (std::ranges::find(scope, id) == scope.end()) {
                    scope.push_back(id);
                }
            }
            toolIds = scope;
            scope.clear();
        }
        else if (type != "Fuse" && wasFuse && scope.empty() && !toolIds.empty()) {
            scope = {toolIds.front()};
            toolIds.erase(toolIds.begin());
        }
        commands.push_back("PartDesign.studioSetScopeIds(" + cmd + ", " + pyList(scope) + ")");
        commands.push_back("PartDesign.studioSetToolIds(" + cmd + ", " + pyList(toolIds) + ")");
        run(commands);
    }

    void setKeepTools(bool on)
    {
        auto owner = ownerT.getObject();
        if (!owner) {
            return;
        }
        const std::string cmd = Gui::Command::getObjectCmd(owner);
        const auto list = PartDesign::StudioList::holding(owner);
        run({cmd + ".KeepTools = " + (on ? "True" : "False"),
             std::string("PartDesign.studioReconcile(App.getDocument('")
                 + owner->getDocument()->getName() + "').getObject('"
                 + (list ? list->getNameInDocument() : "") + "'))"});
    }

private:
    void onTicked(QListWidgetItem* item, bool tool)
    {
        auto owner = freecad_cast<PartDesign::Boolean*>(ownerT.getObject());
        if (updating || !owner || !item) {
            return;
        }
        const std::string id = item->data(Qt::UserRole).toString().toStdString();
        const bool on = item->checkState() == Qt::Checked;
        auto ids = tool ? owner->StudioTools.getValues() : PartDesign::studioScopeIds(owner);
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
        const std::string cmd = Gui::Command::getObjectCmd(owner);
        run({std::string(tool ? "PartDesign.studioSetToolIds(" : "PartDesign.studioSetScopeIds(")
             + cmd + ", " + pyList(ids) + ")"});
    }

    App::DocumentObjectT ownerT;
    QLabel* targetsLabel = nullptr;
    QListWidget* targets = nullptr;
    QLabel* toolsLabel = nullptr;
    QListWidget* tools = nullptr;
    QLabel* note = nullptr;
    QString refusal;
    bool updating = false;
};

}  // namespace

namespace
{
/// studioPartName() among live, the parts live where the name is shown
QString partNameAmong(const PartDesign::Body* body, const std::vector<PartDesign::Body*>& live)
{
    const QString label = body ? QString::fromUtf8(body->Label.getValue()) : QString();
    const QString prefix = QCoreApplication::translate("QObject", "Part %1").arg(QString());
    auto isDefault = [&prefix](const QString& text) {
        if (!text.startsWith(prefix) || text.size() == prefix.size()) {
            return false;
        }
        bool ok = false;
        text.mid(prefix.size()).toInt(&ok);
        return ok;
    };
    if (!body || !isDefault(label)) {
        return label;
    }
    if (std::ranges::find(live, body) == live.end()) {
        return label;
    }
    std::set<QString> typed;
    for (auto part : live) {
        const QString text = QString::fromUtf8(part->Label.getValue());
        if (!isDefault(text)) {
            typed.insert(text);
        }
    }
    int n = 0;
    QString name;
    for (auto part : live) {
        if (!isDefault(QString::fromUtf8(part->Label.getValue()))) {
            continue;
        }
        do {
            name = QCoreApplication::translate("QObject", "Part %1").arg(++n);
        } while (typed.count(name));
        if (part == body) {
            return name;
        }
    }
    return label;
}
}  // namespace

/// The name a part shows in lists (P6a): its label; in a listed studio a default name ("Part N")
/// is positional, as Onshape renumbers default names when a part goes (O9): the parts live at the
/// bar with default names, in the studio's order, take the lowest numbers no typed name has
QString studioPartName(const PartDesign::Body* body)
{
    App::Part* studio = nullptr;
    const PartDesign::StudioList* list = nullptr;
    if (body && Part::BodyBase::studioOf(body, studio)) {
        list = PartDesign::StudioList::of(body->getDocument(), studio);
    }
    if (!list) {
        return body ? QString::fromUtf8(body->Label.getValue()) : QString();
    }
    return partNameAmong(body, PartDesign::studioLivePartsAt(list, -1));
}

/// studioPartName() where at is in the history (a dialog's list of parts): numbered among the
/// parts live just before at
QString studioPartNameAt(const PartDesign::Body* body, const App::DocumentObject* at)
{
    if (!at || !PartDesign::StudioList::holding(at)) {
        return studioPartName(body);
    }
    return partNameAmong(body, liveStudioParts(at));
}

QWidget* makeStudioBooleanBox(App::DocumentObject* owner)
{
    if (!freecad_cast<PartDesign::Boolean*>(owner) || !PartDesign::isStudioOwner(owner)) {
        return nullptr;
    }
    return new StudioBooleanBox(owner);
}

void studioBooleanBoxSetType(QWidget* box, const char* type)
{
    if (auto booleanBox = dynamic_cast<StudioBooleanBox*>(box)) {
        booleanBox->setType(type);
    }
}

void studioBooleanBoxSetKeepTools(QWidget* box, bool on)
{
    if (auto booleanBox = dynamic_cast<StudioBooleanBox*>(box)) {
        booleanBox->setKeepTools(on);
    }
}

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
    // In a listed studio, the App's query (P6a): live just before at's place, so no part merged
    // away, consumed by a Boolean before it, or made by it or later
    if (const PartDesign::StudioList* list = PartDesign::StudioList::holding(at)) {
        const auto& entries = list->Entries.getValues();
        const auto it = std::ranges::find(entries, at);
        return PartDesign::studioLivePartsAt(list, static_cast<int>(it - entries.begin()));
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
