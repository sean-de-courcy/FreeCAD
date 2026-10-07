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
#include <cstring>
#include <map>
#include <optional>

#include <QAction>
#include <QApplication>
#include <QFocusEvent>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QLabel>
#include <QListWidget>
#include <QMenu>
#include <QMouseEvent>
#include <QTimer>
#include <QVBoxLayout>

#include <boost/algorithm/string/predicate.hpp>
#include <Inventor/SbBox3f.h>
#include <Standard_Failure.hxx>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/ElementNamingUtils.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <App/ReferenceReport.h>
#include <Base/Console.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/Document.h>
#include <Gui/Tools.h>
#include <Gui/View3DInventor.h>
#include <Gui/View3DInventorViewer.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/Gui/ReferenceHighlighter.h>
#include <Mod/Part/Gui/ViewProviderExt.h>
#include <Mod/PartDesign/App/FeatureAddSub.h>

#include "ReferenceField.h"
#include "ReferenceSelection.h"

using namespace PartDesignGui;

namespace
{

constexpr int IndexRole = Qt::UserRole;
constexpr int StateRole = Qt::UserRole + 1;
constexpr int SubRole = Qt::UserRole + 2;

QPointer<ReferenceField> armedFieldPtr;

// The element of a stored sub without its missing mark: `Edge5` for `?Edge5`.
std::string bareElement(const std::string& sub)
{
    const char* element = Data::findElementName(sub.c_str());
    std::string name = element ? element : sub;
    name.erase(0, name.find_first_not_of('?'));
    return name;
}

QString distanceText(double distance)
{
    if (std::isnan(distance)) {
        return {};
    }
    return ReferenceField::tr("%1 mm").arg(distance, 0, 'g', 4);
}

bool matchesRedo(QKeyEvent* ke)
{
    // Ctrl+Y on every platform, besides the platform's own redo key
    return ke->matches(QKeySequence::Redo)
        || Gui::QtTools::matches(ke, QKeySequence(QStringLiteral("Ctrl+Y")));
}

/// The field's gate: elements of the field's target and kind, in the owner's document. Tells the
/// field when it goes, whoever removed it (TaskReferences' PickGate pattern).
class ReferenceFieldGate: public Gui::SelectionGate
{
public:
    ReferenceFieldGate(ReferenceField* field,
                       App::DocumentObject* target,
                       App::DocumentObject* owner,
                       const ReferenceField::Options& options)
        : field(field)
        , target(target)
        , owner(owner)
        , flags(options.flags)
        , accept(options.accept)
        , noDependents(options.noDependents)
        , kind(options.kind)
        , wholeObject(options.wholeObject)
    {}
    ~ReferenceFieldGate() override
    {
        if (field) {
            field->gateGone();
        }
    }

    bool allow(App::Document* doc, App::DocumentObject* obj, const char* sub) override
    {
        App::DocumentObject* support = target.getObject();
        App::DocumentObject* own = owner.getObject();
        if (!obj || !own || (kind == ReferenceField::Kind::Elements && !support)) {
            return false;
        }
        if (doc != own->getDocument()) {
            notAllowedReason = QT_TR_NOOP("The element is in another document.");
            return false;
        }
        if (kind == ReferenceField::Kind::Elements) {
            if (obj != support) {
                notAllowedReason = QT_TR_NOOP("Pick an element of the shape the field shows.");
                return false;
            }
            if (Base::Tools::isNullOrEmpty(sub)) {
                notAllowedReason = QT_TR_NOOP("Pick an element, not the whole object.");
                return false;
            }
        }
        else if (obj == own) {
            notAllowedReason = QT_TR_NOOP("The feature can't refer to itself.");
            return false;
        }
        if (wholeObject) {
            if (!obj->isDerivedFrom<Part::Feature>()) {
                notAllowedReason = QT_TR_NOOP("Pick a shape.");
                return false;
            }
        }
        else if (kind != ReferenceField::Kind::Profile && kind != ReferenceField::Kind::Objects) {
            // A profile's gate is its accept test alone (an object of the body, or its elements),
            // and so is a list of objects'
            if (ReferenceSelection selection(support, flags); !selection.allow(doc, obj, sub)) {
                notAllowedReason = QT_TR_NOOP("The field doesn't take this kind of element.");
                return false;
            }
        }
        std::string why;
        if (accept && !accept(obj, sub, why)) {
            notAllowedReason = why;
            return false;
        }
        if (noDependents) {
            NoDependentsSelection independent(owner.getObject());
            if (!independent.allow(doc, obj, sub)) {
                notAllowedReason = independent.notAllowedReason;
                return false;
            }
        }
        return true;
    }

private:
    QPointer<ReferenceField> field;
    App::DocumentObjectT target;
    App::DocumentObjectT owner;
    AllowSelectionFlags flags;
    std::function<bool(App::DocumentObject*, const char*, std::string&)> accept;
    bool noDependents;
    ReferenceField::Kind kind;
    bool wholeObject;
};

// The link properties a field writes: PropertyLinkSub, and PropertyLinkSubList (an up-to-shape)
template<class Fn>
void visitLink(App::PropertyLinkBase* prop, Fn&& fn)
{
    if (auto link = freecad_cast<App::PropertyLinkSub*>(prop)) {
        fn(*link);
    }
    else if (auto list = freecad_cast<App::PropertyLinkSubList*>(prop)) {
        fn(*list);
    }
}

}  // namespace

/*********************************************************************
 *                          Reference field                          *
 *********************************************************************/

ReferenceField::ReferenceField(App::DocumentObject* owner,
                               const char* property,
                               Options options,
                               Writer write,
                               QWidget* parent)
    : QWidget(parent)
    , Gui::SelectionObserver(true, Gui::ResolveMode::OldStyleElement)
    , ownerT(owner)
    , propertyNameStr(property)
    , options(std::move(options))
    , writer(std::move(write))
{
    setObjectName(QStringLiteral("field") + QString::fromLatin1(property));
    auto layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);

    const QString& title = this->options.label.isEmpty() ? this->options.kinds : this->options.label;
    label = new QLabel(title, this);
    label->setObjectName(QStringLiteral("label"));

    entryList = new QListWidget(this);
    entryList->setObjectName(QStringLiteral("entries"));
    entryList->setContextMenuPolicy(Qt::CustomContextMenu);
    label->setBuddy(entryList);
    if (isSingle()) {
        // One line, the label beside it, as the line edits it replaces
        entryList->setSelectionMode(QAbstractItemView::SingleSelection);
        entryList->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        entryList->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        entryList->setFixedHeight(entryList->fontMetrics().height() + 2 * entryList->frameWidth() + 6);
        entryList->setToolTip(
            tr("Click here, then pick in the 3D view: a pick replaces the reference.\n"
               "Delete clears it; Ctrl+Z undoes the last change here.")
        );
        auto row = new QHBoxLayout();
        row->addWidget(label);
        row->addWidget(entryList, 1);
        layout->addLayout(row);
    }
    else {
        entryList->setSelectionMode(QAbstractItemView::ExtendedSelection);
        entryList->setToolTip(
            isObjects()
                ? tr("Click here, then pick features in the tree: a pick adds a feature or "
                     "takes it out.\n"
                     "Delete removes the selected entries; Ctrl+Z undoes the last change here.")
                : tr("Click here, then pick in the 3D view: a pick adds an element or takes it "
                     "out.\n"
                     "Delete removes the selected entries; Ctrl+Z undoes the last change here.")
        );
        layout->addWidget(label);
        layout->addWidget(entryList);
    }

    hint = new QLabel(this);
    hint->setObjectName(QStringLiteral("hint"));
    hint->setWordWrap(true);
    hint->hide();
    layout->addWidget(hint);

    status = new QLabel(this);
    status->setObjectName(QStringLiteral("status"));
    status->setWordWrap(true);
    status->setTextInteractionFlags(Qt::TextSelectableByMouse);
    status->hide();
    layout->addWidget(status);

    entryList->installEventFilter(this);
    entryList->viewport()->installEventFilter(this);
    connect(entryList, &QListWidget::customContextMenuRequested, this, &ReferenceField::showMenu);
    connect(entryList, &QListWidget::currentItemChanged, this, [this]() {
        if (armed) {
            highlight(true);
        }
    });
    connect(entryList, &QListWidget::itemDoubleClicked, this, [this](QListWidgetItem* item) {
        const App::ReferenceRow* row = rowOf(item);
        if (!row || (row->alternatives.empty() && row->candidates.empty())) {
            return;
        }
        auto use = new QMenu(entryList);
        use->setObjectName(QStringLiteral("useMenu"));
        use->setAttribute(Qt::WA_DeleteOnClose);
        fillUseMenu(use, *row);
        QPoint corner = entryList->visualItemRect(item).bottomLeft();
        use->popup(entryList->viewport()->mapToGlobal(corner));
    });

    if (owner && owner->getDocument()) {
        attachDocument(owner->getDocument());
    }
    reload();
}

