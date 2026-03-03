import sys
import os
import shutil
import subprocess
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QListWidget, QFileDialog, QMessageBox,
                             QAbstractItemView, QProgressBar, QApplication)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl


# --- 工作线程：在后台运行 FFmpeg，防止界面卡死 ---
class MergeWorker(QThread):
    finished_signal = pyqtSignal(str)  # 成功信号，传回保存路径
    error_signal = pyqtSignal(str)  # 失败信号，传回错误信息

    def __init__(self, ffmpeg_path, file_paths, save_path):
        super().__init__()
        self.ffmpeg_path = ffmpeg_path
        self.file_paths = file_paths
        self.save_path = save_path

    def run(self):
        temp_list_path = "temp_file_list.txt"
        try:
            # 1. 生成文件列表
            with open(temp_list_path, "w", encoding="utf-8") as f:
                for path in self.file_paths:
                    # FFmpeg concat 协议要求：Windows路径的反斜杠需转义，或者用正斜杠
                    safe_path = path.replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")

            # 2. 构建命令 (使用 filter_complex 进行流式拼接，兼容性最强)
            inputs = []
            filter_str = ""
            for i in range(len(self.file_paths)):
                inputs.extend(["-i", self.file_paths[i]])
                filter_str += f"[{i}:a]"

            filter_str += f"concat=n={len(self.file_paths)}:v=0:a=1[outa]"

            cmd = [self.ffmpeg_path] + inputs + ["-filter_complex", filter_str, "-map", "[outa]", "-y", self.save_path]

            # 3. 执行命令 (隐藏黑窗口)
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            subprocess.run(cmd, check=True, startupinfo=startupinfo, stderr=subprocess.PIPE)

            self.finished_signal.emit(self.save_path)

        except subprocess.CalledProcessError as e:
            # 捕获 FFmpeg 的错误输出
            err_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            self.error_signal.emit(f"FFmpeg 执行错误: {err_msg}")
        except Exception as e:
            self.error_signal.emit(f"发生未知错误: {str(e)}")
        finally:
            # 清理临时文件
            if os.path.exists(temp_list_path):
                try:
                    os.remove(temp_list_path)
                except:
                    pass


# --- 自定义列表控件：支持拖拽 ---
class DraggableListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)  # 开启拖拽接收
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # 优化：适配深色主题
        self.setStyleSheet("""
            QListWidget {
                border: 2px dashed #555;
                border-radius: 5px;
                background-color: #252526;
                color: #ffffff;
                font-size: 14px;
                outline: none;
            }
            QListWidget::item { padding: 8px; border-bottom: 1px solid #333; }
            QListWidget::item:hover { background-color: #2a2d2e; }
            QListWidget::item:selected { background-color: #37373d; border-left: 3px solid #1a73e8; }
        """)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            files = [u.toLocalFile() for u in event.mimeData().urls()]
            # 过滤音频文件
            valid_exts = ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg')
            for f in files:
                if f.lower().endswith(valid_exts):
                    self.addItem(f)  # 添加完整路径
            event.accept()
        else:
            event.ignore()


