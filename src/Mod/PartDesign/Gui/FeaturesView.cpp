// SPDX-License-Identifier: LGPL-2.1-or-later

#include "FeaturesView.h"

#include <algorithm>
#include <map>
#include <set>

#include <TopoDS_Iterator.hxx>

#include <cmath>

#include <QAction>
#include <QApplication>
#include <QCheckBox>
#include <QComboBox>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPointer>
#include <QTimer>
#include <QCoreApplication>
#include <QEvent>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QMouseEvent>
#include <QPainter>
#include <QRegularExpression>
#include <QScopedValueRollback>
#include <QScrollBar>
#include <QSignalBlocker>
#include <QSplitter>
#include <QStyle>
#include <QToolButton>
#include <QTreeWidgetItemIterator>
#include <QVBoxLayout>

#include <App/Application.h>
#include <App/Datums.h>
#include <App/Document.h>
#include <App/DocumentTabs.h>
#include <App/DocumentObject.h>
#include <App/ElementNamingUtils.h>
#include <App/DocumentObjectGroup.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/GeoFeature.h>
#include <App/GroupExtension.h>
#include <App/Link.h>
#include <App/Origin.h>
#include <App/OriginGroupExtension.h>
#include <App/Part.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <App/SuppressibleExtension.h>
#include <App/ConfigurationHooks.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Interpreter.h>
#include <Base/Quantity.h>
#include <Base/Unit.h>
#include <Gui/ActiveObjectList.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/Document.h>
#include <Gui/DockWindowManager.h>
#include <Gui/DocumentTabBar.h>
#include <Gui/ForkKeymap.h>
#include <Gui/MainWindow.h>
#include <Gui/MDIView.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Gui/Workbench.h>
#include <Gui/WorkbenchManager.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/Gui/ViewProviderExt.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/DatumPlane.h>
#include <Mod/PartDesign/App/Feature.h>
#include <Mod/PartDesign/App/FeatureBoolean.h>
#include <Mod/PartDesign/App/FeatureChamfer.h>
#include <Mod/PartDesign/App/FeatureFillet.h>
#include <Mod/PartDesign/App/FeatureSketchBased.h>
#include <Mod/PartDesign/App/Derived.h>
#include <Mod/PartDesign/App/FeatureBase.h>
#include <Mod/PartDesign/App/FeatureDeletePart.h>
#include <Mod/PartDesign/App/ShapeBinder.h>
#include <Mod/PartDesign/App/Studio.h>
#include <Mod/PartDesign/App/StudioConfig.h>
#include <Mod/PartDesign/App/StudioList.h>
#include <Mod/Sketcher/App/SketchObject.h>

#include "ViewProviderBody.h"

using namespace PartDesignGui;

namespace PartDesign
{
// App/StudioList.cpp (FreeCAD-CH ops#654 P6a; declared where used)
PartDesignExport std::vector<Body*> studioLivePartsAt(const StudioList* list, int index);
}  // namespace PartDesign

namespace PartDesignGui
{
// StudioGui.cpp (ops#654 P6a): a part's name in lists, default names positional
QString studioPartName(const PartDesign::Body* body);
}  // namespace PartDesignGui

QPointer<FeaturesView> FeaturesView::registered;

namespace PartDesignGui
{

/** FreeCAD-CH (ops#640 rank 35, blind test F45; round 8): obj's status message \a message in the
 * user's words, as the rows' tooltips show it, and under the Onshape keymap the dialogs' banner
 * and their reference fields' status line (the report view keeps the technical text). Declared
 * where it is used (no header names it).
 *
 * A failure passed on from an input reads "Depends on 'Square', which failed", not the
 * recompute's "ReferenceAxis links to 'Square', which has an error" (a property the user never
 * set); a reference a reorder set aside "Depends on 'Pad', which now comes after 'Pocket'"; a
 * missing reference "Edge15 is missing", without where it is and its candidates (the field's rows
 * show those). A C++ exception's type or OCCT's raw text ("BRep_API: command not done",
 * "Standard_ConstructionError") reads as a failed operation, a fillet's or a chamfer's with what
 * to try [guess on the words]; an empty dress-up says what to pick; an extrusion's message loses
 * its "SketchBased: ".
 */
QString plainStatusText(const App::DocumentObject* obj, const QString& message);
QString plainStatusText(const App::DocumentObject* obj, const QString& message)
{
    auto tr = [](const char* source) {
        return QCoreApplication::translate("PartDesignGui::FeaturesView", source);
    };
    QString text = message.trimmed();
    static const QRegularExpression passedOn(
        QStringLiteral(R"(^(?:\w+ links to '(.*)', which has an error|'(.*)' has an error)$)")
    );
    if (auto match = passedOn.match(text); match.hasMatch()) {
        const QString input = match.captured(1).isEmpty() ? match.captured(2) : match.captured(1);
        return tr("Depends on '%1', which failed").arg(input);
    }
    static const QRegularExpression setAside(
        QStringLiteral(R"(^\w+ refers to '(.*?)', which (.*)$)")
    );
    if (auto match = setAside.match(text); match.hasMatch()) {
        return tr("Depends on '%1', which %2").arg(match.captured(1), match.captured(2));
    }
    const bool fillet = obj && obj->isDerivedFrom<PartDesign::Fillet>();
    const bool chamfer = obj && obj->isDerivedFrom<PartDesign::Chamfer>();
    static const QRegularExpression internal(QStringLiteral(
        R"(\b(?:BRep\w*API\w*|Standard_\w+|StdFail_\w+|gp_\w+|TopoDS::\w+|Base::\w+|Part::\w+Exception|std::\w+)\b)"
        R"(|command not done|Unknown C\+\+ exception)"
    ));
    if (internal.match(text).hasMatch()) {
        if (fillet) {
            return tr("The fillet could not be built: try a smaller radius");
        }
        if (chamfer) {
            return tr("The chamfer could not be built: try a smaller size");
        }
        return tr("The geometry operation failed: change the inputs or the values");
    }
    // Nothing to work on: what to pick
    if (chamfer && text == QLatin1String("No edges specified")) {
        return tr("Select edges or faces to chamfer");
    }
    if (fillet && text == QLatin1String("Fillet not possible on selected shapes")) {
        auto feature = static_cast<const PartDesign::Fillet*>(obj);
        if (feature->Base.getSubValues().empty() && !feature->UseAllEdges.getValue()) {
            return tr("Select edges or faces to fillet");
        }
    }
    // "Missing edge reference: Edge15 (Base[0], no candidates)", with its ", rejected: ..." or
    // ", picked for ..."; a reorder's "; it was on 'Pad', ..." after it stays
    static const QRegularExpression missing(QStringLiteral(
        R"(Missing \w+ reference: (\w+)(?:, (?:rejected:|picked for) [^(;]*)? \((?:[^()]|\([^()]*\))*\))"
    ));
    if (text.contains(missing)) {
        QString plain;
        qsizetype at = 0;
        for (auto it = missing.globalMatch(text); it.hasNext();) {
            const auto match = it.next();
            plain += text.mid(at, match.capturedStart() - at);
            plain += tr("%1 is missing").arg(match.captured(1));
            at = match.capturedEnd();
        }
        return plain + text.mid(at);
    }
    const QLatin1String sketchBased("SketchBased: ");
    if (text.startsWith(sketchBased)) {
        text = text.mid(sketchBased.size());
    }
    return text;
}

}  // namespace PartDesignGui

