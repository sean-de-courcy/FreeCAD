# SPDX-License-Identifier: LGPL-2.1-or-later
# ****************************************************************************
# *                                                                          *
# *   This file is part of FreeCAD.                                          *
# *                                                                          *
# *   FreeCAD is free software: you can redistribute it and/or modify it     *
# *   under the terms of the GNU Lesser General Public License as            *
# *   published by the Free Software Foundation, either version 2.1 of the   *
# *   License, or (at your option) any later version.                        *
# *                                                                          *
# *   FreeCAD is distributed in the hope that it will be useful, but         *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
# *   Lesser General Public License for more details.                        *
# *                                                                          *
# *   You should have received a copy of the GNU Lesser General Public       *
# *   License along with FreeCAD. If not, see                                *
# *   <https://www.gnu.org/licenses/>.                                       *
# *                                                                          *
# ***************************************************************************/

"""Static copies of variables from Onshape exports: `App::VarSetCopy` (FreeCAD-CH, ops#317 PR E1).

The design is notes/variables-studio.md, sections 2.5, 2.6 and 3. Each studio entry of the
exports imported becomes one copy, a VarSet whose variables hold the translated expressions and
are read-only while the copy is attached. Nothing is guessed:

- `plan_import()` reads and translates everything and lists what stands in the way: names the
  files use but don't define (section 2.6), names several files define, refused expressions,
  and the variable names FreeCAD can't use (`t`, `pi`, `W2`), with a proposed name for each.
  It changes nothing.
- The choices of section 2.6 come in as arguments: `bindings` (a document variable's path),
  `values` (a value, which becomes an input variable in the document's "Variables" set),
  `skip` (the variables that need the name aren't imported), `providers` (which entry provides a
  name several define) and `name_map` (another name than the proposal).
- `import_studios()` makes the copies in one transaction only when nothing stands in the way,
  then checks each variable (section 2.5): FreeCAD's value of the written text, evaluated with
  the copy as owner, must have the variable's unit and equal the translator's own value. Any
  failure undoes everything.
- `detach()` turns a copy into a plain, editable set of variables, as one undo step.

Refresh, the stamps' "out of date" checks and FreeCAD documents as a source are later PRs
(E2, F); `stamp()` is the stamp they compare with.
"""

import datetime
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import FreeCAD as App

from freecad.variables import onshape
from freecad.variables.onshape import ANGLE, LENGTH, NONE, Binding, Quantity

COPY_TYPE = "App::VarSetCopy"
JSON_KIND = "Onshape JSON"
DETACHED = "None"
GROUP = "Base"  # the group the panel's Add uses
VARIABLES = "Variables"  # the document's own set, as the panel finds it

# The copy's static properties (section 3.1); a variable can't take one of these names.
SOURCE_PROPERTIES = ("CopyFormat", "SourceKind", "SourcePath", "SourceRelativePath",
                     "SourceObject", "SourceEntries", "SourceStamp", "SourceRefreshed",
                     "SourceExpressions", "NameMap", "Bindings", "Skipped", "Orphans")

# A test hook (I-4): called as hook(result, value) for each variable checked, its return value
# replaces the translator's in the check.
_check_hook = None


class ImportBlocked(Exception):
    """Something stands in the way and nothing was created; `plan` says what."""

    def __init__(self, plan: "Plan"):
        super().__init__(plan.report())
        self.plan = plan


class ImportCheckFailed(Exception):
    """FreeCAD's value of a written expression disagrees with the translator's: a translator bug.
    The import was undone."""


@dataclass
class Source:
    """One studio entry of one file: one copy."""

    path: str  # absolute, with "/" (saved so, section 3.1)
    index: int  # the entry's index in its file, from 0
    entries_in_file: int
    entry: onshape.StudioEntry
    name: str  # the copy's internal name
    label: str


