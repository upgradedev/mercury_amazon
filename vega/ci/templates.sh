#!/usr/bin/env bash
# Generates Amazon's vegaWebview and helloWorld templates with the installed SDK.
#
# vegaWebview is what vega/ is checked against: the same --name and --packageId,
# so a diff shows only what Mercury changed. helloWorld is the control app for
# the virtual device: it has no WebView, so it tells a broken VVD pipeline apart
# from a missing WebView module.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

templates="${RUNNER_TEMP:-/tmp}/vega-templates"
rm -rf "$templates"
mkdir -p "$templates"
vega project list-templates > "$OUT/logs/list-templates.txt" 2>&1 || true
cat "$OUT/logs/list-templates.txt"

generate() {  # generate <template> <name> <packageId>
  local dir="$templates/$1"
  vega project generate --template "$1" --name "$2" --packageId "$3" --outputDir "$dir" \
    < /dev/null > "$OUT/logs/generate-$1.log" 2>&1
  # The project root is wherever manifest.toml landed (the output dir or a child).
  local manifest root
  manifest="$(find "$dir" -maxdepth 3 -name manifest.toml ! -path '*/node_modules/*' | head -1)"
  if [ -z "$manifest" ]; then
    echo "::error::vega project generate --template $1 produced no manifest.toml"
    cat "$OUT/logs/generate-$1.log"
    exit 1
  fi
  root="$(dirname "$manifest")"
  printf '%s\n' "$root" > "$OUT/status/template_root_$1"
  (cd "$root" && find . -type f ! -path './node_modules/*' -printf '%s\t%p\n' | sort -k2) \
    > "$OUT/logs/template-$1-files.tsv"
}

generate vegaWebview MercuryCockpit com.upgradedev.mercury
generate helloWorld HelloVega com.upgradedev.hellovega

# Keep the whole generated vegaWebview project (no node_modules) as an artifact.
webview_root="$(status_of template_root_vegaWebview)"
template_out="${TEMPLATE_OUT:?TEMPLATE_OUT must name the template artifact directory}"
mkdir -p "$template_out"
(cd "$webview_root" && tar --exclude=./node_modules -cf - .) | (cd "$template_out" && tar -xf -)

# What Mercury's committed files change relative to the generated ones.
{
  for file in package.json manifest.toml app.json index.js babel.config.js metro.config.js \
    tsconfig.json jest.config.json .gitignore src/App.tsx; do
    if [ -f "vega/$file" ]; then
      diff -u "$webview_root/$file" "vega/$file" || true
    else
      echo "=== vega/$file is not committed; the build uses the generated one"
    fi
  done
} > "$OUT/logs/template-vs-vega.diff" 2>&1
status templates ok