namespace
{

constexpr const char* paramPath = "User parameter:BaseApp/Preferences/Mod/PartDesign";

/// Why the studio's bar doesn't move during an edit (as ViewProviderBody::rollBar())
constexpr const char* editLockedMessage = QT_TRANSLATE_NOOP(
    "Exception",
    "The bodies can't roll back while a dialog or an edit is open"
);

/// Why the features don't move during an edit (design 3.3, the bar's rule)
constexpr const char* reorderLockedMessage = QT_TRANSLATE_NOOP(
    "Exception",
    "The features can't be reordered while a dialog or an edit is open"
);

bool inPartDesign()
{
    auto wb = Gui::WorkbenchManager::instance()->active();
    return wb && wb->name() == "PartDesignWorkbench";
}

/// A sketch of a Body is in edit: its EditingWorkbench (the Sketcher's) was activated for it
/// (ViewProviderSketch::setEdit), and the edit is set before that (Gui::Document::setEdit)
bool editingBodySketch()
{
    auto gdoc = Gui::Application::Instance->editDocument();
    auto vp = gdoc ? freecad_cast<Gui::ViewProviderDocumentObject*>(gdoc->getEditViewProvider()) : nullptr;
    auto obj = vp ? vp->getObject() : nullptr;
    return obj && obj->isDerivedFrom<Part::Part2DObject>() && PartDesign::Body::findBodyOf(obj);
}

/// FreeCAD-CH (ops#640 round 10, gap A27): under the Onshape keymap the Assembly workbench shows
/// an Assembly tab's list in the Model panel, as Onshape's assembly list
bool inAssemblyUnderOnshape()
{
    auto wb = Gui::WorkbenchManager::instance()->active();
    return Gui::ForkKeymap::isOnshape() && wb && wb->name() == "AssemblyWorkbench";
}

/// The assembly of view's tab, when it is an Assembly tab; else null
App::DocumentObject* assemblyOfView(const Gui::MDIView* view)
{
    App::Document* doc = view ? view->getAppDocument() : nullptr;
    const std::string tab = doc ? Gui::DocumentTabs::tabOfView(view) : std::string();
    App::DocumentObject* obj = tab.empty() ? nullptr : doc->getObject(tab.c_str());
    App::DocumentTabs::Kind kind {};
    if (obj && App::DocumentTabs::isTabObject(obj, &kind) && kind == App::DocumentTabs::Kind::Assembly) {
        return obj;
    }
    return nullptr;
}

/// An Assembly tab is the active one, in the Assembly workbench under the Onshape keymap
bool assemblyTabActive()
{
    if (!inAssemblyUnderOnshape()) {
        return false;
    }
    auto gdoc = Gui::Application::Instance->activeDocument();
    return gdoc && assemblyOfView(gdoc->getActiveView());
}

/// A row of an assembly's Instances: a part, a link or a subassembly in it; not its groups (the
/// joints, the views, the snapshots...) nor its datums (mate connectors aren't listed yet)
bool isInstance(const App::DocumentObject* obj)
{
    if (obj->isDerivedFrom<App::DocumentObjectGroup>() || obj->isDerivedFrom<App::LocalCoordinateSystem>()
        || obj->isDerivedFrom<App::DatumElement>()) {
        return false;
    }
    return obj->isDerivedFrom<App::GeoFeature>()
        || obj->hasExtension(App::LinkBaseExtension::getExtensionClassTypeId());
}

/// A joint's own Suppressed (a property of the Python joint, not the suppressible extension)
bool mateSuppressed(const App::DocumentObject* obj)
{
    auto prop = freecad_cast<App::PropertyBool*>(obj->getPropertyByName("Suppressed"));
    return prop && prop->getValue();
}

/// The lists stay in the Model panel: in PartDesign, and in the workbench a Body's sketch opened
/// for its edit, as Onshape keeps its Feature list while a sketch is edited (ops#640); and in an
/// Assembly tab under the Onshape keymap, its list (round 10)
bool listsBelong()
{
    if (inPartDesign() || assemblyTabActive()) {
        return true;
    }
    auto wb = Gui::WorkbenchManager::instance()->active();
    return wb && wb->name() == "SketcherWorkbench" && editingBodySketch();
}

/// The Model panel's splitter (the Combo view: the tree above the Properties panel), or null when
/// the Combo view is turned off
QSplitter* modelSplitter()
{
    QWidget* combo = Gui::DockWindowManager::instance()->findRegisteredDockWindow("Std_ComboView");
    return combo ? combo->findChild<QSplitter*>(QString(), Qt::FindDirectChildrenOnly) : nullptr;
}

/// The tree in the Model panel's splitter (Gui::TreePanel, not exported: found by class name)
QWidget* treePanelOf(QSplitter* splitter)
{
    for (int i = 0; splitter && i < splitter->count(); ++i) {
        QWidget* widget = splitter->widget(i);
        if (qstrcmp(widget->metaObject()->className(), "Gui::TreePanel") == 0) {
            return widget;
        }
    }
    return nullptr;
}

/// Shows the lists or the tree in the Model panel
void showLists(bool lists)
{
    auto splitter = modelSplitter();
    auto tree = treePanelOf(splitter);
    if (auto view = FeaturesView::instance()) {
        view->setVisible(lists);
    }
    if (tree) {
        tree->setVisible(!lists || !FeaturesView::instance());
    }
}

Gui::ViewProviderDocumentObject* viewProviderOf(const App::DocumentObject* obj)
{
    return freecad_cast<Gui::ViewProviderDocumentObject*>(
        Gui::Application::Instance->getViewProvider(obj)
    );
}

/// The tree's status look (Tree.cpp, DocumentObjectItem::testStatus): the icon with the error,
/// warning, held or recompute overlay at its top right
QIcon statusIcon(const App::DocumentObject* obj, bool held)
{
    auto vp = viewProviderOf(obj);
    QIcon icon = vp ? vp->getIcon() : QIcon();
    const char* overlay = nullptr;
    if (obj->isError()) {
        overlay = "overlay_error";
    }
    else if (obj->isWarning()) {
        overlay = "overlay_warning";
    }
    else if (held) {
        overlay = "overlay_rolledback";
    }
    else if (obj->isTouched() || obj->mustExecute() == 1) {
        overlay = "overlay_recompute";
    }
    if (!overlay) {
        return icon;
    }
    QPixmap px = Gui::BitmapFactory().pixmapFromSvg(overlay, QSize(10, 10));
    return QIcon(Gui::BitmapFactory().merge(icon.pixmap(16, 16), px, Gui::BitmapFactoryInst::TopRight));
}

bool isSuppressed(const App::DocumentObject* obj)
{
    if (auto suppressible = obj->getExtensionByType<App::SuppressibleExtension>(true)) {
        return suppressible->Suppressed.getValue();
    }
    // FreeCAD-CH ops#654 S3: a studio feature without the extension has its own Suppressed
    auto prop = freecad_cast<App::PropertyBool*>(obj->getPropertyByName("Suppressed"));
    return prop && prop->getValue();
}

/// Italic for a held object, struck through for a suppressed one, as in the tree
QFont statusFont(QFont font, const App::DocumentObject* obj, bool held)
{
    font.setItalic(held);
    font.setStrikeOut(isSuppressed(obj));
    return font;
}

/// The Merge folded into obj's row: its merge scope, the accepted one right after an Add (Onshape
/// lists no merge of its own, ops#640 rank 1); or null. A Merge Parts made and not accepted yet, or
/// one after a cut, keeps its own row, where its panel and Accept are
const PartDesign::Boolean* foldedMerge(const App::DocumentObject* obj)
{
    return obj ? PartDesign::Boolean::scopeMerge(obj) : nullptr;
}

/// obj, or the Merge folded into its row: the bar and a drop after the row go after the Merge
App::DocumentObject* pastMerge(App::DocumentObject* obj)
{
    auto merge = foldedMerge(obj);
    return merge ? const_cast<PartDesign::Boolean*>(merge) : obj;
}

/// Whether obj is a Merge folded into its feature's row
bool isFoldedMerge(const App::DocumentObject* obj)
{
    auto merge = freecad_cast<const PartDesign::Boolean*>(obj);
    return merge && merge->isMerge() && foldedMerge(merge->BaseFeature.getValue()) == merge;
}

/// Whether obj is a Derived feature's member other than its lead: the lead's row stands for the
/// feature, as Onshape lists one Derived (ops#640 round 6)
bool isFoldedDerived(const App::DocumentObject* obj)
{
    auto lead = PartDesign::derivedLead(obj);
    return lead && lead != obj;
}

/// A Derived feature's lead: its other members, whose status its row shows; else none
std::vector<PartDesign::FeatureBase*> foldedDerived(const App::DocumentObject* obj)
{
    PartDesign::FeatureBase* lead = PartDesign::derivedLead(obj);
    if (!lead || lead != obj) {
        return {};
    }
    auto members = PartDesign::derivedMembers(lead);
    members.pop_back();
    return members;
}

/// What a row's status shows: a folded Merge's failure, warning or pending compute when its
/// feature has none of its own, else the feature's. A Derived feature's row shows the failure of
/// any of its parts
const App::DocumentObject* statusObject(const App::DocumentObject* obj)
{
    if (!obj->isError()) {
        for (auto member : foldedDerived(obj)) {
            if (member->isError()) {
                return member;
            }
        }
        // FreeCAD-CH ops#654 S3: a studio feature's row shows a failing step's status (its steps
        // have no rows)
        if (PartDesign::isStudioOwner(obj)) {
            for (auto step : PartDesign::StudioList::stepsOf(obj)) {
                if (step->isError()) {
                    return step;
                }
            }
        }
    }
    const PartDesign::Boolean* merge = foldedMerge(obj);
    if (!merge || obj->isError()) {
        return obj;
    }
    if (merge->isError() || (!obj->isWarning() && merge->isWarning())) {
        return merge;
    }
    return obj;
}

/// For each of bodies whose Tip isn't its old one, as the tree's bar does: shows the feature the
/// bar follows (which hides the Body's other features), or none at the very top. False when no
/// Tip moved
bool showMovedTips(const std::vector<PartDesign::Body*>& bodies, const std::vector<App::DocumentObject*>& oldTips)
{
    bool changed = false;
    for (std::size_t i = 0; i < bodies.size(); ++i) {
        auto body = bodies[i];
        App::DocumentObject* tip = body->Tip.getValue();
        if (tip == oldTips[i]) {
            continue;
        }
        changed = true;
        if (tip) {
            FCMD_OBJ_SHOW(tip);
        }
        else {
            for (auto obj : body->Group.getValues()) {
                if (PartDesign::Body::isSolidFeature(obj) && obj->Visibility.getValue()) {
                    FCMD_OBJ_HIDE(obj);
                }
            }
        }
    }
    return changed;
}

/// FreeCAD-CH (ops#640): a sketch whose conflict was solved around (its constraints left out, the
/// rest solved) is a warning to the document, but Onshape's list reads it red, as a failed feature
/// (PL1d: "Sketch could not be solved.")
bool sketchCouldNotSolve(const App::DocumentObject* obj)
{
    const auto* sketch = dynamic_cast<const Sketcher::SketchObject*>(obj);
    return sketch && sketch->getLastSolvedAroundConflict();
}

/// What a row shows of obj: its name, label and status (statusIcon(), statusFont(), and the
/// message of an error or a warning, rowToolTip())
std::string rowKey(const App::DocumentObject* obj, bool held, const std::string& extra = {})
{
    std::string key = obj->getNameInDocument();
    key += '\x1f';
    key += obj->Label.getValue();
    key += '\x1f';
    key += obj->isError() ? 'e' : obj->isWarning() ? 'w' : '-';
    key += sketchCouldNotSolve(obj) ? 'c' : '-';
    key += held ? 'h' : '-';
    key += obj->isTouched() || obj->mustExecute() == 1 ? 't' : '-';
    key += isSuppressed(obj) ? 's' : '-';
    if (obj->isError() || obj->isWarning()) {
        key += obj->getStatusString();
    }
    key += extra;
    return key;
}

/// Where obj's error comes from: the first object in error it reads, directly or through others
/// in error, that reads none in error itself (a pocket failing on its sketch's missing face: the
/// sketch); null when obj's error is its own. The message of a failure passed on names a link
/// property ("ReferenceAxis links to 'Square', which has an error", blind test F45); the cause's
/// says what to fix
const App::DocumentObject* errorCause(const App::DocumentObject* obj)
{
    std::set<const App::DocumentObject*> seen {obj};
    const App::DocumentObject* cause = nullptr;
    for (const App::DocumentObject* at = obj; at;) {
        const App::DocumentObject* next = nullptr;
        // Not through a container (a Body in error names its Tip, a later feature); the out-list
        // leaves the hidden links (a feature's _Body) out
        for (auto in : at->getOutList()) {
            if (in && in->isError() && !in->hasExtension(App::GroupExtension::getExtensionClassTypeId())
                && seen.insert(in).second) {
                next = in;
                break;
            }
        }
        if (next) {
            cause = next;
        }
        at = next;
    }
    return cause;
}

/// obj's status message in the user's words (PartDesignGui::plainStatusText()); the tooltip adds
/// the cause's own message (errorCause())
QString plainStatus(const App::DocumentObject* obj)
{
    return plainStatusText(obj, QString::fromUtf8(obj->getStatusString()));
}

/// The row's tooltip: its name and Body, the message of an error or a warning, and where an error
/// comes from (errorCause()), as Onshape's hover over a failed feature (blind test F38)
QString rowToolTip(const App::DocumentObject* obj, const App::DocumentObject* body)
{
    QString tip = QString::fromUtf8(obj->Label.getValue());
    if (body && body != obj) {
        tip = QObject::tr("%1 (%2)").arg(tip, QString::fromUtf8(body->Label.getValue()));
    }
    if (!obj->isError() && !obj->isWarning()) {
        return tip;
    }
    tip += QStringLiteral("\n") + plainStatus(obj);
    if (auto cause = obj->isError() ? errorCause(obj) : nullptr) {
        tip += QStringLiteral("\n")
            + QObject::tr("Caused by '%1': %2").arg(QString::fromUtf8(cause->Label.getValue()), plainStatus(cause));
    }
    return tip;
}

/// An error row's text is red, a warning's orange, as Onshape's (blind test F38), and a sketch
/// that could not be solved red (sketchCouldNotSolve()); other rows keep the palette's
QVariant statusForeground(const App::DocumentObject* obj)
{
    if (obj->isError() || sketchCouldNotSolve(obj)) {
        return QBrush(QColor(0xd0, 0x30, 0x30));
    }
    if (obj->isWarning()) {
        return QBrush(QColor(0xc8, 0x78, 0x00));
    }
    return {};
}

/// The studio's parts: its Bodies with a solid feature at or above their bar, and the other solids
/// at its level (an imported shape, a Part workbench feature) that no other shape reads. A part
/// exists only while the history makes it, as in Onshape (ops#635): a Body whose new-part feature
/// was deleted, whose bar is at its top, or that a Delete part deleted, isn't one; it keeps its
/// sketches, and shows nothing
std::vector<App::DocumentObject*> studioParts(App::Document* doc, App::Part* studio)
{
    // A part exists at the bar while one of its solid features above it makes a solid, and no
    // Merge above its own bar absorbed it, as Onshape lists no part whose features all fail or that
    // an Add merged away (blind test F37, F26; report 10)
    auto exists = [](PartDesign::Body* body) {
        if (auto merge = PartDesign::Boolean::mergeOf(body)) {
            auto into = PartDesign::Body::findBodyOf(merge);
            if (!isSuppressed(merge) && !(into && into->holds(merge))) {
                return false;
            }
        }
        // A Boolean's tool with Keep tools off is consumed, as Onshape deletes it (ops#640 rank 28,
        // B3-3a); a tool a Union left apart stays a part (A-2' b)
        if (PartDesign::Boolean::consumerOf(body)) {
            return false;
        }
        return std::ranges::any_of(body->Group.getValues(), [body](App::DocumentObject* obj) {
            auto feature = freecad_cast<Part::Feature*>(obj);
            return feature && PartDesign::Body::isSolidFeature(obj) && !body->holds(obj) && !obj->isError()
                && !isSuppressed(obj) && !feature->Shape.getShape().isNull();
        });
    };
    // A studio with a history list (FreeCAD-CH ops#654 P6a, report 26): only the parts live at
    // its bar, the App's one query (no part a Boolean consumed or a merge absorbed there)
    const PartDesign::StudioList* list = PartDesign::StudioList::of(doc, studio);
    std::vector<PartDesign::Body*> live;
    if (list) {
        live = PartDesign::studioLivePartsAt(list, -1);
    }
    std::vector<App::DocumentObject*> parts;
    for (auto body : PartDesign::studioBodies(doc, studio)) {
        if (list && std::ranges::find(live, body) == live.end()) {
            continue;
        }
        if (body->Tip.getValue() && !PartDesign::DeletePart::deleterOf(body) && exists(body)) {
            parts.push_back(body);
        }
    }
    std::vector<App::DocumentObject*> candidates;
    if (studio) {
        candidates = studio->Group.getValues();
    }
    else {
        for (auto obj : doc->getObjects()) {
            if (!App::GroupExtension::getGroupOfObject(obj)
                && !App::GeoFeatureGroupExtension::getGroupOfObject(obj)) {
                candidates.push_back(obj);
            }
        }
    }
    for (auto obj : candidates) {
        if (!obj || !obj->isDerivedFrom<Part::Feature>() || obj->isDerivedFrom<Part::BodyBase>()
            || Part::BodyBase::findBodyOf(obj)) {
            continue;
        }
        auto vp = viewProviderOf(obj);
        if (!vp || !vp->showInTree()) {
            continue;
        }
        // A tool of another shape (a Cut's, a Body's base feature) is part of that shape
        bool read = std::ranges::any_of(obj->getInList(), [](App::DocumentObject* in) {
            return in && in->isDerivedFrom<App::GeoFeature>()
                && !in->hasExtension(App::GroupExtension::getExtensionClassTypeId());
        });
        if (!read) {
            parts.push_back(obj);
        }
    }
    return parts;
}

/// How many Parts rows a part has (ops#640 rank 3b, hands-on A-2' a): a Body has one per solid at
/// its bar, as Onshape makes a part of each piece a Remove cuts apart (the Body stays one, with
/// AllowCompound), and none when an Intersect that missed left it empty (A-2' c); anything else,
/// or a Body with no shape yet, has one
int partPieces(const App::DocumentObject* obj)
{
    auto body = freecad_cast<const PartDesign::Body*>(obj);
    if (!body) {
        return 1;
    }
    const Part::TopoShape& shape = body->Shape.getShape();
    if (shape.isNull()) {
        return 1;
    }
    const int solids = shape.countSubShapes(TopAbs_SOLID);
    if (solids > 0) {
        return solids;
    }
    return TopoDS_Iterator(shape.getShape()).More() ? 1 : 0;
}

/** Onshape's default geometry rows at the top of the Features list (ops#640 rank 33): Origin, Top,
 * Front and Right, of the studio's own Origin (an App::Part's), or at the top level of the first
 * Body's (each Body has one; they coincide while the Bodies aren't moved)
 */
std::vector<std::pair<App::DocumentObject*, QString>> defaultGeometry(App::Document* doc, App::Part* studio)
{
    App::DocumentObject* owner = studio;
    if (!owner) {
        const auto bodies = PartDesign::studioBodies(doc, nullptr);
        owner = bodies.empty() ? nullptr : bodies.front();
    }
    auto group = owner ? owner->getExtensionByType<App::OriginGroupExtension>(true) : nullptr;
    auto origin = group ? freecad_cast<App::Origin*>(group->Origin.getValue()) : nullptr;
    if (!origin) {
        return {};
    }
    std::vector<std::pair<App::DocumentObject*, QString>> rows;
    auto add = [&rows](App::DocumentObject* obj, const QString& label) {
        if (obj && obj->isAttachedToDocument()) {
            rows.emplace_back(obj, label);
        }
    };
    try {
        add(origin->getOrigin(), FeaturesView::tr("Origin"));
        add(origin->getXY(), FeaturesView::tr("Top"));
        add(origin->getXZ(), FeaturesView::tr("Front"));
        add(origin->getYZ(), FeaturesView::tr("Right"));
    }
    catch (const Base::Exception&) {
        // An Origin missing an element (a damaged file): no default rows
        return {};
    }
    return rows;
}

/// A row with an eye (ops#640 rank 33): a sketch, a plane (a datum plane, a default plane or the
/// origin) or a binder, as Onshape's; a solid's visibility follows the bar
bool hasEye(const App::DocumentObject* obj)
{
    return obj
        && (obj->isDerivedFrom<Part::Part2DObject>() || obj->isDerivedFrom<PartDesign::Plane>()
            || obj->isDerivedFrom<App::Plane>() || obj->isDerivedFrom<App::Point>()
            || obj->isDerivedFrom<PartDesign::ShapeBinder>()
            || obj->isDerivedFrom<PartDesign::SubShapeBinder>());
}

/// Whether obj is shown: a default plane only with its Origin
bool rowShown(const App::DocumentObject* obj)
{
    auto vp = viewProviderOf(obj);
    if (!vp || !vp->isShow()) {
        return false;
    }
    auto element = freecad_cast<const App::DatumElement*>(obj);
    auto lcs = element ? element->getLCS() : nullptr;
    auto lcsVp = lcs ? viewProviderOf(lcs) : nullptr;
    return !lcsVp || lcsVp->isShow();
}

/// A row's EyeRole value: 0 none, 1 shown, 2 hidden
int eyeState(const App::DocumentObject* obj)
{
    if (!hasEye(obj)) {
        return 0;
    }
    return rowShown(obj) ? 1 : 2;
}

/// The filter box's text matches obj: its label or its type, case aside; ":errors" and
/// ":warnings" its status, the one its row shows (statusObject()) (Onshape's filter, ref-D #23)
bool matchesFilter(const App::DocumentObject* obj, const App::DocumentObject* status, const QString& filter)
{
    const QString text = filter.trimmed();
    if (text.isEmpty()) {
        return true;
    }
    if (text.compare(QStringLiteral(":errors"), Qt::CaseInsensitive) == 0) {
        return status->isError();
    }
    if (text.compare(QStringLiteral(":warnings"), Qt::CaseInsensitive) == 0) {
        return status->isWarning();
    }
    return QString::fromUtf8(obj->Label.getValue()).contains(text, Qt::CaseInsensitive)
        || QString::fromLatin1(obj->getTypeId().getName()).contains(text, Qt::CaseInsensitive);
}

/// The object in edit in doc (its dialog open), or null
App::DocumentObject* objectInEdit(App::Document* doc)
{
    auto gdoc = doc ? Gui::Application::Instance->getDocument(doc) : nullptr;
    auto vp = gdoc ? freecad_cast<Gui::ViewProviderDocumentObject*>(gdoc->getInEdit()) : nullptr;
    return vp ? vp->getObject() : nullptr;
}

// FreeCAD-CH ops#654 S3: the rows of a studio with a list (notes/parts-design.md 3.5) are its
// entries: a studio feature (owner) is one row for all its steps, which have none

/// The row obj is shown in: its owner's for a step, else its own
App::DocumentObject* entryOfRow(App::DocumentObject* obj)
{
    if (PartDesign::StudioList::isStep(obj)) {
        if (auto owner = static_cast<PartDesign::Feature*>(obj)->StudioOwner.getValue()) {
            return owner;
        }
    }
    return obj;
}

/// The rows of a studio with list: studioSequence() (the list's order: members, and each owner's
/// steps) with the steps folded into their owner's row, and the owners acting on no part after the
/// entry before them. barRow: the row the bar goes before, the first one the list's bar holds
std::vector<App::DocumentObject*> listRows(const PartDesign::StudioList* list,
                                           App::Document* doc,
                                           App::Part* studio,
                                           std::size_t& barRow)
{
    std::vector<App::DocumentObject*> rows;
    std::set<const App::DocumentObject*> listed;
    for (auto obj : PartDesign::studioSequence(doc, studio)) {
        auto row = entryOfRow(obj);
        if (listed.insert(row).second) {
            rows.push_back(row);
        }
    }
    std::vector<App::DocumentObject*> entries;
    for (auto entry : list->Entries.getValues()) {
        if (entry) {
            entries.push_back(entry);
        }
    }
    for (std::size_t i = 0; i < entries.size(); ++i) {
        if (listed.count(entries[i])) {
            continue;
        }
        std::size_t at = 0;
        for (std::size_t j = i; j-- > 0;) {
            auto it = std::ranges::find(rows, entries[j]);
            if (it != rows.end()) {
                at = static_cast<std::size_t>(it - rows.begin()) + 1;
                break;
            }
        }
        rows.insert(rows.begin() + static_cast<std::ptrdiff_t>(at), entries[i]);
        listed.insert(entries[i]);
    }
    const int bar = std::clamp(list->barIndex(), 0, static_cast<int>(entries.size()));
    const std::set<const App::DocumentObject*> held(entries.begin() + bar, entries.end());
    barRow = rows.size();
    for (std::size_t r = 0; r < rows.size(); ++r) {
        if (held.count(rows[r])) {
            barRow = r;
            break;
        }
    }
    return rows;
}

/// The entry at the list's bar (null at its end, or without a list): a bar or a drag moved it
const App::DocumentObject* entryAtBar(const PartDesign::StudioList* list)
{
    if (!list) {
        return nullptr;
    }
    const auto& entries = list->Entries.getValues();
    const int bar = list->barIndex();
    return bar >= 0 && bar < static_cast<int>(entries.size()) ? entries[bar] : nullptr;
}

/// The rows a menu action acts on: the selected ones, or clicked when it isn't one of them
std::vector<App::DocumentObject*> rowsActedOn(const std::vector<App::DocumentObject*>& selected,
                                              App::DocumentObject* clicked)
{
    if (!clicked || std::ranges::find(selected, clicked) != selected.end()) {
        return selected;
    }
    return {clicked};
}

std::string documentCmd(const App::Document* doc)
{
    return std::string("App.getDocument('") + doc->getName() + "')";
}

bool anyOwner(const std::vector<App::DocumentObject*>& rows)
{
    return std::ranges::any_of(rows, [](const App::DocumentObject* obj) {
        return PartDesign::isStudioOwner(obj);
    });
}

/** Delete on rows of which one is a studio feature, in one undo step "Delete": an owner leaves the
 * list, its steps with it (PartDesign.studioRemove), and is deleted; a Body member is deleted as
 * Std_Delete deletes it (its view provider's onDelete(), then removeObject). Not Std_Delete itself,
 * which would ask about the steps that read the owner. False when no row is an owner: Std_Delete
 * runs, as before. Throws Base::Exception (an open edit, a refusal)
 */
bool deleteOwnerRows(App::Document* doc, const std::vector<App::DocumentObject*>& rows)
{
    if (!doc || !anyOwner(rows)) {
        return false;
    }
    if (ViewProviderBody::isEditLocked(doc)) {
        throw Base::RuntimeError(editLockedMessage);
    }
    // By name: one delete may take another row's object with it
    std::vector<std::string> names;
    for (auto obj : rows) {
        names.emplace_back(obj->getNameInDocument());
    }
    int tid = doc->openTransaction(QT_TRANSLATE_NOOP("Command", "Delete"));
    if (tid == 0 && doc->isStepLocked()) {
        throw Base::RuntimeError("Finish the open dialog first");
    }
    try {
        Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
        for (const auto& name : names) {
            App::DocumentObject* obj = doc->getObject(name.c_str());
            if (!obj) {
                continue;
            }
            if (PartDesign::isStudioOwner(obj)) {
                Gui::Command::doCommand(
                    Gui::Command::Doc,
                    "PartDesign.studioRemove(%s)",
                    Gui::Command::getObjectCmd(obj).c_str()
                );
            }
            else if (auto vp = viewProviderOf(obj); !vp || !vp->onDelete({})) {
                continue;
            }
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "%s.removeObject('%s')",
                documentCmd(doc).c_str(),
                name.c_str()
            );
        }
        Gui::Command::doCommand(Gui::Command::Doc, "%s.recompute()", documentCmd(doc).c_str());
        App::GetApplication().commitTransaction(tid);
    }
    catch (const Base::Exception&) {
        App::GetApplication().abortTransaction(tid);
        throw;
    }
    return true;
}

