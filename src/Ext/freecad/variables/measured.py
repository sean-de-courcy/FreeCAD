# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, notes/measured-variables-design.md in the ops repo)

"""Measured variables: Onshape's Variable feature in the `MEASURED` mode.

A measured variable is an ordinary property of a part studio's VarSet (an App::VarSet held by an
App::Part) whose expression reads `<measurement>.Value`. The measurement is an App::FeaturePython
with a `MeasuredVariable` proxy, in the same studio. It re-reads the geometry on every recompute,
and a lost reference raises an error naming it; FreeCAD then marks the VarSet and every feature
using the variable as failed ("'<measurement>' has an error").

Kinds, as Onshape's (notes/onshape-facts.md MV0-MV3 in the ops repo):
- Distance: two references (vertex, edge or face). Minimum (the default) is the gap between them
  (BRepExtrema); Maximum the farthest points. With Minimum, Use axis measures a circle, an arc or
  a sphere from its center and a cylinder or a cone from its axis. Value to record: the distance,
  or its X, Y or Z component (unsigned, in the studio's frame).
- Length: edges and wire bodies, summed; a face beside them is ignored, a face alone refused.
- Diameter: one circle or arc edge, or one cylinder or sphere face; Radius records the radius.
"""

import FreeCAD as App

FORMAT = 1
# Saved by index: append only.
KINDS = ["Distance", "Length", "Diameter"]
DISTANCE_TYPES = ["Minimum", "Maximum"]
RECORDS = ["Distance", "X", "Y", "Z"]

_READ_ONLY_OUTPUT = 1 | 8  # Prop_ReadOnly | Prop_Output


class MeasureError(RuntimeError):
    """A measured variable that can't be measured (a lost or unsuitable reference)."""


class MeasuredVariable:
    """Proxy of an App::FeaturePython measuring a distance, a length or a diameter."""

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        def add(type_id, name, doc, attr=0):
            if name not in obj.PropertiesList:
                obj.addProperty(type_id, name, "Measured variable", doc, attr)

        add("App::PropertyInteger", "Format", "Version of this object's property table", _READ_ONLY_OUTPUT)
        add("App::PropertyEnumeration", "Kind", "What is measured")
        add("App::PropertyEnumeration", "DistanceType", "Distance only: Minimum or Maximum")
        add("App::PropertyBool", "UseAxis",
            "Distance with Minimum only: circles, arcs and spheres from their centers, cylinders "
            "and cones from their axes")
        add("App::PropertyEnumeration", "ValueToRecord",
            "Distance only: the distance, or its X, Y or Z component (unsigned)")
        add("App::PropertyBool", "Radius", "Diameter only: record the radius")
        add("App::PropertyLinkSubList", "References", "The measured vertices, edges or faces")
        add("App::PropertyLength", "Value", "The measured value", _READ_ONLY_OUTPUT)
        add("App::PropertyStringList", "ReferenceNames",
            "The references as last measured, to name a lost one", _READ_ONLY_OUTPUT | 4)
        if not obj.Kind or obj.Kind not in KINDS:
            obj.Kind = KINDS
        if not obj.DistanceType or obj.DistanceType not in DISTANCE_TYPES:
            obj.DistanceType = DISTANCE_TYPES
        if not obj.ValueToRecord or obj.ValueToRecord not in RECORDS:
            obj.ValueToRecord = RECORDS
        if obj.Format == 0:
            obj.Format = FORMAT

    def onDocumentRestored(self, obj):
        self.setup(obj)
        if obj.Format > FORMAT:
            App.Console.PrintWarning(
                "{}: made by a newer build (measured variable format {}); it may not measure as "
                "intended\n".format(obj.Label, obj.Format))
        try:  # the saved value was measured with the saved placements
            self.frames = _frames([(o, s) for o, subs in obj.References for s in (subs or ("",))])
        except Exception:
            self.frames = None

    def execute(self, obj):
        refs = _references(obj)
        try:
            value = measure(obj.Kind, refs, **options_of(obj))
        except MeasureError as e:
            raise MeasureError("Measured variable '{}': {}".format(variable_name(obj), e)) from None
        obj.ReferenceNames = [_show(o, sub) for o, sub in refs]
        obj.Value = value
        self.frames = _frames(refs)

    def mustExecute(self, obj):
        # A body's placement change touches neither the measurement nor the features it links
        # (and a link to the body would be a cycle when one of its features uses the variable):
        # compare the placements read at the last measurement (kept in memory only; a reopened
        # file starts from its saved placements, onDocumentRestored).
        frames = getattr(self, "frames", None)
        if frames is None:
            return False
        try:
            pairs = [(o, s) for o, subs in obj.References for s in (subs or ("",))]
            return _frames(pairs) != frames
        except Exception:
            return False

    def dumps(self):
        return None

    def loads(self, state):
        return None

    __getstate__ = dumps

    def __setstate__(self, state):
        return None


