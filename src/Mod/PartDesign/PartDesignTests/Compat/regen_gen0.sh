#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Regenerates, or checks, gen0 of the CI reopen corpus with a given build (FreeCAD-CH ops#418;
# notes/beta-compatibility.md 3.9 in the ops repo).
#
#   regen_gen0.sh [options]            generate gen0 into a scratch folder and report how it differs
#                                      from the committed one; writes nothing in the checkout
#   regen_gen0.sh --check              the same, and exit 1 if it differs (no difference: exit 0)
#   regen_gen0.sh --install            generate, then replace the checkout's gen0 with the result
#
# What it does: starts the build's FreeCADCmd (pixi environment on PATH, QT_QPA_PLATFORM=offscreen,
# FREECAD_USER_HOME a new absolute scratch folder, checked again inside FreeCAD) on
# regen_gen0_drive.py, which runs make_generation.main() for gen0's own models, then compares the
# result with the committed gen0 by compare_generations.py: the MANIFEST's fields, every oracle
# value and every file's Document.xml, ignoring what a regeneration always changes (object ids,
# Uids, dates, the build string, file hashes). The model list is read from the committed gen0's
# MANIFEST; a model that isn't in gen0 yet is added with --add.
#
# Options:
#   --checkout DIR       the source checkout whose gen0 is compared or replaced
#                        (default: the checkout this script is in)
#   --build DIR          the build to run (default: <checkout>/build/relWithDebInfo)
#   --env DIR            its pixi environment (default: <checkout>/.pixi/envs/default; if that
#                        doesn't exist, the PATH is used as it is)
#   --out DIR            keep the generation in DIR/gen0 (default: a new temporary folder, removed
#                        at the end unless the check differs or --keep)
#   --against DIR        compare with this gen0 folder instead of the checkout's
#   --against-rev REV    compare with the gen0 committed in git revision REV (extracted with
#                        git archive; with it the model list is that revision's), e.g. the commit
#                        the build was made from
#   --add MODEL          also build MODEL (repeatable), for a model new to gen0
#   --models "A B"       build exactly these models
#   --all                build every model of models.py (including ones meant for gen1)
#   --keep               keep the scratch folder
#   --timeout SEC        stop FreeCADCmd after SEC seconds (default 1200)
#   --strict             a known flake (compare_generations.py) counts as a difference
#   --force-stale        go on although the build is not the checkout's: its Compat files differ, or
#                        (--check, --install) the generation's namingRevision isn't the source's
#                        ForkNamingRevision or its build commit differs in src/ from the checkout
#                        (HEAD, or REV with --against-rev)
#
# Exit status: 0 done (check: no difference), 1 the check found a difference, 2 usage or
# environment error, 3 the generation failed, 4 (--install) CMakeLists.txt doesn't list gen0's
# files, 5 the build is not the checkout's (see --force-stale): build the merged integration first.
#
# A regenerated gen0 is a commit of its own on the PR's branch (beta-compatibility.md 3.9). Run
# `FreeCADCmd -t PartDesignTests.Compat.TestCompatCorpus` against it before pushing.
#
# Works in Git Bash on Windows (the first target) and in bash on macOS and Linux.

set -u

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
checkout=$(cd "$here/../../../../.." && pwd)
build=
envdir=
outdir=
against=
againstRev=
addModels=
onlyModels=
allModels=0
keep=0
timeoutSec=1200
mode=report
strict=
forceStale=0

