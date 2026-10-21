"""Windows device template library for profile personas.

Every template is a real, believable Windows machine (laptop or desktop):
its GPU reports the vendor/renderer strings Chromium actually exposes via
WebGL (``ANGLE (<vendor>, <model> (0x<device-id>) Direct3D11 ...)``), its
screen is a real shipping resolution, and its core count / memory bucket
match the paired CPU. Applying a template pins those fields onto a profile
through ``POST /api/profiles/{id}/apply-device-template``.

The library is data only: no kernel behaviour is touched.
"""

from __future__ import annotations

import hashlib
import random
import re
from typing import Any

# Family key -> human-readable label. Families exist so the API can filter.
FAMILIES: dict[str, str] = {
    "nvidia-rtx40": "NVIDIA RTX 40 系",
    "nvidia-rtx30": "NVIDIA RTX 30 系",
    "nvidia-gtx16": "NVIDIA GTX 16 系",
    "nvidia-rtx20": "NVIDIA RTX 20 系",
    "intel-igpu": "Intel 核显 / Arc",
    "amd-radeon": "AMD Radeon",
    "qualcomm": "高通 Snapdragon",
}

# Only resolutions the template library may use.
ALLOWED_SCREENS: frozenset[tuple[int, int]] = frozenset({
    (1920, 1080), (1366, 768), (1536, 864), (1600, 900),
    (2560, 1440), (2880, 1800), (3840, 2160), (1440, 900), (1680, 1050),
})

# Chrome's deviceMemory only ever reports these buckets.
MEMORY_BUCKETS = (4, 8)

# CPU name -> physical+logical core count (navigator.hardwareConcurrency).
CPU_CORES: dict[str, int] = {
    "Intel i3-10100F": 4,
    "Intel i5-8250U": 4,
    "Intel i5-9400": 6,
    "Intel i5-9400F": 6,
    "Intel i5-10300H": 4,
    "Intel i5-10400F": 6,
    "Intel i5-11320H": 4,
    "Intel i5-1135G7": 4,
    "Intel i5-11400H": 6,
    "Intel i5-1165G7": 4,
    "Intel i5-1235U": 10,
    "Intel i5-12400": 6,
    "Intel i5-12400F": 6,
    "Intel i5-12450H": 8,
    "Intel i5-13400": 10,
    "Intel i5-13400F": 10,
    "Intel i5-1340P": 12,
    "Intel i5-13420H": 8,
    "Intel i5-13500H": 12,
    "Intel i7-8550U": 4,
    "Intel i7-9700": 8,
    "Intel i7-9750H": 6,
    "Intel i7-10750H": 6,
    "Intel i7-1165G7": 4,
    "Intel i7-1255U": 10,
    "Intel i7-12700": 12,
    "Intel i7-12700F": 12,
    "Intel i7-12700H": 14,
    "Intel i7-13650HX": 14,
    "Intel i7-13700": 16,
    "Intel i7-13700H": 14,
    "Intel i7-13700K": 16,
    "Intel i7-13700KF": 16,
    "Intel i7-14650HX": 16,
    "Intel i7-14700HX": 20,
    "Intel i9-12900HX": 16,
    "Intel i9-13900K": 24,
    "Intel i9-13900KF": 24,
    "Intel i9-13900HX": 24,
    "Intel i9-13980HX": 24,
    "Intel i9-14900K": 24,
    "Intel i9-14900HX": 24,
    "Intel Core Ultra 5 125H": 14,
    "Intel Core Ultra 7 155H": 16,
    "AMD R5 3600": 6,
    "AMD R5 5500U": 6,
    "AMD R5 5600": 6,
    "AMD R5 6600H": 6,
    "AMD R5 7500F": 6,
    "AMD R5 7535HS": 6,
    "AMD R7 5700U": 8,
    "AMD R7 6800H": 8,
    "AMD R7 7700": 8,
    "AMD R7 7735H": 8,
    "AMD R7 7735HS": 8,
    "AMD R7 7745HX": 12,
    "AMD R7 7800X3D": 8,
    "AMD R7 7840H": 8,
    "AMD R7 7840HS": 8,
    "AMD R7 7840U": 8,
    "AMD R7 8845H": 8,
    "AMD R9 6900HX": 8,
    "AMD R9 7940HS": 8,
    "AMD R9 7940HX": 16,
    "AMD R9 7945HX": 16,
    "Qualcomm Snapdragon X Elite": 12,
}

