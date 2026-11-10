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

Refresh and the source's state (PR E2, section 3.2 and 3.4):
- `source_state()` compares the source file's stamp with the copy's (`SourceStamp`): up to date,
  out of date, not found, unreadable, another stamp version, or two differing files (the relative
  and the absolute path). A session cache keyed by the file's size and time keeps it cheap; it
  never changes the document.
- `plan_refresh()` reads the source again and says what a Refresh would do (the preview: added,
  changed, description changed, removed, removed but still used (an orphan, frozen), retyped,
  changed here and overwritten) and what stands in its way; `refresh()` applies it as one
  transaction, the stamp included, and checks the values as the import does (any failure undoes
  it). With another `path` (and entry or VarSet), it is Locate: the copy follows that file.

FreeCAD documents as a source (PR F, section 3.3): `read_fcstd()` reads a saved `.FCStd` as a
zip (its Document.xml) without opening it; `plan_copy()` and `copy_from_fcstd()` copy a VarSet
from it, and its Refresh is the same as a JSON copy's. A reference to anything outside the
source VarSet is a name the source uses but doesn't define (section 2.6), with one more choice:
freeze the value saved in the file. After the recompute, each copied variable's value must equal
the value saved in the file (unless it depends on a value chosen here).
"""

import datetime
import functools
import hashlib
import json
import math
import os
import re
import xml.etree.ElementTree as ElementTree
import zipfile
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
    # the names the imported entries define, once the skipped variables are left out
    defined: frozenset = frozenset()
    # unresolved name -> Binding (path and value), from `bindings` and `values`
    bindings: Dict[str, Binding] = field(default_factory=dict)
    # unresolved name -> (Onshape type, FreeCAD name, property type, translation) of the input
    # variables `values` asks for
    inputs: Dict[str, Tuple[str, str, str, onshape.Translation]] = field(default_factory=dict)
    inputs_set: Optional[str] = None  # the internal name of the set the inputs go in
    inputs_set_new: bool = False
    # name of a value FreeCAD can't use for its input variable -> the proposal (a name_map entry
    # gives another)
    input_renames: Dict[str, str] = field(default_factory=dict)
    # the edges of a cycle between the copies: (user source, provider source, variable, name)
    cycle: List[Tuple[int, int, str, str]] = field(default_factory=list)
    # FreeCAD names the copies would define that a local set defines too (decision 317) -> the
    # local variables' paths; the paths the copies make for them; and, from `clashes`, the path
    # each name's `#name` is to mean
    clashes: Dict[str, List[str]] = field(default_factory=dict)
    clash_paths: Dict[str, List[str]] = field(default_factory=dict)
    chosen: Dict[str, str] = field(default_factory=dict)
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
        for name, (_kind, fc_name, _type, _translation) in self.inputs.items():
            if fc_name != name:
                lines.append(f"The value of #{name} becomes {self.inputs_set}.{fc_name}")
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
                default_units: Optional[Mapping[str, str]] = None,
                clashes=None) -> Plan:
    """Reads and translates @a paths (Onshape exports) for @a doc and says what stands in the
    way; changes nothing.

    @a name_map: Onshape name -> FreeCAD name, instead of the proposal for a name FreeCAD can't
    use. @a bindings: unresolved name -> a document variable's path, `Object.Property` by
    internal name. @a values: unresolved name -> (Onshape type, Onshape text), an input variable
    in the document's "Variables" set. @a skip: unresolved names, or variable names, whose
    variables (and the ones that need them) aren't imported. @a providers: a name several
    entries define -> the source index (as in `Plan.sources`) that provides it.
    @a default_units: "LENGTH" / "ANGLE" -> the Onshape document's default unit.
    @a clashes: what `#name` means for a name a copy would define that a local set defines too
    (decision 317): IMPORT or LOCAL for every such name, or a dict FreeCAD name -> IMPORT, LOCAL
    or a path (`Variables.Width`, `Studio_A.Width`: "Pick"). None, or a name left out: nothing
    is chosen, and `#name` stays ambiguous for new expressions, as before (a warning says so).
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

    # Skipped variables leave the entries; what needs them waits on their name, which is skipped
    # unless a choice binds it.
    entries = [onshape.StudioEntry(s.entry.reference,
                                   tuple(v for v in s.entry.variables if v.name not in skip))
               for s in plan.sources]
    plan.defined = frozenset(v.name for e in entries for v in e.variables)

    # The choices for names nothing defines (section 2.6). One for a name the files define isn't
    # used: dropped before anything checks or makes it (an input variable nobody uses).
    for name in sorted((set(bindings) | set(values)) & plan.defined):
        plan.warnings.append(f"#{name} is defined by the imported files; its choice isn't used")
        bindings.pop(name, None)
        values.pop(name, None)
    for name in set(bindings) & set(values):
        plan.problems.append(f"#{name} has two choices: a document variable and a value")
    for name, path in bindings.items():
        try:
            plan.bindings[name] = Binding(path, _document_value(doc, path))
        except Exception as e:  # noqa: BLE001 (any failure to read it is a problem to show)
            plan.problems.append(f"#{name}: {e}")
    if values:
        _plan_inputs(doc, plan, values, default_units, name_map)

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
    plan.cycle = cycle
    if cycle:
        uses = ", ".join(f"{plan.sources[i].label}.{name} uses #{ref} of "
                         f"{plan.sources[j].label}" for i, j, name, ref in cycle)
        plan.problems.append(
            f"The copies would depend on each other ({uses}): a FreeCAD object can't depend on "
            "one that depends on it. Skip one of these variables.")
    made: Dict[str, List[str]] = {}
    provided: Dict[str, str] = {}
    for i, source in enumerate(plan.sources):
        for var in plan.variables(i):
            path = f"{source.name}.{var.freecad_name}"
            made.setdefault(var.freecad_name, []).append(path)
            if (providers or {}).get(var.name) == i:
                provided[var.freecad_name] = path
    _plan_clashes(doc, plan, made, provided, clashes,
                  {s.name: s.label + " (" + os.path.basename(s.path) + ")" for s in plan.sources})
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
    """The value of the document variable `Object.Property` (internal names), in SI units: the
    property's own value (its bare name as an expression would read `H` or `m` as a unit). The
    path must work in an expression; since rank 54 a variable named like a unit does, qualified
    (`Variables.H`)."""
    obj_name, _, prop = path.partition(".")
    obj = doc.getObject(obj_name)
    if obj is None or not prop or prop not in obj.PropertiesList:
        raise ValueError(f"{path} isn't a variable of this document")
    try:
        obj.evalExpression(path)
    except Exception as e:  # noqa: BLE001 (the parser's and the evaluation's errors alike)
        raise ValueError(f"{path} can't be used in an expression: {e}") from None
    return to_quantity(getattr(obj, prop), path)


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


def _plan_inputs(doc, plan: Plan, values, default_units, name_map):
    """Input variables for `values`, in the document's "Variables" set (made if missing). A
    name FreeCAD can't use there (`t`, or one the set has) gets a proposal, as the copies'
    variables do, and `name_map` can give another."""
    holder = _variables_set(doc)
    if holder is not None:
        plan.inputs_set = holder.Name
    else:
        plan.inputs_set = _unique_name(doc, VARIABLES, {s.name for s in plan.sources})
        plan.inputs_set_new = True
    rules = holder if holder is not None else "App::VarSet"
    taken = set()
    for name in sorted(values):
        if check_name(name, rules):
            plan.input_renames[name] = propose_name(name, taken | set(values), rules)
            taken.add(plan.input_renames[name])
    taken = set()
    for name, choice in values.items():
        try:
            kind, text = choice
        except (TypeError, ValueError):
            plan.problems.append(f"#{name}: a value is (Onshape type, text)")
            continue
        fc_name = name_map.get(name) or plan.input_renames.get(name, name)
        reason = check_name(fc_name, rules)
        if not reason and fc_name in taken:
            reason = f"another value is named {fc_name!r} too"
        if reason:
            plan.problems.append(
                f"#{name} can't be the input variable {fc_name} in {VARIABLES}: {reason}")
            continue
        taken.add(fc_name)
        try:
            translation = onshape.translate(text, kind, _no_reference, default_units)
        except onshape.Refused as e:
            plan.problems.append(f"#{name}: the value {text!r}: {e}")
            continue
        plan.inputs[name] = (kind, fc_name, translation.property_type, translation)
        plan.bindings[name] = Binding(f"{plan.inputs_set}.{fc_name}", translation.value)


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
        made = {copy.Name for copy in result.copies}
        for fc, path in plan.chosen.items():
            _record(copies_defining(doc, fc, exclude=made), fc, path)
        for copy in result.copies:
            copy.SourceKind = JSON_KIND  # the variables become read-only
    except BaseException:
        if own:
            doc.abortTransaction()
        for obj_name, prop in reversed(created):
            try:
                obj = doc.getObject(obj_name)
                if obj is None:
                    continue
                if prop is None:
                    doc.removeObject(obj_name)
                elif prop in obj.PropertiesList:
                    obj.removeProperty(prop)
            except Exception as e:  # noqa: BLE001 (the import's own error is the one to raise)
                App.Console.PrintWarning(
                    f"Import: couldn't remove {obj_name} {prop or ''}: {e}\n")
        raise
    if own:
        doc.commitTransaction()
    return result


