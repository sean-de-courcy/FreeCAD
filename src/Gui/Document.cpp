/***************************************************************************
 *   Copyright (c) 2004 Jürgen Riegel <juergen.riegel@web.de>              *
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

#include <tuple>
#include <algorithm>
#include <memory>
#include <list>
#include <string>
#include <map>
#include <set>
#include <unordered_map>
#include <vector>
#include <cctype>
#include <mutex>
#include <QAction>
#include <QApplication>
#include <QCheckBox>
#include <QDir>
#include <QFileInfo>
#include <QMessageBox>
#include <QOpenGLWidget>
#include <QTextStream>
#include <QStatusBar>
#include <Inventor/actions/SoSearchAction.h>
#include <Inventor/nodes/SoSeparator.h>

#include <App/AutoTransaction.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/DocumentObjectGroup.h>
#include <App/ForkRelease.h>
#include <App/Transactions.h>
#include <App/ElementNamingUtils.h>
#include <App/NameTable.h>
#include <App/PropertyPythonObject.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Matrix.h>
#include <Base/Reader.h>
#include <Base/Writer.h>
#include <Base/Tools.h>

#include "Document.h"
#include "DocumentPy.h"
#include "Application.h"
#include "Command.h"
#include "Control.h"
#include "DocumentTabBar.h"
#include "FileDialog.h"
#include "MainWindow.h"
#include "MDIView.h"
#include "NamedViews.h"
#include "NotificationArea.h"
#include "Selection.h"
#include "Thumbnail.h"
#include "Tree.h"
#include "View3DInventor.h"
#include "View3DInventorViewer.h"
#include "ViewProviderDocumentObject.h"
#include "ViewProviderDocumentObjectGroup.h"
#include "WaitCursor.h"


FC_LOG_LEVEL_INIT("Gui", true, true)

using namespace Gui;
namespace sp = std::placeholders;

namespace Gui::DocumentTabs
{
// FreeCAD-CH (ops#640, F6-3): DocumentTabBar.cpp's (no header names it): shows the tab the next
// undo or redo step was made in; false when an open dialog refuses that switch (the undo refused)
bool undoAllowed(Gui::Document* gdoc, bool undo);
}  // namespace Gui::DocumentTabs

namespace Gui
{

/// FreeCAD-CH (ops#640): no document regenerates on commit while an object is in edit (defined
/// and explained in Gui/Application.cpp; not in Application.h, which hundreds of files include)
void updateRegenerationHold(const App::Document* closingStep = nullptr);
/// FreeCAD-CH (ops#640): defined below; Gui/CommandDoc.cpp and Gui/View3DInventor.cpp declare it
bool hasUndoStep(const Document* doc, bool undo);
/// FreeCAD-CH (ops#640): defined below; PartDesign's TaskFeatureParameters.cpp declares it
GuiExport bool editStartedUnchanged(const App::Document* doc);
/// FreeCAD-CH (ops#640, hands-on B5-5): defined below; Sketcher's ViewProviderSketch.cpp declares it
GuiExport int undoOpenSketchSession(const App::Document* doc);

// Pimpl class
struct DocumentP
{
    Thumbnail thumb;
    int _iWinCount;
    int _iDocId;
    bool _isClosing;
    bool _isModified;
    bool _isTransacting;
    bool _isActive;
    bool _restoredGuiDocument;
    bool _changeViewTouchDocument;
    bool _editWantsRestore;
    bool _editWantsRestorePrevious;
    /// FreeCAD-CH (ops#640): this edit holds the App document's step lock (one lockStep())
    bool _editHoldsStep = false;
    /// FreeCAD-CH (ops#640): acceptOpenStep() is accepting the dialog (no re-entry)
    bool _acceptingStep = false;
    /** FreeCAD-CH (ops#640, regen-plan item 7, hands-on R9, R14): a sketch's edit is a session
     * that is one undo step once it is closed, as in Onshape. Its transactions stay App's own
     * (each tool commits one: the sketch's Ctrl+Z steps them one by one); the Gui document
     * groups them by id: _stepGroupOf maps each transaction opened during the edit, and the one
     * pending or booked when it started (the "New Sketch" or "Sketch on Face" that made the
     * sketch: the opener), to the session's key. undo(), redo() and the undo/redo lists then
     * take a closed session's transactions together. While the session is open they step its
     * own transactions only (_sessionIds, the opener excepted): Ctrl+Z stops at the sketch's
     * start, and the sketch stays open. Ids outlive an undo (App's redo transaction keeps the
     * id), so the grouping holds through undo and redo; ids no stack holds any more are left
     * in the map, unread. App's own undo() (a script's App.ActiveDocument.undo()) still pops
     * one transaction. */
    std::map<int, int> _stepGroupOf;
    std::map<int, std::string> _stepGroupName;  ///< a closed session's step name, by key
    int _stepGroupCount = 0;
    int _session = 0;  ///< the open session's key; 0 when no sketch is in edit
    int _sessionOpener = 0;
    std::string _sessionLabel;
    std::set<int> _sessionIds;
    /** FreeCAD-CH (ops#640): the session's transactions that changed an object other than the
     * one in edit outside a recompute (a Variables panel edit during the sketch's edit): the
     * Cancel's undo (undoOpenSketchSession) leaves them alone and restores the sketch instead */
    std::set<int> _sessionForeignIds;
    /** FreeCAD-CH (ops#640): the user's undo limit (the MaxUndoSize preference) counts steps,
     * not App's transactions: App's limit is set before each commit (updateUndoLimit) so that its
     * trim leaves the newest steps whole, a closed sketch session with all its transactions.
     * Counted by transactions, a sketch of more strokes than the limit lost its oldest ones, the
     * "New Sketch" opener first, and one Ctrl+Z after the close left the sketch with its first
     * elements. */
    unsigned _undoSteps = 20;
    /// FreeCAD-CH (ops#640): the edit started with no change in its step (editStartedUnchanged())
    bool _editStartedUnchanged = false;
    int _editMode;
    int _editModePrevious;
    ViewProvider* _editViewProvider;
    ViewProvider* _editViewProviderPrevious;
    App::DocumentObject* _editingObject;
    ViewProviderDocumentObject* _editViewProviderParent;
    std::string _editSubname;
    std::string _editSubElement;
    std::string _workbenchName;  // Name of the workbench acting on this document
    Base::Matrix4D _editingTransform;
    View3DInventorViewer* _editingViewer;
    std::set<const App::DocumentObject*> _editObjs;

    Application* _pcAppWnd;
    // the doc/Document
    App::Document* _pcDocument;
    /// List of all registered views
    std::list<Gui::BaseView*> baseViews;
    /// List of all registered views
    std::list<Gui::BaseView*> passiveViews;
    std::map<const App::DocumentObject*, ViewProviderDocumentObject*> _ViewProviderMap;
    std::map<SoSeparator*, ViewProviderDocumentObject*> _CoinMap;
    std::map<std::string, ViewProvider*> _ViewProviderMapAnnotation;
    std::list<ViewProviderDocumentObject*> _redoViewProviders;

    using Connection = fastsignals::connection;
    using AdvancedConnection = fastsignals::advanced_connection;
    Connection connectNewObject;
    Connection connectDelObject;
    Connection connectCngObject;
    Connection connectRenObject;
    AdvancedConnection connectActObject;
    Connection connectSaveDocument;
    Connection connectRestDocument;
    Connection connectStartLoadDocument;
    Connection connectFinishLoadDocument;
    Connection connectShowHidden;
    Connection connectFinishRestoreDocument;
    Connection connectFinishRestoreObject;
    Connection connectExportObjects;
    Connection connectImportObjects;
    Connection connectFinishImportObjects;
    Connection connectUndoDocument;
    Connection connectRedoDocument;
    Connection connectRecomputed;
    Connection connectSkipRecompute;
    Connection connectTransactionAppend;
    Connection connectTransactionRemove;
    Connection connectTouchedObject;
    Connection connectOpenTransaction;  // FreeCAD-CH (ops#640): the sketch session's ids
    std::size_t nameRefSource = 0;  // Data::NameRefCollector::addSource()'s key
    Connection connectChangePropertyEditor;
    AdvancedConnection connectChangeDocument;

    using ConnectionBlock = fastsignals::shared_connection_block;
    ConnectionBlock connectActObjectBlocker;
    ConnectionBlock connectChangeDocumentBlocker;

    static ViewProviderDocumentObject* throwIfCastFails(ViewProvider* p)
    {
        if (auto vp = freecad_cast<ViewProviderDocumentObject*>(p)) {
            return vp;
        }

        throw Base::RuntimeError("cannot edit non ViewProviderDocumentObject");
    }

    static App::DocumentObject* tryGetObject(ViewProviderDocumentObject* vp)
    {
        auto obj = vp->getObject();
        if (!obj->isAttachedToDocument()) {
            throw Base::RuntimeError("cannot edit detached object");
        }

        return obj;
    }

    // FreeCAD-CH (ops#640, regen-plan item 7): the sketch session's step (_stepGroupOf)

    /// Whether the edit that just started is a session: a sketch's own edit
    bool editIsSession() const
    {
        const Base::Type sketch = Base::Type::fromName("SketcherGui::ViewProviderSketch");
        return _editViewProvider && !_editHoldsStep && !sketch.isBad()
            && _editViewProvider->isDerivedFrom(sketch) && _editMode == ViewProvider::Default;
    }

    void beginSession()
    {
        endSession();
        _session = ++_stepGroupCount;
        _sessionIds.clear();
        _sessionForeignIds.clear();
        // the transaction that made the sketch, still open or booked when the edit starts
        // (SketchWorkflow, Sketcher_NewSketch): the session's step takes it along, so that one
        // Ctrl+Z after the close removes the new sketch. A re-edit's opener, if any, holds only
        // what the edit changed.
        _sessionOpener = _pcDocument->hasPendingTransaction()
            ? _pcDocument->getTransactionID(true, 0)
            : _pcDocument->getBookedTransactionID();
        if (_sessionOpener != 0) {
            _stepGroupOf[_sessionOpener] = _session;
        }
        auto vpd = freecad_cast<ViewProviderDocumentObject*>(_editViewProvider);
        _sessionLabel = vpd && vpd->getObject() ? vpd->getObject()->Label.getValue() : "";
    }

    void endSession()
    {
        if (_session == 0) {
            return;
        }
        // The step's name: the opener's ("New Sketch") when it is on the stack, else the edit's
        std::string name;
        if (_sessionOpener != 0) {
            const auto names = _pcDocument->getAvailableUndoNames();
            for (std::size_t pos = 0; pos < names.size(); ++pos) {
                if (_pcDocument->getTransactionID(true, static_cast<unsigned>(pos))
                    == _sessionOpener) {
                    name = names[pos];
                    break;
                }
            }
        }
        if (name.empty()) {
            name = QObject::tr("Edit %1").arg(QString::fromStdString(_sessionLabel)).toStdString();
        }
        _stepGroupName[_session] = name;
        _session = 0;
        _sessionOpener = 0;
        _sessionIds.clear();
        _sessionForeignIds.clear();
    }

    /// A transaction opened in the document: one of the open session's
    void slotOpenTransaction(const App::Document& doc)
    {
        if (_session == 0) {
            return;
        }
        const int id = doc.getTransactionID(true, 0);
        if (id != 0 && id != _sessionOpener) {
            _stepGroupOf[id] = _session;
            _sessionIds.insert(id);
        }
    }

    /** App's undo limit for the commit of the transaction just opened (pending: App's position
     * 0): the newest _undoSteps steps stay whole, counted as the grouped steps they are once
     * the session closes (the open session's transactions as one). The pending transaction
     * either joins the newest step (a stroke of the open session) or starts one. App's trim
     * (_commitTransaction) pops from the oldest end, so what it pops is whole steps. With no
     * session ever grouped here, the user's limit stands, as set at the document's start. */
    void updateUndoLimit()
    {
        if (_stepGroupOf.empty()) {
            return;
        }
        if (_undoSteps == 0) {
            _pcDocument->setMaxUndoStackSize(0);
            return;
        }
        const int group = groupOf(_pcDocument->getTransactionID(true, 0));
        const bool joins = group != 0 && group == groupOf(_pcDocument->getTransactionID(true, 1));
        const unsigned steps = joins ? _undoSteps : _undoSteps - 1;
        unsigned pos = 1;
        for (unsigned i = 0; i < steps; ++i) {
            const int size = groupSize(true, pos);
            if (size == 0) {
                break;
            }
            pos += static_cast<unsigned>(size);
        }
        // pos - 1 transactions kept on the stack, and the pending one
        _pcDocument->setMaxUndoStackSize(pos);
    }

    int groupOf(int id) const
    {
        auto it = _stepGroupOf.find(id);
        return it == _stepGroupOf.end() ? 0 : it->second;
    }

    /// The number of App transactions from App's position pos with the group of the one there:
    /// one when it has none
    int groupSize(bool undo, unsigned pos) const
    {
        const int id = _pcDocument->getTransactionID(undo, pos);
        if (id == 0) {
            return 0;
        }
        const int group = groupOf(id);
        if (group == 0) {
            return 1;
        }
        int size = 1;
        while (groupOf(_pcDocument->getTransactionID(undo, pos + size)) == group) {
            ++size;
        }
        return size;
    }

    /// The number of App transactions, from App's position pos (getTransactionID()), that make
    /// one step: one, or a closed session's
    int stepSize(bool undo, unsigned pos) const
    {
        const int id = _pcDocument->getTransactionID(undo, pos);
        if (id == 0) {
            return 0;
        }
        const int group = groupOf(id);
        if (group == 0 || group == _session) {
            return 1;
        }
        return groupSize(undo, pos);
    }

    /// Whether the transaction at App's position pos is a step here: inside an open session,
    /// only the session's own transactions are (its start is the floor, hands-on R14)
    bool isStep(bool undo, unsigned pos) const
    {
        const int id = _pcDocument->getTransactionID(undo, pos);
        return id != 0 && (_session == 0 || _sessionIds.contains(id));
    }

    /// The number of App transactions that `steps` steps undo or redo
    int transactionsOfSteps(bool undo, int steps) const
    {
        unsigned pos = 0;
        for (int i = 0; i < steps && isStep(undo, pos); ++i) {
            pos += static_cast<unsigned>(stepSize(undo, pos));
        }
        return static_cast<int>(pos);
    }

    /// The undo or redo list, one name per step
    std::vector<std::string> stepNames(bool undo) const
    {
        const auto names = undo ? _pcDocument->getAvailableUndoNames()
                                : _pcDocument->getAvailableRedoNames();
        std::vector<std::string> steps;
        unsigned pos = 0;
        while (pos < names.size() && isStep(undo, pos)) {
            const int group = groupOf(_pcDocument->getTransactionID(undo, pos));
            auto named = _stepGroupName.find(group);
            steps.push_back(
                group != 0 && group != _session && named != _stepGroupName.end() ? named->second
                                                                                  : names[pos]
            );
            pos += static_cast<unsigned>(std::max(1, stepSize(undo, pos)));
        }
        return steps;
    }

    void throwIfNotInMap(App::DocumentObject* obj, App::Document* doc) const
    {
        if (_ViewProviderMap.find(obj) == _ViewProviderMap.end()) {
            // We can actually support editing external object, by calling
            // View3DInventViewer::setupEditingRoot() before exiting from
            // ViewProvider::setEditViewer(), which transfer all child node of the view
            // provider into an editing node inside the viewer of this document. And
            // that's may actually be the case, as the subname referenced sub object
            // is allowed to be in other documents.
            //
            // We just disabling editing external parent object here, for bug
            // tracking purpose. Because, bringing an unrelated external object to
            // the current view for editing will confuse user, and is certainly a
            // bug. By right, the top parent object should always belong to the
            // editing document, and the actually editing sub object can be
            // external.
            //
            // So, you can either call setEdit() with subname set to 0, which cause
            // the code above to auto detect selection context, and dispatch the
            // editing call to the correct document. Or, supply subname yourself,
            // and make sure you get the document right.
            //
            std::stringstream str;
            str << "cannot edit object '" << obj->getNameInDocument() << "': not found in document "
                << "'" << doc->getName() << "'";
            throw Base::RuntimeError(str.str());
        }
    }

    App::DocumentObject* tryGetSubObject(App::DocumentObject* obj, const char* subname)
    {
        _editingTransform = Base::Matrix4D();
        auto sobj = obj->getSubObject(subname, nullptr, &_editingTransform);
        if (!sobj || !sobj->isAttachedToDocument()) {
            std::stringstream str;
            str << "Invalid sub object '" << obj->getFullName() << '.' << (subname ? subname : "")
                << "'";
            throw Base::RuntimeError(str.str());
        }

        return sobj;
    }

    ViewProviderDocumentObject* tryGetSubViewProvider(
        ViewProviderDocumentObject* vp,
        App::DocumentObject* obj,
        App::DocumentObject* sobj
    ) const
    {
        auto svp = vp;
        if (sobj != obj) {
            svp = freecad_cast<ViewProviderDocumentObject*>(
                Application::Instance->getViewProvider(sobj)
            );
            if (!svp) {
                std::stringstream str;
                str << "Cannot edit '" << sobj->getFullName() << "' without view provider";
                throw Base::RuntimeError(str.str());
            }
        }

        return svp;
    }

    void setParentViewProvider(ViewProviderDocumentObject* vp)
    {
        _editViewProviderParent = vp;
    }

    void clearSubElement()
    {
        _editSubElement.clear();
        _editSubname.clear();
    }

    void findElementName(const char* subname)
    {
        if (subname) {
            const char* element = Data::findElementName(subname);
            if (element) {
                _editSubname = std::string(subname, element - subname);
                _editSubElement = element;
            }
            else {
                _editSubname = subname;
            }
        }
    }

    void findSubObjectList(App::DocumentObject* obj, const char* subname)
    {
        auto sobjs = obj->getSubObjectList(subname);
        _editObjs.clear();
        _editObjs.insert(sobjs.begin(), sobjs.end());
    }

    void resetFailedEditing()
    {
        _editViewProvider = nullptr;
        _editViewProviderParent = nullptr;
        _editObjs.clear();
        _editingObject = nullptr;
    }

    bool tryStartEditing(
        ViewProviderDocumentObject* vp,
        App::DocumentObject* obj,
        const char* subname,
        int ModNum
    )
    {
        auto sobj = tryGetSubObject(obj, subname);
        auto svp = tryGetSubViewProvider(vp, obj, sobj);

        setParentViewProvider(vp);
        clearSubElement();
        findElementName(subname);
        findSubObjectList(obj, subname);
        return tryStartEditing(svp, sobj, ModNum);
    }

    bool tryStartEditing(ViewProviderDocumentObject* svp, App::DocumentObject* sobj, int ModNum)
    {
        try {
            return startEditing(svp, sobj, ModNum);
        }
        catch (const Base::Exception& e) {
            resetFailedEditing();
            FC_ERR("startEditing:" << e.what());
            return false;
        }
        catch (const std::exception& e) {
            resetFailedEditing();
            FC_ERR("startEditing:" << e.what());
            return false;
        }
        catch (...) {
            resetFailedEditing();
            FC_ERR("startEditing: Unknown C++ exception");
            return false;
        }
    }

    bool startEditing(ViewProviderDocumentObject* svp, App::DocumentObject* sobj, int ModNum)
    {
        _editingObject = sobj;
        _editMode = ModNum;
        _editViewProvider = svp;  // Used to resolve start editing (find the document in edit from
                                  // within the viewprovider)
        _editViewProvider = svp->startEditing(ModNum);
        if (!_editViewProvider) {
            resetFailedEditing();
            FC_LOG("object '" << sobj->getFullName() << "' refuse to edit");
            return false;
        }

        return true;
    }

    void setEditingViewerIfPossible(View3DInventor* view3d, int ModNum)
    {
        if (view3d) {
            view3d->getViewer()->setEditingViewProvider(_editViewProvider, ModNum);
            _editingViewer = view3d->getViewer();
        }
    }

    void signalEditMode()
    {
        if (auto vpd = freecad_cast<ViewProviderDocumentObject*>(_editViewProvider)) {
            vpd->getDocument()->signalInEdit(*vpd);
        }
    }

    void setDocumentNameOfTaskDialog(App::Document* doc)
    {
        Gui::TaskView::TaskDialog* dlg = Gui::Control().activeDialog(_pcDocument);
        if (dlg) {
            dlg->setDocumentName(doc->getName());
        }
    }
};

