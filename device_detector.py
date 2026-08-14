from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DeviceInfo:
    gpu_available: bool
    gpu_name: Optional[str]
    gpu_vendor: Optional[str]
    webgpu_available: bool
    cpu_threads: Optional[int]
    device_memory_gb: Optional[float]
    recommended_mode: str
    reason: str


def analyze_device(
    gpu_available: bool,
    gpu_name: Optional[str],
    gpu_vendor: Optional[str],
    webgpu_available: bool,
    cpu_threads: Optional[int],
    device_memory_gb: Optional[float],
) -> DeviceInfo:
    """
    ブラウザから送られてきた端末情報をもとに
    推奨される生成方式を判定する。

    recommended_mode:
      - local_gpu
      - local_cpu
      - cloud
    """

    threads = cpu_threads or 0
    memory = device_memory_gb or 0

    # -----------------------------------------------------
    # GPU + WebGPU
    # -----------------------------------------------------

    if gpu_available and webgpu_available:
        return DeviceInfo(
            gpu_available=True,
            gpu_name=gpu_name,
            gpu_vendor=gpu_vendor,
            webgpu_available=True,
            cpu_threads=cpu_threads,
            device_memory_gb=device_memory_gb,
            recommended_mode="local_gpu",
            reason=(
                "GPUとWebGPUが利用可能です。"
                "この端末はローカルGPU生成の候補です。"
            ),
        )

    # -----------------------------------------------------
    # CPU
    # -----------------------------------------------------

    if threads >= 8 and memory >= 8:
        return DeviceInfo(
            gpu_available=gpu_available,
            gpu_name=gpu_name,
            gpu_vendor=gpu_vendor,
            webgpu_available=webgpu_available,
            cpu_threads=cpu_threads,
            device_memory_gb=device_memory_gb,
            recommended_mode="local_cpu",
            reason=(
                "十分なCPUスレッド数とメモリが検出されました。"
                "GPUが利用できない場合はローカルCPU生成の候補です。"
            ),
        )

    # -----------------------------------------------------
    # Cloud
    # -----------------------------------------------------

    return DeviceInfo(
        gpu_available=gpu_available,
        gpu_name=gpu_name,
        gpu_vendor=gpu_vendor,
        webgpu_available=webgpu_available,
        cpu_threads=cpu_threads,
        device_memory_gb=device_memory_gb,
        recommended_mode="cloud",
        reason=(
            "ローカル生成に十分な性能情報を確認できませんでした。"
            "クラウド生成を推奨します。"
        ),
    )


def mode_label(mode: str) -> str:
    labels = {
        "local_gpu": "⚡ ローカルGPU",
        "local_cpu": "🖥️ ローカルCPU",
        "cloud": "☁️ クラウド生成",
    }

    return labels.get(
        mode,
        "☁️ クラウド生成",
    )
