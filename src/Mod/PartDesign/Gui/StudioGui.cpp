// SPDX-License-Identifier: LGPL-2.1-or-later

// Gui helpers for studio features (FreeCAD-CH ops#654): the parts live at an owner's place, and
// the owner's Result box in its extrude-family dialog (S4, notes/parts-design.md 3.5).

#include <algorithm>
#include <cstring>
#include <map>
#include <set>
#include <sstream>

#include <QCheckBox>
#include <QComboBox>
#include <QCoreApplication>
#include <QEvent>
#include <QFont>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QPointer>
#include <QPushButton>
#include <QSignalBlocker>
#include <QStringList>
#include <QVBoxLayout>

#include <BRepExtrema_DistShapeShape.hxx>
#include <Precision.hxx>
#include <TopAbs_ShapeEnum.hxx>

#include <App/Datums.h>
#include <App/Document.h>
#include <App/DocumentObserver.h>
#include <App/Part.h>
#include <App/PropertyStandard.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Tools.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>
#include <Gui/Control.h>
#include <Gui/Selection/Selection.h>
#include <Gui/TaskView/TaskDialog.h>
#include <Gui/TaskView/TaskView.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/Feature.h>
#include <Mod/PartDesign/App/FeatureAddSub.h>
#include <Mod/PartDesign/App/Pieces.h>
#include <Mod/PartDesign/App/FeatureApply.h>
#include <Mod/PartDesign/App/FeatureBoolean.h>
#include <Mod/PartDesign/App/FeaturePad.h>
#include <Mod/PartDesign/App/FeaturePocket.h>
#include <Mod/PartDesign/App/FeatureSketchBased.h>
#include <Mod/PartDesign/App/FeatureTransformed.h>
#include <Mod/PartDesign/App/Studio.h>
#include <Mod/PartDesign/App/StudioList.h>

#include "StudioGui.h"
#include "TaskFeatureParameters.h"
#include "ViewProvider.h"

