# Unitree_GO_dm_lib

宇树 **GO-M8010-6** 关节电机驱动（STM32 · 半双工 RS485 · **DMA + 空闲中断接收**）＋ **Keil MDK 工程一键配置工具**（Python + tkinter GUI）。

输入一个 `MDK-ARM` 目录，点一下按钮，工具就会把驱动、移植层（含串口 / DMA / 中断 / 回调）、FreeRTOS 线程和 Keil 工程配置全部装好，并自动备份所有被改动的文件。

```
┌─────────────────────────────────────────────────────────────┐
│  Unitree_GO 一键配置  v1.1.0                                │
│                                                             │
│  1. 选择 Keil 工程目录（MDK-ARM）                            │
│  [ D:\27RC\dm_demo\MDK-ARM                     ] [浏览…] [仅检测] │
│                                                             │
│  2. 选项（一般不用改）                                       │
│  485 通道：(•) 1（USART2 / PD5 PD6，DE=PD4）  ( ) 2（USART3…）│
│  电机 ID：1   周期 ms：10   目标位置 rad：0.5  kp：4.0  kd：1.0│
│  [x] 生成示例任务   [ ] 只检查不写入（Dry run）               │
│                                                             │
│  [一键配置]  [打开备份目录]  [打开库目录]              [退出]│
│                                                             │
│  3. 日志                                                    │
│  DMA 策略    : 生成（DMA1_Stream3 / DMA1_Stream3_IRQn）      │
│  回调接线    : 工程已有 HAL 回调 -> 插转发                    │
│  [写入] bsp\uper\Unitree_GO_port.c                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 目录

1. [目录结构](#1-目录结构)
2. [快速开始](#2-快速开始)
3. [工具具体改了什么](#3-工具具体改了什么)
4. [config.json 说明](#4-configjson-说明)
5. [串口与 DMA 配置（重点）](#5-串口与-dma-配置重点)
6. [生成的移植层](#6-生成的移植层unitree_go_portch)
7. [驱动 API](#7-驱动-api)
8. [报文协议](#8-报文协议)
9. [故障排查](#9-故障排查)
10. [FAQ](#10-faq)

---

## 1. 目录结构

```
Unitree_GO_dm_lib/
├── README.md                        ← 本文件
├── config.json                      ← 工具配置（路径/锚点/DMA/默认值）
├── Unitree_GO.c                     ← 驱动实现
├── Unitree_GO.h                     ← 驱动头文件
└── Unitree_GO_configurator.py       ← 一键配置工具（GUI + CLI）
```

驱动分两层：

| 层 | 文件 | 谁维护 | 内容 |
|---|---|---|---|
| 协议层 | `Unitree_GO.c/.h` | 本库，跨工程通用 | 组帧/解帧、CRC、定标、模式、**DMA 空闲中断收发**、按 ID 分发 |
| 移植层 | `Unitree_GO_port.c/.h`（**工具生成到目标工程**） | 每个工程一份 | 4 Mbps 串口、485 方向脚、**DMA 通道**、中断入口、HAL 回调、示例任务 |

换板子只改移植层，协议层一行不用动。

---

## 2. 快速开始

### 2.1 环境

- Windows + Python 3.8 以上（官方安装包自带 `tkinter`，无需 pip 安装）
- 目标工程：STM32CubeMX + Keil MDK（STM32H7xx HAL + FreeRTOS + `cmsis_os.h`）
- 板子：DM-MC-Board02（或任何有 USART2/USART3 + RS485 方向脚的板子）
- **接收要 DMA**：工具会自动配好；如果你自己在 CubeMX 里配，见[第 5 章](#5-串口与-dma-配置重点)

### 2.2 GUI

```bat
python Unitree_GO_configurator.py
```

1. 「浏览…」选中工程的 `MDK-ARM` 目录（填工程根目录也行，工具会自动往下找）；
2. 选 485 通道（默认 1）；
3. 填电机 ID（**必须和电机里烧的一致**，出厂未设置时是 15）；
4. 点「一键配置」。

日志里出现 `配置完成` 就结束了，接着用 Keil 打开 `.uvprojx`，**Rebuild**。

> 不确定工程状态时先点「仅检测」，或勾「只检查不写入」，工具会把检测结果（串口策略 / DMA 策略 / 回调接线）和将要做的事都列出来，不改任何文件。

### 2.3 命令行

```bat
:: 配置（默认通道 1、ID 1）
python Unitree_GO_configurator.py --mdkarm "D:\27RC\dm_demo\MDK-ARM"

:: 先看要改什么
python Unitree_GO_configurator.py --mdkarm "..." --dry-run

:: 换通道 / ID / 控制参数
python Unitree_GO_configurator.py --mdkarm "..." --channel 2 --id 7 --pos 0.3 --kp 8 --kd 0.5

