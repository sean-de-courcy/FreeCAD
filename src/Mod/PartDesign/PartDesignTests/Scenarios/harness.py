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

"""The scenario harness: build a model, record references, edit, recompute, judge.

A scenario's references are judged against elements described geometrically by its author, from
the scenario's own parameters (`self.width`, ...), never from names or indexes taken from a run.
Each reference gets one verdict per configuration, from two checks:

1. The stored reference: its sub-names are read back from the property. A `?` prefix, or a
   sub-name the shape can't resolve, is broken. Otherwise the resolved elements are compared with
   the expected ones: the same set is correct, some of the expected pieces only is partial
   (a split), anything else is wrong.
2. The consumer's result: an `Outcome` compares the consumer (fillet, attachment, ...) with an
   oracle built from the expected elements. A consumer that fails is broken, one whose result
   differs is wrong. A broken reference counts as broken only when it is reported, i.e. its
   consumer fails: one that stays valid without its element is wrong (principle 1).

The verdict combines them (`combine`): wrong, partial, broken, equivalent (a different element
that gives the consumer the same result) or correct. Each verdict is printed as a `SCORE` line
(JSON) for the ops repo's scorecard, and appended to FREECAD_SCENARIO_SCORE_FILE if it is set.

Configurations: V1, V2 and V2multi (V2 with the user parameter NamingMultiMatch on: a dress-up's
Base and a Profile keep every piece of a split element).
"""

import json
import math
import os
import re
import sys

import FreeCAD as App
import Part

from . import models

V = App.Vector
X, Y, Z = V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)

PARAM_GROUP = "User parameter:BaseApp/Preferences/Mod/PartDesign"
MULTI_PARAM = "NamingMultiMatch"
CONFIGS = {"V1": ("V1", False), "V2": ("V2", False), "V2multi": ("V2", True)}
VERDICTS = ("correct", "equivalent", "broken", "partial", "wrong")


class ScenarioError(Exception):
    """The scenario is wrong (a predicate matches nothing, or too much; the model fails before
    the edit). The test errors, and the scenario gets fixed. Never a verdict."""


# ---------------------------------------------------------------------------------------------
# Element names in reports (also used by TestNamingDump)
# ---------------------------------------------------------------------------------------------


class MaskError(Exception):
    pass


class Masker:
    """Replaces the tags (object IDs) in element names with `{ObjectName}`.

    V2: each section's tag is replaced, recursing into Linked and Connected Names; the name is
    decoded and encoded again, and must come back byte for byte with the tags left as they are.
    V1: the `:H<hex>` tags are replaced, after expanding the hasher's `#<hex>` string IDs. The
    length after a tag (`:H<hex>:<hex length>`) counts the characters of the name before it, tags
    included, so it depends on the tags' values: it is written `:L`.
    A tag that is no object's ID is written `#<tag>` (e.g. a slice's number), a negative object ID
    `{-ObjectName}`; 0 stays 0.
    """

    V1_TAG = re.compile(r":H(-?)([0-9a-f]*)(:[0-9a-f]+)?")
    V1_SID = re.compile(r"#([0-9a-f]+)")

    def __init__(self, doc):
        self.names = {str(obj.ID): obj.Name for obj in doc.Objects}

    def tag(self, tag):
        if tag in ("", "0"):
            return tag
        sign = "-" if tag.startswith("-") else ""  # e.g. a Pocket's tool, tagged -ID
        name = self.names.get(tag.lstrip("-"))
        return "{" + sign + name + "}" if name else "#" + tag

    def v2(self, name, mask=True):
        sections = App.getDecodedMappedName(name)
        if not sections:
            return name
        encoded = []
        for section in sections:
            section = dict(section)
            for field in ("linkedNames", "connectedElements"):
                names = [self.v2(n, mask) for n in section[field]]
                # sorted by bytes with the tags; with the tags masked, sorted again
                section[field] = sorted(names) if mask else names
            if mask:
                section["iterationTag"] = self.tag(section["iterationTag"])
            encoded.append(App.makeEncodedSection(**section))
        return "|".join(encoded)  # Data::NAME_SECTION_DELIMINATOR

    @classmethod
    def unsortedList(cls, name):
        """A Linked or Connected Names list in the name that isn't sorted by bytes and unique."""
        for section in App.getDecodedMappedName(name) or []:
            for field in ("linkedNames", "connectedElements"):
                names = list(section[field])
                if names != sorted(set(names)):
                    return names
                for linked in names:
                    found = cls.unsortedList(linked)
                    if found:
                        return found
        return None

    def maskV2(self, name):
        if self.v2(name, mask=False) != name:
            raise MaskError(f"decoding and encoding changes the name {name!r}")
        unsorted = self.unsortedList(name)
        if unsorted:
            raise MaskError(f"a list in {name!r} isn't sorted by bytes (ops#19): {unsorted!r}")
        return self.v2(name)

    def maskV1(self, name, table):
        if table:
            for _ in range(20):
                expanded = self.V1_SID.sub(
                    lambda m: "<" + str(table.get(int(m.group(1), 16), m.group(0))) + ">", name
                )
                if expanded == name:
                    break
                name = expanded
        def tag(match):
            value = match.group(2)
            if value:
                value = self.tag(str(int(value, 16) * (-1 if match.group(1) else 1)))
            return ":H" + value + (":L" if match.group(3) else "")

        return self.V1_TAG.sub(tag, name)

    def mask(self, name, mode, shape=None):
        """The masked name for a report; the raw name when it can't be masked."""
        try:
            if mode == "V2":
                return self.maskV2(name)
            table = {}
            if shape is not None and shape.Hasher is not None:
                table = dict(shape.Hasher.Table)
            return self.maskV1(name, table)
        except Exception:
            return name


