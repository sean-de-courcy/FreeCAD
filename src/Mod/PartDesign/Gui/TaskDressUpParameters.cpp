// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2012 Jan Rheinländer                                    *
 *                                   <jrheinlaender@users.sourceforge.net> *
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
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/


#include <cstring>

#include <functional>

#include <QAction>
#include <QApplication>
#include <QBoxLayout>
#include <QLayout>
#include <QListWidget>
#include <QPointer>
#include <QTimer>
#include <QWidget>


#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Transactions.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>
#include <Gui/Control.h>
#include <Gui/Document.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Tools.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Gui/WaitCursor.h>
#include <App/ElementNamingUtils.h>
#include <Base/Console.h>
#include <Gui/MainWindow.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureChamfer.h>
#include <Mod/PartDesign/App/FeatureFillet.h>
#include <Mod/PartDesign/App/StudioList.h>
#include <Mod/PartDesign/App/FeatureThickness.h>
#include <Mod/PartDesign/Gui/ReferenceSelection.h>

#include "ReferenceField.h"
#include "TaskDressUpParameters.h"


FC_LOG_LEVEL_INIT("PartDesign", true, true)

using namespace PartDesignGui;
using namespace Gui;

namespace PartDesignGui
{
// TaskFeatureParameters.cpp: ends the feature's edit, runs `change` and edits the feature again,
// all in the dialog's step (its restartEdit)
void restartFeatureEdit(const App::DocumentObjectT& featureT, const std::function<void()>& change);
}  // namespace PartDesignGui

