# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (asm-patterns): assembly instance patterns, as Onshape's assembly Linear and Circular
# pattern. Design note: notes/assembly-patterns-design.md in the ops repo.
#
# A pattern is an object of the assembly's joint group. For each seed (an instance of the
# assembly) and each i in 1..Count-1 it owns one copy: an App::Link in the assembly's Group, so the
# instance list and the BOM count it as Onshape does. Copy i of a seed is placed at
#   Linear:   Translate(i * Distance * d) * seed
#   Circular: Rotate(axis, i * step) * seed
# with d and the axis read in the assembly's frame from the Direction reference. A linear pattern
# with SecondDirection on (Onshape's enableDirection2) owns a copy for each grid cell (i, j) but the
# seed's (0, 0), j in 0..Count2-1, at Translate(i * Distance * d + j * Distance2 * d2) * seed
# (PatternIndex i, PatternIndex2 j; a copy with no PatternIndex2 is on the seed's row). The solver
# (AssemblyObject.cpp) gives a seed and its copies one solver body, and calls placeInstances()
# before and after each solve, so the copies follow their seed and mates to copies hold.

import math
import re

import weakref

import FreeCAD as App
import Part

from PySide.QtCore import QT_TRANSLATE_NOOP

if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets

translate = App.Qt.translate

__title__ = "Assembly instance patterns"

PATTERN_TYPES = ["Linear", "Circular"]
# Placements closer than this are the same (mm, and radians for the rotation)
TOLERANCE = 1e-7
# The pattern panel that is open (as JointObject.activeTask)
activePanel = None


