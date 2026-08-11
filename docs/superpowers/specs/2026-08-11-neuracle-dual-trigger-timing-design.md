# NeuroScope 博睿康双通道高精度打标设计

## 1. 背景与目标

当前 NeuroScope 的博睿康采集路径只接收 EEG 数据，并按已接收样本数估算事件位置；刺激事件在 Qt 状态切换时产生，尚未与显示换帧、音频物理输出或放大器 Trigger 通道建立统一时间基准。该路径适合功能验证，但不能作为采样点级硬件打标依据。

博睿康示例工程 `/Volumes/SANDISK ELE/collect/` 提供两条触发路径：

- LSL Marker 由范式电脑发送，Collect 勾选“接收LSLTrigger”后接收；
- 范式电脑通过串口控制 TriggerBox，再由 TriggerBox 接入放大器 Trigger 输入。

示例工程的串口实现支持裸单字节或 ASCII 码，但现场已确认设备为 NDE0001。NDE0001 产品说明书规定 USB 串口使用十六进制 DCP 帧；本次以设备手册为权威协议，不沿用示例工程的裸字节发送方式。

本设计统一两条路径，默认用 TriggerBox 硬触发获得 EEG 采样点级事件位置，同时发送带完整语义和 LSL 时间戳的镜像 Marker。系统还保留纯 LSL 模式，使没有硬件接线时仍可运行，但必须明确标记为软件同步、未完成硬件校准。

目标是让 NeuroScope 内所有现有范式使用同一打标接口、同一码表和同一审计格式，在现有 B 类硬件条件下把 NDE0001 事件可靠写入博睿康 Trigger 通道，同时如实保留屏幕与扬声器物理起始未校准的边界。

## 2. 范围

### 2.1 包含

- TriggerBox 串口硬件触发；
- NeuroScope LSL Marker 镜像流；
- `hardware_lsl` 和 `lsl_only` 两种显式模式；
- 所有内置视觉、听觉和行为范式的统一事件入口；
- 视觉换帧、音频起始和按键回调的分类型时间语义；
- 版本化 8-bit 硬件事件码表；
- 硬件事件、LSL Marker、EEG Trigger 样本和本地日志的配对；
- 启动自检、运行状态、故障降级和同步质量摘要；
- JSONL、CSV 和 Excel 中文对照输出；
- 自动测试和博睿康台架测试流程。

### 2.2 不包含

- 把纯 LSL 接收描述为放大器采样点级硬打标；
- 猜测博睿康未提供的设备内部时间戳；
- 在 8-bit TriggerBox 通道中拆分发送字符串时间戳；
- 未经光电或音频回环测量就宣称屏幕或扬声器端已完成物理校准；
- NDE0001 事件盒、光电传感器或声感传感器的控制协议；
- 修改 N-back trial 数、SOA 或其他已确认的范式流程；
- 对无关采集源或解码器进行重构。

## 3. 已确认方案

采用“硬触发主通道 + LSL 镜像通道”，并保留纯 LSL 运行模式。

### 3.1 `hardware_lsl`

- 刺激起始时先向 TriggerBox 发送硬件事件码；
- TriggerBox 接入博睿康放大器 Trigger 输入；
- 随后发送包含同一事件编号和硬件码的 LSL JSON Marker；
- 硬件事件通道是 EEG 样本位置的主要依据；
- LSL 和本地日志提供完整条件语义及跨程序审计信息。

### 3.2 `lsl_only`

- 不要求范式电脑直连 TriggerBox；
- 只发送 LSL JSON Marker；
- 使用 LSL 时钟和 EEG 时间轴完成软件对齐；
- 会话状态固定为 `lsl_software_sync_uncalibrated`，不能显示为硬件同步。

模式只能在实验开始前选择。运行中任何通道失败都要形成显式状态，不能静默改变模式或伪装为完整成功。

## 4. 组件边界

### 4.1 `TriggerRouter`

所有范式只向 `TriggerRouter` 提交结构化事件，不再直接访问串口或 LSL。它负责：