@dataclass
class Plan:
    """What an import would do and what stands in its way (nothing is created)."""

    sources: List[Source]
    translation: Optional[onshape.ExportTranslation] = None
    # Onshape name -> FreeCAD name, where they differ (proposals, and the name_map given)
    renames: Dict[str, str] = field(default_factory=dict)
    # names nothing defines and no choice covers -> the variables that use them
    unresolved: Dict[str, List[str]] = field(default_factory=dict)
    # names several entries define and no provider picks -> those entries (indexes into sources)
    ambiguous: Dict[str, List[int]] = field(default_factory=dict)
    # (source index, Onshape name, reason): refused and not skipped
    refused: List[Tuple[int, str, str]] = field(default_factory=list)
    # (source index, Onshape name, why): left out by the choices
    skipped: List[Tuple[int, str, str]] = field(default_factory=list)
    # the `skip` choices, kept per copy in Skipped so Refresh can tell them from new variables
    skip: frozenset = frozenset()
    # unresolved name -> Binding (path and value), from `bindings` and `values`
    bindings: Dict[str, Binding] = field(default_factory=dict)
    # unresolved name -> (Onshape type, FreeCAD name, property type, translation) of the input
    # variables `values` asks for
    inputs: Dict[str, Tuple[str, str, str, onshape.Translation]] = field(default_factory=dict)
    inputs_set: Optional[str] = None  # the internal name of the set the inputs go in
    inputs_set_new: bool = False
    problems: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def variables(self, source: int) -> List[onshape.VariableResult]:
        """The translated variables of @a source, the ones the import creates."""
        if not self.translation:
            return []
        return [r for r in self.translation.variables
                if r.entry == source and r.translation is not None]

    def report(self) -> str:
        lines = list(self.problems)
        for name, fc_name in self.renames.items():
            lines.append(f"{name} becomes {fc_name}")
        for source, name, why in self.skipped:
            lines.append(f"{name} ({self.sources[source].label}) is skipped: {why}")
        lines.extend(self.warnings)
        return "\n".join(lines) if lines else "Nothing stands in the way."


# The stamp's prefix: the hash and the canonical form's version (section 3.2). A later change to
# the canonical form takes a new version, so a stamp of the old form reads as "can't compare"
# rather than "out of date".
STAMP_JSON = "sha256:json1:"


def stamp(entry: onshape.StudioEntry) -> str:
    """`sha256:json1:` and the SHA-256 of an Onshape entry's canonical form (section 3.2): per
    variable, in the file's order, its name, type, expression, description and value.
    Formatting doesn't count."""
    data = [[v.name, v.type, v.expression, v.description, v.value] for v in entry.variables]
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return STAMP_JSON + hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_name(name: str, holder=COPY_TYPE) -> str:
    """Why FreeCAD can't use @a name for a variable of @a holder (an object, or a type name for
    one not made yet), or "" (the rules of section 1.3, App's checkVariableName)."""
    return App.checkVariableName(name, holder)


def propose_name(name: str, taken: Iterable[str] = (), holder=COPY_TYPE) -> str:
    """A name FreeCAD can use for @a name: `t` -> `t_`, then `t_2`, `t_3`..."""
    taken = set(taken)
    base = re.sub(r"[^A-Za-z0-9_]", "_", name) or "_"
    if base[0].isdigit():
        base = "_" + base
    candidate = base + "_"
    count = 1
    while check_name(candidate, holder) or candidate in taken:
        count += 1
        candidate = f"{base}_{count}"
    return candidate


