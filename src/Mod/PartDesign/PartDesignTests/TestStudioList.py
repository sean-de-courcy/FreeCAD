# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (S1): the studio's list, reconcile, and the projection property test
#
# The list (PartDesign::StudioList) is the only truth of a studio's history; each Body's chain is
# its projection, rebuilt by reconcile in the edit's transaction (notes/parts-design.md 3.2, 10.1,
# 10.8; notes/one-history-design.md 5 and 9). Ported from the bake-off's prototype
# (work/standby-a/reconcile.py).
#
# Designed geometry only: three 10 mm boxes A (x 0..10), B (x 20..30), C (x 40..50), each a Body
# with a sketch and a native Pad. Until S2 makes Pockets owners, a studio feature (owner) is a
# Part::Box in the studio carrying a dynamic Operation (string) and StudioScope (part ids): a cut
# box reaches down from the top (z 10 - depth .. 10.001), a fuse box sits on it (z 9.999 ..
# 10 + depth). Expected values come from the boxes themselves (Part booleans), never from a run.
#
# The property test: random edits (insert, delete, move, scope, depth, suppress, the bar, undo,
# redo, save and reopen). After each, the document must equal one built from scratch from its
# list (G2, notes/stored-tags.md 4): each Body's chain in order (steps by owner name), its Tip, the
# state at the bar (the Tip's volume, area, solid count and element names, object IDs written as
# object names; the from-scratch build makes the owners in the live document's ID order, since
# names depend on the IDs' order), the steps in error, and the Body's own shape when it isn't
# rolled back (a rolled-back Body keeps its last complete shape, design R5 of
# notes/reorder-rollback-design.md, which depends on the history, not on the list). And G1, in the
# document itself: every active step deleted and made again from the list gives every Tip and
# active step identical names on the same geometry, and so does aborting that. The control (a
# step tagged with its own ID, as a step written like Pocket) must fail G1. STUDIO_PROP_SEEDS
# (e.g. "1,2,3") and STUDIO_PROP_OPS set the size for a long run.
#
# P5 adds Boolean studio features to the random edits (PartDesign::Boolean owners: Subtract and
# Union, Keep tools on and off, targets in StudioScope and tools in StudioTools): the oracle applies
# Onshape's O3 rules itself, and its consumed rule (a tool part a Boolean consumes is no part from
# the Boolean's place on: a later pick of it resolves to nothing) gives the live parts at the bar,
# compared with PartDesign.studioLiveParts and the Bodies' visibility.
#
# Slice 8 adds in-Body patterns of owners' steps (a LinearPattern along the part's y, or a Mirrored
# about a datum plane at y 5 in each part, with one box owner as the original): the oracle copies
# the owner's box itself where the pattern applies (the owner resolved at its place to exactly the
# pattern's part, its step applied, neither suppressed), and nothing otherwise (Onshape's patterns
# across parts come later: refused loudly).
#
# T3 adds Reapply on and off to the patterns, and Up to face Remove owners (a Pocket studio feature
# on a rectangle at z 10.001, down to a plane slanted along y, z = 6.01 + 0.171 y): with Reapply
# off a pattern of one copies the seed's prism (oracle 9, R3); with Reapply on each instance is
# re-solved, the oracle's prism from its own rectangle down to the plane (O6).
#
# Slice 9 adds part mirrors (PartDesign::Mirrored owners with PatternType Part, outside every Body):
# a source part mirrored about a plane x = 15 or x = 35 (a Part::Plane in the studio, outside the
# list), New (a new part holding the copy), Add or Remove (its scope). The oracle mirrors the
# source's shape at the mirror's place itself: New gives the new part that copy; Remove cuts it from
# each scope part (a cut leaving no solid or two changes nothing); Add fuses it into the one scope
# part it touches, and does nothing when it touches none or two (refused loudly). Onshape oracle 9
# (R4): an Add's source outside the scope that touches the copy or that part is merged too, and
# consumed from the mirror's place on. A New mirror's part is compared by its maker's name.

import os
import random
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.Scenarios.harness import Masker
from PartDesignTests.TestStudio import faceAt, pad, sketch, xyPlane

V = App.Vector
PARTS = (("A", 0), ("B", 20), ("C", 40))
NATIVES = 6  # each part's sketch and Pad, first in the list


# ------------------------------------------------------------------------------------- the model
def idWidth(doc, width=4):
    """Moves doc's next object ID up to `width` decimal digits. A document starts its IDs at a
    random 0-5000 (Document.cpp), and names sort tagged names by their bytes, so an ID of 3 digits
    sorts after one of 4 that is larger: comparing names across documents (G2) needs IDs of one
    width in both, as it needs their order."""
    probe = doc.addObject("App::DocumentObjectGroup", "IdProbe")
    start = probe.ID
    doc.removeObject(probe.Name)
    for _ in range(max(0, 10 ** (width - 1) - start - 1)):
        doc.removeObject(doc.addObject("App::DocumentObjectGroup", "IdProbe").Name)


def newStudio(name, parts=PARTS):
    doc = App.newDocument(name)
    idWidth(doc)
    doc.UndoMode = 1
    studio = doc.addObject("App::Part", "S")
    for p, x in parts:
        body = doc.addObject("PartDesign::Body", p)
        studio.addObject(body)
        pad(body, p + "Pad", sketch(body, p + "Sk", xyPlane(body), (x, 0, x + 10, 10)), 10)
    doc.recompute()
    return doc, studio


def toolBox(rect, depth, op):
    """The box a record makes, as (length, width, height, corner)."""
    x0, y0, x1, y1 = rect
    z0, z1 = (10 - depth, 10.001) if op == "Subtraction" else (9.999, 10 + depth)
    return x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0)


def setBox(box, rect, depth, op):
    length, width, height, corner = toolBox(rect, depth, op)
    box.Length, box.Width, box.Height = length, width, height
    box.Placement = App.Placement(corner, App.Rotation())


def makeOwner(doc, studio, name, rect, depth, op, scope=(), suppressed=False):
    """A shape owner: a Part::Box in the studio with Operation and StudioScope (not yet listed)."""
    box = doc.addObject("Part::Box", name)
    studio.addObject(box)
    box.addProperty("App::PropertyString", "Operation", "Studio")
    box.Operation = op
    box.addProperty("App::PropertyStringList", "StudioScope", "Studio")
    box.StudioScope = list(scope)
    if suppressed:
        box.addProperty("App::PropertyBool", "Suppressed", "Studio")
        box.Suppressed = True
    setBox(box, rect, depth, op)
    return box


def booleanOwner(doc, studio, name, kind, targets=(), tools=(), keep=False, suppressed=False):
    """A Boolean studio feature (P5) of Type kind (Cut, Fuse), not yet listed."""
    owner = doc.addObject("PartDesign::Boolean", name)
    studio.addObject(owner)
    owner.Type = kind
    owner.KeepTools = keep
    owner.Refine = False
    owner.StudioScope = list(targets)
    owner.StudioTools = list(tools)
    if suppressed:
        owner.Suppressed = True
    return owner


def isPartMirror(obj):
    """A part mirror (slice 9): a studio feature, not a pattern in a Body."""
    return obj.TypeId == "PartDesign::Mirrored" and getattr(obj, "PatternType", "") == "Part"


def isOwner(obj):
    return obj.TypeId in ("Part::Box", "PartDesign::Boolean", "PartDesign::Pocket") or isPartMirror(
        obj
    )


# The slanted plane of the Up to face owners (T3), z = a + b y; digits that put no element's
# centre on a rounding boundary of elementKey()
SLANT = (6.0123457, 0.17131729)


def slantTool(rect):
    """The prism an Up to face owner on rect makes: from z 10.001 down to the slanted plane."""
    x0, y0, x1, y1 = rect
    a, b = SLANT
    points = [V(x0, y0, a + b * y0), V(x0, y1, a + b * y1), V(x0, y1, 10.001), V(x0, y0, 10.001)]
    face = Part.Face(Part.makePolygon(points + [points[0]]))
    return face.extrude(V(x1 - x0, 0, 0))


def makeUpTo(doc, studio, name, rect, scope=(), suppressed=False):
    """An Up to face Remove owner (T3): a Pocket studio feature on a rectangle sketched at z 10.001,
    down to the studio's slanted plane (not yet listed)."""
    from PartDesignTests.TestStudioOwner import studioSketch

    sk = studioSketch(doc, studio, name + "Sk", rects=(tuple(rect),), z=10.001)
    owner = doc.addObject("PartDesign::Pocket", name)
    studio.addObject(owner)
    owner.Profile = sk
    owner.Type = "UpToFace"
    owner.UpToFace = (doc.getObject("Slant"), ["Face1"])
    owner.Refine = False
    owner.StudioScope = list(scope)
    if suppressed:
        owner.Suppressed = True
    return owner


PATTERN_TYPES = {"Linear": "PartDesign::LinearPattern", "Mirror": "PartDesign::Mirrored"}


def isPattern(obj):
    return obj.TypeId in PATTERN_TYPES.values() and not isPartMirror(obj)


def makeMirror(doc, studio, name, source, x, op, scope=(), suppressed=False):
    """A part mirror (slice 9) of the part source about the plane x (15 or 35), op New, Add or
    Remove, not yet listed (New: studioNewPart after it is listed)."""
    owner = doc.addObject("PartDesign::Mirrored", name)
    studio.addObject(owner)
    owner.PatternType = "Part"
    owner.StudioEntities = [source]
    owner.MirrorPlane = (doc.getObject(f"Mx{x}"), ["Face1"])
    owner.Refine = False
    owner.addProperty("App::PropertyEnumeration", "Operation", "Studio")
    owner.Operation = ["Union", "Subtraction", "Common"]
    owner.Operation = "Subtraction" if op == "Remove" else "Union"
    owner.StudioScope = [] if op == "New" else list(scope)
    if suppressed:
        owner.Suppressed = True
    return owner