def _references(obj):
    """The (object, subelement) pairs; a lost one raises MeasureError naming it."""
    pairs = []
    for linked, subs in obj.References:
        for sub in subs or ("",):
            pairs.append((linked, sub))
    expected = list(obj.ReferenceNames)
    if len(pairs) < len(expected):
        shown = [_show(o, s) for o, s in pairs]
        lost = [name for name in expected if name not in shown]
        raise MeasureError("Measured variable '{}': lost reference {}".format(
            variable_name(obj), ", ".join(lost) or ", ".join(expected)))
    for linked, sub in pairs:
        if _is_missing(sub):
            raise MeasureError("Measured variable '{}': lost reference {}".format(
                variable_name(obj), _show(linked, sub)))
    return pairs


def _is_missing(sub):
    # The fork keeps a lost element with a '?' prefix (Data::MISSING_PREFIX).
    return "?" in sub


def _show(obj, sub):
    """Label.Element of one reference (References holds the indexed name, kept current by the
    fork's element naming)."""
    name = obj.Label if obj is not None else "?"
    sub = sub.replace("?", "")
    return "{}.{}".format(name, sub) if sub else name


def _frame_path(obj):
    """(root, path objects, transform) placing `obj` in its studio's frame: `root` is the studio
    (its own placement left out, transform False) or, for the implicit studio, `obj`'s top parent
    (placed, transform True); `path` the objects from below `root` down to `obj`, each placing the
    next (a body, then its feature)."""
    studio = studio_of(obj)
    try:
        parents = list(obj.Parents)
    except Exception:
        parents = []
    best = None
    for parent, sub in parents:
        try:
            chain = parent.getSubObjectList(sub)
        except Exception:
            continue
        if not chain or chain[-1] != obj:
            continue
        if studio is not None and studio in chain:
            i = chain.index(studio)
            return studio, chain[i + 1:], False
        if best is None:
            best = (parent, chain[1:], True)
    if best is not None:
        return best
    if studio is obj:
        return obj, [], False
    return obj, [], True


def _frames(pairs):
    """The placements that put each reference in the studio's frame, apart from the referenced
    object's own (a change of which touches it): a body's, a nested part's. A change of one of
    these doesn't touch the measurement, so mustExecute compares them."""
    out = []
    for linked, _sub in pairs:
        root, path, transform = _frame_path(linked)
        placed = ([root] if transform else []) + path[:-1]
        out.append(tuple((o.Name, tuple(round(x, 12) for x in o.Placement.toMatrix().A))
                         for o in placed if hasattr(o, "Placement")))
    return out


def _resolve(obj, sub):
    """The shape of one reference in its studio's frame (so two references in differently placed
    bodies compare right, and a body's placement counts), or raise MeasureError."""
    import Part

    root, path, transform = _frame_path(obj)
    try:
        shape = Part.getShape(root, "".join(o.Name + "." for o in path) + sub,
                              needSubElement=True, transform=transform)
    except Exception:
        shape = None
    if shape is None or shape.isNull():
        raise MeasureError("lost reference {}".format(_show(obj, sub)))
    return shape


def options_of(m):
    """The measurement `m`'s options, as `measure` and `add` take them."""
    return {"distance_type": m.DistanceType, "use_axis": bool(m.UseAxis),
            "record": m.ValueToRecord, "radius": bool(m.Radius)}


def check_options(distance_type="Minimum", use_axis=False, record="Distance", radius=False):
    """Raise ValueError for an option value that doesn't exist."""
    if distance_type not in DISTANCE_TYPES:
        raise ValueError("distance type must be one of {}".format(", ".join(DISTANCE_TYPES)))
    if record not in RECORDS:
        raise ValueError("value to record must be one of {}".format(", ".join(RECORDS)))


