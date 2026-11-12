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
    return (
        obj.TypeId in ("Part::Box", "PartDesign::Boolean", "PartDesign::Pocket")
        or isPartMirror(obj)
        or isFillet(obj)
    )


def isFillet(obj):
    """A Fillet studio feature (P8a): outside every Body, so no step (a step has an owner)."""
    return obj.TypeId == "PartDesign::Fillet" and getattr(obj, "StudioOwner", None) is None


def makeFillet(doc, studio, name, radius, picks, suppressed=False):
    """A Fillet owner (P8a) on picks ("<part id>|<name>"), not yet listed."""
    owner = doc.addObject("PartDesign::Fillet", name)
    studio.addObject(owner)
    owner.Radius = radius
    owner.StudioPickIds = list(picks)
    owner.Suppressed = suppressed
    return owner


def activeFillet(body):
    """Whether body holds a step of a Fillet owner up to its Tip, not suppressed, whose owner
    isn't in error: the Part oracle doesn't model a fillet (P8a: G1, G2, the solids and the step
    count check those parts)."""
    return any(isFillet(o.StudioOwner) and o.StudioOwner.isValid() for o in activeSteps(body))


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
    if isFillet(box):
        # P8a: the picks' names with their object IDs as names (the scratch build has its own)
        masker = Masker(box.Document)
        picks = []
        for text in box.StudioPickIds:
            part, _, name = text.partition("|")
            picks.append(part + "|" + masker.v2(name))
        return dict(
            name=box.Name,
            id=box.ID,
            fillet=True,
            radius=round(box.Radius.Value, 6),
            picks=picks,
            suppressed=bool(box.Suppressed),
        )
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
    # For the Part oracle (not the scratch build): each piece's side of the slot, as the test
    # noted it when the command made it (labelPieces), and its place among the Bodies (the
    # order a scope resolves in)
    sides = {
        b.StudioPartId: (getattr(b, "OracleSide", ""), i)
        for i, b in enumerate(box.Document.Objects)
        if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == box and b.StudioPieceWitness
    }
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
        sides=sides,
    )


def labelPieces(made, box):
    """Notes on each part the command just made from a piece the side of box's slot it lies on
    (L, R; N for a leftover), for the Part oracle: identity stays with the side (notes/
    parts-design.md 10.12). Any assignment is right when made; the oracle checks it holds."""
    middle = box.Placement.Base.x + box.Length.Value / 2
    for body in made:
        if not body.StudioParentId:
            side = "N"
        else:
            shape = body.Tip.Shape if body.Tip else Part.Shape()
            side = "?" if shape.isNull() else ("L" if shape.BoundBox.Center.x < middle else "R")
        if not hasattr(body, "OracleSide"):
            body.addProperty("App::PropertyString", "OracleSide", "Test")
        body.OracleSide = side


def studioList(doc):
    return PartDesign.studioList(doc.getObject("S"), True)


def owners(doc):
    return [e for e in studioList(doc).Entries if isOwner(e)]


def isStep(obj):
    return getattr(obj, "StudioOwner", None) is not None