# --- 主功能模块 ---
class AudioMergerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ffmpeg_path = self.find_ffmpeg()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 1. 标题与状态
        header_layout = QHBoxLayout()
        title = QLabel("🎵 音频合并模块")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #4fc3f7;")
        header_layout.addWidget(title)

        self.status_label = QLabel()
        if self.ffmpeg_path:
            self.status_label.setText("✅ 组件就绪")
            self.status_label.setStyleSheet("color: #55ff55; font-weight: bold;") # 适配深色的亮绿
        else:
            self.status_label.setText("❌ 缺少 ffmpeg.exe")
            self.status_label.setStyleSheet("color: #ff5555; font-weight: bold;") # 适配深色的亮红
        header_layout.addWidget(self.status_label)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # 2. 拖拽列表区
        lbl_hint = QLabel("请将音频文件拖拽至下方 (支持 mp3, wav, m4a...)：")
        lbl_hint.setStyleSheet("color: #ccc;")
        layout.addWidget(lbl_hint)
        self.list_widget = DraggableListWidget()
        layout.addWidget(self.list_widget)

        # 3. 操作按钮区
        btn_layout = QHBoxLayout()

        self.btn_add = QPushButton("➕ 添加文件")
        self.btn_up = QPushButton("⬆️ 上移")
        self.btn_down = QPushButton("⬇️ 下移")
        self.btn_clear = QPushButton("🗑️ 清空")

        for btn in [self.btn_add, self.btn_up, self.btn_down, self.btn_clear]:
            btn.setStyleSheet("""
                QPushButton { background-color: #333; color: white; border: 1px solid #555; padding: 6px; border-radius: 4px; }
                QPushButton:hover { background-color: #444; border-color: #1a73e8; }
            """)

        self.btn_add.clicked.connect(self.add_files)
        self.btn_up.clicked.connect(self.move_item_up)
        self.btn_down.clicked.connect(self.move_item_down)
        self.btn_clear.clicked.connect(self.list_widget.clear)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_up)
        btn_layout.addWidget(self.btn_down)
        btn_layout.addWidget(self.btn_clear)
        layout.addLayout(btn_layout)

        # 4. 底部合并按钮
        self.btn_merge = QPushButton("🚀 开始合并导出")
        self.btn_merge.setFixedHeight(40)
        self.btn_merge.setStyleSheet("""
            QPushButton { background-color: #1565c0; color: white; font-weight: bold; font-size: 14px; border-radius: 6px; }
            QPushButton:hover { background-color: #1976d2; }
            QPushButton:disabled { background-color: #333; color: #777; }
        """)
        self.btn_merge.clicked.connect(self.start_merge)
        layout.addWidget(self.btn_merge)

        # 禁用按钮如果没找到环境
        if not self.ffmpeg_path:
            self.btn_merge.setEnabled(False)
            self.btn_merge.setText("无法运行 (根目录缺少 ffmpeg.exe)")
            self.list_widget.setEnabled(False)

    def find_ffmpeg(self):
        """查找 ffmpeg，逻辑同之前一样，支持开发环境和打包环境"""
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        # 1. 检查当前目录
        local = os.path.join(base_path, "ffmpeg.exe")
        if os.path.exists(local): return local

        # 2. 检查 bin 目录
        bin_p = os.path.join(base_path, "bin", "ffmpeg.exe")
        if os.path.exists(bin_p): return bin_p

        # 3. 检查环境变量
        sys_p = shutil.which("ffmpeg")
        if sys_p: return sys_p

        return None

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择音频", "", "音频文件 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)"
        )
        if files:
            self.list_widget.addItems(files)

    def move_item_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row - 1, item)
            self.list_widget.setCurrentRow(row - 1)

    def move_item_down(self):
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row + 1, item)
            self.list_widget.setCurrentRow(row + 1)

    def start_merge(self):
        count = self.list_widget.count()
        if count < 2:
            QMessageBox.warning(self, "提示", "请至少添加 2 个音频文件！")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存合并后的音频", "merged_audio.mp3", "MP3 音频 (*.mp3);;WAV 音频 (*.wav)"
        )

        if not save_path:
            return

        # 收集路径
        file_paths = [self.list_widget.item(i).text() for i in range(count)]

        # 界面锁定，防止重复操作
        self.btn_merge.setEnabled(False)
        self.btn_merge.setText("正在合并中...")

        # 启动线程
        self.worker = MergeWorker(self.ffmpeg_path, file_paths, save_path)
        self.worker.finished_signal.connect(self.on_merge_success)
        self.worker.error_signal.connect(self.on_merge_error)
        self.worker.start()

    def on_merge_success(self, path):
        self.btn_merge.setEnabled(True)
        self.btn_merge.setText("🚀 开始合并导出")
        QMessageBox.information(self, "成功", f"合并完成！\n文件已保存至：\n{path}")

    def on_merge_error(self, error_msg):
        self.btn_merge.setEnabled(True)
        self.btn_merge.setText("🚀 开始合并导出")
        QMessageBox.critical(self, "失败", error_msg)


# --- 测试代码：如果你直接运行这个文件，会弹出一个窗口让你测试 ---
if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 创建窗口来承载这个模块
    window = QWidget()
    window.setWindowTitle("测试音频合并模块")
    window.resize(600, 500)
    window.setStyleSheet("background-color: #1e1e1e; color: white;") # 测试时添加全局深色背景
    layout = QVBoxLayout(window)

    # 实例化我们的模块
    merger_widget = AudioMergerWidget()
    layout.addWidget(merger_widget)

    window.show()
    sys.exit(app.exec())