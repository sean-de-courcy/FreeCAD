# The naming corpus (FreeCAD-CH)

The corpus is the scenario suite's set of **cases**: designed models whose references are judged
geometrically after an edit, each with a verdict expected in a **ledger**. CI's step "Naming corpus
gate" runs the quick set (tier G) on every PR; the full set (tier F) runs locally before every push.
A PR may not move any case into the wrong set (ops#506; the design: the ops repo's
`notes/naming-system.md` sections 2 and 3).

## Files

| Path | What |
|---|---|
| `harness.py` | The framework: predicates, expectations, outcome checks, verdicts, the case tags |
| `models.py` | Model helpers (bodies, sketches, pads, pockets, line edits) |
| `corpus.py` | Case folders, ledgers, tiers, the comparison with the ledger |
| `cases/<module>.py` | The fork's case modules |
| `cases/ledger/<module>.json` | Their ledgers, written by runs only |
| `scorecard.py` | Tables from SCORE lines or from ledgers (plain Python) |
| `../TestCorpusGate.py` | The test module the runs go through |

## A case

A case is a `Scenario` subclass with `CLASSES` set:

```python
from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, X, Z, face
from PartDesignTests.Scenarios import models as m


class TopFaceAfterLonger(Scenario):
    """A 600 x 300 block padded 300 high; a sketch on its top face; the pad gets longer."""

    area = "attachment"
    CLASSES = ("D",)               # the naming classes it belongs to
    AXES = ("M1", "E5", "X4:600")  # the taxonomy's model, edit and scale cells
    ISSUE = "ops#506"              # the class's umbrella issue, or the issue it tracks
    FOUND_BY = "attacker D"        # "port", "attacker <class>", "review pr<n>-r<r>"
    TIER = "F"                     # "G": also in CI's quick set (under 10 s); "F": full set only
    REFS = ("sketch_top",)
    height = 300

    def top(self):
        return face("plane", normal=Z, through=(0, 0, self.height))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 600, 300), body)
        pad = m.pad(body, profile, 300)
        doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "OnTop")
        sketch.AttachmentSupport = [(pad, self.names(pad, self.top())[0])]
        sketch.MapMode = "FlatFace"
        self.ref("sketch_top", sketch, "AttachmentSupport", self.top, Attached())

    def edit(self, doc):
        doc.Pad.Length = 450
        self.height = 450
```

Rules:
- **Designed geometry only**: the smallest model that shows the behaviour, built by the script. Never
  a user's file or anything derived from one.
- **The expectation is geometric** and says what a correct system gives on the **edited** model: a
  predicate (`face`, `edge`, `vertex`, `pieces(...)`) for the element the reference must hold, or
  `BROKEN` where a loud break is the only right answer (the element is gone, or the case is
  ambiguous on purpose). Never a name or an index taken from a run. `harness.py`'s docstrings list
  the predicates, the expectations (`Guessed`, `Settled`, `Warned`, `OwnOrBroken`, `PartialWarned`)
  and the outcome checks (`Attached`, `Filleted`, `Chamfered`, `Drafted`, `Extruded`, ...).
- Expectations are callables evaluated after each step, so they read the case's parameters
  (`self.height` above) as the edit leaves them.
- `edit(doc)`, or several steps (`steps = ("first", "second")`, each a method): the verdict is the
  worst over the steps.
- **Scale**: `SIZE` (the case's largest extent at scale 1) and `SCALE` (the default scale, the user's
  ~600 mm) let tier F run the case at other sizes: the case multiplies its lengths by `self.scale`
  (`self.s(20, 10)` gives them scaled). **Thin**: `THIN = True` and the case builds a thin member
  when `self.thin` is set. `cases/attachment.py` does both.
