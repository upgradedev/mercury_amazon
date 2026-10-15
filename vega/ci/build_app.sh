#!/usr/bin/env bash
# build_app.sh mercury | control
#
# mercury: builds Mercury's Vega app, armv7 for Fire TV sticks first, then
#   x86_64 for the Vega Virtual Device on this Intel runner, then aarch64 for
#   the VVD on an M-series Mac, the one VVD that runs WebView apps
#   (build-an-app.html, kvd-issues.html; run-apps.html:
#   build/<ARCH>-<TYPE>/<APP>_<ARCH>.vpkg). vega/ builds as committed when it
#   has a package.json. Without one, the committed src/ and test/ are laid over
#   the freshly generated vegaWebview template, so the SDK's own package.json
#   and manifest.toml are used.
# control: builds the generated helloWorld template for x86_64. It has no
#   WebView, so on the VVD it separates a broken pipeline from a missing module.
set -uo pipefail
source "$(dirname "$0")/lib.sh"

what="${1:?usage: build_app.sh mercury|control}"
strict="${VEGA_STRICT_CHECKS:-0}"
repo="${GITHUB_WORKSPACE:-$(pwd)}"

# vpkg_for <dir> <arch>: the newest vpkg built for that architecture.
vpkg_for() {
  find "$1/build" -name "*_$2.vpkg" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-
}

# build <dir> <arch> <label>: one Release build for one architecture, through
# the project's own build:release script so its flags (--build-number) apply.
# Falls back to the script without --target if no vpkg for <arch> appears.
build() {
  local dir="$1" arch="$2" label="$3" log rc vpkg
  log="$OUT/logs/$label-build-$arch.log"
  (cd "$dir" && timeout 1200 npm run build:release -- --target "$arch") > "$log" 2>&1
  rc=$?
  if [ -z "$(vpkg_for "$dir" "$arch")" ]; then
    echo "--- no $arch vpkg after --target (exit $rc); trying npm run build:release" >> "$log"
    (cd "$dir" && timeout 1800 npm run build:release) >> "$log" 2>&1 || true
  fi
  vpkg="$(vpkg_for "$dir" "$arch")"
  if [ -n "$vpkg" ]; then
    status "${label}_build_$arch" ok
    printf '%s\n' "$vpkg"
    return 0
  fi
  status "${label}_build_$arch" "failed (exit $rc)"
  tail -40 "$log" >&2
  return 1
}

npm_install() {  # npm_install <dir> <label>: npm ci when a lockfile is committed
  local log="$OUT/logs/$2-npm-install.log"
  mark "npm install ($2)"
  if [ -f "$1/package-lock.json" ] && (cd "$1" && npm ci --no-audit --no-fund) > "$log" 2>&1; then
    status "${2}_npm_install" "ok (npm ci)"
    return 0
  fi
  if (cd "$1" && npm install --no-audit --no-fund) >> "$log" 2>&1; then
    status "${2}_npm_install" "ok (npm install)"
    return 0
  fi
  tail -60 "$log"
  status "${2}_npm_install" failed
  return 1
}

if [ "$what" = control ]; then
  control_root="$(status_of template_root_helloWorld)"
  npm_install "$control_root" control || exit 1
  mark "build the helloWorld control for x86_64"
  vpkg="$(build "$control_root" x86_64 control)" || exit 1
  status control_vpkg "$vpkg"
  exit 0
fi

webview_root="$(status_of template_root_vegaWebview)"
if [ -f "$repo/vega/package.json" ]; then
  app="$repo/vega"
  status mercury_build_mode direct
else
  app="${RUNNER_TEMP:-/tmp}/mercury-vega-app"
  rm -rf "$app"
  cp -a "$webview_root" "$app"
  rm -rf "$app/test" "$app/__tests__" "$app/src"
  mkdir -p "$app/src" "$app/test"
  cp -a "$repo/vega/src/." "$app/src/"
  cp -a "$repo/vega/test/." "$app/test/"
  status mercury_build_mode overlay_on_generated_vegaWebview
fi
status mercury_app_dir "$app"

npm_install "$app" mercury || exit 1

