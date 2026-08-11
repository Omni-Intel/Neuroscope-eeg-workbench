# 博睿康 NDE0001 双通道高精度打标实施计划

## 目标

为 NeuroScope 所有内置范式增加统一的 NDE0001 DCP 硬件打标与 LSL 镜像标记。默认 `hardware_lsl` 模式先发送 `01 E1 01 00 XX`，再发送同一事件的 LSL JSON；同时保留 `lsl_only`。事件、硬件写入、LSL 时间和博睿康 Trigger 采样点可追溯，并生成清晰的中文 Excel 码表与时间线。

## 已确认硬件边界

- 现场设备：博睿康 NDE0001；
- 连接：范式电脑可通过 USB 虚拟串口直连；
- 串口：115200 bps、8N1、无流控；
- 协议：十六进制 DCP，而不是裸单字节；
- 自描述查询：`01 04 00 00`，应返回 `TriggerBox.Titing`；
- 即时事件：`01 E1 01 00 XX`；
- 现场没有事件盒光电/声感传感器；
- 最高可验证状态为 `hardware_sample_locked`，视觉和听觉物理起始保持未校准。

## 成功标准

- 所有内置范式通过一个版本化事件码表和一个 `TriggerRouter` 打标；
- NDE0001 DCP 帧、设备识别和错误处理有字节级自动测试；
- `hardware_lsl` 严格先写 DCP，再推送 LSL；
- `lsl_only` 不打开串口，状态明确为软件同步未校准；
- JellyFish 若提供 Trigger/Event 通道，硬件码能映射到真实 EEG 采样点；
- JellyFish 未提供 Trigger/Event 通道时，不用已接收样本数伪造硬件位置；
- 视觉关键事件在显示完成一帧提交后标时，听觉关键事件保存音频输出 hook；
- 每个完整会话生成权威 JSONL、中文事件码 Excel、逐事件时间线 Excel和同步摘要；
- 现有范式流程、N-back 480 trials 和非 Neuracle 数据源不回归；
- 定向测试、完整测试和 Ruff 全部通过。

## 任务 1：建立事件码表和路由数据契约

新增或修改：

- `neuroscope_eeg/timing/__init__.py`
- `neuroscope_eeg/timing/codebook.py`
- `neuroscope_eeg/timing/models.py`
- `tests/timing/test_codebook.py`
- `tests/timing/test_models.py`

步骤：

1. 先写失败测试，固定设计文档中的所有事件码、符号名、中文含义和范式范围。
2. 验证事件码唯一、位于 `1–127`，`0` 不作为事件。
3. 定义不可变的 `TriggerRequest`、`TriggerDispatch`、`ClockBridgeSample` 和 `HardwareTriggerSample`。
4. 定义 `StimulusEvent → EventCode` 的纯映射函数，覆盖所有内置范式关键 phase、条件和反应结果。
5. 非关键事件返回无硬件码，但仍保留 LSL/本地日志资格。
6. 运行 `pytest tests/timing/test_codebook.py tests/timing/test_models.py -q`。

## 任务 2：实现 NDE0001 DCP 串口传输

新增或修改：

- `neuroscope_eeg/timing/neuracle_dcp.py`
- `tests/timing/test_neuracle_dcp.py`
- `pyproject.toml`

步骤：

1. 写失败测试，验证自描述查询帧精确为 `01 04 00 00`。
2. 验证事件 `1`、`127`、`255` 编码为 `01 E1 01 00 XX`，越界拒绝。
3. 使用 fake serial 测试 115200/8N1/no-flow 配置、完整写入、短写入、超时和关闭。
4. 打开串口后发送自描述查询并解析 DCP 长度；只有 payload 包含 `TriggerBox.Titing` 才通过。
5. 不发送软件复位码，不创建 5 ms timer。
6. 将 `pyserial` 加入 desktop 可选依赖。
7. 运行 `pytest tests/timing/test_neuracle_dcp.py -q`。