- 校验事件是否存在于版本化码表；
- 分配会话内唯一 `event_id` 和递增 `sequence`；
- 根据模式决定硬件与 LSL 路径；
- 保证硬件发送先于对应的 LSL 镜像；
- 收集每条路径的时间、结果和异常；
- 将不可变的最终事件记录交给记录器。

它不负责范式调度、绘制刺激、生成音频或解释 EEG。

### 4.2 `TriggerBoxTransport`

负责预先打开 NDE0001 USB 虚拟串口，固定使用 115200 bps、8 data bits、1 stop bit、no parity、no flow control。打开后发送自描述查询帧：

```text
01 04 00 00
```

只有收到包含 `TriggerBox.Titing` 的有效 DCP 回复才允许进入 `hardware_lsl`。实时输出一次事件使用：

```text
01 E1 01 00 XX
```

其中 `XX` 是单字节硬件事件码。该命令由设备输出一次 Trigger 事件，不再由软件追加 `0` 复位码或 5 ms 定时器。正式实验开始后不在事件路径中扫描端口、重新建连或等待用户输入。

每次发送保存：

- 写入请求前的 monotonic 时间；
- 串口写入返回后的 monotonic 时间；
- 完整 DCP 帧、事件码和写入结果；
- 串口异常。

### 4.3 `LSLMarkerTransport`

每次会话只创建一个不规则字符串 Marker Outlet，使用稳定的 stream name、type 和唯一 source ID。每条 Marker 使用 `pylsl.local_clock()` 显式标时，内容为稳定 JSON。

LSL 推送不能阻塞或反向延迟硬件触发。是否存在接收者在启动自检时显示，但正式事件发送不等待订阅者临时响应。

### 4.4 刺激适配层

范式仍负责何时进入新状态，但关键刺激由适配层在对应的权威起始钩子提交：

- 视觉适配层：显示换帧回调；
- 听觉适配层：首个有效输出缓冲的时间信息；
- 行为适配层：按键输入回调；
- 非关键提示：普通软件事件，仅写 LSL 和本地日志。

### 4.5 会话记录器

记录器保存码表版本、所有发送结果、博睿康 Trigger 导入结果、校准结果和最终时间映射。它负责生成机器可读文件及面向实验人员的 Excel 对照，不负责实时触发。

## 5. 时间语义

每个事件至少区分：

- `intent_time`：范式决定切换状态的本机 monotonic 时间；
- `onset_hook_time`：显示换帧、音频输出或输入回调触发的本机 monotonic 时间；
- `hardware_dispatch_time`：串口写入硬件码前的本机 monotonic 时间；
- `hardware_write_complete_time`：串口写入返回时间；
- `lsl_timestamp`：Marker 使用的 LSL 时钟时间；
- `hardware_sample_index`：博睿康 EEG Trigger 通道中的触发采样点；
- `eeg_time_sec`：`hardware_sample_index / sfreq` 得到的会话内硬件时间；
- `physical_onset_sample_index`：光电或音频回环测得的物理刺激起始采样点。

TriggerBox 的单字节码不承载完整时间戳。硬件打标的权威时间来自放大器把触发沿记录到 EEG 的具体采样点；LSL Marker 则直接携带浮点时间戳。两者并行保存，不互相替代。

本机 monotonic 时钟和 LSL `local_clock()` 属于不同字段，不能直接相减。会话启动时及运行期间定期执行括号采样：读取 monotonic、读取 LSL clock、再次读取 monotonic，以中点估算两者偏移，并用括号宽度记录换算不确定度。所有跨时钟差值必须同时写入：

- 原始时钟值；
- 时钟域名称；
- 使用的偏移样本；
- `comparison_method`；
- `conversion_uncertainty_ms`。

若不能建立可靠换算，就保留原始时间，不输出伪精确的跨时钟差值。

## 6. 各类事件的起始规则

### 6.1 视觉刺激

关键视觉刺激不能在 `QTimer` 状态更新时提前打标。显示状态先准备并请求绘制，在实际换帧回调中提交刺激起始事件。

需要硬件标记的视觉事件包括：

