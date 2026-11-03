# Unitree_GO_dm_lib

宇树 **GO-M8010-6** 关节电机驱动（STM32 · 半双工 RS485）＋ **Keil MDK 工程一键配置工具**（Python + tkinter GUI）。

输入一个 `MDK-ARM` 目录，点一下按钮，工具就会把驱动、移植层、FreeRTOS 线程和 Keil 工程配置全部装好，并自动备份所有被改动的文件。

```
┌─────────────────────────────────────────────────────────────┐
│  Unitree_GO 一键配置  v1.0.0                                │
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
│  工程根目录 : D:\27RC\dm_demo                               │
│  [写入] bsp\uper\Unitree_GO.c                               │
│  [修改] Core\Src\freertos.c（插入 includes, prototypes, …）  │
└─────────────────────────────────────────────────────────────┘
```

---

## 目录

1. [目录结构](#1-目录结构)
2. [快速开始](#2-快速开始)
3. [工具具体改了什么](#3-工具具体改了什么)
4. [config.json 说明](#4-configjson-说明)
5. [生成的移植层](#5-生成的移植层unitree_go_portch)
6. [驱动 API](#6-驱动-api)
7. [报文协议](#7-报文协议)
8. [故障排查](#8-故障排查)
9. [FAQ](#9-faq)

---

## 1. 目录结构

```
Unitree_GO_dm_lib/
├── README.md                        ← 本文件
├── config.json                      ← 工具配置（路径/锚点/默认值）
├── Unitree_GO.c                     ← 驱动实现（582 行）
├── Unitree_GO.h                     ← 驱动头文件（209 行）
└── Unitree_GO_configurator.py       ← 一键配置工具（GUI + CLI）
```

驱动被分成两层：

| 层 | 文件 | 谁维护 |
|---|---|---|
| 协议层 | `Unitree_GO.c/.h` | 本库，跨工程通用，不含任何板级引脚 |
| 移植层 | `Unitree_GO_port.c/.h`（**由工具生成到目标工程**） | 每个工程一份，绑定具体串口/引脚/任务参数 |

这样换板子只改移植层，协议层一行不用动。

---

## 2. 快速开始

### 2.1 环境

- Windows + Python 3.8 以上（官方安装包自带 `tkinter`，无需 pip 安装任何东西）
- 目标工程：STM32CubeMX 生成 + Keil MDK（STM32H7xx HAL + FreeRTOS + `cmsis_os.h`）
- 板子：DM-MC-Board02（或任何有 USART2/USART3 + RS485 方向脚的板子）

### 2.2 方式一：GUI

```bat
python Unitree_GO_configurator.py
```

1. 点「浏览…」选中工程的 `MDK-ARM` 目录（填工程根目录也行，工具会自动往下找）；
2. 选 485 通道（默认 1）；
3. 填电机 ID（**必须和电机里烧的一致**，出厂未设置时是 15）；
4. 点「一键配置」。

日志里出现 `配置完成` 就结束了，接着用 Keil 打开 `.uvprojx`，**Rebuild**。

> 不确定工程状态时，先点「仅检测」或勾上「只检查不写入」，工具会把检测结果和将要做的事列出来，不改任何文件。

### 2.3 方式二：命令行

```bat
:: 配置（默认通道 1、ID 1）
python Unitree_GO_configurator.py --mdkarm "D:\27RC\dm_demo\MDK-ARM"

:: 先看要改什么
python Unitree_GO_configurator.py --mdkarm "D:\27RC\dm_demo\MDK-ARM" --dry-run

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

### 2.4 方式三：手工（不用脚本也能装）

1. 把 `Unitree_GO.c/.h` 拷到 `<工程>/bsp/uper/`；
2. 在 `Unitree_GO.h` 里把 `UNITREE_GO_485_CHANNEL` 改成 1 或 2；
3. 参考本库生成逻辑（`Unitree_GO_configurator.py` 里的 `_port_files()`）写一个 `Unitree_GO_port.c`：
   4 Mbps 串口初始化 + `Unitree_GO_Init()` + 一个任务；
4. Keil 工程里加入两个 `.c`，头文件路径加 `../bsp/uper`；
5. `freertos.c` 的 USER CODE 区里 `osThreadNew(APP_Unitree_GO_Task, NULL, &attr)`。

---

## 3. 工具具体改了什么

工具只做 4 件事，**全部幂等**（同一工程重复运行不会重复插入），且改动前先备份：

| # | 目标 | 动作 | 备份 |
|---|---|---|---|
| 1 | `bsp/uper/Unitree_GO.c` `.h` | 复制（`.h` 里的通道宏按选择写入）。已有且内容相同 → 跳过 | 内容不同才备份 |
| 2 | `bsp/uper/Unitree_GO_port.c` `.h` | 按当前选项生成/覆盖 | 有旧文件才备份 |
| 3 | `Core/Src/freertos.c` | 在 4 个 `USER CODE` 区插入：`#include`、线程声明、线程属性、`osThreadNew()` | ✔ |
| 4 | `R1.uvprojx` | 往 `bsp_upper` 组登记 `Unitree_GO.c` / `Unitree_GO_port.c`；给主 target 的 `IncludePath` 补 `../bsp/uper` | ✔ |

- 备份位置：`<MDK-ARM>/Unitree_GO_backup/<yyyyMMdd_HHmmss>/`，保留原来的相对目录结构，并附 `install_report.txt`（本次改动明细 + 下一步提示）。
- **只改 CubeMX 的 `USER CODE` 区**，所以之后用 CubeMX 重新生成代码时这些插入不会被冲掉；生成的 `Unitree_GO_port.*` 在 `bsp/uper/` 下，CubeMX 根本不碰。
- 检测到工程里**已有别人写的** GO 电机接入代码（比如 `app/fdcan_it.c` 里的 `APP_Unitree_test`）时，为免两个任务抢同一路半双工 485，只同步驱动文件，不生成移植层和线程；确实要覆盖时加 `--force`。
- 工程里已有 `huart2/huart3`（CubeMX 配过串口）时，移植层走**复用模式**：只借用句柄并把波特率校正到 4 Mbps；没有则自己建。两种模式在生成的 `Unitree_GO_port.c` 注释里写得清清楚楚。

---

## 4. config.json 说明

所有可调项都在 `config.json`，改完不用动 Python 代码。

| 键 | 含义 | 默认 |
|---|---|---|
| `layout.driver_dir` | 驱动放到工程的哪个目录（相对工程根） | `bsp/uper` |
| `layout.port_prefix` | 移植层文件名前缀 | `Unitree_GO_port` |
| `layout.freertos_c` | 要插线程的 RTOS 文件 | `Core/Src/freertos.c` |
| `layout.usart_c` / `usart_h` | 用来探测"工程是否已有串口"的文件 | `Core/Src/usart.c` / `Core/Inc/usart.h` |
| `layout.uvprojx_glob` | Keil 工程文件的匹配模式 | `*.uvprojx` |
| `layout.backup_dir` | 备份目录（相对 MDK-ARM） | `Unitree_GO_backup` |
| `uvprojx.preferred_group` | 优先把文件登记进哪个组 | `bsp_upper` |
| `uvprojx.fallback_group` | 组不存在时新建的组名 | `Unitree_GO` |
| `uvprojx.include_entry` | 要补进 `IncludePath` 的路径 | `../bsp/uper` |
| `freertos.blocks.*` | 4 个插入锚点（USER CODE 标记） | CubeMX 标准标记 |
| `thread.name` / `stack_words` / `priority` | 生成线程的名字、栈（字）、优先级 | `UnitreeGO` / `512` / `osPriorityNormal` |
| `defaults.*` | GUI / CLI 的默认值（通道、ID、周期、kp、kd、位置） | 见文件 |
| `channel_map.*` | 每路 485 对应的串口、引脚、DE、AF | 见文件 |
| `marker` | 幂等标记，出现在所有插入片段里 | `UNITREE_GO_AUTOCONFIG` |

> 换板子/换引脚时改 `channel_map` 即可，工具生成移植层时直接用这里的值。

---

## 5. 生成的移植层（`Unitree_GO_port.c/.h`）

### 5.1 可调宏

| 宏 | 默认 | 说明 |
|---|---|---|
| `UG_PORT_MOTOR_ID` | 1 | 电机 ID，必须与电机里烧的一致 |
| `UG_PORT_RATIO` | 6.33 | 减速比 |
| `UG_PORT_PERIOD_MS` | 10 | 控制周期 ms |
| `UG_PORT_DEMO_POS` | 0.5 | 示例目标位置（关节侧 rad） |
| `UG_PORT_DEMO_KP` | 4.0 | 示例 kp（关节侧，1 = 1 N·m/rad） |
| `UG_PORT_DEMO_KD` | 1.0 | 示例 kd（关节侧） |
| `UG_PORT_SETTLE_MS` | 2000 | 上电先零力矩多久（手拨确认通信） |

### 5.2 接口

```c
void Unitree_GO_Port_Init(void);              // 幂等：初始化 485 + 电机句柄
void APP_Unitree_GO_Task(void *argument);     // 示例任务
extern Unitree_GO_HandleTypeDef g_go_joint;   // 全局句柄，调试器直接 Watch
```

示例任务流程：**零力矩 2 s**（手拨能轻松转 = 通信 + FOC 都正常）→ 收一帧 → 把当前位置记成关节 0 点 → **位置伺服到 `UG_PORT_DEMO_POS` 并保持**。

> 默认会真的让电机转动。只想验证通信就把 `UG_PORT_DEMO_KP/KD` 改成 0（等价零力矩），或者用 `--no-task` 不生成任务、自己写控制循环。

---

## 6. 驱动 API

驱动所有接口在 `Unitree_GO.h`。句柄一个电机一个：

```c
typedef struct {
    UART_HandleTypeDef *huart;      GPIO_TypeDef *de_port;   uint16_t de_pin;
    uint8_t  id;                    float ratio;
    uint8_t  mode;   float T, W, Pos, K_P, K_W, pos_offset;   // 指令（转子侧）
    int8_t   temperature;  uint8_t error_code;  uint16_t foot_force;
    float    torque, speed, pos;                              // 反馈（转子侧）
    float    joint_torque, joint_speed, joint_pos;            // 反馈（关节侧）
    uint8_t  correct;  uint32_t ok_cnt, timeout_cnt, crc_err_cnt, last_tick;
    uint8_t  tx_buf[17], rx_buf[16];
} Unitree_GO_HandleTypeDef;
```

### 6.1 初始化

```c
void Unitree_GO_Init(Unitree_GO_HandleTypeDef *motor, UART_HandleTypeDef *huart,
                     GPIO_TypeDef *de_port, uint16_t de_pin, uint8_t id, float ratio);
```

绑定串口、DE 方向脚、ID、减速比；把 DE 脚配成推挽输出并切到接收方向。初始 `mode = 0`（锁定）。
`id` 夹到 0~15；`ratio <= 0.01` 时回退 6.33。**不发起任何通讯**。

### 6.2 模式

```c
void Unitree_GO_SetMode(motor, mode);   // 0 锁定 / 1 FOC / 2 编码器标定
void Unitree_GO_Enable(motor);          // → FOC
void Unitree_GO_Lock(motor);            // → 锁定
void Unitree_GO_Calibrate(motor);       // → 标定（总线上只能挂一个电机）
```

只改 `motor->mode`，**必须再 `SendRecv()`/`SendOnly()` 才生效**。

### 6.3 控制（关节侧单位，自动切 FOC）

| API | 说明 |
|---|---|
| `Unitree_GO_MITMode(m, pos, spd, kp, kd, tq)` | 力位混合，五个量全生效 |
| `Unitree_GO_PositionMode(m, pos, kp, kd)` | 纯位置 PD（速度前馈、力矩为 0） |
| `Unitree_GO_SpeedMode(m, spd, kd)` | 只有速度阻尼（目标速度 0 = 阻尼模式） |
| `Unitree_GO_TorqueMode(m, tq)` | 只给前馈力矩 |
| `Unitree_GO_ZeroTorqueMode(m)` | 全 0 + FOC，可用手拖动 |
| `Unitree_GO_MITModeRaw(m, pos, spd, kp, kd, tq)` | 转子侧原样下发，与手册表 1 一一对应，**不做减速比换算、不加零点** |

内部换算：`Pos = 零点 + joint_pos × ratio`、`W = joint_speed × ratio`、`T = joint_torque / ratio`、`K_P/K_W = kp/kd ÷ gain_scale`。

### 6.4 零点

```c
void Unitree_GO_SetZeroPosition(motor);   // 把当前反馈位置记成关节 0 点
```

写的是 RAM 里的 `pos_offset`，不下发、不写电机，掉电丢失；**必须在至少收到一帧有效反馈之后调用**，否则 `pos` 还是 0。

### 6.5 通讯

| API | 说明 |
|---|---|
| `Unitree_GO_SendRecv(m)` | 组帧 → 切 DE 发送 → 收回包 → 校验解析；返回 1 = 成功 |
| `Unitree_GO_SendOnly(m)` | 只发不收（广播 id=15、标定命令） |
| `Unitree_GO_ParseData(m, buf)` | 解析 16 字节回包（改成 DMA/中断接收时在回调里调它） |
| `Unitree_GO_IsOnline(m)` | 50 ms 内收到过有效帧返回 1 |
| `Unitree_GO_Crc16(data, len)` | CRC16-CCITT（反射，init=0，poly 0x8408） |

`SendRecv` 细节：广播 ID 直接返回不发等待；发送/接收超时分别 2 ms / 1 ms；接收前会再清一次 RX 缓冲，防止某些 485 芯片把自己发的包收回来。

### 6.6 单位与增益口径（最容易踩的坑）

`UNITREE_GO_GAIN_IN_JOINT_SPACE`（默认 1）：

| 取值 | 口径 | 内部处理 | kp/kd 常用值 |
|---|---|---|---|
| `1` | 关节侧：1 = 1 N·m/rad | `÷ ratio²` 后下发 | 2 ~ 20 |
| `0` | 转子侧：与手册/R2 一致 | 原样下发 | 0.02 ~ 0.2 |

`ratio = 6.33` 时 `ratio² ≈ 40`。口径反了的典型现象：电机**完全不转**（系数被定点量化掉）或**猛地一甩**。

---

## 7. 报文协议

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

## 8. 故障排查

| 现象 | 看什么 | 多半是 |
|---|---|---|
| 电机不动，`ok_cnt` 不涨 | `g_go_joint.timeout_cnt` | 485 通道选错、DE 极性（`UNITREE_GO_DE_ACTIVE_HIGH`）、A/B 接反、没共地、**ID 与 `UG_PORT_MOTOR_ID` 不一致**、没上电 |
| 收得到但帧错 | `crc_err_cnt` | 波特率不是 4 Mbps、线太长/无终端电阻、DE 等待太短（加大 `UNITREE_GO_DE_SETTLE_LOOPS`） |
| 收得到、`correct = 1`，却不动 | `joint_pos` 是否变化、换算后的 `K_P` 是否为 0 | kp/kd 口径、模式没进 FOC、供电不足 |
| 电机猛甩 | — | kp 用了转子侧数值当关节侧，系数放大 40 倍 |
| 回零位置不对 | `pos_offset` | 上电后没先收一帧就 `SetZeroPosition` |
| Keil 编译报 `huart2 undefined` | 生成的 port 文件 | 工程已启用 USART2 但工具用了 installer 模式 → 重新运行工具（会检测并切复用模式） |
| Keil 里看不到新文件 | `.uvprojx` | 关掉 Keil 重新打开工程（工具是在磁盘上改的工程文件） |

调试顺序建议：**先确认通道/极性**（两路都试）→ `ZeroTorqueMode` 手拨能动 → 再上位置/速度环。

---

## 9. FAQ

**Q：工具会破坏我的工程吗？**
不会。所有改动前都备份；只插 CubeMX 的 `USER CODE` 区；`uvprojx` 改完会先做一次 XML 解析验证；重复运行是幂等的。

**Q：CubeMX 重新生成代码后要重跑吗？**
不用。插入点都在 `USER CODE` 里，CubeMX 会保留；`bsp/uper/` 也不在生成范围。除非你把串口配置改了，那就重跑一次让移植层跟着更新。

**Q：一个工程多个电机？**
一个 `Unitree_GO_HandleTypeDef` 对应一个电机，按 ID 建多个句柄，**在同一个任务里顺序收发**（半双工总线不能并发发）。

**Q：电机 ID 怎么查/怎么改？**
用宇树官方 MotorTools 的 `swboot`，出厂未设置时是 15（广播）。

**Q：能用在别的板子吗？**
可以。改 `config.json` 的 `channel_map`（串口、TX/RX、DE、AF），或用 `--channel 2`；驱动本身只依赖 HAL 的 UART/GPIO。

---

## 版本

- **v1.0.0** — 驱动 + 一键配置工具首发：GUI/CLI、通道 1/2、复用/自建串口、CubeMX 安全插入、自动备份、幂等。

驱动来源：移植自 `R2_Code/Application/Unitree`（`gom_protocol.c/h` + `Unitree_control.c/h` + `crc_ccitt.c/h`），改为半双工板载 485 + 字节级组帧。