def set_options(m, distance_type="Minimum", use_axis=False, record="Distance", radius=False):
    """Set the measurement `m`'s options (each kind reads its own; the others are kept)."""
    check_options(distance_type, use_axis, record, radius)
    m.DistanceType = distance_type
    m.UseAxis = bool(use_axis)
    m.ValueToRecord = record
    m.Radius = bool(radius)


def measure(kind, refs, distance_type="Minimum", use_axis=False, record="Distance", radius=False):
    """The measured value in mm of `refs`, a list of (object, subelement) pairs. Each kind reads
    its own options and ignores the others, as Onshape ignores Radius for a Length (MV2)."""
    if kind == "Length":
        return _length(refs)
    if kind == "Diameter":
        d = _diameter(refs)
        return d / 2.0 if radius else d
    if kind == "Distance":
        d, vector = _distance(refs, distance_type, use_axis)
        if record == "Distance":
            return d
        return abs({"X": vector.x, "Y": vector.y, "Z": vector.z}[record])
    raise MeasureError("unknown kind {!r}".format(kind))


def distance_components(refs, distance_type="Minimum", use_axis=False):
    """(distance, |X|, |Y|, |Z|) of a Distance (Onshape's Axis measurements group)."""
    d, v = _distance(refs, distance_type, use_axis)
    return d, abs(v.x), abs(v.y), abs(v.z)


def _shape(obj, sub):
    if obj is None:
        raise MeasureError("lost reference (the measured object was deleted)")
    return _resolve(obj, sub)


def is_wire_body(shape):
    """Whether `shape`, a whole object's, is a wire body (edges and no faces: a sketch, a wire)."""
    return bool(shape.Edges) and not shape.Faces


def _length(refs):
    """Onshape's Length (MV2): the edges and wire bodies summed. Anything else picked (a face, a
    vertex) is ignored, as Onshape ignores a face beside an edge; with no edge at all it fails, as
    Onshape's does: a face's perimeter is not measured."""
    if not refs:
        raise MeasureError("Length needs one or more edges")
    total = 0.0
    counted = 0
    for obj, sub in refs:
        shape = _shape(obj, sub)
        if shape.ShapeType == "Edge":
            total += shape.Length
            counted += 1
        elif not sub and is_wire_body(shape):
            total += sum(e.Length for e in shape.Edges)
            counted += 1
    if not counted:
        raise MeasureError("Length takes edges and wire bodies: select edges to measure ({} has "
                           "none; a face's perimeter is not measured)".format(
                               ", ".join(_show(o, s) for o, s in refs)))
    return total


def _analytic(shape):
    """What `shape` is for Diameter and Use axis: ("Circle", radius, center, axis) for a circle or
    arc edge, ("Cylinder", radius, point on the axis, axis), ("Sphere", radius, center, None) or
    ("Cone", None, point on the axis, axis) for such a face; else None."""
    import Part

    if shape.ShapeType == "Edge":
        curve = shape.Curve
        if isinstance(curve, Part.Circle):
            return "Circle", curve.Radius, curve.Center, curve.Axis
        return None
    if shape.ShapeType != "Face":
        return None
    surface = shape.Surface
    if isinstance(surface, Part.Cylinder):
        return "Cylinder", surface.Radius, surface.Center, surface.Axis
    if isinstance(surface, Part.Sphere):
        return "Sphere", surface.Radius, surface.Center, None
    if isinstance(surface, Part.Cone):
        return "Cone", None, surface.Apex, surface.Axis
    return None


def _describe(shape):
    """A few words on what `shape` is, for an error."""
    kind = _analytic(shape)
    if kind is not None:
        return {"Circle": "a circle", "Cylinder": "a cylinder face", "Sphere": "a sphere face",
                "Cone": "a cone face"}[kind[0]]
    if shape.ShapeType == "Face":
        return "a {} face".format(type(shape.Surface).__name__.lower())
    if shape.ShapeType == "Edge":
        return "a {} edge".format(type(shape.Curve).__name__.lower())
    return "a " + shape.ShapeType.lower()


