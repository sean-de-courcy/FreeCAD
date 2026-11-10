# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (lane solid-ops): Thicken, Scale and Offset surface as PartDesign Body features.
#
# Python proxies on PartDesign::FeatureAdditivePython (Thicken: Union / Subtraction / Common) and
# PartDesign::FeaturePython (Scale, Offset surface). Element names hold: Thicken and Offset
# surface go through TopoShape.makeOffsetShape (mapped names, op OFS); Scale re-maps the
# transformed shape's elements onto the source's names (TopoShape.mapShapes).
#
# New / Add / Remove: a Thicken is a New part when the Body has nothing before it, an Add
# (Union) or a Remove (Subtraction) otherwise; the command moves a New one into a new part with
# PartDesign.newPartFrom, as a native Pad's dialog does.

import FreeCAD as App
import Part

TOL = 1e-6
SCALE_MIN, SCALE_MAX = 1e-5, 1e5  # Onshape's range


class SolidOpsError(Exception):
    """A loud failure: the feature goes Invalid with this text (Onshape shows an error)."""


# ---------------------------------------------------------------- helpers


def _resolve_faces(obj):
    """The faces (Part.Face) and surfaces the Base links name, in global coordinates."""
    faces = []
    for link, subs in obj.Base or []:
        if link is None:
            continue
        names = [s for s in subs if s]
        if not names:
            # A whole sheet or face body: take its faces
            shape = Part.getShape(link)
            if shape.isNull():
                continue
            faces.extend(shape.Faces)
            continue
        for sub in names:
            shape = Part.getShape(link, sub, needSubElement=True)
            if shape.isNull() or shape.ShapeType != "Face":
                raise SolidOpsError(
                    "%s.%s is not a face" % (link.Label, sub)
                )
            faces.append(shape)
    if not faces:
        raise SolidOpsError("Select a face or surface")
    return faces


def _components(faces):
    """Group faces that share an edge (connected pieces of surface)."""
    groups = []
    for f in faces:
        touching = [g for g in groups if any(_share_edge(f, h) for h in g)]
        merged = [f]
        for g in touching:
            merged.extend(g)
            groups.remove(g)
        groups.append(merged)
    return groups


def _share_edge(a, b):
    for ea in a.Edges:
        for eb in b.Edges:
            if ea.isSame(eb):
                return True
    return False


def _as_surface(group):
    if len(group) == 1:
        return group[0]
    shell = Part.Shell(group)
    return shell


def _check_offset(src, res, what):
    if res.isNull():
        raise SolidOpsError("%s failed: no result" % what)
    if not res.isValid():
        raise SolidOpsError("%s failed: the result is not valid (it folds over itself)" % what)
    if len(res.Faces) < len(src.Faces):
        raise SolidOpsError(
            "%s failed: %d of %d faces collapsed" % (what, len(src.Faces) - len(res.Faces), len(src.Faces))
        )


def thicken_tool(faces, t1, t2):
    """Solid thickened from the faces: t1 along each face's normal, t2 against it."""
    if t1 < 0 or t2 < 0:
        raise SolidOpsError("Thickness must not be negative")
    if t1 + t2 <= TOL:
        raise SolidOpsError("Thickness is zero")
    pieces = []
    for group in _components(faces):
        surf = _as_surface(group)
        try:
            start = surf.makeOffsetShape(-t2, TOL) if t2 > TOL else surf
            solid = start.makeOffsetShape(t1 + t2, TOL, False, False, 0, 0, True)
        except Part.OCCError as e:
            raise SolidOpsError("Thicken failed: %s" % e)
        except Exception as e:
            raise SolidOpsError("Thicken failed: %s" % e)
        _check_offset(surf, solid, "Thicken")
        if solid.ShapeType != "Solid" and not solid.Solids:
            raise SolidOpsError("Thicken failed: the result has no solid")
        if solid.Volume <= TOL:
            raise SolidOpsError("Thicken failed: the result has no volume")
        pieces.append(solid)
    tool = pieces[0]
    if len(pieces) > 1:
        tool = pieces[0].fuse(pieces[1:])
    return tool


