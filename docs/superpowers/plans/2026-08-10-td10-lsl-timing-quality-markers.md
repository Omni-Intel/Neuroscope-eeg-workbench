# TD10 LSL 时间轴、Quality 与 Markers 实现计划

## 成功标准

- 原 TD10 EEG 单流分支以非快进方式合并并保留作者；
- EEG-only 可预览，完整采集必须具备 EEG、Quality、Markers；
- 原始与校正后的 EEG/Quality LSL 时间均可追溯；
- `Valid=0` 不被删除，Quality 可确定性对齐到 EEG；
- NeuroScope 事件通过 LSL 时钟发布和记录；
- `events.csv` 依据完整校正时间轴生成样本号；
- UI/诊断包显示 LSL 健康状态；
- TD10 始终保持物理时序未校准，所有回归测试通过。

## 任务 1：合并实验性 TD10 分支并建立基线

涉及：Git 历史、全仓测试。

1. 确认 `main` 工作区干净。
2. 执行 `git merge --no-ff origin/feat/test-headband-td10-lsl`。
3. 运行：

   ```bash
   .venv312/bin/python -m pytest -q
   .venv312/bin/python -m ruff check neuroscope_eeg tests
   ```

4. 验证原作者提交仍在历史中，merge commit 位于 `main`。

## 任务 2：先定义并测试 TD10 sidecar 数据契约

涉及：

- `neuroscope_eeg/acquisition/td10_lsl.py`
- `tests/acquisition/test_td10_lsl.py`

先写失败测试，覆盖：

- Quality 三通道协议校验；
- Markers 单字符串通道协议校验；
- EEG/Quality 原始时间戳、clock correction 和校正时间；
- `Valid/DeviceSeq/DeviceFlag` 原值保留；
- Marker 原始字符串保留；
- companion 缺失时状态降级；
- `drain_sidecars()` 清空且不会重复返回；
- DeviceSeq 回绕、重复和异常增量统计。

实现小型不可变数据类型：

- EEG timing batch；
- Quality batch；
- iFET marker；
- NeuroScope marker；
- clock-correction sample；
- sidecar drain result。

## 任务 3：扩展 TD10LSLSource 为三流接收器

涉及：

- `neuroscope_eeg/acquisition/td10_lsl.py`
- `tests/acquisition/test_td10_lsl.py`

实现：

1. EEG 为必需流；Quality 和 Markers 为 companion 流。
2. 精确按 `<base>:eeg|quality|markers` 解析。
3. EEG、Quality 批量读取，Markers 非阻塞批量读取。
4. 每个流定期获取 `time_correction()`。
5. 主 `EEGChunk.timestamps` 使用校正到 Inlet 本机 LSL 时钟的时间；sidecar 同时保留 Outlet 原始时间戳。
6. 统计有效率、时间间隔、有效采样率、DeviceSeq 和最近 correction。
7. 缺 companion 时继续 EEG 预览，但 `companions_ready=False`。

验证：TD10 单元测试和既有 acquisition 测试通过。

## 任务 4：新增 NeuroScope Marker Outlet

涉及：

- `neuroscope_eeg/acquisition/td10_lsl.py`
- `neuroscope_eeg/desktop/app.py`
- `tests/acquisition/test_td10_lsl.py`
- `tests/desktop/test_console.py`

先写失败测试，覆盖稳定 JSON 字段和 LSL 时间戳。

实现：

1. TD10 刺激会话开始时创建独立 Marker Outlet；
2. 每个 `StimulusEvent` 使用 `pylsl.local_clock()`；
3. 推送 Marker 的同时写入 source sidecar；
4. 会话结束释放 Outlet；
5. 非 TD10 刺激行为不变。

## 任务 5：让 SessionController 转发 sidecar

涉及：

- `neuroscope_eeg/core/session.py`
- `tests/core/test_session_stats.py` 或新增针对性测试

先写失败测试：

- 支持 sidecar 的 source 每轮都被 drain；
- 有 recorder 时 sidecar 只提交一次；
- 无 recorder 时 sidecar 被安全丢弃但 source 统计保留；
- 普通 source/recorder 不受影响。

实现显式小协议，不在控制器中依赖 TD10 具体类。

## 任务 6：流式持久化时间轴、Quality、Markers 和 correction

涉及：

- `neuroscope_eeg/io/session_recorder.py`
- `tests/io/test_session_recorder.py`

先写失败测试，验证二进制文件的 dtype、字节序、行数和值。

实现后台队列写入：

- `lsl_timestamps.f64`：EEG 原始时间；
- `lsl_timestamps_corrected.f64`：EEG 校正时间；
- `quality_raw.i32`；
- `quality_timestamps.f64`：Quality 原始时间；
- `quality_timestamps_corrected.f64`；
- `ifet_markers.jsonl`；
- `neuroscope_markers.jsonl`；
- `clock_corrections.jsonl`。

收尾时：

1. 原子关闭 sidecar；
2. 检查 EEG/BDF/时间戳数量；
3. 用校正后的时间和半采样周期容差生成 `quality_aligned.i32`；
4. 更新 `session.json` 的完整统计；
5. 任一权威文件失败则会话为 error。

## 任务 7：依据完整时间轴重建事件样本号

涉及：

- `neuroscope_eeg/desktop/protocols.py`
- `neuroscope_eeg/desktop/app.py`
- `neuroscope_eeg/io/session_recorder.py`
- `tests/io/test_session_recorder.py`

先写失败测试：

- 精确命中、最近邻、左右边界；
- 超半采样周期拒绝；
- 非单调时间轴拒绝；
- 不再回退 `submitted_samples`；
- 原子重写失败保留原始事件与 error 状态。

`events.csv` 新增：

- `lsl_time`
- `alignment_method`
- `alignment_error_ms`
- `alignment_status`

完整会话结束后再原子生成权威样本号。

## 任务 8：完整采集门禁与桌面诊断

涉及：

- `neuroscope_eeg/desktop/app.py`
- `neuroscope_eeg/diagnostics/environment.py`
- `tests/desktop/test_console.py`
- `tests/diagnostics/test_environment.py`

实现：

- EEG-only 允许预览；
- TD10 companion 未齐全时禁用完整采集/刺激并给出缺失流；
- 展示三流状态、Valid 比例、有效率、gap、DeviceSeq 异常和 correction；
- 诊断真实导入 pylsl/liblsl，而不只检查 `find_spec`；
- 固定显示 `LSL 软件同步未完成物理校准`；
- 不启用微伏质量阈值或 decoder。

## 任务 9：真实 pylsl 集成测试与文档

涉及：

- 新增 `tests/integration/test_td10_lsl_integration.py`
- `README.md`
- `requirements-desktop.txt` 或 `pyproject.toml`（仅在必要时）

实现本机 Outlet→Inlet 测试；pylsl/liblsl 不可用时明确 skip。

README 说明：

- 三流要求；
- 记录文件和读取方法；
- LSL 软件同步边界；
- LabRecorder/XDF 对照建议；
- AUX 暂不接入的协议缺失原因。

## 任务 10：最终验证

运行：

```bash
.venv312/bin/python -m pytest -q
.venv312/bin/python -m ruff check neuroscope_eeg tests
git diff --check
```

检查：

- 工作区只包含本任务相关修改；
- `main` 保留原 TD10 作者提交；
- 没有推送远端；
- README、UI 和 session.json 均不声称 ERP 已校准。