def _make_inputs(doc, plan, created: list, inputs: list):
    """The input variables of @a plan's `values` choices, in the document's "Variables" set (made
    if missing); appends (set, name) to @a inputs."""
    if not plan.inputs:
        return
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
        inputs.append((holder, name))


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make(doc, plan: Plan, created: list) -> ImportResult:
    result = ImportResult(plan, [])
    _make_inputs(doc, plan, created, result.inputs)
    refreshed = _now()
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
            if var.freecad_name in plan.chosen:
                bindings[choice_key(var.freecad_name)] = plan.chosen[var.freecad_name]
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
    """Whether @a name comes from one of the imported entries, not from a binding (a skipped
    variable's name can be bound)."""
    return name in plan.defined


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
    has the variable's unit and the translator's value, and so has the value the variable
    stores (what its users read)."""
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
                stored = to_quantity(getattr(copy, var.freecad_name), where)
            except Exception as e:  # noqa: BLE001 (any failure is the check's)
                raise ImportCheckFailed(f"{where}: FreeCAD can't evaluate {text!r} "
                                        f"(from {var.variable.expression!r}): {e}") from None
            if got.dims != expected.dims or not onshape.values_agree(got.value, expected.value):
                raise ImportCheckFailed(
                    f"{where}: FreeCAD computes {_show(got)} for {text!r}, the translator "
                    f"{_show(expected)} for {var.variable.expression!r}")
            if stored.dims != got.dims or not onshape.values_agree(stored.value, got.value):
                raise ImportCheckFailed(
                    f"{where}: the variable holds {_show(stored)}, its expression {text!r} "
                    f"computes {_show(got)}")


# --- Name clashes between local and imported variables (ops#640, decision 317) -----------------
#
# A local variable (a plain VarSet's) and an imported one (a copy's) of the same name make `#name`
# ambiguous for new expressions: App's parser refuses it ("#Width is ambiguous: ...; write the
# full path"), the panel and the fields show both by their full paths, and stored expressions,
# which hold full paths, keep computing what they did. The user chooses which one `#name` means:
# the choice is recorded on every copy that defines the name, in its Bindings under `#name`, as
# the chosen variable's path; App reads it there (App/VariableChoice.h) when it parses `#name`
# and when it shows a reference as `#name`. Existing expressions keep the variables they name.

IMPORT = "import"
LOCAL = "local"


def choice_key(name: str) -> str:
    """The key under which a copy's Bindings records what `#name` means (a source's own names
    never start with '#')."""
    return "#" + name


@functools.lru_cache(maxsize=None)
def _usable(name: str, type_id: str) -> bool:
    """Whether @a name can be a variable of a @a type_id object (not one of its static
    properties, and read as a name by expressions)."""
    return not App.checkVariableName(name, type_id)


def _defines(obj, name: str) -> bool:
    return name in obj.PropertiesList and _usable(name, obj.TypeId)


def is_imported(obj) -> bool:
    """Whether @a obj's variables are imported ones: a copy still attached to its source. A
    detached copy (SourceKind "None") is a plain set of the document's own, a local one, as
    App's choice of what `#name` means takes it (App/VariableChoice.h; review R6-6)."""
    return obj.TypeId == COPY_TYPE and obj.SourceKind != DETACHED


def local_holders(doc, name: str) -> List[str]:
    """The paths of @a doc's variables named @a name that aren't imported, as `#name` finds
    them: a plain VarSet's or a detached copy's (a local variable) or a sheet's alias."""
    found = []
    for obj in doc.Objects:
        if obj.isDerivedFrom("App::VarSet"):
            if not is_imported(obj) and _defines(obj, name):
                found.append(f"{obj.Name}.{name}")
        elif obj.TypeId == "Spreadsheet::Sheet" and obj.getCellFromAlias(name):
            found.append(f"{obj.Name}.{name}")
    return found


def copies_defining(doc, name: str, exclude: Iterable[str] = ()) -> list:
    """The attached copies of @a doc (is_imported()) that define a variable @a name, but those
    whose internal names are in @a exclude: where the choice of what `#name` means is recorded
    (a detached copy's variables are local ones)."""
    exclude = set(exclude)
    return [obj for obj in doc.findObjects(COPY_TYPE)
            if obj.Name not in exclude and is_imported(obj) and _defines(obj, name)]


def _record(objs, name: str, path: str):
    key = choice_key(name)
    for copy in objs:
        bindings = dict(copy.Bindings)
        if bindings.get(key) != path:
            bindings[key] = path
            copy.Bindings = bindings  # an output property: doesn't touch the copy


def choose(doc, name: str, path: str):
    """Makes `#name` mean @a path (`Object.name`, internal names) in @a doc's new expressions:
    records it on every copy that defines @a name. Existing expressions keep the variables they
    name. Runs in the caller's transaction (the Variables panel's add), so an undo takes it back
    with what made the clash."""
    obj_name, _, prop = path.partition(".")
    holder = doc.getObject(obj_name)
    if (prop != name or holder is None or not holder.isDerivedFrom("App::VarSet")
            or not _defines(holder, name)):
        raise ValueError(f"{path} isn't a variable {name} of {doc.Name}")
    found = copies_defining(doc, name)
    if not found:
        raise ValueError(f"No copy defines {name}: #{name} needs no choice")
    _record(found, name, path)


def _plan_clashes(doc, plan, made: Mapping[str, List[str]], provided: Mapping[str, str],
                  clashes, labels: Mapping[str, str]):
    """Fills @a plan's clashes, clash_paths and chosen (and its problems and warnings) for the
    variables an import, a Refresh or a copy makes: @a made, FreeCAD name -> the paths made for
    it (several when several files define it, @a provided naming the one `providers` picks).
    @a clashes is plan_import()'s argument; @a labels names the copies in the warnings."""
    for fc in sorted(made):
        local = local_holders(doc, fc)
        if len(local) == 1:
            plan.clashes[fc] = local
            plan.clash_paths[fc] = list(made[fc])
        elif local:
            # ambiguous among the document's own already: no choice of the copy's can settle it
            plan.warnings.append(f"#{fc} is ambiguous here already ({', '.join(local)}) and "
                                 "stays so: new expressions write the full path")
    if clashes is None:
        wanted = {}
    elif isinstance(clashes, str):
        wanted = {fc: clashes for fc in plan.clashes}
    else:
        wanted = dict(clashes)
    for fc, choice in sorted(wanted.items()):
        if fc not in plan.clashes:
            plan.warnings.append(f"#{fc} isn't defined by one local set: its choice isn't used")
            continue
        local, ours = plan.clashes[fc], list(made[fc])
        if choice == LOCAL:
            options = local
        elif choice == IMPORT:
            options = [provided[fc]] if len(ours) > 1 and fc in provided else ours
        else:
            others = [f"{obj.Name}.{fc}" for obj in copies_defining(doc, fc)]
            candidates = local + ours + [p for p in others if p not in ours]
            if choice not in candidates:
                plan.problems.append(f"#{fc} can't mean {choice}: pick one of "
                                     f"{', '.join(candidates)}")
                continue
            options = [choice]
        if len(options) != 1:
            plan.problems.append(f"#{fc} is defined by {', '.join(options)}: pick which one "
                                 f"#{fc} means")
            continue
        plan.chosen[fc] = options[0]
    for fc, local in sorted(plan.clashes.items()):
        where = ", ".join(labels.get(p.partition(".")[0], p) for p in plan.clash_paths[fc])
        line = f"#{fc} is defined here by {', '.join(local)} and comes from {where} too: "
        if fc in plan.chosen:
            line += f"new expressions' #{fc} means {plan.chosen[fc]}"
        else:
            line += (f"#{fc} stays ambiguous for new expressions (they write the full path) "
                     "until you choose")
        plan.warnings.append(line + "; existing expressions keep the variable they use")


def detach(copy):
    """Turns @a copy into a plain set of variables, editable, with no source, as one undo step
    (section 3.1, Detach). The object keeps its type; refreshing it is no longer possible."""
    if copy.TypeId != COPY_TYPE:
        raise TypeError(f"{copy.Label} isn't a copy")
    doc = copy.Document
    own = doc.getBookedTransactionID() == 0
    # SourceKind last: until it changes, the copy is still attached and read-only.
    # The choices of what `#name` means (decision 317) stay: they are the document's, not the
    # source's.
    records = {key: path for key, path in dict(copy.Bindings).items() if key.startswith("#")}
    cleared = {"SourcePath": "", "SourceRelativePath": "", "SourceObject": "",
               "SourceEntries": 0, "SourceStamp": "", "SourceRefreshed": "",
               "SourceExpressions": {}, "NameMap": {}, "Bindings": records, "Skipped": [],
               "Orphans": [], "SourceKind": DETACHED}
    before = {name: getattr(copy, name) for name in cleared}
    if own:
        doc.openTransaction(f"Detach {copy.Label}")
    try:
        for name, value in cleared.items():
            setattr(copy, name, value)
    except BaseException:
        if own:
            doc.abortTransaction()
        else:  # someone else's transaction, or none: put back what was set
            for name in reversed(list(cleared)):
                try:
                    setattr(copy, name, before[name])
                except Exception as e:  # noqa: BLE001 (Detach's own error is the one to raise)
                    App.Console.PrintWarning(f"Detach: couldn't restore {name}: {e}\n")
        raise
    if own:
        doc.commitTransaction()



# --- The source's state and Refresh (PR E2), FreeCAD documents as a source (PR F) -------------

FCSTD_KIND = "FreeCAD document"
# A FreeCAD source's stamp (section 3.2): the canonical form of a VarSet read from a saved file.
STAMP_FCSTD = "sha256:fcstd1:"
# The VarSet types a FreeCAD source can be: a copy of a copy is allowed (section 3.1).
VARSET_TYPES = ("App::VarSet", COPY_TYPE)

# The states of section 3.2, as source_state() names them.
UP_TO_DATE = "up to date"
OUT_OF_DATE = "out of date"
NOT_FOUND = "not found"
UNREADABLE = "unreadable"
OTHER_STAMP = "other stamp"
TWO_SOURCES = "two sources"
DETACHED_STATE = "detached"

# The default units a unitless Length or Angle can take (the import dialog's list).
_DEFAULT_UNITS = {"LENGTH": ("mm", "cm", "m", "in", "ft", "yd"), "ANGLE": ("deg", "rad")}
# A binding that is a frozen value (section 3.3), not a path: `12.5 mm`, `30.0 deg`, `3.0`.
_FROZEN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?: (?:mm|deg))?\Z")


class RefreshBlocked(Exception):
    """Something stands in the way of a Refresh (or of a copy from a FreeCAD file) and nothing was
    changed; `plan` says what."""

    def __init__(self, plan: "RefreshPlan"):
        super().__init__(plan.report())
        self.plan = plan


class RefreshCheckFailed(ImportCheckFailed):
    """A value after the Refresh disagrees with the translator's, or with the value saved in the
    source file: the Refresh was undone."""


