#!/bin/bash
# run_truth.sh: unattended truth-walk seeds, one FreeCADCmd at a time (ops#640).
# Usage: run_truth.sh <workspace> <out dir> <user home dir> <steps> <template:seed>...
#   e.g. run_truth.sh wt/feature8 work/sbef2/truth work/sbef2/uh 200 T7:1 T7:2 T4:1
# TRUTH_BUILD=relWithDebInfo on Windows (default release). Writes <out>/pid; stops before the next seed when <out>/STOP exists. Prints each seed's TRUTH summary line.
set -u
WS=$1; OUT=$2; UH=$3; STEPS=$4; shift 4
mkdir -p "$OUT"
[ -d "$UH" ] || { echo "no user home $UH"; exit 2; }
echo $$ > "$OUT/pid"
for spec in "$@"; do
    if [ -e "$OUT/STOP" ]; then echo "=== $(date -u +%H:%M:%SZ) STOP file, ending before $spec"; break; fi
    t=${spec%%:*}; n=${spec#*:}
    echo "=== $(date -u +%H:%M:%SZ) $t seed $n steps=$STEPS"
    FREECAD_USER_HOME="$UH" TRUTH_OUT="$OUT" TRUTH_T=$t TRUTH_SEED=$n TRUTH_STEPS=$STEPS \
        pixi run --manifest-path "$WS/pixi.toml" "$WS/build/${TRUTH_BUILD:-release}/bin/FreeCADCmd" "$WS/tools/fuzz/truth.py" \
        > "$OUT/$t-$n.log" 2>&1
    grep '^TRUTH' "$OUT/$t-$n.log" || echo "$t seed $n: no summary (see $t-$n.log)"
done
echo "=== $(date -u +%H:%M:%SZ) done"
rm -f "$OUT/pid"