# ---------------------------------------------------------------------------------------------
# Predicates: elements described geometrically
# ---------------------------------------------------------------------------------------------


def _vector(v):
    return v if isinstance(v, App.Vector) else V(*v)


def _parallel(a, b, sameSense):
    a, b = V(a).normalize(), V(b).normalize()
    dot = a.dot(b)
    return dot > 1 - 1e-9 if sameSense else abs(dot) > 1 - 1e-9


def faceNormal(face):
    u0, u1, v0, v1 = face.ParameterRange
    return face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)


def tolerance(shape):
    return max(1e-7, 1e-6 * shape.BoundBox.DiagonalLength)


class Predicate:
    """A test on one element type. `select` gives the 1-based index names of the matches."""

    def __init__(self, kind, description, tests):
        self.kind, self.description, self.tests = kind, description, tests

    def matches(self, element, tol):
        return all(test(element, tol) for test in self.tests)

    def select(self, shape):
        tol = tolerance(shape)
        elements = {"Face": shape.Faces, "Edge": shape.Edges, "Vertex": shape.Vertexes}[self.kind]
        return [f"{self.kind}{i}" for i, e in enumerate(elements, 1) if self.matches(e, tol)]

    def one(self, shape):
        names = self.select(shape)
        if len(names) != 1:
            raise ScenarioError(f"{self} matches {names or 'nothing'}, not one element")
        return names

    def __repr__(self):
        return f"{self.kind}({self.description})"


def face(surface=None, normal=None, through=None, contains=None, where=None):
    """A face: its surface type ('plane', 'cylinder'), its normal (oriented, planar faces), a
    point of its plane, a point on the face itself, or any test."""
    tests, words = [], []
    if surface:
        tests.append(lambda f, tol: type(f.Surface).__name__.lower() == surface)
        words.append(surface)
    if normal is not None:
        n = _vector(normal)
        tests.append(lambda f, tol: _parallel(faceNormal(f), n, True))
        words.append(f"normal={tuple(n)}")
    if through is not None:
        p = _vector(through)

        def onPlane(f, tol):
            if not isinstance(f.Surface, Part.Plane):
                return False
            return abs((p - f.Surface.Position).dot(f.Surface.Axis)) < tol

        tests.append(onPlane)
        words.append(f"through={tuple(p)}")
    if contains is not None:
        p = _vector(contains)
        tests.append(lambda f, tol: f.isInside(p, tol, True))
        words.append(f"contains={tuple(p)}")
    if where is not None:
        tests.append(lambda f, tol: where(f))
        words.append("where")
    return Predicate("Face", ", ".join(words), tests)


def _curve(e):
    """The edge's curve, or None where Part can't give one ("undefined curve type")."""
    try:
        return e.Curve
    except Exception:
        return None


def edge(curve=None, direction=None, through=None, contains=None, where=None, center=None,
         radius=None):
    """An edge: its curve type ('line', 'circle'), its direction (lines, either sense), a point
    of its infinite line, a point on the edge itself, a circle's centre and radius, or any
    test."""
    tests, words = [], []
    if curve:
        tests.append(lambda e, tol: type(_curve(e)).__name__.lower() == curve)
        words.append(curve)
    if center is not None:
        c = _vector(center)
        tests.append(
            lambda e, tol: isinstance(_curve(e), Part.Circle) and (e.Curve.Center - c).Length < tol
        )
        words.append(f"center={tuple(c)}")
    if radius is not None:
        tests.append(
            lambda e, tol: isinstance(_curve(e), Part.Circle) and abs(e.Curve.Radius - radius) < tol
        )
        words.append(f"radius={radius}")
    if direction is not None:
        d = _vector(direction)
        tests.append(
            lambda e, tol: isinstance(_curve(e), Part.Line)
            and _parallel(e.Curve.Direction, d, False)
        )
        words.append(f"direction={tuple(d)}")
    if through is not None:
        p = _vector(through)

        def onLine(e, tol):
            if not isinstance(_curve(e), Part.Line):
                return False
            return (p - e.Curve.Location).cross(V(e.Curve.Direction).normalize()).Length < tol

        tests.append(onLine)
        words.append(f"through={tuple(p)}")
    if contains is not None:
        p = _vector(contains)
        tests.append(lambda e, tol: Part.Vertex(p).distToShape(e)[0] < tol)
        words.append(f"contains={tuple(p)}")
    if where is not None:
        tests.append(lambda e, tol: where(e))
        words.append("where")
    return Predicate("Edge", ", ".join(words), tests)


