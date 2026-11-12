#!/bin/bash
# The crash-recovery walk (ops#640 A3): kill the GUI mid-work, restart, record what comes back.
#
# usage: bash tests/journeys/recovery/walk.sh <checkout> [case ...]       cases: tabs unnamed steps saved early
#   <checkout>  absolute path of a built checkout (its pixi environment and build/relWithDebInfo run FreeCAD)
#   env: WALK_TIMEOUT_MIN (auto-recovery interval in minutes, default 1; the Onshape pack's is 5),
#        WALK_ONSCREEN=1 (show the windows), OPS_SCRIPTS (default C:/CustomFreeCAD/scripts),
#        WALK_BASE (output folder, default C:/CustomFreeCAD/work/a3-home/runs/<UTC time>)
# Everything runs on fresh FREECAD_USER_HOME folders under the output folder, never the real settings.
# Output: <base>/report.md and, per case, <base>/<case>/out/*.json and walk.log.
set -u
checkout=$1; shift
case $checkout in [A-Za-z]:[/\\]*) ;; *) echo "walk.sh: <checkout> must be absolute with its drive" >&2; exit 2 ;; esac
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BASE=${WALK_BASE:-C:/CustomFreeCAD/work/a3-home/runs/$(date -u +%Y%m%dT%H%M%SZ)}
hook=$BASE/hook.sh
mkdir -p "$BASE" || exit 2
pixi shell-hook --manifest-path "$checkout/pixi.toml" --as-is -s bash > "$hook" || exit 2
# shellcheck disable=SC1090
source "$hook"
export QT_PLUGIN_PATH="$checkout/.pixi/envs/default/Library/lib/qt6/plugins"
exec python "$HERE/driver.py" "$checkout/build/relWithDebInfo/bin/FreeCAD.exe" "$BASE" "$@"
