#!/usr/bin/env python3
"""Compile the repaired API forms on both sides of the probed interfaces."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from fix_sukisu_compat import fix_sources

NET = '''
struct netlink_kernel_cfg {
    unsigned groups, flags;
    void (*input)(void);
    CB_FIELD
    void (*bind)(void);
    void (*unbind)(void);
};
'''
SUPER = '''
struct DynamicStructMember { const char *name; unsigned long size, offset; };
struct DynamicStructInfo { const char *name; unsigned long count, total_size; struct DynamicStructMember *members; };
#define offsetof(type, member) __builtin_offsetof(type, member)
#define DYNAMIC_STRUCT_BEGIN(n) static struct DynamicStructMember n##_members[] = {
#define DEFINE_MEMBER(n, m) { #m, sizeof(((struct n *)0)->m), offsetof(struct n, m) },
#define DYNAMIC_STRUCT_END(n) }; static struct DynamicStructInfo n##_info = { #n, sizeof(n##_members)/sizeof(struct DynamicStructMember), sizeof(struct n), n##_members };
DYNAMIC_STRUCT_BEGIN(netlink_kernel_cfg)
DEFINE_MEMBER(netlink_kernel_cfg, groups)
DEFINE_MEMBER(netlink_kernel_cfg, flags)
DEFINE_MEMBER(netlink_kernel_cfg, input)
DEFINE_MEMBER(netlink_kernel_cfg, cb_mutex)
DEFINE_MEMBER(netlink_kernel_cfg, bind)
DEFINE_MEMBER(netlink_kernel_cfg, unbind)
DYNAMIC_STRUCT_END(netlink_kernel_cfg)
int verify_members(void) { return netlink_kernel_cfg_info.count; }
'''
THRONE = '''
struct my_dir_context { int depth; };
struct pos { int depth; };
int manager_depth(struct pos *pos) {
    struct my_dir_context ctx = { .depth = pos->depth }
    return ctx.depth;
}
'''
HOOK = '''
#define __init
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
static struct security_hook_list ksu_hooks[1];
void __init ksu_lsm_hook_init(void)
{
    security_add_hooks(ksu_hooks, ARRAY_SIZE(ksu_hooks), "ksu");
}
'''


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.common, self.root = self.directory / "common", self.directory / "root"
        (self.common / "include/linux").mkdir(parents=True)
        for name, content in (("extension/kpm/super_access.c", SUPER), ("manager/throne_tracker.c", THRONE), ("hook/lsm_hook.c", HOOK)):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def setup_headers(self, cb_mutex, lsm_id):
        net = NET.replace("CB_FIELD", "void *cb_mutex;" if cb_mutex else "")
        lsm = "struct security_hook_list { int hook; };\n"
        if lsm_id:
            lsm += '#define LSM_ID_UNDEF 0\nstruct lsm_id { const char *name; unsigned long long id; };\n'
            lsm += "void security_add_hooks(struct security_hook_list *, int, const struct lsm_id *);\n"
        else:
            lsm += "void security_add_hooks(struct security_hook_list *, int, const char *);\n"
        (self.common / "include/linux/netlink.h").write_text(net)
        (self.common / "include/linux/lsm_hooks.h").write_text(lsm)
        return net, lsm

    def compile(self, name, text, success=True):
        path = self.directory / name
        path.write_text(text)
        result = subprocess.run([os.environ.get("CC", "clang"), "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-fsyntax-only", str(path)], capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result.stderr

    def test_current_kernel_and_idempotence(self):
        net, lsm = self.setup_headers(False, True)
        self.assertIn("cb_mutex", self.compile("bad-net.c", net + SUPER, False))
        self.assertIn("expected ';'", self.compile("bad-throne.c", THRONE, False))
        self.assertIn("incompatible", self.compile("bad-lsm.c", lsm + HOOK, False))
        changed = fix_sources(self.common, self.root)
        self.assertEqual(len(changed), 3)
        self.compile("fixed-net.c", net + (self.root / "extension/kpm/super_access.c").read_text())
        self.compile("fixed-throne.c", (self.root / "manager/throne_tracker.c").read_text())
        self.compile("fixed-lsm.c", lsm + (self.root / "hook/lsm_hook.c").read_text())
        self.assertEqual(fix_sources(self.common, self.root), [])

    def test_legacy_kernel_keeps_real_field_and_string_api(self):
        net, lsm = self.setup_headers(True, False)
        self.assertEqual(fix_sources(self.common, self.root), ["manager/throne_tracker.c"])
        self.compile("legacy-net.c", net + (self.root / "extension/kpm/super_access.c").read_text())
        self.compile("legacy-lsm.c", lsm + (self.root / "hook/lsm_hook.c").read_text())

    def test_mixed_backported_interfaces(self):
        net, lsm = self.setup_headers(True, True)
        fix_sources(self.common, self.root)
        self.assertIn("DEFINE_MEMBER(netlink_kernel_cfg, cb_mutex)", (self.root / "extension/kpm/super_access.c").read_text())
        self.compile("backport-net.c", net + (self.root / "extension/kpm/super_access.c").read_text())
        self.compile("backport-lsm.c", lsm + (self.root / "hook/lsm_hook.c").read_text())

    def test_unknown_manager_layout_does_not_half_modify_sources(self):
        self.setup_headers(False, True)
        (self.root / "manager/throne_tracker.c").write_text("unknown source layout\n")
        with self.assertRaises(ValueError):
            fix_sources(self.common, self.root)
        self.assertEqual((self.root / "extension/kpm/super_access.c").read_text(), SUPER)


if __name__ == "__main__":
    unittest.main()