def madeBy(owner):
    return [
        b for b in owner.Document.Objects
        if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == owner
    ]


def mirrorRecord(owner):
    plane = owner.MirrorPlane[0] if owner.MirrorPlane else None
    new = bool(madeBy(owner))
    op = "New" if new else ("Remove" if owner.Operation == "Subtraction" else "Add")
    return dict(
        name=owner.Name,
        id=owner.ID,
        mirror=True,
        source=list(owner.StudioEntities)[0] if owner.StudioEntities else "",
        x=int(round(plane.Placement.Base.x)) if plane else 0,
        op=op,
        scope=[] if new else list(owner.StudioScope),
        suppressed=bool(owner.Suppressed),
    )


def makePattern(
    doc, name, kind, part, originals, length=0, count=2, suppressed=False, reapply=False
):
    """A pattern (slice 8) of part's, outside its Body until inserted (insertPattern)."""
    pat = doc.addObject(PATTERN_TYPES[kind], name)
    pat.Reapply = reapply
    body = doc.getObject(part)
    pat.Originals = [doc.getObject(o) for o in originals if doc.getObject(o)]
    if kind == "Linear":
        pat.Direction = (body.Origin.OriginFeatures[1], [""])
        pat.Mode = "Extent"
        pat.Length = length
        pat.Occurrences = count
    else:
        pat.MirrorPlane = (doc.getObject(part + "Mid"), [""])
    pat.Refine = False
    if suppressed:
        pat.Suppressed = True
    return pat


def insertPattern(pat, part, index):
    """pat into part's Body and the list. One with no original (its original deleted in the live
    document) goes in the chain, red, as a pattern whose original went stays in it (ops#640 F3),
    not out of it as a new one with nothing picked (ops#590)."""
    empty = not pat.Originals
    if empty:
        pat.TransformMode = "Whole shape"
    pat.Document.getObject(part).addObject(pat)
    if empty:
        pat.TransformMode = "Features"
    PartDesign.studioInsert(pat, index)


def patternRecord(pat):
    kind = "Mirror" if pat.TypeId == PATTERN_TYPES["Mirror"] else "Linear"
    record = dict(
        name=pat.Name,
        id=pat.ID,
        pattern=kind,
        part=pat.getParentGeoFeatureGroup().Name,
        originals=[o.Name for o in pat.Originals],
        suppressed=bool(pat.Suppressed),
        reapply=bool(pat.Reapply),
    )
    if kind == "Linear":
        record["length"] = round(pat.Length.Value, 6)
        record["count"] = int(pat.Occurrences)
    return record


def ownerRecord(box):
    if isPartMirror(box):
        return mirrorRecord(box)
    if box.TypeId == "PartDesign::Pocket":
        bound = box.Profile[0].Shape.BoundBox
        return dict(
            name=box.Name,
            id=box.ID,
            upto=True,
            rect=[round(v, 6) for v in (bound.XMin, bound.YMin, bound.XMax, bound.YMax)],
            op="Subtraction",
            scope=list(box.StudioScope),
            suppressed=bool(box.Suppressed),
        )
    if box.TypeId == "PartDesign::Boolean":
        return dict(
            name=box.Name,
            id=box.ID,
            kind=box.Type,
            scope=list(box.StudioScope),
            tools=list(box.StudioTools),
            keep=bool(box.KeepTools),
            suppressed=bool(box.Suppressed),
        )
    p = box.Placement.Base
    op = box.Operation
    depth = round(box.Height.Value - 0.001, 6)
    # P6p: the parts the command made from its pieces are intent, copied to the scratch build
    # (the witness's object IDs written as object names: the scratch build has its own IDs)
    masker = Masker(box.Document)
    pieces = sorted(
        (
            b.StudioPartId,
            b.StudioParentId,
            tuple(w[:2] + masker.v2(w[2:]) for w in b.StudioPieceWitness),
        )
        for b in box.Document.Objects
        if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == box and b.StudioPieceWitness
    )
    rect = [
        round(p.x, 6),
        round(p.y, 6),
        round(p.x + box.Length.Value, 6),
        round(p.y + box.Width.Value, 6),
    ]
    return dict(
        name=box.Name,
        id=box.ID,
        rect=rect,
        depth=depth,
        op=op,
        scope=list(box.StudioScope),
        suppressed=bool(getattr(box, "Suppressed", False)),
        pieces=pieces,
    )


def studioList(doc):
    return PartDesign.studioList(doc.getObject("S"), True)


def owners(doc):
    return [e for e in studioList(doc).Entries if isOwner(e)]


def isStep(obj):
    return getattr(obj, "StudioOwner", None) is not None


# ------------------------------------------------------------------------------------- the names
def _number(value):
    text = f"{value:.4f}"
    return "0.0000" if text == "-0.0000" else text


def elementKey(kind, element):
    try:
        point = element.CenterOfMass
    except Exception:
        point = element.BoundBox.Center
    mass = element.Area if kind == "Face" else element.Length
    return f"{kind} c=({_number(point.x)},{_number(point.y)},{_number(point.z)}) m={_number(mass)}"


def elementNames(shape, masker=None):
    """The shape's faces and edges, each keyed by its geometry, with its mapped names (expanded;
    with masker, their object IDs written as object names), sorted."""
    if shape.isNull():
        return []
    expand = getattr(App, "expandMappedName", None)
    reverse = shape.ElementReverseMap
    lines = []
    for kind, elements in (("Face", shape.Faces), ("Edge", shape.Edges)):
        for index, element in enumerate(elements, 1):
            key = elementKey(kind, element)
            found = reverse.get(f"{kind}{index}") or []
            if isinstance(found, str):
                found = [found]
            if not found:
                lines.append(f"{key} : -")
            for name in found:
                if expand:
                    name = expand(name)
                if masker is not None:
                    name = masker.v2(name)
                lines.append(f"{key} : {name}")
    return sorted(lines)


def partNames(doc, masker=None):
    return {p: elementNames(doc.getObject(p).Shape, masker) for p, _ in PARTS if doc.getObject(p)}


# ------------------------------------------------------------------------------------- comparison
def chainOf(body):
    """The Body's Group in order: a step by its owner's name, a native member by its own."""
    return [o.StudioOwner.Name if isStep(o) else o.Name for o in body.Group]


def failedUpToTip(body):
    """The members in error up to the Tip (a held member keeps the error of its last run)"""
    group = list(body.Group)
    if body.Tip is None:
        return []  # nothing active (a part made later than the bar, P6p): every member is held
    last = group.index(body.Tip) if body.Tip in group else len(group) - 1
    chain = chainOf(body)
    return sorted(chain[i] for i, o in enumerate(group[: last + 1]) if not o.isValid())


def snapshot(doc, names=True):
    """Each part's chain, Tip and state at the bar (the Tip's shape); the Body's own shape only
    when it isn't rolled back (rolled back, it keeps its last complete shape: design R5)."""
    out = {}
    masker = Masker(doc) if names else None
    for p, _ in PARTS:
        body = doc.getObject(p)
        if body is None:
            continue
        tip = body.Tip
        shape = tip.Shape if tip else Part.Shape()
        rolled = body.isRolledBack()
        out[p] = dict(
            chain=chainOf(body),
            suppressed=sorted(o.StudioOwner.Name for o in body.Group if isStep(o) and o.Suppressed),
            tip=(tip.StudioOwner.Name if isStep(tip) else tip.Name) if tip else None,
            volume=0.0 if shape.isNull() else round(shape.Volume, 4),
            area=0.0 if shape.isNull() else round(shape.Area, 4),
            solids=0 if shape.isNull() else len(shape.Solids),
            failed=failedUpToTip(body),
            rolledBack=rolled,
            body=None if rolled or body.Shape.isNull() else round(body.Shape.Volume, 4),
            live=body in PartDesign.studioLiveParts(body),
            visible=bool(body.Visibility),
        )
        if names:
            out[p]["names"] = elementNames(shape, masker)
    # P6p: each part made from a piece, by its part id (its name depends on the order made)
    for body in doc.Objects:
        if body.TypeId != "PartDesign::Body" or not body.StudioPieceWitness:
            continue
        tip = body.Tip
        shape = tip.Shape if tip else Part.Shape()
        key = "piece:" + body.StudioPartId
        out[key] = dict(
            chain=chainOf(body),
            tip=(tip.StudioOwner.Name if isStep(tip) else tip.Name) if tip else None,
            volume=0.0 if shape.isNull() else round(shape.Volume, 4),
            solids=0 if shape.isNull() else len(shape.Solids),
            failed=failedUpToTip(body),
            live=body in PartDesign.studioLiveParts(body),
            visible=bool(body.Visibility),
        )
        if names:
            out[key]["names"] = elementNames(shape, masker)
    # A New part mirror's part (slice 9), by its maker's name (its own name depends on the order
    # the parts were made in)
    for owner in studioList(doc).Entries:
        if not isPartMirror(owner):
            continue
        for body in madeBy(owner):
            tip = body.Tip
            shape = tip.Shape if tip else Part.Shape()
            out["new:" + owner.Name] = dict(
                volume=0.0 if shape.isNull() else round(shape.Volume, 4),
                solids=0 if shape.isNull() else len(shape.Solids),
                live=body in PartDesign.studioLiveParts(body),
            )
    return out


def listOf(doc):
    """The list as data: the owners in order with their values, and the bar among them."""
    lst = studioList(doc)
    entries = list(lst.Entries)
    bar = lst.Bar if 0 <= lst.Bar < len(entries) else len(entries)
    records = [
        patternRecord(e) if isPattern(e) else ownerRecord(e)
        for e in entries
        if isOwner(e) or isPattern(e)
    ]
    natives = [e.Name for e in entries if not isOwner(e) and not isPattern(e)]
    return natives, records, bar


