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

"""Corpus cases (ops#504, class E's E2, invariant I-S10): a rewrite keeps the records of the entries
it doesn't change, at call sites the first E2 module (`rewrite.py` on the E2 branch) doesn't have.

Ports (`corpus/predicted/E.json`): `FacebinderAdd|guessed_entry|V2s`, `JointSwapJCS|guessed_entry|V2s`,
`LinkSubListMissingEntryFp|missing_entry_fp|V2s` (the row `LinkSubListAddValue|missing_entry_fp|V2s`;
the class is named differently because `rewrite.py` has a `LinkSubListAddValue`),
`PropertyEditorListEdit|guessed_entry|V2s` and `ShapeBinderListEdit|guessed_entry|V2s`; the extra
case `ShapeBinderListRemove|kept_entry|V2s` is the other write of the same dialog.

The model of `rewrite.py`: a rectangle 0..20 x 0..10 padded 10 high (`Profile`, `Pad`). The
`RewriteCase` steps: `redraw`, the profile drawn again from its right back corner the other way
round (the same geometry with new IDs: a reference into the pad becomes a tier 3 guess of its
element in the same place, its owner warned), then `rewrite`, the case's own rewrite. A reference
holds its element plainly before the redraw and with a warning after each step: a rewrite that
drops the record leaves the right element but silently (the wrong set).

The GUI call sites are ported as the property write they end in (the property editor's list edit
and TaskShapeBinder's add and remove are Python assignments of `(object, [subs])` to the list;
TaskShapeBinder.cpp:333 and :533 call `setValue(obj, subs)`, as `binder.Support = (obj, subs)`
does). The joints' `swapJCS` is C++ run by a solve; the Python path that exchanges the two
references is `Joint.ensureUnconnectedIsSecondRef` (JointObject.py:1073), which the case calls."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Scenario,
    ScenarioError,
    Warned,
    X,
    Z,
    edge,
    face,
    faceNormal,
    pieces,
)
from PartDesignTests.Scenarios import models as m


class RewriteCase(Scenario):
    """A rectangle 0..20 x 0..10 padded 10 high (`Profile`, `Pad`). Steps: `redraw`, then
    `rewrite`, the case's own rewrite. Before the redraw a reference holds its element plainly;
    after each step it holds it with its owner warned."""

    abstract = True
    area = "rewrite_more"
    CLASSES = ("E",)
    AXES = ("M1", "E9")
    ISSUE = "ops#504"
    FOUND_BY = "port"
    TIER = "F"
    steps = ("redraw", "rewrite")

    def padded(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        return body, pad

    def redraw(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)

    def kept(self, before, after=None):
        """The expectation: `before` plainly at the build, then warned; after the rewrite
        `after` (default `before`), warned."""

        def expect():
            if self.stepName is None:
                return before
            return Warned(after if after is not None and self.stepName == "rewrite" else before)

        return expect

    @staticmethod
    def corner():
        """The pad's vertical edge at (20, 0)."""
        return edge("line", direction=Z, through=(20, 0, 0))

    @staticmethod
    def origin():
        """The pad's vertical edge at (0, 0)."""
        return edge("line", direction=Z, through=(0, 0, 0))

    @staticmethod
    def bottomEdges(xs):
        """The pad's vertical edges at (x, 0) for x in xs, as one expected set."""
        return pieces(
            edge(
                "line",
                direction=Z,
                where=lambda e: abs(e.Vertexes[0].Point.y) < 1e-6
                and any(abs(e.Vertexes[0].Point.x - x) < 1e-6 for x in xs),
            )
        )

    @staticmethod
    def right():
        return face("plane", normal=X, through=(20, 0, 0))

    @staticmethod
    def left():
        return face("plane", normal=-X, through=(0, 0, 0))

    @staticmethod
    def sides():
        """The pad's two side faces at x = 0 and x = 20, as one expected set."""
        return pieces(
            face(
                "plane",
                where=lambda f: abs(abs(faceNormal(f).x) - 1) < 1e-9
                and (abs(f.CenterOfMass.x) < 1e-6 or abs(f.CenterOfMass.x - 20) < 1e-6),
            )
        )


