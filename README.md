# NeuroScope

**多范式脑电可视化工作台**，用于博睿康 Neuracle、强脑 BrainCo、test-头带（TD10 LSL）、模拟 EEG 和 NPZ 回放。

NeuroScope 提供高刷新率桌面控制台、实时波形、频谱、信号质量、实验记录和多类开箱即用的即时基线 decoder。它适合在采集现场快速看趋势；未经个人标定的结果不是科研结论或医疗诊断。

## 已支持功能

- 数据源：模拟、NPZ 回放、博睿康 JellyFish 实时转发、强脑 BCIGo SDK 1.0.2、test-头带（TD10 LSL EEG/Quality/Markers）
- SSVEP：滤波组谐波 CCA，直接输出候选刺激频率
- 运动想象：C3/C4 的 µ/β 侧化趋势
- 视觉任务：枕区视觉响应；独立记录图像类别、目标是否出现、是否报告看见
- 注意力：theta/alpha/beta 会话内趋势分数
- 静息睁眼/闭眼：前额 alpha、theta、beta 和闭眼相对睁眼变化
- N-back 工作记忆：分 block 运行 0/1/2-back；完整采集每负荷 4×40、共 480 个正式试次，数字呈现 1500 ms 后空屏 500 ms，目标按 `J`、非目标按 `F`，仅练习反馈，block 间休息 25 秒
- Stroop 色词冲突：12 个练习后运行 30/120 个正式试次，一致按 `J`、不一致按 `F`，仅练习反馈
- 情绪图片唤醒：自有素材七类各 15 张，完整采集分成三个平衡区块，无逐图片评分
- 听觉 ASSR：双耳、右耳、左耳三种等量伪随机条件，使用 40 Hz 调幅音和 T3/T4 优先的频率跟随 SNR
- 听觉 Oddball：10 个练习后运行 100/300 个 80/20 标准音与偏差音，高音按 `J`
- 结果来源标识、候选分离度/趋势强度、缺失通道提示和信号质量保护
- 刺激窗口内置快速演示/完整采集预设、练习与正式阶段、内容提示、行为评分、自动结束和 `Esc` 安全退出
- 完整采集启动范式时自动创建独立目录，持续保存全导 BDF、事件 CSV 和会话 JSON；正常结束或中止时自动关闭文件
- BrainCo 官方 32 通道映射、干电极去漂移显示和数据新鲜度监控
- PySide6 + pyqtgraph 桌面控制台，默认 30 FPS，可选 20/60 FPS，并显示实际刷新率
- Windows 环境诊断包

视觉任务中的 `image_category`、`target_present` 和 `seen_reported` 是实验记录，不是 decoder 预测。没有带标签的个人训练数据时，NeuroScope 不会声称从 EEG 解出了任意图像类别。

## 本地运行（推荐桌面控制台）

需要 Python 3.12：

```bash
python3.12 -m venv .venv312
.venv312/bin/python -m pip install -U pip setuptools wheel
.venv312/bin/python -m pip install '.[desktop,dev]'
.venv312/bin/python -m neuroscope_eeg.desktop.app
```

启动后先选择“模拟”，确认波形持续移动、实际刷新率接近目标值，并检查各范式的即时结果。将模拟通道数设为 5 时，通道自动使用 `Fp1/Fp2/Fpz/T3/T4`。桌面控制台默认 30 FPS；采集电脑性能足够时可选择 60 FPS。

需要运行内置范式时，先填写受试者编号和记录目录、启动采集，再选择任务范式、协议预设和第二块显示器，点击“开始刺激”。`快速演示` 减少阶段时长或正式试次且不自动保存原始脑电；`完整采集` 使用 0/1/2-back 各 4×40（共 480 个正式试次）、120 个 Stroop、36 个 ASSR trial、300 个 Oddball 和全部 105 张情绪图片，并在刺激出现前创建 `<记录目录>/<受试者编号>/<时间_范式_full>/`。目录内的 `eeg.bdf` 是全导原始脑电，`events.csv` 是带 EEG 样本索引的事件，`session.json` 保存通道、采样率、有效样本数和完成/中止状态。练习事件会标记为 `is_practice=true`，不进入正式行为统计。按 `Esc` 可随时退出刺激；已采集数据会自动收尾保留，原有“导出事件 CSV”按钮仍可另存事件副本。