namespace
{
// FreeCAD-CH (ops#640 rank 14): the dress-ups made with nothing selected whose dialog waits for
// its first pick (notePlacedByFirstPick), and those whose dialog comes back after that pick with
// its Base field to arm
std::vector<App::DocumentObjectT> placedByFirstPick;
std::vector<App::DocumentObjectT> armAfterPlacing;

bool hasMark(std::vector<App::DocumentObjectT>& marks, const App::DocumentObject* obj)
{
    std::erase_if(marks, [](const App::DocumentObjectT& mark) { return !mark.getObject(); });
    return obj && std::ranges::find(marks, App::DocumentObjectT(obj)) != marks.end();
}

void forgetMark(std::vector<App::DocumentObjectT>& marks, const App::DocumentObject* obj)
{
    std::erase_if(marks, [obj](const App::DocumentObjectT& mark) {
        return !mark.getObject() || mark.getObject() == obj;
    });
}

/* The feature a first pick links, or null with \a why: an edge or a face (as the dress-up takes
 * them) of a solid feature of any Body in the dress-up's studio, which doesn't use the dress-up.
 * A pick of the dress-up's own shape (shown in place of its base) is its base's. */
App::DocumentObject* placingTarget(
    App::DocumentObject* own,
    App::DocumentObject* obj,
    const std::string& sub,
    bool edges,
    bool faces,
    std::string& why
)
{
    auto dressUp = freecad_cast<PartDesign::DressUp*>(own);
    if (!dressUp || !obj) {
        return nullptr;
    }
    // A vertex stands for its adjacent edge nearest the click (selection parity P6b, SQ13)
    const bool edge = sub.starts_with("Edge") || sub.starts_with("Vertex");
    const bool face = sub.starts_with("Face");
    if (!(edge && edges) && !(face && faces)) {
        why = edges && faces ? QT_TRANSLATE_NOOP("PartDesignGui::TaskDressUpParameters",
                                                 "Pick an edge or a face of a part.")
            : faces          ? QT_TRANSLATE_NOOP("PartDesignGui::TaskDressUpParameters",
                                                 "Pick a face of a part.")
                             : QT_TRANSLATE_NOOP("PartDesignGui::TaskDressUpParameters",
                                                 "Pick an edge of a part.");
        return nullptr;
    }
    if (obj == own) {
        obj = dressUp->getBaseObject(/* silent = */ true);
    }
    PartDesign::Body* body = obj ? PartDesign::Body::findBodyOf(obj) : nullptr;
    if (!body || !obj->isDerivedFrom<Part::Feature>()
        || !(obj->isDerivedFrom<PartDesign::Feature>() || body->BaseFeature.getValue() == obj)) {
        why = QT_TRANSLATE_NOOP("PartDesignGui::TaskDressUpParameters",
                                "Pick an element of a part's solid.");
        return nullptr;
    }
    if (!Part::BodyBase::isInOneStudio(own, obj)) {
        why = QT_TRANSLATE_NOOP("PartDesignGui::TaskDressUpParameters",
                                "The part is in another part studio.");
        return nullptr;
    }
    // Another part's element: of its current shape (its Tip). An earlier feature shown would
    // make the dress-up the part's Tip on that feature, and the later material would vanish
    if (body != PartDesign::Body::findBodyOf(own) && body->Tip.getValue() != obj) {
        why = QT_TRANSLATE_NOOP("PartDesignGui::TaskDressUpParameters",
                                "Pick an element of the part's current shape.");
        return nullptr;
    }
    const auto users = own->getInListRecursive();
    if (std::ranges::find(users, obj) != users.end()) {
        why = QT_TRANSLATE_NOOP("PartDesignGui::TaskDressUpParameters",
                                "The feature comes after this one.");
        return nullptr;
    }
    return obj;
}

// The first pick's gate (placingTarget()); says when it goes, whoever removed it
class PlacingGate: public Gui::SelectionGate
{
public:
    PlacingGate(App::DocumentObject* dressUp, bool edges, bool faces, std::function<void()> gone)
        : dressUpT(dressUp)
        , edges(edges)
        , faces(faces)
        , gone(std::move(gone))
    {}
    ~PlacingGate() override
    {
        if (gone) {
            gone();
        }
    }
    bool allow(App::Document* doc, App::DocumentObject* obj, const char* sub) override
    {
        App::DocumentObject* own = dressUpT.getObject();
        if (!own || !obj) {
            return false;
        }
        if (doc != own->getDocument()) {
            notAllowedReason = QT_TRANSLATE_NOOP("PartDesignGui::TaskDressUpParameters",
                                                 "The element is in another document.");
            return false;
        }
        return placingTarget(own, obj, sub ? sub : "", edges, faces, notAllowedReason) != nullptr;
    }

private:
    App::DocumentObjectT dressUpT;
    bool edges;
    bool faces;
    std::function<void()> gone;
};

// The first pick's observer: its additions, resolved to the feature and element
class PlacingObserver: public Gui::SelectionObserver
{
public:
    explicit PlacingObserver(std::function<void(const Gui::SelectionChanges&)> picked)
        : Gui::SelectionObserver(true, Gui::ResolveMode::OldStyleElement)
        , picked(std::move(picked))
    {}

private:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override
    {
        if (msg.Type == Gui::SelectionChanges::AddSelection && picked) {
            picked(msg);
        }
    }
    std::function<void(const Gui::SelectionChanges&)> picked;
};

// Whether another part of the dress-up's studio could take its first pick: with its own Body
// alone, the field arms on that Body as before (ops#640 rank 14)
bool hasOtherParts(const App::DocumentObject* dressUp)
{
    PartDesign::Body* body = PartDesign::Body::findBodyOf(dressUp);
    if (!body) {
        return false;
    }
    for (PartDesign::Body* other : body->getDocument()->getObjectsOfType<PartDesign::Body>()) {
        if (other != body && Part::BodyBase::areStudioSiblings(body, other)) {
            return true;
        }
    }
    return false;
}

// Shows the Body's Tip when none of its solid features is shown, so the part isn't left empty
void showTipIfNoneShown(const PartDesign::Body* body)
{
    App::DocumentObject* tip = body->Tip.getValue();
    bool shown = std::ranges::any_of(body->Group.getValues(), [](App::DocumentObject* obj) {
        return obj->isDerivedFrom<PartDesign::Feature>() && obj->Visibility.getValue();
    });
    if (tip && !shown) {
        Gui::cmdAppObjectShow(tip);
    }
}

// The view properties a feature takes from the one before it (as the commands' finishFeature)
void copyLook(App::DocumentObject* to, App::DocumentObject* from)
{
    Gui::ViewProvider* target = Gui::Application::Instance->getViewProvider(to);
    Gui::ViewProvider* source = Gui::Application::Instance->getViewProvider(from);
    if (!target || !source) {
        return;
    }
    for (const char* name : {"ShapeAppearance", "LineColor", "PointColor", "Transparency", "DisplayMode"}) {
        App::Property* mine = target->getPropertyByName(name);
        App::Property* theirs = source->getPropertyByName(name);
        if (mine && theirs && mine->getTypeId() == theirs->getTypeId()) {
            try {
                mine->Paste(*theirs);
            }
            catch (const Base::Exception& e) {
                e.reportException();
            }
        }
    }
}

// The dress-up goes to `base`'s Body, after its Tip, and Base becomes `base`'s `sub`: inside a
// restart of its edit (restartFeatureEdit), in the dialog's step
void moveDressUp(const App::DocumentObjectT& featureT, const App::DocumentObjectT& baseT, const std::string& sub)
{
    auto dressUp = freecad_cast<PartDesign::DressUp*>(featureT.getObject());
    App::DocumentObject* base = baseT.getObject();
    PartDesign::Body* from = dressUp ? PartDesign::Body::findBodyOf(dressUp) : nullptr;
    PartDesign::Body* to = base ? PartDesign::Body::findBodyOf(base) : nullptr;
    if (!from || !to) {
        return;
    }
    auto cmd = [](const App::DocumentObject* obj) {
        return Gui::Command::getObjectCmd(obj);
    };
    auto run = [](const std::string& line) {
        Gui::Command::doCommand(Gui::Command::Doc, "%s", line.c_str());
    };
    if (to != from) {
        run(cmd(from) + ".removeObject(" + cmd(dressUp) + ")");
        // The part it left shows its own solid again: the command hid it for the dress-up, and
        // OK purges the touched objects (as New part's move, TaskFeatureParameters.cpp)
        from->recomputeFeature(/* recursive = */ true);
        showTipIfNoneShown(from);
        // Shown, so its new Body hides the solid it shows now (Body::addObject)
        if (!dressUp->Visibility.getValue()) {
            Gui::cmdAppObjectShow(dressUp);
        }
        run(cmd(to) + ".addObject(" + cmd(dressUp) + ")");
        copyLook(dressUp, base);
    }
    run(cmd(dressUp) + ".Base = (" + cmd(base) + ", ['" + sub + "'])");
    dressUp->recomputeFeature();
}
}  // namespace