def oracle(natives, records, bar, live=None):
    """Per part, (volume, solids) by Part booleans from the list as data, never by reconcile
    (the S1 skeptic, 2026-11-10: fromScratch() reconciles too, so it shows only that incremental
    and one-shot reconcile agree). Records apply in list order up to the bar, each to the parts
    its scope names unless suppressed; a step that would split its part contributes nothing.
    The generator keeps the natives first, so the bar counts them first.

    Boolean records (P5, Onshape O3, O9b): only live parts resolve. Subtract cuts the fused tools
    (targets left out) from each target; Union fuses the parts listed (targets, then tools) into
    the first. A Boolean that resolves to no target, no tool, a part both, or a Union of one part
    does nothing; otherwise, Keep tools off and not suppressed, its tools are consumed (even when
    the geometry fails it), so no later record acts on them. live, a set, gets the parts live at
    the bar.

    Pattern records (slice 8): a pattern in part p of one box owner copies the owner's box (its
    instances at k * length / (count - 1) along y, or its mirror about y 5) into p when the owner
    comes before it, resolved at its place to exactly [p], its step applied in p, and neither is
    suppressed; otherwise it does nothing."""
    shapes = {p: Part.makeBox(10, 10, 10, V(x, 0, 0)) for p, x in PARTS}
    # Slice 9: the part each New mirror makes, by its maker ("new:<name>"); None: empty
    made = {
        "new:" + r["name"]: None
        for i, r in enumerate(records)
        if r.get("mirror") and r["op"] == "New" and len(natives) + i < bar
    }
    consumed = set()
    resolved = {}  # box owner -> the parts it resolved to at its place
    applied = set()  # (box owner, part) whose step changed its part
    for i, record in enumerate(records):
        if len(natives) + i >= bar:
            break
        if record["suppressed"]:
            continue
        if record.get("mirror"):
            src = record["source"]
            if src not in shapes or src in consumed:
                continue  # no part to mirror: it fails
            copy = shapes[src].mirror(V(record["x"], 0, 0), V(1, 0, 0))
            if record["op"] == "New":
                made["new:" + record["name"]] = copy
                continue
            targets = []
            for p in record["scope"]:
                if p in shapes and p not in consumed and p not in targets:
                    targets.append(p)
            tool = [copy]
            if record["op"] == "Add":
                touched = [p for p in targets if copy.distToShape(shapes[p])[0] <= 1e-7]
                if len(touched) != 1:
                    continue  # touching none, or two (merging parts: refused)
                # Oracle 9 R4: the source outside the scope touching the copy or the survivor
                # is merged with the copy, and consumed
                survivor = shapes[touched[0]]
                if src not in targets and (
                    shapes[src].distToShape(copy)[0] <= 1e-7
                    or shapes[src].distToShape(survivor)[0] <= 1e-7
                ):
                    tool.append(shapes[src])
                    consumed.add(src)
            for p in targets:
                cut = record["op"] == "Remove"
                if cut:
                    result = shapes[p].cut(copy)
                else:
                    # A step fuses the tool's solids that touch its part (all when none does)
                    solids = tool[0].fuse(tool[1:]) if len(tool) > 1 else copy
                    pieces = solids.Solids or [solids]
                    kept = [t for t in pieces if t.distToShape(shapes[p])[0] <= 1e-7] or pieces
                    result = shapes[p].fuse(kept)
                result = result.removeSplitter()
                if len(result.Solids) == 1:
                    shapes[p] = result
            continue
        if "pattern" in record:
            p = record["part"]
            originals = [o for o in record["originals"] if o in resolved]
            if len(originals) != len(record["originals"]) or len(originals) != 1:
                continue
            o = originals[0]
            if resolved[o] != [p] or (o, p) not in applied:
                continue
            owner = next(r for r in records if r["name"] == o)
            if owner.get("upto"):
                # T3: with Reapply on, each instance re-solved from its own rectangle; off, copies
                # of the seed's prism (oracle 9, R3: Reapply off copies an Up to face seed)
                x0, y0, x1, y1 = owner["rect"]
                if not record.get("reapply"):
                    tool = slantTool(owner["rect"])
                    if record["pattern"] == "Linear":
                        count = record["count"]
                        copies = [
                            tool.translated(V(0, k * record["length"] / (count - 1), 0))
                            for k in range(1, count)
                        ]
                    else:
                        copies = [tool.mirror(V(0, 5, 0), V(0, 1, 0))]
                elif record["pattern"] == "Linear":
                    count = record["count"]
                    moves = [k * record["length"] / (count - 1) for k in range(1, count)]
                    rects = [(x0, y0 + d, x1, y1 + d) for d in moves]
                    copies = [slantTool(r) for r in rects]
                else:
                    copies = [slantTool((x0, 10 - y1, x1, 10 - y0))]
            else:
                length, width, height, corner = toolBox(owner["rect"], owner["depth"], owner["op"])
                tool = Part.makeBox(length, width, height, corner)
                if record["pattern"] == "Linear":
                    count = record["count"]
                    copies = [
                        tool.translated(V(0, k * record["length"] / (count - 1), 0))
                        for k in range(1, count)
                    ]
                else:
                    copies = [tool.mirror(V(0, 5, 0), V(0, 1, 0))]
            cut = owner["op"] == "Subtraction"
            result = (shapes[p].cut(copies) if cut else shapes[p].fuse(copies)).removeSplitter()
            if len(result.Solids) == 1:
                shapes[p] = result
            continue
        if "kind" in record:
            targets = [p for p in record["scope"] if p in shapes and p not in consumed]
            tools = [p for p in record["tools"] if p in shapes and p not in consumed]
            if record["kind"] == "Fuse":
                listed = targets + [p for p in tools if p not in targets]
                if len(listed) < 2:
                    continue
                survivor, others = listed[0], listed[1:]
                # P6p (Onshape A-2' b): a tool touching none of the parts merged (in turn)
                # stays a part, not fused, not consumed; with none touching the Union fails
                merged, rest = [survivor], list(others)
                grew = True
                while grew:
                    grew = False
                    for p in list(rest):
                        if any(shapes[p].distToShape(shapes[q])[0] <= 1e-7 for q in merged):
                            merged.append(p)
                            rest.remove(p)
                            grew = True
                others = merged[1:]
                if not others:
                    continue
                result = shapes[survivor].fuse([shapes[p] for p in others]).removeSplitter()
                if len(result.Solids) == 1:
                    shapes[survivor] = result
            else:
                cutters = [p for p in tools if p not in targets]
                if not targets or not cutters or len(cutters) < len(tools):
                    continue
                tool = shapes[cutters[0]]
                if len(cutters) > 1:
                    tool = tool.fuse([shapes[p] for p in cutters[1:]])
                for p in targets:
                    result = shapes[p].cut(tool).removeSplitter()
                    if len(result.Solids) == 1:
                        shapes[p] = result
                others = cutters
            if not record["keep"]:
                consumed.update(others)
            continue
        if record.get("upto"):
            tool = slantTool(record["rect"])
        else:
            length, width, height, corner = toolBox(record["rect"], record["depth"], record["op"])
            tool = Part.makeBox(length, width, height, corner)
        resolved[record["name"]] = []
        for p in record["scope"]:
            if p not in shapes or p in consumed or p in resolved[record["name"]]:
                continue
            resolved[record["name"]].append(p)
            cut = record["op"] == "Subtraction"
            result = (shapes[p].cut(tool) if cut else shapes[p].fuse(tool)).removeSplitter()
            if len(result.Solids) == 1:
                shapes[p] = result
                applied.add((record["name"], p))
    if live is not None:
        live.update(p for p in shapes if p not in consumed)
        live.update(made)
    out = {p: (round(s.Volume, 4), len(s.Solids)) for p, s in shapes.items()}
    out.update({k: (0.0, 0) if s is None else (round(s.Volume, 4), len(s.Solids)) for k, s in made.items()})
    return out


def liveKey(body):
    """A part as the oracle names it: its name, or a New mirror's part by its maker."""
    maker = body.StudioMadeBy
    return "new:" + maker.Name if maker is not None else body.Name


def oracleDifferences(doc):
    """oracle() against each Tip's shape (the state at the bar), and the Body's own shape when
    it is not rolled back; plus hygiene: nothing touched or invalid after a recompute, no step
    without an owner or outside every Body."""
    live = set()
    want = oracle(*listOf(doc), live=live)
    found = []
    bodies = [doc.getObject(p) for p, _ in PARTS]
    # P6p: the oracle doesn't model pieces; with any part made from a piece, the shapes and the
    # live parts are checked by G2 and G1 only (the hygiene below still applies)
    if any(b.TypeId == "PartDesign::Body" and b.StudioPieceWitness for b in doc.Objects):
        bodies = []
        live = None
    # The consumed rule: the live parts at the bar, and a consumed part hidden (no test hides one)
    got = sorted(liveKey(b) for b in PartDesign.studioLiveParts(studioList(doc)))
    if live is not None and got != sorted(live):
        found.append(f"live parts {got}, oracle {sorted(live)}")
    for body in bodies:
        if bool(body.Visibility) != (body.Name in live):
            found.append(f"{body.Name}: Visibility {body.Visibility}, oracle live {body.Name in live}")
    for body in bodies:
        tip = body.Tip
        shape = tip.Shape if tip else Part.Shape()
        got = (0.0 if shape.isNull() else round(shape.Volume, 4), len(shape.Solids))
        if got != want[body.Name]:
            found.append(f"{body.Name}: Tip {got}, oracle {want[body.Name]}")
        if not body.isRolledBack() and not body.Shape.isNull():
            volume = round(body.Shape.Volume, 4)
            if volume != want[body.Name][0]:
                found.append(f"{body.Name}: Body {volume}, oracle {want[body.Name][0]}")
    # Slice 9: each listed New mirror's part, at the bar
    for owner in studioList(doc).Entries:
        if not isPartMirror(owner) or live is None:
            continue
        key = "new:" + owner.Name
        for body in madeBy(owner):
            tip = body.Tip
            shape = tip.Shape if tip else Part.Shape()
            got = (0.0 if shape.isNull() else round(shape.Volume, 4), len(shape.Solids))
            if got != want.get(key, (0.0, 0)):
                found.append(f"{key}: Tip {got}, oracle {want.get(key, (0.0, 0))}")
    # A held object (after its Body's Tip) and a rolled-back Body are not recomputed: they stay
    # touched until the bar passes them (ops#127 R5/R7)
    held = set()
    for body in [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]:  # New parts too
        group = list(body.Group)
        if body.Tip in group:
            held.update(o.Name for o in group[group.index(body.Tip) + 1:])
        elif body.Tip is None and body not in bodies:
            held.update(o.Name for o in group)  # a New part whose maker is past the bar
        if body.isRolledBack():
            held.add(body.Name)
    for obj in doc.Objects:
        if "Touched" in obj.State and obj.Name not in held:
            found.append(f"{obj.Name} touched after a recompute")
        if obj.TypeId == "PartDesign::FeatureApply":
            if obj.StudioOwner is None:
                found.append(f"{obj.Name}: a step without an owner")
            if not any(
                b.hasObject(obj) for b in doc.Objects if b.TypeId == "PartDesign::Body"
            ):
                found.append(f"{obj.Name}: a step in no Body")
    return found


