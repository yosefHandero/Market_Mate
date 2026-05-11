#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
DRY_RUN=0

usage() {
  printf 'Usage: %s [--dry-run]\n' "$0"
  printf 'Copies services/scanner/market_mate.db to services/scanner/backups/ without deleting old backups.\n'
}

for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN=1
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

src_rel="services/scanner/market_mate.db"
backup_dir_rel="services/scanner/backups"
src="$ROOT/$src_rel"
backup_dir="$ROOT/$backup_dir_rel"

if [ ! -f "$src" ]; then
  printf 'Database not found: %s\n' "$src_rel" >&2
  exit 1
fi

if command -v git >/dev/null 2>&1; then
  if ! git -C "$ROOT" check-ignore -q "$backup_dir_rel/"; then
    printf 'Refusing backup because %s/ is not ignored by git.\n' "$backup_dir_rel" >&2
    exit 1
  fi
fi

stamp=$(date '+%Y%m%d-%H%M')
dest_rel="$backup_dir_rel/market_mate.db.$stamp.bak"
dest="$ROOT/$dest_rel"

if [ -e "$dest" ]; then
  printf 'Refusing to overwrite existing backup: %s\n' "$dest_rel" >&2
  exit 1
fi

if [ "$DRY_RUN" -eq 1 ]; then
  printf 'DRY-RUN would create %s/ if missing\n' "$backup_dir_rel"
  printf 'DRY-RUN would copy %s to %s\n' "$src_rel" "$dest_rel"
  exit 0
fi

mkdir -p -- "$backup_dir"
cp -p -- "$src" "$dest"
printf 'Backed up %s to %s\n' "$src_rel" "$dest_rel"
