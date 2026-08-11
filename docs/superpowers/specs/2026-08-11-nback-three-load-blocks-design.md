# NeuroScope 0/1/2-back 三负荷分块设计

## 1. 目标与范围

将现有“2-back 工作记忆”升级为“N-back 工作记忆”，通过 0-back、1-back、2-back 三个负荷水平观察同一受试者在不同认知负荷下的行为与 EEG 频带趋势。

本次只扩展 N-back 的负荷和 block 结构。数字范围、按键、练习反馈、正式阶段无反馈、漏答计错、自动记录和现有统计口径均沿用当前 2-back。其他范式、采集源和记录格式不做无关改动。

## 2. 已确认参数

- 负荷条件：0-back、1-back、2-back。
- 每个负荷：4 blocks × 40 个正式 trials，共 160 trials。
- 完整采集：12 blocks、480 个正式 trials。
- block 顺序：`0 → 1 → 2` 为一轮，共重复 4 轮。
- 单 trial SOA：2000 ms。
- block 间休息：25 秒，位于用户要求的 20–30 秒范围内。
- 自动流程预计约 24 分钟；加上实验员说明、确认规则和练习准备后，整轮按约 30 分钟安排。

## 3. 保留的现有 2-back 规则

- 刺激使用数字 `0–9`。
- target 按 `J`，non-target 按 `F`。
- 每个 trial 只接受第一次有效按键。
- 漏答计为错误并产生 `omission` 事件。
- 练习阶段即时显示正确或错误反馈；正式阶段不显示逐 trial 反馈。
- 正式行为统计排除练习和上下文数字。
- 保留 10 秒静息基线。
- 保留总体正确率、平衡正确率、target/non-target 正确率、d-prime、中位反应时和遗漏数。

## 4. 三个负荷的判定规则

### 4.1 0-back

每个 0-back block 开始前显示该 block 的指定目标数字。当前数字等于指定数字时为 target，否则为 non-target。

四个 0-back blocks 使用可复现种子选择目标数字。目标数字写入 block 提示和每个正式 trial 的事件 payload。

### 4.2 1-back

当前数字与前一个数字一致时为 target，否则为 non-target。每个 block 在正式计分前呈现 1 个上下文数字；上下文数字不计入 40 个正式 trials。

### 4.3 2-back

当前数字与前两个数字一致时为 target，否则为 non-target。每个 block 在正式计分前呈现 2 个上下文数字；上下文数字不计入 40 个正式 trials。

### 4.4 目标数量

现有完整 2-back 的 target 比例是 40/120。新的每个 40-trial block 使用 13 个 target 和 27 个 non-target，保持接近原有三分之一的比例，同时保证每个 block 的条件组成一致。

序列生成器必须保证：

- target 数量准确；
- target 不相邻；
- 1-back 和 2-back 不产生未计划的偶然匹配；
- 相同参数和种子生成相同序列。

## 5. 时序与 block 流程

现有数字呈现时长保持 1500 ms。为满足 2000 ms SOA，每个 trial 在数字后增加 500 ms 空屏：

1. 数字呈现 1500 ms；
2. 空屏 500 ms；
3. 下一个数字立即开始。

反应窗继续与数字呈现重合，为数字出现后的 `0–1500 ms`。空屏期间不把按键记入前一 trial，也不提前记入下一 trial。

完整流程为：

1. 10 秒静息基线；
2. 0-back、1-back、2-back 各 10 个练习 trials，沿用练习反馈；
3. 正式 blocks 按 `0, 1, 2, 0, 1, 2, 0, 1, 2, 0, 1, 2` 运行；
4. 每个 block 前用 5 秒规则页显示负荷规则和当前进度；
5. 1/2-back block 的规则页后呈现必要的上下文数字；
6. 每个非末尾 block 后显示 25 秒休息倒计时；
7. 最后一个 block 完成后自动结束并保存。

## 6. 预设与界面

### 6.1 完整采集

完整采集使用已确认的 12 × 40、共 480 个正式 trials。

### 6.2 快速演示

快速演示保留短流程，用于检查显示、按键、事件和记录，不承担正式负荷分析。每个负荷运行 1 个 10-trial block，共 30 个正式 trials；每 block 使用 3 个 target。

### 6.3 文案

- 范式名称由“2-back 工作记忆”改为“N-back 工作记忆”。
- 协议摘要显示三个负荷、block 数、每 block trial 数、SOA、按键和预计总时长。
- 刺激页显示当前负荷、当前 block、总 block 进度和正式 trial 进度。
- 0-back 规则页明确显示当前目标数字。

