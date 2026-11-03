"""Review pr564opus-r1 (ops#564): a record held while its target is still to be recomputed is
taken again only at the end of a Document::recompute() of the holder's own document. Paths where
the reference resolves (and D2 took the record) but no such end comes before the next edit:
- a holder in another document than its target (only the target's document is recomputed);
- a non-recursive recompute of the target (obj.recompute(), a task dialog's preview).
The R3-1 family on them: a rim drawn after the reference, the reference resolved, then the rim
slid onto the vacated place: it must break."""

import os
import shutil
import tempfile

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    Bound,
    Scenario,
    X,
    Y,
    edge,
    face,
)
from PartDesignTests.Scenarios import models as m


class CrossDocRims(Scenario):
    """Document B: rim 1 (L x T, H high) padded from sketch Profile in a Body. Document A (the
    scenario's): a SubShapeBinder of the pad's outer face of rim 1 (y = 0, normal -Y)."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:600")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564opus-r1"
    TIER = "F"
    SIZE = 600
    REFS = ("binder",)
    length, thickness, height = 600, 20, 100
    second = 300
    edited = False

    def outer(self):
        return face("plane", normal=-Y, through=(0, 0, 0))

    def want(self):
        return self.outer()

    def rect(self, y):
        L, T = self.s(self.length, self.thickness)
        return m.rectangle(0, self.s(y), L, self.s(y) + T)

    def path(self, doc):
        return os.path.join(self.folder, doc.Name + ".FCStd")

    def build(self, doc):
        self.folder = os.path.realpath(tempfile.mkdtemp(prefix="NamingScenario"))
        target = self.newDocument("B")
        target.saveAs(self.path(target))
        body = m.body(target)
        profile = m.sketch(target, "Profile", self.rect(0), body)
        pad = m.pad(body, profile, self.s(self.height), "Rims")
        target.recompute()
        target.save()
        doc.saveAs(self.path(doc))
        binder = doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(pad, tuple(self.names(pad, self.outer())))]
        doc.recompute()
        self.target = target
        self.ref("binder", binder, "Support", lambda: self.want(), Bound())

    def cleanup(self):
        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class CrossDocSiblingSlidAfterItsRecompute(CrossDocRims):
    """Rim 2 (y = second) drawn in B and B recomputed (the binder's reference resolves: its
    record should take rim 2's IDs); then rim 1's lines deleted and rim 2 dragged (IDs kept) to
    y = 0, B recomputed, then A. Rim 2 was in the model when the reference last resolved: the
    reference must break (R3-1 across documents)."""

    def want(self):
        return BROKEN if self.edited else self.outer()

    def edit(self, doc):
        B = self.target
        B.Profile.addGeometry(self.rect(self.second), False)
        B.recompute()
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(B.Profile, 0, 0, L, T, first=4)
        B.Profile.delGeometries([0, 1, 2, 3])
        B.recompute()
        self.edited = True


class CrossDocSiblingSlidAfterBothRecomputes(CrossDocRims):
    """The control: as CrossDocSiblingSlidAfterItsRecompute with A recomputed after the draw
    (two steps). Must break."""

    steps = ("draw", "slide_in")

    def want(self):
        return BROKEN if self.edited else self.outer()

    def draw(self, doc):
        self.target.Profile.addGeometry(self.rect(self.second), False)
        self.target.recompute()

    def slide_in(self, doc):
        B = self.target
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(B.Profile, 0, 0, L, T, first=4)
        B.Profile.delGeometries([0, 1, 2, 3])
        B.recompute()
        self.edited = True


class CrossDocRimRedrawnInPlace(CrossDocRims):
    """Rim 1's lines deleted and the rectangle drawn again the other way round at the same place
    (new IDs), B recomputed, then A: decision 97 Q3's redraw in place, the person's face is the
    redrawn one."""

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        B = self.target
        B.Profile.delGeometries([0, 1, 2, 3])
        B.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)
        B.recompute()


class FeatureRecomputeRims(Scenario):
    """One document: rim 1 (L x T, H high) padded from Profile in a Body; a datum Plane in the
    Body on rim 1's outer top edge (y = 0) of the Pad ("inner"), and a Part Plane outside it
    attached (NormalToEdge) to the same edge of the Body ("plane")."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:600")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564opus-r1"
    TIER = "F"
    SIZE = 600
    REFS = ("inner", "plane")
    length, thickness, height = 600, 20, 100
    second = 300
    edited = False

    def topEdge(self):
        return edge("line", direction=X, through=(0, 0, self.s(self.height)))

    def want(self):
        return BROKEN if self.edited else self.topEdge()

    def rect(self, y):
        L, T = self.s(self.length, self.thickness)
        return m.rectangle(0, self.s(y), L, self.s(y) + T)

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", self.rect(0), body)
        pad = m.pad(body, profile, self.s(self.height), "Rims")
        doc.recompute()
        inner = body.newObject("PartDesign::Plane", "InnerPlane")
        inner.AttachmentSupport = [(pad, self.names(pad, self.topEdge())[0])]
        inner.MapMode = "NormalToEdge"
        doc.recompute()
        plane = doc.addObject("Part::Plane", "EdgePlane")
        plane.Length = plane.Width = self.s(10)
        plane.AttachmentSupport = [(body, self.names(body, self.topEdge())[0])]
        plane.MapMode = "NormalToEdge"
        doc.recompute()
        self.ref("inner", inner, "AttachmentSupport", lambda: self.want(), Attached())
        self.ref("plane", plane, "AttachmentSupport", lambda: self.want(), Attached())

    def slide(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class SiblingSlidAfterFeatureRecomputes(FeatureRecomputeRims):
    """Rim 2 drawn, then the sketch, the Pad and the Body recomputed one by one, non-recursively
    (obj.recompute(), as a macro or a task dialog's preview does): the references resolve against
    the model with rim 2. Then rim 1 deleted and rim 2 dragged (IDs kept) to y = 0, and the
    document recomputed. Rim 2 was in the model at the last resolution: both must break."""

    def edit(self, doc):
        doc.Profile.addGeometry(self.rect(self.second), False)
        for name in ("Profile", "Rims", "Body"):
            doc.getObject(name).recompute()
        self.slide(doc)


class SiblingSlidAfterRecursiveRecompute(FeatureRecomputeRims):
    """The control: as SiblingSlidAfterFeatureRecomputes with the Body recomputed recursively
    (obj.recompute(True): a Document::recompute()). Both must break."""

    def edit(self, doc):
        doc.Profile.addGeometry(self.rect(self.second), False)
        doc.Body.recompute(True)
        self.slide(doc)
