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
# list: each Body's chain in order (steps by owner name), its Tip, volume, area, solid count, the
# steps in error, and the element names with object IDs written as object names. And the names
# gate (one-history rule 3, a hard assertion): delete every step, regenerate them all from the
# list, and every Body's element names are identical. STUDIO_PROP_SEEDS (e.g. "1,2,3") and
# STUDIO_PROP_OPS set the size for a long run.

import os
import random
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.Scenarios.harness import Masker
from PartDesignTests.TestStudio import pad, sketch, xyPlane

V = App.Vector
PARTS = (("A", 0), ("B", 20), ("C", 40))
NATIVES = 6  # each part's sketch and Pad, first in the list


# ------------------------------------------------------------------------------------- the model
def newStudio(name, parts=PARTS):
    doc = App.newDocument(name)
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


def ownerRecord(box):
    p = box.Placement.Base
    op = box.Operation
    depth = round(box.Height.Value - 0.001, 6)
    rect = [
        round(p.x, 6),
        round(p.y, 6),
        round(p.x + box.Length.Value, 6),
        round(p.y + box.Width.Value, 6),
    ]
    return dict(
        name=box.Name,
        rect=rect,
        depth=depth,
        op=op,
        scope=list(box.StudioScope),
        suppressed=bool(getattr(box, "Suppressed", False)),
    )


def studioList(doc):
    return PartDesign.studioList(doc.getObject("S"), True)


def owners(doc):
    return [e for e in studioList(doc).Entries if e.TypeId == "Part::Box"]


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
    last = group.index(body.Tip) if body.Tip in group else len(group) - 1
    chain = chainOf(body)
    return sorted(chain[i] for i, o in enumerate(group[: last + 1]) if not o.isValid())


def snapshot(doc, names=True):
    out = {}
    masker = Masker(doc) if names else None
    for p, _ in PARTS:
        body = doc.getObject(p)
        if body is None:
            continue
        tip = body.Tip
        shape = body.Shape
        out[p] = dict(
            chain=chainOf(body),
            suppressed=sorted(o.StudioOwner.Name for o in body.Group if isStep(o) and o.Suppressed),
            tip=(tip.StudioOwner.Name if isStep(tip) else tip.Name) if tip else None,
            volume=0.0 if shape.isNull() else round(shape.Volume, 4),
            area=0.0 if shape.isNull() else round(shape.Area, 4),
            solids=0 if shape.isNull() else len(shape.Solids),
            failed=failedUpToTip(body),
        )
        if names:
            out[p]["names"] = elementNames(shape, masker)
    return out


def listOf(doc):
    """The list as data: the owners in order with their values, and the bar among them."""
    lst = studioList(doc)
    entries = list(lst.Entries)
    bar = lst.Bar if 0 <= lst.Bar < len(entries) else len(entries)
    records = [ownerRecord(e) for e in entries if e.TypeId == "Part::Box"]
    natives = [e.Name for e in entries if e.TypeId != "Part::Box"]
    return natives, records, bar


def deleteSteps(doc):
    for p, _ in PARTS:
        body = doc.getObject(p)
        for obj in list(body.Group):
            if isStep(obj):
                body.removeObject(obj)
                doc.removeObject(obj.Name)


def fromScratch(natives, records, bar, gate=None):
    """The document built from scratch from the list: the same parts, the owners appended in the
    list's order, then the bar. With gate (a list), the names gate runs on it too: every step
    deleted and regenerated from the list gives identical names; differences go into gate."""
    doc, studio = newStudio("scratch")
    try:
        lst = studioList(doc)
        assert [e.Name for e in lst.Entries] == natives, ([e.Name for e in lst.Entries], natives)
        for r in records:
            box = makeOwner(
                doc, studio, r["name"], r["rect"], r["depth"], r["op"], r["scope"], r["suppressed"]
            )
            assert box.Name == r["name"], (box.Name, r["name"])
            PartDesign.studioInsert(box, -1)
        PartDesign.studioSetBar(lst, bar if bar < len(lst.Entries) else -1)
        doc.recompute()
        snap = snapshot(doc)
        if gate is not None:
            before = partNames(doc)
            deleteSteps(doc)
            PartDesign.studioReconcile(lst)
            doc.recompute()
            after = partNames(doc)
            for p in before:
                if before[p] != after[p]:
                    gate.append((p, sorted(set(before[p]) ^ set(after[p]))[:6]))
        return snap
    finally:
        App.closeDocument(doc.Name)


