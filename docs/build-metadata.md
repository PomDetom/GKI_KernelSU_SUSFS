# Build timestamp

The workflow and the build action capture the actual build instant and export
`SOURCE_DATE_EPOCH`, `KBUILD_BUILD_TIMESTAMP` (UTC), and `BUILD_DATE`
(Asia/Shanghai, YYYYMMDD). The build action refreshes these values even when
reusing an already prepared workspace. The Android security patch level remains
unchanged and is not used as a fabricated build timestamp.

Kleaf builds enable `--config=stamp`. Without this option the pinned Kleaf
`impl/stamp.bzl` sets `SOURCE_DATE_EPOCH=0`, and `_setup_env.sh` turns that into
the Unix epoch for Kbuild. Setting the outer workflow environment alone cannot
fix that override. In stamped mode, `workspace_status_stamp.py` reads the
provided epoch and passes it through `STABLE_SOURCE_DATE_EPOCHS` to the kernel
environment. Legacy build.sh receives the same exported build timestamp.

Validate the result in the built artifact, rather than relying only on the
workflow's exported variables:

```bash
strings path/to/Image | grep -m1 'Linux version '
```

The `#1 SMP PREEMPT ...` time should correspond to the build instant in UTC,
and must not read 1970. Device `/proc/version` reflects the Image actually booted.
The timestamp change applies to both main and wsl; main's branding inputs and
branding action are unchanged.