ReferenceField::ReferenceField(App::DocumentObject* owner,
                               const char* property,
                               Options options,
                               ObjectsWriter write,
                               QWidget* parent)
    : ReferenceField(owner, property, std::move(options), Writer(), parent)
{
    objectsWriter = std::move(write);
}

ReferenceField::~ReferenceField()
{
    Gui::SelectionGate* own = gate;
    gate = nullptr;
    const bool wasArmed = armed;
    armed = false;
    if (armedFieldPtr == this) {
        armedFieldPtr = nullptr;
    }
    try {
        if (own && Gui::Selection().getSelectionGate(nullptr) == own) {
            Gui::Selection().rmvSelectionGate();
        }
        if (wasArmed) {
            highlight(false);
        }
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
}

ReferenceField* ReferenceField::armedField()
{
    return armedFieldPtr.data();
}

void ReferenceField::setGroup(ReferenceFieldGroup* group)
{
    this->group = group;
}

void ReferenceField::addMenuAction(QAction* action)
{
    menuActions.emplace_back(action);
}

void ReferenceField::takePlaceOf(QWidget* placeholder)
{
    if (QWidget* parent = placeholder->parentWidget(); parent && parent->layout()) {
        delete parent->layout()->replaceWidget(placeholder, this, Qt::FindChildrenRecursively);
    }
    placeholder->hide();
    placeholder->deleteLater();
}

App::PropertyLinkBase* ReferenceField::property() const
{
    auto own = owner();
    if (!own) {
        return nullptr;
    }
    App::Property* prop = own->getPropertyByName(propertyNameStr.c_str());
    if (isObjects() ? freecad_cast<App::PropertyLinkList*>(prop) != nullptr
                    : (freecad_cast<App::PropertyLinkSub*>(prop)
                       || freecad_cast<App::PropertyLinkSubList*>(prop))) {
        return static_cast<App::PropertyLinkBase*>(prop);
    }
    return nullptr;
}

std::vector<App::DocumentObject*> ReferenceField::linkedObjects() const
{
    std::vector<App::DocumentObject*> objs;
    if (auto list = freecad_cast<App::PropertyLinkList*>(property())) {
        for (App::DocumentObject* obj : list->getValues()) {
            if (obj && obj->isAttachedToDocument()) {
                objs.push_back(obj);
            }
        }
    }
    return objs;
}

App::DocumentObject* ReferenceField::linkedObject() const
{
    App::DocumentObject* obj = nullptr;
    visitLink(property(), [&obj](auto& link) { obj = link.getValue(); });
    return obj && obj->isAttachedToDocument() ? obj : nullptr;
}

App::DocumentObject* ReferenceField::target() const
{
    App::DocumentObject* obj = options.target ? options.target() : nullptr;
    return obj && obj->isAttachedToDocument() ? obj : nullptr;
}

App::DocumentObject* ReferenceField::listObject() const
{
    App::DocumentObject* linked = linkedObject();
    return linked ? linked : target();
}

std::vector<std::string> ReferenceField::storedSubs() const
{
    std::vector<std::string> subs;
    visitLink(property(), [&subs](auto& link) { subs = link.getSubValues(); });
    return subs;
}

std::vector<std::string> ReferenceField::entries() const
{
    std::vector<std::string> subs;
    for (int i = 0; i < entryList->count(); ++i) {
        subs.push_back(entryList->item(i)->data(SubRole).toString().toStdString());
    }
    return subs;
}

QString ReferenceField::state() const
{
    QString result = QStringLiteral("exact");
    for (int i = 0; i < entryList->count(); ++i) {
        QString st = entryList->item(i)->data(StateRole).toString();
        if (st == QLatin1String("broken")) {
            return st;
        }
        if (st == QLatin1String("guessed")) {
            result = st;
        }
    }
    return result;
}

void ReferenceField::setArmed(bool on)
{
    if (on == armed) {
        return;
    }
    if (on) {
        App::DocumentObject* support = target();
        // A single entry can take a datum or origin plane with nothing to show
        if (!isEnabled() || busy || (!support && options.kind == Kind::Elements)) {
            return;
        }
        if (group) {
            group->fieldArming(this);
        }
        else if (ReferenceField* other = armedField(); other && other != this) {
            other->setArmed(false);
        }
        // The panel's own pick modes end first: they would remove this gate when they end.
        Q_EMIT arming();
        armed = true;
        armedFieldPtr = this;
        if (support) {
            display.show(support);
        }
        {
            Base::StateLocker lock(busy, true);
            Gui::Selection().clearSelection();
        }
        gate = new ReferenceFieldGate(this, support, owner(), options);
        Gui::Selection().addSelectionGate(gate);
        highlight(true);
    }
    else {
        armed = false;
        if (armedFieldPtr == this) {
            armedFieldPtr = nullptr;
        }
        repickIndex = -1;
        // Only its own gate: another one put in its place stays (the gate goes only by its owner)
        Gui::SelectionGate* own = gate;
        gate = nullptr;
        if (own && Gui::Selection().getSelectionGate(nullptr) == own) {
            Gui::Selection().rmvSelectionGate();
        }
        highlight(false);
        display.restore();
    }
    updateLook();
    Q_EMIT armedChanged(on);
}

void ReferenceField::gateGone()
{
    gate = nullptr;
    if (armed) {
        setArmed(false);
    }
}

void ReferenceField::reload()
{
    reloadPending = false;
    rows.clear();
    if (isObjects()) {
        // One entry per object, by its Label; objects of one Label are told apart by their
        // names (B6). An object is there or not: no states.
        const std::vector<App::DocumentObject*> objs = linkedObjects();
        std::map<std::string, int> labels;
        for (App::DocumentObject* obj : objs) {
            ++labels[obj->Label.getValue()];
        }
        const int current = entryList->currentRow();
        QSignalBlocker block(entryList);
        entryList->clear();
        for (std::size_t i = 0; i < objs.size(); ++i) {
            const QString label = QString::fromUtf8(objs[i]->Label.getValue());
            const QString name = QString::fromLatin1(objs[i]->getNameInDocument());
            auto item = new QListWidgetItem(entryList);
            item->setData(IndexRole, static_cast<int>(i));
            item->setData(SubRole, name);
            item->setData(StateRole, QStringLiteral("exact"));
            item->setText(labels[objs[i]->Label.getValue()] > 1
                              ? QStringLiteral("%1 (%2)").arg(label, name)
                              : label);
            item->setToolTip(name);
        }
        if (current >= 0 && current < entryList->count()) {
            entryList->setCurrentRow(current);
        }
        block.unblock();
        updateLook();
        return;
    }
    std::vector<App::ReferenceReport::Slot> slots;
    auto own = owner();
    if (own && own->isAttachedToDocument()) {
        for (auto& slot : App::ReferenceReport::slotsOf(own)) {
            if (slot.property == propertyNameStr) {
                slots.push_back(std::move(slot));
            }
        }
        for (auto& row : App::referenceRows(own)) {
            if (row.property == propertyNameStr) {
                rows.push_back(std::move(row));
            }
        }
    }
    std::ranges::sort(slots, {}, &App::ReferenceReport::Slot::index);
    if (isSingle()) {
        // One entry: the linked object with its element, or the object alone (a datum, a whole
        // shape), for which there is no slot
        App::DocumentObject* linked = linkedObject();
        if (options.wholeObject || slots.empty()) {
            slots.clear();
            if (linked) {
                App::ReferenceReport::Slot slot;
                slot.property = propertyNameStr;
                slot.index = 0;
                slot.obj = linked;
                slots.push_back(std::move(slot));
            }
        }
        else if (slots.size() > 1) {
            slots.resize(1);
        }
    }
    else if (isProfile()) {
        // The linked object's elements, or the object whole: one entry, for which there is no
        // slot (index -1)
        std::erase_if(slots, [](const App::ReferenceReport::Slot& slot) {
            return bareElement(slot.sub).empty();
        });
        App::DocumentObject* linked = linkedObject();
        if (slots.empty() && linked) {
            App::ReferenceReport::Slot slot;
            slot.property = propertyNameStr;
            slot.index = -1;
            slot.obj = linked;
            slots.push_back(std::move(slot));
        }
        for (auto& slot : slots) {
            if (!slot.obj) {
                slot.obj = linked;
            }
        }
    }
    else {
        // A list's object-only entry (an up-to-shape's whole shape) isn't an element
        std::erase_if(slots, [](const App::ReferenceReport::Slot& slot) {
            return bareElement(slot.sub).empty();
        });
    }

    // A profile's whole object is index -1
    std::optional<int> currentIndex;
    if (QListWidgetItem* current = entryList->currentItem()) {
        currentIndex = current->data(IndexRole).toInt();
    }
    QSignalBlocker block(entryList);
    entryList->clear();
    for (const auto& slot : slots) {
        auto item = new QListWidgetItem(entryList);
        item->setData(IndexRole, slot.index);
        item->setData(SubRole, QString::fromStdString(slot.sub));
        const App::ReferenceRow* row = nullptr;
        for (const auto& r : rows) {
            if (r.index == slot.index) {
                row = &r;
            }
        }
        const std::string element = bareElement(slot.sub);
        const bool broken = Data::hasMissingElement(slot.sub.c_str())
            || (row && row->status == "broken");
        QString text = QString::fromStdString(element);
        if ((isSingle() || isProfile()) && slot.obj) {
            // The object varies: `Pad:Face6`, or `DatumPlane` alone; a profile's `Sketch (whole)`
            const QString name = QString::fromUtf8(slot.obj->Label.getValue());
            if (!element.empty()) {
                text = QStringLiteral("%1:%2").arg(name, text);
            }
            else {
                text = isProfile() ? tr("%1 (whole)").arg(name) : name;
            }
        }
        QStringList tip;
        if (broken) {
            item->setData(StateRole, QStringLiteral("broken"));
            text = tr("%1 (missing)").arg(text);
            item->setBackground(QColor(255, 0, 0, 70));
            item->setIcon(Gui::BitmapFactory().pixmap("overlay_error"));
            tip << tr("%1 is missing.").arg(QString::fromStdString(element));
            if (row && !row->candidates.empty()) {
                tip << tr("Candidates (right-click, Use):");
                for (const auto& candidate : row->candidates) {
                    tip << QStringLiteral("  %1  %2").arg(QString::fromStdString(candidate.index),
                                                          distanceText(candidate.distance));
                }
            }
        }
        else if (row) {
            item->setData(StateRole, QStringLiteral("guessed"));
            item->setBackground(QColor(255, 200, 0, 90));
            item->setIcon(Gui::BitmapFactory().pixmap("overlay_warning"));
            tip << QString::fromStdString(row->headline.empty() ? row->evidence : row->headline);
            if (row->hasOriginal && !row->originalIndex.empty()) {
                tip << tr("Originally %1").arg(QString::fromStdString(row->originalIndex));
            }
            for (const auto& alternative : row->alternatives) {
                tip << QStringLiteral("  %1  %2").arg(QString::fromStdString(alternative.index),
                                                      distanceText(alternative.distance));
            }
        }
        else {
            item->setData(StateRole, QStringLiteral("exact"));
        }
        item->setText(text);
        if (!tip.isEmpty()) {
            item->setToolTip(tip.join(QLatin1Char('\n')));
        }
        if (slot.index == currentIndex) {
            entryList->setCurrentItem(item);
        }
    }
    block.unblock();
    updateLook();
}

void ReferenceField::scheduleReload()
{
    if (reloadPending) {
        return;
    }
    reloadPending = true;
    // Not now: the change may be one of many, or the field's own write still running.
    QTimer::singleShot(0, this, [this]() {
        if (reloadPending) {
            reload();
            if (armed) {
                highlight(true);
            }
        }
    });
}

void ReferenceField::slotChangedObject(const App::DocumentObject& obj, const App::Property& prop)
{
    const char* name = obj.getPropertyName(&prop);
    if (&obj == owner() && name && propertyNameStr == name) {
        // Changed by something else (a document undo, a script): the field's steps no longer
        // lead back to what the user had
        if (!busy) {
            undoStack.clear();
            redoStack.clear();
        }
        scheduleReload();
    }
    else if (isObjects() && &prop == &obj.Label) {
        // A listed object renamed: its row shows the new Label (PR 154 review)
        const auto objs = linkedObjects();
        if (std::ranges::find(objs, &obj) != objs.end()) {
            scheduleReload();
        }
    }
}

void ReferenceField::slotRecomputedObject(const App::DocumentObject& obj)
{
    if (&obj == owner()) {
        scheduleReload();
    }
}

void ReferenceField::slotDeletedDocument(const App::Document& doc)
{
    if (&doc == getDocument()) {
        if (armed) {
            armed = false;
            if (armedFieldPtr == this) {
                armedFieldPtr = nullptr;
            }
            highlightedTarget = App::DocumentObjectT();
            display.forget();
            Gui::SelectionGate* own = gate;
            gate = nullptr;
            if (own && Gui::Selection().getSelectionGate(nullptr) == own) {
                Gui::Selection().rmvSelectionGate();
            }
        }
        detachDocument();
    }
}

void ReferenceField::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    if (!armed || busy || msg.Type != Gui::SelectionChanges::AddSelection) {
        return;
    }
    auto own = owner();
    if (!own || !msg.pDocName || std::strcmp(msg.pDocName, own->getDocument()->getName()) != 0) {
        return;
    }
    App::DocumentObject* obj = own->getDocument()->getObject(msg.pObjectName);
    if (!obj) {
        return;
    }
    // The gate let through only what the field takes
    if (isObjects()) {
        pickObject(obj);
        return;
    }
    if (isSingle()) {
        pickSingle(msg);
        return;
    }
    if (isProfile()) {
        pickProfile(msg);
        return;
    }
    if (obj != target() || Base::Tools::isNullOrEmpty(msg.pSubName)) {
        return;
    }
    pick(obj, msg.pSubName);
}

