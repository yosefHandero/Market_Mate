#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
CONFIRM=0

usage() {
  printf 'Usage: %s [--yes]\n' "$0"
  printf 'Dry-run is the default. Pass --yes to delete only the allowlisted local artifacts.\n'
}

for arg in "$@"; do
  case "$arg" in
    --yes)
      CONFIRM=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

assert_allowed() {
  case "$1" in
    apps/web/.next/|apps/web/node_modules/.vite/|apps/web/tsconfig.tsbuildinfo|services/scanner/var/cache/*.json)
      ;;
    *)
      printf 'Refusing cleanup target outside allowlist: %s\n' "$1" >&2
      exit 1
      ;;
  esac
}

print_target() {
  if [ "$CONFIRM" -eq 1 ]; then
    printf 'DELETE %s\n' "$1"
  else
    printf 'DRY-RUN would delete %s\n' "$1"
  fi
}

delete_dir() {
  rel="$1"
  display="$rel/"
  target="$ROOT/$rel"

  assert_allowed "$display"
  if [ -e "$target" ] || [ -L "$target" ]; then
    print_target "$display"
    if [ "$CONFIRM" -eq 1 ]; then
      rm -rf -- "$target"
    fi
  else
    printf 'SKIP missing %s\n' "$display"
  fi
}

delete_file() {
  rel="$1"
  target="$ROOT/$rel"

  assert_allowed "$rel"
  if [ -e "$target" ] || [ -L "$target" ]; then
    print_target "$rel"
    if [ "$CONFIRM" -eq 1 ]; then
      rm -f -- "$target"
    fi
  else
    printf 'SKIP missing %s\n' "$rel"
  fi
}

delete_dir "apps/web/.next"
delete_dir "apps/web/node_modules/.vite"
delete_file "apps/web/tsconfig.tsbuildinfo"

cache_dir="$ROOT/services/scanner/var/cache"
cache_found=0
if [ -d "$cache_dir" ]; then
  for target in "$cache_dir"/*.json; do
    [ -e "$target" ] || [ -L "$target" ] || continue
    rel=${target#"$ROOT"/}
    assert_allowed "$rel"
    print_target "$rel"
    cache_found=1
    if [ "$CONFIRM" -eq 1 ]; then
      rm -f -- "$target"
    fi
  done
fi

if [ "$cache_found" -eq 0 ]; then
  printf 'SKIP missing services/scanner/var/cache/*.json\n'
fi

if [ "$CONFIRM" -eq 1 ]; then
  printf 'Cleanup complete.\n'
else
  printf 'Dry-run only. Re-run with --yes to delete the listed paths.\n'
fi
