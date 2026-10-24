# lfs-archive-guard 中文说明

发布 ZIP 中的资源可能仍然是 Git LFS 指针，也可能装入了错误版本。本工具先读取
Git 提交树里的指针，生成路径、大小和 SHA-256 清单，再逐项核验实际 ZIP，整个过程
离线进行，不解压、不下载资源、不修改仓库。

需要 Python 3.11 以上。生成清单还需要维护中的 Git（建议 2.46 以上）；核验不需要
Git LFS。克隆仓库后创建虚拟环境，用该环境的 Python 执行 `python -m pip install .`。

```sh
lfs-archive-guard manifest --repo /path/to/project --ref HEAD --output lfs-manifest.json
lfs-archive-guard verify lfs-manifest.json release.zip --json
```

GitHub 下载的 ZIP 通常带一层目录，使用 `--strip-components 1` 显式移除。
`python examples/demo.py .demo` 可运行完整的合成示例，含正常资源和未还原指针两种结果。

退出码：`0` 全部通过；`1` 完成检查但发现问题；`2` 输入错误、资源限额或检查未完成。
默认限制为 50,000 个条目、压缩包 512 MiB、声明解压总量 2 GiB，显示最多 200 条问题；
截断报告仍然失败。只支持 ZIP 和标准 v1 SHA-256 指针，不支持 LFS 扩展变换。
ZIP 目录元数据会进入内存，工具不是操作系统级资源沙箱。

清单来自所指定的可信 Git 树；它不提供签名认证，也不检查任意构建输出。
报告会显示文件名、大小和哈希；普通额外文件不进行完整性验证。通过不代表整个 ZIP
安全或可运行。完整安装、边界、测试及限制见 [英文 README](README.md)。

卸载：`python -m pip uninstall lfs-archive-guard`，再按需删除独立虚拟环境、`.demo` 和
生成的清单。工具不安装服务、不写 Git 全局配置、不保存凭据。代码与原创测试数据采用 MIT。
