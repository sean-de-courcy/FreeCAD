"""Review pr564son-r2 (ops#564 round 2): probes aimed at round 2's changes: the take-all after a
feature's recompute alone (T2), the end-of-recompute rule for objects outside the run (T3), the
cross-document take (T1)."""

import os
import shutil
import tempfile

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN, Attached, Bound, Chamfered, Scenario, X, Y, edge, face,
)
from PartDesignTests.Scenarios import models as m


class Rim(Scenario):
    """Rim 3600 x 45, 235 high, padded from Profile in a Body; a Chamfer (5) on its outer top
    edge (y = 0); a Part Box Spare elsewhere. Subclasses edit."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564son-r2"
    TIER = "F"
    SIZE = 3600
    REFS = ("chamfer",)
    length, thickness, height = 3600, 45, 235
    edited = False

    def topEdge(self):
        return edge("line", direction=X, through=(0, 0, self.s(self.height)))

    def want(self):
        return self.topEdge()

    def rect(self, y):
        L, T = self.s(self.length, self.thickness)
        return m.rectangle(0, self.s(y), L, self.s(y) + T)

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, self.names(pad, self.topEdge()))
        chamfer.Size = self.s(5)
        spare = doc.addObject("Part::Box", "Spare")
        spare.Placement.Base = App.Vector(0, self.s(5000), 0)
        doc.recompute()
        self.ref("chamfer", chamfer, "Base", lambda: self.want(), Chamfered(self.s(5)))

    def redraw(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)

    def slide(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])


class RedrawSetBaseUnrelatedSingle(Rim):
    """Redraw in place, Base set again (hold), then an unrelated Spare.recompute() (one feature,
    non-recursive: a macro, a dialog's preview of something else), then the document. Right on
    integration (decision 97 Q3); T2's take-all takes the Chamfer's record early."""

    def edit(self, doc):
        self.redraw(doc)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Spare.recompute()


class RedrawSetBaseSketchSingle(Rim):
    """Redraw in place, Base set again, the sketch recomputed alone (the Pad and Chamfer still
    to come), then the document."""

    def edit(self, doc):
        self.redraw(doc)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Profile.recompute()


class RedrawSketchSingleNoSetter(Rim):
    """As above without the setter: the redraw, the sketch recomputed alone, the document."""

    def edit(self, doc):
        self.redraw(doc)
        doc.Profile.recompute()


class RedrawSetBaseSpareSingleTwoSteps(Rim):
    """Redraw + setter in one step; Spare.recompute() in the next; the document recomputes in the
    third."""

    steps = ("redraw_set", "spare", "full")

    def redraw_set(self, doc):
        self.redraw(doc)
        doc.Chamfer.Base = doc.Chamfer.Base

    def spare(self, doc):
        doc.Spare.recompute()

    def full(self, doc):
        pass


class SiblingThenSpareSingle(Rim):
    """Rim 2 drawn and the document recomputed (the reference resolves with rim 2 in the model),
    then rim 1 deleted and rim 2 dragged to y = 0, the Base set again, Spare.recompute(), the
    document: rim 2 was there, so the reference must break."""

    steps = ("draw", "slide")

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def draw(self, doc):
        doc.Profile.addGeometry(self.rect(2000), False)

    def slide(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Spare.recompute()
        self.edited = True


class FailedPadThenRedrawn(Rim):
    """The rim's lines deleted (the Pad fails: no wire), the Base set again, the document
    recomputed (the Pad fails; touched); then the rim drawn again (new IDs) and the document
    recomputed: the redraw in place; the reference follows (a warned guess is right too)."""

    steps = ("delete", "redraw_again")
    deleted = False

    def want(self):
        return BROKEN if self.deleted else self.topEdge()

    def delete(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Chamfer.Base = doc.Chamfer.Base
        self.deleted = True

    def redraw_again(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)
        self.deleted = False


class FailedPadSiblingSlid(Rim):
    """Rim 2 drawn and recomputed; rim 1's lines deleted (the Pad still has rim 2: no failure);
    the Base set again; the document recomputed (rim 1's edge gone: the reference breaks or is
    held); then rim 2 dragged onto y = 0 and the document recomputed. Rim 2 was there at the last
    resolution: must not resolve silently to rim 2."""

    steps = ("draw", "delete", "slide_in")

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def draw(self, doc):
        doc.Profile.addGeometry(self.rect(2000), False)

    def delete(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Chamfer.Base = doc.Chamfer.Base
        self.edited = True

    def slide_in(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=0)


class PartialSketchOnlyThenSlide(Rim):
    """Rim 2 drawn; the document recomputed (resolved with rim 2); the Base set again with rim 1
    redrawn (hold); doc.recompute([Profile]) (sketch only; the Pad still to come); then the
    slide of rim 2 onto the vacated place; the document recomputed. Rim 2 was there: break."""

    steps = ("draw", "redraw_set_partial", "slide_in")

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def draw(self, doc):
        doc.Profile.addGeometry(self.rect(2000), False)

    def redraw_set_partial(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(self.rect(0), False)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.recompute([doc.Profile])

    def slide_in(self, doc):
        # delete the redrawn rim (the last four lines), drag rim 2 onto its place
        n = doc.Profile.GeometryCount
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=0)
        doc.Profile.delGeometries([n - 4, n - 3, n - 2, n - 1])
        self.edited = True


class RedrawSetBasePartialThroughPad(Rim):
    """Redraw in place, Base set again (hold), then doc.recompute([Rims]) (the Pad and its sketch,
    not the Chamfer that holds the reference: a recompute of the selected object), then the
    document. The Pad is made, so the end of the partial run takes the record with the redraw in
    its marks before the Chamfer has solved."""

    def edit(self, doc):
        self.redraw(doc)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.recompute([doc.Rims])


class RedrawPartialThroughPadNoSetter(Rim):
    """As above without the setter: no record is held; the partial recompute doesn't touch it."""

    def edit(self, doc):
        self.redraw(doc)
        doc.recompute([doc.Rims])


class RedrawSetBaseRecursiveSingle(Rim):
    """Redraw in place, Base set again, then Rims.recompute(True) (a recursive recompute of the
    Pad: the GUI's 'recompute selection'), then the document."""

    def edit(self, doc):
        self.redraw(doc)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Rims.recompute(True)


class CrossDocBinderSetter(Scenario):
    """Document B: rim padded; document A: a binder of its outer face; redraw in place in B, the
    binder's Support set again (hold), B.Pad.recompute() alone, then B.recompute()."""

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:600")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564son-r2"
    TIER = "F"
    SIZE = 600
    REFS = ("binder",)
    length, thickness, height = 600, 20, 100

    def outer(self):
        return face("plane", normal=-Y, through=(0, 0, 0))

    def want(self):
        return self.outer()

    def path(self, doc):
        return os.path.join(self.folder, doc.Name + ".FCStd")

    def build(self, doc):
        self.folder = os.path.realpath(tempfile.mkdtemp(prefix="NamingScenario"))
        L, T, H = self.s(self.length, self.thickness, self.height)
        target = self.newDocument("B")
        target.saveAs(self.path(target))
        body = m.body(target)
        profile = m.sketch(target, "Profile", m.rectangle(0, 0, L, T), body)
        pad = m.pad(body, profile, H, "Rims")
        target.recompute()
        target.save()
        doc.saveAs(self.path(doc))
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(pad, tuple(self.names(pad, self.outer())))]
        doc.recompute()
        self.target = target
        self.ref("binder", binder, "Support", lambda: self.want(), Bound())

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        B = self.target
        B.Profile.delGeometries([0, 1, 2, 3])
        B.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)
        doc.Binder.Support = doc.Binder.Support
        B.Profile.recompute()
        B.recompute()

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)
