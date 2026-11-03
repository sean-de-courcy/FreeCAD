# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr557o-r2f (fork PR 557o round 2f, decision 236's two stops): attacks on the guard of
211's quiet keep (FOLLOWED empty while the twin sits at OLD), on the frame route's quiet paths
the guard doesn't cover (a naming migration in the same recompute), and on the routes neither
stop reaches. Designed geometry only: the 30 x 20 ring of pipe_closed_r6l.py and its square
profile, the whole model turned by its sketches' Placements (the frame turns), the Pipe's
Binormal set while its Mode is Standard (it drives nothing, but the closure reads "not one
piece", so decision 211 decides). The expectation follows the part (decision 212) and the
history of the edited element."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, OwnOrBroken, Scenario, X, Y, Z, edge, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector


def originFeature(body, role):
    return [f for f in body.Origin.OriginFeatures if role in (getattr(f, "Role", ""), f.Name)][0]


class Ring(Scenario):
    abstract = True
    area = "rigid-review"
    CLASSES = ("D",)
    AXES = ("M3", "E7", "E2")
    ISSUE = "ops#557"
    FOUND_BY = "review pr557o-r2f"
    TIER = "F"
    SIZE = 60
    SCALE = 1.0
    half = 2
    verts0 = ((0, 0), (0, 20), (30, 20), (30, 0))
    pivot = (15, 0, 10)
    axis = Y
    degrees = 0
    verts = None
    route = "placement"  # or "offset"
    held = "feature"  # or "body"
    binormal = V(0, 0, 1)
    startShift = (0, 0, 0)  # where the edit moved the start corner in the ring's own frame
    REFS = ("leg0", "leg1", "leg2", "leg3", "start_pt")

    A = property(lambda self: self.s(self.half))

    def P(self):
        if self.verts is None:
            self.verts = [tuple(self.s(c) for c in p) for p in self.verts0]
        return self.verts

    def T(self):
        rot = App.Rotation(self.axis, self.degrees)
        c = V(*(self.s(v) for v in self.pivot))
        return App.Placement(c - rot.multVec(c), rot)

    def at(self, x, y, z):
        return self.T().multVec(V(x, y, z))

    def along(self, d):
        return self.T().Rotation.multVec(d)

    def legFace(self, i):
        def predicate():
            P = self.P()
            n = len(P)
            (x0, z0), (x1, z1) = P[i % n], P[(i + 1) % n]
            dx, dz = x1 - x0, z1 - z0
            L = math.hypot(dx, dz)
            nx, nz = -dz / L, dx / L
            mx, mz = (x0 + x1) / 2 + nx * self.A, (z0 + z1) / 2 + nz * self.A
            return face("plane", normal=self.along(V(nx, 0, nz)), contains=self.at(mx, 0, mz))

        return predicate

    def startPoint(self):
        a = self.A
        dx, dy, dz = (self.s(c) for c in self.startShift) if self.stepName else (0, 0, 0)
        return vertex(self.at(-a + dx, -a + dy, -a + dz))

    def spinePlacement(self):
        return self.T().multiply(App.Placement(V(), App.Rotation(X, 90)))

    def profilePlacement(self):
        return self.T()

    def place(self):
        if self.route == "offset":
            self.spine.AttachmentOffset = self.xz.Placement.inverse().multiply(self.spinePlacement())
            self.profile.AttachmentOffset = self.xy.Placement.inverse().multiply(self.profilePlacement())
        else:
            self.spine.Placement = self.spinePlacement()
            self.profile.Placement = self.profilePlacement()

    def build(self, doc):
        body = m.body(doc)
        self.body = body
        self.xz = originFeature(body, "XZ_Plane")
        self.xy = originFeature(body, "XY_Plane")
        P = self.P()
        self.spine = m.sketch(doc, "Spine", m.polygon(P), body)
        a = self.A
        self.profile = m.sketch(doc, "Square", m.rectangle(-a, -a, a, a), body)
        if self.route == "offset":
            self.spine.AttachmentSupport = [(self.xz, "")]
            self.spine.MapMode = "FlatFace"
            self.profile.AttachmentSupport = [(self.xy, "")]
            self.profile.MapMode = "FlatFace"
        self.place()
        doc.recompute()
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.spine, [])
        pipe.Transition = "Right corner"
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise RuntimeError(f"the pipe is invalid: {pipe.getStatusString()}")
        self.pipe = pipe
        if self.binormal is not None:
            pipe.Binormal = self.binormal
            doc.recompute()
        target = body if self.held == "body" else pipe
        made = {}
        n = len(P)
        for name in self.REFS:
            if name.startswith("leg"):
                i = int(name[3:])
                predicate = self.legFace(i)
                if self.held == "body":
                    obj = doc.addObject("Sketcher::SketchObject", name)
                else:
                    obj = body.newObject("PartDesign::Plane", name)
                obj.MapMode = "FlatFace"
            else:
                predicate = self.startPoint
                if self.held == "body":
                    obj = doc.addObject("Sketcher::SketchObject", name)
                    obj.MapMode = "Translate"
                else:
                    obj = body.newObject("PartDesign::Point", name)
                    obj.MapMode = "Vertex"
            obj.AttachmentSupport = [(target, self.names(target, predicate()))]
            made[name] = (obj, predicate)
        doc.recompute()
        for name, (obj, predicate) in made.items():
            self.ref(name, obj, "AttachmentSupport", predicate, Attached())

    def moveVerts(self, verts0, redraw=False):
        """The spine's corners moved to verts0: each line's own endpoints moved (its geometry ID
        kept), or every line drawn anew (redraw)."""
        self.verts = None
        self.verts0 = verts0
        P = self.P()
        n = len(P)
        g = self.spine.Geometry
        for i in range(n):
            p, q = P[i], P[(i + 1) % n]
            if redraw:
                g[i] = Part.LineSegment(V(p[0], p[1], 0), V(q[0], q[1], 0))
            else:
                line = g[i]
                line.StartPoint = V(p[0], p[1], 0)
                line.EndPoint = V(q[0], q[1], 0)
                g[i] = line
        self.spine.Geometry = g

    def turn(self):
        self.degrees = 180
        self.place()

    def edit(self, doc):
        self.turn()
        doc.recompute()