def offset_surface(faces, distance):
    """Sheets offset along the face normals; adjacent faces become one sheet, extended to meet
    (a sharp edge, as Onshape); zero is a copy."""
    out = []
    for group in _components(faces):
        surf = _as_surface(group)
        if abs(distance) <= TOL:
            out.append(surf.copy())
            continue
        try:
            res = surf.makeOffsetShape(distance, TOL, False, False, 0, 2 if len(group) > 1 else 0)  # join: intersection
        except Exception as e:
            raise SolidOpsError("Offset surface failed: %s" % e)
        _check_offset(surf, res, "Offset surface")
        if res.Area <= TOL:
            raise SolidOpsError("Offset surface failed: the result has no area")
        out.append(res)
    if len(out) == 1:
        return out[0]
    return Part.makeCompound(out)


def scale_matrix(point, sx, sy, sz):
    return App.Matrix(
        sx, 0, 0, (1 - sx) * point.x,
        0, sy, 0, (1 - sy) * point.y,
        0, 0, sz, (1 - sz) * point.z,
        0, 0, 0, 1,
    )


def scale_shape(shape, point, sx, sy, sz):
    """Scale about point, keeping the source's element names (mapShapes by index)."""
    res = shape.copy()
    res.transformShape(scale_matrix(point, sx, sy, sz), False, True)
    pairs = []
    for kind, prefix in (("Faces", "Face"), ("Edges", "Edge"), ("Vertexes", "Vertex")):
        for i in range(len(getattr(shape, kind))):
            name = "%s%d" % (prefix, i + 1)
            pairs.append((shape.getElement(name), res.getElement(name)))
    mapped = res.copy()
    try:
        mapped.mapShapes([], pairs, "SCL")
    except Exception:
        return res
    return mapped if len(mapped.ElementMap) else res


def _base_shape(obj):
    base = obj.BaseFeature
    if base is None:
        return None
    shape = base.Shape
    if shape is None or shape.isNull():
        return None
    return shape


# ---------------------------------------------------------------- proxies


class _Proxy:
    def __init__(self, obj):
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def onDocumentRestored(self, obj):
        pass


class Thicken(_Proxy):
    """Thicken faces or surfaces into a solid, on one or both sides; New / Add / Remove."""

    def __init__(self, obj):
        super().__init__(obj)
        obj.Operation = ["Union", "Subtraction", "Common"]
        obj.Operation = "Union"
        obj.addProperty("App::PropertyLinkSubList", "Base", "Thicken", "Faces or surfaces to thicken")
        obj.addProperty("App::PropertyLength", "Thickness1", "Thicken", "Thickness along the face normal")
        obj.addProperty("App::PropertyLength", "Thickness2", "Thicken", "Thickness against the face normal")
        obj.addProperty("App::PropertyBool", "Flip", "Thicken", "Opposite direction: Thickness 1 against the face normal")
        obj.addProperty("App::PropertyBool", "Midplane", "Thicken", "Thicken on both sides, half of Thickness each")
        obj.addProperty("App::PropertyLength", "Thickness", "Thicken", "Total thickness for Midplane")
        obj.Thickness1 = 5.0  # Onshape's defaults
        obj.Thickness2 = 0.0
        obj.Thickness = 5.0

    def execute(self, obj):
        faces = _resolve_faces(obj)
        if obj.Midplane:
            t1 = t2 = obj.Thickness.Value / 2
        elif obj.Flip:
            t1, t2 = obj.Thickness2.Value, obj.Thickness1.Value
        else:
            t1, t2 = obj.Thickness1.Value, obj.Thickness2.Value
        tool = thicken_tool(faces, t1, t2)
        obj.AddSubShape = tool
        base = _base_shape(obj)
        op = obj.Operation
        if base is None:
            if op != "Union":
                raise SolidOpsError(
                    "No merge scope selected. Nothing to %s: a Remove needs a part before it"
                    % ("cut" if op == "Subtraction" else "intersect")
                )
            obj.Shape = tool
            return
        if op == "Union":
            res = base.fuse(tool)
        elif op == "Subtraction":
            res = base.cut(tool)
        else:
            res = base.common(tool)
        if res.isNull() or not res.Solids:
            raise SolidOpsError("The result has no solid")
        if obj.Refine and op != "Common":
            res = res.removeSplitter()
        obj.Shape = res