void ReferenceField::pick(App::DocumentObject* obj, const std::string& sub)
{
    {
        Base::StateLocker lock(busy, true);
        Gui::Selection().clearSelection();
    }
    message.clear();
    if (repickIndex >= 0) {
        std::string command =
            ReferenceActions::repickCommand(owner(), propertyNameStr, repickIndex, sub);
        repickIndex = -1;
        updateLook();
        // After this notification, as the References panel does it
        QTimer::singleShot(0, this, [this, command]() { runAction(command); });
        return;
    }
    Q_UNUSED(obj)
    if (!property()) {
        return;
    }
    std::vector<std::string> stored = storedSubs();
    std::vector<std::string> old;
    visitLink(property(), [&old](auto& link) { old = link.getSubValues(false); });
    auto found = std::ranges::find(old, sub);
    if (found != old.end() && static_cast<std::size_t>(found - old.begin()) < stored.size()) {
        stored.erase(stored.begin() + (found - old.begin()));
    }
    else {
        stored.push_back(sub);
    }
    if (refusesLastElement(stored)) {
        return;
    }
    write(stored);
}

void ReferenceField::pickObject(App::DocumentObject* obj)
{
    {
        Base::StateLocker lock(busy, true);
        Gui::Selection().clearSelection();
    }
    message.clear();
    std::vector<App::DocumentObject*> objs = linkedObjects();
    if (auto found = std::ranges::find(objs, obj); found != objs.end()) {
        objs.erase(found);
    }
    else {
        objs.push_back(obj);
    }
    writeObjects(objs);
}

