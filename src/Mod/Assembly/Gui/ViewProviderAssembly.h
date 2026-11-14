// SPDX-License-Identifier: LGPL-2.1-or-later
/****************************************************************************
 *                                                                          *
 *   Copyright (c) 2023 Ondsel <development@ondsel.com>                     *
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 *   FreeCAD is distributed in the hope that it will be useful, but         *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
 *   Lesser General Public License for more details.                        *
 *                                                                          *
 *   You should have received a copy of the GNU Lesser General Public       *
 *   License along with FreeCAD. If not, see                                *
 *   <https://www.gnu.org/licenses/>.                                       *
 *                                                                          *
 ***************************************************************************/

#pragma once

#include <QCoreApplication>
#include <QMetaObject>
#include <QPointer>
#include <fastsignals/signal.h>

#include <Mod/Assembly/AssemblyGlobal.h>

#include <Gui/Selection/Selection.h>
#include <Gui/ViewProviderPart.h>

class QLineEdit;
class SoSwitch;
class SoSensor;
class SoDragger;
class SoFieldSensor;

namespace Gui
{
class SoTransformDragger;
class View3DInventorViewer;
}  // namespace Gui

namespace AssemblyGui
{
class TaskAssemblyMessages;

struct MovingObject
{
    App::DocumentObject* obj;  // moving part
    Base::Placement plc;
    App::PropertyXLinkSub* ref;
    App::DocumentObject* rootObj;  // object of the selection object
    const std::string sub;         // sub name given by the selection.

    // Constructor
    MovingObject(
        App::DocumentObject* o,
        const Base::Placement& p,
        App::DocumentObject* ro,
        const std::string& s
    )
        : obj(o)
        , plc(p)
        , ref(nullptr)
        , rootObj(ro)
        , sub(s)
    {}

    // Default constructor
    MovingObject()
        : obj(nullptr)
        , ref(nullptr)
        , rootObj(nullptr)
    {}