- `ACCEPTED = {"ref": "decision <n>"}` accepts a wrong-set verdict (only with the user's decision);
  `ALLOWED = {"ref": ["correct", "broken"]}` allows a known flake. Both go into the ledger.
- A case imports the harness absolutely (`from PartDesignTests.Scenarios...`): runs import case
  modules by path. A module's file name is its ledger's name (not `random`).
- A case doesn't run in the general `-t 0` run (`TestNamingScenarios` leaves tagged scenarios out),
  only in `TestCorpusGate`.

## Verdicts and sets

| Set | Verdicts | Meaning |
|---|---|---|
| right | `correct`; `equivalent`, `guessed`, `quiet` | the reference holds the expected element (`equivalent`: another one with the same result; `guessed`: a warned guess of it; `quiet`: only through the `same-place` warning level or a twin trade) |
| loud+ | `broken` | a reported break with the right element among the solver's candidates, or a break that is the right answer |
| loud- | `broken-` | a reported break whose candidates leave the right element out (V2s only) |
| wrong | `wrong`, `guessed-wrong`, `partial`, `partial-warned` | silent or warned but wrong, or only some pieces kept |
| neither | `error` (the case's run failed), `flaky` (a different verdict under another hash seed) | red until explained |

## Running

Every run sets `FREECAD_USER_HOME` to an absolute folder that exists. On Windows run FreeCADCmd from
Python with its output through a pipe (a file as stdout stops `-t` runs early; ops repo
`notes/build.md`, "Tests"):

```bash
export FREECAD_USER_HOME='D:\CustomFreeCAD\work\<you>\home'
export FREECAD_SCENARIO_TIER=F FREECAD_SCENARIO_UPDATE_LEDGER=1
pixi run --manifest-path 'D:\CustomFreeCAD\wt\<checkout>\pixi.toml' python -c "import subprocess; subprocess.run([r'D:\CustomFreeCAD\wt\<checkout>\build\relWithDebInfo\bin\FreeCADCmd.exe', '-t', 'PartDesignTests.TestCorpusGate'])" 2>&1 | cat > corpus.log
```

- **Tier G** (`FREECAD_SCENARIO_TIER=G`, the default): the `TIER = "G"` cases in V2s, one run each.
  CI's gate.
- **Tier F** (`F`): every case in V2s, its thin variant (`V2s:thin`), the V2si oracle (V2si must give
  what V2s gives), random sequences (`Random<seed>`), and the same run in a second process under
  another naming hash seed (a verdict that differs is `flaky`). The implementer runs it before every
  push, with `FREECAD_SCENARIO_UPDATE_LEDGER=1`, and commits the ledgers it writes.
- A run reads the cases and ledgers of the build's source tree (`CMakeCache.txt`), so edits to case
  modules need no rebuild; edits to `harness.py`, `corpus.py` or `TestCorpusGate.py` are copied into
  `build/.../Mod/PartDesign/PartDesignTests/` by a build (or by hand).
- **An attacker's inbox** (no checkout): `FREECAD_SCENARIO_MODULES=D:\CustomFreeCAD\corpus\inbox\<class>`
  (several folders separated by `;`) runs those modules instead, against any build, with their
  ledgers in `<folder>\ledger\` if there are any. Without a ledger every key is printed with its
  verdict and nothing fails but an `error`. For a quick score of an inbox in tier F set
  `FREECAD_SCENARIO_CHILD_SEED=none FREECAD_SCENARIO_ORACLE=0` (random sequences run only for the
  fork's own folder).
- Other settings: `FREECAD_SCENARIO_CONFIGS=V2s,V2` (tier F's configurations: V2 and V1 are report
  columns), `FREECAD_SCENARIO_SCALES=60,4000` (tier F at those sizes, at a class's exit),
  `FREECAD_SCENARIO_SEEDS=1-40` (the default) / `none`, `FREECAD_SCENARIO_STEPS=8`,
  `FREECAD_SCENARIO_LEDGER_OUT=<folder>` (write the would-be ledgers there, CI's artifact),
  `FREECAD_SCENARIO_SHA` (the sha for the run header, where git can't tell).

What a run prints:
- `CORPUS VERDICT <case>|<ref>|<config> <verdict>` for every key, and the harness's `SCORE` JSON lines.
- `CORPUS REGRESSED|IMPROVED|CHANGED|NEW|STALE ...` for every key that differs from its ledger entry.
  REGRESSED (worse), NEW (no entry) and STALE (an entry without its case) fail the run; IMPROVED and
  CHANGED pass with a line (and a CI warning): the merge guard refuses them until the ledger is
  updated by a full run.
- At the end: `CORPUS tier ...` (counts, time), `CORPUS time <case>` for the slowest cases, and in
  tier F the line for the PR description:
  `Tier F: <sha> <platform> <time> <cases> <wrong>/<loud>/<right>`.

## The ledger

`cases/ledger/<module>.json`, one entry per line, sorted:

```json
"AttachLength|datum_top_face|V2s": {"axes": ["M1", "E5", "X4:600"], "classes": ["D"], "expected": "correct", "found_by": "port", "issue": "ops#506", "tier": "G"},
```

- `expected` is the Windows verdict (or an allowed set), `macos` a macOS override; `tier`, `classes`,
  `axes`, `issue`, `found_by`, `accepted` come from the case. The `run` header has the sha (`dirty` when
  the checkout had other uncommitted changes), platform, time, tier and number of cases.
- **Never edited by hand**: a run with `FREECAD_SCENARIO_UPDATE_LEDGER=1` writes it (tier G only its
  own entries, tier F the module). Commit the code first, then run, then commit the ledgers: the
  guard checks that the run's sha is the head commit, or that only ledgers changed since.
- The merge guard (`scripts/corpus_guard.sh` in the ops repo, run by `merge_pr.sh`) refuses an entry
  that moves into the wrong set (unless `accepted`), a new wrong-set entry without `issue` and
  `found_by`, an allowed set or entry in the wrong or neither set, a removed or renamed entry, a change to an existing
  case module without the label `corpus`, a `corpus` PR touching more than `Scenarios/` and `tests/`,
  a PR without the `Tier F:` line for its head, and a Windows gate that reported IMPROVED or CHANGED;
  it flags right -> loud moves (`decision 120 (4)` in the description lets them through).
- `python scorecard.py --ledger cases/ledger [--base <other ledger folder>]` tabulates the ledgers by
  class, axis and set without a run.
