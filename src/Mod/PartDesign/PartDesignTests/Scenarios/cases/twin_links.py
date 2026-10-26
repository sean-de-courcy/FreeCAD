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

"""Corpus cases (ops#500, class A; also class D, ops#503): two App::Link instances of one Body in
the same document, combined into one shape.

A Body holds a 10 x 10 x 10 AdditiveBox. Two App::Link instances of it, L1 at x = 0 and L2 at
x = 100, are combined by a Part::MultiFuse, a Part::Compound, or an App::Part (the links as its
group) bound by a PartDesign::SubShapeBinder; the combiner's elements for the two instances have
the same names but for a count. Three references: `ref_a` (a LinkSub) and `att` (a Part::Box
attached FlatFace) are on L2's +X face, at x = 110; `ref_b` (a LinkSub) is on L1's +X face, at
x = 10. The inputs are reordered ([L2, L1]), L1 is removed ([L2], or [L2, L3] for the MultiFuse, which needs two), or an instance L3 at x = 200 is
inserted first ([L3, L1, L2]). Each reference must stay on its face (the one at x = 110 facing
+X, the one at x = 10), or `ref_b` must break where L1 is gone. A reference on another instance's
face is a silent move.
Ported from `work/repro-deferred/repro_104_twin_links.py` (`run104.sh`;
`corpus/predicted/A.json`: ops104|same_document_twin_links_row92, `accepted` on integration)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, X, face

V = App.Vector


class TwinLinks(Scenario):
    """The model and its references; a subclass picks the combiner and the edit."""

    abstract = True
    area = "twin-links"
    CLASSES = ("A", "D")
    AXES = ("M5", "E1")
    ISSUE = "ops#500"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("ref_a", "ref_b", "att")
    combiner = None  # "fuse", "compound" or "part"
    gone = False  # the edit removes L1
    spare = False  # a third instance L3 at x = 200 stays, so that a MultiFuse keeps two inputs

    def faceA(self):
        return face("plane", normal=X, through=(110, 0, 0))

    def faceB(self):
        return face("plane", normal=X, through=(10, 0, 0))

    def faceBOrBroken(self):
        return BROKEN if self.gone else self.faceB()

    def link(self, doc, name, x):
        link = doc.addObject("App::Link", name)
        link.LinkedObject = self.body
        link.Placement.Base = V(x, 0, 0)
        return link

    def setInputs(self, links):
        if self.combiner == "fuse":
            self.combined.Shapes = links
        elif self.combiner == "compound":
            self.combined.Links = links
        else:
            for obj in list(self.part.Group):
                if obj not in links:
                    self.part.removeObject(obj)
            self.part.Group = links

    def build(self, doc):
        self.body = doc.addObject("PartDesign::Body", "Body")
        box = doc.addObject("PartDesign::AdditiveBox", "Box")
        self.body.addObject(box)
        box.Length = box.Width = box.Height = 10
        doc.recompute()
        self.l1 = self.link(doc, "L1", 0)
        self.l2 = self.link(doc, "L2", 100)
        self.rest = [self.link(doc, "L3", 200)] if self.spare else []
        if self.combiner == "fuse":
            self.combined = doc.addObject("Part::MultiFuse", "Combined")
        elif self.combiner == "compound":
            self.combined = doc.addObject("Part::Compound", "Combined")
        else:
            self.part = doc.addObject("App::Part", "Holder")
            self.combined = doc.addObject("PartDesign::SubShapeBinder", "Combined")
        self.setInputs([self.l1, self.l2] + self.rest)
        if self.combiner == "part":
            self.combined.Support = [(self.part, [""])]
        doc.recompute()
        combined = self.combined
        for name, expect in (("RefA", self.faceA), ("RefB", self.faceB)):
            holder = doc.addObject("App::FeaturePython", name)
            holder.addProperty("App::PropertyLinkSub", "Face")
            holder.Face = (combined, [self.names(combined, expect())[0]])
        box = doc.addObject("Part::Box", "Att")
        box.Length = box.Width = box.Height = 1
        box.AttachmentSupport = [(combined, [self.names(combined, self.faceA())[0]])]
        box.MapMode = "FlatFace"
        doc.recompute()
        self.ref("ref_a", doc.RefA, "Face", self.faceA)
        self.ref("ref_b", doc.RefB, "Face", self.faceBOrBroken)
        self.ref("att", box, "AttachmentSupport", self.faceA, Attached())


class TwinLinksFuseReorder(TwinLinks):
    """A MultiFuse of the links, the inputs reordered."""

    combiner = "fuse"
    AXES = ("M5", "E2")

    def edit(self, doc):
        self.setInputs([self.l2, self.l1])


class TwinLinksFuseRemove(TwinLinks):
    """A MultiFuse of the links L1, L2 and L3, L1 removed (a MultiFuse of one shape is invalid, so
    a third instance stays)."""

    combiner = "fuse"
    spare = True

    def edit(self, doc):
        self.gone = True
        self.setInputs([self.l2] + self.rest)


class TwinLinksFuseInsert(TwinLinks):
    """A MultiFuse of the links, L3 inserted first."""

    combiner = "fuse"

    def edit(self, doc):
        self.setInputs([self.link(doc, "L3", 200), self.l1, self.l2])


class TwinLinksCompoundReorder(TwinLinks):
    """A Compound of the links, the inputs reordered."""

    combiner = "compound"
    AXES = ("M5", "E2")

    def edit(self, doc):
        self.setInputs([self.l2, self.l1])


class TwinLinksCompoundRemove(TwinLinks):
    """A Compound of the links, L1 removed."""

    combiner = "compound"

    def edit(self, doc):
        self.gone = True
        self.setInputs([self.l2])


class TwinLinksCompoundInsert(TwinLinks):
    """A Compound of the links, L3 inserted first."""

    combiner = "compound"

    def edit(self, doc):
        self.setInputs([self.link(doc, "L3", 200), self.l1, self.l2])


class TwinLinksPartReorder(TwinLinks):
    """The links as an App::Part's group, bound by a SubShapeBinder; the group reordered."""

    combiner = "part"
    AXES = ("M5", "E2")

    def edit(self, doc):
        self.setInputs([self.l2, self.l1])


class TwinLinksPartRemove(TwinLinks):
    """The links as an App::Part's group, bound by a SubShapeBinder; L1 removed."""

    combiner = "part"

    def edit(self, doc):
        self.gone = True
        self.setInputs([self.l2])


class TwinLinksPartInsert(TwinLinks):
    """The links as an App::Part's group, bound by a SubShapeBinder; L3 inserted first."""

    combiner = "part"

    def edit(self, doc):
        self.setInputs([self.link(doc, "L3", 200), self.l1, self.l2])
