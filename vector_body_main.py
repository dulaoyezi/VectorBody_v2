# -*- coding: utf-8 -*-
"""
==========================================================================
项目名称：VectorBody 智能体态检测系统
文件名称：vector_body_main.py
功能描述：
    1. 系统主控制器，负责硬件初始化与多线程资源调度。
    2. 集成 MediaPipe 姿态评估引擎与 GUI 界面交互。
    3. 实现实时画面渲染、异常捕获及数据持久化逻辑。
开发者：杜文鑫
编写日期：2026年03月26日
==========================================================================
"""

#主程序，负责调度各模块
import sys, cv2, time, pythoncom, os, datetime, traceback
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap

from ui.vector_body_dashboard import VectorBodyDashboard
from core.vector_body_stabilizer import VectorBodyStabilizer
from core.vector_body_analyzer import VectorBodyAnalyzer
from utils.vector_body_visualizer import VectorBodyVisualizer
from utils.vector_body_audio import VectorBodyAudio
import mediapipe as mp
from PIL import Image, ImageDraw, ImageFont
import numpy as np

# 处理 PyInstaller 打包后的 MediaPipe 资源路径问题
if hasattr(sys, '_MEIPASS'):
    # 指向打包后的 _internal/mediapipe 目录
    mp_path = os.path.join(sys._MEIPASS, 'mediapipe')
    
    # 强制 MediaPipe 使用这个路径来查找资源
    os.environ['MEDIAPIPE_BINARY_GRAPH_PATH'] = mp_path
    
    # 直接调用 MediaPipe 的资源工具函数来设置路径
    from mediapipe.python import resource_util
    resource_util.set_resource_dir(mp_path)
    print(f">>> 已强制重定向 MediaPipe 资源路径: {mp_path}")
# 备用函数，确保在任何环境下都能正确获取资源路径
def get_resource_path(relative_path):
    """ 处理 PyInstaller 打包后的路径问题 """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# 加载中文字体，优先使用系统字体，失败则回退到默认字体
try:
    CHINESE_FONT_30 = ImageFont.truetype("msyh.ttc", 30)
    CHINESE_FONT_25 = ImageFont.truetype("msyh.ttc", 25)
except:
    CHINESE_FONT_30 = ImageFont.load_default()
    CHINESE_FONT_25 = ImageFont.load_default()
def draw_chinese_text(img, text, position, font, color=(255, 0, 0)):
    # 将 OpenCV 的 BGR 图片转为 Pillow 的 RGB 图片
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    
    draw.text(position, text, font=font, fill=color)
    
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

# 主控制器，负责系统初始化与主循环调度
class VectorBodyController:
    def __init__(self):

        print(">>> [1/5] 初始化多线程 COM...")
        pythoncom.CoInitialize() 
        
        self.app = QApplication(sys.argv)
        self.window = VectorBodyDashboard()
        
        print(">>> [2/5] 启动摄像头...")
        self.cap = cv2.VideoCapture(0)
        
        print(">>> [3/5] 加载 MediaPipe 模型...")
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(
            model_complexity=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        
        print(">>> [4/5] 初始化算法与资源...")
        self.stabilizer = VectorBodyStabilizer()
        self.analyzer = VectorBodyAnalyzer()
        self.visualizer = VectorBodyVisualizer()
        self.audio = VectorBodyAudio()

        self.warn_font = CHINESE_FONT_30  # 将内存中的 30 号字体存入实例变量
        self.tip_font = CHINESE_FONT_25   # 将内存中的 25 号字体存入实例变量

        self.last_voice_time = 0 
        self.setup_connections()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_loop)
        self.timer.start(33) 
        print(">>> [5/5] 系统已就绪。")

    def setup_connections(self):
        try:
            self.window.btn_m.clicked.connect(lambda: self.switch_view("muscle"))
            self.window.btn_s.clicked.connect(lambda: self.switch_view("skeleton"))
            self.window.btn_save.clicked.connect(self.handle_save)
        except AttributeError as e:
            print(f"!!! 界面连接失败: {e}。")

    def handle_save(self):
        if hasattr(self.window, 'save_and_reset'):
            self.window.save_and_reset()

    def switch_view(self, mode):
        side = "back" if "front" in self.window.view_mode else "front"
        self.window.view_mode = f"{side}_{mode}"

    def update_loop(self):
        try:
            ret, frame = self.cap.read()
            if not ret or frame is None: return

            frame = cv2.flip(frame, 1)
            h, w, ch = frame.shape
            cv2.circle(frame, (w // 2, h // 2), 200, (200, 200, 200), 1, cv2.LINE_AA)
            
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.pose.process(rgb_frame)

            if results.pose_landmarks:# 获取关键点坐标
                lm = results.pose_landmarks.landmark
                # 获取核心中心
                center_x = (lm[11].x + lm[12].x + lm[23].x + lm[24].x) / 4
                center_y = (lm[11].y + lm[12].y + lm[23].y + lm[24].y) / 4
                dist_from_center = ((center_x - 0.5)**2 + (center_y - 0.5)**2)**0.5
                
                # 情况 1：人在中心区域
                if dist_from_center < 0.5:
                    frame = self.visualizer.draw_skeleton(frame, results.pose_landmarks)
                    points = self.stabilizer.smooth(results.pose_landmarks)
                    
                    # 计算指标并判断有效性
                    metrics, is_valid = self.analyzer.get_metrics(points)
                    
                    # --- 这里是显示“请保证全身入镜”的地方 ---
                    if not is_valid:
                        frame = draw_chinese_text(frame, "请保证全身入镜", (w // 2 - 120, 110), self.warn_font)
                    
                    # 分析结果并更新 UI
                    status, report_html, voice_text = self.analyzer.analyze_clinical(
                        metrics, self.window.patient_name.text() or "待测患者"
                    )
                    self.window.val_sh.setText(f"高低肩: {abs(metrics['sh']):.1f}°")
                    self.window.val_pl.setText(f"骨盆偏移: {abs(metrics['pl']):.1f}°")
                    if hasattr(self.window, 'val_sc'):
                        self.window.val_sc.setText(f"脊柱侧弯: {abs(metrics['sc']):.1f}°")
                    self.window.report_area.setHtml(report_html)
                    self.window.update_anatomy(status)

                    # 语音触发
                    now = time.time()
                    if is_valid and voice_text and (now - self.last_voice_time > 6):
                        self.audio.speak(voice_text)
                        self.last_voice_time = now
                
                # 情况 2：人在边缘
                else:
                    frame = draw_chinese_text(frame, "请移至检测圈内", (w // 2 - 120, 60), self.tip_font)

            # 将画面渲染到 UI 窗口 
            qt_img = QImage(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).data, w, h, w*ch, QImage.Format_RGB888).copy()
            self.window.update_frame(QPixmap.fromImage(qt_img))

        except Exception as e:
            traceback.print_exc()

            # 将画面渲染到 UI 窗口
            qt_img = QImage(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).data, w, h, w*ch, QImage.Format_RGB888).copy()
            self.window.update_frame(QPixmap.fromImage(qt_img))

        except Exception as e:
            traceback.print_exc()

    def run(self):
        self.window.show()
        return self.app.exec()

if __name__ == "__main__":
    controller = VectorBodyController()
    sys.exit(controller.run())