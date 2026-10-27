# SukiSU kernel interface compatibility

[Run 40439910371](https://github.com/PomDetom/GKI_KernelSU_SUSFS/actions/runs/40439910371/job/121977786130) passed the SUSFS patch stage and reached compilation with GKI `68067f2dc973fef7f359efc0fd07e37a97a1d099` and SukiSU-Ultra `05f5cdf082d32bbc651c205ba4bdd1dc66cca7f5`.

The five compiler diagnostics have three causes in the pinned SukiSU source:

1. `super_access.c` registers `netlink_kernel_cfg.cb_mutex`, which is absent from this GKI header. The two invalid-member diagnostics also cause the incomplete-array `sizeof` diagnostic. Remove this metadata entry only when the actual target structure lacks the field. Do not invent an offset or alter the kernel structure.
2. `throne_tracker.c` lacks a semicolon after the `my_dir_context` initializer ending in `.depth = pos->depth }`. Restore the declaration terminator.
3. `lsm_hook.c` passes the old string argument to `security_add_hooks`, but the target prototype requires `const struct lsm_id *`. For this prototype, pass a persistent `static const struct lsm_id` with name `ksu` and ID `LSM_ID_UNDEF`. The legacy string-based registration remains unchanged on headers using the old API.

The root setup action runs `.github/scripts/fix_sukisu_compat.py` for SukiSU-Ultra after cloning and before compilation. It probes the target headers rather than guessing from the version number, validates all source transformations before writing, and is repeatable. KPM, LSM hooks, root and SUSFS remain enabled according to the selected configuration.

Focused tests reproduce the old errors with Clang, compile the corrected API forms with warnings treated as errors, exercise modern/legacy/mixed headers, and check repeatability and an unknown source layout. These are small interface fixtures, not a complete kernel compilation or proof of device boot.

```bash
python3 .github/scripts/test_sukisu_compat.py
```

Sources: [target netlink header](https://android.googlesource.com/kernel/common/+/68067f2dc973fef7f359efc0fd07e37a97a1d099/include/linux/netlink.h), [target LSM header](https://android.googlesource.com/kernel/common/+/68067f2dc973fef7f359efc0fd07e37a97a1d099/include/linux/lsm_hooks.h), and [pinned SukiSU source](https://github.com/SukiSU-Ultra/SukiSU-Ultra/tree/05f5cdf082d32bbc651c205ba4bdd1dc66cca7f5/kernel).

## Final-link contract repair

Run 40444338280 compiled successfully and then exposed six undefined symbols. The root adapter now also restores `ksu_manager_appid`, initialized to `KSU_INVALID_APPID`. For Android 16 / 6.12, the SUSFS adapter supplies the actual backup-policy SELinux operations omitted from SukiSU and guards the preinit hooks when this fork has no preinit backend. See [the integration notes](../.github/actions/susfs/sukisu_compat/README.md).

Verification includes five root compatibility tests and three SUSFS wiring tests. In addition, the exact GKI common source was used to compile ARM64 `drivers/kernelsu/ksu.o`, `fs/exec.o`, `security/selinux/selinuxfs.o`, and `security/selinux/hooks.o`. A relocatable link of those objects has definitions for the manager and three SELinux operations, and no unresolved references to any of the six reported symbols. The four-object compile and relocatable-link checks pass both with CFI disabled and with CONFIG_CFI_CLANG=y. These focused probes use host Clang 21 with LTO, Rust and BTF disabled; they are not the complete production-profile image build or device acceptance.

## Additional LSM capacity on GKI 6.12

GKI `security_add_hooks()` panics when `lsm_active_cnt` reaches
`MAX_LSM_COUNT`. The stock `include/linux/lsm_count.h` counts neither
Baseband Guard nor KSU, although both register an LSM. This can let a
kernel compile and link successfully but fail during boot.

After Baseband Guard setup and before networking, the build recipe runs
`.github/scripts/fix_lsm_count.py`. It counts one additional LSM for each of
`IS_ENABLED(CONFIG_BBG)` and `IS_ENABLED(CONFIG_KSU)`, using the existing
trailing-comma count convention. Existing LSM registration and static-call
bounds checks remain intact. Reapplying the same fix is harmless; unknown
header layouts fail before writing. Kernels without this header are skipped.

The fix changes only compile-time capacity. The 6.12.69 kernel, 4K pages,
Keep KMI setting, SUSFS, NoMount, BBG and other feature settings are retained.
It addresses the missing slots; device boot still requires verification.

For an already prepared WSL workspace, apply the helper once before rebuilding:

```bash
cd ~/gki-build/GKI_KernelSU_SUSFS
python3 .github/scripts/fix_lsm_count.py --kernel .local-build/android16-6.12/kernel/common
scripts/wsl-build build
scripts/wsl-build package
```

This reuses synced source and Bazel cache without reapplying the full patch set.

Verified with the existing production configuration: capacity expands from 5 to 7.
Eighteen C compiler assertions using the actual GKI headers cover SECURITY
on/off and BBG/KSU disabled, built-in or module configurations.
