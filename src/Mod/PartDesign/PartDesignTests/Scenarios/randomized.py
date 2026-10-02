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

"""Randomized edit sequences (`notes/scenarios.md` section 6): a seed gives a model and a sequence
of edits, and every reference in the model is judged after every edit.

The model is a `Spec`: a block (a pad of a polygon sketch, W x D x H) and features in body order:
bosses, pockets and holes whose sketches are attached to a top face, fillets and chamfers on
edges, empty sketches attached to faces (markers) and sketches with an external edge. Every
reference names its element by a label, e.g. ("block", "edge", "top", "front") or
(3, "face", "top") for feature 3's top face, and the label's predicate comes from the spec's
numbers. So after an edit the expected elements are worked out from the edited spec, never from
names or indexes.

A label on a target object is gone when its feature was deleted, is after the target, or a
dress-up at or before the target used it up, and a block corner edge is gone when the corner is cut.
An element split by a notch in the profile gives pieces: every piece for a dress-up, one piece (any
coplanar one is equivalent) for an attachment, broken with the pieces as candidates for external
geometry (`notes/naming-design.md` section 8).

Features keep apart: each region on the top keeps MARGIN from the block's sides and GAP from the
others, notches and corner cuts stay within the margin, and dress-ups are small. So the labels stay
unique, and a model is valid when it builds. **Validity is decided by a fresh build**: the edited
spec built from scratch in a new document, every reference picked by its predicate, must recompute
and judge correct. An edit whose fresh build fails is geometry, not naming: it is discarded, and
the next one is drawn from the seed. The plan (the model and its edits) is made once per seed in V2
and replayed in every configuration.

A step whose edit leaves references with nothing to point to is judged twice: first the references
expected broken (their consumers must fail, principle 1), then, after the repair (the broken
consumers deleted, last first, as a user would), every reference left. Such an edit is only drawn
when the repair leaves a valid model. An expected break whose consumer stays valid because a
feature it builds on is invalid counts as reported: the consumer recomputes on that feature's stale
shape, and the model shows the error one feature up.

A sequence stops after a step with any unexpected verdict, partial included: from there the live
model may differ from the spec (a fillet on one piece of an edge instead of both), and later
verdicts would judge the spec's model, not the live one. A live edit that can't find the element it
needs is scored wrong for the same reason (the model has diverged).

Environment (TestNamingScenarios): FREECAD_SCENARIO_SEEDS ("1-4", "7,9"),
FREECAD_SCENARIO_STEPS (8), FREECAD_SCENARIO_REPLAY=<seed>:<steps> (one seed).
"""

import copy
import random
import sys

import FreeCAD as App

from .harness import (
    BROKEN,
    MULTI_PARAM,
    PARAM_GROUP,
    Attached,
    Broken,
    Chamfered,
    ExternalCoincides,
    Filleted,
    Ref,
    Result,
    Scenario,
    ScenarioError,
    X,
    Y,
    Z,
    edge,
    emit,
    expectedNames,
    face,
    pieces,
)
from . import models as m

V = App.Vector

QUANTUM = 0.25  # every generated length is a multiple of it
MARGIN = 3.0  # between the block's sides and the regions of the features on its top
GAP = 2.0  # between two regions, and between two notches
PIECE_AT = 2.5  # a split side face's piece for an attachment: the one at 2.5 along the side
LIMITS = {"W": (16, 44), "D": (12, 32), "H": (5, 16)}

SIDES = ("front", "right", "back", "left")
CORNERS = ("fl", "fr", "br", "bl")
SOLID = ("boss", "pocket", "hole", "fillet", "chamfer")
DRESS = ("fillet", "chamfer")
OBJECT = {
    "boss": "Boss",
    "pocket": "Pocket",
    "hole": "Hole",
    "fillet": "Fillet",
    "chamfer": "Chamfer",
    "marker": "Marker",
    "external": "External",
}


def q(x):
    return round(x / QUANTUM) * QUANTUM


def uniform(rng, a, b):
    return q(rng.uniform(a, b))


def weighted(rng, weights):
    total = sum(w for _, w in weights)
    x = rng.uniform(0, total)
    for value, w in weights:
        x -= w
        if x <= 0:
            return value
    return weights[-1][0]


# ---------------------------------------------------------------------------------------------
# Sides and corners of the block (the profile runs counter-clockwise: front, right, back, left)
# ---------------------------------------------------------------------------------------------

# a coordinate is (base, offset): base 0, "W" or "D"
SIDE = {
    # normal, point on the side's plane (from W, D), its edges' direction, along (x or y),
    # the vertex at t along the side and depth d inward
    "front": (-Y, lambda W, D: V(0, 0, 0), X, "x", lambda t, d: ((0, t), (0, d))),
    "right": (X, lambda W, D: V(W, 0, 0), Y, "y", lambda t, d: (("W", -d), (0, t))),
    "back": (Y, lambda W, D: V(0, D, 0), X, "x", lambda t, d: ((0, t), ("D", -d))),
    "left": (-X, lambda W, D: V(0, 0, 0), Y, "y", lambda t, d: ((0, d), (0, t))),
}
TRAVERSAL = {"front": 1, "right": 1, "back": -1, "left": -1}  # t increases or decreases
CORNER = {
    "fl": ((0, 0), (0, 0)),
    "fr": (("W", 0), (0, 0)),
    "br": (("W", 0), ("D", 0)),
    "bl": ((0, 0), ("D", 0)),
}