namespace PartDesign
{
// FeatureDressUp.cpp (FreeCAD-CH ops#654 P8a-2; declared where used)
PartDesignExport std::vector<std::string> studioDressUpRows(const DressUp* owner);
PartDesignExport std::string studioDressUpPickOf(const DressUp* owner,
                                                 App::DocumentObject* obj,
                                                 const std::string& element,
                                                 std::string& why);
}  // namespace PartDesign

namespace
{
/// A Fillet or Chamfer studio feature (FreeCAD-CH ops#654 P8a, parts-design.md 10.14): outside
/// every Body, in a studio's list
bool isStudioDressUpOwner(const App::DocumentObject* obj)
{
    return obj
        && (obj->isDerivedFrom<PartDesign::Fillet>() || obj->isDerivedFrom<PartDesign::Chamfer>())
        && PartDesign::isStudioOwner(obj);
}

/** The edges of a dress-up studio feature (FreeCAD-CH ops#654 P8a-2, 10.14 "the dialog"): its
 * picks, of any live part of its studio, one row each, "Part 2: Edge7" (SQ13's fix: no "other
 * part" refusal). A pick of an edge or face in the 3D view or the tree adds it, a pick of a listed
 * one takes it out; Delete takes out the selected rows. Each change sets the picks
 * (StudioPickIds) in the dialog's transaction, reconciles the list (the scope follows the picks)
 * and recomputes. */
class StudioPicksField: public QListWidget, public Gui::SelectionObserver
{
public:
    StudioPicksField(PartDesign::DressUp* owner, std::function<void()> beforeWrite, QWidget* parent)
        : QListWidget(parent)
        , Gui::SelectionObserver(true)
        , owner(owner)
        , beforeWrite(std::move(beforeWrite))
    {
        setObjectName(QStringLiteral("studioPicks"));
        setSelectionMode(QAbstractItemView::ExtendedSelection);
        setMinimumHeight(60);
        auto remove = new QAction(QObject::tr("Remove"), this);
        remove->setShortcut(QKeySequence::Delete);
        remove->setShortcutContext(Qt::WidgetShortcut);
        addAction(remove);
        setContextMenuPolicy(Qt::ActionsContextMenu);
        QObject::connect(remove, &QAction::triggered, this, [this]() { removeSelectedRows(); });
        reload();
    }

    void reload()
    {
        auto dressUp = freecad_cast<PartDesign::DressUp*>(owner.getObject());
        clear();
        if (!dressUp) {
            return;
        }
        for (const auto& row : PartDesign::studioDressUpRows(dressUp)) {
            addItem(QString::fromStdString(row));
        }
    }

    void removeSelectedRows()
    {
        auto dressUp = freecad_cast<PartDesign::DressUp*>(owner.getObject());
        if (!dressUp) {
            return;
        }
        const std::vector<std::string> picks = dressUp->StudioPickIds.getValues();
        std::vector<std::string> kept;
        for (int i = 0; i < static_cast<int>(picks.size()); ++i) {
            if (i >= count() || !item(i)->isSelected()) {
                kept.push_back(picks[i]);
            }
        }
        if (kept.size() != picks.size()) {
            write(kept);
        }
    }

private:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override
    {
        if (msg.Type != Gui::SelectionChanges::AddSelection || !isEnabled() || !isVisible()) {
            return;
        }
        auto dressUp = freecad_cast<PartDesign::DressUp*>(owner.getObject());
        App::DocumentObject* obj = msg.Object.getSubObject();
        if (!dressUp || !obj || obj->getDocument() != dressUp->getDocument() || !msg.pSubName) {
            return;
        }
        const char* element = Data::findElementName(msg.pSubName);
        const std::string name = Data::oldElementName(element ? element : "");
        if (!name.starts_with("Edge") && !name.starts_with("Face")) {
            return;
        }
        auto body = freecad_cast<PartDesign::Body*>(obj);
        if (!body) {
            body = PartDesign::Body::findBodyOf(obj);
        }
        // A part of another studio: refused, as the per-Body path does (two studios need a
        // Derived feature in Onshape)
        const PartDesign::StudioList* history = PartDesign::StudioList::holding(dressUp);
        App::Part* studio = nullptr;
        if (!body || !history || !Part::BodyBase::studioOf(body, studio)
            || studio != history->studio()) {
            Gui::getMainWindow()->showMessage(
                QObject::tr("Pick edges of the parts of this part studio"),
                10000
            );
            return;
        }
        std::string why;
        const std::string pick = PartDesign::studioDressUpPickOf(dressUp, obj, name, why);
        if (pick.empty()) {
            Gui::getMainWindow()->showMessage(
                QObject::tr("Not taken: %1").arg(QString::fromStdString(why)),
                10000
            );
            return;
        }
        std::vector<std::string> picks = dressUp->StudioPickIds.getValues();
        if (auto it = std::ranges::find(picks, pick); it != picks.end()) {
            picks.erase(it);
        }
        else {
            picks.push_back(pick);
        }
        // After this notification: the selection is cleared, as the reference fields do
        QTimer::singleShot(0, []() { Gui::Selection().clearSelection(); });
        write(picks);
    }

