# -*- coding: utf-8 -*-
import os
import re
import sys
import time
import traceback
from datetime import datetime

import cv2
import mediapipe as mp
import numpy as np
import pythoncom
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from core.compensation_risk_engine import CompensationRiskEngine
from core.vector_body_analyzer import VectorBodyAnalyzer
from core.vector_body_stabilizer import VectorBodyStabilizer
from ui.vector_body_dashboard import VectorBodyDashboard
from utils.vector_body_audio import VectorBodyAudio
from utils.vector_body_visualizer import VectorBodyVisualizer


def zh(text):
    return text.encode("ascii").decode("unicode_escape")


if hasattr(sys, "_MEIPASS"):
    mp_path = os.path.join(sys._MEIPASS, "mediapipe")
    os.environ["MEDIAPIPE_BINARY_GRAPH_PATH"] = mp_path
    from mediapipe.python import resource_util

    resource_util.set_resource_dir(mp_path)
    print(f">>> MediaPipe resource path: {mp_path}")


try:
    CHINESE_FONT_30 = ImageFont.truetype("msyh.ttc", 30)
    CHINESE_FONT_25 = ImageFont.truetype("msyh.ttc", 25)
except Exception:
    CHINESE_FONT_30 = ImageFont.load_default()
    CHINESE_FONT_25 = ImageFont.load_default()


def draw_chinese_text(img, text, position, font, color=(255, 0, 0)):
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    draw.text(position, font=font, fill=color, text=text)
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


