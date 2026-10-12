# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fail on C/C++ identifiers that <windows.h> defines as macros.

<windows.h> (minwindef.h) defines `near` and `far` as empty macros, so `const double near = 1;`
becomes `const double = 1;` in any translation unit that includes it. PR CI passed two such
names while the conda release build failed on them (fork-0.6.0, ops#294; earlier ops#83), so this
check runs before the build in PR CI.

The other words below are <windows.h> macros too, and none is used as code in src/ (checked
2026-10-12): a new enum value `DIFFERENCE` or `ERROR` would break the same way. Not checked:
`min` and `max` (the build defines NOMINMAX), `small` (rpcndr.h; TechDraw's EdgeWidth::small
compiles), and `IN`, `OUT`, `TRUE`, `FALSE`, `DELETE`, `VOID`, which src/ uses as intended.

Comments, string and character literals (raw strings included) and preprocessor lines are
skipped, so the words may appear there. A line that must use one of them as the Win32 macro
(e.g. `WaitForSingleObject(h, INFINITE)`) carries the comment `// windows-macro-ok`.

Usage: check_windows_macros.py [PATH ...]   (default: src; 3rdParty directories are skipped)
Exit status: 0 when clean, 1 on any hit.
"""

import os
import re
import sys

MACRO_WORDS = (
    "near far NEAR FAR pascal OPTIONAL".split()  # minwindef.h
    + "interface hyper".split()  # objbase.h, rpcndr.h
    # wingdi.h, winbase.h
    + "ERROR TRANSPARENT OPAQUE ABSOLUTE RELATIVE DIFFERENCE INFINITE IGNORE".split()
)
ALLOW_MARKER = "windows-macro-ok"
EXTENSIONS = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp", ".mm")
SKIP_DIRS = {"3rdParty", ".git"}

WORD_RE = re.compile(r"\b(" + "|".join(MACRO_WORDS) + r")\b")
IDENT_RE = re.compile(r"[A-Za-z_]\w*")
NUMBER_RE = re.compile(r"\.?\d(?:[eEpP][+-]|'?[\w.])*")  # pp-number, with 1'000 separators
RAW_PREFIXES = {"R", "u8R", "uR", "UR", "LR"}
RAW_DELIM_RE = re.compile(r'"([^()\\\s]{0,16})\(')


def strip_code(text):
    """Return text with comments, literals and preprocessor lines blanked, newlines kept."""
    out = []
    i, n = 0, len(text)
    line_start = True  # only whitespace so far on this line
    in_directive = False

    def skip_to(j):
        out.append("\n" * text.count("\n", i, j))
        return j

    while i < n:
        c = text[i]
        if c == "\n":
            # A directive continues onto the next line after a backslash.
            if not (in_directive and text[i - 1] == "\\"):
                in_directive = False
            out.append("\n")
            line_start = True
            i += 1
            continue
        if c.isspace():
            out.append(c)
            i += 1
            continue
        if line_start and c == "#":
            in_directive = True
        line_start = False
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = skip_to(n if j < 0 else j + 2)
            continue
        m = IDENT_RE.match(text, i) or NUMBER_RE.match(text, i)
        if m:
            word = m.group()
            d = RAW_DELIM_RE.match(text, m.end()) if word in RAW_PREFIXES else None
            if d:
                j = text.find(")" + d.group(1) + '"', d.end())
                i = skip_to(n if j < 0 else j + len(d.group(1)) + 2)
                continue
            out.append(" " * len(word) if in_directive else word)
            i = m.end()
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            i = skip_to(min(j + 1, n))
            continue
        out.append(" " if in_directive else c)
        i += 1
    return "".join(out)


def check_file(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if not WORD_RE.search(text):
        return []
    raw_lines = text.split("\n")
    return [
        (path, number, m.group(1))
        for number, line in enumerate(strip_code(text).split("\n"), 1)
        if ALLOW_MARKER not in raw_lines[number - 1]
        for m in WORD_RE.finditer(line)
    ]


def main(paths):
    hits = []
    for root in paths or ["src"]:
        if os.path.isfile(root):
            hits += check_file(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                if name.endswith(EXTENSIONS):
                    hits += check_file(os.path.join(dirpath, name))
    for path, number, word in hits:
        path = path.replace(os.sep, "/")
        print(f"{path}:{number}: '{word}' is a macro in <windows.h>; rename the identifier")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error file={path},line={number}::'{word}' is a macro in <windows.h>")
    if hits:
        print(f"{len(hits)} identifier(s) named after <windows.h> macros (ops#294).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
