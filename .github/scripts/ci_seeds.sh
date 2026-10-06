#!/bin/bash
# TEMPORARY (ops#127 P8b, fork PR 122; reverted before the merge): design note N3 9.1 step 8's
# seed series on both platforms. Seeds 1-200, 12 steps, V2s, standard and with
# FREECAD_SCENARIO_GAP=1; SCORE records and logs go to the logs folder (the Logs artifact).
#   ci_seeds.sh <FreeCADCmd> <logs folder>
FC="$1"
OUT="$2"
mkdir -p "$OUT"
status=0
for series in standard gap1; do
  gap=""
  [ "$series" = gap1 ] && gap=1
  rm -f "$OUT/seeds-$series.jsonl"
  FREECAD_SCENARIO_CONFIGS=V2s FREECAD_SCENARIO_SEEDS=1-200 FREECAD_SCENARIO_STEPS=12 \
    FREECAD_SCENARIO_GAP="$gap" FREECAD_SCENARIO_SCORE_FILE="$OUT/seeds-$series.jsonl" \
    "$FC" -t PartDesignTests.TestNamingScenarios.RandomSequences 2>&1 \
    | grep -v 'SCORE {' > "$OUT/seeds-$series.log"
  s=${PIPESTATUS[0]}
  echo "seeds $series: exit $s; $(grep -E '^Ran [0-9]+ tests|^OK|^FAILED' "$OUT/seeds-$series.log" | tr '\n' ' ')"
  grep -E '^(FAIL|ERROR): ' "$OUT/seeds-$series.log"
  [ "$s" -ne 0 ] && status=$s
done
exit $status