void ReferenceField::pickSingle(const Gui::SelectionChanges& msg)
{
    App::DocumentObject* obj = owner()->getDocument()->getObject(msg.pObjectName);
    const std::string sub = msg.pSubName ? msg.pSubName : "";
    if (repickIndex >= 0 && !options.wholeObject && !sub.empty() && obj == linkedObject()) {
        pick(obj, sub);  // the References panel's re-pick of the element
        return;
    }
    std::vector<std::string> subs;
    if (options.resolve && !options.wholeObject) {
        // Before the selection is cleared: the resolver reads the pick (and may ask about a
        // copy of another body's element)
        if (!options.resolve(msg, obj, subs) || !obj) {
            Base::StateLocker lock(busy, true);
            Gui::Selection().clearSelection();
            return;
        }
    }
    else if (!options.wholeObject && !sub.empty()) {
        subs.push_back(sub);
    }
    {
        Base::StateLocker lock(busy, true);
        Gui::Selection().clearSelection();
    }
    message.clear();
    repickIndex = -1;
    std::erase(subs, std::string());
    // The same reference again: nothing to write
    std::vector<std::string> old;
    visitLink(property(), [&old](auto& link) { old = link.getSubValues(false); });
    std::erase(old, std::string());
    if (obj != linkedObject() || subs != old) {
        write(obj, subs);
    }
    if (options.once) {
        setArmed(false);
    }
}

void ReferenceField::pickProfile(const Gui::SelectionChanges& msg)
{
    App::DocumentObject* obj = owner()->getDocument()->getObject(msg.pObjectName);
    const std::string sub = msg.pSubName ? msg.pSubName : "";
    App::DocumentObject* linked = linkedObject();
    if (obj == linked && !sub.empty()) {
        pick(obj, sub);  // an element of the profile: added or taken out, or a re-pick's
        return;
    }
    {
        Base::StateLocker lock(busy, true);
        Gui::Selection().clearSelection();
    }
    if (repickIndex >= 0) {
        // A re-pick replaces one entry: another object, or the object whole, would replace the
        // profile and drop every entry with its records
        message = tr("Re-pick takes an element of %1.")
                      .arg(linked ? QString::fromUtf8(linked->Label.getValue()) : QString());
        updateLook();
        return;
    }
    message.clear();
    // Another object, or the object whole: the profile is replaced
    if (obj != linked || !storedSubs().empty()) {
        std::vector<std::string> subs;
        if (!sub.empty()) {
            subs.push_back(sub);
        }
        write(obj, subs);
    }
    else {
        updateLook();
    }
}

void ReferenceField::useWhole()
{
    App::DocumentObject* linked = linkedObject();
    if (linked && !storedSubs().empty()) {
        write(linked, {});
    }
}

bool ReferenceField::refusesLastElement(const std::vector<std::string>& stored)
{
    App::DocumentObject* linked = isProfile() ? linkedObject() : nullptr;
    if (!linked || !stored.empty() || linked->isDerivedFrom<Part::Part2DObject>()) {
        return false;
    }
    message = tr(
        "The profile keeps its last element: pick another element of the solid first, or "
        "another profile."
    );
    updateLook();
    return true;
}

bool ReferenceField::lacksRegions() const
{
    App::DocumentObject* linked = isProfile() ? linkedObject() : nullptr;
    auto makeInternals = linked
        ? freecad_cast<App::PropertyBool*>(linked->getPropertyByName("MakeInternals"))
        : nullptr;
    return makeInternals && !makeInternals->getValue();
}

void ReferenceField::makeRegions()
{
    App::DocumentObject* linked = linkedObject();
    if (!linked || !lacksRegions()) {
        return;
    }
    // A change of the sketch, not of the field's property: no step of the field's undo, and
    // Cancel takes it back with the edit
    const std::string command = Gui::Command::getObjectCmd(linked) + ".MakeInternals = True";
    QString error;
    bool done = false;
    {
        Base::StateLocker lock(busy, true);
        done = ReferenceActions::run(owner(), command, &error);
    }
    message = done ? QString() : error;
    reload();
    highlight(armed);
}