def deleteSteps(doc, active=False):
    """Deletes every step (with active, only those up to the Tip and not suppressed)."""
    for p, _ in PARTS:
        body = doc.getObject(p)
        for obj in activeSteps(body) if active else [o for o in body.Group if isStep(o)]:
            body.removeObject(obj)
            doc.removeObject(obj.Name)


def activeSteps(body):
    """The steps up to the Tip, not suppressed (a held or suppressed step's shape isn't
    recomputed, and nothing reads it until it is active again)."""
    group = list(body.Group)
    last = group.index(body.Tip) if body.Tip in group else -1
    return [o for o in group[: last + 1] if isStep(o) and not o.Suppressed]


def plainNames(shape):
    """Each element's plain mapped name -> its geometry (kind, centre, size): faces, edges and
    vertices."""
    out = {}
    if shape.isNull():
        return out
    for kind, items in (("Face", shape.Faces), ("Edge", shape.Edges), ("Vertex", shape.Vertexes)):
        for i, element in enumerate(items, 1):
            mapped = shape.getElementMappedName(f"{kind}{i}")
            mapped = mapped[0] if isinstance(mapped, tuple) else mapped
            if not mapped:
                continue
            point = element.Point if kind == "Vertex" else element.CenterOfMass
            size = element.Area if kind == "Face" else element.Length if kind == "Edge" else 0
            key = (kind, *(round(c, 4) for c in point), round(size, 4))
            out[str(App.expandMappedName(str(mapped)))] = key
    return out


def g1Record(doc):
    """G1's record: every Tip's and every active step's names with their geometry."""
    out = {}
    for p, _ in PARTS:
        body = doc.getObject(p)
        out[p] = plainNames(body.Tip.Shape) if body.Tip else {}
        for step in activeSteps(body):
            out[f"{step.StudioOwner.Name}@{p}"] = plainNames(step.Shape)
    return out


def g1Differences(before, after):
    """Names lost, new, or on an element of other geometry (a few of each)."""
    found = []
    for key in sorted(set(before) | set(after)):
        a, b = before.get(key, {}), after.get(key, {})
        lost = [n for n in a if n not in b]
        new = [n for n in b if n not in a]
        moved = [n for n in a if n in b and a[n] != b[n]]
        if lost or new or moved:
            sample = [n[:120] for n in (lost + new + moved)[:2]]
            found.append(f"{key}: lost {len(lost)}, new {len(new)}, moved {len(moved)}: {sample}")
    return found


def gateG1(doc, regenerate=None):
    """G1 (notes/stored-tags.md 4): in a transaction, every active step deleted and made again by
    reconcile (then regenerate(doc), the control's hook), recomputed: every Tip's and active step's
    names come back on the same geometry and none is new; then the transaction is aborted and the
    names checked again. Returns the differences."""
    before = g1Record(doc)
    doc.openTransaction("gate G1")
    try:
        deleteSteps(doc, active=True)
        PartDesign.studioReconcile(studioList(doc))
        if regenerate:
            regenerate(doc)
        doc.recompute()
        regenerated = g1Record(doc)
    finally:
        doc.abortTransaction()
    doc.recompute()
    back = g1Record(doc)
    found = ["regenerated: " + d for d in g1Differences(before, regenerated)]
    found += ["after abort: " + d for d in g1Differences(before, back)]
    return found


class OwnIdStep:
    """The control's step: FeatureApply's Boolean and refine in Python, tagged with the step's own
    object ID (as a C++ step written like Pocket, FeatureExtrude's makeTopoShape())."""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        owner = obj.StudioOwner
        op = "CUT" if owner.Operation == "Subtraction" else "FUS"
        obj.Shape = Part.Shape([obj.BaseFeature.Shape, owner.Shape.copy()], op, obj.ID).removeSplitter()

    def dumps(self):
        return None

    def loads(self, state):
        return None


def ownIdSteps(doc):
    """Replaces every FeatureApply step with an OwnIdStep at its place (the control)."""
    for p, _ in PARTS:
        body = doc.getObject(p)
        for old in [o for o in body.Group if o.TypeId == "PartDesign::FeatureApply"]:
            step = doc.addObject("PartDesign::FeaturePython", old.Name + "Own")
            OwnIdStep(step)
            step.StudioOwner = old.StudioOwner
            step.Suppressed = old.Suppressed
            wasTip = body.Tip == old
            body.insertObject(step, old, True)
            body.removeObject(old)
            doc.removeObject(old.Name)
            if wasTip:
                body.Tip = step
    doc.recompute()


def unmasked(name, doc):
    """A name Masker.v2 wrote, with each `{ObjectName}` tag doc's object's ID again (the lists
    sorted again by their bytes)."""
    sections = App.getDecodedMappedName(name)
    if not sections:
        return name
    out = []
    for section in sections:
        section = dict(section)
        for field in ("linkedNames", "connectedElements"):
            section[field] = sorted(unmasked(n, doc) for n in section[field])
        tag = section["iterationTag"]
        if tag.startswith("{") and tag.endswith("}"):
            sign = "-" if tag.startswith("{-") else ""
            obj = doc.getObject(tag.strip("{}-"))
            if obj is not None:
                section["iterationTag"] = sign + str(obj.ID)
        out.append(App.makeEncodedSection(**section))
    return "|".join(out)


def fromScratch(natives, records, bar, maker=None):
    """The document built from scratch from the list (G2): the same parts; the owners made in the
    live document's ID order (names depend on the IDs' order, notes/stored-tags.md 4), then
    inserted in the list's order; then the bar."""
    doc, studio = (maker or newStudio)("scratch")
    try:
        lst = studioList(doc)
        assert [e.Name for e in lst.Entries] == natives, ([e.Name for e in lst.Entries], natives)
        for r in sorted(records, key=lambda r: r["id"]):
            if "pattern" in r:
                box = makePattern(
                    doc, r["name"], r["pattern"], r["part"], r["originals"], r.get("length", 0),
                    r.get("count", 2), r["suppressed"], r.get("reapply", False),
                )
            elif r.get("mirror"):
                box = makeMirror(
                    doc, studio, r["name"], r["source"], r["x"], r["op"], r["scope"],
                    r["suppressed"],
                )
            elif r.get("upto"):
                box = makeUpTo(doc, studio, r["name"], r["rect"], r["scope"], r["suppressed"])
            elif "kind" in r:
                box = booleanOwner(
                    doc, studio, r["name"], r["kind"], r["scope"], r["tools"], r["keep"],
                    r["suppressed"],
                )
            else:
                box = makeOwner(
                    doc, studio, r["name"], r["rect"], r["depth"], r["op"], r["scope"],
                    r["suppressed"],
                )
            assert box.Name == r["name"], (box.Name, r["name"])
        for r in records:
            if "pattern" in r:
                insertPattern(doc.getObject(r["name"]), r["part"], -1)
            else:
                PartDesign.studioInsert(doc.getObject(r["name"]), -1)
                if r.get("mirror") and r["op"] == "New":
                    PartDesign.studioNewPart(doc.getObject(r["name"]))
        # P6p: the piece records, as the command wrote them (intent)
        for r in records:
            for partId, parentId, witness in r.get("pieces", ()):
                body = doc.addObject("PartDesign::Body", "Body")
                studio.addObject(body)
                body.StudioPartId = partId
                body.StudioParentId = parentId
                body.StudioMadeBy = doc.getObject(r["name"])
                body.StudioPieceWitness = [w[:2] + unmasked(w[2:], doc) for w in witness]
                body.Label = "Part 1"
        if any(r.get("pieces") for r in records):
            PartDesign.studioReconcile(lst)
        PartDesign.studioSetBar(lst, bar if bar < len(lst.Entries) else -1)
        doc.recompute()
        # P6p: a Union's tools apart are decided by its compute and taken by the projection after
        # it (the document's resync after a recompute); done here too, so the build doesn't
        # depend on whether that signal reached this document (open question, ops#654 P6p)
        stale = [
            e for e in lst.Entries
            if e.TypeId == "PartDesign::Boolean"
            and list(getattr(e, "StudioApartTools", [])) != list(getattr(e, "StudioApartToolsSeen", []))
        ]
        if stale:
            PartDesign.studioReconcile(lst)
            doc.recompute()
        return snapshot(doc)
    finally:
        App.closeDocument(doc.Name)


