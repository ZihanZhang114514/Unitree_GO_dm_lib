#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unitree_GO 一键配置工具（GUI / CLI）
=====================================

给任何一份「STM32CubeMX + Keil MDK」工程（DM-MC-Board02 / STM32H723 这一套）装上
宇树 GO-M8010-6 电机驱动：

  * 把 Unitree_GO.c / .h 复制到 <工程根>/bsp/uper/
  * 生成移植层 Unitree_GO_port.c / .h（4 Mbps 串口 + 485 方向脚 + 示例任务）
  * 在 Core/Src/freertos.c 的 USER CODE 区插入线程声明 / 属性 / osThreadNew()
  * 把新增源文件登记进 R1.uvprojx 的工程组，并补齐 ../bsp/uper 头文件路径
  * 所有被改动的文件先备份到 MDK-ARM/Unitree_GO_backup/<时间戳>/

用法：
    python Unitree_GO_configurator.py                              # 打开 GUI
    python Unitree_GO_configurator.py --mdkarm "D:\\xx\\MDK-ARM"   # 命令行直接配置
    python Unitree_GO_configurator.py --mdkarm ... --dry-run       # 只检查不写入

依赖：Python 3.8+（GUI 需要标准库 tkinter，Windows 官方安装包自带）

作者：自动生成  版本：见 config.json / VERSION
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

VERSION = "1.2.1"
LIB_DIR = Path(__file__).resolve().parent
CONFIG_FILE = LIB_DIR / "config.json"
LAST_PATH_FILE = Path(tempfile.gettempdir()) / "unitree_go_configurator.json"

MARKER = "UNITREE_GO_AUTOCONFIG"