# ---- the guard with FOLLOWED empty: the followed corner moved by the same edit


class RfHexStaleBinormalTurnedKinked(Ring):
    """The stale-Binormal ring as a hexagon symmetric under the half turn ((0, 0), (0, 10),
    (0, 20), (30, 20), (30, 10), (30, 0): its left and right legs split at their middles), the
    whole model turned 180 about the ring's normal, and in the same recompute the left leg's
    middle corner (0, 10) moved to (-1, 10) (each line keeping its geometry ID). The pipe's
    start, read in the body, stays at the old start corner, where the turned ring's (30, 20)
    corner now sits: a twin of the start corner, which the edit leaves as it was (its legs keep
    their directions). The start corner went with the part to the turned (0, 0) corner, whose
    mitre the kink moved: nothing matches the record there (FOLLOWED empty), so the guard lets
    211 keep the twin. The reference follows the part: the start corner's mitre at the turned
    (0, 0), or it breaks."""

    verts0 = ((0, 0), (0, 10), (0, 20), (30, 20), (30, 10), (30, 0))
    kinked = ((0, 0), (-1, 10), (0, 20), (30, 20), (30, 10), (30, 0))
    REFS = ("leg2", "leg3", "start_pt")

    def startPoint(self):
        a = self.A
        if not self.stepName:
            return vertex(self.at(-a, -a, -a))
        # The mitre of the legs (30, 0) -> (0, 0) (outer offset z = -a) and (0, 0) -> P1
        P = self.P()
        (x0, z0), (x1, z1) = P[0], P[1]
        dx, dz = x1 - x0, z1 - z0
        L = math.hypot(dx, dz)
        nx, nz = -dz / L, dx / L  # outward (away from the ring's inside)
        # the point on z = -a with ((x, z) - (P0 + a n)) . n = 0
        px, pz = x0 + a * nx, z0 + a * nz
        z = -a
        x = px - (z - pz) * nz / nx
        return OwnOrBroken(vertex(self.at(x, -a, z)))

    def edit(self, doc):
        self.moveVerts(self.kinked)
        self.turn()
        doc.recompute()


class RfHexStaleBinormalTurned(RfHexStaleBinormalTurnedKinked):
    """Control: the hexagon turned, no kink (Rv2eRingStaleBinormalTurned's case)."""

    kinked = RfHexStaleBinormalTurnedKinked.verts0


class RfHexStaleBinormalTurnedKinkedRedrawn(RfHexStaleBinormalTurnedKinked):
    """As RfHexStaleBinormalTurnedKinked, every spine line drawn anew (new geometry IDs: the
    references miss, and the missing entries' pick guard decides)."""

    def edit(self, doc):
        self.moveVerts(self.kinked, redraw=True)
        self.turn()
        doc.recompute()