ReferenceField::Snapshot ReferenceField::snapshot() const
{
    Snapshot value;
    auto prop = property();
    visitLink(prop, [&value](auto& link) {
        if (App::DocumentObject* obj = link.getValue()) {
            value.object = obj;
        }
        value.subs = link.getSubValues();
        value.shadows = link.getShadowSubs();
        value.records = link.getElementRecords();
        value.fingerprints = link.getElementFingerprints();
        value.froms = link.getExpandedFroms();
    });
    if (prop && isObjects()) {
        for (App::DocumentObject* obj : linkedObjects()) {
            value.objects.emplace_back(obj);
        }
        return value;
    }
    if (prop) {
        value.report = App::ReferenceReport::get(prop);
    }
    const std::size_t count = value.subs.size();
    value.shadows.resize(count);
    value.records.resize(count);
    value.fingerprints.resize(count);
    value.froms.resize(count);
    return value;
}

void ReferenceField::pushUndo()
{
    undoStack.push_back(snapshot());
    redoStack.clear();
}

void ReferenceField::write(const std::vector<std::string>& subs, bool undoable)
{
    // The object the property links, which the writers pass back: a dress-up's Base can name
    // the feature before the one its picks come from (BaseFeature after Body::insertObject), and
    // the entries' records go along only with the same object
    write(listObject(), subs, undoable);
}

void ReferenceField::write(App::DocumentObject* obj,
                           const std::vector<std::string>& written,
                           bool undoable)
{
    std::vector<std::string> subs = written;
    if (!isSingle()) {
        // A list of elements: an object-only entry (a whole up-to-shape) goes with the first one
        std::erase(subs, std::string());
    }
    // Each kept entry takes its mapped name, records, fingerprint, `from` and report along,
    // wherever it moves; a new one, or any on another object, has none
    const Snapshot now = snapshot();
    Snapshot value;
    if (obj) {
        value.object = obj;
    }
    value.subs = subs;
    value.shadows.resize(subs.size());
    value.records.resize(subs.size());
    value.fingerprints.resize(subs.size());
    value.froms.resize(subs.size());
    const bool sameObject = obj && now.object.getObject() == obj;
    std::vector<bool> used(now.subs.size(), !sameObject);
    for (std::size_t j = 0; j < subs.size(); ++j) {
        for (std::size_t i = 0; i < now.subs.size(); ++i) {
            if (!used[i] && now.subs[i] == subs[j]) {
                used[i] = true;
                value.shadows[j] = now.shadows[i];
                value.records[j] = now.records[i];
                value.fingerprints[j] = now.fingerprints[i];
                value.froms[j] = now.froms[i];
                for (const auto& entry : now.report) {
                    if (entry.index == static_cast<int>(i)) {
                        value.report.push_back(entry);
                        value.report.back().index = static_cast<int>(j);
                    }
                }
                break;
            }
        }
    }
    write(value, undoable);
}

void ReferenceField::write(const Snapshot& value, bool undoable)
{
    if (!property() || (isObjects() ? !objectsWriter : !writer)) {
        return;
    }
    if (undoable) {
        pushUndo();
    }
    if (isObjects()) {
        std::vector<App::DocumentObject*> objs;
        for (const auto& objT : value.objects) {
            if (App::DocumentObject* obj = objT.getObject()) {
                objs.push_back(obj);
            }
        }
        Base::StateLocker lock(busy, true);
        objectsWriter(objs);
    }
    else {
        Base::StateLocker lock(busy, true);
        pending = value;
        valuePending = true;
        writer(value.object.getObject(), value.subs);
        valuePending = false;
        pending = Snapshot();
    }
    reload();
    if (armed) {
        highlight(true);
    }
    Q_EMIT picked();
}

void ReferenceField::writeObjects(const std::vector<App::DocumentObject*>& objs, bool undoable)
{
    Snapshot value;
    for (App::DocumentObject* obj : objs) {
        value.objects.emplace_back(obj);
    }
    write(value, undoable);
}

void ReferenceField::assign(App::DocumentObject* obj, const std::vector<std::string>& subs)
{
    auto prop = property();
    if (!prop) {
        return;
    }
    // A writer passes what the field gave it; anything else is written as it comes
    if (!valuePending || pending.subs != subs || pending.object.getObject() != obj) {
        visitLink(prop, [&](auto& link) { link.setValue(obj, subs); });
        return;
    }
    // Where a kept entry has no mapped name, it is found again from its sub, as a new one is
    std::vector<std::string> names = pending.subs;
    std::vector<App::PropertyLinkBase::ShadowSub> shadows = pending.shadows;
    if (auto link = freecad_cast<App::PropertyLinkSub*>(prop)) {
        link->setValue(obj, std::move(names), std::move(shadows));
    }
    else if (auto list = freecad_cast<App::PropertyLinkSubList*>(prop)) {
        if (!obj || names.empty()) {
            list->setValue(obj, names);
        }
        else {
            std::vector<App::DocumentObject*> objs(names.size(), obj);
            list->setValues(std::move(objs), std::move(names), std::move(shadows));
        }
    }
    if (pending.subs.empty()) {
        return;
    }
    visitLink(prop, [this](auto& link) {
        link.setElementRecords(std::vector<App::ElementRecords>(pending.records));
        link.setExpandedFroms(std::vector<std::string>(pending.froms));
        for (std::size_t i = 0; i < pending.fingerprints.size(); ++i) {
            if (!pending.fingerprints[i].empty()) {
                link.setElementFingerprint(i, pending.fingerprints[i]);
            }
        }
    });
    // The setter dropped the report; what it said of the kept entries still holds
    std::map<std::string, std::vector<App::ReferenceReport::Entry>> byTarget;
    for (const auto& entry : pending.report) {
        byTarget[entry.target].push_back(entry);
    }
    for (auto& [name, entries] : byTarget) {
        App::ReferenceReport::replace(prop, name, std::move(entries));
    }
}

void ReferenceField::replaceEntries(const std::vector<std::string>& subs)
{
    write(subs);
}

void ReferenceField::removeSelected()
{
    std::vector<int> indexes;
    for (QListWidgetItem* item : entryList->selectedItems()) {
        indexes.push_back(item->data(IndexRole).toInt());
    }
    if (indexes.empty() && entryList->currentItem()) {
        indexes.push_back(entryList->currentItem()->data(IndexRole).toInt());
    }
    // A profile's whole object isn't removed: the profile is required
    std::erase_if(indexes, [](int index) { return index < 0; });
    if (indexes.empty()) {
        return;
    }
    if (isSingle()) {
        write(nullptr, {});
        return;
    }
    std::ranges::sort(indexes, std::greater<> {});
    if (isObjects()) {
        std::vector<App::DocumentObject*> objs = linkedObjects();
        for (int index : indexes) {
            if (index < static_cast<int>(objs.size())) {
                objs.erase(objs.begin() + index);
            }
        }
        writeObjects(objs);
        return;
    }
    std::vector<std::string> stored = storedSubs();
    for (int index : indexes) {
        if (index >= 0 && index < static_cast<int>(stored.size())) {
            stored.erase(stored.begin() + index);
        }
    }
    if (refusesLastElement(stored)) {
        return;
    }
    write(stored);
}

bool ReferenceField::undo()
{
    if (undoStack.empty()) {
        return false;
    }
    redoStack.push_back(snapshot());
    Snapshot value = std::move(undoStack.back());
    undoStack.pop_back();
    write(value, false);
    return true;
}