def vertex(at):
    p = _vector(at)
    return Predicate("Vertex", f"at={tuple(p)}", [lambda v, tol: (v.Point - p).Length < tol])


class Pieces:
    """Every piece of a split element: the expected set is all the predicate's matches."""

    def __init__(self, predicate):
        self.predicate = predicate

    def select(self, shape):
        names = self.predicate.select(shape)
        if not names:
            raise ScenarioError(f"{self} matches nothing")
        return names

    def __repr__(self):
        return f"pieces({self.predicate})"


def pieces(predicate):
    return Pieces(predicate)


class Broken:
    """The element is gone, or the case is deliberately ambiguous: the reference should break.
    `candidates` (predicates or `pieces`) are the elements a solver would offer, e.g. the pieces
    of a split edge: a reference kept on some of them is partial, on anything else wrong."""

    def __init__(self, *candidates):
        self.candidates = candidates

    def select(self, shape):
        return [name for c in self.candidates for name in c.select(shape)]

    def __repr__(self):
        return f"BROKEN{list(self.candidates)}" if self.candidates else "BROKEN"


BROKEN = Broken()


INTERNAL = "Internal"  # SketchObject::internalPrefix()


class Internal:
    """One element of a sketch's InternalShape (its regions with MakeInternals), referenced as
    `Internal<Face|Edge|Vertex><n>`."""

    def __init__(self, predicate):
        self.predicate = predicate

    def select(self, shape):
        return [INTERNAL + name for name in self.predicate.select(shape)]

    def one(self, shape):
        return [INTERNAL + name for name in self.predicate.one(shape)]

    def __repr__(self):
        return f"internal({self.predicate})"


def internal(predicate):
    return Internal(predicate)


def shapeFor(obj, expectation):
    """The shape whose elements the expectation names: a sketch's InternalShape for
    `internal(...)` (in the sketch's own coordinates), otherwise the object's Shape."""
    return obj.InternalShape if isinstance(expectation, Internal) else obj.Shape


def elementOf(obj, sub):
    """(shape, index name) of a reference's sub-name, `Internal...` on the InternalShape."""
    if sub.startswith(INTERNAL) and hasattr(obj, "InternalShape"):
        return obj.InternalShape, sub[len(INTERNAL) :]
    return obj.Shape, sub


def subElement(obj, sub):
    shape, name = elementOf(obj, sub)
    return shape.getElement(name)


def expectedNames(expectation, shape):
    if isinstance(expectation, Pieces):
        return expectation.select(shape)
    return expectation.one(shape)


# ---------------------------------------------------------------------------------------------
# Outcomes: the consumer's result, against an oracle built from the expected elements
# ---------------------------------------------------------------------------------------------


def _mass(shape):
    """Volume, area and centre of mass of a shape's solids (PartDesign results are compounds)."""
    solids = shape.Solids
    volume = sum(s.Volume for s in solids)
    centre = V()
    for s in solids:
        centre += s.CenterOfMass * (s.Volume / volume)
    return volume, sum(s.Area for s in solids), centre


def sameSolid(a, b):
    """Two shapes whose solids have the same volume, area, centre of mass and bounding box."""
    tol = tolerance(b)
    if a.isNull() or b.isNull() or not a.Solids or not b.Solids:
        return False, "no solid"
    (va, aa, ca), (vb, ab, cb) = _mass(a), _mass(b)
    for label, x, y in (("volume", va, vb), ("area", aa, ab)):
        if abs(x - y) > 1e-7 * max(1.0, abs(y)):
            return False, f"{label} {x:.6f} != {y:.6f}"
    if (ca - cb).Length > tol:
        return False, f"centre of mass {ca} != {cb}"
    ba, bb = a.BoundBox, b.BoundBox
    corners = [
        (V(ba.XMin, ba.YMin, ba.ZMin), V(bb.XMin, bb.YMin, bb.ZMin)),
        (V(ba.XMax, ba.YMax, ba.ZMax), V(bb.XMax, bb.YMax, bb.ZMax)),
    ]
    if any((p - q).Length > tol for p, q in corners):
        return False, f"bounding box {ba} != {bb}"
    return True, ""


class Outcome:
    """Checks a consumer's result. `check` returns ("correct" | "wrong" | "broken", detail)."""

    def check(self, scenario, consumer, target, expectation):
        if not consumer.isValid():
            return "broken", f"{consumer.Name} is invalid: {consumer.State}"
        try:
            ok, detail = self.compare(scenario, consumer, target, expectation)
        except ScenarioError:
            raise
        except Exception as e:  # the oracle can't be built from the expected elements
            raise ScenarioError(f"{type(self).__name__} oracle failed: {type(e).__name__}: {e}")
        return ("correct" if ok else "wrong"), detail