def cutPoints(corner, s):
    """The two vertices replacing a corner cut by s: on the incoming side, then the outgoing."""
    return {
        "fl": (((0, 0), (0, s)), ((0, s), (0, 0))),
        "fr": ((("W", -s), (0, 0)), (("W", 0), (0, s))),
        "br": ((("W", 0), ("D", -s)), (("W", -s), ("D", 0))),
        "bl": (((0, s), ("D", 0)), ((0, 0), ("D", -s))),
    }[corner]


# ---------------------------------------------------------------------------------------------
# The spec
# ---------------------------------------------------------------------------------------------


class Feature:
    """One feature of the spec. boss, pocket: `region` (x0, y0, x1, y1) and `size` (height,
    depth); hole: `center` and `size` (radius); fillet, chamfer: `label` and `size`; marker,
    external: `label`. `target` names the object the reference links to."""

    def __init__(self, fid, kind, target, **values):
        self.fid, self.kind, self.target = fid, kind, target
        self.region = self.center = self.label = None
        self.size = None
        for key, value in values.items():
            setattr(self, key, value)

    @property
    def name(self):
        return f"F{self.fid}{OBJECT[self.kind]}"

    @property
    def sketchName(self):
        return f"F{self.fid}Sketch"

    @property
    def solid(self):
        return self.kind in SOLID

    def area(self):
        """The region the feature takes on the block's top (bosses, pockets, holes)."""
        if self.kind == "hole":
            (x, y), r = self.center, self.size
            return (x - r, y - r, x + r, y + r)
        return self.region

    def describe(self):
        if self.kind in ("boss", "pocket"):
            return f"{self.kind} {self.name} {fmt(self.region)} size {self.size:g} on {self.target}"
        if self.kind == "hole":
            return f"hole {self.name} at {fmt(self.center)} r {self.size:g} on {self.target}"
        size = f" size {self.size:g}" if self.size is not None else ""
        return f"{self.kind} {self.name} on {self.target} {labelText(self.label)}{size}"


def fmt(values):
    return "(" + ", ".join(f"{v:g}" for v in values) + ")"


def labelText(label):
    owner = "block" if label[0] == "block" else f"F{label[0]}"
    return ".".join([owner] + list(label[1:]))


