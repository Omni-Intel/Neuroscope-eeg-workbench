# NeuroScope TD10 LSL 完整接入与时序增强设计

## 1. 背景与目标

`feat/test-headband-td10-lsl` 已实现 TD10 的实验性 EEG 单流接入，包括按 `source_id` 发现设备、校验四通道 `int32` EEG 流、保留 LSL 样本时间戳、显示原始 ADC counts，以及将计数值无损写入 BDF。

本次在保留该提交作者和历史的前提下，将该分支合并到 `main`，随后直接在 `main` 补齐 TD10 协议中对正式采集有用的时间轴、Quality 和 Markers 信息。目标是尽可能提高可测量的时间精度，并完整保存校正与审计依据。

LSL 无法恢复 TD10 固件没有发送的设备硬件采样时刻，也无法消除 BLE 传输发生在上位机标时之前的全部抖动。因此本次完成后仍使用 `lsl_software_sync_uncalibrated` 状态；只有光电二极管或音频回采等物理校准通过后，才允许进入 ERP 已校准状态。

## 2. 范围

### 2.1 包含

- 合并 `origin/feat/test-headband-td10-lsl`，保留原提交作者；
- 接收 TD10 EEG、Quality 和 Markers 三条 LSL 流；
- 保留原始 LSL 样本时间戳和 LSL clock correction；
- 将 Quality 与 EEG 时间轴对齐，不删除 `Valid=0` 行；
- 原样保存 iFET Marker，并由 NeuroScope 发布自己的实验 Marker 流；
- 使用统一 LSL 时钟记录刺激事件；
- 根据完整 EEG 时间轴离线确定事件最近样本号，不再把已接收样本数作为权威事件位置；
- 保存时间健康统计并在桌面端展示；
- 保持 TD10 ADC counts 不换算微伏、不启用依赖电极位置或微伏阈值的 decoder；
- 单元测试、同机 LSL 集成测试和现有回归测试。

### 2.2 不包含

- 猜测 ADC counts 到微伏的换算系数；
- 猜测 `EEG1` 至 `EEG4` 的物理电极位置；
- 恢复设备未提供的逐样本硬件时间戳；
- 宣称 BLE/LSL 软件同步达到硬件 Trigger 精度；
- 开放 TD10 的 ERP、诊断或医疗结论；
- 接入 AUX 流的生理算法。当前协议只给出 AUX 的通道数，没有提供九个通道的顺序、标签、单位和数值语义，因此本次不能安全解释或入库；硬件团队补齐这些字段后再独立设计；
- 博睿康网络同步器 `192.168.3.3` 的接入。其协议、端口和报文格式尚未提供，属于独立工作流。

## 3. 合并策略

在干净的本地 `main` 上使用非快进合并：

```text
git merge --no-ff origin/feat/test-headband-td10-lsl
```

这样保留 `18yiba <haorana710@gmail.com>` 的原始提交作者，并以独立 merge commit 标识实验性 TD10 接入的来源。后续实现提交直接写入本地 `main`。未经用户单独要求，本次不推送远端。

## 4. LSL 流发现与生命周期

### 4.1 必需流

以用户选择的基础来源 ID `<base>` 查找：

| 语义 | `source_id` | 类型 | 采样率 |
| --- | --- | --- | --- |
| EEG | `<base>:eeg` | `EEG` | 125/250/500/1000 Hz |
| Quality | `<base>:quality` | `Quality` | 与 EEG 相同 |
| iFET Markers | `<base>:markers` | `Markers` | 0 Hz |

EEG 是实时预览的最低要求。Quality 或 Markers 缺失时允许 EEG-only 预览，但界面显示降级状态，并禁止 TD10 的“完整采集”和内置刺激启动，避免产生看似完整但不可审计的记录。

### 4.2 Inlet 设置

- EEG 和 Quality 使用批量 `pull_chunk()`；
- Markers 使用非阻塞或短超时批量读取；
- 保存 Outlet 原始时间戳；
- 定期调用并保存每个 Inlet 的 `time_correction()`；
- 在线显示使用校正后的时间用于跨流比较，但原始时间戳始终保留；
- 不默认启用会改变原始时间戳的 de-jitter 后处理；若以后启用，必须同时保存处理前后时间戳和配置。

### 4.3 NeuroScope Marker Outlet

NeuroScope 为每次刺激会话创建独立的不规则字符串流：

- `name`: `NeuroScope_Markers`
- `type`: `Markers`
- `source_id`: `neuroscope:<participant>:<session-id>:markers`
- `channel_count`: 1
- `nominal_srate`: 0
- `channel_format`: string

