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

import math

import FreeCAD as App
import Part

TOL = 1e-6
SCALE_MIN, SCALE_MAX = 1e-5, 1e5  # Onshape's range


class SolidOpsError(Exception):
    """A loud failure: the feature goes Invalid with this text (Onshape shows an error)."""


# ---------------------------------------------------------------- helpers


def _container_placement(obj):
    """The global placement of the Body (or other group) that holds obj; identity if none."""
    group = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
    return group.getGlobalPlacement() if group is not None else App.Placement()


def _resolve_faces(obj):
    """The faces (Part.Face) and surfaces the Base links name, in the coordinates of obj's Body.

    Part.getShape puts a face in its own Body's frame; a face of another Body moves by the two Bodies'
    placements, so the result lies where the face is (Onshape has no Body placement: SO3)."""
    to_here = _container_placement(obj).inverse()
    faces = []
    for link, subs in obj.Base or []:
        if link is None:
            continue
        move = to_here.multiply(_container_placement(link))
        names = [s for s in subs if s]
        if not names:
            # A whole sheet or face body: take its faces
            shape = Part.getShape(link)
            if shape.isNull():
                continue
            found = shape.Faces
        else:
            found = []
            for sub in names:
                shape = Part.getShape(link, sub, needSubElement=True)
                if shape.isNull() or shape.ShapeType != "Face":
                    raise SolidOpsError(
                        "%s.%s is not a face" % (link.Label, sub)
                    )
                found.append(shape)
        if not move.isIdentity():
            for f in found:
                f.Placement = move.multiply(f.Placement)
        faces.extend(found)
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


def _revolved_circle(face):
    """A face on a surface of revolution whose meridian is a circle (a bent tube's bend): its frame,
    or None. The face must be the whole (u, v) patch of its surface (u the revolution angle)."""
    surf = face.Surface
    kind = surf.__class__.__name__
    if kind == "Toroid":
        base, axis = surf.Center, surf.Axis
    elif kind == "SurfaceOfRevolution":
        base, axis = surf.Location, surf.Direction
    else:
        return None
    u0, u1, v0, v1 = face.ParameterRange
    if u1 - u0 <= TOL:
        return None
    try:
        merid = surf.uIso(u0)
        patch = surf.toShape(u0, u1, v0, v1)
    except Exception:
        return None
    circ = merid.Circle if isinstance(merid, Part.ArcOfCircle) else merid
    if not isinstance(circ, Part.Circle):
        return None
    if abs(patch.Area - face.Area) > 1e-6 * max(1.0, face.Area):
        return None  # trimmed inside its patch: not a plain bend
    axis = App.Vector(axis).normalize()
    centre = circ.Center
    foot = base + axis * (centre - base).dot(axis)
    out = centre - foot
    d = out.Length
    if d <= TOL or abs(circ.Axis.dot(out)) > 1e-7 * d or abs(circ.Axis.dot(axis)) > 1e-7:
        return None  # the meridian circle does not lie in a plane through the axis
    # the axis must turn u0's meridian toward u1's: a Reversed face's torus can be parametrised the other
    # way round (Axis -y for a sweep about +y), and the ring revolved about it would be mirrored (review r3)
    vs = max((v0 + (v1 - v0) * k / 8.0 for k in range(9)),
             key=lambda v: _axis_distance(surf.value(u0, v), base, axis))
    du = min(0.1, 0.5 * (u1 - u0))
    p0, p1 = surf.value(u0, vs) - foot, surf.value(u0 + du, vs)
    ahead = lambda s: (foot + App.Rotation(axis * s, math.degrees(du)).multVec(p0) - p1).Length
    if ahead(-1.0) < ahead(1.0):
        axis = -axis
    elif not ahead(1.0) <= 1e-6 * max(1.0, d + circ.Radius):
        return None  # u is not the revolution angle about this axis
    # sample the face where it is farthest from the axis: a horn torus has no normal at its apex
    um = 0.5 * (u0 + u1)
    vm = max((v0 + (v1 - v0) * k / 8.0 for k in range(1, 8)),
             key=lambda v: _axis_distance(face.valueAt(um, v), base, axis))
    p, n = face.valueAt(um, vm), face.normalAt(um, vm)
    radial = p - surf.uIso(um).Center
    return {
        "circle": circ, "u0": u0, "u1": u1, "v0": v0, "v1": v1, "full": v1 - v0 >= 2 * math.pi - 1e-9,
        "axis": axis, "foot": foot, "out": out.normalize(), "d": d, "r": circ.Radius,
        "outward": n.dot(radial) > 0,  # the face normal points away from the meridian circle's centre
        "mid": p,
    }


