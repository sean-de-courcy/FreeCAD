"""Review pr564son-r3 (ops#564 round 3): twins. Two equal rims A (y = 0) and B (y = 2000) padded
from one sketch; a Chamfer (5) on A's outer top edge. The records of a closure member recomputed
alone after a setter are taken early (loud side by design): do the twins turn that into a silent
pick of B?"""

from PartDesignTests.Scenarios.harness import (
    BROKEN, Chamfered, Scenario, X, edge,
)
from PartDesignTests.Scenarios import models as m


class TwinRims(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review pr564son-r3"
    TIER = "F"
    SIZE = 3600
    REFS = ("chamfer",)
    length, thickness, height = 3600, 45, 235

    def topEdge(self, y=0):
        return edge("line", direction=X, through=(0, self.s(y), self.s(self.height)))

    def want(self):
        return self.topEdge()

    def rect(self, y):
        L, T = self.s(self.length, self.thickness)
        return m.rectangle(0, self.s(y), L, self.s(y) + T)

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", self.rect(0) + self.rect(2000), body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, self.names(pad, self.topEdge()))
        chamfer.Size = self.s(5)
        doc.recompute()
        self.ref("chamfer", chamfer, "Base", lambda: self.want(), Chamfered(self.s(5)))

    def poly(self, y):
        L, T = self.s(self.length, self.thickness)
        y = self.s(y)
        return m.polygon([(L, y + T), (L, y), (0, y), (0, y + T)])


class TwinARedrawnSketchSingle(TwinRims):
    """A redrawn in place, Base set, the sketch recomputed alone, the document."""

    def edit(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(self.poly(0), False)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Profile.recompute()


class TwinARedrawnNoSetter(TwinRims):
    """The control: A redrawn in place, the document."""

    def edit(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(self.poly(0), False)


class TwinBothRedrawnSketchSingle(TwinRims):
    """Both rims redrawn in place (B first, then A), Base set, the sketch recomputed alone."""

    def edit(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3, 4, 5, 6, 7])
        doc.Profile.addGeometry(self.poly(2000), False)
        doc.Profile.addGeometry(self.poly(0), False)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Profile.recompute()


class TwinBothRedrawnNoSetter(TwinRims):
    """The control: both redrawn in place (B first, then A), the document."""

    def edit(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3, 4, 5, 6, 7])
        doc.Profile.addGeometry(self.poly(2000), False)
        doc.Profile.addGeometry(self.poly(0), False)


class TwinARedrawnPadSingle(TwinRims):
    """A redrawn in place, Base set, the Pad recomputed alone, the document."""

    def edit(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(self.poly(0), False)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Rims.recompute()


class TwinBothRedrawnPadSingle(TwinRims):
    """Both redrawn in place (B first), Base set, the Pad recomputed alone, the document."""

    def edit(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3, 4, 5, 6, 7])
        doc.Profile.addGeometry(self.poly(2000), False)
        doc.Profile.addGeometry(self.poly(0), False)
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Rims.recompute()


class TwinSwapSketchSingle(TwinRims):
    """A deleted, B kept; a new rim drawn at A's place; Base set; sketch alone. (A redrawn in
    place with B untouched, the other order of the lines.)"""

    def edit(self, doc):
        doc.Profile.addGeometry(self.poly(0), False)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Chamfer.Base = doc.Chamfer.Base
        doc.Profile.recompute()