def _diameter(refs):
    """Onshape's Diameter (MV3): one circle or arc edge, or one cylinder or sphere face. A cone
    face or a plane fails (a cone's circular edge is a circle)."""
    if len(refs) != 1:
        raise MeasureError("Diameter takes one circle, arc, cylinder or sphere, not {} "
                           "references".format(len(refs)))
    obj, sub = refs[0]
    shape = _shape(obj, sub)
    kind = _analytic(shape)
    if kind is not None and kind[0] in ("Circle", "Cylinder", "Sphere"):
        return 2.0 * kind[1]
    raise MeasureError("Diameter takes a circle or arc edge, or a cylinder or sphere face: "
                       "select an entity to measure ({} is {})".format(
                           _show(obj, sub), _describe(shape)))


def _distance(refs, distance_type="Minimum", use_axis=False):
    """(distance, vector from the first reference's point to the second's) of a Distance (MV1).
    Use axis applies to Minimum only: Onshape hides it with Maximum."""
    if len(refs) != 2:
        raise MeasureError("Distance takes two references, not {}".format(len(refs)))
    first, second = (_shape(obj, sub) for obj, sub in refs)
    try:
        if distance_type == "Maximum":
            return _farthest(first, second)
        if use_axis:
            first, second = _axis_form(first), _axis_form(second)
        d, pairs, _info = first.distToShape(second)
        return d, pairs[0][1] - pairs[0][0]
    except MeasureError:
        raise
    except Exception as e:
        raise MeasureError("no distance between {} and {} ({})".format(
            _show(*refs[0]), _show(*refs[1]), e))


# Half the length of the line standing for a cylinder's or a cone's axis (Use axis): the axis is
# infinite in Onshape [R]; a kilometre each way is beyond any part studio here.
_AXIS_HALF = 1.0e6


def _axis_form(shape):
    """Use axis (MV1): a circle, an arc or a sphere becomes its center, a cylinder or a cone its
    axis; anything else stays as it is."""
    import Part

    kind = _analytic(shape)
    if kind is None:
        return shape
    name, _radius, point, axis = kind
    if name in ("Circle", "Sphere"):
        return Part.Vertex(point)
    axis = App.Vector(axis).normalize()
    com = shape.CenterOfMass
    middle = point + axis * (com - point).dot(axis)
    return Part.Edge(Part.LineSegment(middle - axis * _AXIS_HALF, middle + axis * _AXIS_HALF))


# --- Maximum: the farthest points of two vertices, edges or faces. OCC has no maximum distance
# (BRepExtrema is the minimum), and Quick Measure's is approximate. Each shape is split into
# parametrized pieces (a point; an edge's curve on its range; a face's surface on its domain, and
# its boundary edges, since a maximum on a face may lie inside it or on its boundary), sampled, and
# the best sampled pairs are refined by a pattern search on both pieces' parameters until the step
# is below 1e-12 of the range. At a maximum the distance is flat, so the value is exact to far
# below 1e-9 mm wherever the samples land in the maximum's neighbourhood.

_EDGE_SAMPLES = 32
_FACE_SAMPLES = 12  # per parameter direction
_STARTS = 6


def _edge_piece(edge):
    lo, hi = edge.FirstParameter, edge.LastParameter

    def at(x, e=edge):
        try:
            return e.valueAt(x[0])
        except Exception:
            return None
    return (lo,), (hi,), at


def _pieces(shape):
    """[(lows, highs, at)]: `at(params)` is a point of the piece, or None outside its domain."""
    t = shape.ShapeType
    if t == "Vertex":
        point = shape.Point
        return [((), (), lambda x, p=point: p)]
    if t == "Edge":
        return [_edge_piece(shape)]
    if t == "Face":
        pieces = [_edge_piece(e) for e in shape.Edges]
        u0, u1, v0, v1 = shape.ParameterRange

        def at(x, f=shape):
            try:
                if not f.isPartOfDomain(x[0], x[1]):
                    return None
                return f.valueAt(x[0], x[1])
            except Exception:
                return None
        pieces.append(((u0, v0), (u1, v1), at))
        return pieces
    raise MeasureError("Maximum measures vertices, edges and faces, not a {}".format(t.lower()))