/** Suppress or Unsuppress (on) on rows of which one is a studio feature, in one undo step: an owner
 * by PartDesign.studioSuppress (its steps follow), a Body member by its Suppressed. False when no
 * row is an owner: Std_ToggleSuppress runs, as before. Throws Base::Exception
 */
bool suppressOwnerRows(App::Document* doc, const std::vector<App::DocumentObject*>& rows, bool on)
{
    if (!doc || !anyOwner(rows)) {
        return false;
    }
    if (ViewProviderBody::isEditLocked(doc)) {
        throw Base::RuntimeError(editLockedMessage);
    }
    int tid = doc->openTransaction(
        on ? QT_TRANSLATE_NOOP("Command", "Suppress") : QT_TRANSLATE_NOOP("Command", "Unsuppress")
    );
    if (tid == 0 && doc->isStepLocked()) {
        throw Base::RuntimeError("Finish the open dialog first");
    }
    try {
        Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
        const char* value = on ? "True" : "False";
        for (auto obj : rows) {
            const std::string cmd = Gui::Command::getObjectCmd(obj);
            if (PartDesign::isStudioOwner(obj)) {
                Gui::Command::doCommand(
                    Gui::Command::Doc,
                    "PartDesign.studioSuppress(%s, %s)",
                    cmd.c_str(),
                    value
                );
            }
            else if (freecad_cast<App::PropertyBool*>(obj->getPropertyByName("Suppressed"))) {
                Gui::Command::doCommand(Gui::Command::Doc, "%s.Suppressed = %s", cmd.c_str(), value);
            }
        }
        Gui::Command::doCommand(Gui::Command::Doc, "%s.recompute()", documentCmd(doc).c_str());
        App::GetApplication().commitTransaction(tid);
    }
    catch (const Base::Exception&) {
        App::GetApplication().abortTransaction(tid);
        throw;
    }
    return true;
}

}  // namespace

// ------------------------------------------------------------------------------- FeatureList

FeatureList::FeatureList(QWidget* parent)
    : QListWidget(parent)
{}

QListWidgetItem* FeatureList::barItem() const
{
    for (int i = 0; i < count(); ++i) {
        if (item(i)->type() == BarType) {
            return item(i);
        }
    }
    return nullptr;
}

QRect FeatureList::eyeRect(const QRect& row)
{
    const int size = std::min(16, row.height());
    return {row.right() - size - 3, row.center().y() - size / 2, size, size};
}

int FeatureList::dropRowAt(const QPoint& pos) const
{
    // Before the row under the cursor, or after it in the row's lower half
    if (auto target = itemAt(pos)) {
        return row(target) + (pos.y() > visualItemRect(target).center().y() ? 1 : 0);
    }
    return pos.y() < 0 ? 0 : count();
}

void FeatureList::endRowDrag()
{
    rowPressed = false;
    rowDragging = false;
    pressDeferred = false;
    dropRow = -1;
    unsetCursor();
    viewport()->update();
}

void FeatureList::mousePressEvent(QMouseEvent* event)
{
    QPoint pos = event->position().toPoint();
    auto pressed = itemAt(pos);
    if (event->button() == Qt::LeftButton && pressed && pressed->type() == BarType) {
        dragging = true;
        barMoved = false;
        setCursor(Qt::ClosedHandCursor);
        event->accept();
        return;
    }
    // A click on a row's eye shows or hides its object, leaving the selection (ops#640 rank 33)
    if (event->button() == Qt::LeftButton && pressed && pressed->data(EyeRole).toInt() != 0
        && eyeRect(visualItemRect(pressed)).contains(pos)) {
        event->accept();
        Q_EMIT eyeClicked(pressed);
        return;
    }
    // A plain press on a row may start a drag of the selected rows (ops#632). On a row of a
    // selection of several it keeps the selection until the release, as Qt does with drags on
    if (event->button() == Qt::LeftButton && pressed && event->modifiers() == Qt::NoModifier) {
        rowPressed = true;
        pressPos = pos;
        if (pressed->isSelected() && selectedItems().size() > 1) {
            pressDeferred = true;
            event->accept();
            return;
        }
    }
    QListWidget::mousePressEvent(event);
}

void FeatureList::mouseMoveEvent(QMouseEvent* event)
{
    if (rowPressed) {
        QPoint pos = event->position().toPoint();
        if (!rowDragging && (event->buttons() & Qt::LeftButton)
            && (pos - pressPos).manhattanLength() >= QApplication::startDragDistance()) {
            rowDragging = true;
            setCursor(Qt::ClosedHandCursor);
        }
        if (rowDragging) {
            dropRow = dropRowAt(pos);
            viewport()->update();
        }
        // Not the list's own drag selection: the press is a drag's
        event->accept();
        return;
    }
    auto bar = barItem();
    if (!dragging || !bar) {
        QListWidget::mouseMoveEvent(event);
        return;
    }
    // The bar goes before the row under the cursor, or after it in the row's lower half
    QPoint pos = event->position().toPoint();
    int from = row(bar);
    int to = 0;
    if (auto target = itemAt(pos)) {
        to = row(target) + (pos.y() > visualItemRect(target).center().y() ? 1 : 0);
    }
    else {
        to = pos.y() < 0 ? 0 : count();
    }
    if (to > from) {
        --to;  // taking the bar out moves the rows below it up
    }
    if (to != from) {
        takeItem(from);
        insertItem(to, bar);
        barMoved = true;
    }
    event->accept();
}

void FeatureList::mouseReleaseEvent(QMouseEvent* event)
{
    if (rowDragging) {
        int before = dropRow;
        endRowDrag();
        event->accept();
        Q_EMIT rowsDropped(before);
        return;
    }
    if (pressDeferred) {
        // A click on a row of the selection, without a drag: the press it held back
        QMouseEvent press(
            QEvent::MouseButtonPress,
            event->position(),
            event->globalPosition(),
            Qt::LeftButton,
            Qt::LeftButton,
            Qt::NoModifier
        );
        QListWidget::mousePressEvent(&press);
    }
    if (rowPressed) {
        endRowDrag();
    }
    if (!dragging) {
        QListWidget::mouseReleaseEvent(event);
        return;
    }
    dragging = false;
    unsetCursor();
    event->accept();
    auto bar = barItem();
    if (bar && !barMoved) {
        // A click: the bar is selected, for the arrow keys (Onshape)
        clearSelection();
        setCurrentItem(bar);
        bar->setSelected(true);
        return;
    }
    if (bar) {
        Q_EMIT barDropped(row(bar) - 1);
    }
}

void FeatureList::keyPressEvent(QKeyEvent* event)
{
    if (rowDragging && event->key() == Qt::Key_Escape) {
        endRowDrag();
        event->accept();
        return;
    }
    if (dragging && event->key() == Qt::Key_Escape) {
        dragging = false;
        unsetCursor();
        event->accept();
        Q_EMIT barDragCancelled();
        return;
    }
    // With the bar selected, Up and Down step it one row (Onshape, ref-D 3.11)
    auto bar = barItem();
    if (bar && bar->isSelected() && currentItem() == bar && event->modifiers() == Qt::NoModifier
        && (event->key() == Qt::Key_Up || event->key() == Qt::Key_Down)) {
        event->accept();
        Q_EMIT barStepped(event->key() == Qt::Key_Up ? -1 : 1);
        return;
    }
    QListWidget::keyPressEvent(event);
}

void FeatureList::paintEvent(QPaintEvent* event)
{
    QListWidget::paintEvent(event);
    if (!rowDragging || dropRow < 0 || count() == 0) {
        return;
    }
    // Where the dragged rows go: a line in the highlight colour
    int y = dropRow < count() ? visualItemRect(item(dropRow)).top()
                              : visualItemRect(item(count() - 1)).bottom() + 1;
    QPainter painter(viewport());
    painter.setPen(QPen(palette().color(QPalette::Highlight), 2));
    painter.drawLine(0, y, viewport()->width(), y);
}

void FeatureBarDelegate::paint(QPainter* painter, const QStyleOptionViewItem& option, const QModelIndex& index) const
{
    auto list = qobject_cast<const FeatureList*>(parent());
    auto item = list ? list->item(index.row()) : nullptr;
    if (!item || item->type() != FeatureList::BarType) {
        QStyledItemDelegate::paint(painter, option, index);
        // The eye of a sketch, plane or binder row (ops#640 rank 33): always while hidden, on
        // hover while shown, as Onshape's
        const int eye = item ? item->data(FeatureList::EyeRole).toInt() : 0;
        if (eye == 2 || (eye == 1 && (option.state & QStyle::State_MouseOver))) {
            QIcon icon(Gui::BitmapFactory().pixmap(eye == 1 ? "TreeItemVisible" : "TreeItemInvisible"));
            icon.paint(painter, FeatureList::eyeRect(option.rect));
        }
        return;
    }
    // As the tree's bar (Tree.cpp, TreeWidgetItemDelegate::paint): a line across the row with a
    // grip at its start, in the highlight colour while dragged
    QColor color = list->isDraggingBar() ? option.palette.color(QPalette::Highlight)
                                         : option.palette.color(QPalette::Mid);
    painter->save();
    painter->setRenderHint(QPainter::Antialiasing, false);
    QRect rect = option.rect;
    int thickness = std::max(2, rect.height() / 3);
    painter->fillRect(QRect(rect.left(), rect.center().y() - thickness / 2, rect.width(), thickness), color);
    int dot = thickness + 1;
    int y = rect.center().y() - dot / 2;
    for (int k = 0; k < 3; ++k) {
        painter->fillRect(QRect(rect.left() + 2 + k * (dot + 2), y - dot, dot, dot), color);
        painter->fillRect(QRect(rect.left() + 2 + k * (dot + 2), y + dot, dot, dot), color);
    }
    painter->restore();
}

// ------------------------------------------------------------------------------ FeaturesView

FeaturesView::FeaturesView(QWidget* parent)
    : QWidget(parent)
    , Gui::SelectionObserver(true, Gui::ResolveMode::OldStyleElement)
{
    auto layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    auto splitter = new QSplitter(Qt::Vertical, this);
    layout->addWidget(splitter);
    lists = splitter;
    // FreeCAD-CH (ops#640 round 10, gap A27): an Assembly tab's list in place of the two
    assemblyList = new QTreeWidget(this);
    assemblyList->setObjectName(QStringLiteral("assemblyList"));
    assemblyList->setHeaderHidden(true);
    // The name, and a fixed instance's pin
    assemblyList->setColumnCount(2);
    assemblyList->header()->setStretchLastSection(false);
    assemblyList->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    assemblyList->header()->setSectionResizeMode(1, QHeaderView::ResizeToContents);
    assemblyList->setIconSize(QSize(16, 16));
    assemblyList->setSelectionMode(QAbstractItemView::ExtendedSelection);
    assemblyList->setEditTriggers(QAbstractItemView::NoEditTriggers);
    assemblyList->setContextMenuPolicy(Qt::CustomContextMenu);
    assemblyList->hide();
    layout->addWidget(assemblyList);

    auto featuresBox = new QWidget(splitter);
    auto featuresLayout = new QVBoxLayout(featuresBox);
    featuresLayout->setContentsMargins(0, 0, 0, 0);
    featuresLayout->setSpacing(2);
    // The header: Onshape's error icon (the count on hover, a click shows only the failed rows;
    // ref-D #24), then "Features (n)"
    auto header = new QHBoxLayout();
    header->setContentsMargins(4, 2, 4, 0);
    header->setSpacing(4);
    errorsButton = new QToolButton(featuresBox);
    errorsButton->setObjectName(QStringLiteral("featuresErrors"));
    errorsButton->setIcon(QIcon(Gui::BitmapFactory().pixmapFromSvg("overlay_error", QSize(16, 16))));
    errorsButton->setAutoRaise(true);
    errorsButton->setCheckable(true);
    errorsButton->hide();
    header->addWidget(errorsButton);
    title = new QLabel(tr("Features"), featuresBox);
    title->setObjectName(QStringLiteral("featuresTitle"));
    header->addWidget(title, 1);
    // Onshape's Configurations button beside the list (ops#671 C2): the studio's panel
    configButton = new QToolButton(featuresBox);
    configButton->setObjectName(QStringLiteral("featuresConfigurations"));
    configButton->setText(tr("Configurations"));
    configButton->setToolTip(tr("The part studio's configurations: its inputs and the values they configure"));
    configButton->setAutoRaise(true);
    header->addWidget(configButton);
    connect(configButton, &QToolButton::clicked, this, [this]() {
        auto doc = document();
        if (!doc) {
            return;
        }
        const std::string code = "from PartDesign import ConfigurationsGui\nConfigurationsGui.openFor('"
            + std::string(doc->getName()) + "', '" + studioName + "')\n";
        try {
            Base::Interpreter().runString(code.c_str());
        }
        catch (const Base::Exception& e) {
            e.reportException();
        }
    });
    featuresLayout->addLayout(header);
    // The active-configuration bar (Onshape's, above the Feature list; CP2-8): one control per input
    configBar = new QWidget(featuresBox);
    configBar->setObjectName(QStringLiteral("configBar"));
    auto barLayout = new QHBoxLayout(configBar);
    barLayout->setContentsMargins(4, 0, 4, 0);
    barLayout->setSpacing(6);
    configBar->hide();
    featuresLayout->addWidget(configBar);
    // Onshape's filter box (ops#640 rank 33): rows by name or type, ":errors", ":warnings"
    filterBox = new QLineEdit(featuresBox);
    filterBox->setObjectName(QStringLiteral("featuresFilter"));
    filterBox->setPlaceholderText(tr("Filter by name or type"));
    filterBox->setClearButtonEnabled(true);
    filterBox->setToolTip(tr("Rows whose name or type contains the text; :errors or :warnings by status"));
    featuresLayout->addWidget(filterBox);
    features = new FeatureList(featuresBox);
    features->setObjectName(QStringLiteral("featureList"));
    features->setItemDelegate(new FeatureBarDelegate(features));
    features->setSelectionMode(QAbstractItemView::ExtendedSelection);
    features->setIconSize(QSize(16, 16));
    features->setContextMenuPolicy(Qt::CustomContextMenu);
    // Rename by F2 or Onshape's Shift+N (ref-D #17), never by a click: a double-click edits
    features->setEditTriggers(QAbstractItemView::NoEditTriggers);
    featuresLayout->addWidget(features);

    parts = new QTreeWidget(splitter);
    parts->setObjectName(QStringLiteral("partsList"));
    parts->setColumnCount(2);
    parts->setHeaderLabels({tr("Parts"), QString()});
    parts->setRootIsDecorated(false);
    parts->setIconSize(QSize(16, 16));
    parts->setSelectionMode(QAbstractItemView::ExtendedSelection);
    parts->header()->setStretchLastSection(false);
    parts->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    parts->header()->setSectionResizeMode(1, QHeaderView::ResizeToContents);
    parts->setEditTriggers(QAbstractItemView::NoEditTriggers);
    parts->setContextMenuPolicy(Qt::CustomContextMenu);
    splitter->setStretchFactor(0, 3);
    splitter->setStretchFactor(1, 1);

    for (QAbstractItemView* view : {static_cast<QAbstractItemView*>(features), static_cast<QAbstractItemView*>(parts)}) {
        auto rename = new QAction(tr("Rename"), view);
        rename->setObjectName(QStringLiteral("renameAction"));
        rename->setShortcuts({QKeySequence(Qt::Key_F2), QKeySequence(Qt::SHIFT | Qt::Key_N)});
        rename->setShortcutContext(Qt::WidgetShortcut);
        connect(rename, &QAction::triggered, this, [this, view]() { renameCurrent(view); });
        view->addAction(rename);
    }

    rebuildTimer = new QTimer(this);
    rebuildTimer->setSingleShot(true);
    rebuildTimer->setInterval(50);
    connect(rebuildTimer, &QTimer::timeout, this, &FeaturesView::rebuild);
    selectionTimer = new QTimer(this);
    selectionTimer->setSingleShot(true);
    selectionTimer->setInterval(0);
    connect(selectionTimer, &QTimer::timeout, this, &FeaturesView::syncSelectionFromApp);

    connect(features, &FeatureList::barDropped, this, &FeaturesView::onBarDropped);
    connect(features, &FeatureList::barDragCancelled, this, &FeaturesView::forceRebuild);
    connect(features, &FeatureList::rowsDropped, this, &FeaturesView::onRowsDropped);
    connect(features, &FeatureList::barStepped, this, &FeaturesView::stepBar);
    connect(features, &QListWidget::customContextMenuRequested, this, &FeaturesView::onFeatureMenu);
    connect(features, &QListWidget::itemDoubleClicked, this, &FeaturesView::onFeatureDoubleClicked);
    connect(features, &QListWidget::itemSelectionChanged, this, [this]() {
        if (syncing) {
            return;
        }
        // Show dependencies' marks last until the user selects again
        if (!dependencyParents.empty() || !dependencyChildren.empty()) {
            dependencyParents.clear();
            dependencyChildren.clear();
            markDependencies();
        }
        // The bar is selected alone (a click on it), never in a range of rows
        auto bar = features->barItem();
        if (bar && bar->isSelected() && features->selectedItems().size() > 1) {
            QScopedValueRollback<bool> quiet(syncing, true);
            bar->setSelected(false);
        }
        barSelected = bar && bar->isSelected();
        std::vector<App::DocumentObject*> objs;
        for (auto item : features->selectedItems()) {
            if (auto obj = objectOf(item)) {
                objs.push_back(obj);
            }
        }
        pushSelection(objs);
    });
    connect(errorsButton, &QToolButton::toggled, this, &FeaturesView::applyErrorFilter);
    connect(filterBox, &QLineEdit::textChanged, this, &FeaturesView::applyErrorFilter);
    connect(features, &FeatureList::eyeClicked, this, [this](QListWidgetItem* item) {
        toggleRowVisibility(objectOf(item));
    });
    // The hover pre-highlights the row's object in the 3D view (ops#640 rank 33)
    for (QAbstractItemView* view : {static_cast<QAbstractItemView*>(features),
                                    static_cast<QAbstractItemView*>(parts),
                                    static_cast<QAbstractItemView*>(assemblyList)}) {
        view->setMouseTracking(true);
        view->viewport()->setMouseTracking(true);
        view->viewport()->installEventFilter(this);
    }
    // FreeCAD-CH ops#654 S3: the Delete key on a studio feature's row (eventFilter())
    features->installEventFilter(this);
    connect(features->itemDelegate(), &QAbstractItemDelegate::closeEditor, this, &FeaturesView::endRename);
    connect(parts->itemDelegate(), &QAbstractItemDelegate::closeEditor, this, &FeaturesView::endRename);
    connect(features, &QListWidget::itemChanged, this, [this](QListWidgetItem* item) {
        if (!syncing) {
            rename(objectOf(item), item->text());
        }
    });
    connect(parts, &QTreeWidget::itemChanged, this, [this](QTreeWidgetItem* item, int column) {
        if (!syncing && column == 0) {
            rename(objectOf(item), item->text(0));
        }
    });
    connect(parts, &QTreeWidget::customContextMenuRequested, this, &FeaturesView::onPartMenu);
    connect(parts, &QTreeWidget::itemClicked, this, &FeaturesView::onPartClicked);
    connect(parts, &QTreeWidget::itemDoubleClicked, this, &FeaturesView::onPartDoubleClicked);
    connect(parts, &QTreeWidget::itemSelectionChanged, this, [this]() {
        if (syncing) {
            return;
        }
        std::vector<App::DocumentObject*> objs;
        for (auto item : parts->selectedItems()) {
            if (auto obj = objectOf(item)) {
                objs.push_back(obj);
            }
        }
        pushSelection(objs);
    });
    connect(assemblyList, &QTreeWidget::itemSelectionChanged, this, [this]() {
        if (syncing) {
            return;
        }
        std::vector<App::DocumentObject*> objs;
        for (auto item : assemblyList->selectedItems()) {
            if (auto obj = objectOf(item)) {
                objs.push_back(obj);
            }
        }
        pushSelection(objs);
    });
    connect(assemblyList, &QTreeWidget::itemDoubleClicked, this, &FeaturesView::onAssemblyDoubleClicked);
    connect(assemblyList, &QTreeWidget::customContextMenuRequested, this, &FeaturesView::onAssemblyMenu);

    auto& app = App::GetApplication();
    connections.emplace_back(app.signalNewObject.connect([this](const App::DocumentObject& obj) {
        // A new member goes in at the bar (Body::addObject): the bar follows it, not the row it
        // was last dragged after, or a sketch made there would be listed below it (ops#640 rank
        // 34, blind test F42)
        if (obj.getDocument() && documentName == obj.getDocument()->getName()) {
            barHinted = false;
            barHint.clear();
        }
        onObject(obj);
    }));
    connections.emplace_back(app.signalDeletedObject.connect([this](const App::DocumentObject& obj) {
        onObject(obj);
    }));
    connections.emplace_back(app.signalChangedObject.connect(
        [this](const App::DocumentObject& obj, const App::Property& prop) { onChangedObject(obj, prop); }
    ));
    auto ofThisDocument = [this](const App::Document& doc) {
        if (documentName == doc.getName()) {
            scheduleRebuild();
        }
    };
    connections.emplace_back(app.signalRecomputed.connect(ofThisDocument));
    connections.emplace_back(app.signalUndoDocument.connect(ofThisDocument));
    connections.emplace_back(app.signalRedoDocument.connect(ofThisDocument));
    connections.emplace_back(Gui::Application::Instance->signalActiveDocument.connect(
        [this](const Gui::Document& gdoc) { onActiveDocument(gdoc); }
    ));
    connections.emplace_back(Gui::Application::Instance->signalDeleteDocument.connect(
        [this](const Gui::Document& gdoc) { onDeleteDocument(gdoc); }
    ));
    // FreeCAD-CH (ops#640, rank 59): the lists follow the typed tab, its own view
    connections.emplace_back(Gui::Application::Instance->signalActivateView.connect(
        [this](const Gui::MDIView* view) {
            App::Document* doc = view ? view->getAppDocument() : nullptr;
            if (doc && documentName == doc->getName()) {
                scheduleRebuild();
            }
        }
    ));
    // Kept through a sketch's edit (leavePartDesign()), the lists leave with the next workbench
    // that isn't the sketch's, as PartDesign's own deactivation would
    connections.emplace_back(Gui::Application::Instance->signalActivateWorkbench.connect([](const char*) {
        if (!listsBelong()) {
            showLists(false);
        }
        else if (registered && !inPartDesign() && !prefersModelTree()) {
            // Back in the Sketcher while a Body's sketch is still edited (another workbench went
            // in between): the lists come back, as they stayed when the edit opened it
            showLists(true);
        }
    }));
    if (auto gdoc = Gui::Application::Instance->activeDocument()) {
        onActiveDocument(*gdoc);
    }
}