:: 只装驱动，不加示例任务
python Unitree_GO_configurator.py --mdkarm "..." --no-task
```

| 参数 | 含义 |
|---|---|
| `--mdkarm PATH` | MDK-ARM 目录（含 `.uvprojx`），也可以是工程根目录 |
| `--channel {1,2}` | 485 通道：1 = USART2/PD5 PD6，DE=PD4；2 = USART3/PD8 PD9，DE=PB14 |
| `--id N` | 电机 ID（0~15） |
| `--ratio F` | 减速比，GO-M8010-6 固定 6.33 |
| `--period N` | 控制周期 ms（默认 10，建议 ≥ 2） |
| `--pos F` `--kp F` `--kd F` | 示例任务的目标位置 / 刚度 / 阻尼（关节侧） |
| `--no-task` | 不生成示例任务、不改 `freertos.c` |
| `--dry-run` | 只检查不写入 |
| `--force` | 工程里已有别的 GO 接入代码时，仍强制生成移植层 |

### 2.4 手工（不用脚本）

1. 把 `Unitree_GO.c/.h` 拷到 `<工程>/bsp/uper/`，改 `UNITREE_GO_485_CHANNEL`；
2. 按第 5 章在 CubeMX 里配好串口 + DMA + NVIC（或照抄工具生成的 `Unitree_GO_port.c`）；
3. 在 `HAL_UARTEx_RxEventCallback` / `HAL_UART_ErrorCallback` 里各加一行转发；
4. Keil 工程加入 `Unitree_GO.c`，头文件路径加 `../bsp/uper`；
5. `freertos.c` 的 USER CODE 区里建线程。

---

## 3. 工具具体改了什么

工具做 5 件事，**全部幂等**（重复运行不会重复插入），改动前全部备份：

| # | 目标 | 动作 | 备份 |
|---|---|---|---|
| 1 | `bsp/uper/Unitree_GO.c` `.h` | 复制（`.h` 里的通道宏按选择写入）。已有且内容相同 → 跳过 | 内容不同才备份 |
| 2 | `bsp/uper/Unitree_GO_port.c` `.h` | 按当前选项生成/覆盖：**串口初始化 + DMA 初始化 + 中断入口 + HAL 回调 + 示例任务** | 有旧文件才备份 |
| 3 | `app/usart_it.c` 等（工程里已有 HAL 回调时） | 在 `HAL_UARTEx_RxEventCallback` / `HAL_UART_ErrorCallback` 函数体开头各插一行转发（+ 补 `#include`） | ✔ |
| 4 | `Core/Src/freertos.c` | 在 4 个 `USER CODE` 区插入 `#include`、线程声明、线程属性、`osThreadNew()` | ✔ |
| 5 | `R1.uvprojx` | 往 `bsp_upper` 组登记 `Unitree_GO.c` / `Unitree_GO_port.c`；给主 target 的 `IncludePath` 补 `../bsp/uper` | ✔ |

- 备份位置：`<MDK-ARM>/Unitree_GO_backup/<yyyyMMdd_HHmmss>/`，保留原相对目录结构，并附 `install_report.txt`。
- **只改 CubeMX 的 `USER CODE` 区**，CubeMX 重新生成代码时插入不会被冲掉；生成的 `Unitree_GO_port.*` 在 `bsp/uper/` 下，CubeMX 不碰。
- 检测到工程里**已有别人写的** GO 电机接入代码（例如 `app/fdcan_it.c` 里的 `APP_Unitree_test`）时，只同步驱动文件，不生成移植层/线程（避免两个任务抢同一路半双工 485）；此时驱动会自动退回阻塞接收（见 5.6），旧代码仍能跑。要覆盖请加 `--force`。
- 串口/DMA 的"复用还是自己建"是**自动判断**的：工程已有 `huart2/huart3` → 复用；已有 `DMA_REQUEST_USART2_RX` → 复用 DMA；都没有 → 移植层自己建，并自动挑一个**空闲的 DMA 流**（跳过工程已用的流和已有中断函数的流）。

---

## 4. config.json 说明

所有可调项都在 `config.json`，改完不用动 Python 代码。

| 键 | 含义 | 默认 |
|---|---|---|
| `layout.driver_dir` | 驱动放到工程的哪个目录（相对工程根） | `bsp/uper` |
| `layout.port_prefix` | 移植层文件名前缀 | `Unitree_GO_port` |
| `layout.freertos_c` | 要插线程的 RTOS 文件 | `Core/Src/freertos.c` |
| `layout.usart_c` / `usart_h` | 用来探测"工程是否已有串口"的文件 | `Core/Src/usart.c` / `Core/Inc/usart.h` |
| `layout.uvprojx_glob` | Keil 工程文件匹配模式 | `*.uvprojx` |
| `layout.backup_dir` | 备份目录（相对 MDK-ARM） | `Unitree_GO_backup` |
| `uvprojx.preferred_group` / `fallback_group` | 文件登记进哪个组 / 组不存在时新建的组名 | `bsp_upper` / `Unitree_GO` |
| `uvprojx.include_entry` | 补进 `IncludePath` 的路径 | `../bsp/uper` |
| `freertos.blocks.*` | 4 个插入锚点（USER CODE 标记） | CubeMX 标准标记 |
| `thread.name` / `stack_words` / `priority` | 生成线程的名字、栈（字）、优先级 | `UnitreeGO` / `512` / `osPriorityNormal` |
| `dma.irq_priority` | 生成的 DMA / 串口中断优先级 | `5` |
| `dma.controller` / `fallback` | 优先用哪个 DMA 控制器 | `DMA1` / `DMA2` |
| `callbacks.rx_event` / `error` | 工程里 HAL 回调的函数名（用于探测和插转发） | `HAL_UARTEx_RxEventCallback` / `HAL_UART_ErrorCallback` |
| `defaults.*` | GUI / CLI 默认值（通道、ID、周期、kp、kd、位置） | 见文件 |
| `channel_map.*` | 每路 485 的串口、引脚、DE、AF、DMA 请求号 | 见文件 |
| `marker` | 幂等标记，出现在所有插入片段里 | `UNITREE_GO_AUTOCONFIG` |