mark "unit tests and type check (Mercury)"
(cd "$app" && npx jest --ci) > "$OUT/logs/mercury-jest.log" 2>&1
jest_rc=$?
status mercury_jest "$([ $jest_rc = 0 ] && echo passed || echo "failed (exit $jest_rc)")"
(cd "$app" && npx tsc --noEmit) > "$OUT/logs/mercury-tsc.log" 2>&1
tsc_rc=$?
status mercury_tsc "$([ $tsc_rc = 0 ] && echo passed || echo "failed (exit $tsc_rc)")"
tail -25 "$OUT/logs/mercury-jest.log"
tail -25 "$OUT/logs/mercury-tsc.log"
if [ "$strict" = 1 ] && { [ $jest_rc != 0 ] || [ $tsc_rc != 0 ]; }; then
  echo "::error::Mercury's Vega unit tests or type check failed"
  exit 1
fi

: > "$OUT/vpkg/SHA256SUMS"
for arch in armv7 x86_64 aarch64; do
  mark "build Mercury $arch"
  if vpkg="$(build "$app" "$arch" mercury)"; then
    cp "$vpkg" "$OUT/vpkg/"
    (cd "$OUT/vpkg" && sha256sum "$(basename "$vpkg")" >> SHA256SUMS)
    status "mercury_vpkg_$arch" "$(basename "$vpkg")"
  fi
done
cat "$OUT/vpkg/SHA256SUMS"
ls -la "$OUT/vpkg"
for file in manifest.toml package.json package-lock.json; do
  cp "$app/$file" "$OUT/logs/mercury-$file" 2>/dev/null || true
done
# The manifest each vpkg carries: vega/manifest.toml plus the modules the
# build's remapper (amzn_kepler_manifest_module_remapper) added for the
# @amazon-devices packages, WebView included. The run log shows the module
# ids, what the build said about the icon, and where it staged the icon.
for arch in armv7 x86_64 aarch64; do
  packaged="$(find "$app/build" -path "*/vega/$arch/Release/manifest.toml" 2>/dev/null | head -1)"
  if [ -n "$packaged" ]; then
    cp "$packaged" "$OUT/logs/mercury-manifest-packaged-$arch.toml"
    status "mercury_packaged_webview_$arch" \
      "$(grep -c 'com.amazon.kepler.webview_4@IWebview_4' "$packaged" || true)"
    echo "Modules the $arch package needs:"
    grep -E '^id *= *"/' "$packaged" || true
  fi
done
echo "Build lines on the icon and the module remapper:"
sed -E 's/\x1b\[[0-9;]*m//g' "$OUT"/logs/mercury-build-*.log \
  | grep -E 'package\.icon|Found dependencies to add|needs: \[' | sort -u || true
echo "Icon files the build staged:"
find "$app/build" -name 'mercury_icon*.png' -printf '%s\t%p\n' 2>/dev/null | head -8 || true
find "$app/build" -maxdepth 3 > "$OUT/logs/mercury-build-tree.txt" 2>/dev/null || true

# A committed vega/ must not change when it is installed, tested and built.
if [ "$(status_of mercury_build_mode)" = direct ]; then
  git -C "$repo" status --porcelain -- vega/ > "$OUT/logs/vega-tree-after-build.txt"
  git -C "$repo" diff -- vega/ > "$OUT/logs/vega-tree-after-build.diff"
  if [ -s "$OUT/logs/vega-tree-after-build.txt" ]; then
    status vega_tree_after_build dirty
    echo "::warning::building changed tracked files under vega/"
    cat "$OUT/logs/vega-tree-after-build.txt"
  else
    status vega_tree_after_build clean
  fi
fi

# The armv7 package is the one a Vega Fire TV stick installs; without it the
# step fails. A missing x86_64 package is left to the verdict step, so the
# virtual device steps still run. A missing aarch64 package (the Mac VVD's)
# shows as mercury_build_aarch64 in status/ and in the vpkg artifact.
[ -n "$(status_of mercury_vpkg_armv7)" ] || { echo "::error::no armv7 vpkg"; exit 1; }