class SourceError(ValueError):
    """The source file can't be read as what it should be; str() says why."""


def _native(path: str) -> str:
    return os.path.normpath(path) if path else ""


def _short(type_id: str) -> str:
    return type_id.replace("App::Property", "")


def _expression_text(obj, prop: str) -> Optional[str]:
    for path, text in obj.ExpressionEngine:
        if path == prop:
            return text
    return None


# --- FreeCAD expressions: the paths they name --------------------------------------------------

_FC_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<string><<(?:\\.|[^\\>\n]|>(?!>))*>>)
  | (?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)
  | (?P<name>[^\W\d]\w*)
  | (?P<op>.)
""", re.VERBOSE | re.DOTALL)


@dataclass
class FcPath:
    """A path a FreeCAD expression names: `Width`, `.Width`, `VarSet.Width`, `<<My set>>.Width`,
    `Doc#Box.Length`, `Box.Placement.Base.x`."""

    start: int
    end: int
    text: str
    document: Optional[str]
    obj: Optional[str]  # an internal name, or a label when `by_label`
    by_label: bool
    props: List[str]
    local: bool  # written `.Width`: the owner's own property
    indexed: bool  # followed by `[...]`


def _unquote(token) -> str:
    if token[0] != "string":
        return token[1]
    return re.sub(r"\\(.)", r"\1", token[1][2:-2])


def fc_paths(text: str) -> List[FcPath]:
    """The paths a FreeCAD expression @a text names, with their spans. Function names, string
    literals and numbers aren't paths; a unit (`mm`) is one here: the caller tells it from a
    variable."""
    tokens = [(m.lastgroup, m.group(), m.start(), m.end()) for m in _FC_TOKEN.finditer(text)
              if m.lastgroup != "space"]
    paths = []
    i = 0
    while i < len(tokens):
        kind, value, start, _end = tokens[i]
        after_operand = i > 0 and (tokens[i - 1][0] in ("name", "string", "number")
                                   or tokens[i - 1][1] in (")", "]"))
        local = False
        if (kind == "op" and value == "." and i + 1 < len(tokens)
                and tokens[i + 1][0] in ("name", "string") and not after_operand):
            local = True
            j = i + 1
        elif kind in ("name", "string"):
            j = i
        else:
            i += 1
            continue
        parts = [tokens[j]]
        seps = []
        k = j + 1
        while k + 1 < len(tokens) and tokens[k][0] == "op":
            sep = tokens[k][1]
            if (sep == "@" and tokens[k + 1][1] == "." and k + 2 < len(tokens)
                    and tokens[k + 2][0] in ("name", "string")):
                seps.append(".")
                parts.append(tokens[k + 2])
                k += 3
            elif sep in ("#", ".") and tokens[k + 1][0] in ("name", "string"):
                seps.append(sep)
                parts.append(tokens[k + 1])
                k += 2
            else:
                break
        if len(parts) == 1 and not local and (
                kind == "string" or (k < len(tokens) and tokens[k][1] == "(")):
            i = k  # a string literal, or a function's name
            continue
        names = [_unquote(p) for p in parts]
        document = obj = None
        by_label = False
        if "#" in seps:
            document = names[0]
            obj = names[1] if len(names) > 1 else None
            by_label = len(parts) > 1 and parts[1][0] == "string"
            props = names[2:]
        elif local or len(parts) == 1:
            props = names
        else:
            obj = names[0]
            by_label = parts[0][0] == "string"
            props = names[1:]
        end = parts[-1][3]
        indexed = k < len(tokens) and tokens[k][1] == "["
        paths.append(FcPath(start, end, text[start:end], document, obj, by_label, props, local,
                            indexed))
        i = k
    return paths


@functools.lru_cache(maxsize=None)
def _is_unit_or_constant(name: str) -> bool:
    """Whether FreeCAD's parser reads @a name alone as a unit or a constant (`mm`, `t`, `pi`)."""
    if name in ("pi", "e", "True", "False"):
        return True
    try:
        App.Units.Quantity("1 " + name)
    except Exception:  # noqa: BLE001 (not a unit: the parser's error)
        return False
    return True


# --- Who uses a copy's variable (section 3.5) --------------------------------------------------

def _expressions_of(obj) -> List[Tuple[str, str]]:
    """(path, text) of @a obj's expressions: its ExpressionEngine, and a sheet's formulas."""
    found = []
    try:
        found.extend((str(path), str(text)) for path, text in obj.ExpressionEngine)
    except Exception:  # noqa: BLE001 (an object without one)
        pass
    if obj.TypeId == "Spreadsheet::Sheet":
        try:
            for cell in obj.getUsedCells():
                content = obj.getContents(cell)
                if isinstance(content, str) and content.startswith("="):
                    found.append((cell, content[1:]))
        except Exception:  # noqa: BLE001 (a sheet that can't list its cells)
            pass
    return found


def _names_variable(path: FcPath, copy, name: str, same_document: bool) -> bool:
    if path.obj is None or not path.props or path.props[0] != name:
        return False
    if path.obj != (copy.Label if path.by_label else copy.Name):
        return False
    if path.document is None:
        return same_document
    return path.document in (copy.Document.Name, copy.Document.Label)


def uses(copy, name: str) -> List[str]:
    """Where @a copy's variable @a name is used outside the copy, in every open document:
    `Box.Length`, `Other doc#Pad.Length` (labels, then the property)."""
    found = set()
    home = copy.Document.Name
    for doc in App.listDocuments().values():
        same = doc.Name == home
        for obj in doc.Objects:
            if same and obj.Name == copy.Name:
                continue
            for prop, text in _expressions_of(obj):
                if any(_names_variable(p, copy, name, same) for p in fc_paths(text)):
                    where = f"{obj.Label}.{prop}"
                    found.add(where if same else f"{doc.Label}#{where}")
    return sorted(found)


def _user_objects(users: Iterable[str]) -> List[str]:
    """The objects of @a users (`Box.Length` -> `Box`)."""
    return sorted({u.split(".", 1)[0] for u in users})


# --- Reading a saved FreeCAD document (section 3.3) --------------------------------------------

@dataclass
class FcProperty:
    name: str
    type: str
    dynamic: bool  # a variable (a dynamic property: saved with its group)
    description: str
    element: Optional[object]  # the value's element (`<Float value="..."/>`), or None


@dataclass
class FcObject:
    name: str
    type: str
    label: str = ""
    touched: bool = False  # saved before its recompute: its values may be stale
    invalid: bool = False  # saved with an error
    properties: Dict[str, FcProperty] = field(default_factory=dict)  # the file's order (by name)
    expressions: Dict[str, str] = field(default_factory=dict)  # property path -> saved text

    def variables(self) -> List[FcProperty]:
        return [p for p in self.properties.values() if p.dynamic]

    def string(self, name: str) -> str:
        prop = self.properties.get(name)
        if prop is None or prop.element is None:
            return ""
        return prop.element.get("value", "")

    def expression(self, name: str) -> str:
        return self.expressions.get(name, self.expressions.get("." + name, ""))


@dataclass
class FcFile:
    path: str
    objects: Dict[str, FcObject]

    def find(self, name: str, by_label: bool = False) -> Optional[FcObject]:
        if not by_label:
            return self.objects.get(name)
        found = [o for o in self.objects.values() if o.label == name]
        return found[0] if len(found) == 1 else None


def read_fcstd(path: str) -> FcFile:
    """The objects of a saved FreeCAD document, read from its Document.xml without opening the
    document (no shapes, no recompute, no recent-file entry): their types, saved states and
    properties. Raises OSError or SourceError."""
    try:
        with zipfile.ZipFile(path) as archive:
            data = archive.read("Document.xml")
    except zipfile.BadZipFile:
        raise SourceError("it isn't a FreeCAD document (not a zip file)") from None
    except KeyError:
        raise SourceError("it isn't a FreeCAD document (no Document.xml)") from None
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as e:
        raise SourceError(f"its Document.xml can't be read: {e}") from None
    if root.tag != "Document":
        raise SourceError("it isn't a FreeCAD document")
    objects: Dict[str, FcObject] = {}
    for element in root.iterfind("Objects/Object"):
        name = element.get("name")
        if name:
            objects[name] = FcObject(
                name, element.get("type", ""),
                touched=element.get("Touched", "0") not in ("", "0"),
                invalid=element.get("Invalid", "0") not in ("", "0", "false"))
    for element in root.iterfind("ObjectData/Object"):
        obj = objects.get(element.get("name"))
        if obj is None:
            continue
        for prop in element.iterfind("Properties/Property"):
            name, kind = prop.get("name", ""), prop.get("type", "")
            value = prop[0] if len(prop) else None
            obj.properties[name] = FcProperty(name, kind, prop.get("group") is not None,
                                              prop.get("doc", ""), value)
            if kind == "App::PropertyExpressionEngine" and value is not None:
                for expression in value.iterfind("Expression"):
                    obj.expressions[expression.get("path", "")] = expression.get("expression", "")
        obj.label = obj.string("Label") or obj.name
    return FcFile(_portable(os.path.abspath(path)), objects)


def fcstd_varsets(path: str) -> List[Tuple[str, str, int]]:
    """(internal name, label, number of variables) of each VarSet saved in @a path, in the file's
    order; copies included (a copy of a copy is allowed)."""
    return [(o.name, o.label, len(o.variables()))
            for o in read_fcstd(path).objects.values() if o.type in VARSET_TYPES]


# The variable types a FreeCAD source's variable can have (section 3.3).
_FC_LENGTHS = ("App::PropertyLength", "App::PropertyDistance")
_FC_TYPES = _FC_LENGTHS + ("App::PropertyAngle", "App::PropertyFloat", "App::PropertyBool",
                           "App::PropertyString")