---

## 5. 串口与 DMA 配置（重点）

### 5.1 硬件通道

DM-MC-Board02 板载两路高速 RS485（最高 10 Mbps，丝印 RS485-U2 / RS485-U3），GO-M8010-6 固定 **4 Mbps / 8 数据位 / 无校验 / 1 停止位**：

| 通道 | 串口 | TX | RX | DE（方向脚） | DMA 请求（DMAMUX1） |
|---|---|---|---|---|---|
| 1 | USART2 | PD5 | PD6 | PD4 | `DMA_REQUEST_USART2_RX` = 43 |
| 2 | USART3 | PD8 | PD9 | PB14 | `DMA_REQUEST_USART3_RX` = 45 |

选通道：`Unitree_GO.h` 里的 `UNITREE_GO_485_CHANNEL`（1 或 2），工具会按 GUI/CLI 的选择写好。

### 5.2 CubeMX 里怎么配

**① 串口（Connectivity → USART2）**

| 项 | 值 |
|---|---|
| Mode | Asynchronous |
| Baud Rate | **4000000** |
| Word Length | 8 Bits（无校验） |
| Parity | None |
| Stop Bits | 1 |
| Oversampling | 16 |
| 引脚 | PD5 = USART2_TX，PD6 = USART2_RX（CubeMX 自动配成 AF7，速度 High） |

**② DMA（USART2 → DMA Settings → Add）**

| 项 | 值 | 说明 |
|---|---|---|
| DMA Request | **USART2_RX** | 只配接收；发送用阻塞 API |
| Stream | 任选一个空闲流（CubeMX 默认 DMA1 Stream0/2/3…） | **不能和工程里别的外设撞车** |
| Direction | Peripheral To Memory | 固定 |
| Mode | **Normal** | 每帧结束后驱动会在回调里重新武装 |
| Data Width | Peripheral = **Byte**，Memory = **Byte** | 串口是字节流 |
| Increment Address | Memory ✔ / Peripheral ✘ | |
| Priority | Low | 16 字节一帧，不急 |

> 打开 **Circular** 也能用，但驱动每次 IDLE 后都会重新武装，Normal 更直观。

**③ NVIC（USART2 → NVIC Settings）**

| 中断 | 必须 | 原因 |
|---|---|---|
| **USART2 global interrupt** | ✔ | 空闲中断（IDLE）由串口中断上报，HAL 在中断里回调 `HAL_UARTEx_RxEventCallback` |
| **DMA1 Stream3 global interrupt**（编号以你选的流为准） | ✔ | DMA 传输完成/错误中断 |
| 优先级 | 与工程其它串口一致（CubeMX 默认 5） | 驱动不在中断里调用 FreeRTOS API，不受 `configMAX_SYSCALL_INTERRUPT_PRIORITY` 限制 |

**④ 485 方向脚**

PD4（通道 1）/ PB14（通道 2）由 `Unitree_GO_Init()` 初始化成推挽输出，**不需要在 CubeMX 里配**；如果你配了，设成 `GPIO_Output` 即可（驱动会重新初始化）。

**⑤ 生成代码后**

在 `stm32h7xx_it.c` 里 CubeMX 会自动生成 `USART2_IRQHandler()` 和 `DMA1_Stream3_IRQHandler()`，它们分别调用 `HAL_UART_IRQHandler(&huart2)` / `HAL_DMA_IRQHandler(&hdma_usart2_rx)`——驱动就靠这条链拿到 IDLE 事件。**不用改它们**。

### 5.3 工具生成的等价代码（不用 CubeMX 时）

工具在 `Unitree_GO_port.c` 里做了同样的事，可直接照抄：