FeaturesView::~FeaturesView() = default;

FeaturesView* FeaturesView::instance()
{
    return registered.data();
}

bool FeaturesView::prefersModelTree()
{
    return App::GetApplication().GetParameterGroupByPath(paramPath)->GetBool("ShowModelTree", false);
}

void FeaturesView::placeLists()
{
    QSplitter* splitter = modelSplitter();
    if (registered || !splitter) {
        return;
    }
    QWidget* tree = treePanelOf(splitter);
    int index = tree ? splitter->indexOf(tree) : 0;
    QList<int> sizes = splitter->sizes();
    auto view = new FeaturesView();
    view->setObjectName(QStringLiteral("FeaturesView"));
    splitter->insertWidget(index, view);
    registered = view;
    // The lists take the tree's room
    if (index < sizes.size()) {
        sizes.insert(index, sizes[index]);
        splitter->setSizes(sizes);
    }
}

void FeaturesView::enterPartDesign()
{
    // Deferred: at start-up the window's saved layout is restored after the workbench activates
    QTimer::singleShot(0, []() {
        if (!inPartDesign() || !modelSplitter()) {
            return;
        }
        placeLists();
        showLists(!prefersModelTree());
    });
}

void FeaturesView::followTabs()
{
    // Not scoped: the module stays loaded as long as the application
    Gui::Application::Instance->signalActivateWorkbench.connect([](const char*) { followTab(); });
    Gui::Application::Instance->signalActivateView.connect([](const Gui::MDIView*) { followTab(); });
}

void FeaturesView::followTab()
{
    // Deferred: a tab's switch activates its view, then its workbench, then puts its assembly in
    // edit (Gui::DocumentTabs)
    QTimer::singleShot(0, []() {
        // The rows follow the workbench too: an Assembly tab lists its assembly in the Assembly
        // workbench only
        if (registered) {
            registered->scheduleRebuild();
        }
        if (inPartDesign()) {
            // PartDesign's activation shows its lists
            return;
        }
        if (!assemblyTabActive()) {
            if (registered && !listsBelong()) {
                showLists(false);
            }
            return;
        }
        if (prefersModelTree()) {
            showLists(false);
            return;
        }
        placeLists();
        showLists(true);
    });
}

void FeaturesView::leavePartDesign()
{
    // The workbench activated now (it activates before the old one is deactivated): a Body's
    // sketch opened in the Sketcher keeps the lists
    if (!listsBelong()) {
        showLists(false);
    }
}

void FeaturesView::toggleModelTree()
{
    bool tree = !prefersModelTree();
    App::GetApplication().GetParameterGroupByPath(paramPath)->SetBool("ShowModelTree", tree);
    // An Assembly tab's list goes and comes back with the studios' (ops#640 round 10)
    if (inPartDesign() || assemblyTabActive()) {
        if (!registered && !tree) {
            placeLists();
        }
        showLists(!tree);
    }
}

App::Document* FeaturesView::document() const
{
    return documentName.empty() ? nullptr : App::GetApplication().getDocument(documentName.c_str());
}

App::Part* FeaturesView::studio() const
{
    auto doc = document();
    if (!doc || studioName.empty()) {
        return nullptr;
    }
    return freecad_cast<App::Part*>(doc->getObject(studioName.c_str()));
}

void FeaturesView::onActiveDocument(const Gui::Document& gdoc)
{
    std::string name = gdoc.getDocument() ? gdoc.getDocument()->getName() : "";
    if (name != documentName) {
        documentName = name;
        barHinted = false;
        barHint.clear();
        watchDocument(&gdoc);
    }
    scheduleRebuild();
}

void FeaturesView::onDeleteDocument(const Gui::Document& gdoc)
{
    if (gdoc.getDocument() && documentName == gdoc.getDocument()->getName()) {
        // Now, not on the timer: no row may name an object of the closing document
        documentConnections.clear();
        documentName.clear();
        studioName.clear();
        assemblyName.clear();
        syncing = true;
        features->clear();
        parts->clear();
        assemblyList->clear();
        featureRows.clear();
        partRows.clear();
        featureNames.clear();
        partNames.clear();
        assemblyRows.clear();
        syncing = false;
    }
}

void FeaturesView::watchDocument(const Gui::Document* gdoc)
{
    documentConnections.clear();
    if (!gdoc) {
        return;
    }
    // The active Body (it picks the studio)
    documentConnections.emplace_back(gdoc->signalActivatedViewProvider.connect(
        [this](const Gui::ViewProviderDocumentObject*, const char* name) {
            if (name && strcmp(name, PDBODYKEY) == 0) {
                scheduleRebuild();
            }
        }
    ));
    // The edit roll-back point changes no property: the Body's view provider tells it as a Tip
    // change (ViewProviderBody::setEditRoll())
    documentConnections.emplace_back(gdoc->signalChangedObject.connect(
        [this](const Gui::ViewProviderDocumentObject&, const App::Property& prop) {
            const char* name = prop.getName();
            if (name && (strcmp(name, "Tip") == 0 || strcmp(name, "Visibility") == 0)) {
                scheduleRebuild();
            }
        }
    ));
    documentConnections.emplace_back(
        gdoc->signalInEdit.connect([this](const Gui::ViewProviderDocumentObject&) { scheduleRebuild(); })
    );
    documentConnections.emplace_back(
        gdoc->signalResetEdit.connect([this](const Gui::ViewProviderDocumentObject&) { scheduleRebuild(); })
    );
}

void FeaturesView::onObject(const App::DocumentObject& obj)
{
    if (obj.getDocument() && documentName == obj.getDocument()->getName()) {
        scheduleRebuild();
    }
}

void FeaturesView::onChangedObject(const App::DocumentObject& obj, const App::Property& prop)
{
    if (!obj.getDocument() || documentName != obj.getDocument()->getName()) {
        return;
    }
    // The order follows the links and the saved ranks; the rows show Label, the held look the
    // Tip, the status Suppressed, the Parts list's eye Visibility
    const char* name = prop.getName();
    bool shown = name
        && (strcmp(name, "Group") == 0 || strcmp(name, "Tip") == 0 || strcmp(name, "Label") == 0
            || strcmp(name, "Suppressed") == 0 || strcmp(name, "Visibility") == 0
            || strcmp(name, "HistoryRank") == 0 || strcmp(name, "Bar") == 0
            // The active-configuration bar (ops#671 C2)
            || (obj.isDerivedFrom<PartDesign::StudioConfig>()
                && (strcmp(name, "Inputs") == 0 || strcmp(name, "Active") == 0)));
    if (shown || prop.isDerivedFrom<App::PropertyLinkBase>()) {
        scheduleRebuild();
    }
}

void FeaturesView::scheduleRebuild()
{
    if (!isVisible()) {
        dirty = true;
        return;
    }
    rebuildTimer->start();
}

void FeaturesView::showEvent(QShowEvent* event)
{
    QWidget::showEvent(event);
    if (dirty) {
        rebuild();
    }
}

void FeaturesView::findStudio()
{
    studioName.clear();
    assemblyName.clear();
    auto doc = document();
    if (!doc) {
        return;
    }
    PartDesign::Body* body = nullptr;
    auto gdoc = Gui::Application::Instance->getDocument(doc);
    if (auto view = gdoc ? gdoc->getActiveView() : nullptr) {
        // FreeCAD-CH (ops#640, rank 59): a typed tab's view lists its own Part Studio
        const std::string tab = Gui::DocumentTabs::tabOfView(view);
        App::DocumentTabs::Kind kind {};
        App::DocumentObject* tabObject = tab.empty() ? nullptr : doc->getObject(tab.c_str());
        if (tab == App::DocumentTabs::implicitName()) {
            return;
        }
        if (tabObject && App::DocumentTabs::isTabObject(tabObject, &kind)
            && kind == App::DocumentTabs::Kind::PartStudio) {
            studioName = tab;
            return;
        }
        // FreeCAD-CH (ops#640 round 10): an Assembly tab lists its assembly
        if (inAssemblyUnderOnshape() && assemblyOfView(view)) {
            assemblyName = tab;
            return;
        }
        body = view->getActiveObject<PartDesign::Body*>(PDBODYKEY);
    }
    App::Part* part = nullptr;
    if (body && Part::BodyBase::studioOf(body, part)) {
        if (part) {
            studioName = part->getNameInDocument();
        }
        return;
    }
    // No active Body: the top level, or the App::Part of the first Body when the top level has none
    if (!PartDesign::studioBodies(doc, nullptr).empty()) {
        return;
    }
    for (auto obj : doc->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        if (Part::BodyBase::studioOf(static_cast<PartDesign::Body*>(obj), part) && part) {
            studioName = part->getNameInDocument();
            return;
        }
    }
}

void FeaturesView::rebuild()
{
    if (!isVisible()) {
        dirty = true;
        return;
    }
    // Not under the user's hand: a drag ends with its own rebuild, a rename with its commit
    if (features->isDraggingBar() || features->isDraggingRows() || renaming) {
        rebuildTimer->start();
        return;
    }
    dirty = false;
    findStudio();
    syncing = true;
    // An Assembly tab: its list in place of the studio's two (ops#640 round 10)
    const bool assembly = !assemblyName.empty();
    lists->setVisible(!assembly);
    assemblyList->setVisible(assembly);
    rebuildAssembly();
    if (!assembly) {
        rebuildFeatures();
        rebuildParts();
    }
    rebuildConfigBar();
    // A selected bar stays selected through a rebuild (its row is new after a move)
    if (auto bar = !assembly && barSelected ? features->barItem() : nullptr) {
        features->setCurrentItem(bar);
        bar->setSelected(true);
    }
    syncing = false;
    syncSelectionFromApp();
}

void FeaturesView::forceRebuild()
{
    featureRows.clear();
    partRows.clear();
    assemblyRows.clear();
    featureNames.clear();
    partNames.clear();
    rebuild();
}

