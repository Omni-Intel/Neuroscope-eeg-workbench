# BCIGo SDK 1.0.2 迁移设计

## 目标

将 NeuroScope 的 BrainCo 真机接入从已弃用的 `bc-ecap-sdk` 0.5.x 迁移到
`bcigo-sdk` 1.0.2。迁移后不再支持旧 SDK；模拟、NPZ 回放和博睿康 Neuracle
数据源的接口与行为不变。

迁移必须让仓库自身包含可运行的 BrainCo 适配器。当前 `realtime_eeg_viewer.py`
通过 `--oi-mi-path` 导入另一工作区的 `acquisition.brainco_acquirer`，该适配器
硬编码旧 SDK，不能作为新版交付的一部分。

## 范围与约束

- 依赖升级为 `bcigo-sdk==1.0.2`，导入名为 `bcigo_sdk`。
- 仅支持 Python 3.12 的 Windows x86-64 与 Linux 发行版。SDK 当前没有 macOS
  wheel；macOS 上继续支持模拟与回放，但 BrainCo 连接显示清晰的安装限制。
- 保持 BrainCo 32 通道官方顺序、250/500/1000/2000 Hz、增益
  1/2/4/6/8/12/24、自动发现和手工地址端口。
- 不修改任何非 BrainCo 的采集、实时缓冲、预处理、范式或解码行为。
- 不将设备固件、厂商软件或个人数据写入仓库。

## API 映射

| 旧接口 | 新接口 | 采用方式 |
| --- | --- | --- |
| `import bc_ecap_sdk` | `import bcigo_sdk` | 只保留新包 |
| `ECapClient` | `BCIGoClient` | 新客户端 |
| `MsgType.EEGCap` | `MsgType.BCIGo` | 新协议解析器 |
| `start_data_stream` + `set_eeg_config` + `start_eeg_stream` | `start_stream` | 常规采集使用新版统一启动 |
| `stop_eeg_stream` + `disconnect_tcp_blocking` | `disconnect_tcp_blocking` | 统一安全关闭 |
| 低层 lead-off 调用 | `enable_impedance_detection_mode` / `disable_impedance_detection_mode` | 高层阻抗模式切换 |

统一启动仍注册接收、消息响应和阻抗回调，并从 SDK EEG 缓冲取出新增数据；这样
可以继续提供数据新鲜度、启动超时和清晰的设备/协议错误提示。启动失败时按现有
重试次数重连，任何失败均断开 SDK 后再重试。

## 结构

新增 `neuroscope_eeg/acquisition/brainco.py`，作为唯一的 SDK 边界：

- `BrainCoAcquirer`：管理异步 SDK 客户端、后台事件循环、发现、启动、关闭、
  样本缓冲和阻抗模式；向上只暴露 `start_stream()`、`stop_stream()` 和
  `get_new_samples()`。
- `BrainCoSource`：从旧兼容入口迁入或替换为本仓库适配器，不再接受
  `oi_mi_path`。
- `legacy.py`：保留模块名以保护 UI 调用点，但直接构建新的本地 BrainCo 源。
- `realtime_eeg_viewer.py`：移除 `--oi-mi-path` 参数和动态 `sys.path` 注入，
  保留 `--brainco-*` 连接参数。

SDK 未安装、当前平台无可用 wheel、找不到设备、没有收到 EEG 样本或协议设置
不匹配时，均在连接阶段给出可操作错误；不回退到旧 SDK，也不伪造数据。

## 配置、阻抗与数据

常规采集使用 `BCIGoClient.start_stream(parser, fs, gain, signal)`；配置值转换为
新版枚举。自动发现优先使用 SDK 的 mDNS 结果，保留对回调式 mDNS 结果和手工
IP/端口的解析。取样继续从 SDK 缓冲读取并归一化为通道优先 `float32` 数组。

阻抗检查先切换到 `enable_impedance_detection_mode()`，在限定时间内收集回调，
再调用 `disable_impedance_detection_mode()` 恢复 EEG。由于厂商未在公开类型存根
中定义阻抗回调载荷结构，保留保守解析及“未知格式”的明确提示，而不捏造单位或
接触质量。

## 依赖、诊断和文档

- `pyproject.toml` 的 `brainco` 可选组、`requirements-brainco.txt`、README
  和诊断命令统一使用 `bcigo-sdk==1.0.2` / `bcigo_sdk`。
- README 的 Windows 真机安装与 CLI 示例不再引用 `oi-mi`。
- 环境诊断报告检测 `bcigo_sdk`，同时给出当前系统和“SDK 当前不提供 macOS
  wheel”的说明。

## 验证

- 单元测试使用假 `bcigo_sdk` 模块，覆盖导入、`BCIGoClient`、`MsgType.BCIGo`、
  枚举配置、统一启动、安全停止、样本归一化和缺包错误。
- 保留现有 32 通道布局及 BrainCo 显示预处理测试；运行完整 `pytest` 与 `ruff`。
- 在 Windows 采集电脑用 SDK 1.0.2 做真机验收：自动发现、手工 IP/端口、数据
  连续更新、退出后进程不残留，以及阻抗模式能够回到正常采集。

本开发机是 macOS，无法安装 SDK 的 Windows/Linux 原生 wheel；因此本地验证
覆盖接口契约和所有非硬件路径，真机连接必须在 Windows 采集电脑完成。
