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
_VARSET_OWN = frozenset(("Label", "Label2", "ExpressionEngine", "Visibility"))


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


# --- picks: a 3D selection resolved to the feature that made the element (design section 2)

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


def _same_body(a, b):
    return a.getParentGeoFeatureGroup() == b.getParentGeoFeatureGroup()


def resolve_pick(root, subname):
    """The reference a 3D pick stands for: (feature, element name), the element named in the
    feature that made it (the design note's section 2).

    `root` and `subname` are a selection's object and subname (a part studio and
    "Body.Pad2.Edge3", or a body and "Edge3"). A PartDesign body's shape is its tip's. From the
    feature whose shape was picked, the pick walks back along the body's BaseFeature chain while
    the earlier feature still has an element of the same geometry, and names the element in the
    earliest one. An edge that later features left alone is read from the feature that made it,
    so a feature in between can use the variable without a cycle; an edge a later feature changed
    (trimmed, split) stays on the feature that changed it, so the value is the one picked.
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
        if obj.isDerivedFrom("App::Link") or obj.isDerivedFrom("App::LinkElement") \
                or obj.isDerivedFrom("App::LinkGroup"):
            raise MeasureError("{} is picked through the link {}: pick the original".format(
                owner.Label, obj.Label))
    if element and not element[0].isalpha():
        # a mapped name: its indexed form in the owner's shape
        try:
            import Part

            element = Part.getShape(owner).getElementName(element, 1) or element
        except Exception:
            pass
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
    feature = owner
    seen = {feature.Name}
    while feature.isDerivedFrom("PartDesign::Feature"):
        base = getattr(feature, "BaseFeature", None)
        if (base is None or base.Name in seen or not base.isDerivedFrom("PartDesign::Feature")
                or not _same_body(base, feature)):
            break
        seen.add(base.Name)
        name = _element_like(base, picked)
        if name is None:
            break
        feature, element = base, name
    return feature, element


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


def add(studio, name, kind, references, distance_type="Minimum", description=""):
    """Add the measured variable `name` to the part studio `studio`: an App::Part, or the document
    for the implicit studio (the top level).

    `references`: a list of (object, subelement name) pairs, e.g. [(pad, "Edge5")].
    Returns (holder, measurement): the holder is the variable's own VarSet, in the studio.
    The caller recomputes (and opens the undo transaction).
    """
    implicit = _is_document(studio)
    if studio is None or not (implicit or studio.isDerivedFrom("App::Part")):
        raise ValueError("a measured variable belongs to a part studio (an App::Part)")
    if kind not in KINDS:
        raise ValueError("kind must be one of {}".format(", ".join(KINDS)))
    if distance_type not in DISTANCE_TYPES:
        raise ValueError("distance type must be one of {}".format(", ".join(DISTANCE_TYPES)))
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
    m.DistanceType = distance_type
    set_references(m, references)
    holder.addProperty("App::PropertyLength", name, "",
                       description or "Measured {}".format(kind.lower()))
    holder.setExpression(name, m.Name + ".Value")
    return holder, m