def plan_import(doc, paths: Sequence[str], *,
                name_map: Optional[Mapping[str, str]] = None,
                bindings: Optional[Mapping[str, str]] = None,
                values: Optional[Mapping[str, Tuple[str, str]]] = None,
                skip: Iterable[str] = (),
                providers: Optional[Mapping[str, int]] = None,
                default_units: Optional[Mapping[str, str]] = None) -> Plan:
    """Reads and translates @a paths (Onshape exports) for @a doc and says what stands in the
    way; changes nothing.

    @a name_map: Onshape name -> FreeCAD name, instead of the proposal for a name FreeCAD can't
    use. @a bindings: unresolved name -> a document variable's path, `Object.Property` by
    internal name. @a values: unresolved name -> (Onshape type, Onshape text), an input variable
    in the document's "Variables" set. @a skip: unresolved names, or variable names, whose
    variables (and the ones that need them) aren't imported. @a providers: a name several
    entries define -> the source index (as in `Plan.sources`) that provides it.
    @a default_units: "LENGTH" / "ANGLE" -> the Onshape document's default unit.
    """
    name_map = dict(name_map or {})
    bindings = dict(bindings or {})
    values = dict(values or {})
    skip = set(skip)
    plan = Plan([], skip=frozenset(skip))

    # The files, one copy per studio entry.
    taken = set()
    for path in paths:
        path = _portable(os.path.abspath(path))
        try:
            entries = onshape.read_export(path)
        except (OSError, onshape.ExportError) as e:
            plan.problems.append(f"{path}: {e}")
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        for index, entry in enumerate(entries):
            label = stem if len(entries) == 1 else f"{stem} {index + 1}"
            name = _unique_name(doc, label, taken)
            taken.add(name)
            plan.sources.append(Source(path, index, len(entries), entry, name, label))
            for obj in doc.findObjects(COPY_TYPE):
                if obj.SourcePath == path and obj.SourceObject == str(index):
                    plan.warnings.append(f"{obj.Label} is already a copy of {label}")
    if plan.problems:
        return plan

    # FreeCAD names: the rules of section 1.3; one name per Onshape name across the import.
    defined = {v.name for s in plan.sources for v in s.entry.variables}
    for name in sorted(defined):
        if name in name_map:
            reason = check_name(name_map[name])
            if reason:
                plan.problems.append(f"{name} can't become {name_map[name]}: {reason}")
            elif name_map[name] != name:
                plan.renames[name] = name_map[name]
        elif check_name(name):
            used = defined | set(plan.renames.values()) | set(name_map.values())
            plan.renames[name] = propose_name(name, used)
    for source in plan.sources:
        fc_names = {}
        for v in source.entry.variables:
            fc_name = plan.renames.get(v.name, v.name)
            if fc_name in fc_names and fc_names[fc_name] != v.name:
                plan.problems.append(f"{v.name} and {fc_names[fc_name]} would both be {fc_name} "
                                     f"in {source.label}")
            fc_names[fc_name] = v.name

    # The choices for names nothing defines (section 2.6). One for a name the files define isn't
    # used: dropped before anything checks or makes it (an input variable nobody uses).
    for name in sorted((set(bindings) | set(values)) & defined):
        plan.warnings.append(f"#{name} is defined by the imported files; its choice isn't used")
        bindings.pop(name, None)
        values.pop(name, None)
    for name in set(bindings) & set(values):
        plan.problems.append(f"#{name} has two choices: a document variable and a value")
    for name, path in bindings.items():
        try:
            plan.bindings[name] = Binding(path, _document_value(doc, path))
        except ValueError as e:
            plan.problems.append(f"#{name}: {e}")
    if values:
        _plan_inputs(doc, plan, values, default_units)

    # Skipped variables leave the entries; what needs them waits on their name, which is skipped.
    entries = [onshape.StudioEntry(s.entry.reference,
                                   tuple(v for v in s.entry.variables if v.name not in skip))
               for s in plan.sources]
    for i, source in enumerate(plan.sources):
        for v in source.entry.variables:
            if v.name in skip:
                plan.skipped.append((i, v.name, "skipped"))
    translation = onshape.translate_export(
        entries,
        containers=[s.name for s in plan.sources],
        name_map=plan.renames,
        bindings=plan.bindings,
        providers=providers,
        default_units=default_units,
    )
    plan.translation = translation
    plan.ambiguous = dict(translation.ambiguous)
    plan.unresolved = {n: users for n, users in translation.unresolved.items() if n not in skip}
    for result in translation.variables:
        if result.translation is not None:
            continue
        if result.needs and set(result.needs) <= skip:
            needs = ", ".join(f"#{n}" for n in result.needs)
            plan.skipped.append((result.entry, result.name, f"it needs {needs}, skipped"))
        elif result.refusal:
            plan.refused.append((result.entry, result.name, result.refusal))
    for name, users in sorted(plan.unresolved.items()):
        plan.problems.append(
            f"#{name} is used by {', '.join(users)} but defined in none of the imported files. "
            "Onshape doesn't export the studios a studio imports: import that studio's export "
            f"too, or choose how to resolve #{name}.")
    for name, idx in sorted(plan.ambiguous.items()):
        where = ", ".join(plan.sources[i].label for i in idx)
        plan.problems.append(f"#{name} is defined in {where}: choose which provides it")
    for source, name, reason in plan.refused:
        plan.problems.append(f"{name} ({plan.sources[source].label}): {reason}")
    cycle = _copy_cycle(plan, entries, providers or {})
    if cycle:
        uses = ", ".join(f"{plan.sources[i].label}.{name} uses #{ref} of "
                         f"{plan.sources[j].label}" for i, j, name, ref in cycle)
        plan.problems.append(
            f"The copies would depend on each other ({uses}): a FreeCAD object can't depend on "
            "one that depends on it. Skip one of these variables.")
    return plan