namespace PartDesign
{
// App/StudioList.cpp (FreeCAD-CH ops#654 P5, P6a; declared where used)
PartDesignExport std::vector<Body*> studioLivePartsAt(const StudioList* list, int index);
PartDesignExport void studioBooleanParts(const App::DocumentObject* owner,
                                         std::vector<Body*>& steps,
                                         std::vector<Body*>& tools,
                                         std::vector<Body*>& both);
// App/Pieces.cpp (FreeCAD-CH ops#654 10.13): the contact test of an Add's merge, its leftovers
// and this pre-fill
PartDesignExport bool studioSolidsJoin(const TopoDS_Shape& a, const TopoDS_Shape& b);
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
    const char* value = nullptr;
    if (auto addSub = freecad_cast<const PartDesign::FeatureAddSub*>(owner)) {
        value = addSub->Operation.getValueAsString();
    }
    else if (owner) {
        // A part mirror's (slice 9): a dynamic enumeration of the same words
        auto prop = dynamic_cast<App::PropertyEnumeration*>(owner->getPropertyByName("Operation"));
        value = prop ? prop->getValueAsString() : nullptr;
    }
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

/// part's solid just before owner's place in the list, in the document's frame (as the App's
/// studioBaseAt reads a scope part's): its last solid feature whose own place, or its owner's
/// for a step, comes before owner's. Null when it has none there
Part::TopoShape partSolidBefore(const App::DocumentObject* owner, const PartDesign::Body* part)
{
    const PartDesign::StudioList* list = PartDesign::StudioList::holding(owner);
    if (!list || !part) {
        return {};
    }
    const auto& entries = list->Entries.getValues();
    auto placeOf = [&entries](const App::DocumentObject* obj) {
        auto it = std::ranges::find(entries, obj);
        return it == entries.end() ? -1 : static_cast<int>(it - entries.begin());
    };
    const int at = placeOf(owner);
    if (at < 0) {
        return {};
    }
    const Part::Feature* last = nullptr;
    int key = -1;
    for (App::DocumentObject* obj : part->Group.getValues()) {
        int here = placeOf(obj);
        if (here < 0) {
            if (auto feature = freecad_cast<PartDesign::Feature*>(obj)) {
                here = placeOf(feature->StudioOwner.getValue());
            }
        }
        if (here >= 0) {
            key = here;  // else the place of the member before it
        }
        if (key >= at || !PartDesign::Body::isSolidFeature(obj)) {
            continue;
        }
        auto feature = static_cast<const Part::Feature*>(obj);
        const Part::TopoShape& shape = feature->Shape.getShape();
        if (!shape.isNull() && shape.hasSubShape(TopAbs_SOLID)) {
            last = feature;  // a failed feature contributes nothing (parts-design 10.9)
        }
    }
    if (!last) {
        return {};
    }
    Part::TopoShape shape = last->Shape.getShape();
    shape.transformShape(part->globalPlacement().toMatrix(), false, true);
    return shape;
}

/** The live parts at owner's place that its tool touches or intersects (face contact counts, an
 * edge or a vertex in common doesn't: the compute's own test, ops#654 10.13 skeptic 3): false
 * when it has no tool. A tool its last recompute didn't keep (an Add touching no part of
 * its scope, an empty scope) is computed for this and dropped again.
 */
bool toolContacts(App::DocumentObject* owner, std::vector<PartDesign::Body*>& out)
{
    out.clear();
    auto addSub = freecad_cast<PartDesign::FeatureAddSub*>(owner);
    if (!addSub) {
        return false;
    }
    Part::TopoShape tool = PartDesign::FeatureApply::toolOf(owner);
    if (tool.isNull()) {
        App::DocumentObjectExecReturn* result = nullptr;
        try {
            if (auto pad = freecad_cast<PartDesign::Pad*>(owner)) {
                result = pad->execute();
            }
            else if (auto pocket = freecad_cast<PartDesign::Pocket*>(owner)) {
                result = pocket->execute();
            }
            if (result == App::DocumentObject::StdReturn) {
                tool = PartDesign::FeatureApply::toolOf(owner);
            }
        }
        catch (...) {
            tool = Part::TopoShape();
        }
        if (result && result != App::DocumentObject::StdReturn) {
            delete result;
        }
        if (!addSub->AddSubShape.getShape().isNull()) {
            addSub->AddSubShape.setValue(Part::TopoShape());
        }
        if (tool.isNull()) {
            return false;
        }
    }
    const auto toolSolids = tool.getSubTopoShapes(TopAbs_SOLID);
    if (toolSolids.empty()) {
        return false;
    }
    for (PartDesign::Body* body : liveStudioParts(owner)) {
        const Part::TopoShape solid = partSolidBefore(owner, body);
        if (solid.isNull()) {
            continue;
        }
        bool touches = false;
        for (const auto& partSolid : solid.getSubTopoShapes(TopAbs_SOLID)) {
            for (const auto& toolSolid : toolSolids) {
                if (PartDesign::studioSolidsJoin(toolSolid.getShape(), partSolid.getShape())) {
                    touches = true;
                    break;
                }
            }
            if (touches) {
                break;
            }
        }
        if (touches) {
            out.push_back(body);
        }
    }
    return true;
}

/// The owners whose dialog picks the operation live (a new Extrude, until the person chooses)
std::vector<App::DocumentObjectT> livePrefill;

/// The members of the parts owner made that come after its step there, by name (a later step by
/// its studio feature's)
QStringList laterFeatures(const App::DocumentObject* owner, const std::vector<PartDesign::Body*>& made)
{
    QStringList names;
    for (PartDesign::Body* body : made) {
        PartDesign::Feature* own = PartDesign::StudioList::stepOf(owner, body);
        for (App::DocumentObject* obj : body->Group.getValues()) {
            if (!obj || obj == own) {
                continue;
            }
            const App::DocumentObject* named = obj;
            if (auto feature = freecad_cast<PartDesign::Feature*>(obj)) {
                if (App::DocumentObject* by = feature->StudioOwner.getValue()) {
                    named = by;
                }
            }
            const QString name = QString::fromUtf8(named->Label.getValue());
            if (!names.contains(name)) {
                names.append(name);
            }
        }
    }
    return names;
}

/** The owner's Result box (ops#654 S4, parts-design 3.5): New / Add / Remove / Intersect and one
 * tick per live part of the studio, any of which can be cleared (report 21). With two or more
 * ticked, each ticked row is numbered in the scope's order ("1 Part 2"): an Add that joins them
 * keeps the first (10.13, Onshape O9b). Merge with all (StudioMergeAll, off by default as
 * Onshape's Q1 shows it): the scope is every live part at its place, ordered by each part's first
 * feature in the history (M3), its ticks greyed. Each change is a list
 * edit (PartDesign.studioSetScopeIds, studioNewPart) in the dialog's transaction; a refusal is said
 * under the ticks and the box shows the owner as it is. Operation stays the owner's: Union (Add,
 * or New when the scope is parts it made), Subtraction (Remove), Common (Intersect).
 *
 * Onshape's Extrude (oracle 6, batch 6 Q1): while the person has chosen neither an operation nor a
 * tick, a new Extrude's box picks the operation live from what the tool meets at its current
 * values: exactly one live part touched or intersected -> Add, scope that part; none, or two or
 * more -> New. A hand switch from New leaves the scope empty (the feature fails loudly, "No merge
 * scope selected"); Add -> Remove keeps the scope. Remove flips the direction (into the material),
 * and leaving it flips back (Intersect flips with Remove, as the Body path's ops#640 H4).
 * Leaving New deletes the part it made, unless that part has later features: then the switch is
 * refused, loudly (Onshape keeps or merges it, Q2: not done here).
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

        mergeAll = new QCheckBox(trStudio("Merge with all"), this);
        mergeAll->setObjectName(QStringLiteral("studioMergeAll"));
        mergeAll->setToolTip(trStudio("The feature acts on every part at its place in the history"));
        groupLayout()->addWidget(mergeAll);
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
            auto it = std::ranges::find(livePrefill, ownerT);
            if (it != livePrefill.end()) {
                livePrefill.erase(it);
                live = true;
            }
            // Every recompute of the tool: the live pick again, after the event
            toolChanged = owner->getDocument()->signalChangedObject.connect(
                [this](const App::DocumentObject& obj, const App::Property& prop) {
                    auto addSub = freecad_cast<const PartDesign::FeatureAddSub*>(&obj);
                    if (live && !deciding && addSub && &prop == &addSub->AddSubShape
                        && &obj == ownerT.getObject()) {
                        scheduleDecision();
                    }
                }
            );
        }
        refresh();
        QObject::connect(combo, qOverload<int>(&QComboBox::currentIndexChanged), this, [this](int index) {
            onResultChanged(index);
        });
        QObject::connect(ticks, &QListWidget::itemChanged, this, [this](QListWidgetItem* item) {
            onTicked(item);
        });
        QObject::connect(mergeAll, &QCheckBox::toggled, this, [this](bool on) {
            onMergeAll(on);
        });
    }

private:
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
        const bool all = mergesWithAll(owner);
        // The scope's order: its ticks', or with Merge with all the App's resolved order
        std::vector<std::string> ids = PartDesign::studioScopeIds(owner);
        if (all) {
            ids.clear();
            for (PartDesign::Body* body : PartDesign::studioScopeOf(owner)) {
                ids.push_back(PartDesign::studioPartId(body));
            }
        }
        {
            QSignalBlocker block(mergeAll);
            mergeAll->setChecked(all);
        }
        {
            QSignalBlocker block(ticks);
            ticks->clear();
            const auto parts = liveStudioParts(owner);
            std::vector<std::string> ticked;  // the ticked rows' ids, in the scope's order
            for (const auto& id : ids) {
                if (std::ranges::any_of(parts, [&id](PartDesign::Body* body) {
                        return PartDesign::studioPartId(body) == id;
                    })
                    && std::ranges::find(ticked, id) == ticked.end()) {
                    ticked.push_back(id);
                }
            }
            for (PartDesign::Body* body : parts) {
                const std::string id = PartDesign::studioPartId(body);
                const auto at = std::ranges::find(ticked, id);
                QString label = studioPartNameAt(body, owner);
                if (ticked.size() >= 2 && at != ticked.end()) {
                    label = QStringLiteral("%1 %2").arg(at - ticked.begin() + 1).arg(label);
                }
                auto item = new QListWidgetItem(label, ticks);
                item->setData(Qt::UserRole, QString::fromStdString(id));
                item->setFlags(
                    all ? Qt::ItemFlags(Qt::ItemIsUserCheckable)
                        : Qt::ItemFlags(Qt::ItemIsEnabled | Qt::ItemIsUserCheckable)
                );
                item->setCheckState(at != ticked.end() ? Qt::Checked : Qt::Unchecked);
            }
        }
        mergeAll->setVisible(!isNew);
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

    /// Whether the owner's end follows its direction (Blind, Through all, Up to next/last): a
    /// face or a shape fixes the side itself (the Body path's rule, ops#640 H4)
    static bool directionBound(const App::DocumentObject* owner)
    {
        auto type = dynamic_cast<App::PropertyEnumeration*>(owner->getPropertyByName("Type"));
        const char* value = type ? type->getValueAsString() : nullptr;
        const std::string name = value ? value : "";
        return name == "Length" || name == "ThroughAll" || name == "UpToLast" || name == "UpToFirst";
    }

    /// The extrude panel's Reversed switch shows the owner's (its OK writes the switch back)
    void showReversed()
    {
        auto profileBased = freecad_cast<PartDesign::ProfileBased*>(ownerT.getObject());
        Gui::TaskView::TaskDialog* dialog = Gui::Control().activeDialog();
        if (!profileBased || !dialog) {
            return;
        }
        for (QWidget* widget : dialog->getDialogContent()) {
            if (!widget) {
                continue;
            }
            for (auto box : widget->findChildren<QCheckBox*>(QStringLiteral("checkBoxReversed"))) {
                QSignalBlocker block(box);
                box->setChecked(profileBased->Reversed.getValue());
            }
        }
    }

    /// The edits that leave New: the parts it made go, after the scope lets go of them
    static void leaveNew(App::DocumentObject* owner, std::vector<std::string>& commands)
    {
        const std::string ownerCmd = Gui::Command::getObjectCmd(owner);
        commands.push_back("PartDesign.studioSetScopeIds(" + ownerCmd + ", [])");
        for (PartDesign::Body* body : partsMadeBy(owner)) {
            commands.push_back(Gui::Command::getObjectCmd(body) + ".removeObjectsFromDocument()");
            commands.push_back(
                std::string("App.getDocument('") + owner->getDocument()->getName()
                + "').removeObject('" + body->getNameInDocument() + "')"
            );
        }
    }

    void onResultChanged(int index)
    {
        App::DocumentObject* owner = ownerT.getObject();
        if (updating || !owner) {
            return;
        }
        live = false;  // the person chose: never picked for them again
        const std::string ownerCmd = Gui::Command::getObjectCmd(owner);
        const bool wasNew = isNewResult(owner);
        const std::string op = operationOf(owner);
        const bool wasCut = !wasNew && (op == "Subtraction" || op == "Common");
        const bool toCut = index == 2 || index == 3;
        std::vector<std::string> commands;
        if (index == 0) {
            if (wasNew) {
                return;
            }
            if (mergesWithAll(owner)) {
                commands.push_back("PartDesign.studioSetMergeAll(" + ownerCmd + ", False)");
            }
            commands.push_back("PartDesign.studioSetScopeIds(" + ownerCmd + ", [])");
            commands.push_back("PartDesign.studioNewPart(" + ownerCmd + ")");
        }
        else {
            if (wasNew) {
                // Never a part's Body while it holds later features (they would be lost)
                const auto made = partsMadeBy(owner);
                const QStringList later = laterFeatures(owner, made);
                if (!later.isEmpty()) {
                    refusal = trStudio("%1 has later features: %2. Leaving New would delete them; "
                                       "delete or move them first.")
                                  .arg(made.empty() ? QString() : studioPartName(made.front()),
                                       later.join(QStringLiteral(", ")));
                    refresh();
                    return;
                }
            }
            const char* ops[] = {"Union", "Union", "Subtraction", "Common"};
            commands.push_back(ownerCmd + ".Operation = '" + ops[index] + "'");
            if (wasNew) {
                // Onshape (Q1b, Q1d): a hand switch from New fills no scope
                leaveNew(owner, commands);
            }
            else {
                // The steps take the operation from the owner at reconcile; Add -> Remove keeps
                // the scope (Q1e)
                commands.push_back(
                    "PartDesign.studioSetScopeIds(" + ownerCmd + ", "
                    + pyList(PartDesign::studioScopeIds(owner)) + ")"
                );
            }
        }
        if (wasCut != toCut && directionBound(owner)) {
            commands.push_back(ownerCmd + ".Reversed = not " + ownerCmd + ".Reversed");
        }
        run(commands);
        showReversed();
        recompute();
        refresh();
    }

    void onTicked(QListWidgetItem* item)
    {
        App::DocumentObject* owner = ownerT.getObject();
        if (updating || !owner || !item) {
            return;
        }
        live = false;  // the person chose a part: never picked for them again
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

    /// Whether owner's Merge with all is on (StudioMergeAll, 10.13)
    static bool mergesWithAll(const App::DocumentObject* owner)
    {
        auto prop = freecad_cast<App::PropertyBool*>(owner->getPropertyByName("StudioMergeAll"));
        return prop && prop->getValue();
    }

    void onMergeAll(bool on)
    {
        App::DocumentObject* owner = ownerT.getObject();
        if (updating || !owner || on == mergesWithAll(owner)) {
            return;
        }
        live = false;  // the person chose the scope: never picked for them again
        run({"PartDesign.studioSetMergeAll(" + Gui::Command::getObjectCmd(owner) + ", "
             + (on ? "True" : "False") + ")"});
        recompute();
        refresh();
    }

    void scheduleDecision()
    {
        if (pending) {
            return;
        }
        pending = true;
        QMetaObject::invokeMethod(this, [this]() { decide(); }, Qt::QueuedConnection);
    }

    /// The live pick (Q1, Q1f): Add into the one part the tool meets, else New
    void decide()
    {
        pending = false;
        App::DocumentObject* owner = ownerT.getObject();
        if (!live || updating || !owner || owner->getDocument()->isPerformingTransaction()) {
            return;
        }
        std::vector<PartDesign::Body*> touched;
        bool known = false;
        deciding = true;
        try {
            known = toolContacts(owner, touched);
        }
        catch (...) {
            known = false;
        }
        deciding = false;
        if (!known) {
            return;
        }
        const bool isNew = isNewResult(owner);
        const std::string ownerCmd = Gui::Command::getObjectCmd(owner);
        std::vector<std::string> commands;
        if (touched.size() != 1) {
            if (isNew) {
                return;
            }
            commands.push_back("PartDesign.studioSetScopeIds(" + ownerCmd + ", [])");
            commands.push_back("PartDesign.studioNewPart(" + ownerCmd + ")");
        }
        else {
            const std::string id = PartDesign::studioPartId(touched.front());
            if (!isNew && operationOf(owner) == "Union"
                && PartDesign::studioScopeIds(owner) == std::vector<std::string> {id}) {
                return;
            }
            if (isNew && !laterFeatures(owner, partsMadeBy(owner)).isEmpty()) {
                return;  // never a part with later features (none in a new feature's dialog)
            }
            commands.push_back(ownerCmd + ".Operation = 'Union'");
            if (isNew) {
                leaveNew(owner, commands);
            }
            commands.push_back("PartDesign.studioSetScopeIds(" + ownerCmd + ", " + pyList({id}) + ")");
        }
        run(commands);
        recompute();
        refresh();
    }

    App::DocumentObjectT ownerT;
    QComboBox* combo = nullptr;
    QCheckBox* mergeAll = nullptr;
    QLabel* scopeLabel = nullptr;
    QListWidget* ticks = nullptr;
    QLabel* note = nullptr;
    QString refusal;
    fastsignals::scoped_connection toolChanged;
    bool updating = false;
    bool live = false;
    bool deciding = false;
    bool pending = false;
};

/// The live part at owner's place a pick on obj names (selection parity P4, SQ15): obj is the
/// part itself or one of its solid features (a face, edge or vertex of it); null for a sketch, a
/// plane, a part not live there (consumed, merged away, made later) or another document's object
PartDesign::Body* pickedLivePart(const App::DocumentObject* owner, App::DocumentObject* obj)
{
    if (!owner || !obj || obj->getDocument() != owner->getDocument()) {
        return nullptr;
    }
    auto body = freecad_cast<PartDesign::Body*>(obj);
    if (!body && freecad_cast<PartDesign::Feature*>(obj)) {
        body = PartDesign::Body::findBodyOf(obj);
    }
    if (!body) {
        return nullptr;
    }
    const auto live = liveStudioParts(owner);
    return std::ranges::find(live, body) != live.end() ? body : nullptr;
}

/// While a studio Boolean's dialog is open, only its live parts are pickable (P4): a sketch
/// element or a plane is refused, as Onshape's Boolean fields take parts only
class StudioPartPickGate: public Gui::SelectionGate
{
public:
    explicit StudioPartPickGate(App::DocumentObject* owner)
        : ownerT(owner)
    {}

    bool allow(App::Document* /*doc*/, App::DocumentObject* obj, const char* /*sub*/) override
    {
        return pickedLivePart(ownerT.getObject(), obj) != nullptr;
    }