# ---------------------------------------------------------------------------
# 默认配置（config.json 缺失时的兜底，字段与 config.json 保持一致）
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: dict = {
    "lib": {
        "name": "Unitree_GO",
        "version": VERSION,
        "driver_files": ["Unitree_GO.c", "Unitree_GO.h"],
    },
    "layout": {
        "driver_dir": "bsp/uper",
        "port_prefix": "Unitree_GO_port",
        "freertos_c": "Core/Src/freertos.c",
        "core_src": "Core/Src",
        "usart_c": "Core/Src/usart.c",
        "usart_h": "Core/Inc/usart.h",
        "uvprojx_glob": "*.uvprojx",
        "backup_dir": "Unitree_GO_backup",
    },
    "uvprojx": {
        "preferred_group": "bsp_upper",
        "fallback_group": "Unitree_GO",
        "include_entry": "../bsp/uper",
    },
    "freertos": {
        "blocks": {
            "prototypes": ["/* USER CODE BEGIN FunctionPrototypes */", "/* USER CODE END FunctionPrototypes */"],
            "variables": ["/* USER CODE BEGIN Variables */", "/* USER CODE END Variables */"],
            "threads": ["/* USER CODE BEGIN RTOS_THREADS */", "/* USER CODE END RTOS_THREADS */"],
        },
        "includes_block": ["/* USER CODE BEGIN Includes */", "/* USER CODE END Includes */"],
    },
    "thread": {"name": "UnitreeGO", "stack_words": 512, "priority": "osPriorityNormal"},
    "main": {
        "file": "Core/Src/main.c",
        "blocks": {
            "includes": ["/* USER CODE BEGIN Includes */", "/* USER CODE END Includes */"],
            "init": ["/* USER CODE BEGIN 2 */", "/* USER CODE END 2 */"],
            "loop": ["/* USER CODE BEGIN 3 */", "/* USER CODE END 3 */"],
        },
    },
    "dma": {"controller": "DMA1", "fallback": "DMA2", "irq_priority": 5},
    "callbacks": {
        "rx_event": "HAL_UARTEx_RxEventCallback",
        "error": "HAL_UART_ErrorCallback",
    },
    "defaults": {
        "channel": 1,
        "motor_id": 1,
        "ratio": 6.33,
        "period_ms": 10,
        "demo_pos": 0.5,
        "demo_kp": 4.0,
        "demo_kd": 1.0,
        "uart": "",
        "de_pin": "",
        "baud": 4000000,
    },
    "channel_map": {
        "1": {
            "uart_index": 2, "uart_name": "huart2", "instance": "USART2",
            "tx_pin": 5, "rx_pin": 6, "de_port": "GPIOD", "de_pin": 4,
            "af": "GPIO_AF7_USART2", "dma_request": "DMA_REQUEST_USART2_RX",
        },
        "2": {
            "uart_index": 3, "uart_name": "huart3", "instance": "USART3",
            "tx_pin": 8, "rx_pin": 9, "de_port": "GPIOB", "de_pin": 14,
            "af": "GPIO_AF7_USART3", "dma_request": "DMA_REQUEST_USART3_RX",
        },
    },
}


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def nl_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def merge_dict(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    if not CONFIG_FILE.is_file():
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            return merge_dict(DEFAULT_CONFIG, json.load(f))
    except Exception:
        return dict(DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# 选项 / 检测结果
# ---------------------------------------------------------------------------
@dataclass
class Options:
    channel: int = 1
    motor_id: int = 1
    ratio: float = 6.33
    period_ms: int = 10
    demo_pos: float = 0.5
    demo_kp: float = 4.0
    demo_kd: float = 1.0
    with_task: bool = True
    dry_run: bool = False
    force: bool = False
    # ---- 自选串口（通道 3）：uart 非空即启用 ----
    uart: str = ""          # 例如 "USART6" / "UART4" / "LPUART1"
    de_pin: str = ""        # 例如 "PB14"；空 = 没有 485 方向脚（两线 485 / 三线直连）
    baud: int = 0           # 0 = 用默认值（板载 4 Mbps）


@dataclass
class Scan:
    mdkarm: Path
    root: Path
    uvprojx: Path
    driver_dir: Path
    freertos: Path | None
    usart_c: Path | None
    usart_h: Path | None
    main_c: Path | None = None
    has_driver: bool = False
    has_port: bool = False
    has_thread_patch: bool = False
    uart_owned_by: str = "installer"      # "project" | "installer"
    uart_reason: str = ""
    dma_owned_by: str = "installer"       # "project" | "installer"
    dma_stream: str = ""                  # 例如 DMA1_Stream3
    dma_irq: str = ""                     # 例如 DMA1_Stream3_IRQn
    dma_irq_defined: bool = False
    usart_irq_defined: bool = False
    cb_rx_file: Path | None = None        # 工程里已有 HAL_UARTEx_RxEventCallback 的文件
    cb_err_file: Path | None = None
    other_user_files: list = field(default_factory=list)
    manual_refs: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# 安装器
# ---------------------------------------------------------------------------
class Installer:
    def __init__(self, mdkarm: Path, opts: Options, cfg: dict | None = None, log=print):
        self.cfg = cfg or load_config()
        self.opts = opts
        self.log = log
        self.mdkarm = Path(mdkarm)
        self.scan_result: Scan | None = None
        self.changes: list[tuple[str, str, Path | None]] = []   # (动作, 说明, 备份路径)
        self.backup_root: Path | None = None

    # ---------------- 端口规格（通道 1/2 或 自选串口） ----------------
    @staticmethod
    def _parse_pin(text: str) -> tuple:
        """'PB14' -> ('GPIOB', 14)；空 / none -> (None, 0)"""
        t = (text or "").strip().upper().replace("GPIO", "").replace("_", "")
        if not t or t in ("NONE", "NO", "-", "0"):
            return None, 0
        m = re.fullmatch(r"P([A-K])(\d{1,2})", t)
        if not m:
            raise ValueError(f"引脚写法不对：{text}（应为 PB14 这种形式，或留空表示没有方向脚）")
        return f"GPIO{m.group(1)}", int(m.group(2))

    def _spec(self) -> dict:
        """把“通道 1/2”或“自选串口”统一成一份移植层参数。"""
        o = self.opts
        if o.uart or int(o.channel) == 3:
            if not o.uart:
                raise ValueError("选了「3 自选串口」但没填串口名（例如 USART6）")
            inst = o.uart.strip().upper()
            m = re.fullmatch(r"(USART|UART|LPUART)(\d+)", inst)
            if not m:
                raise ValueError(
                    f"串口名写法不对：{o.uart}（应为 USART1…USART10 / UART4…UART9 / LPUART1）")
            name = ("hlpuart" if m.group(1) == "LPUART" else "huart") + m.group(2)
            de_port, de_num = self._parse_pin(o.de_pin)
            return {
                "custom": True,
                "channel": 3,
                "instance": inst,
                "uart_name": name,
                "de_port": de_port if de_port else "NULL",
                "de_pin": f"GPIO_PIN_{de_num}" if de_port else "0u",
                "de_text": (f"{de_port} pin{de_num}" if de_port else "无（两线 485 / 三线直连）"),
                "baud": int(o.baud or 4000000),
                "dma_request": f"DMA_REQUEST_{inst}_RX",
                # 通道 3 时驱动头文件不定义 UNITREE_GO_485_*，这里补一份兼容别名，
                # 让照着旧 README 写的代码（&UNITREE_GO_485_UART）也能编过
                "compat": """
/* ---- 兼容别名：旧代码里写 UNITREE_GO_485_UART / DE_PORT / DE_PIN 也能编过 ---- */
#define UNITREE_GO_485_UART         UG_PORT_UART
#define UNITREE_GO_DE_PORT          UG_PORT_DE_PORT
#define UNITREE_GO_DE_PIN           UG_PORT_DE_PIN
""",
            }

        info = self.cfg["channel_map"][str(o.channel)]
        return {
            "custom": False,
            "channel": int(o.channel),
            "instance": info["instance"],
            "uart_name": info["uart_name"],
            "de_port": info["de_port"],
            "de_pin": f"GPIO_PIN_{info['de_pin']}",
            "de_text": f"{info['de_port']} pin{info['de_pin']}",
            "baud": 4000000,
            "dma_request": info.get("dma_request", ""),
            "compat": "",
        }

    # ---------------- 定位与检测 ----------------
    def resolve(self) -> Scan:
        mdkarm = self.mdkarm
        if not mdkarm.exists():
            raise FileNotFoundError(f"目录不存在：{mdkarm}")
        mdkarm = mdkarm.resolve()

        # 允许直接给工程根目录
        if not list(mdkarm.glob(self.cfg["layout"]["uvprojx_glob"])):
            cand = mdkarm / "MDK-ARM"
            if cand.is_dir() and list(cand.glob(self.cfg["layout"]["uvprojx_glob"])):
                mdkarm = cand.resolve()

        uvprojxs = sorted(mdkarm.glob(self.cfg["layout"]["uvprojx_glob"]))
        if not uvprojxs:
            raise FileNotFoundError(
                f"没在 {mdkarm} 里找到 .uvprojx —— 请选择 Keil 工程所在的 MDK-ARM 目录")
        uvprojx = uvprojxs[0]

        root = mdkarm.parent
        lay = self.cfg["layout"]
        driver_dir = root / lay["driver_dir"]
        freertos = root / lay["freertos_c"]
        usart_c = root / lay["usart_c"]
        usart_h = root / lay["usart_h"]
        main_c = root / self.cfg.get("main", {}).get("file", "Core/Src/main.c")

        scan = Scan(
            mdkarm=mdkarm,
            root=root,
            uvprojx=uvprojx,
            driver_dir=driver_dir,
            freertos=freertos if freertos.is_file() else None,
            usart_c=usart_c if usart_c.is_file() else None,
            usart_h=usart_h if usart_h.is_file() else None,
            main_c=main_c if main_c.is_file() else None,
        )
        scan.has_driver = (driver_dir / "Unitree_GO.c").is_file()
        scan.has_port = (driver_dir / f"{lay['port_prefix']}.c").is_file()

        if scan.freertos:
            txt = read_text(scan.freertos)
            scan.has_thread_patch = MARKER in txt

        self._detect_uart(scan)
        self._hint_other_channel(scan)
        self._detect_dma(scan)
        self._detect_callbacks(scan)
        self._detect_other_users(scan)
        if not scan.freertos:
            if scan.main_c is not None:
                scan.warnings.append(
                    "工程里没有 Core/Src/freertos.c（裸机工程）—— 会在 main.c 的 USER CODE 区"
                    "插入 Unitree_GO_App_Init() / Unitree_GO_App_Step()")
            else:
                scan.warnings.append(
                    "工程里既没有 freertos.c 也没有 main.c —— 请手动调用 Unitree_GO_Port_Init() 并在循环里收发")
        self.scan_result = scan
        return scan

    def _hint_other_channel(self, scan: Scan) -> None:
        """用户没选的那一路串口如果已经在工程里跑 4 Mbps，多半是想用那一路。"""
        if self.opts.uart:
            return              # 自选串口模式不做这个提示
        other = "2" if str(self.opts.channel) == "1" else "1"
        info = self.cfg["channel_map"][other]
        name, inst = info["uart_name"], info["instance"]

        blob = ""
        for p in self._project_sources(scan):
            try:
                blob += read_text(p) + "\n"
            except Exception:
                continue
        if re.search(rf"{name}\.Init\.BaudRate\s*=\s*4000000", blob):
            scan.warnings.append(
                f"工程里已经有 {name}（{inst}）跑 4 Mbps —— 如果电机是接在另一路 485 上，"
                f"请选通道 {other}（GUI 里点一下，或命令加 --channel {other}），这样可以复用现有串口配置")

    def _detect_uart(self, scan: Scan) -> None:
        """决定复用工程现有串口句柄，还是由移植层自己建。"""
        spec = self._spec()
        uart_name = spec["uart_name"]
        inst = spec["instance"]
        want_baud = spec["baud"]

        declared = False
        inited = False
        baud = None
        # CubeMX 既可能把串口初始化放在 usart.c，也可能全放在 main.c（没有 usart.h）
        for p in (scan.usart_c, scan.usart_h, scan.main_c):
            if p and p.is_file():
                txt = read_text(p)
                if re.search(rf"UART_HandleTypeDef\s+{uart_name}\s*;", txt):
                    declared = True
                if re.search(rf"void\s+MX_{inst}_UART_Init\s*\(", txt):
                    inited = True
                m = re.search(rf"{uart_name}\.Init\.BaudRate\s*=\s*(\d+)", txt)
                if m:
                    baud = int(m.group(1))

        if spec["custom"] and not declared:
            raise RuntimeError(
                f"没有在工程里找到 {uart_name}（{inst}）—— 自选串口用的是你在 CubeMX 里已经配好的那一路。\n"
                f"  办法一：在 CubeMX 里加 {inst}（Mode=Asynchronous，引脚随便选，波特率按设备来），"
                f"生成代码后重新运行本工具；\n"
                f"  办法二：先选通道 1/2 由工具自己建 USART2/USART3（板载 485 用）。")

        if declared:
            scan.uart_owned_by = "project"
            scan.uart_reason = (
                f"工程里已有 {uart_name} 句柄" + (f"（{baud} bps）" if baud else ""))
            if inited and baud != want_baud:
                scan.warnings.append(
                    f"{uart_name} 当前波特率是 {baud}，与要求的 {want_baud} 不一致 —— "
                    f"移植层会在启动时把它改成 {want_baud}（依赖工程里已调用过 MX_{inst}_UART_Init）")
        else:
            scan.uart_owned_by = "installer"
            scan.uart_reason = f"工程里没有 {uart_name}，由移植层自己建 {inst}（{want_baud} bps）"

    # ---- DMA / 回调检测 ----
    def _port_paths(self, scan: Scan) -> set:
        """本工具自己生成/管理的文件，扫描工程时要排除，否则会误判成“工程自带”。"""
        lay = self.cfg["layout"]
        p = lay["port_prefix"]
        return {
            (scan.driver_dir / "Unitree_GO.c").resolve(),
            (scan.driver_dir / "Unitree_GO.h").resolve(),
            (scan.driver_dir / f"{p}.c").resolve(),
            (scan.driver_dir / f"{p}.h").resolve(),
        }

    def _project_sources(self, scan: Scan) -> list[Path]:
        mine = self._port_paths(scan)
        out: list[Path] = []
        for sub in ("Core/Src", "app", "bsp"):
            d = scan.root / sub
            if d.is_dir():
                for p in d.rglob("*.c"):
                    if p.is_file() and p.resolve() not in mine:
                        out.append(p)
        return sorted(out)

    def _detect_dma(self, scan: Scan) -> None:
        """决定 DMA 用工程现成的，还是由移植层生成（自动挑一个空闲 stream）。"""
        spec = self._spec()
        inst = spec["instance"]
        req = spec["dma_request"]

        blob = ""
        for p in self._project_sources(scan):
            try:
                blob += read_text(p) + "\n"
            except Exception:
                continue

        used = set(re.findall(r"Instance\s*=\s*(DMA[12]_Stream\d+)", blob))
        defined = set(re.findall(r"void\s+(DMA[12]_Stream\d+_IRQHandler)\s*\(", blob))
        scan.usart_irq_defined = bool(re.search(rf"void\s+{inst}_IRQHandler\s*\(", blob))

        m = re.search(rf"hdma_{inst.lower()}_rx\.Instance\s*=\s*(DMA[12]_Stream\d+)", blob)
        if m and req in blob:
            # 工程已经为这路串口配好了 DMA（CubeMX 生成的 hdma_usartx_rx）
            scan.dma_owned_by = "project"
            scan.dma_stream = m.group(1)
            scan.dma_irq = f"{m.group(1)}_IRQn"
            scan.dma_irq_defined = f"{m.group(1)}_IRQHandler" in defined
        elif req in blob and "__HAL_LINKDMA" in blob:
            scan.dma_owned_by = "project"
            scan.dma_stream = ""
            scan.dma_irq = ""
            scan.dma_irq_defined = True
        else:
            scan.dma_owned_by = "installer"
            cands = ([f"DMA1_Stream{i}" for i in range(8)] +
                     [f"DMA2_Stream{i}" for i in range(8)])
            free = [c for c in cands
                    if c not in used and f"{c}_IRQHandler" not in defined]
            if not free:
                raise RuntimeError("工程里 16 个 DMA 流都被占用，没法给串口接收分配 DMA")
            scan.dma_stream = free[0]
            scan.dma_irq = f"{free[0]}_IRQn"
            scan.dma_irq_defined = False

    def _detect_callbacks(self, scan: Scan) -> None:
        rx_name = self.cfg["callbacks"]["rx_event"]
        err_name = self.cfg["callbacks"]["error"]
        for p in self._project_sources(scan):
            try:
                txt = read_text(p)
            except Exception:
                continue
            if scan.cb_rx_file is None and re.search(rf"void\s+{rx_name}\s*\(", txt):
                scan.cb_rx_file = p
            if scan.cb_err_file is None and re.search(rf"void\s+{err_name}\s*\(", txt):
                scan.cb_err_file = p
            if scan.cb_rx_file and scan.cb_err_file:
                break

    def _detect_other_users(self, scan: Scan) -> None:
        """看看工程里是否已经有人用这个驱动（避免重复建任务抢总线）。

        分两类：
          * 别人的接入代码（app/、bsp/ 里的）→ 不再自动加线程；
          * main.c / freertos.c 里手写的接入代码 → 只提示（多半是照 README 抄的样例，
            和移植层的 App_Init/App_Step 重复，建议删掉）。
        """
        mine = self._port_paths(scan)
        # 本工具自己插入的符号，判断“是不是用户手写”时要先摘掉
        own = ("Unitree_GO_port.h", "Unitree_GO_App_Init", "Unitree_GO_App_Step",
               "APP_Unitree_GO_Task", "unitree_go_attributes",
               "Unitree_GO_RxEvent", "Unitree_GO_Error")
        hits, manual = [], []
        for sub in ("app", "Core/Src", "Core/Inc", "bsp"):
            d = scan.root / sub
            if not d.is_dir():
                continue
            for p in d.rglob("*"):
                if p.suffix.lower() not in (".c", ".h") or not p.is_file():
                    continue
                if p.resolve() in mine:
                    continue
                try:
                    txt = read_text(p)
                except Exception:
                    continue
                txt = re.sub(r"/\*.*?\*/", " ", txt, flags=re.S)
                txt = re.sub(r"//[^\n]*", " ", txt)
                for name in own:
                    txt = txt.replace(name, " ")
                if not re.search(r"Unitree_GO_\w+|\bg_go_joint\b|APP_Unitree_test", txt):
                    continue
                rel = str(p.relative_to(scan.root))
                is_patched = ((scan.freertos and p.resolve() == scan.freertos.resolve()) or
                              (scan.main_c and p.resolve() == scan.main_c.resolve()))
                (manual if is_patched else hits).append(rel)

        scan.other_user_files = hits
        scan.manual_refs = manual
        if hits and not scan.has_thread_patch:
            scan.warnings.append(
                "工程里已经存在别的宇树 GO 代码：" + "，".join(hits[:5]) +
                "；为避免两个任务抢同一路 485，本次不会自动加线程，请自行决定是否删掉旧的接入代码")
        if manual:
            scan.warnings.append(
                "这些文件里有手写的 Unitree_GO 接入代码：" + "，".join(manual[:5]) +
                "（例如 motor_init()/go_joint）。它和移植层的 App_Init/App_Step 重复，"
                "建议删掉手写那份，否则两个句柄会抢同一路 485")

    # ---------------- 备份 ----------------
    def _backup(self, path: Path) -> Path | None:
        scan = self.scan_result
        assert scan is not None
        if not path.is_file():
            return None
        if self.backup_root is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.backup_root = scan.mdkarm / self.cfg["layout"]["backup_dir"] / ts
        rel = path.resolve().relative_to(scan.root.resolve())
        dst = self.backup_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        return dst

    # ---------------- 主流程 ----------------
    def run(self) -> list[tuple[str, str, Path | None]]:
        scan = self.resolve()
        o = self.opts

        if o.dry_run:
            self.log("【只检查，不写入】")
        self.log(f"工程根目录 : {scan.root}")
        self.log(f"Keil 工程   : {scan.uvprojx.name}")
        self.log(f"驱动目录    : {scan.driver_dir}")
        self.log(f"串口策略    : {scan.uart_reason}")
        if scan.dma_owned_by == "project":
            self.log(f"DMA 策略    : 复用工程自带" + (f"（{scan.dma_stream}）" if scan.dma_stream else ""))
        else:
            self.log(f"DMA 策略    : 生成（{scan.dma_stream} / {scan.dma_irq}，自动挑的空闲流）")
        self.log("回调接线    : " + ("工程已有 HAL 回调 -> 插转发" if (scan.cb_rx_file or scan.cb_err_file)
                                     else "工程没有 HAL 回调 -> 在移植层里定义"))
        for w in scan.warnings:
            self.log(f"[注意] {w}")

        # 1) 驱动文件
        self._install_driver(scan)

        # 工程里已经有别人写的 GO 电机接入代码时，只同步驱动，不生成移植层
        # （否则两个任务抢同一路半双工 485，符号也可能撞车）
        skip_port = bool(scan.other_user_files) and not o.force
        if skip_port:
            self.log("[跳过] 工程里已有其它 GO 电机接入代码，只同步驱动文件；"
                     "不生成移植层/线程（确认要覆盖请加 --force）")

        # 2) 移植层
        if not skip_port:
            self._install_port(scan)
            self._patch_callbacks(scan)

        # 3) 示例代码：RTOS 工程插线程，裸机工程插 main 的主循环
        if skip_port:
            pass
        elif not o.with_task:
            self.log("[跳过] --no-task：不生成示例代码，请自行调用 Unitree_GO_Port_Init() 并收发")
        elif scan.freertos:
            self._patch_freertos(scan)
        elif scan.main_c is not None:
            self._patch_main(scan)
        else:
            self.log("[跳过] 既没有 Core/Src/freertos.c 也没有 Core/Src/main.c，示例代码没处放")

        # 4) Keil 工程
        self._patch_uvprojx(scan, with_port=not skip_port)

        # 5) 报告
        self._write_report(scan)
        return self.changes

    # ---- 1) 驱动 ----
    def _install_driver(self, scan: Scan) -> None:
        for name in self.cfg["lib"]["driver_files"]:
            src = LIB_DIR / name
            if not src.is_file():
                raise FileNotFoundError(f"库目录里缺少 {name}")
            text = read_text(src)
            if name.endswith(".h"):
                text = self._set_channel(text, self._spec()["channel"])
            self._put_file(scan.driver_dir / name, text, scan)

    def _set_channel(self, header_text: str, channel: int) -> str:
        return re.sub(r"(#define\s+UNITREE_GO_485_CHANNEL\s+)\d+",
                      rf"\g<1>{channel}", header_text, count=1)

    @staticmethod
    def _stable(text: str) -> str:
        """比较用：忽略“生成时间”行，重复运行不会因为时间戳不同而反复改写文件。"""
        return re.sub(r"^.*生成时间.*$\r?\n?", "", text, flags=re.M)

    def _put_file(self, dst: Path, text: str, scan: Scan) -> None:
        same = dst.is_file() and self._stable(read_text(dst)) == self._stable(text)
        if same:
            rel = dst.relative_to(scan.root)
            self.log(f"[不变] {rel}")
            self.changes.append(("unchanged", str(rel), None))
            return
        if self.opts.dry_run:
            self.log(f"[将写入] {dst.relative_to(scan.root)}")
            self.changes.append(("would-write", str(dst.relative_to(scan.root)), None))
            return
        bak = self._backup(dst)
        write_text(dst, text)
        rel = dst.relative_to(scan.root)
        self.log(f"[写入] {rel}" + (f"（原文件已备份）" if bak else ""))
        self.changes.append(("written", str(rel), bak))

    # ---- 2) 移植层 ----
    def _port_files(self, scan: Scan) -> tuple[str, str]:
        o = self.opts
        lay = self.cfg["layout"]
        prefix = lay["port_prefix"]
        spec = self._spec()
        # 通道 3（自选串口）不查 channel_map；tx/rx/af 只在“自己建串口”时才用，自选串口不走那条路
        info = ({"tx_pin": 0, "rx_pin": 0, "af": "", "de_port": "NULL", "de_pin": 0}
                if spec["custom"] else self.cfg["channel_map"][str(o.channel)])
        nl = "\n"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        baremetal = scan.freertos is None          # 裸机工程：用 App_Init/App_Step 而不是 RTOS 线程

        if baremetal:
            task_decl = """/* 裸机用法：main 里调一次 Init，while(1) 里每轮调一次 Step
 * （返回 1 = 这一轮收到了有效反馈） */
void    Unitree_GO_App_Init(void);
uint8_t Unitree_GO_App_Step(void);"""
        else:
            task_decl = "void APP_Unitree_GO_Task(void *argument);"

        # ---------------- 头文件 ----------------
        head = f"""/**
  ******************************************************************************
  * @file    {prefix}.h
  * @brief   宇树 GO-M8010-6 移植层（由 Unitree_GO_configurator.py 生成）
  *
  * 生成时间 : {stamp}
  * 配置来源 : MDK-ARM/Unitree_GO_dm_lib/config.json
  * 485 通道 : {spec['channel']}（{spec['instance']} {spec['uart_name']}，DE={spec['de_text']}，{spec['baud']} bps）
  * DMA 接收 : {"工程自带" if scan.dma_owned_by == "project" else (scan.dma_stream or "移植层生成")}（空闲中断判帧尾）
  * 电机 ID  : {o.motor_id}    减速比 : {o.ratio}
  *
  * 想改参数：直接改下面几个宏；想重装：重新运行配置工具（会先备份）。
  * 本文件带 {MARKER} 标记，重新运行工具时会整份覆盖。
  ******************************************************************************
  */
#ifndef {prefix.upper()}_H
#define {prefix.upper()}_H

#include "main.h"
#include "Unitree_GO.h"

/* ---- 用的串口 / 485 方向脚（改这里就能换口，不用动驱动） --------------- */
#define UG_PORT_INSTANCE            {spec['instance']}
#define UG_PORT_UART                {spec['uart_name']}
#define UG_PORT_DE_PORT             {spec['de_port']}      /* NULL = 没有方向脚（两线 485 / 三线直连） */
#define UG_PORT_DE_PIN              {spec['de_pin']}
#define UG_PORT_BAUD                {spec['baud']}u
{spec['compat']}
/* ---- 用户可调参数 ---------------------------------------------------- */
#define UG_PORT_MOTOR_ID            {o.motor_id}u      /* 电机 ID，必须和电机里烧的一致（0~14） */
#define UG_PORT_RATIO               {o.ratio}f    /* GO-M8010-6 减速比 */
#define UG_PORT_PERIOD_MS           {o.period_ms}u         /* 控制周期 ms，建议 >= 2 */
#define UG_PORT_DEMO_POS            {o.demo_pos}f      /* 示例目标位置（关节侧 rad） */
#define UG_PORT_DEMO_KP             {o.demo_kp}f       /* 示例 kp（关节侧，1 = 1 N·m/rad） */
#define UG_PORT_DEMO_KD             {o.demo_kd}f       /* 示例 kd（关节侧） */
#define UG_PORT_SETTLE_MS           2000u        /* 上电先零力矩多久，方便手拨确认 */

/* ---- 接口 ------------------------------------------------------------ */
/* 初始化 485 + 电机句柄（幂等，可重复调用） */
void Unitree_GO_Port_Init(void);

/* 示例代码 */
{task_decl}

/* 给调试器/其它模块用的全局句柄 */
extern Unitree_GO_HandleTypeDef g_go_joint;

#endif /* {prefix.upper()}_H */
"""

        # ---------------- 源文件 ----------------
        uart_name = spec["uart_name"]
        inst = spec["instance"]
        baud = spec["baud"]
        tx_pin = info.get("tx_pin", 0)
        rx_pin = info.get("rx_pin", 0)
        af = info.get("af", "")

        dma_req = spec["dma_request"]
        stream = scan.dma_stream or "DMA1_Stream0"
        dma_ctrl = stream.split("_")[0]
        dma_irq = scan.dma_irq or f"{stream}_IRQn"
        irq_prio = int(self.cfg["dma"]["irq_priority"])
        dma_handle = f"hdma_{inst.lower()}_rx"
        dma_installer = (scan.dma_owned_by == "installer")

        dma_section = ""
        if dma_installer:
            dma_section = f"""/* ---- 接收 DMA（{dma_ctrl} / {dma_req}） ------------------------------
 * 4 Mbps 下一帧回包只有 16 字节（32 µs），用 DMA 搬运 + 空闲中断判帧尾，
 * CPU 不用在 HAL_UART_Receive 里轮询。
 * CubeMX 里的等价配置：{inst} -> DMA Settings -> Add -> {inst}_RX，
 *   Mode = Normal，Data Width = Byte/Byte，MemInc 使能，Priority = Low；
 *   NVIC 里打开 {dma_irq} 全局中断（USART 的也要开）。 */
DMA_HandleTypeDef {dma_handle};

static void UG_Port_DmaInit(void)
{{
    __HAL_RCC_{dma_ctrl}_CLK_ENABLE();

    {dma_handle}.Instance                 = {stream};
    {dma_handle}.Init.Request             = {dma_req};
    {dma_handle}.Init.Direction           = DMA_PERIPH_TO_MEMORY;
    {dma_handle}.Init.PeriphInc           = DMA_PINC_DISABLE;
    {dma_handle}.Init.MemInc              = DMA_MINC_ENABLE;
    {dma_handle}.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
    {dma_handle}.Init.MemDataAlignment    = DMA_MDATAALIGN_BYTE;
    {dma_handle}.Init.Mode                = DMA_NORMAL;
    {dma_handle}.Init.Priority            = DMA_PRIORITY_LOW;
    {dma_handle}.Init.FIFOMode            = DMA_FIFOMODE_DISABLE;
    if (HAL_DMA_Init(&{dma_handle}) != HAL_OK)
    {{
        Error_Handler();
    }}

    /* 串口 <-> DMA 绑定：必须在 Unitree_GO_StartRx() 之前完成 */
    __HAL_LINKDMA(&{uart_name}, hdmarx, {dma_handle});

    HAL_NVIC_SetPriority({dma_irq}, {irq_prio}, 0);
    HAL_NVIC_EnableIRQ({dma_irq});
}}
"""

        dma_call = "    UG_Port_DmaInit();\n" if dma_installer else ""

        # 串口句柄必须先声明：UG_Port_DmaInit() 里有 __HAL_LINKDMA(&huartX, ...)
        if scan.uart_owned_by == "project":
            uart_decl = f"""/* 复用工程已有的 {inst} 句柄（定义在 usart.c 或 main.c 里） */
extern UART_HandleTypeDef {uart_name};"""
        else:
            uart_decl = f"""/* 工程里没有 {inst}，由移植层自己定义 */
UART_HandleTypeDef {uart_name};"""

        if scan.uart_owned_by == "project":
            uart_section = f"""/* ---- 串口：复用工程里已有的 {uart_name}（{inst}）---------------------
 * 工程自己的 MX_{inst}_UART_Init() 负责引脚/时钟；这里只保证波特率是 {baud}。
 * {"DMA 由本移植层补上（见上面的 UG_Port_DmaInit）。" if dma_installer else "DMA 工程里已经配好，直接用。"}
 * 如果工程还没调用过串口初始化，请在 main() 里调用 MX_{inst}_UART_Init()。 */
static void UG_Port_UartInit(void)
{{
{dma_call}    if (({uart_name}.Instance == {inst}) && ({uart_name}.Init.BaudRate != UG_PORT_BAUD))
    {{
        {uart_name}.Init.BaudRate = UG_PORT_BAUD;
        if (HAL_UART_Init(&{uart_name}) != HAL_OK)
        {{
            Error_Handler();
        }}
    }}

    /* 空闲中断靠串口全局中断：CubeMX 里没勾的话这里补上（重复使能无副作用） */
    HAL_NVIC_SetPriority({inst}_IRQn, {irq_prio}, 0);
    HAL_NVIC_EnableIRQ({inst}_IRQn);
}}"""
        else:
            uart_section = f"""/* ---- 串口：工程里没有 {uart_name}，这里自己建 {inst} ---------------
 * 引脚 {info['de_port'][-1]}{tx_pin}/{info['de_port'][-1]}{rx_pin} = {inst}_TX/RX，4 Mbps 8N1；
 * 485 方向脚 DE（{info['de_port']} pin{info['de_pin']}）由 Unitree_GO_Init() 负责。
 * 接收走 DMA + 空闲中断，发送仍是阻塞（17 字节 34 µs，没必要上 DMA）。 */
static void UG_Port_UartInit(void)
{{
    RCC_PeriphCLKInitTypeDef clk = {{0}};
    GPIO_InitTypeDef gpio = {{0}};

{dma_call}    /* {inst} 内核时钟 = D2PCLK1（与 CubeMX 默认一致） */

    clk.PeriphClockSelection = RCC_PERIPHCLK_{inst};
    clk.Usart234578ClockSelection = RCC_USART234578CLKSOURCE_D2PCLK1;
    if (HAL_RCCEx_PeriphCLKConfig(&clk) != HAL_OK)
    {{
        Error_Handler();
    }}

    __HAL_RCC_{inst}_CLK_ENABLE();
    __HAL_RCC_{info['de_port']}_CLK_ENABLE();

    /* {info['de_port'][-1]}{tx_pin} = {inst}_TX, {info['de_port'][-1]}{rx_pin} = {inst}_RX */
    gpio.Pin       = GPIO_PIN_{tx_pin} | GPIO_PIN_{rx_pin};
    gpio.Mode      = GPIO_MODE_AF_PP;
    gpio.Pull      = GPIO_NOPULL;
    gpio.Speed     = GPIO_SPEED_FREQ_HIGH;
    gpio.Alternate = {af};
    HAL_GPIO_Init({info['de_port']}, &gpio);

    {uart_name}.Instance = {inst};
    {uart_name}.Init.BaudRate = UG_PORT_BAUD;
    {uart_name}.Init.WordLength = UART_WORDLENGTH_8B;
    {uart_name}.Init.StopBits = UART_STOPBITS_1;
    {uart_name}.Init.Parity = UART_PARITY_NONE;
    {uart_name}.Init.Mode = UART_MODE_TX_RX;
    {uart_name}.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    {uart_name}.Init.OverSampling = UART_OVERSAMPLING_16;
    {uart_name}.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
    {uart_name}.Init.ClockPrescaler = UART_PRESCALER_DIV1;
    /* 不写 AdvancedInit：不同 HAL 版本它一个在 Init 里、一个在句柄顶层。
     * 句柄是全局变量（.bss 清零），等价于 UART_ADVFEATURE_NO_INIT，不用管。 */
    if (HAL_UART_Init(&{uart_name}) != HAL_OK)
    {{
        Error_Handler();
    }}

    /* 空闲中断（IDLE）靠串口全局中断，必须开 */
    HAL_NVIC_SetPriority({inst}_IRQn, {irq_prio}, 0);
    HAL_NVIC_EnableIRQ({inst}_IRQn);
}}"""

        # ---------------- 中断入口 / 回调 ----------------
        irq_parts = []
        if not scan.usart_irq_defined:
            irq_parts.append(f"""void {inst}_IRQHandler(void)
{{
    HAL_UART_IRQHandler(&{uart_name});
}}""")
        if dma_installer and not scan.dma_irq_defined:
            irq_parts.append(f"""void {stream}_IRQHandler(void)
{{
    HAL_DMA_IRQHandler(&{dma_handle});
}}""")
        irq_section = ""
        if irq_parts:
            irq_section = ("/* ---- 中断入口：工程里原来没有，这里补上 ----------------\n"
                           " * 以后若在 CubeMX 里也开启了这路串口/这个 DMA 流，CubeMX 会在\n"
                           " * stm32h7xx_it.c 里再生成一份同名函数 —— 那时把这里的两段删掉即可。 */\n"
                           + "\n\n".join(irq_parts) + "\n")

        cb_parts = []
        cb_rx = self.cfg["callbacks"]["rx_event"]
        cb_err = self.cfg["callbacks"]["error"]
        if scan.cb_rx_file is None:
            cb_parts.append(f"""void {cb_rx}(UART_HandleTypeDef *huart, uint16_t Size)
{{
    Unitree_GO_RxEvent(huart, Size);      /* 只认 GO 电机那一路，其它串口原样返回 */
}}""")
        if scan.cb_err_file is None:
            cb_parts.append(f"""void {cb_err}(UART_HandleTypeDef *huart)
{{
    Unitree_GO_Error(huart);
}}""")
        callback_section = ""
        if cb_parts:
            callback_section = ("/* ---- HAL 回调：工程里没有，这里定义（空闲中断靠它分发） ---- */\n"
                                + "\n\n".join(cb_parts) + "\n")

        rtos_include = '#include "cmsis_os.h"' if (self.opts.with_task and not baremetal) else ""
        task_body = ""
        if self.opts.with_task and baremetal:
            task_body = f"""
/* ---- 裸机用法 --------------------------------------------------------
 * main() 里调一次 Unitree_GO_App_Init()；
 * while (1) 里每轮调一次 Unitree_GO_App_Step()，中间给个 UG_PORT_PERIOD_MS 的延时。
 * 配置工具会把这几个调用自动插进 main.c 的 USER CODE 区（带 {MARKER} 标注）。 */
void Unitree_GO_App_Init(void)
{{
    Unitree_GO_Port_Init();             /* 幂等：串口 + DMA + 电机句柄 + 武装接收 */

    /* 先收一帧拿到当前位置，再把它记成关节 0 点（只改 RAM 偏移，不动电机） */
    if (Unitree_GO_SendRecv(&g_go_joint) != 0u)
    {{
        Unitree_GO_SetZeroPosition(&g_go_joint);
    }}
}}

uint8_t Unitree_GO_App_Step(void)
{{
    Unitree_GO_Port_Init();             /* 幂等，忘了先调 App_Init 也不会炸 */

    Unitree_GO_MITMode(&g_go_joint, UG_PORT_DEMO_POS, 0.0f,
                       UG_PORT_DEMO_KP, UG_PORT_DEMO_KD, 0.0f);
    return Unitree_GO_SendRecv(&g_go_joint);
}}"""
        elif self.opts.with_task:               # RTOS 工程：示例线程
            task_body = f"""
/* ---- 示例任务 --------------------------------------------------------
 * 上电先零力矩 UG_PORT_SETTLE_MS（手拨能轻松转 = 通信与 FOC 都正常），
 * 然后把当前位置记成关节 0 点，再按位置伺服走到 UG_PORT_DEMO_POS 并保持。
 * 注意：这段会让电机真的动；不想动就删掉本函数和 freertos.c 里的 osThreadNew。 */
void APP_Unitree_GO_Task(void *argument)
{{
    uint32_t t0;

    (void)argument;
    Unitree_GO_Port_Init();

    /* 1) 零力矩，确认通信 + 可以手拨 */
    t0 = HAL_GetTick();
    while ((HAL_GetTick() - t0) < UG_PORT_SETTLE_MS)
    {{
        Unitree_GO_ZeroTorqueMode(&g_go_joint);
        (void)Unitree_GO_SendRecv(&g_go_joint);
        osDelay(UG_PORT_PERIOD_MS);
    }}

    /* 2) 把当前位置记成关节 0 点（只改 RAM 偏移，不会动电机） */
    if (Unitree_GO_SendRecv(&g_go_joint) != 0u)
    {{
        Unitree_GO_SetZeroPosition(&g_go_joint);
    }}

    /* 3) 位置伺服，保持 */
    for (;;)
    {{
        Unitree_GO_MITMode(&g_go_joint, UG_PORT_DEMO_POS, 0.0f,
                           UG_PORT_DEMO_KP, UG_PORT_DEMO_KD, 0.0f);
        (void)Unitree_GO_SendRecv(&g_go_joint);
        osDelay(UG_PORT_PERIOD_MS);
    }}
}}"""

        src = f"""/**
  ******************************************************************************
  * @file    {prefix}.c
  * @brief   宇树 GO-M8010-6 移植层（由 Unitree_GO_configurator.py 生成）
  *
  * 生成时间 : {stamp}
  * 485 通道 : {spec['channel']}（{inst}，TX={tx_pin} RX={rx_pin}，DE={spec['de_text']}，{baud} bps）
  *
  * 本文件带 {MARKER} 标记，重新运行配置工具会整份覆盖。
  * 不想被覆盖的改动请放到别的文件里。
  ******************************************************************************
  */
#include "{prefix}.h"
{rtos_include}

Unitree_GO_HandleTypeDef g_go_joint;

/* ---- 串口句柄（必须声明在 DmaInit / UartInit 之前） ---- */
{uart_decl}

{dma_section}
{uart_section}

/* ---- 对外接口 -------------------------------------------------------- */
void Unitree_GO_Port_Init(void)
{{
    static uint8_t inited = 0u;

    if (inited != 0u)
    {{
        return;
    }}
    inited = 1u;

    UG_Port_UartInit();

    /* DE 方向脚由驱动自己初始化；这里只做句柄绑定
     * （Unitree_GO_Init 内部会自动武装 DMA + 空闲中断接收） */
    Unitree_GO_Init(&g_go_joint, &UG_PORT_UART,
                    UG_PORT_DE_PORT, UG_PORT_DE_PIN,
                    UG_PORT_MOTOR_ID, UG_PORT_RATIO);
}}
{task_body}
{irq_section}
{callback_section}
"""
        return head, src

    def _install_port(self, scan: Scan) -> None:
        lay = self.cfg["layout"]
        prefix = lay["port_prefix"]
        head, src = self._port_files(scan)
        self._put_file(scan.driver_dir / f"{prefix}.h", head, scan)
        self._put_file(scan.driver_dir / f"{prefix}.c", src, scan)

    def _patch_callbacks(self, scan: Scan) -> None:
        """工程里已有 HAL_UARTEx_RxEventCallback / HAL_UART_ErrorCallback 时，
        往里面插一行转发（DMA 空闲中断靠它把帧交给驱动）。"""
        pairs = []
        if scan.cb_rx_file is not None:
            pairs.append((scan.cb_rx_file, self.cfg["callbacks"]["rx_event"],
                          "Unitree_GO_RxEvent(huart, Size);", "rx"))
        if scan.cb_err_file is not None:
            pairs.append((scan.cb_err_file, self.cfg["callbacks"]["error"],
                          "Unitree_GO_Error(huart);", "err"))

        for path, fname, call, tag in pairs:
            rel = path.relative_to(scan.root)
            text = read_text(path)
            marker = f"{MARKER}: {tag}"
            if marker in text:
                self.log(f"[不变] {rel}（{fname} 已转发）")
                self.changes.append(("unchanged", str(rel), None))
                continue
            if self.opts.dry_run:
                self.log(f"[将修改] {rel}（在 {fname} 里插一行转发）")
                self.changes.append(("would-patch", str(rel), None))
                continue

            m = re.search(rf"void\s+{fname}\s*\([^)]*\)\s*\{{", text)
            if not m:
                self.log(f"[跳过] 找不到 {fname} 的函数体：{rel}")
                continue

            nl = nl_of(text)
            snippet = (f"{nl}    /* {marker}: 宇树 GO 电机（DMA + 空闲中断）分发 */"
                       f"{nl}    {call}")
            new_text = text[:m.end()] + snippet + text[m.end():]
            new_text = self._ensure_include(new_text, '#include "Unitree_GO_port.h"')

            bak = self._backup(path)
            write_text(path, new_text)
            self.log(f"[修改] {rel}（{fname} 里插一行转发）")
            self.changes.append(("patched", str(rel), bak))

    @staticmethod
    def _ensure_include(text: str, include_line: str) -> str:
        if include_line in text:
            return text
        nl = nl_of(text)
        lines = text.split(nl)
        last = -1
        for i, line in enumerate(lines[:200]):
            if line.strip().startswith("#include"):
                last = i
        if last < 0:
            return text
        lines.insert(last + 1, include_line)
        return nl.join(lines)

    # ---- 3) freertos.c ----
    def _patch_freertos(self, scan: Scan) -> None:
        assert scan.freertos is not None
        path = scan.freertos
        text = read_text(path)
        if MARKER in text:
            self.log("[不变] Core/Src/freertos.c（已配置过）")
            self.changes.append(("unchanged", str(path.relative_to(scan.root)), None))
            return
        if self.opts.dry_run:
            self.log("[将修改] Core/Src/freertos.c（插入线程声明/属性/osThreadNew）")
            self.changes.append(("would-patch", str(path.relative_to(scan.root)), None))
            return

        nl = nl_of(text)
        thr = self.cfg["thread"]
        blocks = self.cfg["freertos"]["blocks"]

        code_proto = f"""void APP_Unitree_GO_Task(void *argument);   /* {MARKER}: 宇树 GO-M8010-6 示例任务 */"""
        code_vars = f"""/* {MARKER}: 宇树 GO-M8010-6 线程属性 */
const osThreadAttr_t unitree_go_attributes = {{
  .name = "{thr['name']}",
  .stack_size = {thr['stack_words']} * 4,
  .priority = (osPriority_t) {thr['priority']},
}};"""
        code_threads = f"""  osThreadNew(APP_Unitree_GO_Task, NULL, &unitree_go_attributes);   /* {MARKER} */"""
        code_include = f"""/* {MARKER}: 宇树 GO-M8010-6 移植层 */
#include "Unitree_GO_port.h\""""

        new_text = text
        applied, missing = [], []
        for key, code in (("includes", code_include), ("prototypes", code_proto),
                          ("variables", code_vars), ("threads", code_threads)):
            begin, end = (self.cfg["freertos"]["includes_block"] if key == "includes"
                          else blocks[key])
            new_text, ok = self._insert_after_line(new_text, begin, code)
            if ok:
                applied.append(key)
            else:
                missing.append(key)

        if "threads" in missing or "variables" in missing or "prototypes" in missing:
            raise RuntimeError(
                "freertos.c 里找不到 USER CODE 插入锚点（" + "，".join(missing) +
                "）—— 这份工程可能不是 CubeMX 生成的，请按 README 手动加线程")

        bak = self._backup(path)
        write_text(path, new_text)
        rel = path.relative_to(scan.root)
        self.log(f"[修改] {rel}（插入 {', '.join(applied)}）")
        self.changes.append(("patched", str(rel), bak))

    # ---- 3b) main.c（裸机工程） ----
    def _patch_main(self, scan: Scan) -> None:
        assert scan.main_c is not None
        path = scan.main_c
        text = read_text(path)
        rel = path.relative_to(scan.root)

        if MARKER in text:
            self.log(f"[不变] {rel}（main 里已接好）")
            self.changes.append(("unchanged", str(rel), None))
            return
        if self.opts.dry_run:
            self.log(f"[将修改] {rel}（插 include / App_Init / App_Step）")
            self.changes.append(("would-patch", str(rel), None))
            return

        blocks = self.cfg["main"]["blocks"]
        snippets = (
            ("includes", '#include "Unitree_GO_port.h"'),
            ("init", f"  Unitree_GO_App_Init();      /* {MARKER}: 串口 + DMA + 电机句柄 + 记零点 */"),
            ("loop", (f"    Unitree_GO_App_Step();      /* {MARKER}: 位置伺服 + 收发 */"
                      f"\n    HAL_Delay(UG_PORT_PERIOD_MS);")),
        )

        new_text, missing = text, []
        for key, code in snippets:
            begin, _end = blocks[key]
            new_text, ok = self._insert_after_line(new_text, begin, code)
            if not ok:
                missing.append(key)

        if missing:
            self.log(f"[跳过] {rel} 里找不到 USER CODE 锚点（{', '.join(missing)}），"
                     "请手动加：Unitree_GO_App_Init(); + while(1) 里 Unitree_GO_App_Step();")
            return

        bak = self._backup(path)
        write_text(path, new_text)
        self.log(f"[修改] {rel}（插入 include / App_Init / App_Step）")
        self.changes.append(("patched", str(rel), bak))

    @staticmethod
    def _insert_after_line(text: str, anchor: str, code: str) -> tuple[str, bool]:
        if anchor not in text:
            return text, False
        idx = text.index(anchor)
        nl = nl_of(text)
        line_end = text.find(nl, idx)
        if line_end < 0:
            return text, False
        pos = line_end + len(nl)
        return text[:pos] + code + nl + text[pos:], True

    # ---- 4) uvprojx ----
    def _patch_uvprojx(self, scan: Scan, with_port: bool = True) -> None:
        path = scan.uvprojx
        text = read_text(path)
        nl = nl_of(text)
        lay = self.cfg["layout"]
        prefix = lay["port_prefix"]
        ucfg = self.cfg["uvprojx"]
        drv = lay["driver_dir"].replace("/", "\\")

        wanted = [("Unitree_GO.c", f"..\\{drv}\\Unitree_GO.c")]
        if with_port:
            wanted.append((f"{prefix}.c", f"..\\{drv}\\{prefix}.c"))

        new_text = text
        added = []
        for fname, fpath in wanted:
            new_text, ok = self._add_uvprojx_file(new_text, fname, fpath, nl)
            if ok:
                added.append(fname)

        new_text, inc_ok = self._ensure_include_path(new_text, ucfg["include_entry"])
        if inc_ok:
            added.append(f"IncludePath += {ucfg['include_entry']}")

        if new_text == text:
            self.log("[不变] R1.uvprojx（源文件已登记）")
            self.changes.append(("unchanged", str(path.relative_to(scan.root)), None))
            return
        if self.opts.dry_run:
            self.log(f"[将修改] {path.name}：" + "，".join(added))
            self.changes.append(("would-patch", str(path.relative_to(scan.root)), None))
            return

        # 保险：改完必须是合法 XML
        import xml.etree.ElementTree as ET
        ET.fromstring(new_text.encode("utf-8"))

        bak = self._backup(path)
        write_text(path, new_text)
        self.log(f"[修改] {path.name}（" + "，".join(added) + "）")
        self.changes.append(("patched", str(path.relative_to(scan.root)), bak))

    def _add_uvprojx_file(self, text: str, fname: str, fpath: str, nl: str) -> tuple[str, bool]:
        entry = (f"            <File>{nl}"
                 f"              <FileName>{fname}</FileName>{nl}"
                 f"              <FileType>1</FileType>{nl}"
                 f"              <FilePath>{fpath}</FilePath>{nl}"
                 f"            </File>{nl}")

        groups = [self.cfg["uvprojx"]["preferred_group"], self.cfg["uvprojx"]["fallback_group"]]
        starts: list[int] = []
        for group in groups:
            starts = [m.start() for m in
                      re.finditer(rf"<Group>\s*<GroupName>{re.escape(group)}</GroupName>", text)]
            if starts:
                break

        if not starts:
            # 没有目标组：新建一个组，插在 </Groups> 前面
            block = (f"        <Group>{nl}"
                     f"          <GroupName>{groups[-1]}</GroupName>{nl}"
                     f"          <Files>{nl}"
                     f"{entry}"
                     f"          </Files>{nl}"
                     f"        </Group>{nl}")
            idx = text.find("</Groups>")
            if idx < 0:
                return text, False
            return text[:idx] + block + text[idx:], True

        # 多个 Target 时每个同名组都要登记；从后往前改，避免前面插入让后面的位置失效
        changed = False
        for g_start in reversed(starts):
            g_end = text.find("</Group>", g_start)
            if g_end < 0:
                continue
            if f"<FileName>{fname}</FileName>" in text[g_start:g_end]:
                continue
            files_close = text.find("</Files>", g_start, g_end)
            if files_close < 0:
                continue
            line_start = text.rfind(nl, 0, files_close) + 1   # 插在 </Files> 这一行的行首
            text = text[:line_start] + entry + text[line_start:]
            changed = True
        return text, changed

    def _ensure_include_path(self, text: str, entry: str) -> tuple[str, bool]:
        changed = False

        def repl(m: re.Match) -> str:
            nonlocal changed
            value = m.group(2).strip()
            if not value or "../Core/Inc" not in value:
                return m.group(0)          # 只补主工程的 Cads，不动分组的
            parts = [p.strip() for p in value.split(";") if p.strip()]
            if entry in parts:
                return m.group(0)
            changed = True
            return f"{m.group(1)}{value};{entry}{m.group(3)}"

        out = re.sub(r"(<IncludePath>)([^<]*)(</IncludePath>)", repl, text)
        return out, changed

    # ---- 5) 报告 ----
    def _write_report(self, scan: Scan) -> None:
        if self.opts.dry_run:
            return
        if self.backup_root is None:
            self.backup_root = scan.mdkarm / self.cfg["layout"]["backup_dir"] / datetime.now().strftime("%Y%m%d_%H%M%S")
        self.backup_root.mkdir(parents=True, exist_ok=True)
        lines = [
            f"Unitree_GO 一键配置报告   {datetime.now():%Y-%m-%d %H:%M:%S}",
            f"工具版本 {VERSION}",
            "-" * 60,
            f"工程根目录 : {scan.root}",
            f"Keil 工程  : {scan.uvprojx}",
            f"驱动目录   : {scan.driver_dir}",
            f"485 通道   : {self._spec()['channel']}  ({scan.uart_reason})",
            f"DMA        : {'复用工程自带' if scan.dma_owned_by == 'project' else '移植层生成'} "
            f"{scan.dma_stream or '-'} / {scan.dma_irq or '-'}",
            f"电机 ID    : {self.opts.motor_id}   减速比 {self.opts.ratio}",
            f"示例代码   : {'未生成' if not self.opts.with_task else ('裸机 App_Init/App_Step' if not scan.freertos else 'RTOS 线程 UnitreeGO')}",
            "",
            "改动明细：",
        ]
        for action, desc, bak in self.changes:
            lines.append(f"  - [{action}] {desc}" + (f"   备份: {bak}" if bak else ""))
        if scan.warnings:
            lines += ["", "注意："] + [f"  * {w}" for w in scan.warnings]
        lines += [
            "",
            "下一步：",
            "  1) 用 Keil 打开 .uvprojx，Rebuild，应能看到 Unitree_GO.c / Unitree_GO_port.c 参与编译",
            "  2) 确认电机 ID 与 UG_PORT_MOTOR_ID 一致（宇树 MotorTools -> swboot）",
            "  3) 把电机插到对应的板载 485 口（通道 1 = RS485-U2 / USART2）",
            "  4) 调试器 Watch 里看 g_go_joint.ok_cnt / timeout_cnt / crc_err_cnt",
            "  5) 若收不到回包：换另一路 485、改 DE 极性、检查 A/B 与共地",
        ]
        (self.backup_root / "install_report.txt").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
def run_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    cfg = load_config()
    d = cfg["defaults"]

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(f"Unitree_GO 一键配置  v{VERSION}")
            self.geometry("880x640")
            self.minsize(760, 560)
            self.cfg = cfg
            self.path_var = tk.StringVar(value=self._last_path())
            self.channel_var = tk.IntVar(value=int(d["channel"]))
            self.id_var = tk.StringVar(value=str(d["motor_id"]))
            self.period_var = tk.StringVar(value=str(d["period_ms"]))
            self.pos_var = tk.StringVar(value=str(d["demo_pos"]))
            self.kp_var = tk.StringVar(value=str(d["demo_kp"]))
            self.kd_var = tk.StringVar(value=str(d["demo_kd"]))
            self.task_var = tk.BooleanVar(value=True)
            self.dry_var = tk.BooleanVar(value=False)
            self.uart_var = tk.StringVar(value=str(d.get("uart", "")))
            self.de_var = tk.StringVar(value=str(d.get("de_pin", "")))
            self.baud_var = tk.StringVar(value=str(d.get("baud", 4000000)))
            self._build()

        # ---- 上次路径 ----
        @staticmethod
        def _last_path() -> str:
            try:
                return json.loads(LAST_PATH_FILE.read_text(encoding="utf-8")).get("last", "")
            except Exception:
                return ""

        def _save_last(self, p: str) -> None:
            try:
                LAST_PATH_FILE.write_text(json.dumps({"last": p}, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

        # ---- 界面 ----
        def _build(self) -> None:
            pad = {"padx": 10, "pady": 4}

            top = ttk.LabelFrame(self, text="1. 选择 Keil 工程目录（MDK-ARM）")
            top.pack(fill="x", **pad)
            row = ttk.Frame(top)
            row.pack(fill="x", padx=8, pady=8)
            ttk.Entry(row, textvariable=self.path_var).pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="浏览…", command=self.browse, width=8).pack(side="left", padx=(6, 0))
            ttk.Button(row, text="仅检测", command=self.scan_click, width=8).pack(side="left", padx=(6, 0))
            ttk.Label(top, foreground="#555",
                      text="填 MDK-ARM 目录（含 .uvprojx）；填工程根目录也可以，会自动找 MDK-ARM。"
                      ).pack(anchor="w", padx=10, pady=(0, 8))

            opt = ttk.LabelFrame(self, text="2. 选项（一般不用改）")
            opt.pack(fill="x", **pad)
            r1 = ttk.Frame(opt)
            r1.pack(fill="x", padx=8, pady=6)
            ttk.Label(r1, text="485 通道：").pack(side="left")
            ttk.Radiobutton(r1, text="1（USART2 / PD5 PD6，DE=PD4）",
                            variable=self.channel_var, value=1).pack(side="left")
            ttk.Radiobutton(r1, text="2（USART3 / PD8 PD9，DE=PB14）",
                            variable=self.channel_var, value=2).pack(side="left", padx=(12, 0))
            ttk.Radiobutton(r1, text="3（自选串口）",
                            variable=self.channel_var, value=3).pack(side="left", padx=(12, 0))

            # 自选串口（通道 3）：勾 3 时生效
            r1b = ttk.Frame(opt)
            r1b.pack(fill="x", padx=8, pady=(0, 6))
            ttk.Label(r1b, text="   自选串口：").pack(side="left")
            ttk.Entry(r1b, width=10, textvariable=self.uart_var).pack(side="left")
            ttk.Label(r1b, text="（如 USART6；需在 CubeMX 里已配好）   方向脚：").pack(side="left")
            ttk.Entry(r1b, width=7, textvariable=self.de_var).pack(side="left")
            ttk.Label(r1b, text="（如 PB14，留空=两线/三线无方向脚）   波特率：").pack(side="left")
            ttk.Entry(r1b, width=10, textvariable=self.baud_var).pack(side="left")

            r2 = ttk.Frame(opt)
            r2.pack(fill="x", padx=8, pady=6)
            ttk.Label(r2, text="电机 ID：").pack(side="left")
            ttk.Spinbox(r2, from_=0, to=15, width=5, textvariable=self.id_var).pack(side="left")
            ttk.Label(r2, text="   周期 ms：").pack(side="left")
            ttk.Spinbox(r2, from_=2, to=100, width=5, textvariable=self.period_var).pack(side="left")
            ttk.Label(r2, text="   目标位置 rad：").pack(side="left")
            ttk.Entry(r2, width=6, textvariable=self.pos_var).pack(side="left")
            ttk.Label(r2, text="   kp：").pack(side="left")
            ttk.Entry(r2, width=6, textvariable=self.kp_var).pack(side="left")
            ttk.Label(r2, text="   kd：").pack(side="left")
            ttk.Entry(r2, width=6, textvariable=self.kd_var).pack(side="left")

            r3 = ttk.Frame(opt)
            r3.pack(fill="x", padx=8, pady=(2, 8))
            ttk.Checkbutton(r3, text="生成示例任务（上电零力矩 2 s -> 位置伺服）",
                            variable=self.task_var).pack(side="left")
            ttk.Checkbutton(r3, text="只检查不写入（Dry run）",
                            variable=self.dry_var).pack(side="left", padx=(16, 0))

            btns = ttk.Frame(self)
            btns.pack(fill="x", **pad)
            self.go_btn = ttk.Button(btns, text="一键配置", command=self.install_click)
            self.go_btn.pack(side="left")
            ttk.Button(btns, text="打开备份目录", command=self.open_backup).pack(side="left", padx=6)
            ttk.Button(btns, text="打开库目录", command=self.open_lib).pack(side="left")
            ttk.Button(btns, text="退出", command=self.destroy).pack(side="right")

            logf = ttk.LabelFrame(self, text="3. 日志")
            logf.pack(fill="both", expand=True, **pad)
            self.log_box = scrolledtext.ScrolledText(logf, height=18, wrap="word",
                                                     font=("Consolas", 9))
            self.log_box.pack(fill="both", expand=True, padx=8, pady=8)
            self.log_box.configure(state="disabled")

        # ---- 交互 ----
        def browse(self) -> None:
            p = filedialog.askdirectory(title="选择 MDK-ARM 目录（或工程根目录）")
            if p:
                self.path_var.set(p)

        def open_lib(self) -> None:
            self._open(LIB_DIR)

        def open_backup(self) -> None:
            p = self.path_var.get().strip()
            if not p:
                self._msg("info", "提示", "先选择工程目录")
                return
            base = Path(p)
            if not (base / self.cfg["layout"]["backup_dir"]).is_dir() and (base / "MDK-ARM").is_dir():
                base = base / "MDK-ARM"
            target = base / self.cfg["layout"]["backup_dir"]
            if not target.is_dir():
                self._msg("info", "提示", "还没有备份目录（尚未配置过）")
                return
            self._open(target)

        @staticmethod
        def _open(p: Path) -> None:
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(p))          # noqa: S606
                elif sys.platform == "darwin":
                    os.system(f'open "{p}"')
                else:
                    os.system(f'xdg-open "{p}"')
            except Exception:
                pass          # 打不开就算了，不要因为一个弹窗把流程搞崩

        def _msg(self, kind: str, title: str, text: str) -> None:
            """弹窗包装：窗口系统异常时只写日志，绝不吞掉/覆盖已经完成的配置结果。"""
            self._log(f"[{title}] {text}")
            try:
                {"error": messagebox.showerror,
                 "warn": messagebox.showwarning}.get(kind, messagebox.showinfo)(title, text)
            except Exception:
                pass

        def _log(self, msg: str) -> None:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
            self.update_idletasks()

        def _collect_options(self) -> Options:
            ch = int(self.channel_var.get())
            uart = self.uart_var.get().strip() if ch == 3 else ""
            if ch == 3 and not uart:
                raise ValueError("选了「3 自选串口」就必须填串口名，例如 USART6")
            baud_txt = self.baud_var.get().strip()
            return Options(
                channel=ch,
                motor_id=int(self.id_var.get()),
                period_ms=int(self.period_var.get()),
                demo_pos=float(self.pos_var.get()),
                demo_kp=float(self.kp_var.get()),
                demo_kd=float(self.kd_var.get()),
                with_task=bool(self.task_var.get()),
                dry_run=bool(self.dry_var.get()),
                uart=uart,
                de_pin=self.de_var.get().strip() if ch == 3 else "",
                baud=int(baud_txt) if (ch == 3 and baud_txt) else 0,
            )

        def scan_click(self) -> None:
            p = self.path_var.get().strip()
            if not p:
                self._msg("warn", "提示", "请先选择 MDK-ARM 目录")
                return
            try:
                inst = Installer(Path(p), self._collect_options(), self.cfg, log=self._log)
                s = inst.resolve()
                self._log("—" * 40)
                self._log(f"工程根目录 : {s.root}")
                self._log(f"Keil 工程  : {s.uvprojx.name}")
                self._log(f"驱动目录   : {s.driver_dir}")
                self._log(f"串口策略   : {s.uart_reason}")
                self._log(f"已装驱动   : {'是' if s.has_driver else '否'}    已装移植层: {'是' if s.has_port else '否'}")
                if s.other_user_files:
                    self._log("其它接入点 : " + "，".join(s.other_user_files[:5]))
                for w in s.warnings:
                    self._log(f"[注意] {w}")
                self._log("—" * 40)
            except Exception as e:
                self._log(f"[错误] {e}")
                self._msg("error", "检测失败", str(e))

        def install_click(self) -> None:
            p = self.path_var.get().strip()
            if not p:
                self._msg("warn", "提示", "请先选择 MDK-ARM 目录")
                return
            try:
                opts = self._collect_options()
            except ValueError as e:
                self._msg("error", "参数错误", f"数值填错了：{e}")
                return
            self._save_last(p)
            self.go_btn.configure(state="disabled")
            self._log("=" * 52)
            self._log(f"开始配置：{p}")
            try:
                inst = Installer(Path(p), opts, self.cfg, log=self._log)
                changes = inst.run()
                changed = [c for c in changes if c[0] in ("written", "patched")]
                self._log("=" * 52)
                if opts.dry_run:
                    self._log("检查完成（Dry run，未写入任何文件）")
                elif changed:
                    self._log(f"配置完成：{len(changed)} 处改动"
                              + (f"，备份在 {inst.backup_root}" if inst.backup_root else ""))
                    self._msg("info-later", "完成", "配置完成！\n请用 Keil 打开工程 Rebuild。")
                else:
                    self._log("工程已是配置状态，无需改动")
                    self._msg("info", "完成", "工程已是配置状态，无需改动。")
            except Exception as e:
                self._log(f"[错误] {e}")
                self._log(traceback.format_exc())
                self._msg("error", "配置失败", str(e))
            finally:
                self.go_btn.configure(state="normal")

    app = App()
    app.mainloop()
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def run_cli(args) -> int:
    cfg = load_config()
    d = cfg["defaults"]
    opts = Options(
        channel=args.channel if args.channel else int(d["channel"]),
        motor_id=args.id if args.id is not None else int(d["motor_id"]),
        ratio=args.ratio if args.ratio else float(d["ratio"]),
        period_ms=args.period if args.period else int(d["period_ms"]),
        demo_pos=args.pos if args.pos is not None else float(d["demo_pos"]),
        demo_kp=args.kp if args.kp is not None else float(d["demo_kp"]),
        demo_kd=args.kd if args.kd is not None else float(d["demo_kd"]),
        with_task=not args.no_task,
        dry_run=args.dry_run,
        force=args.force,
        uart=(args.uart or "").strip(),
        de_pin=(getattr(args, "de", "") or "").strip(),
        baud=(args.baud or 0),
    )
    inst = Installer(Path(args.mdkarm), opts, cfg, log=print)
    try:
        inst.run()
    except Exception as e:
        print(f"[错误] {e}")
        return 1
    print("\n完成。" + ("（Dry run，未写入）" if args.dry_run else ""))
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")     # 中文日志
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="Unitree_GO（宇树 GO-M8010-6）Keil 工程一键配置工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="不带参数运行 = 打开 GUI。")
    ap.add_argument("--mdkarm", help="MDK-ARM 目录（含 .uvprojx），也可以给工程根目录")
    ap.add_argument("--channel", type=int, choices=(1, 2), help="485 通道：1=USART2/PD4，2=USART3/PB14")
    ap.add_argument("--uart", help="自选串口（通道 3）：USART1…USART10 / UART4…UART9 / LPUART1，"
                                   "要求工程里已经在 CubeMX 配好这一路")
    ap.add_argument("--de", metavar="PIN", help="自选串口的方向脚，如 PB14；留空/ none = 无方向脚"
                                                "（两线 485 或三线 UART 直连）")
    ap.add_argument("--baud", type=int, help="自选串口的波特率，默认 4000000")
    ap.add_argument("--id", type=int, help="电机 ID（0~15）")
    ap.add_argument("--ratio", type=float, help="减速比，GO-M8010-6 为 6.33")
    ap.add_argument("--period", type=int, help="控制周期 ms")
    ap.add_argument("--pos", type=float, help="示例目标位置（关节侧 rad）")
    ap.add_argument("--kp", type=float, help="示例 kp（关节侧）")
    ap.add_argument("--kd", type=float, help="示例 kd（关节侧）")
    ap.add_argument("--no-task", action="store_true", help="不生成示例任务、不改 freertos.c")
    ap.add_argument("--dry-run", action="store_true", help="只检查，不写入任何文件")
    ap.add_argument("--force", action="store_true",
                    help="工程里已有其它 GO 电机接入代码时，仍强制生成移植层并接线程")
    ap.add_argument("--version", action="version", version=f"Unitree_GO configurator {VERSION}")
    args = ap.parse_args()

    if args.mdkarm:
        return run_cli(args)
    try:
        return run_gui()
    except ImportError:
        ap.error("当前 Python 没有 tkinter，请用 --mdkarm 走命令行模式")


if __name__ == "__main__":
    sys.exit(main())
