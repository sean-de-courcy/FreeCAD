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
    // A geometry tool stays enabled while another runs, so these take the running tool's own
    // M / U / R, which move to Ctrl+M / U / J / R / F (DrawSketchHandler::isToolKey(), PR D)
    {"Sketcher_CreateRectangle_Center", "R"},
    {"Sketcher_Trimming", "M"},
    {"Sketcher_Projection", "U"},
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
    // Other workbenches' chords starting with an Onshape key: once such a workbench is loaded, the
    // key would wait for the chord everywhere (ShortcutManager counts every enabled action). Most
    // are Python commands, whose key PythonCommand::getAccel() asks of this table.
    // Draft
    {"Draft_Arc", ""},
    {"Draft_Arc_3Points", ""},
    {"Draft_BezCurve", ""},
    {"Draft_BSpline", ""},
    {"Draft_Circle", ""},
    {"Draft_Clone", ""},
    {"Draft_Dimension", ""},
    {"Draft_Downgrade", ""},
    {"Draft_Edit", ""},
    {"Draft_Ellipse", ""},
    {"Draft_Facebinder", ""},
    {"Draft_Fillet", ""},
    {"Draft_Hatch", ""},
    {"Draft_Label", ""},
    {"Draft_Line", ""},
    {"Draft_Offset", ""},
    {"Draft_SelectPlane", ""},
    {"Draft_SubelementHighlight", ""},
    {"Draft_Text", ""},
    {"Draft_ToggleConstructionMode", ""},
    {"Draft_ToggleGrid", ""},
    {"Draft_Trimex", ""},
    // BIM
    {"Arch_Axis", ""},
    {"Arch_AxisSystem", ""},
    {"Arch_Building", ""},
    {"Arch_CloneComponent", ""},
    {"Arch_Component", ""},
    {"Arch_CurtainWall", ""},
    {"Arch_Equipment", ""},
    {"Arch_Floor", ""},
    {"Arch_Frame", ""},
    {"Arch_Grid", ""},
    {"Arch_IfcSpreadsheet", ""},
    {"Arch_Level", ""},
    {"Arch_Nest", ""},
    {"Arch_Reference", ""},
    {"Arch_Truss", ""},
    {"Arch_Wall", ""},
    {"Arch_Window", ""},
    {"BIM_Beam", ""},
    {"BIM_Clone", ""},
    {"BIM_Column", ""},
    {"BIM_Copy", ""},
    {"BIM_Covering", ""},
    {"BIM_DimensionAligned", ""},
    {"BIM_DimensionHorizontal", ""},
    {"BIM_DimensionVertical", ""},
    {"BIM_Door", ""},
    {"BIM_DrawingView", ""},
    {"BIM_Leader", ""},
    {"BIM_LinkMake", ""},
    {"BIM_ResetCloneColors", ""},
    {"BIM_SetWPFront", ""},
    {"BIM_SetWPSide", ""},
    {"BIM_SetWPTop", ""},
    {"BIM_Shape2DCut", ""},
    {"BIM_Shape2DView", ""},
    {"BIM_TDPage", ""},
    {"BIM_TDView", ""},
    {"BIM_Text", ""},
    {"IFC_Diff", ""},
    {"IFC_Expand", ""},
    {"IFC_MakeProject", ""},
    // Draft, BIM and FEM: starting with R, M or U (PR D)
    {"Draft_Mirror", ""},
    {"Draft_Move", ""},
    {"Draft_Rectangle", ""},
    {"Draft_Rotate", ""},
    {"Draft_Upgrade", ""},
    {"Arch_Material", ""},
    {"Arch_MultiMaterial", ""},
    {"Arch_Rebar", ""},
    {"Arch_Roof", ""},
    {"BIM_Material", ""},
    {"BIM_Rewire", ""},
    {"FEM_MaterialSolid", ""},
    {"FEM_ResultShow", ""},
    {"FEM_ResultsPurge", ""},
    // Assembly's single letters that are the fork's general keys (F fit, Z zoom out, W box zoom,
    // Y hide): its joint commands are ForEdit and an active assembly counts as an edit, so the tie
    // rule gave them the key (PLAN.md decision 31). Its other letters stay: no fork key is enabled
    // with them (the sketch tools' keys need a sketch in edit, whose dialog disables Assembly's).
    {"Assembly_CreateJointFixed", ""},
    {"Assembly_SolveAssembly", ""},
    {"Assembly_CreateJointScrew", ""},
    {"Assembly_CreateJointRigidGroup", ""},
    // FEM (F, G), and Robot's single A and W (the arc and the box zoom)
    {"FEM_PostFilterGlyph", ""},
    {"Robot_InsertWaypoint", ""},
    {"Robot_InsertWaypointPreselect", ""},
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
    // Not under Shortcut: Customize > Keyboard > Reset All clears that group and every subgroup
    return preferenceGroup()->GetASCII("Keymap", "Onshape") != "FreeCAD";
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