    void write(const std::vector<std::string>& picks)
    {
        auto dressUp = freecad_cast<PartDesign::DressUp*>(owner.getObject());
        if (!dressUp) {
            return;
        }
        beforeWrite();
        dressUp->StudioPickIds.setValues(picks);
        std::string why;
        PartDesign::StudioList* history = PartDesign::StudioList::holding(dressUp);
        if (history && !history->reconcile(&why)) {
            Base::Console().error("%s\n", why.c_str());
        }
        dressUp->getDocument()->recompute();
        reload();
    }

    App::DocumentObjectT owner;
    std::function<void()> beforeWrite;
};
}  // namespace

/* TRANSLATOR PartDesignGui::TaskDressUpParameters */

TaskDressUpParameters::TaskDressUpParameters(
    ViewProviderDressUp* DressUpView,
    bool selectEdges,
    bool selectFaces,
    QWidget* parent
)
    : TaskFeatureParameters(DressUpView, parent, DressUpView->featureIcon(), DressUpView->menuName)
    , proxy(nullptr)
    , addAllEdgesAction(nullptr)
    , allowFaces(selectFaces)
    , allowEdges(selectEdges)
    , DressUpView(DressUpView)
{
    // remember initial transaction ID
    transactionID = DressUpView->getObject()->getDocument()->getBookedTransactionID();

    // FreeCAD-CH (ops#640 rank 14): a dress-up made with nothing selected waits for its first
    // pick, of any part; once it is placed, its dialog comes back with the Base field armed. With
    // no other part in its studio its field arms on its own Body as before
    auto dressUp = DressUpView->getObject<PartDesign::DressUp>();
    if (hasMark(armAfterPlacing, dressUp)) {
        forgetMark(armAfterPlacing, dressUp);
        armBaseOnOpen = true;
    }
    if (hasMark(placedByFirstPick, dressUp) && dressUp->Base.getSubValues().empty()
        && hasOtherParts(dressUp)) {
        startPlacing();
    }
    // An edit too: Onshape's dialog opens with its first selection field active, so a pick in the
    // 3D view goes to the list at once (round 8, J11). An empty one arms as the dialog's first
    // empty field (ReferenceFieldGroup::armFirstEmpty)
    if (!placing && !dressUp->Base.getSubValues().empty()) {
        armBaseOnOpen = true;
    }
}

// The fields remove their own gates; the first pick's goes here
TaskDressUpParameters::~TaskDressUpParameters()
{
    stopPlacing();
}

void TaskDressUpParameters::notePlacedByFirstPick(App::DocumentObject* dressUp)
{
    if (dressUp && !hasMark(placedByFirstPick, dressUp)) {
        placedByFirstPick.emplace_back(dressUp);
    }
}

void TaskDressUpParameters::startPlacing()
{
    placing = true;
    placingObserver = std::make_unique<PlacingObserver>([this](const Gui::SelectionChanges& msg) {
        onPlacingPick(msg);
    });
    installPlacingGate();
    // Another field's gate took the place of this one (a Draft's neutral plane): back when that
    // field is done, after the panel's fields are made
    QTimer::singleShot(0, this, [this]() {
        for (ReferenceField* field : referenceFields()) {
            connect(field, &ReferenceField::armedChanged, this, [this](bool on) {
                if (!on && placing) {
                    QTimer::singleShot(0, this, [this]() { installPlacingGate(); });
                }
            });
        }
    });
}

void TaskDressUpParameters::installPlacingGate()
{
    App::DocumentObject* own = getObject();
    if (!placing || placingGate || !own || Gui::Selection().getSelectionGate(own->getDocument())) {
        return;
    }
    QPointer<TaskDressUpParameters> self(this);
    auto gate = new PlacingGate(own, allowEdges, allowFaces, [self]() {
        if (self) {
            self->placingGate = nullptr;
        }
    });
    placingGate = gate;
    Gui::Selection().addSelectionGate(gate);
}