class FacebinderAdd(RewriteCase):
    """Draft's facebinder holds the pad's side face at x = 20; `addSubobjects` adds the face at
    x = 0 (it reads `Faces`, appends the pair and assigns the list again: facebinder.py:232)."""

    REFS = ("guessed_entry",)

    def build(self, doc):
        from draftmake.make_facebinder import make_facebinder

        _, pad = self.padded(doc)
        App.setActiveDocument(doc.Name)
        binder = make_facebinder([(pad, tuple(self.names(pad, self.right())))])
        self.binderName = binder.Name
        self.ref("guessed_entry", binder, "Faces", self.kept(self.right(), self.sides()))

    def rewrite(self, doc):
        binder = doc.getObject(self.binderName)
        binder.Proxy.addSubobjects(binder, [(doc.Pad, tuple(self.names(doc.Pad, self.left())))])


class JointSwapJCS(RewriteCase):
    """An assembly of two links of the pad's body, LinkB grounded; a joint's Reference1 holds the
    pad's vertical edge at (20, 0) on LinkA and its Reference2 the edge at (0, 0) on LinkB. The
    rewrite is `ensureUnconnectedIsSecondRef` (JointObject.py:1073): the ungrounded part's
    reference goes second, the two references exchange their values by assignment. Reference1 then
    holds the edge at (0, 0) on LinkB, and the record of the guess goes with the entry."""

    REFS = ("guessed_entry",)

    def swapped(self):
        return self.stepName == "rewrite"

    def expected(self):
        if self.stepName is None:
            return self.corner()
        return Warned(self.origin() if self.swapped() else self.corner())

    def target(self):
        return "LinkB" if self.swapped() else "LinkA"

    def build(self, doc):
        import JointObject

        body, pad = self.padded(doc)
        assembly = doc.addObject("Assembly::AssemblyObject", "Assembly")
        assembly.Type = "Assembly"  # as the Create Assembly command sets it
        joints = assembly.newObject("Assembly::JointGroup", "Joints")
        links = []
        for name in ("LinkA", "LinkB"):
            link = doc.addObject("App::Link", name)
            link.LinkedObject = body
            assembly.addObject(link)
            links.append(link)
        doc.recompute()
        ground = joints.newObject("App::FeaturePython", "GroundedJoint")
        JointObject.GroundedJoint(ground, links[1])
        joint = joints.newObject("App::FeaturePython", "Joint")
        JointObject.Joint(joint, 0)
        joint.Reference1 = [links[0], self.names(links[0], self.corner())]
        joint.Reference2 = [links[1], self.names(links[1], self.origin())]
        doc.recompute()
        self.ref("guessed_entry", joint, "Reference1", self.expected, on=self.target)

    def rewrite(self, doc):
        joint = doc.Joint
        joint.Proxy.ensureUnconnectedIsSecondRef(joint)
        if joint.Reference1[0].Name != "LinkB":
            raise ScenarioError("the joint didn't exchange its references")