# ------------------------------------------------------------------------------------- the names
def _number(value):
    # Nudged off the half: the designed boxes put centres on binary fractions such as 4.40625,
    # exactly half way at four places, where noise of 1e-15 between two constructions of the same
    # face flips the last digit (seed 5, op 73, ops#654 P8a-2)
    text = f"{value + 1e-7:.4f}"
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
            # Unlisted (a property seed's start, ops#654 list on first use): every Body a part
            live=body in PartDesign.studioLiveParts(body)
            if PartDesign.studioList(PartDesign.studioOf(body)) is not None
            else True,
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
    # the parts were made in). Unlisted (ops#654): none, and no list made here
    lst = PartDesign.studioList(doc.getObject("S"))
    for owner in lst.Entries if lst is not None else []:
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
    suppressed; otherwise it does nothing.

    Pieces (P6p, notes/parts-design.md 10.12): a box record's piece records (intent, copied
    from the parts its command made, with the side of its slot each was made on) make parts at
    its place: each holds the solid on its side of the split, the parent is no part after it,
    and scopes resolve an id to its living descendants. Out: "piece:<id>" -> (volume, solids),
    or "failed" when the record holds nothing.

    Merges (10.13, Onshape O9, O9b, M1, M2): a Union box record whose tool joins two or more of
    its resolved parts (their fuse has fewer solids than its inputs: overlap or a face, never an
    edge) makes them one: the first in its scope's order survives, holding the fuse of all, the
    others are consumed from its place on (no later record acts on them, and their shapes stay
    as they were before it)."""
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
    # P6p: the parts made from pieces, by part id. A maker's pieces are parts from its place on
    # (not suppressed, before the bar); a split parent is none after it (dead), unless the split
    # is gone (its result is one solid, Onshape Q13): then its pieces are no parts (vanished) and
    # a pick of one resolves to the parent. A piece whose record holds nothing is a part that
    # fails (failed): a scope still resolves to it, and what acts on it fails there (a Boolean
    # with it still consumes its tools). A scope resolves to an id's part and its living
    # descendants, in the Bodies' order
    pieceRecs = {
        r["name"]: {
            pid: (parent, r.get("sides", {}).get(pid, ("", 0))[0])
            for pid, parent, _ in r.get("pieces", ())
        }
        for r in records
    }
    order = [p for p, _ in PARTS] + [
        pid for _, pid in sorted(
            (side[1], pid) for r in records for pid, side in r.get("sides", {}).items()
        )
    ]
    parentOf = {}
    madePieces = set()  # made: live unless consumed or dead
    dead = set()
    failed = set()
    vanished = set()  # the pieces of a split that is gone (10.12 amendment)

    def descends(key, ident):
        seen = set()
        while key and key not in seen:
            if key == ident:
                return True
            seen.add(key)
            key = parentOf.get(key)
        return False

    def resolve(ids):
        out = []
        for ident in ids:
            seen = set()
            while ident in vanished and ident not in seen:  # a gone split's piece: its parent
                seen.add(ident)
                ident = parentOf.get(ident, ident)
            for key in order:
                if (
                    key not in out and (key in shapes or key in failed) and key not in consumed
                    and key not in dead and descends(key, ident)
                ):
                    out.append(key)
        return out
    for i, record in enumerate(records):
        if len(natives) + i >= bar:
            break
        if record["suppressed"] or record.get("fillet"):
            continue  # P8a: a fillet isn't modelled (activeFillet)
        if record.get("mirror"):
            sources = resolve([record["source"]])
            if len(sources) != 1 or sources[0] not in shapes:
                continue  # no part to mirror, or a split part's pieces: it fails
            src = sources[0]
            copy = shapes[src].mirror(V(record["x"], 0, 0), V(1, 0, 0))
            if record["op"] == "New":
                made["new:" + record["name"]] = copy
                continue
            targets = [p for p in resolve(record["scope"]) if p in shapes]
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
            targets = resolve(record["scope"])
            tools = resolve(record["tools"])
            if record["kind"] == "Fuse":
                listed = targets + [p for p in tools if p not in targets]
                if len(listed) < 2:
                    continue
                survivor, others = listed[0], listed[1:]
                if any(p not in shapes for p in listed):
                    # A part that fails (P6p): the Union fails, its tools consumed
                    if not record["keep"]:
                        consumed.update(others)
                    continue
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
                if all(p in shapes for p in targets + cutters):
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
        own = pieceRecs.get(record["name"], {})
        resolved[record["name"]] = []
        merging = False
        if record["op"] == "Union" and not record.get("upto"):
            scope = resolve(record["scope"])
            joined = [p for p in scope if p in shapes and joins(tool, shapes[p])]
            if len(joined) >= 2:
                resolved[record["name"]] = scope
                survivor, others = joined[0], joined[1:]
                result = shapes[survivor].fuse([tool] + [shapes[p] for p in others])
                result = result.removeSplitter()
                if len(result.Solids) == 1:
                    shapes[survivor] = result
                    applied.add((record["name"], survivor))
                consumed.update(others)
                merging = True
        for p in [] if merging else resolve(record["scope"]):
            resolved[record["name"]].append(p)
            if p not in shapes:
                continue  # a part that fails: its step fails
            cut = record["op"] == "Subtraction"
            result = (shapes[p].cut(tool) if cut else shapes[p].fuse(tool)).removeSplitter()
            recs = sorted(pid for pid, (parent, _) in own.items() if parent == p)
            if not recs:
                if len(result.Solids) == 1:
                    shapes[p] = result
                    applied.add((record["name"], p))
                continue
            # P6p: a split of p (its records name it). Each record holds the solid on its side of
            # the slot (the leftmost, the rightmost), the step holding them all; with a solid
            # unheld the step fails and contributes nothing. One solid: the record whose wall
            # (the slot's face on its side) is on it holds it, if only one's is; else the split
            # is lost and p goes on
            solids = sorted(result.Solids, key=lambda solid: solid.BoundBox.Center.x)
            x0, _, x1, _ = record["rect"]
            claims = {}
            if len(solids) > 1:
                for pid in recs:
                    if own[pid][1] in ("L", "R"):
                        claims[pid] = solids[0] if own[pid][1] == "L" else solids[-1]
                held = {id(solid) for solid in claims.values()}
                if len(claims) == len(held) == len(solids):
                    shapes[p] = result
                else:
                    claims = {}
                dead.add(p)
            else:
                # 10.12 amendment (Onshape Q13, SPLIT_NO_CHANGE): one solid, the split is gone:
                # p goes on with it, the pieces are no parts and picks of them resolve to p
                shapes[p] = result
                applied.add((record["name"], p))
                vanished.update(recs)
            for pid in recs:
                parentOf[pid] = p
                madePieces.add(pid)
                if pid in claims:
                    shapes[pid] = claims[pid]
                elif pid not in vanished:
                    failed.add(pid)
        # Its records of a parent it doesn't act on hold nothing (the parent stays split); a
        # leftover (H1a) holds the tool when it touches no part of the scope
        bases = [shapes[p] for p in resolved[record["name"]] if p in shapes]
        left = (
            record["op"] != "Subtraction" and bool(bases)
            and all(tool.distToShape(base)[0] > 1e-7 for base in bases)
        )
        for pid, (parent, _) in sorted(own.items()):
            if pid in madePieces:
                continue
            madePieces.add(pid)
            if parent:
                parentOf[pid] = parent
                dead.add(parent)
                failed.add(pid)
            elif left:
                shapes[pid] = tool
                left = False  # one solid: the first record holds it
            else:
                failed.add(pid)
    if live is not None:
        live.update(
            p for p in shapes if p not in consumed and p not in dead and p not in madePieces
        )
        live.update(made)
        live.update(
            "piece:" + pid for pid in madePieces
            if pid not in consumed and pid not in dead and pid not in vanished
        )
    out = {p: (round(s.Volume, 4), len(s.Solids)) for p, s in shapes.items() if p not in madePieces}
    out.update(
        {
            "piece:" + pid: "failed" if pid in failed or pid not in shapes else
            (round(shapes[pid].Volume, 4), len(shapes[pid].Solids))
            for pid in madePieces if pid not in vanished
        }
    )
    out.update({k: (0.0, 0) if s is None else (round(s.Volume, 4), len(s.Solids)) for k, s in made.items()})
    return out


def joins(a, b):
    """Whether solids a and b join (10.13, skeptic 3): they meet, and their fuse has fewer solids
    than its inputs (an overlap or a face in common, never an edge or a vertex)."""
    if a.distToShape(b)[0] > 1e-7:
        return False
    return len(a.fuse(b).Solids) < len(a.Solids) + len(b.Solids)


def spans(doc, y):
    """The x spans of the gate's slots (y -1, P6p) or merge bars (y 3, 10.13) in doc"""
    return [
        (r["rect"][0], r["rect"][2])
        for r in (ownerRecord(o) for o in doc.Objects
                  if o.TypeId == "Part::Box" and hasattr(o, "Operation")
                  and round(o.Placement.Base.y) == y)
    ]