情绪图片流程包含内容提示、20 秒中性基线，以及每张图片前 1 秒注视、6 秒图片和 1 秒空屏，不进行效价或唤醒评分。七个细分类为愉悦、厌恶、恐惧、鼓舞、中性、悲伤、温情，每类 15 张；完整采集在第 35 和第 70 张后休息。素材为公司自有素材，不标注为 IAPS。按 `S` 可以跳过当前图片。

刺激事件支持两种同步模式：推荐的“博睿康硬件 + LSL”会先通过 NDE0001 串口按 DCP 立即事件命令 `01 E1 01 00 XX` 发码，再发布同一事件的通用 LSL Marker；“仅 LSL”用于没有 TriggerBox 的预览。视觉关键事件在 `frameSwapped` 后发码，听觉关键事件在首个音频输出缓冲回调发码。博睿康 Trigger/Event 通道里实际收到的码会按采样点回配，只有成功配对的事件才标记为 `hardware_sample_locked`。当前设备没有光电二极管或音频回环，因此不能把软件显示/音频 hook 当成已校准的物理起始时刻；界面中的“候选分离度”和“趋势分”也不是模型准确率。

完整采集的会话目录会额外生成：

- `event_codebook.xlsx` / `event_codebook.json`：硬件码、符号名、范式、阶段和中文含义的固定对照；
- `event_timeline.xlsx`：每个事件的直接时间戳、DCP 写入时间、LSL 时间、Trigger 通道采样点、配对状态和同步等级；
- `events.jsonl`、`triggerbox_log.jsonl`、`lsl_markers.jsonl`、`hardware_triggers.jsonl`：不依赖 Excel 的原始审计记录；
- `synchronization_summary.json`：硬件事件缺失、乱序、发送失败及硬件/LSL差值摘要。

硬件模式启动时会先发送校准码 `120`，实验员必须在博睿康采集界面确认收到后才能继续。串口固定为 115200、8N1、无流控；设备自描述必须包含 `TriggerBox.Titing`。正式采集前可运行全码表台架自检：

```bash
neuroscope-trigger-bench --port COM5 --output trigger-bench-output
```

macOS/Linux 串口可写成 `/dev/cu.usbserial-xxx`。自检会逐个发送码表中的全部事件码并输出 `trigger_bench.csv/json`；仍需在博睿康端核对码值和顺序。

听觉 ASSR 使用双耳、右耳单耳、左耳单耳三种等量条件，并按固定随机种子在每三个 trial 内各呈现一次。每个 trial 包含 5 秒安静基线和 20 秒 1000 Hz 载波、40 Hz 100% 调幅音；快速预设每条件 2 个、共 6 个 trial，完整预设每条件 12 个、共 36 个 trial，完整时长约 15 分钟。ASSR 起止事件记录 `condition`、`ear` 和 `trial_index`。实验前应校准左右耳机声压一致；未校准时可进行条件内 ASSR 分析，不应把左右差异解释为生理侧化。听觉 Oddball 使用 80% 标准音和 20% 偏差音，声音起始间隔为 1200–1600 ms，听到偏差音时按 `J`。尚未校准设备时间戳与电脑音频/显示延迟时，Oddball 的 N1/MMN 类差异/靶音晚期正波以及 Stroop 的 N2 类趋势均只显示“ERP 时序待校准”，不输出确证数值。

