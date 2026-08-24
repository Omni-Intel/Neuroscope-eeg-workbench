# NeuroScope 范式随机化与通道显示修复设计

## 目标

修复 N-back 中近似 target/non-target 交替、Stroop 中一致/不一致严格交替，以及固定范式实时图形不受左侧通道数控制的问题。任务时长、按键、条件数量和行为统计口径保持不变。

## N-back

- 完整 block 保持 40 个正式 trial、13 个 target；快速 block 保持 10 个正式 trial、3 个 target。
- 先生成条件序列，再生成满足条件的数字，non-target 不得形成意外 N-back 匹配。
- 允许相邻 target，但最多连续 2 个；non-target 最多连续 4 个。
- 严格 target/non-target 交替片段最多 6 个 trial。
- 每个 block 使用独立子 seed；相同 seed 可复现，不同 seed 生成不同序列。

## Stroop

- 一致和不一致 trial 各占一半，四种墨色在每种条件内尽量均衡。
- 条件序列不再通过两个列表交叉拼接；同一条件最多连续 3 次。
- CC、CI、IC、II 四种相邻条件转移次数相差不超过 1。
- 相邻 trial 不重复词义或墨色，避免直接刺激和反应启动。
- 相同 seed 可复现，不同 seed 生成不同序列。

## 会话 seed

N-back 和 Stroop 每次启动生成新的会话 seed。练习、正式序列和各 N-back block 从会话 seed 派生独立子 seed。seed 写入每个刺激事件，并由完整采集记录器写入 `session.json`。

## 通道显示

实时波形、频谱和质量数据使用采集源提供的完整通道，不再因范式选择被裁成五通道。范式 decoder 在分析入口单独调用五通道选择，因此仍可使用 `Fp1/Fpz/Fp2/T7/T8`，且不影响显示或原始记录。

## 验证

- 检查 N-back 数量、判定、连续限制、交替限制和 seed 可复现性。
- 检查 Stroop 条件/颜色平衡、转移平衡、相邻刺激、连续限制和 seed 可复现性。
- 检查固定范式实时刷新仍向绘图传入全部采集通道。
- 检查 decoder 五通道选择保持有效。
- 检查完整采集的 `session.json` 保存会话 seed。