def clear(offsets, width, taken, base):
    """All the offsets: a merge bar may bridge a slot again. The 10.13 gate round left bridges out
    (work/hub7/gate/probe-cross.txt, X8 and X10: a bar over a slot before it in the list keeps
    both sides of the cut on one solid, and P6p's matchPieces gave that solid to the stronger
    record and failed the other loudly); the 10.12 amendment (Onshape Q13) makes such a split gone:
    the unsplit part keeps its id and picks of either piece resolve to it."""
    return offsets


def stranded(doc):
    """Raises when an Add the edit's recompute made merge a part leaves a Body member of that part
    after it (10.13: no part to act on, a projection error, loud by design: every list edit is
    refused until it moves). The gate takes it as the edit refused: aborted, nothing changes."""
    lst = PartDesign.studioList(doc.getObject("S"))
    if lst is None:
        return
    try:
        PartDesign.studioProject(lst)
    except Exception as e:
        if "merged into" in str(e):
            raise ValueError(f"stranded by a merge: {e}") from None


def merges(owner):
    """owner's merge record (StudioMergedParts, 10.13; none until it first merges)."""
    return list(getattr(owner, "StudioMergedParts", []))


def liveKey(body):
    """A part as the oracle names it: its name, a part made from a piece by its part id, or a
    New mirror's part by its maker."""
    if body.StudioPieceWitness:
        return "piece:" + body.StudioPartId
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
    pieceBodies = [
        b for b in doc.Objects if b.TypeId == "PartDesign::Body" and b.StudioPieceWitness
    ]
    # P8a: the Part oracle doesn't model a fillet, and a rounded part changes what later
    # records do with it (a merge's contact, a copy's shape): with a fillet active anywhere,
    # G1, G2, the step counts and the hygiene below check the state
    geometric = not any(
        activeFillet(b) for b in doc.Objects if b.TypeId == "PartDesign::Body"
    )
    if geometric:
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
            if activeFillet(body):
                if got[1] != want[body.Name][1]:
                    found.append(f"{body.Name}: Tip solids {got[1]}, oracle {want[body.Name][1]}")
                continue  # P8a: rounded, which the oracle doesn't model
            if got != want[body.Name]:
                found.append(f"{body.Name}: Tip {got}, oracle {want[body.Name]}")
            if not body.isRolledBack() and not body.Shape.isNull():
                volume = round(body.Shape.Volume, 4)
                if volume != want[body.Name][0]:
                    found.append(f"{body.Name}: Body {volume}, oracle {want[body.Name][0]}")
        # P6p: each part made from a piece, live at the bar: its Tip's solid, or failing when its
        # record holds nothing (a piece's Tip fails too when a later feature in it fails: then only
        # the solid is checked, as for any part)
        for body in pieceBodies:
            key = "piece:" + body.StudioPartId
            if key not in live:
                continue
            tip = body.Tip
            expected = want.get(key)
            if expected == "failed":
                if tip is not None and tip.isValid() and tip.StudioOwner == body.StudioMadeBy:
                    found.append(f"{key} ({body.Name}): piece step valid, oracle: holds nothing")
                continue
            shape = tip.Shape if tip else Part.Shape()
            got = (0.0 if shape.isNull() else round(shape.Volume, 4), len(shape.Solids))
            if activeFillet(body) and expected:
                got, expected = got[1], expected[1]  # P8a: the solids only
            if got != expected:
                found.append(f"{key} ({body.Name}): Tip {got}, oracle {expected}")
            parent = body.StudioParentId
            if parent and not any(
                b.StudioPartId == parent for b in doc.Objects if b.TypeId == "PartDesign::Body"
            ):
                found.append(f"{key}: its parent {parent} is gone")
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
    # P8a: a Fillet owner has one step in each part its scope resolves to, none elsewhere
    for owner in studioList(doc).Entries:
        if isFillet(owner):
            scope = sorted(b.Name for b in PartDesign.studioScopeOf(owner))
            steps = sorted(
                b.Name
                for b in doc.Objects
                if b.TypeId == "PartDesign::Body"
                and any(getattr(o, "StudioOwner", None) == owner for o in b.Group)
            )
            if scope != steps:
                found.append(f"{owner.Name}: steps in {steps}, scope {scope}")
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
            elif r.get("fillet"):
                picks = []
                for text in r["picks"]:
                    part, _, name = text.partition("|")
                    picks.append(part + "|" + unmasked(name, doc))
                box = makeFillet(doc, studio, r["name"], r["radius"], picks, r["suppressed"])
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
        return snapshot(doc)
    finally:
        App.closeDocument(doc.Name)