def differences(got, want):
    out = []
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
        self.assertEqual(self.step(f1, "A").Name, "F1_A")

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
        self.assertEqual(boss.BaseFeature.Name, "F1_B")
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

    def testNamesGate(self):
        """One-history rule 3 in one document: every step deleted and regenerated from the list
        gives every Body identical element names."""
        self.owner("F1", [5, 2, 25, 8], 2, "Subtraction", ["A", "B"])
        self.owner("F2", [22, 2, 26, 6], 3, "Union", ["B"])
        self.owner("F3", [2, 4, 8, 9], 1, "Subtraction", ["A"])
        before = partNames(self.doc)
        ids = self.stepIds()
        deleteSteps(self.doc)
        PartDesign.studioReconcile(self.list)
        self.doc.recompute()
        regenerated = self.stepIds()
        self.assertEqual(sorted(ids), sorted(regenerated))
        self.assertTrue(all(ids[n] != regenerated[n] for n in ids))  # new objects
        self.assertEqual(partNames(self.doc), before)

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


# ------------------------------------------------------------------------------------- random edits
def touches(rect):
    x0, _, x1, _ = rect
    return [p for p, x in PARTS if x0 < x + 10 and x1 > x]


class TestStudioListProperty(unittest.TestCase):
    """After every random edit the document equals the one built from scratch from its list."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="studiolist")
        self.log = []

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith(("prop", "scratch")):
                App.closeDocument(doc.Name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def edit(self, rng, doc, counter):
        lst = studioList(doc)
        boxes = owners(doc)
        kinds = ["insert"] * 3 + ["delete", "move", "scope", "depth", "suppress", "bar"]
        kind = rng.choice(kinds) if boxes else "insert"
        if kind == "insert":
            x0 = rng.choice([2, 5, 8, 22, 25, 42, 45, 5, 25])
            w = rng.choice([2, 4, 8, 20, 25])
            y0 = rng.choice([1, 2, 4])
            rect = [x0, y0, x0 + w, y0 + rng.choice([2, 3, 5])]
            parts = touches(rect) or ["A"]
            scope = sorted(rng.sample(parts, rng.randint(1, len(parts))))
            op = rng.choice(["Subtraction", "Subtraction", "Union"])
            depth = rng.choice([1, 2, 3, 4])
            at = rng.randint(0, len(boxes))
            box = makeOwner(doc, doc.getObject("S"), f"F{counter}", rect, depth, op, scope)
            PartDesign.studioInsert(box, NATIVES + at)
            return f"insert {box.Name} {op} {rect} d{depth} scope {scope} at {at}"
        box = rng.choice(boxes)
        name = box.Name
        if kind == "delete":
            PartDesign.studioRemove(box)
            doc.removeObject(name)
            return f"delete {name}"
        if kind == "move":
            j = rng.randrange(len(boxes))
            PartDesign.studioMove(box, NATIVES + j)
            return f"move {name} -> {j}"
        if kind == "scope":
            scope = list(box.StudioScope)
            p = rng.choice([p for p, _ in PARTS])
            if p in scope and len(scope) > 1:
                scope.remove(p)
            elif p not in scope:
                scope = sorted(scope + [p])
            PartDesign.studioSetScopeIds(box, scope)
            return f"scope {name} {scope}"
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
        doc, _ = newStudio(f"prop{seed}")
        path = os.path.join(self.dir, f"prop{seed}.FCStd")
        studioList(doc)
        bad = 0
        gate = []
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
                    bad += 1
            doc.recompute()
            got = snapshot(doc)
            want = fromScratch(*listOf(doc), gate=gate)
            found = differences(got, want)
            if gate:
                found.append(f"names gate: {gate[:2]}")
                gate.clear()
            if found:
                bad += 1
                self.log.append(f"seed {seed} op {step} after {what}:")
                self.log.extend("    " + d for d in found)
                if bad > 3:
                    break
        # The names gate on the edited document itself: its steps deleted and made again
        if not bad:
            before = partNames(doc)
            deleteSteps(doc)
            PartDesign.studioReconcile(studioList(doc))
            doc.recompute()
            if partNames(doc) != before:
                bad += 1
                self.log.append(f"seed {seed}: names changed when every step was made again")
        App.closeDocument(doc.Name)
        return bad

    def testRandomEdits(self):
        seeds = [int(s) for s in os.environ.get("STUDIO_PROP_SEEDS", "1,2,3").split(",") if s]
        nops = int(os.environ.get("STUDIO_PROP_OPS", "25"))
        total = sum(self.run_sequence(seed, nops) for seed in seeds)
        self.assertEqual(total, 0, "\n".join(self.log))


if __name__ == "__main__":
    unittest.main()