void TaskDressUpParameters::stopPlacing()
{
    placing = false;
    // Only its own gate: another one put in its place stays
    Gui::SelectionGate* own = placingGate;
    placingGate = nullptr;
    if (own && Gui::Selection().getSelectionGate(nullptr) == own) {
        Gui::Selection().rmvSelectionGate();
    }
}

void TaskDressUpParameters::onPlacingPick(const Gui::SelectionChanges& msg)
{
    App::DocumentObject* own = getObject();
    if (!placing || !placingGate || !own || !msg.pDocName || !msg.pObjectName
        || Gui::Selection().getSelectionGate(own->getDocument()) != placingGate) {
        return;
    }
    App::Document* doc = own->getDocument();
    if (std::strcmp(msg.pDocName, doc->getName()) != 0) {
        return;
    }
    std::string sub = msg.pSubName ? msg.pSubName : "";
    std::string why;
    App::DocumentObject* base = placingTarget(own, doc->getObject(msg.pObjectName), sub,
                                              allowEdges, allowFaces, why);
    if (!base) {
        return;
    }
    if (sub.starts_with("Vertex")) {
        // Its adjacent edge nearest the click (selection parity P6b, oracle 8 SQ13)
        sub = nearestEdgeAt(base, sub, Base::Vector3d(msg.x, msg.y, msg.z));
        if (sub.empty()) {
            return;
        }
    }
    // Placed: the dialog comes back on the moved dress-up, after this notification (the panel
    // goes with the edit's restart)
    QTimer::singleShot(0, this, [this]() { stopPlacing(); });
    placing = false;
    forgetMark(placedByFirstPick, own);
    armAfterPlacing.emplace_back(own);
    App::DocumentObjectT featureT(own);
    App::DocumentObjectT baseT(base);
    QTimer::singleShot(0, qApp, [featureT, baseT, sub]() {
        App::Document* doc = featureT.getDocument();
        Gui::Document* guiDoc = doc ? Gui::Application::Instance->getDocument(doc) : nullptr;
        auto vp = guiDoc
            ? freecad_cast<Gui::ViewProviderDocumentObject*>(guiDoc->getEditViewProvider())
            : nullptr;
        // Still this dress-up's dialog, in its step
        if (!vp || !featureT.getObject() || vp->getObject() != featureT.getObject()
            || !baseT.getObject() || !Gui::Control().activeDialog(doc)) {
            forgetMark(armAfterPlacing, featureT.getObject());
            return;
        }
        Gui::Selection().clearSelection();
        restartFeatureEdit(featureT, [&featureT, &baseT, &sub]() {
            moveDressUp(featureT, baseT, sub);
            // the restarted dialog is still the command's new feature's (hasInput)
            TaskDlgFeatureParameters::noteCreated(featureT.getObject());
        });
        // No dialog came back: nothing to arm
        if (!Gui::Control().activeDialog(doc)) {
            forgetMark(armAfterPlacing, featureT.getObject());
        }
    });
}

void TaskDressUpParameters::setupTransaction()
{
    if (DressUpView.expired()) {
        return;
    }

    // Join a transaction booked since the dialog opened, as the transformed dialogs do: the
    // References panel books one when the dialog has none, and opening another here would commit
    // the panel's repair on its own, out of Cancel's reach (ops#130).
    int tid = DressUpView->getObject()->getDocument()->getBookedTransactionID();
    if (tid != App::NullTransaction) {
        transactionID = tid;
        return;
    }

    // open a transaction if none is active
    // where is this transaction committed - theo-vt?
    std::string n("Edit ");
    n += DressUpView->getObject()->Label.getValue();
    transactionID = DressUpView->getObject()->getDocument()->openTransaction(n.c_str());
}