每个 Marker 使用 `pylsl.local_clock()` 标时，内容为稳定 JSON，至少包含：

- `schema_version`
- `session_id`
- `paradigm`
- `phase`
- `label`
- `trial_index`
- `is_practice`
- `protocol_version`

iFET Marker 的字符串格式尚未在协议中定义，因此输入 Marker 作为不透明字符串保存，不猜测其 JSON 结构。

## 5. 数据模型与组件边界

### 5.1 TD10LSLSource

负责：

- 发现并验证三个 LSL 流；
- 从 EEG、Quality、Markers Inlet 批量读取；
- 输出现有 `EEGChunk`，保持主采集接口兼容；
- 缓存待提交的 Quality、Marker 和 clock-correction 批次；
- 提供线程安全的 `drain_sidecars()`；
- 累计连接、有效率、时间戳间隔和时钟校正统计。

它不负责文件命名、会话生命周期、事件样本映射或 ERP 分析。

### 5.2 SessionController

保留现有 EEG 数据路径。在每次读取 EEG 后：

1. 提交 EEGChunk 给记录器；
2. 若数据源支持 sidecar，则取出新增 Quality、Marker 和 correction 批次；
3. 若记录器支持 sidecar，则提交这些批次；
4. 再更新滚动缓冲和运行统计。

非 TD10 数据源行为保持不变。

### 5.3 SessionRecorder

记录器从只接收 EEG 数组扩展为同时保存 EEG 时间戳和 TD10 sidecar。写入仍在后台线程完成，采集线程不执行磁盘阻塞操作。

`session.json` 增加：

- `source_metadata_extra`
- `timestamp_source`
- `timestamp_clock`
- `timestamp_samples_written`
- `timestamp_nonmonotonic_count`
- `timestamp_gap_count`
- `timestamp_max_gap_ms`
- `effective_sample_rate_hz`
- `quality_samples_written`
- `quality_aligned_samples_written`
- `quality_valid_samples`
- `quality_invalid_samples`
- `device_sequence_anomalies`
- `ifet_markers_written`
- `neuroscope_markers_written`
- `clock_correction_samples`
- `timing_status`

## 6. 文件格式

完整 TD10 会话目录增加：

```text
<session>/
├── eeg.bdf
├── events.csv
├── session.json
├── lsl_timestamps.f64
├── quality_raw.i32
├── quality_timestamps.f64
├── quality_aligned.i32
├── ifet_markers.jsonl
├── neuroscope_markers.jsonl
└── clock_corrections.jsonl
```

### 6.1 `lsl_timestamps.f64`

- little-endian float64；
- 一个值对应一个 BDF 有效 EEG 样本；
- 不包含 BDF 尾部填充样本；
- `session.json` 记录 dtype、字节序、数量和文件名；
- EEG 和时间戳写入数量不一致时，会话进入 error，不能静默完成。

### 6.2 Quality 原始与对齐文件

- `quality_raw.i32` 使用 little-endian int32 行主序，每行依次为 `Valid/DeviceSeq/DeviceFlag`；
- `quality_timestamps.f64` 使用 little-endian float64，一个时间戳对应一行 `quality_raw.i32`；
- 原始 Quality 行数与原始 Quality 时间戳数不一致时，会话进入 error；
- `quality_aligned.i32` 与有效 EEG 样本逐行对应，使用校正后的 LSL 时间戳进行最近邻匹配；
- 匹配容差固定为半个 EEG 标称采样周期；超过容差的 EEG 行写入 `Valid=0, DeviceSeq=-1, DeviceFlag=-1`，并累计不匹配数量；
- 原始 Quality 行和时间戳始终保留，不通过删除 EEG 或 Quality 行来强行对齐。

### 6.3 Marker JSONL

每行包含：

- `raw_lsl_time`
- `clock_correction`
- `corrected_lsl_time`
- `raw_value`
- NeuroScope Marker 额外包含结构化事件字段。

### 6.4 Clock correction JSONL

每次采样保存：

- `stream_source_id`
- `local_lsl_time`
- `time_correction_sec`
- `measured_at_wall_time`

## 7. 事件与 EEG 对齐

刺激事件发出时同时记录：

- Python monotonic time；
- 墙钟审计时间；
- `pylsl.local_clock()`；
- NeuroScope Marker JSON。

完整采集结束、所有 EEG 时间戳写入完成后，以校正后的事件 LSL 时间在完整 EEG 时间轴中查找最近样本，生成权威 `eeg_sample_index` 和 `eeg_session_sec`。记录器通过临时文件原子重写 `events.csv`，避免收尾中断留下半写文件。同时保留：

