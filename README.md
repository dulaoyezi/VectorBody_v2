# VectorBody 智能体态检测系统

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

## 📖 项目简介
**VectorBody** 是一款基于计算机视觉与生物力学分析的人体体态监测系统。系统通过实时采集人体关键点（Landmarks），利用自适应平滑滤波算法（OneEuroFilter）处理抖动，并针对高低肩、骨盆偏移及脊柱侧弯等常见体态问题提供量化评估与临床级康复建议。

## 🛠️ 核心技术路线
* **姿态提取**：基于 MediaPipe Pose 模型获取人体 33 个 3D 坐标向量。
* **信号处理**：采用指数移动平均 (EMA) 与一欧元滤波器 (OneEuroFilter) 确保数据稳定性。
* **评估算法**：基于三角几何模型计算人体力线夹角。
* **交互反馈**：采用 PySide6 构建多线程 UI，并集成异步语音指导系统。

## 📂 项目结构
```text
VectorBody/
├── core/                # 核心算法（分析器、平滑器）
├── ui/                  # GUI 界面定义
├── utils/               # 工具类（音频、可视化绘制）
├── assets/              # 解剖图资源（必须包含 front_muscle.png 等）
├── reports/             # 自动化生成的评估报告存档
└── vector_body_main.py  # 程序入口
#代码更新
cd D:\VectorBody
git add .
git commit -m "你的提交说明"
git push