def differences(got, want):
    out = [f"{p}: in the document only" for p in got if p not in want]
    for p in want:
        for key in want[p]:
            if got.get(p, {}).get(key) != want[p][key]:
                if key == "names":
                    a, b = set(got.get(p, {}).get(key, [])), set(want[p][key])
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


def activeKey(studio):
    """The studio's active configuration key, or "" without configuration inputs (ops#671)"""
    try:
        return PartDesign.configKey(studio)
    except Exception:
        return ""


class TestStudioListProperty(unittest.TestCase):
    """After every random edit the document equals the one built from scratch from its list."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="studiolist")
        self.log = []
        self.consumedSeen = 0  # states after an edit with a part consumed at the bar (P5)
        self.patternsSeen = 0  # valid patterns of an owner, summed over the states (slice 8)
        self.mirrorsSeen = 0  # valid part mirrors, summed over the states (slice 9)
        self.piecesSeen = 0  # states with a live part made from a piece (P6p)
        self.unlistedSeen = 0  # states without a list after an edit, undo or reopen (ops#654)
        self.mergesSeen = 0  # states with a part an Add merged into another at the bar (10.13)
        self.lateSeen = 0  # edits committed, then recomputed outside the transaction (10.15)
        self.filletsSeen = 0  # states with a part a Fillet owner rounds at the bar (P8a)
        self.switchesSeen = 0  # switches of the active configuration (ops#671 C1)
        self.switchRefusals = 0  # switches the list refused loudly (a split or merge before)

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
        kinds += ["merge", "merge", "fillet", "fillet"]
        kind = rng.choice(kinds) if boxes else rng.choice(["insert", "insert", "boolean"])
        if kind == "pattern" and not shapeOwners:
            kind = "insert"
        if kind == "fillet":
            # P8a: a Fillet owner r 0.5 or 1 on a random edge of one or two random parts (their
            # shapes at the bar, as a pick is made), anywhere in the list
            names = [p for p, _ in PARTS if not doc.getObject(p).Shape.isNull()]
            picks = []
            for p in rng.sample(names, min(rng.randint(1, 2), len(names))):
                body = doc.getObject(p)
                edge = f"Edge{rng.randint(1, len(body.Shape.Edges))}"
                try:
                    picks.append(PartDesign.studioPickId(body, edge))
                except ValueError:
                    pass
            radius = rng.choice([0.5, 1])
            at = rng.randint(0, free)
            owner = makeFillet(doc, doc.getObject("S"), f"F{counter}", radius, picks)
            PartDesign.studioInsert(owner, NATIVES + at)
            parts = [t.split("|")[0] for t in picks]
            return f"fillet {owner.Name} r{radius} picks {parts} at {at}"
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
        if kind == "merge":
            # 10.13: an Add bar (y 3..7, 15 long) over two neighbouring parts, both in its scope in
            # a random order (the first listed survives); its x decides whether it joins one part
            # or both (the random parameter)
            pair = rng.choice([("A", "B"), ("B", "C")])
            base = dict(PARTS)[pair[0]]
            x0 = base + rng.choice(clear([2, 6, 8, 12, 14], 15, spans(doc, -1), base))
            rect = [x0, 3, x0 + 15, 7]
            scope = list(pair)
            rng.shuffle(scope)
            at = rng.randint(0, free)
            box = makeOwner(doc, doc.getObject("S"), f"F{counter}", rect, rng.choice([1, 2]),
                            "Union", scope)
            PartDesign.studioInsert(box, NATIVES + at)
            return f"merge {box.Name} {rect} scope {scope} at {at}"
        if kind == "split":
            # P6p: a slot through a part (its x the random parameter), and its command
            p, px = rng.choice(PARTS)
            x = px + rng.choice(clear([3, 4, 5, 6], 1, spans(doc, 3), px))
            rect = [x, -1, x + 1, 11]
            at = rng.randint(0, free)
            box = makeOwner(doc, doc.getObject("S"), f"F{counter}", rect, 11, "Subtraction", [p])
            PartDesign.studioInsert(box, NATIVES + at)
            made = PartDesign.studioMakePieces(box)
            labelPieces(made, box)
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
        if isFillet(box) and kind in ("scope", "depth"):
            # P8a: its radius, read by its steps when they run
            box.Radius = 1.5 - box.Radius.Value  # 0.5 <-> 1
            return f"radius {name} {box.Radius.Value}"
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
                # P6p: a moved feature's command (the drag's)
                labelPieces(PartDesign.studioMakePieces(box), box)
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
            px = dict(PARTS)[p]
            x = px + rng.choice(clear([3, 4, 5, 6], 1, spans(doc, 3), px))
            setBox(box, [x, -1, x + 1, 11], 11, "Subtraction")
            PartDesign.studioReconcile(lst)
            made = PartDesign.studioMakePieces(box)
            labelPieces(made, box)
            return f"slot {name} at x {x}: {len(made)} new parts"
        if kind == "depth" and box.TypeId == "Part::Box" and round(box.Placement.Base.y) == 3:
            # 10.13: the Add bar moved, which can join a second part or let it go (its edit's OK
            # is the command)
            r = ownerRecord(box)
            x0 = r["rect"][0] + rng.choice(clear([-6, -4, 4, 6], 15, spans(doc, -1), r["rect"][0]))
            setBox(box, [x0, 3, x0 + 15, 7], r["depth"], "Union")
            PartDesign.studioReconcile(lst)
            labelPieces(PartDesign.studioMakePieces(box), box)
            return f"bar {name} at x {x0}"
        if kind == "depth":
            r = ownerRecord(box)
            depth = rng.choice([1, 2, 3, 4, 5])
            if PartDesign.configIsConfigured(box, "Height"):
                # ops#671: a configured field's edit writes the active row's cell (CF3)
                box.setExpression("Height", f"{depth + 0.001} mm")
                PartDesign.studioReconcile(lst)
                return f"depth {name} {depth} (its active cell)"
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

    def switch(self, rng, doc):
        """ops#671 C1's edit: configure an owner (a Union box's height, or any owner's
        suppression) by the List Size (Small, Large), then switch the active row. The document at
        the new row is then compared with the from-scratch build of its list like after any edit,
        and its names after a switch and back with the names before (G1). None while the studio
        has no list."""
        studio = doc.getObject("S")
        if PartDesign.studioList(studio) is None:
            return None
        key = activeKey(studio)
        if not key:
            PartDesign.configAddList(studio, "Size", ["Small", "Large"])
            key = activeKey(studio)
        size, row = key.split(";")[0].split("=")
        other = "Large" if row == "Default" else "Small"
        unions = [
            b for b in owners(doc)
            if b.TypeId == "Part::Box" and b.Operation == "Union" and round(b.Placement.Base.y) not in (-1, 3)
            and not PartDesign.configIsConfigured(b, "Height")
        ]
        plain = [
            b for b in owners(doc)
            if not isPartMirror(b) and not PartDesign.configIsConfigured(b)
        ]
        done = []
        roll = rng.random()
        if unions and roll < 0.4:
            b = rng.choice(unions)
            PartDesign.configConfigure(b, "Height", size)
            depth = rng.choice([1, 2, 3, 4, 5])
            PartDesign.configSetCell(b, "Height", other, f"{depth + 0.001} mm")
            done.append(f"{b.Name}.Height {other} d{depth}")
        elif plain and roll < 0.7:
            b = rng.choice(plain)
            PartDesign.configConfigureSuppression(b, size)
            on = not bool(getattr(b, "Suppressed", False))
            PartDesign.configSetSuppressionCell(b, other, on)
            done.append(f"{b.Name} suppressed {on} in {other}")
        doc.recompute()
        before = snapshot(doc)

        def switchTo(value):
            PartDesign.configSetActive(studio, {"Size": value})
            # The parts the switch made from pieces get their side for the Part oracle, as
            # the command's do (labelPieces: the side is the solid's, so a piece that comes
            # back with its id comes back on its side)
            for body in doc.Objects:
                maker = getattr(body, "StudioMadeBy", None)
                if (
                    body.TypeId == "PartDesign::Body" and body.StudioPieceWitness
                    and not hasattr(body, "OracleSide") and maker is not None
                    and maker.TypeId == "Part::Box"
                ):
                    labelPieces([body], maker)

        switchTo(other)
        switchTo("Small" if other == "Large" else "Large")
        doc.recompute()
        found = differences(snapshot(doc), before)
        if found:
            raise AssertionError("the names after a switch and back differ: " + "; ".join(found[:6]))
        switchTo(other)
        self.switchesSeen += 1
        return f"switch to {other}" + (f" after configuring {done}" if done else "")

    def run_sequence(self, seed, nops):
        rng = random.Random(seed)
        late = random.Random(f"late{seed}")
        doc, _ = propStudio(f"prop{seed}")
        path = os.path.join(self.dir, f"prop{seed}.FCStd")
        # ops#654 list on first use: these seeds start from the document without a list (its
        # parts' sketches and Pads in-Body), and the first edit makes it in its own transaction by
        # the call the studio commands make (PartDesign.studioList(studio, True), in edit()); until
        # then, and after that edit's undo, the document is its start, unlisted
        unlisted = seed in {
            int(s) for s in os.environ.get("STUDIO_PROP_UNLISTED", "2,4,6").split(",") if s
        }
        start = snapshot(doc)
        if not unlisted:
            studioList(doc)
        bad = 0
        switching = os.environ.get("STUDIO_PROP_SWITCH", "1") == "1"
        for step in range(nops):
            switched = None
            side = random.Random(seed * 100003 + step)
            if switching and step and side.random() < 0.2:
                doc.openTransaction("switch")
                try:
                    switched = self.switch(side, doc)
                    doc.recompute()
                    doc.commitTransaction()
                except Exception as e:
                    doc.abortTransaction()
                    # The list's loud refusals (an owner in a part another row splits or merges
                    # before it) refuse the switch as they refuse an edit: nothing changes
                    refusals = ("split before it", "makes after it", "merged into")
                    if any(r in str(e) for r in refusals):
                        self.switchRefusals += 1
                    else:
                        bad += 1
                        self.log.append(f"seed {seed} op {step} switch failed: {e}")
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
                # 10.15: some edits are committed first and recomputed after, outside the
                # transaction (Python's commitTransaction() then recompute(), the property
                # editor's commit then recompute). Drawn from a stream of its own, so the seeds'
                # edits stay as they were
                committedFirst = late.random() < 0.25
                committed = False
                doc.openTransaction("edit")
                try:
                    what = self.edit(rng, doc, step + 1)
                    if committedFirst:
                        # The resync after the recompute records into the edit's step, so its
                        # undo takes what the resync made of it too (ops#654 10.15)
                        doc.commitTransaction()
                        committed = True
                        doc.recompute()
                        what += " (committed, then recomputed)"
                        self.lateSeen += 1
                        stranded(doc)
                    else:
                        # The command's recompute is in its transaction, as every GUI command
                        # and dialog OK does it (recompute, then commit): what the recompute
                        # decides and the projection takes after it (a Union's tools apart, a
                        # part mirror's consumption, a lost split) goes with the edit's undo
                        # step (seed 3, edit 63, ops#654 P6p open item a)
                        doc.recompute()
                        stranded(doc)
                        doc.commitTransaction()
                except Exception as e:
                    if committed:
                        doc.undo()  # refused after its commit: its undo takes it all back
                    else:
                        doc.abortTransaction()
                    what = f"refused: {e}"
                    # P6p: a member placed in a part after its split, or in a piece before the
                    # split, is refused loudly by design (nothing changes); so is one placed in a
                    # part after an Add merged it into another (10.13)
                    refusals = ("split before it", "makes after it", "merged into")
                    if not any(r in str(e) for r in refusals):
                        bad += 1
                        self.log.append(f"seed {seed} op {step} {what}")
            doc.recompute()
            if unlisted and step == 0 and doc.UndoCount:
                # The first edit's undo takes the list back with it: the start, unlisted; redo
                doc.undo()
                doc.recompute()
                if PartDesign.studioList(doc.getObject("S")) is not None:
                    bad += 1
                    self.log.append(f"seed {seed}: the first edit's undo kept the list")
                found = ["first undo " + d for d in differences(snapshot(doc), start)]
                if found:
                    bad += 1
                    self.log.append(f"seed {seed} after the first edit's undo:")
                    self.log.extend("    " + d for d in found)
                self.unlistedSeen += 1
                doc.redo()
                doc.recompute()
            if switched:
                what = f"{switched}, then {what}"
            got = snapshot(doc)
            if PartDesign.studioList(doc.getObject("S")) is None:
                self.unlistedSeen += 1
                self.assertTrue(unlisted, f"seed {seed} op {step}: the list is gone after {what}")
                found = ["unlisted " + d for d in differences(got, start)]
                if found:
                    bad += 1
                    self.log.append(f"seed {seed} op {step} after {what} (no list):")
                    self.log.extend("    " + d for d in found)
                continue
            want = fromScratch(*listOf(doc), maker=propStudio)
            found = differences(got, want)
            if activeKey(doc.getObject("S")):
                check = PartDesign.configReconcile(doc.getObject("S"))
                if check:
                    found.append("configuration check: " + check)
            found += ["oracle " + d for d in oracleDifferences(doc)]
            found += ["G1 " + d for d in gateG1(doc)[:4]]
            # A part consumed at the bar by a Boolean or a part mirror (a split's parent, P6p,
            # is no consumed part here)
            consumers = [PartDesign.studioConsumerOf(doc.getObject(p)) for p, _ in PARTS]
            if any(c is not None and c.TypeId != "Part::Box" for c in consumers):
                self.consumedSeen += 1
            if any(c is not None and merges(c) for c in consumers):
                self.mergesSeen += 1
            if any(b.StudioPieceWitness for b in PartDesign.studioLiveParts(studioList(doc))):
                self.piecesSeen += 1
            if any(activeFillet(b) for b in doc.Objects if b.TypeId == "PartDesign::Body"):
                self.filletsSeen += 1
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
        self.assertGreater(self.mergesSeen, 0)
        self.assertGreater(self.lateSeen, 0)
        self.assertGreater(self.filletsSeen, 0)
        if os.environ.get("STUDIO_PROP_SWITCH", "1") == "1":
            self.assertGreater(self.switchesSeen, 0)  # ops#671: a switch was compared
        unlisted = os.environ.get("STUDIO_PROP_UNLISTED", "2,4,6").split(",")
        if any(str(s) in unlisted for s in seeds):
            self.assertGreater(self.unlistedSeen, 0)  # ops#654: an unlisted start was checked
        print(f"testRandomEdits: {len(seeds)} seeds x {nops} edits, {self.consumedSeen} states "
              f"with a consumed part, {self.patternsSeen} valid patterns, {self.mirrorsSeen} valid "
              f"part mirrors seen, {self.piecesSeen} states with a live piece, {self.unlistedSeen} "
              f"states without a list, {self.mergesSeen} states with a merge, {self.lateSeen} "
              f"edits committed before their recompute, {self.filletsSeen} states with a fillet, "
              f"{self.switchesSeen} switches, {self.switchRefusals} refused")


if __name__ == "__main__":
    unittest.main()
