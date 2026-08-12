# NeuroScope

**多范式脑电可视化工作�?*，用于博睿康 Neuracle、强�?BrainCo、test-头带（TD10 LSL）、模�?EEG �?NPZ 回放�?

NeuroScope 提供高刷新率桌面控制台、实时波形、频谱、信号质量、实验记录和多类开箱即用的即时基线 decoder。它适合在采集现场快速看趋势；未经个人标定的结果不是科研结论或医疗诊断�?

## 已支持功�?

- 数据源：模拟、NPZ 回放、博睿康 JellyFish 实时转发、强�?BCIGo SDK 1.0.2、test-头带（TD10 LSL EEG/Quality/Markers�?
- SSVEP：滤波组谐波 CCA，直接输出候选刺激频率
- 运动想象：C3/C4 �?µ/β 侧化趋势
- 视觉任务：枕区视觉响应；独立记录图像类别、目标是否出现、是否报告看�?
- 注意力：theta/alpha/beta 会话内趋势分�?
- 静息睁眼/闭眼：前�?alpha、theta、beta 和闭眼相对睁眼变�?
- N-back 工作记忆：分 block 运行 0/1/2-back；完整采集每负荷 4×40、共 480 个正式试次，数字呈现 1500 ms 后空�?500 ms，目标按 `J`、非目标�?`F`，仅练习反馈，block 间休�?25 �?
- Stroop 色词冲突�?2 个练习后运行 30/120 个正式试次，一致按 `J`、不一致按 `F`，仅练习反馈
- 情绪图片唤醒：自有素材七类各 15 张，完整采集分成三个平衡区块，无逐图片评�?
- 听觉 ASSR�?0 Hz 调幅音刺激�?T3/T4 优先的频率跟�?SNR
- 听觉 Oddball�?0 个练习后运行 100/300 �?80/20 标准音与偏差音，高音�?`J`
- 结果来源标识、候选分离度/趋势强度、缺失通道提示和信号质量保�?
- 刺激窗口内置快速演�?完整采集预设、练习与正式阶段、内容提示、行为评分、自动结束和 `Esc` 安全退�?
- 完整采集启动范式时自动创建独立目录，持续保存全导 BDF、事�?CSV 和会�?JSON；正常结束或中止时自动关闭文�?
- BrainCo 官方 32 通道映射、干电极去漂移显示和数据新鲜度监�?
- PySide6 + pyqtgraph 桌面控制台，默认 30 FPS，可�?20/60 FPS，并显示实际刷新�?
- Windows 环境诊断�?

视觉任务中的 `image_category`、`target_present` �?`seen_reported` 是实验记录，不是 decoder 预测。没有带标签的个人训练数据时，NeuroScope 不会声称�?EEG 解出了任意图像类别�?

## 本地运行（推荐桌面控制台�?

需�?Python 3.12�?

```bash
python3.12 -m venv .venv312
.venv312/bin/python -m pip install -U pip setuptools wheel
.venv312/bin/python -m pip install '.[desktop,dev]'
.venv312/bin/python -m neuroscope_eeg.desktop.app
```

启动后先选择“模拟”，确认波形持续移动、实际刷新率接近目标值，并检查各范式的即时结果。将模拟通道数设�?5 时，通道自动使用 `Fp1/Fp2/Fpz/T3/T4`。桌面控制台默认 30 FPS；采集电脑性能足够时可选择 60 FPS�?

需要运行内置范式时，先填写受试者编号和记录目录、启动采集，再选择任务范式、协议预设和第二块显示器，点击“开始刺激”。`快速演示` 减少阶段时长或正式试次且不自动保存原始脑电；`完整采集` 使用 0/1/2-back �?4×40（共 480 个正式试次）�?20 �?Stroop�?0 �?ASSR�?00 �?Oddball 和全�?105 张情绪图片，并在刺激出现前创�?`<记录目录>/<受试者编�?/<时间_范式_full>/`。目录内�?`eeg.bdf` 是全导原始脑电，`events.csv` 是带 EEG 样本索引的事件，`session.json` 保存通道、采样率、有效样本数和完�?中止状态。练习事件会标记�?`is_practice=true`，不进入正式行为统计。按 `Esc` 可随时退出刺激；已采集数据会自动收尾保留，原有“导出事�?CSV”按钮仍可另存事件副本�?