博睿康真机采集仍接收全导数据；本轮固定范式的在线波形、质量和结果只显示 `Fp1/Fpz/Fp2/T7/T8`（兼容旧命名 `T3/T4`），但“完整采集”自动生成的 BDF 始终保存设备返回的全部通道，不受五通道在线视图影响。

## Windows 采集电脑

将仓库克隆或解压到 `neuroscope-eeg-workbench`，然后执行：

```cmd
py -3.12 -m venv .venv312
.venv312\Scripts\python.exe -m pip install -U pip setuptools wheel
.venv312\Scripts\python.exe -m pip install -r requirements-desktop.txt
.venv312\Scripts\python.exe -m neuroscope_eeg.desktop.app
```

安装完成后也可以直接双击 `start-neuroscope-desktop.bat`（或中文同名入口）。启动脚本会优先使用项目的 `.venv312`，其次使用当前激活的 conda 环境，再尝试常见位置中的 `oi` 或 `omni`。

### 使用现有 oi / omni 环境

可以直接使用采集电脑已有的 `oi` 环境，前提是该环境使用 Python 3.12，并已安装桌面依赖：

```cmd
conda activate oi
python -m pip install -r requirements-desktop.txt
python -m neuroscope_eeg.desktop.app
```

启动脚本依次寻找项目 `.venv312`、当前激活的 conda 环境、`oi` 和 `omni`。博睿康还需要先运行 JellyFish，并保留本机 `oi-mi` 目录中的采集接口；这些厂商程序和本地采集代码不会上传到仓库。BrainCo 使用仓库内置的 BCIGo 适配器；Windows 采集电脑安装 SDK：

```cmd
python -m pip install -r requirements-brainco.txt
```

测试强脑设备时再安装厂商 SDK 依赖：

```cmd
.venv312\Scripts\python.exe -m pip install -r requirements-brainco.txt
```

博睿康需要先打开 JellyFish 实时转发，默认地址为 `127.0.0.1:8712`。强脑模式不再需要 `oi-mi` 路径；安装 `bcigo-sdk==1.0.2` 后，使用自动发现或填写设备 IP 与端口。该 SDK 当前提供 Windows x86-64 与 Linux wheel，macOS 只支持本工作台的模拟与回放模式。

BrainCo 实时页会显示累计样本、缓冲样本和最近数据时间。波形经过 1–45 Hz 显示滤波并逐通道独立缩放；官方 32 通道顺序和该处理只作用于 BrainCo，Neuracle 仍使用原有通道和显示链路。

### test-头带（TD10 LSL）

test-头带只接入桌面控制台。先在 iFET 上位机开启 LSL，并保证发布端与 NeuroScope 电脑位于同一局域网；随后双击 `启动-NeuroScope桌面控制台.bat`，选择“test-头带”，点击“查找设备”，再从下拉框选择要连接的头带。多台头带会按来源 ID 分开显示，例如 `ifet-td10-subject-001` 和 `ifet-td10-subject-002`；程序连接时分别查找 `ifet-td10-subject-001:eeg` 和 `ifet-td10-subject-002:eeg`。局域网发现不可用时，也可以直接在下拉框中填写来源 ID。

TD10 适配器要求 EEG 流为固定 4 通道、`int32`，标称采样率为 125、250、500 或 1000 Hz。实际采样率从 LSL `StreamInfo` 读取，通道固定为 `EEG1/EEG2/EEG3/EEG4`。EEG-only 仍可用于预览；“完整采集”要求同一来源 ID 的 `:eeg`、`:quality`、`:markers` 三流同时存在。Quality 固定保存 `Valid/DeviceSeq/DeviceFlag` 三列，包括 `Valid=0` 的行，绝不删除或压缩时间轴。LSL 数值是有符号 24 位原始 ADC counts；在硬件团队确认参考电压、PGA 增益、模拟前端比例和实际电极位置之前，程序不换算微伏、不应用微伏质量阈值，也不执行范式解码。

