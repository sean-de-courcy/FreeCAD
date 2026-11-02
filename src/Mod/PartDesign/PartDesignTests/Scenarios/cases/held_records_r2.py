"""Review pr564opus-r2 (ops#564 round 2): the round's two new ways a held record is taken.
- recomputeFeature() outside a document's recompute takes every held record (T2's fix), whatever
  the object recomputed and whatever is still touched: a redraw in place held by a setter is then
  taken from the unchanged Pad with the redraw's marks.
- at the end of a recompute, an object of the closure the run included but left touched (a Body's
  members past its roll-back bar) no longer holds the record (T3's fix): the same early take.
RedrawThenSetBase (vacated_place_holders.py) with each of them between the setter and the
recompute that makes the target. The redraw in place: the person's edge is the redrawn one
(decision 97 Q3)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Chamfered, Scenario, X, edge
from PartDesignTests.Scenarios import models as m


class RedrawSetBaseBase(Scenario):
    """A rim 3600 x 45, 235 high, padded from Profile in a Body; a Chamfer (5) on its outer top
    edge (y = 0); a Part Box "Spare" elsewhere, not linked to anything."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564opus-r2"
    TIER = "F"
    SIZE = 3600
    REFS = ("chamfer",)
    length, thickness, height = 3600, 45, 235

    def topEdge(self):
        return edge("line", direction=X, through=(0, 0, self.s(self.height)))

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
        self.ref("chamfer", chamfer, "Base", self.topEdge, Chamfered(self.s(5)))

    def redrawAndSet(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)
        doc.Chamfer.Base = doc.Chamfer.Base


class RedrawSetBaseSpareAlone(RedrawSetBaseBase):
    """The redraw, the Chamfer's Base set again (a dialog's OK), then the unrelated Spare
    recomputed alone (`Spare.recompute()`: a Part primitive dialog's preview, a macro), then the
    document recomputed."""

    def edit(self, doc):
        self.redrawAndSet(doc)
        doc.Spare.touch()
        doc.Spare.recompute()
        doc.recompute()


class RedrawSetBaseHolderPreview(RedrawSetBaseBase):
    """The redraw, the Chamfer's Base set again, then the Chamfer recomputed alone (its task
    dialog's preview: `recomputeFeature(obj, false)`), then the document recomputed."""

    def edit(self, doc):
        self.redrawAndSet(doc)
        doc.Chamfer.recompute()
        doc.recompute()


class RolledBackRedrawSetBase(Scenario):
    """A block Pad0 (100 x 100, H/2 high) at the rim's far inner corner, then the rim 3600 x 45,
    235 high (Rims, fused with Pad0), a Chamfer (5) on the rim's outer top edge (y = 0). Edit: the
    Tip rolled back to Pad0 and the document recomputed; the rim redrawn in place (new IDs) and
    the Chamfer's Base set again; the document recomputed (Rims and the Chamfer held past the
    bar); the Tip brought forward to the Chamfer and the document recomputed. The redraw in place:
    the person's edge is the redrawn one."""

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564opus-r2"
    TIER = "F"
    SIZE = 3600
    REFS = ("chamfer",)
    length, thickness, height = 3600, 45, 235

    def topEdge(self):
        return edge("line", direction=X, through=(0, 0, self.s(self.height)))

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        B = self.s(100)
        body = m.body(doc)
        block = m.sketch(doc, "Block", m.rectangle(L - B, T, L, T + B), body)
        m.pad(body, block, H / 2, "Pad0")
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, self.names(pad, self.topEdge()))
        chamfer.Size = self.s(5)
        doc.recompute()
        self.ref("chamfer", chamfer, "Base", self.topEdge, Chamfered(self.s(5)))

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Body.Tip = doc.Pad0
        doc.recompute()
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.recompute()
        doc.Body.Tip = doc.Chamfer
        doc.recompute()


class RolledBackRedraw(RolledBackRedrawSetBase):
    """The control: the same without the setter."""

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Body.Tip = doc.Pad0
        doc.recompute()
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)
        doc.recompute()
        doc.Body.Tip = doc.Chamfer
        doc.recompute()