private:
    App::DocumentObjectT ownerT;
};

/** A Boolean studio feature's parts (ops#654 P5, Onshape O3): Targets and Tools, one tick per part
 * live at its place (P6a: never a consumed or merged-away part), as Onshape's fields; Union has
 * Tools only, merged into the first ticked. Each change is a list edit
 * (PartDesign.studioSetScopeIds / studioSetToolIds) in the dialog's transaction; why the Boolean
 * fails is said under the ticks, in red.
 * 3D picks (selection parity P4, Onshape SQ14/SQ15): one list is armed, Tools when the dialog
 * opens, Targets after a click on it; a pick on a live part toggles that part's tick in the armed
 * list (the same list edit), clears the selection and leaves the list armed.
 */
class StudioBooleanBox: public QWidget, public Gui::SelectionObserver
{
public:
    explicit StudioBooleanBox(App::DocumentObject* owner)
        : Gui::SelectionObserver(true, Gui::ResolveMode::NoResolve)
        , ownerT(owner)
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
        for (QListWidget* list : {targets, tools}) {
            list->viewport()->installEventFilter(this);
            list->installEventFilter(this);
        }
        gate = new StudioPartPickGate(owner);
        Gui::Selection().addSelectionGate(gate);
    }

    ~StudioBooleanBox() override
    {
        if (gate && Gui::Selection().getSelectionGate(nullptr) == gate) {
            Gui::Selection().rmvSelectionGate();
        }
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
        hasTargets = !fuse;
        arm(armTargets);
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

protected:
    /// A click on a list arms it (P4)
    bool eventFilter(QObject* watched, QEvent* event) override
    {
        const auto type = event->type();
        if (type == QEvent::MouseButtonPress || type == QEvent::FocusIn) {
            if (watched == targets || watched == targets->viewport()) {
                arm(true);
            }
            else if (watched == tools || watched == tools->viewport()) {
                arm(false);
            }
        }
        return QWidget::eventFilter(watched, event);
    }

    void onSelectionChanged(const Gui::SelectionChanges& msg) override
    {
        auto owner = ownerT.getObject();
        if (msg.Type != Gui::SelectionChanges::AddSelection || !owner) {
            return;
        }
        App::DocumentObject* obj = msg.Object.getSubObject();
        if (!obj) {
            obj = msg.Object.getObject();
        }
        PartDesign::Body* body = pickedLivePart(owner, obj);
        if (!body) {
            return;
        }
        // After the selection signal: the toggle runs a list edit and clears the selection
        QPointer<StudioBooleanBox> self(this);
        const std::string id = PartDesign::studioPartId(body);
        QMetaObject::invokeMethod(
            this,
            [self, id]() {
                if (self) {
                    self->toggle(id);
                    Gui::Selection().clearSelection();
                }
            },
            Qt::QueuedConnection
        );
    }

private:
    /// Arms Targets (on) or Tools; a Union has no Targets, so Tools
    void arm(bool targetsOn)
    {
        armTargets = targetsOn && hasTargets;
        const QString frame = QStringLiteral("QListWidget { border: 2px solid palette(highlight); }");
        targets->setProperty("armed", armTargets);
        tools->setProperty("armed", !armTargets);
        targets->setStyleSheet(armTargets ? frame : QString());
        tools->setStyleSheet(armTargets ? QString() : frame);
        QFont font = toolsLabel->font();
        font.setBold(armTargets);
        targetsLabel->setFont(font);
        font.setBold(!armTargets);
        toolsLabel->setFont(font);
    }

    /// The armed list's tick of the part id, toggled (itemChanged makes the list edit)
    void toggle(const std::string& id)
    {
        QListWidget* list = armTargets ? targets : tools;
        const QString key = QString::fromStdString(id);
        for (int i = 0; i < list->count(); ++i) {
            QListWidgetItem* item = list->item(i);
            if (item->data(Qt::UserRole).toString() == key) {
                item->setCheckState(item->checkState() == Qt::Checked ? Qt::Unchecked : Qt::Checked);
                return;
            }
        }
    }

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
    StudioPartPickGate* gate = nullptr;
    bool updating = false;
    bool armTargets = false;
    bool hasTargets = true;
};