完整采集写入 BDF 时，TD10 使用 `ADCcnt` 作为 BDF 的八字符物理维度，并让物理范围与有符号 24 位数字范围一致，从而保存原始计数值。会话目录还包含：

- `lsl_timestamps.f64` / `lsl_timestamps_corrected.f64`：EEG 的 Outlet 原始时间和加上 `time_correction()` 后的 Inlet 本机 LSL 时间；
- `quality_raw.i32`、`quality_timestamps.f64`、`quality_timestamps_corrected.f64`：原始 Quality 三列及两套时间；
- `quality_aligned.i32`：按校正时间、半个 EEG 采样周期容差对齐到每个 EEG 样本的 Quality；未匹配行写为 `0,-1,-1`；
- `ifet_markers.jsonl` / `neuroscope_markers.jsonl`：设备 Marker 原文和 NeuroScope 刺激 Marker；
- `clock_corrections.jsonl`：各流定期测得的 LSL clock correction；
- `events.csv`：以完整 EEG 校正时间轴最终重建的样本号、对齐误差和状态；
- `session.json`：来源扩展信息、计数、Quality 统计和固定的 `lsl_software_sync_uncalibrated` 时序状态。

这些 `.f64`/`.i32` 文件均为小端、逐行连续二进制。TD10 当前固件不提供硬件采样时刻；发布端只给 chunk 最后一个样本打 `local_clock()` 时间，LSL 会按标称采样率回填同 chunk 之前的样本。因此 clock correction 只能统一两台电脑的 LSL 时钟，无法恢复 BLE/设备内部延迟或显示/音频的物理起始时刻。正式实验建议同时用 LabRecorder 记录 XDF 做独立对照；ERP 仍需光电二极管、音频回环或已知报文的硬件 Trigger 实测校准后才能解锁。

协议虽定义了 9 通道 `:aux` 流，但当前文件没有给出九列的名称、单位和语义，所以本轮不把 AUX 写成可能误导的数据结构。取得厂家字段表后再接入。

现场网络记录值为采集电脑 A `192.168.3.22`、JellyFish `8712`、同步器 `192.168.3.3`。这些值不构成 TriggerBox 网络协议；在明确 TCP/UDP、端口、报文和应答格式前，NeuroScope 不会向同步器发送猜测报文。

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

也可以点击工作台侧栏的“生成诊断包”。回传 `neuroscope-diagnostic.zip` 即可排查 Windows 环境和回放链路。

## 备用真机入口

博睿康：

```cmd
.venv312\Scripts\python.exe realtime_eeg_viewer.py --mode neuracle --host 127.0.0.1 --port 8712 --sfreq 1000 --n-channels 64 --stim-freqs 8,10,12,15
```

强脑：

```cmd
.venv312\Scripts\python.exe realtime_eeg_viewer.py --mode brainco --sfreq 250 --n-channels 32 --stim-freqs 8,10,12,15
```

## 仓库内容

```text
neuroscope_eeg/       NeuroScope 主程序、采集适配、decoder 和界面
neuroscope_eeg/assets/emotion_arousal 公司自有七类情绪图片、清单和授权说明
tests/                 自动化测试
neuroscope_eeg/desktop 高刷新率桌面控制台
streamlit_app.py       浏览器备用入口
realtime_eeg_viewer.py 备用真机 CLI
pyproject.toml         安装与依赖配置
requirements-brainco.txt
requirements-desktop.txt
start-neuroscope-desktop.bat
启动-NeuroScope桌面控制台.bat
docs/superpowers/specs/2026-07-11-neuroscope-design.md
docs/superpowers/specs/2026-07-12-neuroscope-rename-and-baseline-decoders-design.md
docs/superpowers/specs/2026-07-13-desktop-realtime-console-design.md
```

不要提交 `.venv312`、采集数据、受试者隐私数据、厂商密钥、未经许可的 SDK 或本地诊断输出。
