# OmniBCI Python 0.2.0 部署

NeuroScope 使用正式发布的 Windows x64 Python wheel：

- [发布页](https://github.com/Omni-Intel/omnibci-python/releases/tag/v0.2.0)
- [下载 omnibci-0.2.0-cp311-abi3-win_amd64.whl](https://github.com/Omni-Intel/omnibci-python/releases/download/v0.2.0/omnibci-0.2.0-cp311-abi3-win_amd64.whl)
- SHA256：`13e32f6063503eb44d6d5517808bc0d718fd83bae0e6376c6ec5ee69b80d2bdf`

把 wheel 放在本目录，不用解压。wheel 不随 Git 分发，复制部署目录时需同时携带 `LICENSE`、`SHA256SUMS.txt` 和 `BUILD-INFO.txt`。本项目使用 Python 3.12，该 cp311-abi3 包兼容此环境。

在仓库根目录运行 `setup-workbench.ps1`，安装脚本会校验 wheel 并按 `uv.lock` 同步依赖。可用以下命令检查版本：

```powershell
.\.venv\Scripts\python.exe -c "import omnibci; print(omnibci.__version__, omnibci.SDK_VERSION, omnibci.SDK_REVISION)"
```

Python 包版本应为 `0.2.0`，不再使用 `0.2.0.dev0`。Python 包版本与底层 SDK 版本分别记录，不根据文件名推断底层版本。

## 设备使用

1. 在实验准备页选择“公司 OmniBCI”，选择 ESP32（8 通道）或 STM32（32 通道）。
2. 选择串口或 BLE 后点击“扫描公司设备”，选取候选地址；也可直接填写 SDK 地址，例如 `serial://COM5`。
3. 点击“连接并检查数据”。扫描到候选不等于连接成功，以实际收到样本和界面状态为准。
4. 前端配置必须已验证，且处于 `eeg`、`both_bias` 或 `no_bias` 模式；拒绝 `test`、`shorted` 和未知模式。连接失败不切换模拟源。

扫描使用 SDK 的 `Board.discover`，连接与读数使用 `Board.connect/start/read`。串口扫描列出候选串口，不验证板卡身份；BLE 使用 SDK 设备发现。

阻抗入口使用 `Board.measure_impedance()`，支持 ESP32 与 STM32。测量与 EEG 采集互斥，测量结束保持停止，正式采集需重新启动。读到阻抗数值不等于已完成硬件精度标定。

版本、接口及离线回归验证不等于实机验收；USB/BLE 连通、实际固件、连续收样和阻抗仍需在对应板卡上确认。
