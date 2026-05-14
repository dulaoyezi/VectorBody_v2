# -*- coding: utf-8 -*-
"""
Asynchronous speech playback wrapper for VectorBody.

Windows SAPI is used instead of pyttsx3 because pyttsx3 can leave its driver
run loop open after repeated start/reset cycles.
"""

import queue
import re
import threading
import time

import pythoncom
import win32com.client


class VectorBodyAudio:
    def __init__(self):
        self.rate = 0
        self._queue = queue.Queue(maxsize=12)
        self._lock = threading.Lock()
        self._worker_lock = threading.Lock()
        self._generation = 0
        self._worker = None
        self._start_worker()

    def speak(self, text, clear=False):
        segments = self._split_text(str(text)) if text else []
        if not segments:
            return
        self._start_worker()

        if clear:
            generation = self.reset()
        else:
            generation = self._generation

        for segment in segments:
            try:
                self._queue.put_nowait((generation, segment))
            except queue.Full:
                break

    def clear(self):
        self.reset()

    def reset(self):
        with self._lock:
            self._generation += 1
            generation = self._generation
        self._drain_queue()
        self._start_worker()
        return generation

    def _start_worker(self):
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._speech_worker, daemon=True)
            self._worker.start()

    def _drain_queue(self):
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

    def _split_text(self, text):
        text = re.sub(r"\s+", "", text.strip())
        if not text:
            return []
        pieces = [p for p in re.split(r"(?<=[\u3002\uff01\uff1f\uff1b])", text) if p]
        segments = []
        for piece in pieces:
            if len(piece) <= 32:
                segments.append(piece)
                continue
            for idx in range(0, len(piece), 28):
                segments.append(piece[idx : idx + 28])
        return segments

    def _speech_worker(self):
        pythoncom.CoInitialize()
        speaker = None
        try:
            while True:
                generation, text = self._queue.get()
                if generation != self._generation:
                    continue
                try:
                    if speaker is None:
                        speaker = self._create_speaker()
                    speaker.Speak(text)
                except Exception as exc:
                    print(f"Speech playback failed, recreating speaker: {exc}")
                    speaker = None
                    time.sleep(0.2)
        finally:
            pythoncom.CoUninitialize()

    def _create_speaker(self):
        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        speaker.Rate = self.rate
        preferred_tokens = (
            "chinese",
            "mandarin",
            "huihui",
            "kangkang",
            "hanhan",
            "xiaoxiao",
            "xiaoyi",
            "zh-cn",
        )
        try:
            for voice in speaker.GetVoices():
                desc = voice.GetDescription().lower()
                if any(token in desc for token in preferred_tokens):
                    speaker.Voice = voice
                    break
        except Exception:
            pass
        return speaker