## 7. 事件与保存

原有 `start`、`nback_trial`、`response`、`omission`、`stop` 事件继续保留。新增 block 边界事件：

- `nback_block_start`；
- `nback_block_end`；
- `nback_block_rest`。

N-back trial、response、omission 和 block 事件至少记录：

- `nback_level`：0、1 或 2；
- `block_index`：全程 0–11；
- `load_block_index`：当前负荷内 0–3；
- `trial_index`：当前 block 内 0–39；
- `formal_trial_index`：全程正式 trial 0–479；
- `symbol`；
- `comparison_symbol`，0-back 时为指定目标数字；
- `is_target`；
- `condition`；
- `correct_response`；
- `sequence_seed`；
- `is_practice`。

会话目录继续使用 `nback` slug，避免无必要地破坏既有记录目录约定。协议版本升级，保证离线分析能区分旧 2-back 和新三负荷数据。

## 8. 行为与 EEG 结果

行为结果先按 block 统计，再按 0/1/2-back 汇总：

- 正式 trial 数；
- 总体正确率和平衡正确率；
- target 正确率和 non-target 正确率；
- 命中率、误报率和 d-prime；
- target/non-target 正确试次中位反应时；
- 遗漏数。

EEG 结果按三个负荷分别显示 theta、alpha、beta 频带功率，并显示 1-back/2-back 相对 0-back 的会话内变化。结果措辞使用“负荷间趋势”，不预设三个负荷必须严格单调，也不包装成认知能力或医疗诊断。

已知前额电极位置时，可继续显示前额 theta 等区域指标。TD10 若仍只有 `EEG1–EEG4` 且电极位置、硬件比例未确认，只记录负荷与事件，不把原始 ADC counts 解释为特定脑区或确证性认知负荷结果。

## 9. 错误处理与中止

- `Esc` 中止时保留已完成 blocks、当前未完成 block 的事件和原始 EEG。
- 保存状态继续标记为 `aborted`，不能把不足 480 个正式 trials 的会话标记为完整完成。
- 记录失败时沿用现有行为立即停止实验，不能静默继续。
- 若采集数据不足以计算某个 block，行为结果仍保留，EEG 结果明确显示数据不足。

## 10. 自动化测试

- 三个负荷的 target 判定正确。
- 完整预设生成每负荷 4 × 40、总计 480 个正式 trials。
- 快速预设生成每负荷 1 × 10、总计 30 个正式 trials。
- 每个完整 block 恰有 13 个 target，且无相邻或意外 target。
- 1/2-back 上下文数字不计入正式 trial。
- 数字 1500 ms、空屏 500 ms、SOA 2000 ms、反应窗 1500 ms。
- 正式 block 顺序为四轮 `0 → 1 → 2`。
- 相邻正式 blocks 之间有 25 秒休息，最后一个 block 后无多余休息。
- trial 和响应事件包含完整负荷、block 与全程索引。
- 行为汇总能同时给出单 block、单负荷和全任务结果。
- 旧范式入口、记录 slug 和其他范式测试继续通过。

## 11. 手工验收

1. 使用快速演示确认 0/1/2-back 各运行一个 block。
2. 确认 0-back 规则页显示指定目标数字，1/2-back 显示对应规则。
3. 确认数字呈现 1500 ms，随后空屏 500 ms。
4. 分别测试正确、错误、漏答和重复按键。
5. 确认练习有反馈、正式阶段无反馈。
6. 确认 block 结束后出现 25 秒休息页及下一负荷提示。
7. 中途按 `Esc`，确认已采集 EEG 与事件可读取且状态为中止。
8. 完整流程结束后核对 12 blocks、每负荷 160 trials、总计 480 trials。
9. 核对结果按 0/1/2-back 分别显示行为与 EEG 负荷趋势。

## 12. 完成标准

- 原“2-back 工作记忆”入口被“N-back 工作记忆”替代。
- 完整采集可靠执行 0/1/2-back 各 4 × 40，共 480 个正式 trials。
- 单 trial SOA 为 2000 ms，block 间休息为 25 秒，整轮目标时长约 30 分钟。
- 现有 2-back 的刺激、响应、反馈、记录和中止规则在三个负荷中保持一致。
- 事件足以按负荷和 block 重建实验，并能生成分负荷行为与 EEG 趋势。
- 所有新增测试和既有测试通过。