class ParentFinder
{
public:
    ParentFinder(App::DocumentObject* obj, ViewProviderDocumentObject* vp, const std::string& subname)
        : obj {obj}
        , vp {vp}
        , subname {subname}
    {}

    App::DocumentObject* getObject() const
    {
        return obj;
    }

    ViewProviderDocumentObject* getViewProvider() const
    {
        return vp;
    }

    std::string getSubname() const
    {
        return subname;
    }

    bool findParent()
    {
        auto result = findParentAndSubName(obj);
        App::DocumentObject* parentObj = std::get<0>(result);

        if (parentObj) {
            subname = std::get<1>(result);
            obj = parentObj;
            vp = findParentObject(parentObj, subname.c_str());
            return true;
        }

        return false;
    }

private:
    static std::tuple<App::DocumentObject*, std::string> findParentAndSubName(App::DocumentObject* obj)
    {
        // No subname reference is given, we try to extract one from the current
        // selection in order to obtain the correct transformation matrix below
        auto sels = Gui::Selection().getCompleteSelection(ResolveMode::NoResolve);
        App::DocumentObject* parentObj = nullptr;
        std::string _subname;
        for (auto& sel : sels) {
            if (!sel.pObject || !sel.pObject->isAttachedToDocument()) {
                continue;
            }
            if (!parentObj) {
                parentObj = sel.pObject;
            }
            else if (parentObj != sel.pObject) {
                FC_LOG("Cannot deduce subname for editing, more than one parent?");
                parentObj = nullptr;
                break;
            }

            auto sobj = parentObj->getSubObject(sel.SubName);
            if (!sobj || (sobj != obj && sobj->getLinkedObject(true) != obj)) {
                FC_LOG("Cannot deduce subname for editing, subname mismatch");
                parentObj = nullptr;
                break;
            }

            _subname = sel.SubName;
        }

        return std::make_tuple(parentObj, _subname);
    }

    static Gui::ViewProviderDocumentObject* findParentObject(
        App::DocumentObject* parentObj,
        const char* subname
    )
    {
        FC_LOG("deduced editing reference " << parentObj->getFullName() << '.' << subname);
        auto vp = freecad_cast<ViewProviderDocumentObject*>(
            Application::Instance->getViewProvider(parentObj)
        );
        if (!vp || !vp->getDocument()) {
            throw Base::RuntimeError("invalid view provider for parent object");
        }

        return vp;
    }

private:
    App::DocumentObject* obj;
    ViewProviderDocumentObject* vp;
    std::string subname;
};

namespace
{
/// FreeCAD-CH (ops#640): each Gui document's pimpl, for hasUndoStep() (no header names it)
std::map<const Document*, DocumentP*> stepDocuments;  // NOLINT
}  // namespace

}  // namespace Gui

/* TRANSLATOR Gui::Document */

/// @namespace Gui @class Document

int Document::_iDocCount = 0;

Document::Document(App::Document* pcDocument, Application* app)
{
    d = new DocumentP;
    stepDocuments[this] = d;  // FreeCAD-CH (ops#640)
    d->_iWinCount = 1;
    // new instance
    d->_iDocId = (++_iDocCount);
    d->_isClosing = false;
    d->_isModified = false;
    d->_isTransacting = false;
    d->_isActive = false;
    d->_restoredGuiDocument = false;
    d->_pcAppWnd = app;
    d->_pcDocument = pcDocument;
    d->_editViewProvider = nullptr;
    d->_editViewProviderPrevious = nullptr;
    d->_editingObject = nullptr;
    d->_editViewProviderParent = nullptr;
    d->_editingViewer = nullptr;
    d->_editMode = 0;
    d->_editModePrevious = 0;
    d->_editWantsRestore = false;
    d->_editWantsRestorePrevious = false;

    // NOLINTBEGIN
    //  Setup the connections
    d->connectNewObject = pcDocument->signalNewObject.connect(
        std::bind(&Gui::Document::slotNewObject, this, sp::_1)
    );
    d->connectDelObject = pcDocument->signalDeletedObject.connect(
        std::bind(&Gui::Document::slotDeletedObject, this, sp::_1)
    );
    d->connectCngObject = pcDocument->signalChangedObject.connect(
        std::bind(&Gui::Document::slotChangedObject, this, sp::_1, sp::_2)
    );
    d->connectRenObject = pcDocument->signalRelabelObject.connect(
        std::bind(&Gui::Document::slotRelabelObject, this, sp::_1)
    );
    d->connectActObject = pcDocument->signalActivatedObject.connect(
        std::bind(&Gui::Document::slotActivatedObject, this, sp::_1),
        fastsignals::advanced_tag()
    );
    d->connectActObjectBlocker = fastsignals::shared_connection_block(d->connectActObject, false);
    d->connectSaveDocument = pcDocument->signalSaveDocument.connect(
        std::bind(&Gui::Document::Save, this, sp::_1)
    );
    d->connectRestDocument = pcDocument->signalRestoreDocument.connect(
        std::bind(&Gui::Document::Restore, this, sp::_1)
    );
    d->connectStartLoadDocument = App::GetApplication().signalStartRestoreDocument.connect(
        std::bind(&Gui::Document::slotStartRestoreDocument, this, sp::_1)
    );
    d->connectFinishLoadDocument = App::GetApplication().signalFinishRestoreDocument.connect(
        std::bind(&Gui::Document::slotFinishRestoreDocument, this, sp::_1)
    );
    d->connectShowHidden = App::GetApplication().signalShowHidden.connect(
        std::bind(&Gui::Document::slotShowHidden, this, sp::_1)
    );

    d->connectChangePropertyEditor = pcDocument->signalChangePropertyEditor.connect(
        std::bind(&Gui::Document::slotChangePropertyEditor, this, sp::_1, sp::_2)
    );
    d->connectChangeDocument
        = d->_pcDocument->signalChanged.connect  // use the same slot function
          (std::bind(&Gui::Document::slotChangePropertyEditor, this, sp::_1, sp::_2),
           fastsignals::advanced_tag());
    d->connectChangeDocumentBlocker
        = fastsignals::shared_connection_block(d->connectChangeDocument, true);
    d->connectFinishRestoreObject = pcDocument->signalFinishRestoreObject.connect(
        std::bind(&Gui::Document::slotFinishRestoreObject, this, sp::_1)
    );
    d->connectExportObjects = pcDocument->signalExportViewObjects.connect(
        std::bind(&Gui::Document::exportObjects, this, sp::_1, sp::_2)
    );
    d->connectImportObjects = pcDocument->signalImportViewObjects.connect(
        std::bind(&Gui::Document::importObjects, this, sp::_1, sp::_2, sp::_3)
    );
    d->connectFinishImportObjects = pcDocument->signalFinishImportObjects.connect(
        std::bind(&Gui::Document::slotFinishImportObjects, this, sp::_1)
    );

    d->connectUndoDocument = pcDocument->signalUndo.connect(
        std::bind(&Gui::Document::slotUndoDocument, this, sp::_1)
    );
    d->connectRedoDocument = pcDocument->signalRedo.connect(
        std::bind(&Gui::Document::slotRedoDocument, this, sp::_1)
    );
    d->connectRecomputed = pcDocument->signalRecomputed.connect(
        std::bind(&Gui::Document::slotRecomputed, this, sp::_1)
    );
    d->connectSkipRecompute = pcDocument->signalSkipRecompute.connect(
        std::bind(&Gui::Document::slotSkipRecompute, this, sp::_1, sp::_2)
    );
    d->connectTouchedObject = pcDocument->signalTouchedObject.connect(
        std::bind(&Gui::Document::slotTouchedObject, this, sp::_1)
    );

    d->connectTransactionAppend = pcDocument->signalTransactionAppend.connect(
        std::bind(&Gui::Document::slotTransactionAppend, this, sp::_1, sp::_2)
    );
    d->connectTransactionRemove = pcDocument->signalTransactionRemove.connect(
        std::bind(&Gui::Document::slotTransactionRemove, this, sp::_1, sp::_2)
    );
    d->connectOpenTransaction = pcDocument->signalOpenTransaction.connect(
        [this](const App::Document& doc, const std::string&) {
            d->slotOpenTransaction(doc);
            d->updateUndoLimit();
        }
    );
    // NOLINTEND

    // A view provider's Python state may hold interned names (an add-on's subname), and
    // GuiDocument.xml is written after Document.xml has its name table: a save or an export of
    // this document's objects gets the states before it decides the table, as
    // PropertyPythonObject::Save() gives them in Document.xml (ops#97)
    d->nameRefSource = Data::NameRefCollector::addSource(
        [this](const App::DocumentObject& obj, Data::NameRefCollector& collector) {
            if (obj.getDocument() != getDocument()) {
                return;
            }
            auto vp = getViewProvider(&obj);
            if (!vp) {
                return;
            }
            std::vector<App::Property*> props;
            vp->getPropertyList(props);
            for (auto prop : props) {
                // what PropertyContainer::Save() writes
                auto python = freecad_cast<App::PropertyPythonObject*>(prop);
                if (!python || prop->testStatus(App::Property::PropNoPersist)
                    || (!prop->testStatus(App::Property::PropDynamic)
                        && (prop->testStatus(App::Property::Transient)
                            || (vp->getPropertyType(prop) & App::Prop_Transient) != 0))) {
                    continue;
                }
                collector.add(python->toString());
            }
        }
    );

    // pointer to the python class
    // NOTE: As this Python object doesn't get returned to the interpreter we
    // mustn't increment it (Werner Jan-12-2006)
    Base::PyGILStateLocker lock;
    _pcDocPy = new Gui::DocumentPy(this);

    ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Document"
    );

    // FreeCAD-CH (ops#640): kept as a number of steps (DocumentP::updateUndoLimit)
    d->_undoSteps = static_cast<unsigned>(std::max<long>(0, hGrp->GetInt("MaxUndoSize", 20)));
    d->_pcDocument->setMaxUndoStackSize(d->_undoSteps);
    // FreeCAD-CH (ops#640, regen-design section 1): a document shown in the GUI regenerates on the
    // close of each transaction and after undo/redo, as Onshape regenerates the Part Studio after
    // every action; FreeCADCmd documents keep their explicit recompute()s (the flag is off in App)
    d->_pcDocument->setRegenerateOnCommit(true);
    d->_changeViewTouchDocument = hGrp->GetBool("ChangeViewProviderTouchDocument", true);
}

Document::~Document()
{
    stepDocuments.erase(this);  // FreeCAD-CH (ops#640)
    NamedViews::forget(this);   // FreeCAD-CH (ops#640)
    // disconnect everything to avoid to be double-deleted
    // in case an exception is raised somewhere
    Data::NameRefCollector::removeSource(d->nameRefSource);
    d->connectNewObject.disconnect();
    d->connectDelObject.disconnect();
    d->connectCngObject.disconnect();
    d->connectRenObject.disconnect();
    d->connectActObject.disconnect();
    d->connectSaveDocument.disconnect();
    d->connectRestDocument.disconnect();
    d->connectStartLoadDocument.disconnect();
    d->connectFinishLoadDocument.disconnect();
    d->connectShowHidden.disconnect();
    d->connectFinishRestoreObject.disconnect();
    d->connectExportObjects.disconnect();
    d->connectImportObjects.disconnect();
    d->connectFinishImportObjects.disconnect();
    d->connectUndoDocument.disconnect();
    d->connectRedoDocument.disconnect();
    d->connectRecomputed.disconnect();
    d->connectSkipRecompute.disconnect();
    d->connectTransactionAppend.disconnect();
    d->connectTransactionRemove.disconnect();
    d->connectTouchedObject.disconnect();
    d->connectOpenTransaction.disconnect();
    d->connectChangePropertyEditor.disconnect();
    d->connectChangeDocument.disconnect();

    // e.g. if document gets closed from within a Python command
    d->_isClosing = true;
    // calls Document::detachView() and alter the view list
    std::list<Gui::BaseView*> temp = d->baseViews;
    for (auto& it : temp) {
        it->deleteSelf();
    }

    for (const auto& vp : d->_ViewProviderMap) {
        delete vp.second;
    }

    for (const auto& va : d->_ViewProviderMapAnnotation) {
        delete va.second;
    }

    // remove the reference from the object
    Base::PyGILStateLocker lock;
    _pcDocPy->setInvalid();
    _pcDocPy->DecRef();
    delete d;
}

//*****************************************************************************************************
// 3D viewer handling
//*****************************************************************************************************

bool Document::setEdit(Gui::ViewProvider* p, int ModNum, const char* subname)
{
    try {
        return trySetEdit(p, ModNum, subname);
    }
    catch (const Base::Exception& e) {
        FC_ERR("setEdit:" << e.what());
        return false;
    }
    catch (const std::exception& e) {
        FC_ERR("setEdit:" << e.what());
        return false;
    }
    catch (...) {
        FC_ERR("setEdit: Unknown C++ exception");
        return false;
    }
}

void Document::resetIfEditing()
{
    // Fix regression: https://forum.freecad.org/viewtopic.php?f=19&t=43629&p=371972#p371972
    // When an object is already in edit mode a subsequent call for editing is only possible
    // when resetting the currently edited object.
    if (d->_editViewProvider) {
        _resetEdit();
    }
}