void FeaturesView::rebuildFeatures()
{
    auto doc = document();
    if (!doc) {
        features->clear();
        featureRows.clear();
        featureNames.clear();
        editedName.clear();
        return;
    }
    // FreeCAD-CH ops#654 S3: a studio with a list shows its entries (steps folded into their
    // owner's row) and the list's bar; one without, the derived order and its Bodies' bars
    const PartDesign::StudioList* list = PartDesign::StudioList::of(doc, studio());
    std::size_t barRow = 0;
    const auto sequence = list ? listRows(list, doc, studio(), barRow)
                               : PartDesign::studioSequence(doc, studio());
    // Onshape's default geometry at the top (ops#640 rank 33)
    const auto defaults = defaultGeometry(doc, studio());
    // The feature being made or edited is highlighted (ops#640 rank 40)
    App::DocumentObject* inEdit = objectInEdit(doc);
    editedName = inEdit ? inEdit->getNameInDocument() : "";
    // A Merge its feature's merge scope made has no row: its status shows on the feature's
    // (ops#640 rank 1)
    std::vector<bool> folded;
    for (auto obj : sequence) {
        folded.push_back(isFoldedMerge(obj) || isFoldedDerived(obj));
    }
    const auto shown = static_cast<int>(std::ranges::count(folded, false));
    if (!list) {
        App::DocumentObject* hint = barHint.empty() ? nullptr : doc->getObject(barHint.c_str());
        bool hinted = barHinted && (barHint.empty() || hint);
        App::DocumentObject* after = PartDesign::studioBarAfter(sequence, hinted, hint);
        if (after) {
            barRow = static_cast<std::size_t>(std::ranges::find(sequence, after) - sequence.begin()) + 1;
        }
    }
    // The header: the count, and the error icon while some row above the bar fails (the rows
    // below it are grey, not evaluated: review R6-5)
    int errors = 0;
    for (std::size_t i = 0; i < sequence.size() && i < barRow; ++i) {
        errors += !folded[i] && statusObject(sequence[i])->isError() ? 1 : 0;
    }
    title->setText(tr("Features (%1)").arg(shown));
    errorsButton->setVisible(errors > 0);
    errorsButton->setToolTip(tr("%n feature(s) in error: click to show only them", "", errors));
    if (errors == 0 && errorsButton->isChecked()) {
        QSignalBlocker block(errorsButton);
        errorsButton->setChecked(false);
    }
    // The rows in list order: a member's index in sequence, or -1 for the bar (none in an empty
    // studio)
    std::vector<int> order;
    std::vector<std::string> rows;
    std::vector<std::string> names;
    for (std::size_t i = 0; i < sequence.size(); ++i) {
        if (i == barRow) {
            order.push_back(-1);
        }
        if (!folded[i]) {
            order.push_back(static_cast<int>(i));
        }
    }
    if (barRow >= sequence.size() && !sequence.empty()) {
        order.push_back(-1);
    }
    // Every row below the bar is rolled back, greyed with the features it holds: the sketches and
    // datums waiting there too (ops#640 rank 34, blind test F43). Not a solid its Body doesn't
    // hold: one Body rolled back from the tree leaves another's later solids computed and shown
    std::vector<bool> below(sequence.size(), false);
    bool pastBar = false;
    for (int index : order) {
        if (index < 0) {
            pastBar = true;
        }
        else if (pastBar) {
            const App::DocumentObject* obj = sequence[index];
            auto body = PartDesign::Body::findBodyOf(obj);
            // With a list, every row below its bar is held (ops#654 S3)
            below[index] = list || !(body && PartDesign::Body::isSolidFeature(obj) && !body->holds(obj));
        }
    }
    for (const auto& [obj, label] : defaults) {
        rows.push_back(rowKey(obj, false, "\x1d" + std::to_string(eyeState(obj))));
        names.emplace_back(obj->getNameInDocument());
    }
    for (int index : order) {
        if (index < 0) {
            rows.emplace_back("|");
            names.emplace_back("|");
            continue;
        }
        auto obj = sequence[index];
        auto body = PartDesign::Body::findBodyOf(obj);
        std::string extra = body ? body->Label.getValue() : "";
        if (auto merge = foldedMerge(obj)) {
            extra += '\x1e' + rowKey(merge, body && body->holds(merge));
        }
        for (auto member : foldedDerived(obj)) {
            extra += '\x1e' + rowKey(member, false);
        }
        // A studio feature's steps: their status shows on its row (ops#654 S3)
        if (PartDesign::isStudioOwner(obj)) {
            for (auto step : PartDesign::StudioList::stepsOf(obj)) {
                extra += '\x1e' + rowKey(step, false);
            }
        }
        extra += '\x1d' + std::to_string(eyeState(obj));
        if (obj == inEdit) {
            extra += "\x1d" "edit";
        }
        rows.push_back(rowKey(obj, below[index], extra));
        names.emplace_back(obj->getNameInDocument());
    }
    // Unchanged: the rows (and the user's selection anchor in them) stay
    if (rows == featureRows && features->count() == static_cast<int>(rows.size())) {
        applyErrorFilter();
        return;
    }
    // The same rows in the same order (a status or a label changed): updated in place, so a
    // selection and its Shift anchor survive (review props602-r1fix R2)
    bool inPlace = names == featureNames && features->count() == static_cast<int>(names.size());
    featureRows = rows;
    featureNames = names;
    auto decorate = [this, inEdit](QListWidgetItem* item, App::DocumentObject* obj, bool isBelow) {
        auto body = PartDesign::Body::findBodyOf(obj);
        // A folded Merge's status shows here, its icon the feature's (ops#640 rank 1)
        const App::DocumentObject* status = statusObject(obj);
        item->setFlags(item->flags() | Qt::ItemIsEditable);
        item->setText(QString::fromUtf8(obj->Label.getValue()));
        item->setData(Qt::UserRole, QByteArray(obj->getNameInDocument()));
        item->setData(FeatureList::DefaultRole, QVariant());
        item->setData(FeatureList::EyeRole, eyeState(obj));
        // Below the bar the icon is dimmed, not marked (ops#640 rank 34): Onshape greys the row,
        // an error's mark too, as nothing below the bar is evaluated (round 6, J2) [guess]
        auto rowVp = isBelow ? viewProviderOf(obj) : nullptr;
        QIcon icon = rowVp ? rowVp->getIcon() : statusIcon(obj, false);
        if (status != obj && !isBelow) {
            const char* overlay = status->isError() ? "overlay_error"
                : status->isWarning()               ? "overlay_warning"
                                                    : "overlay_recompute";
            auto vp = viewProviderOf(obj);
            QPixmap px = Gui::BitmapFactory().pixmapFromSvg(overlay, QSize(10, 10));
            icon = QIcon(Gui::BitmapFactory().merge(
                (vp ? vp->getIcon() : QIcon()).pixmap(16, 16),
                px,
                Gui::BitmapFactoryInst::TopRight
            ));
        }
        if (isBelow) {
            icon = QIcon(icon.pixmap(QSize(16, 16), QIcon::Disabled));
        }
        item->setIcon(icon);
        // Greyed and italic below the bar (hands-on F5: "later rows go grey and italic"); the
        // feature in edit bold (ops#640 rank 40)
        QFont font = statusFont(features->font(), obj, isBelow);
        font.setBold(obj == inEdit);
        item->setFont(font);
        // Grey below the bar, not an error's red or a warning's orange (round 6, J2); grey when
        // suppressed too, as Onshape greys a suppressed row (round 8, J13) [guess: struck as well]
        QVariant foreground = isBelow || isSuppressed(obj)
            ? QVariant(QBrush(features->palette().color(QPalette::Disabled, QPalette::Text)))
            : statusForeground(status);
        item->setData(Qt::ForegroundRole, foreground);
        QString tip = rowToolTip(obj, body);
        if (status != obj) {
            tip += QStringLiteral("\n") + plainStatus(status);
        }
        if (obj == inEdit) {
            tip += QStringLiteral("\n") + tr("In edit");
        }
        item->setToolTip(tip);
    };
    // A default geometry row: Onshape's name, the object's icon and eye; not renamed or dragged
    auto decorateDefault = [](QListWidgetItem* item, App::DocumentObject* obj, const QString& label) {
        item->setFlags(item->flags() & ~Qt::ItemIsEditable);
        item->setText(label);
        item->setData(Qt::UserRole, QByteArray(obj->getNameInDocument()));
        item->setData(FeatureList::DefaultRole, true);
        item->setData(FeatureList::EyeRole, eyeState(obj));
        auto vp = viewProviderOf(obj);
        item->setIcon(vp ? vp->getIcon() : QIcon());
        item->setToolTip(QStringLiteral("%1 (%2)").arg(label, QString::fromUtf8(obj->Label.getValue())));
    };
    const int offset = static_cast<int>(defaults.size());
    if (inPlace) {
        for (int r = 0; r < offset; ++r) {
            decorateDefault(features->item(r), defaults[r].first, defaults[r].second);
        }
        for (std::size_t r = 0; r < order.size(); ++r) {
            if (order[r] >= 0) {
                decorate(features->item(offset + static_cast<int>(r)), sequence[order[r]], below[order[r]]);
            }
        }
        markDependencies();
        applyErrorFilter();
        return;
    }
    int scroll = features->verticalScrollBar() ? features->verticalScrollBar()->value() : 0;
    features->clear();
    for (const auto& [obj, label] : defaults) {
        decorateDefault(new QListWidgetItem(features), obj, label);
    }
    for (int index : order) {
        if (index < 0) {
            auto bar = new QListWidgetItem(features, FeatureList::BarType);
            bar->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
            bar->setSizeHint(QSize(0, 9));
            bar->setToolTip(tr("Roll-back bar: drag it to roll every body of the part studio back"));
            continue;
        }
        decorate(new QListWidgetItem(features), sequence[index], below[index]);
    }
    markDependencies();
    applyErrorFilter();
    if (auto bar = features->verticalScrollBar()) {
        bar->setValue(scroll);
    }
}

void FeaturesView::applyErrorFilter()
{
    bool only = errorsButton->isChecked();
    const QString filter = filterBox ? filterBox->text() : QString();
    const bool filtering = only || !filter.trimmed().isEmpty();
    // The error icon shows the failed rows above the bar, the ones it counts (review R6-5)
    bool belowBar = false;
    for (int i = 0; i < features->count(); ++i) {
        auto item = features->item(i);
        auto obj = objectOf(item);
        if (!obj) {
            // The bar: only in the whole list
            item->setHidden(filtering);
            belowBar = true;
            continue;
        }
        const App::DocumentObject* status = item->data(FeatureList::DefaultRole).toBool() ? obj : statusObject(obj);
        item->setHidden((only && (belowBar || !status->isError())) || !matchesFilter(obj, status, filter));
    }
}

void FeaturesView::rebuildParts()
{
    auto doc = document();
    if (!doc) {
        parts->clear();
        partRows.clear();
        partNames.clear();
        return;
    }
    // One row per piece of a part (partPieces): the second piece of a Body cut in two is a row of
    // that Body too, "<label> (2)" (ops#640 rank 3b)
    std::vector<App::DocumentObject*> objs;
    std::vector<int> pieces;
    for (auto obj : studioParts(doc, studio())) {
        for (int piece = 0, count = partPieces(obj); piece < count; ++piece) {
            objs.push_back(obj);
            pieces.push_back(piece);
        }
    }
    parts->headerItem()->setText(0, tr("Parts (%1)").arg(objs.size()));
    std::vector<std::string> rows;
    std::vector<std::string> names;
    for (std::size_t i = 0; i < objs.size(); ++i) {
        auto obj = objs[i];
        auto body = freecad_cast<PartDesign::Body*>(obj);
        auto vp = viewProviderOf(obj);
        std::string eye = !vp || !vp->canToggleVisibility() ? "" : vp->isShow() ? "v" : "i";
        const std::string piece = pieces[i] ? "#" + std::to_string(pieces[i] + 1) : std::string();
        rows.push_back(rowKey(obj, body && body->isRolledBack(), eye + piece));
        names.emplace_back(obj->getNameInDocument() + piece);
    }
    if (rows == partRows && parts->topLevelItemCount() == static_cast<int>(rows.size())) {
        return;
    }
    bool inPlace = names == partNames && parts->topLevelItemCount() == static_cast<int>(names.size());
    partRows = rows;
    partNames = names;
    QIcon visible(Gui::BitmapFactory().pixmap("TreeItemVisible"));
    QIcon invisible(Gui::BitmapFactory().pixmap("TreeItemInvisible"));
    if (!inPlace) {
        parts->clear();
    }
    // Under the Onshape keymap a later piece is "Part N", the lowest N no row's name takes, as
    // Onshape names the part a split makes (round 8, J3); else "<label> (2)"
    const bool partNumbers = Gui::ForkKeymap::isOnshape();
    std::set<QString> taken;
    for (std::size_t i = 0; i < objs.size(); ++i) {
        if (!pieces[i]) {
            auto part = freecad_cast<PartDesign::Body*>(objs[i]);
            taken.insert(part ? studioPartName(part) : QString::fromUtf8(objs[i]->Label.getValue()));
        }
    }
    auto nextPartName = [&taken]() {
        for (int n = 1;; ++n) {
            QString name = tr("Part %1").arg(n);
            if (taken.insert(name).second) {
                return name;
            }
        }
    };
    for (std::size_t i = 0; i < objs.size(); ++i) {
        auto obj = objs[i];
        auto body = freecad_cast<PartDesign::Body*>(obj);
        bool held = body && body->isRolledBack();
        auto item = inPlace ? parts->topLevelItem(static_cast<int>(i)) : new QTreeWidgetItem(parts);
        // A later piece names its Body: its rename is the first row's. A default name is
        // positional in a listed studio, as Onshape renumbers it (ops#654 P6a)
        const QString label = body ? studioPartName(body) : QString::fromUtf8(obj->Label.getValue());
        if (pieces[i]) {
            item->setFlags(item->flags() & ~Qt::ItemIsEditable);
            item->setText(0, partNumbers ? nextPartName()
                                         : tr("%1 (%2)").arg(label).arg(pieces[i] + 1));
        }
        else {
            item->setFlags(item->flags() | Qt::ItemIsEditable);
            item->setText(0, label);
        }
        item->setData(0, Qt::UserRole, QByteArray(obj->getNameInDocument()));
        item->setIcon(0, statusIcon(obj, held));
        // Not italic while rolled back: a part in the list exists at the bar (round 6, J22)
        item->setFont(0, statusFont(parts->font(), obj, false));
        item->setData(0, Qt::ForegroundRole, statusForeground(obj));
        item->setToolTip(0, rowToolTip(obj, nullptr));
        auto vp = viewProviderOf(obj);
        if (vp && vp->canToggleVisibility()) {
            item->setIcon(1, vp->isShow() ? visible : invisible);
            item->setToolTip(1, tr("Show or hide"));
        }
    }
}

App::DocumentObject* FeaturesView::objectOf(const QListWidgetItem* item) const
{
    auto doc = document();
    if (!doc || !item || item->type() == FeatureList::BarType) {
        return nullptr;
    }
    return doc->getObject(item->data(Qt::UserRole).toByteArray().constData());
}

App::DocumentObject* FeaturesView::memberOf(const QListWidgetItem* item) const
{
    return item && item->data(FeatureList::DefaultRole).toBool() ? nullptr : objectOf(item);
}

bool FeaturesView::eventFilter(QObject* watched, QEvent* event)
{
    // FreeCAD-CH ops#654 S3: Delete on selected rows with a studio feature is the list's delete
    // (deleteOwnerRows()), taken from Std_Delete's shortcut, which would ask about its steps;
    // Backspace too on the Mac (ForkKeymap::isDeleteKey())
    if (watched == features
        && (event->type() == QEvent::ShortcutOverride || event->type() == QEvent::KeyPress)) {
        auto key = static_cast<QKeyEvent*>(event);
        if (Gui::ForkKeymap::isDeleteKey(key)) {
            std::vector<App::DocumentObject*> rows;
            for (auto item : features->selectedItems()) {
                if (auto obj = memberOf(item)) {
                    rows.push_back(obj);
                }
            }
            if (anyOwner(rows)) {
                event->accept();
                if (event->type() == QEvent::KeyPress) {
                    try {
                        deleteOwnerRows(document(), rows);
                    }
                    catch (const Base::Exception& e) {
                        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 5000);
                    }
                }
                return true;
            }
        }
    }
    const bool overFeatures = watched == features->viewport();
    if (watched == assemblyList->viewport()) {
        if (event->type() == QEvent::MouseMove) {
            auto pos = static_cast<QMouseEvent*>(event)->position().toPoint();
            preselectRow(objectOf(assemblyList->itemAt(pos)));
        }
        else if (event->type() == QEvent::Leave) {
            preselectRow(nullptr);
        }
    }
    else if (overFeatures || watched == parts->viewport()) {
        if (event->type() == QEvent::MouseMove) {
            auto pos = static_cast<QMouseEvent*>(event)->position().toPoint();
            // Not while a drag is under way: the rows move under the cursor
            App::DocumentObject* obj = nullptr;
            if (overFeatures && !features->isDraggingBar() && !features->isDraggingRows()) {
                obj = objectOf(features->itemAt(pos));
            }
            else if (!overFeatures) {
                obj = objectOf(parts->itemAt(pos));
            }
            preselectRow(obj);
        }
        else if (event->type() == QEvent::Leave) {
            preselectRow(nullptr);
        }
    }
    return QWidget::eventFilter(watched, event);
}

void FeaturesView::preselectRow(App::DocumentObject* obj)
{
    const std::string name = obj ? obj->getNameInDocument() : "";
    if (name == preselected) {
        return;
    }
    preselected = name;
    auto doc = document();
    Gui::Selection().rmvPreselect();
    if (!obj || !doc || obj->getDocument() != doc) {
        return;
    }
    // As the tree's hover (TreeWidget::onItemEntered): from the top-level object down
    auto parents = obj->getParents();
    if (!parents.empty() && parents.front().first) {
        Gui::Selection().setPreselect(
            doc->getName(),
            parents.front().first->getNameInDocument(),
            parents.front().second.c_str(),
            0,
            0,
            0,
            Gui::SelectionChanges::MsgSource::TreeView
        );
    }
    else {
        Gui::Selection()
            .setPreselect(doc->getName(), obj->getNameInDocument(), "", 0, 0, 0, Gui::SelectionChanges::MsgSource::TreeView);
    }
}

void FeaturesView::toggleRowVisibility(App::DocumentObject* obj)
{
    auto vp = obj ? viewProviderOf(obj) : nullptr;
    if (!vp) {
        return;
    }
    // A default plane shows with its Origin: shown alone, the Origin's other elements hidden
    // first; hidden, the Origin goes too when nothing of it is left shown
    auto element = freecad_cast<App::DatumElement*>(obj);
    auto lcs = element ? element->getLCS() : nullptr;
    auto lcsVp = lcs ? viewProviderOf(lcs) : nullptr;
    if (!lcsVp) {
        vp->Gui::ViewProvider::toggleVisibility();
    }
    else if (rowShown(obj)) {
        vp->hide();
        bool any = std::ranges::any_of(lcs->baseObjects(), [](App::DatumElement* other) {
            auto otherVp = other ? viewProviderOf(other) : nullptr;
            return otherVp && otherVp->isShow();
        });
        if (!any) {
            lcsVp->hide();
        }
    }
    else {
        if (!lcsVp->isShow()) {
            for (App::DatumElement* other : lcs->baseObjects()) {
                auto otherVp = other && other != obj ? viewProviderOf(other) : nullptr;
                if (otherVp && otherVp->isShow()) {
                    otherVp->hide();
                }
            }
            lcsVp->show();
        }
        vp->show();
    }
    scheduleRebuild();
}

App::DocumentObject* FeaturesView::objectOf(const QTreeWidgetItem* item) const
{
    auto doc = document();
    if (!doc || !item) {
        return nullptr;
    }
    return doc->getObject(item->data(0, Qt::UserRole).toByteArray().constData());
}