class VectorBodyController:
    def __init__(self):
        print(">>> [1/5] Init COM...")
        pythoncom.CoInitialize()

        self.app = QApplication(sys.argv)
        self._configure_app_font()
        self.window = VectorBodyDashboard()

        print(">>> [2/5] Open camera...")
        self.cap = cv2.VideoCapture(0)

        print(">>> [3/5] Load MediaPipe...")
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(
            model_complexity=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        print(">>> [4/5] Init engines...")
        self.stabilizer = VectorBodyStabilizer()
        self.analyzer = VectorBodyAnalyzer()
        self.compensation_engine = CompensationRiskEngine(level="normal")
        self.visualizer = VectorBodyVisualizer()
        self.audio = VectorBodyAudio()

        self.current_mode = "posture"
        self.current_action_tag = ""
        self.training_phase = "idle"
        self.input_source = "camera"
        self.video_path = None
        self.video_playing = False
        self.video_finished = False
        self.video_score_archived = False
        self.video_archive_path = None
        self.current_frame_index = 0
        self.current_video_msec = 0.0
        self.prepare_stable_since = None
        self.last_center = None
        self.last_voice_time = 0
        self.last_report_update = 0
        self.report_update_interval = 0.6
        self.prepare_required_seconds = 2.0
        self.warn_font = CHINESE_FONT_30
        self.tip_font = CHINESE_FONT_25

        self.setup_connections()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_loop)
        self.timer.start(33)
        print(">>> [5/5] Ready.")

    def _configure_app_font(self):
        font = self.app.font()
        family = font.family() or "Microsoft YaHei UI"
        app_font = QFont(family)
        base_size = font.pointSize()
        if base_size <= 0:
            base_size = 10
        app_font.setPointSize(base_size)
        self.app.setFont(app_font)

    def setup_connections(self):
        self.window.btn_m.clicked.connect(lambda: self.switch_view("muscle"))
        self.window.btn_s.clicked.connect(lambda: self.switch_view("skeleton"))
        self.window.btn_save.clicked.connect(self.handle_save)
        self.window.btn_start_training.clicked.connect(self.start_selected_mode)
        self.window.btn_reset_phase.clicked.connect(self.reset_training_phase)
        self.window.btn_open_video.clicked.connect(self.open_video_file)
        self.window.btn_camera.clicked.connect(self.use_camera_source)
        self.window.mode_combo.currentIndexChanged.connect(self.reset_training_phase)
        self.window.view_combo.currentIndexChanged.connect(self.reset_training_phase)
        self.window.level_combo.currentIndexChanged.connect(self.reset_training_phase)

    def handle_save(self):
        self.window.save_and_reset()

    def switch_view(self, mode):
        side = "back" if "front" in self.window.view_mode else "front"
        self.window.view_mode = f"{side}_{mode}"

    def open_video_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.window,
            zh(r"\u9009\u62e9\u5f85\u68c0\u6d4b\u89c6\u9891"),
            "",
            zh(r"\u89c6\u9891\u6587\u4ef6 (*.mp4 *.avi *.mov *.mkv *.m4v);;\u6240\u6709\u6587\u4ef6 (*.*)"),
        )
        if not file_path:
            return

        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            QMessageBox.warning(self.window, zh(r"\u89c6\u9891\u65e0\u6cd5\u6253\u5f00"), zh(r"\u8bf7\u786e\u8ba4\u89c6\u9891\u6587\u4ef6\u53ef\u8bfb\u3002"))
            return

        if self.cap is not None:
            self.cap.release()
        self.cap = cap
        self.input_source = "video"
        self.video_path = file_path
        self.video_playing = False
        self.video_finished = False
        self.video_score_archived = False
        self.video_archive_path = None
        self.current_frame_index = 0
        self.current_video_msec = 0.0
        self.reset_training_phase()
        self.window.video_label.clear()
        self.window.video_label.setText(zh(r"\u89c6\u9891\u5df2\u5bfc\u5165\uff0c\u9009\u62e9\u52a8\u4f5c\u548c\u6b63/\u4fa7\u4f4d\u540e\u70b9\u51fb\u5f00\u59cb"))
        self.window.update_source_state(os.path.basename(file_path), file_path)
        ready_msg = zh(r"\u5df2\u5bfc\u5165\u89c6\u9891\u3002\u8bf7\u9009\u62e9\u52a8\u4f5c\u3001\u6b63\u4f4d\u6216\u4fa7\u4f4d\uff0c\u7136\u540e\u70b9\u51fb\u5f00\u59cb\uff1b\u7cfb\u7edf\u4f1a\u5728\u8eab\u4f53\u7a33\u5b9a\u5e76\u5f97\u5230\u6709\u6548\u8bc4\u5206\u65f6\u81ea\u52a8\u5f52\u6863\u3002")
        self.window.update_report_html(f"<p style='color:#94A3B8;'>{ready_msg}</p>", force=True)

    def use_camera_source(self):
        if self.input_source == "camera" and self.cap is not None and self.cap.isOpened():
            return
        camera_cap = cv2.VideoCapture(0)
        if not camera_cap.isOpened():
            QMessageBox.warning(self.window, zh(r"\u6444\u50cf\u5934\u65e0\u6cd5\u6253\u5f00"), zh(r"\u8bf7\u68c0\u67e5\u6444\u50cf\u5934\u8fde\u63a5\u6216\u6743\u9650\u3002"))
            camera_cap.release()
            return
        if self.cap is not None:
            self.cap.release()
        self.cap = camera_cap
        self.input_source = "camera"
        self.video_path = None
        self.video_playing = False
        self.video_finished = False
        self.video_score_archived = False
        self.video_archive_path = None
        self.window.update_source_state(zh(r"\u6444\u50cf\u5934"))
        self.reset_training_phase()

    def _reset_signal_state(self):
        self.stabilizer = VectorBodyStabilizer()
        self.analyzer = VectorBodyAnalyzer()
        if hasattr(self.compensation_engine, "_hist"):
            self.compensation_engine._hist.clear()

    def start_selected_mode(self):
        self.current_mode = self.window.selected_mode()
        self.current_action_tag = "" if self.current_mode == "posture" else self.current_mode
        self.compensation_engine.level = self.window.selected_level()
        self.prepare_stable_since = None
        self.last_center = None
        self._reset_signal_state()

        if self.input_source == "video":
            if not self.video_path or self.cap is None or not self.cap.isOpened():
                QMessageBox.information(self.window, zh(r"\u8bf7\u5148\u5bfc\u5165\u89c6\u9891"), zh(r"\u89c6\u9891\u68c0\u6d4b\u9700\u8981\u5148\u9009\u62e9\u89c6\u9891\u6587\u4ef6\u3002"))
                return
            if self.current_mode == "posture":
                QMessageBox.information(self.window, zh(r"\u8bf7\u9009\u62e9\u52a8\u4f5c"), zh(r"\u89c6\u9891\u68c0\u6d4b\u9700\u8981\u9009\u62e9\u6218\u58eb\u4e00\u5f0f\u3001\u6218\u58eb\u4e8c\u5f0f\u6216\u80a9\u5012\u7acb\uff0c\u5e76\u6307\u5b9a\u6b63\u4f4d/\u4fa7\u4f4d\u3002"))
                return
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.video_playing = True
            self.video_finished = False
            self.video_score_archived = False
            self.video_archive_path = None
            self.current_frame_index = 0
            self.current_video_msec = 0.0

        if self.current_mode == "posture":
            self.training_phase = "hold"
            self.window.update_phase(zh(r"\u57fa\u7840\u4f53\u6001\u8bc4\u4f30\u4e2d"))
            self.window.update_detection_state("hold")
            self.window.update_yoga_metrics()
            self.audio.speak(zh(r"\u5f00\u59cb\u57fa\u7840\u4f53\u6001\u8bc4\u4f30\u3002"), clear=True)
            return

        self.training_phase = "prepare"
        pose_name = self._pose_name(self.current_mode)
        self.window.update_phase(pose_name + zh(r"\u51c6\u5907\u4e2d"))
        self.window.update_detection_state("prepare")
        self.window.update_yoga_metrics()
        self.window.update_report_html(self._pose_prepare_html(self.current_mode), force=True)
        self.audio.speak(self._pose_prepare_voice(self.current_mode), clear=True)

    def reset_training_phase(self):
        self.current_mode = self.window.selected_mode()
        self.current_action_tag = "" if self.current_mode == "posture" else self.current_mode
        self.compensation_engine.level = self.window.selected_level()
        self.training_phase = "idle"
        self.prepare_stable_since = None
        self.last_center = None
        if self.input_source == "video":
            self.video_playing = False
            self.video_finished = False
        self.audio.reset()
        self.window.update_phase(zh(r"\u5f85\u5f00\u59cb"))
        self.window.update_detection_state("idle")
        self.window.update_yoga_metrics()
        idle_msg = zh(r"\u8bf7\u9009\u62e9\u68c0\u6d4b\u6a21\u5f0f\uff0c\u7136\u540e\u70b9\u51fb\u5f00\u59cb\u3002")
        self.window.update_report_html(
            f"<p style='color:#94A3B8;'>{idle_msg}</p>",
            force=True,
        )

    def _pose_name(self, mode):
        if mode in ("warrior1", "warrior1_front"):
            return zh(r"\u6218\u58eb\u4e00\u5f0f-\u6b63\u4f4d")
        if mode == "warrior1_side":
            return zh(r"\u6218\u58eb\u4e00\u5f0f-\u4fa7\u4f4d")
        if mode in ("warrior2", "warrior2_front"):
            return zh(r"\u6218\u58eb\u4e8c\u5f0f-\u6b63\u4f4d")
        if mode == "warrior2_side":
            return zh(r"\u6218\u58eb\u4e8c\u5f0f-\u4fa7\u4f4d")
        if mode in ("shoulderstand", "shoulderstand_front"):
            return zh(r"\u80a9\u5012\u7acb-\u6b63\u4f4d")
        if mode == "shoulderstand_side":
            return zh(r"\u80a9\u5012\u7acb-\u4fa7\u4f4d")
        return zh(r"\u57fa\u7840\u4f53\u6001")

    def _pose_prepare_voice(self, mode):
        pose_name = self._pose_name(mode)
        if mode in ("warrior1", "warrior1_front"):
            return (
                zh(r"\u8bf7\u8fdb\u5165") + pose_name
                + zh(r"\u3002\u524d\u811a\u671d\u524d\uff0c\u540e\u811a\u7a33\u5b9a\u624e\u5730\uff0c\u524d\u819d\u5bf9\u51c6\u811a\u8dbe\uff0c\u53cc\u81c2\u5411\u4e0a\u5ef6\u5c55\u3002\u52a8\u4f5c\u5b8c\u6210\u540e\u4fdd\u6301\u7a33\u5b9a\uff0c\u7cfb\u7edf\u4f1a\u81ea\u52a8\u5f00\u59cb\u68c0\u6d4b\u3002")
            )
        if mode == "warrior1_side":
            return (
                zh(r"\u8bf7\u8fdb\u5165") + pose_name
                + zh(r"\u3002\u8eab\u4f53\u4fa7\u9762\u9762\u5411\u6444\u50cf\u5934\u3002\u524d\u819d\u4fdd\u6301\u5728\u524d\u811a\u8e1d\u9644\u8fd1\uff0c\u540e\u817f\u7a33\u5b9a\u4f38\u5c55\u3002\u8eaf\u5e72\u76f4\u7acb\uff0c\u53cc\u81c2\u5411\u4e0a\u5ef6\u5c55\uff0c\u9888\u90e8\u653e\u677e\u3002\u52a8\u4f5c\u5b8c\u6210\u540e\u4fdd\u6301\u7a33\u5b9a\uff0c\u7cfb\u7edf\u4f1a\u81ea\u52a8\u5f00\u59cb\u68c0\u6d4b\u3002")
            )
        if mode in ("warrior2", "warrior2_front"):
            return (
                zh(r"\u8bf7\u8fdb\u5165") + pose_name
                + zh(r"\u3002\u53cc\u811a\u6253\u5f00\u3002\u524d\u819d\u5bf9\u51c6\u7b2c\u4e8c\u3001\u7b2c\u4e09\u811a\u8dbe\u3002\u9aa8\u76c6\u4fdd\u6301\u4e2d\u6b63\u3002\u53cc\u81c2\u5411\u4e24\u4fa7\u6c34\u5e73\u5ef6\u5c55\u3002\u52a8\u4f5c\u5b8c\u6210\u540e\u4fdd\u6301\u7a33\u5b9a\uff0c\u7cfb\u7edf\u4f1a\u81ea\u52a8\u5f00\u59cb\u68c0\u6d4b\u3002")
            )
        if mode == "warrior2_side":
            return (
                zh(r"\u8bf7\u8fdb\u5165") + pose_name
                + zh(r"\u3002\u8eab\u4f53\u4fa7\u9762\u9762\u5411\u6444\u50cf\u5934\u3002\u524d\u819d\u7a33\u5b9a\u5c48\u66f2\uff0c\u4e0d\u8981\u660e\u663e\u8d85\u8fc7\u811a\u5c16\u3002\u8eaf\u5e72\u76f4\u7acb\uff0c\u8170\u690e\u4fdd\u6301\u4e2d\u7acb\uff0c\u9888\u90e8\u653e\u677e\u3002\u52a8\u4f5c\u5b8c\u6210\u540e\u4fdd\u6301\u7a33\u5b9a\uff0c\u7cfb\u7edf\u4f1a\u81ea\u52a8\u5f00\u59cb\u68c0\u6d4b\u3002")
            )
        if mode in ("shoulderstand", "shoulderstand_front"):
            return (
                zh(r"\u8bf7\u8fdb\u5165") + pose_name
                + zh(r"\u3002\u8eab\u4f53\u6b63\u9762\u9762\u5411\u6444\u50cf\u5934\uff0c\u80a9\u80cc\u7a33\u5b9a\u652f\u6491\uff0c\u53cc\u817f\u5e76\u62e2\u5411\u4e0a\u4f38\u5c55\uff0c\u9acb\u90e8\u5806\u53e0\u5230\u5934\u90e8\u4e0a\u65b9\uff0c\u5934\u90e8\u4fdd\u6301\u4e2d\u6b63\u3002\u52a8\u4f5c\u5b8c\u6210\u540e\u4fdd\u6301\u7a33\u5b9a\uff0c\u7cfb\u7edf\u4f1a\u81ea\u52a8\u5f00\u59cb\u68c0\u6d4b\u3002")
            )
        if mode == "shoulderstand_side":
            return (
                zh(r"\u8bf7\u8fdb\u5165") + pose_name
                + zh(r"\u3002\u8eab\u4f53\u4fa7\u9762\u9762\u5411\u6444\u50cf\u5934\uff0c\u80a9\u3001\u9acb\u3001\u8e1d\u5c3d\u91cf\u63a5\u8fd1\u5782\u76f4\u5806\u53e0\uff0c\u5934\u90e8\u4e0d\u8981\u8f6c\u52a8\uff0c\u9888\u90e8\u4e0d\u8981\u627f\u91cd\u3002\u52a8\u4f5c\u5b8c\u6210\u540e\u4fdd\u6301\u7a33\u5b9a\uff0c\u7cfb\u7edf\u4f1a\u81ea\u52a8\u5f00\u59cb\u68c0\u6d4b\u3002")
            )
        return zh(r"\u8bf7\u4fdd\u6301\u5168\u8eab\u5165\u955c\uff0c\u5f00\u59cb\u57fa\u7840\u4f53\u6001\u8bc4\u4f30\u3002")

    def _pose_prepare_html(self, mode):
        pose_name = self._pose_name(mode)
        if mode in ("warrior1", "warrior1_front"):
            steps = [
                zh(r"\u524d\u811a\u671d\u524d\uff0c\u540e\u811a\u7a33\u5b9a\u624e\u5730\u3002"),
                zh(r"\u524d\u819d\u5bf9\u51c6\u811a\u8dbe\uff0c\u9aa8\u76c6\u5c3d\u91cf\u4fdd\u6301\u4e2d\u6b63\u3002"),
                zh(r"\u8eaf\u5e72\u76f4\u7acb\uff0c\u53cc\u81c2\u5411\u5934\u9876\u4e0a\u65b9\u5ef6\u5c55\u3002"),
            ]
        elif mode == "warrior1_side":
            steps = [
                zh(r"\u8eab\u4f53\u4fa7\u9762\u9762\u5411\u6444\u50cf\u5934\uff0c\u524d\u540e\u811a\u5728\u753b\u9762\u4e2d\u5c55\u5f00\u3002"),
                zh(r"\u524d\u819d\u5c48\u66f2\u4f46\u4e0d\u8981\u660e\u663e\u524d\u51b2\uff0c\u540e\u817f\u7a33\u5b9a\u4f38\u5c55\u3002"),
                zh(r"\u8eaf\u5e72\u63a5\u8fd1\u5782\u76f4\uff0c\u53cc\u81c2\u5411\u4e0a\u5ef6\u5c55\uff0c\u4e0d\u8981\u4ef0\u5934\u6216\u584c\u8170\u3002"),
            ]
        elif mode in ("warrior2", "warrior2_front"):
            steps = [
                zh(r"\u53cc\u811a\u6253\u5f00\uff0c\u540e\u811a\u8ddf\u548c\u811a\u5916\u4fa7\u7a33\u5b9a\u538b\u5730\u3002"),
                zh(r"\u524d\u819d\u5bf9\u51c6\u7b2c\u4e8c\u3001\u7b2c\u4e09\u811a\u8dbe\uff0c\u9aa8\u76c6\u548c\u8170\u690e\u4fdd\u6301\u4e2d\u7acb\u3002"),
                zh(r"\u80f8\u8154\u5c55\u5f00\uff0c\u53cc\u81c2\u5411\u4e24\u4fa7\u6c34\u5e73\u5ef6\u5c55\uff0c\u9888\u90e8\u653e\u677e\u3002"),
            ]
        elif mode == "warrior2_side":
            steps = [
                zh(r"\u8eab\u4f53\u4fa7\u9762\u9762\u5411\u6444\u50cf\u5934\uff0c\u524d\u540e\u811a\u5728\u753b\u9762\u4e2d\u5c55\u5f00\u3002"),
                zh(r"\u524d\u819d\u5c48\u66f2\u4f46\u4e0d\u8981\u660e\u663e\u524d\u51b2\uff0c\u540e\u817f\u7a33\u5b9a\u4f38\u5c55\u3002"),
                zh(r"\u8eaf\u5e72\u76f4\u7acb\uff0c\u8170\u690e\u4fdd\u6301\u4e2d\u7acb\uff0c\u5934\u9888\u4e0d\u8981\u524d\u63a2\u3002"),
            ]
        elif mode in ("shoulderstand", "shoulderstand_front"):
            steps = [
                zh(r"\u53cc\u80a9\u548c\u4e0a\u80cc\u7a33\u5b9a\u8d34\u5730\u652f\u6491\uff0c\u5934\u90e8\u4fdd\u6301\u4e2d\u6b63\uff0c\u4e0d\u8981\u5de6\u53f3\u8f6c\u5934\u3002"),
                zh(r"\u53cc\u8098\u63a5\u8fd1\u80a9\u5bbd\uff0c\u53cc\u817f\u5411\u4e2d\u7ebf\u5e76\u62e2\uff0c\u9aa8\u76c6\u4fdd\u6301\u6c34\u5e73\u3002"),
                zh(r"\u819d\u76d6\u81ea\u7136\u4f38\u5c55\uff0c\u9acb\u90e8\u548c\u53cc\u817f\u5411\u4e0a\u5806\u53e0\uff0c\u5148\u4fdd\u8bc1\u9888\u690e\u5b89\u5168\u3002"),
            ]
        elif mode == "shoulderstand_side":
            steps = [
                zh(r"\u8eab\u4f53\u4fa7\u9762\u9762\u5411\u6444\u50cf\u5934\uff0c\u80a9\u3001\u9acb\u3001\u8e1d\u5c3d\u91cf\u63a5\u8fd1\u4e00\u6761\u5782\u76f4\u7ebf\u3002"),
                zh(r"\u9acb\u90e8\u5411\u4e0a\u5806\u53e0\u5230\u80a9\u4e0a\u65b9\u9644\u8fd1\uff0c\u8170\u80cc\u4fdd\u6301\u652f\u6491\uff0c\u907f\u514d\u584c\u8170\u3002"),
                zh(r"\u5934\u9888\u653e\u677e\u5e76\u4fdd\u6301\u4e2d\u6b63\uff0c\u82e5\u9888\u90e8\u53d7\u538b\u8bf7\u9000\u51fa\u6216\u4f7f\u7528\u652f\u6491\u7248\u672c\u3002"),
            ]
        else:
            steps = [zh(r"\u8bf7\u9762\u5411\u6444\u50cf\u5934\uff0c\u4fdd\u6301\u5168\u8eab\u5165\u955c\u3002")]
        items = "".join([f"<li>{step}</li>" for step in steps])
        title_suffix = zh(r"\u51c6\u5907\u9636\u6bb5")
        intro = zh(r"\u8bf7\u6309\u7167\u8bed\u97f3\u5f15\u5bfc\u8fdb\u5165\u52a8\u4f5c\uff0c\u6b64\u9636\u6bb5\u53ea\u505a\u5165\u955c\u548c\u7a33\u5b9a\u5224\u65ad\uff0c\u4e0d\u8fdb\u884c\u52a8\u4f5c\u8bc4\u5206\u3002")
        hold_tip = zh(r"\u52a8\u4f5c\u5b8c\u6210\u540e\u4fdd\u6301\u7a33\u5b9a 2 \u79d2\uff0c\u7cfb\u7edf\u5c06\u81ea\u52a8\u8fdb\u5165\u4fdd\u6301\u68c0\u6d4b\u9636\u6bb5\u3002")
        return f"""
        <div style='font-size:14px; line-height:1.55; color:#E2E8F0;'>
            <h3 style='color:#F59E0B;'>{pose_name}{title_suffix}</h3>
            <p>{intro}</p>
            <ol>{items}</ol>
            <p style='color:#94A3B8;'>{hold_tip}</p>
        </div>
        """

    def _is_body_stable(self, center_x, center_y, now):
        center = np.array([center_x, center_y], dtype=float)
        if self.last_center is None:
            self.last_center = center
            self.prepare_stable_since = now
            return False
        movement = float(np.linalg.norm(center - self.last_center))
        self.last_center = center
        if movement < 0.012:
            if self.prepare_stable_since is None:
                self.prepare_stable_since = now
            return now - self.prepare_stable_since >= self.prepare_required_seconds
        self.prepare_stable_since = now
        return False

    def _update_report(self, report_html, now=None, force=False):
        if now is None:
            now = time.time()
        if force or (now - self.last_report_update >= self.report_update_interval):
            self.window.update_report_html(report_html, force=force)
            self.last_report_update = now

    def _render_frame(self, frame, w, h, ch):
        qt_img = QImage(
            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).data,
            w,
            h,
            w * ch,
            QImage.Format_RGB888,
        ).copy()
        self.window.update_frame(QPixmap.fromImage(qt_img))

    def _run_basic_assessment(self, metrics):
        status, report_html, voice_text = self.analyzer.analyze_clinical(
            metrics, self.window.patient_name.text() or zh(r"\u5f85\u6d4b\u7ec3\u4e60\u8005")
        )
        self.window.val_sh.setText(zh(r"\u9ad8\u4f4e\u80a9: ") + f"{abs(metrics['sh']):.1f}\u00b0")
        self.window.val_pl.setText(zh(r"\u9aa8\u76c6\u504f\u79fb: ") + f"{abs(metrics['pl']):.1f}\u00b0")
        self.window.val_sc.setText(zh(r"\u810a\u67f1\u4fa7\u5f2f: ") + f"{abs(metrics['sc']):.1f}\u00b0")
        return status, report_html, voice_text

    def _run_yoga_hold(self, points, metrics):
        result = self.compensation_engine.analyze_report(points, self.current_action_tag)
        if result is None:
            return self._run_basic_assessment(metrics)
        status, report_html, voice_text, risk, score, grade, detail, metric_scores = result
        self.window.update_yoga_metrics(score, grade, detail)
        if self.input_source == "video" and not self.video_score_archived and not detail.get("gate_state"):
            archive_path = self._archive_video_score(risk, score, grade, detail, metric_scores, report_html)
            if archive_path:
                archived = zh(r"\u7a33\u5b9a\u8bc4\u5206\u5df2\u5f52\u6863\uff1a")
                report_html += (
                    f"<p style='color:#10B981;'><b>{archived}</b>{score:.0f} / 100 ({grade})<br>"
                    f"<span style='color:#94A3B8;'>{archive_path}</span></p>"
                )
        return status, report_html, voice_text

    def _safe_archive_name(self, text):
        cleaned = re.sub(r'[\\/:*?"<>|]+', "_", text.strip())
        return cleaned[:60] or zh(r"\u533f\u540d")

    def _archive_video_score(self, risk, score, grade, detail, metric_scores, report_html):
        if not self.video_path:
            return None
        report_dir = os.path.join(os.getcwd(), "reports", "video_scores")
        os.makedirs(report_dir, exist_ok=True)

        name = self.window.patient_name.text().strip() if self.window.patient_name.text() else zh(r"\u533f\u540d\u7ec3\u4e60\u8005")
        video_name = os.path.splitext(os.path.basename(self.video_path))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = (
            f"{self._safe_archive_name(name)}_"
            f"{self._safe_archive_name(self._pose_name(self.current_mode))}_"
            f"{self._safe_archive_name(video_name)}_{timestamp}.txt"
        )
        file_path = os.path.join(report_dir, file_name)
        pose_view = zh(r"\u6b63\u4f4d") if self.current_mode.endswith("_front") else zh(r"\u4fa7\u4f4d")
        video_time = self.current_video_msec / 1000.0 if self.current_video_msec else 0.0

        metric_lines = []
        for key, item in metric_scores.items():
            metric_lines.append(
                f"- {key}: 值 {item.get('value', 0.0):.2f}, 评分 {item.get('score', 0.0):.0f}, "
                f"稳定度 {item.get('stability', 0.0):.2f}, 权重 {item.get('weight', 0.0):.2f}"
            )

        content = [
            zh(r"VectorBody \u89c6\u9891\u7a33\u5b9a\u8bc4\u5206\u5f52\u6863"),
            "=" * 40,
            zh(r"\u5f52\u6863\u65f6\u95f4: ") + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            zh(r"\u7ec3\u4e60\u8005: ") + name,
            zh(r"\u89c6\u9891\u6587\u4ef6: ") + self.video_path,
            zh(r"\u68c0\u6d4b\u52a8\u4f5c: ") + self._pose_name(self.current_mode),
            zh(r"\u68c0\u6d4b\u89c6\u89d2: ") + pose_view,
            zh(r"\u7a33\u5b9a\u5e27\u5e8f\u53f7: ") + str(self.current_frame_index),
            zh(r"\u7a33\u5b9a\u89c6\u9891\u65f6\u95f4: ") + f"{video_time:.2f}s",
            "",
            zh(r"\u7a33\u5b9a\u8bc4\u5206: ") + f"{score:.0f} / 100",
            zh(r"\u4f53\u6001\u7b49\u7ea7: ") + str(grade),
            zh(r"\u603b\u4f53\u98ce\u9669: ") + f"{risk * 100:.1f}%",
            zh(r"\u7075\u6d3b\u5173\u8282\u9501\u5b9a: ") + f"{detail.get('risk_mobile_lock', 0.0) * 100:.1f}%",
            zh(r"\u975e\u7075\u6d3b\u5173\u8282\u4ee3\u507f: ") + f"{detail.get('risk_stiff_comp', 0.0) * 100:.1f}%",
            "",
            zh(r"\u5173\u952e\u6307\u6807:"),
            *(metric_lines or [zh(r"\u6682\u65e0\u5206\u9879\u6307\u6807\u3002")]),
            "",
            zh(r"\u754c\u9762\u62a5\u544a HTML:"),
            report_html,
        ]
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(content))
            self.video_score_archived = True
            self.video_archive_path = file_path
            return file_path
        except Exception as e:
            QMessageBox.warning(self.window, zh(r"\u5f52\u6863\u5931\u8d25"), zh(r"\u65e0\u6cd5\u5199\u5165\u7a33\u5b9a\u8bc4\u5206: ") + str(e))
            return None

    def _handle_video_finished(self):
        if self.video_finished:
            return
        self.video_finished = True
        self.video_playing = False
        self.window.update_phase(zh(r"\u89c6\u9891\u68c0\u6d4b\u5b8c\u6210"))
        if self.video_archive_path:
            done_msg = zh(r"\u89c6\u9891\u68c0\u6d4b\u5b8c\u6210\uff0c\u7a33\u5b9a\u8bc4\u5206\u5df2\u5f52\u6863\uff1a")
            self.window.update_report_html(
                f"<p style='color:#10B981;'>{done_msg}<br>{self.video_archive_path}</p>",
                force=True,
            )
        else:
            miss_msg = zh(r"\u89c6\u9891\u5df2\u64ad\u653e\u5b8c\uff0c\u4f46\u672a\u83b7\u5f97\u8fde\u7eed\u7a33\u5b9a\u7684\u6709\u6548\u52a8\u4f5c\u8bc4\u5206\u3002\u53ef\u68c0\u67e5\u5168\u8eab\u662f\u5426\u5165\u955c\uff0c\u6216\u91cd\u65b0\u9009\u62e9\u52a8\u4f5c/\u6b63\u4fa7\u4f4d\u540e\u518d\u6b21\u5f00\u59cb\u3002")
            self.window.update_report_html(f"<p style='color:#F59E0B;'>{miss_msg}</p>", force=True)

    def update_loop(self):
        try:
            if self.input_source == "video" and not self.video_playing:
                return
            ret, frame = self.cap.read()
            if not ret or frame is None:
                if self.input_source == "video":
                    self._handle_video_finished()
                return

            if self.input_source == "camera":
                frame = cv2.flip(frame, 1)
            else:
                self.current_frame_index = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                self.current_video_msec = float(self.cap.get(cv2.CAP_PROP_POS_MSEC))
            h, w, ch = frame.shape
            circle_radius = min(w, h) // 2 if self.input_source == "video" else 200
            cv2.circle(frame, (w // 2, h // 2), circle_radius, (200, 200, 200), 1, cv2.LINE_AA)

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.pose.process(rgb_frame)
            if not results.pose_landmarks:
                self._render_frame(frame, w, h, ch)
                return

            lm = results.pose_landmarks.landmark
            center_x = (lm[11].x + lm[12].x + lm[23].x + lm[24].x) / 4
            center_y = (lm[11].y + lm[12].y + lm[23].y + lm[24].y) / 4
            center_px = center_x * w
            center_py = center_y * h
            dist_from_center = ((center_px - w / 2) ** 2 + (center_py - h / 2) ** 2) ** 0.5

            if dist_from_center >= circle_radius:
                frame = draw_chinese_text(frame, zh(r"\u8bf7\u79fb\u81f3\u68c0\u6d4b\u5708\u5185"), (w // 2 - 120, 60), self.tip_font)
                self._render_frame(frame, w, h, ch)
                return

            frame = self.visualizer.draw_skeleton(frame, results.pose_landmarks)
            points = self.stabilizer.smooth(results.pose_landmarks)
            metrics, is_valid = self.analyzer.get_metrics(points)
            if not is_valid:
                frame = draw_chinese_text(frame, zh(r"\u8bf7\u4fdd\u8bc1\u5168\u8eab\u5165\u955c"), (w // 2 - 120, 110), self.warn_font)

            now = time.time()
            force_report_update = False
            if self.training_phase == "idle":
                status = {"neck": "ok", "shoulder_l": "ok", "shoulder_r": "ok", "pelvis": "ok", "spine": "ok"}
                idle_msg = zh(r"\u8bf7\u9009\u62e9\u68c0\u6d4b\u6a21\u5f0f\uff0c\u7136\u540e\u70b9\u51fb\u5f00\u59cb\u3002")
                report_html = (
                    f"<p style='color:#94A3B8;'>{idle_msg}</p>"
                )
                voice_text = ""
            elif self.current_mode == "posture" or (
                self.training_phase in ("idle", "hold") and self.current_action_tag == ""
            ):
                status, report_html, voice_text = self._run_basic_assessment(metrics)
            elif self.training_phase == "prepare":
                pose_name = self._pose_name(self.current_mode)
                if is_valid and self._is_body_stable(center_x, center_y, now):
                    self.training_phase = "hold"
                    self.window.update_phase(pose_name + zh(r"\u4fdd\u6301\u68c0\u6d4b\u4e2d"))
                    self.window.update_detection_state("hold")
                    self.audio.speak(zh(r"\u4fdd\u6301\u52a8\u4f5c\uff0c\u5f00\u59cb\u68c0\u6d4b\u3002"), clear=True)
                    status, report_html, voice_text = self._run_yoga_hold(points, metrics)
                    force_report_update = True
                else:
                    status = {"neck": "ok", "shoulder_l": "ok", "shoulder_r": "ok", "pelvis": "ok", "spine": "ok"}
                    report_html = self._pose_prepare_html(self.current_mode)
                    voice_text = ""
                    self.window.update_yoga_metrics()
            else:
                status, report_html, voice_text = self._run_yoga_hold(points, metrics)

            self._update_report(report_html, now, force=force_report_update)
            self.window.update_anatomy(status)
            if is_valid and voice_text and (now - self.last_voice_time > 6):
                self.audio.speak(voice_text)
                self.last_voice_time = now

            self._render_frame(frame, w, h, ch)
        except Exception:
            traceback.print_exc()

    def run(self):
        self.window.show()
        return self.app.exec()


if __name__ == "__main__":
    controller = VectorBodyController()
    sys.exit(controller.run())