View3DInventor* Document::openEditingView3D(const ViewProviderDocumentObject* vp)
{
    auto view3d = dynamic_cast<View3DInventor*>(getActiveView());
    // if the currently active view is not the 3d view search for it and activate it
    if (view3d) {
        getMainWindow()->setActiveWindow(view3d);
    }
    else {
        view3d = dynamic_cast<View3DInventor*>(setActiveView(vp));
    }

    return view3d;
}

View3DInventor* Document::openEditingView3D(const App::DocumentObject* obj)
{
    if (auto vp
        = freecad_cast<ViewProviderDocumentObject*>(Application::Instance->getViewProvider(obj))) {
        return openEditingView3D(vp);
    }

    return nullptr;
}

namespace
{
bool bookEditStep(
    Gui::Document* gdoc,
    App::DocumentObject* obj,
    const std::string& subname,
    int ModNum
)
{
    // FreeCAD-CH (ops#640): an edit opened with no transaction (Gui.ActiveDocument.setEdit from a
    // script or macro; the tree's double-click, Std_Edit and the feature commands open one first)
    // gets its step here, before its dialog opens, named as the double-click names it, so that
    // the dialog's changes from its start (the sketches it shows) are in it, as from the
    // double-click: under the lock the panels' own fallback, "Edit X" opened at their first
    // change when none is booked (setupTransaction), is refused, and the dialog's changes were
    // recorded nowhere (its Cancel restored nothing, its OK left no step). An unchanged accept
    // still leaves none (the commit's no-op rule).
    App::Document* doc = gdoc->getDocument();
    if (!obj || doc->getBookedTransactionID() != App::NullTransaction
        || doc->hasPendingTransaction() || doc->isTransactionLocked() || doc->transacting()) {
        return false;
    }
    App::DocumentObject* target = subname.empty() ? obj : obj->getSubObject(subname.c_str());
    auto vp = target ? freecad_cast<Gui::ViewProviderDocumentObject*>(
                           Gui::Application::Instance->getViewProvider(target)
                       )
                     : nullptr;
    if (!vp || vp->getDocument() != gdoc || !vp->editHoldsOneStep(ModNum)) {
        return false;
    }
    const QString text = QObject::tr("Edit %1").arg(QString::fromUtf8(target->Label.getValue()));
    return doc->openTransaction(text.toUtf8().constData()) != App::NullTransaction;
}
}  // namespace

bool Document::trySetEdit(Gui::ViewProvider* p, int ModNum, const char* subname)
{
    auto vp = DocumentP::throwIfCastFails(p);

    // FreeCAD-CH (ops#640): another edit beside the held step accepts the open dialog first;
    // resetIfEditing() below would otherwise commit the dialog's step without its accept()'s
    // validation and start the next edit with no transaction (its openCommand was refused)
    if (d->_editHoldsStep && !acceptOpenStep()) {
        return false;
    }

    auto obj = DocumentP::tryGetObject(vp);

    std::string _subname = subname ? subname : "";
    if (_subname.empty()) {
        ParentFinder finder(obj, vp, _subname);
        if (finder.findParent()) {
            _subname = finder.getSubname();
            obj = finder.getObject();
            vp = finder.getViewProvider();
            if (vp->getDocument() != this) {
                resetIfEditing();

                return vp->getDocument()->setEdit(vp, ModNum, _subname.c_str());
            }
        }
    }

    // Fix for #13852: When switching edit directly between sketches, resetIfEditing()
    // triggers unsetEdit() on the previous sketch which restores its selection.
    // This clobbers the selection of the new sketch that ParentFinder relies on.
    // Moving resetIfEditing() after ParentFinder ensures we resolve the parent context correctly
    // using the current selection before closing the previous edit.
    resetIfEditing();

    // FreeCAD-CH (ops#640, rank 59; R6T-3, R6T-11): an object of another typed tab is edited in
    // its tab's view, switched to only now (the held step's dialog accepted, so its step stays
    // its own tab's) and by the edited path's top object (a sketch edited through an assembly's
    // link stays in the assembly); refused beside another open dialog
    if (!DocumentTabs::beforeEdit(this, vp)) {
        return false;
    }

    d->throwIfNotInMap(obj, getDocument());

    // FreeCAD-CH (ops#640): an edit that holds its step, opened with no transaction, books it
    // before the dialog opens (bookEditStep)
    const bool bookedHere = bookEditStep(this, obj, _subname, ModNum);
    // FreeCAD-CH (ops#640): whether the edit's step holds nothing yet (editStartedUnchanged())
    d->_editStartedUnchanged = !getDocument()->hasPendingTransaction();

    Application::Instance->setEditDocument(this);

    if (!d->tryStartEditing(vp, obj, _subname.c_str(), ModNum)) {
        if (bookedHere) {
            getDocument()->abortTransaction();
        }
        d->setDocumentNameOfTaskDialog(getDocument());
        return false;
    }

    d->setDocumentNameOfTaskDialog(getDocument());

    // FreeCAD-CH (ops#640, regen-design section 3): after the edit started (its "Edit X" or
    // "Make X" transaction was opened before), the open dialog's step is locked until the edit
    // resets: no undo, redo, implicit commit or other transaction behind the dialog
    holdEditStep(ModNum);
    // FreeCAD-CH (ops#640, regen-plan item 7): a sketch's edit is a session, one undo step
    if (d->editIsSession()) {
        d->beginSession();
    }
    // FreeCAD-CH (ops#640): and no document regenerates on commit until the edit ends
    updateRegenerationHold();

    auto view3d = openEditingView3D(vp);
    d->setEditingViewerIfPossible(view3d, ModNum);
    d->signalEditMode();

    return true;
}

const Base::Matrix4D& Document::getEditingTransform() const
{
    return d->_editingTransform;
}

void Document::setEditingTransform(const Base::Matrix4D& mat)
{
    d->_editObjs.clear();
    d->_editingTransform = mat;
    auto activeView = dynamic_cast<View3DInventor*>(getActiveView());
    if (activeView) {
        activeView->getViewer()->setEditingTransform(mat);
    }
}

void Document::resetEdit()
{
    bool vpIsNotNull = d->_editViewProvider != nullptr;
    bool vpHasChanged = d->_editViewProvider != d->_editViewProviderPrevious;
    int modeToRestore = d->_editModePrevious;
    Gui::ViewProvider* vpToRestore = d->_editViewProviderPrevious;
    bool shouldRestorePrevious = d->_editWantsRestorePrevious;

    Application::Instance->unsetEditDocument(this);

    if (vpIsNotNull && vpHasChanged && shouldRestorePrevious) {
        setEdit(vpToRestore, modeToRestore);
    }
}

void Document::holdEditStep(int ModNum)
{
    if (d->_editHoldsStep || !d->_editViewProvider
        || !d->_editViewProvider->editHoldsOneStep(ModNum)) {
        return;
    }
    // FreeCAD-CH (ops#640): the edit whose step bookEditStep couldn't book before it started
    // (its target found only by the edit itself) books it now, from its first change on
    App::Document* doc = getDocument();
    auto vpd = freecad_cast<ViewProviderDocumentObject*>(d->_editViewProvider);
    if (vpd && vpd->getObject() && doc->getBookedTransactionID() == App::NullTransaction
        && !doc->hasPendingTransaction() && !doc->isTransactionLocked() && !doc->transacting()) {
        const QString text = QObject::tr("Edit %1").arg(
            QString::fromUtf8(vpd->getObject()->Label.getValue())
        );
        doc->openTransaction(text.toUtf8().constData());
    }
    doc->lockStep();
    d->_editHoldsStep = true;
}

void Document::releaseEditStep()
{
    if (!d->_editHoldsStep) {
        return;
    }
    d->_editHoldsStep = false;
    getDocument()->unlockStep();
}

bool Document::dialogClosingStep() const
{
    TaskView::TaskDialog* dlg = Gui::Control().activeDialog(getDocument());
    return dlg && dlg->property("taskview_accept_or_reject").isValid();
}

bool Document::acceptOpenStep()
{
    App::Document* doc = getDocument();
    if (!doc->isStepLocked()) {
        return true;
    }
    bool inOwnClose = d->_acceptingStep || dialogClosingStep();
    if (d->_editHoldsStep && !inOwnClose && Gui::Control().activeDialog(doc)) {
        Base::FlagToggler<> accepting(d->_acceptingStep);
        // the dialog's OK commits its step and resets the edit (releaseEditStep); a failed
        // accept shows the dialog's own message and leaves both
        Gui::Control().accept(doc);
    }
    if (!doc->isStepLocked()) {
        return true;
    }
    if (!inOwnClose) {
        getMainWindow()->showMessage(
            QObject::tr("The open dialog could not be accepted: finish or cancel it first"),
            5000
        );
    }
    return false;
}

void Document::_resetEdit()
{
    // FreeCAD-CH (ops#640): the step lock goes first, before the commit below and before
    // finishEditing() (whose unsetEdit may recompute); the step lock never refuses the explicit
    // commit or abort of the dialog itself, and restartEdit's TransactionLocker still makes the
    // commit below a no-op
    // FreeCAD-CH (ops#640): a dialog that held its step commits it below and regenerates, even
    // while another document holds the regeneration (updateRegenerationHold)
    const bool heldStep = d->_editHoldsStep;
    releaseEditStep();

    if (d->_editViewProvider) {
        for (auto* v : d->baseViews) {
            auto activeView = dynamic_cast<View3DInventor*>(v);
            if (activeView) {
                activeView->getViewer()->resetEditingViewProvider();
            }
        }

        d->_editViewProvider->finishEditing();

        d->_editViewProviderPrevious = d->_editViewProvider;
        d->_editModePrevious = d->_editMode;
        d->_editWantsRestorePrevious = d->_editWantsRestore;
        d->_editWantsRestore = false;

        // Have to check d->_editViewProvider below, because there is a chance
        // the editing object gets deleted inside the above call to
        // 'finishEditing()', which will trigger our slotDeletedObject(), which
        // nullifies _editViewProvider.
        if (d->_editViewProvider
            && d->_editViewProvider->isDerivedFrom<ViewProviderDocumentObject>()) {
            auto vpd = static_cast<ViewProviderDocumentObject*>(d->_editViewProvider);
            vpd->getDocument()->signalResetEdit(*vpd);
        }
        d->_editViewProvider = nullptr;
        // FreeCAD-CH (ops#640): the hold on regeneration ends before the edit's own commit
        // below, so the dialog's OK regenerates: a feature dialog's always, a sketch's unless
        // another document is in a sketch's edit (then at that edit's end)
        updateRegenerationHold(heldStep ? getDocument() : nullptr);

        // The logic below is not necessary anymore, because this method is
        // changed into a private one,  _resetEdit(). And the exposed
        // resetEdit() above calls into Application->unsetEditDocument() which
        // will prevent recursive calling.

        App::GetApplication().commitTransaction(getDocument()->getBookedTransactionID());
    }
    d->_editViewProviderParent = nullptr;
    d->_editingViewer = nullptr;
    d->_editObjs.clear();
    d->_editingObject = nullptr;
    Application::Instance->unsetEditDocument(this);
    updateRegenerationHold();  // FreeCAD-CH (ops#640): as above
    // FreeCAD-CH (ops#640, regen-plan item 7): the sketch session closes after its last commit
    // (the close's "Sketch recompute" or "Cancel sketch editing" and the commit above are in it)
    d->endSession();
}

ViewProvider* Document::getInEdit(
    ViewProviderDocumentObject** parentVp,
    std::string* subname,
    int* mode,
    std::string* subelement
) const
{
    if (parentVp) {
        *parentVp = d->_editViewProviderParent;
    }
    if (subname) {
        *subname = d->_editSubname;
    }
    if (subelement) {
        *subelement = d->_editSubElement;
    }
    if (mode) {
        *mode = d->_editMode;
    }

    if (d->_editViewProvider) {
        // there is only one 3d view which is in edit mode
        auto activeView = dynamic_cast<View3DInventor*>(getActiveView());
        if (activeView && activeView->getViewer()->isEditingViewProvider()) {
            return d->_editViewProvider;
        }
    }

    return nullptr;
}
ViewProvider* Document::getEditViewProvider() const
{
    return d->_editViewProvider;
}

void Document::setInEdit(ViewProviderDocumentObject* parentVp, const char* subname)
{
    if (d->_editViewProvider) {
        d->_editViewProviderParent = parentVp;
        d->_editSubname = subname ? subname : "";
    }
}

void Document::setAnnotationViewProvider(const char* name, ViewProvider* pcProvider)
{
    // already in ?
    std::map<std::string, ViewProvider*>::iterator it = d->_ViewProviderMapAnnotation.find(name);
    if (it != d->_ViewProviderMapAnnotation.end()) {
        removeAnnotationViewProvider(name);
    }

    // add
    d->_ViewProviderMapAnnotation[name] = pcProvider;

    // cycling to all views of the document
    for (auto* v : d->baseViews) {
        auto activeView = dynamic_cast<View3DInventor*>(v);
        if (activeView) {
            activeView->getViewer()->addViewProvider(pcProvider);
        }
    }
}

void Document::setEditRestore(bool askRestore)
{
    d->_editWantsRestore = askRestore;
}

ViewProvider* Document::getAnnotationViewProvider(const char* name) const
{
    std::map<std::string, ViewProvider*>::const_iterator it = d->_ViewProviderMapAnnotation.find(name);
    return ((it != d->_ViewProviderMapAnnotation.end()) ? it->second : 0);
}

bool Document::isAnnotationViewProvider(const ViewProvider* vp) const
{
    for (const auto& va : d->_ViewProviderMapAnnotation) {
        if (va.second == vp) {
            return true;
        }
    }
    return false;
}


ViewProvider* Document::takeAnnotationViewProvider(const char* name)
{
    auto it = d->_ViewProviderMapAnnotation.find(name);
    if (it == d->_ViewProviderMapAnnotation.end()) {
        return nullptr;
    }

    ViewProvider* vp = it->second;
    d->_ViewProviderMapAnnotation.erase(it);

    // cycling to all views of the document
    for (auto vIt : d->baseViews) {
        if (auto activeView = dynamic_cast<View3DInventor*>(vIt)) {
            activeView->getViewer()->removeViewProvider(vp);
        }
    }

    return vp;
}


void Document::removeAnnotationViewProvider(const char* name)
{
    delete takeAnnotationViewProvider(name);
}


ViewProvider* Document::getViewProvider(const App::DocumentObject* Feat) const
{
    std::map<const App::DocumentObject*, ViewProviderDocumentObject*>::const_iterator it
        = d->_ViewProviderMap.find(Feat);
    return ((it != d->_ViewProviderMap.end()) ? it->second : 0);
}

std::vector<ViewProvider*> Document::getViewProvidersOfType(const Base::Type& typeId) const
{
    std::vector<ViewProvider*> Objects;
    for (const auto& vp : d->_ViewProviderMap) {
        if (vp.second->isDerivedFrom(typeId)) {
            Objects.push_back(vp.second);
        }
    }
    return Objects;
}

ViewProvider* Document::getViewProviderByName(const char* name) const
{
    // first check on feature name
    App::DocumentObject* pcFeat = getDocument()->getObject(name);

    if (pcFeat) {
        std::map<const App::DocumentObject*, ViewProviderDocumentObject*>::const_iterator it
            = d->_ViewProviderMap.find(pcFeat);

        if (it != d->_ViewProviderMap.end()) {
            return it->second;
        }
    }
    else {
        // then try annotation name
        std::map<std::string, ViewProvider*>::const_iterator it2
            = d->_ViewProviderMapAnnotation.find(name);

        if (it2 != d->_ViewProviderMapAnnotation.end()) {
            return it2->second;
        }
    }

    return nullptr;
}

bool Document::isShow(const char* name)
{
    ViewProvider* pcProv = getViewProviderByName(name);
    return pcProv ? pcProv->isShow() : false;
}

/// put the feature in show
void Document::setShow(const char* name)
{
    ViewProvider* pcProv = getViewProviderByName(name);

    if (pcProv && pcProv->isDerivedFrom<ViewProviderDocumentObject>()) {
        static_cast<ViewProviderDocumentObject*>(pcProv)->Visibility.setValue(true);
    }
}

/// set the feature in Noshow
void Document::setHide(const char* name)
{
    ViewProvider* pcProv = getViewProviderByName(name);

    if (pcProv && pcProv->isDerivedFrom<ViewProviderDocumentObject>()) {
        static_cast<ViewProviderDocumentObject*>(pcProv)->Visibility.setValue(false);
    }
}

/// set the feature in Noshow
void Document::setPos(const char* name, const Base::Matrix4D& rclMtrx)
{
    ViewProvider* pcProv = getViewProviderByName(name);
    if (pcProv) {
        pcProv->setTransformation(rclMtrx);
    }
}