def fc_value(prop: FcProperty):
    """(value, unit) saved for a variable of a FreeCAD source: a float in mm, deg or plain, a
    bool or a str; unit "mm", "deg" or "". Raises onshape.Refused for a type that isn't read,
    with the reason (section 3.3)."""
    if prop.type == "App::PropertyInteger":
        raise onshape.Refused("an Integer variable rounds what an expression gives it (ops#319): "
                              "make it a Number")
    if prop.type == "App::PropertyQuantity":
        raise onshape.Refused("a plain Quantity variable: its unit isn't saved in the file")
    if prop.type not in _FC_TYPES:
        raise onshape.Refused(f"a {_short(prop.type)} variable: only Length, Distance, Angle, "
                              "Float (Number), Bool and String variables are copied")
    if prop.element is None:
        raise onshape.Refused("its value isn't in the file")
    text = prop.element.get("value")
    if prop.type == "App::PropertyBool":
        return text == "true", ""
    if prop.type == "App::PropertyString":
        return text or "", ""
    try:
        number = float(text)
    except (TypeError, ValueError):
        raise onshape.Refused(f"its saved value {text!r} can't be read") from None
    if prop.type in _FC_LENGTHS:
        return number, "mm"
    if prop.type == "App::PropertyAngle":
        return number, "deg"
    return number, ""


def stamp_fcstd(obj: FcObject) -> str:
    """`sha256:fcstd1:` and the SHA-256 of a FreeCAD source VarSet's canonical form (section
    3.2): per variable, in the file's order (by name), its name, type, saved expression,
    description, and saved value with its unit (None for a type that isn't copied). A resave that
    changes nothing keeps it; a frozen value that changes at the source changes it."""
    data = []
    for prop in obj.variables():
        try:
            value, unit = fc_value(prop)
        except onshape.Refused:
            value, unit = None, ""
        data.append([prop.name, prop.type, obj.expression(prop.name), prop.description, value,
                     unit])
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return STAMP_FCSTD + hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- The source's state (section 3.2) ----------------------------------------------------------

@dataclass
class SourceState:
    state: str  # UP_TO_DATE, OUT_OF_DATE, NOT_FOUND, UNREADABLE, OTHER_STAMP, TWO_SOURCES...
    message: str
    path: str = ""  # the file read ("" when none was)
    detail: str = ""  # more, for a tooltip


# (normalized path, kind, object) -> ((size, mtime_ns), (stamp, entries, stale, about) or error):
# a session cache, never a property, so a check never marks the document modified.
_stamp_cache: Dict[tuple, tuple] = {}
# (document, copy, state, stamp) already written to the Report view
_reported: set = set()


def _same_file(a: str, b: str) -> bool:
    if not a or not b:
        return False
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def source_candidates(copy) -> List[str]:
    """The source files of @a copy that exist: the path relative to its document's file first,
    then the absolute one (section 3.2), each file once."""
    found = []
    folder = os.path.dirname(copy.Document.FileName) if copy.Document.FileName else ""
    if copy.SourceRelativePath and folder:
        path = os.path.normpath(os.path.join(folder, copy.SourceRelativePath))
        if os.path.isfile(path):
            found.append(path)
    if (copy.SourcePath and os.path.isfile(copy.SourcePath)
            and not any(_same_file(copy.SourcePath, f) for f in found)):
        found.append(os.path.normpath(copy.SourcePath))
    return found


def _compute_stamp(path: str, kind: str, obj: str):
    if kind == JSON_KIND:
        entries = onshape.read_export(path)
        try:
            index = int(obj)
        except ValueError:
            raise SourceError(f"the copy's entry {obj!r} isn't an index") from None
        if not 0 <= index < len(entries):
            raise SourceError(f"it has no studio entry {index + 1}")
        return stamp(entries[index]), len(entries), "", ""
    source = read_fcstd(path).objects.get(obj)
    if source is None or source.type not in VARSET_TYPES:
        raise SourceError(f"it has no VarSet {obj}")
    stale = ""
    if source.invalid:
        stale = f"{source.label} was saved with an error: its values may be stale"
    elif source.touched:
        stale = f"{source.label} was saved before its recompute: its values may be stale"
    about = ""
    if source.type == COPY_TYPE:
        about = (f"The source is a copy of {os.path.basename(source.string('SourcePath'))}, "
                 f"refreshed on {source.string('SourceRefreshed') or 'no date'}")
    return stamp_fcstd(source), 0, stale, about


def _read_stamp(path: str, kind: str, obj: str):
    """(stamp, entries, stale, about) of the source @a obj in @a path; raises OSError or
    SourceError. Read again only when the file's size or time changed."""
    st = os.stat(path)
    key = (os.path.normcase(os.path.abspath(path)), kind, obj)
    cached = _stamp_cache.get(key)
    if cached is not None and cached[0] == (st.st_size, st.st_mtime_ns):
        result = cached[1]
    else:
        try:
            result = _compute_stamp(path, kind, obj)
        except (OSError, SourceError, onshape.ExportError) as e:
            result = SourceError(str(e))
        _stamp_cache[key] = ((st.st_size, st.st_mtime_ns), result)
    if isinstance(result, Exception):
        raise result
    return result


def _open_note(path: str) -> str:
    """A FreeCAD source open here with unsaved changes: Refresh reads the saved file."""
    for doc in App.listDocuments().values():
        if not doc.FileName or not _same_file(doc.FileName, path):
            continue
        modified = False
        try:
            if App.GuiUp:
                import FreeCADGui
                modified = bool(FreeCADGui.getDocument(doc.Name).Modified)
            else:
                modified = bool(doc.isTouched())
        except Exception:  # noqa: BLE001 (no Gui document yet: nothing to say)
            modified = False
        if modified:
            return (f"{os.path.basename(path)} is open with unsaved changes: Refresh reads the "
                    "saved file")
    return ""


def _two_sources(copy, candidates) -> Optional[str]:
    """The message when the relative and the absolute path are different files that differ in
    content (section 3.2: shown, never chosen silently), else None."""
    if len(candidates) < 2:
        return None
    stamps = []
    for path in candidates[:2]:
        try:
            stamps.append(_read_stamp(path, copy.SourceKind, copy.SourceObject)[0])
        except (OSError, SourceError) as e:
            stamps.append(f"error: {e}")
    if stamps[0] == stamps[1]:
        return None
    return (f"Two different sources: {_native(candidates[0])} (relative to this document) and "
            f"{_native(candidates[1])}. Locate... the one to use")


def source_state(copy) -> SourceState:
    """The state of @a copy's source (section 3.2): up to date, out of date (the stamp differs),
    not found, unreadable (the file, the entry or the VarSet; a FreeCAD source saved with stale
    values), a stamp of another version (can't compare), or two differing files. Reads the file
    only when its size or time changed this session; changes nothing."""
    if copy.TypeId != COPY_TYPE or copy.SourceKind == DETACHED:
        return SourceState(DETACHED_STATE, "Detached: its variables are editable")
    refreshed = copy.SourceRefreshed or "never"
    candidates = source_candidates(copy)
    if not candidates:
        shown = copy.SourcePath or copy.SourceRelativePath
        return SourceState(NOT_FOUND, f"{_native(shown)} is missing. Locate...")
    two = _two_sources(copy, candidates)
    if two:
        return SourceState(TWO_SOURCES, two, "", "\n".join(_native(p) for p in candidates))
    path = candidates[0]
    name = os.path.basename(path)
    try:
        new_stamp, entries, stale, about = _read_stamp(path, copy.SourceKind, copy.SourceObject)
    except (OSError, SourceError) as e:
        return SourceState(UNREADABLE, f"{name} can't be read: {e}", path, _native(path))
    extra = [x for x in (about, _open_note(path) if copy.SourceKind == FCSTD_KIND else "") if x]
    detail = "\n".join([_native(path)] + extra)
    if copy.SourceKind == JSON_KIND and entries != copy.SourceEntries:
        return SourceState(
            UNREADABLE, f"{name} now has {entries} studio entries (it had {copy.SourceEntries}): "
            "Locate... the entry", path, detail)
    if stale:
        return SourceState(UNREADABLE, f"{name}: {stale}. Recompute and save it, then Refresh",
                           path, detail)
    version = new_stamp[:new_stamp.rindex(":") + 1]
    if not copy.SourceStamp.startswith(version):
        state = OTHER_STAMP
        message = (f"The stamp is of another version, so {name} can't be compared: Refresh to "
                   "update it")
    elif copy.SourceStamp == new_stamp:
        state, message = UP_TO_DATE, f"Up to date with {name} (refreshed {refreshed})"
    else:
        state = OUT_OF_DATE
        message = f"{name} changed since the last Refresh ({refreshed}). Refresh"
    if extra:
        message += ". " + ". ".join(extra)
    return SourceState(state, message, path, detail)


def panel_state(copy):
    """For the Variables panel: (state, message, tooltip, {orphan: its flag}) of @a copy. The
    first time a copy is seen not up to date, one line goes to the Report view (section 3.2)."""
    state = source_state(copy)
    if state.state not in (UP_TO_DATE, DETACHED_STATE):
        key = (copy.Document.Name, copy.Name, state.state, copy.SourceStamp)
        if key not in _reported:
            _reported.add(key)
            App.Console.PrintWarning(f"{copy.Label}: {state.message}\n")
    orphans = {}
    props = set(copy.PropertiesList)
    for name in copy.Orphans:
        if name not in props:
            continue
        users = _user_objects(uses(copy, name))
        orphans[name] = "removed at the source; " + (
            f"used by {', '.join(users)}" if users else "no longer used")
    return state.state, state.message, state.detail, orphans


# --- Refresh (section 3.4) ----------------------------------------------------------------------

@dataclass
class Target:
    """A copied variable as a Refresh (or a copy from a FreeCAD file) leaves it."""

    name: str  # the source's name
    fc_name: str
    property_type: str
    text: Optional[str]  # the FreeCAD expression; None: a plain value
    expected: object  # the translator's Quantity (JSON), or (value, unit) saved in the file
    description: str
    source_text: str  # SourceExpressions' entry: the source's expression ("" for a plain value)
    check: bool = True  # the value after the recompute must equal `expected`
    translation: Optional[onshape.Translation] = None  # JSON
    external: bool = False  # it uses a name its source doesn't define