void TaskDressUpParameters::createBaseField(QWidget* placeholder)
{
    ReferenceField::Options options;
    options.flags.setFlag(AllowSelection::EDGE, allowEdges);
    options.flags.setFlag(AllowSelection::FACE, allowFaces);
    // A vertex click takes its adjacent edge nearest the click, as Onshape's Fillet (selection
    // parity P6b, oracle 8 SQ13)
    options.vertexToEdge = allowEdges;
    // Picks are written as subs of the object Base links, so they come from its shape. That is
    // BaseFeature's, except after a move to it that didn't happen at dialog open (ops#176).
    options.target = [this]() -> App::DocumentObject* {
        // Waiting for the first pick, of any part: no target, so the field doesn't arm
        // (ops#640 rank 14; the first pick's gate is the panel's, startPlacing())
        if (placing || isStudioDressUpOwner(getObject())) {
            return nullptr;
        }
        if (ViewProviderDressUp* view = getDressUpView()) {
            App::DocumentObject* linked =
                view->getObject<PartDesign::DressUp>()->Base.getValue();
            if (linked && linked->isDerivedFrom<Part::Feature>()) {
                return linked;
            }
        }
        return getBase();
    };
    if (allowEdges && allowFaces) {
        options.kinds = tr("Edges, faces");
    }
    else if (allowFaces) {
        options.kinds = tr("Faces");
    }
    else {
        options.kinds = tr("Edges");
    }
    // Onshape's word for the shell's field (ops#640 polish P10)
    if (getObject<PartDesign::Thickness>()) {
        options.label = tr("Faces to remove");
    }
    auto write =[this](App::DocumentObject* /*target*/, const std::vector<std::string>& subs) {
        if (ViewProviderDressUp* view = getDressUpView()) {
            updateFeature(view->getObject<PartDesign::DressUp>(), subs);
        }
    };
    baseField = new ReferenceField(getObject(), "Base", options, write, proxy);
    baseField->takePlaceOf(placeholder);
    // FreeCAD-CH ops#654 P8a-2: a studio feature's edges are its picks, of any part (10.14): its
    // own list beside the Base field, which stays, hidden and never armed, for the panel's code
    // that reads it
    if (isStudioDressUpOwner(getObject())) {
        baseField->setVisible(false);
        auto picks = new StudioPicksField(
            getObject<PartDesign::DressUp>(),
            [this]() { setupTransaction(); },
            proxy
        );
        QWidget* holder = baseField->parentWidget();
        QLayout* layout = holder ? holder->layout() : nullptr;
        auto box = qobject_cast<QBoxLayout*>(layout);
        const int at = layout ? layout->indexOf(baseField) : -1;
        if (box && at >= 0) {
            box->insertWidget(at + 1, picks);
        }
        else if (layout) {
            layout->addWidget(picks);
        }
        return;
    }
    connect(baseField, &ReferenceField::picked, this, [this]() { onBaseChanged(); });
    // Onshape's "Clear missing references": the entries whose element is gone leave the field in
    // one write, the others stay (FreeCAD-CH ops#640 rank 12, blind test F19)
    auto clearMissing = new QAction(tr("Clear missing references"), this);
    clearMissing->setObjectName(QStringLiteral("clearMissingReferences"));
    connect(clearMissing, &QAction::triggered, this, [this]() {
        ViewProviderDressUp* view = getDressUpView();
        if (!view || !baseField) {
            return;
        }
        auto dressUp = view->getObject<PartDesign::DressUp>();
        const std::vector<std::string> stored = dressUp->Base.getSubValues();
        const std::vector<std::string> plain = dressUp->Base.getSubValues(false);
        std::vector<std::string> kept;
        for (std::size_t i = 0; i < stored.size() && i < plain.size(); ++i) {
            if (!plain[i].starts_with(Data::MISSING_PREFIX)) {
                kept.push_back(stored[i]);
            }
        }
        if (kept.size() != stored.size()) {
            baseField->replaceEntries(kept);
            onBaseChanged();
        }
        // The next pick goes to the field, as after Re-pick (round 8, J11)
        QPointer<ReferenceField> field(baseField);
        QTimer::singleShot(0, this, [field]() {
            if (field && field->isEnabled()) {
                field->setArmed(true);
                field->list()->setFocus(Qt::OtherFocusReason);
            }
        });
    });
    baseField->addMenuAction(clearMissing);
    // Its base is gone (the feature it was on deleted): the field says so, and the picks it
    // held went with that feature [guess on the words]
    auto dressUp = getObject<PartDesign::DressUp>();
    if (dressUp && !dressUp->getBaseObject(/* silent = */ true)) {
        baseField->setNote(tr("The feature this one was built on is gone, with the picks on it: "
                              "pick new ones, or delete this feature."));
    }
    // The first pick placed the dress-up, or it is edited: the next picks go on adding to the
    // field, once the dialog is open (ops#640 rank 14, round 8)
    if (armBaseOnOpen) {
        QPointer<ReferenceField> field(baseField);
        QTimer::singleShot(0, this, [field]() {
            if (field && field->isEnabled()) {
                field->setArmed(true);
                field->list()->setFocus(Qt::OtherFocusReason);
            }
        });
    }
}

void TaskDressUpParameters::createAddAllEdgesAction()
{
    addAllEdgesAction = new QAction(tr("Add All Edges"), this);
    addAllEdgesAction->setShortcut(QKeySequence(QStringLiteral("Ctrl+Shift+A")));
    // display shortcut behind the context menu entry
    addAllEdgesAction->setShortcutVisibleInContextMenu(true);
    addAllEdgesAction->setShortcutContext(Qt::WidgetShortcut);
    addAllEdgesAction->setStatusTip(tr("Adds all edges of the base to the list"));
    connect(addAllEdgesAction, &QAction::triggered, this, [this]() { addAllEdges(); });
    if (baseField) {
        baseField->addMenuAction(addAllEdgesAction);
    }
}