//*****************************************************************************************************
// Document
//*****************************************************************************************************
void Document::slotNewObject(const App::DocumentObject& Obj)
{
    auto pcProvider = static_cast<ViewProviderDocumentObject*>(getViewProvider(&Obj));
    if (!pcProvider) {
        std::string_view cName {Obj.getViewProviderNameStored()};
        for (;;) {
            if (cName.empty()) {
                // handle document object with no view provider specified
                FC_LOG(Obj.getFullName() << " has no view provider specified");
                return;
            }
            Base::Type type = Base::Type::getTypeIfDerivedFrom(
                cName,
                ViewProviderDocumentObject::getClassTypeId(),
                true
            );
            pcProvider = static_cast<ViewProviderDocumentObject*>(type.createInstance());
            // createInstance could return a null pointer
            if (!pcProvider) {
                // type not derived from ViewProviderDocumentObject!!!
                FC_ERR("Invalid view provider type '" << cName << "' for " << Obj.getFullName());
                return;
            }
            else if (cName != Obj.getViewProviderName() && !pcProvider->allowOverride(Obj)) {
                FC_WARN("View provider type '" << cName << "' does not support " << Obj.getFullName());
                delete pcProvider;
                pcProvider = nullptr;
                cName = Obj.getViewProviderName();
            }
            else {
                break;
            }
        }

        setModified(true);
        d->_ViewProviderMap[&Obj] = pcProvider;
        d->_CoinMap[pcProvider->getRoot()] = pcProvider;
        pcProvider->setStatus(Gui::ViewStatus::TouchDocument, d->_changeViewTouchDocument);

        try {
            // if successfully created set the right name and calculate the view
            // FIXME: Consider to change argument of attach() to const pointer
            pcProvider->attach(const_cast<App::DocumentObject*>(&Obj));
            pcProvider->updateView();
            pcProvider->setActiveMode();
        }
        catch (const Base::MemoryException& e) {
            FC_ERR("Memory exception in " << Obj.getFullName() << " thrown: " << e.what());
        }
        catch (Base::Exception& e) {
            e.reportException();
        }
#ifndef FC_DEBUG
        catch (...) {
            FC_ERR("Unknown exception in Feature " << Obj.getFullName() << " thrown");
        }
#endif
    }
    else {
        try {
            pcProvider->reattach(const_cast<App::DocumentObject*>(&Obj));
        }
        catch (Base::Exception& e) {
            e.reportException();
        }
    }

    if (pcProvider) {
        // cycling to all views of the document
        for (auto* v : d->baseViews) {
            auto activeView = dynamic_cast<View3DInventor*>(v);
            if (activeView) {
                activeView->getViewer()->addViewProvider(pcProvider);
            }
        }

        // adding to the tree
        signalNewObject(*pcProvider);
        pcProvider->pcDocument = this;

        // it is possible that a new viewprovider already claims children
        handleChildren3D(pcProvider);
        if (d->_isTransacting) {
            d->_redoViewProviders.push_back(pcProvider);
        }
    }
}

void Document::slotDeletedObject(const App::DocumentObject& Obj)
{
    setModified(true);

    // cycling to all views of the document
    ViewProvider* viewProvider = getViewProvider(&Obj);
    if (!viewProvider) {
        return;
    }

    if (d->_editViewProvider == viewProvider || d->_editViewProviderParent == viewProvider) {
        _resetEdit();
    }
    else {
        Application::Instance->unsetEditDocumentIf([&viewProvider](Gui::Document* editdoc) {
            return editdoc->d->_editViewProvider == viewProvider
                || editdoc->d->_editViewProviderParent == viewProvider;
        });
    }

    handleChildren3D(viewProvider, true);

    if (viewProvider && viewProvider->isDerivedFrom(ViewProviderDocumentObject::getClassTypeId())) {
        // go through the views
        for (auto* v : d->baseViews) {
            auto activeView = dynamic_cast<View3DInventor*>(v);
            if (activeView) {
                activeView->getViewer()->removeViewProvider(viewProvider);
            }
        }

        // removing from tree
        signalDeletedObject(*(static_cast<ViewProviderDocumentObject*>(viewProvider)));
    }

    viewProvider->beforeDelete();
}

void Document::beforeDelete()
{
    Application::Instance->unsetEditDocumentIf([this](Gui::Document* editDoc) {
        auto vp = freecad_cast<ViewProviderDocumentObject*>(editDoc->d->_editViewProvider);
        auto vpp = freecad_cast<ViewProviderDocumentObject*>(editDoc->d->_editViewProviderParent);

        return editDoc == this || (vp && vp->getDocument() == this)
            || (vpp && vpp->getDocument() == this);
    });
    for (auto& v : d->_ViewProviderMap) {
        v.second->beforeDelete();
    }
}

void Document::slotChangedObject(const App::DocumentObject& Obj, const App::Property& Prop)
{
    // FreeCAD-CH (ops#640): a change of another object in one of the open sketch session's
    // transactions, not a recompute's (_sessionForeignIds)
    if (d->_session != 0 && &Obj != d->_editingObject && d->_pcDocument->hasPendingTransaction()
        && !d->_pcDocument->testStatus(App::Document::Recomputing)) {
        const int id = d->_pcDocument->getTransactionID(true, 0);
        if (d->_sessionIds.contains(id)) {
            d->_sessionForeignIds.insert(id);
        }
    }
    ViewProvider* viewProvider = getViewProvider(&Obj);
    if (viewProvider) {
        try {
            viewProvider->update(&Prop);
            if (d->_editingViewer && d->_editingObject && d->_editViewProviderParent
                && (Prop.isDerivedFrom<App::PropertyPlacement>()
                    // Issue ID 0004230 : getName() can return null in which case strstr() crashes
                    || (Prop.getName() && strstr(Prop.getName(), "Scale")))
                && d->_editObjs.contains(&Obj)) {
                Base::Matrix4D mat;
                auto sobj = d->_editViewProviderParent->getObject()
                                ->getSubObject(d->_editSubname.c_str(), nullptr, &mat);
                if (sobj == d->_editingObject && d->_editingTransform != mat) {
                    d->_editingTransform = mat;
                    d->_editingViewer->setEditingTransform(d->_editingTransform);
                }
            }
        }
        catch (const Base::MemoryException& e) {
            FC_ERR("Memory exception in " << Obj.getFullName() << " thrown: " << e.what());
        }
        catch (Base::Exception& e) {
            e.reportException();
        }
        catch (const std::exception& e) {
            FC_ERR("C++ exception in " << Obj.getFullName() << " thrown " << e.what());
        }
        catch (...) {
            FC_ERR("Cannot update representation for " << Obj.getFullName());
        }

        handleChildren3D(viewProvider);

        if (viewProvider->isDerivedFrom<ViewProviderDocumentObject>()) {
            signalChangedObject(static_cast<ViewProviderDocumentObject&>(*viewProvider), Prop);
        }
    }

    // a property of an object has changed
    if (!Prop.testStatus(App::Property::NoModify) && !isModified()) {
        FC_LOG(Prop.getFullName() << " modified");
        setModified(true);
    }

    getMainWindow()->updateActions(true);
}

void Document::slotRelabelObject(const App::DocumentObject& Obj)
{
    ViewProvider* viewProvider = getViewProvider(&Obj);
    if (viewProvider && viewProvider->isDerivedFrom<ViewProviderDocumentObject>()) {
        signalRelabelObject(*(static_cast<ViewProviderDocumentObject*>(viewProvider)));
    }
}

void Document::slotTransactionAppend(const App::DocumentObject& obj, App::Transaction* transaction)
{
    ViewProvider* viewProvider = getViewProvider(&obj);
    if (viewProvider && viewProvider->isDerivedFrom<ViewProviderDocumentObject>()) {
        transaction->addObjectDel(viewProvider);
    }
}

void Document::slotTransactionRemove(const App::DocumentObject& obj, App::Transaction* transaction)
{
    std::map<const App::DocumentObject*, ViewProviderDocumentObject*>::const_iterator it
        = d->_ViewProviderMap.find(&obj);
    if (it != d->_ViewProviderMap.end()) {
        ViewProvider* viewProvider = it->second;

        auto itC = d->_CoinMap.find(viewProvider->getRoot());
        if (itC != d->_CoinMap.end()) {
            d->_CoinMap.erase(itC);
        }

        d->_ViewProviderMap.erase(&obj);
        // transaction being a nullptr indicates that undo/redo is off and the object
        // can be safely deleted
        if (transaction) {
            transaction->addObjectNew(viewProvider);
        }
        else {
            delete viewProvider;
        }
    }
}

void Document::slotActivatedObject(const App::DocumentObject& Obj)
{
    ViewProvider* viewProvider = getViewProvider(&Obj);
    if (viewProvider && viewProvider->isDerivedFrom<ViewProviderDocumentObject>()) {
        signalActivatedObject(*(static_cast<ViewProviderDocumentObject*>(viewProvider)));
    }
}

void Document::slotUndoDocument(const App::Document& doc)
{
    if (d->_pcDocument != &doc) {
        return;
    }

    signalUndoDocument(*this);
    getMainWindow()->updateActions();
}

void Document::slotRedoDocument(const App::Document& doc)
{
    if (d->_pcDocument != &doc) {
        return;
    }

    signalRedoDocument(*this);
    getMainWindow()->updateActions();
}

void Document::slotRecomputed(const App::Document& doc)
{
    if (d->_pcDocument != &doc) {
        return;
    }
    getMainWindow()->updateActions();
    TreeWidget::updateStatus();
}

// This function is called when some asks to recompute a document that is marked
// as 'SkipRecompute'. We'll check if we are the current document, and if either
// not given an explicit recomputing object list, or the given single object is
// the eidting object or the active object. If the conditions are met, we'll
// force recompute only that object and all its dependent objects.
void Document::slotSkipRecompute(const App::Document& doc, const std::vector<App::DocumentObject*>& objs)
{
    if (d->_pcDocument != &doc) {
        return;
    }
    if (objs.size() > 1 || App::GetApplication().getActiveDocument() != &doc
        || !doc.testStatus(App::Document::AllowPartialRecompute)) {
        return;
    }
    App::DocumentObject* obj = nullptr;

    if (Gui::Application::Instance->isInEdit(this)) {
        auto vp = freecad_cast<ViewProviderDocumentObject*>(getInEdit());
        if (vp) {
            obj = vp->getObject();
        }
    }
    if (objs.size() > 1 || App::GetApplication().getActiveDocument() != &doc
        || !doc.testStatus(App::Document::AllowPartialRecompute)) {
        return;
    }

    auto editDoc = Application::Instance->editDocument();
    if (editDoc) {
        auto vp = freecad_cast<ViewProviderDocumentObject*>(editDoc->getInEdit());
        if (vp) {
            obj = vp->getObject();
        }
    }
    if (!obj) {
        obj = doc.getActiveObject();
    }
    if (!obj || !obj->isAttachedToDocument() || (!objs.empty() && objs.front() != obj)) {
        return;
    }
    obj->recomputeFeature(true);
}

void Document::slotTouchedObject(const App::DocumentObject& Obj)
{
    getMainWindow()->updateActions(true);
    if (!isModified()) {
        FC_LOG(Obj.getFullName() << " touched");
        setModified(true);
    }
}

void Document::addViewProvider(Gui::ViewProviderDocumentObject* vp)
{
    // Hint: The undo/redo first adds the view provider to the Gui
    // document before adding the objects to the App document.

    // the view provider is added by TransactionViewProvider and an
    // object can be there only once
    assert(d->_ViewProviderMap.find(vp->getObject()) == d->_ViewProviderMap.end());
    vp->setStatus(Detach, false);
    d->_ViewProviderMap[vp->getObject()] = vp;
    d->_CoinMap[vp->getRoot()] = vp;
}

void Document::setModified(bool b)
{
    if (d->_isModified == b) {
        return;
    }
    d->_isModified = b;

    std::list<MDIView*> mdis = getMDIViews();
    for (auto& mdi : mdis) {
        mdi->setWindowModified(b);
    }
}

bool Document::isModified() const
{
    return d->_isModified;
}
void Document::setWorkbench(const std::string& name)
{
    d->_workbenchName = name;
}
std::string Document::workbench() const
{
    return d->_workbenchName;
}

bool Document::isAboutToClose() const
{
    return d->_isClosing;
}

ViewProviderDocumentObject* Document::getViewProviderByPathFromTail(SoPath* path) const
{
    // Get the lowest root node in the pick path!
    for (int i = 0; i < path->getLength(); i++) {
        SoNode* node = path->getNodeFromTail(i);
        if (node->isOfType(SoSeparator::getClassTypeId())) {
            auto it = d->_CoinMap.find(static_cast<SoSeparator*>(node));
            if (it != d->_CoinMap.end()) {
                return it->second;
            }
        }
    }

    return nullptr;
}

ViewProviderDocumentObject* Document::getViewProviderByPathFromHead(SoPath* path) const
{
    for (int i = 0; i < path->getLength(); i++) {
        SoNode* node = path->getNode(i);
        if (node->isOfType(SoSeparator::getClassTypeId())) {
            auto it = d->_CoinMap.find(static_cast<SoSeparator*>(node));
            if (it != d->_CoinMap.end()) {
                return it->second;
            }
        }
    }

    return nullptr;
}

ViewProviderDocumentObject* Document::getViewProvider(SoNode* node) const
{
    if (!node || !node->isOfType(SoSeparator::getClassTypeId())) {
        return nullptr;
    }
    auto it = d->_CoinMap.find(static_cast<SoSeparator*>(node));
    if (it != d->_CoinMap.end()) {
        return it->second;
    }
    return nullptr;
}

std::vector<std::pair<ViewProviderDocumentObject*, int>> Document::getViewProvidersByPath(
    SoPath* path
) const
{
    std::vector<std::pair<ViewProviderDocumentObject*, int>> ret;
    for (int i = 0; i < path->getLength(); i++) {
        SoNode* node = path->getNodeFromTail(i);
        if (node->isOfType(SoSeparator::getClassTypeId())) {
            auto it = d->_CoinMap.find(static_cast<SoSeparator*>(node));
            if (it != d->_CoinMap.end()) {
                ret.emplace_back(it->second, i);
            }
        }
    }
    return ret;
}

App::Document* Document::getDocument() const
{
    return d->_pcDocument;
}
void Document::setIsActive(bool active)
{
    d->_isActive = active;
    if (d->_editViewProvider) {
        d->_editViewProvider->setActive(active);
    }
}
bool Document::isActive() const
{
    return d->_isActive;
}

static bool checkCanonicalPath(const std::map<App::Document*, bool>& docs)
{
    std::map<QString, std::vector<App::Document*>> paths;
    bool warn = false;
    for (auto doc : App::GetApplication().getDocuments()) {
        QFileInfo info(QString::fromUtf8(doc->FileName.getValue()));
        auto& d = paths[info.canonicalFilePath()];
        d.push_back(doc);
        if (!warn && d.size() > 1) {
            if (docs.contains(d.front()) || docs.contains(d.back())) {
                warn = true;
            }
        }
    }
    if (!warn) {
        return true;
    }
    QString msg;
    QTextStream ts(&msg);
    ts << QObject::tr("Identical physical path detected. It may cause unwanted overwrite of existing document!\n\n")
       << QObject::tr("Are you sure you want to continue?");

    auto docName = [](App::Document* doc) -> QString {
        if (doc->Label.getStrValue() == doc->getName()) {
            return QString::fromUtf8(doc->getName());
        }
        return QStringLiteral("%1 (%2)").arg(
            QString::fromUtf8(doc->Label.getValue()),
            QString::fromUtf8(doc->getName())
        );
    };
    int count = 0;
    for (auto& v : paths) {
        if (v.second.size() <= 1) {
            continue;
        }
        for (auto doc : v.second) {
            if (docs.contains(doc)) {
                FC_WARN("Physical path: " << v.first.toUtf8().constData());
                for (auto d : v.second) {
                    FC_WARN(
                        "  Document: " << docName(d).toUtf8().constData() << ": "
                                       << d->FileName.getValue()
                    );
                }
                if (count == 3) {
                    ts << "\n\n" << QObject::tr("Check report view for more…");
                }
                else if (count < 3) {
                    ts << "\n\n"
                       << QObject::tr("Physical path:") << ' ' << v.first << "\n"
                       << QObject::tr("Document:") << ' ' << docName(doc) << "\n  "
                       << QObject::tr("Path:") << ' ' << QString::fromUtf8(doc->FileName.getValue());
                    for (auto d : v.second) {
                        if (d == doc) {
                            continue;
                        }
                        ts << "\n"
                           << QObject::tr("Document:") << ' ' << docName(d) << "\n  "
                           << QObject::tr("Path:") << ' '
                           << QString::fromUtf8(d->FileName.getValue());
                    }
                }
                ++count;
                break;
            }
        }
    }
    int ret = QMessageBox::warning(
        getMainWindow(),
        QObject::tr("Identical physical path"),
        msg,
        QMessageBox::Yes,
        QMessageBox::No
    );
    return ret == QMessageBox::Yes;
}

