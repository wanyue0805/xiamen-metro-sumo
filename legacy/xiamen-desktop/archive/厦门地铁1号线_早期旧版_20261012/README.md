# 厦门地铁 1 号线 SUMO 仿真

项目位置：F:\SUMO_Xiamen_Line1

## 开始使用

### Python 控制面板

1. 双击 Start.bat。
2. 选择“镇海路 → 岩内”或“岩内 → 镇海路”始发方向。
3. 点击“启动 / 重置”。列车初始停在相应始发站，仿真处于暂停状态。
4. 点击“自动全线往返”。列车逐站停靠，到终点停车后折返，持续往返。

建议选择 20、50 或 100 倍仿真倍率，方便快速观察完整线路。1 倍按仿真时间正常推进，全线运行需要较长时间。

需要原生 SUMO 窗口时，启动前勾选“同时打开 SUMO 原生窗口”。程序自动加载 XiamenLine1 显示方案，按六节车厢显示列车，避免整列直杆横跨弯道。

### 直接启动 SUMO 演示

双击 SUMO_Demo.bat。不需要 Python 面板，列车会按预设计划执行：

    镇海路 → 岩内 → 镇海路 → 岩内

演示共有 70 次计划停站，最后结束运行。可在原生窗口调整播放速度。

也可以直接用 SUMO-GUI 打开 network\line1.sumocfg，点击播放。network\line1.control.sumocfg 为 Python 控制专用配置，单独打开时尚未添加列车。

## 本项目的建模范围

真实资料部分：镇海路至岩内的 24 个站名与顺序；公开资料中的线路长 30.3 km；B 型车、6 辆编组、80 km/h 的配置参考。

仿真假设部分：轨道走向为示意布局，站间距离为估计值，按 30.3 km 的站点中心连线参考长度缩放。平滑曲线和站内配线生成后，实际模型轨道长度会略有差别。模型没有导入实测 GIS、真实纵坡、施工图、运营配线图或正式列车运行图。

列车在模型中取 120 米长、2.8 米宽，显示为六节车厢；加速度 1.0 m/s²、正常制动减速度 1.2 m/s²、最高速度 80 km/h。平台停车区间长 210 米，默认普通停站 20 秒、终点停站 40 秒。这些数值是模型参数，并非对真实列车或运营时刻的测定。

线路包含分别建模的上、下行轨道，站间使用连续曲线连接，配有 SUMO rail_signal 区间信号。在两端设置可双向使用的站内轨道和简化的渡线。折返由 SUMO 自身的列车反向逻辑执行：停车后交换车头车尾，并沿反向轨道驶出；保留同一车辆，无需删除、重建或移动列车来模拟折返。

目前为单列车往返演示；多列车发车间隔、客流、容量与真实时刻表未纳入本版。

## 24 站顺序

01 镇海路 → 02 中山公园 → 03 将军祠 → 04 文灶 → 05 湖滨东路 → 06 莲坂 → 07 莲花路口 → 08 吕厝 → 09 乌石浦 → 10 塘边 → 11 火炬园 → 12 殿前 → 13 高崎 → 14 集美学村 → 15 园博苑 → 16 杏林村 → 17 杏锦路 → 18 官任 → 19 诚毅广场 → 20 集美软件园 → 21 集美大道 → 22 天水路 → 23 厦门北站 → 24 岩内。

## 控制功能

- 启动 / 重置：按所选方向开始新仿真。
- 自动全线往返：开关自动逐站运行，终点自动折返。
- 暂停 / 继续：暂停或继续仿真时间。
- 发往下一站：到站后发往当前方向的下一站；终点会切换方向。
- 单步 0.2 秒：暂停并推进一个仿真步。
- 驶向所选站：双击站点列表，或点击地图站名。列车按可达路线前往目标站；需要反向时会先到终点停车折返。此模式不逐站停靠所有途经站。
- 最高速度：10～80 km/h。加减速、信号、折返渡线速度等约束仍会影响实际速度。
- 仿真倍率：1、5、10、20、50、100。
- 停站秒数：调整自动运行的普通站停留时间；终点默认停留 40 秒。
- 保存到站 / 折返记录：保存至 logs\arrival-log.json。