_VENDOR_WORD = {"nvidia": "NVIDIA", "intel": "Intel", "amd": "AMD", "qualcomm": "Qualcomm"}


def _gpu_vendor(vendor_key: str) -> str:
    """Chromium's UNMASKED_VENDOR_WEBGL string on Windows."""
    return f"Google Inc. ({_VENDOR_WORD[vendor_key]})"


def _gpu_renderer(vendor_key: str, gpu_model: str, devid_hex: str) -> str:
    """Chromium's UNMASKED_RENDERER_WEBGL string on Windows (ANGLE/D3D11)."""
    word = _VENDOR_WORD[vendor_key]
    if vendor_key == "nvidia":
        body = f"NVIDIA {gpu_model}"
    elif vendor_key == "intel":
        body = f"Intel(R) {gpu_model}"
    elif vendor_key == "amd":
        body = f"AMD {gpu_model}"
    else:
        body = f"Qualcomm(R) {gpu_model}"
    return f"ANGLE ({word}, {body} (0x{int(devid_hex, 16):08X}) Direct3D11 vs_5_0 ps_5_0, D3D11)"


# (family, gpu_key, gpu_model, vendor_key, devid_hex, machine_name, cpu_name,
#  [(screen_w, screen_h, device_scale_factor, device_memory), ...])
_SPECS: list[tuple] = [
    # ── NVIDIA RTX 40 系 ──────────────────────────────────────────────────
    ("nvidia-rtx40", "rtx4050-laptop", "GeForce RTX 4050 Laptop GPU", "nvidia", "28A1",
     "华硕天选5", "Intel i7-13650HX", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx40", "rtx4050-laptop", "GeForce RTX 4050 Laptop GPU", "nvidia", "28A1",
     "联想小新16", "Intel i5-13420H", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx40", "rtx4060-laptop", "GeForce RTX 4060 Laptop GPU", "nvidia", "28A0",
     "联想拯救者 Y7000P", "Intel i7-14650HX", [(1920, 1080, 1, 8), (2560, 1440, 1.25, 8)]),
    ("nvidia-rtx40", "rtx4060-laptop", "GeForce RTX 4060 Laptop GPU", "nvidia", "28A0",
     "惠普暗影精灵10", "Intel i7-14700HX", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx40", "rtx4060-laptop", "GeForce RTX 4060 Laptop GPU", "nvidia", "28A0",
     "华硕天选5 Pro", "AMD R7 8845H", [(2560, 1440, 1.25, 8)]),
    ("nvidia-rtx40", "rtx4060-laptop", "GeForce RTX 4060 Laptop GPU", "nvidia", "28A0",
     "戴尔 G16", "Intel i9-13900HX", [(2560, 1440, 1.25, 8)]),
    ("nvidia-rtx40", "rtx4060-laptop", "GeForce RTX 4060 Laptop GPU", "nvidia", "28A0",
     "机械革命蛟龙16", "Intel i7-14650HX", [(2560, 1440, 1.25, 8)]),
    ("nvidia-rtx40", "rtx4060-laptop", "GeForce RTX 4060 Laptop GPU", "nvidia", "28A0",
     "联想拯救者 R9000P", "AMD R9 7945HX", [(2560, 1440, 1.25, 8)]),
    ("nvidia-rtx40", "rtx4060-laptop", "GeForce RTX 4060 Laptop GPU", "nvidia", "28A0",
     "ROG 魔霸新锐", "Intel i7-13650HX", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx40", "rtx4060", "GeForce RTX 4060", "nvidia", "2882",
     "组装台式机", "Intel i5-13400F", [(1920, 1080, 1, 8), (2560, 1440, 1, 8)]),
    ("nvidia-rtx40", "rtx4060", "GeForce RTX 4060", "nvidia", "2882",
     "组装台式机", "AMD R5 7500F", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx40", "rtx4060ti", "GeForce RTX 4060 Ti", "nvidia", "2803",
     "组装台式机", "AMD R7 7800X3D", [(2560, 1440, 1, 8), (3840, 2160, 1.5, 8)]),
    ("nvidia-rtx40", "rtx4070-laptop", "GeForce RTX 4070 Laptop GPU", "nvidia", "2820",
     "ROG 魔霸7 Plus", "AMD R9 7940HX", [(2560, 1440, 1.25, 8), (1920, 1080, 1, 8)]),
    ("nvidia-rtx40", "rtx4070-laptop", "GeForce RTX 4070 Laptop GPU", "nvidia", "2820",
     "联想拯救者 Y9000P", "Intel i9-14900HX", [(2560, 1440, 1.25, 8)]),
    ("nvidia-rtx40", "rtx4070-laptop", "GeForce RTX 4070 Laptop GPU", "nvidia", "2820",
     "惠普暗影精灵10", "Intel i9-14900HX", [(2560, 1440, 1.25, 8)]),
    ("nvidia-rtx40", "rtx4070", "GeForce RTX 4070", "nvidia", "2786",
     "组装台式机", "Intel i7-13700KF", [(2560, 1440, 1, 8), (3840, 2160, 1.5, 8)]),
    ("nvidia-rtx40", "rtx4070", "GeForce RTX 4070", "nvidia", "2786",
     "组装台式机", "AMD R7 7800X3D", [(2560, 1440, 1, 8)]),
    ("nvidia-rtx40", "rtx4070ti", "GeForce RTX 4070 Ti", "nvidia", "2782",
     "组装台式机", "Intel i9-13900K", [(2560, 1440, 1, 8), (3840, 2160, 1.5, 8)]),
    ("nvidia-rtx40", "rtx4080-laptop", "GeForce RTX 4080 Laptop GPU", "nvidia", "27E0",
     "ROG 枪神8", "Intel i9-14900HX", [(2560, 1440, 1.25, 8)]),
    ("nvidia-rtx40", "rtx4080", "GeForce RTX 4080", "nvidia", "2704",
     "组装台式机", "Intel i9-13900KF", [(2560, 1440, 1, 8), (3840, 2160, 1.5, 8)]),
    ("nvidia-rtx40", "rtx4090-laptop", "GeForce RTX 4090 Laptop GPU", "nvidia", "2757",
     "ROG 冰刃7", "Intel i9-13980HX", [(2560, 1440, 1.25, 8)]),
    ("nvidia-rtx40", "rtx4090", "GeForce RTX 4090", "nvidia", "2684",
     "组装台式机", "Intel i9-14900K", [(2560, 1440, 1, 8), (3840, 2160, 1.5, 8)]),
    # ── NVIDIA RTX 30 系 ──────────────────────────────────────────────────
    ("nvidia-rtx30", "rtx3050-laptop", "GeForce RTX 3050 Laptop GPU", "nvidia", "25A2",
     "联想拯救者 R7000", "AMD R7 7840H", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx30", "rtx3050-laptop", "GeForce RTX 3050 Laptop GPU", "nvidia", "25A2",
     "惠普暗影精灵9", "Intel i5-13500H", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx30", "rtx3050-laptop", "GeForce RTX 3050 Laptop GPU", "nvidia", "25A2",
     "神舟战神", "Intel i5-12450H", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx30", "rtx3050ti-laptop", "GeForce RTX 3050 Ti Laptop GPU", "nvidia", "25A0",
     "戴尔 G15", "Intel i7-12700H", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx30", "rtx3060-laptop", "GeForce RTX 3060 Laptop GPU", "nvidia", "2520",
     "联想拯救者 Y7000", "Intel i7-13700H", [(1920, 1080, 1, 8), (2560, 1440, 1.25, 8)]),
    ("nvidia-rtx30", "rtx3060-laptop", "GeForce RTX 3060 Laptop GPU", "nvidia", "2520",
     "华硕天选4", "AMD R7 7735H", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx30", "rtx3060-laptop", "GeForce RTX 3060 Laptop GPU", "nvidia", "2520",
     "机械革命旷世 G16", "Intel i7-13700H", [(2560, 1440, 1.25, 8)]),
    ("nvidia-rtx30", "rtx3060-laptop", "GeForce RTX 3060 Laptop GPU", "nvidia", "2520",
     "神舟战神 Z8", "Intel i7-12700H", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx30", "rtx3060", "GeForce RTX 3060", "nvidia", "2503",
     "组装台式机", "Intel i5-12400F", [(1920, 1080, 1, 8), (2560, 1440, 1, 8)]),
    ("nvidia-rtx30", "rtx3070-laptop", "GeForce RTX 3070 Laptop GPU", "nvidia", "249D",
     "机械革命蛟龙16K", "Intel i7-13650HX", [(2560, 1440, 1.25, 8)]),
    ("nvidia-rtx30", "rtx3070-laptop", "GeForce RTX 3070 Laptop GPU", "nvidia", "249D",
     "ROG 魔霸6", "AMD R9 6900HX", [(2560, 1440, 1.25, 8)]),
    ("nvidia-rtx30", "rtx3070", "GeForce RTX 3070", "nvidia", "2484",
     "组装台式机", "Intel i7-12700F", [(2560, 1440, 1, 8), (3840, 2160, 1.5, 8)]),
    ("nvidia-rtx30", "rtx3070ti-laptop", "GeForce RTX 3070 Ti Laptop GPU", "nvidia", "24A0",
     "联想拯救者 Y9000K", "Intel i9-12900HX", [(2560, 1440, 1.25, 8)]),
    # ── NVIDIA GTX 16 系 ──────────────────────────────────────────────────
    ("nvidia-gtx16", "gtx1650-laptop", "GeForce GTX 1650 Laptop GPU", "nvidia", "1F91",
     "联想小新 Pro 14", "Intel i5-10300H", [(1920, 1080, 1, 8)]),
    ("nvidia-gtx16", "gtx1650-laptop", "GeForce GTX 1650 Laptop GPU", "nvidia", "1F91",
     "惠普暗影精灵7", "Intel i5-11400H", [(1920, 1080, 1, 8)]),
    ("nvidia-gtx16", "gtx1650ti-laptop", "GeForce GTX 1650 Ti Laptop GPU", "nvidia", "1F95",
     "华硕飞行堡垒8", "Intel i7-10750H", [(1920, 1080, 1, 8)]),
    ("nvidia-gtx16", "gtx1650", "GeForce GTX 1650", "nvidia", "1F82",
     "组装台式机", "Intel i3-10100F", [(1920, 1080, 1, 4)]),
    ("nvidia-gtx16", "gtx1650", "GeForce GTX 1650", "nvidia", "1F82",
     "联想拯救者刃 7000", "Intel i5-10400F", [(1920, 1080, 1, 4)]),
    ("nvidia-gtx16", "gtx1650s", "GeForce GTX 1650 SUPER", "nvidia", "2187",
     "组装台式机", "Intel i5-10400F", [(1920, 1080, 1, 8)]),
    ("nvidia-gtx16", "gtx1660", "GeForce GTX 1660", "nvidia", "2184",
     "组装台式机", "AMD R5 5600", [(1920, 1080, 1, 8)]),
    ("nvidia-gtx16", "gtx1660s", "GeForce GTX 1660 SUPER", "nvidia", "21C4",
     "组装台式机", "Intel i5-12400F", [(1920, 1080, 1, 8), (2560, 1440, 1, 8)]),
    ("nvidia-gtx16", "gtx1660ti-laptop", "GeForce GTX 1660 Ti Laptop GPU", "nvidia", "2191",
     "联想拯救者 Y7000", "Intel i7-9750H", [(1920, 1080, 1, 8)]),
    ("nvidia-gtx16", "gtx1660ti", "GeForce GTX 1660 Ti", "nvidia", "2182",
     "组装台式机", "Intel i5-10400F", [(1920, 1080, 1, 8)]),
    # ── NVIDIA RTX 20 系 ──────────────────────────────────────────────────
    ("nvidia-rtx20", "rtx2060-laptop", "GeForce RTX 2060 Laptop GPU", "nvidia", "1F15",
     "联想拯救者 Y7000", "Intel i7-10750H", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx20", "rtx2060-laptop", "GeForce RTX 2060 Laptop GPU", "nvidia", "1F15",
     "惠普暗影精灵6", "Intel i7-10750H", [(1440, 900, 1, 8)]),
    ("nvidia-rtx20", "rtx2060", "GeForce RTX 2060", "nvidia", "1F08",
     "组装台式机", "Intel i5-9400F", [(1920, 1080, 1, 8)]),
    ("nvidia-rtx20", "rtx2060s", "GeForce RTX 2060 SUPER", "nvidia", "1F06",
     "组装台式机", "AMD R5 3600", [(1920, 1080, 1, 8), (2560, 1440, 1, 8)]),
    # ── Intel 核显 / Arc ──────────────────────────────────────────────────
    ("intel-igpu", "iris-xe-tgl", "Iris(R) Xe Graphics", "intel", "9A49",
     "联想小新 Air 14", "Intel i7-1165G7", [(1920, 1080, 1, 8)]),
    ("intel-igpu", "iris-xe-adl", "Iris(R) Xe Graphics", "intel", "46A6",
     "ThinkPad T14", "Intel i7-12700H", [(1920, 1080, 1, 8)]),
    ("intel-igpu", "iris-xe-adl", "Iris(R) Xe Graphics", "intel", "46A6",
     "戴尔灵越 13", "Intel i5-1235U", [(1920, 1080, 1, 8)]),
    ("intel-igpu", "iris-xe-rpl", "Iris(R) Xe Graphics", "intel", "A7A0",
     "联想小新 Pro 16", "Intel i7-13700H", [(2560, 1440, 1.25, 8)]),
    ("intel-igpu", "iris-xe-rpl", "Iris(R) Xe Graphics", "intel", "A7A0",
     "惠普战 66", "Intel i5-1340P", [(1920, 1080, 1, 8)]),
    ("intel-igpu", "uhd620", "UHD Graphics 620", "intel", "5917",
     "ThinkPad X1 Carbon 6代", "Intel i7-8550U", [(1920, 1080, 1, 8)]),
    ("intel-igpu", "uhd620", "UHD Graphics 620", "intel", "5917",
     "戴尔灵越 5000", "Intel i5-8250U", [(1366, 768, 1, 4)]),
    ("intel-igpu", "uhd620", "UHD Graphics 620", "intel", "5917",
     "惠普 EliteBook 840", "Intel i7-8550U", [(1920, 1080, 1, 8)]),
    ("intel-igpu", "uhd630", "UHD Graphics 630", "intel", "3E9B",
     "组装台式机", "Intel i5-9400", [(1920, 1080, 1, 8)]),
    ("intel-igpu", "uhd630", "UHD Graphics 630", "intel", "3E9B",
     "戴尔 OptiPlex 3070", "Intel i7-9700", [(1920, 1080, 1, 8), (1600, 900, 1, 4)]),
    ("intel-igpu", "uhd730", "UHD Graphics 730", "intel", "4692",
     "组装台式机", "Intel i5-12400", [(1920, 1080, 1, 8)]),
    ("intel-igpu", "uhd770", "UHD Graphics 770", "intel", "4680",
     "组装台式机", "Intel i7-13700", [(1920, 1080, 1, 8), (2560, 1440, 1, 8)]),
    ("intel-igpu", "uhd770", "UHD Graphics 770", "intel", "4680",
     "组装台式机", "Intel i5-13400", [(2560, 1440, 1, 8)]),
    ("intel-igpu", "arc-a370m", "Arc(TM) A370M Graphics", "intel", "5696",
     "华硕无畏 Pro 15", "Intel i7-12700H", [(2880, 1800, 1.5, 8), (1920, 1080, 1, 8)]),
    ("intel-igpu", "arc-mtl", "Arc(TM) Graphics", "intel", "7D55",
     "联想小新 Pro 14", "Intel Core Ultra 7 155H", [(2880, 1800, 1.5, 8)]),
    ("intel-igpu", "arc-mtl", "Arc(TM) Graphics", "intel", "7D55",
     "联想 ThinkBook 14", "Intel Core Ultra 5 125H", [(2880, 1800, 1.5, 8)]),
    # ── AMD Radeon ────────────────────────────────────────────────────────
    ("amd-radeon", "r780m", "Radeon 780M Graphics", "amd", "15BF",
     "联想小新 Pro 14", "AMD R7 7840HS", [(2880, 1800, 1.5, 8)]),
    ("amd-radeon", "r780m", "Radeon 780M Graphics", "amd", "15BF",
     "华硕天选 Air", "AMD R7 8845H", [(2560, 1440, 1.25, 8)]),
    ("amd-radeon", "r780m", "Radeon 780M Graphics", "amd", "15BF",
     "ROG 幻14 Air", "AMD R9 7940HS", [(2880, 1800, 1.5, 8), (1920, 1080, 1, 8)]),
    ("amd-radeon", "r780m", "Radeon 780M Graphics", "amd", "15BF",
     "ThinkPad T14s", "AMD R7 7840U", [(1920, 1080, 1, 8)]),
    ("amd-radeon", "r680m", "Radeon 680M Graphics", "amd", "1681",
     "联想小新 Pro 16", "AMD R7 6800H", [(2560, 1440, 1.25, 8)]),
    ("amd-radeon", "r680m", "Radeon 680M Graphics", "amd", "1681",
     "惠普战 99", "AMD R7 7735HS", [(1920, 1080, 1, 8)]),
    ("amd-radeon", "r680m", "Radeon 680M Graphics", "amd", "1681",
     "机械革命 Code 01", "AMD R7 6800H", [(2560, 1440, 1.25, 8)]),
    ("amd-radeon", "r660m", "Radeon 660M Graphics", "amd", "1680",
     "联想小新 Air 14", "AMD R5 6600H", [(1920, 1080, 1, 8)]),
    ("amd-radeon", "vega8", "Radeon RX Vega 8 Graphics", "amd", "15D8",
     "ThinkPad E14", "AMD R7 5700U", [(1920, 1080, 1, 8)]),
    ("amd-radeon", "vega8", "Radeon RX Vega 8 Graphics", "amd", "15D8",
     "惠普战 66", "AMD R5 5500U", [(1920, 1080, 1, 4)]),
    ("amd-radeon", "rx6600", "Radeon RX 6600", "amd", "73FF",
     "组装台式机", "AMD R5 5600", [(1920, 1080, 1, 8), (2560, 1440, 1, 8)]),
    ("amd-radeon", "rx6600m", "Radeon RX 6600M", "amd", "73E1",
     "戴尔 G15", "AMD R7 6800H", [(1920, 1080, 1, 8)]),
    ("amd-radeon", "rx6650m", "Radeon RX 6650M", "amd", "73EF",
     "华硕天选3", "AMD R7 6800H", [(1920, 1080, 1, 8)]),
    ("amd-radeon", "rx7600", "Radeon RX 7600", "amd", "7480",
     "组装台式机", "AMD R7 7700", [(2560, 1440, 1, 8), (1920, 1080, 1, 8)]),
    ("amd-radeon", "rx7600", "Radeon RX 7600", "amd", "7480",
     "组装台式机", "Intel i5-13400F", [(1920, 1080, 1, 8)]),
    # ── 高通 Snapdragon ───────────────────────────────────────────────────
    ("qualcomm", "x1-85", "Adreno(TM) X1-85 GPU", "qualcomm", "68C0",
     "Surface Laptop 7", "Qualcomm Snapdragon X Elite", [(2880, 1800, 1.5, 8)]),
    ("qualcomm", "x1-85", "Adreno(TM) X1-85 GPU", "qualcomm", "68C0",
     "Surface Pro 11", "Qualcomm Snapdragon X Elite", [(2880, 1800, 2, 8)]),
    ("qualcomm", "x1-85", "Adreno(TM) X1-85 GPU", "qualcomm", "68C0",
     "联想 Yoga Slim 7x", "Qualcomm Snapdragon X Elite", [(2880, 1800, 1.5, 8)]),
    ("qualcomm", "x1-85", "Adreno(TM) X1-85 GPU", "qualcomm", "68C0",
     "惠普 OmniBook X 14", "Qualcomm Snapdragon X Elite", [(2560, 1440, 1.25, 8)]),
    ("qualcomm", "x1-85", "Adreno(TM) X1-85 GPU", "qualcomm", "68C0",
     "三星 Galaxy Book4 Edge", "Qualcomm Snapdragon X Elite", [(2880, 1800, 1.75, 8)]),
]