bool Document::askIfSavingFailed(const QString& error)
{
    int ret = QMessageBox::question(
        getMainWindow(),
        QObject::tr("Could not save document"),
        QObject::tr(
            "There was an issue trying to save the file. "
            "This may be because some of the parent folders do not exist, "
            "or you do not have sufficient permissions, "
            "or for other reasons. Error details:\n\n\"%1\"\n\n"
            "Would you like to save the file with a different name?"
        )
            .arg(error),
        QMessageBox::Yes,
        QMessageBox::No
    );

    if (ret == QMessageBox::No) {
        // TODO: Understand what exactly is supposed to be returned here
        getMainWindow()->showMessage(QObject::tr("Saving aborted"), 2000);
        return false;
    }
    else if (ret == QMessageBox::Yes) {
        return saveAs();
    }

    return false;
}

namespace
{
/// What a save does with documents opened from a newer fork release (ops#323)
enum class NewerSave
{
    Save,
    Copy,
    Cancel
};

/** Asks before \a docs, about to be saved over their own files, overwrite a file of a newer fork
 * release (ops#323): what this build dropped or misread in it would be lost for good. "Save a
 * Copy" is offered with \a canCopy (the one document a Save saves). Saves without a GUI or a
 * newer document; FreeCADCmd's save warns on its own (App::Document::save()).
 */
NewerSave askBeforeSavingNewer(const std::vector<App::Document*>& docs, bool canCopy)
{
    QStringList newer;
    for (auto doc : docs) {
        if (App::isNewerFormat(doc)) {
            newer << QString::fromStdString(App::newerFormatMessage(doc));
        }
    }
    if (newer.isEmpty() || !getMainWindow()) {
        return NewerSave::Save;
    }
    QMessageBox box(getMainWindow());
    box.setWindowTitle(QObject::tr("File from a Newer FreeCAD-CH Build"));
    box.setIcon(QMessageBox::Warning);
    box.setText(
        newer.join(QStringLiteral("\n\n")) + QStringLiteral("\n\n")
        + QObject::tr("Saving over it loses what this build doesn't know for good.")
    );
    QPushButton* copyButton =
        canCopy ? box.addButton(QObject::tr("Save a Copy…"), QMessageBox::ActionRole) : nullptr;
    QPushButton* saveButton = box.addButton(QObject::tr("Save Anyway"), QMessageBox::DestructiveRole);
    box.addButton(QMessageBox::Cancel);
    box.setDefaultButton(QMessageBox::Cancel);
    box.exec();
    if (copyButton && box.clickedButton() == copyButton) {
        return NewerSave::Copy;
    }
    return box.clickedButton() == saveButton ? NewerSave::Save : NewerSave::Cancel;
}
}  // namespace

bool Document::warnIfOlderVersion()
{
    // Skip warning if no GUI (headless/scripted mode)
    if (!getMainWindow()) {
        return true;
    }

    // Check if version checking is disabled in preferences
    if (App::GetApplication()
            .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Document")
            ->GetBool("DisableVersionCheckOnSave", false)) {
        return true;
    }

    // Get document version info
    const char* docVersion = d->_pcDocument->getProgramVersion();
    const bool hasVersionString = !Base::Tools::isNullOrEmpty(docVersion);

    // Parse document version string like "1.0R39319 (Git)" or "0.21R33694 (Git)"
    // hasVersion is true only if the string is present AND parses as major.minor.
    // Unrecognised strings like "pre-0.14" still display in the dialog but cannot
    // be compared numerically, so they are treated as older versions.
    int docMajor = 0, docMinor = 0;
    const bool hasVersion = hasVersionString
        && std::sscanf(docVersion, "%d.%d", &docMajor, &docMinor) == 2;

    // Get current FreeCAD version
    auto config = App::Application::Config();
    int currentMajor = 0, currentMinor = 0;
    if (config.count("BuildVersionMajor") && config.count("BuildVersionMinor")) {
        currentMajor = std::stoi(config["BuildVersionMajor"]);
        currentMinor = std::stoi(config["BuildVersionMinor"]);
    }
    else {
        return true;
    }

    // Warn if the document was created with an older version or has no version info
    if (!hasVersion || (docMajor < currentMajor)
        || (docMajor == currentMajor && docMinor < currentMinor)) {
        QMessageBox msgBox(getMainWindow());
        msgBox.setWindowTitle(QObject::tr("File Created with Older FreeCAD Version"));
        msgBox.setIcon(QMessageBox::Warning);
        msgBox.setText(
            QObject::tr(
                "This file was created with %1, but you are using v%2.%3.\n\n"
                "Saving will upgrade the file format. The file may not be readable "
                "by older versions of FreeCAD after saving.\n\n"
                "Use 'Save As…' to preserve the original file."
                "\n"
            )
                .arg(
                    !hasVersionString
                        ? QObject::tr("an unknown older version of FreeCAD")
                        : QObject::tr("FreeCAD version %1").arg(QString::fromUtf8(docVersion))
                )
                .arg(currentMajor)
                .arg(currentMinor)
        );
        QPushButton* saveButton = msgBox.addButton(QObject::tr("Save"), QMessageBox::AcceptRole);
        QPushButton* saveAsButton = msgBox.addButton(QObject::tr("Save As…"), QMessageBox::ActionRole);
        msgBox.addButton(QMessageBox::Cancel);
        msgBox.setDefaultButton(QMessageBox::Cancel);

        QCheckBox dontShowCheckBox(QObject::tr("Do not show this warning again"), &msgBox);
        msgBox.setCheckBox(&dontShowCheckBox);

        int ret = msgBox.exec();

        if (msgBox.clickedButton() == saveButton) {
            if (dontShowCheckBox.isChecked()) {
                App::GetApplication()
                    .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Document")
                    ->SetBool("DisableVersionCheckOnSave", true);
            }
        }
        else if (msgBox.clickedButton() == saveAsButton) {
            saveAs();
            return false;
        }

        if (ret == QMessageBox::Cancel) {
            return false;
        }
    }
    return true;
}

/// Save the document
bool Document::save()
{
    if (d->_pcDocument->isSaved()) {
        // A file of a newer fork release (ops#323)
        switch (askBeforeSavingNewer({getDocument()}, true)) {
            case NewerSave::Copy:
                saveCopy();
                return false;
            case NewerSave::Cancel:
                return false;
            case NewerSave::Save:
                break;
        }

        // Warn if this document was created with an older FreeCAD version
        if (!warnIfOlderVersion()) {
            return false;
        }

        try {
            std::vector<App::Document*> docs;
            std::map<App::Document*, bool> dmap;
            try {
                docs = getDocument()->getDependentDocuments();
                for (auto it = docs.begin(); it != docs.end();) {
                    App::Document* doc = *it;
                    if (doc == getDocument()) {
                        dmap[doc] = doc->mustExecute();
                        ++it;
                        continue;
                    }
                    auto gdoc = Application::Instance->getDocument(doc);
                    if ((gdoc && !gdoc->isModified()) || doc->testStatus(App::Document::PartialDoc)
                        || doc->testStatus(App::Document::TempDoc)) {
                        it = docs.erase(it);
                        continue;
                    }
                    dmap[doc] = doc->mustExecute();
                    ++it;
                }
            }
            catch (const Base::RuntimeError& e) {
                FC_ERR(e.what());
                docs = {getDocument()};
                dmap.clear();
                dmap[getDocument()] = getDocument()->mustExecute();
            }

            if (docs.size() > 1) {
                int ret = QMessageBox::question(
                    getMainWindow(),
                    QObject::tr("Save dependent files"),
                    QObject::tr(
                        "The file contains external dependencies. "
                        "Do you want to save the dependent files, too?"
                    ),
                    QMessageBox::Yes,
                    QMessageBox::No
                );

                if (ret != QMessageBox::Yes) {
                    docs = {getDocument()};
                    dmap.clear();
                    dmap[getDocument()] = getDocument()->mustExecute();
                }
            }

            if (!checkCanonicalPath(dmap)) {
                return false;
            }

            // Dependent files of a newer fork release (ops#323); this one was asked above
            std::vector<App::Document*> dependents;
            std::copy_if(
                docs.begin(),
                docs.end(),
                std::back_inserter(dependents),
                [this](App::Document* doc) { return doc != getDocument(); }
            );
            if (askBeforeSavingNewer(dependents, false) != NewerSave::Save) {
                return false;
            }

            Gui::WaitCursor wc;
            // save all documents
            for (auto doc : docs) {
                // Changed 'mustExecute' status may be triggered by saving external document
                if (!dmap[doc] && doc->mustExecute()) {
                    App::AutoTransaction trans(doc, "Recompute");
                    Command::doCommand(
                        Command::Doc,
                        "App.getDocument(\"%s\").recompute()",
                        doc->getName()
                    );
                }

                Command::doCommand(Command::Doc, "App.getDocument(\"%s\").save()", doc->getName());
                auto gdoc = Application::Instance->getDocument(doc);
                if (gdoc) {
                    gdoc->setModified(false);
                }
            }
        }
        catch (const Base::FileException& e) {
            e.reportException();
            return askIfSavingFailed(QString::fromStdString(e.getTranslatedMessage()));
        }
        catch (const Base::Exception& e) {
            QMessageBox::critical(
                getMainWindow(),
                QObject::tr("Saving document failed"),
                QString::fromLatin1(e.what())
            );
            return false;
        }
        return true;
    }
    else {
        return saveAs();
    }
}

/// Save the document under a new file name
bool Document::saveAs()
{
    getMainWindow()->showMessage(QObject::tr("Save document under new filename…"));

    QString exe = qApp->applicationName();
    QString name = QString::fromUtf8(getDocument()->FileName.getValue());
    if (name.isEmpty()) {
        name = QString::fromUtf8(getDocument()->Label.getValue());
    }
    if (name.endsWith(QStringLiteral(".FCBak"), Qt::CaseInsensitive)) {
        name.chop(QStringLiteral(".FCBak").size());
        if (!name.endsWith(QStringLiteral(".FCStd"), Qt::CaseInsensitive)) {
            name += QStringLiteral(".FCStd");
        }
    }
    QString fn = FileDialog::getSaveFileName(
        getMainWindow(),
        QObject::tr("Save %1 Document").arg(exe),
        name,
        FileDialog::FilterList {{QObject::tr("%1 document").arg(exe), {"*.FCStd"}}}
    );

    if (!fn.isEmpty()) {
        QFileInfo fi;
        fi.setFile(fn);

        // Onto its own file, App::Document::saveAs() saves: a newer file asks as a Save does
        // (ops#323, PR 293 review)
        const QFileInfo own(QString::fromUtf8(getDocument()->FileName.getValue()));
        if (getDocument()->isSaved() && own.exists() && fi.exists() && fi == own) {
            switch (askBeforeSavingNewer({getDocument()}, true)) {
                case NewerSave::Copy:
                    saveCopy();
                    return false;
                case NewerSave::Cancel:
                    return false;
                case NewerSave::Save:
                    break;
            }
        }

        const char* DocName = App::GetApplication().getDocumentName(getDocument());

        // save as new file name
        try {
            Gui::WaitCursor wc;
            std::string escapedstr = Base::Tools::escapedUnicodeFromUtf8(fn.toUtf8());
            escapedstr = Base::Tools::escapeEncodeFilename(escapedstr);
            Command::doCommand(
                Command::Doc,
                "App.getDocument(\"%s\").saveAs(u\"%s\")",
                DocName,
                escapedstr.c_str()
            );
            // App::Document::saveAs() may modify the passed file name
            fi.setFile(QString::fromUtf8(d->_pcDocument->FileName.getValue()));
            setModified(false);
            getMainWindow()->appendRecentFile(fi.filePath());
        }
        catch (const Base::FileException& e) {
            e.reportException();
            return askIfSavingFailed(QString::fromUtf8(e.getTranslatedMessage().c_str()));
        }
        catch (const Base::Exception& e) {
            QMessageBox::critical(
                getMainWindow(),
                QObject::tr("Saving document failed"),
                QString::fromLatin1(e.what())
            );
        }
        return true;
    }
    else {
        getMainWindow()->showMessage(QObject::tr("Saving aborted"), 2000);
        return false;
    }
}

void Document::saveAll()
{
    std::vector<App::Document*> docs;
    try {
        docs = App::Document::getDependentDocuments(App::GetApplication().getDocuments(), true);
    }
    catch (Base::Exception& e) {
        e.reportException();
        int ret = QMessageBox::critical(
            getMainWindow(),
            QObject::tr("Failed to save document"),
            QObject::tr("Documents contains cyclic dependencies. Do you still want to save them?"),
            QMessageBox::Yes,
            QMessageBox::No
        );
        if (ret != QMessageBox::Yes) {
            return;
        }
        docs = App::GetApplication().getDocuments();
    }

    std::map<App::Document*, bool> dmap;
    for (auto doc : docs) {
        if (doc->testStatus(App::Document::PartialDoc) || doc->testStatus(App::Document::TempDoc)) {
            continue;
        }
        dmap[doc] = doc->mustExecute();
    }

    if (!checkCanonicalPath(dmap)) {
        return;
    }

    // Files of a newer fork release (ops#323)
    std::vector<App::Document*> saved;
    for (const auto& entry : dmap) {
        if (entry.first->isSaved()) {
            saved.push_back(entry.first);
        }
    }
    if (askBeforeSavingNewer(saved, false) != NewerSave::Save) {
        return;
    }

    for (auto doc : docs) {
        if (doc->testStatus(App::Document::PartialDoc) || doc->testStatus(App::Document::TempDoc)) {
            continue;
        }
        auto gdoc = Application::Instance->getDocument(doc);
        if (!gdoc) {
            continue;
        }
        if (!doc->isSaved()) {
            if (!gdoc->saveAs()) {
                break;
            }
        }
        Gui::WaitCursor wc;

        try {
            // Changed 'mustExecute' status may be triggered by saving external document
            if (!dmap[doc] && doc->mustExecute()) {
                App::AutoTransaction trans(doc, "Recompute");
                Command::doCommand(Command::Doc, "App.getDocument('%s').recompute()", doc->getName());
            }
            Command::doCommand(Command::Doc, "App.getDocument('%s').save()", doc->getName());
            gdoc->setModified(false);
        }
        catch (const Base::Exception& e) {
            QMessageBox::critical(
                getMainWindow(),
                QObject::tr("Failed to save document")
                    + QStringLiteral(": %1").arg(QString::fromUtf8(doc->getName())),
                QString::fromLatin1(e.what())
            );
            break;
        }
    }
}

/// Save a copy of the document under a new file name
bool Document::saveCopy()
{
    getMainWindow()->showMessage(QObject::tr("Save a copy of the document under new filename…"));

    QString exe = qApp->applicationName();
    QString name = QString::fromUtf8(getDocument()->FileName.getValue());
    if (name.endsWith(QStringLiteral(".FCBak"), Qt::CaseInsensitive)) {
        name.chop(QStringLiteral(".FCBak").size());
        if (!name.endsWith(QStringLiteral(".FCStd"), Qt::CaseInsensitive)) {
            name += QStringLiteral(".FCStd");
        }
    }
    // A newer file's copy (ops#323: the save guard's "Save a Copy…") is offered beside it, not
    // over it
    if (App::isNewerFormat(getDocument()) && !name.isEmpty()) {
        QFileInfo file(name);
        name = file.dir().filePath(
            QObject::tr("%1 (copy)").arg(file.completeBaseName()) + QStringLiteral(".FCStd")
        );
    }
    QString fn = FileDialog::getSaveFileName(
        getMainWindow(),
        QObject::tr("Save %1 Document").arg(exe),
        name,
        FileDialog::FilterList {{QObject::tr("%1 document").arg(exe), {"*.FCStd"}}}
    );
    // App::Document::saveCopy() doesn't write over the document's own file, and says nothing
    const QFileInfo own(QString::fromUtf8(getDocument()->FileName.getValue()));
    if (!fn.isEmpty() && own.exists() && QFileInfo(fn) == own) {
        QMessageBox::warning(
            getMainWindow(),
            QObject::tr("Save a Copy"),
            QObject::tr("A copy can't be saved over the document's own file. Choose another name.")
        );
        return false;
    }
    if (!fn.isEmpty()) {
        const char* DocName = App::GetApplication().getDocumentName(getDocument());

        // save as new file name
        Gui::WaitCursor wc;
        std::string pyfn = Base::Tools::escapeEncodeFilename(fn.toUtf8().constData());
        Command::doCommand(
            Command::Doc,
            "App.getDocument(\"%s\").saveCopy(\"%s\")",
            DocName,
            pyfn.c_str()
        );

        return true;
    }
    else {
        getMainWindow()->showMessage(QObject::tr("Saving aborted"), 2000);
        return false;
    }
}

unsigned int Document::getMemSize() const
{
    unsigned int size = 0;

    // size of the view providers in the document

    for (const auto& vp : d->_ViewProviderMap) {
        size += vp.second->getMemSize();
    }
    return size;
}

/**
 * Adds a separate XML file to the projects file that contains information about the view providers.
 */