std::vector<ReferenceField*> TaskDressUpParameters::referenceFields() const
{
    if (!baseField) {
        return {};
    }
    return {baseField};
}

void TaskDressUpParameters::disarmFields()
{
    for (ReferenceField* field : referenceFields()) {
        field->setArmed(false);
    }
}

void TaskDressUpParameters::addAllEdges()
{
    if (DressUpView.expired()) {
        return;
    }

    PartDesign::DressUp* pcDressUp = DressUpView->getObject<PartDesign::DressUp>();
    App::DocumentObject* base = pcDressUp->Base.getValue();
    if (!base) {
        return;
    }
    int count = Part::Feature::getTopoShape(
                    base,
                    Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
    )
                    .countSubShapes(TopAbs_EDGE);
    const auto oldStyle = pcDressUp->Base.getSubValues(false);
    // The entries there stay as stored (their records with them); the missing edges follow
    auto subValues = pcDressUp->Base.getSubValues();
    std::size_t len = subValues.size();
    for (int i = 0; i < count; ++i) {
        std::string name = "Edge" + std::to_string(i + 1);
        if (std::ranges::find(oldStyle, name) == oldStyle.end()) {
            subValues.push_back(name);
        }
    }
    if (subValues.size() == len) {
        return;
    }
    // Through the field: one step of its undo, and the list shows them (B5)
    if (baseField) {
        baseField->replaceEntries(subValues);
        return;
    }
    try {
        setupTransaction();
        pcDressUp->Base.setValue(base, subValues);
        pcDressUp->recomputeFeature();
        hideOnError();
    }
    catch (Base::Exception& e) {
        e.reportException();
    }
    onBaseChanged();
}

void TaskDressUpParameters::updateFeature(
    PartDesign::DressUp* pcDressUp,
    const std::vector<std::string>& refs
)
{
    setupTransaction();
    // With its base gone, the picks are of the solid before it (FreeCAD-CH ops#640 rank 12, F19)
    App::DocumentObject* base = pcDressUp->Base.getValue();
    if (!base) {
        base = getBase();
    }
    // Through the field, the entries it keeps keep their guess and rejection records
    if (baseField) {
        baseField->assign(base, refs);
    }
    else {
        pcDressUp->Base.setValue(base, refs);
    }
    pcDressUp->recomputeFeature();
    hideOnError();
}

const std::vector<std::string> TaskDressUpParameters::getReferences() const
{
    PartDesign::DressUp* pcDressUp = DressUpView->getObject<PartDesign::DressUp>();
    // A studio feature's are its picks (ops#654 P8a-2)
    if (isStudioDressUpOwner(pcDressUp)) {
        return pcDressUp->StudioPickIds.getValues();
    }
    std::vector<std::string> result = pcDressUp->Base.getSubValues();
    return result;
}

void TaskDressUpParameters::hideOnError()
{
    App::DocumentObject* dressup = DressUpView->getObject();
    DressUpView->setErrorState(dressup->isError());
}

ViewProviderDressUp* TaskDressUpParameters::getDressUpView() const
{
    return DressUpView.expired() ? nullptr : DressUpView.get();
}

Part::Feature* TaskDressUpParameters::getBase() const
{
    if (ViewProviderDressUp* vp = getDressUpView()) {
        auto dressUp = vp->getObject<PartDesign::DressUp>();
        // Unlikely but this may throw an exception in case we are started to edit an object which
        // base feature was deleted. This exception will be likely unhandled inside the dialog and
        // pass upper. But an error message inside the report view is better than a SEGFAULT.
        // FreeCAD-CH (ops#640 rank 12, F19): the dialog opens with no base too; null then
        return dressUp->getBaseObject(/* silent = */ true);
    }

    return nullptr;
}

void TaskDressUpParameters::onReferencesRepaired()
{
    for (ReferenceField* field : referenceFields()) {
        field->reload();
    }
}

void TaskDressUpParameters::onReferenceSelectionTaken()
{
    disarmFields();
}

