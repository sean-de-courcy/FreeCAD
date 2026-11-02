"""Reviews prd2eopus-r4 and prd2eson-r4 (ops#526 D2, round 4): a record's marks taken again at every
recompute (214ee01e86). A record held through a Body or a later feature is refreshed before its
target is recomputed (`updateElementReferences` after an upstream shape changes), by a setter, or
by a reopen between the edit and the recompute: its marks then date the edit as there before. A
redraw in place breaks there where integration resolves it: right -> loud, accepted under D2's
Decision 120 (4) line until ops#564 (no refresh while the target is still to be recomputed). The
R3-1 family (a rim drawn after the reference, then slid onto the vacated place) still breaks
through both holders."""

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    Chamfered,
    Reopens,
    Scenario,
    X,
    edge,
)
from PartDesignTests.Scenarios import models as m


class TwoHolderRims(Scenario):
    """Rims 3600 x 45, 235 high, padded from one sketch (rim 1 at y = 0, others per `rims`); a
    datum Plane in the Body on rim 1's outer top edge (y = 0) of the Pad, and a Part Plane outside
    it attached (NormalToEdge) to the same edge of the Body."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#526"
    FOUND_BY = "review prd2eopus-r4"
    TIER = "F"
    SIZE = 4090
    REFS = ("inner", "plane")
    length, thickness, height = 3600, 45, 235
    rims = (0,)
    later = ()  # rims drawn after the references, recomputed before the edit
    edited = False

    def topEdge(self, y):
        y, H = self.s(y, self.height)
        return edge("line", direction=X, through=(0, y, H))

    def rect(self, y):
        L, T = self.s(self.length, self.thickness)
        return m.rectangle(0, self.s(y), L, self.s(y) + T)

    def want(self):
        return self.topEdge(0)

    def build(self, doc):
        H = self.s(self.height)
        body = m.body(doc)
        geometry = []
        for y in self.rims:
            geometry += self.rect(y)
        profile = m.sketch(doc, "Profile", geometry, body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        inner = body.newObject("PartDesign::Plane", "InnerPlane")
        inner.AttachmentSupport = [(pad, self.names(pad, self.topEdge(0))[0])]
        inner.MapMode = "NormalToEdge"
        doc.recompute()
        plane = doc.addObject("Part::Plane", "EdgePlane")
        plane.Length = plane.Width = self.s(10)
        plane.AttachmentSupport = [(body, self.names(body, self.topEdge(0))[0])]
        plane.MapMode = "NormalToEdge"
        doc.recompute()
        if self.later:
            more = []
            for y in self.later:
                more += self.rect(y)
            profile.addGeometry(more, False)
            doc.recompute()
        self.ref("inner", inner, "AttachmentSupport", lambda: self.want(), Attached())
        self.ref("plane", plane, "AttachmentSupport", lambda: self.want(), Attached())


class TwoHoldersRimRedrawnInPlace(TwoHolderRims):
    """Rims at y = 0 and 2000. Edit: rim 1's four lines deleted and the same rectangle drawn again
    (new IDs): decision 97 Q3's redraw in place, the person's edge is the redrawn one. Its cost
    case: the outer holder's marks are taken after the redraw (loud by design, 9.11 D2d)."""

    ISSUE = "ops#564"

    rims = (0, 2000)

    def edit(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(self.rect(0), False)


class TwoHoldersLaterRimSlid(TwoHolderRims):
    """R3-1 with both holders: rim 2 (y = 2000) drawn after the references and recomputed. Edit:
    rim 1's lines deleted, rim 2 dragged (IDs kept) to y = 0. Rim 1 is gone: both break."""

    later = (2000,)

    def want(self):
        return BROKEN if self.edited else self.topEdge(0)

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class TwoHoldersLaterRimSlidThick(TwoHoldersLaterRimSlid):
    """The same, rims 100 thick (beyond d_max)."""

    thickness = 100


class TwoHoldersSpareDrawnAndSlidOneEdit(TwoHolderRims):
    """Rim 1 alone. Edit (one recompute): a spare rim drawn at y = 2000, rim 1's lines deleted,
    the spare dragged (IDs kept) to y = 0. Decision 208 (3)'s accepted risk for the inner plane
    (drawn after the last resolution: a redraw); the expectation is the redrawn edge, as a redraw
    in place (the geometry can't be told from it)."""

    ISSUE = "ops#564"

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(self.rect(2000), False)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])