void Document::Save(Base::Writer& writer) const
{
    // It's only possible to add extra information if force of XML is disabled
    if (!writer.isForceXML()) {
        writer.addFile("GuiDocument.xml", this);

        ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
            "User parameter:BaseApp/Preferences/Document"
        );
        if (hGrp->GetBool("SaveThumbnail", true)) {
            int size = hGrp->GetInt("ThumbnailSize", 256);
            size = Base::clamp<int>(size, 64, 512);
            std::list<MDIView*> mdi = getMDIViews();

            View3DInventorViewer* view = nullptr;
            for (const auto& it : mdi) {
                if (it->isDerivedFrom<View3DInventor>()) {
                    view = static_cast<View3DInventor*>(it)->getViewer();
                    break;
                }
            }

            d->thumb.setFileName(d->_pcDocument->FileName.getValue());
            d->thumb.setSize(size);
            d->thumb.setViewer(view);
            d->thumb.Save(writer);
        }
    }
}

/**
 * Loads a separate XML file from the projects file with information about the view providers.
 */
void Document::Restore(Base::XMLReader& reader)
{
    d->_restoredGuiDocument = false;
    reader.addFile("GuiDocument.xml", this);

    // hide all elements to avoid to update the 3d view when loading data files
    // RestoreDocFile then restores the visibility status again
    std::map<const App::DocumentObject*, ViewProviderDocumentObject*>::iterator it;
    for (const auto& vp : d->_ViewProviderMap) {
        vp.second->startRestoring();
        vp.second->setStatus(Gui::isRestoring, true);
    }
}

/**
 * Restores the properties of the view providers.
 */
void Document::RestoreDocFile(Base::Reader& reader)
{
    d->_restoredGuiDocument = true;

    // We must create an XML parser to read from the input stream
    std::shared_ptr<Base::XMLReader> localreader
        = std::make_shared<Base::XMLReader>("GuiDocument.xml", reader);
    localreader->FileVersion = reader.getFileVersion();

    localreader->readElement("Document");
    long scheme = localreader->getAttribute<long>("SchemaVersion");
    localreader->DocumentSchema = scheme;
    localreader->ProgramVersion = d->_pcDocument->getProgramVersion();

    bool hasExpansion = localreader->hasAttribute("HasExpansion");
    if (hasExpansion) {
        auto tree = TreeWidget::instance();
        if (tree) {
            auto docItem = tree->getDocumentItem(this);
            if (docItem) {
                docItem->Restore(*localreader);
            }
        }
    }

    // At this stage all the document objects and their associated view providers exist.
    // Now we must restore the properties of the view providers only.
    //
    // SchemeVersion "1"
    if (scheme == 1) {
        // read the viewproviders itself
        localreader->readElement("ViewProviderData");
        int Cnt = localreader->getAttribute<long>("Count");
        for (int i = 0; i < Cnt; i++) {
            localreader->readElement("ViewProvider");
            std::string name = localreader->getAttribute<const char*>("name");

            bool expanded = false;
            if (!hasExpansion && localreader->hasAttribute("expanded")) {
                const char* attr = localreader->getAttribute<const char*>("expanded");
                if (strcmp(attr, "1") == 0) {
                    expanded = true;
                }
            }

            int treeRank = -1;
            if (localreader->hasAttribute("treeRank")) {
                treeRank = localreader->getAttribute<int>("treeRank");
            }

            auto pObj = freecad_cast<ViewProviderDocumentObject*>(getViewProviderByName(name.c_str()));
            // check if this feature has been registered
            if (pObj) {
                pObj->Restore(*localreader);
            }

            if (pObj && treeRank >= 0) {
                pObj->setTreeRank(treeRank);
            }

            if (pObj && expanded) {
                this->signalExpandObject(*pObj, TreeItemMode::ExpandItem, 0, 0);
            }
            localreader->readEndElement("ViewProvider");
        }
        localreader->readEndElement("ViewProviderData");

        // read camera settings
        localreader->readElement("Camera");
        const char* ppReturn = localreader->getAttribute<const char*>("settings");
        cameraSettings.clear();
        if (!Base::Tools::isNullOrEmpty(ppReturn)) {
            saveCameraSettings(ppReturn);
            try {
                for (const auto& it : getMDIViews()) {
                    if (auto* viewCamera = freecad_cast<MDIViewWithCamera*>(it)) {
                        viewCamera->setCamera(cameraSettings.c_str());
                    }
                }
            }
            catch (const Base::Exception& e) {
                Base::Console().error("%s\n", e.what());
            }
        }

        // FreeCAD-CH (ops#640): named views, an optional element after the camera
        NamedViews::forget(this);
        if (localreader->readNextElement()
            && std::string(localreader->localName()) == "NamedViews") {
            NamedViews::read(this, *localreader);
        }
    }

    reader.initLocalReader(localreader);

    // reset modified flag
    setModified(false);
}

void Document::slotStartRestoreDocument(const App::Document& doc)
{
    if (d->_pcDocument != &doc) {
        return;
    }
    // disable this signal while loading a document
    d->connectActObjectBlocker.block();
}

void Document::slotFinishRestoreObject(const App::DocumentObject& obj)
{
    auto vpd = freecad_cast<ViewProviderDocumentObject*>(getViewProvider(&obj));
    if (vpd) {
        vpd->setStatus(Gui::isRestoring, false);
        vpd->finishRestoring();
        if (!vpd->canAddToSceneGraph()) {
            toggleInSceneGraph(vpd);
        }
    }
}

void Document::slotFinishRestoreDocument(const App::Document& doc)
{
    if (d->_pcDocument != &doc) {
        return;
    }
    d->connectActObjectBlocker.unblock();
    App::DocumentObject* act = doc.getActiveObject();
    if (act) {
        ViewProvider* viewProvider = getViewProvider(act);
        if (viewProvider && viewProvider->isDerivedFrom<ViewProviderDocumentObject>()) {
            signalActivatedObject(*(static_cast<ViewProviderDocumentObject*>(viewProvider)));
        }
    }

    if (!d->_restoredGuiDocument) {
        for (auto* mdiView : getMDIViews()) {
            if (auto* view3D = freecad_cast<View3DInventor*>(mdiView)) {
                view3D->viewAll();
                break;
            }
        }
    }

    // reset modified flag
    setModified(doc.testStatus(App::Document::LinkStampChanged));
}

void Document::slotShowHidden(const App::Document& doc)
{
    if (d->_pcDocument != &doc) {
        return;
    }

    Application::Instance->signalShowHidden(*this);
}

/**
 * Saves the properties of the view providers.
 */
void Document::SaveDocFile(Base::Writer& writer) const
{
    writer.Stream() << "<?xml version='1.0' encoding='utf-8'?>" << std::endl
                    << "<!--" << std::endl
                    << " FreeCAD Document, see https://www.freecad.org for more information…"
                    << std::endl
                    << "-->" << std::endl;

    writer.Stream() << "<Document SchemaVersion=\"1\"";

    writer.incInd();

    auto tree = TreeWidget::instance();
    bool hasExpansion = false;
    if (tree) {
        auto docItem = tree->getDocumentItem(this);
        if (docItem) {
            hasExpansion = true;
            writer.Stream() << " HasExpansion=\"1\">" << std::endl;
            docItem->Save(writer);
        }
    }
    if (!hasExpansion) {
        writer.Stream() << ">" << std::endl;
    }

    // writing the view provider names itself
    writer.Stream() << writer.ind() << "<ViewProviderData Count=\"" << d->_ViewProviderMap.size()
                    << "\">" << std::endl;

    bool xml = writer.isForceXML();
    // writer.setForceXML(true);
    writer.incInd();  // indentation for 'ViewProvider name'
    for (const auto& it : d->_ViewProviderMap) {
        const App::DocumentObject* doc = it.first;
        ViewProviderDocumentObject* obj = it.second;
        writer.Stream() << writer.ind() << "<ViewProvider name=\"" << doc->getNameInDocument() << "\""
                        << " expanded=\"" << (doc->testStatus(App::Expand) ? 1 : 0) << "\""
                        << " treeRank=\"" << obj->getTreeRank() << "\"";
        if (obj->hasExtensions()) {
            writer.Stream() << " Extensions=\"True\"";
        }

        writer.Stream() << ">" << std::endl;
        obj->Save(writer);
        writer.Stream() << writer.ind() << "</ViewProvider>" << std::endl;
    }
    writer.setForceXML(xml);

    writer.decInd();  // indentation for 'ViewProvider name'
    writer.Stream() << writer.ind() << "</ViewProviderData>" << std::endl;
    writer.decInd();  // indentation for 'ViewProviderData Count'

    // save camera settings
    for (const auto& it : getMDIViews()) {
        if (auto* viewCamera = freecad_cast<MDIViewWithCamera*>(it)) {
            const std::string& camera = viewCamera->getCamera();
            if (saveCameraSettings(camera.c_str())) {
                break;
            }
        }
    }

    writer.incInd();  // indentation for camera settings
    writer.Stream() << writer.ind() << "<Camera settings=\"" << encodeAttribute(getCameraSettings())
                    << "\"/>\n";
    writer.decInd();  // indentation for camera settings

    // FreeCAD-CH (ops#640): the named views follow the camera
    NamedViews::write(this, writer);

    writer.Stream() << "</Document>" << std::endl;
}

void Document::exportObjects(const std::vector<App::DocumentObject*>& obj, Base::Writer& writer)
{
    writer.Stream() << "<?xml version='1.0' encoding='utf-8'?>" << std::endl;
    writer.Stream() << "<Document SchemaVersion=\"1\">" << std::endl;

    std::map<const App::DocumentObject*, ViewProvider*> views;
    for (const auto& it : obj) {
        Document* doc = Application::Instance->getDocument(it->getDocument());
        if (doc) {
            ViewProvider* vp = doc->getViewProvider(it);
            if (vp) {
                views[it] = vp;
            }
        }
    }

    // writing the view provider names itself
    writer.incInd();  // indentation for 'ViewProviderData Count'
    writer.Stream() << writer.ind() << "<ViewProviderData Count=\"" << views.size() << "\">"
                    << std::endl;

    bool xml = writer.isForceXML();
    // writer.setForceXML(true);
    writer.incInd();  // indentation for 'ViewProvider name'
    std::map<const App::DocumentObject*, ViewProvider*>::const_iterator jt;
    for (jt = views.begin(); jt != views.end(); ++jt) {
        const App::DocumentObject* doc = jt->first;
        ViewProvider* vp = jt->second;
        writer.Stream() << writer.ind() << "<ViewProvider name=\"" << doc->getExportName() << "\" "
                        << "expanded=\"" << (doc->testStatus(App::Expand) ? 1 : 0) << "\"";
        if (vp->hasExtensions()) {
            writer.Stream() << " Extensions=\"True\"";
        }

        writer.Stream() << ">" << std::endl;
        vp->Save(writer);
        writer.Stream() << writer.ind() << "</ViewProvider>" << std::endl;
    }
    writer.setForceXML(xml);

    writer.decInd();  // indentation for 'ViewProvider name'
    writer.Stream() << writer.ind() << "</ViewProviderData>" << std::endl;
    writer.decInd();  // indentation for 'ViewProviderData Count'
    writer.incInd();  // indentation for camera settings
    writer.Stream() << writer.ind() << "<Camera settings=\"\"/>" << std::endl;
    writer.decInd();  // indentation for camera settings
    writer.Stream() << "</Document>" << std::endl;
}

void Document::importObjects(
    const std::vector<App::DocumentObject*>& obj,
    Base::Reader& reader,
    const std::map<std::string, std::string>& nameMapping
)
{
    // We must create an XML parser to read from the input stream
    std::shared_ptr<Base::XMLReader> localreader
        = std::make_shared<Base::XMLReader>("GuiDocument.xml", reader);
    localreader->readElement("Document");
    long scheme = localreader->getAttribute<long>("SchemaVersion");

    // At this stage all the document objects and their associated view providers exist.
    // Now we must restore the properties of the view providers only.
    //
    // SchemeVersion "1"
    if (scheme == 1) {
        // read the viewproviders itself
        localreader->readElement("ViewProviderData");
        int Cnt = localreader->getAttribute<long>("Count");
        auto it = obj.begin();
        for (int i = 0; i < Cnt && it != obj.end(); ++i, ++it) {
            // The stored name usually doesn't match with the current name anymore
            // thus we try to match by type. This should work because the order of
            // objects should not have changed
            localreader->readElement("ViewProvider");
            std::string name = localreader->getAttribute<const char*>("name");
            auto jt = nameMapping.find(name);
            if (jt != nameMapping.end()) {
                name = jt->second;
            }
            bool expanded = false;
            if (localreader->hasAttribute("expanded")) {
                const char* attr = localreader->getAttribute<const char*>("expanded");
                if (strcmp(attr, "1") == 0) {
                    expanded = true;
                }
            }
            Gui::ViewProvider* pObj = this->getViewProviderByName(name.c_str());
            if (pObj) {
                pObj->setStatus(Gui::isRestoring, true);
                auto vpd = freecad_cast<ViewProviderDocumentObject*>(pObj);
                if (vpd) {
                    vpd->startRestoring();
                }
                pObj->Restore(*localreader);
                if (expanded && vpd) {
                    this->signalExpandObject(*vpd, TreeItemMode::ExpandItem, 0, 0);
                }
            }
            localreader->readEndElement("ViewProvider");
            if (it == obj.end()) {
                break;
            }
        }
        localreader->readEndElement("ViewProviderData");
    }

    localreader->readEndElement("Document");

    // In the file GuiDocument.xml new data files might be added
    if (localreader->hasFilenames()) {
        reader.initLocalReader(localreader);
    }
}

void Document::slotFinishImportObjects(const std::vector<App::DocumentObject*>& objs)
{
    (void)objs;
    // finishRestoring() is now triggered by signalFinishRestoreObject
    //
    // for(auto obj : objs) {
    //     auto vp = getViewProvider(obj);
    //     if(!vp) continue;
    //     vp->setStatus(Gui::isRestoring,false);
    //     auto vpd = freecad_cast<ViewProviderDocumentObject*>(vp);
    //     if(vpd) vpd->finishRestoring();
    // }
}

void Document::addRootObjectsToGroup(
    const std::vector<App::DocumentObject*>& obj,
    App::DocumentObjectGroup* grp
)
{
    std::map<App::DocumentObject*, bool> rootMap;
    for (const auto it : obj) {
        rootMap[it] = true;
    }
    // get the view providers and check which objects are children
    for (const auto it : obj) {
        Gui::ViewProvider* vp = getViewProvider(it);
        if (vp) {
            std::vector<App::DocumentObject*> child = vp->claimChildren();
            for (const auto& jt : child) {
                auto kt = rootMap.find(jt);
                if (kt != rootMap.end()) {
                    kt->second = false;
                }
            }
        }
    }

    // all objects that are not children of other objects can be added to the group
    for (const auto& it : rootMap) {
        if (it.second) {
            grp->addObject(it.first);
        }
    }
}

MDIView* Document::createView(const Base::Type& typeId, CreateViewMode mode)
{
    if (!typeId.isDerivedFrom(MDIView::getClassTypeId())) {
        return nullptr;
    }

    std::list<MDIView*> theViews = this->getMDIViewsOfType(typeId);
    if (typeId == View3DInventor::getClassTypeId()) {

        QOpenGLWidget* shareWidget = nullptr;
        // VBO rendering doesn't work correctly when we don't share the OpenGL widgets
        if (!theViews.empty()) {
            auto firstView = static_cast<View3DInventor*>(theViews.front());
            shareWidget = qobject_cast<QOpenGLWidget*>(firstView->getViewer()->getGLWidget());

            const std::string& camera = firstView->getCamera();
            saveCameraSettings(camera.c_str());
        }

        auto view3D = new View3DInventor(this, getMainWindow(), shareWidget);
        if (!theViews.empty()) {
            auto firstView = static_cast<View3DInventor*>(theViews.front());
            std::string overrideMode = firstView->getViewer()->getOverrideMode();
            view3D->getViewer()->setOverrideMode(overrideMode);
        }

        // attach the viewproviders. we need to make sure that we only attach the toplevel ones
        // and not viewproviders which are claimed by other providers. To ensure this we first
        // add all providers and then remove the ones already claimed

        std::vector<App::DocumentObject*> child_vps;
        for (const auto& vp : d->_ViewProviderMap) {
            view3D->getViewer()->addViewProvider(vp.second);
            std::vector<App::DocumentObject*> children = vp.second->claimChildren3D();
            child_vps.insert(child_vps.end(), children.begin(), children.end());
        }

        for (const auto& va : d->_ViewProviderMapAnnotation) {
            view3D->getViewer()->addViewProvider(va.second);
            std::vector<App::DocumentObject*> children = va.second->claimChildren3D();
            child_vps.insert(child_vps.end(), children.begin(), children.end());
        }

        for (App::DocumentObject* obj : child_vps) {
            view3D->getViewer()->removeViewProvider(getViewProvider(obj));
        }

        // FreeCAD-CH (ops#640, rank 59): under the Onshape keymap the view is a typed tab's
        DocumentTabs::viewCreated(this, view3D);

        // When cloning the view, don't increment the window counter as the old view will be deleted
        // shortly after.
        if (mode != CreateViewMode::Clone) {
            const char* name = getDocument()->Label.getValue();
            QString title
                = QStringLiteral("%1 : %2[*]").arg(QString::fromUtf8(name)).arg(d->_iWinCount++);

            view3D->setWindowTitle(title);
        }

        view3D->setWindowModified(this->isModified());
        view3D->resize(400, 300);

        if (!cameraSettings.empty()) {
            view3D->setCamera(cameraSettings.c_str());
        }

        // When cloning the view, don't add the view to the main window. The whole purpose of the
        // workaround using cloned views is that the view can be shown in undocked/fullscreen mode
        // without having been docked before.
        if (mode != CreateViewMode::Clone) {
            getMainWindow()->addWindow(view3D);
        }

        view3D->getViewer()->redraw();
        return view3D;
    }
    return nullptr;
}

