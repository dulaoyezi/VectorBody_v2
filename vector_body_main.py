# -*- coding: utf-8 -*-
import os
import re
import sys
import time
import traceback
from copy import deepcopy
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
        self.camera_blank_frames = 0
        self.camera_read_failures = 0
        self.camera_last_notice_time = 0.0
        self.camera_open_note = ""
        self.cap = self._open_camera_capture()

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
        self.video_best_result = None
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
        if self.cap is None or not self.cap.isOpened():
            self.window.video_label.setText(zh(r"\u6444\u50cf\u5934\u65e0\u6cd5\u6253\u5f00\uff0c\u8bf7\u68c0\u67e5\u6743\u9650\u6216\u8fde\u63a5\u3002"))
            self.window.update_source_state(zh(r"\u6444\u50cf\u5934\u672a\u8fde\u63a5"))
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

    def _open_capture(self, index, backend):
        if backend is None:
            return cv2.VideoCapture(index)
        return cv2.VideoCapture(index, backend)

    def _probe_frame(self, cap):
        ret, frame = False, None
        for _ in range(5):
            ret, frame = cap.read()
            if ret and frame is not None:
                break
        return ret, frame

    def _is_blank_camera_frame(self, frame):
        if frame is None:
            return True
        return float(frame.mean()) < 25.0 and float(frame.std()) < 5.0

    def _open_camera_capture(self):
        backends = [
            ("DirectShow", cv2.CAP_DSHOW),
            ("Media Foundation", cv2.CAP_MSMF),
            ("Default", None),
        ]
        fallback = None
        for index in range(4):
            for backend_name, backend in backends:
                cap = self._open_capture(index, backend)
                if not cap.isOpened():
                    cap.release()
                    continue
                ret, frame = self._probe_frame(cap)
                if ret and frame is not None and not self._is_blank_camera_frame(frame):
                    self.camera_open_note = f"camera index {index}, {backend_name}"
                    print(f">>> Camera ready: {self.camera_open_note}")
                    return cap
                if fallback is None:
                    fallback = (index, backend_name, backend)
                cap.release()

        if fallback is not None:
            index, backend_name, backend = fallback
            self.camera_open_note = f"camera index {index}, {backend_name}, blank frame"
            print(f">>> Camera opened but frame is blank: {self.camera_open_note}")
            return self._open_capture(index, backend)

        self.camera_open_note = "no available camera"
        print(">>> Camera open failed: no available camera")
        return None

    def _notify_camera_issue(self, message, force=False):
        now = time.time()
        if not force and now - self.camera_last_notice_time < 2.0:
            return
        self.camera_last_notice_time = now
        self.window.update_phase(message)
        self.window.update_detection_state("idle")
        self.window.update_report_html(f"<p style='color:#F59E0B;'>{message}</p>", force=True)

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
        if self.input_source == "video" and self.current_mode != "posture":
            archive_path = self._archive_best_video_score()
            if archive_path:
                archived_msg = zh(r"\u89c6\u9891\u6700\u9ad8\u8bc4\u5206\u5df2\u5f52\u6863\uff1a")
                QMessageBox.information(
                    self.window,
                    zh(r"\u6210\u529f"),
                    archived_msg + archive_path,
                )
                self.window.update_report_html(
                    f"<p style='color:#10B981;'>{archived_msg}<br>{archive_path}</p>",
                    force=True,
                )
                return
            QMessageBox.information(
                self.window,
                zh(r"\u6682\u65e0\u53ef\u4fdd\u5b58\u8bc4\u5206"),
                zh(r"\u5c1a\u672a\u83b7\u5f97\u6709\u6548\u89c6\u9891\u8bc4\u5206\u5e27\uff0c\u8bf7\u7ee7\u7eed\u64ad\u653e\u6216\u91cd\u65b0\u68c0\u6d4b\u3002"),
            )
            return
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
        self.video_best_result = None
        self.current_frame_index = 0
        self.current_video_msec = 0.0
        self.reset_training_phase()
        self.window.video_label.clear()
        self.window.video_label.setText(zh(r"\u89c6\u9891\u5df2\u5bfc\u5165\uff0c\u9009\u62e9\u52a8\u4f5c\u548c\u6b63/\u4fa7\u4f4d\u540e\u70b9\u51fb\u5f00\u59cb"))
        self.window.update_source_state(os.path.basename(file_path), file_path)
        ready_msg = zh(r"\u5df2\u5bfc\u5165\u89c6\u9891\u3002\u8bf7\u9009\u62e9\u52a8\u4f5c\u3001\u6b63\u4f4d\u6216\u4fa7\u4f4d\uff0c\u7136\u540e\u70b9\u51fb\u5f00\u59cb\uff1b\u7cfb\u7edf\u4f1a\u8bb0\u5f55\u5168\u6bb5\u89c6\u9891\u4e2d\u7684\u6700\u9ad8\u5f97\u5206\uff0c\u5e76\u5728\u64ad\u653e\u7ed3\u675f\u540e\u5f52\u6863\u3002")
        self.window.update_report_html(f"<p style='color:#94A3B8;'>{ready_msg}</p>", force=True)

    def use_camera_source(self):
        if self.input_source == "camera" and self.cap is not None:
            self.cap.release()
            self.cap = None
        camera_cap = self._open_camera_capture()
        if camera_cap is None or not camera_cap.isOpened():
            QMessageBox.warning(self.window, zh(r"\u6444\u50cf\u5934\u65e0\u6cd5\u6253\u5f00"), zh(r"\u8bf7\u68c0\u67e5\u6444\u50cf\u5934\u8fde\u63a5\u6216\u6743\u9650\u3002"))
            if camera_cap is not None:
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
        self.video_best_result = None
        self.camera_blank_frames = 0
        self.camera_read_failures = 0
        self.window.update_source_state(zh(r"\u6444\u50cf\u5934"))
        self.reset_training_phase()

    def _reset_signal_state(self):
        self.stabilizer = VectorBodyStabilizer()
        self.analyzer = VectorBodyAnalyzer()
        if hasattr(self.compensation_engine, "reset"):
            self.compensation_engine.reset()
        elif hasattr(self.compensation_engine, "_hist"):
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
                QMessageBox.information(self.window, zh(r"\u8bf7\u9009\u62e9\u52a8\u4f5c"), zh(r"\u89c6\u9891\u68c0\u6d4b\u9700\u8981\u9009\u62e9\u4e00\u4e2a\u745c\u4f3d\u52a8\u4f5c\uff0c\u5e76\u6307\u5b9a\u6b63\u4f4d/\u4fa7\u4f4d\u3002"))
                return
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.video_playing = True
            self.video_finished = False
            self.video_score_archived = False
            self.video_archive_path = None
            self.video_best_result = None
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
            self.video_score_archived = False
            self.video_archive_path = None
            self.video_best_result = None
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
        names = {
            "warrior1": zh(r"\u6218\u58eb\u4e00\u5f0f-\u6b63\u4f4d"),
            "warrior1_front": zh(r"\u6218\u58eb\u4e00\u5f0f-\u6b63\u4f4d"),
            "warrior1_side": zh(r"\u6218\u58eb\u4e00\u5f0f-\u4fa7\u4f4d"),
            "warrior2": zh(r"\u6218\u58eb\u4e8c\u5f0f-\u6b63\u4f4d"),
            "warrior2_front": zh(r"\u6218\u58eb\u4e8c\u5f0f-\u6b63\u4f4d"),
            "warrior2_side": zh(r"\u6218\u58eb\u4e8c\u5f0f-\u4fa7\u4f4d"),
            "tadasana": zh(r"\u5c71\u5f0f-\u6b63\u4f4d"),
            "tadasana_front": zh(r"\u5c71\u5f0f-\u6b63\u4f4d"),
            "tadasana_side": zh(r"\u5c71\u5f0f-\u4fa7\u4f4d"),
            "sukhasana": zh(r"\u7b80\u6613\u5750-\u6b63\u4f4d"),
            "sukhasana_front": zh(r"\u7b80\u6613\u5750-\u6b63\u4f4d"),
            "sukhasana_side": zh(r"\u7b80\u6613\u5750-\u4fa7\u4f4d"),
            "uttanasana": zh(r"\u7ad9\u7acb\u524d\u5c48\u5f0f-\u6b63\u4f4d"),
            "uttanasana_front": zh(r"\u7ad9\u7acb\u524d\u5c48\u5f0f-\u6b63\u4f4d"),
            "uttanasana_side": zh(r"\u7ad9\u7acb\u524d\u5c48\u5f0f-\u4fa7\u4f4d"),
            "cobra": zh(r"\u773c\u955c\u86c7\u5f0f-\u6b63\u4f4d"),
            "cobra_front": zh(r"\u773c\u955c\u86c7\u5f0f-\u6b63\u4f4d"),
            "cobra_side": zh(r"\u773c\u955c\u86c7\u5f0f-\u4fa7\u4f4d"),
            "bhujangasana": zh(r"\u773c\u955c\u86c7\u5f0f-\u6b63\u4f4d"),
            "bhujangasana_front": zh(r"\u773c\u955c\u86c7\u5f0f-\u6b63\u4f4d"),
            "bhujangasana_side": zh(r"\u773c\u955c\u86c7\u5f0f-\u4fa7\u4f4d"),
            "balance": zh(r"\u5e73\u8861\u5f0f-\u6b63\u4f4d"),
            "balance_front": zh(r"\u5e73\u8861\u5f0f-\u6b63\u4f4d"),
            "balance_side": zh(r"\u5e73\u8861\u5f0f-\u4fa7\u4f4d"),
            "downward": zh(r"\u4e0b\u72ac\u5f0f-\u6b63\u4f4d"),
            "downward_front": zh(r"\u4e0b\u72ac\u5f0f-\u6b63\u4f4d"),
            "downward_side": zh(r"\u4e0b\u72ac\u5f0f-\u4fa7\u4f4d"),
            "downward_dog": zh(r"\u4e0b\u72ac\u5f0f-\u6b63\u4f4d"),
            "downward_dog_front": zh(r"\u4e0b\u72ac\u5f0f-\u6b63\u4f4d"),
            "downward_dog_side": zh(r"\u4e0b\u72ac\u5f0f-\u4fa7\u4f4d"),
        }
        return names.get(mode, zh(r"\u57fa\u7840\u4f53\u6001"))

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
        if mode.startswith(("tadasana", "sukhasana", "uttanasana", "cobra", "bhujangasana", "balance", "downward")):
            return (
                zh(r"\u8bf7\u8fdb\u5165") + pose_name
                + zh(r"\u3002\u4fdd\u6301\u5168\u8eab\u5165\u955c\uff0c\u6309\u5f53\u524d\u6b63\u4f4d\u6216\u4fa7\u4f4d\u89c6\u89d2\u7a33\u5b9a\u5b8c\u6210\u52a8\u4f5c\uff0c\u8c03\u6574\u547c\u5438\u548c\u8eab\u4f53\u5bf9\u7ebf\u3002\u52a8\u4f5c\u5b8c\u6210\u540e\u4fdd\u6301\u7a33\u5b9a\uff0c\u7cfb\u7edf\u4f1a\u81ea\u52a8\u5f00\u59cb\u68c0\u6d4b\u3002")
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
        elif mode.startswith(("tadasana", "sukhasana", "uttanasana", "cobra", "bhujangasana", "balance", "downward")):
            steps = [
                zh(r"\u4fdd\u6301\u5168\u8eab\u5165\u955c\uff0c\u6309\u5f53\u524d\u6b63\u4f4d\u6216\u4fa7\u4f4d\u9762\u5bf9\u6444\u50cf\u5934\u3002"),
                zh(r"\u5148\u5b8c\u6210\u52a8\u4f5c\u5f62\u6001\uff0c\u518d\u5fae\u8c03\u810a\u67f1\u3001\u9aa8\u76c6\u3001\u80a9\u9888\u548c\u91cd\u5fc3\u3002"),
                zh(r"\u52a8\u4f5c\u7a33\u5b9a\u540e\u4fdd\u6301\u547c\u5438\uff0c\u7b49\u5f85\u7cfb\u7edf\u8fdb\u5165\u68c0\u6d4b\u3002"),
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
        self.window.update_basic_metrics(metrics, voice_text)
        return status, report_html, voice_text

    def _run_yoga_hold(self, points, metrics):
        result = self.compensation_engine.analyze_report(points, self.current_action_tag)
        if result is None:
            return self._run_basic_assessment(metrics)
        status, report_html, voice_text, risk, score, grade, detail, metric_scores = result
        self.window.update_yoga_metrics(score, grade, detail, voice_text)
        if self.input_source == "video":
            self._record_video_best_score(risk, score, grade, detail, metric_scores, report_html)
            if self.video_best_result:
                best_label = zh(r"\u5f53\u524d\u89c6\u9891\u6700\u9ad8\u5206\uff1a")
                frame_label = zh(r"\u5e27")
                time_label = zh(r"\u65f6\u95f4")
                best = self.video_best_result
                report_html += (
                    f"<p style='color:#10B981;'><b>{best_label}</b>"
                    f"{best['score']:.0f} / 100 ({best['grade']}) "
                    f"<span style='color:#94A3B8;'>"
                    f"{frame_label} {best['frame_index']} / {time_label} {best['video_msec'] / 1000.0:.2f}s"
                    f"</span></p>"
                )
        return status, report_html, voice_text

    def _is_video_score_candidate(self, detail):
        return True

    def _record_video_best_score(self, risk, score, grade, detail, metric_scores, report_html):
        if not self._is_video_score_candidate(detail):
            return False
        if self.video_best_result and score <= self.video_best_result["score"]:
            return False
        if self.video_score_archived:
            self.video_score_archived = False
            self.video_archive_path = None
        self.video_best_result = {
            "risk": float(risk),
            "score": float(score),
            "grade": str(grade),
            "detail": deepcopy(detail),
            "metric_scores": deepcopy(metric_scores),
            "report_html": str(report_html),
            "frame_index": int(self.current_frame_index),
            "video_msec": float(self.current_video_msec),
        }
        return True

    def _safe_archive_name(self, text):
        cleaned = re.sub(r'[\\/:*?"<>|]+', "_", text.strip())
        return cleaned[:60] or zh(r"\u533f\u540d")

    def _archive_video_score(
        self,
        risk,
        score,
        grade,
        detail,
        metric_scores,
        report_html,
        frame_index=None,
        video_msec=None,
    ):
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
        if frame_index is None:
            frame_index = self.current_frame_index
        if video_msec is None:
            video_msec = self.current_video_msec
        video_time = video_msec / 1000.0 if video_msec else 0.0
        if detail.get("bone_length_ready"):
            bone_state = zh(r"\u53ef\u4fe1") if detail.get("bone_length_valid") else zh(r"\u5f02\u5e38")
            bone_quality = f"{float(detail.get('bone_length_quality', 0.0)) * 100:.1f}%"
            bone_deviation = f"{float(detail.get('bone_length_max_deviation', 0.0)) * 100:.1f}%"
        else:
            bone_state = zh(r"\u7a97\u53e3\u5efa\u7acb\u4e2d")
            bone_quality = "--"
            bone_deviation = "--"
        hold_state = str(detail.get("hold_phase_label", zh(r"\u51c6\u5907\u4e2d")))
        bone_sampling = (
            zh(r"\u91c7\u6837\u4e2d")
            if detail.get("bone_length_learn_reference")
            else zh(r"\u6682\u505c\u91c7\u6837")
        )

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
            zh(r"\u6700\u9ad8\u5206\u5e27\u5e8f\u53f7: ") + str(frame_index),
            zh(r"\u6700\u9ad8\u5206\u89c6\u9891\u65f6\u95f4: ") + f"{video_time:.2f}s",
            "",
            zh(r"\u89c6\u9891\u6700\u9ad8\u8bc4\u5206: ") + f"{score:.0f} / 100",
            zh(r"\u4f53\u6001\u7b49\u7ea7: ") + str(grade),
            zh(r"\u603b\u4f53\u98ce\u9669: ") + f"{risk * 100:.1f}%",
            zh(r"\u5173\u8282-\u59ff\u6001\u7b26\u5408\u5ea6: ") + f"{float(detail.get('score_joint_conformity', 0.0)):.1f} / 100",
            zh(r"\u62d3\u6251\u7a33\u5b9a\u4e0e\u4ee3\u507f\u63a7\u5236: ") + f"{float(detail.get('score_topology_stability', 0.0)):.1f} / 100",
            zh(r"\u529b\u6a21\u5f0f\u4ee3\u7406\u5408\u7406\u6027: ") + f"{float(detail.get('score_force_proxy', 0.0)):.1f} / 100",
            zh(r"\u7075\u6d3b\u5173\u8282\u9501\u5b9a: ") + f"{detail.get('risk_mobile_lock', 0.0) * 100:.1f}%",
            zh(r"\u975e\u7075\u6d3b\u5173\u8282\u4ee3\u507f: ") + f"{detail.get('risk_stiff_comp', 0.0) * 100:.1f}%",
            zh(r"\u4fdd\u6301\u9636\u6bb5: ") + hold_state,
            zh(r"\u865a\u62df\u9aa8\u957f\u91c7\u6837: ") + bone_sampling,
            zh(r"\u865a\u62df\u9aa8\u957f\u72b6\u6001: ") + bone_state,
            zh(r"\u865a\u62df\u9aa8\u957f\u53ef\u4fe1\u5ea6: ") + bone_quality,
            zh(r"\u865a\u62df\u9aa8\u957f\u6700\u5927\u504f\u79bb: ") + bone_deviation,
            zh(r"\u4eba\u4f53\u62d3\u6251\u6811\u8282\u70b9\u6570: ") + str(detail.get("topology_node_count", 0)),
            zh(r"\u62d3\u6251\u8fb9/\u9aa8\u9abc\u5411\u91cf\u6570: ") + str(detail.get("topology_edge_count", 0)),
            zh(r"DLS-IK \u8fed\u4ee3\u6b21\u6570: ") + str(detail.get("ik_iterations", 0)),
            zh(r"DLS-IK \u6700\u7ec8\u6b8b\u5dee: ") + f"{float(detail.get('ik_final_residual', 0.0)):.6f}",
            zh(r"DLS-IK \u6700\u5927\u9aa8\u957f\u8bef\u5dee: ") + f"{float(detail.get('ik_max_length_error', 0.0)) * 100:.2f}%",
            zh(r"\u5e73\u5747\u9aa8\u9abc\u5411\u91cf\u957f\u5ea6: ") + f"{float(detail.get('skeleton_vector_mean_length', 0.0)):.6f}",
            zh(r"\u8eaf\u5e72\u94fe\u5411\u91cf\u957f\u5ea6: ") + f"{float(detail.get('skeleton_vector_trunk_length', 0.0)):.6f}",
            zh(r"\u5de6\u4e0b\u80a2\u94fe\u5411\u91cf\u957f\u5ea6: ") + f"{float(detail.get('skeleton_vector_left_leg_length', 0.0)):.6f}",
            zh(r"\u53f3\u4e0b\u80a2\u94fe\u5411\u91cf\u957f\u5ea6: ") + f"{float(detail.get('skeleton_vector_right_leg_length', 0.0)):.6f}",
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

    def _archive_best_video_score(self):
        if not self.video_best_result or self.video_score_archived:
            return self.video_archive_path
        best = self.video_best_result
        return self._archive_video_score(
            best["risk"],
            best["score"],
            best["grade"],
            best["detail"],
            best["metric_scores"],
            best["report_html"],
            frame_index=best["frame_index"],
            video_msec=best["video_msec"],
        )

    def _handle_video_finished(self):
        if self.video_finished:
            return
        self.video_finished = True
        self.video_playing = False
        self.window.update_phase(zh(r"\u89c6\u9891\u68c0\u6d4b\u5b8c\u6210"))
        if self.video_best_result and not self.video_score_archived:
            self._archive_best_video_score()
        if self.video_archive_path:
            done_msg = zh(r"\u89c6\u9891\u68c0\u6d4b\u5b8c\u6210\uff0c\u6700\u9ad8\u8bc4\u5206\u5df2\u5f52\u6863\uff1a")
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
            if self.cap is None or not self.cap.isOpened():
                if self.input_source == "camera":
                    self._notify_camera_issue(zh(r"\u6444\u50cf\u5934\u672a\u6253\u5f00\uff0c\u8bf7\u68c0\u67e5\u6743\u9650\u6216\u91cd\u65b0\u70b9\u51fb\u201c\u6444\u50cf\u5934\u201d\u3002"))
                return
            ret, frame = self.cap.read()
            if not ret or frame is None:
                if self.input_source == "video":
                    self._handle_video_finished()
                elif self.input_source == "camera":
                    self.camera_read_failures += 1
                    if self.camera_read_failures >= 5:
                        self._notify_camera_issue(zh(r"\u6444\u50cf\u5934\u5df2\u6253\u5f00\uff0c\u4f46\u6ca1\u6709\u8fd4\u56de\u753b\u9762\uff0c\u8bf7\u5173\u95ed\u5360\u7528\u6444\u50cf\u5934\u7684\u8f6f\u4ef6\u6216\u68c0\u67e5\u7cfb\u7edf\u6743\u9650\u3002"))
                return
            self.camera_read_failures = 0

            if self.input_source == "camera":
                frame = cv2.flip(frame, 1)
            else:
                self.current_frame_index = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                self.current_video_msec = float(self.cap.get(cv2.CAP_PROP_POS_MSEC))
            h, w, ch = frame.shape
            camera_frame_blank = self.input_source == "camera" and self._is_blank_camera_frame(frame)
            circle_radius = min(w, h) // 2 if self.input_source == "video" else 200
            cv2.circle(frame, (w // 2, h // 2), circle_radius, (200, 200, 200), 1, cv2.LINE_AA)

            if camera_frame_blank:
                self.camera_blank_frames += 1
                if self.camera_blank_frames >= 10:
                    message = zh(r"\u6444\u50cf\u5934\u753b\u9762\u8fc7\u6697\u6216\u88ab\u906e\u6321\uff0c\u8bf7\u6253\u5f00\u9690\u79c1\u5f00\u5173/\u955c\u5934\u76d6\uff0c\u5e76\u68c0\u67e5 Windows \u76f8\u673a\u6743\u9650\u3002")
                    frame = draw_chinese_text(frame, message, (max(20, w // 2 - 310), 60), self.tip_font, color=(245, 158, 11))
                    self._render_frame(frame, w, h, ch)
                    self._notify_camera_issue(message)
                    return
            else:
                self.camera_blank_frames = 0

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
