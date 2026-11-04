"""ops#579's record-take (decision 256), from its designer: a target that ran and failed without
making its shape, no rule claiming it (not failed in S1). A Part::Extrusion Ext of Profile, given a
zero custom direction, throws in execute() and keeps its last shape; a free sketch Top is attached
to its front face (y = 0). Step 1: rim 2 drawn, Ext broken. Step 2: rim 1 deleted, rim 2 slid onto
y = 0, Ext made good. Expected: a break (rim 2 was in the model while Ext was down). Wrong on both
builds before the take: the reference into Ext kept its build record, and rim 2 read as drawn
since."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m


class ExtOwn(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#579"
    FOUND_BY = "designer pr579 record-take"
    TIER = "F"
    SIZE = 3600
    REFS = ("front",)
    length, thickness, height = 3600, 45, 300
    edited = False

    def frontFace(self):
        return face("plane", normal=(0, -1, 0), through=(0, 0, 0))

    def want(self):
        return BROKEN if self.edited else self.frontFace()

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T))
        ext = doc.addObject("Part::Extrusion", "Ext")
        ext.Base = profile
        ext.DirMode = "Custom"
        ext.Dir = App.Vector(0, 0, 1)
        ext.LengthFwd = H
        ext.Solid = True
        doc.recompute()
        top = m.sketch(doc, "Top", [])
        top.AttachmentSupport = [(ext, self.names(ext, self.frontFace())[0])]
        top.MapMode = "FlatFace"
        doc.recompute()
        self.ref("front", top, "AttachmentSupport", lambda: self.want(), Attached())

    def drawRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)

    def slideRim2(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class ExtOwnFailSlidFixed(ExtOwn):
    steps = ("drawAndBreak", "slideAndFix")

    def drawAndBreak(self, doc):
        self.drawRim2(doc)
        doc.Ext.Dir = App.Vector(0, 0, 0)

    def slideAndFix(self, doc):
        self.slideRim2(doc)
        doc.Ext.Dir = App.Vector(0, 0, 1)


class ExtOwnControl(ExtOwn):
    """The control: the same edits, Ext never broken."""

    steps = ("draw", "slide")

    def draw(self, doc):
        self.drawRim2(doc)

    def slide(self, doc):
        self.slideRim2(doc)
