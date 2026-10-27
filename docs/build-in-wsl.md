# 在 WSL2 中构建

本地入口复用仓库现有的复合 action 和补丁顺序，默认配置对应 Android 16 / 6.12.69、2026-03、SukiSU-Ultra、4k 页大小，以及原构建选择的 SUSFS、NoMount、BBG、NET、DroidSpaces、NTSync、Ptrace、Unicode、BPF。

当前本地入口只支持 Android 16 / 6.12 + SukiSU-Ultra。不会执行云端清理、上传缓存、下载管理器、发布或通知作业。GitHub 云端构建仍按原流程执行。

本地适配只解释这条构建链使用的表达式和本仓库的 composite actions，不支持第三方 action 或任意 GitHub 工作流。上游 recipe 增加本地不支持的表达式时，入口会报告具体位置，不会默默跳过。

## 本机配置

在 Windows 的 `%UserProfile%\.wslconfig` 的 `[wsl2]` 下配置：

```ini
memory=8GB
swap=8GB
```

保留文件中其他配置。关闭 WSL 内正在运行的任务后执行 `wsl --shutdown`，再进入 Ubuntu。对 16GB 物理内存的电脑，默认先用 4 路并行；可用 `--jobs 2` 降低占用。

仓库、源码和缓存放在 WSL 自己的文件系统，避免使用 `/mnt/c` 作为构建目录：

```bash
mkdir -p ~/gki-build
git clone --branch wsl https://github.com/PomDetom/GKI_KernelSU_SUSFS.git ~/gki-build/GKI_KernelSU_SUSFS
cd ~/gki-build/GKI_KernelSU_SUSFS
bash scripts/install-wsl-deps.sh
scripts/wsl-build doctor
scripts/wsl-build plan
```

依赖安装需要 sudo；实际构建用普通用户执行。`plan` 只展开本地支持的 action 并检查 shell 语法，不下载内核或打补丁。

## 首次构建与重复编译

```bash
# 首次：同步源码、应用补丁、构建、打包
scripts/wsl-build all

# 或分别运行，便于检查每个阶段
scripts/wsl-build sync
scripts/wsl-build prepare
scripts/wsl-build build
scripts/wsl-build package

# 已准备好源码后，修改代码再编译；不会重新同步或重复打补丁
scripts/wsl-build build --jobs 4
scripts/wsl-build package
```

默认位置：

| 内容 | 位置 |
| --- | --- |
| 源码、外部依赖、阶段状态 | `.local-build/android16-6.12/` |
| 内核源码 | `.local-build/android16-6.12/kernel/common/` |
| Bazel 磁盘缓存 | `~/.cache/gki-kernels/bazel/` |
| ZIP、SHA256 和版本信息 | `.local-build/android16-6.12/dist/` |
| 同步完成时的完整 manifest | `.local-build/android16-6.12/manifest.lock.xml` |
| 准备失败时的步骤 | `.local-build/android16-6.12/local-state.json` |
| 各 action 的本地日志 | `.local-build/android16-6.12/logs/actions.log` |

可以从 Windows 资源管理器访问 `\\wsl.localhost\Ubuntu\home\PomDetom\gki-build\GKI_KernelSU_SUSFS`。

`sync` 下载 repo、源码和 Google manifest 指定的工具链；内核 common 固定为配置中的提交，避免上游分支移动导致补丁漂移。失败后再次运行 sync 会复用已下载内容，不清空源码。其他依赖使用 profile 中的精确提交；BBG 和官方 stock config 的下载方式仍沿用原 action，可能随上游变化。`manifest.lock.xml` 记录实际同步版本，不代表所有第三方下载均已固定。

`prepare` 成功后再次运行会跳过打补丁。失败或中断后不会自动重打：先查看 `local-state.json` 和部分修改，修好失败步骤的现场后使用 `prepare --resume-prepare`，从失败的顶层 action 重试；该 action 内已成功的子步骤可能需要手工还原。也可以用新的 `--workspace` 重新准备，原现场和缓存保留。

构建失败不会清除源码、Bazel 输出或缓存，也不会允许将旧 Image 当作本次成功结果打包。修复源码后再次运行 build 即可。构建阶段沿用 `--config=fast`，并同时通过 `--jobs` 和 Kleaf 的 `--make_jobs` 限制并行度。

## 自定义配置

默认配置为 `profiles/wsl-android16-6.12.json`。可以复制该文件，调整功能组合、页大小或品牌文字，然后：

```bash
scripts/wsl-build all --profile /path/to/profile.json --workspace ~/gki-work/another-build
```

每次对同一 workspace 使用同一个 profile。更改功能、版本或提交后选择新 workspace；`--jobs` 和 `--cache` 可以单独改变。原工作目录不被自动删除。

本地入口当前只构建正常内核，不执行强制绕过模块版本校验；`allow_version_mismatch` 必须保持 false。

本地入口无需 GitHub token 即可访问公开依赖。如果网络限流，需要自行通过环境注入已有凭据；不要把凭据写进 profile、脚本或提交中。

## 验证边界

`doctor` 和 `plan` 分别检查本机依赖、实际采用的 action 及其 shell 语法。开发时的本地测试还覆盖嵌套 action、条件、环境和输出传递、三处 SUSFS rollup 修复、重复构建的配置修改，以及打包状态限制。

完整内核编译成功后，才会输出 `Build-verified only` 的元信息。它不代表已验证设备兼容性或开机；这些需要设备验收。首次下载量和时间取决于 Google 源码、工具链与本地网络，首次构建不承诺比云端更快。

## 构建时间与定制后缀

默认 WSL profile 的 `brand_name` 为 `pandora-sukisu{date}-pomdetom`。
`{date}` 在每次实际编译时按 Asia/Shanghai 的当天日期展开，准备源码的日期
不会固定后续增量构建的后缀。例如 2026-10-27 的结果为：

```text
6.12.69-android16-6-pandora-sukisu20261027-pomdetom
```

`keep_kmi=true` 保留源码中的 KMI_GENERATION=6。构建阶段会覆盖旧品牌输出，
重复编译不会追加重复后缀。内核源码版本、4K 页大小及功能组合保持原配置。
这一默认定制只在 wsl 分支的本地入口使用，main 不加入该后缀。

Bazel 同时启用 `--config=fast --config=stamp`。时间戳采用实际编译时刻，
内核显示 UTC 时间；品牌日期采用北京时间。ZIP 配套 metadata JSON 会记录
本次时间戳、品牌日期和预期 release。详见 [构建时间戳](build-metadata.md)。