@dataclass
class RefreshPlan:
    """What a Refresh (or a copy from a FreeCAD file, `copy` None) would do: the preview of
    section 3.4, and what stands in its way. Variables are named by their FreeCAD names."""

    copy: object
    doc: object
    kind: str
    path: str = ""
    object: str = ""  # SourceObject: the entry's index (JSON) or the VarSet's name (FreeCAD)
    entries: int = 0
    label: str = ""
    name: str = ""
    stamp: str = ""
    targets: List[Target] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    restored: List[str] = field(default_factory=list)  # orphans the source defines again
    changed: List[str] = field(default_factory=list)
    described: List[str] = field(default_factory=list)
    retyped: Dict[str, Tuple[str, str, List[str]]] = field(default_factory=dict)
    overwritten: List[str] = field(default_factory=list)  # changed here, from Python
    removed: List[str] = field(default_factory=list)  # unused: deleted
    orphaned: Dict[str, List[str]] = field(default_factory=dict)  # removed, still used: users
    orphans: List[str] = field(default_factory=list)  # Orphans after the Refresh
    renames: Dict[str, str] = field(default_factory=dict)  # new proposals
    name_map: Dict[str, str] = field(default_factory=dict)
    binding_texts: Dict[str, str] = field(default_factory=dict)  # Bindings after the Refresh
    skipped_names: List[str] = field(default_factory=list)  # Skipped after the Refresh
    skipped: List[Tuple[str, str]] = field(default_factory=list)  # (name, why)
    refused: List[Tuple[str, str]] = field(default_factory=list)  # (name, reason)
    unresolved: Dict[str, List[str]] = field(default_factory=dict)  # name -> its users
    gone: Dict[str, str] = field(default_factory=dict)  # name -> why its binding no longer works
    ambiguous: Dict[str, List[str]] = field(default_factory=dict)  # name -> copies defining it
    switchable: Dict[str, Tuple[str, str]] = field(default_factory=dict)  # name -> (bound, copies)
    freezable: Dict[str, str] = field(default_factory=dict)  # FreeCAD: name -> the frozen text
    # as Plan's (decision 317): names a local set defines too that have no choice on the copy yet
    clashes: Dict[str, List[str]] = field(default_factory=dict)
    clash_paths: Dict[str, List[str]] = field(default_factory=dict)
    chosen: Dict[str, str] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # the choices' bindings (JSON: Binding objects the translator reads) and the input variables
    # of `values`, as plan_import's (_plan_inputs fills them)
    bindings: Dict[str, Binding] = field(default_factory=dict)
    recorded: set = field(default_factory=set)  # names whose binding goes into Bindings
    sources: list = field(default_factory=list)
    inputs: Dict[str, tuple] = field(default_factory=dict)
    inputs_set: Optional[str] = None
    inputs_set_new: bool = False
    input_renames: Dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        """`Added 2, changed 3, description changed 1, removed 1 (used by 2 objects), retyped
        1`, or "Nothing changed at the source"."""
        parts = []
        if self.added or self.restored:
            parts.append(f"added {len(self.added) + len(self.restored)}")
        if self.changed:
            parts.append(f"changed {len(self.changed)}")
        if self.described:
            parts.append(f"description changed {len(self.described)}")
        removed = len(self.removed) + len(self.orphaned)
        if removed:
            text = f"removed {removed}"
            if self.orphaned:
                count = len(_user_objects(u for users in self.orphaned.values() for u in users))
                text += f" (used by {count} object{'' if count == 1 else 's'})"
            parts.append(text)
        if self.retyped:
            parts.append(f"retyped {len(self.retyped)}")
        if self.overwritten:
            parts.append(f"changed here and overwritten {len(self.overwritten)}")
        if not parts:
            return "Nothing changed at the source"
        text = ", ".join(parts)
        return text[0].upper() + text[1:]

    def report(self) -> str:
        lines = list(self.problems)
        if self.copy is None:
            if self.added:
                lines.append(f"Copies {len(self.added)} variables: {', '.join(self.added)}")
        else:
            lines.append(self.summary() + ".")
            for name in self.added:
                lines.append(f"Added: {name}")
            for name in self.restored:
                lines.append(f"Added again: {name} (an orphan until now)")
            for name in self.changed:
                lines.append(f"Changed: {name}")
            for name in self.described:
                lines.append(f"Description changed: {name}")
            for name, (old, new, users) in self.retyped.items():
                line = f"Retyped: {name}, {_short(old)} to {_short(new)}"
                lines.append(line + (f"; used by {', '.join(users)}" if users else ""))
            for name in self.removed:
                lines.append(f"Removed: {name}")
            for name, users in self.orphaned.items():
                lines.append(f"Removed at the source but used by {', '.join(users)}: {name} stays "
                             "as an orphan, frozen to its value")
            for name in self.overwritten:
                lines.append(f"Changed here, overwritten: {name}")
        for name, fc_name in self.renames.items():
            lines.append(f"{name} becomes {fc_name}")
        for name, why in self.skipped:
            lines.append(f"{name} is skipped: {why}")
        lines.extend(self.notes)
        lines.extend(self.warnings)
        return "\n".join(lines)


@dataclass
class _Choices:
    name_map: Dict[str, str]
    bindings: Dict[str, str]
    values: Dict[str, Tuple[str, str]]
    skip: set
    freeze: set
    providers: Dict[str, str]
    switch: set
    default_units: Dict[str, str]
    clashes: object = None  # plan_import()'s `clashes`


def _choices(name_map=None, bindings=None, values=None, skip=(), freeze=(), providers=None,
             switch=(), default_units=None, clashes=None) -> _Choices:
    return _Choices(dict(name_map or {}), dict(bindings or {}), dict(values or {}), set(skip),
                    set(freeze), dict(providers or {}), set(switch), dict(default_units or {}),
                    clashes)


def plan_refresh(copy, path: Optional[str] = None, *, entry: Optional[int] = None,
                 varset: Optional[str] = None, **choices) -> RefreshPlan:
    """Reads @a copy's source again and says what a Refresh would do and what stands in its way
    (section 3.4); changes nothing.

    @a path: another source file (Locate), with @a entry (JSON, from 0: needed when the file's
    number of entries changed) or @a varset (FreeCAD: the VarSet's internal name). The choices,
    as plan_import()'s: `name_map`, `bindings` (a name -> a document variable's path), `values`
    (a name -> (Onshape type, text): an input variable), `skip` (names), `default_units`; and
    `providers` (a name several other copies define -> the copy's internal name), `switch`
    (bound names to switch to the copy that now defines them), `freeze` (FreeCAD: references
    whose saved value is used), `clashes` (plan_import()'s: for the names a local set defines
    too, those the copy has no choice for yet). The copy's Bindings, NameMap and Skipped are kept
    unless a choice changes them.
    """
    if copy.TypeId != COPY_TYPE:
        raise TypeError(f"{copy.Label} isn't a copy")
    doc = copy.Document
    plan = RefreshPlan(copy, doc, copy.SourceKind, label=copy.Label, name=copy.Name)
    if copy.SourceKind == DETACHED:
        plan.problems.append(f"{copy.Label} is detached: it has no source to refresh from")
        return plan
    if doc.getBookedTransactionID() != 0:
        plan.problems.append("Another edit is open: finish it before a Refresh")
        return plan
    if path is None:
        candidates = source_candidates(copy)
        if not candidates:
            shown = copy.SourcePath or copy.SourceRelativePath
            plan.problems.append(f"{_native(shown)} is missing: Locate... the source")
            return plan
        two = _two_sources(copy, candidates)
        if two:
            plan.problems.append(two)
            return plan
        path = candidates[0]
    elif not os.path.isfile(path):
        plan.problems.append(f"{_native(path)} doesn't exist")
        return plan
    plan.path = _portable(os.path.abspath(path))
    c = _choices(**choices)
    if copy.SourceKind == JSON_KIND:
        _plan_json(plan, entry, c)
    else:
        _plan_fcstd(plan, varset if varset is not None else copy.SourceObject, c)
    if plan.stamp:
        _diff(plan)
    # a name chosen before keeps its choice
    made = {t.fc_name: [f"{copy.Name}.{t.fc_name}"] for t in plan.targets
            if choice_key(t.fc_name) not in copy.Bindings}
    _plan_clashes(doc, plan, made, {}, c.clashes,
                  {copy.Name: f"{copy.Label} ({os.path.basename(plan.path)})"})
    _list_problems(plan)
    return plan


def refresh(copy, path: Optional[str] = None, **choices) -> RefreshPlan:
    """Refreshes @a copy from its source (or Locate: from @a path) as one transaction ("Refresh
    <label>"), the stamp included; the arguments are plan_refresh()'s. Raises RefreshBlocked
    (nothing changed) when anything stands in the way, and RefreshCheckFailed (everything undone)
    when a value disagrees. Returns the plan applied."""
    plan = plan_refresh(copy, path, **choices)
    if not plan.ok:
        raise RefreshBlocked(plan)
    _transaction(plan.doc, f"Refresh {copy.Label}", lambda: _apply(plan, copy))
    return plan


def plan_copy(doc, path: str, varset: str, **choices) -> RefreshPlan:
    """What copying the VarSet @a varset (internal name) of the saved FreeCAD document @a path
    into @a doc would do, and what stands in its way (section 3.3); changes nothing. The choices
    are plan_refresh()'s (`freeze` included)."""
    plan = RefreshPlan(None, doc, FCSTD_KIND)
    if doc.getBookedTransactionID() != 0:
        plan.problems.append("Another edit is open: finish it first")
        return plan
    if not os.path.isfile(path):
        plan.problems.append(f"{_native(path)} doesn't exist")
        return plan
    plan.path = _portable(os.path.abspath(path))
    c = _choices(**choices)
    _plan_fcstd(plan, varset, c)
    if plan.label:
        plan.name = _unique_name(doc, plan.label, ())
        made = {t.fc_name: [f"{plan.name}.{t.fc_name}"] for t in plan.targets}
        _plan_clashes(doc, plan, made, {}, c.clashes,
                      {plan.name: f"{plan.label} ({os.path.basename(plan.path)})"})
    for obj in doc.findObjects(COPY_TYPE):
        if (obj.SourceKind == FCSTD_KIND and obj.SourceObject == varset
                and _same_file(obj.SourcePath, plan.path)):
            plan.warnings.append(f"{obj.Label} is already a copy of {plan.label}")
    _diff(plan)
    _list_problems(plan)
    return plan