情绪图片流程包含内容提示�?0 秒中性基线，以及每张图片�?1 秒注视�? 秒图片和 1 秒空屏，不进行效价或唤醒评分。七个细分类为愉悦、厌恶、恐惧、鼓舞、中性、悲伤、温情，每类 15 张；完整采集在第 35 和第 70 张后休息。素材为公司自有素材，不标注�?IAPS。按 `S` 可以跳过当前图片�?

刺激事件支持两种同步模式：推荐的“博睿康硬件 + LSL”会先通过 NDE0001 串口�?DCP 立即事件命令 `01 E1 01 00 XX` 发码，再发布同一事件的通用 LSL Marker；“仅 LSL”用于没�?TriggerBox 的预览。视觉关键事件在 `frameSwapped` 后发码，听觉关键事件在首个音频输出缓冲回调发码。博睿康 Trigger/Event 通道里实际收到的码会按采样点回配，只有成功配对的事件才标记为 `hardware_sample_locked`。当前设备没有光电二极管或音频回环，因此不能把软件显�?音频 hook 当成已校准的物理起始时刻；界面中的“候选分离度”和“趋势分”也不是模型准确率�?

完整采集的会话目录会额外生成�?

- `event_codebook.xlsx` / `event_codebook.json`：硬件码、符号名、范式、阶段和中文含义的固定对照；
- `event_timeline.xlsx`：每个事件的直接时间戳、DCP 写入时间、LSL 时间、Trigger 通道采样点、配对状态和同步等级�?
- `events.jsonl`、`triggerbox_log.jsonl`、`lsl_markers.jsonl`、`hardware_triggers.jsonl`：不依赖 Excel 的原始审计记录；
- `synchronization_summary.json`：硬件事件缺失、乱序、发送失败及硬件/LSL差值摘要�?

硬件模式启动时会先发送校准码 `120`，实验员必须在博睿康采集界面确认收到后才能继续。串口固定为 115200�?N1、无流控；设备自描述必须包含 `TriggerBox.Titing`。正式采集前可运行全码表台架自检�?

```bash
neuroscope-trigger-bench --port COM5 --output trigger-bench-output
```

macOS/Linux 串口可写�?`/dev/cu.usbserial-xxx`。自检会逐个发送码表中的全部事件码并输�?`trigger_bench.csv/json`；仍需在博睿康端核对码值和顺序�?

听觉 ASSR 每个 trial 使用 10 秒安静基线和 20 �?1000 Hz 载波�?0 Hz 100% 调幅音；双耳、右耳、左耳三种条件以可复现伪随机顺序呈现，快�?完整预设每条件分别为 2/12 �?trial，共 6/36 个。听�?Oddball 使用 80% 标准音和 20% 偏差音，声音起始间隔�?1200�?600 ms，听到偏差音时按 `J`。两项听觉任务建议准备同一副舒适音量的有线双耳耳机。尚未校准设备时间戳与电脑音�?显示延迟时，Oddball �?N1/MMN 类差�?靶音晚期正波以及 Stroop �?N2 类趋势均只显示“ERP 时序待校准”，不输出确证数值�?
博睿康真机采集仍接收全导数据；本轮固定范式的在线波形、质量和结果只显�?`Fp1/Fpz/Fp2/T7/T8`（兼容旧命名 `T3/T4`），但“完整采集”自动生成的 BDF 始终保存设备返回的全部通道，不受五通道在线视图影响�?

## Windows 采集电脑

将仓库克隆或解压�?`neuroscope-eeg-workbench`，然后执行：