def _grid(lows, highs):
    if not lows:
        return [()]
    if len(lows) == 1:
        n = _EDGE_SAMPLES
        return [(lows[0] + (highs[0] - lows[0]) * i / n,) for i in range(n + 1)]
    n = _FACE_SAMPLES
    return [(lows[0] + (highs[0] - lows[0]) * i / n, lows[1] + (highs[1] - lows[1]) * j / n)
            for i in range(n + 1) for j in range(n + 1)]


def _samples(pieces):
    found = []
    for k, (lows, highs, at) in enumerate(pieces):
        for x in _grid(lows, highs):
            p = at(x)
            if p is not None:
                found.append((k, x, p))
    return found


def _refine(piece_a, xa, piece_b, xb):
    """Pattern search on (xa, xb) for the farthest points of the two pieces; returns
    (distance, point a, point b)."""
    lows = list(piece_a[0]) + list(piece_b[0])
    highs = list(piece_a[1]) + list(piece_b[1])
    na = len(piece_a[0])
    x = list(xa) + list(xb)

    def value(params):
        pa = piece_a[2](params[:na])
        pb = piece_b[2](params[na:])
        if pa is None or pb is None:
            return -1.0, pa, pb
        return (pa - pb).Length, pa, pb

    best, pa, pb = value(x)
    steps = [(h - lo) / _EDGE_SAMPLES for lo, h in zip(lows, highs)]
    ends = [(h - lo) * 1e-12 for lo, h in zip(lows, highs)]
    for _ in range(20000):
        if all(s <= e for s, e in zip(steps, ends)):
            break
        moved = False
        for i in range(len(x)):
            for sign in (1.0, -1.0):
                trial = list(x)
                trial[i] = min(highs[i], max(lows[i], x[i] + sign * steps[i]))
                if trial[i] == x[i]:
                    continue
                v, qa, qb = value(trial)
                if v > best:
                    best, pa, pb, x, moved = v, qa, qb, trial, True
                    break
        if not moved:
            steps = [s / 2.0 for s in steps]
    return best, pa, pb


def _farthest(a, b):
    """(maximum distance, vector from a's point to b's) of the shapes `a` and `b`."""
    pieces_a, pieces_b = _pieces(a), _pieces(b)
    samples_a, samples_b = _samples(pieces_a), _samples(pieces_b)
    if not samples_a or not samples_b:
        raise MeasureError("no point to measure from")
    best_of = {}  # (piece of a, piece of b) -> its best sampled pair
    for ka, xa, pa in samples_a:
        for kb, xb, pb in samples_b:
            d = (pa - pb).Length
            key = (ka, kb)
            if key not in best_of or d > best_of[key][0]:
                best_of[key] = (d, xa, xb)
    starts = sorted(best_of.items(), key=lambda item: -item[1][0])[:_STARTS]
    result = None
    for (ka, kb), (_d, xa, xb) in starts:
        d, pa, pb = _refine(pieces_a[ka], xa, pieces_b[kb], xb)
        if result is None or d > result[0]:
            result = (d, pa, pb)
    return result[0], result[2] - result[1]


def variable_name(obj):
    """The name of the VarSet property reading this measurement, else its label."""
    target = obj.Name + ".Value"
    for holder in obj.InList:
        if not holder.isDerivedFrom("App::VarSet"):
            continue
        for prop, expr in holder.ExpressionEngine:
            if expr.replace(" ", "") == target:
                return prop
    return obj.Label


def measurement_of(holder, name):
    """The measurement the variable `name` of the VarSet `holder` reads, or None."""
    for prop, expr in holder.ExpressionEngine:
        if prop != name:
            continue
        target = expr.replace(" ", "")
        if target.endswith(".Value"):
            obj = holder.Document.getObject(target[: -len(".Value")])
            if obj is not None and type(getattr(obj, "Proxy", None)).__name__ == "MeasuredVariable":
                return obj
    return None


def holder_of(m):
    """The VarSet holding the variable that reads the measurement `m`, or None."""
    for holder in m.InList:
        if holder.isDerivedFrom("App::VarSet"):
            for prop, _expr in holder.ExpressionEngine:
                if measurement_of(holder, prop) is m:
                    return holder
    return None