全线图按站点顺序拉开间距，方便看清全部 24 站；青色标记代表列车实时位置。右侧近景按列车实际轨道位置显示六节车厢；原生 SUMO 窗口显示完整轨道几何。

## 复制到其他电脑

适用目标：Windows 10/11，x86-64 电脑。

复制整个 SUMO_Xiamen_Line1 文件夹，或解压完整的 SUMO_Xiamen_Line1_Windows_Portable.zip，然后双击 Start.bat。包内带有 Python 3.12.10、Tkinter、SUMO 1.27.1、TraCI、sumolib 和相关 DLL，不依赖原电脑的 F 盘、D 盘或联网下载。

必须保留 runtime、network、app.py、panel.py、stations.json 等完整内容。请解压到全英文路径，例如 C:\SUMO_Xiamen_Line1。当前 SUMO Windows 程序在中文路径下存在兼容问题。

双击 Check.bat 可进行自检。结果位于 logs\self-test.json；错误日志为 logs\panel.log 和 logs\sumo-errors.log。已在本机检查窗口、真实仿真行驶和解压到另一盘后的独立运行，其他实体电脑与 ARM 设备尚未实测。

Linux/macOS 可另行安装本系统 SUMO、Python 3.10+ 和 Tkinter，再执行 python3 -m pip install -r requirements.txt 与 python3 app.py；附带的二进制运行环境只适用于 Windows，其他系统源码运行尚未实测。

## 文件说明

- app.py：仿真控制、停站、寻路、真实列车折返。
- panel.py：Python 控制面板、全线图与列车近景。
- stations.json：24 站资料、示意坐标、模型参数与来源。
- self_test.py、Check.bat：双向全站运行、折返、控制和环境自检。
- Start.bat：控制面板入口。
- SUMO_Demo.bat：独立 SUMO 演示入口。
- network/line1.nod.xml、line1.edg.xml、line1.con.xml：节点、轨道、连接的源文件。
- network/line1.net.xml：已生成的 SUMO 路网。
- network/line1.rou.xml：地铁车型。
- network/line1.add.xml：双向站台与站点标记。
- network/demo.rou.xml：独立演示的车次、线路和停站计划。
- network/line1.sumocfg：独立演示配置。
- network/line1.control.sumocfg：Python 控制配置。
- network/metro.view.xml：固定六节车厢显示的原生窗口设置。
- runtime：便携运行环境与对应授权文件。
- logs：运行日志、到站记录、独立演示停站记录和验证结果。
- preview.png、native-preview.png：面板与原生列车预览。

## 数据来源

- 厦门地铁站点线路：https://www.xmgdjt.com.cn/Modules/ControlHtml/Line.aspx
- 厦门市招商办轨道交通介绍（24 站、镇海路至岩内、30.3 km）：https://www.investxiamen.org.cn/detail/1173.html
- 国家发展改革委近期建设规划批复（B 型车、6 辆编组、80 km/h）：https://www.ndrc.gov.cn/fggz/zcssfz/zdgc/201209/t20120905_1145854.html
- SUMO 轨道与列车折返说明：https://sumo.dlr.de/docs/Simulation/Railways.html

资料核对日期：2026-10-12。本项目的停站时长、渡线与轨道参数以 stations.json、车型和路网配置为准。

## 开源授权

项目控制与显示源码采用 MIT 授权，见 LICENSE.txt。
SUMO：EPL-2.0 或 GPL-2.0-or-later，见 runtime/sumo/NOTICE.txt、Libraries_Licenses.html。
Python：见 runtime/python/LICENSE.txt。