class TwoHoldersLaterRimSlidAfterUndo(TwoHolderRims):
    """Rim 2 (y = 2000) drawn after the references and recomputed (the records take its IDs).
    Step 1: rim 2's lines deleted (a transaction), recompute; step 2: undone, recompute; step 3:
    rim 1 deleted, rim 2 dragged (IDs kept) to y = 0. Rim 2 was in the model when the references
    last resolved: both break."""

    later = (2000,)
    steps = ("remove", "undo", "slide_in")
    stage = None

    def want(self):
        return BROKEN if self.stage == "slide_in" else self.topEdge(0)

    def remove(self, doc):
        self.stage = "remove"
        doc.UndoMode = 1
        doc.openTransaction("remove")
        doc.Profile.delGeometries([4, 5, 6, 7])
        doc.commitTransaction()

    def undo(self, doc):
        self.stage = "undo"
        doc.undo()

    def slide_in(self, doc):
        self.stage = "slide_in"
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])


# ---------------------------------------------------------------------------------------------
# the closure taken again: a sketch switched away and back (prd2eopus-r4)
# ---------------------------------------------------------------------------------------------


class SwitchedRims(Scenario):
    """Rims 3600 x 45, 235 high, at y = 0 and 2000, padded from sketch Profile (A); a datum Plane
    in the Body attached to rim 1's outer top edge (y = 0) of the Pad, and a Part Plane outside the
    Body attached (NormalToEdge) to the same edge of the Body. Step 1 (`away`): a sketch B with
    the same two rims is drawn and the Pad's Profile switched to it (A stays in the Body, unused):
    the same edge, now B's."""

    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#526"
    FOUND_BY = "review prd2eopus-r4"
    TIER = "F"
    SIZE = 4090
    REFS = ("inner", "plane")
    length, thickness, height = 3600, 45, 235
    rims = (0, 2000)
    stage = None

    def topEdge(self, y):
        y, H = self.s(y, self.height)
        return edge("line", direction=X, through=(0, y, H))

    def rect(self, y):
        L, T = self.s(self.length, self.thickness)
        return m.rectangle(0, self.s(y), L, self.s(y) + T)

    def want(self):
        return self.topEdge(0)

    def build(self, doc):
        H = self.s(self.height)
        body = m.body(doc)
        geometry = []
        for y in self.rims:
            geometry += self.rect(y)
        profile = m.sketch(doc, "Profile", geometry, body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        inner = body.newObject("PartDesign::Plane", "InnerPlane")
        inner.AttachmentSupport = [(pad, self.names(pad, self.topEdge(0))[0])]
        inner.MapMode = "NormalToEdge"
        doc.recompute()
        plane = doc.addObject("Part::Plane", "EdgePlane")
        plane.Length = plane.Width = self.s(10)
        plane.AttachmentSupport = [(body, self.names(body, self.topEdge(0))[0])]
        plane.MapMode = "NormalToEdge"
        self.ref("inner", inner, "AttachmentSupport", lambda: self.want(), Attached())
        self.ref("plane", plane, "AttachmentSupport", lambda: self.want(), Attached())

    def away(self, doc):
        self.stage = "away"
        geometry = []
        for y in self.rims:
            geometry += self.rect(y)
        b = m.sketch(doc, "B", geometry, doc.Body)
        doc.Rims.Profile = b


class SketchSwitchedAwayThenBack(SwitchedRims):
    """Step 2 (`back`): the Pad's Profile switched back to A, unchanged: rim 1's edge is the edge
    the references were made on (A's own lines, IDs as at the build)."""

    ISSUE = "ops#564"

    steps = ("away", "back")

    def back(self, doc):
        self.stage = "back"
        doc.Rims.Profile = doc.Profile


class SketchSwitchedAwayThenBackSlid(SwitchedRims):
    """Step 2 (`back`): in A, rim 1's lines deleted and rim 2 dragged (IDs kept) to y = 0; the
    Pad's Profile switched back to A. Rim 1 is gone and rim 2 was in A when the references were
    made (and in B at the last resolve): both break."""

    steps = ("away", "back")

    def want(self):
        return BROKEN if self.stage == "back" else self.topEdge(0)

    def back(self, doc):
        self.stage = "back"
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Rims.Profile = doc.Profile


class SketchSwitchedAwayThenBackRedrawn(SwitchedRims):
    """Step 2 (`back`): in A, rim 1's lines deleted and the same rectangle drawn again (new IDs);
    the Pad's Profile switched back to A. A redraw in place in a sketch switched in: decision 97
    Q3's redraw, the person's edge is the redrawn one (a warned guess is right too)."""

    ISSUE = "ops#564"

    steps = ("away", "back")

    def back(self, doc):
        self.stage = "back"
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(self.rect(0), False)
        doc.Rims.Profile = doc.Profile


# ---------------------------------------------------------------------------------------------
# an early refresh: a setter, a reopen, a Body-rooted holder (prd2eson-r4)
# ---------------------------------------------------------------------------------------------


class Redraw(Scenario):
    abstract = True
    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#526"
    FOUND_BY = "review prd2eson-r4"
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
        doc.recompute()
        self.ref("chamfer", chamfer, "Base", self.topEdge, Chamfered(self.s(5)))

    def redraw(self, doc):
        """The rim's lines deleted and the rectangle drawn again the other way round, at the
        same place (new geometry IDs): the quiet redraw (decision 97 Q3)."""
        L, T = self.s(self.length, self.thickness)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)


