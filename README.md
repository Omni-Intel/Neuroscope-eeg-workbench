# NeuroScope 多设备脑电实验工作台

0.4.0 开发分支：独立桌面工程，无外部 oi-mi 或同级参考仓库运行依赖。

首次使用请阅读 [安装与实验报告使用指南](docs/自动评估使用说明.md)：从安装、设备连接到实验与报告查看，并按报告顺序解释指标含义及其分析代码来源。

支持 Neuracle、BrainCo（demo 的 BCIGo SDK 2.1.2）、公司 OmniBCI SDK、通用 LSL、EMOTIV/EmotivPRO 外部录制，以及原有模拟、NPZ 回放和 TD10。保留全部十个范式；自由选择被试、设备、范式，每次完整采集独立 UUID。

## 启动

Windows x64 / Python 3.12，先安装 uv，再在本目录运行：

```powershell
.\setup-workbench.ps1
.\start-neuroscope-desktop.bat
```

已有本地环境可直接双击 `启动-NeuroScope桌面控制台.bat`。公司预览 SDK 已复制到 `vendor_sdk/omnibci/`，wheel 不提交 Git；在另一台电脑部署时需一起复制该目录及许可证。未准备某家 SDK 时可安装时选择 `-SkipBrainCo` / `-SkipOmni`，其余设备仍可使用。

安装使用 `uv.lock` 和项目 `.venv`，不使用 conda 或旧 `.venv312`。新增规范与操作见 [规范实施与使用](docs/规范实施与使用.md)。

## 使用与数据

详见 [多设备工作台说明](docs/multi-device-workbench.md)：连接准备、一次实验的操作、EMOTIV 流程、原始文件结构、EEGQC 交付结构、对齐与校验要求。

- “快速演示”不创建正式记录；“完整采集”需要 8 位平台编号、已登记的范式代码和 unique_name。
- 保存根目录下分为三类：`Records/recording-<UUID>/` 保存原始记录与分析依据。
- 单段 EDF 交付：`data/<unique_name>/recording-<UUID>/`，实验封存后自动导出并尝试 BIDS 校验。
- Word 报告：`Reports/<unique_name>/recording-<UUID>/<生成版本>/`；分析 JSON、CSV、图片与校验状态保存在 Records。
- 缺少配置、事件对齐或 EMOTIV EDF 时显示待补充原因；报告和交付分别显示状态。重试不会覆盖已封存的交付包。
- 波形显示和分析不改写原始值。未知单位、丢样、未对齐外部事件不能被当作有效且同步的 EEG。
- 本地质量指标与 EEGQC 的最终评分、上传和入库分开；没有运行并通过官方 BIDS Validator 时不标记已验证。

设备配置示例：[profiles/device-profile.example.json](profiles/device-profile.example.json)。必须按实际硬件修改后再确认，示例不是任何品牌的默认电极布局。

命令行工具：

```powershell
.\.venv\Scripts\python.exe -m neuroscope_eeg.io.data_cli --help
.\.venv\Scripts\python.exe -m pytest --basetemp=.test-tmp
```

完整硬件验收需在实际设备上执行。已实现的接口不等于已通过真机测试。Neuracle/BrainCo 参考代码来源与哈希见 `neuroscope_eeg/acquisition/vendor/PROVENANCE.json`，保留原作者声明；EMOTIV 串口流程依据本地 visual-video-task-master。旧 Streamlit/Matplotlib 入口保留兼容用途，新流程使用桌面入口。

## 自动 Word 评估

SSVEP、运动想象现支持可调总试次、分组和阶段时长、熟悉流程、独立静息基线及组间休息及自动结束。
完整记录封存后自动在后台生成 Word + JSON/CSV，快速演示不保存报告，不生成 HTML。
详见 [自动评估使用说明](docs/自动评估使用说明.md)。原有十个范式与单试次内容保留。