class Spec:
    def __init__(self, W, D, H):
        self.W, self.D, self.H = W, D, H
        self.vertices = dict(CORNER)
        self.lines = [["fl", "fr"], ["fr", "br"], ["br", "bl"], ["bl", "fl"]]
        self.notches = {side: [] for side in SIDES}  # (t0, t1, depth), t0 < t1
        self.cuts = {}  # corner: size
        self.features = []
        self.nextId = 1
        self.nextKey = 1

    def copy(self):
        return copy.deepcopy(self)

    # numbers

    def value(self, coordinate):
        base, offset = coordinate
        return {0: 0, "W": self.W, "D": self.D}[base] + offset

    def point(self, key):
        x, y = self.vertices[key]
        return (self.value(x), self.value(y))

    def length(self, side):
        return self.W if SIDE[side][3] == "x" else self.D

    def profileLines(self):
        """{geometry index: ((x0, y0), (x1, y1))}"""
        return {i: (self.point(a), self.point(b)) for i, (a, b) in enumerate(self.lines)}

    def newVertex(self, coordinates):
        key = f"v{self.nextKey}"
        self.nextKey += 1
        self.vertices[key] = coordinates
        return key

    # features

    def byId(self, fid):
        for f in self.features:
            if f.fid == fid:
                return f
        return None

    def byName(self, name):
        for f in self.features:
            if f.name == name:
                return f
        return None

    def chain(self):
        """The solid features' object names in body order, the block's pad first."""
        return ["Pad"] + [f.name for f in self.features if f.solid]

    def position(self, name):
        return self.chain().index(name)

    def tip(self):
        return self.chain()[-1]

    def previousSolid(self, name):
        chain = self.chain()
        return chain[chain.index(name) - 1]

    def nextSolid(self, name):
        chain = self.chain()
        i = chain.index(name)
        return self.byName(chain[i + 1]) if i + 1 < len(chain) else None

    # labels

    def state(self, label, target):
        """'one', 'pieces' or 'gone': the label's element on the target object's shape."""
        owner = label[0]
        if owner != "block":
            feature = self.byId(owner)
            if feature is None or self.position(feature.name) > self.position(target):
                return "gone"
        for f in self.features:
            if f.kind in DRESS and f.label == label:
                if self.position(f.name) <= self.position(target):
                    return "gone"
        if owner == "block":
            if label[1] == "vert" and label[2] in self.cuts:
                return "gone"
            side = label[2] if label[1] == "face" else label[3] if label[1] == "edge" else None
            if side in SIDES and self.notches[side]:
                return "pieces"
        return "one"

    def predicate(self, label, onePiece=False):
        owner, kind = label[0], label[1]
        W, D, H = self.W, self.D, self.H
        if owner == "block":
            if kind == "face":
                side = label[2]
                if side == "top":
                    return face("plane", normal=Z, through=(0, 0, H))
                if side == "bottom":
                    return face("plane", normal=-Z, through=(0, 0, 0))
                normal, at, _, along, _ = SIDE[side]
                p = at(W, D)
                if not onePiece:
                    return face("plane", normal=normal, through=p)
                inside = p + (X if along == "x" else Y) * PIECE_AT + Z * (H / 2)
                return face("plane", normal=normal, through=p, contains=inside)
            if kind == "edge":
                level, side = label[2], label[3]
                z = H if level == "top" else 0
                _, at, direction, _, _ = SIDE[side]
                p = at(W, D) + Z * z
                return segment(p, p + direction * self.length(side))
            if kind == "vert":
                x, y = (self.value(c) for c in CORNER[label[2]])
                return segment(V(x, y, 0), V(x, y, H))
        f = self.byId(owner)
        if f.kind == "hole":
            (x, y), r = f.center, f.size
            z = H if label[2] == "rim" else 0
            return edge("circle", center=(x, y, z), radius=r)
        x0, y0, x1, y1 = f.region
        top = H + f.size if f.kind == "boss" else H - f.size if f.kind == "pocket" else None
        centre = V((x0 + x1) / 2, (y0 + y1) / 2, top)
        if kind == "face":  # a boss's top, a pocket's floor
            return face("plane", normal=Z, through=centre, contains=centre)
        corners = {"fl": (x0, y0), "fr": (x1, y0), "br": (x1, y1), "bl": (x0, y1)}
        if kind == "vert":
            x, y = corners[label[2]]
            return segment(V(x, y, min(H, top)), V(x, y, max(H, top)))
        level, side = label[2], label[3]
        z = H if level == "rim" else top
        a, b = {"front": ("fl", "fr"), "right": ("fr", "br"), "back": ("bl", "br"),
                "left": ("fl", "bl")}[side]
        return segment(V(*corners[a], z), V(*corners[b], z))

    def labels(self, target, kinds):
        """Labels whose element is on the target's shape, as one element or pieces: 'edge'
        (lines and circles), 'face', or 'bottom' (edges at z = 0, as one element)."""
        found = []
        if "face" in kinds:
            found += [("block", "face", s) for s in ("top", "bottom") + SIDES]
        if "edge" in kinds:
            found += [("block", "edge", level, s) for level in ("top", "bottom") for s in SIDES]
            found += [("block", "vert", c) for c in CORNERS]
        if "bottom" in kinds:
            found += [("block", "edge", "bottom", s) for s in SIDES]
        for f in self.features:
            if f.kind == "boss":
                if "face" in kinds:
                    found.append((f.fid, "face", "top"))
                if "edge" in kinds:
                    found += [(f.fid, "vert", c) for c in CORNERS]
                    found += [(f.fid, "edge", "top", s) for s in SIDES]
            elif f.kind == "pocket":
                if "face" in kinds:
                    found.append((f.fid, "face", "floor"))
                if "edge" in kinds:
                    found += [(f.fid, "vert", c) for c in CORNERS]
                    found += [(f.fid, "edge", level, s)
                              for level in ("rim", "floor") for s in SIDES]
            elif f.kind == "hole":
                if "edge" in kinds:
                    found.append((f.fid, "edge", "rim"))
                if "bottom" in kinds:
                    found.append((f.fid, "edge", "bottom"))
        states = {label: self.state(label, target) for label in found}
        if kinds == ("bottom",):
            return [label for label, s in states.items() if s == "one"]
        return [label for label, s in states.items() if s != "gone"]

    # references

    def refs(self):
        """{reference name: (owner object, property, label, target, consumer, feature)}"""
        refs = {}
        for f in self.features:
            if f.kind in ("boss", "pocket", "hole"):
                refs[f"F{f.fid}.support"] = (f.sketchName, "AttachmentSupport",
                                             ("block", "face", "top"), f.target, "attach", f)
            elif f.kind in DRESS:
                refs[f"F{f.fid}.base"] = (f.name, "Base", f.label, f.target, "dress", f)
            elif f.kind == "marker":
                refs[f"F{f.fid}.support"] = (f.name, "AttachmentSupport", f.label, f.target,
                                             "attach", f)
            elif f.kind == "external":
                refs[f"F{f.fid}.external"] = (f.name, "ExternalGeometry", f.label, f.target,
                                              "external", f)
        return refs

    def expectation(self, label, target, consumer):
        state = self.state(label, target)
        if state == "gone":
            return self.gone(label, target)
        if state == "one":
            return self.predicate(label)
        if consumer == "dress":
            return pieces(self.predicate(label))
        if consumer == "attach":
            return self.predicate(label, onePiece=True)
        return Broken(pieces(self.predicate(label)))

    def gone(self, label, target):
        """BROKEN, with the candidates a solver would offer: a cut corner's edge has the two
        new corner edges (FilletCornerCut)."""
        if label[:2] == ("block", "vert") and label[2] in self.cuts:
            ends = cutPoints(label[2], self.cuts[label[2]])
            points = [V(self.value(x), self.value(y), 0) for x, y in ends]
            return Broken(*(segment(p, p + Z * self.H) for p in points))
        return BROKEN

    def outcome(self, consumer, feature):
        if consumer == "dress":
            return Filleted(feature.size) if feature.kind == "fillet" else Chamfered(feature.size)
        return Attached() if consumer == "attach" else ExternalCoincides()

    def broken(self):
        """The features whose reference is expected broken."""
        broken = []
        for name, (_, _, label, target, consumer, f) in self.refs().items():
            if isinstance(self.expectation(label, target, consumer), Broken):
                broken.append(f)
        return broken

    # validity (before the fresh build)

    def valid(self):
        for key, (low, high) in LIMITS.items():
            if not low <= getattr(self, key) <= high:
                return False
        areas = []
        for f in self.features:
            if f.kind == "pocket" and f.size > self.H - 2:
                return False
            if f.kind in ("boss", "pocket", "hole"):
                x0, y0, x1, y1 = f.area()
                if x0 < MARGIN or y0 < MARGIN or x1 > self.W - MARGIN or y1 > self.D - MARGIN:
                    return False
                areas.append((x0, y0, x1, y1))
        for i, a in enumerate(areas):
            for b in areas[i + 1 :]:
                if not (a[2] + GAP <= b[0] or b[2] + GAP <= a[0]
                        or a[3] + GAP <= b[1] or b[3] + GAP <= a[1]):
                    return False
        for side, notches in self.notches.items():
            length = self.length(side)
            spans = sorted(notches)
            for t0, t1, _ in spans:
                if t0 < MARGIN or t1 > length - MARGIN:
                    return False
            for (a0, a1, _), (b0, b1, _) in zip(spans, spans[1:]):
                if a1 + GAP > b0:
                    return False
        return True

    def referrers(self, name):
        return [f for f in self.features if f.target == name]

    def deletable(self, feature):
        """A feature can be deleted when nothing links to it but the next solid feature's
        dress-up, which the body relinks to the feature before it."""
        if not feature.solid:
            return True
        after = self.nextSolid(feature.name)
        return all(f is after and f.kind in DRESS for f in self.referrers(feature.name))

    def delete(self, feature):
        """Removes the feature, as Body.removeObject and Document.removeObject do."""
        if feature.solid:
            after = self.nextSolid(feature.name)
            if after is not None and after.kind in DRESS and after.target == feature.name:
                after.target = self.previousSolid(feature.name)
        self.features.remove(feature)

    def repaired(self):
        """The spec with the broken consumers deleted, last first, or None when one of them
        can't be deleted cleanly."""
        spec = self.copy()
        for _ in range(4):
            broken = spec.broken()
            if not broken:
                return spec
            for f in sorted(broken, key=lambda f: spec.features.index(f), reverse=True):
                f = spec.byId(f.fid)
                if not spec.deletable(f):
                    return None
                spec.delete(f)
        return None