class RedrawThenSetBase(Redraw):
    """The redraw, and before the document recomputes the Chamfer's Base is set again (the
    task dialog's OK, a macro). The record refreshes from the unchanged Pad shape with the
    redraw's IDs in its marks: right on integration, broken here (right -> loud, by 9.8 Q3's
    literal rule)."""

    ISSUE = "ops#564"

    def edit(self, doc):
        self.redraw(doc)
        doc.Chamfer.Base = doc.Chamfer.Base


class RedrawThenReopen(Reopens, Redraw):
    """The redraw, the document saved and opened again before it is recomputed (the saved
    record's check refreshes the marks from the live sketch): right on integration, broken
    here (right -> loud)."""

    ISSUE = "ops#564"

    steps = ("redraw_and_reopen",)

    def redraw_and_reopen(self, doc):
        self.redraw(doc)
        self.reopen(doc)


class BodyEdgeRedrawn(Scenario):
    """A sketch outside the Body attached to the Body's own edge (Body, "EdgeN"): how an
    assembly joint or a datum in another part holds it. The rim redrawn at the same place. The
    Pad's shape is set first and refreshes the record against the Body's old shape with the
    redraw's IDs: the Body's solve then finds the redraw was there before and breaks. Right on
    integration (right -> loud here)."""

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#564"
    FOUND_BY = "review prd2eson-r4"
    TIER = "F"
    SIZE = 3600
    REFS = ("ext",)
    length, thickness, height = 3600, 45, 235

    def topEdge(self):
        return edge("line", direction=X, through=(0, 0, self.s(self.height)))

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        ext = doc.addObject("Sketcher::SketchObject", "Ext")
        ext.AttachmentSupport = [(body, self.names(body, self.topEdge()))]
        ext.MapMode = "NormalToEdge"
        doc.recompute()
        self.ref("ext", ext, "AttachmentSupport", self.topEdge, Attached())

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon([(L, T), (L, 0), (0, 0), (0, T)]), False)


class BodyEdgeSiblingDraggedIn(BodyEdgeRedrawn):
    """The Body-level holder of BodyEdgeRedrawn, with a second rim drawn after the reference
    (recomputed), then rim 1 deleted and rim 2 dragged (IDs kept) onto its place: a sibling,
    the reference must break (the R3-1 family through a Body-rooted reference)."""

    ISSUE = "ops#526"
    steps = ("draw", "slide_in")
    stage = None

    def want(self):
        return BROKEN if self.stage == "slide_in" else self.topEdge()

    def build(self, doc):
        super().build(doc)
        self.refs["ext"].expect = lambda: self.want()

    def draw(self, doc):
        self.stage = "draw"
        L, T = self.s(self.length, self.thickness)
        doc.Profile.addGeometry(m.rectangle(0, self.s(2000), L, self.s(2000) + T), False)

    def slide_in(self, doc):
        self.stage = "slide_in"
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
