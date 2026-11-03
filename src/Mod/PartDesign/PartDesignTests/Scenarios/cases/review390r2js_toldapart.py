# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2js, L1: the contest of a pick the twin clause broke where only the PR sees a twin
(decision 214's toldApart bridge: a twin told apart by a connected vertex and the lone member its
twin left are the same name up to that key). takenOnIntegration reads state.twinSurvivor, twinPick
and orderBreaks' groups with the PR's wider isTwinName, so it can say "integration broke" where
integration kept tier 1's lone survivor.

Model of review390r2gs_toldapart.py: a block 0..40 x 0..20 x 0..10 (scaled), a through pocket from a
circle A in an unattached sketch at z = 10, centre (cx, -3), r 5: a notch in the front face (y 0)
with two vertical lines at cx -+ 4 (twins) and their vertexes. Two references in one owner (a sketch
attached at the first, the second its external geometry: the forced matching runs over both), or
each in a datum. The edits move A so that one line goes, redraw it (new geometry id), and draw a new
circle N at A's old place."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    OwnOrBroken,
    Scenario,
    Z,
    edge,
    vertex,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector
L, W, H = 40, 20, 10
R, CY = 5, -3
HALF = 4

# reference -> (side, kind)
REFDEF = {
    "line_l": (-1, "line"),
    "line_r": (1, "line"),
    "top_l": (-1, "top"),
    "top_r": (1, "top"),
    "bot_l": (-1, "bot"),
    "bot_r": (1, "bot"),
}


class Base(Scenario):
    abstract = True
    area = "split"
    CLASSES = ("A",)
    AXES = ("M1", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2js"
    TIER = "F"
    SIZE = 40
    REFS = ("line_l", "line_r")
    OWNERS = "pair"
    cx0 = 20
    OPS = ()  # ("move", x) / ("redraw", x) / ("new", x)

    def predicate(self, kind, x):
        s = self.scale
        if kind == "line":
            return edge("line", direction=Z, through=V(x * s, 0, 0))
        return vertex(V(x * s, 0, (H if kind == "top" else 0) * s))

    def expected(self, name):
        side, kind = REFDEF[name]

        def expect():
            if not self.edited:
                return self.predicate(kind, self.cx0 + side * HALF)
            x = self.cx + side * HALF
            if not 0 < x < L:
                return BROKEN
            if self.redrawn and self.cx == self.cx0:
                return OwnOrBroken(self.predicate(kind, x))
            if self.redrawn:
                return OwnOrBroken(self.predicate(kind, x))
            return self.predicate(kind, x)

        return expect

    def build(self, doc):
        s = self.scale
        self.edited = False
        self.redrawn = False
        self.cx = self.cx0
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L * s, W * s), body)
        m.pad(body, profile, H * s)
        self.notchSketch = m.sketch(
            doc, "NotchSketch", [m.circle(self.cx0 * s, CY * s, R * s)], body, z=H * s
        )
        pocket = m.pocketThroughAll(body, self.notchSketch, "Notch")
        doc.recompute()
        subs = {}
        for name in self.REFS:
            side, kind = REFDEF[name]
            subs[name] = self.names(pocket, self.predicate(kind, self.cx0 + side * HALF))[0]
        if self.OWNERS == "pair":
            first, second = self.REFS
            probe = body.newObject("Sketcher::SketchObject", "Probe")
            probe.AttachmentSupport = [(pocket, subs[first])]
            probe.MapMode = "NormalToEdge" if REFDEF[first][1] == "line" else "Translate"
            probe.addExternal(pocket.Name, subs[second])
            self.ref(first, probe, "AttachmentSupport", self.expected(first), Attached())
            self.ref(second, probe, "ExternalGeometry", self.expected(second))
        else:
            for name in self.REFS:
                datum = body.newObject("PartDesign::Point", "On" + name)
                datum.AttachmentSupport = [(pocket, subs[name])]
                datum.MapMode = "CenterOfMass"
                self.ref(name, datum, "AttachmentSupport", self.expected(name), Attached())
        body.Tip = pocket
        doc.recompute()

    def edit(self, doc):
        s = self.scale
        for op, x in self.OPS:
            if op == "move":
                g = self.notchSketch.Geometry
                g[0].Center = V(x * s, CY * s, 0)
                self.notchSketch.Geometry = g
                self.cx = x
            elif op == "redraw":
                self.notchSketch.delGeometry(0)
                self.notchSketch.addGeometry(m.circle(x * s, CY * s, R * s), False)
                self.cx = x
                self.redrawn = True
            elif op == "new":
                self.notchSketch.addGeometry(m.circle(x * s, CY * s, R * s), False)
        self.edited = True


OPS = {
    "LeftGoes": (("move", 3),),
    "RightGoes": (("move", 37),),
    "LeftGoesNewAtOld": (("move", 3), ("new", 20)),
    "RightGoesNewAtOld": (("move", 37), ("new", 20)),
    "LeftGoesNewAtLeft": (("move", 3), ("new", 20 - HALF + 2)),
    "RedrawLeftGoes": (("redraw", 3),),
    "RedrawRightGoes": (("redraw", 37),),
    "Redraw": (("redraw", 20),),
    "RedrawNew": (("redraw", 3), ("new", 20)),
    "MoveFar": (("move", 28),),
}

PAIRS = {
    "LL": ("line_l", "line_r"),
    "RL": ("line_r", "line_l"),
    "TL": ("top_l", "line_r"),
    "LT": ("line_r", "top_l"),
    "TR": ("top_r", "line_l"),
    "RT": ("line_l", "top_r"),
    "TT": ("top_l", "top_r"),
    "BT": ("bot_l", "bot_r"),
}

for _edit, _ops in OPS.items():
    for _label, _pair in PAIRS.items():
        _c = type(
            "R2jsTold%s%s" % (_edit, _label),
            (Base,),
            {"__doc__": "%s, pair %s" % (_edit, _label), "REFS": _pair, "OPS": _ops},
        )
        globals()[_c.__name__] = _c
    _c = type(
        "R2jsTold%sDatums" % _edit,
        (Base,),
        {
            "__doc__": _edit + ", six datums",
            "REFS": tuple(REFDEF),
            "OWNERS": "datum",
            "OPS": _ops,
        },
    )
    globals()[_c.__name__] = _c


class R2jsToldApartSurvivorBreakKeepsItsContest(Base):
    """The named case: one owner, the left line (attached) and the right line (external) of the
    notch; A moves so that the left line goes while a new circle N takes A's old place (new id,
    same sketch): the left line's old place holds N's left line (another source), the right line
    survives alone at 7 (told apart by its connected vertex before)."""

    REFS = ("line_l", "line_r")
    OPS = (("move", 3), ("new", 20))


del _c, _edit, _ops, _label, _pair