def _axis_distance(p, base, axis):
    q = p - base
    return (q - axis * q.dot(axis)).Length


def _bend_radii(info, t1, t2):
    """The thick ring's inner and outer radius about the meridian circle's centre."""
    t_out, t_in = (t1, t2) if info["outward"] else (t2, t1)
    return info["r"] - t_in, info["r"] + t_out


def _reaches_axis(info, t1, t2):
    return _bend_radii(info, t1, t2)[1] >= info["d"] - TOL


def _bend_solids(face, info, t1, t2):
    """The bend thickened: the ring between the two radii in the meridian plane at u0, revolved
    through the face's angle. Where the ring crosses the axis, its two sides are revolved apart (each is
    a valid revolve; the whole ring would fold over itself): their union is the swept ring, filled up to
    the axis (Onshape TK1-TK4)."""
    r_in, r_out = _bend_radii(info, t1, t2)
    if r_in < -TOL:
        raise SolidOpsError("Thicken failed: the thickness toward the bend's centre exceeds its radius")
    circ = info["circle"]

    def arc(radius):
        c = circ.copy()
        c.Radius = radius
        return c if info["full"] else Part.ArcOfCircle(c, info["v0"], info["v1"])

    if info["full"]:
        ring = Part.Face(Part.Wire(arc(r_out).toShape()))
        if r_in > TOL:
            ring = ring.cut(Part.Face(Part.Wire(arc(r_in).toShape()))).Faces[0]
    else:
        outer = arc(r_out).toShape()
        if r_in > TOL:
            inner = arc(r_in).toShape()
            ends = [Part.LineSegment(inner.Vertexes[0].Point, outer.Vertexes[0].Point).toShape(),
                    Part.LineSegment(inner.Vertexes[-1].Point, outer.Vertexes[-1].Point).toShape()]
            ring = Part.Face(Part.Wire(Part.__sortEdges__([outer, inner] + ends)))
        else:
            c = circ.Center
            ends = [Part.LineSegment(c, outer.Vertexes[0].Point).toShape(),
                    Part.LineSegment(c, outer.Vertexes[-1].Point).toShape()]
            ring = Part.Face(Part.Wire(Part.__sortEdges__([outer] + ends)))
    regions = [ring]
    if r_out > info["d"] - TOL:
        # split at the axis: a rectangle in the meridian plane on each side of it
        size = 2.0 * (info["d"] + r_out) + 1.0
        a, foot = info["axis"], info["foot"]
        regions = []
        for e in (info["out"], -info["out"]):
            pts = [foot - a * size, foot + a * size, foot + a * size + e * size, foot - a * size + e * size]
            part = ring.common(Part.Face(Part.makePolygon(pts + [pts[0]])))
            regions.extend(f for f in part.Faces if f.Area > TOL)
        if not regions:
            raise SolidOpsError("Thicken failed: the bend could not be thickened")
    angle = math.degrees(info["u1"] - info["u0"])
    half = App.Rotation(info["axis"], 0.5 * angle)
    solids, probes = [], []
    for region in regions:
        solid = region.revolve(info["foot"], info["axis"], angle)
        # each region lies on one side of the axis, so its sweep's volume is exact (Pappus): OCC's revolve
        # of a region touching an oblique axis gave a valid wrong solid (654.0505 for 461.4811, review r4)
        exact = math.radians(angle) * region.Area * _axis_distance(region.CenterOfMass, info["foot"], info["axis"])
        if not solid.isValid() or solid.Volume <= TOL or abs(solid.Volume - exact) > 1e-6 * max(1.0, exact):
            raise SolidOpsError("Thicken failed: the bend could not be thickened")
        solids.append(solid)
        # points inside the piece: the region's inner points, turned through half the angle
        probes.extend(info["foot"] + half.multVec(q - info["foot"]) for q in _inner_points(region))
    if not any(s.isInside(info["mid"], 1e-5, True) for s in solids):
        raise SolidOpsError("Thicken failed: the bend could not be thickened")
    return solids, probes


def _inner_points(face, offset=0.0):
    """Points of the face's interior on a 3 x 3 parameter grid, moved by offset along its normal."""
    u0, u1, v0, v1 = face.ParameterRange
    pts = []
    for a in (0.25, 0.5, 0.75):
        for b in (0.25, 0.5, 0.75):
            u, v = u0 + a * (u1 - u0), v0 + b * (v1 - v0)
            if not face.isPartOfDomain(u, v):
                continue
            try:
                pts.append(face.valueAt(u, v) + face.normalAt(u, v) * offset)
            except Exception:
                continue  # no normal there (a horn's apex)
    return pts