void FeaturesView::pushSelection(const std::vector<App::DocumentObject*>& objs)
{
    auto doc = document();
    if (!doc) {
        return;
    }
    syncing = true;
    Gui::Selection().clearSelection(doc->getName());
    for (auto obj : objs) {
        // As the tree selects: from the top-level object down (Body1.Pad.)
        auto parents = obj->getParents();
        if (!parents.empty() && parents.front().first) {
            Gui::Selection().addSelection(
                doc->getName(),
                parents.front().first->getNameInDocument(),
                parents.front().second.c_str()
            );
        }
        else {
            Gui::Selection().addSelection(doc->getName(), obj->getNameInDocument());
        }
    }
    syncing = false;
    // The other list follows (review props602s-r1, finding 1: a Parts row stayed selected)
    selectionTimer->start();
}

void FeaturesView::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    if (msg.Type != Gui::SelectionChanges::AddSelection && msg.Type != Gui::SelectionChanges::RmvSelection
        && msg.Type != Gui::SelectionChanges::SetSelection
        && msg.Type != Gui::SelectionChanges::ClrSelection) {
        return;
    }
    // A double click's tint lasts until the selection changes (P8)
    clearCreator();
    if (syncing) {
        return;
    }
    selectionTimer->start();
}

void FeaturesView::syncSelectionFromApp()
{
    auto doc = document();
    if (!doc || !isVisible()) {
        return;
    }
    std::set<std::string> selected;
    // A face, edge or vertex picked highlights its part's row too (selection parity, Onshape SQ6);
    // a whole feature picked doesn't (review props602s-r1, finding 1)
    std::set<std::string> partsOfPicks;
    for (const auto& sel : Gui::Selection().getSelection(doc->getName())) {
        if (sel.pObject && sel.pObject->isAttachedToDocument()) {
            selected.insert(sel.pObject->getNameInDocument());
            if (sel.SubName && sel.SubName[0]) {
                if (auto body = PartDesign::Body::findBodyOf(sel.pObject)) {
                    partsOfPicks.insert(body->getNameInDocument());
                }
            }
        }
    }
    // Only the rows that differ: setSelected() on a row commits the range a Shift+click is still
    // building, so the next Shift+click couldn't shrink it (review props602-r1fix R2)
    syncing = true;
    // Something selected elsewhere: the bar isn't any more
    if (auto bar = features->barItem(); bar && bar->isSelected() && !selected.empty()) {
        bar->setSelected(false);
        barSelected = false;
    }
    for (int i = 0; i < features->count(); ++i) {
        auto item = features->item(i);
        bool want = selected.count(item->data(Qt::UserRole).toByteArray().toStdString()) > 0;
        if (item->type() != FeatureList::BarType && item->isSelected() != want) {
            item->setSelected(want);
        }
    }
    for (int i = 0; i < parts->topLevelItemCount(); ++i) {
        auto item = parts->topLevelItem(i);
        const std::string name = item->data(0, Qt::UserRole).toByteArray().toStdString();
        bool want = selected.count(name) > 0 || partsOfPicks.count(name) > 0;
        if (item->isSelected() != want) {
            item->setSelected(want);
        }
    }
    // The Assembly tab's rows (a header stands for no object)
    for (QTreeWidgetItemIterator it(assemblyList); *it; ++it) {
        auto item = *it;
        const std::string name = item->data(0, Qt::UserRole).toByteArray().toStdString();
        bool want = !name.empty() && selected.count(name) > 0;
        if (item->isSelected() != want) {
            item->setSelected(want);
        }
    }
    syncing = false;
}

void FeaturesView::rollStudio(App::Document* doc, App::Part* studio, App::DocumentObject* member, bool toEnd)
{
    if (!doc) {
        return;
    }
    // Its transaction would commit an open edit's: Cancel couldn't take the edit back
    if (ViewProviderBody::isEditLocked(doc)) {
        throw Base::RuntimeError(editLockedMessage);
    }
    // The bar after a row is after its folded Merge (ops#640 rank 1)
    member = pastMerge(member);
    const auto bodies = PartDesign::studioBodies(doc, studio);
    std::vector<App::DocumentObject*> oldTips;
    for (auto body : bodies) {
        oldTips.push_back(body->Tip.getValue());
    }
    std::string studioCmd = studio ? Gui::Command::getObjectCmd(studio)
                                   : std::string("App.getDocument('") + doc->getName() + "')";
    int tid = doc->openTransaction(
        toEnd ? QT_TRANSLATE_NOOP("Command", "Roll to end") : QT_TRANSLATE_NOOP("Command", "Roll to here")
    );
    // FreeCAD-CH (ops#640): refused beside an open dialog's held step; commitTransaction(0)
    // would commit that step behind the dialog
    if (tid == 0 && doc->isStepLocked()) {
        throw Base::RuntimeError("Finish the open dialog first");
    }
    try {
        Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
        // FreeCAD-CH ops#654 S3: the bar is the studio's list's, made from the derived order the
        // first time (in this step: undone with it)
        Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.studioList(%s, True)", studioCmd.c_str());
        const PartDesign::StudioList* list = PartDesign::StudioList::of(doc, studio);
        const App::DocumentObject* oldBar = entryAtBar(list);
        if (toEnd) {
            Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.rollStudioToEnd(%s)", studioCmd.c_str());
        }
        else {
            std::string memberCmd = member ? Gui::Command::getObjectCmd(member) : std::string("None");
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "PartDesign.rollStudioTo(%s, %s)",
                studioCmd.c_str(),
                memberCmd.c_str()
            );
        }
        // The list's bar may move past a sketch, no Tip with it
        bool tipsMoved = showMovedTips(bodies, oldTips);
        if (!tipsMoved && entryAtBar(list) == oldBar) {
            App::GetApplication().abortTransaction(tid);
            return;
        }
        Gui::Command::updateActive();
        App::GetApplication().commitTransaction(tid);
    }
    catch (const Base::Exception&) {
        App::GetApplication().abortTransaction(tid);
        throw;
    }
}

void FeaturesView::onBarDropped(int row)
{
    auto doc = document();
    App::DocumentObject* member = row >= 0 ? memberOf(features->item(row)) : nullptr;
    // After the last row: the end
    bool toEnd = row >= 0 && row == features->count() - 2;
    barHinted = true;
    barHint = member ? member->getNameInDocument() : "";
    try {
        rollStudio(doc, studio(), member, toEnd);
    }
    catch (const Base::Exception& e) {
        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 5000);
    }
    // The dragged bar row moved without the signature knowing
    forceRebuild();
}

void FeaturesView::stepBar(int delta)
{
    auto bar = features->barItem();
    if (!bar) {
        return;
    }
    int at = features->row(bar);
    // Up: after the row two above (the top when only one is); Down: after the row below
    App::DocumentObject* member = nullptr;
    bool toEnd = false;
    if (delta < 0) {
        if (at == 0) {
            return;
        }
        member = at >= 2 ? memberOf(features->item(at - 2)) : nullptr;
    }
    else {
        if (at + 1 >= features->count()) {
            return;
        }
        member = memberOf(features->item(at + 1));
        toEnd = at + 1 == features->count() - 1;
    }
    barHinted = !toEnd;
    barHint = member && !toEnd ? member->getNameInDocument() : "";
    try {
        rollStudio(document(), studio(), member, toEnd);
    }
    catch (const Base::Exception& e) {
        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 5000);
    }
    // The bar stays selected for the next step
    barSelected = true;
    rebuild();
}

void FeaturesView::onRowsDropped(int row)
{
    auto doc = document();
    if (!doc || row < 0) {
        return;
    }
    // The dragged rows (the selected ones), and the list as dropped: the other rows and the bar,
    // with the dragged rows before row
    std::vector<App::DocumentObject*> rows;
    std::set<int> dragged;
    for (int i = 0; i < features->count(); ++i) {
        auto item = features->item(i);
        if (item->isSelected() && item->type() != FeatureList::BarType) {
            // A default geometry row stays at the top
            if (auto obj = memberOf(item)) {
                rows.push_back(obj);
                dragged.insert(i);
                // Its folded Merge goes with it (ops#640 rank 1)
                if (auto merge = foldedMerge(obj)) {
                    rows.push_back(const_cast<PartDesign::Boolean*>(merge));
                }
            }
        }
    }
    if (rows.empty()) {
        return;
    }
    std::vector<App::DocumentObject*> listed;  // the bar as null
    std::size_t dropAt = 0;
    int barAt = -1;
    for (int i = 0; i <= features->count(); ++i) {
        if (i == row) {
            dropAt = listed.size();
            listed.insert(listed.end(), rows.begin(), rows.end());
        }
        if (i == features->count()) {
            break;
        }
        if (dragged.count(i)) {
            continue;
        }
        auto item = features->item(i);
        if (item->type() == FeatureList::BarType) {
            barAt = static_cast<int>(listed.size());
            listed.push_back(nullptr);
            continue;
        }
        // A default geometry row is the top: null, as the bar's is, but not the bar
        listed.push_back(memberOf(item));
    }
    // What each goes after: the last row above it (null: the top)
    auto rowBefore = [&listed](std::size_t end) -> App::DocumentObject* {
        for (std::size_t i = end; i-- > 0;) {
            if (listed[i]) {
                return listed[i];
            }
        }
        return nullptr;
    };
    // After a row is after its folded Merge
    App::DocumentObject* after = pastMerge(rowBefore(dropAt));
    App::DocumentObject* bar =
        barAt >= 0 ? pastMerge(rowBefore(static_cast<std::size_t>(barAt))) : nullptr;
    std::string barName = bar ? bar->getNameInDocument() : "";
    bool rolledBack = PartDesign::isStudioRolledBack(doc, studio());
    try {
        moveRows(doc, studio(), rows, after, barAt >= 0, bar);
        // Rolled back, the bar stays where the list showed it as dropped (at the end it stays
        // at the end)
        if (rolledBack && barAt >= 0) {
            barHinted = true;
            barHint = barName;
        }
    }
    catch (const Base::Exception& e) {
        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 5000);
    }
    forceRebuild();
}

void FeaturesView::moveRows(App::Document* doc,
                            App::Part* studio,
                            const std::vector<App::DocumentObject*>& rows,
                            App::DocumentObject* after,
                            bool hinted,
                            App::DocumentObject* bar)
{
    if (!doc || rows.empty()) {
        return;
    }
    // Its transaction would commit an open edit's, as the bar's
    if (ViewProviderBody::isEditLocked(doc)) {
        throw Base::RuntimeError(reorderLockedMessage);
    }
    const auto bodies = PartDesign::studioBodies(doc, studio);
    std::vector<App::DocumentObject*> oldTips;
    for (auto body : bodies) {
        oldTips.push_back(body->Tip.getValue());
    }
    auto objCmd = [](App::DocumentObject* obj) {
        return obj ? Gui::Command::getObjectCmd(obj) : std::string("None");
    };
    std::string studioCmd = studio ? Gui::Command::getObjectCmd(studio)
                                   : std::string("App.getDocument('") + doc->getName() + "')";
    std::string rowsCmd = "[";
    for (auto obj : rows) {
        rowsCmd += (rowsCmd.size() > 1 ? ", " : "") + objCmd(obj);
    }
    rowsCmd += "]";
    std::string barCmd = hinted ? ", " + objCmd(bar) : std::string();
    int tid = doc->openTransaction(QT_TRANSLATE_NOOP("Command", "Reorder"));
    // FreeCAD-CH (ops#640): refused beside an open dialog's held step; commitTransaction(0)
    // would commit that step behind the dialog
    if (tid == 0 && doc->isStepLocked()) {
        throw Base::RuntimeError("Finish the open dialog first");
    }
    try {
        Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
        // FreeCAD-CH ops#654 S3: a drag of the studio's list's entries (the list made from the
        // derived order the first time, in this step)
        Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.studioList(%s, True)", studioCmd.c_str());
        const PartDesign::StudioList* list = PartDesign::StudioList::of(doc, studio);
        const auto oldSequence = PartDesign::studioSequence(doc, studio);
        const auto oldEntries = list ? list->Entries.getValues() : std::vector<App::DocumentObject*>();
        const App::DocumentObject* oldBar = entryAtBar(list);
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "PartDesign.moveInStudio(%s, %s, %s%s)",
            studioCmd.c_str(),
            rowsCmd.c_str(),
            objCmd(after).c_str(),
            barCmd.c_str()
        );
        bool tipsMoved = showMovedTips(bodies, oldTips);
        bool listMoved = list && (list->Entries.getValues() != oldEntries || entryAtBar(list) != oldBar);
        // FreeCAD-CH ops#654 P6p: a moved studio feature or pattern that now splits a part, or
        // leaves a solid outside its scope, makes them parts, in this step (Onshape H2)
        if (listMoved) {
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "for _o in %s:\n"
                "    if PartDesign.studioScopeIds(_o) or _o.isDerivedFrom('PartDesign::Transformed'):\n"
                "        PartDesign.studioMakePieces(_o)",
                rowsCmd.c_str()
            );
        }
        if (!tipsMoved && !listMoved && PartDesign::studioSequence(doc, studio) == oldSequence) {
            App::GetApplication().abortTransaction(tid);
            return;
        }
        Gui::Command::updateActive();
        App::GetApplication().commitTransaction(tid);
    }
    catch (const Base::Exception&) {
        App::GetApplication().abortTransaction(tid);
        throw;
    }
}

void FeaturesView::rollFromMenu(App::DocumentObject* member, bool toEnd)
{
    barHinted = !toEnd;
    barHint = member && !toEnd ? member->getNameInDocument() : "";
    try {
        rollStudio(document(), studio(), member, toEnd);
    }
    catch (const Base::Exception& e) {
        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 5000);
    }
    rebuild();
}

void FeaturesView::onFeatureDoubleClicked(QListWidgetItem* item)
{
    if (auto obj = memberOf(item)) {
        if (auto vp = viewProviderOf(obj)) {
            vp->doubleClicked();
        }
    }
}

void FeaturesView::rebuildConfigBar()
{
    auto doc = document();
    const bool assembly = !assemblyName.empty();
    auto cfg = doc && !assembly ? PartDesign::StudioConfig::of(doc, studio()) : nullptr;
    // An open Configuration panel follows the list's studio
    const std::string studioKey = doc ? std::string(doc->getName()) + "#" + studioName : std::string();
    if (studioKey != configStudioKey) {
        configStudioKey = studioKey;
        if (doc && !assembly && Gui::getMainWindow()->findChild<QWidget*>(QStringLiteral("Configurations"))) {
            const std::string code = "from PartDesign import ConfigurationsGui\nConfigurationsGui.follow('"
                + std::string(doc->getName()) + "', '" + studioName + "')\n";
            try {
                Base::Interpreter().runString(code.c_str());
            }
            catch (const Base::Exception& e) {
                e.reportException();
            }
        }
    }
    configButton->setVisible(!assembly);
    std::string key = studioKey;
    if (cfg && cfg->hasInputs()) {
        key += "\n" + std::string(cfg->Inputs.getValue()) + "\n";
        for (const auto& [input, value] : cfg->Active.getValues()) {
            key += input + "=" + value + ";";
        }
    }
    if (key == configBarKey) {
        return;
    }
    configBarKey = key;
    auto layout = configBar->layout();
    while (auto item = layout->takeAt(0)) {
        if (auto widget = item->widget()) {
            // Out of the bar now (a lookup by name finds the new control), deleted later
            widget->hide();
            widget->setObjectName(QString());
            widget->deleteLater();
        }
        delete item;
    }
    if (!cfg || !cfg->hasInputs()) {
        configBar->hide();
        return;
    }
    const auto active = cfg->Active.getValues();
    const QJsonArray inputs =
        QJsonDocument::fromJson(QByteArray(cfg->Inputs.getValue())).object().value(QLatin1String("inputs")).toArray();
    QPointer<FeaturesView> self(this);
    for (const auto& value : inputs) {
        const QJsonObject in = value.toObject();
        const std::string id = in.value(QLatin1String("id")).toString().toStdString();
        const QString name = in.value(QLatin1String("name")).toString();
        const QString kind = in.value(QLatin1String("kind")).toString();
        const QString objectName = QStringLiteral("configInput_") + QString::fromStdString(id);
        auto it = active.find(id);
        const std::string current = it != active.end() ? it->second : std::string();
        if (kind == QLatin1String("list")) {
            layout->addWidget(new QLabel(name, configBar));
            auto combo = new QComboBox(configBar);
            combo->setObjectName(objectName);
            std::string shown = current;
            bool found = false;
            for (const auto& row : in.value(QLatin1String("rows")).toArray()) {
                const QJsonObject r = row.toObject();
                combo->addItem(r.value(QLatin1String("name")).toString(), r.value(QLatin1String("id")).toString());
                found = found || r.value(QLatin1String("id")).toString().toStdString() == current;
            }
            if (!found) {
                shown = in.value(QLatin1String("default")).toString().toStdString();
            }
            combo->setCurrentIndex(std::max(0, combo->findData(QString::fromStdString(shown))));
            connect(combo, qOverload<int>(&QComboBox::activated), this, [self, combo, id](int index) {
                if (self) {
                    self->setActiveConfiguration(id, combo->itemData(index).toString().toStdString());
                }
            });
            layout->addWidget(combo);
        }
        else if (kind == QLatin1String("checkbox")) {
            auto box = new QCheckBox(name, configBar);
            box->setObjectName(objectName);
            const bool on = current == "true" || (current != "false" && in.value(QLatin1String("default")).toBool(true));
            box->setChecked(on);
            connect(box, &QCheckBox::clicked, this, [self, id](bool checked) {
                if (self) {
                    self->setActiveConfiguration(id, checked ? "true" : "false");
                }
            });
            layout->addWidget(box);
        }
        else {
            // A configuration Variable: its value box, in the user's units
            layout->addWidget(new QLabel(QStringLiteral("#") + name, configBar));
            auto line = new QLineEdit(configBar);
            line->setObjectName(objectName);
            const QString type = in.value(QLatin1String("type")).toString();
            QString text;
            if (type == QLatin1String("Text")) {
                text = QString::fromStdString(current.empty() ? in.value(QLatin1String("default")).toString().toStdString() : current);
            }
            else {
                const double v = current.empty() ? in.value(QLatin1String("default")).toDouble()
                                                 : QString::fromStdString(current).toDouble();
                if (type == QLatin1String("Length")) {
                    text = QString::fromStdString(Base::Quantity(v, Base::Unit::Length).getUserString());
                }
                else if (type == QLatin1String("Angle")) {
                    text = QString::fromStdString(Base::Quantity(v, Base::Unit::Angle).getUserString());
                }
                else if (type == QLatin1String("Integer")) {
                    text = QString::number(static_cast<long long>(std::llround(v)));
                }
                else {
                    text = QString::number(v, 'g', 12);
                }
            }
            line->setText(text);
            line->setMaximumWidth(110);
            connect(line, &QLineEdit::editingFinished, this, [self, line, id, text]() {
                if (self && line->text() != text) {
                    self->setActiveConfiguration(id, line->text().toStdString());
                }
            });
            layout->addWidget(line);
        }
    }
    static_cast<QHBoxLayout*>(layout)->addStretch(1);
    configBar->show();
}