usage() {
    sed -n '4,/^# Works in/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}
die() {
    echo "regen_gen0: $*" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --checkout) [ $# -ge 2 ] || die "$1 needs a value"; checkout=$(cd "$2" && pwd) || die "no such folder: $2"; shift ;;
        --build) [ $# -ge 2 ] || die "$1 needs a value"; build=$(cd "$2" && pwd) || die "no such folder: $2"; shift ;;
        --env) [ $# -ge 2 ] || die "$1 needs a value"; envdir=$(cd "$2" && pwd) || die "no such folder: $2"; shift ;;
        --out) [ $# -ge 2 ] || die "$1 needs a value"; mkdir -p "$2" && outdir=$(cd "$2" && pwd) || die "can't use $2"; shift ;;
        --against) [ $# -ge 2 ] || die "$1 needs a value"; against=$(cd "$2" && pwd) || die "no such folder: $2"; shift ;;
        --against-rev) [ $# -ge 2 ] || die "$1 needs a value"; againstRev=$2; shift ;;
        --add) [ $# -ge 2 ] || die "$1 needs a value"; addModels="$addModels $2"; shift ;;
        --models) [ $# -ge 2 ] || die "$1 needs a value"; onlyModels=$2; shift ;;
        --all) allModels=1 ;;
        --keep) keep=1 ;;
        --timeout) [ $# -ge 2 ] || die "$1 needs a value"; timeoutSec=$2; shift ;;
        --strict) strict=--strict ;;
        --force-stale) forceStale=1 ;;
        --check) mode=check ;;
        --install) mode=install ;;
        -h | --help) usage; exit 0 ;;
        *) die "unknown option $1 (see --help)" ;;
    esac
    shift
done

compat=src/Mod/PartDesign/PartDesignTests/Compat
gen0src="$checkout/$compat/gen0"
[ -f "$checkout/$compat/make_generation.py" ] || die "$checkout is not a FreeCAD-CH checkout (no $compat/make_generation.py)"
[ -n "$build" ] || build="$checkout/build/relWithDebInfo"
[ -n "$envdir" ] || envdir="$checkout/.pixi/envs/default"
[ -z "$against" ] || [ -z "$againstRev" ] || die "--against and --against-rev exclude each other"
[ "$mode" != install ] || [ -z "$against$againstRev" ] || die "--install replaces the checkout's gen0: no --against"

windows=0
case "$(uname -s)" in MINGW* | MSYS* | CYGWIN*) windows=1 ;; esac
if [ $windows = 1 ]; then
    cmd="$build/bin/FreeCADCmd.exe"
    native() { cygpath -w "$1"; }
else
    cmd="$build/bin/FreeCADCmd"
    native() { printf '%s\n' "$1"; }
fi
[ -x "$cmd" ] || die "no FreeCADCmd at $cmd (--build)"

# The python that reads the MANIFEST and compares: the environment's, else the system's.
py=
for candidate in "$envdir/python.exe" "$envdir/bin/python" python3 python; do
    if command -v "$candidate" > /dev/null 2>&1; then py=$candidate; break; fi
done
[ -n "$py" ] || die "no python found"

# The build must be this checkout's: the models it builds are its own copies of the Compat files.
stale=
for f in make_generation.py models.py models_assembly.py models_part.py models_partdesign.py \
    models_sketcher.py models_studio.py __init__.py; do
    cmp -s "$checkout/$compat/$f" "$build/Mod/PartDesign/PartDesignTests/Compat/$f" || stale="$stale $f"
done
cmp -s "$checkout/src/Mod/Part/CompatRecord.py" "$build/Mod/Part/CompatRecord.py" || stale="$stale CompatRecord.py"
if [ -n "$stale" ]; then
    echo "regen_gen0: the build's copies of$stale differ from the checkout's: the build isn't this checkout's" >&2
    [ $forceStale = 1 ] && echo "regen_gen0: going on (--force-stale)" >&2 || exit 5
fi

scratch=$(mktemp -d "${TMPDIR:-/tmp}/regen_gen0.XXXXXX") || die "can't make a scratch folder"
mkdir -p "$scratch/home"
cleanup() {
    if [ "$keep" = 0 ] && [ -z "$outdir" ] && [ "${failed:-0}" = 0 ]; then rm -rf "$scratch"; fi
}
trap cleanup EXIT
failed=0