- SSVEP 闪烁开始和结束；
- 运动想象 cue；
- 视觉识别目标或非目标出现；
- 注意力题目出现；
- 睁眼或闭眼阶段开始；
- N-back 数字出现；
- Stroop 色词出现；
- 情绪图片出现。

SSVEP 不为每一帧发送硬件码，只标记稳定闪烁段的开始和结束。显示角落保留可配置的黑白同步块，供未来外部测量使用。现场没有配套光电事件盒，因此本次不能生成光电校准结果，视觉状态最高只能到 `hardware_sample_locked`。

### 6.2 听觉刺激

听觉输出改用持续的音频流，预先准备样本，避免每个 trial 临时创建播放链路。开始输出首个有效缓冲时提交硬件与 LSL 事件，并保存音频后端提供的输出时间信息。

声卡、驱动和扬声器仍会引入固定延迟与抖动。现场没有声感事件盒或音频回环，因此本次只能标为硬件触发已记录、声音物理起始未校准。

### 6.3 行为反应

按键输入回调立即提交反应事件。反应时基于同一 trial 的校准后刺激起始计算；若没有物理校准，则保留基于 onset hook 的软件反应时，并在状态中说明依据。

### 6.4 非关键事件

倒计时、规则说明、提示文字、统计更新和普通反馈不占用硬件码，只写入 LSL 与本地日志。block 起止、实验起止和异常中止仍使用公共硬件码。

## 7. 硬件事件码

NDE0001 DCP 支持 `0–255`，本码表 v1 主动把 `0` 保留为无事件值，把 `1–127` 用于事件。任何范式不得直接写裸数字，必须通过版本化码表的符号名获取。DCP 即时事件命令不需要软件发送 `0` 复位。

| 范围 | 用途 |
| --- | --- |
| 1–4 | 运动想象四分类 cue，兼容示例工程 |
| 10 | 公共 fixation，兼容示例工程 |
| 11–19 | SSVEP 目标位置或频率索引及结束 |
| 20 | 公共 rest，兼容示例工程 |
| 21–29 | 视觉识别目标、非目标和结束 |
| 30–39 | 注意力任务 |
| 40–49 | 静息睁眼/闭眼 |
| 50–59 | N-back 负荷与 target/non-target |
| 60–69 | Stroop 一致、不一致和结束 |
| 70–79 | 情绪图片条件 |
| 80–89 | ASSR、Oddball 标准音和偏差音 |
| 90/91 | block 开始/结束 |
| 100/101 | 实验开始/结束 |
| 110–119 | 正确、错误、漏答及行为反应 |
| 120–126 | 校准和同步诊断 |
| 127 | 中止或异常结束 |

统一码表 v1 固定映射为：