def differences(got, want):
    out = [f"{p}: in the document only" for p in got if p not in want]
    for p in want:
        for key in want[p]:
            if got.get(p, {}).get(key) != want[p][key]:
                if key == "names":
                    a, b = set(got[p][key]), set(want[p][key])
                    out.append(
                        f"{p}.names: {len(a - b)} only in the document, {len(b - a)} only built: "
                        f"{sorted(a - b)[:3]} / {sorted(b - a)[:3]}"
                    )
                else:
                    have = got.get(p, {}).get(key)
                    out.append(f"{p}.{key}: document {have}, built {want[p][key]}")
    return out


# ------------------------------------------------------------------------------------- the tests
class StudioCase(unittest.TestCase):
    def setUp(self):
        self.doc, self.studio = newStudio("TestStudioList")
        self.list = studioList(self.doc)

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith(("TestStudioList", "prop", "scratch")):
                App.closeDocument(doc.Name)

    def owner(self, name, rect, depth, op, scope):
        box = makeOwner(self.doc, self.studio, name, rect, depth, op, scope)
        self.doc.openTransaction("insert " + name)
        PartDesign.studioInsert(box, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        return box

    def step(self, owner, part):
        return PartDesign.studioStepOf(owner, self.doc.getObject(part))

    def assertVolume(self, part, expected):
        self.assertAlmostEqual(self.doc.getObject(part).Shape.Volume, expected, places=4)

    def state(self):
        return [e.Name for e in self.list.Entries], snapshot(self.doc, names=False)

    def stepIds(self):
        return {o.Name: o.ID for p, _ in PARTS for o in self.doc.getObject(p).Group if isStep(o)}

    def laterBoss(self, doc=None):
        """B's boss (z 10..15) after everything in the history: its sketch inserted at the end,
        the Pad adopted after it"""
        doc = doc or self.doc
        b = doc.getObject("B")
        sk2 = sketch(b, "BSk2", xyPlane(b), (20, 0, 30, 10), z=10)
        boss = pad(b, "BBoss", sk2, 5)
        PartDesign.studioInsert(sk2, -1)
        return boss

    @staticmethod
    def partBox(part):
        x = dict(PARTS)[part]
        return Part.makeBox(10, 10, 10, V(x, 0, 0))

    @staticmethod
    def tool(rect, depth, op):
        length, width, height, corner = toolBox(rect, depth, op)
        return Part.makeBox(length, width, height, corner)


class TestStudioList(StudioCase):
    def testAdoptsTheDerivedOrder(self):
        """A list made for an existing studio holds its Bodies' members in the derived order, and
        reconcile gives every part its id (its Body's name)."""
        self.assertEqual(
            [e.Name for e in self.list.Entries], ["ASk", "APad", "BSk", "BPad", "CSk", "CPad"]
        )
        self.assertEqual(self.list.Bar, -1)
        PartDesign.studioReconcile(self.list)
        for p, _ in PARTS:
            self.assertEqual(self.doc.getObject(p).StudioPartId, p)
        projection = PartDesign.studioProject(self.list)
        self.assertEqual(
            projection["A"], [("ASk", False, False, False), ("APad", False, False, False)]
        )

    def testAdoptsAMemberAfterTheEntryBeforeIt(self):
        """A member made by an old command (body.newObject) joins the list right after the entry
        before it in its Body."""
        b = self.doc.getObject("B")
        boss = pad(b, "BBoss", sketch(b, "BSk2", xyPlane(b), (20, 0, 30, 10), z=10), 5)
        PartDesign.studioReconcile(self.list)
        self.assertEqual(
            [e.Name for e in self.list.Entries],
            ["ASk", "APad", "BSk", "BPad", "BSk2", "BBoss", "CSk", "CPad"],
        )
        self.doc.recompute()
        self.assertIs(b.Tip, boss)
        self.assertVolume("B", 1500)

    def testOneCutTwoParts(self):
        """One owner, one step in each part of its scope, computing its one tool."""
        rect, depth = [5, 2, 25, 8], 4
        f1 = self.owner("F1", rect, depth, "Subtraction", ["A", "B"])
        tool = self.tool(rect, depth, "Subtraction")
        for p in "AB":
            self.assertTrue(self.step(f1, p).isValid(), p)
            self.assertVolume(p, self.partBox(p).cut(tool).Volume)
        self.assertVolume("C", 1000)
        self.assertIsNone(self.step(f1, "C"))
        self.assertEqual(self.step(f1, "A").Name, "F1_at_A")

    def testLateScopeGoesInOrder(self):
        """c10: a part added late to an early cut's scope gets its step at the cut's place in the
        history, before the part's later boss: Onshape's order, not appended at the Body's end."""
        rect, depth = [5, 2, 28, 8], 4
        f1 = makeOwner(self.doc, self.studio, "F1", rect, depth, "Subtraction", ["A"])
        f1.Height = 14  # z 6..20: through the later boss too, so the order shows in the volume
        PartDesign.studioInsert(f1, -1)
        b = self.doc.getObject("B")
        boss = self.laterBoss()
        self.doc.recompute()
        self.assertVolume("B", 1500)

        self.doc.openTransaction("scope")
        PartDesign.studioSetScopeIds(f1, ["A", "B"])
        self.doc.commitTransaction()
        self.doc.recompute()

        tool = Part.makeBox(23, 6, 14, V(5, 2, 6))
        bossBox = Part.makeBox(10, 10, 5, V(20, 0, 10))
        inOrder = self.partBox("B").cut(tool).fuse(bossBox).Volume
        appended = self.partBox("B").fuse(bossBox).cut(tool).Volume
        self.assertGreater(abs(inOrder - appended), 1)  # the case tells them apart
        self.assertVolume("B", inOrder)
        self.assertVolume("A", self.partBox("A").cut(tool).Volume)
        self.assertEqual(chainOf(b), ["BSk", "BPad", "F1", "BSk2", "BBoss"])
        self.assertEqual(boss.BaseFeature.Name, "F1_at_B")
        self.assertIs(b.Tip, boss)

    def testOneOwnerHasOnePlace(self):
        f1 = self.owner("F1", [2, 2, 4, 4], 2, "Subtraction", ["A"])
        with self.assertRaises(ValueError):
            PartDesign.studioInsert(f1, 7)
        self.assertEqual([e.Name for e in self.list.Entries].count("F1"), 1)
        # The list written directly with an entry twice: refused, nothing changed
        entries = list(self.list.Entries)
        chain = chainOf(self.doc.getObject("A"))
        self.list.Entries = entries + [f1]
        with self.assertRaises(ValueError):
            PartDesign.studioReconcile(self.list)
        with self.assertRaises(ValueError):
            PartDesign.studioProject(self.list)
        self.assertEqual(chainOf(self.doc.getObject("A")), chain)

    def testSplitIsAnError(self):
        """A cut that splits a part fails, naming the part and the count; the part goes on with
        the state before it (one solid), as a failed feature contributes nothing."""
        f1 = self.owner("F1", [4, -1, 6, 11], 11, "Subtraction", ["A"])  # z -1..10.001
        step = self.step(f1, "A")
        self.assertFalse(step.isValid())
        self.assertIn("splits", step.getStatusString())
        self.assertIn("2 pieces", step.getStatusString())
        a = self.doc.getObject("A")
        self.assertEqual(len(a.Shape.Solids), 1)
        self.assertVolume("A", 1000)

    def testFailedOwnerContributesNothing(self):
        """Onshape F1: an owner that fails fails its steps only; later features compute against
        the state before it."""
        f1 = self.owner("F1", [2, 2, 5, 5], 2, "Subtraction", ["A"])
        f2 = self.owner("F2", [6, 6, 8, 8], 3, "Subtraction", ["A"])
        f3 = self.owner("F3", [5, 5, 8, 8], 3, "Union", ["A"])
        f2.Height = 0  # a box of no height fails
        self.doc.recompute()
        self.assertFalse(f2.isValid())
        self.assertFalse(self.step(f2, "A").isValid())
        self.assertTrue(self.step(f3, "A").isValid())
        expected = self.partBox("A").cut(self.tool([2, 2, 5, 5], 2, "Subtraction"))
        expected = expected.fuse(self.tool([5, 5, 8, 8], 3, "Union"))
        self.assertVolume("A", expected.Volume)
        self.assertTrue(f1.isValid())

    def testUndoRestoresListAndChains(self):
        f1 = self.owner("F1", [5, 2, 25, 8], 2, "Subtraction", ["A", "B"])
        self.owner("F2", [22, 2, 26, 6], 3, "Union", ["B"])
        before = self.state()
        self.doc.openTransaction("move")
        PartDesign.studioMove(self.doc.getObject("F2"), NATIVES)
        self.doc.commitTransaction()
        self.doc.recompute()
        after = self.state()
        self.assertNotEqual(before[0], after[0])
        self.assertNotEqual(before[1]["B"]["chain"], after[1]["B"]["chain"])
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.state(), before)
        self.doc.redo()
        self.doc.recompute()
        self.assertEqual(self.state(), after)
        self.assertIsNotNone(self.step(f1, "B"))

    def testDroppedPartLosesItsStepAndGetsTheSameNamesBack(self):
        f1 = self.owner("F1", [5, 2, 25, 8], 2, "Subtraction", ["A", "B"])
        names = partNames(self.doc)
        stepId = self.step(f1, "B").ID
        self.doc.openTransaction("drop B")
        PartDesign.studioSetScopeIds(f1, ["A"])
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertIsNone(self.step(f1, "B"))
        self.assertVolume("B", 1000)
        self.doc.openTransaction("add B")
        PartDesign.studioSetScopeIds(f1, ["A", "B"])
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertNotEqual(self.step(f1, "B").ID, stepId)
        self.assertEqual(partNames(self.doc), names)

    def testGoneIdResolvesToNothing(self):
        """Onshape F2: an id whose part is gone is ignored when another resolves; alone, the owner
        acts on nothing (listed as unresolved)."""
        f1 = self.owner("F1", [2, 2, 4, 4], 2, "Subtraction", ["A", "Gone"])
        self.assertEqual([b.Name for b in PartDesign.studioScopeOf(f1)], ["A"])
        self.assertIsNotNone(self.step(f1, "A"))
        PartDesign.studioSetScopeIds(f1, ["Gone"])
        self.assertEqual(PartDesign.studioScopeOf(f1), [])
        self.assertIsNone(self.step(f1, "A"))

    def gateModel(self):
        self.owner("F1", [5, 2, 25, 8], 2, "Subtraction", ["A", "B"])
        self.owner("F2", [22, 2, 26, 6], 3, "Union", ["B"])
        self.owner("F3", [2, 4, 8, 9], 1, "Subtraction", ["A"])
        self.owner("F4", [3, 1, 9, 3], 1, "Subtraction", ["A"])

    def testNamesGate(self):
        """G1 in one document: every active step deleted and made again from the list (new
        objects, the same names) gives every Tip and active step identical names on the same
        geometry, and so does the abort."""
        self.gateModel()
        before = partNames(self.doc)
        ids = self.stepIds()
        self.assertEqual(gateG1(self.doc), [])
        self.doc.openTransaction("regenerate")
        deleteSteps(self.doc)
        PartDesign.studioReconcile(self.list)
        self.doc.commitTransaction()
        self.doc.recompute()
        regenerated = self.stepIds()
        self.assertEqual(sorted(ids), sorted(regenerated))
        self.assertTrue(all(ids[n] != regenerated[n] for n in ids))  # new objects
        self.assertEqual(partNames(self.doc), before)

    def testNamesGateControlFails(self):
        """The control: steps tagged with their own object ID (a step written like Pocket) change
        names when made again, and G1 catches it."""
        self.gateModel()
        ownIdSteps(self.doc)
        self.assertTrue(all(o.TypeId == "PartDesign::FeaturePython" for o in activeSteps(self.doc.A)))
        self.assertTrue(all(o.isValid() for p, _ in PARTS for o in self.doc.getObject(p).Group))
        found = gateG1(self.doc, regenerate=ownIdSteps)
        self.assertTrue(any(d.startswith("regenerated: ") for d in found), found)

    def testComparisonCatchesAnAppendedStep(self):
        """The control: a step appended at a Body's end (body.addObject, as today's siblings),
        instead of at its owner's place, is caught by the comparison with a from-scratch build."""

        def build(doc, studio):
            f1 = makeOwner(doc, studio, "F1", [5, 2, 28, 8], 4, "Subtraction", ["A", "B"])
            f1.Height = 14  # z 6..20: through B's later boss too
            PartDesign.studioInsert(f1, -1)
            self.laterBoss(doc)
            doc.recompute()
            return f1

        f1 = build(self.doc, self.studio)
        scratch, studio = newStudio("scratchControl")
        build(scratch, studio)
        want = snapshot(scratch)
        App.closeDocument(scratch.Name)
        self.assertEqual(differences(snapshot(self.doc), want), [])
        # Break it: B's step made again and appended after the boss
        b = self.doc.getObject("B")
        old = self.step(f1, "B")
        b.removeObject(old)
        self.doc.removeObject(old.Name)
        step = self.doc.addObject("PartDesign::FeatureApply", "F1_B")
        step.StudioOwner = f1
        step.Operation = "Subtraction"
        b.addObject(step)
        self.doc.recompute()
        self.assertIs(b.Tip, step)
        found = differences(snapshot(self.doc), want)
        self.assertTrue(any(d.startswith("B.chain") for d in found), found)
        self.assertTrue(any(d.startswith("B.volume") for d in found), found)

    # --------------------------------------------------------------------- step names (format)
    def testStepNameIsOwnerAndPartId(self):
        """A step's object name is a function of (owner name, part id), one to one: letters and
        digits kept, '_' doubled, other bytes as _HH, and "_at_" between (part ids have ':')."""
        d = self.doc.addObject("PartDesign::Body", "D")
        self.studio.addObject(d)
        pad(d, "DPad", sketch(d, "DSk", xyPlane(d), (60, 0, 70, 10)), 10)
        d.StudioPartId = "Sk:1/x_y"
        self.doc.recompute()
        f1 = self.owner("F1", [62, 2, 66, 6], 2, "Subtraction", ["Sk:1/x_y", "A"])
        f2 = self.owner("F_2", [2, 2, 4, 4], 1, "Subtraction", ["A"])
        self.assertEqual(self.step(f1, "D").Name, "F1_at_Sk_3A1_2Fx__y")
        self.assertEqual(self.step(f1, "A").Name, "F1_at_A")
        self.assertEqual(self.step(f2, "A").Name, "F__2_at_A")
        self.assertTrue(self.step(f1, "D").isValid())

    def testStepNameTakenIsAnError(self):
        """The name a step must have, taken by another object: reconcile refuses (no suffixed
        name), and changes nothing."""
        other = self.doc.addObject("App::DocumentObjectGroup", "F1_at_A")
        box = makeOwner(self.doc, self.studio, "F1", [2, 2, 4, 4], 2, "Subtraction", ["A", "B"])
        chains = {p: chainOf(self.doc.getObject(p)) for p, _ in PARTS}
        self.doc.openTransaction("insert")
        with self.assertRaises(ValueError) as caught:
            PartDesign.studioInsert(box, -1)
        self.doc.abortTransaction()
        self.assertIn("'F1_at_A'", str(caught.exception))
        self.assertEqual({p: chainOf(self.doc.getObject(p)) for p, _ in PARTS}, chains)
        self.assertIs(self.doc.getObject("F1_at_A"), other)
        self.assertIsNone(self.doc.getObject("F1_at_A001"))
        self.assertIsNone(self.step(box, "B"))

    # --------------------------------------------------------------------- readers keep a step
    def testDeletedOwnersReadStepGoesAndFreesItsName(self):
        """S1 skeptic 3: an owner deleted while a datum reads its step's floor takes the step
        with it (its readers fail, as Onshape's dependants of a deleted feature), so a new owner
        given the freed name is accepted; undo brings the old one back, readers intact."""
        f1 = self.owner("F1", [5, 2, 25, 8], 2, "Subtraction", ["A", "B"])  # floor z 8
        a = self.doc.getObject("A")
        step = self.step(f1, "A")
        datum = a.newObject("PartDesign::Plane", "ADatum")
        datum.AttachmentSupport = [(step, faceAt(step, 8))]
        datum.MapMode = "FlatFace"
        self.doc.openTransaction("adopt")
        PartDesign.studioReconcile(self.list)
        self.doc.commitTransaction()
        self.doc.recompute()
        stepName = step.Name

        self.doc.openTransaction("delete F1")
        PartDesign.studioRemove(f1)
        self.doc.removeObject("F1")
        self.doc.commitTransaction()
        self.doc.recompute()
        self.doc.openTransaction("a new F1")
        g = makeOwner(self.doc, self.studio, "F1", [1, 1, 3, 3], 1, "Subtraction", ["A"])
        PartDesign.studioInsert(g, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(g.Name, "F1")
        new = self.step(g, "A")
        self.assertIsNotNone(new)
        self.assertEqual(new.Name, stepName)
        self.assertIs(new.StudioOwner, g)
        self.assertTrue(new.isValid(), new.getStatusString())
        self.assertVolume("A", 1000 - 2 * 2 * 1)
        self.assertFalse(datum.isValid())  # its floor is gone: loud

        self.doc.undo()
        self.doc.undo()
        self.doc.recompute()
        f1 = self.doc.getObject("F1")
        self.assertIs(self.step(f1, "A").StudioOwner, f1)
        self.assertIs(datum.AttachmentSupport[0][0], self.step(f1, "A"))
        self.assertTrue(datum.isValid(), datum.getStatusString())
        self.assertAlmostEqual(datum.getGlobalPlacement().Base.z, 8, places=6)

    def testReadStepIsKeptSuppressed(self):
        """A step something reads (a datum on its cut floor, an Up to face Pocket to that floor)
        isn't deleted when its part leaves the scope: it stays, suppressed, at its owner's place,
        and comes back with the same names when the part is added again, its readers' links
        intact. Deleting a later feature keeps them too. Without readers it is deleted."""
        f1 = self.owner("F1", [5, 2, 25, 8], 2, "Subtraction", ["A", "B"])  # floor z 8
        self.owner("F2", [7, 0.5, 9, 1.5], 1, "Subtraction", ["A"])
        a = self.doc.getObject("A")
        step = self.step(f1, "A")
        floor = faceAt(step, 8)
        datum = a.newObject("PartDesign::Plane", "ADatum")
        datum.AttachmentSupport = [(step, floor)]
        datum.MapMode = "FlatFace"
        pocket = a.newObject("PartDesign::Pocket", "APocket")
        pocket.Profile = sketch(a, "APSk", xyPlane(a), (1, 3, 4, 7), z=10)
        pocket.Type = "UpToFace"
        pocket.UpToFace = (step, [floor])
        self.doc.openTransaction("adopt")
        PartDesign.studioReconcile(self.list)
        self.doc.commitTransaction()
        self.doc.recompute()
        expected = 1000 - 5 * 6 * 2 - 2 * 1 * 1 - 3 * 4 * 2
        self.assertVolume("A", expected)
        self.assertAlmostEqual(datum.getGlobalPlacement().Base.z, 8, places=6)
        names = partNames(self.doc)
        stepName, stepId = step.Name, step.ID

        def readersIntact():
            self.assertIs(datum.AttachmentSupport[0][0], step)
            self.assertIs(pocket.UpToFace[0], step)

        self.doc.openTransaction("drop A")
        PartDesign.studioSetScopeIds(f1, ["B"])
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertIs(self.step(f1, "A"), step)
        self.assertTrue(step.Suppressed)
        self.assertEqual(chainOf(a)[:3], ["ASk", "APad", "F1"])  # at its owner's place
        readersIntact()

        self.doc.openTransaction("add A")
        PartDesign.studioSetScopeIds(f1, ["A", "B"])
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertIs(self.step(f1, "A"), step)
        self.assertEqual((step.Name, step.ID), (stepName, stepId))
        self.assertFalse(step.Suppressed)
        readersIntact()
        self.assertTrue(all(o.isValid() for o in a.Group), [o.Name for o in a.Group if not o.isValid()])
        self.assertAlmostEqual(datum.getGlobalPlacement().Base.z, 8, places=6)
        self.assertVolume("A", expected)
        self.assertEqual(partNames(self.doc), names)

        self.doc.openTransaction("delete F2")
        PartDesign.studioRemove(self.doc.getObject("F2"))
        self.doc.removeObject("F2")
        self.doc.commitTransaction()
        self.doc.recompute()
        readersIntact()
        self.assertTrue(all(o.isValid() for o in a.Group), [o.Name for o in a.Group if not o.isValid()])
        self.assertAlmostEqual(datum.getGlobalPlacement().Base.z, 8, places=6)
        self.assertVolume("A", expected + 2)

        # The readers gone, the dropped step goes too
        self.doc.openTransaction("drop A, no readers")
        for obj in (pocket, pocket.Profile[0], datum):
            name = obj.Name
            a.removeObject(obj)
            self.doc.removeObject(name)
        PartDesign.studioSetScopeIds(f1, ["B"])
        self.doc.commitTransaction()
        self.assertIsNone(self.step(f1, "A"))
        self.assertIsNone(self.doc.getObject(stepName))

    # --------------------------------------------------------------------- copied parts (P7a)
    def copiedPart(self, partId):
        """A Body as one copied alone would be: in the studio, its part id given, with a copy of
        F1's step (the original owner, the copy's name)."""
        f1 = self.owner("F1", [2, 2, 4, 4], 2, "Subtraction", ["A"])
        copy = self.doc.addObject("PartDesign::Body", "A001")
        self.studio.addObject(copy)
        copy.StudioPartId = partId
        step = self.doc.addObject("PartDesign::FeatureApply", "F1_at_A001")
        step.StudioOwner = f1
        copy.addObject(step)
        return f1, copy, step

    def everything(self):
        return (
            [e.Name for e in self.list.Entries],
            {b.Name: (chainOf(b), b.Tip.Name if b.Tip else None, b.StudioPartId)
             for b in self.doc.Objects if b.TypeId == "PartDesign::Body"},
            sorted(o.Name for o in self.doc.Objects),
        )

    def testDuplicatePartIdIsRefused(self):
        """Two parts holding one part id (a Body copied alone): reconcile refuses loudly and
        changes nothing."""
        f1, copy, step = self.copiedPart("A")
        before = self.everything()
        with self.assertRaises(ValueError) as caught:
            PartDesign.studioReconcile(self.list)
        self.assertIn("part id 'A' is held by two parts", str(caught.exception))
        self.assertEqual(self.everything(), before)

    def testStepOutsideItsOwnersScopeIsRefused(self):
        """A step in a part its owner's scope doesn't hold, not made there (a copy with a part id
        of its own): refused loudly, not deleted."""
        f1, copy, step = self.copiedPart("A2")
        before = self.everything()
        with self.assertRaises(ValueError) as caught:
            PartDesign.studioReconcile(self.list)
        self.assertIn("'F1_at_A001'", str(caught.exception))
        self.assertIn("a part its scope doesn't hold", str(caught.exception))
        self.assertEqual(self.everything(), before)
        self.assertIs(self.doc.getObject("F1_at_A001"), step)


class TestObjectIds(unittest.TestCase):
    """ops#657: a document saves its highest object ID, so a deleted object's ID is never given
    again after a save and reopen (a reference naming it would re-bind silently)."""

    def testDeletedLastIdIsNotGivenAgain(self):
        folder = tempfile.mkdtemp(prefix="studioids")
        try:
            doc = App.newDocument("TestStudioListIds")
            doc.addObject("App::DocumentObjectGroup", "First")
            last = doc.addObject("App::DocumentObjectGroup", "Last")
            lastId = last.ID
            doc.removeObject("Last")
            path = os.path.join(folder, "ids.FCStd")
            doc.saveAs(path)
            App.closeDocument(doc.Name)
            doc = App.openDocument(path)
            made = doc.addObject("App::DocumentObjectGroup", "Made")
            self.assertGreater(made.ID, lastId)
            App.closeDocument(doc.Name)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


# ------------------------------------------------------------------------------------- random edits
def touches(rect):
    x0, _, x1, _ = rect
    return [p for p, x in PARTS if x0 < x + 10 and x1 > x]


PROP_NATIVES = NATIVES + len(PARTS)  # and each part's mirror plane


def propStudio(name):
    """newStudio, plus a datum plane at y 5 in each part (a Mirrored's plane, slice 8)."""
    doc, studio = newStudio(name)
    for p, _ in PARTS:
        mid = doc.getObject(p).newObject("PartDesign::Plane", p + "Mid")
        mid.MapMode = "Deactivated"
        mid.Placement = App.Placement(V(0, 5, 0), App.Rotation(V(1, 0, 0), -90))
    # T3: the plane the Up to face owners go down to (SLANT, outside the list)
    import math

    slant = doc.addObject("Part::Plane", "Slant")
    studio.addObject(slant)
    slant.Length, slant.Width = 80, 40
    angle = math.degrees(math.atan(SLANT[1]))
    slant.Placement = App.Placement(
        V(-15, -15, SLANT[0] - 15 * SLANT[1]), App.Rotation(V(1, 0, 0), angle)
    )
    # Slice 9: the part mirrors' planes x = 15 and x = 35 (outside the list)
    for x in (15, 35):
        plane = doc.addObject("Part::Plane", f"Mx{x}")
        studio.addObject(plane)
        plane.Length, plane.Width = 40, 40
        plane.Placement = App.Placement(V(x, -15, 25), App.Rotation(V(0, 1, 0), 90))
    doc.recompute()
    return doc, studio


class TestStudioListProperty(unittest.TestCase):
    """After every random edit the document equals the one built from scratch from its list."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="studiolist")
        self.log = []
        self.consumedSeen = 0  # states after an edit with a part consumed at the bar (P5)
        self.patternsSeen = 0  # valid patterns of an owner, summed over the states (slice 8)
        self.mirrorsSeen = 0  # valid part mirrors, summed over the states (slice 9)
        self.piecesSeen = 0  # states with a live part made from a piece (P6p)

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith(("prop", "scratch")):
                App.closeDocument(doc.Name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def edit(self, rng, doc, counter):
        lst = studioList(doc)
        NATIVES = PROP_NATIVES
        boxes = owners(doc)
        shapeOwners = [b for b in boxes if b.TypeId in ("Part::Box", "PartDesign::Pocket")]
        entries = boxes + [e for e in lst.Entries if isPattern(e)]
        free = len(lst.Entries) - NATIVES  # places after the natives
        kinds = ["insert"] * 3 + ["boolean", "pattern", "pattern", "mirror", "mirror"]
        kinds += ["delete", "move", "scope", "depth", "suppress", "bar", "split", "split"]
        kind = rng.choice(kinds) if boxes else rng.choice(["insert", "insert", "boolean"])
        if kind == "pattern" and not shapeOwners:
            kind = "insert"
        if kind == "mirror":
            # Slice 9: a part mirror of a part about x = 15 or 35, New, Add or Remove
            names = [p for p, _ in PARTS]
            source = rng.choice(names)
            x = rng.choice([15, 35])
            op = rng.choice(["New", "Add", "Remove"])
            scope = [] if op == "New" else rng.sample(names, rng.randint(1, 2))
            at = rng.randint(0, free)
            owner = makeMirror(doc, doc.getObject("S"), f"F{counter}", source, x, op, scope)
            PartDesign.studioInsert(owner, NATIVES + at)
            if op == "New":
                PartDesign.studioNewPart(owner)
            return f"mirror {owner.Name} {op} of {source} about x {x} scope {scope} at {at}"
        if kind == "pattern":
            # Slice 8: a Linear (along y) or a Mirror (about y 5) of one box owner, in one of its
            # scope's parts (or another part: refused), somewhere after it
            owner = rng.choice(shapeOwners)
            scope = list(owner.StudioScope) or ["A"]
            part = rng.choice(scope) if rng.random() < 0.85 else rng.choice([p for p, _ in PARTS])
            which = rng.choice(["Linear", "Linear", "Mirror"])
            count = rng.choice([2, 3])
            length = rng.choice([1, 2]) * (count - 1)
            after = list(lst.Entries).index(owner) + 1 - NATIVES
            at = rng.randint(after, free)
            reapply = rng.random() < 0.5  # T3
            pat = makePattern(
                doc, f"F{counter}", which, part, [owner.Name], length, count, reapply=reapply
            )
            insertPattern(pat, part, NATIVES + at)
            return (
                f"pattern {pat.Name} {which} of {owner.Name} in {part} L{length} n{count} at {at}"
                f" reapply {reapply}"
            )
        if kind == "boolean":
            # P5: a Subtract or a Union between parts, Keep tools on or off
            names = [p for p, _ in PARTS]
            op = rng.choice(["Cut", "Cut", "Fuse"])
            targets = rng.sample(names, rng.randint(0 if op == "Fuse" else 1, 1))
            rest = [p for p in names if p not in targets]
            tools = rng.sample(rest, rng.randint(1, len(rest)))
            keep = rng.random() < 0.4
            at = rng.randint(0, free)
            owner = booleanOwner(doc, doc.getObject("S"), f"F{counter}", op, targets, tools, keep)
            PartDesign.studioInsert(owner, NATIVES + at)
            return f"boolean {owner.Name} {op} targets {targets} tools {tools} keep {keep} at {at}"
        if kind == "split":
            # P6p: a slot through a part (its x the random parameter), and its command
            p, px = rng.choice(PARTS)
            x = px + rng.choice([3, 4, 5, 6])
            rect = [x, -1, x + 1, 11]
            at = rng.randint(0, free)
            box = makeOwner(doc, doc.getObject("S"), f"F{counter}", rect, 11, "Subtraction", [p])
            PartDesign.studioInsert(box, NATIVES + at)
            made = PartDesign.studioMakePieces(box)
            return f"split {box.Name} {rect} scope {[p]} at {at}: {len(made)} parts"
        if kind == "insert":
            x0 = rng.choice([2, 5, 8, 22, 25, 42, 45, 5, 25])
            w = rng.choice([2, 4, 8, 20, 25])
            y0 = rng.choice([1, 2, 4])
            rect = [x0, y0, x0 + w, y0 + rng.choice([2, 3, 5])]
            parts = touches(rect) or ["A"]
            scope = sorted(rng.sample(parts, rng.randint(1, len(parts))))
            op = rng.choice(["Subtraction", "Subtraction", "Union"])
            depth = rng.choice([1, 2, 3, 4])
            at = rng.randint(0, free)
            if rng.random() < 0.3:
                # T3: an Up to face Remove owner
                box = makeUpTo(doc, doc.getObject("S"), f"F{counter}", rect, scope)
                PartDesign.studioInsert(box, NATIVES + at)
                return f"insert {box.Name} up to face {rect} scope {scope} at {at}"
            box = makeOwner(doc, doc.getObject("S"), f"F{counter}", rect, depth, op, scope)
            PartDesign.studioInsert(box, NATIVES + at)
            return f"insert {box.Name} {op} {rect} d{depth} scope {scope} at {at}"
        box = rng.choice(entries)
        name = box.Name
        if isPattern(box) and kind in ("scope", "depth"):
            if box.TypeId == PATTERN_TYPES["Mirror"] or kind == "scope":
                # T3: Reapply toggled
                box.Reapply = not box.Reapply
                PartDesign.studioReconcile(lst)
                return f"reapply {name} {box.Reapply}"
            else:
                count = rng.choice([2, 3])
                box.Occurrences = count
                box.Length = rng.choice([1, 2]) * (count - 1)
                PartDesign.studioReconcile(lst)
                return f"count {name} n{count} L{box.Length.Value}"
        if isPartMirror(box) and kind in ("scope", "depth"):
            if kind == "depth":
                x = 50 - int(round(box.MirrorPlane[0].Placement.Base.x))  # 15 <-> 35
                box.MirrorPlane = (doc.getObject(f"Mx{x}"), ["Face1"])
                PartDesign.studioReconcile(lst)
                return f"plane {name} x {x}"
            names = [p for p, _ in PARTS]
            if madeBy(box):
                source = rng.choice(names)
                box.StudioEntities = [source]
                PartDesign.studioReconcile(lst)
                return f"source {name} {source}"
            scope = sorted(rng.sample(names, rng.randint(1, 2)))
            PartDesign.studioSetScopeIds(box, scope)
            return f"scope {name} {scope}"
        if kind == "delete" and isPartMirror(box):
            # Its New part goes with it (an empty part of no feature isn't the list's)
            made = [b.Name for b in madeBy(box)]
            PartDesign.studioRemove(box)
            doc.removeObject(name)
            for body in made:
                doc.getObject(body).removeObjectsFromDocument()
                doc.removeObject(body)
            return f"delete {name} and {made}"
        if kind == "delete":
            profile = box.Profile[0] if box.TypeId == "PartDesign::Pocket" else None
            PartDesign.studioRemove(box)
            doc.removeObject(name)
            if profile is not None:
                doc.removeObject(profile.Name)
            return f"delete {name}"
        if kind == "move":
            j = rng.randrange(free)
            try:
                PartDesign.studioMove(box, NATIVES + j)
            except ValueError as e:
                # Onshape's drag: refused above what it reads or below what reads it (a pattern
                # reads its original, slice 8); nothing changes
                if " uses " not in str(e):
                    raise
                return f"move {name} -> {j} refused: {e}"
            if box.TypeId == "Part::Box":
                PartDesign.studioMakePieces(box)  # P6p: a moved feature's command (the drag's)
            return f"move {name} -> {j}"
        if kind in ("scope", "depth") and box.TypeId == "PartDesign::Boolean":
            names = [p for p, _ in PARTS]
            if kind == "depth":
                box.KeepTools = not box.KeepTools
                PartDesign.studioReconcile(lst)
                return f"keep {name} {box.KeepTools}"
            if rng.random() < 0.5:
                tools = sorted(rng.sample(names, rng.randint(1, 2)))
                PartDesign.studioSetToolIds(box, tools)
                return f"tools {name} {tools}"
            targets = sorted(rng.sample(names, rng.randint(0 if box.Type == "Fuse" else 1, 1)))
            PartDesign.studioSetScopeIds(box, targets)
            return f"targets {name} {targets}"
        if kind == "scope":
            scope = list(box.StudioScope)
            p = rng.choice([p for p, _ in PARTS])
            if p in scope and len(scope) > 1:
                scope.remove(p)
            elif p not in scope:
                scope = sorted(scope + [p])
            PartDesign.studioSetScopeIds(box, scope)
            return f"scope {name} {scope}"
        if kind == "depth" and box.TypeId == "PartDesign::Pocket":
            kind = "suppress"  # an Up to face owner has no depth
        if kind == "depth" and box.TypeId == "Part::Box" and round(box.Placement.Base.y) == -1:
            # P6p: the slot moved (its edit's OK is the command)
            r = ownerRecord(box)
            p = r["scope"][0]
            x = dict(PARTS)[p] + rng.choice([3, 4, 5, 6])
            setBox(box, [x, -1, x + 1, 11], 11, "Subtraction")
            PartDesign.studioReconcile(lst)
            made = PartDesign.studioMakePieces(box)
            return f"slot {name} at x {x}: {len(made)} new parts"
        if kind == "depth":
            r = ownerRecord(box)
            depth = rng.choice([1, 2, 3, 4, 5])
            setBox(box, r["rect"], depth, r["op"])
            PartDesign.studioReconcile(lst)
            return f"depth {name} {depth}"
        if kind == "suppress":
            on = not bool(getattr(box, "Suppressed", False))
            PartDesign.studioSuppress(box, on)
            return f"suppress {name} {on}"
        bar = rng.randint(NATIVES, len(lst.Entries))
        PartDesign.studioSetBar(lst, bar if bar < len(lst.Entries) else -1)
        return f"bar {bar}"

    def run_sequence(self, seed, nops):
        rng = random.Random(seed)
        doc, _ = propStudio(f"prop{seed}")
        path = os.path.join(self.dir, f"prop{seed}.FCStd")
        studioList(doc)
        bad = 0
        for step in range(nops):
            roll = rng.random()
            if roll < 0.12 and doc.UndoCount:
                doc.undo()
                what = "undo"
            elif roll < 0.18 and doc.RedoCount:
                doc.redo()
                what = "redo"
            elif roll < 0.23:
                doc.saveAs(path)
                App.closeDocument(doc.Name)
                doc = App.openDocument(path)
                doc.UndoMode = 1
                what = "save, close, reopen"
            else:
                doc.openTransaction("edit")
                try:
                    what = self.edit(rng, doc, step + 1)
                    doc.commitTransaction()
                except Exception as e:
                    doc.abortTransaction()
                    what = f"refused: {e}"
                    # P6p: a member placed in a part after its split, or in a piece before the
                    # split, is refused loudly by design (nothing changes)
                    if "split before it" not in str(e) and "makes after it" not in str(e):
                        bad += 1
                        self.log.append(f"seed {seed} op {step} {what}")
            doc.recompute()
            got = snapshot(doc)
            want = fromScratch(*listOf(doc), maker=propStudio)
            found = differences(got, want)
            found += ["oracle " + d for d in oracleDifferences(doc)]
            found += ["G1 " + d for d in gateG1(doc)[:4]]
            # A part consumed at the bar by a Boolean or a part mirror (a split's parent, P6p,
            # is no consumed part here)
            consumers = [PartDesign.studioConsumerOf(doc.getObject(p)) for p, _ in PARTS]
            if any(c is not None and c.TypeId != "Part::Box" for c in consumers):
                self.consumedSeen += 1
            if any(b.StudioPieceWitness for b in PartDesign.studioLiveParts(studioList(doc))):
                self.piecesSeen += 1
            self.patternsSeen += sum(
                1 for e in studioList(doc).Entries if isPattern(e) and e.isValid() and e.Originals
            )
            self.mirrorsSeen += sum(
                1 for e in studioList(doc).Entries
                if isPartMirror(e) and e.isValid() and not e.Suppressed
            )
            if found:
                bad += 1
                self.log.append(f"seed {seed} op {step} after {what}:")
                self.log.extend("    " + d for d in found)
                if bad > 3:
                    break
        App.closeDocument(doc.Name)
        return bad

    def testRandomEdits(self):
        seeds = [int(s) for s in os.environ.get("STUDIO_PROP_SEEDS", "1,2,3").split(",") if s]
        nops = int(os.environ.get("STUDIO_PROP_OPS", "25"))
        total = sum(self.run_sequence(seed, nops) for seed in seeds)
        self.assertEqual(total, 0, "\n".join(self.log))
        # The consumed rule was exercised, not only Booleans that keep their tools
        self.assertGreater(self.consumedSeen, 0)
        self.assertGreater(self.patternsSeen, 0)
        self.assertGreater(self.mirrorsSeen, 0)
        self.assertGreater(self.piecesSeen, 0)
        print(f"testRandomEdits: {len(seeds)} seeds x {nops} edits, {self.consumedSeen} states "
              f"with a consumed part, {self.patternsSeen} valid patterns, {self.mirrorsSeen} valid "
              f"part mirrors seen, {self.piecesSeen} states with a live piece")


if __name__ == "__main__":
    unittest.main()
