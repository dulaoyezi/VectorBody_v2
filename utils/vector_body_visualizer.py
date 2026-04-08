# -*- coding: utf-8 -*-
"""
==========================================================================
项目名称：VectorBody 智能体态检测系统
文件名称：vector_body_visualizer.py
功能描述：
    1. 基于 MediaPipe Drawing 模块实现人体 33 个关键点的实时渲染。
    2. 自定义 VectorBody 系统专属视觉样式（线条粗细、颜色、连接关系）。
    3. 为前端 UI 提供直观的姿态反馈，辅助临床姿态评估。
开发者：杜文鑫
编写日期：2026年03月26日
==========================================================================
"""

import cv2
import mediapipe as mp
# 定义一个专门负责视觉渲染的类，封装 MediaPipe 的绘图功能
class VectorBodyVisualizer:
    def __init__(self):
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_pose = mp.solutions.pose
        
        self.line_style = self.mp_drawing.DrawingSpec(color=(255, 255, 255), thickness=2)
        self.point_style = self.mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=1)

    def draw_skeleton(self, frame, landmarks):
        if landmarks:
            self.mp_drawing.draw_landmarks(
                frame, 
                landmarks, 
                self.mp_pose.POSE_CONNECTIONS,
                self.point_style,
                self.line_style
            )
        return frame