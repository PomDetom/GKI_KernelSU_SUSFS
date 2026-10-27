#!/usr/bin/env python3
"""Run the Android 16 / SukiSU build recipe locally, preserving source and cache.

The action adapter supports only the local composite actions used by build.yml;
it is deliberately not a general GitHub Actions runner. Cloud cleanup, cache
uploads, manager builds, publishing and release jobs are never executed.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

try:
    import yaml
except ImportError:
    raise SystemExit("Install dependencies first: bash scripts/install-wsl-deps.sh")

REPO = Path(__file__).resolve().parents[1]
EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}", re.S)


def string(value):
    return str(value).lower() if isinstance(value, bool) else str(value)


def expression(text, context):
    """Evaluate the small expression subset present in the checked-in actions."""
    if not isinstance(text, str):
        return text
    text = text.strip()
    if text.startswith("${{"):
        text = EXPR.fullmatch(text).group(1)
    text = text.replace("&&", " and ").replace("||", " or ")
    text = re.sub(r"!(?!=)", " not ", text).strip()
    text = re.sub(r"\bsteps\.([A-Za-z_][\w-]*)", r'steps["\1"]', text)

    def visit(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            literals = {"true": True, "false": False, "null": None}
            if node.id in literals:
                return literals[node.id]
            if node.id in context:
                return context[node.id]
            raise ValueError(f"Unsupported local context: {node.id}")
        if isinstance(node, ast.Attribute):
            parent = visit(node.value)
            return parent.get(node.attr, "") if isinstance(parent, dict) else ""
        if isinstance(node, ast.Subscript):
            parent = visit(node.value)
            return parent.get(visit(node.slice), "") if isinstance(parent, dict) else ""
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not visit(node.operand)
        if isinstance(node, ast.BoolOp):
            result = visit(node.values[0])
            for child in node.values[1:]:
                if isinstance(node.op, ast.And) and not result:
                    break
                if isinstance(node.op, ast.Or) and result:
                    break
                result = visit(child)
            return result
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = visit(node.left), visit(node.comparators[0])
            op = node.ops[0]
            if isinstance(op, ast.Eq):
                return left == right
            if isinstance(op, ast.NotEq):
                return left != right
            if isinstance(op, ast.LtE):
                return left <= right
            if isinstance(op, ast.GtE):
                return left >= right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            args = [visit(arg) for arg in node.args]
            if node.func.id == "contains":
                return args[1] in args[0]
            if node.func.id in ("always", "success") and not args:
                return True
        raise ValueError(f"Unsupported local action expression: {text}")

    return visit(ast.parse(text, mode="eval").body)


def render(value, context):
    if isinstance(value, str):
        return EXPR.sub(lambda m: string(expression(m.group(1), context)), value)
    return string(value)


def command(args, cwd=None, env=None, capture=False):
    return subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def read_exports(path):
    result = {}
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if "<<" in line and ("=" not in line or line.index("<<") < line.index("=")):
            key, delimiter = line.split("<<", 1)
            values = []
            i += 1
            while i < len(lines) and lines[i] != delimiter:
                values.append(lines[i])
                i += 1
            if i == len(lines):
                raise ValueError("Unterminated multiline action output")
            result[key] = "\n".join(values)
        elif "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
        i += 1
    return result


class LocalBuild:
    def __init__(self, args):
        self.args = args
        self.profile = json.loads(args.profile.read_text())
        self.inputs = dict(self.profile["inputs"])
        if self.inputs["version"] != "android16-6.12" or self.inputs["root_flavor"] != "sukisu-ultra":
            raise ValueError("This local profile supports Android 16 / 6.12 with SukiSU-Ultra only")
        if self.inputs["page_size"] not in ("4k", "16k"):
            raise ValueError("page_size must be 4k or 16k")
        if self.inputs.get("allow_version_mismatch"):
            raise ValueError("The local entry builds normal kernels; allow_version_mismatch must be false")
        if not re.fullmatch(r"[0-9a-f]{40}", self.profile["kernel_commit"]):
            raise ValueError("kernel_commit must be a full immutable SHA")
        self.brand_template = self.inputs["brand_name"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]*", self.brand_template.replace("{date}", "20000101")):
            raise ValueError("brand_name accepts letters, numbers, dots, underscores, hyphens and {date}")
        self.inputs["brand_name"] = self.brand_template.replace("{date}", datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"))
        for key, value in self.inputs.items():
            if key.endswith("_commit") and not re.fullmatch(r"[0-9a-f]{40}", value):
                raise ValueError(f"{key} must be a full immutable SHA")
        self.jobs = args.jobs or self.profile["jobs"]
        if self.jobs < 1:
            raise ValueError("jobs must be positive")
        self.workspace = args.workspace.resolve()
        if str(self.workspace).startswith("/mnt/") and args.command not in ("plan", "doctor"):
            raise ValueError("Use WSL's Linux filesystem for --workspace, e.g. ~/gki-work/default")
        self.cache = args.cache.resolve()
        self.state_file = self.workspace / "local-state.json"
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        identity = {k: v for k, v in self.profile.items() if k != "jobs"}
        self.signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        if self.state and self.state.get("profile_hash") != self.signature:
            raise ValueError("Profile changed. Use a different --workspace; the current source is retained.")
        self.exports = self.state.get("exports", {})
        self.env = dict(os.environ)
        self.env.update(self.exports)
        self.env.update(GITHUB_WORKSPACE=str(self.workspace), RUNNER_TEMP=str(self.workspace / "tmp"),
                        BAZEL_CACHE_DIR=str(self.cache / "bazel"), KERNEL_OUT_DIR=str(self.workspace / "out"),
                        KERNEL_BUILD_JOBS=str(self.jobs), KBUILD_BUILD_USER="kleaf", KBUILD_BUILD_HOST="build-host",
                        GIT_AUTHOR_NAME="Local GKI build", GIT_AUTHOR_EMAIL="gki-local@localhost",
                        GIT_COMMITTER_NAME="Local GKI build", GIT_COMMITTER_EMAIL="gki-local@localhost")
        self.env.update(WSL_BRAND_TEMPLATE=self.brand_template,
                        WSL_KEEP_KMI=string(self.inputs["keep_kmi"]),
                        WSL_BRANDING_SCRIPT=str(REPO / "scripts/wsl_branding.py"))
        self.env["PATH"] = str(self.workspace / "bin") + os.pathsep + str(Path.home() / ".local/bin") + os.pathsep + self.env["PATH"]
        self.steps = self.state.get("steps", {})
        self.workflow = yaml.safe_load((REPO / ".github/workflows/build.yml").read_text())["jobs"]["build-gki"]["steps"]

    def save(self, **updates):
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state.update(profile_hash=self.signature, exports=self.exports, steps=self.steps, **updates)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2) + "\n")
        temporary.replace(self.state_file)

    def context(self, inputs, action_path, steps):
        return {"inputs": inputs, "env": self.env, "steps": steps,
                "github": {"workspace": str(self.workspace), "action_path": str(action_path),
                           "repository": "PomDetom/GKI_KernelSU_SUSFS", "token": self.env.get("GH_TOKEN", "")}}

    def run_steps(self, steps, inputs, action_path=REPO, results=None, plan=False):
        results = {} if results is None else results
        for step in steps:
            context = self.context(inputs, action_path, results)
            if not expression(step.get("if", True), context):
                continue
            name = step.get("name", step.get("id", step.get("uses", "shell")))
            if "uses" in step:
                target = step["uses"]
                if not target.startswith("./.github/actions/"):
                    raise ValueError(f"External action is not part of the local recipe: {target}")
                directory = (REPO / target).resolve()
                action = yaml.safe_load((directory / "action.yml").read_text())
                child_inputs = {key: render(spec.get("default", ""), context) for key, spec in action.get("inputs", {}).items()}
                child_inputs.update({key: render(value, context) for key, value in step.get("with", {}).items()})
                child_steps = self.run_steps(action["runs"]["steps"], child_inputs, directory, plan=plan)
                child_context = self.context(child_inputs, directory, child_steps)
                outputs = {key: render(spec["value"], child_context) for key, spec in action.get("outputs", {}).items()}
            elif "run" in step:
                body = render(step["run"], context)
                # Isolate the one CI summary path shared across old action recipes.
                body = body.replace("/tmp/kernel-fixes-summary.md", str(self.workspace / "kernel-fixes-summary.md"))
                cwd = Path(render(step.get("working-directory", "${{ github.workspace }}"), context))
                print(f"{'PLAN' if plan else 'RUN'}: {action_path.name} / {name}", flush=True)
                if plan:
                    subprocess.run(["bash", "-n"], input=body, check=True, text=True)
                    outputs = {}
                else:
                    env = dict(self.env)
                    env.update({key: render(value, context) for key, value in step.get("env", {}).items()})
                    with tempfile.TemporaryDirectory(dir=self.workspace / "tmp") as temporary:
                        files = {key: Path(temporary) / key for key in ("GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH")}
                        for key, path in files.items():
                            path.touch()
                            env[key] = str(path)
                        log_dir = self.workspace / "logs"
                        log_dir.mkdir(exist_ok=True)
                        argv = ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", body]
                        with (log_dir / "actions.log").open("a") as log:
                            log.write(f"\nRUN: {action_path.name} / {name}\n")
                            with subprocess.Popen(argv, cwd=cwd, env=env, text=True,
                                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
                                for line in process.stdout:
                                    print(line, end="", flush=True)
                                    log.write(line)
                                if process.wait():
                                    raise subprocess.CalledProcessError(process.returncode, argv)
                        changes = read_exports(files["GITHUB_ENV"])
                        self.exports.update(changes)
                        self.env.update(changes)
                        paths = files["GITHUB_PATH"].read_text().splitlines()
                        if paths:
                            self.env["PATH"] = os.pathsep.join(paths + [self.env["PATH"]])
                        outputs = read_exports(files["GITHUB_OUTPUT"])
            else:
                raise ValueError(f"Unsupported local step: {name}")
            if step.get("id"):
                results[step["id"]] = {"outputs": outputs}
        return results

    def recipe(self):
        names = [step.get("name") for step in self.workflow]
        return self.workflow[names.index("Spoof /proc/config.gz With Stock Config"):names.index("Clean Kernel Flags") + 1]

    def plan(self):
        print(f"Workspace: {self.workspace}\nCache: {self.cache}\nJobs: {self.jobs}")
        print("Stages: sync -> prepare -> build -> package; source and caches are retained")
        results = {"extract": {"outputs": {"sublevel": self.inputs["sublevel"], "file_name": "local-kernel"}},
                   "susfs-cm": {"outputs": {"commit": self.inputs["susfs_commit"]}}}
        # Future outputs are seeded only for syntax validation; plan never executes a recipe.
        for step in self.recipe():
            previous = json.loads(json.dumps(results))
            self.run_steps([step], self.inputs, results=results, plan=True)
            results.update(previous)
        self.run_steps([{"uses": "./.github/actions/build-kernel", "with": {"version": self.inputs["version"], "page_size": self.inputs["page_size"]}}], self.inputs, plan=True)

    def doctor(self):
        missing = [name for name in ("git", "curl", "make", "gcc", "clang", "ld.lld", "bc", "bison", "flex", "patch", "rsync", "zip", "unzip", "cpio", "xz", "lz4", "zstd", "jq", "ccache", "pahole") if not shutil.which(name)]
        print(f"Linux: {sys.platform}; CPUs: {os.cpu_count()}; parallel jobs: {self.jobs}")
        command(["free", "-h"])
        command(["df", "-h", str(REPO)])
        if missing:
            raise ValueError("Missing dependencies: " + ", ".join(missing) + ". Run bash scripts/install-wsl-deps.sh")
        print("Doctor passed. repo and kernel toolchains are downloaded by sync, not installed globally.")

    def checkout(self, name, url, sha):
        target = self.workspace / name
        if not (target / ".git").exists():
            target.mkdir(parents=True, exist_ok=True)
            command(["git", "init", str(target)])
            command(["git", "-C", str(target), "remote", "add", "origin", url])
        current = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True)
        if current.returncode == 0:
            if current.stdout.strip() != sha:
                raise ValueError(f"Existing {name} has another commit; use a new workspace")
            return
        command(["git", "-C", str(target), "fetch", "--depth=1", "origin", sha], env=self.env)
        command(["git", "-C", str(target), "checkout", "--detach", "FETCH_HEAD"], env=self.env)

    def sync(self):
        if self.state.get("synced"):
            print("Already synced; retaining source, patches and build outputs.")
            return
        for directory in (self.workspace / "tmp", self.workspace / "kernel", self.cache):
            directory.mkdir(parents=True, exist_ok=True)
        link = self.workspace / ".github"
        if not link.exists():
            link.symlink_to(REPO / ".github", target_is_directory=True)
        tool = self.workspace / "bin/repo"
        tool.parent.mkdir(exist_ok=True)
        if not tool.exists():
            command(["curl", "--fail", "--location", "--retry", "3", "https://storage.googleapis.com/git-repo-downloads/repo", "--output", str(tool)])
            tool.chmod(0o755)
        env = dict(self.env)
        for i, (key, value) in enumerate((("http.lowSpeedLimit", "1024"), ("http.lowSpeedTime", "60"), ("user.name", "Local GKI build"), ("user.email", "gki-local@localhost"))):
            env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = key, value
        env["GIT_CONFIG_COUNT"] = "4"
        kernel = self.workspace / "kernel"
        command([str(tool), "init", "-u", "https://android.googlesource.com/kernel/manifest", "-b", self.profile["manifest_branch"], "--depth=1"], cwd=kernel, env=env)
        local = kernel / ".repo/local_manifests"
        local.mkdir(exist_ok=True)
        (local / "local-gki.xml").write_text('<manifest><extend-project name="kernel/common" revision="' + self.profile["kernel_commit"] + '" /></manifest>\n')
        command([str(tool), "sync", "-c", "--no-clone-bundle", "--no-tags", f"-j{self.jobs}"], cwd=kernel, env=env)
        actual = command(["git", "-C", str(kernel / "common"), "rev-parse", "HEAD"], capture=True).strip()
        if actual != self.profile["kernel_commit"]:
            raise ValueError("Kernel SHA mismatch after sync")
        for name, url, key in (("kernel_patches", "https://github.com/WildKernels/kernel_patches.git", "kernel_patches_commit"), ("AnyKernel3", "https://github.com/WildKernels/AnyKernel3.git", "anykernel3_commit")):
            self.checkout(name, url, self.inputs[key])
        manifest = command([str(tool), "manifest", "-r"], cwd=kernel, env=env, capture=True)
        (self.workspace / "manifest.lock.xml").write_text(manifest)
        self.exports["KERNEL_SOURCE_COMMIT"] = actual
        self.env["KERNEL_SOURCE_COMMIT"] = actual
        self.save(synced=True)

    def prepare(self):
        if not self.state.get("synced"):
            raise ValueError("Run sync first")
        if self.state.get("prepared"):
            print("Already prepared; not applying patches again. Use build to recompile edits.")
            return
        if self.state.get("prepare_started") and not self.args.resume_prepare:
            raise ValueError("Preparation was interrupted. Inspect/fix the failed step, then use --resume-prepare, or choose a new --workspace. No source is deleted automatically.")
        self.save(prepare_started=True)
        completed = self.state.get("completed_prepare", [])
        for index, step in enumerate(self.recipe()):
            if index in completed:
                continue
            self.save(current_step=step.get("name", "unnamed"))
            self.run_steps([step], self.inputs, results=self.steps)
            completed.append(index)
            self.save(completed_prepare=completed)
        self.run_steps([{"uses": "./.github/actions/scan-patch-rejects"}], self.inputs)
        if int(self.exports.get("REJ_COUNT", "0")):
            raise ValueError("Patch rejects found; inspect patch-rejects before building")
        (self.workspace / "wild_gki.fragment").touch()
        self.save(prepared=True, current_step="prepared")

    def build(self):
        if not self.state.get("prepared"):
            raise ValueError("Run prepare first")
        self.save(built=False)
        self.run_steps([{"uses": "./.github/actions/build-kernel", "with": {"version": self.inputs["version"], "page_size": self.inputs["page_size"]}}], self.inputs)
        self.save(built=True)

    def package(self):
        if not self.state.get("built"):
            raise ValueError("A successful build is required before packaging")
        anykernel = self.workspace / "AnyKernel3"
        if not (anykernel / "Image").is_file():
            raise ValueError("AnyKernel3/Image missing")
        output = self.workspace / "dist"
        output.mkdir(exist_ok=True)
        filename = self.exports["FILE_NAME"]
        artifact = output / (filename + "-AnyKernel3.zip")
        with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(anykernel.rglob("*")):
                relative = path.relative_to(anykernel)
                if ".git" not in relative.parts and path.is_file():
                    archive.write(path, str(relative))
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        (output / (artifact.name + ".sha256")).write_text(digest + "  " + artifact.name + "\n")
        metadata = {"profile": self.profile, "kernel_source_commit": self.exports["KERNEL_SOURCE_COMMIT"],
                    "components": {key: value for key, value in self.exports.items() if key.endswith("_COMMIT")},
                    "build_metadata": {key: self.exports[key] for key in ("SOURCE_DATE_EPOCH", "KBUILD_BUILD_TIMESTAMP", "BUILD_DATE", "EXPECTED_KERNEL_RELEASE") if key in self.exports},
                    "recipe_commit": command(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture=True).strip(),
                    "sha256": digest, "status": "Build-verified only", "device_boot": "not-validated"}
        (output / (filename + "-metadata.json")).write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"Artifact: {artifact}\nSHA256: {digest}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "plan", "sync", "prepare", "build", "package", "all"))
    parser.add_argument("--profile", type=Path, default=REPO / "profiles/wsl-android16-6.12.json")
    parser.add_argument("--workspace", type=Path, default=REPO / ".local-build/android16-6.12")
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache/gki-kernels")
    parser.add_argument("--jobs", type=int)
    parser.add_argument("--resume-prepare", action="store_true", help="Retry a failed preparation step after inspecting its partial changes")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Run inside Linux / WSL2")
    try:
        build = LocalBuild(args)
        if args.command == "all":
            build.doctor()
            for stage in ("sync", "prepare", "build", "package"):
                getattr(build, stage)()
        else:
            getattr(build, args.command)()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
