#!/bin/bash
# run.sh <checkout> <seed> <steps> [edits]: one assembly walk seed; log in work/asmwalk/runs/
CO=${1:-D:/CustomFreeCAD/wt/feature8}; SEED=${2:-1}; STEPS=${3:-60}
R=D:/CustomFreeCAD/work/asmwalk; H=$(dirname "$0")
export FREECAD_USER_HOME='D:\CustomFreeCAD\work\asmwalk\home'
export ASMWALK_SEED=$SEED ASMWALK_STEPS=$STEPS ASMWALK_EDITS=${4:-}
export ASMWALK_OUT="D:\\CustomFreeCAD\\work\\asmwalk\\runs\\s$SEED.jsonl"
( cd "$CO" && timeout 1800 pixi run build/relWithDebInfo/bin/FreeCADCmd.exe "$(cygpath -w "$(cd "$H" && pwd)/asm_walk.py")" ) > $R/runs/s$SEED.out 2>&1
echo "seed $SEED rc=$?"
python $H/summ.py $R/runs/s$SEED.jsonl