def segment(p, q):
    """An edge on the line through p and q whose centre lies strictly between them (also every
    piece of it)."""
    direction = q - p
    length = direction.Length
    unit = V(direction).normalize()

    def within(e):
        t = (e.CenterOfMass - p).dot(unit)
        return 1e-6 < t < length - 1e-6

    return edge("line", direction=unit, through=p, where=within)


# ---------------------------------------------------------------------------------------------
# Building a spec, and editing a live document
# ---------------------------------------------------------------------------------------------


def buildProfile(doc, body, spec):
    lines = [((x0, y0), (x1, y1)) for (x0, y0), (x1, y1) in spec.profileLines().values()]
    geometry = [m.polyline([a, b])[0] for a, b in lines]
    return m.sketch(doc, "Profile", geometry, body)


def build(doc, spec):
    """Builds the spec from scratch: every reference is picked by its predicate."""
    body = m.body(doc)
    profile = buildProfile(doc, body, spec)
    m.pad(body, profile, spec.H)
    doc.recompute()
    for f in spec.features:
        create(doc, body, spec, f, fresh=True)
    return body


def attachedSketch(doc, body, name, target, sub):
    sketch = body.newObject("Sketcher::SketchObject", name)
    sketch.AttachmentSupport = [(target, sub)]
    sketch.MapMode = "FlatFace"
    doc.recompute()
    rotation = sketch.Placement.Rotation
    if not rotation.isSame(App.Rotation(), 1e-9):
        raise ScenarioError(f"{name} on {target.Name}.{sub} is turned: {rotation}")
    return sketch


def create(doc, body, spec, f, fresh=False):
    """Adds the feature at the body's tip. In a fresh build a dress-up links to the tip (the
    object it builds on), as a user building the model now would; elsewhere to its target."""
    target = doc.getObject(f.target)
    if f.kind in ("boss", "pocket", "hole"):
        top = spec.predicate(("block", "face", "top")).one(target.Shape)[0]
        sketch = attachedSketch(doc, body, f.sketchName, target, top)
        if f.kind == "hole":
            sketch.addGeometry(m.circle(*f.center, f.size), False)
        else:
            sketch.addGeometry(m.rectangle(*f.region), False)
        feature = body.newObject("PartDesign::Pad" if f.kind == "boss" else "PartDesign::Pocket",
                                 f.name)
        feature.Profile = sketch
        if f.kind == "hole":
            feature.Type = "ThroughAll"
        else:
            feature.Length = f.size
    elif f.kind in DRESS:
        if fresh:
            target = doc.getObject(spec.previousSolid(f.name))
        expectation = spec.expectation(f.label, target.Name, "dress")
        subs = expectedNames(expectation, target.Shape)
        feature = body.newObject(
            "PartDesign::Fillet" if f.kind == "fillet" else "PartDesign::Chamfer", f.name
        )
        feature.Base = (target, subs)
        if f.kind == "fillet":
            feature.Radius = f.size
        else:
            feature.Size = f.size
    elif f.kind == "marker":
        expectation = spec.expectation(f.label, f.target, "attach")
        attachedSketch(doc, body, f.name, target, expectation.one(target.Shape)[0])
    else:
        sub = spec.predicate(f.label).one(target.Shape)[0]
        sketch = m.sketch(doc, f.name, [], body, z=0)
        sketch.addExternal(target.Name, sub)
    doc.recompute()


