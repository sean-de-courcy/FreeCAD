#!/bin/bash
# run_seeds.sh: unattended fuzz D+ seeds, one FreeCADCmd at a time (ops#640).
# Usage: run_seeds.sh <workspace> <out dir> <user home dir> <steps> <seed spec>...
#   seed spec: <n> (plain) or h<n> (FUZZ_HEAL=1). Writes <out>/pid; stops before the next seed when <out>/STOP exists.
# On the Mac, call it from a wrapper that takes the slot lock (work/mac-coord/slot-lock.sh) first.
set -u
WS=$1; OUT=$2; UH=$3; STEPS=$4; shift 4
mkdir -p "$OUT"
[ -d "$UH" ] || { echo "no user home $UH"; exit 2; }
echo $$ > "$OUT/pid"
for spec in "$@"; do
    if [ -e "$OUT/STOP" ]; then echo "=== $(date -u +%H:%M:%SZ) STOP file, ending before $spec"; break; fi
    heal=0; n=$spec
    case $spec in h*) heal=1; n=${spec#h};; esac
    tag=plus$n; [ $heal = 1 ] && tag=plush$n
    echo "=== $(date -u +%H:%M:%SZ) seed $n heal=$heal steps=$STEPS"
    FREECAD_USER_HOME="$UH" FUZZ_OUT="$OUT" FUZZ_SEED=$n FUZZ_STEPS=$STEPS FUZZ_HEAL=$heal FUZZ_TAG=$tag FUZZ_STOPAT=${FUZZ_STOPAT:-SILENT,LOUD} \
        pixi run --manifest-path "$WS/pixi.toml" "$WS/build/release/bin/FreeCADCmd" "$WS/tools/fuzz/fuzzplus.py" \
        > "$OUT/$tag.log" 2>&1
    grep '^FUZZ' "$OUT/$tag.log" || echo "seed $n: no summary (see $tag.log)"
done
echo "=== $(date -u +%H:%M:%SZ) done"
rm -f "$OUT/pid"
