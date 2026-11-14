# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""The PartDesign toolbar in Onshape's order, and Onshape's words (FreeCAD-CH, ops#605 brief C).

PartDesign has one "Features" toolbar in Onshape's order (notes/onshape-gui-plan.md 2.0, as
corrected by section 7: Groove and the subtractive Pipe and Loft stay beside their additive twins).
Pocket is off it (ops#640, rank 22: Onshape's one Extrude removes too), and Onshape's Variable tool
(Std_AddVariable, rank 15) is on it. The four stock toolbars are still there, hidden until
the user shows them from the toolbar menu. Pad, Pocket, Thickness, Mirrored, LinearPattern and
PolarPattern read "Extrude", "Extrude (remove)", "Shell", "Mirror", "Linear pattern" and "Circular
pattern" in menus and tooltips; the command names, the object types and the saved files keep
FreeCAD's names.

The oracles are written out here, independently of the C++ lists, and read from the toolbars the
ToolBarManager built in the main window after the toolbar settings were cleared, as on a fresh
settings folder."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtGui, QtWidgets

TOOLBARS = "User parameter:BaseApp/MainWindow/Toolbars"

SEP = "|"

# Onshape's order, section 2.0 as corrected by section 7
FEATURES = [
    "PartDesign_NewSketch",
    "PartDesign_Pad",
    "PartDesign_Revolution",
    "PartDesign_Groove",
    "PartDesign_AdditivePipe",
    "PartDesign_SubtractivePipe",
    "PartDesign_AdditiveLoft",
    "PartDesign_SubtractiveLoft",
    SEP,
    "PartDesign_Fillet",
    "PartDesign_Chamfer",
    "PartDesign_Draft",
    "PartDesign_Thicken",  # lane solid-ops: Thicken, Scale, Offset surface before Shell
    "PartDesign_ScalePart",
    "PartDesign_OffsetSurface",
    "PartDesign_Thickness",
    "PartDesign_Hole",
    SEP,
    "PartDesign_Mirrored",
    "PartDesign_LinearPattern",
    "PartDesign_PolarPattern",
    "PartDesign_CurvePattern",
    "PartDesign_MultiTransform",
    SEP,
    "PartDesign_Boolean",
    "PartDesign_Split",
    "PartDesign_MergeParts",
    "PartDesign_Derived",  # Onshape's Derived (ops#640 round 6)
    SEP,
    "PartDesign_CompDatums",
    "PartDesign_AdditiveHelix",
    "PartDesign_SubShapeBinder",
    "PartDesign_Body",
    "PartDesign_CompPrimitiveAdditive",
    "Std_AddVariable",  # Onshape's Variable tool (ops#640, rank 15)
    "Sketcher_ValidateSketch",
    "PartDesign_ToggleModelTree",  # brings the model tree back (ops#602, decision 279)
]

# The four stock toolbars, kept but hidden by default
STOCK = {
    "Part Design Helper Features": [
        "PartDesign_Body",
        "PartDesign_ToggleModelTree",
        "PartDesign_CompSketches",
        "Sketcher_ValidateSketch",
        "Part_CheckGeometry",
        "PartDesign_SubShapeBinder",
        "PartDesign_Clone",
    ],
    "Part Design Modeling Features": [
        "PartDesign_Pad",
        "PartDesign_Revolution",
        "PartDesign_AdditiveLoft",
        "PartDesign_AdditivePipe",
        "PartDesign_AdditiveHelix",
        "PartDesign_CompPrimitiveAdditive",
        SEP,
        "PartDesign_Pocket",
        "PartDesign_Hole",
        "PartDesign_Groove",
        "PartDesign_SubtractiveLoft",
        "PartDesign_SubtractivePipe",
        "PartDesign_SubtractiveHelix",
        "PartDesign_CompPrimitiveSubtractive",
        SEP,
        "PartDesign_Boolean",
    ],
    "Part Design Dress-Up Features": [
        "PartDesign_Fillet",
        "PartDesign_Chamfer",
        "PartDesign_Draft",
        "PartDesign_Thickness",
        "PartDesign_Defeaturing",
    ],
    "Part Design Transformation Features": [
        "PartDesign_Mirrored",
        "PartDesign_LinearPattern",
        "PartDesign_PolarPattern",
        "PartDesign_CurvePattern",
        "PartDesign_MultiTransform",
    ],
}

# What a user reads in the menus: the menu text, as Onshape words it
TEXTS = {
    "PartDesign_Pad": "Extrude",
    "PartDesign_Pocket": "Extrude (remove)",
    "PartDesign_Thickness": "Shell",
    "PartDesign_Mirrored": "Mirror",
    "PartDesign_LinearPattern": "Linear pattern",
    "PartDesign_PolarPattern": "Circular pattern",
    "PartDesign_CurvePattern": "Curve pattern",
}


def toolbar(name):
    found = [
        t for t in Gui.getMainWindow().findChildren(QtWidgets.QToolBar) if t.objectName() == name
    ]
    return found[0] if found else None


def commands(tb):
    """The command names of a toolbar's actions in order, SEP for a separator."""
    return [SEP if a.isSeparator() else a.objectName() for a in tb.actions()]


def clear_toolbar_settings():
    """Forget the saved visibility of every toolbar this test reads, as on a fresh settings folder;
    returns what to put back."""
    group = App.ParamGet(TOOLBARS)
    saved = {name: group.GetBool(name) for name in group.GetBools()}
    for name in saved:
        group.RemBool(name)
    return saved


def restore_toolbar_settings(saved):
    group = App.ParamGet(TOOLBARS)
    for name in group.GetBools():
        group.RemBool(name)
    for name, value in saved.items():
        group.SetBool(name, value)


class TestToolbarsGui(unittest.TestCase):
    def setUp(self):
        Gui.getMainWindow().show()
        # Workbench toolbars are built on activation: leave (which saves the toolbars' visibility),
        # forget what was saved, and come back to build them anew
        Gui.activateWorkbench("PartWorkbench")
        self.saved = clear_toolbar_settings()
        Gui.activateWorkbench("PartDesignWorkbench")
        QtGui.QApplication.processEvents()

    def tearDown(self):
        restore_toolbar_settings(self.saved)

    def test_features_toolbar_is_onshapes_order(self):
        tb = toolbar("Features")
        self.assertIsNotNone(tb, "Expected a PartDesign toolbar named Features")
        self.assertEqual(commands(tb), FEATURES)

    def test_features_toolbar_is_shown_on_a_fresh_settings_folder(self):
        tb = toolbar("Features")
        self.assertIsNotNone(tb)
        self.assertFalse(tb.isHidden(), "Expected the Features toolbar to be shown")

    def test_stock_toolbars_are_hidden_but_can_be_shown(self):
        for name, expected in STOCK.items():
            with self.subTest(name):
                tb = toolbar(name)
                self.assertIsNotNone(tb, f"Expected the stock toolbar {name}")
                self.assertEqual(commands(tb), expected)
                self.assertTrue(tb.isHidden(), f"Expected {name} hidden by default")
                self.assertTrue(
                    tb.toggleViewAction().isVisible(),
                    f"Expected {name} to be listed in the toolbar menu",
                )

    def test_a_stock_toolbar_the_user_showed_stays_shown(self):
        # leaving a workbench saves the toolbars' visibility: set the user's choice after that
        Gui.activateWorkbench("PartWorkbench")
        App.ParamGet(TOOLBARS).SetBool("Part Design Dress-Up Features", True)
        Gui.activateWorkbench("PartDesignWorkbench")
        QtGui.QApplication.processEvents()
        self.assertFalse(toolbar("Part Design Dress-Up Features").isHidden())

    def test_menu_texts_are_onshapes_words(self):
        actions = {}
        for action in Gui.getMainWindow().findChildren(QtGui.QAction):
            actions.setdefault(action.objectName(), action)
        for name, text in TEXTS.items():
            with self.subTest(name):
                self.assertIn(name, actions)
                self.assertEqual(actions[name].text().replace("&", ""), text)

    def test_tooltips_use_onshapes_words(self):
        actions = {a.objectName(): a for a in Gui.getMainWindow().findChildren(QtGui.QAction)}
        self.assertIn("Shell", actions["PartDesign_Thickness"].toolTip())
        self.assertIn("circular pattern", actions["PartDesign_PolarPattern"].toolTip().lower())

    def test_command_names_are_unchanged(self):
        """The words change in menus only: the commands keep their names."""
        for name in TEXTS:
            self.assertIsNotNone(Gui.Command.get(name), name)


if __name__ == "__main__":
    unittest.main()