def deleteObject(doc, body, name):
    obj = doc.getObject(name)
    if obj is None:
        return
    body.removeObject(obj)
    doc.removeObject(name)


def deleteFeature(doc, body, f):
    deleteObject(doc, body, f.name)
    if f.kind in ("boss", "pocket", "hole"):
        deleteObject(doc, body, f.sketchName)


# ---------------------------------------------------------------------------------------------
# Edits: each changes a copy of the spec (`change`) and the live document the same way (`apply`)
# ---------------------------------------------------------------------------------------------


class Edit:
    def __init__(self, text):
        self.text = text

    def change(self, spec):
        raise NotImplementedError

    def apply(self, doc, body, before, after):
        raise NotImplementedError


class BlockSize(Edit):
    def __init__(self, key, value):
        super().__init__(f"block {key} -> {value:g}")
        self.key, self.value = key, value

    def change(self, spec):
        setattr(spec, self.key, self.value)

    def apply(self, doc, body, before, after):
        if self.key == "H":
            doc.Pad.Length = after.H
        else:
            m.setLines(doc.Profile, after.profileLines())


class FeatureSize(Edit):
    def __init__(self, fid, value, text):
        super().__init__(text)
        self.fid, self.value = fid, value

    def change(self, spec):
        spec.byId(self.fid).size = self.value

    def apply(self, doc, body, before, after):
        f = after.byId(self.fid)
        obj = doc.getObject(f.name)
        if f.kind in ("boss", "pocket"):
            obj.Length = f.size
        elif f.kind == "fillet":
            obj.Radius = f.size
        elif f.kind == "chamfer":
            obj.Size = f.size
        else:
            moveHole(doc.getObject(f.sketchName), f)


class FeatureMove(Edit):
    def __init__(self, fid, dx, dy, text):
        super().__init__(text)
        self.fid, self.dx, self.dy = fid, dx, dy

    def change(self, spec):
        f = spec.byId(self.fid)
        if f.kind == "hole":
            f.center = (f.center[0] + self.dx, f.center[1] + self.dy)
        else:
            x0, y0, x1, y1 = f.region
            f.region = (x0 + self.dx, y0 + self.dy, x1 + self.dx, y1 + self.dy)

    def apply(self, doc, body, before, after):
        f = after.byId(self.fid)
        sketch = doc.getObject(f.sketchName)
        if f.kind == "hole":
            moveHole(sketch, f)
        else:
            m.moveRectangle(sketch, *f.region)


def moveHole(sketch, f):
    """The hole's circle to its centre and radius; it keeps its geometry ID."""
    geometry = sketch.Geometry
    geometry[0].Center = V(*f.center, 0)
    geometry[0].Radius = f.size
    sketch.Geometry = geometry


class Notch(Edit):
    """A notch into one side of the profile: the side's line is cut short at the notch, and
    four lines are added (the notch's three and the rest of the side), as in SketchNotch."""

    def __init__(self, side, t0, t1, depth):
        super().__init__(f"notch {side} {t0:g}..{t1:g} depth {depth:g}")
        self.side, self.t0, self.t1, self.depth = side, t0, t1, depth
        self.line = None

    def change(self, spec):
        side, vertex = self.side, SIDE[self.side][4]
        axis = 0 if SIDE[side][3] == "x" else 1
        for i, (a, b) in enumerate(spec.lines):
            pa, pb = spec.point(a), spec.point(b)
            if not (onSide(spec, side, pa) and onSide(spec, side, pb)):
                continue
            low, high = sorted((pa[axis], pb[axis]))
            if low < self.t0 and self.t1 < high:
                break
        else:
            raise ScenarioError(f"no line on the {side} side spans {self.t0}..{self.t1}")
        first, second = (self.t0, self.t1) if TRAVERSAL[side] > 0 else (self.t1, self.t0)
        keys = [
            spec.newVertex(vertex(first, 0)),
            spec.newVertex(vertex(first, self.depth)),
            spec.newVertex(vertex(second, self.depth)),
            spec.newVertex(vertex(second, 0)),
        ]
        end = spec.lines[i][1]
        spec.lines[i] = [a, keys[0]]
        spec.lines += [[keys[0], keys[1]], [keys[1], keys[2]], [keys[2], keys[3]], [keys[3], end]]
        spec.notches[side].append((self.t0, self.t1, self.depth))
        self.line = i

    def apply(self, doc, body, before, after):
        lines = after.profileLines()
        m.setLines(doc.Profile, {self.line: lines[self.line]})
        added = [lines[i] for i in range(len(before.lines), len(after.lines))]
        doc.Profile.addGeometry(m.polyline([added[0][0]] + [b for _, b in added]), False)