```cmd
py -3.12 -m venv .venv312
.venv312\Scripts\python.exe -m pip install -U pip setuptools wheel
.venv312\Scripts\python.exe -m pip install -r requirements-desktop.txt
.venv312\Scripts\python.exe -m neuroscope_eeg.desktop.app
```

安装完成后也可以直接双击 `start-neuroscope-desktop.bat`（或中文同名入口）。启动脚本会优先使用项目�?`.venv312`，其次使用当前激活的 conda 环境，再尝试常见位置中的 `oi` �?`omni`�?

### 使用现有 oi / omni 环境

可以直接使用采集电脑已有�?`oi` 环境，前提是该环境使�?Python 3.12，并已安装桌面依赖：

```cmd
conda activate oi
python -m pip install -r requirements-desktop.txt
python -m neuroscope_eeg.desktop.app
```

启动脚本依次寻找项目 `.venv312`、当前激活的 conda 环境、`oi` �?`omni`。博睿康还需要先运行 JellyFish，并保留本机 `oi-mi` 目录中的采集接口；这些厂商程序和本地采集代码不会上传到仓库。BrainCo 使用仓库内置�?BCIGo 适配器；Windows 采集电脑安装 SDK�?

```cmd
python -m pip install -r requirements-brainco.txt
```

测试强脑设备时再安装厂商 SDK 依赖�?

```cmd
.venv312\Scripts\python.exe -m pip install -r requirements-brainco.txt
```

博睿康需要先打开 JellyFish 实时转发，默认地址�?`127.0.0.1:8712`。强脑模式不再需�?`oi-mi` 路径；安�?`bcigo-sdk==1.0.2` 后，使用自动发现或填写设�?IP 与端口。该 SDK 当前提供 Windows x86-64 �?Linux wheel，macOS 只支持本工作台的模拟与回放模式�?

BrainCo 实时页会显示累计样本、缓冲样本和最近数据时间。波形经�?1�?5 Hz 显示滤波并逐通道独立缩放；官�?32 通道顺序和该处理只作用于 BrainCo，Neuracle 仍使用原有通道和显示链路�?

### test-头带（TD10 LSL�?

test-头带只接入桌面控制台。先�?iFET 上位机开�?LSL，并保证发布端与 NeuroScope 电脑位于同一局域网；随后双�?`启动-NeuroScope桌面控制�?bat`，选择“test-头带”，点击“查找设备”，再从下拉框选择要连接的头带。多台头带会按来�?ID 分开显示，例�?`ifet-td10-subject-001` �?`ifet-td10-subject-002`；程序连接时分别查找 `ifet-td10-subject-001:eeg` �?`ifet-td10-subject-002:eeg`。局域网发现不可用时，也可以直接在下拉框中填写来�?ID�?

TD10 适配器要�?EEG 流为固定 4 通道、`int32`，标称采样率�?125�?50�?00 �?1000 Hz。实际采样率�?LSL `StreamInfo` 读取，通道固定�?`EEG1/EEG2/EEG3/EEG4`。EEG-only 仍可用于预览；“完整采集”要求同一来源 ID �?`:eeg`、`:quality`、`:markers` 三流同时存在。Quality 固定保存 `Valid/DeviceSeq/DeviceFlag` 三列，包�?`Valid=0` 的行，绝不删除或压缩时间轴。LSL 数值是有符�?24 位原�?ADC counts；在硬件团队确认参考电压、PGA 增益、模拟前端比例和实际电极位置之前，程序不换算微伏、不应用微伏质量阈值，也不执行范式解码�?

完整采集写入 BDF 时，TD10 使用 `ADCcnt` 作为 BDF 的八字符物理维度，并让物理范围与有符�?24 位数字范围一致，从而保存原始计数值。会话目录还包含�?

