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

"""A generic record of a document's saved state and results, and the comparison of two records
(FreeCAD-CH ops#323, notes/beta-compatibility.md 3.2).

The CI reopen gate (PartDesignTests/TestCompatCorpus.py) compares a file's record saved with it
against the record of the same file reopened, recomputed, and saved and reopened again. The
difference check at open (PR E) will compare a file's restored results with its recompute. Both
use this module, so one comparison serves both.

`record(doc)` works on a live document and on a restored one alike: it reads only what the
document holds now. One entry per object:

- `type`, `id` (the object id: creation order, 5.1), `invalid`, `touched` (still to recompute);
- `props`: every saved property (not transient, not a shape) as `[type, value]`, the value in a
  plain form (numbers, strings, vectors, placements, lists, links by object name, a material by
  its UUID). A link-sub property holds its targets only: its sub-elements are compared by
  geometry, in `refs`. A value with no plain form is recorded as `{"py": <type>}`, which
  make_generation refuses (`opaqueValues`);
- `refs`: every sub-element reference, from every link-sub property and from
  `Part::PropertyFilletEdges` (edge indices into the base's shape): the target, the sub as saved,
  and the element's geometric key (kind, centre, mass; a planar face's normal; a line's ends; a
  circle's centre, axis and radius; a vertex's point). Compared by key, never by name or index;
- `shape`: the shape's type, volume, area, exact bounding box, element counts and centre;
- `geometry`: a sketch's geometry, one entry per geometry with its key points and construction
  flag (the generic property value can't be compared: `Part.Geometry` has no plain form);
- `names`: the element names, one sorted line per element and name, "kind centre mass : name",
  the name expanded (interned names) and its tags (object ids) masked to object names;
- `guesses`: the reference solver's guess records (`App.getReferenceReport`);
- `dof`: a sketch's degrees of freedom (meaningful after a recompute only).

`compare(expected, actual, stage, tolerance)` returns the differences as readable lines and the
largest float deviations seen (for calibrating the tolerances). The stages:
- "open": everything but `dof`, at the tight tolerance (values from the same BRep);
- "recompute": everything, at the recompute tolerance;
- "rehearsal": a forced naming migration, so no names (guess records are compared).

`delta(base, other)` and `applyDelta(base, delta)` keep one record as a small overlay of another
(a generation's records as reopened, over its records as saved).

From the command line, without FreeCAD: `python CompatRecord.py diff a.json b.json [stage]`
prints the differences of two record files.
"""

import json
import math
import sys

FORMAT = 1

# Tolerances (relative, absolute floor in mm), by stage: about ten times the largest drift both
# CI platforms showed on gen0 (fork PR 295, run 38327969727: macOS 9.1e-13 abs / 2.8e-16 rel,
# Windows 4.5e-13 / 1.6e-16, the same in every stage; the design note started at 1e-9 for the
# open and 1e-6 / 1e-5 mm after a recompute). B2's BSpline models (Loft, Pipe) recalibrate them
# from the COMPAT-DRIFT lines; a looser bound is a `compat-neutral` change.
TOLERANCE = {
    "open": (1e-14, 1e-11),
    "recompute": (1e-14, 1e-11),
    "rehearsal": (1e-14, 1e-11),
}

# Properties left out of the record: derived, not content.
SKIPPED_PROPERTIES = {
    # the element map's version: the reading build's own (the names are compared instead)
    "_ElementMapVersion",
    # an App::Link's shape cache, added when the link's shape is first asked for
    "_Part_ShapeCache",
}

_LINK_SUB_TYPES = ("LinkSub",)  # PropertyLinkSub*, PropertyXLinkSub*
_FILLET_EDGES = "Part::PropertyFilletEdges"


# ---------------------------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------------------------


def record(doc, names=True):
    """The record of `doc` as it is now: a dict that `json.dump` writes."""
    masker = _Masker(doc)
    objects = {}
    for obj in doc.Objects:
        objects[obj.Name] = _object(obj, doc, masker, names)
    return {"format": FORMAT, "objects": objects}