def onSide(spec, side, point):
    normal, at, _, along, _ = SIDE[side]
    p = at(spec.W, spec.D)
    axis = 1 if along == "x" else 0  # the coordinate fixed on the side
    return abs(point[axis] - (p.y if axis == 1 else p.x)) < 1e-9


class CornerCut(Edit):
    """A corner of the profile is cut off: the two lines at it end short, and a line joins them."""

    def __init__(self, corner, size):
        super().__init__(f"cut corner {corner} by {size:g}")
        self.corner, self.size = corner, size
        self.lines = None

    def change(self, spec):
        incoming = next(i for i, (a, b) in enumerate(spec.lines) if b == self.corner)
        outgoing = next(i for i, (a, b) in enumerate(spec.lines) if a == self.corner)
        p, q_ = cutPoints(self.corner, self.size)
        kp, kq = spec.newVertex(p), spec.newVertex(q_)
        spec.lines[incoming][1] = kp
        spec.lines[outgoing][0] = kq
        spec.lines.append([kp, kq])
        spec.cuts[self.corner] = self.size
        self.lines = (incoming, outgoing)

    def apply(self, doc, body, before, after):
        lines = after.profileLines()
        m.setLines(doc.Profile, {i: lines[i] for i in self.lines})
        doc.Profile.addGeometry(m.polyline(list(lines[len(after.lines) - 1])), False)


class AddFeature(Edit):
    """A feature added at the tip, or inserted after the block's pad (`insert`), as a user does
    it: the tip set to the pad, the sketch and the feature added, the tip set back."""

    def __init__(self, feature, insert=False):
        verb = "insert" if insert else "add"
        super().__init__(f"{verb} {feature.describe()}")
        self.feature, self.insert = feature, insert

    def change(self, spec):
        f = copy.deepcopy(self.feature)
        spec.features.insert(0, f) if self.insert else spec.features.append(f)
        spec.nextId = max(spec.nextId, f.fid + 1)

    def apply(self, doc, body, before, after):
        f = after.byId(self.feature.fid)
        if self.insert:
            body.Tip = doc.Pad
            create(doc, body, after, f)
            # The spec's last solid feature, not the tip before the insert: when that was the pad
            # (the later features deleted), the inserted feature is the last one (ops#89)
            body.Tip = doc.getObject(after.tip())
        else:
            create(doc, body, after, f)


class DeleteFeature(Edit):
    def __init__(self, fid, text):
        super().__init__(text)
        self.fid = fid

    def change(self, spec):
        spec.delete(spec.byId(self.fid))

    def apply(self, doc, body, before, after):
        deleteFeature(doc, body, before.byId(self.fid))


# ---------------------------------------------------------------------------------------------
# Drawing features and edits from the seed
# ---------------------------------------------------------------------------------------------


def drawRegion(rng, spec, size):
    w, d = uniform(rng, *size), uniform(rng, *size)
    if spec.W - 2 * MARGIN < w or spec.D - 2 * MARGIN < d:
        return None
    x0 = uniform(rng, MARGIN, spec.W - MARGIN - w)
    y0 = uniform(rng, MARGIN, spec.D - MARGIN - d)
    return (x0, y0, x0 + w, y0 + d)


def drawFeature(rng, spec, insert=False):
    """A new feature for the tip (or, with insert, for after the pad), or None."""
    kinds = [("boss", 2), ("pocket", 2), ("hole", 1.5)]
    if not insert:
        kinds += [("fillet", 2), ("chamfer", 2), ("marker", 1.5), ("external", 1)]
    kind = weighted(rng, kinds)
    tip = "Pad" if insert else spec.tip()
    fid = spec.nextId
    if kind in ("boss", "pocket", "hole"):
        target = tip if insert or rng.random() < 0.7 else "Pad"
        if kind == "hole":
            r = uniform(rng, 1, 2.5)
            region = drawRegion(rng, spec, (2 * r, 2 * r))
            if region is None:
                return None
            return Feature(fid, kind, target, center=((region[0] + region[2]) / 2,
                                                      (region[1] + region[3]) / 2), size=r)
        region = drawRegion(rng, spec, (3, 8))
        if region is None:
            return None
        size = uniform(rng, 2, 6) if kind == "boss" else uniform(rng, 1, spec.H - 2)
        return Feature(fid, kind, target, region=region, size=size)
    if kind in DRESS:
        labels = spec.labels(tip, ("edge",))
        if not labels:
            return None
        label = rng.choice(labels)
        sizes = (0.5, 0.75, 1.0) if label[0] == "block" else (0.25, 0.5)
        return Feature(fid, kind, tip, label=label, size=rng.choice(sizes))
    labels = spec.labels(tip, ("face",) if kind == "marker" else ("bottom",))
    if not labels:
        return None
    return Feature(fid, kind, tip, label=rng.choice(labels))