/** The part mirror's panel (ops#654 slice 9; Onshape's Mirror of the Part type,
 * notes/onshape-facts.md "Field filters" and "Focus"): the part to mirror (a tick per part live at
 * its place; in the view, a face click picks its part), then the mirror plane (an origin or datum
 * plane, or a planar face); after the plane nothing is armed (the Result box's ticks are the merge
 * scope). Each change is an edit in the dialog's transaction.
 */
class TaskStudioPartMirror: public Gui::TaskView::TaskBox, public Gui::SelectionObserver
{
public:
    explicit TaskStudioPartMirror(ViewProvider* vp)
        : TaskBox(Gui::BitmapFactory().pixmap("PartDesign_Mirrored"), trStudio("Part mirror"), true, nullptr)
        , ownerT(vp->getObject())
    {
        setObjectName(QStringLiteral("studioPartMirror"));
        auto* sourceRow = new QWidget(this);
        auto* sourceLayout = new QHBoxLayout(sourceRow);
        sourceLayout->setContentsMargins(0, 0, 0, 0);
        sourceLayout->addWidget(new QLabel(trStudio("Part to mirror:"), sourceRow));
        sourceButton = new QPushButton(trStudio("Pick in the view"), sourceRow);
        sourceButton->setObjectName(QStringLiteral("studioMirrorSourceButton"));
        sourceButton->setCheckable(true);
        sourceLayout->addWidget(sourceButton, 1);
        groupLayout()->addWidget(sourceRow);
        sources = new QListWidget(this);
        sources->setObjectName(QStringLiteral("studioMirrorSourceList"));
        sources->setToolTip(trStudio("The part mirrored"));
        groupLayout()->addWidget(sources);
        auto* planeRow = new QWidget(this);
        auto* planeLayout = new QHBoxLayout(planeRow);
        planeLayout->setContentsMargins(0, 0, 0, 0);
        planeLayout->addWidget(new QLabel(trStudio("Mirror plane:"), planeRow));
        planeButton = new QPushButton(planeRow);
        planeButton->setObjectName(QStringLiteral("studioMirrorPlaneButton"));
        planeButton->setCheckable(true);
        planeButton->setToolTip(trStudio("A plane, a datum plane or a planar face"));
        planeLayout->addWidget(planeButton, 1);
        groupLayout()->addWidget(planeRow);
        note = new QLabel(this);
        note->setObjectName(QStringLiteral("studioMirrorNote"));
        note->setWordWrap(true);
        groupLayout()->addWidget(note);

        auto pattern = freecad_cast<PartDesign::Transformed*>(ownerT.getObject());
        if (pattern && pattern->StudioEntities.getValues().empty()) {
            armed = Armed::Source;
        }
        else if (pattern && !linkedPlane()) {
            armed = Armed::Plane;
        }
        refresh();
        QObject::connect(sourceButton, &QPushButton::toggled, this, [this](bool on) {
            if (!updating) {
                arm(on ? Armed::Source : Armed::None);
            }
        });
        QObject::connect(planeButton, &QPushButton::toggled, this, [this](bool on) {
            if (!updating) {
                arm(on ? Armed::Plane : Armed::None);
            }
        });
        QObject::connect(sources, &QListWidget::itemChanged, this, [this](QListWidgetItem* item) {
            onTicked(item);
        });
    }

private:
    enum class Armed
    {
        None,
        Source,
        Plane
    };