def _copy_cycle(plan: Plan, entries, providers) -> List[Tuple[int, int, str, str]]:
    """A cycle between the copies, which FreeCAD can't recompute although no variable refers to
    itself (A.x uses B.y, B.z uses A.w): its edges (user entry, provider entry, variable, name),
    or []."""
    defined: Dict[str, List[int]] = {}
    for i, entry in enumerate(entries):
        for v in entry.variables:
            defined.setdefault(v.name, [])
            if i not in defined[v.name]:
                defined[v.name].append(i)
    edges: Dict[int, Dict[int, Tuple[str, str]]] = {}
    for result in plan.translation.variables:
        if result.translation is None:
            continue
        i = result.entry
        for ref in onshape.references(onshape.parse(result.variable.expression)):
            idx = defined.get(ref, [])
            if i in idx:
                continue
            j = idx[0] if len(idx) == 1 else providers.get(ref)
            if j is not None and j in idx:
                edges.setdefault(i, {}).setdefault(j, (result.name, ref))
    state: Dict[int, str] = {}
    path: List[int] = []

    def visit(i):
        state[i] = "busy"
        path.append(i)
        for j in sorted(edges.get(i, {})):
            if state.get(j) == "busy":
                loop = path[path.index(j):] + [j]
                return [(a, b) + edges[a][b] for a, b in zip(loop, loop[1:])]
            if j not in state:
                found = visit(j)
                if found:
                    return found
        path.pop()
        state[i] = "done"
        return []

    for i in sorted(edges):
        if i not in state:
            found = visit(i)
            if found:
                return found
    return []


def _unique_name(doc, label: str, taken: Iterable[str]) -> str:
    """An internal name for a new object from @a label, not used in @a doc or @a taken."""
    base = re.sub(r"[^A-Za-z0-9_]", "_", label) or "Copy"
    if base[0].isdigit():
        base = "_" + base
    name, count = base, 1
    while doc.getObject(name) is not None or name in taken:
        count += 1
        name = f"{base}{count:03d}"
    return name


def _document_value(doc, path: str) -> Quantity:
    """The value of the document variable `Object.Property` (internal names), in SI units."""
    obj_name, _, prop = path.partition(".")
    obj = doc.getObject(obj_name)
    if obj is None or not prop or prop not in obj.PropertiesList:
        raise ValueError(f"{path} isn't a variable of this document")
    return to_quantity(obj.evalExpression(prop), path)


def to_quantity(value, what: str) -> Quantity:
    """A FreeCAD value (a Base.Quantity or a number) as the translator's Quantity."""
    if isinstance(value, bool) or not isinstance(value, (int, float, App.Units.Quantity)):
        raise ValueError(f"{what} isn't a number or a quantity")
    if not isinstance(value, App.Units.Quantity):
        return Quantity(float(value))
    unit = value.Unit
    if unit == App.Units.Length:
        return Quantity(value.Value / 1000, LENGTH)  # internal unit mm
    if unit == App.Units.Angle:
        return Quantity(math.radians(value.Value), ANGLE)  # internal unit deg
    if unit == App.Units.Unit():
        return Quantity(value.Value)
    raise ValueError(f"{what} is {value.UserString}: only lengths, angles and numbers are "
                     "supported")


def _variables_set(doc):
    """The document's "Variables" set, as the panel finds it: by name, then by label."""
    obj = doc.getObject(VARIABLES)
    if obj is not None and obj.TypeId == "App::VarSet":  # a plain set: a copy is read-only
        return obj
    for obj in doc.findObjects("App::VarSet"):
        if obj.TypeId == "App::VarSet" and obj.Label == VARIABLES:
            return obj
    return None


