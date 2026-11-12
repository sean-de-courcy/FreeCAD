# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, notes/measured-variables-design.md in the ops repo)

"""Measured variables: Onshape's Variable feature in the `MEASURED` mode.

A measured variable is an ordinary property of a part studio's VarSet (an App::VarSet held by an
App::Part) whose expression reads `<measurement>.Value`. The measurement is an App::FeaturePython
with a `MeasuredVariable` proxy, in the same studio. It re-reads the geometry on every recompute,
and a lost reference raises an error naming it; FreeCAD then marks the VarSet and every feature
using the variable as failed ("'<measurement>' has an error").

Kinds:
- Distance: two references (vertex, edge or face); Minimum by default (BRepExtrema), or Center
  (Quick Measure's center: a circle's or sphere's center, else the center of mass).
- Length: one or more edges, summed.
- Diameter: one circle or arc edge, or one cylindrical face.

Readings marked [R] are the most Onshape-like reading, kept until the Onshape oracle answers
(the design note's section 6).
"""

import FreeCAD as App

FORMAT = 1
# Saved by index: append only.
KINDS = ["Distance", "Length", "Diameter"]
DISTANCE_TYPES = ["Minimum", "Center"]

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
        add("App::PropertyEnumeration", "DistanceType", "Distance only: Minimum, or between centers")
        add("App::PropertyLinkSubList", "References", "The measured vertices, edges or faces")
        add("App::PropertyLength", "Value", "The measured value", _READ_ONLY_OUTPUT)
        add("App::PropertyStringList", "ReferenceNames",
            "The references as last measured, to name a lost one", _READ_ONLY_OUTPUT | 4)
        if not obj.Kind or obj.Kind not in KINDS:
            obj.Kind = KINDS
        if not obj.DistanceType or obj.DistanceType not in DISTANCE_TYPES:
            obj.DistanceType = DISTANCE_TYPES
        if obj.Format == 0:
            obj.Format = FORMAT

    def onDocumentRestored(self, obj):
        self.setup(obj)
        if obj.Format > FORMAT:
            App.Console.PrintWarning(
                "{}: made by a newer build (measured variable format {}); it may not measure as "
                "intended\n".format(obj.Label, obj.Format))

    def execute(self, obj):
        refs = _references(obj)
        try:
            value = measure(obj.Kind, refs, obj.DistanceType)
        except MeasureError as e:
            raise MeasureError("Measured variable '{}': {}".format(variable_name(obj), e)) from None
        obj.ReferenceNames = [_show(o, sub) for o, sub in refs]
        obj.Value = value

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


def _resolve(obj, sub):
    """The shape of one reference in the coordinates of its top parent (the studio's frame, so two
    references in differently placed bodies compare right), or raise MeasureError."""
    import Part

    root, path = obj, sub
    try:
        parents = obj.getParents()
        if parents:
            root, prefix = parents[0]
            path = prefix + sub
    except Exception:
        pass
    try:
        shape = Part.getShape(root, path, needSubElement=True)
    except Exception:
        shape = None
    if shape is None or shape.isNull():
        raise MeasureError("lost reference {}".format(_show(obj, sub)))
    return shape


def measure(kind, refs, distance_type="Minimum"):
    """The measured value in mm of `refs`, a list of (object, subelement) pairs."""
    if kind == "Length":
        return _length(refs)
    if kind == "Diameter":
        return _diameter(refs)
    if kind == "Distance":
        return _distance(refs, distance_type)
    raise MeasureError("unknown kind {!r}".format(kind))


def _shape(obj, sub):
    if obj is None:
        raise MeasureError("lost reference (the measured object was deleted)")
    return _resolve(obj, sub)


def _length(refs):
    if not refs:
        raise MeasureError("Length needs one or more edges")
    total = 0.0
    for obj, sub in refs:
        shape = _shape(obj, sub)
        if shape.ShapeType != "Edge":
            raise MeasureError("Length takes edges; {} is a {}".format(
                _show(obj, sub), shape.ShapeType.lower()))
        total += shape.Length
    return total


def _diameter(refs):
    import Part

    if len(refs) != 1:
        raise MeasureError("Diameter takes one circle, arc or cylindrical face, not {}".format(len(refs)))
    obj, sub = refs[0]
    shape = _shape(obj, sub)
    if shape.ShapeType == "Edge" and isinstance(shape.Curve, Part.Circle):
        return 2.0 * shape.Curve.Radius
    if shape.ShapeType == "Face" and isinstance(shape.Surface, Part.Cylinder):
        return 2.0 * shape.Surface.Radius
    raise MeasureError("Diameter takes a circle, arc or cylindrical face; {} is not one".format(
        _show(obj, sub)))


def _distance(refs, distance_type):
    if len(refs) != 2:
        raise MeasureError("Distance takes two references, not {}".format(len(refs)))
    first, second = (_shape(obj, sub) for obj, sub in refs)
    if distance_type == "Center":
        return (_center(first) - _center(second)).Length
    try:
        return first.distToShape(second)[0]
    except Exception as e:
        raise MeasureError("no distance between {} and {} ({})".format(
            _show(*refs[0]), _show(*refs[1]), e))


def _center(shape):
    """Quick Measure's center (notes/measure-design.md): a vertex's point, a circle's or a sphere's
    center, else the center of mass."""
    import Part

    if shape.ShapeType == "Vertex":
        return shape.Point
    if shape.ShapeType == "Edge" and isinstance(shape.Curve, Part.Circle):
        return shape.Curve.Center
    if shape.ShapeType == "Face" and isinstance(shape.Surface, Part.Sphere):
        return shape.Surface.Center
    return shape.CenterOfMass


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


def studio_variables(studio, create=True):
    """The studio's own VarSet (directly in the App::Part, not a copy); made when missing."""
    for o in studio.Group:
        if o.TypeId == "App::VarSet":
            return o
    if not create:
        return None
    vs = studio.Document.addObject("App::VarSet", "Variables")
    vs.Label = "Variables"
    studio.addObject(vs)
    return vs


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


def add(studio, name, kind, references, distance_type="Minimum"):
    """Add the measured variable `name` to the part studio `studio` (an App::Part).

    `references`: a list of (object, subelement name) pairs, e.g. [(pad, "Edge5")].
    Returns (varset, measurement). The caller recomputes (and opens the undo transaction).
    """
    if studio is None or not studio.isDerivedFrom("App::Part"):
        raise ValueError("a measured variable belongs to a part studio (an App::Part)")
    if kind not in KINDS:
        raise ValueError("kind must be one of {}".format(", ".join(KINDS)))
    if distance_type not in DISTANCE_TYPES:
        raise ValueError("distance type must be one of {}".format(", ".join(DISTANCE_TYPES)))
    low, high = _COUNTS[kind]
    n = len(references)
    if n < low or (high is not None and n > high):
        want = str(low) if low == high else "{} or more".format(low)
        raise ValueError("{} takes {} reference(s), not {}".format(kind, want, n))
    if not name.isidentifier():
        raise ValueError("{!r} is not a valid variable name".format(name))
    vs = studio_variables(studio)
    if name in vs.PropertiesList:
        raise ValueError("{} already has a variable named {}".format(vs.Label, name))

    doc = studio.Document
    m = doc.addObject("App::FeaturePython", "Measured")
    MeasuredVariable(m)
    m.Label = "Measured " + name
    m.Kind = kind
    m.DistanceType = distance_type
    set_references(m, references)
    studio.addObject(m)
    vs.addProperty("App::PropertyLength", name, "", "Measured {}".format(kind.lower()))
    vs.setExpression(name, m.Name + ".Value")
    return vs, m