def _tangent_joins(group):
    """True when every edge two faces of the group share is smooth (the normals agree along it)."""
    for i, a in enumerate(group):
        for b in group[i + 1:]:
            for ea in a.Edges:
                if not any(ea.isSame(eb) for eb in b.Edges):
                    continue
                p0, p1 = ea.ParameterRange
                for k in (0.1, 0.5, 0.9):
                    p = ea.valueAt(p0 + k * (p1 - p0))
                    na = a.normalAt(*a.Surface.parameter(p))
                    nb = b.normalAt(*b.Surface.parameter(p))
                    if na.dot(nb) < 1.0 - 1e-6:
                        return False
    return True


def _cylinder_piece_volume(face, t1, t2):
    """The exact volume of a cylinder face thickened t1 along its normal and t2 against it: the layer at
    signed distance s from the face (s > 0 away from the axis) has the face's area times (R + s) / R."""
    surf = face.Surface
    u0, u1, v0, v1 = face.ParameterRange
    um, vm = 0.5 * (u0 + u1), 0.5 * (v0 + v1)
    out = 1.0 if face.normalAt(um, vm).dot(face.valueAt(um, vm) - _axis_foot(face.valueAt(um, vm), surf)) > 0 else -1.0
    lo, hi = (-t2, t1) if out > 0 else (-t1, t2)  # the piece's signed radial extent
    return face.Area * ((hi - lo) + (hi * hi - lo * lo) / (2.0 * surf.Radius)), out


def _axis_foot(p, surf):
    a = App.Vector(surf.Axis).normalize()
    return surf.Center + a * (p - surf.Center).dot(a)


def _radial_scale(surf, k):
    """The affine map that scales distances from the cylinder's axis by k and keeps the axial
    coordinate: it takes the cylinder of radius R to the coaxial one of radius k R."""
    a = App.Vector(surf.Axis).normalize()
    av = (a.x, a.y, a.z)
    p = [[k * (i == j) + (1.0 - k) * av[i] * av[j] for j in range(3)] for i in range(3)]
    c = surf.Center
    cv = (c.x, c.y, c.z)
    m = App.Matrix()
    m.A11, m.A12, m.A13 = p[0]
    m.A21, m.A22, m.A23 = p[1]
    m.A31, m.A32, m.A33 = p[2]
    m.A14, m.A24, m.A34 = (cv[i] - sum(p[i][j] * cv[j] for j in range(3)) for i in range(3))
    return m


def _ruled_cylinder_piece(face, t1, t2, out):
    """A cylinder face's thick piece built directly: the face moved to the two radii by _radial_scale,
    closed by ruled faces along each boundary edge (the rulings are the face's normals, as an offset's
    caps). Used where OCC's offset of the face comes out wrong (#90: a leg whose free end is two
    edges meeting at its seam gave twisted caps, 763.83 for 279.17)."""
    R = face.Surface.Radius
    k_hi, k_lo = (R + t1) / R, (R - t2) / R
    if out < 0:
        k_hi, k_lo = (R + t2) / R, (R - t1) / R
    if k_lo < TOL:
        raise SolidOpsError("Thicken failed: the thickness toward the axis exceeds the radius")
    m_hi, m_lo = _radial_scale(face.Surface, k_hi), _radial_scale(face.Surface, k_lo)
    faces = [face.transformGeometry(m_hi), face.transformGeometry(m_lo)]
    for e in face.Edges:
        if e.isSeam(face):
            continue
        faces.extend(Part.makeRuledSurface(e.transformGeometry(m_hi), e.transformGeometry(m_lo)).Faces)
    sewn = Part.Compound(faces)
    sewn.sewShape(1e-6)
    solid = Part.Solid(Part.Shell(sewn.Faces))
    if solid.Volume < 0:
        solid.reverse()
    return solid


def _offset_piece(face, t1, t2):
    """OCC's thick piece of one face: offset by -t2, then filled through t1 + t2."""
    start = face.makeOffsetShape(-t2, TOL) if t2 > TOL else face
    return start.makeOffsetShape(t1 + t2, TOL, False, False, 0, 0, True)


