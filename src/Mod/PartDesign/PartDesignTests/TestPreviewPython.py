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

"""The preview of Python additive and subtractive features (FreeCAD-CH, ops#13).

A PartDesign::FeatureAdditivePython or FeatureSubtractivePython gets a Python view provider,
which attaches only once its proxy is set. Until then the preview extension has no scene
graph nodes, and writing to them crashed."""

import os
import tempfile
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PySide import QtWidgets


class BoxFeature:
    """A Python add/sub feature whose tool is a 4 mm cube above the origin."""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        box = Part.makeBox(4, 4, 4, App.Vector(-2, -2, 8))
        obj.AddSubShape = box
        obj.Shape = box

    def dumps(self):
        return None

    def loads(self, state):
        return None


class BoxViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def dumps(self):
        return None

    def loads(self, state):
        return None


class TestPreviewPython(unittest.TestCase):
    def setUp(self):
        self.Doc = App.newDocument("PartDesignTestPreviewPython")
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.path = None

    def tearDown(self):
        if self.Doc.Name in App.listDocuments():
            App.closeDocument(self.Doc.Name)
        if self.path and os.path.exists(self.path):
            os.remove(self.path)

    def addFeature(self, typeName, name, viewProvider=True):
        feature = self.Doc.addObject(typeName, name)
        BoxFeature(feature)
        self.Body.addObject(feature)
        if viewProvider:
            BoxViewProvider(feature.ViewObject)
        return feature

    def testPreviewColorBeforeViewProviderAttaches(self):
        """PreviewColor can be set before the Python view provider has its proxy; once it
        attaches, the feature gets the additive preview color, as a built-in additive feature
        does. Setting it wrote to a preview node that didn't exist yet."""
        # Arrange
        feature = self.addFeature("PartDesign::FeatureAdditivePython", "Add", viewProvider=False)
        builtIn = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(builtIn)

        # Act
        feature.ViewObject.PreviewColor = (1.0, 0.0, 0.0)
        BoxViewProvider(feature.ViewObject)
        self.Doc.recompute()

        # Assert
        self.assertIsInstance(feature.ViewObject.Proxy, BoxViewProvider)
        self.assertEqual(feature.ViewObject.PreviewColor, builtIn.ViewObject.PreviewColor)

    def testShowPreviewBeforeViewProviderAttaches(self):
        """showPreview before the Python view provider has its proxy does nothing: there is no
        preview to show yet. It added a null node to the scene graph."""
        # Arrange
        feature = self.addFeature(
            "PartDesign::FeatureSubtractivePython", "Sub", viewProvider=False
        )
        self.Doc.recompute()

        # Act
        feature.ViewObject.showPreview(True)
        enabled = feature.ViewObject.isPreviewEnabled()
        feature.ViewObject.showPreview(False)

        # Assert
        self.assertFalse(enabled)

    def testReopenPythonAddSubFeatures(self):
        """A document with additive and subtractive Python features and Python view providers
        reopens in the GUI, their view providers attach, and their previews show."""
        # Arrange
        self.addFeature("PartDesign::FeatureAdditivePython", "Add")
        self.addFeature("PartDesign::FeatureSubtractivePython", "Sub")
        self.Doc.recompute()
        QtWidgets.QApplication.processEvents()
        fd, self.path = tempfile.mkstemp(suffix=".FCStd", prefix="PreviewPython")
        os.close(fd)
        self.Doc.saveAs(self.path)
        App.closeDocument(self.Doc.Name)
        QtWidgets.QApplication.processEvents()

        # Act
        self.Doc = App.openDocument(self.path)
        QtWidgets.QApplication.processEvents()
        self.Doc.recompute()
        QtWidgets.QApplication.processEvents()

        # Assert
        for name in ("Add", "Sub"):
            with self.subTest(feature=name):
                vobj = self.Doc.getObject(name).ViewObject
                self.assertIsInstance(vobj.Proxy, BoxViewProvider)
                vobj.showPreview(True)
                self.assertTrue(vobj.isPreviewEnabled())
                vobj.showPreview(False)