def _build_templates() -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    counters: dict[tuple[str, str], int] = {}
    for family, gpu_key, gpu_model, vendor_key, devid_hex, machine, cpu, screens in _SPECS:
        cores = CPU_CORES.get(cpu)
        if cores is None:
            raise ValueError(f"CPU {cpu!r} 缺少核数定义，请补到 CPU_CORES")
        for width, height, dpr, mem in screens:
            key = (gpu_key, f"{width}x{height}")
            counters[key] = counters.get(key, 0) + 1
            tpl_id = f"win-{gpu_key}-{width}x{height}-{counters[key]:02d}"
            templates.append({
                "id": tpl_id,
                "name": f"{machine} · {gpu_model} · {width}×{height}",
                "family": family,
                "cpu": cpu,
                "gpu_vendor": _gpu_vendor(vendor_key),
                "gpu_renderer": _gpu_renderer(vendor_key, gpu_model, devid_hex),
                "screen_width": width,
                "screen_height": height,
                "hardware_concurrency": cores,
                "device_memory": mem,
                "device_scale_factor": dpr,
            })
    return templates


_TEMPLATES: list[dict[str, Any]] = _build_templates()
_BY_ID: dict[str, dict[str, Any]] = {t["id"]: t for t in _TEMPLATES}


def list_templates() -> list[dict[str, Any]]:
    """Return a copy of every device template, in stable order."""
    return [dict(t) for t in _TEMPLATES]


