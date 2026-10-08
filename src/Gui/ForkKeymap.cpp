// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ForkKeymap.h"

#include <algorithm>
#include <cstring>
#include <iterator>
#include <map>
#include <string>

#include <QKeySequence>
#include <QPointer>
#include <QWidget>

#include <App/Application.h>

#include "Action.h"
#include "Application.h"
#include "Command.h"
#include "MainWindow.h"
#include "ShortcutManager.h"

namespace Gui::ForkKeymap
{

namespace
{

struct Entry
{
    const char* name;
    /// The fork's key; "" takes upstream's away
    const char* key;
};

/// An action of a command's group that isn't a command of its own, taking the key of  name
struct SubAction
{
    const char* group;
    int index;
    const char* name;
    const char* upstream;
};

// Onshape's keys (notes/onshape-shortcuts.md section 2; PLAN.md decision 27). A command Onshape has
// a key for but FreeCAD lacks comes with it (ops#194 PR B: Space, P, Shift+H, Shift+I, the arrows).
// The other entries take away a key an Onshape key needs: one FreeCAD gave a command, or a chord
// starting with an Onshape key (it would make that key wait ShortcutTimeout for the chord).
const Entry table[] = {
    // General and Part Studio
    {"Std_Measure", "["},
    {"PartDesign_NewSketch", "Shift+S"},
    {"PartDesign_Pad", "Shift+E"},
    {"PartDesign_Revolution", "Shift+W"},
    {"PartDesign_Fillet", "Shift+F"},
    {"Std_BoxElementSelection", ""},
    {"Std_FreezeViews", ""},
    {"Std_ClarifySelection", ""},  // the context menu and long-press stay
    // 3D view
    {"Std_ViewFront", "Shift+1"},
    {"Std_ViewRear", "Shift+2"},
    {"Std_ViewLeft", "Shift+3"},
    {"Std_ViewRight", "Shift+4"},
    {"Std_ViewTop", "Shift+5"},
    {"Std_ViewBottom", "Shift+6"},
    {"Std_ViewIsometric", "Shift+7"},
    {"Std_ViewFitAll", "F"},
    {"Std_ViewZoomOut", "Z"},
    {"Std_ViewZoomIn", "Shift+Z"},
    {"Std_ViewBoxZoom", "W"},
    {"Std_HideSelection", "Y"},
    {"Std_ShowObjects", "Shift+Y"},
    {"Std_ToggleTransparency", "Shift+T"},
    {"Std_ToggleClipPlane", "Shift+X"},
    {"Std_ViewFitSelection", ""},
    {"Std_OrthographicCamera", ""},
    {"Std_PerspectiveCamera", ""},
    {"Std_ViewDock", ""},
    {"Std_ViewUndock", ""},
    {"Std_DrawStyleAsIs", ""},
    {"Std_DrawStylePoints", ""},
    {"Std_DrawStyleWireframe", ""},
    {"Std_DrawStyleHiddenLine", ""},
    {"Std_DrawStyleNoShading", ""},
    {"Std_DrawStyleShaded", ""},
    {"Std_DrawStyleFlatLines", ""},
    {"Std_AxisCross", ""},
    {"Std_TreeSelection", ""},
    {"Std_TreeSyncView", ""},
    {"Std_TreeSyncSelection", ""},
    {"Std_TreeSyncPlacement", ""},
    {"Std_TreePreSelection", ""},
    {"Std_TreeRecordSelection", ""},
    {"Std_TreeDrag", ""},
    {"Std_DockOverlayMouseTransparent", ""},
    // The Part selection filters: off their chords (C, E, X and F are Onshape keys)
    {"Part_VertexSelection", "Shift+Alt+V"},
    {"Part_EdgeSelection", "Shift+Alt+E"},
    {"Part_FaceSelection", "Shift+Alt+F"},
    {"Part_RemoveSelectionGate", "Shift+Alt+C"},
    // Sketch tools
    {"Sketcher_CreatePolyline", "L"},  // Onshape's line chains segments
    {"Sketcher_Create3PointArc", "A"},
    {"Sketcher_CreateCircle", "C"},
    {"Sketcher_CreateRectangle", "G"},
    {"Sketcher_CreatePoint", "Shift+S"},
    {"Sketcher_CreateFillet", "Shift+F"},
    {"Sketcher_Offset", "O"},
    {"Sketcher_Extend", "X"},
    {"Sketcher_Intersection", "Shift+G"},
    {"Sketcher_ToggleConstruction", "Q"},
    {"Sketcher_ViewSketch", "N"},
    {"Sketcher_ViewSection", ""},
    // Sketch constraints
    {"Sketcher_Dimension", "D"},
    {"Sketcher_ConstrainCoincidentUnified", "I"},
    {"Sketcher_ConstrainEqual", "E"},
    {"Sketcher_ConstrainHorizontal", "H"},
    {"Sketcher_ConstrainVertical", "V"},
    {"Sketcher_ConstrainParallel", "B"},
    {"Sketcher_ConstrainPerpendicular", "Shift+L"},
    {"Sketcher_ConstrainTangent", "T"},
    {"Sketcher_ConstrainSymmetric", "Shift+Q"},
    {"Sketcher_ConstrainBlock", "Shift+J"},
    {"Sketcher_ConstrainCoincident", ""},
    {"Sketcher_ConstrainPointOnObject", ""},
    {"Sketcher_ConstrainDistanceX", ""},
    {"Sketcher_ConstrainDistanceY", ""},
    {"Sketcher_ConstrainHorVer", ""},
    {"Sketcher_CompConstrainRadDia", ""},
    {"Sketcher_Translate", ""},
    // R, M and U (centre rectangle, trim, use) wait for PR D, which moves the sketch tools' own
    // keys (M, U, J, R, F) off them first: a geometry tool stays enabled while another runs, so its
    // key would take the running tool's (ops#194 PR D). Until then they have no key (their chords
    // start with G).
    {"Sketcher_CreateRectangle_Center", ""},
    {"Sketcher_Trimming", ""},
    {"Sketcher_Projection", ""},
    // The G, ... and Z, ... chords of the sketch tools Onshape has no key for
    {"Sketcher_CompLine", ""},
    {"Sketcher_CreateLine", ""},
    {"Sketcher_CompCreateArc", ""},
    {"Sketcher_CreateArc", ""},
    {"Sketcher_CreateArcOfEllipse", ""},
    {"Sketcher_CreateArcOfHyperbola", ""},
    {"Sketcher_CreateArcOfParabola", ""},
    {"Sketcher_CompCreateConic", ""},
    {"Sketcher_Create3PointCircle", ""},
    {"Sketcher_CreateEllipseByCenter", ""},
    {"Sketcher_CreateEllipseBy3Points", ""},
    {"Sketcher_CompCreateRectangles", ""},
    {"Sketcher_CreateOblong", ""},
    {"Sketcher_CompCreateRegularPolygon", ""},
    {"Sketcher_CreateTriangle", ""},
    {"Sketcher_CreateSquare", ""},
    {"Sketcher_CreatePentagon", ""},
    {"Sketcher_CreateHexagon", ""},
    {"Sketcher_CreateHeptagon", ""},
    {"Sketcher_CreateOctagon", ""},
    {"Sketcher_CreateRegularPolygon", ""},
    {"Sketcher_CompSlot", ""},
    {"Sketcher_CreateSlot", ""},
    {"Sketcher_CreateArcSlot", ""},
    {"Sketcher_CompCreateBSpline", ""},
    {"Sketcher_CreateBSpline", ""},
    {"Sketcher_CreatePeriodicBSpline", ""},
    {"Sketcher_CreateBSplineByInterpolation", ""},
    {"Sketcher_CreatePeriodicBSplineByInterpolation", ""},
    {"Sketcher_CompCreateFillets", ""},
    {"Sketcher_CreateChamfer", ""},
    {"Sketcher_CompCurveEdition", ""},
    {"Sketcher_Split", ""},
    {"Sketcher_CompExternal", ""},
    {"Sketcher_CarbonCopy", ""},
    {"Sketcher_SelectConstraints", ""},
    {"Sketcher_SelectOrigin", ""},
    {"Sketcher_SelectVerticalAxis", ""},
    {"Sketcher_SelectHorizontalAxis", ""},
    {"Sketcher_SelectRedundantConstraints", ""},
    {"Sketcher_SelectConflictingConstraints", ""},
    {"Sketcher_SelectElementsAssociatedWithConstraints", ""},
    {"Sketcher_SelectElementsWithDoFs", ""},
    {"Sketcher_RestoreInternalAlignmentGeometry", ""},
    {"Sketcher_Symmetry", ""},
    {"Sketcher_Copy", ""},
    {"Sketcher_Clone", ""},
    {"Sketcher_Move", ""},
    {"Sketcher_RectangularArray", ""},
    {"Sketcher_RemoveAxesAlignment", ""},
    {"Sketcher_Rotate", ""},
    {"Sketcher_Scale", ""},
    {"Sketcher_SwitchVirtualSpace", ""},
};

// The draw styles' and the Part selection filters' actions (CommandView.cpp, Part's
// CommandFilter.cpp): accel(name, upstream) when they are made, again here on a switch
const SubAction subActions[] = {
    {"Std_DrawStyle", 0, "Std_DrawStyleAsIs", "V,1"},
    {"Std_DrawStyle", 1, "Std_DrawStylePoints", "V,2"},
    {"Std_DrawStyle", 2, "Std_DrawStyleWireframe", "V,3"},
    {"Std_DrawStyle", 3, "Std_DrawStyleHiddenLine", "V,4"},
    {"Std_DrawStyle", 4, "Std_DrawStyleNoShading", "V,5"},
    {"Std_DrawStyle", 5, "Std_DrawStyleShaded", "V,6"},
    {"Std_DrawStyle", 6, "Std_DrawStyleFlatLines", "V,7"},
    {"Part_SelectFilter", 0, "Part_VertexSelection", "X,S"},
    {"Part_SelectFilter", 1, "Part_EdgeSelection", "E,S"},
    {"Part_SelectFilter", 2, "Part_FaceSelection", "F,S"},
    {"Part_SelectFilter", 3, "Part_RemoveSelectionGate", "C,S"},
};

// Commands whose key works where their toolbars are hidden: a sketch's edit mode hides Part
// Design's, and the toolbar manager's shortcut widget then drops their actions
const char* const reachable[] = {"PartDesign_Pad", "PartDesign_Revolution"};

const Entry* find(const char* name)
{
    if (!name) {
        return nullptr;
    }
    static const std::map<std::string, const Entry*> index = [] {
        std::map<std::string, const Entry*> map;
        for (const auto& entry : table) {
            map[entry.name] = &entry;
        }
        return map;
    }();
    auto it = index.find(name);
    return it == index.end() ? nullptr : it->second;
}

bool readPreference()
{
    auto hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Shortcut/Settings"
    );
    return hGrp->GetASCII("Keymap", "Onshape") != "FreeCAD";
}

bool& onshape()
{
    static bool value = readPreference();
    return value;
}

/// The commands' own `sAccel`, as they registered, for a switch back to FreeCAD's keymap
std::map<std::string, std::string>& upstreamAccels()
{
    static std::map<std::string, std::string> map;
    return map;
}

}  // namespace