```c
DMA_HandleTypeDef hdma_usart2_rx;

static void UG_Port_DmaInit(void)
{
    __HAL_RCC_DMA1_CLK_ENABLE();

    hdma_usart2_rx.Instance                 = DMA1_Stream3;            /* 自动挑的空闲流 */
    hdma_usart2_rx.Init.Request             = DMA_REQUEST_USART2_RX;
    hdma_usart2_rx.Init.Direction           = DMA_PERIPH_TO_MEMORY;
    hdma_usart2_rx.Init.PeriphInc           = DMA_PINC_DISABLE;
    hdma_usart2_rx.Init.MemInc              = DMA_MINC_ENABLE;
    hdma_usart2_rx.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
    hdma_usart2_rx.Init.MemDataAlignment    = DMA_MDATAALIGN_BYTE;
    hdma_usart2_rx.Init.Mode                = DMA_NORMAL;
    hdma_usart2_rx.Init.Priority            = DMA_PRIORITY_LOW;
    hdma_usart2_rx.Init.FIFOMode            = DMA_FIFOMODE_DISABLE;
    if (HAL_DMA_Init(&hdma_usart2_rx) != HAL_OK) { Error_Handler(); }

    __HAL_LINKDMA(&huart2, hdmarx, hdma_usart2_rx);   /* 必须在 StartRx 之前 */

    HAL_NVIC_SetPriority(DMA1_Stream3_IRQn, 5, 0);
    HAL_NVIC_EnableIRQ(DMA1_Stream3_IRQn);
}

void USART2_IRQHandler(void)      { HAL_UART_IRQHandler(&huart2); }
void DMA1_Stream3_IRQHandler(void){ HAL_DMA_IRQHandler(&hdma_usart2_rx); }
```

串口本身（4 Mbps 8N1 + PD5/PD6 AF7 + 空闲中断 NVIC）也一并生成：

```c
void HAL_UART_MspInit 等价的初始化在 UG_Port_UartInit() 里；
huart2.Init.BaudRate = 4000000; ... HAL_UART_Init(&huart2);
HAL_NVIC_SetPriority(USART2_IRQn, 5, 0);
HAL_NVIC_EnableIRQ(USART2_IRQn);
```

> 工程里已有 USART2/DMA 时工具不会重复生成；已存在同名中断函数时也不会重复定义（否则会链接报重复符号）。

### 5.4 回调接线（必须，工具自动做）

`HAL_UARTEx_RxEventCallback` / `HAL_UART_ErrorCallback` 是**全局回调，所有串口共用**，所以驱动不占用它们，只要求转发一行。工程里已有这两个函数（本工程在 `app/usart_it.c`），工具会插入：

```c
void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size)
{
    /* UNITREE_GO_AUTOCONFIG: rx: 宇树 GO 电机（DMA + 空闲中断）分发 */
    Unitree_GO_RxEvent(huart, Size);      // 只认 GO 那一路，其它串口原样返回
    ... 原来的 SBUS / 陀螺仪处理 ...
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    /* UNITREE_GO_AUTOCONFIG: err: 宇树 GO 电机（DMA + 空闲中断）分发 */
    Unitree_GO_Error(huart);
    ... 原来的处理 ...
}
```

工程里**没有**这两个函数时，工具在 `Unitree_GO_port.c` 里直接定义（内容就是上面那两行）。

### 5.5 一帧的完整时序（半双工）

```
任务： MITMode()  →  Send()
         │
         ├─ BuildFrame()：限幅 + 组 17 字节 + CRC
         ├─ StopRx()：HAL_UART_AbortReceive()，发送期间关接收（防回波）
         ├─ DE 拉高 → HAL_UART_Transmit(17B, 2ms) → DE 拉低
         └─ StartRx()：HAL_UARTEx_ReceiveToIdle_DMA(buf, 32)
                                   │
电机：  收 17 字节（34 µs）→ 处理 → 回 16 字节
                                   │
总线空闲 1 个字符时间（≈2.5 µs）后 IDLE
                                   ▼
USART2_IRQHandler → HAL_UART_IRQHandler → HAL_UARTEx_RxEventCallback
                                   │
                     Unitree_GO_RxEvent(huart, size)
                       ├─ 在 buf 里找 0xFD 0xEE（容忍残包/回波）
                       ├─ 按帧里的 ID 找到对应句柄
                       ├─ ParseData()：校验 CRC、换算成物理量、rx_seq++
                       └─ StartRx()：重新武装 DMA，等下一帧

任务： SendRecv 里 Poll() 看到 rx_seq 变化 → 返回 1
```

要点：

- **发送不用 DMA**：17 字节 34 µs，阻塞发送反而能精确控制 DE 翻转时刻，半双工更可靠。
- **接收是中断驱动**：任务里 `Send()` 之后不用轮询，`Poll()` 只是读一个计数器。
- **每次 IDLE 后必须重新武装**：HAL 在 IDLE 时已结束本次 DMA 接收，驱动在回调里自动 `StartRx()`。
- **半传输中断被关掉**：`__HAL_DMA_DISABLE_IT(hdmarx, DMA_IT_HT)`，16 字节的帧用不着 HT，少进一次中断。
- **数据不对齐也能活**：DMA 缓冲里按帧头搜索，回波/残包只会被记进 `crc_err_cnt`。

### 5.6 缓冲长度、兜底模式与注意事项