def is_measured_holder(vs):
    """Whether the VarSet `vs` is a measured variable's own holder: every variable it has is a
    measured one (design section 2: one VarSet per measured variable, so that a measurement of a
    feature using another studio variable is no cycle)."""
    if vs.TypeId != "App::VarSet":
        return False
    names = [p for p in vs.PropertiesList if p not in _VARSET_OWN]
    return bool(names) and all(measurement_of(vs, p) is not None for p in names)


# An App::VarSet's own properties (DocumentObject's); every other one is a variable.
# VariablePositions: the Part Studio variables' places in the history (ops#723)
_VARSET_OWN = frozenset(("Label", "Label2", "ExpressionEngine", "Visibility", "VariablePositions"))


def studio_sets(studio):
    """Every VarSet of `studio` (in the App::Part, or at the top level for the implicit studio):
    its own set and the measured variables' holders."""
    if _is_document(studio):
        return [o for o in studio.Objects
                if o.TypeId == "App::VarSet" and o.getParentGeoFeatureGroup() is None
                and not _is_variable_studio(o)]
    return [o for o in studio.Group if o.TypeId == "App::VarSet" and not _is_variable_studio(o)]


def _is_document(studio):
    return isinstance(studio, App.Document)


def _is_variable_studio(obj):
    try:
        return bool(App.DocumentTabs.isVariableStudio(obj))
    except Exception:
        return False


def studio_variables(studio, create=True):
    """The studio's own VarSet, made when missing. A studio is an App::Part, or the document itself
    for the implicit studio (the top level): there the VarSet named, else labelled, "Variables"
    that no part holds, as the Variables panel's Add picks it. Never a copy (App::VarSetCopy) or a
    Variable Studio."""
    if _is_document(studio):
        doc = studio
        candidates = [o for o in doc.Objects
                      if o.TypeId == "App::VarSet" and o.getParentGeoFeatureGroup() is None
                      and not _is_variable_studio(o) and not is_measured_holder(o)]
        for o in candidates:
            if o.Name == "Variables":
                return o
        for o in candidates:
            if o.Label == "Variables":
                return o
        if not create:
            return None
        vs = doc.addObject("App::VarSet", "Variables")
        vs.Label = "Variables"
        return vs
    for o in studio.Group:
        if o.TypeId == "App::VarSet" and not _is_variable_studio(o) and not is_measured_holder(o):
            return o
    if not create:
        return None
    vs = studio.Document.addObject("App::VarSet", "Variables")
    vs.Label = "Variables"
    studio.addObject(vs)
    return vs


def studio_of(obj):
    """The part studio holding `obj`: its App::Part tab object, or its document for the implicit
    studio; None when it is in another kind of tab (an assembly, a Variable Studio)."""
    try:
        name = App.DocumentTabs.tabOf(obj)
    except Exception:
        name = None
    doc = obj.Document
    if name in (None, "", "*"):
        part = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
        while part is not None and not part.isDerivedFrom("App::Part"):
            part = part.getParentGeoFeatureGroup()
        if name in (None, "") and part is not None:
            return part
        return doc
    tab = doc.getObject(name)
    if tab is not None and tab.isDerivedFrom("App::Part"):
        return tab
    return None


# --- picks: a 3D selection resolved to the feature it was picked on (design section 3)

_TOL = 1e-6


def _same_point(a, b):
    return (a - b).Length <= _TOL


def _same_points(a, b):
    """Whether the vertex lists `a` and `b` hold the same points, in any order."""
    if len(a) != len(b):
        return False
    left = [v.Point for v in b]
    for v in a:
        match = next((i for i, p in enumerate(left) if _same_point(v.Point, p)), None)
        if match is None:
            return False
        left.pop(match)
    return True


def _same_box(a, b):
    ba, bb = a.BoundBox, b.BoundBox
    return all(abs(x - y) <= _TOL for x, y in (
        (ba.XMin, bb.XMin), (ba.YMin, bb.YMin), (ba.ZMin, bb.ZMin),
        (ba.XMax, bb.XMax), (ba.YMax, bb.YMax), (ba.ZMax, bb.ZMax)))


def _midpoint(edge):
    return edge.valueAt(edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) / 2)