    App::PropertyLinkSub* planeLink() const
    {
        App::DocumentObject* owner = ownerT.getObject();
        return owner ? dynamic_cast<App::PropertyLinkSub*>(owner->getPropertyByName("MirrorPlane"))
                     : nullptr;
    }

    App::DocumentObject* linkedPlane() const
    {
        App::PropertyLinkSub* link = planeLink();
        return link ? link->getValue() : nullptr;
    }

    void arm(Armed what)
    {
        armed = what;
        QSignalBlocker blockSource(sourceButton);
        QSignalBlocker blockPlane(planeButton);
        sourceButton->setChecked(armed == Armed::Source);
        planeButton->setChecked(armed == Armed::Plane);
    }

    void refresh()
    {
        auto pattern = freecad_cast<PartDesign::Transformed*>(ownerT.getObject());
        if (!pattern) {
            return;
        }
        updating = true;
        const auto ids = pattern->StudioEntities.getValues();
        {
            QSignalBlocker block(sources);
            sources->clear();
            for (PartDesign::Body* body : liveStudioParts(pattern)) {
                if (body->StudioMadeBy.getValue() == pattern) {
                    continue;  // its own New part
                }
                const std::string id = PartDesign::studioPartId(body);
                auto item = new QListWidgetItem(studioPartNameAt(body, pattern), sources);
                item->setData(Qt::UserRole, QString::fromStdString(id));
                item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsUserCheckable);
                item->setCheckState(
                    std::ranges::find(ids, id) != ids.end() ? Qt::Checked : Qt::Unchecked
                );
            }
        }
        QString plane = trStudio("Select...");
        if (App::DocumentObject* obj = linkedPlane()) {
            plane = QString::fromUtf8(obj->Label.getValue());
            const auto& subs = planeLink()->getSubValues();
            if (!subs.empty() && !subs.front().empty()) {
                plane += QStringLiteral(":") + QString::fromStdString(subs.front());
            }
        }
        planeButton->setText(plane);
        arm(armed);
        QString text = refusal;
        if (text.isEmpty() && pattern->isError()) {
            text = QString::fromUtf8(pattern->getStatusString());
        }
        note->setText(text);
        note->setStyleSheet(text.isEmpty() ? QString() : QStringLiteral("color: #d32f2f;"));
        note->setVisible(!text.isEmpty());
        updating = false;
    }

    /// Runs the Python edits in the dialog's transaction and computes the document again; the
    /// panel then shows the owner as it is
    void run(const std::vector<std::string>& commands)
    {
        refusal.clear();
        App::DocumentObject* owner = ownerT.getObject();
        try {
            Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
            for (const auto& command : commands) {
                Gui::Command::doCommand(Gui::Command::Doc, "%s", command.c_str());
            }
            if (owner) {
                Gui::cmdAppDocument(owner->getDocument(), "recompute()");
            }
        }
        catch (const Base::Exception& e) {
            refusal = QString::fromUtf8(e.what());
        }
        QPointer<TaskStudioPartMirror> self(this);
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

    void setSource(const std::vector<std::string>& ids)
    {
        App::DocumentObject* owner = ownerT.getObject();
        const PartDesign::StudioList* list = owner ? PartDesign::StudioList::holding(owner) : nullptr;
        if (!list) {
            return;
        }
        run({Gui::Command::getObjectCmd(owner) + ".StudioEntities = " + pyList(ids),
             "PartDesign.studioReconcile(" + Gui::Command::getObjectCmd(list) + ")"});
    }

    void onTicked(QListWidgetItem* item)
    {
        if (updating || !item) {
            return;
        }
        const std::string id = item->data(Qt::UserRole).toString().toStdString();
        // One part: a tick replaces the one before
        setSource(item->checkState() == Qt::Checked ? std::vector<std::string> {id}
                                                    : std::vector<std::string> {});
    }

    static bool isPlaneObject(const App::DocumentObject* obj)
    {
        return obj->isDerivedFrom<App::Plane>()
            || std::string(obj->getTypeId().getName()) == "PartDesign::Plane";
    }

    void onSelectionChanged(const Gui::SelectionChanges& msg) override
    {
        App::DocumentObject* owner = ownerT.getObject();
        if (busy || armed == Armed::None || !owner || msg.Type != Gui::SelectionChanges::AddSelection
            || !msg.pDocName || std::strcmp(msg.pDocName, owner->getDocument()->getName()) != 0) {
            return;
        }
        App::DocumentObject* obj = owner->getDocument()->getObject(msg.pObjectName);
        const std::string sub = msg.pSubName ? msg.pSubName : "";
        if (!obj) {
            return;
        }
        if (armed == Armed::Plane) {
            // A plane, a datum plane, or a planar face; anything else is refused silently
            // (Onshape's field filters)
            bool planar = isPlaneObject(obj);
            if (!planar && sub.rfind("Face", 0) == 0) {
                if (auto feature = freecad_cast<Part::Feature*>(obj)) {
                    try {
                        const Part::TopoShape face =
                            feature->Shape.getShape().getSubTopoShape(sub.c_str());
                        planar = face.isPlanarFace();
                    }
                    catch (const Base::Exception&) {
                        planar = false;
                    }
                }
            }
            if (planar) {
                const std::string element = isPlaneObject(obj) ? std::string() : sub;
                arm(Armed::None);  // Onshape: after the plane, the merge scope
                run({Gui::Command::getObjectCmd(owner) + ".MirrorPlane = ("
                     + Gui::Command::getObjectCmd(obj) + ", ['" + element + "'])"});
            }
        }
        else {
            // The part field takes a face click as its part
            auto body = freecad_cast<PartDesign::Body*>(obj);
            if (!body && obj->isDerivedFrom<PartDesign::Feature>()) {
                body = PartDesign::Body::findBodyOf(obj);
            }
            const auto live = liveStudioParts(owner);
            if (body && body->StudioMadeBy.getValue() != owner
                && std::ranges::find(live, body) != live.end()) {
                arm(linkedPlane() ? Armed::None : Armed::Plane);
                setSource({PartDesign::studioPartId(body)});
            }
        }
        // The pick is taken: the selection clears after this message
        QPointer<TaskStudioPartMirror> self(this);
        QMetaObject::invokeMethod(
            this,
            [self]() {
                if (self) {
                    Base::StateLocker lock(self->busy, true);
                    Gui::Selection().clearSelection();
                }
            },
            Qt::QueuedConnection
        );
    }

    App::DocumentObjectT ownerT;
    QPushButton* sourceButton = nullptr;
    QListWidget* sources = nullptr;
    QPushButton* planeButton = nullptr;
    QLabel* note = nullptr;
    QString refusal;
    Armed armed = Armed::None;
    bool updating = false;
    bool busy = false;
};

