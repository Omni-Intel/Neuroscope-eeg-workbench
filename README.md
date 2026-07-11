# MI Control

MI Control 是给博睿康 Neuracle、强脑 BrainCo 和本地 EEG 回放使用的实时任务工作台。当前 A 版已经包含统一界面、模拟源、NPZ 回放、实时监控、信号质量、范式分析入口和诊断包。

## 当前状态

- A 版工作台入口：`streamlit_app.py`
- 可直接演示：模拟源、NPZ 回放、SSVEP、运动想象、视觉图像识别、注意力、情绪分类的特征展示
- 视觉图像任务已区分：`image_category`、`target_present`、`seen_reported`
- 真机采集：A 版工作台可选择博睿康和强脑，并复用旧 CLI 已验证过的设备接口
- 下一阶段：用 Windows 诊断包和两台设备实测结果继续加固真机适配

没有验证模型时，A 版只显示可审计特征，不输出“分类正确/看见目标/情绪类别”等结论。

## 在本机运行 A 版工作台

```bash
python3.12 -m venv .venv312
.venv312/bin/python -m pip install -U pip setuptools wheel
.venv312/bin/python -m pip install -e '.[dev]'
.venv312/bin/streamlit run streamlit_app.py
```

打开网页后先选“模拟”，点击“启动”。页面包含四个标签：

- 实时监控
- 信号质量
- 范式分析
- 记录

在 Windows 采集电脑上，博睿康需要先打开 JellyFish 实时转发；强脑需要先安装 `requirements-brainco.txt` 并确认 SDK 能发现设备。

## 打包发到 Windows 采集电脑

先不要发 `.venv312`、`.git`、`__pycache__`、`.pytest_cache`、`diagnostics` 这些本机生成目录。

建议发送这些文件和目录：

```text
README.md
pyproject.toml
requirements.txt
requirements-brainco.txt
streamlit_app.py
realtime_eeg_viewer.py
mi_control/
docs/superpowers/specs/2026-07-11-mi-control-design.md
docs/superpowers/plans/2026-07-11-mi-control-foundation.md
```

Windows 采集电脑上解压后执行：

```cmd
py -3.12 -m venv .venv312
.venv312\Scripts\python.exe -m pip install -U pip setuptools wheel
.venv312\Scripts\python.exe -m pip install -e .
.venv312\Scripts\streamlit.exe run streamlit_app.py
```

如果要测强脑 SDK，再装：

```cmd
.venv312\Scripts\python.exe -m pip install -r requirements-brainco.txt
```

## Windows 采集电脑先回传诊断包

A 版工作台左侧有“生成诊断包”按钮。也可以用命令：

```cmd
.venv312\Scripts\mi-control-doctor.exe
.venv312\Scripts\mi-control-bundle.exe --output mi-control-diagnostic.zip
```

把 `mi-control-diagnostic.zip` 发回 Mac 后，可以用其中的 `environment.json` 和 `simulated-replay.npz` 判断 Windows 环境是否一致。

## 旧真机 CLI 仍可保留作为备用

博睿康 JellyFish 转发：

```cmd
.venv312\Scripts\python.exe realtime_eeg_viewer.py --mode neuracle --host 127.0.0.1 --port 8712 --sfreq 1000 --n-channels 64 --stim-freqs 8,10,12,15
```

强脑 BrainCo：

```cmd
.venv312\Scripts\python.exe realtime_eeg_viewer.py --mode brainco --oi-mi-path "D:\oi-armi copy\oi-mi" --sfreq 250 --n-channels 32 --stim-freqs 8,10,12,15
```

这两条仍然依赖 Windows 上的设备软件、SDK 和 `oi-mi` 路径。A 版下一步会把它们迁移到统一工作台。
