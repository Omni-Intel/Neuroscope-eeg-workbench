"""Compact response figures and Word sections, backed by exported numeric tables."""
from pathlib import Path

import numpy as np


def response_figures(report, destination):
    from matplotlib import pyplot as plt

    evidence = report["task"].get("response_evidence", {})
    spectra = evidence.get("spectra", [])
    if not spectra:
        return []
    destination = Path(destination)
    figures = []
    ssvep = report["run"]["paradigm"] == "SSVEP"
    colors = ["#286a96", "#b45d24", "#4a8051", "#8a569c"]

    def save(fig, name, title):
        path = destination / (name + ".png")
        fig.savefig(path, dpi=160)
        plt.close(fig)
        figures.append((title, path))

    if ssvep:
        chosen = [s for s in spectra if s["subset"] == "analyzable" and s["channel"] == "ROI"]
        fig, axes = plt.subplots(2, 1, figsize=(7, 4.8), layout="constrained", sharex=True)
        for s, color in zip(chosen, colors):
            f, p = np.array(s["frequency_hz"]), np.array(s["psd"])
            axes[0].semilogy(f, np.maximum(p, 1e-20), color=color, label=f"{s['condition']} Hz (n={s['n']})")
            axes[1].plot(f, np.array(s["snr_db"], dtype=float), color=color)
        for s, color in zip(chosen, colors):
            for h in (1, 2, 3):
                for ax in axes:
                    ax.axvline(float(s["condition"])*h, color=color, linestyle=":" if h > 1 else "--", alpha=.3, linewidth=.7)
        line = report["profile"].get("power_line_frequency")
        if isinstance(line, (float, int)):
            for ax in axes:
                ax.axvline(line, color="black", linestyle="-.", linewidth=.8, label="工频" if ax is axes[0] else None)
        axes[0].legend(fontsize=8, ncol=3)
        axes[0].set(ylabel="PSD (μV²/Hz)", title="各注视条件的枕区平均频谱")
        upper = max(65, max(float(s['condition'])*3+2 for s in chosen))
        axes[1].set(xlabel="频率 (Hz)", ylabel="局部 SNR (dB)", xlim=(4, min(upper, report['device']['sfreq']/2)))
        for ax in axes:
            ax.grid(alpha=.2)
        save(fig, "response-ssvep-spectrum", "SSVEP 条件频谱与 SNR 谱（虚线为基频，点线为二三次谐波）")
        values = [r for r in evidence["summary"] if r["subset"] == "analyzable" and r["metric"] == "snr_db"
                  and r["harmonic"] == 1 and r["channel"] != "ROI"]
        channels = list(dict.fromkeys(r["channel"] for r in values))
        conditions = list(dict.fromkeys(r["condition"] for r in values))
        matrix = np.array([[next((r["mean"] for r in values if r["condition"] == c and r["channel"] == ch), np.nan)
                            for ch in channels] for c in conditions], dtype=float)
        if matrix.size:
            fig, ax = plt.subplots(figsize=(7, 2.7), layout="constrained")
            im = ax.imshow(matrix, aspect="auto", cmap="viridis")
            ax.set_xticks(range(len(channels)), channels)
            ax.set_yticks(range(len(conditions)), [c + " Hz" for c in conditions])
            ax.set(title="逐通道基频 SNR（dB）；位置未经验证时不绘制头皮插值图")
            fig.colorbar(im, ax=ax, label="dB")
            save(fig, "response-channels", "SSVEP 逐通道响应分布")
    else:
        fig, axes = plt.subplots(1, 2, figsize=(7, 2.8), layout="constrained", sharey=True)
        for ax, ch in zip(axes, ("C3", "C4")):
            for condition, color in zip(("左手", "右手", "静息"), colors):
                for phase, style in (("fixation", "--"), ("task", "-")):
                    s = next((s for s in spectra if s["subset"] == "analyzable" and s["channel"] == ch
                              and s["condition"] == condition and s["phase"] == phase), None)
                    if s:
                        ax.semilogy(s["frequency_hz"], np.maximum(s["psd"], 1e-20), style, color=color,
                                    label=f"{condition} {'基线' if phase == 'fixation' else '任务'}")
            ax.set(title=ch, xlabel="频率 (Hz)", xlim=(4, 40))
            ax.grid(alpha=.2)
        axes[0].set_ylabel("PSD (μV²/Hz)")
        axes[1].legend(fontsize=7, ncol=2)
        save(fig, "response-mi-psd", "MI 条件功率谱（虚线为各试次准备基线，实线为任务）")
        tfrs = [r for r in evidence.get("time_frequency", []) if r["subset"] == "analyzable"]
        if tfrs:
            fig, axes = plt.subplots(3, 2, figsize=(7, 6), layout="constrained", sharex=True, sharey=True)
            for i, condition in enumerate(("左手", "右手", "静息")):
                for j, ch in enumerate(("C3", "C4")):
                    ax = axes[i, j]
                    row = next((r for r in tfrs if r["condition"] == condition and r["channel"] == ch), None)
                    if row:
                        im = ax.pcolormesh(row["time_sec"], row["frequency_hz"], np.asarray(row["change_db"], dtype=float),
                                           shading="auto", cmap="RdBu_r", vmin=-10, vmax=10)
                        ax.set_title(f"{condition} · {ch} · n={row['n']}", fontsize=9)
                    else:
                        ax.set_title(f"{condition} · {ch} · 无可用试次", fontsize=9)
                    if j == 0:
                        ax.set_ylabel("频率 (Hz)")
                    if i == 2:
                        ax.set_xlabel("想象阶段起点后秒数")
            fig.colorbar(im, ax=axes, label="相对每试次准备基线 (dB)；色阶固定 ±10")
            save(fig, "response-mi-tfr", "MI 时频响应（蓝为功率下降；显示完整窗中心，不推断精确起始潜伏期）")
        metrics = [r for r in evidence["trial_metrics"] if r["metric"] == "mu_lateral_db" and r["channel"] == "C3-C4"]
        if metrics:
            fig, ax = plt.subplots(figsize=(7, 2.8), layout="constrained")
            for i, (condition, color) in enumerate(zip(("左手", "右手", "静息"), colors)):
                rows = [r for r in metrics if r["condition"] == condition]
                for k, r in enumerate(rows):
                    ax.scatter(i + (k % 7 - 3)*.035, r["value"], color=color, marker="o" if r["clean"] else "x", alpha=.65, s=17)
            ax.axhline(.6, color="gray", linestyle="--", linewidth=.8)
            ax.axhline(-.6, color="gray", linestyle="--", linewidth=.8)
            ax.set_xticks(range(3), ["左手", "右手", "静息"])
            ax.set(ylabel="μ 功率变化 C3−C4 (dB)", title="单试次侧化差；圆点=幅值筛查保留，叉号=幅值标记")
            save(fig, "response-mi-lateral", "MI 侧化分布（±0.6 dB 为现有判别规则，非设备合格线）")

    blocks = evidence.get("block_summary", [])
    block_ids = sorted({r["block"] for r in blocks if r["block"] is not None})
    if len(block_ids) > 1:
        fig, axes = plt.subplots(1, 1 if ssvep else 2, figsize=(7, 2.8), layout="constrained", squeeze=False)
        for j, band in enumerate(["snr_db"] if ssvep else ["mu_erd_pct", "beta_erd_pct"]):
            ax = axes[0, j]
            keys = list(dict.fromkeys((r["condition"], r["channel"]) for r in blocks if r["metric"] == band))
            for idx, (condition, channel) in enumerate(keys):
                selected = [r for r in blocks if r["subset"] == "analyzable" and r["metric"] == band
                            and r["condition"] == condition and r["channel"] == channel]
                selected.sort(key=lambda r: r["block"])
                ax.plot([r["block"] for r in selected], [r["mean"] for r in selected], marker="o",
                        label=f"{condition} {channel}", color=colors[(idx if ssvep else idx//2) % len(colors)],
                        linestyle="-" if ssvep or channel == "C3" else "--")
            ax.set(xlabel="正式 block", ylabel="SNR (dB)" if ssvep else band.replace("_pct", " (%)"))
            ax.set_xticks(block_ids)
            ax.grid(alpha=.2)
            ax.legend(fontsize=7, ncol=2)
        save(fig, "response-blocks", "分组响应均值（各组样本量及离散度见 block_response.csv，不等于重测信度）")
    return figures


def write_retention_section(layout, report, shown):
    evidence = report["task"].get("response_evidence")
    if not evidence:
        return False
    doc, paragraph, table = layout.doc, layout.paragraph, layout.table
    doc.add_heading("试次完成与保留情况", 2)
    table(["条件", "计划", "观察", "完成", "可分析", "筛查后"], [
        (r["condition"], *(shown(r[k]) for k in ("planned", "observed", "completed", "analyzable", "clean")))
        for r in evidence["retention"]], [1.5, 1, 1, 1, 1, 1])
    paragraph("计划完成率以计划数为分母；可分析率以观察数为分母；幅值保留率以可分析数为分母。筛查后不代表已排除所有伪迹。")
    table(["条件", "计划完成率", "可分析率", "幅值保留率"], [
        (r["condition"], *(shown(r[k], True) for k in ("completion_fraction", "analyzable_fraction_observed", "clean_fraction_analyzable")))
        for r in evidence["retention"]], [1.5, 1.5, 1.5, 2])
    return True


def write_response_section(layout, report, figures, shown):
    evidence = report["task"].get("response_evidence")
    if not evidence:
        return
    paragraph, table, doc = layout.paragraph, layout.table, layout.doc
    ssvep = report["run"]["paradigm"] == "SSVEP"
    summary = evidence["summary"]

    def value(condition, channel, metric, subset="analyzable", harmonic=None):
        return next((r for r in summary if r["condition"] == str(condition) and r["channel"] == channel
                     and r["metric"] == metric and r["subset"] == subset and r["harmonic"] == harmonic), {})

    def estimate(row):
        if not row or row.get("mean") is None:
            return "不可用"
        ci = row["ci95"]
        return shown(row["mean"]) + (f" [{shown(ci[0])}, {shown(ci[1])}]" if ci else "（区间不可用）")

    if evidence["errors"]:
        paragraph(f"有 {len(evidence['errors'])} 个试次的补充响应计算失败，已在 response_errors.csv 保留原因；不补造数值，也不改变原固定分类结果。")
    if not summary:
        paragraph("没有可用的补充响应结果。")
        return
    conditions = [r["condition"] for r in evidence["retention"] if r["condition"] != "全部"]
    paragraph("以下响应均值及 95% 区间以本次可分析试次计算，另列幅值筛查后结果。区间为试次自助法描述，同一被试内试次可能相关，不代表跨被试或跨设备推断；不足 3 次不估计区间。")
    if ssvep:
        doc.add_heading("SSVEP 频率响应", 2)
        table(["目标 Hz", "范围", "基频 n", "基频 SNR", "二次 SNR", "三次 SNR"], [
            (condition, label, value(condition, "ROI", "snr_db", subset, 1).get("n", 0),
             *(estimate(value(condition, "ROI", "snr_db", subset, h)) for h in (1, 2, 3)))
            for condition in conditions for subset, label in (("analyzable", "可分析"), ("screened", "筛查后"))
        ], [.65, .7, .5, 1.55, 1.55, 1.55])
        paragraph("SNR 单位 dB，方括号为均值的 95% 区间；每个目标并列可分析与幅值筛查后结果。各谐波有效 n、功率（μV²）、背景频点数及逐通道明细保存于响应数据表。缺少足够背景频点时 SNR 不可用。")
        overlaps = evidence["harmonic_overlaps"]
        if overlaps:
            frequencies = sorted({r["frequency_hz"] for r in overlaps})
            paragraph("本次存在共享频率：" + "、".join(f"{f:g} Hz" for f in frequencies) + "。四目标同时闪烁，共享频率的响应归属不唯一，不能作为各目标相互独立的谐波证据。", "谐波解释")
        baseline = [r for r in evidence["baseline_comparison"] if r["channel"] == "ROI" and r["subset"] == "analyzable"]
        if baseline:
            table(["目标 Hz", "任务功率", "睁眼功率", "变化 dB", "任务 n／基线窗 n"], [
                (r["condition"], shown(r["task_power_uv2"]), shown(r["baseline_power_uv2"]), shown(r["change_db"]),
                 f"{r['n_trials']}／{r['n_baseline_windows']}") for r in baseline], [1, 1.2, 1.2, 1, 2.1])
            paragraph("功率单位 μV²；变化=10log10（任务平均功率／独立睁眼平均功率）。两者使用相同电极、窗长和频谱方法；视野、亮度及实际注视没有独立验证，因此仅作描述性对照。筛查后对照另存 baseline_comparison.csv。")
        else:
            paragraph(evidence["resting_baseline"].get("reason", "无匹配睁眼基线"), "静息对照不可用")
    else:
        doc.add_heading("MI 基线功率与响应", 2)
        table(["条件／通道", "μ 基线", "μ 任务", "β 基线", "β 任务"], [
            (f"{condition} {channel}", *(shown(value(condition, channel, key).get("mean")) for key in
                                        ("mu_baseline_power_uv2", "mu_task_power_uv2", "beta_baseline_power_uv2", "beta_task_power_uv2")))
            for condition in conditions for channel in ("C3", "C4")], [1.7, 1.2, 1.2, 1.2, 1.2])
        paragraph("功率单位 μV²。此表保留原 ERD 计算所用的完整基线／任务窗积分功率；基线为每试次准备阶段，不以实验开头的独立静息替代。条件 PSD 图另统一采用 1 秒 Welch 段便于频谱比较。")
        for band, title in (("mu", "μ"), ("beta", "β")):
            table([f"{title} 条件／通道", "可分析 n", "ERD %", "筛查后 n", "筛查后 ERD %"], [
                (f"{condition} {channel}", value(condition, channel, band+"_erd_pct").get("n", 0), estimate(value(condition, channel, band+"_erd_pct")),
                 value(condition, channel, band+"_erd_pct", "screened").get("n", 0), estimate(value(condition, channel, band+"_erd_pct", "screened")))
                for condition in conditions for channel in ("C3", "C4")], [1.4, .7, 1.85, .7, 1.85])
        table(["条件", "μ 对侧−同侧 dB", "β 对侧−同侧 dB"], [
            (condition, *(estimate(value(condition, "contra-ipsi", band+"_change_db")) for band in ("mu", "beta")))
            for condition in ("左手", "右手")], [1, 2.75, 2.75])
        paragraph("左手对侧为 C4，右手对侧为 C3；负的对侧−同侧 dB 差表示对侧相对抑制更强。各通道 dB 与同／对侧 ERD 明细另存；不以该差值单独判断设备质量。")
        recovery = [r for r in summary if r["metric"] == "beta_recovery_erd_pct" and r["subset"] == "analyzable"]
        if recovery:
            table(["条件／通道", "n", "恢复窗 β 变化 %"], [(f"{r['condition']} {r['channel']}", r["n"], estimate(r)) for r in recovery], [2, .75, 3.75])
            paragraph("恢复窗为休息开始后 0.5–1.5 秒，相对同一试次准备基线。该窗仅描述早期恢复，不保证覆盖 β 反弹峰值，也不以未见反弹判定设备差。")
        else:
            paragraph("有效休息窗不足或没有可分析试次，恢复期 β 变化不可用。")
    for label, path in figures:
        layout.figure(label, path)
    aggregation = "条件 PSD 先在每个试次内计算，再按条件取算术均值。"
    aggregation += ("ROI 先平均通道 PSD；频谱图的 SNR 是平均 PSD 的比值，谐波表是逐试次 dB 的均值，两者不可混用。"
                    if ssvep else "时频图保留所有试次共同覆盖的窗中心。")
    paragraph(aggregation + "不同网格仅在绘图汇总时插值。", "汇总口径")
    paragraph("分组图用于查看本次响应变化；响应离散度、逐条件绝对／相对带功率及筛查后的时频数据见 CSV/JSON。相对带功率统一以 1–40 Hz（不含 40 Hz）为分母。")


def write_classification_details(layout, task, shown, paradigm):
    layout.doc.add_heading("固定算法分类评价", 1)
    layout.table(["计分范围", "数据不可分析", "模型不确定", "判定覆盖率", "已判定准确率"], [
        (label, task[key]["data_unavailable"], task[key]["model_abstained"], shown(task[key]["coverage"], True), shown(task[key]["selective_accuracy"], True))
        for label, key in (("全部已观察", "all_trials"), ("可分析", "analyzable_trials"), ("幅值筛查后", "clean_trials"))], [1.4, 1.1, 1.1, 1.4, 1.5])
    summary = task["analyzable_trials"]
    layout.table(["真实条件", "Precision", "Recall", "F1"], [
        (label, shown(summary["precision_per_condition"][str(label)], True), shown(summary["per_condition"][str(label)], True),
         shown(summary["f1_per_condition"][str(label)])) for label in summary["labels"]], [1.6, 1.6, 1.6, 1.7])
    layout.paragraph("未判定在相应总体准确率和召回率中按未正确处理；已判定准确率只使用已给出类别的试次，必须与覆盖率一起看。没有预测为某类别时 Precision 不可用；真实类别缺失时不计算完整 macro F1 或平衡准确率。", "分类口径")
    method = ("固定 FBCCA 使用三个滤波子带和三次谐波，不训练个人模板、不选择本次最优参数；四目标名义随机水平为 25%。不设置低分拒判阈值，模型不确定通常为零。" if paradigm == "SSVEP" else
              "固定 μ 频带 C3−C4 功率变化 dB 差 >0.6 判左手、<−0.6 判右手，其余未判定。静息独立描述，不进入左右手二分类，名义随机水平为 50%。")
    layout.paragraph(method + "分类结果是任务信息可分性的辅助证据，不等于被试执行正确率或设备总体质量。")