    ~MovingObject()
    {}
};

class AssemblyGuiExport ViewProviderAssembly: public Gui::ViewProviderPart,
                                              public Gui::SelectionObserver
{
    Q_DECLARE_TR_FUNCTIONS(AssemblyGui::ViewProviderAssembly)
    PROPERTY_HEADER_WITH_OVERRIDE(AssemblyGui::ViewProviderAssembly);

    enum class DragMode
    {
        Translation,
        TranslationNoSolve,
        TranslationOnAxis,
        TranslationOnPlane,
        Rotation,
        RotationOnPlane,
        TranslationOnAxisAndRotationOnePlane,
        Ball,
        None,
    };

public:
    enum class IsolateMode
    {
        Transparent,
        Wireframe,
        Hidden,
    };

    ViewProviderAssembly();
    ~ViewProviderAssembly() override;

    /// deliver the icon shown in the tree view. Override from ViewProvider.h
    QIcon getIcon() const override;

    bool doubleClicked() override;
    void setupContextMenu(QMenu* menu, QObject* receiver, const char* member) override;
    bool onDelete(const std::vector<std::string>& subNames) override;
    bool canDelete(App::DocumentObject* obj) const override;

    void updateData(const App::Property*) override;

    /** @name enter/exit edit mode */
    //@{
    bool setEdit(int ModNum) override;
    void unsetEdit(int ModNum) override;
    void setEditViewer(Gui::View3DInventorViewer*, int ModNum) override;
    bool isInEditMode() const;

    /// Ask the view provider if it accepts object deletions while in edit
    bool acceptDeletionsInEdit() override
    {
        return true;
    }

    bool canDragObject(App::DocumentObject*) const override;
    bool canDragObjectToTarget(App::DocumentObject* obj, App::DocumentObject* target) const override;

    App::DocumentObject* getActivePart() const;


    /// is called when the Provider is in edit and a key event ocours. Only ESC ends edit.
    bool keyPressed(bool pressed, int key) override;
    /// is called when the provider is in edit and the mouse is moved
    bool mouseMove(const SbVec2s& cursorPos, Gui::View3DInventorViewer* viewer) override;
    /// is called when the Provider is in edit and the mouse is clicked
    bool mouseButtonPressed(
        int Button,
        bool pressed,
        const SbVec2s& cursorPos,
        const Gui::View3DInventorViewer* viewer
    ) override;
    // Function to handle double click event
    void doubleClickedIn3dView();


    /// Finds what drag mode should be used based on the user selection.
    DragMode findDragMode();
    void initMove(const SbVec2s& cursorPos, Gui::View3DInventorViewer* viewer);
    void endMove();
    virtual void setEnableMovement(bool enable = true)
    {
        enableMovement = enable;
    }
    virtual bool getEnableMovement() const
    {
        return enableMovement;
    }
    virtual void setMoveOnlyPreselected(bool enable = true)
    {
        moveOnlyPreselected = enable;
    }
    virtual bool getMoveOnlyPreselected() const
    {
        return moveOnlyPreselected;
    }
    virtual void setMoveInCommand(bool enable = true)
    {
        moveInCommand = enable;
    }
    virtual bool getMoveInCommand() const
    {
        return moveInCommand;
    }


    bool canDragObjectIn3d(App::DocumentObject* obj) const;
    bool getSelectedObjectsWithinAssembly(bool addPreselection = true, bool onlySolids = false);
    App::DocumentObject* getSelectedJoint();

    /// Get the python wrapper for that ViewProvider
    PyObject* getPyObject() override;

    // protected:
    /// get called by the container whenever a property has been changed
    // void onChanged(const App::Property* prop) override;

    void onSelectionChanged(const Gui::SelectionChanges& msg) override;

    // Dragger controls:
    /// Shows the triad: at @a pickedPoint (global) when given, else the selection's bounding box centre
    void initMoveDragger(const Base::Vector3d* pickedPoint = nullptr);
    void endMoveDragger();
    static void draggerMotionCallback(void* data, SoDragger* d);
    // FreeCAD-CH (ops#640, C8): Onshape's typed triad moves (notes/assemblies-design.md 4b)
    static void draggerStartCallback(void* data, SoDragger* d);
    static void draggerFinishCallback(void* data, SoDragger* d);
    enum class TriadHandle
    {
        None,
        TranslateX,
        TranslateY,
        TranslateZ,
        RotateX,
        RotateY,
        RotateZ,
        Plane,
    };
    /// A drag of @a handle starts: opens the undo step and remembers where the triad was
    void beginTriadDrag(TriadHandle handle);
    /// Puts the shown triad at @a triad (global) and moves the parts with it, exactly (no float
    /// rounding), as a drag of the dragger's fields to @a triad would
    void moveTriadTo(const Base::Placement& triad);
    /// The drag ends: commits its undo step, aligns the triad with the assembly's axes again and,
    /// for an arrow or a ring, opens the value box
    void endTriadDrag();
    /// FreeCAD-CH (ops#640, C10): moves the triad alone to @a point (global), on the assembly's
    /// axes; the parts stay where they are, and a ring then turns them about @a point
    void moveTriadOriginTo(const Base::Vector3d& point);
    /// Where a pick of @a subName (under @a root, the element included) at @a cursor (global) puts
    /// the triad's origin: an open edge's end close to the cursor (the Transform dialog's snap), else
    /// the cursor
    Base::Vector3d triadOriginPick(
        App::DocumentObject* root,
        const std::string& subName,
        const Base::Vector3d& cursor
    ) const;
    TriadHandle getTriadHandle() const
    {
        return triadHandle;
    }
    /// The distance (mm) or angle (degrees) the last arrow or ring drag moved, from where it started
    double getTriadValue() const;
    /// A typed value: the move becomes exactly @a text (an expression) from where the drag started,
    /// in one undo step. False, with the box kept open and marked, if it doesn't evaluate.
    bool applyTriadValue(const std::string& text);
    bool isTriadBoxOpen() const;
    QLineEdit* getTriadBox() const;
    void closeTriadBox();
    /// The triad as shown (global): aligned with the assembly's axes except during a ring drag
    Base::Placement getTriadPlacement() const
    {
        return triadShownPlc;
    }

    void setDragger();
    void unsetDragger();
    void setDraggerVisibility(bool val);
    bool getDraggerVisibility();
    void setDraggerPlacement(Base::Placement plc);
    Base::Placement getDraggerPlacement();
    Gui::SoTransformDragger* getDragger();

    static Base::Vector3d getCenterOfBoundingBox(const std::vector<MovingObject>& movingObjs);

    void UpdateSolverInformation();

    void isolateComponents(std::set<App::DocumentObject*>& parts, IsolateMode mode);
    void isolateJointReferences(App::DocumentObject* joint, IsolateMode mode = IsolateMode::Transparent);
    void clearIsolate();
    bool explodeTemporarily(App::DocumentObject* explodedView);
    void clearTemporaryExplosion();

    DragMode dragMode;
    bool canStartDragging;
    bool partMoving;
    bool enableMovement;
    bool moveOnlyPreselected;
    bool moveInCommand;
    bool ctrlPressed;
    bool forceSolveOnMoveForRigid;

    long lastClickTime;  // Store last click time as milliseconds
    // C10: Alt (Option on a Mac) held, as the viewer's key events tell it; a press it took moved
    // the triad alone, and its release is taken too
    bool triadAltHeld = false;
    bool triadOriginPress = false;
    // C10: the viewer whose selection is off from that press to its release (its selection
    // root selects on the release, before this view provider sees it)
    QPointer<Gui::View3DInventorViewer> triadOriginViewer;
    void endTriadOriginPress();

    int numberOfSel;
    Base::Vector3d prevPosition;
    Base::Vector3d initialPosition;
    Base::Vector3d initialPositionRot;
    Base::Placement jcsPlc;
    Base::Placement jcsGlobalPlc;
    Base::Placement draggerInitPlc;

    App::DocumentObject* movingJoint;

    std::vector<std::pair<App::DocumentObject*, bool>> jointVisibilitiesBackup;
    std::vector<std::pair<App::DocumentObject*, double>> objectMasses;
    std::vector<MovingObject> docsToMove;

    Gui::SoTransformDragger* asmDragger = nullptr;
    SoSwitch* asmDraggerSwitch = nullptr;
    SoFieldSensor* translationSensor = nullptr;
    SoFieldSensor* rotationSensor = nullptr;

    fastsignals::signal<
        void(const QString& state, const QString& msg, const QString& url, const QString& linkText)>
        signalSetUp;

private:
    // FreeCAD-CH (ops#640, C8)
    TriadHandle triadHandleOf(SoDragger* child) const;
    void setTriadCallbacks(bool on);
    Base::Placement triadTarget(TriadHandle handle, double value) const;
    void openTriadBox();
    void showTriadAt(const Base::Placement& plc);
    bool pressIsOnTriad(const SbVec2s& cursorPos, const Gui::View3DInventorViewer* viewer) const;
    void restoreTriadAfterMove();
    TriadHandle triadHandle = TriadHandle::None;
    /// The triad as shown: at triadPlc's origin, aligned with the assembly's axes between drags
    Base::Placement triadShownAt(const Base::Placement& plc) const;
    Base::Placement triadPlc;               // the parts' move, as a placement (global, exact)
    Base::Placement triadShownPlc;          // the triad as shown (global, exact)
    Base::Placement triadDragStartPlc;      // triadPlc when the last drag started
    Base::Placement triadDragStartShown;    // triadShownPlc then: the handles' axes
    Base::Placement triadDragStartFields;   // the dragger's single-precision fields then
    bool triadDragging = false;
    QPointer<QLineEdit> triadBox;
    // A body drag that starts while the triad is shown hides it; it comes back moved with the part
    bool triadShownBeforeMove = false;
    App::DocumentObject* triadAnchor = nullptr;
    Base::Placement triadAnchorPlc;

    bool tryMouseMove(const SbVec2s& cursorPos, Gui::View3DInventorViewer* viewer);
    void tryInitMove(const SbVec2s& cursorPos, Gui::View3DInventorViewer* viewer);

    // FreeCAD-CH (ops#683, C4): the triad moves what the mouse drag moves
    void addPartsJoinedToMoving();

    void collectMovableObjects(
        App::DocumentObject* selRoot,
        const std::string& subNamePrefix,
        App::DocumentObject* currentObject,
        bool onlySolids
    );

    void slotAboutToOpenTransaction(const std::string& cmdName);
    void slotActivatedVP(const Gui::ViewProviderDocumentObject* vp, const char* name);

    void onWorkbenchActivated(const QString& name);
    void updateTaskPanel(bool show);

    struct ComponentState
    {
        bool visibility;
        bool selectable;
        // For Links
        bool overrideMaterial;
        App::Material shapeMaterial;
    };

    std::unordered_map<App::DocumentObject*, ComponentState> stateBackup;
    App::DocumentObject* temporaryExplosion {nullptr};
    App::DocumentObject* isolatedJoint {nullptr};
    bool isolatedJointVisibilityBackup {false};

    void highlightJointElements(App::DocumentObject* joint);
    void clearJointElementHighlight();
    /// Drops the connections setEdit() makes (FreeCAD-CH, ops#651)
    void disconnectEditSignals();

    void applyIsolationRecursively(
        App::DocumentObject* current,
        std::set<App::DocumentObject*>& isolateSet,
        IsolateMode mode,
        std::set<App::DocumentObject*>& visited
    );

    // A QPointer: the task panel deletes its contextual panels when its dialog closes (ops#640)
    QPointer<TaskAssemblyMessages> taskSolver;
    // The document taskSolver joined, set with it: removeContextualPanel()'s key (R7A-1)
    App::Document* taskSolverDoc = nullptr;

    QMetaObject::Connection workbenchConnection;
    QMetaObject::Connection taskViewConnection;
    fastsignals::connection connectActivatedVP;
    fastsignals::connection connectSolverUpdate;
    fastsignals::scoped_connection m_preTransactionConn;
};

}  // namespace AssemblyGui