def _plan_inputs(doc, plan: Plan, values, default_units):
    """Input variables for `values`, in the document's "Variables" set (made if missing)."""
    holder = _variables_set(doc)
    if holder is not None:
        plan.inputs_set = holder.Name
    else:
        plan.inputs_set = _unique_name(doc, VARIABLES, {s.name for s in plan.sources})
        plan.inputs_set_new = True
    for name, choice in values.items():
        try:
            kind, text = choice
        except (TypeError, ValueError):
            plan.problems.append(f"#{name}: a value is (Onshape type, text)")
            continue
        reason = check_name(name, holder if holder is not None else "App::VarSet")
        if reason:
            plan.problems.append(f"#{name} can't be an input variable in {VARIABLES}: {reason}")
            continue
        try:
            translation = onshape.translate(text, kind, _no_reference, default_units)
        except onshape.Refused as e:
            plan.problems.append(f"#{name}: the value {text!r}: {e}")
            continue
        plan.inputs[name] = (kind, name, translation.property_type, translation)
        plan.bindings[name] = Binding(f"{plan.inputs_set}.{name}", translation.value)


def _no_reference(name):
    raise onshape.Refused(f"a value can't use #{name}")


@dataclass
class ImportResult:
    plan: Plan
    copies: List[object]  # the App::VarSetCopy objects, one per source
    inputs: List[Tuple[object, str]] = field(default_factory=list)  # (set, name) made for values


def import_studios(doc, paths: Sequence[str], **choices) -> ImportResult:
    """Imports @a paths (Onshape exports) into @a doc as copies, in one transaction; the
    arguments are plan_import()'s. Raises ImportBlocked (nothing created) when anything stands
    in the way, and ImportCheckFailed (everything undone) when a value disagrees."""
    plan = plan_import(doc, paths, **choices)
    if not plan.ok:
        raise ImportBlocked(plan)
    names = ", ".join(s.label for s in plan.sources)
    created = []  # objects made, removed by hand if the transaction can't take them back
    own = doc.getBookedTransactionID() == 0
    if own:
        doc.openTransaction(f"Import {names}")
    try:
        result = _make(doc, plan, created)
        _check(doc, plan, result)
        for copy in result.copies:
            copy.SourceKind = JSON_KIND  # the variables become read-only
    except BaseException:
        if own:
            doc.abortTransaction()
        for obj_name, prop in reversed(created):
            obj = doc.getObject(obj_name)
            if obj is None:
                continue
            if prop is None:
                doc.removeObject(obj_name)
            elif prop in obj.PropertiesList:
                obj.removeProperty(prop)
        raise
    if own:
        doc.commitTransaction()
    return result


def _make(doc, plan: Plan, created: list) -> ImportResult:
    result = ImportResult(plan, [])
    if plan.inputs:
        holder = doc.getObject(plan.inputs_set)
        if plan.inputs_set_new:
            holder = doc.addObject("App::VarSet", plan.inputs_set)
            created.append((holder.Name, None))
            if holder.Name != plan.inputs_set:
                raise RuntimeError(f"{plan.inputs_set} was made as {holder.Name}")
            holder.Label = VARIABLES
        for _kind, name, property_type, translation in plan.inputs.values():
            holder.addProperty(property_type, name, GROUP)
            created.append((holder.Name, name))
            setattr(holder, name, _freecad_value(translation.value))
            result.inputs.append((holder, name))
    refreshed = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Every copy first: an expression naming another copy binds to it only if it exists.
    for source in plan.sources:
        copy = doc.addObject(COPY_TYPE, source.name)
        created.append((copy.Name, None))
        if copy.Name != source.name:
            raise RuntimeError(f"{source.name} was made as {copy.Name}")
        copy.Label = source.label
        result.copies.append(copy)
    for i, (source, copy) in enumerate(zip(plan.sources, result.copies)):
        expressions, name_map, bindings = {}, {}, {}
        for var in plan.variables(i):
            copy.addProperty(var.translation.property_type, var.freecad_name, GROUP,
                             var.variable.description)
            copy.setExpression(var.freecad_name, var.translation.text)
            expressions[var.name] = var.variable.expression
            if var.freecad_name != var.name:
                name_map[var.name] = var.freecad_name
            for ref in onshape.references(onshape.parse(var.variable.expression)):
                if ref in plan.bindings and not _defined(plan, ref):
                    bindings[ref] = plan.bindings[ref].text
        copy.SourcePath = source.path
        copy.SourceRelativePath = _relative(doc, source.path)
        copy.SourceObject = str(source.index)
        copy.SourceEntries = source.entries_in_file
        copy.SourceStamp = stamp(source.entry)
        copy.SourceRefreshed = refreshed
        copy.SourceExpressions = expressions
        copy.NameMap = name_map
        copy.Bindings = bindings
        copy.Skipped = _skipped(plan, source)
    doc.recompute([obj for obj in result.copies] + [h for h, _n in result.inputs[:1]])
    return result