def reachOf(seed):
    """How far the seed's shape reaches from its placement's origin (mm; 100 when it has none)"""
    try:
        box = seed.Shape.BoundBox
    except Exception:
        return 100.0
    if not box.isValid():
        return 100.0
    origin = seed.Placement.Base
    corners = [App.Vector(x, y, z) for x in (box.XMin, box.XMax) for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
    return max((c - origin).Length for c in corners)


def hasExpression(obj, name):
    """Whether an expression drives obj's property name"""
    return any(path == name for path, _ in obj.ExpressionEngine)


def isPattern(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == InstancePattern.Type


def assemblyOf(fp):
    """The assembly whose joint group holds fp"""
    for parent in fp.InList:
        if parent.isDerivedFrom("Assembly::AssemblyObject"):
            return parent
        if parent.TypeId == "Assembly::JointGroup":
            for grand in parent.InList:
                if grand.isDerivedFrom("Assembly::AssemblyObject"):
                    return grand
    return None


def sourceOf(seed):
    """What a copy of seed links to: the seed's linked object, or the seed itself"""
    if seed.isDerivedFrom("App::Link") or seed.isDerivedFrom("Assembly::AssemblyLink"):
        linked = seed.LinkedObject
        if linked is not None:
            return linked
    return seed


def instanceLabel(assembly, source):
    """Onshape's instance name, "<source> <N>", N the lowest number free (as Insert names them,
    CommandInsertLink.instanceLabel)"""
    base = source.Label
    taken = set()
    pattern = re.compile(re.escape(base) + r" <(\d+)>$")
    for obj in assembly.Group:
        match = pattern.match(obj.Label)
        if match:
            taken.add(int(match.group(1)))
    duplicates = App.ParamGet("User parameter:BaseApp/Preferences/Document").GetBool(
        "DuplicateLabels", False
    )
    doc = assembly.Document
    n = 1
    while n in taken or (not duplicates and doc.getObjectsByLabel(f"{base} <{n}>")):
        n += 1
    return f"{base} <{n}>"


def patternLabel(assembly, kind):
    """"Linear pattern 1", "Circular pattern 2"... (Onshape's feature names)"""
    base = f"{kind} pattern"
    taken = {o.Label for o in assembly.Document.Objects}
    n = 1
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


def referenceAxis(fp, second=False):
    """(point, unit direction) of the pattern's Direction reference (Direction2 with second) in the
    assembly's frame. Raises RuntimeError with the reason when the reference is missing or its
    element is gone."""
    ref = getattr(fp, "Direction2", None) if second else fp.Direction
    if second:
        what = "second direction"
    else:
        what = "axis" if fp.PatternType == "Circular" else "direction"
    if not ref or ref[0] is None:
        raise RuntimeError(translate("Assembly", "{0}: pick a {1}").format(fp.Label, what))
    obj, subs = ref[0], ref[1]
    sub = subs[0] if subs else ""
    name = f"{obj.Label}.{sub}" if sub else obj.Label
    try:
        shape = Part.getShape(obj, sub, needSubElement=True, transform=True)
    except Exception:
        shape = None
    if shape is None or shape.isNull():
        raise RuntimeError(
            translate("Assembly", "{0}: the {1} reference {2} is gone").format(fp.Label, what, name)
        )
    axis = axisOfShape(shape)
    if axis is None:
        raise RuntimeError(
            translate("Assembly", "{0}: {1} gives no {2} (pick a straight or circular edge, a plane or a cylinder)").format(
                fp.Label, name, what
            )
        )
    return axis


def axisOfShape(shape):
    """(point, unit direction) of a straight or circular edge, a plane (its normal) or a cylinder
    or cone (its axis); None for anything else"""
    if shape.ShapeType == "Edge":
        curve = shape.Curve
        kind = type(curve).__name__
        if kind in ("Line", "LineSegment"):
            points = [v.Point for v in shape.Vertexes]
            if len(points) >= 2 and (points[-1] - points[0]).Length > TOLERANCE:
                return points[0], (points[-1] - points[0]).normalize()
            return App.Vector(curve.Location), App.Vector(curve.Direction).normalize()
        if hasattr(curve, "Axis") and hasattr(curve, "Center"):
            # The axis the edge turns about (right hand), whichever way its curve is parametrized
            axis = App.Vector(curve.Axis).normalize()
            return App.Vector(curve.Center), -axis if shape.Orientation == "Reversed" else axis
        return None
    if shape.ShapeType == "Face":
        surface = shape.Surface
        kind = type(surface).__name__
        if kind == "Plane":
            u0, u1, v0, v1 = shape.ParameterRange
            u, v = (u0 + u1) / 2, (v0 + v1) / 2
            return shape.valueAt(u, v), App.Vector(shape.normalAt(u, v)).normalize()
        if kind in ("Cylinder", "Cone") and hasattr(surface, "Axis"):
            # The axis that turning about (right hand) with the outward normal goes the face's way
            # round: a Part cylinder's side face is reversed on a -Z surface axis, and gives +Z
            center = surface.Center if hasattr(surface, "Center") else surface.Apex
            axis = App.Vector(surface.Axis).normalize()
            return App.Vector(center), -axis if shape.Orientation == "Reversed" else axis
        return None
    if shape.ShapeType in ("Wire", "Compound") and len(shape.Edges) == 1:
        return axisOfShape(shape.Edges[0])
    return None


class InstancePattern:
    """The proxy of an assembly pattern (App::FeaturePython in the joint group)"""

    Type = "Assembly::InstancePattern"

    def __init__(self, fp, kind="Linear"):
        fp.Proxy = self
        self.setProperties(fp)
        fp.PatternType = kind

    def setProperties(self, fp):
        def add(kind, name, doc):
            if not hasattr(fp, name):
                fp.addProperty(kind, name, "Pattern", doc)

        add("App::PropertyEnumeration", "PatternType", QT_TRANSLATE_NOOP("App::Property", "Linear or Circular"))
        fp.PatternType = PATTERN_TYPES
        add("App::PropertyLinkList", "Seeds", QT_TRANSLATE_NOOP("App::Property", "The instances to pattern"))
        add(
            "App::PropertyXLinkSub",
            "Direction",
            QT_TRANSLATE_NOOP(
                "App::Property",
                "The direction (Linear) or the axis (Circular): a straight or circular edge, a plane, a cylinder",
            ),
        )
        add("App::PropertyLength", "Distance", QT_TRANSLATE_NOOP("App::Property", "The distance between neighbouring instances (Linear)"))
        add("App::PropertyAngle", "Angle", QT_TRANSLATE_NOOP("App::Property", "The angle between neighbouring instances, or the whole spread with Equal spacing (Circular)"))
        add("App::PropertyBool", "EqualSpacing", QT_TRANSLATE_NOOP("App::Property", "Spread the instances evenly over the angle (Circular)"))
        add("App::PropertyIntegerConstraint", "Count", QT_TRANSLATE_NOOP("App::Property", "The number of instances, the seed included"))
        add("App::PropertyBool", "Reversed", QT_TRANSLATE_NOOP("App::Property", "Pattern the other way"))
        add("App::PropertyBool", "Suppressed", QT_TRANSLATE_NOOP("App::Property", "A suppressed pattern has no copies"))
        add("App::PropertyLinkListHidden", "Instances", QT_TRANSLATE_NOOP("App::Property", "The copies the pattern made"))
        fp.setPropertyStatus("Instances", ["ReadOnly", "Hidden"])
        fp.Count = (max(int(fp.Count), 2) if fp.Count else 2, 1, 100000, 1)
        if fp.Distance.Value == 0:
            fp.Distance = 25.0
        if fp.Angle.Value == 0:
            fp.Angle = 360.0
            fp.EqualSpacing = True
        self.addSecondDirection(fp)

    def addSecondDirection(self, fp):
        """Onshape's second direction of a linear pattern (enableDirection2): its own direction,
        distance, count (the seed's row included) and flip. Off, or at count 1, the pattern is the
        one-direction pattern it was."""
        def add(kind, name, doc):
            if not hasattr(fp, name):
                fp.addProperty(kind, name, "Second direction", doc)
                return True
            return False

        add("App::PropertyBool", "SecondDirection", QT_TRANSLATE_NOOP("App::Property", "Pattern in a second direction too (Linear)"))
        add(
            "App::PropertyXLinkSub",
            "Direction2",
            QT_TRANSLATE_NOOP("App::Property", "The second direction: a straight or circular edge, a plane, a cylinder (Linear)"),
        )
        if add("App::PropertyLength", "Distance2", QT_TRANSLATE_NOOP("App::Property", "The distance between neighbouring instances in the second direction (Linear)")):
            fp.Distance2 = 25.0
        if add("App::PropertyIntegerConstraint", "Count2", QT_TRANSLATE_NOOP("App::Property", "The number of instances in the second direction, the seed's row included (Linear)")):
            fp.Count2 = (1, 1, 100000, 1)
        add("App::PropertyBool", "Reversed2", QT_TRANSLATE_NOOP("App::Property", "Pattern the other way in the second direction (Linear)"))

    def onDocumentRestored(self, fp):
        # Patterns saved before the second direction get its properties (off)
        self.addSecondDirection(fp)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    # --- what the pattern makes -------------------------------------------------------------------

    def secondCount(self, fp):
        """The count in the second direction, 1 when it is off (or the pattern is circular)"""
        if fp.PatternType != "Linear" or not getattr(fp, "SecondDirection", False):
            return 1
        return max(int(fp.Count2), 1)

    def cells(self, fp, count=None):
        """The grid cells (i, j) of the copies, the seed's (0, 0) left out: direction 1's index i
        runs fastest, so a one-direction pattern's cells are (1, 0)..(Count - 1, 0)"""
        count = int(fp.Count) if count is None else count
        rows = self.secondCount(fp) if count > 0 else 0
        return [(i, j) for j in range(rows) for i in range(count) if (i, j) != (0, 0)]

    def transforms(self, fp):
        """[((i, j), placement)]: the placements that take a seed to each copy's cell"""
        count = int(fp.Count)
        rows = self.secondCount(fp)
        if count < 2 and rows < 2:
            return []
        sign = -1.0 if fp.Reversed else 1.0
        result = []
        if fp.PatternType == "Circular":
            point, direction = referenceAxis(fp)
            angle = fp.Angle.Value
            if fp.EqualSpacing:
                full = abs(abs(angle) - 360.0) < 1e-9
                step = angle / count if full else angle / (count - 1)
            else:
                step = angle
            for i in range(1, count):
                rotation = App.Rotation(direction, sign * step * i)
                result.append(((i, 0), App.Placement(App.Vector(), rotation, point)))
            return result
        spacing = App.Vector()
        if count >= 2:
            spacing = referenceAxis(fp)[1] * (sign * fp.Distance.Value)
        spacing2 = App.Vector()
        if rows >= 2:
            sign2 = -1.0 if fp.Reversed2 else 1.0
            spacing2 = referenceAxis(fp, second=True)[1] * (sign2 * fp.Distance2.Value)
        for i, j in self.cells(fp):
            result.append(((i, j), App.Placement(spacing * i + spacing2 * j, App.Rotation())))
        return result

    def seeds(self, fp):
        assembly = assemblyOf(fp)
        members = set(assembly.Group) if assembly else set()
        return [s for s in fp.Seeds if s is not None and s in members and not isPatternCopy(s)]

    def copySeeds(self, fp):
        """The seeds that are another pattern's copies (not patterned: said, not dropped)"""
        return [s for s in fp.Seeds if s is not None and isPatternCopy(s) and s.PatternOwner != fp]

    def copiesBySeed(self, fp):
        """{seed name: {(i, j): copy}} of the copies the pattern holds that its counts want"""
        result = {}
        wanted = set(self.cells(fp))
        for copy in fp.Instances:
            if copy is None or not hasattr(copy, "PatternIndex") or cellOf(copy) not in wanted:
                continue
            seed = copy.PatternSeed
            result.setdefault(seed.Name if seed else "", {}).setdefault(cellOf(copy), copy)
        return result

    def clusters(self, fp):
        """Each seed followed by its copies (the solver gives them one body)"""
        if fp.Suppressed:
            return []
        held = self.copiesBySeed(fp)
        clusters = []
        for seed in self.seeds(fp):
            copies = held.get(seed.Name, {})
            if copies:
                clusters.append([seed] + [copies[c] for c in sorted(copies, key=lambda c: (c[1], c[0]))])
        return clusters

    def placeInstances(self, fp):
        """Places the copies at the pattern's placements; how far the copy that moved most went (mm,
        the farthest point of its shape). Raises when the direction is lost (the solver reports
        it; the copies stay where they are)."""
        if fp.Suppressed:
            return 0.0
        transforms = self.transforms(fp)
        held = self.copiesBySeed(fp)
        moved = 0.0
        for seed in self.seeds(fp):
            copies = held.get(seed.Name, {})
            reach = reachOf(seed)
            for cell, transform in transforms:
                copy = copies.get(cell)
                if copy is None:
                    continue
                target = transform.multiply(seed.Placement)
                if not copy.Placement.isSame(target, TOLERANCE):
                    step = copy.Placement.inverse().multiply(target)
                    # The farthest point of the copy moves at most this far
                    moved = max(moved, step.Base.Length + abs(step.Rotation.Angle) * reach)
                    copy.Placement = target
                    copy.purgeTouched()
        return moved

    def makeCopy(self, fp, assembly, seed, cell):
        index, index2 = cell
        source = sourceOf(seed)
        kind = "Assembly::AssemblyLink" if seed.isDerivedFrom("Assembly::AssemblyLink") else "App::Link"
        copy = assembly.newObject(kind, source.Name)
        self.matchSeed(copy, seed)
        copy.Label = instanceLabel(assembly, source)
        copy.addProperty("App::PropertyLinkHidden", "PatternSeed", "Pattern", "The seed this copy repeats")
        copy.addProperty("App::PropertyInteger", "PatternIndex", "Pattern", "The copy's number in its pattern")
        copy.addProperty("App::PropertyLinkHidden", "PatternOwner", "Pattern", "The pattern that made this copy")
        names = ["PatternSeed", "PatternIndex", "PatternOwner"]
        if index2:
            # Only copies off the seed's row carry the second index (a one-direction pattern's copies
            # are as they were)
            copy.addProperty("App::PropertyInteger", "PatternIndex2", "Pattern", "The copy's number in its pattern's second direction")
            copy.PatternIndex2 = index2
            names.append("PatternIndex2")
        copy.PatternSeed = seed
        copy.PatternIndex = index
        copy.PatternOwner = fp
        for name in names:
            copy.setPropertyStatus(name, ["ReadOnly"])
        copy.Placement = seed.Placement
        return copy

    def matchSeed(self, copy, seed):
        """The copy links to what its seed links to, scaled and rigid as the seed"""
        source = sourceOf(seed)
        if copy.LinkedObject != source:
            copy.LinkedObject = source
        for name in ("Rigid", "ScaleVector"):
            if hasattr(copy, name) and hasattr(seed, name) and getattr(copy, name) != getattr(seed, name):
                setattr(copy, name, getattr(seed, name))

    def reconcile(self, fp):
        """Makes the copies the properties ask for and removes the others"""
        assembly = assemblyOf(fp)
        if assembly is None:
            raise RuntimeError(translate("Assembly", "{0} is in no assembly").format(fp.Label))
        doc = fp.Document
        cells = self.cells(fp, 0 if fp.Suppressed else int(fp.Count))
        seeds = self.seeds(fp)
        wanted = {(s.Name, c) for s in seeds for c in cells}
        # The copies are the ones listed and any other link of the assembly that names this pattern
        # its owner: an undo outside the recompute's transaction can bring one back unlisted
        listed = [c for c in fp.Instances if c is not None and hasattr(c, "PatternIndex")]
        unlisted = [
            o for o in assembly.Group if getattr(o, "PatternOwner", None) == fp and o not in listed
        ]
        def keyOf(copy):
            return (copy.PatternSeed.Name if copy.PatternSeed else "", cellOf(copy))

        listedKeys = {keyOf(c) for c in listed}
        keep = {}
        extra = []
        for copy in listed + unlisted:
            key = keyOf(copy)
            if copy in unlisted and key in listedKeys:
                # A duplicate of a listed copy (pasted, or copied with its properties): a plain
                # instance of its own, whatever the pattern now asks for (an undo brings back only
                # copies no listed copy stands for)
                stripPattern(copy)
            elif key in wanted and key not in keep:
                keep[key] = copy
            else:
                extra.append(copy)
        # A copy a mate uses isn't removed: the pattern says so and changes nothing (a mate would
        # otherwise lose its part without an error)
        directions = [ref[0] for ref in (fp.Direction, getattr(fp, "Direction2", None)) if ref]
        for copy in extra:
            users = usersOf(assembly, copy, fp)
            if copy in directions:
                users.append(fp)
            if users:
                raise RuntimeError(
                    translate("Assembly", "{0}: {1} is used by {2}; delete or change that first").format(
                        fp.Label, copy.Label, ", ".join(u.Label for u in users)
                    )
                )
        for copy in extra:
            doc.removeObject(copy.Name)
        ordered = []
        for seed in seeds:
            for cell in cells:
                copy = keep.get((seed.Name, cell))
                if copy is None:
                    copy = self.makeCopy(fp, assembly, seed, cell)
                else:
                    self.matchSeed(copy, seed)
                ordered.append(copy)
        if list(fp.Instances) != ordered:
            fp.setPropertyStatus("Instances", "-ReadOnly")
            fp.Instances = ordered
            fp.setPropertyStatus("Instances", "ReadOnly")

    def execute(self, fp):
        copySeeds = self.copySeeds(fp)
        if copySeeds:
            raise RuntimeError(
                translate("Assembly", "{0}: {1} is a copy of {2}; pattern its seed instead").format(
                    fp.Label, copySeeds[0].Label, copySeeds[0].PatternOwner.Label
                )
            )
        if not fp.Suppressed:
            if not self.seeds(fp):
                self.reconcile(fp)  # the copies of a deleted seed go
                raise RuntimeError(translate("Assembly", "{0}: pick the instances to pattern").format(fp.Label))
            # Raises when the direction is lost, before anything changes: the copies stay
            self.transforms(fp)
        self.reconcile(fp)
        # A fixed copy would be moved by its pattern: said instead
        import UtilsAssembly

        for other in UtilsAssembly.getJointGroup(assemblyOf(fp)).Group:
            ground = getattr(other, "ObjectToGround", None)
            if ground is not None and ground in fp.Instances:
                raise RuntimeError(
                    translate("Assembly", "{0}: {1} is fixed; a patterned instance follows its seed: unfix it").format(
                        fp.Label, ground.Label
                    )
                )
            # A rigid group with a copy in it would stop holding its other members to the copy when the
            # pattern moves the copy: said instead
            grouped = [c for c in (getattr(other, "ObjectsToRigidGroup", None) or []) if c in fp.Instances]
            if grouped and not getattr(other, "Suppressed", False):
                raise RuntimeError(
                    translate("Assembly", "{0}: {1} is in {2}; a patterned instance can't be in a rigid group").format(
                        fp.Label, grouped[0].Label, other.Label
                    )
                )
        self.placeInstances(fp)
        for copy in fp.Instances:
            if copy is not None:
                copy.purgeTouched()

    def unsetupObject(self, fp):
        """Deleting the pattern deletes its copies (not called on undo; not when the whole assembly
        or its joint group goes, which removes the copies itself)"""
        doc = fp.Document
        if any(getattr(parent, "Removing", False) for parent in fp.InList):
            return
        assembly = assemblyOf(fp)
        if assembly is not None and assembly.Removing:
            return
        for copy in list(fp.Instances):
            if copy is None or copy.Removing or doc.getObject(copy.Name) is None:
                continue
            if assembly is not None and usersOf(assembly, copy, fp):
                # A copy a mate uses stays, as a plain instance where it is: its mates keep their part
                stripPattern(copy)
                continue
            doc.removeObject(copy.Name)


def usersOf(assembly, obj, pattern=None):
    """The joints, groundings, rigid groups and other patterns of the assembly that use obj"""
    import UtilsAssembly

    users = []
    for other in UtilsAssembly.getJointGroup(assembly).Group:
        if other == pattern:
            continue
        refs = [getattr(other, name, None) for name in ("Reference1", "Reference2", "Direction", "Direction2")]
        if (
            any(ref and ref[0] == obj for ref in refs)
            or getattr(other, "ObjectToGround", None) == obj
            or obj in (getattr(other, "ObjectsToRigidGroup", None) or [])
            or obj in (getattr(other, "Seeds", None) or [])
        ):
            users.append(other)
    return users


def isPatternCopy(obj):
    return obj is not None and hasattr(obj, "PatternOwner") and obj.PatternOwner is not None


def cellOf(copy):
    """A copy's grid cell (i, j); copies of a one-direction pattern have no second index (j 0)"""
    return (copy.PatternIndex, getattr(copy, "PatternIndex2", 0))


def stripPattern(copy):
    """A copy becomes a plain instance: its pattern properties go"""
    for name in ("PatternOwner", "PatternSeed", "PatternIndex", "PatternIndex2"):
        if hasattr(copy, name):
            copy.removeProperty(name)


def makePattern(assembly, kind="Linear", seeds=(), direction=None):
    """Makes a pattern in the assembly's joint group (without recomputing)"""
    import UtilsAssembly

    joints = UtilsAssembly.getJointGroup(assembly)
    fp = joints.newObject("App::FeaturePython", f"{kind}Pattern")
    InstancePattern(fp, kind)
    fp.Label = patternLabel(assembly, kind)
    fp.Seeds = list(seeds)
    if direction is not None:
        fp.Direction = direction
    if App.GuiUp:
        ViewProviderInstancePattern(fp.ViewObject)
    return fp


# --- GUI ------------------------------------------------------------------------------------------


class ViewProviderInstancePattern:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        kind = getattr(getattr(self, "Object", None), "PatternType", "Linear")
        return f":/icons/Assembly_CreatePattern{kind}.svg"

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def setupContextMenu(self, vobj, menu):
        action = menu.addAction(translate("Assembly", "Edit Pattern"))
        action.triggered.connect(lambda: self.edit(vobj))
        return False

    def doubleClicked(self, vobj):
        return self.edit(vobj)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        return self.edit(vobj)

    def unsetEdit(self, vobj, mode=0):
        return False

    def edit(self, vobj):
        if Gui.Control.activeDialog():
            return False
        showPanel(TaskInstancePattern(vobj.Object))
        return True


_made = weakref.WeakValueDictionary()  # id -> widget, of the widgets newWidget() handed out


def newWidget(loader, className):
    """loader.createWidget(className), checked. A widget the loader made for an earlier panel is
    deleted from C++ with it while its Python wrapper may live on (the old panel still holds it):
    a later widget that lands at the same address comes back as that very wrapper, and the
    panel's first connect() raised "Signal source has been deleted", so a double-click on the
    pattern row sometimes opened nothing (TestAssemblyPatternsGui, 2 in 12 under load). A wrapper
    handed out before, or an invalid one, is set aside (kept alive, so that the address is not
    handed out again) and the widget is made again."""
    import shiboken6

    held = []
    for _ in range(16):
        widget = loader.createWidget(className)
        stale = _made.get(id(widget)) is widget
        try:
            valid = shiboken6.isValid(widget)
        except RuntimeError:
            valid = False
        if valid and not stale:
            _made[id(widget)] = widget
            return widget
        held.append(widget)
    raise RuntimeError("the pattern panel could not make a " + className)


def referenceText(ref):
    """"Part 1.Edge3" for a picked reference, a hint when there is none"""
    if ref and ref[0] is not None:
        sub = ref[1][0] if ref[1] else ""
        return f"{ref[0].Label}.{sub.split('.')[-1]}" if sub else ref[0].Label
    return translate("Assembly", "(pick an edge or a face)")


def showPanel(panel):
    """Shows the pattern panel; it closes (Cancel) when its transaction or its document goes"""
    dialog = Gui.Control.showDialog(panel)
    if dialog is not None:
        dialog.setAutoCloseOnTransactionChange(True)
        dialog.setAutoCloseOnDeletedDocument(True)
        dialog.setDocumentName(panel.doc.Name)
    return dialog


class TaskInstancePattern(QtCore.QObject if App.GuiUp else object):
    """Onshape's pattern dialog: the instances, the direction or axis, the distance or angle, the count.
    Picks go to the field that is checked (Instances or Direction); the copies update as you type."""

    def __init__(self, pattern, created=False):
        super().__init__()
        global activePanel
        activePanel = self
        self.pattern = pattern
        self.created = created
        self.doc = pattern.Document
        self.assembly = assemblyOf(pattern)
        if not created:
            self.doc.openTransaction(translate("Assembly", "Edit {0}").format(pattern.Label))
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(pattern.Label)
        layout = QtWidgets.QFormLayout(self.form)

        self.seedsButton = QtWidgets.QPushButton(translate("Assembly", "Instances to pattern"))
        self.seedsButton.setCheckable(True)
        self.seedsList = QtWidgets.QListWidget()
        self.seedsList.setMaximumHeight(90)
        layout.addRow(self.seedsButton)
        layout.addRow(self.seedsList)

        circular = pattern.PatternType == "Circular"
        self.directionButton = QtWidgets.QPushButton(
            translate("Assembly", "Axis") if circular else translate("Assembly", "Direction")
        )
        self.directionButton.setCheckable(True)
        self.directionLabel = QtWidgets.QLabel()
        layout.addRow(self.directionButton, self.directionLabel)
        self.seedsButton.clicked.connect(lambda: self.setField("seeds"))
        self.directionButton.clicked.connect(lambda: self.setField("direction"))

        loader = Gui.UiLoader()
        self.bindings = []
        if circular:
            self.amount = newWidget(loader, "Gui::QuantitySpinBox")
            self.amount.setProperty("unit", "deg")
            self.bind(self.amount, "Angle")
            layout.addRow(translate("Assembly", "Angle"), self.amount)
            self.equal = QtWidgets.QCheckBox(translate("Assembly", "Equal spacing"))
            self.equal.setChecked(pattern.EqualSpacing)
            self.equal.toggled.connect(self.onEqual)
            layout.addRow(self.equal)
        else:
            self.amount = newWidget(loader, "Gui::QuantitySpinBox")
            self.amount.setProperty("unit", "mm")
            self.bind(self.amount, "Distance")
            layout.addRow(translate("Assembly", "Distance"), self.amount)
        self.amount.setObjectName("patternAmount")
        self.amount.setProperty("rawValue", pattern.Angle.Value if circular else pattern.Distance.Value)
        self.amount.valueChanged.connect(self.onAmount)
        self.count = newWidget(loader, "Gui::IntSpinBox")
        self.count.setObjectName("patternCount")
        self.count.setMinimum(1)
        self.count.setMaximum(100000)
        self.count.setValue(int(pattern.Count))
        self.bind(self.count, "Count")
        self.count.valueChanged.connect(self.onCount)
        layout.addRow(translate("Assembly", "Instance count"), self.count)
        self.reversed = QtWidgets.QCheckBox(translate("Assembly", "Flip"))
        self.reversed.setChecked(pattern.Reversed)
        self.reversed.toggled.connect(self.onReversed)
        layout.addRow(self.reversed)
        self.second = None
        if not circular:
            self.addSecondDirection(loader, layout)
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c00000")
        layout.addRow(self.message)

        self.refresh()
        self.setField("seeds" if not pattern.Seeds else "direction" if not pattern.Direction else "")
        Gui.Selection.clearSelection()
        # Picks with their whole path from the root, as the joint dialog takes them
        Gui.Selection.addObserver(self, Gui.Selection.ResolveMode.NoResolve)

    def addSecondDirection(self, loader, layout):
        """Onshape's "Second direction" box: ticked, its own direction, distance, count and flip show.
        Ticking copies nothing from the first direction (an empty direction, count 1)."""
        pattern = self.pattern
        if not hasattr(pattern, "SecondDirection"):
            pattern.Proxy.addSecondDirection(pattern)
        self.second = QtWidgets.QCheckBox(translate("Assembly", "Second direction"))
        self.second.setObjectName("patternSecondDirection")
        self.second.setChecked(pattern.SecondDirection)
        layout.addRow(self.second)
        self.secondBox = QtWidgets.QWidget()
        self.secondBox.setObjectName("patternSecondBox")
        box = QtWidgets.QFormLayout(self.secondBox)
        box.setContentsMargins(0, 0, 0, 0)
        self.direction2Button = QtWidgets.QPushButton(translate("Assembly", "Direction"))
        self.direction2Button.setObjectName("patternDirection2")
        self.direction2Button.setCheckable(True)
        self.direction2Label = QtWidgets.QLabel()
        box.addRow(self.direction2Button, self.direction2Label)
        self.direction2Button.clicked.connect(lambda: self.setField("direction2"))
        self.amount2 = newWidget(loader, "Gui::QuantitySpinBox")
        self.amount2.setObjectName("patternAmount2")
        self.amount2.setProperty("unit", "mm")
        self.bind(self.amount2, "Distance2")
        self.amount2.setProperty("rawValue", pattern.Distance2.Value)
        self.amount2.valueChanged.connect(self.onAmount2)
        box.addRow(translate("Assembly", "Distance"), self.amount2)
        self.count2 = newWidget(loader, "Gui::IntSpinBox")
        self.count2.setObjectName("patternCount2")
        self.count2.setMinimum(1)
        self.count2.setMaximum(100000)
        self.count2.setValue(int(pattern.Count2))
        self.bind(self.count2, "Count2")
        self.count2.valueChanged.connect(self.onCount2)
        box.addRow(translate("Assembly", "Instance count"), self.count2)
        self.reversed2 = QtWidgets.QCheckBox(translate("Assembly", "Flip"))
        self.reversed2.setObjectName("patternReversed2")
        self.reversed2.setChecked(pattern.Reversed2)
        self.reversed2.toggled.connect(self.onReversed2)
        box.addRow(self.reversed2)
        layout.addRow(self.secondBox)
        self.secondBox.setVisible(pattern.SecondDirection)
        self.second.toggled.connect(self.onSecond)

    def bind(self, widget, name):
        binding = Gui.ExpressionBinding(widget)
        binding.bind(self.pattern, name)
        binding.setAutoApply(True)
        self.bindings.append(binding)

    # the fields
    def setField(self, field):
        self.field = field
        self.seedsButton.setChecked(field == "seeds")
        self.directionButton.setChecked(field == "direction")
        if self.second is not None:
            self.direction2Button.setChecked(field == "direction2")

    def refresh(self):
        self.seedsList.clear()
        for seed in self.pattern.Seeds:
            if seed is not None:
                self.seedsList.addItem(seed.Label)
        self.directionLabel.setText(referenceText(self.pattern.Direction))
        if self.second is not None:
            self.direction2Label.setText(referenceText(self.pattern.Direction2))

    def update(self):
        self.pattern.touch()
        self.doc.recompute()
        # Copies removed in a recompute go after it: the assembly solves again without them
        if self.assembly is not None and "Touched" in self.assembly.State:
            self.doc.recompute()
        self.refresh()
        if "Invalid" in self.pattern.State or "Error" in self.pattern.State:
            self.message.setText(self.lastError())
        else:
            self.message.setText("")

    def lastError(self):
        try:
            self.pattern.Proxy.transforms(self.pattern)
            if not self.pattern.Proxy.seeds(self.pattern):
                return translate("Assembly", "Pick the instances to pattern")
        except RuntimeError as error:
            return str(error)
        return translate("Assembly", "The pattern failed (see the report view)")

    def onAmount(self, *args):
        value = self.amount.property("rawValue")
        if self.pattern.PatternType == "Circular":
            if not hasExpression(self.pattern, "Angle") and abs(self.pattern.Angle.Value - value) > 1e-12:
                self.pattern.Angle = value
        elif not hasExpression(self.pattern, "Distance") and abs(self.pattern.Distance.Value - value) > 1e-12:
            self.pattern.Distance = value
        self.update()

    def onCount(self, value):
        if not hasExpression(self.pattern, "Count") and int(self.pattern.Count) != int(value):
            self.pattern.Count = int(value)
        self.update()

    def onReversed(self, checked):
        self.pattern.Reversed = checked
        self.update()

    def onEqual(self, checked):
        self.pattern.EqualSpacing = checked
        self.update()

    def onSecond(self, checked):
        self.pattern.SecondDirection = checked
        self.secondBox.setVisible(checked)
        if checked and not self.pattern.Direction2:
            self.setField("direction2")
        elif not checked and self.field == "direction2":
            self.setField("")
        self.update()

    def onAmount2(self, *args):
        value = self.amount2.property("rawValue")
        if not hasExpression(self.pattern, "Distance2") and abs(self.pattern.Distance2.Value - value) > 1e-12:
            self.pattern.Distance2 = value
        self.update()

    def onCount2(self, value):
        if not hasExpression(self.pattern, "Count2") and int(self.pattern.Count2) != int(value):
            self.pattern.Count2 = int(value)
        self.update()

    def onReversed2(self, checked):
        self.pattern.Reversed2 = checked
        self.update()

    # picks
    def addSelection(self, doc_name, obj_name, sub_name, mousePos=None):
        # An error in a selection observer is lost: report it
        try:
            self.onPick(doc_name, obj_name, sub_name)
        except Exception:
            import traceback

            App.Console.PrintError(traceback.format_exc())

    def onPick(self, doc_name, obj_name, sub_name):
        import UtilsAssembly

        try:
            self.doc.Name
        except ReferenceError:
            # The dialog was closed without OK or Cancel and its document is gone
            Gui.Selection.removeObserver(self)
            return

        if self.assembly is None or doc_name != self.doc.Name:
            return
        root = self.doc.getObject(obj_name)
        comp, sub = UtilsAssembly.getComponentReference(self.assembly, root, sub_name)
        if comp is None:
            return
        if self.field in ("direction", "direction2"):
            if not sub:
                return
            if self.field == "direction":
                self.pattern.Direction = (comp, [sub])
            else:
                self.pattern.Direction2 = (comp, [sub])
            self.setField("")
        elif self.field == "seeds":
            seeds = [s for s in self.pattern.Seeds if s is not None]
            if isPatternCopy(comp):
                # A copy stands for its seed: it adds the seed, it never removes it
                comp = comp.PatternSeed
                if comp in seeds:
                    return
            if comp in seeds:
                seeds.remove(comp)
            else:
                seeds.append(comp)
            self.pattern.Seeds = seeds
        else:
            # No field chosen: a pick goes nowhere (click Instances or Direction first)
            return
        QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)
        self.update()

    # the dialog
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def finish(self):
        global activePanel
        if activePanel is self:
            activePanel = None
        Gui.Selection.removeObserver(self)
        self.bindings = []
        gdoc = Gui.getDocument(self.doc.Name) if self.doc.Name in App.listDocuments() else None
        if gdoc is not None and gdoc.getInEdit() == self.pattern.ViewObject:
            gdoc.resetEdit()

    def autoClosedOnTransactionChange(self):
        self.reject()

    def autoClosedOnDeletedDocument(self):
        Gui.Selection.removeObserver(self)
        self.bindings = []

    def accept(self):
        self.update()
        if "Invalid" in self.pattern.State or "Error" in self.pattern.State:
            # OK keeps the dialog while the pattern is in error (Cancel leaves)
            self.message.setText(self.lastError())
            return False
        self.finish()
        self.doc.recompute()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self.finish()
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


class CommandCreatePattern:
    def __init__(self, kind):
        self.kind = kind

    def GetResources(self):
        if self.kind == "Circular":
            menu = QT_TRANSLATE_NOOP("Assembly_CreatePatternCircular", "Circular Pattern")
            tip = QT_TRANSLATE_NOOP(
                "Assembly_CreatePatternCircular",
                "<p>Repeats the selected instances around an axis.</p>"
                "<p>The copies are instances that follow their seed.</p>",
            )
        else:
            menu = QT_TRANSLATE_NOOP("Assembly_CreatePatternLinear", "Linear Pattern")
            tip = QT_TRANSLATE_NOOP(
                "Assembly_CreatePatternLinear",
                "<p>Repeats the selected instances along a direction.</p>"
                "<p>The copies are instances that follow their seed.</p>",
            )
        return {
            "Pixmap": f"Assembly_CreatePattern{self.kind}",
            "MenuText": menu,
            "ToolTip": tip,
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        import UtilsAssembly

        return (
            UtilsAssembly.isAssemblyCommandActive()
            and UtilsAssembly.assembly_has_at_least_n_parts(1)
            and not Gui.Control.activeDialog()
        )

    def Activated(self):
        import UtilsAssembly

        assembly = UtilsAssembly.activeAssembly()
        if not assembly:
            return
        seeds = []
        for sel in Gui.Selection.getSelectionEx("*", 0):
            for sub in sel.SubElementNames or [""]:
                comp, _ = UtilsAssembly.getComponentReference(assembly, sel.Object, sub)
                if comp is not None and isPatternCopy(comp):
                    comp = comp.PatternSeed
                if comp is not None and comp not in seeds:
                    seeds.append(comp)
        doc = assembly.Document
        doc.openTransaction(translate("Assembly", "{0} pattern").format(self.kind))
        pattern = makePattern(assembly, self.kind, seeds)
        doc.recompute()
        showPanel(TaskInstancePattern(pattern, created=True))


if App.GuiUp:
    Gui.addCommand("Assembly_CreatePatternLinear", CommandCreatePattern("Linear"))
    Gui.addCommand("Assembly_CreatePatternCircular", CommandCreatePattern("Circular"))
