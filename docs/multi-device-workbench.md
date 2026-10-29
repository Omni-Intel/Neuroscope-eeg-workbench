# 多设备实验工作台使用说明（0.4.0）

软件用于用相同范式观察不同设备采到的脑电质量。可以自由选择“被试—设备—范式”，每次完整采集单独保存；不会强制被试按某一顺序完成全部实验。现有十个范式均保留：SSVEP、运动想象、视觉图像识别、注意力、静息睁闭眼、N-back、Stroop、情绪图片唤醒、听觉 ASSR、听觉 Oddball。

## 1. 启动与选择设备

在项目根目录运行 `setup-workbench.ps1` 安装 Python 3.12 环境和依赖，然后双击 `启动-NeuroScope桌面控制台.bat`。已有环境可直接启动。本项目不读取外部 oi-mi 或旁边的参考仓库。

| 数据源 | 连接前准备 |
| --- | --- |
| 模拟 / NPZ 回放 | 用于验证界面和流程，不能当作真实被试数据交付 |
| Neuracle | 在 JellyFish 开启转发，填写 IP、端口及实际 EEG 通道数/采样率；辅助通道一并保存 |
| BrainCo | 使用 demo 的 BCIGo SDK 2.1.2 接口；自动发现或填写 IP、端口；按实际设备确认通道布局和物理单位 |
| 公司 OmniBCI | 安装项目 `vendor_sdk/omnibci/` 中的 0.2.0.dev0 wheel，选择 esp32 或 stm32，填写如 `serial://COM5` 的连接地址；前端配置必须已验证 |
| 通用 LSL | 在设备上位机开启 LSL，填写 source_id；存在多个匹配流时不自动猜选 |
| EMOTIV 外部录制 | 在 EmotivPRO 中录 EEG；本程序仅呈现刺激、保存行为和发送串口 Marker |
| TD10 | 保留原有 EEG/Quality/Markers 三流接入；ADC 计数不冒充微伏 |

“选择设备配置”读取 JSON。模板见 `profiles/device-profile.example.json`，请按真实设备填写，不能直接把示例中的电极位置当成实际布局。`channel_names/channel_types/channel_units` 必须与实际数据顺序一致；Neuracle 以转发元数据为准。未知单位仍可原样记录，但不能做电压阈值解释或正式 EDF 导出。

公司设备的阻抗按钮只能在停止采集后使用；结果是 SDK 的名义 kΩ 值，设备测量后保持停止，需再点击“启动”采 EEG。

## 2. 一次实验怎么做

1. 选择设备，按需要加载已确认的设备配置，点击“启动”。检查实时波形、频谱和数据新鲜度。
2. 填写人员平台的 **8 位被试编号**、真实已登记的 **范式代码**（如 `RSVP-20260924`）和平台 `unique_name`。软件只检查格式，不能验证平台是否已登记。
3. 自由选择范式、屏幕和“完整采集”，设置事件同步方式，再点击“开始刺激”。“快速演示”用于调试，不自动创建正式记录。
4. 正常完成或点击停止 / Esc 后，记录封存。更换设备、范式或重做时会生成新 UUID，不覆盖之前的记录。断连后也需新建记录。
5. 完整采集封存后自动导出并尝试 BIDS Validator；缺少信息时在“记录与报告”显示原因，补齐后可重试。通过后将整个 `recording-UUID` 目录交给 EEGQC；评分、上传和入库仍由 EEGQC 完成。

默认只有 LSL 软件标记。Neuracle 的 NDE0001、公司的 TriggerController 和 EMOTIV 配对串口是不同协议，请按实际触发器选择，不共用正在采 EEG 的串口。发送校准码 120 后，需在设备录制软件确认收到；串口写成功不等于硬件收到。

## 3. EMOTIV 的特殊流程

1. 先在 EmotivPRO 中选择设备、开始录制，并设置串口 Marker 输入。
2. 在本程序填写配对串口：发送口与 EmotivPRO 接收口必须不同。协议沿用视频仓库：**115200、8N1、单字节码 1–255，无接收 ACK**。
3. 勾选“已在 EmotivPRO 开始本次录制”，运行所选范式。本程序不会显示虚构的 EMOTIV 实时 EEG，也不能自动证明 EmotivPRO 正在录制。
4. 在 EmotivPRO 停止录制并导出 EDF；点击“关联 EmotivPRO EDF”，选择本次 `run.json` 和 EDF，人工核对被试、范式与 UUID。软件检查可读性、时长和 SHA-256，并复制到该次记录的 `external/`，不改源文件。
5. 根据 EDF 的真实 Marker / 已测时钟关系完成 `alignment.json`。外部 EDF 没有事件对齐依据时禁止导出；不能把本程序启动时刻当作 EDF 首样本。

用下列命令生成待填写的对齐模板；填好后另存为同目录 `alignment.json`：

```powershell
.\.venv\Scripts\python.exe -m neuroscope_eeg.io.data_cli alignment-template "本次记录目录"
```