def _skipped(plan: Plan, source: Source) -> List[str]:
    """The `skip` choices that concern @a source: names it defines or uses."""
    names = set()
    for v in source.entry.variables:
        names.add(v.name)
        try:
            names.update(onshape.references(onshape.parse(v.expression)))
        except onshape.Refused:
            pass
    return sorted(plan.skip & names)


def _defined(plan: Plan, name: str) -> bool:
    """Whether @a name comes from one of the imported entries, not from a binding."""
    return any(v.name == name for s in plan.sources for v in s.entry.variables)


def _portable(path: str) -> str:
    """@a path with "/" as the separator, as the copy saves it: a document saved on Windows
    still finds a relative path on macOS (Windows reads "/" as well)."""
    return path.replace(os.sep, "/")


def _relative(doc, path: str) -> str:
    if not doc.FileName:
        return ""
    try:
        return _portable(os.path.relpath(path, os.path.dirname(doc.FileName)))
    except ValueError:  # another drive
        return ""


def _freecad_value(value: Quantity):
    if value.dims == LENGTH:
        return App.Units.Quantity(value.value * 1000, App.Units.Length)
    if value.dims == ANGLE:
        return App.Units.Quantity(math.degrees(value.value), App.Units.Angle)
    return value.value


def _show(value: Quantity) -> str:
    if value.dims == LENGTH:
        return f"{value.value * 1000:.12g} mm"
    if value.dims == ANGLE:
        return f"{math.degrees(value.value):.12g} deg"
    return f"{value.value:.12g}"


def _check(doc, plan: Plan, result: ImportResult):
    """Section 2.5, step 3: each variable's text, evaluated by FreeCAD with its copy as owner,
    has the variable's unit and the translator's value."""
    for i, copy in enumerate(result.copies):
        if "Invalid" in copy.State:
            raise ImportCheckFailed(f"{copy.Label} doesn't recompute: {copy.State}")
        for var in plan.variables(i):
            text = var.translation.text
            expected = var.translation.value
            if _check_hook is not None:
                expected = _check_hook(var, expected)
            where = f"{copy.Label}.{var.freecad_name}"
            try:
                got = to_quantity(copy.evalExpression(text), where)
            except Exception as e:  # noqa: BLE001 (any failure is the check's)
                raise ImportCheckFailed(f"{where}: FreeCAD can't evaluate {text!r} "
                                        f"(from {var.variable.expression!r}): {e}") from None
            if got.dims != expected.dims or not onshape.values_agree(got.value, expected.value):
                raise ImportCheckFailed(
                    f"{where}: FreeCAD computes {_show(got)} for {text!r}, the translator "
                    f"{_show(expected)} for {var.variable.expression!r}")


def detach(copy):
    """Turns @a copy into a plain set of variables, editable, with no source, as one undo step
    (section 3.1, Detach). The object keeps its type; refreshing it is no longer possible."""
    if copy.TypeId != COPY_TYPE:
        raise TypeError(f"{copy.Label} isn't a copy")
    doc = copy.Document
    own = doc.getBookedTransactionID() == 0
    if own:
        doc.openTransaction(f"Detach {copy.Label}")
    try:
        copy.SourceKind = DETACHED  # the variables become editable
        copy.SourcePath = ""
        copy.SourceRelativePath = ""
        copy.SourceObject = ""
        copy.SourceEntries = 0
        copy.SourceStamp = ""
        copy.SourceRefreshed = ""
        copy.SourceExpressions = {}
        copy.NameMap = {}
        copy.Bindings = {}
        copy.Skipped = []
        copy.Orphans = []
    except BaseException:
        if own:
            doc.abortTransaction()
        raise
    if own:
        doc.commitTransaction()
