# OmniBCI Python SDK 预览版（非正式发布）

这是一个**开发预览 wheel**，不是 GitHub Release，也不会出现在 PyPI 或项目的 Releases 页面。
它从当前 `master` 构建，包含阻抗检测功能，供合作方提前联调/试用。

## 构建信息

| 项目 | 值 |
| --- | --- |
| Python 包版本 | `0.2.0.dev0` |
| 平台 | Windows x86_64 |
| Python | 3.11 及以上（abi3 wheel，3.11–3.14 通用） |
| omnibci-python 提交 | `0b8c342`（`master`，另含预览版本号提交） |
| SDK 子模块提交 | `843013b`（omnibci-sdk 0.3.0 线） |
| 构建日期 | 2026-10-26 |
| 是否 GitHub Release | **否** |

## 安装

建议在独立虚拟环境中安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install .\omnibci-0.2.0.dev0-cp311-abi3-win_amd64.whl
```

验证：

```powershell
.\.venv\Scripts\python.exe -c "import omnibci; print(omnibci.__version__, omnibci.SDK_VERSION, omnibci.SDK_REVISION)"
```

应输出类似：

```text
0.2.0.dev0 0.2.0 843013ba62f1f05098c8639a657585720ce66a72
```

## 阻抗检测用法

```python
from omnibci import Board

with Board.connect("serial://COM5") as board:
    result = board.measure_impedance()  # 默认测量全部已启用通道
    for channel, value in enumerate(result.values_kohm, start=1):
        print(channel, "invalid" if value is None else f"{value:.2f} kOhm")
    print("clipped mask:", hex(result.clipped_mask))
    # 测量结束后板子保持停止；继续 EEG 采集必须显式调用：
    # board.start()
```

也可以直接运行随附示例：

```powershell
.\.venv\Scripts\python.exe .\example_impedance.py serial://COM5 --mask 0xFF
```

参数：

- `mask`：8 位通道掩码，`bit 0` 对应 CH1；省略时使用全部已启用通道。
- `series_kohm`：串联补偿电阻；省略时 SRB1 用 9.98 kΩ、SRB2 用 4.40 kΩ。
- `window_seconds`：阻抗窗口时长，默认 4 秒。
- `timeout`：采集窗口的总超时，默认 15 秒。

## 重要说明

- 阻抗测量与 EEG 波形采集**互斥**：测量前会先停止采集，测量结束后保持停止，不会自动恢复 EEG。
- 测量要求已确认的 EEG 模式配置（`both_bias` / `eeg` / `no_bias`）和至少一个已启用通道。
- 阻抗值是按 ADS1299 ±6 nA、31.25 Hz LOFF 载波计算的名义值；正式精度验收前应使用已知电阻在目标板上标定。
- 本预览版只做了离线/模拟测试（172 个 Python 测试通过），**未做本次实机硬件验证**。
- 这是开发快照：后续功能会继续进入 `master`，正式版本发布后可以直接用正式 wheel 覆盖安装。
- 不要把该 wheel 上传到 PyPI 或当作正式发布物；如需对外发布，请走项目的 tag/Release 流程。

## 校验

```powershell
certutil -hashfile .\omnibci-0.2.0.dev0-cp311-abi3-win_amd64.whl SHA256
```

对比 `SHA256SUMS.txt`。如果校验值不一致，请不要安装。

## 许可

本项目采用 BSD-3-Clause 许可证，随附 `LICENSE`。转发 wheel 时请保留该许可证文件。