class Scale(_Proxy):
    """Scale the part before it about a point: uniform or per axis."""

    def __init__(self, obj):
        super().__init__(obj)
        obj.addProperty("App::PropertyBool", "Uniform", "Scale", "One factor for all axes")
        obj.addProperty("App::PropertyFloat", "Factor", "Scale", "Scale factor")
        obj.addProperty("App::PropertyFloat", "FactorX", "Scale", "Scale factor along X")
        obj.addProperty("App::PropertyFloat", "FactorY", "Scale", "Scale factor along Y")
        obj.addProperty("App::PropertyFloat", "FactorZ", "Scale", "Scale factor along Z")
        obj.addProperty("App::PropertyVector", "Point", "Scale", "Scale about this point")
        obj.Uniform = True
        obj.Factor = obj.FactorX = obj.FactorY = obj.FactorZ = 1.0

    def execute(self, obj):
        base = _base_shape(obj)
        if base is None:
            raise SolidOpsError("Nothing to scale: Scale needs a part before it in its Body")
        if obj.Uniform:
            sx = sy = sz = obj.Factor
        else:
            sx, sy, sz = obj.FactorX, obj.FactorY, obj.FactorZ
        if min(sx, sy, sz) < SCALE_MIN or max(sx, sy, sz) > SCALE_MAX:
            raise SolidOpsError("Scale factor must be between %g and %g" % (SCALE_MIN, SCALE_MAX))
        obj.Shape = scale_shape(base, obj.Point, sx, sy, sz)


class OffsetSurface(_Proxy):
    """Offset faces or surfaces by a distance (a sheet; the faces keep their connections)."""

    def __init__(self, obj):
        super().__init__(obj)
        obj.addProperty("App::PropertyLinkSubList", "Base", "Offset", "Faces or surfaces to offset")
        obj.addProperty("App::PropertyDistance", "Distance", "Offset", "Offset along the face normal")
        obj.addProperty("App::PropertyBool", "Flip", "Offset", "Offset against the face normal")
        obj.Distance = 5.0  # Onshape's default

    def execute(self, obj):
        faces = _resolve_faces(obj)
        if obj.Distance.Value < 0:
            raise SolidOpsError("Offset distance must not be negative: use Flip to offset the other way")
        d = obj.Distance.Value * (-1 if obj.Flip else 1)
        obj.Shape = offset_surface(faces, d)


# ---------------------------------------------------------------- creation (no GUI)


def make_thicken(body, base_links, t1=5.0, t2=0.0, operation="Union", name="Thicken"):
    obj = body.Document.addObject("PartDesign::FeatureAdditivePython", name)
    Thicken(obj)
    obj.Base = base_links
    obj.Thickness1 = t1
    obj.Thickness2 = t2
    obj.Operation = operation
    body.addObject(obj)
    return obj


def make_scale(body, point=None, factor=1.0, factors=None, name="Scale"):
    obj = body.Document.addObject("PartDesign::FeaturePython", name)
    Scale(obj)
    obj.Point = point or App.Vector()
    if factors is None:
        obj.Uniform = True
        obj.Factor = factor
    else:
        obj.Uniform = False
        obj.FactorX, obj.FactorY, obj.FactorZ = factors
    body.addObject(obj)
    return obj


def make_offset_surface(body, base_links, distance=5.0, flip=False, name="OffsetSurface"):
    obj = body.Document.addObject("PartDesign::FeaturePython", name)
    OffsetSurface(obj)
    obj.Base = base_links
    obj.Distance = distance
    obj.Flip = flip
    body.addObject(obj)
    return obj
