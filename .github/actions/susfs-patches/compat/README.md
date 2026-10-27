# Android 16 / 6.12 SUSFS rollup compatibility

This patch is selected only for this verified source pair:

- GKI common: `68067f2dc973fef7f359efc0fd07e37a97a1d099`
- SUSFS: `9c9f19d8395693327c78df36569b44e94c187b8a`

Other source pairs continue to use their fetched upstream SUSFS patch.

## Failure and change

[Run 40432720384](https://github.com/PomDetom/GKI_KernelSU_SUSFS/actions/runs/40432720384/job/121954278405) rejected task_mmu.c hunks 5 and 6 before compilation. The upstream patch expects `out_unlock`, a centralized rollup branch, and `smap_gather_stats(priv, vma, &mss)`. This GKI instead uses the do/for_each_vma loop and `smap_gather_stats(vma, &mss, start)`.

The adaptation filters SUS_MAP inodes at all three rollup statistics calls: the initial pass, the full VMA after reacquiring the lock, and the extended tail after reacquiring the lock. It retains the original cursor updates, lock handling, and range arguments. Filtering only the first call would miss the other two paths.

Only the task_mmu.c section of the full upstream patch is replaced. The other 23 file sections are byte-for-byte unchanged. This file replaces the upstream patch for this pair; do not apply both full patches to the same tree.

## Verification

- Applying the original task_mmu.c section to this GKI reproduces both rejected hunks. The resulting source and .rej match the failed run's files byte for byte.
- The adapted full patch passes GNU patch `--fuzz=0 --dry-run -p1` and actual application against all 24 affected files fetched at the exact GKI commit, without rejects.
- Applying a separate three-call repair to the partially patched source yields exactly the same task_mmu.c.
- Static checks retain all three cursor assignments and statistics calls. With CONFIG_KSU_SUSFS_SUS_MAP disabled, the rollup code is unchanged apart from whitespace.

These checks establish patch applicability. Full kernel compilation, linking, boot, and concurrent mmap/munmap/mremap runtime behavior remain to be verified by a new build and device testing.

## Sources and license

- [Original SUSFS patch](https://gitlab.com/simonpunk/susfs4ksu/-/blob/9c9f19d8395693327c78df36569b44e94c187b8a/kernel_patches/50_add_susfs_in_gki-android16-6.12.patch), simonpunk/susfs4ksu (GPL-3.0+, as recorded in THIRD_PARTY_NOTICES.md).
- [Exact GKI task_mmu.c](https://android.googlesource.com/kernel/common/+/68067f2dc973fef7f359efc0fd07e37a97a1d099/fs/proc/task_mmu.c), kernel/common (GPL-2.0).

To use a workflow fix, start a new **Run workflow** on the updated main branch. Re-running all jobs or failed jobs in the old run uses its original workflow SHA and does not pick up the fix.
