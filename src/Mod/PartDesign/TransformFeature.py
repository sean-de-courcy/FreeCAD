# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-CH ops#655: Onshape's Transform (move, rotate, copy part) as a studio feature.

The feature is an owner in a studio's history (not in a Body), picking parts by id in StudioScope.
It computes its motion (a placement in the document's frame) into StudioTransform; its steps in the
parts are the studio's FeatureApply steps, which move the part (StudioTransform.cpp) or, with
MakeCopy, make the copies the command made with PartDesign.studioNewPart (notes/transform-design.md).
"""

import FreeCAD
import Part
import PartDesign

V = FreeCAD.Vector

# Onshape's order and default (TR1, Translate by line). The line's separate Scale feature
# (SolidOpsFeatures.py) stays as it is
TYPES = [
    "Translate by line",
    "Translate by distance",
    "Translate by XYZ",
    "Transform by mate connectors",
    "Rotate",
    "Copy in place",
    "Scale",
]
TOL = 1e-7
# Onshape's error codes (TR3, TR5, TR6), kept in the messages
BY_DISTANCE_INPUT = "TRANSFORM_TRANSLATE_BY_DISTANCE_INPUT"
NO_ROTATION_AXIS = "NO_ROTATION_AXIS"
OUT_OF_RANGE = "PARAMETER_OUT_OF_RANGE"


class TransformError(FreeCAD.Base.FreeCADError):
    pass


def _fail(text):
    raise TransformError(text)


def _coded(text, code):
    return text + (f" ({code})" if code else "")


def global_shape(obj, sub, what):
    """The shape of obj's sub (the whole shape for no sub) in the document's frame."""
    if obj is None:
        _fail(f"Select the {what}")
    shape = Part.getShape(obj, sub, needSubElement=bool(sub), transform=True)
    if shape.isNull():
        _fail(f"The {what} has no shape")
    parent = obj.getGlobalPlacement().multiply(obj.Placement.inverse())
    shape = shape.copy()
    shape.transformShape(parent.toMatrix())
    return shape


def picks(link, what, code=None):
    """[(object, shape in the document's frame)]: one per sub, or the object's whole shape."""
    if not link or link[0] is None:
        _fail(_coded(f"Select the {what}", code))
    obj, subs = link
    return [(obj, global_shape(obj, s, what)) for s in (subs or [""])]


def _is_axis_object(obj):
    return obj.TypeId in ("App::Line", "PartDesign::Line")


def _straight(shape):
    """The straight edge a shape is, or None."""
    if shape.Faces or len(shape.Edges) != 1:
        return None
    edge = shape.Edges[0]
    return edge if edge.Curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment") else None


def _edge_ends(edge):
    """The edge's start and end in its own direction (Onshape: the edge's direction, TR2, TR5). An
    unbounded line (an origin axis has no vertices) gives its point and the point one unit along it."""
    if len(edge.Vertexes) < 2:
        start = V(edge.Curve.Location)
        end = start + V(edge.Curve.Direction).normalize()
    else:
        start, end = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    if edge.Orientation == "Reversed":
        start, end = end, start
    return start, end


def _two_vertices(items):
    if len(items) == 2 and all(s.ShapeType == "Vertex" for _, s in items):
        return items[0][1].Point, items[1][1].Point
    return None


def line_of(link, what, code=None):
    """(point, unit direction, length or None) of a line: a straight edge (start to end in its own
    direction), two vertices (first picked to second), or an origin axis or datum line (no
    length)."""
    items = picks(link, what, code)
    ends = _two_vertices(items)
    bounded = True
    if ends is None:
        if len(items) != 1:
            _fail(_coded(f"The {what} must be one edge or two vertices", code))
        obj, shape = items[0]
        edge = _straight(shape)
        if edge is None:
            _fail(_coded(f"The {what} must be a straight edge or an axis", code))
        ends = _edge_ends(edge)
        bounded = not _is_axis_object(obj)
    start, end = ends
    vector = end - start
    if vector.Length < TOL:
        _fail(_coded(f"The {what} has no length", code))
    return start, V(vector).normalize(), vector.Length if bounded else None


def _axis_of_shape(shape):
    """(point, direction) of a circle or arc edge, a cylinder, cone or revolved face, or None."""
    if len(shape.Faces) == 1:
        surface = shape.Faces[0].Surface
        if surface.TypeId in ("Part::GeomCylinder", "Part::GeomCone"):
            return V(surface.Center), V(surface.Axis).normalize()
        if surface.TypeId == "Part::GeomSurfaceOfRevolution":
            return V(surface.Location), V(surface.Direction).normalize()
        return None
    if len(shape.Edges) == 1 and shape.Edges[0].Curve.TypeId == "Part::GeomCircle":
        circle = shape.Edges[0].Curve
        return V(circle.Center), V(circle.Axis).normalize()
    return None


def _frame_z(obj):
    """(origin, Z) of a mate connector (a datum coordinate system), or None."""
    if obj.isDerivedFrom("App::LocalCoordinateSystem") or obj.TypeId == "PartDesign::CoordinateSystem":
        pl = obj.getGlobalPlacement()
        return pl.Base, pl.Rotation.multVec(V(0, 0, 1))
    return None


def direction_of(link, what):
    """A unit direction (TR3): a line, a circle or arc edge, a cylinder, cone or revolved face (its
    axis), a mate connector (its Z), a planar face (its outward normal), or two vertices (first to
    second). Anything else: Onshape's TRANSFORM_TRANSLATE_BY_DISTANCE_INPUT."""
    code = BY_DISTANCE_INPUT
    items = picks(link, what, code)
    if _two_vertices(items):
        return line_of(link, what, code)[1]
    if len(items) == 1:
        obj, shape = items[0]
        frame = _frame_z(obj) if not link[1] else None
        if frame:
            return frame[1]
        if len(shape.Faces) == 1 and shape.Faces[0].Surface.TypeId == "Part::GeomPlane":
            face = shape.Faces[0]
            u0, u1, v0, v1 = face.ParameterRange
            return face.normalAt((u0 + u1) / 2, (v0 + v1) / 2).normalize()
        axis = _axis_of_shape(shape)
        if axis:
            return axis[1]
        if _straight(shape):
            return line_of(link, what, code)[1]
    _fail(f"Select a direction: a line, an axis, a planar face or two vertices ({code})")


def axis_of(link, what):
    """(point, unit direction) of a rotation axis (TR5): a straight edge (its own direction) or
    axis, a circle or arc edge, a cylinder, cone or revolved face, or a mate connector's Z. A planar
    face, a vertex or a sphere: Onshape's NO_ROTATION_AXIS."""
    code = NO_ROTATION_AXIS
    items = picks(link, what, code)
    if len(items) == 1:
        obj, shape = items[0]
        frame = _frame_z(obj) if not link[1] else None
        if frame:
            return frame
        axis = _axis_of_shape(shape)
        if axis:
            return axis
        if _straight(shape):
            point, direction, _ = line_of(link, what, code)
            return point, direction
    _fail(f"Select a rotation axis: an edge, an axis or a cylinder ({code})")


def frame_of(obj, what):
    """A mate connector's frame: a datum coordinate system's global placement (the line has no mate
    connectors yet, decision 352)."""
    if obj is None:
        _fail(f"Select the {what}")
    if _frame_z(obj) is None:
        _fail(f"The {what} must be a coordinate system")
    return obj.getGlobalPlacement()


def point_frame(link, what):
    """(origin, rotation) of Scale's Point or mate connector (TR1): a coordinate system's frame, or
    a vertex or datum point with the world's axes."""
    if not link or link[0] is None:
        _fail(f"Select the {what}")
    obj, subs = link
    if not [s for s in (subs or []) if s] and _frame_z(obj):
        pl = obj.getGlobalPlacement()
        return pl.Base, pl.Rotation
    items = picks(link, what)
    if len(items) == 1:
        shape = items[0][1]
        if len(shape.Vertexes) == 1 and not shape.Edges:
            return shape.Vertexes[0].Point, FreeCAD.Rotation()
    _fail(f"The {what} must be a vertex, a point or a coordinate system")


def scale_matrix(obj):
    """Scale's matrix in the document's frame (TR1): uniform by Scale, or by X/Y/Z along the
    connector's axes (the world's for a point), about the point or connector's origin."""
    origin, rotation = point_frame(obj.ScalePoint, "point or mate connector")
    factors = (obj.Scale,) * 3 if obj.ScaleUniformly else (obj.ScaleX, obj.ScaleY, obj.ScaleZ)
    if any(f <= TOL for f in factors):
        _fail(f"A scale must be more than 0 ({OUT_OF_RANGE})")
    scale = FreeCAD.Matrix()
    scale.scale(V(*factors))
    turn = FreeCAD.Placement(V(), rotation).toMatrix()
    shift = FreeCAD.Placement(origin, FreeCAD.Rotation()).toMatrix()
    return shift * turn * scale * turn.inverse() * shift.inverse()


def motion(obj):
    """The Transform's motion, in the document's frame."""
    kind = obj.TransformType
    sign = -1.0 if obj.OppositeDirection else 1.0
    if kind == "Translate by XYZ":
        return FreeCAD.Placement(V(obj.X.Value, obj.Y.Value, obj.Z.Value), FreeCAD.Rotation())
    if kind == "Translate by line":
        _, direction, length = line_of(obj.Line, "line")
        if length is None:
            _fail("Translate by line needs an edge or two vertices: an axis has no length")
        return FreeCAD.Placement(direction * (sign * length), FreeCAD.Rotation())
    if kind == "Translate by distance":
        direction = direction_of(obj.Direction, "direction")
        if abs(obj.Distance.Value) < TOL:
            _fail(f"The distance must not be 0 ({OUT_OF_RANGE})")
        return FreeCAD.Placement(direction * (sign * obj.Distance.Value), FreeCAD.Rotation())
    if kind == "Rotate":
        point, direction = axis_of(obj.Axis, "axis")
        return FreeCAD.Placement(V(), FreeCAD.Rotation(direction * sign, obj.Angle.Value), point)
    if kind == "Transform by mate connectors":
        source = frame_of(obj.FromConnector, "first mate connector")
        target = frame_of(obj.ToConnector, "second mate connector")
        return target.multiply(source.inverse())
    if kind == "Copy in place":
        if not obj.MakeCopy:
            _fail("Copy in place makes copies, but Copy part is off")
        return FreeCAD.Placement()
    if kind == "Scale":
        return FreeCAD.Placement()  # the scale is StudioScale's (scale_matrix)
    _fail(f"Unknown transform type '{kind}'")


def picked_ids(obj):
    """The parts picked (the scope without the copies the Transform made), in order."""
    made = {record.split("=", 1)[0] for record in obj.StudioCopies}
    return [i for i in obj.StudioScope if i not in made]


class Transform:
    def __init__(self, obj):
        obj.Proxy = self
        self.setupProperties(obj)

    def setupProperties(self, obj):
        def add(kind, name, group, tip, mode=0):
            if name in obj.PropertiesList:
                return False
            obj.addProperty(kind, name, group, tip, mode)
            return True

        new = "TransformType" not in obj.PropertiesList
        add("App::PropertyEnumeration", "TransformType", "Transform", "How the parts move (Onshape's order)")
        if new:
            obj.TransformType = TYPES
            obj.TransformType = "Translate by line"  # Onshape's default (TR1)
        add("App::PropertyLinkSubGlobal", "Line", "Transform", "Translate by line: an edge, or two vertices")
        add("App::PropertyLinkSubGlobal", "Direction", "Transform", "Translate by distance: a line or a planar face")
        add("App::PropertyDistance", "Distance", "Transform", "Translate by distance: how far")
        add("App::PropertyDistance", "X", "Transform", "Translate by XYZ: along the world X")
        add("App::PropertyDistance", "Y", "Transform", "Translate by XYZ: along the world Y")
        add("App::PropertyDistance", "Z", "Transform", "Translate by XYZ: along the world Z")
        add("App::PropertyLinkSubGlobal", "Axis", "Transform", "Rotate: an edge, an axis or a cylinder")
        add("App::PropertyAngle", "Angle", "Transform", "Rotate: the angle")
        if new:
            obj.Angle = 30  # Onshape's default (TR1)
        add("App::PropertyLinkGlobal", "FromConnector", "Transform", "Transform by mate connectors: from")
        add("App::PropertyLinkGlobal", "ToConnector", "Transform", "Transform by mate connectors: to")
        if add("App::PropertyBool", "ScaleUniformly", "Transform", "Scale: one factor (on) or X/Y/Z factors"):
            obj.ScaleUniformly = True  # Onshape's default (TR1)
        for name, tip in (("Scale", "Scale: the factor"), ("ScaleX", "Scale: along the connector's X"),
                          ("ScaleY", "Scale: along the connector's Y"), ("ScaleZ", "Scale: along the connector's Z")):
            if add("App::PropertyFloat", name, "Transform", tip):
                setattr(obj, name, 1.0)
        add("App::PropertyLinkSubGlobal", "ScalePoint", "Transform", "Scale: a point or mate connector")
        add("App::PropertyBool", "OppositeDirection", "Transform", "Flip the direction or the sense")
        add("App::PropertyBool", "MakeCopy", "Transform", "Copy part: new parts, the picked ones stay")
        add("App::PropertyPlacement", "StudioTransform", "Studio", "The motion (output)",
            4 | 8 | 16)  # read-only output, hidden
        add("App::PropertyMatrix", "StudioScale", "Studio", "Scale's matrix, identity otherwise (output)",
            4 | 8 | 16)
        add("App::PropertyStringList", "StudioCopies", "Studio", "'<copy id>=<source id>' per copy made",
            16)

    def onDocumentRestored(self, obj):
        self.setupProperties(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        picked = picked_ids(obj)
        if not picked:
            _fail("Select parts to transform")
        live = {PartDesign.studioPartId(b) for b in live_parts_at(obj)}
        for i in picked:
            if i not in live:
                _fail(f"The part '{i}' is not a part where '{obj.Label}' is in the history")
        placement = motion(obj)
        matrix = scale_matrix(obj) if obj.TransformType == "Scale" else FreeCAD.Matrix()
        if not obj.StudioTransform.isSame(placement, TOL):
            obj.StudioTransform = placement
        if obj.StudioScale != matrix:
            obj.StudioScale = matrix
        obj.Shape = Part.Shape()


# ------------------------------------------------------------------------------------- making it


def studio_of(obj):
    for parent in obj.InList:
        if parent.TypeId == "App::Part":
            return parent
    _fail(f"'{obj.Label}' is in no studio")


def history(obj):
    return PartDesign.studioList(studio_of(obj), True)


def live_parts_at(obj):
    """The parts live just before obj in its studio's history."""
    entries = list(history(obj).Entries)
    index = entries.index(obj) if obj in entries else -1
    return PartDesign.studioLiveParts(obj, index)


def make_transform(parts, name="Transform", copy=False, index=-1, **values):
    """A Transform of the parts (Bodies of one studio), listed at index (-1: at the bar), with
    values set first; with copy, one new part per picked part. No transaction, no recompute."""
    if not parts:
        _fail("Select parts to transform")
    doc = parts[0].Document
    studio = studio_of(parts[0])
    PartDesign.studioList(studio, True)
    obj = doc.addObject("PartDesign::FeaturePython", name)
    Transform(obj)
    studio.addObject(obj)
    for key, value in values.items():
        setattr(obj, key, value)
    obj.StudioScope = [PartDesign.studioPartId(p) for p in parts]
    PartDesign.studioInsert(obj, index)
    if copy or obj.TransformType == "Copy in place":
        set_copy(obj, True)
    return obj


def made_parts(obj):
    return [
        b for b in obj.Document.Objects
        if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == obj
    ]


def set_copy(obj, copy):
    """Copy part on (one new part per picked part, made here, never by a recompute) or off (the
    copies go)."""
    if copy:
        obj.MakeCopy = True
        sources = {r.split("=", 1)[1] for r in obj.StudioCopies}
        for source in picked_ids(obj):
            if source not in sources:
                body = PartDesign.studioNewPart(obj)
                obj.StudioCopies = obj.StudioCopies + [f"{PartDesign.studioPartId(body)}={source}"]
        PartDesign.studioReconcile(history(obj))
        return
    obj.MakeCopy = False
    remove_copies(obj, made_parts(obj))


def set_parts(obj, parts):
    """The picked parts; the copies follow (a new one for a newly picked part with Copy part on, a
    copy goes with its unpicked source)."""
    ids = [PartDesign.studioPartId(p) for p in parts]
    unpicked = {r.split("=", 1)[0] for r in obj.StudioCopies if r.split("=", 1)[1] not in ids}
    remove_copies(obj, [b for b in made_parts(obj) if PartDesign.studioPartId(b) in unpicked])
    copies = [r.split("=", 1)[0] for r in obj.StudioCopies]
    PartDesign.studioSetScopeIds(obj, ids + copies)
    if obj.MakeCopy:
        set_copy(obj, True)


def remove_copies(obj, bodies):
    """Deletes copies the Transform made, with what they hold, and reconciles."""
    doc = obj.Document
    gone = {PartDesign.studioPartId(b) for b in bodies}
    obj.StudioCopies = [r for r in obj.StudioCopies if r.split("=", 1)[0] not in gone]
    PartDesign.studioSetScopeIds(obj, [i for i in obj.StudioScope if i not in gone])
    for body in bodies:
        body.removeObjectsFromDocument()
        doc.removeObject(body.Name)
    PartDesign.studioReconcile(history(obj))
