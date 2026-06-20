# -*- coding: utf-8 -*-
"""
==========================================================================
项目名称：VectorBody 智能体态检测系统
文件名称：vector_body_stabilizer.py
功能描述：
    1. 基于 OneEuroFilter（一欧元滤波器）算法实现姿态关键点去噪。
    2. 实现自适应截止频率调节，在静止时消除抖动，在运动时降低延迟。
    3. 支持 NumPy 矩阵化并行运算，实时稳定 MediaPipe 33 个核心关键点坐标。
开发者：杜文鑫
编写日期：2026年03月26日
==========================================================================
"""
import numpy as np
# 定义一个专门负责姿态稳定的类，封装 OneEuroFilter 的功能
class OneEuroFilter:
    def __init__(self, freq=30, min_cutoff=1.0, beta=0.007, d_cutoff=1.0):
        self.freq = freq
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_prev = None
        self.dx_prev = None

    def _alpha(self, cutoff):
        tau = 1.0 / (2 * np.pi * cutoff)
        te = 1.0 / self.freq
        return 1.0 / (1.0 + tau / te)

    def smooth(self, x):
        if self.x_prev is None:
            self.x_prev = x
            self.dx_prev = np.zeros_like(x)
            return x
        
        te = 1.0 / self.freq
        dx = (x - self.x_prev) / te
        edx = self._alpha(self.d_cutoff) * dx + (1 - self._alpha(self.d_cutoff)) * self.dx_prev
        cutoff = self.min_cutoff + self.beta * np.abs(edx)
        alpha = self._alpha(cutoff)
        result = alpha * x + (1 - alpha) * self.x_prev
        
        self.x_prev, self.dx_prev = result, edx
        return result

class VectorBodyStabilizer:
    def __init__(self, freq=30):
        self.filter = OneEuroFilter(freq=freq)

    def smooth(self, landmarks):
        # 将 Mediapipe 的坐标转为 Numpy 数组进行矩阵运算
        curr = np.array([[lm.x, lm.y, lm.z] for lm in landmarks.landmark])
        return self.filter.smooth(curr)