| 硬件码 | 符号名 | 中文含义 |
| ---: | --- | --- |
| 1 | `MI_LEFT_HAND` | 左手运动想象 cue |
| 2 | `MI_RIGHT_HAND` | 右手运动想象 cue |
| 3 | `MI_BOTH_FEET` | 双脚运动想象 cue |
| 4 | `MI_TONGUE` | 舌部运动想象 cue |
| 10 | `FIXATION` | 公共注视开始 |
| 11–18 | `SSVEP_TARGET_1`–`SSVEP_TARGET_8` | SSVEP 目标 1–8 闪烁开始 |
| 19 | `SSVEP_FLICKER_OFFSET` | SSVEP 闪烁结束 |
| 20 | `REST` | 公共休息开始 |
| 21 | `VISUAL_NONTARGET_ONSET` | 视觉识别非目标出现 |
| 22 | `VISUAL_TARGET_ONSET` | 视觉识别目标出现 |
| 23 | `VISUAL_STIMULUS_OFFSET` | 视觉识别刺激结束 |
| 31 | `ATTENTION_PROBLEM_ONSET` | 注意力题目出现 |
| 32 | `ATTENTION_REST_ONSET` | 注意力休息开始 |
| 33 | `ATTENTION_PROBLEM_OFFSET` | 注意力题目结束 |
| 41 | `EYES_OPEN_ONSET` | 睁眼阶段开始 |
| 42 | `EYES_CLOSED_ONSET` | 闭眼阶段开始 |
| 43 | `EYES_TRANSITION` | 睁闭眼过渡提示 |
| 50 | `NBACK_0_NONTARGET` | 0-back 非目标出现 |
| 51 | `NBACK_0_TARGET` | 0-back 目标出现 |
| 52 | `NBACK_1_NONTARGET` | 1-back 非目标出现 |
| 53 | `NBACK_1_TARGET` | 1-back 目标出现 |
| 54 | `NBACK_2_NONTARGET` | 2-back 非目标出现 |
| 55 | `NBACK_2_TARGET` | 2-back 目标出现 |
| 56 | `NBACK_STIMULUS_OFFSET` | N-back 数字结束 |
| 61 | `STROOP_CONGRUENT_ONSET` | Stroop 一致刺激出现 |
| 62 | `STROOP_INCONGRUENT_ONSET` | Stroop 不一致刺激出现 |
| 63 | `STROOP_STIMULUS_OFFSET` | Stroop 刺激结束 |
| 71 | `EMOTION_POSITIVE_ONSET` | 正向情绪图片出现 |
| 72 | `EMOTION_NEGATIVE_ONSET` | 负向情绪图片出现 |
| 73 | `EMOTION_NEUTRAL_ONSET` | 中性情绪图片出现 |
| 74 | `EMOTION_IMAGE_OFFSET` | 情绪图片结束 |
| 75 | `EMOTION_BASELINE_ONSET` | 情绪基线开始 |
| 81 | `ASSR_ONSET` | ASSR 声音开始 |
| 82 | `ASSR_OFFSET` | ASSR 声音结束 |
| 83 | `ODDBALL_STANDARD_ONSET` | Oddball 标准音开始 |
| 84 | `ODDBALL_DEVIANT_ONSET` | Oddball 偏差音开始 |
| 85 | `AUDITORY_STIMULUS_OFFSET` | Oddball 声音结束 |
| 90 | `BLOCK_START` | block 开始 |
| 91 | `BLOCK_END` | block 结束 |
| 100 | `EXPERIMENT_START` | 实验开始 |
| 101 | `EXPERIMENT_END` | 实验正常结束 |
| 110 | `RESPONSE` | 普通行为反应 |
| 111 | `RESPONSE_CORRECT` | 正确反应 |
| 112 | `RESPONSE_INCORRECT` | 错误反应 |
| 113 | `OMISSION` | 漏答 |
| 114 | `FALSE_ALARM` | 误报 |
| 120 | `TRIGGER_PATH_CALIBRATION` | Trigger 通道自检 |
| 127 | `ABORT` | 中止或异常结束 |

未列出的码值在码表 v1 中保留，不得由范式临时占用；`121–126` 为未来物理传感器或诊断扩展保留，本次不发送。SSVEP 的具体频率保存在 LSL；硬件码对应本次会话中固定的目标索引，实际索引到频率的映射写入会话码表副本。当前 NeuroScope 运动想象只使用左手、右手和静息时，静息沿用公共 `REST=20`；四分类示例仍完整保留 `1–4`。

## 8. LSL Marker 数据格式

LSL JSON 使用 `schema_version=2`，至少包含：

```json
{
  "schema_version": 2,
  "event_id": "EVT-000123",
  "sequence": 123,
  "session_id": "session-id",
  "paradigm": "working_memory_nback",
  "phase": "stimulus",
  "label": "7",
  "hardware_code": 53,
  "condition": "target",
  "block": 5,
  "trial": 17,
  "intent_time": 12345.670,
  "onset_hook_time": 12345.682,
  "hardware_dispatch_time": 12345.682,
  "lsl_timestamp": 98234.5721,
  "timing_mode": "hardware_lsl",
  "timing_status": "hardware_dispatched_unverified"
}
```

负荷、刺激内容、正确答案、练习状态、协议版本和其他范式字段继续保存在 JSON payload 中。硬件码只承担稳定定位，不重复编码全部语义。

## 9. 文件与 Excel 输出

