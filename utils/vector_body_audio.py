# -*- coding: utf-8 -*-
"""
==========================================================================
项目名称：VectorBody 智能体态检测系统
文件名称：vector_body_audio.py
功能描述：
    #异步语音播报设计，防止卡死
开发者：杜文鑫
编写日期：2026年03月26日
==========================================================================
"""

import pyttsx3
import threading
import pythoncom
# 定义一个专门负责语音播报的类，封装 pyttsx3 的功能
class VectorBodyAudio:
    def __init__(self):
        self.rate = 160

    def speak(self, text):
        t = threading.Thread(target=self._run_speech, args=(text,))
        t.daemon = True; t.start()

    def _run_speech(self, text):
        pythoncom.CoInitialize() # 线程内必须初始化
        try:
            engine = pyttsx3.init()
            engine.setProperty('rate', self.rate)
            voices = engine.getProperty('voices')
            for v in voices:
                if "ZH" in v.id or "Chinese" in v.name:
                    engine.setProperty('voice', v.id); break
            engine.say(text); engine.runAndWait(); engine.stop()
        finally:
            pythoncom.CoUninitialize()