bool ReferenceField::redo()
{
    if (redoStack.empty()) {
        return false;
    }
    undoStack.push_back(snapshot());
    Snapshot value = std::move(redoStack.back());
    redoStack.pop_back();
    write(value, false);
    return true;
}

void ReferenceField::updateLook()
{
    QFont font = label->font();
    font.setBold(armed);
    label->setFont(font);
    const QString st = state();
    if (st == QLatin1String("broken")) {
        label->setStyleSheet(QStringLiteral("color: red;"));
    }
    else if (st == QLatin1String("guessed")) {
        label->setStyleSheet(QStringLiteral("color: #c08000;"));
    }
    else {
        label->setStyleSheet(QString());
    }
    entryList->setStyleSheet(
        armed ? QStringLiteral("QListWidget#entries { border: 2px solid palette(highlight); }")
              : QString()
    );

    if (armed) {
        if (repickIndex >= 0) {
            QString element;
            for (int i = 0; i < entryList->count(); ++i) {
                if (entryList->item(i)->data(IndexRole).toInt() == repickIndex) {
                    element = QString::fromStdString(
                        bareElement(entryList->item(i)->data(SubRole).toString().toStdString())
                    );
                }
            }
            hint->setText(
                tr("Re-pick %1: pick the element that replaces it in the 3D view.").arg(element)
            );
        }
        else if (lacksRegions()) {
            hint->setText(
                tr("Select %1 in the 3D view. The sketch makes no regions: right-click here and "
                   "choose Make regions to pick them.")
                    .arg(options.kinds.toLower())
            );
        }
        else if (isObjects()) {
            hint->setText(
                tr("Select %1 in the tree.").arg(options.kinds.toLower())
            );
        }
        else {
            hint->setText(tr("Select %1 in the 3D view.").arg(options.kinds.toLower()));
        }
    }
    hint->setVisible(armed);

    QString text = message;
    if (text.isEmpty() && st != QLatin1String("exact")) {
        if (auto own = owner()) {
            text = QString::fromUtf8(own->getStatusString());
        }
    }
    status->setText(text);
    status->setStyleSheet(!message.isEmpty() ? QStringLiteral("color: red;") : QString());
    status->setVisible(!text.isEmpty());
}

void ReferenceField::highlight(bool on, const std::string& extra)
{
    // Off the element colours of the last target; on: the entries, the current one (and the
    // hovered candidate) in a second colour. The view provider's Coin nodes only: nothing in
    // the edit's transaction or the file (notes 10).
    if (auto previous = highlightedTarget.getObject()) {
        if (auto vp = freecad_cast<PartGui::ViewProviderPartExt*>(
                Gui::Application::Instance->getViewProvider(previous)
            )) {
            vp->unsetHighlightedFaces();
            vp->unsetHighlightedEdges();
        }
    }
    highlightedTarget = App::DocumentObjectT();
    // A single entry is coloured on its own object (a face of the base, not a datum plane)
    App::DocumentObject* support = nullptr;
    // A list of objects colours nothing: its entries are whole features
    if (on && !isObjects()) {
        support = isSingle() ? (options.wholeObject ? nullptr : linkedObject())
                             : (isProfile() ? linkedObject() : target());
    }
    auto feature = freecad_cast<Part::Feature*>(support);
    if (!feature) {
        return;
    }
    auto vp = freecad_cast<PartGui::ViewProviderPartExt*>(
        Gui::Application::Instance->getViewProvider(feature)
    );
    if (!vp) {
        return;
    }
    std::vector<std::string> edges, faces, currentEdges, currentFaces;
    auto sort = [](const std::string& element,
                   std::vector<std::string>& e,
                   std::vector<std::string>& f) {
        if (boost::starts_with(element, "Edge")) {
            e.push_back(element);
        }
        else if (boost::starts_with(element, "Face")) {
            f.push_back(element);
        }
    };
    for (int i = 0; i < entryList->count(); ++i) {
        QListWidgetItem* item = entryList->item(i);
        std::string sub = item->data(SubRole).toString().toStdString();
        if (Data::hasMissingElement(sub.c_str())) {
            continue;
        }
        std::string element = bareElement(sub);
        if (item == entryList->currentItem()) {
            sort(element, currentEdges, currentFaces);
        }
        else {
            sort(element, edges, faces);
        }
    }
    if (!extra.empty()) {
        sort(extra, currentEdges, currentFaces);
    }
    const TopoDS_Shape& shape = feature->Shape.getValue();
    const Base::Color currentColor(0.0F, 0.75F, 1.0F);
    // The highlighter paints every element when given no names: each list goes only when it has
    // some (the first one sizes the colours).
    try {
        if (!edges.empty() || !currentEdges.empty()) {
            std::vector<Base::Color> colors = vp->LineColorArray.getValues();
            PartGui::ReferenceHighlighter highlighter(shape, vp->LineColor.getValue());
            if (!edges.empty()) {
                highlighter.getEdgeColors(edges, colors);
            }
            highlighter.setElementColor(currentColor);
            if (!currentEdges.empty()) {
                highlighter.getEdgeColors(currentEdges, colors);
            }
            vp->setHighlightedEdges(colors);
        }
        if (!faces.empty() || !currentFaces.empty()) {
            std::vector<App::Material> materials = vp->ShapeAppearance.getValues();
            PartGui::ReferenceHighlighter highlighter(shape, vp->ShapeAppearance.getDiffuseColor());
            if (!faces.empty()) {
                highlighter.getFaceMaterials(faces, materials);
            }
            highlighter.setElementColor(currentColor);
            if (!currentFaces.empty()) {
                highlighter.getFaceMaterials(currentFaces, materials);
            }
            vp->setHighlightedFaces(materials);
        }
    }
    catch (const Standard_Failure& e) {
        Base::Console().error("OCC error: %s\n", e.GetMessageString());
    }
    catch (const std::exception& e) {
        Base::Console().error("%s\n", e.what());
    }
    highlightedTarget = feature;
}

void ReferenceField::zoomTo(const std::string& element)
{
    App::DocumentObject* support = (isSingle() || isProfile()) ? linkedObject() : target();
    if (isObjects()) {
        // The entry is an object (its name): its shape
        auto own = owner();
        support = own && !element.empty() ? own->getDocument()->getObject(element.c_str()) : nullptr;
    }
    if (!support || (element.empty() && !isObjects())) {
        return;
    }
    Part::TopoShape sub;
    if (isObjects()) {
        // A feature that adds or removes: what it adds or removes, not the whole solid after it
        if (auto addSub = freecad_cast<PartDesign::FeatureAddSub*>(support)) {
            sub = addSub->AddSubShape.getShape();
        }
        if (sub.isNull()) {
            sub = Part::Feature::getTopoShape(
                support,
                Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
            );
        }
    }
    else {
        // Through the object's sub-object lookup: a sketch's regions (InternalFace3) aren't in
        // its Shape
        sub = Part::Feature::getTopoShape(
            support,
            Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
                | Part::ShapeOption::NeedSubElement,
            element.c_str()
        );
    }
    if (sub.isNull()) {
        return;
    }
    Base::BoundBox3d box = sub.getBoundBox();
    Gui::Document* doc = Gui::Application::Instance->getDocument(support->getDocument());
    auto view = doc ? qobject_cast<Gui::View3DInventor*>(doc->getActiveView()) : nullptr;
    if (!view) {
        return;
    }
    view->getViewer()->viewBoundBox(SbBox3f(static_cast<float>(box.MinX),
                                            static_cast<float>(box.MinY),
                                            static_cast<float>(box.MinZ),
                                            static_cast<float>(box.MaxX),
                                            static_cast<float>(box.MaxY),
                                            static_cast<float>(box.MaxZ)));
}

