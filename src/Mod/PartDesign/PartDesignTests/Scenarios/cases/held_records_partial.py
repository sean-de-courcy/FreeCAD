"""Review pr564opus-r1 (ops#564): the end of any Document::recompute() takes a held record once
the reference's object and the element's holder aren't touched, even when the recompute was a
partial one that never reached them and an object between (the sketch) is still to be recomputed.
RedrawThenSetBase with an unrelated partial recompute between the setter and the document's
recompute."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Chamfered, Scenario, X, edge
from PartDesignTests.Scenarios import models as m


class RedrawSetBasePartial(Scenario):
    """A rim 3600 x 45, 235 high, padded from Profile in a Body; a Chamfer (5) on its outer top
    edge (y = 0); a Part Box "Spare" elsewhere, not linked to anything. Edit: the rim's lines
    deleted and drawn again the other way round at the same place (new IDs), the Chamfer's Base
    set again (a dialog's OK), then `doc.recompute([Spare])` (a partial recompute of something
    else: a task dialog's recursive preview, a macro), and the document recomputed. The redraw in
    place: the person's edge is the redrawn one (decision 97 Q3)."""

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564opus-r1"
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

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Spare.touch()
        doc.recompute([doc.Spare])