## 任务 3：实现通用 LSL Marker、时钟桥和 TriggerRouter

新增或修改：

- `neuroscope_eeg/timing/lsl_markers.py`
- `neuroscope_eeg/timing/router.py`
- `tests/timing/test_lsl_markers.py`
- `tests/timing/test_router.py`

步骤：

1. 用 fake pylsl 测试稳定的 stream name/type/source ID 和 `schema_version=2` JSON。
2. 实现 monotonic→LSL 括号采样，保存中点偏移与括号宽度，不直接混减两个时钟。
3. `hardware_lsl` 打开 DCP 和 LSL；`lsl_only` 只打开 LSL。
4. 每个事件分配唯一 `event_id` 和单调 `sequence`。
5. 硬件写入必须先完成，再生成包含硬件结果的 LSL Marker。
6. 测试硬件失败、LSL 失败和双路失败，状态分别显式降级。
7. 实现线程锁，保证音频回调、Qt 线程和停止流程不会交叉破坏顺序。
8. 运行 `pytest tests/timing/test_lsl_markers.py tests/timing/test_router.py -q`。

## 任务 4：从 Neuracle/JellyFish 提取硬件 Trigger 样本

新增或修改：

- `realtime_eeg_viewer.py`
- `neuroscope_eeg/acquisition/legacy.py`
- `neuroscope_eeg/core/session.py`
- `tests/acquisition/test_neuracle_triggers.py`
- `tests/core/test_session_stats.py`

步骤：

1. 构造假的 `DataServerThread`，覆盖 `channelTypes` 或通道名包含 `TRIGGER`、`STIM`、`EVENT` 的情况。
2. EEG 通道仍按原逻辑输出；Trigger 通道不进入 EEG 矩阵。
3. 对 Trigger 通道进行非零边沿检测：连续相同非零值只产生一个事件，回到零后允许再次产生同码。
4. 使用整块数据的起始样本号生成真实 `hardware_sample_index`。
5. 暴露线程安全、只返回一次的 `drain_hardware_triggers()`。
6. `SessionController` 将硬件 Trigger sidecar 交给记录器；普通 source 行为不变。
7. 没有 Trigger 通道时返回空 sidecar，并保持 `hardware_dispatched_unverified`。
8. 运行定向 acquisition/core 测试。

## 任务 5：持久化触发日志并生成 Excel

新增或修改：

- `neuroscope_eeg/io/trigger_export.py`
- `neuroscope_eeg/io/session_recorder.py`
- `tests/io/test_trigger_export.py`
- `tests/io/test_session_recorder.py`
- `pyproject.toml`

步骤：

1. 增加 `events.jsonl`、`triggerbox_log.jsonl`、`lsl_markers.jsonl`、`hardware_triggers.jsonl`、`event_codebook.json` 和 `synchronization_summary.json`。
2. 记录器按 event ID 接收最终 `TriggerDispatch`，不丢弃原有 `events.csv`。
3. 按 sequence、码值和顺序把本地硬件发送与 Neuracle Trigger 样本配对。
4. 配对状态覆盖 matched、missing、unexpected、ambiguous 和 out-of-order。
5. 匹配成功才写 `hardware_sample_index` 和 `eeg_time_sec`；未匹配保持空值。
6. 使用 `openpyxl` 生成 `event_codebook.xlsx` 和 `event_timeline.xlsx`：
   - “事件码对照”；
   - “事件时间线”；
   - “会话同步摘要”。
7. Excel 使用冻结表头、自动筛选、中文列名、合理列宽和状态颜色；原始 JSONL 仍是权威数据。
8. Excel 可从已有 JSONL/JSON 重新生成，导出失败不破坏原始文件。
9. 将 `openpyxl` 加入 desktop 可选依赖。
10. 运行定向 IO 测试。

## 任务 6：接入桌面端生命周期和运行设置

新增或修改：

- `neuroscope_eeg/desktop/app.py`
- `tests/desktop/test_console.py`