会话至少保存：

```text
<session>/
├── events.jsonl
├── events.csv
├── event_codebook.json
├── event_codebook.xlsx
├── event_timeline.xlsx
├── triggerbox_log.jsonl
├── lsl_markers.jsonl
├── synchronization_summary.json
└── session.json
```

### 9.1 `event_codebook.xlsx`

“事件码对照”工作表至少包含：

- 硬件码；
- 符号名；
- 范式；
- 阶段；
- 条件；
- 中文含义；
- DCP 命令类型；
- 是否关键事件；
- 适用运行模式；
- 码表版本。

### 9.2 `event_timeline.xlsx`

“事件时间线”工作表至少包含：

- 事件编号和顺序号；
- 硬件码、范式、phase、condition、block 和 trial；
- intent、onset hook、硬件写入和 LSL 时间；
- 每个时间值的时钟域、换算方法和换算不确定度；
- 博睿康硬件采样点与 EEG 会话内秒数；
- 光电或音频物理起始采样点；现场无传感器时留空；
- 硬件与 LSL 时间差；
- 硬件与物理刺激时间差；
- 每条通道的发送结果；
- 校准状态和异常说明。

“会话同步摘要”工作表至少包含采样率、运行模式、TriggerBox 串口、LSL stream/source ID、预期与实际事件数、失败数、丢失数、重复数，以及各类时间差的中位数、P95 和 P99。

Excel 是清晰对照和人工检查文件；JSONL/JSON 是无损审计和程序复现的权威文件。Excel 生成失败不能损坏已写入的原始记录，结束阶段应允许从 JSONL 重新生成。

## 10. EEG Trigger 导入与事件配对

博睿康导出的 Trigger 信息必须转换为至少包含 `hardware_code`、`hardware_sample_index` 和顺序的统一记录。随后按会话顺序、码值和容许窗口与 `TriggerRouter` 事件配对。

配对结果分为：

- `matched`：单一硬件事件与单一本地事件对应；
- `missing_hardware`：本地已发送但 EEG 中未找到；
- `unexpected_hardware`：EEG 中存在但本地未发送；
- `ambiguous`：窗口内存在多个候选；
- `out_of_order`：码值存在但顺序不一致。

不得使用当前已接收样本数填充缺失的硬件采样点。`hardware_sample_index` 只有在博睿康 Trigger 数据实际存在并成功配对后才允许写入。

## 11. 启动自检

`hardware_lsl` 开始前必须通过：

1. 打开并锁定配置的 TriggerBox 串口；
2. 使用自描述查询确认设备返回 `TriggerBox.Titing`；
3. 校验 DCP 即时事件帧和事件码范围；
4. 发送专用校准码 `120`；
5. 由实验人员确认博睿康 Trigger 通道收到校准码；
6. 建立 LSL Marker Outlet，并显示 Collect 接收状态；
7. 校验码表版本、EEG 采样率和记录目录可写；
8. 明确显示“无光电/音频回环，物理刺激起始未校准”。

硬件自检失败时不得直接以 `hardware_lsl` 开始。操作者可以明确切换为 `lsl_only`，界面和输出必须同步改变状态。

## 12. 故障处理

- LSL 发送失败：继续硬件触发，状态变为 `hardware_only_degraded`，保存异常；
- TriggerBox 发送失败：继续保存 LSL 和行为数据，状态变为 `hardware_failed`，界面立即红色提示，受影响事件不写伪造的硬件时间；
- 两路都失败：保存本地事件和异常，并明确标记该段无法同步；
- 事件重复、乱序或 DCP 帧发送失败：记录具体序号和码值，不能在收尾时自动隐藏；
- Excel 生成失败：保留原始 JSONL 和 JSON，记录导出错误，并支持重新生成；
- 记录器写入失败：沿用现有策略停止实验并保留错误会话；
- 用户中止：若 TriggerBox 仍可用则发送 `127`，保留已完成数据并标记为 aborted。

任一路径失败时实验不静默退出或静默切换；当前已确认的策略是继续保存能够获取的数据，同时把同步等级和受影响事件明确降级。

