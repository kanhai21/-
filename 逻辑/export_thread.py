from PyQt6.QtCore import QThread, pyqtSignal
import traceback


class ExportThread(QThread):
    finished_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    # 🌟 新增：专门用于后台批量导出的完成通信信号
    batch_finished_signal = pyqtSignal()

    def __init__(self, exporter, audio_path, images, subtitles=None,
                 bgm_path=None, bgm_volume=0.2, subtitle_effect_id=""):
        super().__init__()
        self.exporter = exporter
        self.audio_path = audio_path
        self.images = images
        self.subtitles = subtitles
        self.bgm_path = bgm_path
        self.bgm_volume = bgm_volume
        self.subtitle_effect_id = subtitle_effect_id

    def run(self):
        try:
            p = self.exporter.generate_draft(
                self.audio_path,
                self.images,
                subtitles=self.subtitles,
                bgm_path=self.bgm_path,
                bgm_volume=self.bgm_volume,
                subtitle_effect_id=self.subtitle_effect_id
            )
            # 正常单项导出完成
            self.finished_signal.emit(p)

            # 🌟 新增：触发批量流转信号，通知主程序处理下一个
            self.batch_finished_signal.emit()

        except Exception as e:
            # 打印详细堆栈到控制台以便调试
            traceback.print_exc()

            # 如果发生错误，触发 error_signal (后台管理器监听到 error 后也会自动跳转到下一个)
            self.error_signal.emit(str(e))