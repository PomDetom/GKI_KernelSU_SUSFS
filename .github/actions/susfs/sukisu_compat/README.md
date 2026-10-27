# SukiSU SUSFS link contract

Run 40444338280 reached the final kernel link and reported six missing symbols.

- `ksu_manager_appid` was declared and used but never defined in SukiSU 05f5cdf. Root compatibility setup restores one shared variable initialized to `KSU_INVALID_APPID`, so an unrecognized user is not treated as the built-in manager.
- `my_write_context`, `my_write_access`, and `my_setprocattr` were absent even though SukiSU retained the backup policy and SELinux-hide state. `selinux_operations.inc` restores their actual backup-policy implementations and required private helpers. It retains AVC checks, context translation, access-vector evaluation, and credential-transition checks.
- `ksu_setup_preinit_file` and `ksu_preinit_handle_post_execveat` belong to an optional preinit runner that this SukiSU snapshot does not implement. For this tree, fs/exec.c uses the existing SUSFS `KSU_NO_PREINIT` guard. Its existing ksud/init path stays in use. No success-returning preinit stubs are added. A source tree with a preinit backend is left enabled.

The SUSFS action integrates this asset only for the Android 16 / 6.12 SukiSU flavor, after the base kernel patch. Other root flavors retain their existing integration.

## Provenance

The operations asset comes from [tiann/KernelSU feature/selinux_hide.c at 4663610011d03771a64e7c36a2aa65bd1794022d](https://github.com/tiann/KernelSU/blob/4663610011d03771a64e7c36a2aa65bd1794022d/kernel/feature/selinux_hide.c), after applying its complete file section from [SUSFS 10_enable_susfs_for_ksu.patch at 9c9f19d8395693327c78df36569b44e94c187b8a](https://gitlab.com/simonpunk/susfs4ksu/-/blob/9c9f19d8395693327c78df36569b44e94c187b8a/kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch).

Only the operation declarations, compatibility macros, three public operations and their private policy helpers are carried over. SukiSU's feature registration, policy backup lifecycle and status-page code remain in its original selinux_hide.c. This avoids replacing unrelated behavior with a different root flavor's complete feature module. The include adds explicit scheduler/SELinux headers for the unity build.

See THIRD_PARTY_NOTICES.md for component attribution. The small C fixtures in the wiring tests only check linkage/guard selection; they are not implementations shipped into the kernel and do not establish runtime SELinux behavior.