# What to compare with.
if [ -n "$againstRev" ]; then
    mkdir -p "$scratch/against"
    git -C "$checkout" archive "$againstRev" "$compat/gen0" | tar -x -C "$scratch/against" ||
        die "can't extract gen0 of $againstRev"
    old="$scratch/against/$compat/gen0"
elif [ -n "$against" ]; then
    old=$against
else
    old=$gen0src
fi

# The models.
if [ -n "$onlyModels" ]; then
    models=$onlyModels
elif [ $allModels = 1 ]; then
    models=
else
    [ -f "$old/MANIFEST" ] || die "no MANIFEST in $old: say which models with --models or --all"
    models=$("$py" -c 'import json, sys; print(" ".join(json.load(open(sys.argv[1]))["models"]))' "$(native "$old/MANIFEST")") ||
        die "can't read $old/MANIFEST"
fi
[ $allModels = 1 ] || models="$models$addModels"

gen="${outdir:-$scratch/out}/gen0"
[ ! -e "$gen/MANIFEST" ] || die "$gen already holds a generation (generations are immutable): another --out, or delete it"
mkdir -p "$gen"
result="$scratch/result.txt"
log="$scratch/FreeCADCmd.log"

if [ -d "$envdir" ]; then
    if [ $windows = 1 ]; then
        export PATH="$envdir/Library/bin:$envdir:$envdir/Scripts:$PATH"
        [ -d "$envdir/Library/lib/qt6/plugins" ] && export QT_PLUGIN_PATH="$(native "$envdir/Library/lib/qt6/plugins")"
    else
        export PATH="$envdir/bin:$PATH"
        [ -d "$envdir/lib/qt6/plugins" ] && export QT_PLUGIN_PATH="$envdir/lib/qt6/plugins"
    fi
    export CONDA_PREFIX
    CONDA_PREFIX=$(native "$envdir")
fi
export QT_QPA_PLATFORM=offscreen
export FREECAD_USER_HOME
FREECAD_USER_HOME=$(native "$scratch/home")
export FREECAD_COMPAT_OUT
FREECAD_COMPAT_OUT=$(native "$gen")
export FREECAD_COMPAT_MODELS="${models# }"
export FREECAD_COMPAT_RESULT
FREECAD_COMPAT_RESULT=$(native "$result")

echo "regen_gen0: build $build"
echo "regen_gen0: models: ${models:-all of models.py}" | cut -c1-300
echo "regen_gen0: scratch $scratch"
withTimeout=
command -v timeout > /dev/null 2>&1 && withTimeout="timeout $timeoutSec"
$withTimeout "$cmd" "$(native "$here/regen_gen0_drive.py")" > "$log" 2>&1
rc=$?
if [ ! -f "$result" ] || [ "$(head -n 1 "$result")" != OK ] || [ ! -f "$gen/MANIFEST" ]; then
    failed=1
    echo "regen_gen0: the generation failed (FreeCADCmd exit $rc); log $log" >&2
    [ -f "$result" ] && cat "$result" >&2
    tail -n 15 "$log" >&2
    exit 3
fi
tail -n 1 "$log"

# The generation must come from the checkout's own source, not only its Compat files: a naming PR
# changes C++ and goldens, and a gen0 saved by a build from before it would carry the old naming
# revision, which the gate then reads as "older" and passes, with the name check off indefinitely.
# --install and --check refuse (the report only warns); the build whose source is compared is the
# checkout's HEAD, or REV with --against-rev REV.
manifestOf() {
    "$py" -c 'import json, sys; m = json.load(open(sys.argv[1])); print(m["namingRevision"] if sys.argv[2] == "rev" else m["build"].split()[-1])' \
        "$(native "$gen/MANIFEST")" "$1"
}
genRev=$(manifestOf rev) && genHash=$(manifestOf hash) || die "can't read $gen/MANIFEST"
sourceRef=${againstRev:-HEAD}
sourceName="the working tree of $checkout"
[ -z "$againstRev" ] || sourceName=$againstRev
if [ -n "$againstRev" ]; then
    sourceRev=$(git -C "$checkout" show "$againstRev:src/App/Document.cpp" 2> /dev/null)