def drawEdit(rng, spec):
    kind = weighted(rng, [("block", 3), ("feature", 3), ("notch", 1.5), ("cut", 1),
                          ("insert", 1.5), ("delete", 1.5), ("add", 1.5)])
    if kind == "block":
        key = rng.choice(("W", "D", "H"))
        value = uniform(rng, *LIMITS[key])
        return BlockSize(key, value) if value != getattr(spec, key) else None
    if kind == "feature":
        sized = [f for f in spec.features if f.kind != "marker" and f.kind != "external"]
        if not sized:
            return None
        f = rng.choice(sized)
        if f.kind in ("boss", "pocket", "hole") and rng.random() < 0.5:
            dx, dy = uniform(rng, -4, 4), uniform(rng, -4, 4)
            if dx == dy == 0:
                return None
            return FeatureMove(f.fid, dx, dy, f"move {f.name} by ({dx:g}, {dy:g})")
        if f.kind == "boss":
            value = uniform(rng, 2, 6)
        elif f.kind == "pocket":
            value = uniform(rng, 1, spec.H - 2)
        elif f.kind == "hole":
            value = uniform(rng, 1, 2.5)
        else:
            value = rng.choice((0.5, 0.75, 1.0) if f.label[0] == "block" else (0.25, 0.5))
        if value == f.size:
            return None
        return FeatureSize(f.fid, value, f"{f.name} size {f.size:g} -> {value:g}")
    if kind == "notch":
        side = rng.choice(SIDES)
        width, depth = uniform(rng, 2, 4), uniform(rng, 1, 1.5)
        t0 = uniform(rng, MARGIN, spec.length(side) - MARGIN - width)
        return Notch(side, t0, t0 + width, depth)
    if kind == "cut":
        free = [c for c in CORNERS if c not in spec.cuts]
        return CornerCut(rng.choice(free), uniform(rng, 1, 2)) if free else None
    if kind == "delete":
        candidates = [f for f in spec.features if f.solid and spec.deletable(f)]
        if not candidates:
            return None
        f = rng.choice(candidates)
        return DeleteFeature(f.fid, f"delete {f.name}")
    feature = drawFeature(rng, spec, insert=(kind == "insert"))
    return AddFeature(feature, insert=(kind == "insert")) if feature else None


def freshBuild(spec, mode):
    """Builds the spec in a new document: it must recompute, and every reference judge correct.
    Returns None when it does, else why not (the reason is counted in the plan)."""
    checker = Checker(mode)
    try:
        checker.doc = checker.newDocument("Fresh")
        build(checker.doc, spec)
        checker.doc.recompute()
        invalid = [o.Name for o in checker.doc.Objects if not o.isValid()]
        if invalid:
            return "invalid " + ", ".join(invalid)
        for name in spec.refs():
            verdict = checker.judge(makeRef(spec, name), "fresh").verdict
            if verdict != "correct":
                return f"{name} {verdict}"
        return None
    except Exception as e:  # a predicate that isn't unique, an oracle OCC can't build, ...
        return f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}"
    finally:
        checker.cleanup()


def makeRef(spec, name):
    owner, prop, label, target, consumer, f = spec.refs()[name]
    outcome = None if isinstance(spec.expectation(label, target, consumer), Broken) else (
        spec.outcome(consumer, f)
    )
    return Ref(name, owner, prop, lambda: spec.expectation(label, target, consumer), outcome)


class Step:
    def __init__(self, edit, before, after, repaired):
        self.edit, self.before, self.after, self.repaired = edit, before, after, repaired


class Plan:
    def __init__(self, seed, initial, steps, discarded):
        self.seed, self.initial, self.steps = seed, initial, steps
        self.discarded = discarded  # [why] per fresh build that failed


def makePlan(seed, steps, mode="V2"):
    """The model and its edits for a seed: every accepted state passed a fresh build."""
    rng = random.Random(seed)
    discarded = []
    for _ in range(20):
        spec = Spec(uniform(rng, 20, 40), uniform(rng, 14, 30), uniform(rng, 6, 14))
        for _ in range(rng.randint(3, 8)):
            for _ in range(20):
                f = drawFeature(rng, spec)
                if f is None:
                    continue
                trial = spec.copy()
                trial.features.append(f)
                trial.nextId = f.fid + 1
                if trial.valid():
                    spec = trial
                    break
        why = freshBuild(spec, mode)
        if why is None:
            break
        discarded.append("model: " + why)
    else:
        raise ScenarioError(f"seed {seed}: no model builds")
    initial, plan = spec, []
    for _ in range(steps):
        for _ in range(40):
            edit = drawEdit(rng, spec)
            if edit is None:
                continue
            after = spec.copy()
            try:
                edit.change(after)
            except ScenarioError:
                continue
            if not after.valid():
                continue
            repaired = after.repaired()
            if repaired is None:
                continue
            why = freshBuild(repaired, mode)
            if why is not None:
                discarded.append(f"{edit.text}: {why}")
                continue
            plan.append(Step(edit, spec, after, repaired if after.broken() else None))
            spec = repaired
            break
        else:
            break  # nothing more to draw: the sequence ends early
    return Plan(seed, initial, plan, discarded)


class Checker(Scenario):
    """The harness's judge on a document of our own (fresh builds)."""

    abstract = True
    area = "randomized"


# ---------------------------------------------------------------------------------------------
# Replaying a plan in one configuration
# ---------------------------------------------------------------------------------------------