| 项 | 说明 |
|---|---|
| `UNITREE_GO_RX_DMA_LEN` | DMA 缓冲长度（`Unitree_GO.h`，默认 **32**，必须 ≥ 16）。给 32 是为了容忍一帧之后紧跟的回波/残包 |
| `UNITREE_GO_RX_WAIT_MS` | `SendRecv()` 等回包的最长时间（默认 **3 ms**） |
| `UNITREE_GO_RX_USE_DMA` | 设 0 完全退回阻塞接收（不推荐，仅为兼容老工程） |
| 没配 DMA 时 | `huart->hdmarx == NULL` → `rx_armed = 0` → `Poll()` 自动退回 `HAL_UART_Receive()` 阻塞接收。**不会"编译过但收不到"**，只是效率低 |
| 一个串口多个电机 | 回包按帧里的 ID 自动分发到对应句柄；同一路总线只要有一个句柄的 DMA 武装着即可 |
| 中断里做的事 | 找帧头 + 16 字节解析（含浮点换算），µs 级开销；不在中断里调用 FreeRTOS API |
| 重复定义中断 | 若之后在 CubeMX 里也启用了这路串口/DMA，CubeMX 会在 `stm32h7xx_it.c` 再生成一份同名中断 → 把 `Unitree_GO_port.c` 里那两段删掉 |

---

## 6. 生成的移植层（`Unitree_GO_port.c/.h`）

### 6.1 可调宏

| 宏 | 默认 | 说明 |
|---|---|---|
| `UG_PORT_MOTOR_ID` | 1 | 电机 ID，必须与电机里烧的一致 |
| `UG_PORT_RATIO` | 6.33 | 减速比 |
| `UG_PORT_PERIOD_MS` | 10 | 控制周期 ms |
| `UG_PORT_DEMO_POS` | 0.5 | 示例目标位置（关节侧 rad） |
| `UG_PORT_DEMO_KP` | 4.0 | 示例 kp（关节侧，1 = 1 N·m/rad） |
| `UG_PORT_DEMO_KD` | 1.0 | 示例 kd（关节侧） |
| `UG_PORT_SETTLE_MS` | 2000 | 上电先零力矩多久（手拨确认通信） |

### 6.2 接口

```c
void Unitree_GO_Port_Init(void);              // 幂等：串口 + DMA + 电机句柄（Init 内部会 StartRx）
void APP_Unitree_GO_Task(void *argument);     // 示例任务
extern Unitree_GO_HandleTypeDef g_go_joint;   // 全局句柄，调试器直接 Watch
```

示例任务流程：**零力矩 2 s**（手拨能轻松转 = 通信 + FOC 都正常）→ 收一帧 → 把当前位置记成关节 0 点 → **位置伺服到 `UG_PORT_DEMO_POS` 并保持**。

> 默认会真的让电机转动。只想验证通信就把 `UG_PORT_DEMO_KP/KD` 改成 0（等价零力矩），或用 `--no-task` 自己写控制循环。

---

## 7. 驱动 API

句柄结构体（`Unitree_GO_HandleTypeDef`）分四组：硬件绑定（`huart/de_port/de_pin/de_active_high/id/ratio`）、下发指令（`mode/T/W/Pos/K_P/K_W/pos_offset`，转子侧）、反馈（`torque/speed/pos` 转子侧 + `joint_*` 关节侧、`temperature/error_code/foot_force`）、通讯状态（`correct/ok_cnt/timeout_cnt/crc_err_cnt/error_cnt/last_tick` + 接收侧 `rx_dma_buf/rx_armed/rx_size/rx_seq/rx_seen`）。

下面 7.1 先讲**每个字段归谁写**（这是最容易困惑的地方），7.2 起才是 API。

### 7.1 句柄字段由谁赋值

**一句话：你不用手填结构体。** 你只给 `Unitree_GO_Init()` 6 个参数，其余字段由"初始化 / 控制函数 / 协议层"三处在合适的时机写入。

#### ① 配置字段 —— 只有你写（通过 `Init` 参数，一次性）

| 字段 | 谁写 | 时机 | 备注 |
|---|---|---|---|
| `huart` | 你（`Init` 第 2 个参数） | 初始化一次 | `&huart2` / `&huart3`；**要求该串口已经 `HAL_UART_Init` 过** |
| `de_port` / `de_pin` | 你（`Init` 第 3、4 个参数） | 一次 | 驱动会把它配成推挽输出 |
| `de_active_high` | `Init` 取宏 `UNITREE_GO_DE_ACTIVE_HIGH`；**运行时可改** | 现场试极性 | 1 = 高电平发送 |
| `id` | 你（`Init` 第 5 个参数） | 一次 | 大于 15 会被夹到 15（广播） |
| `ratio` | 你（`Init` 第 6 个参数） | 一次 | `<= 0.01` 回退 6.33 |

#### ② 初始化时自动清零 —— `Unitree_GO_Init()` 写