/// The part mirror's dialog: the Result box on top (New / Add / Remove / Intersect and the merge
/// scope's ticks, as an Extrude owner's), then the part and the plane
class TaskDlgStudioPartMirror: public TaskDlgFeatureParameters
{
public:
    explicit TaskDlgStudioPartMirror(ViewProvider* vp)
        : TaskDlgFeatureParameters(vp)
    {
        Content.push_back(new TaskStudioPartMirror(vp));
        addResultBox();
    }
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
    // A piece of a renamed part shows its name (P6p, Onshape S3)
    if (const std::string inherited = PartDesign::pieceInheritedName(body); !inherited.empty()) {
        return QString::fromUtf8(inherited.c_str());
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

/// FreeCAD-CH ops#654 S4 fix (Onshape oracle 6 Q1; declared where used, Command.cpp): the one
/// live part a new owner's tool touches or intersects at its place, null for none or several;
/// false when it has no tool
bool studioPrefillPart(App::DocumentObject* owner, PartDesign::Body*& part)
{
    part = nullptr;
    std::vector<PartDesign::Body*> touched;
    if (!toolContacts(owner, touched)) {
        return false;
    }
    if (touched.size() == 1) {
        part = touched.front();
    }
    return true;
}

/// The dialog opened next on owner picks its operation live until the person chooses (a new
/// Extrude; declared where used, Command.cpp)
void studioPrefillLive(App::DocumentObject* owner)
{
    std::erase_if(livePrefill, [](const App::DocumentObjectT& made) { return !made.getObject(); });
    if (owner && std::ranges::find(livePrefill, App::DocumentObjectT(owner)) == livePrefill.end()) {
        livePrefill.emplace_back(owner);
    }
}

QWidget* makeStudioResultBox(ViewProvider* vp)
{
    if (!vp || !PartDesign::isStudioOwner(vp->getObject())) {
        return nullptr;
    }
    return new TaskStudioResult(vp);
}

/// The part mirror's dialog (ops#654 slice 9), or null when vp's object is no part mirror in a
/// studio's list (declared where used, ViewProviderMirrored.cpp)
TaskDlgFeatureParameters* makeStudioPartMirrorDialog(ViewProvider* vp)
{
    auto pattern = vp ? freecad_cast<PartDesign::Transformed*>(vp->getObject()) : nullptr;
    if (!pattern || !PartDesign::isStudioOwner(pattern) || pattern->PatternType.getValue() != 1) {
        return nullptr;
    }
    return new TaskDlgStudioPartMirror(vp);
}

}  // namespace PartDesignGui