def _same_geometry(a, b):
    """Whether the subshapes `a` and `b` (one frame) are the same element geometrically, so that a
    measurement of either reads the same."""
    if a.ShapeType != b.ShapeType:
        return False
    if a.ShapeType == "Vertex":
        return _same_point(a.Point, b.Point)
    if a.isSame(b):
        return True
    if not _same_box(a, b) or not _same_points(a.Vertexes, b.Vertexes):
        return False
    if a.ShapeType == "Edge":
        return abs(a.Length - b.Length) <= _TOL and _same_point(_midpoint(a), _midpoint(b))
    if a.ShapeType == "Face":
        size = max(1.0, a.Area)
        return (abs(a.Area - b.Area) <= _TOL * size
                and abs(a.Length - b.Length) <= _TOL * max(1.0, a.Length)
                and _same_point(a.CenterOfMass, b.CenterOfMass))
    return False


def _element_like(obj, picked):
    """The name ("Edge7") of the element of `obj`'s shape that is `picked` geometrically (both in
    the studio's frame), else None."""
    kind = picked.ShapeType
    try:
        whole = _resolve(obj, "")
    except MeasureError:
        return None
    elements = {"Vertex": whole.Vertexes, "Edge": whole.Edges, "Face": whole.Faces}.get(kind, [])
    for i, element in enumerate(elements, 1):
        if _same_geometry(picked, element):
            return "{}{}".format(kind, i)
    return None


def resolve_pick(root, subname, wire_body=False):
    """The reference a 3D pick stands for: (feature, element name), the element named in the
    feature whose shape was picked (the design note's section 3). With `wire_body` (Length), a
    whole object whose shape is edges only (a sketch, a wire) is taken as (object, ""), Onshape's
    wire body.

    `root` and `subname` are a selection's object and subname (a part studio and
    "Body.Pad2.Edge3", or a body and "Edge3"). A PartDesign body's shape is its tip's, so a pick on
    a body names the tip's element. Onshape's variable reads the geometry at its own place in the
    feature list, after every feature that existed when it was made: the picked feature is that
    place. So a later edit of that feature (a pocket moved to trim the edge) changes the value, and
    a feature after it can use the variable; the picked feature itself using it is a cycle,
    refused at once (in Onshape a feature before the variable can't read it).
    Raises MeasureError for a pick that is not a vertex, an edge or a face."""
    owner, _parent, _child, element = root.resolve(subname)
    element = element or ""
    if owner is None:
        raise MeasureError("nothing at {}".format(subname))
    # A link's instance sits where the link places it, its original elsewhere: a reference to
    # the original would measure the wrong place, silently. Refused, loudly.
    try:
        path = root.getSubObjectList(subname)
    except Exception:
        path = []
    for obj in path:
        if obj.hasExtension("App::LinkBaseExtension"):  # Link, LinkElement, LinkGroup, Draft link arrays
            raise MeasureError("{} is picked through the link {}: pick the original".format(
                owner.Label, obj.Label))
    if element:
        # a mapped name (what the selection hands observers when the shape has an element map;
        # it may start with a letter, "g1;..."): its indexed form in the owner's shape
        # (direction 0; 1 would return the mapped form). An indexed name comes back as it is.
        try:
            import Part

            element = Part.getShape(owner).getElementName(element) or element
        except Exception:
            pass
    if wire_body and not element:
        try:
            whole = _resolve(owner, "")
        except MeasureError:
            whole = None
        if whole is not None and is_wire_body(whole):
            return owner, ""
    kind = element.rstrip("0123456789")
    if kind not in ("Vertex", "Edge", "Face") or kind == element:
        raise MeasureError("pick a vertex, an edge or a face, not {}".format(
            owner.Label + ("." + element if element else "")))
    picked = _resolve(owner, element)
    if owner.isDerivedFrom("PartDesign::Body"):
        tip = owner.Tip
        name = _element_like(tip, picked) if tip is not None else None
        if name is None:
            raise MeasureError("{}.{} is not in the body's tip".format(owner.Label, element))
        owner, element = tip, name
    return owner, element


def set_references(m, references):
    """Set what the measurement `m` reads: (object, subelement name) pairs. Edit References only
    through this: ReferenceNames is how a reference dropped by a deleted object is told from one
    removed on purpose."""
    links = {}
    order = []
    for obj, sub in references:
        if obj.Name not in links:
            links[obj.Name] = (obj, [])
            order.append(obj.Name)
        links[obj.Name][1].append(sub)
    m.References = [(links[k][0], links[k][1]) for k in order]
    m.ReferenceNames = [_show(o, s) for o, s in references]


