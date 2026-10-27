# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""The naming audit (ops#502; class C's invariants I-C1 and I-C2): over the models of the
scenarios and of the corpus's cases, as their build leaves them, two lists:

- **unnamed**: every element (vertex, edge, face) of a document object's own result that has no
  name in its element map;
- **IDX**: every name of a document object's own result with an index section (`IDX`), a name
  that borrows a map-less input's index.

Both are empty once every result without history is named by a verified match (MLN). Run:
`FreeCADCmd <this file>` with FREECAD_AUDIT_OUT naming the output file (default: stdout);
FREECAD_AUDIT_ONLY=<name>,... keeps the scenarios whose class name holds one of them. Lines:
`AUDIT unnamed|IDX <scenario> <object> <count> <first names>`, then `AUDIT total ...`."""

import os
import re
import traceback

import FreeCAD as App

from PartDesignTests.Scenarios import corpus, harness

INDEX_SECTION = re.compile(r"(^|[;,:])IDX([;,:]|$)")
TYPES = (("Vertex", "Vertexes"), ("Edge", "Edges"), ("Face", "Faces"))


def ownResults(doc):
    """The document's objects with a shape of their own (Part features, sketches included)."""
    for obj in doc.Objects:
        if not obj.isDerivedFrom("Part::Feature"):
            continue
        shape = obj.Shape
        if shape.isNull():
            continue
        yield obj, shape


def unnamed(shape):
    """The indexed names of the shape's elements without a mapped name."""
    named = shape.ElementReverseMap
    return [
        "%s%d" % (kind, i)
        for kind, attribute in TYPES
        for i in range(1, len(getattr(shape, attribute)) + 1)
        if "%s%d" % (kind, i) not in named
    ]


def indexNamed(shape):
    """The shape's mapped names with an index section, expanded."""
    found = []
    for mapped in shape.ElementMap:
        if mapped.startswith("#") and hasattr(App, "expandMappedName"):
            mapped = App.expandMappedName(mapped)
        if INDEX_SECTION.search(mapped):
            found.append(mapped)
    return found


def audit(doc):
    """[(list, object name, names)] for the document's own results."""
    rows = []
    for obj, shape in ownResults(doc):
        missing = unnamed(shape)
        if missing:
            rows.append(("unnamed", obj.Name, missing))
        borrowed = indexNamed(shape)
        if borrowed:
            rows.append(("IDX", obj.Name, borrowed))
    return rows


def scenarioClasses():
    """Every scenario of the suite's areas and every case of the corpus."""
    from PartDesignTests import TestNamingScenarios

    found = harness.scenarioClasses(TestNamingScenarios.AREAS)
    modules, _ = corpus.loadModules()
    for module in modules:
        found += module.cases
    return found


def main():
    out = os.environ.get("FREECAD_AUDIT_OUT")
    stream = open(out, "w", encoding="utf-8") if out else None
    only = [x for x in os.environ.get("FREECAD_AUDIT_ONLY", "").split(",") if x]

    def say(line):
        if stream:
            stream.write(line + "\n")
            stream.flush()
        else:
            print(line)

    totals = {"unnamed": 0, "IDX": 0, "scenarios": 0, "errors": 0}
    for cls in scenarioClasses():
        if only and not any(o in cls.__name__ for o in only):
            continue
        scenario = cls("V2s")
        try:
            scenario.doc = scenario.newDocument()
            scenario.build(scenario.doc)
            scenario.doc.recompute()
            for kind, name, names in audit(scenario.doc):
                totals[kind] += len(names)
                say("AUDIT %s %s %s %d %s" % (kind, cls.__name__, name, len(names), " ".join(names[:4])))
            totals["scenarios"] += 1
        except Exception:
            totals["errors"] += 1
            say("AUDIT error %s %s" % (cls.__name__, traceback.format_exc().splitlines()[-1]))
        finally:
            scenario.cleanup()
    say("AUDIT total unnamed %(unnamed)d IDX %(IDX)d scenarios %(scenarios)d errors %(errors)d" % totals)
    if stream:
        stream.close()


if __name__ == "__main__":
    main()