def get_template(template_id: str) -> dict[str, Any] | None:
    """Return a copy of the template with this id, or None."""
    tpl = _BY_ID.get(template_id)
    return dict(tpl) if tpl else None


def pick_template(seed_or_index: int | str) -> dict[str, Any]:
    """Deterministically pick a template: int -> index (wraps), str -> sha256 hash."""
    n = len(_TEMPLATES)
    if isinstance(seed_or_index, int):
        index = seed_or_index % n
    else:
        digest = hashlib.sha256(str(seed_or_index).encode("utf-8")).hexdigest()
        index = int(digest, 16) % n
    return dict(_TEMPLATES[index])


def random_template() -> dict[str, Any]:
    """Pick a random template (non-deterministic)."""
    return dict(random.choice(_TEMPLATES))


# ── Consistency validation ────────────────────────────────────────────────

_HIGH_TIER_GPUS = {"rtx4090", "rtx4090-laptop", "rtx4080", "rtx4080-laptop", "rtx4070ti"}
_LOW_TIER_GPUS = {"uhd620", "uhd630", "vega8", "gtx1650", "gtx1650-laptop", "gtx1650ti-laptop", "iris-xe-tgl"}
_LOW_TIER_SCREENS = {(1366, 768), (1440, 900), (1600, 900), (1680, 1050), (1536, 864), (1920, 1080)}
_HIGH_TIER_SCREENS = {(2560, 1440), (2880, 1800), (3840, 2160)}
_VENDOR_RE = re.compile(r"^Google Inc\. \((\w+)\)$")
_RENDERER_RE = re.compile(r"^ANGLE \((\w+),\s+(.+?)\s+\(0x([0-9A-Fa-f]{8})\)\s+Direct3D11 vs_5_0 ps_5_0, D3D11\)$")
_DPR_RULES = {
    (1366, 768): (1,), (1440, 900): (1,), (1600, 900): (1,), (1680, 1050): (1,),
    (1536, 864): (1,), (1920, 1080): (1, 1.25),
    (2560, 1440): (1, 1.25, 1.5), (2880, 1800): (1.5, 1.75, 2),
    (3840, 2160): (1.25, 1.5, 1.75, 2),
}