void FeaturesView::setActiveConfiguration(const std::string& input, const std::string& value)
{
    if (!document()) {
        return;
    }
    std::string why;
    bool ok = false;
    try {
        ok = PartDesign::configSetActive(studio(), {{input, value}}, &why);
    }
    catch (const Base::Exception& e) {
        why = e.what();
    }
    catch (const std::exception& e) {
        why = e.what();
    }
    auto line = configBar->findChild<QLineEdit*>(QStringLiteral("configInput_") + QString::fromStdString(input));
    if (!ok && line) {
        // Onshape (CP2-8): a Variable value out of range is refused, not clamped; the box keeps the
        // typed text in red, with no message, and the value stays the model's
        line->setStyleSheet(QStringLiteral("QLineEdit { color: #c0392b; }"));
        line->setProperty("refused", QString::fromStdString(why));
        return;
    }
    if (!ok) {
        // Refused: the bar shows the model's value again
        Base::Console().warning("Configurations: %s\n", why.c_str());
        Gui::getMainWindow()->showMessage(QString::fromStdString(why), 5000);
        configBar->setToolTip(QString::fromStdString(why));
        configBarKey.clear();
        QPointer<FeaturesView> self(this);
        QTimer::singleShot(0, this, [self]() {
            if (self) {
                self->rebuildConfigBar();
            }
        });
    }
    else {
        configBar->setToolTip(QString());
    }
}

void FeaturesView::onFeatureMenu(const QPoint& pos)
{
    auto item = features->itemAt(pos);
    App::DocumentObject* obj = objectOf(item);
    QPointer<FeaturesView> self(this);
    bool locked = ViewProviderBody::isEditLocked(document());
    if (!obj) {
        // The bar's row and the empty space below the rows: Onshape's Roll to end (ref-D 3.11)
        if (!document() || features->count() == 0) {
            return;
        }
        QMenu menu(this);
        auto end = menu.addAction(tr("Roll to end"), [self]() {
            if (self) {
                self->rollFromMenu(nullptr, true);
            }
        });
        end->setObjectName(QStringLiteral("featureRollToEnd"));
        end->setEnabled(!locked);
        menu.exec(features->viewport()->mapToGlobal(pos));
        return;
    }
    std::string name = obj->getNameInDocument();
    auto runByName = [](const char* command) {
        Gui::Application::Instance->commandManager().runCommandByName(command);
    };
    // FreeCAD-CH ops#654 S3: Suppress and Delete act on the selected rows, or the clicked one; on a
    // studio feature, through its list (its steps with it), in one undo step
    std::vector<App::DocumentObject*> selected;
    for (auto selectedItem : features->selectedItems()) {
        if (auto member = memberOf(selectedItem)) {
            selected.push_back(member);
        }
    }
    std::vector<std::string> actedOn;
    for (auto row : rowsActedOn(selected, memberOf(item))) {
        actedOn.emplace_back(row->getNameInDocument());
    }
    auto rowsNamed = [self, actedOn]() {
        std::vector<App::DocumentObject*> rows;
        auto doc = self ? self->document() : nullptr;
        for (const auto& rowName : actedOn) {
            if (auto row = doc ? doc->getObject(rowName.c_str()) : nullptr) {
                rows.push_back(row);
            }
        }
        return rows;
    };
    QMenu menu(this);
    if (item->data(FeatureList::DefaultRole).toBool()) {
        // A default geometry row: Show/Hide only, as Onshape's
        auto show = menu.addAction(tr("Show/Hide"), [self, name]() {
            auto doc = self ? self->document() : nullptr;
            if (auto target = doc ? doc->getObject(name.c_str()) : nullptr) {
                self->toggleRowVisibility(target);
            }
        });
        show->setObjectName(QStringLiteral("featureToggleVisibility"));
        menu.exec(features->viewport()->mapToGlobal(pos));
        return;
    }
    auto edit = menu.addAction(tr("Edit"), [self, name]() {
        auto doc = self ? self->document() : nullptr;
        auto target = doc ? doc->getObject(name.c_str()) : nullptr;
        if (auto vp = target ? viewProviderOf(target) : nullptr) {
            vp->doubleClicked();
        }
    });
    edit->setObjectName(QStringLiteral("featureEdit"));
    // One feature is edited at a time
    edit->setEnabled(features->selectedItems().size() <= 1);
    auto rename = menu.addAction(tr("Rename"), [self]() {
        if (self) {
            self->renameCurrent(self->features);
        }
    });
    rename->setObjectName(QStringLiteral("featureRename"));
    menu.addSeparator();
    auto here = menu.addAction(tr("Roll to here"), [self, name]() {
        auto doc = self ? self->document() : nullptr;
        if (auto target = doc ? doc->getObject(name.c_str()) : nullptr) {
            self->rollFromMenu(target, false);
        }
    });
    here->setObjectName(QStringLiteral("featureRollTo"));
    here->setEnabled(!locked);
    auto end = menu.addAction(tr("Roll to end"), [self]() {
        if (self) {
            self->rollFromMenu(nullptr, true);
        }
    });
    end->setObjectName(QStringLiteral("featureRollToEnd"));
    end->setEnabled(!locked);
    menu.addSeparator();
    auto show = menu.addAction(tr("Show/Hide"), [runByName]() { runByName("Std_ToggleVisibility"); });
    show->setObjectName(QStringLiteral("featureToggleVisibility"));
    const bool suppressOn = !isSuppressed(obj);
    auto suppress = menu.addAction(
        isSuppressed(obj) ? tr("Unsuppress") : tr("Suppress"),
        [self, runByName, rowsNamed, suppressOn]() {
            try {
                if (!self || !suppressOwnerRows(self->document(), rowsNamed(), suppressOn)) {
                    runByName("Std_ToggleSuppress");
                }
            }
            catch (const Base::Exception& e) {
                Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 5000);
            }
        }
    );
    suppress->setObjectName(QStringLiteral("featureToggleSuppress"));
    // Onshape's configured suppression (ops#671 C2, CP2-3): "Configure suppression with <input>",
    // or "Unconfigure suppression" on a configured one; the row looks like any suppressed one
    if (PartDesign::isStudioOwner(obj) && selected.size() <= 1) {
        for (const auto& configItem : PartDesign::configMenuItems(obj, std::string())) {
            auto action = menu.addAction(QString::fromStdString(configItem.label), [self, name, configItem]() {
                auto doc = self ? self->document() : nullptr;
                if (auto target = doc ? doc->getObject(name.c_str()) : nullptr) {
                    App::runConfigMenuItem(target, std::string(), configItem);
                }
            });
            action->setObjectName(QStringLiteral("featureConfig_") + QString::fromStdString(configItem.action));
            action->setEnabled(!locked);
        }
    }
    auto dependencies = menu.addAction(tr("Show dependencies"), [self, name]() {
        auto doc = self ? self->document() : nullptr;
        if (auto target = doc ? doc->getObject(name.c_str()) : nullptr) {
            self->showDependencies(target);
        }
    });
    dependencies->setObjectName(QStringLiteral("featureDependencies"));
    auto fit = menu.addAction(tr("Zoom to selection"), [runByName]() { runByName("Std_ViewFitSelection"); });
    fit->setObjectName(QStringLiteral("featureZoom"));
    menu.addSeparator();
    auto remove = menu.addAction(tr("Delete"), [self, runByName, rowsNamed]() {
        try {
            if (!self || !deleteOwnerRows(self->document(), rowsNamed())) {
                runByName("Std_Delete");
            }
        }
        catch (const Base::Exception& e) {
            Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 5000);
        }
    });
    remove->setObjectName(QStringLiteral("featureDelete"));
    menu.exec(features->viewport()->mapToGlobal(pos));
}

void FeaturesView::showDependencies(App::DocumentObject* obj)
{
    // Onshape's Show dependencies: the feature's parents (what it uses) and children (what uses
    // it), marked in the list until the selection changes. The base a feature is merged with is
    // the history's order, not a parent, as Onshape's merge scope. FreeCAD-CH ops#654 S3: nor
    // the other links the list's order writes (an owner's in-scope bases, a step's owner); a
    // studio feature reads, and is read, with its steps, each read as its row
    auto linksOf = [](const App::DocumentObject* reader, std::vector<App::DocumentObject*>& found) {
        std::vector<App::Property*> props;
        reader->getPropertyList(props);
        for (auto prop : props) {
            auto link = freecad_cast<App::PropertyLinkBase*>(prop);
            const char* name = prop->getName();
            if (!link || !name || strcmp(name, "BaseFeature") == 0 || strcmp(name, "StudioBases") == 0
                || strcmp(name, "StudioOwner") == 0) {
                continue;
            }
            std::vector<App::DocumentObject*> objs;
            link->getLinks(objs);
            for (auto read : objs) {
                if (read) {
                    found.push_back(entryOfRow(read));
                }
            }
        }
    };
    auto reads = [&linksOf](const App::DocumentObject* reader) {
        std::vector<App::DocumentObject*> found;
        linksOf(reader, found);
        if (PartDesign::isStudioOwner(reader)) {
            for (auto step : PartDesign::StudioList::stepsOf(reader)) {
                linksOf(step, found);
            }
        }
        return found;
    };
    dependencyParents.clear();
    dependencyChildren.clear();
    QStringList parentLabels;
    QStringList childLabels;
    auto doc = document();
    const PartDesign::StudioList* list = doc ? PartDesign::StudioList::of(doc, studio()) : nullptr;
    std::size_t barRow = 0;
    const auto sequence = !doc ? std::vector<App::DocumentObject*>()
        : list                 ? listRows(list, doc, studio(), barRow)
                               : PartDesign::studioSequence(doc, studio());
    auto member = [&sequence](const App::DocumentObject* other) {
        return std::ranges::find(sequence, other) != sequence.end();
    };
    for (auto parent : reads(obj)) {
        if (parent != obj && member(parent) && dependencyParents.insert(parent->getNameInDocument()).second) {
            parentLabels << QString::fromUtf8(parent->Label.getValue());
        }
    }
    for (auto other : sequence) {
        auto in = reads(other);
        if (other != obj && std::ranges::find(in, obj) != in.end()) {
            dependencyChildren.insert(other->getNameInDocument());
            childLabels << QString::fromUtf8(other->Label.getValue());
        }
    }
    QString none = tr("none");
    Gui::getMainWindow()->showMessage(
        tr("'%1': parents: %2; children: %3")
            .arg(
                QString::fromUtf8(obj->Label.getValue()),
                parentLabels.isEmpty() ? none : parentLabels.join(QStringLiteral(", ")),
                childLabels.isEmpty() ? none : childLabels.join(QStringLiteral(", "))
            ),
        10000
    );
    markDependencies();
}

void FeaturesView::markDependencies()
{
    QColor parent = palette().color(QPalette::Highlight);
    parent.setAlpha(60);
    QColor child(0xc8, 0x78, 0x00, 60);
    // The feature being made or edited (ops#640 rank 40)
    QColor edited = palette().color(QPalette::Highlight);
    edited.setAlpha(35);
    // The feature a double click showed and its sketch (P8)
    QColor creator = palette().color(QPalette::Highlight);
    creator.setAlpha(110);
    // Not a rename: the rows' data changes
    QScopedValueRollback<bool> quiet(syncing, true);
    for (int i = 0; i < features->count(); ++i) {
        auto item = features->item(i);
        std::string name = item->data(Qt::UserRole).toByteArray().toStdString();
        QVariant background;
        if (dependencyParents.count(name)) {
            background = QBrush(parent);
        }
        else if (dependencyChildren.count(name)) {
            background = QBrush(child);
        }
        else if (!name.empty() && (name == creatorName || name == creatorSketchName)
                 && item->type() != FeatureList::BarType) {
            background = QBrush(creator);
        }
        else if (!name.empty() && name == editedName && item->type() != FeatureList::BarType) {
            background = QBrush(edited);
        }
        item->setData(Qt::BackgroundRole, background);
        item->setData(DependencyRole, dependencyParents.count(name) ? 1 : dependencyChildren.count(name) ? 2 : 0);
    }
}

App::DocumentObject* FeaturesView::creatorOf(App::DocumentObject* shape, const char* element)
{
    if (!shape || !element || !*element) {
        return nullptr;
    }
    // The history runs from the shape's feature down to where the element comes from; the items
    // above that only changed it (a fillet, a fuse), so the last one decides (as the reference
    // fields' featureOfElement)
    const std::list<Data::HistoryItem> history = Part::Feature::getElementHistory(shape, element, true);
    App::DocumentObject* origin = history.empty() ? shape : history.back().obj;
    if (!origin) {
        return nullptr;
    }
    auto isBinder = [](App::DocumentObject* obj) {
        return obj->isDerivedFrom<PartDesign::ShapeBinder>()
            || obj->isDerivedFrom<PartDesign::SubShapeBinder>();
    };
    if (origin->isDerivedFrom<PartDesign::Feature>() && !isBinder(origin)) {
        return origin;
    }
    // A sketch or a binder: the feature whose profile it is, or a binder of it; one in the
    // history first (a sketch two features use)
    std::vector<App::DocumentObject*> profiles {origin};
    for (std::size_t i = 0; i < profiles.size(); ++i) {
        for (App::DocumentObject* user : profiles[i]->getInList()) {
            if (isBinder(user) && std::ranges::find(profiles, user) == profiles.end()) {
                profiles.push_back(user);
            }
        }
    }
    App::DocumentObject* first = nullptr;
    for (App::DocumentObject* profile : profiles) {
        for (App::DocumentObject* user : profile->getInList()) {
            auto based = freecad_cast<PartDesign::ProfileBased*>(user);
            if (!based || based->Profile.getValue() != profile || based->Suppressed.getValue()) {
                continue;
            }
            const bool inHistory = std::ranges::any_of(history, [based](const Data::HistoryItem& item) {
                return item.obj == based;
            });
            if (inHistory) {
                return based;
            }
            if (!first) {
                first = based;
            }
        }
    }
    return first;
}

void FeaturesView::showCreatorOf(const std::string& doc, const std::string& obj, const std::string& sub)
{
    FeaturesView* view = instance();
    App::Document* document = App::GetApplication().getDocument(doc.c_str());
    App::DocumentObject* owner = document ? document->getObject(obj.c_str()) : nullptr;
    if (!view || !owner) {
        return;
    }
    const char* subElement = nullptr;
    App::DocumentObject* shape = owner->resolve(sub.c_str(), nullptr, nullptr, &subElement);
    const std::string element = subElement ? Data::oldElementName(subElement) : std::string();
    App::DocumentObject* creator = creatorOf(shape, element.c_str());
    view->clearCreator();
    if (!creator) {
        return;
    }
    view->creatorName = creator->getNameInDocument();
    if (auto based = freecad_cast<PartDesign::ProfileBased*>(creator)) {
        if (App::DocumentObject* profile = based->Profile.getValue()) {
            view->creatorSketchName = profile->getNameInDocument();
        }
    }
    // The faces the feature made, tinted in the shown shape
    auto shown = freecad_cast<PartGui::ViewProviderPartExt*>(
        Gui::Application::Instance->getViewProvider(shape)
    );
    const Part::TopoShape topo = shown ? Part::Feature::getTopoShape(shape, Part::ShapeOption::ResolveLink)
                                         : Part::TopoShape();
    const int faces = topo.isNull() ? 0 : static_cast<int>(topo.countSubShapes(TopAbs_FACE));
    const std::vector<App::Material> base = shown ? shown->ShapeAppearance.getValues()
                                                  : std::vector<App::Material>();
    if (faces > 1 && !base.empty()) {
        const QColor tint = view->palette().color(QPalette::Highlight);
        std::vector<App::Material> materials;
        materials.reserve(faces);
        bool any = false;
        for (int i = 0; i < faces; ++i) {
            App::Material material = base[std::size_t(i) < base.size() ? i : 0];
            const std::string face = "Face" + std::to_string(i + 1);
            if (creatorOf(shape, face.c_str()) == creator) {
                material.diffuseColor = Base::Color(
                    static_cast<float>(tint.redF()),
                    static_cast<float>(tint.greenF()),
                    static_cast<float>(tint.blueF())
                );
                any = true;
            }
            materials.push_back(material);
        }
        if (any) {
            shown->setHighlightedFaces(materials);
            view->creatorShape = App::DocumentObjectT(shape);
        }
    }
    view->markDependencies();
}