def copy_from_fcstd(doc, path: str, varset: str, **choices):
    """Copies the VarSet @a varset of the saved FreeCAD document @a path into @a doc as an
    attached copy (SourceKind "FreeCAD document"), in one transaction ("Copy <label>"); the
    arguments are plan_copy()'s. Raises RefreshBlocked or RefreshCheckFailed (nothing left).
    Returns the copy."""
    plan = plan_copy(doc, path, varset, **choices)
    if not plan.ok:
        raise RefreshBlocked(plan)
    made = []

    def body():
        copy = doc.addObject(COPY_TYPE, plan.name)
        copy.Label = plan.label
        made.append(copy)
        _apply(plan, copy)
        copy.SourceKind = FCSTD_KIND  # last: the variables become read-only

    _transaction(doc, f"Copy {plan.label}", body)
    return made[0]


def _transaction(doc, title: str, body):
    """Runs @a body in a transaction of its own, aborted on any error. A document without undo
    gets it for the time being, so the abort can take everything back."""
    undo = doc.UndoMode
    if not undo:
        doc.UndoMode = 1
    try:
        doc.openTransaction(title)
        try:
            body()
        except BaseException:
            doc.abortTransaction()
            raise
        doc.commitTransaction()
    finally:
        if not undo:
            doc.UndoMode = 0


# --- Refresh: a JSON source ----------------------------------------------------------------------

def _plan_json(plan: RefreshPlan, entry: Optional[int], c: _Choices):
    copy, doc = plan.copy, plan.doc
    base = os.path.basename(plan.path)
    try:
        entries = onshape.read_export(plan.path)
    except (OSError, onshape.ExportError) as e:
        plan.problems.append(f"{base} can't be read: {e}")
        return
    if entry is None:
        try:
            index = int(copy.SourceObject)
        except ValueError:
            index = -1
        if len(entries) != copy.SourceEntries:
            plan.problems.append(
                f"{base} now has {len(entries)} studio entries (it had {copy.SourceEntries}). "
                "Entries have no identity, so Refresh can't tell which one this copy is: "
                "Locate... it")
            return
    else:
        index = entry
    if not 0 <= index < len(entries):
        plan.problems.append(f"{base} has no studio entry {index + 1}")
        return
    plan.object, plan.entries = str(index), len(entries)
    source = entries[index]
    plan.stamp = stamp(source)
    skip = set(copy.Skipped) | c.skip
    variables = tuple(v for v in source.variables if v.name not in skip)
    defined = {v.name for v in variables}
    _names_for(plan, [v.name for v in variables], c)
    refs, all_refs = set(), set()
    for v in source.variables:
        try:
            found = set(onshape.references(onshape.parse(v.expression)))
        except onshape.Refused:
            continue
        all_refs |= found
        if v.name not in skip:
            refs |= found
    values = {}
    for name in sorted(refs - defined - skip):
        _resolve_json_name(plan, name, c, values)
    units = _inferred_default_units(copy)
    units.update(c.default_units)
    if values:
        _plan_inputs(doc, plan, values, units, c.name_map)
        plan.recorded |= set(plan.inputs)
    translation = onshape.translate_export(
        [onshape.StudioEntry(source.reference, variables)], containers=[copy.Name],
        name_map=plan.name_map, bindings=plan.bindings, default_units=units)
    for name, users in translation.unresolved.items():
        if name not in skip and name not in plan.ambiguous:
            plan.unresolved[name] = users
    for name in plan.gone:  # used only through a variable that isn't translated
        plan.unresolved.setdefault(name, [])
    for result in translation.variables:
        if result.translation is None:
            if result.needs and set(result.needs) <= skip:
                needs = ", ".join(f"#{n}" for n in result.needs)
                plan.skipped.append((result.name, f"it needs {needs}, skipped"))
            elif result.refusal:
                plan.refused.append((result.name, result.refusal))
            continue
        try:
            external = bool(set(onshape.references(onshape.parse(result.variable.expression)))
                            - defined)
        except onshape.Refused:
            external = False
        plan.targets.append(Target(
            result.name, result.freecad_name, result.translation.property_type,
            result.translation.text, result.translation.value, result.variable.description,
            result.variable.expression, translation=result.translation, external=external))
    for v in source.variables:
        if v.name in skip:
            plan.skipped.append((v.name, "skipped"))
    plan.skipped_names = sorted(skip & (all_refs | {v.name for v in source.variables}))
    plan.binding_texts = {name: plan.bindings[name].text for name in sorted(plan.recorded)
                          if name in plan.bindings and name in refs}


def _resolve_json_name(plan: RefreshPlan, name: str, c: _Choices, values: dict):
    """How a name the entry uses but doesn't define resolves on Refresh (section 2.6): a new
    choice, else the copy's binding (kept, and listed if a copy now defines the name), else the
    other copy that defines it (as the import of several files did)."""
    copy, doc = plan.copy, plan.doc
    if name in c.bindings:
        try:
            plan.bindings[name] = Binding(c.bindings[name], _document_value(doc, c.bindings[name]))
            plan.recorded.add(name)
        except Exception as e:  # noqa: BLE001 (any failure to read it is a problem to show)
            plan.problems.append(f"#{name}: {e}")
        return
    if name in c.values:
        values[name] = c.values[name]
        return
    providers = _providers(copy, name)
    old = copy.Bindings.get(name)
    if old is not None and name not in c.switch:
        try:
            plan.bindings[name] = Binding(old, _binding_value(doc, copy, old))
            plan.recorded.add(name)
        except Exception as e:  # noqa: BLE001 (a target gone: the name is unresolved again)
            plan.gone[name] = f"it was bound to {old}, which can't be read now ({e})"
            return
        if providers:
            where = ", ".join(f"{p.Label}.{fc}" for p, fc in providers)
            plan.switchable[name] = (old, where)
            plan.notes.append(f"#{name} is now defined by {where}; it stays bound to {old} "
                              "unless you switch")
        return
    if len(providers) > 1:
        pick = c.providers.get(name)
        if pick is not None:
            chosen = [p for p in providers if p[0].Name == pick]
        else:
            chosen = [p for p in providers if _names_object(copy, p[0])]
        if len(chosen) != 1:
            plan.ambiguous[name] = [p.Name for p, _fc in providers]
            return
        providers = chosen
    if providers:
        other, fc = providers[0]
        try:
            value = to_quantity(getattr(other, fc), f"{other.Label}.{fc}")
        except ValueError as e:
            plan.problems.append(f"#{name}: {e}")
            return
        plan.bindings[name] = Binding(f"{other.Name}.{fc}", value)
        if old is not None:
            plan.notes.append(f"#{name} switches from {old} to {other.Label}.{fc}")
        return
    if name in c.switch:
        plan.problems.append(f"#{name}: no other copy defines it, so there is nothing to "
                             "switch to")


def _providers(copy, name: str) -> List[Tuple[object, str]]:
    """The other attached copies of @a copy's document whose source defines @a name, with the
    variable's FreeCAD name."""
    found = []
    for other in copy.Document.findObjects(COPY_TYPE):
        if other.Name == copy.Name or other.SourceKind == DETACHED:
            continue
        if name in other.SourceExpressions:
            fc = other.NameMap.get(name, name)
            if fc in other.PropertiesList:
                found.append((other, fc))
    return found


def _names_object(copy, other) -> bool:
    """Whether one of @a copy's expressions names @a other (by its internal name)."""
    return any(p.obj == other.Name and p.document is None and not p.by_label
               for _path, text in _expressions_of(copy) for p in fc_paths(text))


def _binding_value(doc, copy, text: str) -> Quantity:
    """The value of a binding's text: a document variable's path, or any expression text (a
    literal), evaluated with the copy as owner."""
    if re.fullmatch(r"[^\W\d]\w*\.[^\W\d]\w*", text):
        return _document_value(doc, text)
    return to_quantity(copy.evalExpression(text), text)


def _names_for(plan: RefreshPlan, names: Sequence[str], c: _Choices):
    """The FreeCAD names of the source's variables: the copy's own (NameMap) for those it has,
    a choice, or a proposal for a name FreeCAD can't use or that another property of the copy
    has."""
    copy = plan.copy
    old = dict(copy.NameMap) if copy is not None else {}
    copied = set(copy.SourceExpressions) if copy is not None else set()
    existing = set(copy.PropertiesList) if copy is not None else set()
    owned = ({old.get(n, n) for n in copied} | set(copy.Orphans)) if copy is not None else set()
    taken = set()
    for name in names:
        if name in c.name_map:
            fc = c.name_map[name]
            reason = check_name(fc)
            if reason:
                plan.problems.append(f"{name} can't become {fc}: {reason}")
                fc = name
        elif name in old:
            fc = old[name]
        elif name in copied:
            fc = name
        elif check_name(name) or (name in existing and name not in owned):
            fc = propose_name(name, taken | existing | set(names))
            plan.renames[name] = fc
        else:
            fc = name
        if fc in taken:
            plan.problems.append(f"Two of the source's variables would both be {fc}")
        taken.add(fc)
        if fc != name:
            plan.name_map[name] = fc


def _inferred_default_units(copy) -> Dict[str, str]:
    """The Onshape document's default units the import was given, read back from the copy (it
    doesn't record them): a variable whose source text has no unit and no reference took one,
    which the import wrote as `... * 1 in`. A type whose variables disagree gets none."""
    kinds = {"App::PropertyDistance": "LENGTH", "App::PropertyAngle": "ANGLE"}
    found: Dict[str, set] = {}
    props = set(copy.PropertiesList)
    for name, text in copy.SourceExpressions.items():
        try:
            tree = onshape.parse(text)
            if onshape.references(tree) or onshape._has_units(tree, _no_reference):
                continue
        except onshape.Refused:
            continue
        fc = copy.NameMap.get(name, name)
        if fc not in props:
            continue
        kind = kinds.get(copy.getTypeIdOfProperty(fc))
        match = re.search(r"\*\s*1\s*([A-Za-z]+)\s*$", _expression_text(copy, fc) or "")
        if kind and match and match.group(1) in _DEFAULT_UNITS[kind]:
            found.setdefault(kind, set()).add(match.group(1))
    return {kind: next(iter(units)) for kind, units in found.items() if len(units) == 1}