class LinkSubListMissingEntryFp(RewriteCase):
    """A holder's list references the pad's vertical edge at (20, 0). `lose`: the profile becomes a
    quadrilateral with a slanted right side, so the edge is gone and its entry is `?Edge2`, kept
    missing with its last fingerprint and candidates. `rewrite`: the entry at (0, 0) is put in front
    of it (setValues, a count change: `_updateElementFingerprints` blanks every fingerprint of a
    list whose count changed, PropertyLinks.cpp:761). `restore`: the profile is drawn as the
    rectangle again, so the edge comes back in the same place. Without the rewrite the missing entry
    finds it again; a fingerprint blanked by the rewrite leaves it missing for good. The
    expectation after `restore` is the two edges; while the edge is gone, the loud break."""

    REFS = ("missing_entry_fp",)
    steps = ("lose", "rewrite", "restore")

    def expected(self):
        if self.stepName is None:
            return self.corner()
        if self.stepName == "restore":
            return self.bottomEdges((0, 20))
        return BROKEN

    def build(self, doc):
        _, pad = self.padded(doc)
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty("App::PropertyLinkSubListGlobal", "Refs")
        holder.Refs = [(pad, tuple(self.names(pad, self.corner())))]
        self.ref("missing_entry_fp", holder, "Refs", self.expected)

    def lose(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.polygon([(0, 0), (15, 0), (12, 10), (0, 10)]), False)

    def rewrite(self, doc):
        [(pad, [missing])] = doc.Holder.Refs
        other = self.names(pad, self.origin())[0]
        doc.Holder.Refs = [(pad, (other, missing))]

    def restore(self, doc):
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(m.rectangle(0, 0, 20, 10), False)


class PropertyEditorListEdit(RewriteCase):
    """A holder's list references the pad's vertical edge at (20, 0); the property editor's list
    edit (PropertyItem.cpp:4815, `DlgPropertyLink::linksToPython`) writes the whole list again as
    `(object, [subs])` with the edge at (0, 0) added. The same write: `holder.Refs = (pad,
    [held, other])`."""

    REFS = ("guessed_entry",)

    def build(self, doc):
        _, pad = self.padded(doc)
        holder = doc.addObject("App::FeaturePython", "Holder")
        holder.addProperty("App::PropertyLinkSubList", "Refs")
        holder.Refs = [(pad, tuple(self.names(pad, self.corner())))]
        self.ref(
            "guessed_entry", holder, "Refs", self.kept(self.corner(), self.bottomEdges((0, 20)))
        )

    def rewrite(self, doc):
        [(pad, [held])] = doc.Holder.Refs
        other = self.names(pad, self.origin())[0]
        doc.Holder.Refs = (pad, [held, other])


class ShapeBinderListEdit(RewriteCase):
    """A ShapeBinder's Support holds the pad's vertical edge at (20, 0); TaskShapeBinder's add
    (TaskShapeBinder.cpp:533) reads the sub list, appends the picked sub and calls
    `Support.setValue(obj, subs)`. The same write: `binder.Support = (pad, [held, other])`, with
    the edge at (0, 0)."""

    REFS = ("guessed_entry",)

    def build(self, doc):
        _, pad = self.padded(doc)
        binder = doc.addObject("PartDesign::ShapeBinder", "Binder")
        binder.Support = [(pad, tuple(self.names(pad, self.corner())))]
        self.ref(
            "guessed_entry", binder, "Support", self.kept(self.corner(), self.bottomEdges((0, 20)))
        )

    def rewrite(self, doc):
        [(pad, [held])] = doc.Binder.Support
        other = self.names(pad, self.origin())[0]
        doc.Binder.Support = (pad, [held, other])


class ShapeBinderListRemove(RewriteCase):
    """A ShapeBinder's Support holds the pad's vertical edges at (20, 0) and (0, 0); TaskShapeBinder's
    remove (TaskShapeBinder.cpp:333) erases one sub and calls `Support.setValue(obj, subs)`: the
    edge at (0, 0) goes, the other keeps its record."""

    REFS = ("kept_entry",)

    def build(self, doc):
        _, pad = self.padded(doc)
        binder = doc.addObject("PartDesign::ShapeBinder", "Binder")
        binder.Support = [(pad, tuple(self.bottomEdges((0, 20)).select(pad.Shape)))]
        self.ref(
            "kept_entry", binder, "Support", self.kept(self.bottomEdges((0, 20)), self.corner())
        )

    def rewrite(self, doc):
        [(pad, subs)] = doc.Binder.Support
        # the sub of the edge at x = 20, by its place now
        keep = [s for s in subs if abs(pad.Shape.getElement(s).CenterOfMass.x - 20) < 1e-6]
        doc.Binder.Support = (pad, keep)
