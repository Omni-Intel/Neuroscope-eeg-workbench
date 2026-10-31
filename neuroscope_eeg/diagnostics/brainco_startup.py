"""Opt-in startup diagnostics. Does not record an experiment or suppress SDK errors."""
from __future__ import annotations

import argparse
from datetime import datetime
from importlib.metadata import version
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import zipfile

import numpy as np

from neuroscope_eeg.acquisition.vendor.brainco_acquirer import BrainCoAcquirer, _SAMPLE_RATE_TO_ENUM

LOG = logging.getLogger(__name__)
MODES = ("production", "unified", "verified-config", "stepwise", "legacy-mode")
REVISION = "2026-10-31-layout-startup-v3"


class StepwiseBrainCo(BrainCoAcquirer):
    def _start_stream_unified(self, parser):
        sdk, client = self._sdk, self._client
        self._startup_step("诊断：初始化 SDK 缓冲")
        sdk.set_cfg(max(int(self.metadata.sfreq * 60), 1024), max(256, int(self.metadata.sfreq)), 256)
        sdk.clear_eeg_buffer()
        self._step("建立数据连接与解析器", client.start_data_stream, parser)
        self._step("协商 EEG 数据格式", client.negotiate_eeg_stream)
        self._step("配置采样率、增益与 NORMAL 信号源", client.set_eeg_config,
                   getattr(sdk.EegSampleRate, _SAMPLE_RATE_TO_ENUM[int(self.metadata.sfreq)]),
                   sdk.EegSignalGain.GAIN_6, sdk.EegSignalSource.NORMAL)
        self._step("请求启动 EEG", client.start_eeg_stream)
        self._startup_step("诊断：等待实际 EEG 样本")
        self._wait_for_samples()

    def _step(self, label, method, *args):
        self._startup_step("诊断：" + label)
        result = self._run_sdk_call(method, *args)
        LOG.warning("Step returned: %s result=%r (return alone is not proof of device state)", label, result)
        return result


class LegacyModeBrainCo(StepwiseBrainCo):
    """No explicit extra negotiation; start_data_stream still performs SDK negotiation."""

    def _start_stream_unified(self, parser):
        sdk, client = self._sdk, self._client
        self._startup_step("诊断：传统模式入口，保留 SDK 内置握手")
        sdk.set_cfg(max(int(self.metadata.sfreq * 60), 1024), max(256, int(self.metadata.sfreq)), 256)
        sdk.clear_eeg_buffer()
        self._step("建立数据连接与解析器", client.start_data_stream, parser)
        # This public API still checks device responses. Never mask ACK failures.
        self._step("停止阻抗检测、配置并启动 NORMAL EEG", client.enable_eeg_stream_mode,
                   getattr(sdk.EegSampleRate, _SAMPLE_RATE_TO_ENUM[int(self.metadata.sfreq)]),
                   sdk.EegSignalGain.GAIN_6, sdk.EegSignalSource.NORMAL)
        self._startup_step("诊断：等待传统模式实际 EEG 样本")
        self._wait_for_samples()


class VerifiedConfigBrainCo(BrainCoAcquirer):
    def _start_stream_unified(self, parser):
        self._start_stream_verified(parser)


class OriginalUnifiedBrainCo(BrainCoAcquirer):
    def _start_stream_unified(self, parser):
        self._start_stream_sdk(parser)