# --- A FreeCAD source (section 3.3) --------------------------------------------------------------

def _classify(path: FcPath, source: FcObject, siblings: set, f: FcFile) -> str:
    """"sibling", "unit", "external" (a name the source uses but doesn't define), or the reason
    the path can't be copied."""
    if path.document is not None:
        return f"the reference {path.text}[...] has an index" if path.indexed else "external"
    if path.obj is None:
        name = path.props[0]
        if name in siblings:
            if len(path.props) == 1 and not path.indexed:
                return "sibling"
            return f"the sub-path {path.text} of a variable isn't copied"
        if not path.local and len(path.props) == 1 and _is_unit_or_constant(name):
            return "unit"
        return f"{path.text} is a property of {source.label} that isn't a variable"
    if path.obj == (source.label if path.by_label else source.name):
        if len(path.props) == 1 and path.props[0] in siblings and not path.indexed:
            return "sibling"
        return f"{path.text} isn't one of {source.label}'s variables"
    if not path.by_label and path.obj in siblings and f.find(path.obj) is None:
        return f"the sub-path {path.text} of a variable isn't copied"
    if path.indexed:
        return f"the reference {path.text}[...] has an index"
    return "external"


def _freeze_text(f: FcFile, path: FcPath) -> str:
    """The value @a path has in the file, as a literal (`12.5 mm`): what "freeze the value"
    binds it to. Raises onshape.Refused."""
    if path.document is not None:
        raise onshape.Refused("it is in another document")
    obj = f.find(path.obj, path.by_label)
    if obj is None:
        raise onshape.Refused(f"{path.obj} isn't in the file")
    if len(path.props) != 1:
        raise onshape.Refused("only a property's own value can be frozen")
    prop = obj.properties.get(path.props[0])
    if prop is None:
        raise onshape.Refused(f"{obj.label} has no {path.props[0]} in the file")
    if obj.touched or obj.invalid:
        raise onshape.Refused(f"{obj.label} was saved before its recompute or with an error: "
                              "its value may be stale")
    if prop.type == "App::PropertyInteger" and prop.element is not None:
        try:
            return str(int(prop.element.get("value")))
        except (TypeError, ValueError):
            raise onshape.Refused("its saved value can't be read") from None
    if prop.type in ("App::PropertyBool", "App::PropertyString"):
        raise onshape.Refused("only a length, an angle or a number can be frozen")
    value, unit = fc_value(prop)
    return f"{value!r} {unit}".strip()


def _plan_fcstd(plan: RefreshPlan, varset: str, c: _Choices):
    copy, doc = plan.copy, plan.doc
    base = os.path.basename(plan.path)
    try:
        f = read_fcstd(plan.path)
    except (OSError, SourceError) as e:
        plan.problems.append(f"{base} can't be read: {e}")
        return
    source = f.objects.get(varset)
    if source is None or source.type not in VARSET_TYPES:
        plan.problems.append(f"{base} has no VarSet {varset}")
        return
    plan.object = varset
    if not plan.label:
        plan.label = source.label
    if (copy is not None and doc.FileName and _same_file(doc.FileName, plan.path)
            and varset == copy.Name):
        plan.problems.append("A copy can't be its own source")
        return
    if source.touched or source.invalid:
        how = "with an error" if source.invalid else "before its recompute"
        plan.problems.append(
            f"{source.label} in {base} was saved {how}: its saved values may be stale, so they "
            f"can't be copied or checked. Recompute and save {base}, then try again")
        return
    if source.type == COPY_TYPE:
        plan.notes.append(f"The source is a copy of "
                          f"{os.path.basename(source.string('SourcePath'))}, refreshed on "
                          f"{source.string('SourceRefreshed') or 'no date'}")
    plan.stamp = stamp_fcstd(source)
    skip = (set(copy.Skipped) if copy is not None else set()) | c.skip
    every = source.variables()
    siblings = {p.name for p in every}
    variables = [p for p in every if p.name not in skip]
    for p in every:
        if p.name in skip:
            plan.skipped.append((p.name, "skipped"))
    _names_for(plan, [p.name for p in variables], c)

    # each variable's value and the paths of its expression
    info = {}  # name -> (prop, (value, unit), text, pieces)
    deps: Dict[str, set] = {}
    needs: Dict[str, set] = {}
    externals: Dict[str, List[str]] = {}
    external_paths: Dict[str, FcPath] = {}
    for p in variables:
        try:
            saved = fc_value(p)
        except onshape.Refused as e:
            plan.refused.append((p.name, str(e)))
            continue
        text = source.expression(p.name)
        pieces, dep, need, bad = [], set(), set(), None
        for path in fc_paths(text) if text else []:
            kind = _classify(path, source, siblings, f)
            if kind == "unit":
                continue
            if kind == "sibling":
                dep.add(path.props[0])
                pieces.append((path, kind, path.props[0]))
            elif kind == "external":
                need.add(path.text)
                if p.name not in externals.setdefault(path.text, []):
                    externals[path.text].append(p.name)
                external_paths[path.text] = path
                pieces.append((path, kind, path.text))
            else:
                bad = kind
                break
        if bad:
            plan.refused.append((p.name, f"{text!r}: {bad}"))
            continue
        info[p.name] = (p, saved, text, pieces)
        deps[p.name], needs[p.name] = dep, need

    # the names it uses but doesn't define (section 2.6, and 3.3's "freeze the value")
    values = {}
    frozen = set()
    for key in sorted(externals):
        if key in skip:
            continue
        try:
            freeze_text, why_not = _freeze_text(f, external_paths[key]), ""
        except onshape.Refused as e:
            freeze_text, why_not = None, str(e)
        if key in c.freeze:
            if freeze_text is None:
                plan.problems.append(f"{key} can't be frozen: {why_not}")
            else:
                plan.binding_texts[key] = freeze_text
                frozen.add(key)
            continue
        if key in c.bindings:
            try:
                _document_value(doc, c.bindings[key])
                plan.binding_texts[key] = c.bindings[key]
            except Exception as e:  # noqa: BLE001 (any failure to read it is a problem to show)
                plan.problems.append(f"{key}: {e}")
            continue
        if key in c.values:
            values[key] = c.values[key]
            continue
        old = copy.Bindings.get(key) if copy is not None else None
        if old is not None:
            if _FROZEN.match(old):
                if freeze_text is not None:
                    plan.binding_texts[key] = freeze_text
                    frozen.add(key)
                    if freeze_text != old:
                        plan.notes.append(f"{key} is frozen again from the file: {old} becomes "
                                          f"{freeze_text}")
                    continue
                plan.gone[key] = f"it was frozen, and can't be now: {why_not}"
            else:
                try:
                    _binding_value(doc, copy, old)
                    plan.binding_texts[key] = old
                    continue
                except Exception as e:  # noqa: BLE001 (a target gone: unresolved again)
                    plan.gone[key] = f"it was bound to {old}, which can't be read now ({e})"
        plan.unresolved[key] = list(externals[key])
        if freeze_text is not None:
            plan.freezable[key] = freeze_text
    if values:
        _plan_inputs(doc, plan, values, None, c.name_map)
        for key in plan.inputs:
            plan.binding_texts[key] = plan.bindings[key].text

    # what each variable needs, through its siblings
    state: Dict[str, Tuple[str, str]] = {}

    def solve(name, chain):
        if name in state:
            return state[name]
        if name in chain:
            return ("refused", "it refers to itself through " + " -> ".join(chain + [name]))
        if name not in info:
            if name in skip:
                return ("skipped", f"it needs {name}, skipped")
            return ("refused", f"it needs {name}, which isn't copied")
        for key in sorted(needs[name]):
            if key in skip:
                state[name] = ("skipped", f"it needs {key}, skipped")
                return state[name]
            if key not in plan.binding_texts:
                state[name] = ("waiting", "")
                return state[name]
        result = ("ok", "")
        for dep in sorted(deps[name]):
            got = solve(dep, chain + [name])
            if got[0] != "ok":
                result = got
                break
        state[name] = result
        return result

    def checked(name, seen=()):
        """Whether @a name's value must equal the file's: it depends on no value chosen here (a
        document variable, an entered value), only on frozen ones."""
        if name in seen:
            return True
        if any(key not in frozen for key in needs.get(name, ())):
            return False
        return all(checked(dep, seen + (name,)) for dep in deps.get(name, ()))

    for p in variables:
        if p.name not in info:
            continue
        status, why = solve(p.name, [])
        if status == "skipped":
            plan.skipped.append((p.name, why))
            continue
        if status == "refused":
            plan.refused.append((p.name, why))
            continue
        if status == "waiting":
            continue
        prop, saved, text, pieces = info[p.name]
        plan.targets.append(Target(
            p.name, plan.name_map.get(p.name, p.name), prop.type,
            _rewrite(text, pieces, plan) if text else None, saved, prop.description, text or "",
            check=checked(p.name), external=bool(needs[p.name])))
    plan.skipped_names = sorted(skip & (siblings | set(externals)))
    plan.binding_texts = {key: text for key, text in plan.binding_texts.items()
                          if any(key in needs[t.name] for t in plan.targets)}


def _rewrite(text: str, pieces, plan: RefreshPlan) -> str:
    """The source's expression @a text for the copy: a sibling by its name in the copy (bare), a
    name the source doesn't define by its binding's text, in parentheses."""
    out, last = [], 0
    for path, kind, key in sorted(pieces, key=lambda piece: piece[0].start):
        out.append(text[last:path.start])
        if kind == "sibling":
            out.append(plan.name_map.get(key, key))
        else:
            out.append("(" + plan.binding_texts[key] + ")")
        last = path.end
    out.append(text[last:])
    return "".join(out)


# --- Refresh: the preview and its application ----------------------------------------------------