class RandomSequence(Scenario):
    """One seed's plan in one configuration. `run` returns every step's Results."""

    abstract = True
    area = "randomized"

    def __init__(self, config, plan):
        super().__init__(config)
        self.plan = plan

    def diverged(self, name, step, why):
        """The plan's fresh build found the element, so the live model has diverged from the
        spec: something upstream resolved to the wrong element."""
        result = Result(type(self).__name__, name, self.config, step)
        result.verdict = "wrong"
        result.record.update(area=self.area, config=self.config, platform=sys.platform,
                             step=step, consumer=name, target=None, subs=[], expect="diverged",
                             stored="diverged", outcome=None,
                             detail=f"the live model isn't the spec's: {why}", verdict="wrong")
        return result

    def reportedUpstream(self, spec, name, result):
        """An expected break whose consumer stays valid because a solid feature it builds on is
        invalid: the consumer then recomputes on that feature's stale shape, where the element
        still is. The model reports the break, one feature up, so it counts as broken."""
        if not str(result.record.get("expect")).startswith("BROKEN") or result.verdict != "wrong":
            return
        owner = self.doc.getObject(spec.refs()[name][0])
        if owner is None or not owner.isValid():
            return
        feature = owner.BaseFeature if hasattr(owner, "BaseFeature") else None
        if feature is None and spec.refs()[name][3] in spec.chain():
            feature = self.doc.getObject(spec.refs()[name][3])
        while feature is not None:
            if not feature.isValid():
                result.verdict = "broken"
                result.record.update(
                    verdict="broken",
                    outcome="broken",
                    detail=f"{feature.Name}, which {owner.Name} builds on, is invalid",
                )
                return
            feature = getattr(feature, "BaseFeature", None)

    def judgeAll(self, spec, step, text, names=None):
        results = []
        for name in names if names is not None else list(spec.refs()):
            try:
                result = self.judge(makeRef(spec, name), step)
                self.reportedUpstream(spec, name, result)
            except ScenarioError as e:
                result = self.diverged(name, step, e)
            result.scenario = f"Random{self.plan.seed:04d}"
            result.ref = f"{name}@{step}"
            result.record.update(scenario=result.scenario, ref=result.ref, seed=self.plan.seed,
                                 edit=text)
            emit(result)
            results.append(result)
        return results

    def run(self):
        group = App.ParamGet(PARAM_GROUP)
        hadParam = MULTI_PARAM in group.GetBools()
        oldParam = group.GetBool(MULTI_PARAM, False)
        group.SetBool(MULTI_PARAM, self.multi)
        self.doc = self.newDocument()
        results = []
        try:
            body = build(self.doc, self.plan.initial)
            self.doc.recompute()
            first = self.judgeAll(self.plan.initial, "0", "build")
            bad = [r.message() for r in first if r.verdict != "correct"]
            if bad:
                raise ScenarioError("references aren't correct after the build:\n" + "\n".join(bad))
            results += first
            for k, step in enumerate(self.plan.steps, 1):
                try:
                    step.edit.apply(self.doc, body, step.before, step.after)
                except ScenarioError as e:  # an element the edit needs isn't there
                    result = self.diverged(f"edit{k}", str(k), e)
                    result.scenario, result.ref = f"Random{self.plan.seed:04d}", f"edit@{k}"
                    result.record.update(scenario=result.scenario, ref=result.ref,
                                         seed=self.plan.seed, edit=step.edit.text)
                    emit(result)
                    results.append(result)
                    break
                self.doc.recompute()
                if body.Tip is None or body.Tip.Name != step.after.tip():
                    # a feature past the tip would be built on by the next feature added there
                    # (ops#89): a defect of the edit's replay, not a verdict
                    raise ScenarioError(
                        f"step {k} ({step.edit.text}): the body's tip is "
                        f"{body.Tip.Name if body.Tip else None}, the spec's {step.after.tip()}"
                    )
                if step.repaired is None:
                    judged = self.judgeAll(step.after, str(k), step.edit.text)
                else:
                    broken = step.after.broken()
                    names = [n for n, r in step.after.refs().items() if r[5] in broken]
                    judged = self.judgeAll(step.after, str(k), step.edit.text, names)
                    for f in sorted(broken, key=lambda f: step.after.features.index(f),
                                    reverse=True):
                        deleteFeature(self.doc, body, f)
                    self.doc.recompute()
                    text = step.edit.text + "; repair: delete " + ", ".join(
                        f.name for f in broken)
                    judged += self.judgeAll(step.repaired, f"{k}r", text)
                results += judged
                if any(not r.passing for r in judged):
                    break  # the live model may differ from the spec from here on
            return results
        finally:
            self.cleanup()
            if hadParam:
                group.SetBool(MULTI_PARAM, oldParam)
            else:
                group.RemBool(MULTI_PARAM)


def replayText(plan):
    lines = [f"seed {plan.seed}: {len(plan.steps)} steps, {len(plan.discarded)} draws discarded",
             "  build: " + "; ".join(f.describe() for f in plan.initial.features)]
    for k, step in enumerate(plan.steps, 1):
        repair = ""
        if step.repaired is not None:
            repair = " (repair: delete " + ", ".join(f.name for f in step.after.broken()) + ")"
        lines.append(f"  {k}: {step.edit.text}{repair}")
    return "\n".join(lines)
