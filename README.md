# NeuroScope

**多范式脑电可视化工作台**，用于博睿康 Neuracle、强脑 BrainCo、模拟 EEG 和 NPZ 回放。

NeuroScope 提供高刷新率桌面控制台、实时波形、频谱、信号质量、实验记录和五类开箱即用的即时基线 decoder。它适合在采集现场快速看趋势；未经个人标定的结果不是科研结论或医疗诊断。

## 已支持功能

- 数据源：模拟、NPZ 回放、博睿康 JellyFish 实时转发、强脑 BrainCo SDK
- SSVEP：滤波组谐波 CCA，直接输出候选刺激频率
- 运动想象：C3/C4 的 µ/β 侧化趋势
- 视觉任务：枕区视觉响应；独立记录图像类别、目标是否出现、是否报告看见
- 注意力：theta/alpha/beta 会话内趋势分数
- 情绪：额叶 alpha 不对称和唤醒趋势
- 听觉 ASSR：40 Hz 调幅音刺激和 T3/T4 优先的频率跟随 SNR
- 听觉 Oddball：80/20 标准音与偏差音、行为命中率和软件事件记录
- 结果来源标识、候选分离度/趋势强度、缺失通道提示和信号质量保护
- 刺激窗口内置 SSVEP、运动想象、视觉 RSVP、心算注意力、基础情绪、听觉 ASSR 和听觉 Oddball
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

启动后先选择“模拟”，确认波形持续移动、实际刷新率接近目标值，并检查五个范式的即时结果。桌面控制台默认 30 FPS；采集电脑性能足够时可选择 60 FPS。

需要运行内置范式时，先启动采集，再选择任务范式和第二块显示器，点击“开始刺激”。不同范式只显示自己的参数：SSVEP 自动按显示器刷新率生成频率，运动想象使用左/右/静息提示，视觉使用 RSVP 目标检测，注意力使用静息/心算区块，情绪使用基础文字情境。按 `Esc` 可随时退出刺激，事件可导出为 CSV。

当前没有硬件 Trigger 时使用同机软件时间戳同步。界面中的“候选分离度”和“趋势分”不是模型准确率；SSVEP 只有完成带提示目标的试次后才显示本会话试次匹配率。

听觉 ASSR 使用 10 秒安静基线和 20 秒 40 Hz 调幅音，可用于观察频谱中的 40 Hz 跟随趋势。听觉 Oddball 使用 80% 标准音和 20% 偏差音，听到偏差音时按空格。没有硬件事件标记或尚未校准设备时间戳与电脑音频延迟时，Oddball 只展示行为与事件记录，并明确显示“ERP 时序待校准”。

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

启动脚本依次寻找项目 `.venv312`、当前激活的 conda 环境、`oi` 和 `omni`。博睿康还需要先运行 JellyFish，并保留本机 `oi-mi` 目录中的采集接口；这些厂商程序和本地采集代码不会上传到仓库。BrainCo 还需要安装 SDK：

```cmd
python -m pip install -r requirements-brainco.txt
```

测试强脑设备时再安装厂商 SDK 依赖：

```cmd
.venv312\Scripts\python.exe -m pip install -r requirements-brainco.txt
```

博睿康需要先打开 JellyFish 实时转发，默认地址为 `127.0.0.1:8712`。强脑模式需要填写采集电脑上的 `oi-mi` 路径，并确保 SDK 可以发现或连接设备。

BrainCo 实时页会显示累计样本、缓冲样本和最近数据时间。波形经过 1–45 Hz 显示滤波并逐通道独立缩放；官方 32 通道顺序和该处理只作用于 BrainCo，Neuracle 仍使用原有通道和显示链路。

## Streamlit 备用入口

桌面控制台是实时查看的推荐入口。需要浏览器访问时仍可启动兼容版：

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
.venv312\Scripts\python.exe realtime_eeg_viewer.py --mode brainco --oi-mi-path "D:\oi-mi" --sfreq 250 --n-channels 32 --stim-freqs 8,10,12,15
```

## 仓库内容

```text
neuroscope_eeg/       NeuroScope 主程序、采集适配、decoder 和界面
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
