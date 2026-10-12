# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pass test output through unchanged and print the slowest test modules at the end.

Used in a pipe after `FreeCADCmd -t 0` (runPythonTests action, ops#302) so the growth of the
CLI suites shows in every run. A unittest result line, `name (Module.Class.name) ... ok`, ends
a test; the time since the previous result line counts for its top-level module. Output that
reaches the pipe in chunks blurs single tests but not module totals.

The action runs it as `python ... || cat`, so the output still passes if Python fails to
start or stops. The summary goes to stderr (not into the test log the pipe writes) and, on GitHub, into the
step summary.
"""

import os
import re
import sys
import time
from collections import Counter

RESULT_RE = re.compile(rb"\(([A-Za-z_]\w*)[\w.]*\) \.\.\. ")
TOP = 15


def main():
    seconds, counts = Counter(), Counter()
    start = previous = time.monotonic()
    out = sys.stdout.buffer
    for line in sys.stdin.buffer:
        out.write(line)
        out.flush()
        try:  # the timing never costs a line of output
            m = RESULT_RE.search(line)
            if m:
                now = time.monotonic()
                module = m.group(1).decode("ascii", "replace")
                seconds[module] += now - previous
                counts[module] += 1
                previous = now
        except Exception:
            pass
    try:
        total = time.monotonic() - start
        rows = [(module, seconds[module], counts[module]) for module, _ in seconds.most_common(TOP)]
        results = sum(counts.values())
        text = [f"Slowest test modules ({total / 60:.1f} min in all, {results} results):"]
        print(f"test_timings: {sys.executable}", file=sys.stderr)
        text += [f"  {s:7.1f} s  {n:5d} tests  {module}" for module, s, n in rows]
        print("\n".join(text), file=sys.stderr)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary and rows:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"\n{text[0]}\n\n| Module | Seconds | Tests |\n|---|---:|---:|\n")
                f.writelines(f"| {module} | {s:.1f} | {n} |\n" for module, s, n in rows)
    except Exception as e:  # never fail the test step over the summary
        print(f"test_timings: no summary ({e})", file=sys.stderr)


if __name__ == "__main__":
    main()
