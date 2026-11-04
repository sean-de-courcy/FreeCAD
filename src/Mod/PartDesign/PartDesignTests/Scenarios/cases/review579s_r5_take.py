"""Review pr579s-r5 (ops#579, decision 263): the take's skip for a record whose marks are its
target's closure's marks now.

A record whose marks are unchanged is not taken again while its target is down; the take also
refreshed the frame, the placement sources and their digest. These cases move the target, or what
it is built from, while it is down: a sketch's Placement moves (no new geometry, so the marks stay),
and the reference must follow the boss (or break) after the fix, as with no failure at all.

The model: a 600 x 300 block padded 300 high (Pad1, the Body's first feature: its failure stops the
Body); a boss 100 x 100 x 50 on its top at x 100..200 (Boss). The reference: a sketch attached to the
boss's face at x = 200 (normal +X), outside the Body.
"""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Attached, Scenario, X, face
from PartDesignTests.Scenarios import models as m


class Take(Scenario):
    abstract = True
    area = "failure"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "X4:600")
    ISSUE = "ops#579"
    FOUND_BY = "review pr579s-r5"
    TIER = "F"
    SIZE = 600
    REFS = ("side",)
    dx = 0       # how far the boss has moved in x
    dy = 0

    def side(self):
        return face("plane", normal=X, through=self.s(200 + self.dx, 150 + self.dy, 325))

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        m.pad(body, base, self.s(300), "Pad1")
        sk = m.sketch(doc, "BossS", m.rectangle(*self.s(100, 100, 200, 200)), body, z=self.s(300))
        boss = m.pad(body, sk, self.s(50), "Boss")
        doc.recompute()
        side = doc.addObject("Sketcher::SketchObject", "OnSide")
        side.AttachmentSupport = [(boss, self.names(boss, self.side())[0])]
        side.MapMode = "FlatFace"
        self.ref("side", side, "AttachmentSupport", self.side, Attached())

    # -- edit pieces ----------------------------------------------------------------------------
    def stop(self, doc):
        doc.Pad1.Length = 0

    def fixPad(self, doc):
        doc.Pad1.Length = self.s(300)

    def movePiece(self, doc, d=50):
        for name in ("Base", "BossS"):
            sk = getattr(doc, name)
            p = sk.Placement
            sk.Placement = App.Placement(p.Base + App.Vector(self.s(d), 0, 0), p.Rotation)
        self.dx += d

    def moveBoss(self, doc, d=50):
        p = doc.BossS.Placement
        doc.BossS.Placement = App.Placement(p.Base + App.Vector(self.s(d), 0, 0), p.Rotation)
        self.dx += d

    def moveBossInSketch(self, doc, d=20):
        # the boss's lines moved in place (same IDs): the sketch's rectangle slid in x
        m.moveRectangle(doc.BossS, *self.s(100 + d, 100, 200 + d, 200))
        self.dx += d


class TakeMovePieceDown(Take):
    """Stopped; the part is moved while down; then fixed."""
    steps = ("stop", "movePiece", "fixPad")


class TakeMovePieceWithStop(Take):
    """The part is moved in the edit that stops the Body; then fixed."""
    steps = ("stopAndMove", "fixPad")

    def stopAndMove(self, doc):
        self.stop(doc)
        self.movePiece(doc)


class TakeMovePieceAtFix(Take):
    steps = ("stop", "fixAndMove")

    def fixAndMove(self, doc):
        self.fixPad(doc)
        self.movePiece(doc)


class TakeMovePieceControl(Take):
    steps = ("movePiece",)


class TakeMoveBossDown(Take):
    """Stopped; the boss's sketch is moved while down; then fixed."""
    steps = ("stop", "moveBoss", "fixPad")


class TakeMoveBossControl(Take):
    steps = ("moveBoss",)


class TakeSlideBossLinesDown(Take):
    """Stopped; the boss's rectangle slid in place (the IDs stay); then fixed."""
    steps = ("stop", "moveBossInSketch", "fixPad")


class TakeSlideBossLinesControl(Take):
    steps = ("moveBossInSketch",)


class TakeMoveTwiceDown(Take):
    """Stopped; the part moved, the Body recomputed, moved again, then fixed."""
    steps = ("stop", "movePiece", "movePiece2", "fixPad")

    def movePiece2(self, doc):
        self.movePiece(doc, 30)


# -- a reference into the failed first Pad itself, and a turn of the part ---------------------------


class TakeOwn(Take):
    """The reference is into Pad1's front face (y = 0), the object that fails."""

    abstract = True
    REFS = ("front",)
    turn = 0   # quarter turns about Z done so far

    def _rot(self, pt):
        x, y, z = pt
        for _ in range(self.turn % 4):
            x, y = -y, x
        return (x, y, z)

    def _nrm(self, n):
        x, y, z = n
        for _ in range(self.turn % 4):
            x, y = -y, x
        return (x, y, z)

    def front(self):
        return face("plane", normal=self._nrm((0, -1, 0)),
                    through=self._rot(self.s(300 + self.dx, 0, 150)))

    def build(self, doc):
        body = m.body(doc)
        base = m.sketch(doc, "Base", m.rectangle(0, 0, *self.s(600, 300)), body)
        m.pad(body, base, self.s(300), "Pad1")
        sk = m.sketch(doc, "BossS", m.rectangle(*self.s(100, 100, 200, 200)), body, z=self.s(300))
        m.pad(body, sk, self.s(50), "Boss")
        doc.recompute()
        side = doc.addObject("Sketcher::SketchObject", "OnFront")
        side.AttachmentSupport = [(doc.Pad1, self.names(doc.Pad1, self.front())[0])]
        side.MapMode = "FlatFace"
        self.ref("front", side, "AttachmentSupport", self.front, Attached())

    def turnPiece(self, doc):
        R = App.Rotation(App.Vector(0, 0, 1), 90)
        for name in ("Base", "BossS"):
            sk = getattr(doc, name)
            p = sk.Placement
            sk.Placement = App.Placement(R.multVec(p.Base), R.multiply(p.Rotation))
        self.turn += 1


class TakeOwnMoveDown(TakeOwn):
    steps = ("stop", "movePiece", "fixPad")


class TakeOwnMoveControl(TakeOwn):
    steps = ("movePiece",)


class TakeOwnTurnDown(TakeOwn):
    """Stopped; the part is turned a quarter about Z while down; then fixed."""
    steps = ("stop", "turnPiece", "fixPad")


class TakeOwnTurnControl(TakeOwn):
    steps = ("turnPiece",)


class TakeOwnTurnWithStop(TakeOwn):
    steps = ("turnAndStop", "fixPad")

    def turnAndStop(self, doc):
        self.turnPiece(doc)
        self.stop(doc)


class TakeTurnDown(Take):
    """The boss reference; stopped, the part turned while down, then fixed."""
    steps = ("stop", "turnPiece", "fixPad")
    turn = 0

    def side(self):
        x, y, z = self.s(200 + self.dx, 150, 325)
        n = (1, 0, 0)
        for _ in range(self.turn % 4):
            x, y = -y, x
            n = (-n[1], n[0], 0)
        return face("plane", normal=n, through=(x, y, z))

    def turnPiece(self, doc):
        R = App.Rotation(App.Vector(0, 0, 1), 90)
        for name in ("Base", "BossS"):
            sk = getattr(doc, name)
            p = sk.Placement
            sk.Placement = App.Placement(R.multVec(p.Base), R.multiply(p.Rotation))
        self.turn += 1


class TakeTurnControl(TakeTurnDown):
    steps = ("turnPiece",)