bool isOnshape()
{
    return onshape();
}

const char* accel(const char* name)
{
    if (!onshape()) {
        return nullptr;
    }
    const Entry* entry = find(name);
    return entry ? entry->key : nullptr;
}

const char* accel(const char* name, const char* upstream)
{
    const char* key = accel(name);
    return key ? key : upstream;
}

void applyTo(Command* cmd)
{
    // A Python command's key is its resource, which PythonCommand::getAccel() looks up itself
    if (!cmd || dynamic_cast<PythonCommand*>(cmd) || dynamic_cast<PythonGroupCommand*>(cmd)
        || dynamic_cast<MacroCommand*>(cmd) || !find(cmd->getName())) {
        return;
    }
    const char* own = cmd->getAccel();
    const auto& upstream = upstreamAccels().try_emplace(cmd->getName(), own ? own : "").first->second;
    cmd->setAccel(accel(cmd->getName(), upstream.c_str()));
    // An action made before the command registered (e.g. Std_Measure's), or on a switch
    if (cmd->getAction()) {
        cmd->setShortcut(ShortcutManager::instance()->getShortcut(cmd->getName(), cmd->getAccel()));
    }
}

void actionCreated(Command* cmd)
{
    if (!onshape() || !cmd || !cmd->getAction()
        || std::none_of(std::begin(reachable), std::end(reachable), [cmd](const char* name) {
               return std::strcmp(name, cmd->getName()) == 0;
           })) {
        return;
    }
    static QPointer<QWidget> holder;
    if (!holder) {
        if (!getMainWindow()) {
            return;
        }
        // As ToolBarManager's action widget: zero size and out of the way, but shown
        holder = new QWidget(getMainWindow());
        holder->setObjectName(QStringLiteral("_fc_ch_keymap_actions_"));
        holder->resize(0, 0);
        holder->move(QPoint(-100, -100));
        holder->show();
    }
    holder->addAction(cmd->getAction()->action());
}

void reload()
{
    bool value = readPreference();
    if (value == onshape()) {
        return;
    }
    onshape() = value;

    auto& manager = Application::Instance->commandManager();
    for (const auto& entry : table) {
        applyTo(manager.getCommandByName(entry.name));
    }
    for (const auto& sub : subActions) {
        Command* cmd = manager.getCommandByName(sub.group);
        auto group = cmd ? qobject_cast<ActionGroup*>(cmd->getAction()) : nullptr;
        QAction* action = group ? group->actions().value(sub.index) : nullptr;
        if (action) {
            action->setShortcut(QKeySequence(QString::fromLatin1(accel(sub.name, sub.upstream))));
        }
    }
    for (const char* name : reachable) {
        actionCreated(manager.getCommandByName(name));
    }
    if (Command* cmd = manager.getCommandByName("Std_Workbench")) {
        if (auto group = qobject_cast<WorkbenchGroup*>(cmd->getAction())) {
            group->refreshWorkbenchList();
        }
    }
}

}  // namespace Gui::ForkKeymap