- `alignment_error_ms`
- `alignment_method=nearest_corrected_lsl_timestamp`
- `alignment_status`

若事件落在 EEG 时间范围外、最近样本距离超过预设容差或时间轴不单调，则该事件标为未对齐，不能退回使用 `submitted_samples` 冒充精确结果。

快速演示不自动创建完整会话文件，但界面仍可显示实时 LSL 状态和未经持久化的近似事件位置。

## 8. 时间健康诊断

桌面端 TD10 状态区显示：

- EEG、Quality、iFET Markers 三流连接状态；
- 最近 EEG 数据年龄；
- 标称与有效采样率；
- `Valid=1` 比例；
- DeviceSeq 异常数；
- 非单调时间戳数；
- 超过标称间隔容差的 gap 数和最大 gap；
- 最近 clock correction；
- `LSL 软件同步未完成物理校准`。

诊断包保存同样的统计和 pylsl/liblsl 实际加载状态。仅 `find_spec("pylsl")` 成功不代表 liblsl 可用，环境诊断需要真正导入并报告错误。

## 9. 错误处理

- EEG 流缺失或协议字段不匹配：阻止启动；
- Quality/Markers 缺失：允许预览，禁止完整采集与刺激；
- 同一 `source_id` 对应多个流：阻止启动并提示来源 ID 必须唯一；
- EEG 时间戳非有限或样本数不匹配：停止采集并保留错误会话；
- Quality 无法完全匹配：保留 EEG 和占位质量行，记录异常，不删除时间轴；
- Marker 内容无法解析：保存原始字符串，不中止采集；
- clock correction 临时失败：记录失败并重试；完整会话中从未成功获取 correction 时保持降级状态；
- sidecar 写盘失败或队列溢出：中止完整采集，不能只留下看似成功的 BDF；
- 用户中止：保留已经写入的 BDF、时间戳和 sidecar，并将状态记为 aborted。

## 10. 测试与验收

### 10.1 单元测试

- 三流按精确 `source_id` 发现并校验；
- EEG 原始 ADC counts 和 LSL 时间戳不变；
- Quality 位置和缺失占位正确；
- `Valid=0` 行被保留；
- DeviceSeq 回绕不误报，重复和异常增量按协议统计；
- iFET Marker 非 JSON 字符串可原样保存；
- NeuroScope Marker 使用 LSL 时钟并包含稳定字段；
- clock correction 原始记录可追溯；
- 事件依据完整时间轴映射，边界和超容差事件正确拒绝；
- BDF 有效样本数、EEG timestamp 数和 `quality_aligned.i32` 行数一致；
- Quality 原始行数与 Quality timestamp 数一致；
- 非 TD10 数据源回归行为不变。

### 10.2 LSL 集成测试

使用本机真实 pylsl 创建 EEG、Quality 和 Markers Outlet，验证：

- Inlet 可发现和连接；
- chunk、时间戳和 Marker 顺序正确；
- clock correction 可获取；
- 短暂断流与恢复不会产生静默错位；
- 多个来源 ID 不串流。

该测试在 pylsl/liblsl 可用时运行，否则明确 skip；不能用 fake pylsl 代替全部集成证据。

### 10.3 真机验收

1. Windows 上运行 iFET 0.2.27 并发布三流；
2. 连接 TD10，分别验证 125/250/500/1000 Hz 中设备实际支持的配置；
3. 连续采集至少 10 分钟；
4. 人为制造一次短 BLE 遮挡，确认 Quality 与时间异常被记录；
5. 运行短范式，确认 NeuroScope Marker 和 EEG 进入统一 LSL 时间域；
6. 使用 LabRecorder 同时保存 XDF，与 NeuroScope sidecar 比较样本数、时间戳和 Marker；
7. 确认 UI 和 session.json 始终显示未完成物理校准；
8. 只有后续光电/音频校准通过，才另行批准 ERP 状态切换。

## 11. 完成标准

- 原实验性 TD10 EEG 单流功能完整保留；
- 完整采集必须同时具备 EEG、Quality 和 Markers；
- 每个有效 EEG 样本都有持久化的 LSL 时间戳和对齐质量行，原始 Quality 行及其时间戳也完整保留；
- NeuroScope 刺激事件使用 LSL 时钟并能依据完整时间轴映射到 EEG；
- 原始、校正和审计时间信息均可追溯；
- 缺失、断流、非单调、对齐失败和写盘错误不会被静默隐藏；
- 所有既有测试、TD10 单元测试和可用环境中的真实 LSL 集成测试通过；
- 产品文案不把 LSL 软件同步描述成硬件 Trigger 或已校准 ERP 时序。