class DressUpOutcome(Outcome):
    """A fillet or chamfer: the result equals the Part operation on the dress-up's base shape
    with the expected edges."""

    def compare(self, scenario, consumer, target, expectation):
        base = consumer.BaseFeature.Shape
        edges = [base.getElement(n) for n in expectedNames(expectation, base)]
        return sameSolid(consumer.Shape, self.oracle(base, edges))


class Filleted(DressUpOutcome):
    def __init__(self, radius):
        self.radius = radius

    def oracle(self, base, edges):
        return base.makeFillet(self.radius, edges)


class Chamfered(DressUpOutcome):
    def __init__(self, size):
        self.size = size

    def oracle(self, base, edges):
        return base.makeChamfer(self.size, edges)


class Drafted(Outcome):
    """A draft on a neutral plane: each expected face is replaced by a face tilted by the angle
    through its line on the neutral plane, and every other side face stays where it was."""

    def __init__(self, angle, neutral):
        self.angle, self.neutral = angle, neutral

    def compare(self, scenario, consumer, target, expectation):
        base, result = consumer.BaseFeature.Shape, consumer.Shape
        tol = tolerance(base)
        neutral = base.getElement(self.neutral().one(base)[0])
        p0, nz = neutral.Surface.Position, neutral.Surface.Axis
        expected = expectedNames(expectation, base)
        planes = [(f, faceNormal(f)) for f in result.Faces if isinstance(f.Surface, Part.Plane)]
        for name in expected:
            f = base.getElement(name)
            n = faceNormal(f)
            line = [v.Point for v in f.Vertexes if abs((v.Point - p0).dot(nz)) < tol]
            if len(line) < 2:
                raise ScenarioError(f"{name} doesn't meet the neutral plane")
            if not any(
                abs(math.degrees(n.getAngle(ng)) - self.angle) < 1e-6
                and all(abs((p - g.Surface.Position).dot(g.Surface.Axis)) < tol for p in line)
                for g, ng in planes
            ):
                return False, f"no face drafted by {self.angle} deg from {name}"
            # the pieces of a split face share their line on the neutral plane: check that
            # none of the face is left where it was
            if any(
                _parallel(n, ng, True)
                and abs((g.Surface.Position - f.Surface.Position).dot(n)) < tol
                and g.common(f).Area > tol
                for g, ng in planes
            ):
                return False, f"{name} is still in the result, not drafted"
        for i, f in enumerate(base.Faces, 1):
            if f"Face{i}" in expected or not isinstance(f.Surface, Part.Plane):
                continue
            n = faceNormal(f)
            if abs(n.dot(nz)) > 1e-9:
                continue  # not a side face
            if not any(
                _parallel(n, ng, True)
                and abs((f.Surface.Position - g.Surface.Position).dot(n)) < tol
                for g, ng in planes
            ):
                return False, f"side face Face{i} of the base was moved (drafted?)"
        return True, ""


class Attached(Outcome):
    """An attached sketch or datum: its placement equals the attacher's placement for the
    expected elements."""

    def compare(self, scenario, consumer, target, expectation):
        engine = Part.AttachEngine(consumer.AttacherType)
        engine.References = [(target, expectedNames(expectation, target.Shape))]
        engine.Mode = consumer.MapMode
        engine.AttachmentOffset = consumer.AttachmentOffset
        engine.Reverse = consumer.MapReversed
        oracle = engine.calculateAttachedPlacement(consumer.Placement)
        placement = consumer.Placement
        tol = tolerance(target.Shape)
        if (placement.Base - oracle.Base).Length > tol or not placement.Rotation.isSame(
            oracle.Rotation, 1e-9
        ):
            return False, f"placement {placement} != {oracle}"
        return True, ""


class ReachesFace(Outcome):
    """A Pad or Pocket up to a face: the added or removed volume ends on the expected face's
    plane, all on one side of it, and the profile isn't on that plane (the far end)."""

    SUBTRACTIVE = ("PartDesign::Pocket", "PartDesign::Groove", "PartDesign::Hole")

    def compare(self, scenario, consumer, target, expectation):
        names = expectedNames(expectation, target.Shape)
        plane = target.Shape.getElement(names[0])
        if not isinstance(plane.Surface, Part.Plane):
            raise ScenarioError("ReachesFace needs a planar face")
        p, n = plane.Surface.Position, plane.Surface.Axis
        base, result = consumer.BaseFeature.Shape, consumer.Shape
        tool = base.cut(result) if consumer.TypeId in self.SUBTRACTIVE else result.cut(base)
        tol = tolerance(base)
        if tool.isNull() or tool.Volume < tol:
            return False, "the feature adds or removes nothing"
        profile = consumer.Profile[0].Shape
        if any(abs((v.Point - p).dot(n)) < tol for v in profile.Vertexes):
            return False, "the face's plane is the profile's (the near end, not the far one)"
        side = [(v.Point - p).dot(n) for v in tool.Vertexes]
        if min(side) < -tol and max(side) > tol:
            return False, f"the feature crosses the face's plane ({min(side):.4f}..{max(side):.4f})"
        if not any(
            isinstance(f.Surface, Part.Plane)
            and _parallel(f.Surface.Axis, n, False)
            and abs((f.Surface.Position - p).dot(n)) < tol
            for f in tool.Faces
        ):
            return False, "the feature doesn't end on the face's plane"
        return True, ""