def _leg_piece(face, t1, t2):
    """One non-bend face of a sheet thickened alone: OCC's offset, checked. A cylinder face's piece must
    also hold its exact volume (_cylinder_piece_volume); where the offset misses it, the piece is built
    directly (_ruled_cylinder_piece) and checked the same way, else Thicken fails loudly."""
    try:
        piece, error = _offset_piece(face, t1, t2), None
    except Exception as e:
        piece, error = None, SolidOpsError("Thicken failed: %s" % e)
    if not isinstance(face.Surface, Part.Cylinder):
        if error is not None:
            raise error
        _check_offset(face, piece, "Thicken")
        if not piece.Solids:
            raise SolidOpsError("Thicken failed: the result has no solid")
        return piece
    exact, out = _cylinder_piece_volume(face, t1, t2)

    def right(p):
        return (p is not None and not p.isNull() and p.isValid() and len(p.Solids) == 1
                and abs(p.Volume - exact) <= 1e-6 * max(1.0, exact))

    if right(piece):
        return piece
    try:
        piece = _ruled_cylinder_piece(face, t1, t2, out)
    except SolidOpsError:
        raise
    except Exception as e:
        raise SolidOpsError("Thicken failed: %s" % e)
    if not right(piece):
        raise SolidOpsError("Thicken failed: the result is not valid (it folds over itself)")
    return piece


def _thicken_per_face(group, infos, t1, t2):
    """The union of each face's own thick piece, for a smooth sheet with a bend whose ring reaches the
    bend's axis (the whole-sheet offset folds over itself or fails there)."""
    if not _tangent_joins(group):
        raise SolidOpsError("Thicken failed: a bend's thickness reaches its axis where the sheet has a sharp edge")
    pieces, probes = [], []
    for f, info in zip(group, infos):
        if info is not None:
            solids, inner = _bend_solids(f, info, t1, t2)
            pieces.extend(solids)
            probes.extend(inner)
            continue
        probes.extend(_inner_points(f, 0.5 * (t1 - t2)))  # the face's middle layer
        pieces.append(_leg_piece(f, t1, t2))
    reaching = [i for i in infos if i is not None and _reaches_axis(i, t1, t2)]
    pinched = bool(reaching) and all(abs(_bend_radii(i, t1, t2)[1] - i["d"]) <= TOL for i in reaching)
    return _fused(pieces, probes, pinched)


def _self_intersects(shape, pinched):
    """BOPAlgo's self-intersection check. A fuse of tangent pieces can self-intersect yet pass isValid
    (a U-turn bend whose legs' rings collide: 179 degrees, 457.6406 for 457.6189, review r2). Where
    each ring only touches its bend's axis, the pieces meet at a pinch point, which BOPAlgo reports
    as a vertex or edge self-intersection on a right result (Onshape TK2): those count only when no
    ring merely touches. Tolerance reports (InvalidCurveOnSurface, TooSmallEdge) are left to the
    volume and probe checks. A check that could not run (no BOPAlgo report, OperationAborted,
    CheckUnknown) counts as a self-intersection (review r3). The report names no sub-shape
    (TopoShape::analyze), so the pinch allowance can't be limited to the axis."""
    try:
        shape.check(True)
        return False
    except Exception as e:
        report = str(e).splitlines()
    if not any("BOPAlgo" in l for l in report) or any("OperationAborted" in l or "CheckUnknown" in l for l in report):
        return True
    lines = [l for l in report if "SelfIntersect" in l]
    if pinched:
        lines = [l for l in lines if not ("Vertex" in l or "Edge" in l)]
    return bool(lines)


def _fused(pieces, probes, pinched=False):
    """The pieces' union as one checked solid. The pieces meet along tangent faces, where OCC's fuse
    depends on the order (the horn bore's three pieces fused one by one gave two solids; a 150 degree
    bend's list fuse collapsed into a smaller valid solid). So try a list fuse, then one piece at a time
    in each order, and take the first result that is one valid solid, no smaller than its largest piece
    and no larger than their sum, with every probe point (inside each piece) inside it; else fail
    loudly. The result must also pass BOPAlgo's self-intersection check. A ring crossing its axis with
    no neighbour beside it (a lone bend) gives two solids that meet along the axis: that fails too."""
    if len(pieces) == 1:
        return pieces[0]

    def one_by_one(ps):
        res = ps[0]
        for p in ps[1:]:
            res = res.fuse(p)
        return res

    total = sum(p.Volume for p in pieces)
    tol = 1e-6 * max(1.0, total)
    for build in (lambda ps: ps[0].fuse(ps[1:]), one_by_one, lambda ps: one_by_one(ps[::-1])):
        try:
            res = build(pieces).removeSplitter()
            if res.isNull() or not res.isValid() or len(res.Solids) != 1:
                continue
            if not max(p.Volume for p in pieces) - tol <= res.Volume <= total + tol:
                continue
            if not all(res.isInside(q, 1e-6, True) for q in probes):
                continue
            if _self_intersects(res, pinched):
                continue
            return res
        except Exception:
            continue  # past the geometry time limit, the next try stops at once
    raise SolidOpsError("Thicken failed: the thickened bend is not one valid solid")