def _object(obj, doc, masker, names):
    entry = {
        "type": obj.TypeId,
        "id": obj.ID,
        "invalid": "Invalid" in obj.State,
        # still to recompute: after a touch-all recompute, only what the saving build left so
        "touched": "Touched" in obj.State,
    }
    props = {}
    refs = {}
    for name in obj.PropertiesList:
        if name in SKIPPED_PROPERTIES or "Transient" in obj.getPropertyStatus(name):
            continue
        kind = obj.getTypeIdOfProperty(name)
        if kind.startswith("Part::PropertyPartShape") or kind == "Part::PropertyShapeHistory":
            continue
        try:
            value = getattr(obj, name)
        except Exception as e:
            props[name] = [kind, {"error": type(e).__name__}]
            continue
        if any(t in kind for t in _LINK_SUB_TYPES):
            props[name] = [kind, _targets(value, doc)]
            for index, (target, sub) in enumerate(_pairs(value)):
                refs[f"{name}[{index}]"] = _reference(target, sub, doc)
        elif kind == _FILLET_EDGES:
            props[name] = [kind, _plain(value, doc)]
            base = getattr(obj, "Base", None)
            for index, item in enumerate(value or []):
                refs[f"{name}[{index}]"] = _filletEdge(base, item[0], doc)
        elif kind == "Part::PropertyGeometryList":
            props[name] = [kind, len(value)]
            if name == "Geometry":
                entry["geometry"] = _sketchGeometry(obj, value)
        else:
            props[name] = [kind, _plain(value, doc)]
    entry["props"] = props
    if refs:
        entry["refs"] = refs
    shape = _shapeOf(obj)
    if shape is not None:
        entry["shape"] = _shapeEntry(shape)
        if names and not shape.isNull():
            entry["names"] = _names(shape, masker)
    guesses = _guesses(obj)
    if guesses:
        entry["guesses"] = guesses
    if obj.isDerivedFrom("Sketcher::SketchObject"):
        try:
            entry["dof"] = obj.DoF
        except Exception:
            pass
    return entry


def _shapeOf(obj):
    if "Shape" not in obj.PropertiesList:
        return None
    if not obj.getTypeIdOfProperty("Shape").startswith("Part::PropertyPartShape"):
        return None
    return obj.Shape


def _number(value):
    return float(value)


def _vector(v):
    return [float(v.x), float(v.y), float(v.z)]


def _rotation(r):
    """The quaternion, with the sign that makes its first non-zero component positive (q and -q
    are the same rotation)."""
    q = [float(c) for c in r.Q]
    for c in q:
        if abs(c) > 1e-12:
            if c < 0:
                q = [-x for x in q]
            break
    return q


def _linkName(obj, doc):
    if obj.Document is doc:
        return obj.Name
    import os

    fileName = os.path.basename(obj.Document.FileName) or obj.Document.Name
    return f"{fileName}#{obj.Name}"


def _plain(value, doc, depth=0):
    """A JSON form of a property value: numbers, strings, lists; anything else as its type."""
    import FreeCAD as App

    if depth > 20:
        return {"py": "deep"}
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, App.Units.Quantity):
        return float(value.Value)
    if isinstance(value, App.Vector):
        return _vector(value)
    if isinstance(value, App.Placement):
        return {"base": _vector(value.Base), "rotation": _rotation(value.Rotation)}
    if isinstance(value, App.Rotation):
        return {"rotation": _rotation(value)}
    if isinstance(value, App.Matrix):
        return [float(c) for c in value.A]
    if isinstance(value, App.DocumentObject):
        return {"link": _linkName(value, doc)}
    if isinstance(value, (list, tuple)):
        return [_plain(v, doc, depth + 1) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v, doc, depth + 1) for k, v in sorted(value.items())}
    if isinstance(value, bytes):
        return {"bytes": len(value)}
    constraint = _constraint(value)
    if constraint is not None:
        return constraint
    if type(value).__name__ == "Material" and hasattr(value, "UUID"):
        return {"material": value.UUID}
    # A value with no plain form: compared by its type alone, so make_generation refuses a record
    # holding one (`opaqueValues`) unless OPAQUE_ALLOWED lists it.
    return {"py": type(value).__name__}


# (object type, property) whose value may be recorded by its type alone. Empty: every saved value
# has a plain form.
OPAQUE_ALLOWED = set()


def opaqueValues(rec):
    """ "object.property" of each value recorded by its type alone ({"py": <type>}) or not read
    at all ({"error": <exception>}), and not in OPAQUE_ALLOWED."""
    found = []

    def opaque(value):
        if isinstance(value, dict):
            if set(value) in ({"py"}, {"error"}):  # no plain form, or unreadable
                return True
            return any(opaque(v) for v in value.values())
        if isinstance(value, list):
            return any(opaque(v) for v in value)
        return False

    for name, entry in rec.get("objects", {}).items():
        for prop, (kind, value) in entry.get("props", {}).items():
            if (entry["type"], prop) not in OPAQUE_ALLOWED and opaque(value):
                found.append(f"{name}.{prop}")
    return found


