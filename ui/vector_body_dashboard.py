# -*- coding: utf-8 -*-
import datetime
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


def zh(text):
    return text.encode("ascii").decode("unicode_escape")


def get_resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


class VectorBodyDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(zh(r"VectorBody \u667a\u80fd\u745c\u4f3d\u4f53\u6001\u68c0\u6d4b\u7cfb\u7edf"))
        self.resize(1400, 950)
        self.setStyleSheet("QMainWindow { background-color: #0F172A; }")
        self.view_mode = "front_muscle"
        self._last_report_html = ""
        self.setup_ui()

    def _safe_font(self, family="Microsoft YaHei UI", point_size=11, bold=False):
        font = QFont(family)
        font.setPointSize(max(1, int(point_size)))
        font.setBold(bold)
        return font

    def setup_ui(self):
        self.central = QWidget()
        self.setCentralWidget(self.central)
        self.setFont(self._safe_font())
        self.main_lay = QVBoxLayout(self.central)
        self.main_lay.setContentsMargins(20, 20, 20, 20)

        input_layout = QHBoxLayout()
        self.patient_name = QLineEdit()
        self.patient_name.setPlaceholderText(zh(r"\u8f93\u5165\u7ec3\u4e60\u8005\u59d3\u540d\u540e\u5efa\u7acb\u8bad\u7ec3\u6863\u6848..."))
        self.patient_name.setStyleSheet(
            "height: 40px; background: #1E293B; color: white; "
            "padding-left: 10px; border-radius: 5px; font-size: 15px;"
        )

        self.btn_save = QPushButton(zh(r"\u4fdd\u5b58\u8bad\u7ec3\u62a5\u544a"))
        self.btn_save.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: bold; "
            "min-width: 200px; height: 40px; border-radius: 5px;"
        )
        input_layout.addWidget(self.patient_name, stretch=8)
        input_layout.addWidget(self.btn_save, stretch=2)
        self.main_lay.addLayout(input_layout)

        mode_layout = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(zh(r"\u57fa\u7840\u4f53\u6001\u8bc4\u4f30"), "posture")
        self.mode_combo.addItem(zh(r"\u5b66\u4e60\u6218\u58eb\u4e00\u5f0f"), "warrior1")
        self.mode_combo.addItem(zh(r"\u5b66\u4e60\u6218\u58eb\u4e8c\u5f0f"), "warrior2")
        self.mode_combo.addItem(zh(r"\u5b66\u4e60\u80a9\u5012\u7acb"), "shoulderstand")
        self.mode_combo.setStyleSheet(
            "height: 38px; background: #1E293B; color: white; "
            "padding-left: 10px; border-radius: 5px; font-size: 15px;"
        )

        self.view_combo = QComboBox()
        self.view_combo.addItem(zh(r"\u6b63\u4f4d"), "front")
        self.view_combo.addItem(zh(r"\u4fa7\u4f4d"), "side")
        self.view_combo.setStyleSheet(
            "height: 38px; background: #1E293B; color: white; "
            "padding-left: 10px; border-radius: 5px; font-size: 15px;"
        )

        self.level_combo = QComboBox()
        self.level_combo.addItem(zh(r"\u7b49\u7ea7\uff1a\u666e\u901a"), "normal")
        self.level_combo.addItem(zh(r"\u7b49\u7ea7\uff1a\u65b0\u624b"), "beginner")
        self.level_combo.setStyleSheet(
            "height: 38px; background: #1E293B; color: white; "
            "padding-left: 10px; border-radius: 5px; font-size: 15px;"
        )

        self.btn_start_training = QPushButton(zh(r"\u5f00\u59cb"))
        self.btn_reset_phase = QPushButton(zh(r"\u91cd\u7f6e"))
        self.btn_open_video = QPushButton(zh(r"\u5bfc\u5165\u89c6\u9891"))
        self.btn_camera = QPushButton(zh(r"\u6444\u50cf\u5934"))
        for button in (self.btn_start_training, self.btn_reset_phase):
            button.setStyleSheet(
                "background-color: #2563EB; color: white; font-weight: bold; "
                "min-width: 96px; height: 38px; border-radius: 5px;"
            )
        self.btn_open_video.setStyleSheet(
            "background-color: #F59E0B; color: #111827; font-weight: bold; "
            "min-width: 96px; height: 38px; border-radius: 5px;"
        )
        self.btn_camera.setStyleSheet(
            "background-color: #14B8A6; color: #042F2E; font-weight: bold; "
            "min-width: 96px; height: 38px; border-radius: 5px;"
        )
        self.phase_label = QLabel(zh(r"\u9636\u6bb5: \u5f85\u5f00\u59cb"))
        self.phase_label.setFont(self._safe_font(point_size=12, bold=True))
        self.phase_label.setStyleSheet("font-size: 16px; color: #FBBF24; font-weight: bold;")
        self.source_label = QLabel(zh(r"\u6765\u6e90\uff1a\u6444\u50cf\u5934"))
        self.source_label.setFont(self._safe_font(point_size=10, bold=True))
        self.source_label.setStyleSheet("font-size: 14px; color: #CBD5E1;")

        mode_layout.addWidget(self.mode_combo, stretch=4)
        mode_layout.addWidget(self.view_combo, stretch=2)
        mode_layout.addWidget(self.level_combo, stretch=2)
        mode_layout.addWidget(self.btn_start_training, stretch=1)
        mode_layout.addWidget(self.btn_reset_phase, stretch=1)
        mode_layout.addWidget(self.btn_open_video, stretch=1)
        mode_layout.addWidget(self.btn_camera, stretch=1)
        mode_layout.addWidget(self.phase_label, stretch=3)
        mode_layout.addWidget(self.source_label, stretch=3)
        self.main_lay.addLayout(mode_layout)
        self.mode_combo.currentIndexChanged.connect(self.update_view_selector_state)
        self.update_view_selector_state()

        content = QHBoxLayout()
        self.video_label = QLabel(zh(r"\u6444\u50cf\u5934\u51c6\u5907\u4e2d..."))
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(850, 600)
        self.video_label.setStyleSheet("background: black; border-radius: 10px; border: 2px solid #3B82F6;")
        content.addWidget(self.video_label, stretch=7)

        sidebar = QVBoxLayout()
        btn_lay = QHBoxLayout()
        self.btn_m = QPushButton(zh(r"\u808c\u8089\u56fe"))
        self.btn_s = QPushButton(zh(r"\u9aa8\u9abc\u56fe"))
        btn_lay.addWidget(self.btn_m)
        btn_lay.addWidget(self.btn_s)
        sidebar.addLayout(btn_lay)

        self.anatomy_label = QLabel()
        self.anatomy_label.setFixedSize(350, 450)
        self.anatomy_label.setStyleSheet("background: #1E293B; border-radius: 10px;")
        sidebar.addWidget(self.anatomy_label)

        self.status_badge = QLabel(zh(r"\u72b6\u6001\uff1a\u5f85\u5f00\u59cb"))
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setMinimumHeight(40)
        sidebar.addWidget(self.status_badge)
        self.update_detection_state("idle")

        self.val_sh = QLabel(zh(r"\u52a8\u4f5c\u8bc4\u5206: --"))
        self.val_pl = QLabel(zh(r"\u7075\u6d3b\u5173\u8282\u9501\u5b9a: --"))
        self.val_sc = QLabel(zh(r"\u975e\u7075\u6d3b\u5173\u8282\u4ee3\u507f: --"))
        for label in (self.val_sh, self.val_pl, self.val_sc):
            label.setStyleSheet("font-size: 20px; color: #60A5FA; font-weight: bold; margin: 10px 0;")
            sidebar.addWidget(label)

        sidebar.addStretch()
        content.addLayout(sidebar, stretch=3)
        self.main_lay.addLayout(content)

        self.report_area = QTextBrowser()
        self.report_area.setFont(self._safe_font(point_size=10))
        self.report_area.setStyleSheet(
            "background: #020617; color: #E2E8F0; padding: 15px; "
            "border: 1px solid #3B82F6; border-radius: 10px;"
        )
        self.report_area.setMaximumHeight(180)
        self.main_lay.addWidget(self.report_area)

    def selected_mode(self):
        pose = self.mode_combo.currentData()
        if pose == "posture":
            return "posture"
        return f"{pose}_{self.view_combo.currentData()}"

    def selected_level(self):
        return self.level_combo.currentData()

    def update_view_selector_state(self):
        is_yoga_mode = self.mode_combo.currentData() != "posture"
        self.view_combo.setEnabled(is_yoga_mode)
        self.level_combo.setEnabled(is_yoga_mode)

    def update_phase(self, text):
        self.phase_label.setText(zh(r"\u9636\u6bb5: ") + text)

    def update_source_state(self, text, tooltip=None):
        display_text = text
        if len(display_text) > 24:
            display_text = display_text[:21] + "..."
        self.source_label.setText(zh(r"\u6765\u6e90\uff1a") + display_text)
        self.source_label.setToolTip(tooltip or text)

    def update_detection_state(self, state):
        config = {
            "idle": (zh(r"\u72b6\u6001\uff1a\u5f85\u5f00\u59cb"), "#334155", "#CBD5E1"),
            "prepare": (zh(r"\u72b6\u6001\uff1a\u51c6\u5907\u4e2d"), "#F59E0B", "#111827"),
            "hold": (zh(r"\u72b6\u6001\uff1a\u68c0\u6d4b\u4e2d"), "#10B981", "#052E1A"),
        }
        text, bg_color, fg_color = config.get(state, config["idle"])
        self.status_badge.setText(text)
        self.status_badge.setStyleSheet(
            f"background-color: {bg_color}; color: {fg_color}; "
            "font-size: 18px; font-weight: bold; border-radius: 8px; padding: 8px;"
        )

    def update_yoga_metrics(self, score=None, grade=None, detail=None):
        if score is None or grade is None or not detail:
            self.val_sh.setText(zh(r"\u52a8\u4f5c\u8bc4\u5206: --"))
            self.val_pl.setText(zh(r"\u7075\u6d3b\u5173\u8282\u9501\u5b9a: --"))
            self.val_sc.setText(zh(r"\u975e\u7075\u6d3b\u5173\u8282\u4ee3\u507f: --"))
            return
        if detail.get("gate_state"):
            self.val_sh.setText(zh(r"\u9636\u6bb5: ") + str(grade))
            self.val_pl.setText(zh(r"\u5012\u7f6e\u95e8\u63a7\uff1a\u672a\u901a\u8fc7"))
            self.val_sc.setText(zh(r"\u52a8\u4f5c\u8bc4\u5206: --"))
            return
        self.val_sh.setText(zh(r"\u52a8\u4f5c\u8bc4\u5206: ") + f"{score:.0f} / 100 ({grade})")
        self.val_pl.setText(zh(r"\u7075\u6d3b\u5173\u8282\u9501\u5b9a: ") + f"{detail.get('risk_mobile_lock', 0.0) * 100:.0f}%")
        self.val_sc.setText(zh(r"\u975e\u7075\u6d3b\u5173\u8282\u4ee3\u507f: ") + f"{detail.get('risk_stiff_comp', 0.0) * 100:.0f}%")

    def update_report_html(self, html, force=False):
        scroll_bar = self.report_area.verticalScrollBar()
        at_bottom = scroll_bar.value() >= max(0, scroll_bar.maximum() - 4)
        if not force and not at_bottom:
            return
        if not force and html == self._last_report_html:
            return

        self.report_area.setHtml(html)
        self._last_report_html = html
        if at_bottom or force:
            self.report_area.verticalScrollBar().setValue(self.report_area.verticalScrollBar().maximum())

    def update_frame(self, pixmap):
        self.video_label.setPixmap(
            pixmap.scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def save_and_reset(self):
        name = self.patient_name.text().strip() if self.patient_name.text() else zh(r"\u533f\u540d\u7ec3\u4e60\u8005")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = os.path.join(os.getcwd(), "reports")
        os.makedirs(report_dir, exist_ok=True)
        file_path = os.path.join(report_dir, f"{name}_{timestamp}.txt")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(zh(r"VectorBody \u745c\u4f3d\u8bad\u7ec3\u62a5\u544a - ") + f"{name}\n")
                f.write(zh(r"\u65f6\u95f4: ") + f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("-" * 40 + "\n")
                f.write(self.report_area.toPlainText())
            QMessageBox.information(self, zh(r"\u6210\u529f"), zh(r"\u62a5\u544a\u5df2\u5b58\u81f3: ") + file_path)
            self.patient_name.clear()
            self.update_report_html("<p style='color: #94A3B8;'>Ready.</p>", force=True)
            self.update_yoga_metrics()
        except Exception as e:
            QMessageBox.critical(self, zh(r"\u9519\u8bef"), zh(r"\u4fdd\u5b58\u5931\u8d25: ") + str(e))

    def update_anatomy(self, status):
        img_rel_path = os.path.join("assets", f"{self.view_mode}.png")
        path = get_resource_path(img_rel_path)
        if not os.path.exists(path):
            print(f"Missing image resource: {path}")
            return

        pix = QPixmap(path).scaled(self.anatomy_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        coords = {
            "neck": (0.5, 0.18),
            "shoulder_l": (0.35, 0.25),
            "shoulder_r": (0.65, 0.25),
            "pelvis": (0.5, 0.65),
            "spine": (0.5, 0.45),
        }
        for part, state in status.items():
            if state == "issue" and part in coords:
                x, y = coords[part]
                if "back" in self.view_mode:
                    x = 1.0 - x
                painter.setBrush(QColor(239, 68, 68, 180))
                painter.drawEllipse(int(x * pix.width()) - 10, int(y * pix.height()) - 10, 20, 20)
        painter.end()
        self.anatomy_label.setPixmap(pix)

