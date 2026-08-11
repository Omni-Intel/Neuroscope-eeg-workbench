# N-back 三负荷分块实施计划

## 目标

把现有单一 2-back 刺激升级为 0/1/2-back 三负荷协议。完整采集运行每负荷 4 blocks × 40 trials，共 480 trials；数字显示 1500 ms、空屏 500 ms；相邻 blocks 休息 25 秒；行为和事件按负荷及 block 可复核。

## 成功标准

- 纯协议测试证明完整预设精确生成 12 blocks、每 block 40 trials、总计 480 trials。
- 0/1/2-back 的 target 判定、上下文数字和固定 target 数正确且可复现。
- 刺激调度包含 1500 ms 数字、500 ms 空屏、5 秒规则页和 25 秒 block 休息。
- `J/F`、练习反馈、正式无反馈、漏答和首次按键规则保持。
- 事件和停止摘要能按负荷与 block 重建实验。
- 界面、记录 slug 和 decoder 使用“N-back 工作记忆”，且其他范式不回归。
- 定向测试和完整测试套件通过。

## 任务 1：协议模型与失败测试

修改：

- `tests/desktop/test_protocols.py`
- `neuroscope_eeg/desktop/protocols.py`

步骤：

1. 更新预设断言：快速演示每负荷 1 × 10，完整采集每负荷 4 × 40。
2. 增加 0/1/2-back 序列测试，验证 target 数、比较数字、无意外匹配、无相邻 target 和固定种子复现。
3. 增加 block 生成测试，验证顺序为四轮 `0,1,2`、完整索引和目标数字。
4. 增加调度测试，验证数字 1.5 秒、空屏 0.5 秒、规则页 5 秒和 block 休息 25 秒。
5. 运行 `pytest tests/desktop/test_protocols.py -q`，确认新增测试先失败。
6. 最小实现协议数据类、预设属性、序列生成器、block 生成器和调度生成器，直至测试通过。

## 任务 2：刺激窗口和行为统计

修改：

- `neuroscope_eeg/desktop/stimulus.py`
- `tests/desktop/test_protocols.py`

步骤：

1. 用纯协议调度替换当前单序列 `_nback_items`。
2. 在规则页显示当前负荷；0-back 同时显示指定目标数字。
3. 数字阶段开放 1500 ms 响应窗，空屏阶段关闭响应并完成漏答计分。
4. 在进入正式 block、休息和最终完成时发送 block 边界事件。
5. 维护全局及 0/1/2-back 分负荷的 trial、正确、反应时和遗漏计数。
6. 停止摘要加入每个负荷的扁平化行为指标。
7. 更新绘制文案，显示负荷、block 进度和总 trial 进度。
8. 运行 `pytest tests/desktop/test_protocols.py tests/desktop/test_console.py -q`。

## 任务 3：范式注册、记录与界面

修改：

- `neuroscope_eeg/paradigms/base.py`
- `neuroscope_eeg/decoders/baseline.py`
- `neuroscope_eeg/io/session_recorder.py`
- `neuroscope_eeg/desktop/app.py`
- `tests/paradigms/test_paradigms.py`
- `tests/io/test_session_recorder.py`
- `tests/desktop/test_console.py`

步骤：

1. 把用户可见范式名统一为“N-back 工作记忆”，内部 key 更新为 `working_memory_nback`。
2. 记录目录继续映射为 `nback`，避免改变既有文件组织。
3. 更新协议摘要为三负荷、block/trial、SOA、休息和预计时长。
4. 更新允许实时分析的 N-back 阶段。
5. decoder 名称和说明改为 N-back，并读取 0/1/2-back 分负荷行为指标。
6. 保留 TD10 原始 ADC 与未知电极映射的现有解码门禁。
7. 更新测试中的范式名称和记录断言。
8. 运行 `pytest tests/paradigms/test_paradigms.py tests/io/test_session_recorder.py tests/desktop/test_console.py -q`。

## 任务 4：分负荷 EEG block 指标

修改：

- `neuroscope_eeg/desktop/app.py`
- `neuroscope_eeg/decoders/baseline.py`
- `tests/paradigms/test_paradigms.py`

步骤：

1. 在正式 block 结束事件处从 180 秒滚动缓冲提取最后 80 秒正式数据。
2. 对已知前额通道计算 theta、alpha、beta block 功率，并按负荷累计。
3. 将各负荷完成 block 数及平均频带功率加入协议参考指标。
4. decoder 显示三个负荷的频带结果及 1/2-back 相对 0-back 的变化。
5. 无已知电极位置或数据不足时保持明确的不可解释/数据不足状态。
6. 增加合成数据测试，验证分负荷 payload 能生成方向正确的差值指标。

## 任务 5：文档与回归

修改：

- `README.md`

步骤：

1. 更新功能列表和完整采集说明中的 N-back 名称与 480-trial 流程。
2. 搜索并仅更新已失效的用户可见“2-back 工作记忆”引用；历史设计文档保持不变。
3. 运行 `pytest -q`。
4. 运行 `git diff --check`。
5. 检查 `git status --short`，确认未包含用户的 `tmp/` 内容。