def _constraint(value):
    if type(value).__name__ != "Constraint" or not hasattr(value, "FirstPos"):
        return None
    out = {}
    for field in (
        "Type",
        "Name",
        "First",
        "FirstPos",
        "Second",
        "SecondPos",
        "Third",
        "ThirdPos",
        "Value",
        "Driving",
        "IsActive",
        "InVirtualSpace",
    ):
        if hasattr(value, field):
            v = getattr(value, field)
            out[field] = float(v) if isinstance(v, float) else v
    return out


def _pairs(value):
    """The (target, sub) pairs of a link-sub property's value, empty subs left out."""
    import FreeCAD as App

    if value is None:
        return []
    if isinstance(value, tuple) and value and isinstance(value[0], App.DocumentObject):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return []
    pairs = []
    for item in items:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        target, subs = item[0], item[1]
        if not isinstance(target, App.DocumentObject):
            continue
        if isinstance(subs, str):
            subs = [subs]
        for sub in subs or ():
            if sub:
                pairs.append((target, sub))
    return pairs


def _targets(value, doc):
    import FreeCAD as App

    if value is None:
        return None
    if isinstance(value, App.DocumentObject):
        return _linkName(value, doc)
    if isinstance(value, tuple) and value and isinstance(value[0], App.DocumentObject):
        return [_linkName(value[0], doc)]
    out = []
    for item in value if isinstance(value, (list, tuple)) else ():
        if isinstance(item, App.DocumentObject):
            out.append(_linkName(item, doc))
        elif isinstance(item, tuple) and item and isinstance(item[0], App.DocumentObject):
            out.append(_linkName(item[0], doc))
    return out


def _reference(target, sub, doc):
    entry = {"target": _linkName(target, doc), "sub": sub}
    if sub.startswith("?") or ".?" in sub:
        entry["key"] = {"broken": True}
        return entry
    try:
        element = target.getSubObject(sub)
    except Exception as e:
        element = None
        entry["error"] = type(e).__name__
    if element is None or not hasattr(element, "ShapeType") or element.isNull():
        entry["key"] = {"broken": True}
    else:
        entry["key"] = elementKey(element)
    return entry


def _filletEdge(base, index, doc):
    entry = {"target": _linkName(base, doc) if base else None, "sub": f"Edge{index}"}
    try:
        edge = base.Shape.Edges[index - 1]
        entry["key"] = elementKey(edge)
    except Exception:
        entry["key"] = {"broken": True}
    return entry


def _centre(shape):
    for attribute in ("CenterOfMass", "CenterOfGravity"):
        try:
            return _vector(getattr(shape, attribute))
        except Exception:
            pass
    return None


def _endpoints(edge):
    points = [_vector(v.Point) for v in edge.Vertexes]
    return sorted(points, key=lambda p: [round(c, 6) for c in p])


def elementKey(shape):
    """The geometric key of an element (or of a whole shape)."""
    import Part

    kind = shape.ShapeType
    key = {"kind": kind}
    if kind == "Vertex":
        key["point"] = _vector(shape.Point)
        return key
    centre = _centre(shape)
    if centre is not None:
        key["centre"] = centre
    if kind == "Edge":
        key["length"] = float(shape.Length)
        key["ends"] = _endpoints(shape)
        curve = shape.Curve
        if isinstance(curve, Part.Circle):
            key["circle"] = _vector(curve.Center) + _vector(curve.Axis) + [float(curve.Radius)]
    elif kind == "Face":
        key["area"] = float(shape.Area)
        if isinstance(shape.Surface, Part.Plane):
            u0, u1, v0, v1 = shape.ParameterRange
            key["normal"] = _vector(shape.normalAt((u0 + u1) / 2, (v0 + v1) / 2))
    else:
        key["volume"] = float(shape.Volume) if shape.Solids else 0.0
        key["area"] = float(shape.Area)
    return key


def _shapeEntry(shape):
    if shape.isNull():
        return None
    box = shape.optimalBoundingBox(False, False)
    return {
        "type": shape.ShapeType,
        "volume": float(shape.Volume) if shape.Solids else 0.0,
        "area": float(shape.Area),
        "box": [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax],
        "counts": [len(shape.Solids), len(shape.Faces), len(shape.Edges), len(shape.Vertexes)],
        "centre": _centre(shape),
    }