namespace
{
// After Body::insertObject, BaseFeature is the inserted feature and Base still names the feature
// before it (ops#82). The panel shows, highlights and selects on BaseFeature's shape, so Base
// moves there: each reference is resolved as the dress-up resolves it (its mapped name on
// BaseFeature's shape) and replaced by that element's index. A reference without a mapped name,
// one that resolves to nothing, or two that resolve to the same element leave Base as it is
// (ops#84). So does a reference with a record or an expansion (ops#176): the plain setter
// would drop them, and a guessed entry would read exact, its warning gone. The panel then picks
// on Base's object. Returns whether Base moved.
bool moveBaseToBaseFeature(PartDesign::DressUp* dressUp)
{
    App::DocumentObject* base = dressUp->Base.getValue();
    App::DocumentObject* baseFeature = dressUp->BaseFeature.getValue();
    if (!base || !baseFeature || base == baseFeature) {
        return false;
    }
    const auto records = dressUp->Base.getElementRecords();
    const auto froms = dressUp->Base.getExpandedFroms();
    if (std::ranges::any_of(records, [](const auto& record) { return !record.empty(); })
        || std::ranges::any_of(froms, [](const auto& from) { return !from.empty(); })) {
        return false;
    }
    Part::TopoShape shape = dressUp->getBaseTopoShape(/* silent = */ true);
    const auto& shadows = dressUp->Base.getShadowSubs();
    if (shape.isNull() || shadows.empty()) {
        return false;
    }
    std::vector<std::string> subs;
    for (const auto& shadow : shadows) {
        if (shadow.newName.empty()) {
            return false;
        }
        TopoDS_Shape element;
        try {
            element = shape.getSubShape(shadow.newName.c_str(), /* silent = */ true);
        }
        catch (...) {
        }
        int index = element.IsNull() ? 0 : shape.findShape(element);
        if (index <= 0) {
            return false;
        }
        std::string sub = Part::TopoShape::shapeName(element.ShapeType()) + std::to_string(index);
        if (std::ranges::find(subs, sub) != subs.end()) {
            return false;
        }
        subs.push_back(std::move(sub));
    }

    // Inside the panel's transaction, so Cancel restores Base
    App::Document* doc = dressUp->getDocument();
    if (doc->getBookedTransactionID() == App::NullTransaction && !doc->hasPendingTransaction()) {
        doc->openTransaction(std::string("Edit ") + dressUp->Label.getValue());
    }
    dressUp->Base.setValue(baseFeature, subs);
    return true;
}
}  // namespace

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgDressUpParameters::TaskDlgDressUpParameters(ViewProviderDressUp* DressUpView)
    : TaskDlgFeatureParameters(DressUpView)
    , parameter(nullptr)
{
    assert(DressUpView);
    auto pcDressUp = DressUpView->getObject<PartDesign::DressUp>();
    auto base = pcDressUp->Base.getValue();
    std::vector<std::string> newSubList;
    bool changed = false;
    auto& shadowSubs = pcDressUp->Base.getShadowSubs();
    for (auto& shadowSub : shadowSubs) {
        auto displayName = shadowSub.oldName;
        // If there is a missing tag on the shadow sub, take a guess at a new name. Not with the
        // reference solver on (ops#7, Task 2 PR 5): it resolved what it could, and a reference
        // it left broken stays broken until the user picks another element (ops#66).
        if (boost::starts_with(shadowSub.oldName, Data::MISSING_PREFIX)
            && !pcDressUp->Base.inSolverDocument()) {
            Part::Feature::guessNewLink(displayName, base, shadowSub.newName.c_str());
            changed = true;
        }
        newSubList.emplace_back(displayName);
    }
    if (changed) {
        pcDressUp->Base.setValue(base, newSubList);
        pcDressUp->recomputeFeature(false);
    }
    moveBaseToBaseFeature(pcDressUp);
}

TaskDlgDressUpParameters::~TaskDlgDressUpParameters() = default;

//==== calls from the TaskView ===============================================================

bool TaskDlgDressUpParameters::accept()
{
    // The dress-up is placed where it is, picked or not (ops#640 rank 14)
    forgetMark(placedByFirstPick, getObject());
    forgetMark(armAfterPlacing, getObject());
    getViewObject<ViewProviderDressUp>()->highlightReferences(false);
    std::vector<std::string> refs = parameter->getReferences();
    // Base's own object: the references are its element names (ops#84)
    auto dressUp = getObject<PartDesign::DressUp>();
    App::DocumentObject* base = dressUp->Base.getValue();
    if (!base) {
        base = parameter->getBase();
    }
    // No base at all (the feature it was on is gone): committed as it is, red (ops#640 rank 12)
    if (!base) {
        return TaskDlgFeatureParameters::accept();
    }
    // Written only when the dialog changed it: written again with plain names, Base would drop
    // what it keeps per reference, a guess record or a missing element of a partly resolved
    // dress-up among them, without a warning (ops#127).
    if (base == dressUp->Base.getValue()
        && (refs == dressUp->Base.getSubValues(true)
            || refs == dressUp->Base.getSubValues(false))) {
        return TaskDlgFeatureParameters::accept();
    }
    std::stringstream str;
    str << Gui::Command::getObjectCmd(getObject()) << ".Base = ("
        << Gui::Command::getObjectCmd(base) << ",[";
    for (const auto& ref : refs) {
        str << "\"" << ref << "\",";
    }
    str << "])";
    Gui::Command::runCommand(Gui::Command::Doc, str.str().c_str());
    return TaskDlgFeatureParameters::accept();
}

bool TaskDlgDressUpParameters::reject()
{
    forgetMark(placedByFirstPick, getObject());
    forgetMark(armAfterPlacing, getObject());
    getViewObject<ViewProviderDressUp>()->highlightReferences(false);
    return TaskDlgFeatureParameters::reject();
}

#include "moc_TaskDressUpParameters.cpp"