模板中的 `event_index` 对应 `events.jsonl` 从 0 开始的行号；`onset`、`duration` 单位均为秒，零点是 **EDF 实际首样本**。必须填写 `method` 和可复核的 `evidence`，并覆盖全部事件。设备配置中的 `edf_timezone` 要明确 EDF 日期所属时区，如 `+08:00`。该工具不把手工声明视为光电或硬件延迟实测。

本机直采也可提供同样的对齐表；没有表时必须明确选择允许“未经校准的软件估计”才能导出。该估计来自采集线程的样本计数，会受设备缓存及传输延迟影响，写入 `timing_method=software_cursor_unverified`，不用于宣称精确 ERP 潜伏期。

## 4. 数据输出

选择保存根目录后，原始记录与分析依据在 `Records/`，Word 在 `Reports/<unique_name>/recording-<UUID>/<生成版本>/`，标准 EDF 包在 `data/`。报告重新生成保留版本；模拟交付的范式目录加 `simulation_` 前缀。只采用新结构，不执行旧目录迁移。

本地原始记录：

```text
Records/recording-<UUID>/
  run.json                  # 本地状态、UUID、真实中止原因；不是公司交付 session.json
  config.json               # 范式、预设、屏幕、设备配置快照
  device.json               # 通道、单位、采样率、SDK 与时钟来源
  raw/eeg.f32               # 小端 float32，样本×通道，未做显示滤波
  raw/timestamps.f64        # 原始时间轴；依据见 device.json
  raw/sample_indices.i64    # 样本序号，保留跳号
  raw/valid.u8              # SDK 有效性与有限值检查；不代表 EEGQC 有效时长
  raw/chunks.jsonl          # 每块已写入样本数、接收时间、辅助数组索引
  raw/*.bin                 # SDK 原始计数、状态、设备时间戳等辅助数组
  events.jsonl              # 刺激/响应原始事件，含软件时间和样本计数估计
  behavior.csv              # 行为响应
  triggerbox_log.jsonl       # Marker 请求、发送结果、LSL 时间
  hardware_triggers.jsonl    # 可获得的硬件触发样本位置
  sidecars.jsonl             # TD10 原始时间、质量和时钟修正等
  run.log
  analysis/local_quality.json
  external/recording.edf     # 仅 EMOTIV 关联后生成
  external_confirmation.json
```

辅助二进制的 dtype、shape、字节偏移在对应 `chunks.jsonl` 中。`generation` 为块级字段；SDK 包序号与样本序号分开保存。BrainCo 的 `event_seq` 是事件序号，不自动当作刺激码。EMOTIV 本地 `raw/` 为空是正常情况，不补造 EEG。

本地质量报告记录样本完整性，以及最后至多 60 秒的 RMS、峰峰值和工频功率占比；注明单位和统计窗口，不生成跨品牌总分，也不代替 EEGQC 评分。范式解码需满足电极和单位条件；条件不满足时仍可呈现刺激、保存原始记录。

正式交付结构严格区分于本地原始记录：

```text
data/<unique_name>/recording-<UUID>/
  dataset_description.json
  participants.tsv
  .bidsignore               # **/session.json
  sub-<8位编号>/ses-<UUID>/
    session.json            # 公司扩展 schema_version=1
    eeg/
      sub-…_ses-…_task-<字母数字>_run-01_eeg.edf
      sub-…_ses-…_task-<字母数字>_run-01_eeg.json
      sub-…_ses-…_task-<字母数字>_run-01_channels.tsv
      sub-…_ses-…_task-<字母数字>_run-01_events.tsv
      sub-…_ses-…_task-<字母数字>_run-01_events.json
```

一包一段连续 EDF，不附重复 BDF/NPY。EDF 是有量化误差的派生文件，本地 float32 原始值保留；导出回读核对采样率和实际样本数，不给尾部补零。事件前两列是 `onset/duration`；新增列有描述，不声称是尚未提供的公司额外字段表。

`Records/recording-<UUID>/delivery/validation.json` 记录实际校验结果；未运行、无法启动或输出无法识别均不标记通过。默认调用 PATH 中的官方 BIDS Validator，也可通过 CLI `validate --validator <可执行文件>` 指定。软件不自动上传。

## 5. 验收边界

软件测试覆盖模拟流、数据保存回读、EDF 导出、断连/丢样处理和 Marker 协议。每种真机仍需现场验证：通道及单位、长时间连续采集、断连恢复、硬件 Marker 到达、屏幕刷新/声卡输出和 EMOTIV EDF 事件对应关系。不同设备比较时应固定电极覆盖、参考方式、范式参数和分析窗口，记录无法固定的差异。

程序不补齐采样空隙以伪造连续性；含丢样或无效样本的原始记录保留，当前 EDF 导出会阻止将其冒充完整连续信号。只要样本本身连续且可读，手动中止的记录可以导出，并保留 `aborted` 等真实状态。