class Extruded(Outcome):
    """A Pad whose profile is given as faces: the result is its base fused with each expected
    face extruded by the length along the direction."""

    def __init__(self, length, direction=Z):
        self.length, self.direction = length, _vector(direction)

    def compare(self, scenario, consumer, target, expectation):
        names = expectedNames(expectation, shapeFor(target, expectation))
        faces = [subElement(target, n) for n in names]
        solids = [f.extrude(self.direction * self.length) for f in faces]
        oracle = solids[0].fuse(solids[1:]) if len(solids) > 1 else solids[0]
        if consumer.BaseFeature is not None:
            oracle = consumer.BaseFeature.Shape.fuse(oracle)
        return sameSolid(consumer.Shape, oracle)


class ExternalCoincides(Outcome):
    """A sketch's external geometry: each external edge (a line, circle or arc) lies on an
    expected edge, end to end, and each expected edge has one (the first two ExternalGeo entries
    are the sketch's axes)."""

    def compare(self, scenario, consumer, target, expectation):
        edges = [target.Shape.getElement(n) for n in expectedNames(expectation, target.Shape)]
        placement = consumer.getGlobalPlacement()
        external = []
        for g in list(consumer.ExternalGeo)[2:]:
            shape = g.toShape()
            shape.Placement = placement.multiply(shape.Placement)
            external.append(shape)
        if len(external) != len(edges):
            return False, f"{len(external)} external edges for {len(edges)} edges"
        tol = tolerance(target.Shape)
        for edge in edges:
            if not any(_sameEdge(e, edge, tol) for e in external):
                return False, f"no external edge on {edge.Curve} of length {edge.Length:.4f}"
        return True, ""


def _sameEdge(a, b, tol):
    """Two edges of the same length, each point of one on the other."""
    if abs(a.Length - b.Length) > tol:
        return False
    return all(Part.Vertex(p).distToShape(b)[0] < tol for p in a.discretize(9)) and all(
        Part.Vertex(p).distToShape(a)[0] < tol for p in b.discretize(9)
    )


def _sameFace(a, b, tol):
    if abs(a.Area - b.Area) > tol * max(1.0, a.Area):
        return False
    if (a.CenterOfMass - b.CenterOfMass).Length > tol:
        return False
    if isinstance(a.Surface, Part.Plane) != isinstance(b.Surface, Part.Plane):
        return False
    return not isinstance(a.Surface, Part.Plane) or _parallel(faceNormal(a), faceNormal(b), True)


class Bound(Outcome):
    """A SubShapeBinder of faces: its shape has exactly the expected faces."""

    def compare(self, scenario, consumer, target, expectation):
        expected = [target.Shape.getElement(n) for n in expectedNames(expectation, target.Shape)]
        faces = consumer.Shape.Faces
        tol = tolerance(target.Shape)
        if len(faces) != len(expected):
            return False, f"{len(faces)} faces bound for {len(expected)}"
        for f in expected:
            if not any(_sameFace(g, f, tol) for g in faces):
                return False, f"no bound face at {f.CenterOfMass} with area {f.Area:.4f}"
        return True, ""


# ---------------------------------------------------------------------------------------------
# References and verdicts
# ---------------------------------------------------------------------------------------------


class Ref:
    """One reference: the property `prop` of object `owner`, the expected element after each
    step (`expect`, a callable returning a predicate, `pieces(...)` or `BROKEN`), and the
    consumer's outcome check."""

    def __init__(self, name, owner, prop, expect, outcome=None):
        self.name, self.owner, self.prop = name, owner, prop
        self.expect, self.outcome = expect, outcome


def storedLinks(obj, prop):
    """(target object, [sub-names]) of a PropertyLinkSub or a one-object PropertyLinkSubList."""
    value = getattr(obj, prop)
    if not value:
        return None, []
    if isinstance(value, tuple) and not isinstance(value[0], tuple):
        target, subs = value
        return target, [subs] if isinstance(subs, str) else list(subs)
    targets = {o for o, _ in value}
    if len(targets) != 1:
        raise ScenarioError(f"{obj.Name}.{prop} links {len(targets)} objects")
    subs = []
    for _, s in value:
        subs.extend([s] if isinstance(s, str) else s)
    return value[0][0], subs