const char* Document::getCameraSettings() const
{
    return cameraSettings.c_str();
}

bool Document::saveCameraSettings(const char* settings) const
{
    if (!settings) {
        return false;
    }

    // skip starting comment lines
    bool skipping = false;
    char c = *settings;
    for (; c; c = *(++settings)) {
        if (skipping) {
            if (c == '\n') {
                skipping = false;
            }
        }
        else if (c == '#') {
            skipping = true;
        }
        else if (!std::isspace(c)) {
            break;
        }
    }

    if (!c) {
        return false;
    }

    cameraSettings = settings;
    return true;
}

void Document::attachView(Gui::BaseView* pcView, bool bPassiv)
{
    if (!bPassiv) {
        d->baseViews.push_back(pcView);
    }
    else {
        d->passiveViews.push_back(pcView);
    }
}

void Document::detachView(Gui::BaseView* pcView, bool bPassiv)
{
    if (bPassiv) {
        if (find(d->passiveViews.begin(), d->passiveViews.end(), pcView) != d->passiveViews.end()) {
            d->passiveViews.remove(pcView);
        }
    }
    else {
        if (find(d->baseViews.begin(), d->baseViews.end(), pcView) != d->baseViews.end()) {
            d->baseViews.remove(pcView);
        }

        // last view?
        if (d->baseViews.empty()) {
            // decouple a passive view
            std::list<Gui::BaseView*>::iterator it = d->passiveViews.begin();
            while (it != d->passiveViews.end()) {
                (*it)->setDocument(nullptr);
                it = d->passiveViews.begin();
            }

            // is already closing the document, and is not linked by other documents
            if (!d->_isClosing && App::PropertyXLink::getDocumentInList(getDocument()).empty()) {
                d->_pcAppWnd->onLastWindowClosed(this);
            }
        }
    }
}

void Document::onUpdate()
{
#ifdef FC_LOGUPDATECHAIN
    Base::Console().log("Acti: Gui::Document::onUpdate()");
#endif

    for (auto* v : d->baseViews) {
        v->onUpdate();
    }

    for (auto* v : d->passiveViews) {
        v->onUpdate();
    }
}

void Document::onRelabel()
{
#ifdef FC_LOGUPDATECHAIN
    Base::Console().log("Acti: Gui::Document::onRelabel()");
#endif

    for (auto* v : d->baseViews) {
        v->onRelabel(this);
    }

    for (auto* v : d->passiveViews) {
        v->onRelabel(this);
    }

    d->connectChangeDocumentBlocker.unblock();
}

bool Document::isLastView()
{
    if (d->baseViews.size() <= 1) {
        return true;
    }
    return false;
}

/**
 *  This method checks if the document can be closed. It checks on
 *  the save state of the document and is able to abort the closing.
 */
bool Document::canClose(bool checkModify, bool checkLink)
{
    if (d->_isClosing) {
        return true;
    }
    if (!getDocument()->isClosable()) {
        QMessageBox::warning(
            getActiveView(),
            QObject::tr("Document not closable"),
            QObject::tr("The document is not closable for the moment.")
        );
        return false;
    }
    // else if (!Gui::Control().isAllowedAlterDocument()) {
    //     std::string name = Gui::Control().activeDialog()->getDocumentName();
    //     if (name == this->getDocument()->getName()) {
    //         QMessageBox::warning(getActiveView(),
    //             QObject::tr("Document not closable"),
    //             QObject::tr("The document is in editing mode and thus cannot be closed for the
    //             moment.\n"
    //                         "You either have to finish or cancel the editing in the task panel."));
    //         Gui::TaskView::TaskDialog* dlg = Gui::Control().activeDialog();
    //         if (dlg) Gui::Control().showDialog(dlg);
    //         return false;
    //     }
    // }

    if (checkLink && !App::PropertyXLink::getDocumentInList(getDocument()).empty()) {
        return true;
    }

    if (getDocument()->testStatus(App::Document::TempDoc)) {
        return true;
    }

    bool ok = true;
    if (checkModify && isModified() && !getDocument()->testStatus(App::Document::PartialDoc)) {
        int res = getMainWindow()->confirmSave(getDocument(), getActiveView());
        switch (res) {
            case MainWindow::ConfirmSaveResult::Cancel:
                ok = false;
                break;
            case MainWindow::ConfirmSaveResult::SaveAll:
            case MainWindow::ConfirmSaveResult::Save:
                ok = save();
                if (!ok) {
                    const QString docName = QString::fromStdString(getDocument()->Label.getStrValue());
                    const QString text
                        = (!docName.isEmpty()
                               ? QObject::tr("Failed to save document '%1'. Would you like to cancel the closure?")
                                     .arg(docName)
                               : QObject::tr(
                                     "Document saving failed. Would you like to cancel the closure?"
                                 ));
                    int ret = QMessageBox::question(
                        getActiveView(),
                        QObject::tr("Unable to save document"),
                        text,
                        QMessageBox::Discard | QMessageBox::Cancel,
                        QMessageBox::Discard
                    );
                    if (ret == QMessageBox::Discard) {
                        ok = true;
                    }
                }
                break;
            case MainWindow::ConfirmSaveResult::DiscardAll:
            case MainWindow::ConfirmSaveResult::Discard:
                ok = true;
                break;
        }
    }

    if (ok) {
        // If a task dialog is open that doesn't allow other commands to modify
        // the document it must be closed by resetting the edit mode of the
        // corresponding view provider.
        if (!Gui::Control().isAllowedAlterDocument(getDocument())) {
            std::string name = Gui::Control().activeDialog(getDocument())->getDocumentName();
            if (name == this->getDocument()->getName()) {
                // getInEdit() only checks if the currently active MDI view is
                // a 3D view and that it is in edit mode. However, when closing a
                // document then the edit mode must be reset independent of the
                // active view.
                if (d->_editViewProvider) {
                    this->_resetEdit();
                }
            }
        }
    }

    return ok;
}

std::list<MDIView*> Document::getMDIViews(bool includePassive) const
{
    std::list<MDIView*> views;
    for (auto* v : d->baseViews) {
        auto view = dynamic_cast<MDIView*>(v);
        if (view) {
            views.push_back(view);
        }
    }

    if (includePassive) {
        for (auto* v : d->passiveViews) {
            auto view = dynamic_cast<MDIView*>(v);
            if (view) {
                views.push_back(view);
            }
        }
    }

    return views;
}

std::list<MDIView*> Document::getMDIViewsOfType(const Base::Type& typeId, bool includePassive) const
{
    std::list<MDIView*> views;
    for (auto* v : d->baseViews) {
        auto view = dynamic_cast<MDIView*>(v);
        if (view && view->isDerivedFrom(typeId)) {
            views.push_back(view);
        }
    }

    if (includePassive) {
        for (auto* v : d->passiveViews) {
            auto view = dynamic_cast<MDIView*>(v);
            if (view && view->isDerivedFrom(typeId)) {
                views.push_back(view);
            }
        }
    }

    return views;
}

/// send messages to the active view
bool Document::sendMsgToViews(const char* pMsg)
{
    for (auto* v : d->baseViews) {
        if (v->onMsg(pMsg)) {
            return true;
        }
    }

    for (auto* v : d->passiveViews) {
        if (v->onMsg(pMsg)) {
            return true;
        }
    }

    return false;
}

bool Document::sendMsgToFirstView(const Base::Type& typeId, const char* pMsg)
{
    // first try the active view
    Gui::MDIView* view = getActiveView();
    if (view && view->isDerivedFrom(typeId)) {
        if (view->onMsg(pMsg)) {
            return true;
        }
    }

    // now try the other views
    std::list<Gui::MDIView*> views = getMDIViewsOfType(typeId);
    for (const auto& it : views) {
        if ((it != view) && it->onMsg(pMsg)) {
            return true;
        }
    }

    return false;
}

/// Getter for the active view
MDIView* Document::getActiveView() const
{
    // get the main window's active view
    MDIView* active = getMainWindow()->activeWindow();

    // get all MDI views of the document
    std::list<MDIView*> mdis = getMDIViews();

    // check whether the active view is part of this document
    bool ok = false;
    for (const auto& mdi : mdis) {
        if (mdi == active) {
            ok = true;
            break;
        }
    }

    if (ok) {
        return active;
    }

    // the active view is not part of this document, just use the last view
    const auto& windows = Gui::getMainWindow()->windows();
    for (auto rit = mdis.rbegin(); rit != mdis.rend(); ++rit) {
        // Some view is removed from window list for some reason, e.g. TechDraw
        // hidden page has view but not in the list. By right, the view will
        // self delete, but not the case for TechDraw, especially during
        // document restore.
        if (windows.contains(*rit) || (*rit)->isDerivedFrom<View3DInventor>()) {
            return *rit;
        }
    }
    return nullptr;
}

MDIView* Document::setActiveView(const ViewProviderDocumentObject* vp, Base::Type typeId)
{
    MDIView* view = nullptr;
    if (!vp) {
        view = getActiveView();
    }
    else {
        view = vp->getMDIView();
        if (!view) {
            auto obj = vp->getObject();
            if (!obj) {
                view = getActiveView();
            }
            else {
                auto linked = obj->getLinkedObject(true);
                if (linked != obj) {
                    auto vpLinked = freecad_cast<ViewProviderDocumentObject*>(
                        Application::Instance->getViewProvider(linked)
                    );
                    if (vpLinked) {
                        view = vpLinked->getMDIView();
                    }
                }

                if (!view && typeId.isBad()) {
                    MDIView* active = getActiveView();
                    if (active && active->containsViewProvider(vp)) {
                        view = active;
                    }
                    // FreeCAD-CH (ops#640, R6T-5): under the typed tabs the object's own tab's
                    // view, not the document's first 3D view (maybe another tab's)
                    else if (MDIView* tabView = DocumentTabs::viewOfObject(this, obj)) {
                        view = tabView;
                    }
                    else {
                        typeId = View3DInventor::getClassTypeId();
                    }
                }
            }
        }
    }

    if (!view || (!typeId.isBad() && !view->isDerivedFrom(typeId))) {
        view = nullptr;
        for (auto* v : d->baseViews) {
            if (v->isDerivedFrom<MDIView>() && (typeId.isBad() || v->isDerivedFrom(typeId))) {
                view = static_cast<MDIView*>(v);
                break;
            }
        }
    }

    if (!view && !typeId.isBad()) {
        view = createView(typeId);
    }

    if (view) {
        getMainWindow()->setActiveWindow(view);
    }

    return view;
}

/**
 * @brief Document::setActiveWindow
 * If this document is active and the view is part of it then it will be
 * activated. If the document is not active or if the view is already active
 * nothing is done.
 * @param view
 */
void Document::setActiveWindow(Gui::MDIView* view)
{
    // get the main window's active view
    MDIView* active = getMainWindow()->activeWindow();

    // view is already active
    if (active == view) {
        return;
    }

    // get all MDI views of the document
    std::list<MDIView*> mdis = getMDIViews();

    // this document is not active
    if (std::ranges::find(mdis, active) == mdis.end()) {
        return;
    }

    // the view is not part of the document
    if (std::ranges::find(mdis, view) == mdis.end()) {
        return;
    }

    getMainWindow()->setActiveWindow(view);
}

Gui::MDIView* Document::getViewOfNode(SoNode* node) const
{
    std::list<MDIView*> mdis = getMDIViewsOfType(View3DInventor::getClassTypeId());
    for (const auto& mdi : mdis) {
        auto view = static_cast<View3DInventor*>(mdi);
        if (view->getViewer()->searchNode(node)) {
            return mdi;
        }
    }

    return nullptr;
}

Gui::MDIView* Document::getViewOfViewProvider(const Gui::ViewProvider* vp) const
{
    return getViewOfNode(vp->getRoot());
}

Gui::MDIView* Document::getEditingViewOfViewProvider(Gui::ViewProvider* vp) const
{
    std::list<MDIView*> mdis = getMDIViewsOfType(View3DInventor::getClassTypeId());
    for (const auto& mdi : mdis) {
        auto view = static_cast<View3DInventor*>(mdi);
        View3DInventorViewer* viewer = view->getViewer();
        // there is only one 3d view which is in edit mode
        if (viewer->hasViewProvider(vp) && viewer->isEditingViewProvider()) {
            return mdi;
        }
    }

    return nullptr;
}

//--------------------------------------------------------------------------
// UNDO REDO transaction handling
//--------------------------------------------------------------------------
/** Open a new Undo transaction on the active document
 *  This method opens a new UNDO transaction on the active document. This transaction
 *  will later appear in the UNDO/REDO dialog with the name of the command. If the user
 *  recall the transaction everything changed on the document between OpenCommand() and
 *  CommitCommand will be undone (or redone). You can use an alternative name for the
 *  operation default is the command name.
 *  @see CommitCommand(),AbortCommand()
 */
int Document::openCommand(const char* sName)
{
    // FreeCAD-CH (ops#640): a transaction beside the open dialog's held step (double-click on
    // another feature, the row menu's or the context menu's Edit, Accept Merge) accepts the
    // dialog first, as in Onshape; refused (0) when the dialog stays
    if (d->_editHoldsStep && !acceptOpenStep()) {
        FC_LOG("Step held by the open dialog, ignore new command '" << (sName ? sName : "")
                                                                    << "'");
        return 0;
    }
    return getDocument()->openTransaction(App::TransactionName {.name = sName, .temporary = false});
}

void Document::commitCommand()
{
    // FreeCAD-CH (ops#640): beside the held step only the open dialog's own OK or Cancel
    // closes it. Any other commit belongs to an openCommand the lock refused, and
    // App::Document::commitTransaction() would commit the dialog's step behind the dialog
    if (d->_editHoldsStep && getDocument()->isStepLocked() && !dialogClosingStep()) {
        FC_LOG("Step held by the open dialog, ignore commitCommand()");
        return;
    }
    getDocument()->commitTransaction();
}

void Document::abortCommand()
{
    // FreeCAD-CH (ops#640): as commitCommand(); an abort would revert the dialog's step
    if (d->_editHoldsStep && getDocument()->isStepLocked() && !dialogClosingStep()) {
        FC_LOG("Step held by the open dialog, ignore abortCommand()");
        return;
    }
    getDocument()->abortTransaction();
}

bool Document::hasPendingCommand() const
{
    return getDocument()->hasPendingTransaction();
}

namespace
{
/** FreeCAD-CH (ops#640, hands-on R1, R1b): an open feature dialog's own undo history. The
 * dialog (PartDesignGui::TaskDlgFeatureParameters) keeps it and offers it as two actions among
 * its children, so that no header of the core names it: triggering one undoes or redoes the
 * dialog's last edit, its "names" property lists the edits (the newest first) and it is enabled
 * while there is one. A dialog without them has no history (Ctrl+Z does nothing). */
QAction* dialogHistoryAction(App::Document* doc, bool undo)
{
    TaskView::TaskDialog* dlg = Control().activeDialog(doc);
    if (!dlg) {
        return nullptr;
    }
    return dlg->findChild<QAction*>(
        QLatin1String(undo ? "FreeCAD-CH dialog undo" : "FreeCAD-CH dialog redo"),
        Qt::FindDirectChildrenOnly
    );
}

std::vector<std::string> dialogHistoryNames(App::Document* doc, bool undo)
{
    std::vector<std::string> names;
    if (QAction* action = dialogHistoryAction(doc, undo)) {
        if (action->isEnabled()) {
            for (const QString& name : action->property("names").toStringList()) {
                names.push_back(name.toStdString());
            }
        }
    }
    return names;
}
}  // namespace

/** FreeCAD-CH (ops#640): whether getUndoVector() (getRedoVector() for !undo) is not empty, read
 * without building it: Std_Undo's and Std_Redo's isActive() and the 3D view's onHasMsg() ask on
 * every refresh of the actions, and the list costs O(n^2) in App's positions. Declared where it
 * is called (not in Document.h, which hundreds of files include). */