## 13. 同步状态

使用可审计的分级状态：

- `lsl_software_sync_uncalibrated`：仅 LSL；
- `hardware_dispatched_unverified`：DCP 写入成功，但尚未与博睿康 Trigger 样本配对；
- `hardware_sample_locked`：博睿康 Trigger 事件已成功映射到 EEG 采样点；
- `hardware_only_degraded`：硬件有效但 LSL 失败；
- `hardware_failed`：预期硬件标记缺失，只有 LSL 或本地日志；
- `unsynchronized`：没有可用的跨数据时间依据。

一个会话可同时有总体状态和逐事件状态。不能因为大部分事件成功而覆盖少数失败事件的真实状态。现场 B 配置的最高状态为 `hardware_sample_locked`；只有未来增加并验证物理传感器后，才能在独立设计中增加视觉或听觉 calibrated 状态。

## 14. 测试与验收

### 14.1 自动测试

- 所有码值位于 `1–127`，`0` 不作为事件；
- NDE0001 自描述查询和即时事件 DCP 帧逐字节正确；
- 统一码表无冲突，N-back 映射和既有运动想象码保持稳定；
- 所有内置范式通过 `TriggerRouter` 提交关键事件；
- 硬件发送顺序始终早于对应 LSL 镜像；
- 事件 ID 和 sequence 在会话内唯一且单调；
- 1000 次模拟发送无丢失、重复或错配；
- 测试硬件失败、LSL 失败、双路失败和非法 DCP 回复；
- 两种运行模式生成正确的 timing status；
- Excel 行数、码值和关键字段与权威 JSONL 一致；
- Excel 可从已有 JSONL 重新生成；
- 非博睿康采集和既有范式流程回归测试继续通过。

### 14.2 博睿康台架测试

1. TriggerBox 接入放大器 Trigger 输入；
2. 发送至少 1000 个已知、可复现的混合码序列；
3. 导出 EEG 和 Trigger 事件；
4. 确认事件数量、顺序和码值与发送日志完全一致；
5. 计算硬件事件与 LSL 镜像的时间差中位数、P95、P99、最大值；
6. 保存原始数据、软件版本、串口设置、采样率和测试结果。

任何丢失、重复或错配都视为台架测试失败。绝对延迟和抖动不预先伪造阈值；首次台架数据形成基线后，实施阶段再根据采样率、显示刷新率和音频缓冲给出可解释的验收范围。

### 14.3 无传感器边界检查

- 视觉事件必须保存换帧 hook、DCP 写入和 LSL 时间，但物理起始字段保持空值；
- 听觉事件必须保存音频输出 hook、DCP 写入和 LSL 时间，但物理起始字段保持空值；
- UI、Excel 和 `session.json` 必须显示“物理刺激起始未校准”；
- 不得依据固定常数伪造屏幕或声音物理延迟。

## 15. 完成标准

- 所有现有范式使用统一事件接口，范式代码不再自行访问串口或 LSL；
- `hardware_lsl` 能产生博睿康 EEG 采样点级硬件事件和相同语义的 LSL 镜像；
- `lsl_only` 能独立运行并保持明确的软件同步状态；
- 每条关键事件可追溯到唯一 ID、硬件码、发送日志、LSL Marker 和匹配结果；
- 视觉、听觉和行为事件遵循各自明确的 onset 规则；
- 输出包含机器可读原始记录以及清晰的中文 Excel 码表和逐事件时间线；
- 台架测试可量化丢码、错码、延迟和抖动；
- 未完成硬件或物理校准的数据不会被标记为已校准；
- 所有新增测试和既有回归测试通过。

## 16. 参考依据

- 博睿康示例工程：`/Volumes/SANDISK ELE/collect/`；
- LSL 时间同步说明：<https://labstreaminglayer.readthedocs.io/info/time_synchronization.html>；
- LSL FAQ：<https://labstreaminglayer.readthedocs.io/info/faqs.html>；
- PsychoPy `Window` 与换帧相关接口：<https://psychopy.org/api/visual/window.html>。