bool isReachable(const Command* cmd)
{
    return cmd && std::any_of(std::begin(reachable), std::end(reachable), [cmd](const char* name) {
               return std::strcmp(name, cmd->getName()) == 0;
           });
}

/// The widget keeping the actions of reachable[]
QPointer<QWidget>& holder()
{
    static QPointer<QWidget> widget;
    return widget;
}

bool isPython(Command* cmd)
{
    return dynamic_cast<PythonCommand*>(cmd) || dynamic_cast<PythonGroupCommand*>(cmd);
}

}  // namespace

ParameterGrp::handle preferenceGroup()
{
    return App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/General"
    );
}

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
    if (!cmd || isPython(cmd) || dynamic_cast<MacroCommand*>(cmd) || !find(cmd->getName())) {
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
    if (!onshape() || !isReachable(cmd) || !cmd->getAction()) {
        return;
    }
    auto& widget = holder();
    if (!widget) {
        if (!getMainWindow()) {
            return;
        }
        // As ToolBarManager's action widget: zero size and out of the way, but shown
        widget = new QWidget(getMainWindow());
        widget->setObjectName(QStringLiteral("_fc_ch_keymap_actions_"));
        widget->resize(0, 0);
        widget->move(QPoint(-100, -100));
        widget->show();
    }
    widget->addAction(cmd->getAction()->action());
}

void reload()
{
    bool value = readPreference();
    if (value == onshape()) {
        return;
    }
    onshape() = value;

    auto& manager = Application::Instance->commandManager();
    auto shortcuts = ShortcutManager::instance();
    for (const auto& entry : table) {
        Command* cmd = manager.getCommandByName(entry.name);
        applyTo(cmd);
        // A Python command's getAccel() asks the table itself: only its action needs the new key
        if (isPython(cmd) && cmd->getAction()) {
            cmd->setShortcut(shortcuts->getShortcut(cmd->getName(), cmd->getAccel()));
        }
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
        Command* cmd = manager.getCommandByName(name);
        if (onshape()) {
            actionCreated(cmd);
        }
        else if (holder() && cmd && cmd->getAction()) {
            holder()->removeAction(cmd->getAction()->action());  // as upstream: no key in an edit
        }
    }
    if (Command* cmd = manager.getCommandByName("Std_Workbench")) {
        if (auto group = qobject_cast<WorkbenchGroup*>(cmd->getAction())) {
            group->refreshWorkbenchList();
        }
    }
    // A group's button carries its default tool's key (GroupCommand::setup()), and a Python
    // group's drop-down has actions of its own: set them again
    for (Command* cmd : manager.getAllCommands()) {
        auto group = qobject_cast<ActionGroup*>(cmd->getAction());
        if (!group) {
            continue;
        }
        if (dynamic_cast<PythonGroupCommand*>(cmd)) {
            for (QAction* action : group->actions()) {
                QByteArray name = action->property("CommandName").toByteArray();
                if (!name.isEmpty()) {
                    action->setShortcut(shortcuts->getShortcut(name.constData()));
                }
            }
        }
        if (dynamic_cast<GroupCommand*>(cmd) || dynamic_cast<PythonGroupCommand*>(cmd)) {
            cmd->languageChange();
        }
    }
    // Pad's and Revolution's isActive() depend on the keymap in sketch edit
    if (MainWindow* mainWindow = getMainWindow()) {
        mainWindow->updateActions(true);
    }
}

}  // namespace Gui::ForkKeymap
