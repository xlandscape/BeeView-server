#!/usr/bin/env bash
# Build the deployment package of BeeView + xPollinator from the committed state of all repositories.
#
#   bash deploy/package.sh            # writes ../_deploy/package/
#   WITH_WHEELS=0 bash deploy/package.sh   # skip the offline Python packages
#
# Output (input for deploy/windows/install.ps1 and for deploy/aws/deploy.sh upload):
#   xpollinator.zip     xPollinator HEAD + submodules model/core and model/variant/BeeHaveEcotox
#                       + scenario/Scenario-TarnEtGaronne HEAD (bundled Python 3.9.7, JDK, NetLogo included)
#   beeview-server.zip  BeeView-server HEAD + frontend/ built from BeeView HEAD
#   data.zip            data/ with beeview.duckdb (checkpointed copy), forage array, shapefile, caches
#   wheels.zip          Python packages for requirements.txt (cp39, win_amd64) for an offline install
#   install.ps1, INSTALL.md, VERSIONS.txt
#
# Only committed content is packaged (git archive). Uncommitted changes are reported and left out.
# Stop the local BeeView server first: DuckDB keeps the database file locked while it runs.
# Requires: git, tar (Git for Windows), npm (BeeView build), BeeView-server/venv (DuckDB, pip).
# Behind a TLS-inspecting proxy set PIP_CERT to a CA bundle for the wheel download.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRV="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$SRV/.." && pwd)"
XP="$ROOT/xPollinator"
UI="$ROOT/BeeView"
SCN="$XP/scenario/Scenario-TarnEtGaronne"
WORK="${DEPLOY_WORK:-$ROOT/_deploy}"
OUT="$WORK/package"
STAGE="$WORK/stage"
WITH_WHEELS="${WITH_WHEELS:-1}"
PY="$SRV/venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$SRV/venv/bin/python"

REPOS=(
  "xPollinator|$XP"
  "LandscapeModel-Core (model/core)|$XP/model/core"
  "BeeHaveEcotox-Component (model/variant/BeeHaveEcotox)|$XP/model/variant/BeeHaveEcotox"
  "Scenario-TarnEtGaronne (scenario/Scenario-TarnEtGaronne)|$SCN"
  "BeeView|$UI"
  "BeeView-server|$SRV"
)

rm -rf "$STAGE" "$OUT"
mkdir -p "$STAGE" "$OUT"

echo "== repositories"
{
  echo "BeeView + xPollinator deployment package, built $(date '+%Y-%m-%d %H:%M') on $(hostname)"
  echo
  printf "%-56s %-30s %-10s %s\n" "Repository" "Branch" "Commit" "Remote"
  for entry in "${REPOS[@]}"; do
    name="${entry%%|*}"; dir="${entry#*|}"
    branch="$(git -C "$dir" branch --show-current)"; [ -n "$branch" ] || branch="(detached)"
    printf "%-56s %-30s %-10s %s\n" "$name" "$branch" "$(git -C "$dir" rev-parse --short HEAD)" \
      "$(git -C "$dir" remote get-url origin 2>/dev/null || echo '-')"
  done
} > "$OUT/VERSIONS.txt"
cat "$OUT/VERSIONS.txt"
for entry in "${REPOS[@]}"; do
  name="${entry%%|*}"; dir="${entry#*|}"
  changed="$(git -C "$dir" status --short --untracked-files=no | wc -l)"
  unpushed="$(git -C "$dir" rev-list --count '@{u}..HEAD' 2>/dev/null || echo '?')"
  [ "$changed" = "0" ] || echo "WARNING: $name has $changed uncommitted change(s); they are not packaged"
  [ "$unpushed" = "0" ] || echo "WARNING: $name has $unpushed unpushed commit(s) (or no upstream)"
done
if [ -n "$(git -C "$UI" status --short)" ]; then
  echo "ERROR: BeeView has local changes; the frontend is built from the working tree, so commit or stash them first"
  exit 1
fi

echo "== xPollinator (git archive)"
git -C "$XP" archive --format=tar --prefix=xPollinator/ HEAD | tar -x -C "$STAGE"
git -C "$XP/model/core" archive --format=tar --prefix=xPollinator/model/core/ HEAD | tar -x -C "$STAGE"
git -C "$XP/model/variant/BeeHaveEcotox" archive --format=tar --prefix=xPollinator/model/variant/BeeHaveEcotox/ HEAD \
  | tar -x -C "$STAGE"
git -C "$SCN" archive --format=tar --prefix=xPollinator/scenario/Scenario-TarnEtGaronne/ HEAD | tar -x -C "$STAGE"
mkdir -p "$STAGE/xPollinator/run"
cp "$OUT/VERSIONS.txt" "$STAGE/xPollinator/"
(cd "$STAGE" && tar -a -cf "$OUT/xpollinator.zip" xPollinator)

echo "== BeeView-server (git archive) + frontend built from BeeView"
git -C "$SRV" archive --format=tar --prefix=BeeView-server/ HEAD | tar -x -C "$STAGE"
(cd "$UI" && npm run build --silent)
rm -rf "$STAGE/BeeView-server/frontend"
cp -r "$UI/dist" "$STAGE/BeeView-server/frontend"
cp "$OUT/VERSIONS.txt" "$STAGE/BeeView-server/"
(cd "$STAGE" && tar -a -cf "$OUT/beeview-server.zip" BeeView-server)

echo "== data (database copy, checkpointed)"
DATA="$STAGE/data"
mkdir -p "$DATA/cache"
cp "$SRV/data/beeview.duckdb" "$DATA/" || { echo "beeview.duckdb is locked: stop the BeeView server and retry"; exit 1; }
[ -f "$SRV/data/beeview.duckdb.wal" ] && cp "$SRV/data/beeview.duckdb.wal" "$DATA/"
"$PY" - "$DATA/beeview.duckdb" <<'PYEOF'
import sys, duckdb
con = duckdb.connect(sys.argv[1])
con.execute("CHECKPOINT")
runs = con.execute("SELECT count(*) FROM runs").fetchone()[0]
apps = con.execute("SELECT count(*) FROM applications").fetchone()[0]
feats = con.execute("SELECT count(*) FROM features").fetchone()[0]
print(f"database: {runs} runs, {apps} applications, {feats} features, DuckDB {duckdb.__version__}")
con.close()
PYEOF
rm -f "$DATA/beeview.duckdb.wal"
cp "$SRV/data/arr.dat" "$SRV/data/"*.csv "$SRV/data/"*.json "$SRV/data/"Tarn_LULC_v04.* "$DATA/"
find "$SRV/data/cache" -maxdepth 1 -type f ! -name "*.pre-*" -exec cp {} "$DATA/cache/" \;
(cd "$STAGE" && tar -a -cf "$OUT/data.zip" data)

if [ "$WITH_WHEELS" = "1" ]; then
  echo "== wheels (cp39 / win_amd64) for an offline install"
  "$PY" -m pip download --quiet --dest "$STAGE/wheels" --only-binary=:all: \
    --platform win_amd64 --python-version 3.9 --implementation cp --abi cp39 \
    -r "$SRV/requirements.txt" pip
  (cd "$STAGE" && tar -a -cf "$OUT/wheels.zip" wheels)
fi

cp "$SRV/deploy/windows/install.ps1" "$SRV/deploy/windows/INSTALL.md" "$OUT/"
rm -rf "$STAGE"
echo "== package"
ls -la "$OUT"