def combine(stored, outcome):
    """The verdict from the stored reference's check and the consumer's (None: no outcome
    check)."""
    if stored == "partial":
        return "partial"
    if outcome == "wrong":
        return "wrong"
    if stored == "wrong":
        return "equivalent" if outcome == "correct" else "wrong"
    if stored == "broken" or outcome == "broken":
        return "broken"
    return "correct"


class Result:
    def __init__(self, scenario, ref, config, step):
        self.scenario, self.ref, self.config, self.step = scenario, ref, config, step
        self.verdict = None
        self.record = {}

    @property
    def passing(self):
        if str(self.record.get("expect")).startswith("BROKEN"):
            return self.verdict == "broken"
        return self.verdict in ("correct", "equivalent")

    def message(self):
        return "SCORE " + json.dumps(self.record, sort_keys=True)


class Scenario:
    """Subclasses define `build(doc)` (which calls `ref(...)`) and `edit(doc)`, and list their
    reference names in REFS. MULTI marks scenarios whose consumers the multi-match flags touch
    (dress-ups, Profile): CI runs them in V2multi too."""

    abstract = True
    area = None
    REFS = ()
    MULTI = False

    def __init__(self, config):
        self.config = config
        self.mode, self.multi = CONFIGS[config]
        self.refs = {}
        self.documents = []

    # For the scenario's author

    def ref(self, name, owner, prop, expect, outcome=None):
        if name not in self.REFS:
            raise ScenarioError(f"reference {name!r} isn't listed in REFS")
        self.refs[name] = Ref(name, owner.Name, prop, expect, outcome)

    @staticmethod
    def names(obj, predicate):
        """The index name of the one element of obj's shape the predicate matches."""
        return predicate.one(shapeFor(obj, predicate))

    def newDocument(self, suffix=""):
        """A document in the scenario's history algorithm, closed after the run. The first is
        the scenario's own (self.doc); others hold the targets of cross-document links."""
        doc = models.newDocument(f"Scenario{type(self).__name__}{self.config}{suffix}")
        if hasattr(doc, "HistoryAlgorithm"):
            doc.HistoryAlgorithm = self.mode
        self.documents.append(doc.Name)
        return doc

    def build(self, doc):
        raise NotImplementedError

    def edit(self, doc):
        raise NotImplementedError

    def cleanup(self):
        """Closes the scenario's documents that are still open."""
        for name in self.documents:
            if name in App.listDocuments():
                App.closeDocument(name)

    # Running

    def run(self):
        """Builds, judges (every reference must be correct before the edit), edits and judges.
        Returns {ref name: Result} for the step after the edit."""
        group = App.ParamGet(PARAM_GROUP)
        hadParam = MULTI_PARAM in group.GetBools()
        oldParam = group.GetBool(MULTI_PARAM, False)
        group.SetBool(MULTI_PARAM, self.multi)
        self.doc = self.newDocument()
        try:
            self.build(self.doc)
            if set(self.refs) != set(self.REFS):
                raise ScenarioError(
                    f"build() recorded {sorted(self.refs)}, REFS {sorted(self.REFS)}"
                )
            self.doc.recompute()
            before = {name: self.judge(ref, "build") for name, ref in self.refs.items()}
            bad = [r.message() for r in before.values() if r.verdict != "correct"]
            if bad:
                raise ScenarioError("references aren't correct before the edit:\n" + "\n".join(bad))
            self.edit(self.doc)  # may close and reopen the documents (self.doc)
            self.doc.recompute()
            after = {name: self.judge(ref, "edit") for name, ref in self.refs.items()}
            for name, result in after.items():
                result.record["names_before"] = before[name].record["names"]
                result.record["subs_before"] = before[name].record["subs"]
                emit(result)
            return after
        finally:
            self.cleanup()
            if hadParam:
                group.SetBool(MULTI_PARAM, oldParam)
            else:
                group.RemBool(MULTI_PARAM)

    def judge(self, ref, step):
        doc = self.doc
        owner = doc.getObject(ref.owner)
        target, subs = storedLinks(owner, ref.prop)
        expectation = ref.expect()
        result = Result(type(self).__name__, ref.name, self.config, step)
        record = result.record
        masker = Masker(target.Document if target else doc)  # the names' tags are its IDs
        mode = "V2" if self.mode == "V2" and hasattr(doc, "HistoryAlgorithm") else "V1"
        record.update(
            scenario=type(self).__name__,
            area=self.area,
            ref=ref.name,
            config=self.config,
            platform=sys.platform,
            step=step,
            consumer=f"{owner.Name}.{ref.prop}",
            target=target.Name if target else None,
            subs=subs,
            expect=repr(expectation),
        )

        # 1. The stored reference
        resolved = []
        if target is None or not subs or any(s.startswith("?") for s in subs):
            stored = "broken"
        else:
            try:
                resolved = [(s, subElement(target, s)) for s in subs]
                stored = None
            except Exception:
                stored = "broken"
        record["names"] = [self._name(masker, mode, target, s) for s, _ in resolved]
        expected = []
        if isinstance(expectation, Broken):
            if stored is None:
                candidates = expectation.select(target.Shape)
                record["candidate_subs"] = candidates
                stored = "partial" if candidates and set(subs) <= set(candidates) else "wrong"
        elif target is not None:
            expected = expectedNames(expectation, shapeFor(target, expectation))
            record["expected_subs"] = expected
            record["expected_names"] = [self._name(masker, mode, target, s) for s in expected]
            if stored is None:
                got = set(subs)
                if got == set(expected):
                    stored = "correct"
                elif isinstance(expectation, Pieces) and got < set(expected):
                    stored = "partial"
                else:
                    stored = "wrong"

        # 2. The consumer's result
        outcome, detail = None, ""
        if isinstance(expectation, Broken) or target is None:
            if stored == "broken" and owner.isValid():
                # nothing reports the break: the consumer carries on without its element
                outcome, detail = "wrong", f"{owner.Name} stays valid with the broken reference"
            else:
                outcome = None if owner.isValid() else "broken"
        elif ref.outcome is not None:
            outcome, detail = ref.outcome.check(self, owner, target, expectation)
        elif not owner.isValid():
            outcome = "broken"
        result.verdict = combine(stored, outcome)
        record.update(stored=stored, outcome=outcome, detail=detail, verdict=result.verdict)
        return result

    @staticmethod
    def _name(masker, mode, target, sub):
        shape, sub = elementOf(target, sub)
        try:
            name = shape.getElementMappedName(sub)
        except Exception:
            return None
        if isinstance(name, (list, tuple)):
            name = name[0] if name else None
        return masker.mask(name, mode, shape) if name else None