步骤：

1. 在刺激控制区增加同步模式：`硬件 + LSL`、`仅 LSL`。
2. `hardware_lsl` 显示 NDE0001 COM 端口；`lsl_only` 禁用串口字段。
3. 完整采集启动时创建并自检 `TriggerRouter`；快速演示允许 mock router，但状态必须可见。
4. DCP 自描述失败时阻止 `hardware_lsl` 启动，不自动改成 LSL-only。
5. 启动发送 `EXPERIMENT_START`，正常结束发送 `EXPERIMENT_END`，中止发送 `ABORT`。
6. `StimulusEvent` 经码表映射后提交 router，再交给原记录与分析路径。
7. UI 显示硬件、LSL、物理校准和降级状态；现场固定提示物理起始未校准。
8. 停止时先完成结束事件和日志，再关闭 router 和记录器。

## 任务 7：视觉换帧与所有范式事件接入

新增或修改：

- `neuroscope_eeg/desktop/stimulus.py`
- `neuroscope_eeg/desktop/protocols.py`
- `tests/desktop/test_protocols.py`
- `tests/desktop/test_console.py`

步骤：

1. `StimulusEvent` 增加 intent、onset hook 和 hook 类型字段，同时保持现有序列化兼容。
2. 将刺激绘制表面切换为能提供 `frameSwapped` 的 Qt OpenGL 路径；关键视觉事件先排队，在对应帧 swap 完成后发出。
3. 非视觉提示和行为反应继续即时发出，并标明 `software` 或 `input_callback` hook。
4. 为所有范式补齐关键映射：SSVEP、运动想象、视觉识别、注意力、静息、N-back、Stroop、情绪图片、ASSR、Oddball。
5. block 起止、遗漏、正确、错误、误报使用公共码。
6. SSVEP 只标闪烁段起止，不逐帧发送 Trigger。
7. 用纯测试验证同一视觉状态只发一次、下一帧才发、停止时不残留待发事件。

## 任务 8：听觉输出 onset hook

新增或修改：

- `neuroscope_eeg/desktop/audio.py`
- `neuroscope_eeg/desktop/stimulus.py`
- `tests/desktop/test_audio.py`
- `tests/desktop/test_protocols.py`

步骤：

1. 用持久 `sounddevice.OutputStream` 替代每次 `sd.play()` 临时播放。
2. 预生成声音数据，在首个包含有效样本的 callback 保存 PortAudio `outputBufferDacTime` 和本机 hook 时间。
3. 通过线程安全 callback 提交 ASSR/Oddball onset 事件；不把串口 I/O 放进实时音频 callback 内。
4. 记录音频 hook→DCP 提交延迟，状态保持物理起始未校准。
5. 音频停止、重启和异常不会重复发送 onset。
6. 使用 fake sounddevice 测试首 buffer、后续 buffer、stop 和失败路径。

## 任务 9：文档、台架工具和最终回归

新增或修改：

- `neuroscope_eeg/timing/bench.py`
- `README.md`
- `tests/timing/test_bench.py`

步骤：

1. 增加 NDE0001 台架命令，发送自检码和可复现混合码序列，并写 JSONL/CSV 报告。
2. README 记录接线、Collect LSL 选项、DCP 自检、两种模式、码表和 Excel 文件。
3. 明确纯 LSL、硬件已发送未验证、采样点锁定和物理起始未校准的区别。
4. 运行：

   ```bash
   .venv312/bin/python -m pytest tests/timing tests/acquisition/test_neuracle_triggers.py tests/io/test_trigger_export.py -q
   .venv312/bin/python -m pytest -q
   .venv312/bin/python -m ruff check neuroscope_eeg tests realtime_eeg_viewer.py
   git diff --check
   ```

5. 检查工作区，只提交本任务文件，不加入用户现有 `tmp/`。
6. 提交实现；远程推送需获得当前任务的明确授权。