bool Gui::hasUndoStep(const Gui::Document* doc, bool undo)
{
    if (!doc || !doc->getDocument()) {
        return false;
    }
    App::Document* appDoc = doc->getDocument();
    if (appDoc->isStepLocked()) {
        QAction* action = dialogHistoryAction(appDoc, undo);
        return action && action->isEnabled();
    }
    auto it = stepDocuments.find(doc);
    if (it == stepDocuments.end()) {
        return undo ? !doc->getUndoVector().empty() : !doc->getRedoVector().empty();
    }
    return it->second->isStep(undo, 0);
}

/** FreeCAD-CH (ops#640): whether the document's current edit started with nothing in its step:
 * an edit's booked "Edit X", not a new feature's "Make X" that already made the feature, nor a
 * restart's step with a move in it. Changes the edit then makes (Visibility, the panels) aren't
 * counted. PartDesign's dialog history reads it (an OK that changed nothing aborts the step, which
 * would remove a new feature). Exported and declared where it is called, not in Document.h. */
bool Gui::editStartedUnchanged(const App::Document* doc)
{
    Gui::Document* guiDoc = doc && Application::Instance ? Application::Instance->getDocument(doc)
                                                         : nullptr;
    auto it = guiDoc ? stepDocuments.find(guiDoc) : stepDocuments.end();
    return it != stepDocuments.end() && it->second->_editStartedUnchanged;
}

/** FreeCAD-CH (ops#640, hands-on B5-5): a sketch's Cancel leaves no step, as in Onshape (no
 * history entry; Ctrl+Z then undoes the step before the edit). Called while the sketch session
 * is still open (ViewProviderSketch::unsetEdit): undoes the session's own transactions, all of
 * them at the top of App's undo stack (a pending one first), down to the session's start, and
 * takes the session's transactions off the Redo stack. The Redo stack before the edit is gone
 * once the session committed a change (a commit clears it); an edit that committed nothing keeps
 * it. Returns the number of transactions undone, or -1 when that can't be done exactly, with
 * nothing done: no session open, the document closing, the step locked, no undo stack (the limit 0, which drops every
 * transaction), the session's opener (a "New Sketch", a re-edit's "Double click" that changed
 * something) pending or on the stack, one of its transactions below another's, or one shared with
 * another document. The caller then restores the sketch its own way. Exported and declared where
 * it is called, not in Document.h. */
int Gui::undoOpenSketchSession(const App::Document* doc)
{
    Gui::Document* guiDoc = doc && Application::Instance ? Application::Instance->getDocument(doc)
                                                         : nullptr;
    auto it = guiDoc ? stepDocuments.find(guiDoc) : stepDocuments.end();
    if (it == stepDocuments.end()) {
        return -1;
    }
    DocumentP* d = it->second;
    App::Document* appDoc = guiDoc->getDocument();
    if (d->_session == 0 || d->_isClosing || App::GetApplication().isClosingAll()
        || d->_undoSteps == 0 || appDoc->getMaxUndoStackSize() == 0 || appDoc->isStepLocked()
        || appDoc->isPerformingTransaction()) {
        return -1;
    }
    auto own = [d](int id) {
        return id != 0 && d->_sessionIds.contains(id);
    };
    // The session's own transactions, newest first; below them, nothing of the session's. One
    // that changed another object (a Variables panel edit) isn't the sketch's to undo.
    std::vector<int> ids;
    unsigned pos = 0;
    for (; own(appDoc->getTransactionID(true, pos)); ++pos) {
        if (d->_sessionForeignIds.contains(appDoc->getTransactionID(true, pos))) {
            return -1;
        }
        ids.push_back(appDoc->getTransactionID(true, pos));
    }
    for (int id = appDoc->getTransactionID(true, pos); id != 0;
         id = appDoc->getTransactionID(true, ++pos)) {
        if (own(id) || id == d->_sessionOpener) {
            return -1;
        }
    }
    for (App::Document* other : App::GetApplication().getDocuments()) {
        if (other == appDoc) {
            continue;
        }
        for (int id : ids) {
            if (other->getAvailableUndos(id) != 0) {
                return -1;
            }
        }
    }

    if (!ids.empty()) {
        Base::FlagToggler<> flag(d->_isTransacting);
        // One undo down to the oldest (App's undo(id)), as Gui::Document::undo() does
        appDoc->undo(ids.back());
        App::GetApplication().signalUndo();
    }
    // Off the Redo stack: an empty transaction opened at once clears it, and its abort leaves no
    // step (as Sketcher's ConflictRefusal does)
    bool sessionRedo = false;
    for (unsigned redo = 0; !sessionRedo; ++redo) {
        const int id = appDoc->getTransactionID(false, redo);
        if (id == 0) {
            break;
        }
        sessionRedo = own(id);
    }
    if (sessionRedo && !appDoc->hasPendingTransaction()
        && appDoc->openTransaction("Cancel sketch editing") != 0) {
        App::Transaction::openPendingTransaction(*appDoc);
        appDoc->abortTransaction();
    }
    return static_cast<int>(ids.size());
}

/// Get a string vector with the 'Undo' actions
std::vector<std::string> Document::getUndoVector() const
{
    // FreeCAD-CH (ops#640): one name per step: an open dialog's own edits (hands-on R1), a closed
    // sketch session as one, an open one's own transactions only (regen-plan item 7)
    if (getDocument()->isStepLocked()) {
        return dialogHistoryNames(getDocument(), true);
    }
    return d->stepNames(true);
}

/// Get a string vector with the 'Redo' actions
std::vector<std::string> Document::getRedoVector() const
{
    if (getDocument()->isStepLocked()) {  // FreeCAD-CH (ops#640): as getUndoVector()
        return dialogHistoryNames(getDocument(), false);
    }
    return d->stepNames(false);
}

bool Document::checkTransactionID(bool undo, int iSteps)
{
    if (!iSteps) {
        return false;
    }

    std::vector<int> ids;
    for (int i = 0; i < iSteps; i++) {
        int id = getDocument()->getTransactionID(undo, i);
        if (!id) {
            break;
        }
        ids.push_back(id);
    }
    std::set<App::Document*> prompts;
    std::map<App::Document*, int> dmap;
    for (auto doc : App::GetApplication().getDocuments()) {
        if (doc == getDocument()) {
            continue;
        }
        for (auto id : ids) {
            int steps = undo ? doc->getAvailableUndos(id) : doc->getAvailableRedos(id);
            if (!steps) {
                continue;
            }
            int& currentSteps = dmap[doc];
            if (currentSteps + 1 != steps) {
                prompts.insert(doc);
            }
            if (currentSteps < steps) {
                currentSteps = steps;
            }
        }
    }
    if (!prompts.empty()) {
        std::ostringstream str;
        int i = 0;
        for (auto doc : prompts) {
            if (i++ == 5) {
                str << "...\n";
                break;
            }
            str << "    " << doc->getName() << "\n";
        }
        int ret = QMessageBox::warning(
            getMainWindow(),
            undo ? QObject::tr("Undo") : QObject::tr("Redo"),
            QStringLiteral("%1,\n%2%3")
                .arg(
                    QObject::tr(
                        "There are grouped transactions in the following documents with "
                        "other preceding transactions"
                    ),
                    QString::fromStdString(str.str()),
                    QObject::tr(
                        "Choose 'Yes' to roll back all preceding transactions.\n"
                        "Choose 'No' to roll back in the active document only.\n"
                        "Choose 'Abort' to abort"
                    )
                ),
            QMessageBox::Yes | QMessageBox::No | QMessageBox::Abort,
            QMessageBox::Yes
        );
        if (ret == QMessageBox::Abort) {
            return false;
        }
        if (ret == QMessageBox::No) {
            return true;
        }
    }
    for (auto& v : dmap) {
        for (int i = 0; i < v.second; ++i) {
            if (undo) {
                v.first->undo();
            }
            else {
                v.first->redo();
            }
        }
    }
    return true;
}

bool Document::isPerformingTransaction() const
{
    return d->_isTransacting;
}

/// Will UNDO one or more steps
void Document::undo(int iSteps)
{
    // FreeCAD-CH (ops#640, hands-on R1): with a feature dialog open, Ctrl+Z steps back through
    // the dialog's own edits and never past its start (App's undo() refuses the dialog's step)
    if (getDocument()->isStepLocked()) {
        QAction* action = dialogHistoryAction(getDocument(), true);
        for (int i = 0; action && i < iSteps && action->isEnabled(); i++) {
            action->trigger();
        }
        return;
    }
    // FreeCAD-CH (ops#640, rank 59): a step made in another typed tab is undone in that tab;
    // refused when an open dialog refuses the switch (F6-3)
    if (!DocumentTabs::undoAllowed(this, true)) {
        return;
    }
    Base::FlagToggler<> flag(d->_isTransacting);

    // FreeCAD-CH (ops#640, regen-plan item 7): a step is one transaction, or a closed sketch
    // session's; inside an open session one of its own, none past its start
    const int transactions = d->transactionsOfSteps(true, iSteps);
    if (!checkTransactionID(true, transactions)) {
        return;
    }

    // One undo down to the oldest of them (App's undo(id)): the model regenerates once, after
    // the last, not once per transaction of a closed sketch session
    const int oldest = getDocument()->getTransactionID(true, static_cast<unsigned>(transactions - 1));
    if (oldest != 0) {
        getDocument()->undo(oldest);
    }
    App::GetApplication().signalUndo();
}

/// Will REDO one or more steps
void Document::redo(int iSteps)
{
    if (getDocument()->isStepLocked()) {  // FreeCAD-CH (ops#640): as undo()
        QAction* action = dialogHistoryAction(getDocument(), false);
        for (int i = 0; action && i < iSteps && action->isEnabled(); i++) {
            action->trigger();
        }
        return;
    }
    if (!DocumentTabs::undoAllowed(this, false)) {  // FreeCAD-CH (ops#640, rank 59): as undo()
        return;
    }
    Base::FlagToggler<> flag(d->_isTransacting);

    const int transactions = d->transactionsOfSteps(false, iSteps);  // FreeCAD-CH: as undo()
    if (!checkTransactionID(false, transactions)) {
        return;
    }

    const int newest = getDocument()->getTransactionID(false, static_cast<unsigned>(transactions - 1));
    if (newest != 0) {
        getDocument()->redo(newest);
    }
    App::GetApplication().signalRedo();

    for (auto it : d->_redoViewProviders) {
        handleChildren3D(it);
    }
    d->_redoViewProviders.clear();
}

PyObject* Document::getPyObject()
{
    _pcDocPy->IncRef();
    return _pcDocPy;
}

void Document::handleChildren3D(ViewProvider* viewProvider, bool deleting)
{
    // check for children
    if (viewProvider && viewProvider->getChildRoot()) {
        std::vector<App::DocumentObject*> children = viewProvider->claimChildren3D();
        SoGroup* childGroup = viewProvider->getChildRoot();
        SoGroup* frontGroup = viewProvider->getFrontRoot();
        SoGroup* backGroup = viewProvider->getFrontRoot();

        // size not the same -> build up the list new
        if (deleting || childGroup->getNumChildren() != static_cast<int>(children.size())) {

            std::set<ViewProviderDocumentObject*> oldChildren;
            for (int i = 0, count = childGroup->getNumChildren(); i < count; ++i) {
                auto it = d->_CoinMap.find(static_cast<SoSeparator*>(childGroup->getChild(i)));
                if (it == d->_CoinMap.end()) {
                    continue;
                }
                oldChildren.insert(it->second);
            }

            Gui::coinRemoveAllChildren(childGroup);
            Gui::coinRemoveAllChildren(frontGroup);
            Gui::coinRemoveAllChildren(backGroup);

            if (!deleting) {
                for (const auto& it : children) {
                    if (auto ChildViewProvider
                        = dynamic_cast<ViewProviderDocumentObject*>(getViewProvider(it))) {
                        auto itOld = oldChildren.find(ChildViewProvider);
                        if (itOld != oldChildren.end()) {
                            oldChildren.erase(itOld);
                        }

                        if (SoSeparator* childRootNode = ChildViewProvider->getRoot()) {
                            if (childRootNode == childGroup) {
                                Base::Console().warning(
                                    "Document::handleChildren3D: Do not add "
                                    "group of '%s' to itself\n",
                                    it->getNameInDocument()
                                );
                            }
                            else if (childGroup) {
                                childGroup->addChild(childRootNode);
                            }
                        }

                        if (SoSeparator* childFrontNode = ChildViewProvider->getFrontRoot()) {
                            if (childFrontNode == frontGroup) {
                                Base::Console().warning(
                                    "Document::handleChildren3D: Do not add "
                                    "foreground group of '%s' to itself\n",
                                    it->getNameInDocument()
                                );
                            }
                            else if (frontGroup) {
                                frontGroup->addChild(childFrontNode);
                            }
                        }

                        if (SoSeparator* childBackNode = ChildViewProvider->getBackRoot()) {
                            if (childBackNode == backGroup) {
                                Base::Console().warning(
                                    "Document::handleChildren3D: Do not add "
                                    "background group of '%s' to itself\n",
                                    it->getNameInDocument()
                                );
                            }
                            else if (backGroup) {
                                backGroup->addChild(childBackNode);
                            }
                        }

                        // cycling to all views of the document to remove the viewprovider from the
                        // viewer itself
                        for (Gui::BaseView* vIt : d->baseViews) {
                            auto activeView = dynamic_cast<View3DInventor*>(vIt);
                            if (activeView
                                && activeView->getViewer()->hasViewProvider(ChildViewProvider)) {
                                // @Note hasViewProvider()
                                // remove the viewprovider serves the purpose of detaching the
                                // inventor nodes from the top level root in the viewer. However, if
                                // some of the children were grouped beneath the object earlier they
                                // are not anymore part of the toplevel inventor node. we need to
                                // check for that.
                                activeView->getViewer()->removeViewProvider(ChildViewProvider);
                            }
                        }
                    }
                }
            }

            // add the remaining old children back to toplevel invertor node
            for (auto vpd : oldChildren) {
                auto obj = vpd->getObject();
                if (!obj || !obj->isAttachedToDocument()) {
                    continue;
                }

                for (BaseView* view : d->baseViews) {
                    auto activeView = dynamic_cast<View3DInventor*>(view);
                    if (activeView && !activeView->getViewer()->hasViewProvider(vpd)) {
                        activeView->getViewer()->addViewProvider(vpd);
                    }
                }
            }
        }
    }
}

void Document::toggleInSceneGraph(ViewProvider* vp)
{
    // FIXME: What's the point of having this function?
    //
    for (auto view : d->baseViews) {
        auto activeView = dynamic_cast<View3DInventor*>(view);
        if (!activeView) {
            continue;
        }

        auto root = vp->getRoot();
        if (!root) {
            continue;
        }

        auto scenegraph = dynamic_cast<SoGroup*>(activeView->getViewer()->getSceneGraph());
        if (!scenegraph) {
            continue;
        }

        // If it cannot be added then only check the top-level nodes
        if (!vp->canAddToSceneGraph()) {
            int idx = scenegraph->findChild(root);
            if (idx >= 0) {
                scenegraph->removeChild(idx);
            }
        }
        // FreeCAD-CH (ops#640, rank 59): not into a typed tab's view that doesn't show it
        else if (DocumentTabs::accepts(activeView->getViewer(), vp)) {
            // Do a deep search of the scene because the root node
            // isn't necessarily a top-level node when claimed by
            // another view provider.
            // This is to avoid to add a node twice to the scene.
            SoSearchAction sa;
            sa.setNode(root);
            sa.setSearchingAll(false);
            sa.apply(scenegraph);

            SoPath* path = sa.getPath();
            if (!path) {
                scenegraph->addChild(root);
            }
        }
    }
}

void Document::slotChangePropertyEditor(const App::Document& doc, const App::Property& Prop)
{
    if (getDocument() == &doc) {
        FC_LOG(Prop.getFullName() << " editor changed");
        setModified(true);
        getMainWindow()->setUserSchema(doc.UnitSystem.getValue());
    }
}

std::vector<App::DocumentObject*> Document::getTreeRootObjects() const
{
    std::vector<App::DocumentObject*> docObjects = d->_pcDocument->getObjects();
    std::unordered_map<App::DocumentObject*, bool> rootMap;
    for (auto it : docObjects) {
        rootMap[it] = true;
    }

    for (auto obj : docObjects) {
        ViewProvider* vp = Application::Instance->getViewProvider(obj);
        if (!vp) {
            continue;
        }

        std::vector<App::DocumentObject*> children = vp->claimChildren();
        for (auto child : children) {
            rootMap[child] = false;
        }
    }

    // FreeCAD-CH (ops#640): in document order, as the tree shows them; the map's order is its
    // pointers' hash order, which any change in allocation reshuffles
    std::vector<App::DocumentObject*> rootObjs;
    for (auto obj : docObjects) {
        if (rootMap[obj]) {
            rootObjs.push_back(obj);
        }
    }
    return rootObjs;
}