_COUNTS = {"Distance": (2, 2), "Length": (1, None), "Diameter": (1, 1)}


def check_name(studio, name):
    """Why `name` can't be a new measured variable of `studio`, or "" (the Variables panel's
    rules: App.checkVariableName, against the studio's VarSet when it has one)."""
    vs = studio_variables(studio, create=False)
    try:
        reason = App.checkVariableName(name, vs) if vs is not None else App.checkVariableName(name)
    except AttributeError:  # a build without the fork's rules
        reason = "" if name.isidentifier() else "{!r} is not a valid variable name".format(name)
    if not reason:
        for other in studio_sets(studio):
            if name in other.PropertiesList:
                reason = "{} already has a variable named {}".format(_studio_name(studio), name)
                break
    return reason


def _studio_name(studio):
    if _is_document(studio):
        try:
            return App.DocumentTabs.label(studio, "*")
        except Exception:
            return studio.Label
    return studio.Label


def check_references(kind, references):
    """Why `references` can't be measured as `kind` by count, or "" (the values are checked by
    measuring)."""
    low, high = _COUNTS[kind]
    n = len(references)
    if n < low or (high is not None and n > high):
        want = str(low) if low == high else "{} or more".format(low)
        return "{} takes {} reference(s), not {}".format(kind, want, n)
    return ""


def add(studio, name, kind, references, distance_type="Minimum", description="", use_axis=False,
        record="Distance", radius=False):
    """Add the measured variable `name` to the part studio `studio`: an App::Part, or the document
    for the implicit studio (the top level). Never a Variable Studio: it holds no geometry to
    measure (Onshape's MV5).

    `references`: a list of (object, subelement name) pairs, e.g. [(pad, "Edge5")].
    Options (each kind reads its own): `distance_type` "Minimum" or "Maximum", `use_axis` (with
    Minimum), `record` "Distance", "X", "Y" or "Z" (Distance); `radius` (Diameter).
    Returns (holder, measurement): the holder is the variable's own VarSet, in the studio.
    The caller recomputes (and opens the undo transaction).
    """
    implicit = _is_document(studio)
    if studio is not None and not implicit and _is_variable_studio(studio):
        raise ValueError("a Variable Studio holds no geometry to measure: add a measured variable "
                         "in a Part Studio")
    if studio is None or not (implicit or studio.isDerivedFrom("App::Part")):
        raise ValueError("a measured variable belongs to a part studio (an App::Part)")
    if kind not in KINDS:
        raise ValueError("kind must be one of {}".format(", ".join(KINDS)))
    check_options(distance_type, use_axis, record, radius)
    reason = check_references(kind, references)
    if reason:
        raise ValueError(reason)
    if not name.isidentifier():
        raise ValueError("{!r} is not a valid variable name".format(name))
    studio_variables(studio)  # the studio's own set, where the panel lists the variable
    for other in studio_sets(studio):
        if name in other.PropertiesList:
            raise ValueError("{} already has a variable named {}".format(_studio_name(studio), name))

    doc = studio if implicit else studio.Document
    m = doc.addObject("App::FeaturePython", "Measured")
    MeasuredVariable(m)
    m.Label = "Measured " + name
    # Its own holder: FreeCAD's dependencies are per object, so a set shared with other variables
    # would make a measurement of any feature using one of them a cycle.
    holder = doc.addObject("App::VarSet", "MeasuredVariable")
    holder.Label = "{} (measured)".format(name)
    if not implicit:
        # In the studio before the references are set: a link set outside the App::Part and then
        # moved into it lost a reference to a split edge at the next recompute (probe on
        # 5b6ee51f1a, measured variables 2).
        studio.addObject(m)
        studio.addObject(holder)
    m.Kind = kind
    set_options(m, distance_type, use_axis, record, radius)
    set_references(m, references)
    holder.addProperty("App::PropertyLength", name, "",
                       description or "Measured {}".format(kind.lower()))
    holder.setExpression(name, m.Name + ".Value")
    return holder, m