| 字段 | 写入值 |
|---|---|
| `mode` | `0`（LOCK，上电先锁定） |
| `T` `W` `Pos` `K_P` `K_W` | 全 `0` |
| `pos_offset` | `0` |
| `temperature` `error_code` `foot_force` `torque` `speed` `pos` `joint_torque` `joint_speed` `joint_pos` | 全 `0` |
| `correct` `ok_cnt` `timeout_cnt` `crc_err_cnt` `error_cnt` `last_tick` | 全 `0` |
| `rx_armed` `rx_size` `rx_seq` `rx_seen` | 全 `0` |
| `tx_buf` `rx_buf` `rx_dma_buf` | `memset` 清空 |

> 全局句柄在 `.bss` 里本来就是 0，所以"没写初始化列表"是正常的；但**不能因此跳过 `Init`** —— `huart = NULL` 时 `Send()` 直接返回 0。

#### ③ 指令字段 —— 控制函数每轮写

| 字段 | `MITMode` | `PositionMode` | `SpeedMode` | `TorqueMode` | `ZeroTorqueMode` | `MITModeRaw` |
|---|---|---|---|---|---|---|
| `mode` | FOC(1) | FOC(1) | FOC(1) | FOC(1) | FOC(1) | FOC(1) |
| `Pos` | `pos_offset + joint_pos×ratio` | 同 `MITMode` | `pos_offset` | `pos_offset` | `pos_offset` | 原样 |
| `W` | `joint_speed×ratio` | 0 | `joint_speed×ratio` | 0 | 0 | 原样 |
| `T` | `joint_torque/ratio` | 0 | 0 | `joint_torque/ratio` | 0 | 原样 |
| `K_P` | `kp/gain_scale` | 同 `MITMode` | 0 | 0 | 0 | 原样 |
| `K_W` | `kd/gain_scale` | 同 `MITMode` | `kd/gain_scale` | 0 | 0 | 原样 |