def _sketchGeometry(sketch, geometry):
    out = []
    for index, g in enumerate(geometry):
        entry = {"type": type(g).__name__}
        try:
            entry["construction"] = bool(sketch.getConstruction(index))
        except Exception:
            pass
        for field in ("StartPoint", "EndPoint", "Center", "Axis", "XAxis"):
            if hasattr(g, field):
                try:
                    entry[field] = _vector(getattr(g, field))
                except Exception:
                    pass
        for field in ("Radius", "MajorRadius", "MinorRadius", "X", "Y", "Z"):
            if hasattr(g, field):
                try:
                    entry[field] = float(getattr(g, field))
                except Exception:
                    pass
        if hasattr(g, "getPoles"):
            entry["poles"] = [_vector(p) for p in g.getPoles()]
            entry["knots"] = [float(k) for k in g.getKnots()]
            entry["multiplicities"] = list(g.getMultiplicities())
            entry["degree"] = g.Degree
        out.append(entry)
    return out


def _guesses(obj):
    import FreeCAD as App

    if not hasattr(App, "getReferenceReport"):
        return []
    try:
        rows = App.getReferenceReport(obj)
    except Exception:
        return []
    out = []
    for row in rows:
        if not row.get("guess_kind"):
            continue
        original = row.get("original") or {}
        out.append(
            {
                "property": row.get("property"),
                "index": row.get("index"),
                "kind": row.get("guess_kind"),
                "original": original.get("index"),
                "alternatives": sorted(a.get("index") for a in row.get("alternatives") or []),
            }
        )
    return sorted(out, key=lambda g: (g["property"] or "", g["index"] or 0))


# ---------------------------------------------------------------------------------------------
# Element names
# ---------------------------------------------------------------------------------------------


def _format(value):
    text = f"{value:.4f}"
    return "0.0000" if text == "-0.0000" else text


def _nameKey(kind, element):
    if kind == "Vertex":
        point, mass = element.Point, 0.0
    else:
        try:
            point = element.CenterOfMass
        except Exception:
            point = element.BoundBox.Center
        mass = element.Area if kind == "Face" else element.Length
    return (
        f"{kind} c=({','.join(_format(c) for c in (point.x, point.y, point.z))}) m={_format(mass)}"
    )


class _Masker:
    """V2 names with their tags (object ids) written as `{ObjectName}`, recursing into Linked and
    Connected Names (sorted again after masking), as the NamingGolden dumps do."""

    def __init__(self, doc):
        self.names = {str(obj.ID): obj.Name for obj in doc.Objects}

    def tag(self, tag):
        if tag in ("", "0"):
            return tag
        sign = "-" if tag.startswith("-") else ""
        name = self.names.get(tag.lstrip("-"))
        return "{" + sign + name + "}" if name else "#" + tag

    def mask(self, name):
        import FreeCAD as App

        if not hasattr(App, "getDecodedMappedName"):
            return name
        sections = App.getDecodedMappedName(name)
        if not sections:
            return name
        encoded = []
        for section in sections:
            section = dict(section)
            for field in ("linkedNames", "connectedElements"):
                section[field] = sorted(self.mask(n) for n in section[field])
            section["iterationTag"] = self.tag(section["iterationTag"])
            encoded.append(App.makeEncodedSection(**section))
        return "|".join(encoded)


def _names(shape, masker):
    import FreeCAD as App

    expand = getattr(App, "expandMappedName", None)
    reverse = shape.ElementReverseMap
    lines = []
    for kind, elements in (
        ("Face", shape.Faces),
        ("Edge", shape.Edges),
        ("Vertex", shape.Vertexes),
    ):
        for index, element in enumerate(elements, 1):
            key = _nameKey(kind, element)
            found = reverse.get(f"{kind}{index}")
            if found is None:
                found = []
            elif isinstance(found, str):
                found = [found]
            if not found:
                lines.append(f"{key} : -")
            for name in found:
                if expand:
                    try:
                        name = expand(name)
                    except Exception:
                        pass
                try:
                    name = masker.mask(name)
                except Exception:
                    pass
                lines.append(f"{key} : {name}")
    return sorted(lines)


# ---------------------------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------------------------