def observe_samples(source, directory, seconds=30):
    """Keep an inspection sample and measure newly drained samples, not callback counts."""
    source.get_new_samples()  # Exclude startup backlog from the rate measurement.
    chunks = []
    device_ticks = []
    total = 0
    started = last_data = last_report = time.monotonic()
    reported_total = 0
    max_gap = 0.0
    try:
        while time.monotonic() - started < seconds:
            data, _ = source.get_new_samples()
            if data.ndim != 2 or data.shape[0] != 32 or not np.isfinite(data).all():
                raise RuntimeError("EEG 形状不是 32×样本数，或含非有限值")
            now = time.monotonic()
            if data.shape[1]:
                max_gap = max(max_gap, now - last_data)
                chunks.append(data.copy())
                ticks = np.asarray(getattr(source, "last_device_timestamps", []), dtype=np.float64)
                device_ticks.append(ticks.copy() if ticks.shape == (data.shape[1],) else
                                    np.full(data.shape[1], np.nan, dtype=np.float64))
                total += data.shape[1]
                last_data = now
            if now - last_report >= 1:
                LOG.warning("EEG interval=%.3fs new_samples=%d total=%d callback_total=%d raw_packets=%d",
                            now - last_report, total - reported_total, total,
                            source._callback_sample_count, source._raw_packet_count)
                last_report, reported_total = now, total
            time.sleep(.02)
    finally:
        if chunks:
            saved = np.concatenate(chunks, axis=1)
            sample_path = directory / "eeg-preview.npz"
            np.savez_compressed(sample_path, eeg=saved,
                                device_timestamps=np.concatenate(device_ticks),
                                configured_sfreq=source.metadata.sfreq)
            with np.load(sample_path, allow_pickle=False) as restored:
                if not np.array_equal(restored["eeg"], saved) or restored["configured_sfreq"].item() != source.metadata.sfreq:
                    raise RuntimeError("保存后的 EEG 文件回读校验失败")
            LOG.warning("Saved EEG verified: shape=%s sha256=%s", saved.shape,
                        hashlib.sha256(sample_path.read_bytes()).hexdigest())
    elapsed = time.monotonic() - started
    rate = total / elapsed
    metrics = dict(samples=total, elapsed_seconds=elapsed, observed_hz=rate,
                   configured_hz=source.metadata.sfreq, last_sample_age=time.monotonic() - last_data,
                   max_gap_seconds=max_gap, saved_file_verified=bool(chunks))
    LOG.warning("EEG observation: %s", metrics)
    (directory / "observation.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    if not total or max_gap > 2 or metrics["last_sample_age"] > 2 or not .8 <= rate / source.metadata.sfreq <= 1.2:
        raise RuntimeError(f"未观察到接近设定速率的持续 EEG 数据：{metrics}")
    return metrics


class CleanupMonitor(logging.Handler):
    """The adapter logs disconnect errors instead of raising them."""

    failed = False

    def emit(self, record):
        if "Failed to disconnect BrainCo TCP client cleanly" in record.getMessage():
            self.failed = True


def run_all(args):
    folder = args.log_dir / f"brainco-check-{datetime.now():%Y%m%d-%H%M%S-%f}"
    folder.mkdir(parents=True)
    results = []
    code = 1
    host, port = args.host, args.port
    try:
        for mode in MODES:
            directory = folder / mode
            directory.mkdir()
            command = [sys.executable, "-B", "-m", "neuroscope_eeg.diagnostics.brainco_startup",
                       "--mode", mode, "--sfreq", str(args.sfreq), "--seconds", str(args.seconds),
                       "--log-dir", str(directory.resolve())]
            if host:
                command += ["--host", host, "--port", str(port)]
            timeout = 150 + args.seconds
            print(f"Checking {mode} ... (up to {timeout} seconds)", flush=True)
            try:
                with (directory / "console.log").open("w", encoding="utf-8") as output:
                    child = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=timeout,
                                           env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                result_path = directory / "result.json"
                result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
                result.update(mode=mode, exit_code=child.returncode)
                results.append(result)
                # Once discovered, keep every subsequent attempt on that same headset.
                if not host and result.get("target"):
                    target_host, _, target_port = result["target"].rpartition(":")
                    if target_host and target_port.isdigit() and 0 < int(target_port) <= 65535:
                        host, port = target_host, int(target_port)
                if child.returncode == 0 and result.get("status") == "samples_received":
                    code = 0
                    break
                if child.returncode != 1 or result.get("status") != "failed":
                    # Timeout, native crash or uncertain cleanup: do not open another connection.
                    code = 2
                    break
            except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
                results.append(dict(mode=mode, error=str(exc), status="aborted"))
                code = 2
                break
            time.sleep(2)
    finally:
        (folder / "summary.json").write_text(json.dumps(dict(revision=REVISION, exit_code=code, attempts=results),
                                            ensure_ascii=False, indent=2), encoding="utf-8")
        archive = folder.with_suffix(".zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in folder.rglob("*"):
                if path.is_file():
                    bundle.write(path, path.relative_to(folder))
        print("收到持续 EEG 样本；仍需正式实验验收。" if code == 0 else
              "未通过数据检查；请提供诊断包。若发生超时/断开失败，先重启帽子再连接。", flush=True)
        print(f"Diagnostic bundle: {archive.resolve()}", flush=True)
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description="BrainCo SDK 2.1.2 启动诊断；先退出其他采集程序。不会保存实验。")
    parser.add_argument("--mode", choices=("all", *MODES), default="all")
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--sfreq", type=int, choices=tuple(_SAMPLE_RATE_TO_ENUM), default=250)
    parser.add_argument("--log-dir", type=Path, default=Path("logs"))
    parser.add_argument("--seconds", type=int, default=30, help="数据观察秒数，10～120，默认 30")
    args = parser.parse_args(argv)
    if bool(args.host) != bool(args.port) or args.port < 0 or args.port > 65535:
        parser.error("手动连接必须同时提供 --host 和有效 --port")
    if not 10 <= args.seconds <= 120:
        parser.error("--seconds 必须为 10～120")
    print(f"BrainCo diagnostic revision: {REVISION}", flush=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "all":
        return run_all(args)
    path = args.log_dir / f"brainco-startup-{args.mode}-{datetime.now():%Y%m%d-%H%M%S-%f}.log"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()], force=True)
    source = None
    code = 1
    result = dict(revision=REVISION, mode=args.mode, status="failed", python=sys.version, platform=platform.platform(),
                  executable=sys.executable)
    cleanup = CleanupMonitor()
    logging.getLogger().addHandler(cleanup)
    try:
        installed = version("bcigo-sdk")
        result["sdk_distribution_version"] = installed
        LOG.warning("executable=%s sdk=%s mode=%s", sys.executable, installed, args.mode)
        if installed != "2.1.2":
            raise RuntimeError("诊断要求 bcigo-sdk==2.1.2，不自动更换 SDK")
        import bcigo_sdk
        result["sdk_module"] = str(bcigo_sdk.__file__)
        result["sdk_binaries"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in Path(bcigo_sdk.__file__).parent.rglob("*.pyd")}
        cls = {"production": BrainCoAcquirer, "unified": OriginalUnifiedBrainCo, "stepwise": StepwiseBrainCo,
               "legacy-mode": LegacyModeBrainCo, "verified-config": VerifiedConfigBrainCo}[args.mode]
        source = cls(sfreq=args.sfreq, n_channels=32, brainco_addr=args.host, brainco_port=args.port,
                     auto_discover=not bool(args.host), start_retries=1, enable_trigger_sync=False)
        source.start_stream()
        result["metrics"] = observe_samples(source, args.log_dir, args.seconds)
        result["status"] = "samples_received"
        code = 0
    except Exception as exc:
        result["error"] = str(exc)
        LOG.exception("BrainCo startup diagnostic failed")
    finally:
        if source is not None:
            result.update(stage=source.startup_stage, target=source.startup_target)
            result["config_evidence"] = getattr(source, "config_evidence", [])
            try:
                source.stop_stream()
            except Exception:
                cleanup.failed = True
                LOG.exception("Diagnostic cleanup failed")
        if cleanup.failed:
            code = 2
            result["status"] = "cleanup_failed"
        logging.getLogger().removeHandler(cleanup)
        result["exit_code"] = code
        (args.log_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Log: {path.resolve()}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