else
    sourceRev=$(cat "$checkout/src/App/Document.cpp" 2> /dev/null)
fi
sourceRev=$(printf '%s\n' "$sourceRev" | sed -n 's/^constexpr int ForkNamingRevision = \([0-9][0-9]*\);.*/\1/p' | head -n 1)
genStale=
if [ -z "$sourceRev" ]; then
    genStale="$genStale
  - can't find ForkNamingRevision in src/App/Document.cpp of $sourceRef"
elif [ "$genRev" != "$sourceRev" ]; then
    genStale="$genStale
  - the generation's namingRevision is $genRev, the source's ForkNamingRevision is $sourceRev"
fi
if [ -n "$againstRev" ]; then
    git -C "$checkout" diff --quiet "$genHash" "$againstRev" -- src ":!$compat/gen0" 2> /dev/null
else
    git -C "$checkout" diff --quiet "$genHash" -- src ":!$compat/gen0" 2> /dev/null
fi
case $? in
    0) ;;
    1) genStale="$genStale
  - the build ($genHash) differs in src/ from $sourceName: merge, then build, then regenerate" ;;
    *) genStale="$genStale
  - the build's commit $genHash is not in this checkout's history (fetch it, or the build isn't from this repository)" ;;
esac
if [ -n "$genStale" ]; then
    echo "regen_gen0: the generation was not made from this checkout's source:$genStale" >&2
    if [ $forceStale = 1 ]; then
        echo "regen_gen0: going on (--force-stale)" >&2
    elif [ "$mode" != report ]; then
        failed=1
        echo "regen_gen0: build the merged integration first (beta-compatibility.md 3.9); --force-stale goes on" >&2
        exit 5
    else
        echo "regen_gen0: (the report goes on; --check and --install refuse)" >&2
    fi
fi

echo "regen_gen0: comparing $gen with $old"
"$py" -I "$here/compare_generations.py" "$(native "$old")" "$(native "$gen")" $strict
cmpStatus=$?

if [ "$mode" = install ]; then
    rm -rf "$gen0src"
    mkdir -p "$gen0src"
    cp "$gen"/* "$gen0src"/
    echo "regen_gen0: installed into $gen0src"
    missing=
    for f in $(cd "$gen0src" && ls); do
        grep -qF "PartDesignTests/Compat/gen0/$f" "$checkout/src/Mod/PartDesign/CMakeLists.txt" ||
            missing="$missing $f"
    done
    stale=
    for f in $(grep -o "PartDesignTests/Compat/gen0/[A-Za-z0-9_.]*" "$checkout/src/Mod/PartDesign/CMakeLists.txt" | sed 's|.*/||'); do
        [ -e "$gen0src/$f" ] || stale="$stale $f"
    done
    if [ -n "$missing$stale" ]; then
        failed=1
        [ -z "$missing" ] || echo "regen_gen0: src/Mod/PartDesign/CMakeLists.txt (PartDesign_CompatGen0) lacks:$missing" >&2
        [ -z "$stale" ] || echo "regen_gen0: src/Mod/PartDesign/CMakeLists.txt lists files gen0 no longer has:$stale" >&2
        echo "regen_gen0: the build copies only the listed files, so TestCompatCorpus fails until it matches (ops#378)" >&2
        exit 4
    fi
    echo "regen_gen0: CMakeLists.txt lists exactly gen0's files"
    exit 0
fi

if [ "$mode" = check ]; then
    [ $cmpStatus = 0 ] || failed=1
    exit $cmpStatus
fi
if [ $cmpStatus != 0 ]; then
    failed=1
    echo "regen_gen0: the differences above are between the new generation and $old; nothing was written in the checkout (--install does)"
fi
echo "regen_gen0: the generation is in $gen (removed at the end unless --keep, --out or a difference)"
exit 0
