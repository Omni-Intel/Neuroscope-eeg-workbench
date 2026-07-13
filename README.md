# NeuroScope

**多范式脑电可视化工作台**，用于博睿康 Neuracle、强脑 BrainCo、模拟 EEG 和 NPZ 回放。

NeuroScope 提供实时波形、频谱、信号质量、实验记录和五类开箱即用的即时基线 decoder。它适合在采集现场快速看趋势；未经个人标定的结果不是科研结论或医疗诊断。

## 已支持功能

- 数据源：模拟、NPZ 回放、博睿康 JellyFish 实时转发、强脑 BrainCo SDK
- SSVEP：滤波组谐波 CCA，直接输出候选刺激频率
- 运动想象：C3/C4 的 µ/β 侧化趋势
- 视觉任务：枕区视觉响应；独立记录图像类别、目标是否出现、是否报告看见
- 注意力：theta/alpha/beta 会话内趋势分数
- 情绪：额叶 alpha 不对称和唤醒趋势
- 结果来源标识、基线置信度、缺失通道提示和信号质量保护
- BrainCo 官方 32 通道映射、干电极去漂移显示和数据新鲜度监控
- Windows 环境诊断包

视觉任务中的 `image_category`、`target_present` 和 `seen_reported` 是实验记录，不是 decoder 预测。没有带标签的个人训练数据时，NeuroScope 不会声称从 EEG 解出了任意图像类别。

## 本地运行

需要 Python 3.12：

```bash
python3.12 -m venv .venv312
.venv312/bin/python -m pip install -U pip setuptools wheel
.venv312/bin/python -m pip install '.[dev]'
.venv312/bin/streamlit run streamlit_app.py
```

启动后先选择“模拟”，确认五个范式的页面和即时结果正常。

## Windows 采集电脑

将仓库克隆或解压到 `neuroscope-eeg-workbench`，然后执行：

```cmd
py -3.12 -m venv .venv312
.venv312\Scripts\python.exe -m pip install -U pip setuptools wheel
.venv312\Scripts\python.exe -m pip install .
.venv312\Scripts\streamlit.exe run streamlit_app.py
```

测试强脑设备时再安装厂商 SDK 依赖：

```cmd
.venv312\Scripts\python.exe -m pip install -r requirements-brainco.txt
```

博睿康需要先打开 JellyFish 实时转发，默认地址为 `127.0.0.1:8712`。强脑模式需要填写采集电脑上的 `oi-mi` 路径，并确保 SDK 可以发现或连接设备。

BrainCo 实时页会显示累计样本、数据块数量和最近数据时间。波形经过 1–45 Hz 显示滤波并逐通道独立缩放；该处理只作用于 BrainCo，Neuracle 仍使用原有通道和显示链路。

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
streamlit_app.py       推荐启动入口
realtime_eeg_viewer.py 备用真机 CLI
pyproject.toml         安装与依赖配置
requirements-brainco.txt
docs/superpowers/specs/2026-07-11-neuroscope-design.md
docs/superpowers/specs/2026-07-12-neuroscope-rename-and-baseline-decoders-design.md
```

不要提交 `.venv312`、采集数据、受试者隐私数据、厂商密钥、未经许可的 SDK 或本地诊断输出。
