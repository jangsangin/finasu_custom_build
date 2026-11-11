#!/usr/bin/env bash
# FinaSU + SUSFS fixes (ported from GKI_FinaSU-dev scripts/susfs_fixes/apply.sh).
#
#   run.sh verify   - check FinaSU's native SUSFS glue is present (before patching)
#   run.sh post     - fixes to apply after the 50_add_susfs patch landed
#
# Env: KERNEL_ROOT (dir holding common/ and FinaSU/), defaults to ./kernel
set -eo pipefail

MODE="${1:?usage: run.sh verify|post}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KERNEL_ROOT="${KERNEL_ROOT:-$PWD/kernel}"
FINASU_KSU="${FINASU_KSU:-$KERNEL_ROOT/FinaSU/kernel}"

verify_native_susfs() {
  local OPT SYM
  [ -f "$FINASU_KSU/extension/susfs.c" ] || {
    echo "::error::FinaSU has no native SUSFS glue (missing extension/susfs.c); source predates 5b83330b or layout changed." >&2
    exit 1
  }
  for OPT in KSU_SUSFS KSU_SUSFS_SUS_PATH KSU_SUSFS_SUS_MOUNT KSU_SUSFS_SUS_KSTAT \
             KSU_SUSFS_SPOOF_UNAME KSU_SUSFS_ENABLE_LOG KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS \
             KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG KSU_SUSFS_OPEN_REDIRECT KSU_SUSFS_SUS_MAP; do
    grep -q "^config $OPT\$" "$FINASU_KSU/Kconfig" \
      || { echo "::error::FinaSU Kconfig lacks config $OPT" >&2; exit 1; }
  done
  for SYM in ksu_handle_execveat ksu_handle_execveat_sucompat ksu_handle_post_execveat_sucompat; do
    grep -qE "^(int|void) $SYM\(" "$FINASU_KSU/extension/susfs.c" \
      || { echo "::error::FinaSU extension/susfs.c lacks entry point $SYM" >&2; exit 1; }
  done
  for SYM in ksu_setup_preinit_file ksu_preinit_handle_post_execveat; do
    if grep -qE "^(int|void) $SYM\(" "$FINASU_KSU/preinit/preinit.c" 2>/dev/null; then continue; fi
    grep -qE "^(int|void) $SYM\(" "$FINASU_KSU/extension/susfs.c" \
      || { echo "::error::FinaSU lacks entry point $SYM (checked preinit/preinit.c and extension/susfs.c)" >&2; exit 1; }
  done
  grep -q '^int ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid)$' "$FINASU_KSU/hook/setuid_hook.c" \
    || { echo "::error::FinaSU setuid_hook.c lacks the 3-arg ksu_handle_setresuid" >&2; exit 1; }
  for SYM in my_write_context my_write_access my_setprocattr; do
    grep -qE "^(ssize_t|int) $SYM\(" "$FINASU_KSU/feature/selinux_hide.c" \
      || { echo "::error::FinaSU selinux_hide.c does not export $SYM" >&2; exit 1; }
  done
  grep -q 'susfs_init();' "$FINASU_KSU/core/init.c" \
    || { echo "::error::FinaSU init.c does not call susfs_init()" >&2; exit 1; }
  echo "FinaSU native SUSFS integration verified"
}

post_fixes() {
  cd "$KERNEL_ROOT/common"

  # --- 1. FinaSU new selinux_hide model (no fake_state; backup_sepolicy + 8-arg _with_policy)
  local SELINUX_HIDE="$FINASU_KSU/feature/selinux_hide.c" NEW_MODEL=0
  if [ -f "$SELINUX_HIDE" ] && ! grep -q 'fake_state' "$SELINUX_HIDE"; then NEW_MODEL=1; fi
  if [ "$NEW_MODEL" = 1 ] && [ -f security/selinux/selinuxfs.c ] \
    && { grep -q 'static ssize_t my_write_context' security/selinux/selinuxfs.c \
         || grep -q '&fake_state' security/selinux/selinuxfs.c; }; then
    echo "FinaSU new selinux_hide model: switching SUSFS SELinux code to backup_sepolicy + 8-arg _with_policy"
    python3 "$HERE/selinux_newmodel.py"
    grep -n 'backup_sepolicy' security/selinux/selinuxfs.c | head -3 || true
    grep -n 'perm_error' security/selinux/hooks.c | head -3 || true
  else
    echo "selinux new-model adaptation not needed"
  fi

  # --- 2. sus_path: fall back to the LOOP mechanism when the caller's namespace can't resolve the path (FUSE etc.)
  if [ -f fs/susfs.c ] && grep -qF 'void susfs_add_sus_path(void __user **user_info)' fs/susfs.c \
    && ! grep -qF 'FINASU_SUS_PATH_LOOP_FALLBACK' fs/susfs.c; then
    python3 "$HERE/sus_path_loop_fallback.py"
    grep -n 'FINASU_SUS_PATH_LOOP_FALLBACK' fs/susfs.c | head -3 || true
  else
    echo "sus_path loop fallback: already present or susfs_add_sus_path not found, skipping"
  fi

  # --- 3. 5.10: statfs extern declared after its use site -> declare in susfs_def.h (with struct forward decls)
  local SUSFS_DEF_H="$KERNEL_ROOT/common/include/linux/susfs_def.h"
  if [[ -f fs/statfs.c ]] && grep -qF 'susfs_sus_kstat_spoof_vfs_statfs(' fs/statfs.c \
    && [[ -f "$SUSFS_DEF_H" ]] && ! grep -qF 'susfs_sus_kstat_spoof_vfs_statfs(' "$SUSFS_DEF_H"; then
    echo "Declaring susfs_sus_kstat_spoof_vfs_statfs in include/linux/susfs_def.h"
    sed -i '/^#endif \/\/ #ifndef KSU_SUSFS_DEF_H$/i struct inode;\nstruct kstatfs;\nextern int susfs_sus_kstat_spoof_vfs_statfs(struct inode *inode, struct kstatfs *buf, bool *is_fuse);' "$SUSFS_DEF_H"
  fi

  # --- 4. susfs.c calls security_sb_statfs() without including linux/security.h (5.10)
  if [[ -f fs/susfs.c ]] && grep -qF 'security_sb_statfs(' fs/susfs.c \
    && ! grep -qF '#include <linux/security.h>' fs/susfs.c; then
    echo "Adding linux/security.h to fs/susfs.c"
    sed -i '0,/^#include <linux\/fs.h>$/s//#include <linux\/fs.h>\n#include <linux\/security.h>/' fs/susfs.c
  fi

  # --- 5. guard: readable error if the main patch missed susfs_def.h
  local SRC
  for SRC in fs/proc/task_mmu.c fs/namespace.c; do
    [[ -f "$SRC" ]] || continue
    if grep -qE 'SUSFS_IS_INODE_|CL_COPY_MNT_NS' "$SRC" && ! grep -qF '#include <linux/susfs_def.h>' "$SRC"; then
      echo "::error::$SRC uses SUSFS macros but lacks linux/susfs_def.h (main patch hunk not applied)" >&2
      exit 1
    fi
  done
}

case "$MODE" in
  verify) verify_native_susfs ;;
  post)   post_fixes ;;
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