void FeaturesView::clearCreator()
{
    if (creatorName.empty() && creatorSketchName.empty() && !creatorShape.getObject()) {
        return;
    }
    creatorName.clear();
    creatorSketchName.clear();
    if (App::DocumentObject* shape = creatorShape.getObject()) {
        if (auto shown = freecad_cast<PartGui::ViewProviderPartExt*>(
                Gui::Application::Instance->getViewProvider(shape)
            )) {
            shown->unsetHighlightedFaces();
        }
    }
    creatorShape = App::DocumentObjectT();
    markDependencies();
}

void FeaturesView::onPartClicked(QTreeWidgetItem* item, int column)
{
    if (column != 1) {
        return;
    }
    auto obj = objectOf(item);
    auto vp = obj ? viewProviderOf(obj) : nullptr;
    if (vp && vp->canToggleVisibility()) {
        vp->Gui::ViewProvider::toggleVisibility();
        scheduleRebuild();
    }
}

void FeaturesView::onPartDoubleClicked(QTreeWidgetItem* item, int column)
{
    if (column == 1) {
        return;
    }
    // As the tree's double-click: a Body becomes the active one (ViewProviderBody::doubleClicked())
    if (auto obj = objectOf(item)) {
        if (auto vp = viewProviderOf(obj)) {
            vp->doubleClicked();
        }
    }
}

void FeaturesView::renameCurrent(QAbstractItemView* view)
{
    // The row the user acts on: the current one, if selected, else the first selected
    if (view == features) {
        auto item = features->currentItem();
        if (!item || !item->isSelected()) {
            auto selected = features->selectedItems();
            item = selected.isEmpty() ? nullptr : selected.front();
        }
        if (item && objectOf(item)) {
            features->setCurrentItem(item);
            renaming = true;
            features->editItem(item);
            // No editor opened: rebuilds mustn't wait for a commit that won't come (review
            // sff13-r1 Opus)
            renaming = features->viewport()->findChild<QLineEdit*>() != nullptr;
        }
        return;
    }
    auto item = parts->currentItem();
    if (!item || !item->isSelected()) {
        auto selected = parts->selectedItems();
        item = selected.isEmpty() ? nullptr : selected.front();
    }
    if (item && objectOf(item)) {
        parts->setCurrentItem(item, 0);
        renaming = true;
        parts->editItem(item, 0);
        renaming = parts->viewport()->findChild<QLineEdit*>() != nullptr;
    }
}

void FeaturesView::rename(App::DocumentObject* obj, const QString& text)
{
    renaming = false;
    // An empty name, or none changed: the row shows the label again
    QByteArray label = text.trimmed().toUtf8();
    if (obj && !label.isEmpty() && label != obj->Label.getValue()) {
        auto doc = obj->getDocument();
        int tid = doc->openTransaction(QT_TRANSLATE_NOOP("Command", "Rename"));
        obj->Label.setValue(label.constData());
        App::GetApplication().commitTransaction(tid);
    }
    // On the timer: the editor that committed the text is still open (closeEditor follows);
    // the row shows the label again even when the rows' keys didn't change
    featureRows.clear();
    partRows.clear();
    scheduleRebuild();
}

void FeaturesView::endRename()
{
    // The editor closed without a change (Escape, or the same text): no itemChanged
    if (renaming) {
        renaming = false;
        scheduleRebuild();
    }
}

void FeaturesView::onPartMenu(const QPoint& pos)
{
    auto item = parts->itemAt(pos);
    App::DocumentObject* obj = objectOf(item);
    if (!obj) {
        return;
    }
    // The menu acts on the selection: a right-click outside it selects the row alone first
    if (!item->isSelected()) {
        parts->clearSelection();
        item->setSelected(true);
    }
    // Current without touching the selection: the menu acts on every selected row (review R10-1)
    parts->setCurrentItem(item, 0, QItemSelectionModel::NoUpdate);
    QPointer<FeaturesView> self(this);
    auto runByName = [](const char* command) {
        Gui::Application::Instance->commandManager().runCommandByName(command);
    };
    QMenu menu(this);
    auto rename = menu.addAction(tr("Rename"), [self]() {
        if (self) {
            self->renameCurrent(self->parts);
        }
    });
    rename->setObjectName(QStringLiteral("partRename"));
    menu.addSeparator();
    auto show = menu.addAction(tr("Show/Hide"), [runByName]() { runByName("Std_ToggleVisibility"); });
    show->setObjectName(QStringLiteral("partToggleVisibility"));
    auto isolate = menu.addAction(tr("Isolate"), [runByName]() { runByName("Std_Isolate"); });
    isolate->setObjectName(QStringLiteral("partIsolate"));
    // Onshape's Hide other parts: every other part of the list, not the sketches or planes
    std::vector<std::string> keep;
    for (auto selected : parts->selectedItems()) {
        if (auto part = objectOf(selected)) {
            keep.emplace_back(part->getNameInDocument());
        }
    }
    auto others = menu.addAction(tr("Hide other parts"), [self, keep]() {
        if (!self) {
            return;
        }
        for (int i = 0; i < self->parts->topLevelItemCount(); ++i) {
            auto part = self->objectOf(self->parts->topLevelItem(i));
            auto vp = part ? viewProviderOf(part) : nullptr;
            if (vp && vp->isShow() && std::ranges::find(keep, part->getNameInDocument()) == keep.end()) {
                vp->hide();
            }
        }
        self->scheduleRebuild();
    });
    others->setObjectName(QStringLiteral("partHideOthers"));
    auto appearance = menu.addAction(tr("Edit appearance..."), [runByName]() { runByName("Std_SetAppearance"); });
    appearance->setObjectName(QStringLiteral("partAppearance"));
    auto fit = menu.addAction(tr("Zoom to selection"), [runByName]() { runByName("Std_ViewFitSelection"); });
    fit->setObjectName(QStringLiteral("partZoom"));
    // Onshape's Create drawing of <part> (ops#640 rank 62): TechDraw's command, registered at the
    // GUI's start, draws the one selected object, so the part is selected alone first
    menu.addSeparator();
    const std::string partName = obj->getNameInDocument();
    auto drawing = menu.addAction(
        tr("Create drawing of %1...").arg(QString::fromUtf8(obj->Label.getValue())),
        [self, partName, runByName]() {
            auto doc = self ? self->document() : nullptr;
            auto part = doc ? doc->getObject(partName.c_str()) : nullptr;
            if (!part) {
                return;
            }
            self->pushSelection({part});
            runByName("TechDraw_CreateDrawing");
        }
    );
    drawing->setObjectName(QStringLiteral("partCreateDrawing"));
    drawing->setEnabled(
        Gui::Application::Instance->commandManager().getCommandByName("TechDraw_CreateDrawing")
        != nullptr
    );
    menu.addSeparator();
    // A Body's delete is a Delete part feature at the bar (ops#635)
    auto remove = menu.addAction(tr("Delete"), [runByName]() { runByName("Std_Delete"); });
    remove->setObjectName(QStringLiteral("partDelete"));
    menu.exec(parts->viewport()->mapToGlobal(pos));
}

// --------------------------------------------------------- the Assembly tab's list (round 10)

namespace
{
/// The top-level index of the Mates header in the Assembly tab's list
constexpr int matesHeader = 1;

/// Whether item is a row under the Mates header
bool isMateRow(QTreeWidgetItem* item)
{
    if (!item || !item->parent()) {
        return false;
    }
    QTreeWidgetItem* top = item;
    while (top->parent()) {
        top = top->parent();
    }
    return top->treeWidget() && top->treeWidget()->indexOfTopLevelItem(top) == matesHeader;
}
}  // namespace

void FeaturesView::rebuildAssembly()
{
    auto doc = document();
    App::DocumentObject* assembly = doc && !assemblyName.empty() ? doc->getObject(assemblyName.c_str())
                                                                 : nullptr;
    auto group = assembly ? assembly->getExtensionByType<App::GroupExtension>(true) : nullptr;
    if (!group) {
        if (!assemblyRows.empty() || assemblyList->topLevelItemCount() > 0) {
            assemblyList->clear();
            assemblyRows.clear();
        }
        return;
    }
    // Onshape's assembly list (gap A27): the instances, a rigid group's members under it, then the
    // mates. A rigid group and a grounding are objects of the joint group: the group is listed
    // with the instances, a grounding as its instance's pin (Onshape fixes an instance, no mate)
    std::vector<App::DocumentObject*> instances;
    App::DocumentObject* jointGroup = nullptr;
    for (auto obj : group->Group.getValues()) {
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        if (obj->getTypeId().getName() == std::string_view("Assembly::JointGroup")) {
            if (!jointGroup) {
                jointGroup = obj;
            }
        }
        else if (isInstance(obj)) {
            instances.push_back(obj);
        }
    }
    std::vector<App::DocumentObject*> mates;
    std::vector<std::pair<App::DocumentObject*, std::vector<App::DocumentObject*>>> rigidGroups;
    std::set<const App::DocumentObject*> grouped;
    /// The instances fixed, and the grounding that fixes each
    std::map<const App::DocumentObject*, App::DocumentObject*> fixed;
    auto joints = jointGroup ? jointGroup->getExtensionByType<App::GroupExtension>(true) : nullptr;
    for (auto obj : joints ? joints->Group.getValues() : std::vector<App::DocumentObject*>()) {
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        if (auto ground = freecad_cast<App::PropertyLink*>(obj->getPropertyByName("ObjectToGround"))) {
            if (ground->getValue()) {
                fixed.emplace(ground->getValue(), obj);
            }
            continue;
        }
        auto members = freecad_cast<App::PropertyLinkList*>(obj->getPropertyByName("ObjectsToRigidGroup"));
        if (!members) {
            mates.push_back(obj);
            continue;
        }
        std::vector<App::DocumentObject*> kept;
        for (auto member : members->getValues()) {
            if (member && member->isAttachedToDocument()) {
                kept.push_back(member);
                grouped.insert(member);
            }
        }
        rigidGroups.emplace_back(obj, kept);
    }
    std::erase_if(instances, [&grouped](const App::DocumentObject* obj) { return grouped.count(obj) > 0; });
    std::size_t instanceCount = instances.size();
    for (const auto& rigid : rigidGroups) {
        instanceCount += rigid.second.size();
    }

    // What the rows show: unchanged, they stay (with their selection anchor)
    auto key = [&fixed](const App::DocumentObject* obj, char depth) {
        return depth + rowKey(obj, false, std::string(mateSuppressed(obj) ? "S" : "") + (fixed.count(obj) ? "F" : ""));
    };
    std::vector<std::string> rows;
    for (auto obj : instances) {
        rows.push_back(key(obj, '1'));
    }
    for (const auto& [rigid, members] : rigidGroups) {
        rows.push_back(key(rigid, '1'));
        for (auto member : members) {
            rows.push_back(key(member, '2'));
        }
    }
    rows.emplace_back("|");
    for (auto obj : mates) {
        rows.push_back(key(obj, '1'));
    }
    if (rows == assemblyRows && assemblyList->topLevelItemCount() == 2) {
        return;
    }
    assemblyRows = rows;
    assemblyList->clear();
    auto header = [this](const QString& text) {
        auto item = new QTreeWidgetItem(assemblyList, QStringList(text));
        // Not selectable: a header stands for no object
        item->setFlags(Qt::ItemIsEnabled);
        QFont font = assemblyList->font();
        font.setBold(true);
        item->setFont(0, font);
        return item;
    };
    auto row = [this, &fixed](QTreeWidgetItem* parent, App::DocumentObject* obj) {
        auto item = new QTreeWidgetItem(parent, QStringList(QString::fromUtf8(obj->Label.getValue())));
        item->setData(0, Qt::UserRole, QByteArray(obj->getNameInDocument()));
        item->setIcon(0, statusIcon(obj, false));
        const bool suppressed = mateSuppressed(obj);
        QFont font = statusFont(assemblyList->font(), obj, false);
        font.setStrikeOut(font.strikeOut() || suppressed);
        item->setFont(0, font);
        // A mate in error is red, as the solver panel lists it (a suppressed one isn't solved)
        item->setData(0, Qt::ForegroundRole, suppressed ? QVariant() : statusForeground(obj));
        item->setToolTip(0, rowToolTip(obj, nullptr));
        // A fixed instance: the grounding's pin at the row's end
        if (auto it = fixed.find(obj); it != fixed.end()) {
            auto vp = viewProviderOf(it->second);
            item->setIcon(1, vp ? vp->getIcon() : QIcon());
            item->setToolTip(1, tr("Fixed"));
            item->setData(1, Qt::UserRole, QByteArray(it->second->getNameInDocument()));
        }
        return item;
    };
    auto instancesItem = header(tr("Instances (%1)").arg(instanceCount));
    for (auto obj : instances) {
        row(instancesItem, obj);
    }
    for (const auto& [rigid, members] : rigidGroups) {
        auto rigidItem = row(instancesItem, rigid);
        for (auto member : members) {
            row(rigidItem, member);
        }
    }
    auto matesItem = header(tr("Mates (%1)").arg(mates.size()));
    for (auto obj : mates) {
        row(matesItem, obj);
    }
    assemblyList->expandAll();
}

void FeaturesView::onAssemblyDoubleClicked(QTreeWidgetItem* item, int column)
{
    Q_UNUSED(column);
    // A mate's double-click opens its dialog, as Onshape's (the joint's own double-click)
    if (!isMateRow(item)) {
        return;
    }
    if (auto obj = objectOf(item)) {
        if (auto vp = viewProviderOf(obj)) {
            vp->doubleClicked();
        }
    }
}

void FeaturesView::onAssemblyMenu(const QPoint& pos)
{
    auto item = assemblyList->itemAt(pos);
    App::DocumentObject* obj = objectOf(item);
    if (!obj) {
        return;
    }
    // The menu acts on the selection: a right-click outside it selects the row alone first
    if (!item->isSelected()) {
        assemblyList->clearSelection();
        item->setSelected(true);
    }
    // Current without touching the selection: the menu acts on every selected row (review R10-1)
    assemblyList->setCurrentItem(item, 0, QItemSelectionModel::NoUpdate);
    QPointer<FeaturesView> self(this);
    auto runByName = [](const char* command) {
        Gui::Application::Instance->commandManager().runCommandByName(command);
    };
    QMenu menu(this);
    if (isMateRow(item)) {
        const std::string name = obj->getNameInDocument();
        auto edit = menu.addAction(tr("Edit"), [self, name]() {
            auto doc = self ? self->document() : nullptr;
            auto target = doc ? doc->getObject(name.c_str()) : nullptr;
            if (auto vp = target ? viewProviderOf(target) : nullptr) {
                vp->doubleClicked();
            }
        });
        edit->setObjectName(QStringLiteral("mateEdit"));
        edit->setEnabled(assemblyList->selectedItems().size() <= 1);
        // The selected mates suppressed, or back, in one undo step, and solved again
        std::vector<std::string> names;
        for (auto selected : assemblyList->selectedItems()) {
            auto mate = isMateRow(selected) ? objectOf(selected) : nullptr;
            if (mate && freecad_cast<App::PropertyBool*>(mate->getPropertyByName("Suppressed"))) {
                names.emplace_back(mate->getNameInDocument());
            }
        }
        const bool suppress = !mateSuppressed(obj);
        auto toggle = menu.addAction(suppress ? tr("Suppress") : tr("Unsuppress"), [self, names, suppress]() {
            auto doc = self ? self->document() : nullptr;
            if (!doc || names.empty()) {
                return;
            }
            int tid = doc->openTransaction(
                suppress ? QT_TRANSLATE_NOOP("Command", "Suppress") : QT_TRANSLATE_NOOP("Command", "Unsuppress")
            );
            for (const auto& mateName : names) {
                auto mate = doc->getObject(mateName.c_str());
                auto prop = mate ? freecad_cast<App::PropertyBool*>(mate->getPropertyByName("Suppressed"))
                                 : nullptr;
                if (prop) {
                    prop->setValue(suppress);
                }
            }
            doc->recompute();
            App::GetApplication().commitTransaction(tid);
        });
        toggle->setObjectName(QStringLiteral("mateToggleSuppress"));
        toggle->setEnabled(!names.empty());
    }
    else {
        auto show = menu.addAction(tr("Show/Hide"), [runByName]() { runByName("Std_ToggleVisibility"); });
        show->setObjectName(QStringLiteral("instanceToggleVisibility"));
        auto isolate = menu.addAction(tr("Isolate"), [runByName]() { runByName("Std_Isolate"); });
        isolate->setObjectName(QStringLiteral("instanceIsolate"));
        // Onshape's Fix and Unfix: the Assembly workbench's grounding
        auto fix = menu.addAction(tr("Fix/Unfix"), [runByName]() { runByName("Assembly_ToggleGrounded"); });
        fix->setObjectName(QStringLiteral("instanceToggleFixed"));
        fix->setEnabled(
            Gui::Application::Instance->commandManager().getCommandByName("Assembly_ToggleGrounded") != nullptr
        );
        // A rigid group's row is not a part: its Show/Hide, Isolate and Fix would act on the joint
        // object or do nothing (review R10-6)
        if (!obj->isDerivedFrom<App::GeoFeature>()) {
            show->setEnabled(false);
            isolate->setEnabled(false);
            fix->setEnabled(false);
        }
    }
    auto fit = menu.addAction(tr("Zoom to selection"), [runByName]() { runByName("Std_ViewFitSelection"); });
    fit->setObjectName(QStringLiteral("assemblyZoom"));
    menu.addSeparator();
    auto remove = menu.addAction(tr("Delete"), [runByName]() { runByName("Std_Delete"); });
    remove->setObjectName(QStringLiteral("assemblyDelete"));
    menu.exec(assemblyList->viewport()->mapToGlobal(pos));
}

#include "moc_FeaturesView.cpp"
