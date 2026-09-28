# Known test failures (FreeCAD-CH)

CI tolerates the test failures listed here and fails on any other. The C++ tests and the
Python CLI tests are checked (`.github/scripts/known_failures.py`, called from
`.github/workflows/actions/runCPPTests/runAllTests` and `runPythonTests`). A step fails when:
- a test fails that isn't listed for this platform;
- a test executable crashes, times out, or fails without reporting a failing case;
- the Python run doesn't reach its summary (crash or hang), or exits with a code other than 0 or 1.

Listed tests that don't fail are reported as warnings: remove their entries.

## Format

One file per issue that removes its entries: `ops<N>-<slug>.txt`.

```
issue: ops#23
reason: the test expects V1 element names; the base produces V2 names
gtest  App_tests_run/ElementMapTest.mimicSimpleUnion
exe    Gui_tests_run                                  macos
cli    parttests.TopoShapeTest.TopoShapeTest.testTopoShapeCopy   # a comment
```

- `issue:` once per file. `reason:` applies to the entries below it, up to the next `reason:`.
- Entries, one per line: kind, test ID, then optional platforms (`windows`, `macos`, `linux`;
  none means every platform).
  - `gtest <executable>/<Suite.Case>`: one gtest case, named as in gtest's output.
  - `exe <executable>`: the executable as a whole fails without a failing case of its own: a
    crash, a timeout, or a failing QtTest executable (`*_Tests_run`).
  - `cli <id>`: a Python test, the ID in parentheses after `FAIL:` or `ERROR:` in the output of
    `FreeCADCmd -t 0`. Subtests count as their test.
- `#` at the start of a line or after a space starts a comment.
- An ID can be listed twice only for different platforms. The checker rejects the list when an
  entry has no issue or reason, or when a line doesn't parse.

## Updating it

- A PR that makes a listed test pass removes its entry in the same PR.
- A PR that brings a known failure (e.g. a documented gap) adds a file for the issue that tracks
  it. A failure seen only in CI, or only on one platform, gets its own issue first.
- Check locally before pushing (from the checkout root):

  ```
  pixi run python .github/scripts/known_failures.py list
  pixi run python .github/scripts/known_failures.py gtest --build-dir build/relWithDebInfo --out-dir <dir>
  pixi run python .github/scripts/known_failures.py cli --log <FreeCADCmd -t 0 log>
  ```