def emit(result):
    """Prints the SCORE line with one write to the process's stdout: through the console, the
    buffered line gets cut by the test runner's unbuffered output in CI logs."""
    line = result.message()
    try:
        os.write(1, (line + "\n").encode("utf-8"))
    except OSError:
        App.Console.PrintMessage(line + "\n")
    path = os.environ.get("FREECAD_SCENARIO_SCORE_FILE")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


# ---------------------------------------------------------------------------------------------
# Naming assertions for unit tests (ops#23): what a shape's names must satisfy, in place of
# counting them. A failed check raises AssertionError (a test failure); a check the test set up
# wrong raises ScenarioError.
# ---------------------------------------------------------------------------------------------

COUNTER_OPCODE = re.compile(r"_[0-9]+")


def elementNames(shape):
    """{index name: [mapped names]} for every face, edge and vertex of the shape; [] for an
    element without a name."""
    reverse = shape.ElementReverseMap
    names = {}
    kinds = (("Face", shape.Faces), ("Edge", shape.Edges), ("Vertex", shape.Vertexes))
    for kind, elements in kinds:
        for index in range(1, len(elements) + 1):
            value = reverse.get(f"{kind}{index}")
            if value is None:
                names[f"{kind}{index}"] = []
            else:
                names[f"{kind}{index}"] = [value] if isinstance(value, str) else list(value)
    return names


def withoutCounter(name):
    """The V2 name as decoded sections, without its duplicate counter: the counter is the element
    map's tie-breaker between names that are otherwise equal (`ElementMap::setElementName`), not
    part of what the element is (ops#54). Both of its forms are taken out, in every section (a
    later feature keeps the counter of the name it builds on):
    - the duplicate count field (`...;F;1;IDX,SRC;_`): set to 0;
    - a `_<n>` written over the op code from count 2 on (`...;_2;0;F;0;...`, ops#55): the op code
      becomes None, which matches any op code (`sameUpToCounter`).
    A name that doesn't decode (V1) is returned as it is."""
    sections = App.getDecodedMappedName(name)
    if not sections:
        return name
    stripped = []
    for section in sections:
        fields = dict(section)
        fields["duplicateCount"] = "0"
        if COUNTER_OPCODE.fullmatch(fields["opCode"]):
            fields["opCode"] = None
        stripped.append(
            tuple((k, tuple(v) if isinstance(v, list) else v) for k, v in sorted(fields.items()))
        )
    return tuple(stripped)


def _withoutOpCodes(stripped):
    if isinstance(stripped, str):
        return stripped
    return tuple(tuple(field for field in section if field[0] != "opCode") for section in stripped)


def sameUpToCounter(a, b):
    """Two names (`withoutCounter` forms) that differ at most in their duplicate counters."""
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    if _withoutOpCodes(a) != _withoutOpCodes(b):
        return False
    for sectionA, sectionB in zip(a, b):
        opA, opB = dict(sectionA)["opCode"], dict(sectionB)["opCode"]
        if opA is not None and opB is not None and opA != opB:
            return False
    return True