class _Drift:
    """The largest float deviations seen, absolute and relative."""

    def __init__(self):
        self.absolute = 0.0
        self.relative = 0.0
        self.where = ""

    def add(self, a, b, where):
        d = abs(a - b)
        scale = max(abs(a), abs(b))
        if d > self.absolute:
            self.absolute = d
            self.where = where
        if scale > 1e-6:
            self.relative = max(self.relative, d / scale)

    def asDict(self):
        return {"abs": self.absolute, "rel": self.relative, "where": self.where}


class _Comparison:
    def __init__(self, tolerance):
        self.rel, self.abs = tolerance
        self.lines = []
        self.drift = _Drift()

    def differ(self, where, expected, actual):
        self.lines.append(f"{where}: expected {_short(expected)}, got {_short(actual)}")

    def value(self, where, expected, actual):
        """Compares two plain values, floats with the tolerance."""
        if isinstance(expected, bool) or isinstance(actual, bool):
            if type(expected) is not type(actual) or expected != actual:
                self.differ(where, expected, actual)
            return
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            if isinstance(expected, int) and isinstance(actual, int):
                if expected != actual:
                    self.differ(where, expected, actual)
                return
            a, b = float(expected), float(actual)
            if math.isnan(a) or math.isnan(b):
                if not (math.isnan(a) and math.isnan(b)):
                    self.differ(where, expected, actual)
                return
            self.drift.add(a, b, where)
            if abs(a - b) > max(self.abs, self.rel * max(abs(a), abs(b))):
                self.differ(where, expected, actual)
            return
        if isinstance(expected, list) and isinstance(actual, list):
            if len(expected) != len(actual):
                self.differ(where + " (length)", len(expected), len(actual))
                return
            for i, (e, a) in enumerate(zip(expected, actual)):
                self.value(f"{where}[{i}]", e, a)
            return
        if isinstance(expected, dict) and isinstance(actual, dict):
            for k in sorted(set(expected) | set(actual)):
                if k not in actual:
                    self.differ(f"{where}.{k}", expected[k], "(missing)")
                elif k not in expected:
                    self.differ(f"{where}.{k}", "(missing)", actual[k])
                else:
                    self.value(f"{where}.{k}", expected[k], actual[k])
            return
        if expected != actual:
            self.differ(where, expected, actual)


def _short(value, limit=160):
    text = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[:limit] + "..."


def compare(expected, actual, stage, tolerance=None, names=None, touched=True):
    """The differences between two records as lines, and the drift (largest float deviations).

    Objects, their types and ids must match. A saved property that is gone or whose type
    changed is a difference; a property that only the actual record has (a later build added
    it) is not. Names are compared unless `names` is False (by default, in every stage but
    "rehearsal"); a caller turns them off when the file's naming revision isn't the build's.
    Guess records are compared in every stage. `touched=False` leaves out which objects are
    Touched (a forced naming migration touches every migrated object at the open)."""
    c = _Comparison(tolerance or TOLERANCE[stage])
    if names is None:
        names = stage != "rehearsal"
    eobjs, aobjs = expected.get("objects", {}), actual.get("objects", {})
    for name in sorted(set(eobjs) - set(aobjs)):
        c.lines.append(f"{name}: missing")
    for name in sorted(set(aobjs) - set(eobjs)):
        c.lines.append(f"{name}: new object ({aobjs[name].get('type')})")
    for name in sorted(set(eobjs) & set(aobjs)):
        e, a = eobjs[name], aobjs[name]
        for field in ("type", "id", "invalid") + (("touched",) if touched else ()):
            if e.get(field) != a.get(field):
                c.differ(f"{name}.{field}", e.get(field), a.get(field))
        eprops, aprops = e.get("props", {}), a.get("props", {})
        for prop in sorted(eprops):
            if prop not in aprops:
                c.lines.append(f"{name}.{prop}: property gone")
                continue
            if eprops[prop][0] != aprops[prop][0]:
                c.differ(f"{name}.{prop} (type)", eprops[prop][0], aprops[prop][0])
                continue
            c.value(f"{name}.{prop}", eprops[prop][1], aprops[prop][1])
        erefs, arefs = e.get("refs", {}), a.get("refs", {})
        for ref in sorted(set(erefs) | set(arefs)):
            if ref not in arefs or ref not in erefs:
                c.differ(f"{name}.{ref}", erefs.get(ref, "(none)"), arefs.get(ref, "(none)"))
                continue
            er, ar = erefs[ref], arefs[ref]
            where = f"{name}.{ref} ({er.get('sub')} -> {ar.get('sub')})"
            if er.get("target") != ar.get("target"):
                c.differ(where + " target", er.get("target"), ar.get("target"))
            c.value(where, er.get("key"), ar.get("key"))
        c.value(f"{name}.shape", e.get("shape"), a.get("shape"))
        c.value(f"{name}.geometry", e.get("geometry"), a.get("geometry"))
        if names:
            _compareNames(c, name, e.get("names"), a.get("names"))
        if e.get("guesses", []) != a.get("guesses", []):
            c.differ(f"{name}.guesses", e.get("guesses", []), a.get("guesses", []))
        if stage != "open" and e.get("dof") != a.get("dof"):
            c.differ(f"{name}.dof", e.get("dof"), a.get("dof"))
    return c.lines, c.drift.asDict()