def _values_agree(a, b) -> bool:
    """Two values of a copy's variable: quantities and numbers within the tolerance (in their
    internal units), others equal."""
    if isinstance(a, App.Units.Quantity):
        a = a.Value
    if isinstance(b, App.Units.Quantity):
        b = b.Value
    if isinstance(a, (bool, str)) or isinstance(b, (bool, str)):
        return a == b
    try:
        return onshape.values_agree(float(a), float(b))
    except (TypeError, ValueError):
        return a == b


def _same_now(copy, target: Target) -> bool:
    """Whether the copied variable has what the source gives it now, as far as can be told before
    the Refresh: the same expression (or the same value for a plain value)."""
    fc = target.fc_name
    current = _expression_text(copy, fc)
    if target.text is None:
        value, _unit = target.expected
        return current is None and _values_agree(getattr(copy, fc), value)
    if current is None:
        return False
    if re.sub(r"[\s()]", "", current) == re.sub(r"[\s()]", "", target.text):
        return True
    try:  # FreeCAD writes its own form of the text: the same value is the same expression
        return _values_agree(copy.evalExpression(current), copy.evalExpression(target.text))
    except Exception:  # noqa: BLE001 (the new text needs what the Refresh adds)
        return False


def _diff(plan: RefreshPlan):
    copy = plan.copy
    if copy is None:
        plan.added = [t.fc_name for t in plan.targets]
        return
    props = set(copy.PropertiesList)
    old = {name: copy.NameMap.get(name, name) for name in copy.SourceExpressions}
    old_orphans = [name for name in copy.Orphans if name in props]
    new = {t.fc_name for t in plan.targets}
    for t in plan.targets:
        fc = t.fc_name
        if old.get(t.name) == fc and fc in props:
            current = copy.getTypeIdOfProperty(fc)
            if current != t.property_type:
                plan.retyped[fc] = (current, t.property_type, uses(copy, fc))
            if copy.SourceExpressions[t.name] != t.source_text:
                plan.changed.append(fc)
            elif not _same_now(copy, t):
                # the same source text: a binding changed, or someone edited the copy
                (plan.changed if t.external or t.text is None else plan.overwritten).append(fc)
            if copy.getDocumentationOfProperty(fc) != t.description:
                plan.described.append(fc)
        elif fc in old_orphans:
            plan.restored.append(fc)
        else:
            plan.added.append(fc)
    kept = []
    for fc in old.values():
        if fc in new or fc not in props:
            continue
        users = uses(copy, fc)
        if users:
            plan.orphaned[fc] = users
        else:
            plan.removed.append(fc)
    for fc in old_orphans:
        if fc in new or fc in plan.orphaned:
            continue
        if uses(copy, fc):
            kept.append(fc)
        else:
            plan.removed.append(fc)
    plan.orphans = sorted(set(kept) | set(plan.orphaned))


def _list_problems(plan: RefreshPlan):
    source = "the source" if plan.kind == FCSTD_KIND else "the file"
    for name, users in sorted(plan.unresolved.items()):
        shown = name if plan.kind == FCSTD_KIND else f"#{name}"
        line = f"{shown} is used by {', '.join(users) or 'a variable'} but not defined in {source}"
        if name in plan.gone:
            line += f": {plan.gone[name]}"
        line += ". Choose how to resolve it: a document variable, a value"
        if name in plan.freezable:
            line += f", its saved value ({plan.freezable[name]})"
        plan.problems.append(line + ", or skip what uses it")
    for name, copies in sorted(plan.ambiguous.items()):
        plan.problems.append(f"#{name} is defined by several copies ({', '.join(copies)}): "
                             "choose which provides it")
    for name, reason in plan.refused:
        plan.problems.append(f"{name}: {reason}")


def _file_value(target: Target):
    value, unit = target.expected
    if unit == "mm":
        return App.Units.Quantity(value, App.Units.Length)
    if unit == "deg":
        return App.Units.Quantity(value, App.Units.Angle)
    return value


def _apply(plan: RefreshPlan, copy):
    """Makes @a copy what @a plan says, recomputes the document and checks the values; inside the
    caller's transaction."""
    doc = plan.doc
    _make_inputs(doc, plan, [], [])
    frozen = {fc: getattr(copy, fc) for fc in plan.orphaned}
    for fc in plan.orphaned:
        copy.setExpression(fc, None)  # frozen to its value and unit (D2)
    for fc in plan.retyped:
        copy.removeProperty(fc)  # replaced in place: its users bind again (section 3.4)
    for t in plan.targets:
        if t.fc_name not in copy.PropertiesList:
            copy.addProperty(t.property_type, t.fc_name, GROUP, t.description)
        elif copy.getDocumentationOfProperty(t.fc_name) != t.description:
            copy.setDocumentationOfProperty(t.fc_name, t.description)
    # the expressions once every variable exists: a sibling binds only if it does
    for t in plan.targets:
        if t.text is None:
            if _expression_text(copy, t.fc_name) is not None:
                copy.setExpression(t.fc_name, None)
            setattr(copy, t.fc_name, _file_value(t))
        else:
            copy.setExpression(t.fc_name, t.text)
    for fc in plan.removed:
        copy.removeProperty(fc)
    for fc in [t.fc_name for t in plan.targets] + plan.orphans:
        copy.setPropertyStatus(fc, "ReadOnly")
    names = {t.name for t in plan.targets}
    copy.SourcePath = plan.path
    copy.SourceRelativePath = _relative(doc, plan.path)
    copy.SourceObject = plan.object
    copy.SourceEntries = plan.entries
    copy.SourceStamp = plan.stamp
    copy.SourceRefreshed = _now()
    copy.SourceExpressions = {t.name: t.source_text for t in plan.targets}
    copy.NameMap = {name: fc for name, fc in plan.name_map.items() if name in names}
    # the choices of what `#name` means (decision 317): kept for the names the copy still has,
    # and the new ones, on the other copies of the name too
    kept = {t.fc_name for t in plan.targets} | set(plan.orphans)
    records = {key: path for key, path in dict(copy.Bindings).items()
               if key.startswith("#") and key[1:] in kept}
    records.update({choice_key(fc): path for fc, path in plan.chosen.items()})
    copy.Bindings = {**plan.binding_texts, **records}
    for fc, path in plan.chosen.items():
        _record(copies_defining(doc, fc, exclude={copy.Name}), fc, path)
    copy.Skipped = list(plan.skipped_names)
    copy.Orphans = list(plan.orphans)
    doc.recompute()
    _check_refresh(plan, copy, frozen)


def _check_refresh(plan: RefreshPlan, copy, frozen):
    """Sections 2.5 and 3.3: each copied variable's value is the translator's (JSON: FreeCAD's
    value of the text, evaluated with the copy as owner, has its unit and value) or the one saved
    in the file (FreeCAD, unless it depends on a value chosen here); an orphan keeps its value."""
    if "Invalid" in copy.State:
        raise RefreshCheckFailed(f"{copy.Label} doesn't recompute: {copy.State}")
    base = os.path.basename(plan.path)
    for t in plan.targets:
        where = f"{copy.Label}.{t.fc_name}"
        if t.translation is not None:
            expected = t.expected
            if _check_hook is not None:
                expected = _check_hook(t, expected)
            try:
                got = to_quantity(copy.evalExpression(t.text), where)
                stored = to_quantity(getattr(copy, t.fc_name), where)
            except Exception as e:  # noqa: BLE001 (any failure is the check's)
                raise RefreshCheckFailed(f"{where}: FreeCAD can't evaluate {t.text!r} "
                                         f"(from {t.source_text!r}): {e}") from None
            if got.dims != expected.dims or not onshape.values_agree(got.value, expected.value):
                raise RefreshCheckFailed(
                    f"{where}: FreeCAD computes {_show(got)} for {t.text!r}, the translator "
                    f"{_show(expected)} for {t.source_text!r}")
            if stored.dims != got.dims or not onshape.values_agree(stored.value, got.value):
                raise RefreshCheckFailed(f"{where}: the variable holds {_show(stored)}, its "
                                         f"expression {t.text!r} computes {_show(got)}")
        elif t.check:
            expected = t.expected
            if _check_hook is not None:
                expected = _check_hook(t, expected)
            value, unit = expected
            stored = getattr(copy, t.fc_name)
            if not _values_agree(stored, value):
                shown = stored.UserString if isinstance(stored, App.Units.Quantity) else stored
                raise RefreshCheckFailed(
                    f"{where}: the copy computes {shown} from {t.text!r}, {base} saved "
                    f"{value!r} {unit}".rstrip())
    for fc, value in frozen.items():
        if not _values_agree(getattr(copy, fc), value):
            raise RefreshCheckFailed(f"{copy.Label}.{fc}: the orphan doesn't keep its value")


# --- Saving: the relative path (section 3.1) ------------------------------------------------------

def before_save(doc, filename: Optional[str] = None):
    """Rewrites each attached copy's SourceRelativePath for the file @a doc is being saved to
    (Save As included), before it is written, when the copy finds its source. The source
    properties are output properties: this doesn't touch the copies."""
    target = filename or doc.FileName
    if not target:
        return
    folder = os.path.dirname(os.path.abspath(target))
    for copy in doc.findObjects(COPY_TYPE):
        if copy.SourceKind == DETACHED or not copy.SourcePath:
            continue
        # the file the copy finds now (relative first: a folder moved with its sources); none
        # found, the paths stay as they are
        found = source_candidates(copy)
        if not found:
            continue
        try:
            relative = _portable(os.path.relpath(found[0], folder))
        except ValueError:  # another drive
            relative = ""
        if copy.SourceRelativePath != relative:
            copy.SourceRelativePath = relative


class _SaveObserver:
    def slotStartSaveDocument(self, doc, filename):  # noqa: N802 (FreeCAD's name)
        try:
            before_save(doc, filename)
        except Exception as e:  # noqa: BLE001 (a save must not fail for it)
            App.Console.PrintWarning(f"Variables: the copies' relative paths: {e}\n")


_save_observer = _SaveObserver()
App.addDocumentObserver(_save_observer)