def sharedNames(names):
    """Pairs of elements with a name each that are the same up to the duplicate counter, from
    `elementNames`: [(element, element, name, name)]."""
    groups = {}
    for element, own in names.items():
        for name in own:
            stripped = withoutCounter(name)
            groups.setdefault(_withoutOpCodes(stripped), []).append((element, name, stripped))
    shared, seen = [], set()
    for group in groups.values():
        for i, (elementA, nameA, strippedA) in enumerate(group):
            for elementB, nameB, strippedB in group[i + 1 :]:
                pair = tuple(sorted((elementA, elementB)))
                if elementA == elementB or pair in seen:
                    continue
                if sameUpToCounter(strippedA, strippedB):
                    seen.add(pair)
                    shared.append((elementA, elementB, nameA, nameB))
    return shared


def _listed(items, limit=8):
    lines = [f"  {item}" for item in items[:limit]]
    if len(items) > limit:
        lines.append(f"  ... {len(items) - limit} more")
    return "\n".join(lines)


def assertEveryElementNamed(shape):
    """Every face, edge and vertex of the shape has a mapped name. How many names an element has
    is the naming algorithm's business, so tests don't count them."""
    unnamed = [element for element, names in elementNames(shape).items() if not names]
    if unnamed:
        raise AssertionError(f"{len(unnamed)} elements without a mapped name: {unnamed}")


def assertDistinctNames(shape):
    """No two elements share a name. Names that differ only in the duplicate counter count as
    shared (`withoutCounter`)."""
    shared = sharedNames(elementNames(shape))
    if shared:
        raise AssertionError(
            f"{len(shared)} pairs of elements share a name up to the duplicate counter:\n"
            + _listed([f"{a} and {b}: {na!r} / {nb!r}" for a, b, na, nb in shared])
        )


def instanceFaces(shape, original, placements):
    """{original's face: [the result's face per instance, or None]}: each instance's copy of each
    face of the original, found in the pattern's result by its geometry. Instance k is the
    original moved by placements[k]; a copy that the pattern's fusion changed or removed is
    None."""
    tol = tolerance(shape)
    copies = {}
    for index, face in enumerate(original.Faces, 1):
        row = []
        for placement in placements:
            moved = face.copy()
            moved.transformShape(placement.toMatrix())
            found = [f"Face{i}" for i, f in enumerate(shape.Faces, 1) if _sameFace(f, moved, tol)]
            if len(found) > 1:
                raise ScenarioError(
                    f"Face{index} of the original has copies {found} at {placement}"
                )
            row.append(found[0] if found else None)
        copies[f"Face{index}"] = row
    for k in range(len(placements)):
        if all(row[k] is None for row in copies.values()):
            raise ScenarioError(f"instance {k + 1} has no face in the result: check the placements")
    return copies


def _sources(stripped):
    """What a name says its element was made from: the first section's references, linked names,
    tag and type."""
    if isinstance(stripped, str):
        return stripped
    first = dict(stripped[0])
    return (
        first["referenceIDs"],
        first["linkedNames"],
        first["iterationTag"],
        first["elementType"],
    )


def assertInstancesDistinct(shape, original, placements):
    """A pattern's instances: the copies of each face of the original have names distinct from
    each other's (up to the duplicate counter, as in `assertDistinctNames`), and each copy shares
    the original face's sources: its own name's, or, where the original face has no name, its
    index name with the original's tag. Check it on the unrefined result, where the instances'
    faces are still there; `placements` come from the pattern's parameters (the first is the
    original's)."""
    names = elementNames(shape)
    originalNames = elementNames(original)
    problems = []
    for face, row in instanceFaces(shape, original, placements).items():
        copies = [(k + 1, copy) for k, copy in enumerate(row) if copy is not None]
        if originalNames[face]:
            expected = {_sources(withoutCounter(n)) for n in originalNames[face]}
        else:
            expected = {((face,), (), str(original.Tag), "F")}
        for k, copy in copies:
            got = {_sources(withoutCounter(n)) for n in names[copy]}
            if not got & expected:
                problems.append(
                    f"{face}, instance {k} ({copy}): no name shares the original's sources"
                )
        for i, (k, copy) in enumerate(copies):
            for m, other in copies[i + 1 :]:
                for _, _, na, nb in sharedNames({copy: names[copy], other: names[other]}):
                    problems.append(
                        f"{face}, instances {k} and {m} ({copy}, {other}): {na!r} / {nb!r}"
                    )
    if problems:
        raise AssertionError(
            f"{len(problems)} problems with the pattern's instances (names that differ only in "
            "the duplicate counter count as shared):\n" + _listed(problems)
        )


def scenarioClasses(modules):
    """The concrete Scenario classes defined in the modules, in definition order."""
    found = []
    for module in modules:
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, Scenario)
                and value.__module__ == module.__name__
                and not value.__dict__.get("abstract", False)
            ):
                found.append(value)
    return found
