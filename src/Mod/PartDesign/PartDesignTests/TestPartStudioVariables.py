# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (notes/derived-design.md, slice 2: Part Studio variables)

"""Onshape's Part Studio variables (the Variable feature, `assignVariable`): a VarSet held by a
part studio (an App::Part) is what `#name` finds first from that studio's features, and other
studios don't see it; the document's own sets (Variables, Variable Studios) are seen from every
studio.

Designed geometry: studios P, Q and R, each with a Body holding a 10 x 10 x 10 box whose Length is
an expression. P's set has w = 10 mm, Q's w = 20 mm; the document's set has h = 5 mm and, in one
case, w = 7 mm. The expected result is the box's length, read from its volume (L x 10 x 10)."""

import os
import shutil
import tempfile
import unittest

import FreeCAD as App


def variables(doc, container, name, **values):
    vs = doc.addObject("App::VarSet", name)
    if container is not None:
        container.addObject(vs)
    for key, value in values.items():
        vs.addProperty("App::PropertyLength", key)
        setattr(vs, key, value)
    return vs


class TestPartStudioVariables(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("StudioVariables")
        self.boxes = {}
        for name in ("P", "Q", "R"):
            studio = self.doc.addObject("App::Part", name)
            body = self.doc.addObject("PartDesign::Body", name + "Body")
            studio.addObject(body)
            box = body.newObject("PartDesign::AdditiveBox", name + "Box")
            box.Length = box.Width = box.Height = 10
            self.boxes[name] = box
        self.pVars = variables(self.doc, self.doc.getObject("P"), "PVars", w=10)
        self.qVars = variables(self.doc, self.doc.getObject("Q"), "QVars", w=20)
        self.docVars = variables(self.doc, None, "Variables", h=5)
        self.doc.recompute()

    def tearDown(self):
        for name in list(App.listDocuments()):
            if name.startswith("StudioVariables"):
                App.closeDocument(name)

    def length(self, studio):
        box = self.boxes[studio]
        return box.Shape.Volume / 100

    def bind(self, studio, prop, text):
        self.boxes[studio].setExpression(prop, text)
        self.doc.recompute()

    def testEachStudioSeesItsOwnVariable(self):
        self.bind("P", "Length", "#w")
        self.bind("Q", "Length", "#w")
        self.assertAlmostEqual(self.length("P"), 10, places=6)
        self.assertAlmostEqual(self.length("Q"), 20, places=6)
        self.assertEqual(self.boxes["P"].ExpressionEngine[0][1], "PVars.w")
        self.assertEqual(self.boxes["Q"].ExpressionEngine[0][1], "QVars.w")

    def testTheDocumentsVariablesAreSeenEverywhere(self):
        for studio in ("P", "Q", "R"):
            self.bind(studio, "Length", "#h * 3")
            self.assertAlmostEqual(self.length(studio), 15, places=6)

    def testTheStudiosVariableWinsOverTheDocuments(self):
        """w in P's set (10) and in the document's (7): P's box takes 10, R's (no w of its own) 7."""
        self.docVars.addProperty("App::PropertyLength", "w")
        self.docVars.w = 7
        self.doc.recompute()
        self.bind("P", "Length", "#w")
        self.bind("R", "Length", "#w")
        self.assertAlmostEqual(self.length("P"), 10, places=6)
        self.assertAlmostEqual(self.length("R"), 7, places=6)

    def testAnotherStudiosVariableIsRefused(self):
        """R has no w and the document none: P's and Q's are not R's, so `#w` fails loudly."""
        with self.assertRaises(Exception) as ctx:
            self.boxes["R"].setExpression("Length", "#w")
        self.assertIn("part studio", str(ctx.exception))
        self.assertEqual(self.boxes["R"].ExpressionEngine, [])

    def testSaveAndReopen(self):
        self.bind("P", "Length", "#w")
        self.bind("Q", "Length", "#w + #h")
        folder = tempfile.mkdtemp(prefix="studiovars")
        try:
            path = os.path.join(folder, "StudioVariables.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.boxes = {n: self.doc.getObject(n + "Box") for n in ("P", "Q", "R")}
            self.doc.getObject("QVars").w = 30
            self.doc.recompute()
            self.assertAlmostEqual(self.length("P"), 10, places=6)
            self.assertAlmostEqual(self.length("Q"), 35, places=6)
        finally:
            App.closeDocument(self.doc.Name)
            shutil.rmtree(folder, ignore_errors=True)