const App::ReferenceRow* ReferenceField::rowOf(const QListWidgetItem* item) const
{
    if (!item) {
        return nullptr;
    }
    const int index = item->data(IndexRole).toInt();
    for (const auto& row : rows) {
        if (row.index == index) {
            return &row;
        }
    }
    return nullptr;
}

void ReferenceField::showMenu(const QPoint& pos)
{
    QListWidgetItem* item = entryList->itemAt(pos);
    if (item && !item->isSelected()) {
        entryList->setCurrentItem(item);
    }
    QMenu* menu = buildMenu(item);
    menu->popup(entryList->viewport()->mapToGlobal(pos));
}

QMenu* ReferenceField::buildMenu(QListWidgetItem* item)
{
    auto menu = new QMenu(entryList);
    menu->setObjectName(QStringLiteral("entryMenu"));
    menu->setAttribute(Qt::WA_DeleteOnClose);

    // A profile's whole object has no slot: nothing to remove, repair or zoom to
    const bool whole = item && item->data(IndexRole).toInt() < 0;
    QAction* remove = menu->addAction(tr("Remove"));
    remove->setShortcut(QKeySequence(Gui::QtTools::deleteKeySequence()));
    remove->setShortcutContext(Qt::WidgetShortcut);
    remove->setShortcutVisibleInContextMenu(true);
    remove->setEnabled(!whole && (item || !entryList->selectedItems().isEmpty()));
    connect(remove, &QAction::triggered, this, [this]() { removeSelected(); });

    if (item && isObjects()) {
        // An object is listed or not: nothing to accept, use or re-pick
        QAction* zoom = menu->addAction(tr("Zoom to"));
        connect(zoom, &QAction::triggered, this, [this, name = item->data(SubRole).toString()]() {
            zoomTo(name.toStdString());
        });
    }
    else if (item && !whole) {
        const int index = item->data(IndexRole).toInt();
        const App::ReferenceRow* row = rowOf(item);
        const std::string sub = item->data(SubRole).toString().toStdString();
        if (row && ReferenceActions::hasGuess(*row)
            && !ReferenceActions::heldElement(*row).empty()) {
            QAction* accept = menu->addAction(tr("Accept guess"));
            accept->setToolTip(tr("Keep the element the reference holds now; the warning goes"));
            connect(accept, &QAction::triggered, this, [this, index]() {
                runAction(ReferenceActions::acceptCommand(owner(), propertyNameStr, index));
            });
        }
        if (row && (!row->alternatives.empty() || !row->candidates.empty())) {
            QMenu* use = menu->addMenu(tr("Use"));
            use->setObjectName(QStringLiteral("useMenu"));
            fillUseMenu(use, *row);
        }
        if (row && ReferenceActions::hasGuess(*row)) {
            QAction* broken = menu->addAction(tr("Mark broken"));
            broken->setToolTip(
                tr("The guess is wrong and nothing listed is right: the feature fails until the "
                   "reference is re-picked")
            );
            connect(broken, &QAction::triggered, this, [this, index]() {
                runAction(ReferenceActions::markBrokenCommand(owner(), propertyNameStr, index));
            });
        }
        QAction* repick = menu->addAction(tr("Re-pick"));
        repick->setToolTip(tr("The next pick in the 3D view replaces this entry"));
        connect(repick, &QAction::triggered, this, [this, index]() { startRepick(index); });

        QAction* zoom = menu->addAction(tr("Zoom to"));
        zoom->setEnabled(!Data::hasMissingElement(sub.c_str()));
        connect(zoom, &QAction::triggered, this, [this, element = bareElement(sub)]() {
            zoomTo(element);
        });
    }
    if (isProfile()) {
        if (!storedSubs().empty() && freecad_cast<Part::Part2DObject*>(linkedObject())) {
            QAction* useWholeAction = menu->addAction(tr("Use whole sketch"));
            useWholeAction->setToolTip(
                tr("The profile is the whole sketch again, not its regions")
            );
            connect(useWholeAction, &QAction::triggered, this, [this]() { useWhole(); });
        }
        if (lacksRegions()) {
            QAction* make = menu->addAction(tr("Make regions"));
            make->setToolTip(tr("The sketch makes its regions, so that they can be picked"));
            connect(make, &QAction::triggered, this, [this]() { makeRegions(); });
        }
    }
    bool separated = false;
    for (const auto& action : menuActions) {
        if (!action) {
            continue;
        }
        if (!separated) {
            menu->addSeparator();
            separated = true;
        }
        menu->addAction(action);
    }
    return menu;
}

void ReferenceField::fillUseMenu(QMenu* menu, const App::ReferenceRow& row)
{
    const int index = row.index;
    auto add = [&](const std::string& element, const std::string& role, double distance) {
        QString text = QString::fromStdString(element);
        QString detail = distanceText(distance);
        if (detail.isEmpty() && !role.empty()) {
            detail = QString::fromStdString(role);
        }
        if (!detail.isEmpty()) {
            text += QStringLiteral("  (%1)").arg(detail);
        }
        QAction* action = menu->addAction(text);
        action->setEnabled(role != "rejected");
        connect(action, &QAction::hovered, this, [this, element]() { highlight(true, element); });
        connect(action, &QAction::triggered, this, [this, index, element]() {
            runAction(ReferenceActions::useCommand(owner(), propertyNameStr, index, element));
        });
    };
    if (!row.alternatives.empty()) {
        for (const auto& alternative : row.alternatives) {
            add(alternative.index, alternative.role, alternative.distance);
        }
    }
    else {
        for (const auto& candidate : row.candidates) {
            add(candidate.index, candidate.role, candidate.distance);
        }
    }
    // The hovered candidate's colour goes with the menu
    connect(menu, &QMenu::aboutToHide, this, [this]() { highlight(armed); });
}

void ReferenceField::runAction(const std::string& command)
{
    auto own = owner();
    if (!own) {
        return;
    }
    QString error;
    bool done = false;
    // A step of the field's undo, as a pick is
    Snapshot before = snapshot();
    {
        Base::StateLocker lock(busy, true);
        done = ReferenceActions::run(own, command, &error);
    }
    if (done) {
        undoStack.push_back(std::move(before));
        redoStack.clear();
    }
    message = done ? QString() : error;
    reload();
    highlight(armed);
    if (done) {
        Q_EMIT picked();
    }
}

void ReferenceField::startRepick(int index)
{
    if (!armed) {
        setArmed(true);
    }
    if (!armed) {
        return;
    }
    repickIndex = index;
    updateLook();
}