`gain_scale` 见 [7.7](#77-单位与增益口径)。另外 `SetMode/Enable/Lock/Calibrate` 只写 `mode`；`SetZeroPosition` 写 `pos_offset` 和 `joint_pos`。

#### ④ 协议层写 —— `Send()` / 中断回调里

| 字段 | 谁写 | 什么时候 |
|---|---|---|
| `tx_buf`（17 字节帧）+ `T/W/Pos/K_P/K_W/mode` 的**限幅回写** | `BuildFrame()`（`Send()` 内部） | 每发一帧 |
| `torque` `speed` `pos` `joint_torque` `joint_speed` `joint_pos` `temperature` `error_code` `foot_force` | `ParseData()` | 每收到一帧有效回包（DMA 空闲中断里） |
| `correct` `ok_cnt` `last_tick` `rx_seq` | `ParseData()` 成功时 | 同上 |
| `crc_err_cnt` | `ParseData()` 帧头/CRC 错时；`RxEvent()` 收到数据但找不到 `0xFD 0xEE` 时 | 解析失败 |
| `error_cnt` | `StartRx()` 武装失败、`Unitree_GO_Error()` | 通讯异常 |
| `rx_size` | `RxEvent()` | 每次空闲中断 |
| `rx_armed` | `StartRx()` / `StopRx()` | 收发前后 |
| `rx_seen` | `Send()`（发送前对齐）、`Poll()`（消费新帧） | 收发过程中 |

#### ⑤ 你"可以"改、但通常不必改的

| 字段 | 用法 |
|---|---|
| `pos_offset` | 想手动定零点时可以直写；正常用 `SetZeroPosition()` |
| `de_active_high` | 现场发现收发方向反了，运行时翻转再试，不用重编译 |
| `T/W/Pos/K_P/K_W` | 想绕过换算直接下发原始量时才手写，之后 `Send()`（会被限幅写回；下一轮控制函数又会覆盖） |

#### 三条注意事项

1. **反馈字段是只读的**：`torque/speed/pos/joint_*/temperature/...` 你写了也会被下一帧覆盖。
2. **顺序不能反**：`MX_USARTx_UART_Init()` → `Unitree_GO_Init()` → 循环里 `控制函数 + Send/SendRecv`。
3. **别混用两种风格**：每轮调 `MITMode`（等）和手写 `T/W/Pos` 二选一，混用会互相覆盖。

### 7.2 初始化

```c
void Unitree_GO_Init(Unitree_GO_HandleTypeDef *motor, UART_HandleTypeDef *huart,
                     GPIO_TypeDef *de_port, uint16_t de_pin, uint8_t id, float ratio);
```

绑定串口、DE 脚、ID、减速比；把 DE 配成推挽输出切到接收；登记进句柄表并**自动武装 DMA + 空闲中断接收**（`StartRx`）。`id` 夹到 0~15，`ratio <= 0.01` 回退 6.33。不发起通讯。

### 7.3 模式

```c
void Unitree_GO_SetMode(motor, mode);   // 0 锁定 / 1 FOC / 2 编码器标定
void Unitree_GO_Enable(motor);          // → FOC
void Unitree_GO_Lock(motor);            // → 锁定
void Unitree_GO_Calibrate(motor);       // → 标定（总线上只能挂一个电机）
```

只改 `motor->mode`，**必须再发一帧才生效**。

### 7.4 控制（关节侧单位，自动切 FOC）

| API | 说明 |
|---|---|
| `Unitree_GO_MITMode(m, pos, spd, kp, kd, tq)` | 力位混合，五个量全生效 |
| `Unitree_GO_PositionMode(m, pos, kp, kd)` | 纯位置 PD（速度前馈、力矩为 0） |
| `Unitree_GO_SpeedMode(m, spd, kd)` | 只有速度阻尼（目标速度 0 = 阻尼模式） |
| `Unitree_GO_TorqueMode(m, tq)` | 只给前馈力矩 |
| `Unitree_GO_ZeroTorqueMode(m)` | 全 0 + FOC，可用手拖动 |
| `Unitree_GO_MITModeRaw(m, pos, spd, kp, kd, tq)` | 转子侧原样下发，与手册表 1 一致，**不换算、不加零点** |

内部换算：`Pos = 零点 + joint_pos × ratio`、`W = joint_speed × ratio`、`T = joint_torque / ratio`、`K_P/K_W = kp/kd ÷ gain_scale`。

### 7.5 零点

```c
void Unitree_GO_SetZeroPosition(motor);   // 把当前反馈位置记成关节 0 点
```

写 RAM 里的 `pos_offset`，不下发、不写电机，掉电丢失；**必须在至少收到一帧有效反馈之后调用**。

### 7.6 通讯（DMA 版）

| API | 说明 |
|---|---|
| `Unitree_GO_Send(m)` | 组帧 → 关接收 → DE 发送 → 重新武装 DMA。返回 1 = 发送成功 |
| `Unitree_GO_SendRecv(m)` | `Send()` + 最多等 `UNITREE_GO_RX_WAIT_MS`（3 ms）的 `Poll()` |
| `Unitree_GO_SendOnly(m)` | 旧名字，等价 `Send()` |
| `Unitree_GO_Poll(m)` | 有新的一帧有效反馈返回 1（DMA 模式不阻塞；无 DMA 时退回阻塞接收，最坏 1 ms） |
| `Unitree_GO_StartRx(m)` / `Unitree_GO_StopRx(m)` | 武装 / 停止 DMA 接收（`Init` 已自动做，一般不手动调） |
| `Unitree_GO_RxEvent(huart, size)` | 空闲中断分发入口，在 `HAL_UARTEx_RxEventCallback` 里转发 |
| `Unitree_GO_Error(huart)` | 串口错误分发入口，在 `HAL_UART_ErrorCallback` 里转发 |
| `Unitree_GO_ParseData(m, buf)` | 解析 16 字节回包（一般不用直接调） |
| `Unitree_GO_IsOnline(m)` | 50 ms 内收到过有效帧返回 1 |
| `Unitree_GO_Crc16(data, len)` | CRC16-CCITT（反射，init=0，poly 0x8408） |

两种用法：

```c
/* 同步：发完等回包（最常用） */
Unitree_GO_MITMode(&go, 1.57f, 0.0f, 20.0f, 0.6f, 0.0f);
if (Unitree_GO_SendRecv(&go)) { /* 这一轮成功，go.joint_pos 已更新 */ }

/* 异步：发完先干别的，下一拍再取 */
Unitree_GO_Send(&go);
...
if (Unitree_GO_Poll(&go)) { /* 新反馈到了 */ }
```

### 7.7 单位与增益口径

`UNITREE_GO_GAIN_IN_JOINT_SPACE`（默认 1）：

| 取值 | 口径 | 内部处理 | kp/kd 常用值 |
|---|---|---|---|
| `1` | 关节侧：1 = 1 N·m/rad | `÷ ratio²` 后下发 | 2 ~ 20 |
| `0` | 转子侧：与手册/R2 一致 | 原样下发 | 0.02 ~ 0.2 |

`ratio = 6.33` 时 `ratio² ≈ 40`。口径反了的典型现象：电机**完全不转**（系数被定点量化掉）或**猛地一甩**。

---

## 8. 报文协议

小端；`T/W/Pos/K_P/K_W` 均为转子侧量（手册 8.2 节）。

**主机 → 电机（17 B）**

| 字节 | 字段 | 说明 |
|---|---|---|
| 0~1 | 包头 | `0xFE 0xEE` |
| 2 | id+status | bit0~3 id，bit4~6 status（0 锁定/1 FOC/2 标定） |
| 3~4 | tor_des i16 | `T × 256` |
| 5~6 | spd_des i16 | `W / 2π × 256` |
| 7~10 | pos_des i32 | `Pos / 2π × 32768` |
| 11~12 | k_pos i16 | `K_P × 1280` |
| 13~14 | k_spd i16 | `K_W × 1280` |
| 15~16 | CRC16 | 前 15 字节 |

**电机 → 主机（16 B）**

| 字节 | 字段 | 说明 |
|---|---|---|
| 0~1 | 包头 | `0xFD 0xEE` |
| 2 | id+status | 同上 |
| 3~4 | torque i16 | `τ × 256` |
| 5~6 | speed i16 | `ω / 2π × 256` |
| 7~10 | pos i32 | `θ / 2π × 32768` |
| 11 | temp i8 | 温度 ℃ |
| 12~13 | 状态 | bit0~2 错误码，bit3~14 足端力 |
| 14~15 | CRC16 | 前 14 字节 |

协议限幅（下发前自动裁剪）：`T ±127.99`、`W ±804`、`Pos ±411774`、`K_P/K_W 0~25.599`。

---

## 9. 故障排查

| 现象 | 看什么 | 多半是 |
|---|---|---|
| 电机不动，`ok_cnt` 不涨 | `timeout_cnt` | 485 通道选错、DE 极性（`UNITREE_GO_DE_ACTIVE_HIGH`）、A/B 接反、没共地、**ID 与 `UG_PORT_MOTOR_ID` 不一致**、没上电 |
| `SendRecv` 全超时 | `rx_armed` | DMA 没配上（`huart->hdmarx == NULL`）或 `StartRx` 失败；看 `error_cnt` |
| `ok_cnt` 涨但 `SendRecv` 偶尔超时 | `UNITREE_GO_RX_WAIT_MS` | 控制周期太紧 / 总线忙；可把等待加到 5 ms |
| 收得到但帧错 | `crc_err_cnt` | 波特率不是 4 Mbps、线太长/无终端电阻、DE 等待太短（加大 `UNITREE_GO_DE_SETTLE_LOOPS`） |
| 完全收不到，`rx_size` 一直是 0 | 串口 IDLE 中断 | **NVIC 里没开 USARTx 全局中断**，或 `HAL_UARTEx_RxEventCallback` 没转发给 `Unitree_GO_RxEvent` |
| `rx_size` 有值但 `crc_err_cnt` 涨 | 数据内容 | 帧头搜不到 → 波特率错 / A/B 反 / DE 极性反 |
| Keil 链接报重复定义 `USART2_IRQHandler` | `stm32h7xx_it.c` | 后来在 CubeMX 里也启用了 USART2 → 删掉 `Unitree_GO_port.c` 里那段 |
| Keil 编译报 `huart2 undefined` | 生成的 port 文件 | 工程已启用 USART2 但工具用了 installer 模式 → 重新运行工具 |
| 电机猛甩 | — | kp 用了转子侧数值当关节侧，系数放大 40 倍 |
| 回零位置不对 | `pos_offset` | 上电后没先收一帧就 `SetZeroPosition` |

调试顺序：**先确认通道/极性**（两路都试）→ `ZeroTorqueMode` 手拨能动 → 再上位置/速度环。

---

## 10. FAQ

**Q：为什么要 DMA + 空闲中断？**
4 Mbps 下一帧回包 16 字节只要 32 µs，阻塞式 `HAL_UART_Receive` 会占着 CPU 轮询；IDLE 判帧尾是变长帧最省事的做法（宇树固定 16 字节，不用超时判断）。

**Q：工具会破坏我的工程吗？**
不会。改动前备份；只插 CubeMX 的 `USER CODE` 区；回调里只插一行并带标记；`uvprojx` 改完先做 XML 校验；重复运行幂等。

**Q：CubeMX 重新生成代码后要重跑吗？**
不用。插入点都在 `USER CODE` 里，CubeMX 会保留；`bsp/uper/` 不在生成范围。除非你**新开了** USART2/DMA，那就重跑一次让工具改走复用模式（并把重复的中断函数删掉）。

**Q：我不在 CubeMX 里配 DMA，能跑吗？**
能。驱动检测到 `hdmarx == NULL` 会自动退回阻塞接收（效率低）。但工具生成移植层时本来就会帮你把 DMA 配好。

**Q：一个工程多个电机？**
一个 `Unitree_GO_HandleTypeDef` 对应一个电机；同一路 485 上多个电机时，回包按 ID 自动分发，在同一个任务里按 ID 依次收发即可（半双工不能并发发）。

**Q：电机 ID 怎么查/怎么改？**
用宇树官方 MotorTools 的 `swboot`，出厂未设置时是 15（广播）。

**Q：能用在别的板子吗？**
可以。改 `config.json` 的 `channel_map`（串口、TX/RX、DE、AF、DMA 请求号），或用 `--channel 2`。

---

## 版本

- **v1.1.0** — 接收改为 **DMA + 空闲中断**：`StartRx/StopRx/Poll/Send/RxEvent/Error` 新 API，`SendRecv` 变成"发 + 等 3 ms"，半双工发送期间自动关接收；工具自动生成 DMA/中断/回调并支持复用工程已有配置。
- **v1.0.0** — 驱动 + 一键配置工具首发（阻塞接收）。

驱动来源：移植自 `R2_Code/Application/Unitree`（`gom_protocol.c/h` + `Unitree_control.c/h` + `crc_ccitt.c/h`），改为半双工板载 485 + 字节级组帧 + DMA 空闲中断接收。