def validate_template(tpl: dict[str, Any]) -> list[str]:
    """Check a template's internal consistency. Returns a list of problems (empty = OK)."""
    errors: list[str] = []
    tpl_id = tpl.get("id", "?")

    def err(msg: str) -> None:
        errors.append(f"{tpl_id}: {msg}")

    if not tpl.get("id"):
        err("缺少 id")
    if not tpl.get("name"):
        err("缺少可读名")
    if tpl.get("family") not in FAMILIES:
        err(f"未知家族 {tpl.get('family')!r}")

    vendor = str(tpl.get("gpu_vendor") or "")
    renderer = str(tpl.get("gpu_renderer") or "")
    vm = _VENDOR_RE.match(vendor)
    rm = _RENDERER_RE.match(renderer)
    if not vm:
        err(f"gpu_vendor 格式不对：{vendor!r}，应为 'Google Inc. (厂商)'")
    if not rm:
        err(f"gpu_renderer 格式不对：{renderer!r}")
    if vm and rm and vm.group(1).lower() != rm.group(1).lower():
        err(f"厂商不一致：vendor={vm.group(1)!r} vs renderer={rm.group(1)!r}")

    width, height = tpl.get("screen_width"), tpl.get("screen_height")
    if (width, height) not in ALLOWED_SCREENS:
        err(f"分辨率 {width}×{height} 不在允许列表")
    elif width <= height:
        err(f"分辨率 {width}×{height} 不是横屏")

    cores = tpl.get("hardware_concurrency")
    if cores not in {2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 32}:
        err(f"核数 {cores} 不合理")
    cpu = tpl.get("cpu")
    expected_cores = CPU_CORES.get(cpu)
    if expected_cores is not None and cores != expected_cores:
        err(f"核数 {cores} 与 CPU {cpu}（应为 {expected_cores}）不匹配")

    if tpl.get("device_memory") not in MEMORY_BUCKETS:
        err(f"内存桶 {tpl.get('device_memory')} 必须是 4 或 8")

    dpr = tpl.get("device_scale_factor")
    allowed_dpr = _DPR_RULES.get((width, height))
    if allowed_dpr is None:
        err(f"分辨率 {width}×{height} 没有 DPR 规则")
    elif dpr not in allowed_dpr:
        err(f"DPR {dpr} 与分辨率 {width}×{height} 不搭配（允许 {allowed_dpr}）")

    gpu_key = tpl_id.split("-")[1] if tpl_id and tpl_id.startswith("win-") else ""
    if gpu_key in _LOW_TIER_GPUS:
        if (width, height) not in _LOW_TIER_SCREENS:
            err(f"低端 GPU {gpu_key} 不应搭配 {width}×{height}")
    if gpu_key in _HIGH_TIER_GPUS:
        if (width, height) not in _HIGH_TIER_SCREENS:
            err(f"高端 GPU {gpu_key} 不应搭配 {width}×{height}")
        if isinstance(cores, int) and cores < 8:
            err(f"高端 GPU {gpu_key} 的核数 {cores} 太低")

    return errors