bool ReferenceField::eventFilter(QObject* watched, QEvent* event)
{
    if (watched == entryList->viewport()) {
        if (event->type() == QEvent::MouseButtonPress
            && static_cast<QMouseEvent*>(event)->button() == Qt::LeftButton) {  // NOLINT
            setArmed(true);
        }
        return false;
    }
    if (watched != entryList) {
        return QWidget::eventFilter(watched, event);
    }
    switch (event->type()) {
        case QEvent::FocusIn: {
            // Not when the window comes back or a menu closes: a field the user disarmed stays so
            auto reason = static_cast<QFocusEvent*>(event)->reason();  // NOLINT
            if (reason != Qt::ActiveWindowFocusReason && reason != Qt::PopupFocusReason) {
                setArmed(true);
            }
            break;
        }
        case QEvent::ShortcutOverride: {
            // The field's keys before the window's shortcuts (Std_Delete, Std_Undo, ...)
            auto ke = static_cast<QKeyEvent*>(event);  // NOLINT
            bool own = Gui::QtTools::matches(ke, QKeySequence(Gui::QtTools::deleteKeySequence()))
                || ke->matches(QKeySequence::Undo) || matchesRedo(ke)
                || (armed && ke->key() == Qt::Key_Escape);
            for (const auto& action : menuActions) {
                own = own || (action && Gui::QtTools::matches(ke, action->shortcut()));
            }
            if (own) {
                ke->accept();
                return true;
            }
            break;
        }
        case QEvent::KeyPress: {
            auto ke = static_cast<QKeyEvent*>(event);  // NOLINT
            if (Gui::QtTools::matches(ke, QKeySequence(Gui::QtTools::deleteKeySequence()))) {
                removeSelected();
                return true;
            }
            if (ke->matches(QKeySequence::Undo)) {
                undo();
                return true;
            }
            if (matchesRedo(ke)) {
                redo();
                return true;
            }
            if (armed && ke->key() == Qt::Key_Escape) {
                setArmed(false);
                return true;
            }
            for (const auto& action : menuActions) {
                if (action && action->isEnabled()
                    && Gui::QtTools::matches(ke, action->shortcut())) {
                    action->trigger();
                    return true;
                }
            }
            // Up and Down stop at the ends instead of leaving the list
            const Qt::KeyboardModifiers ignored = Qt::ShiftModifier | Qt::KeypadModifier;
            if ((ke->modifiers() & ~ignored) == Qt::NoModifier
                && (ke->key() == Qt::Key_Down || ke->key() == Qt::Key_Up)) {
                const int row = entryList->currentRow();
                const int last = entryList->count() - 1;
                if (row >= 0
                    && ((ke->key() == Qt::Key_Down && row >= last)
                        || (ke->key() == Qt::Key_Up && row <= 0))) {
                    ke->accept();
                    return true;
                }
            }
            break;
        }
        default:
            break;
    }
    return QWidget::eventFilter(watched, event);
}

bool ReferenceField::coversProperty() const
{
    if (!options.covers || !isEnabled()) {
        return false;
    }
    // Hidden itself, or inside a hidden part of its panel (a mode's or a side's widgets); not
    // whatever hides the whole panel (the task view behind another tab)
    for (const QWidget* widget = this; widget && !widget->isWindow();
         widget = widget->parentWidget()) {
        if (group && group->isPanel(widget)) {
            break;
        }
        if (widget->isHidden()) {
            return false;
        }
    }
    return true;
}

void ReferenceField::scheduleCoverageChanged()
{
    if (coveragePending) {
        return;
    }
    coveragePending = true;
    QTimer::singleShot(0, this, [this]() {
        coveragePending = false;
        Q_EMIT coverageChanged();
    });
}

bool ReferenceField::event(QEvent* event)
{
    switch (event->type()) {
        case QEvent::ShowToParent:
        case QEvent::HideToParent:
        case QEvent::Show:
        case QEvent::Hide:
            scheduleCoverageChanged();
            break;
        default:
            break;
    }
    return QWidget::event(event);
}

void ReferenceField::changeEvent(QEvent* event)
{
    QWidget::changeEvent(event);
    if (event->type() == QEvent::EnabledChange) {
        if (!isEnabled() && armed) {
            setArmed(false);
        }
        Q_EMIT coverageChanged();
    }
}

/*********************************************************************
 *                               Group                               *
 *********************************************************************/

ReferenceFieldGroup::ReferenceFieldGroup(QObject* parent)
    : QObject(parent)
{
    connect(qApp, &QApplication::focusChanged, this, &ReferenceFieldGroup::onFocusChanged);
    if (Gui::Application::Instance) {
        activeDocumentConnection = Gui::Application::Instance->signalActiveDocument.connect(
            [this](const Gui::Document& doc) {
                // Another document: its picks aren't this dialog's
                for (const auto& field : fieldList) {
                    if (field && field->isArmed() && field->ownerDocument() != doc.getDocument()) {
                        field->setArmed(false);
                    }
                }
            }
        );
    }
}

ReferenceFieldGroup::~ReferenceFieldGroup()
{
    disarm();
}

void ReferenceFieldGroup::addField(ReferenceField* field)
{
    if (!field
        || std::ranges::any_of(fieldList, [field](const auto& f) { return f.data() == field; })) {
        return;
    }
    fieldList.emplace_back(field);
    field->setGroup(this);
    connect(field, &ReferenceField::coverageChanged, this, &ReferenceFieldGroup::propertiesChanged);
}

void ReferenceFieldGroup::setPanels(const std::vector<QWidget*>& widgets)
{
    panels.clear();
    for (QWidget* widget : widgets) {
        panels.emplace_back(widget);
    }
}

std::vector<ReferenceField*> ReferenceFieldGroup::fields() const
{
    std::vector<ReferenceField*> result;
    for (const auto& field : fieldList) {
        if (field) {
            result.push_back(field);
        }
    }
    return result;
}

bool ReferenceFieldGroup::isPanel(const QWidget* widget) const
{
    return std::ranges::any_of(panels, [widget](const auto& panel) {
        return panel.data() == widget;
    });
}

std::set<std::string> ReferenceFieldGroup::properties() const
{
    std::set<std::string> result;
    for (ReferenceField* field : fields()) {
        if (field->coversProperty()) {
            result.insert(field->propertyName());
        }
    }
    return result;
}

void ReferenceFieldGroup::armFirstEmpty()
{
    // Once the dialog shows, after the panels' own queued focus calls
    QTimer::singleShot(0, this, [this]() {
        for (ReferenceField* field : fields()) {
            if (field->isRequired() && field->isEnabled() && field->entries().empty()) {
                field->setArmed(true);
                field->list()->setFocus(Qt::OtherFocusReason);
                return;
            }
        }
    });
}

void ReferenceFieldGroup::disarm()
{
    for (ReferenceField* field : fields()) {
        field->setArmed(false);
    }
}

void ReferenceFieldGroup::fieldArming(ReferenceField* field)
{
    for (ReferenceField* other : fields()) {
        if (other != field) {
            other->setArmed(false);
        }
    }
}

void ReferenceFieldGroup::onFocusChanged(QWidget* /*old*/, QWidget* now)
{
    if (!now) {
        return;
    }
    for (ReferenceField* field : fields()) {
        if (field == now || field->isAncestorOf(now)) {
            return;  // the field arms itself
        }
    }
    // Another input of the dialog: the 3D view, the tree and other windows keep the field armed
    for (const auto& panel : panels) {
        if (panel && panel->isAncestorOf(now)) {
            disarm();
            return;
        }
    }
}

#include "moc_ReferenceField.cpp"