def delta(base, other, stage="open"):
    """What `other` holds that `base` doesn't, within the stage's tolerance: {object: {field:
    value}}, a property field as {"props": {name: value}}, a gone object as None. With
    `applyDelta`, a record kept as a small overlay of another (a generation's reopened records
    over its saved ones)."""
    tolerance = TOLERANCE[stage]
    out = {}
    bobjs, oobjs = base.get("objects", {}), other.get("objects", {})
    for name in sorted(set(bobjs) - set(oobjs)):
        out[name] = None
    for name, o in sorted(oobjs.items()):
        b = bobjs.get(name)
        if b is None:
            out[name] = {"new": o}
            continue
        changed = {}
        for field in sorted(set(b) | set(o)):
            if field == "props":
                props = {}
                for prop in sorted(set(b["props"]) | set(o.get("props", {}))):
                    if prop not in o["props"]:
                        props[prop] = None
                        continue
                    c = _Comparison(tolerance)
                    c.value(prop, b["props"].get(prop), o["props"][prop])
                    if c.lines or prop not in b["props"]:
                        props[prop] = o["props"][prop]
                if props:
                    changed["props"] = props
                continue
            c = _Comparison(tolerance)
            c.value(field, b.get(field), o.get(field))
            if c.lines:
                changed[field] = o.get(field)
        if changed:
            out[name] = changed
    return out


def applyDelta(base, changes):
    """`base` with `delta`'s changes applied (a new record; `base` is left as it is)."""
    out = json.loads(json.dumps(base))
    objs = out.setdefault("objects", {})
    for name, changed in (changes or {}).items():
        if changed is None:
            objs.pop(name, None)
        elif "new" in changed:
            objs[name] = changed["new"]
        else:
            for field, value in changed.items():
                if field == "props":
                    props = objs[name].setdefault("props", {})
                    for prop, v in value.items():
                        if v is None:
                            props.pop(prop, None)
                        else:
                            props[prop] = v
                elif value is None:
                    objs[name].pop(field, None)
                else:
                    objs[name][field] = value
    return out


def _compareNames(c, name, expected, actual, limit=8):
    if expected == actual:
        return
    if expected is None or actual is None:
        c.differ(f"{name}.names", expected is not None, actual is not None)
        return
    gone = sorted(set(expected) - set(actual))
    new = sorted(set(actual) - set(expected))
    if not gone and not new:
        c.lines.append(f"{name}.names: the same lines, counted differently")
        return
    lines = [f"{name}.names: {len(gone)} lines gone, {len(new)} new"]
    lines += ["  - " + line for line in gone[:limit]]
    lines += ["  + " + line for line in new[:limit]]
    c.lines.append("\n".join(lines))


def dump(rec, path, compact=False):
    """Writes a record as JSON with LF line ends (the generations' hashes are of the bytes).
    `compact` leaves out the indentation and spaces: a generation's records, a third smaller."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        if compact:
            json.dump(rec, fh, sort_keys=True, separators=(",", ":"))
        else:
            json.dump(rec, fh, indent=1, sort_keys=True)
        fh.write("\n")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _main(argv):
    if len(argv) < 4 or argv[1] != "diff":
        print(
            "usage: CompatRecord.py diff <expected.json> <actual.json> [open|recompute|rehearsal]"
        )
        return 2
    stage = argv[4] if len(argv) > 4 else "recompute"
    expected, actual = load(argv[2]), load(argv[3])
    expected = expected.get("record", expected)
    actual = actual.get("record", actual)
    lines, drift = compare(expected, actual, stage)
    for line in lines:
        print(line)
    print(f"{len(lines)} differences; drift {json.dumps(drift)}")
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