- `lsl_timestamps.f64` / `lsl_timestamps_corrected.f64`：EEG �?Outlet 原始时间和加�?`time_correction()` 后的 Inlet 本机 LSL 时间�?
- `quality_raw.i32`、`quality_timestamps.f64`、`quality_timestamps_corrected.f64`：原�?Quality 三列及两套时间；
- `quality_aligned.i32`：按校正时间、半�?EEG 采样周期容差对齐到每�?EEG 样本�?Quality；未匹配行写�?`0,-1,-1`�?
- `ifet_markers.jsonl` / `neuroscope_markers.jsonl`：设�?Marker 原文�?NeuroScope 刺激 Marker�?
- `clock_corrections.jsonl`：各流定期测得的 LSL clock correction�?
- `events.csv`：以完整 EEG 校正时间轴最终重建的样本号、对齐误差和状态；
- `session.json`：来源扩展信息、计数、Quality 统计和固定的 `lsl_software_sync_uncalibrated` 时序状态�?

这些 `.f64`/`.i32` 文件均为小端、逐行连续二进制。TD10 当前固件不提供硬件采样时刻；发布端只�?chunk 最后一个样本打 `local_clock()` 时间，LSL 会按标称采样率回填同 chunk 之前的样本。因�?clock correction 只能统一两台电脑�?LSL 时钟，无法恢�?BLE/设备内部延迟或显�?音频的物理起始时刻。正式实验建议同时用 LabRecorder 记录 XDF 做独立对照；ERP 仍需光电二极管、音频回环或已知报文的硬�?Trigger 实测校准后才能解锁�?

协议虽定义了 9 通道 `:aux` 流，但当前文件没有给出九列的名称、单位和语义，所以本轮不�?AUX 写成可能误导的数据结构。取得厂家字段表后再接入�?

现场网络记录值为采集电脑 A `192.168.3.22`、JellyFish `8712`、同步器 `192.168.3.3`。这些值不构成 TriggerBox 网络协议；在明确 TCP/UDP、端口、报文和应答格式前，NeuroScope 不会向同步器发送猜测报文�?

## Streamlit 备用入口

桌面控制台是实时查看的推荐入口。TD10 LSL 仅在桌面控制台提供；需要浏览器访问其他数据源时仍可启动兼容版：

```cmd
.venv312\Scripts\streamlit.exe run streamlit_app.py
```

## 环境诊断

```cmd
.venv312\Scripts\neuroscope-doctor.exe
.venv312\Scripts\neuroscope-bundle.exe --output neuroscope-diagnostic.zip
```

也可以点击工作台侧栏的“生成诊断包”。回�?`neuroscope-diagnostic.zip` 即可排查 Windows 环境和回放链路�?

## 备用真机入口

博睿康：

```cmd
.venv312\Scripts\python.exe realtime_eeg_viewer.py --mode neuracle --host 127.0.0.1 --port 8712 --sfreq 1000 --n-channels 64 --stim-freqs 8,10,12,15
```

强脑�?

```cmd
.venv312\Scripts\python.exe realtime_eeg_viewer.py --mode brainco --sfreq 250 --n-channels 32 --stim-freqs 8,10,12,15
```

## 仓库内容

```text
neuroscope_eeg/       NeuroScope 主程序、采集适配、decoder 和界�?
neuroscope_eeg/assets/emotion_arousal 公司自有七类情绪图片、清单和授权说明
tests/                 自动化测�?
neuroscope_eeg/desktop 高刷新率桌面控制�?
streamlit_app.py       浏览器备用入�?
realtime_eeg_viewer.py 备用真机 CLI
pyproject.toml         安装与依赖配�?
requirements-brainco.txt
requirements-desktop.txt
start-neuroscope-desktop.bat
启动-NeuroScope桌面控制�?bat
docs/superpowers/specs/2026-07-11-neuroscope-design.md
docs/superpowers/specs/2026-07-12-neuroscope-rename-and-baseline-decoders-design.md
docs/superpowers/specs/2026-07-13-desktop-realtime-console-design.md
```

不要提交 `.venv312`、采集数据、受试者隐私数据、厂商密钥、未经许可的 SDK 或本地诊断输出�?