# ---- the frame route's quiet keep in a naming migration (the guard isn't there)


class RfRingStaleBinormalTurnedMigrated(Ring):
    """Rv2eRingStaleBinormalTurned (the stale Binormal, the whole model turned 180 about the
    ring's normal, nothing else edited) in a recompute that is also a naming migration: the
    Pipe's stamped element-map version is stale (set to an older string before the recompute,
    as a file from an older build opens). Every reference follows the turn. (The migration's
    frame keep is not reached: the update on the old shape under the new frame, where the stamp
    is renewed, skips the frame-moved entries, and the later update solves them in solveOwner.)"""

    def edit(self, doc):
        self.pipe._ElementMapVersion = "stale"
        self.turn()
        doc.recompute()


class RfRingStaleBinormalMigratedNoTurn(RfRingStaleBinormalTurnedMigrated):
    """Control: the migration alone, nothing moved."""

    def edit(self, doc):
        self.pipe._ElementMapVersion = "stale"
        self.pipe.touch()
        doc.recompute()


class RfRingTurnedMigrated(RfRingStaleBinormalTurnedMigrated):
    """Control: the plain ring (no Binormal: rigid) turned 180 in a migration."""

    binormal = None


class RfRingStaleBinormalTurnedRedrawnMigrated(RfRingStaleBinormalTurnedMigrated):
    """As RfRingStaleBinormalTurnedMigrated, every spine line drawn anew in the same recompute
    (the references miss: the migration's index carry)."""

    def edit(self, doc):
        self.pipe._ElementMapVersion = "stale"
        self.moveVerts(self.verts0, redraw=True)
        self.turn()
        doc.recompute()


# ---- the snap-back of a guess at the old place (the frame route's other quiet keep)


class RfRingStaleBinormalGuessThenTurnUndo(Ring):
    """The stale-Binormal ring. (1) The profile square drawn anew in an undo transaction (the
    start corner and the legs are found again where they were: guesses with their originals'
    records); (2) the whole model turned 180 about the ring's normal (the frame route: the
    closure is not one piece); (3) the redraw undone: the original's names give elements again,
    and a guess snaps back if its name's element agrees with the original's record mapped to
    where it was before the turn. The references follow the turn. The finding: the start
    corner's guess snaps back by its original's name to the pipe's start, read in the body at the
    old start corner, where the turned ring's twin corner sits (ElementSolverBatch.cpp's snap-back,
    the frame branch: the original's record mapped to where it was, no scan there or where it
    went), quietly; c734dca553 breaks it."""

    steps = ("redrawProfile", "doTurn", "undoRedraw")

    def redrawProfile(self, doc):
        doc.UndoMode = 1
        a = self.A
        doc.openTransaction("redraw")
        self.profile.deleteAllGeometry()
        self.profile.addGeometry(m.polygon([(a, a), (-a, a), (-a, -a), (a, -a)]), False)
        doc.commitTransaction()
        doc.recompute()

    def doTurn(self, doc):
        self.turn()
        doc.recompute()

    def undoRedraw(self, doc):
        doc.undo()
        self.place()
        doc.recompute()


class RfRingStaleBinormalGuessThenUndoAndTurn(RfRingStaleBinormalGuessThenTurnUndo):
    """As RfRingStaleBinormalGuessThenTurnUndo, the undo and the turn in one recompute (two
    steps: the redraw, then the undo with the turn)."""

    steps = ("redrawProfile", "undoAndTurn")

    def undoAndTurn(self, doc):
        doc.undo()
        self.turn()
        doc.recompute()


class RfSquareStaleBinormalGuessThenUndoAndTurn90(RfRingStaleBinormalGuessThenUndoAndTurn):
    """As RfRingStaleBinormalGuessThenUndoAndTurn, the 20 x 20 square ring turned 90."""

    verts0 = ((0, 0), (0, 20), (20, 20), (20, 0))
    pivot = (10, 0, 10)

    def turn(self):
        self.degrees = 90
        self.place()


class RfRingGuessThenUndoAndTurn(RfRingStaleBinormalGuessThenUndoAndTurn):
    """Control: no Binormal (the closure is one piece; the undo changed the profile, so the turn
    is one piece with another edit: decision 236 (1) breaks, a turned probe never snaps back)."""

    binormal = None