def _sheet_piece(surf, t1, t2):
    """OCC's thick piece of a whole smooth sheet: offset by -t2, then filled through t1 + t2, checked."""
    try:
        start = surf.makeOffsetShape(-t2, TOL) if t2 > TOL else surf
        solid = start.makeOffsetShape(t1 + t2, TOL, False, False, 0, 0, True)
    except Exception as e:
        raise SolidOpsError("Thicken failed: %s" % e)
    _check_offset(surf, solid, "Thicken")
    if solid.ShapeType != "Solid" and not solid.Solids:
        raise SolidOpsError("Thicken failed: the result has no solid")
    if solid.Volume <= TOL:
        raise SolidOpsError("Thicken failed: the result has no volume")
    return solid


def _has_full_cylinder(group):
    """True when a face of the group is a cylinder face that goes all the way round its axis."""
    for f in group:
        if isinstance(f.Surface, Part.Cylinder):
            u0, u1 = f.ParameterRange[:2]
            if u1 - u0 >= 2 * math.pi - 1e-9:
                return True
    return False


def thicken_tool(faces, t1, t2):
    """Solid thickened from the faces: t1 along each face's normal, t2 against it."""
    if t1 < 0 or t2 < 0:
        raise SolidOpsError("Thickness must not be negative")
    if t1 + t2 <= TOL:
        raise SolidOpsError("Thickness is zero")
    pieces = []
    for group in _components(faces):
        infos = [_revolved_circle(f) for f in group]
        if any(i is not None and _reaches_axis(i, t1, t2) for i in infos):
            # a bend's ring reaches its axis: the whole-sheet offset is a spindle torus there, which
            # throws or folds over itself while still passing as valid (Onshape TK1-TK4 fill it to the axis)
            pieces.append(_thicken_per_face(group, infos, t1, t2))
            continue
        surf = _as_surface(group)
        try:
            pieces.append(_sheet_piece(surf, t1, t2))
        except SolidOpsError:
            # a smooth sheet with a full-turn cylinder face (a bore's leg): OCC's whole-sheet offset can come out
            # invalid on it (brief 2: a leg with a degree-1 B-spline seam and an oblique end). Its pieces built face
            # by face, each checked, fused and checked again (_thicken_per_face) are the same solid; else the
            # whole-sheet error stands
            if not (_has_full_cylinder(group) and _tangent_joins(group)):
                raise
            pieces.append(_thicken_per_face(group, infos, t1, t2))
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


def _set_shape(obj, shape):
    """Give obj the shape where it lies. During a recompute Part::Feature replaces the shape's own
    location with the feature's Placement (PartFeature.cpp, onChanged), so a copy of a placed shape
    (a Pad on the XZ plane) would move: the location becomes the Placement first (SO1, SO2)."""
    obj.Placement = shape.Placement
    obj.Shape = shape


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
        obj.addProperty("App::PropertyLinkSubListGlobal", "Base", "Thicken", "Faces or surfaces to thicken")
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
            _set_shape(obj, tool)
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
        _set_shape(obj, res)


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
        _set_shape(obj, scale_shape(base, obj.Point, sx, sy, sz))


class OffsetSurface(_Proxy):
    """Offset faces or surfaces by a distance (a sheet; the faces keep their connections)."""

    def __init__(self, obj):
        super().__init__(obj)
        obj.addProperty("App::PropertyLinkSubListGlobal", "Base", "Offset", "Faces or surfaces to offset")
        obj.addProperty("App::PropertyDistance", "Distance", "Offset", "Offset along the face normal")
        obj.addProperty("App::PropertyBool", "Flip", "Offset", "Offset against the face normal")
        obj.Distance = 5.0  # Onshape's default

    def execute(self, obj):
        faces = _resolve_faces(obj)
        if obj.Distance.Value < 0:
            raise SolidOpsError("Offset distance must not be negative: use Flip to offset the other way")
        d = obj.Distance.Value * (-1 if obj.Flip else 1)
        _set_shape(obj, offset_surface(faces, d))


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
