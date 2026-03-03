import sys
import os
import re
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QListWidget, QFileDialog, QMessageBox,
                             QAbstractItemView, QDoubleSpinBox, QApplication)
from PyQt6.QtCore import Qt, QMimeData


# --- 自定义列表：支持拖拽 .srt 文件 ---
class DraggableListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # 优化：适配深色主题
        self.setStyleSheet("""
            QListWidget {
                border: 2px dashed #555;
                border-radius: 5px;
                background-color: #252526;
                color: #ffffff;
                font-family: Consolas, "Microsoft YaHei";
                font-size: 13px;
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
            for f in files:
                if f.lower().endswith('.srt'):
                    self.addItem(f)
            event.accept()
        else:
            event.ignore()


# --- 字幕合并核心模块 ---
class SubtitleMergerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 1. 标题
        header = QHBoxLayout()
        title = QLabel("📝 SRT 字幕合并模块 (仿剪映逻辑)")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #4fc3f7;")
        header.addWidget(title)
        layout.addLayout(header)

        # 2. 拖拽提示与列表
        lbl_hint = QLabel("请将 SRT 文件拖入下方列表 (按顺序合并)：")
        lbl_hint.setStyleSheet("color: #ccc;")
        layout.addWidget(lbl_hint)

        self.list_widget = DraggableListWidget()
        layout.addWidget(self.list_widget)

        # 3. 功能按钮区
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

        # 4. 设置与导出区
        bottom_layout = QHBoxLayout()

        lbl_gap = QLabel("两段间隔(秒):")
        lbl_gap.setStyleSheet("color: #ddd;")
        bottom_layout.addWidget(lbl_gap)

        self.spin_gap = QDoubleSpinBox()
        self.spin_gap.setRange(0.0, 60.0)
        self.spin_gap.setValue(1.0)  # 默认间隔1秒
        self.spin_gap.setSingleStep(0.5)
        self.spin_gap.setStyleSheet("""
            QDoubleSpinBox { background-color: #1e1e1e; color: white; border: 1px solid #555; padding: 4px; border-radius: 4px; }
            QDoubleSpinBox:focus { border-color: #1a73e8; }
        """)
        bottom_layout.addWidget(self.spin_gap)

        bottom_layout.addStretch()

        self.btn_merge = QPushButton("🚀 开始合并并导出")
        self.btn_merge.setFixedHeight(38)
        self.btn_merge.setStyleSheet("""
            QPushButton { background-color: #1565c0; color: white; font-weight: bold; padding: 0 20px; border-radius: 6px; font-size: 14px;}
            QPushButton:hover { background-color: #1976d2; }
        """)
        self.btn_merge.clicked.connect(self.start_merge)
        bottom_layout.addWidget(self.btn_merge)

        layout.addLayout(bottom_layout)

    # --- 逻辑功能函数 ---
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择字幕", "", "SRT 字幕 (*.srt)")
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

    # --- 核心算法区 (保留了解决兼容性的关键代码) ---
    def parse_time(self, time_str):
        """解析时间字符串 -> 毫秒"""
        time_str = time_str.replace('.', ',')
        try:
            h, m, s = time_str.split(':')
            seconds, millis = s.split(',')
            return (int(h) * 3600000) + (int(m) * 60000) + (int(seconds) * 1000) + int(millis)
        except:
            return 0

    def format_time(self, total_ms):
        """毫秒 -> SRT时间格式"""
        h = total_ms // 3600000
        m = (total_ms % 3600000) // 60000
        s = (total_ms % 60000) // 1000
        ms = total_ms % 1000
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    def read_srt_file(self, filepath):
        """读取并解析单个SRT文件 (含编码自动检测)"""
        entries = []
        content = ""
        # 1. 尝试 UTF-8
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # 2. 尝试 GBK (兼容旧软件)
            try:
                with open(filepath, 'r', encoding='gbk') as f:
                    content = f.read()
            except:
                raise Exception(f"无法识别文件编码: {os.path.basename(filepath)}")

        # 正则匹配
        pattern = re.compile(
            r'(\d+)\s*\n(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*\n([\s\S]*?)(?=\n\n|\Z)',
            re.MULTILINE)
        matches = pattern.findall(content)

        for m in matches:
            entries.append({
                'start_ms': self.parse_time(m[1]),
                'end_ms': self.parse_time(m[2]),
                'text': m[3].strip()
            })
        return entries

    def start_merge(self):
        count = self.list_widget.count()
        if count < 2:
            QMessageBox.warning(self, "提示", "请至少添加 2 个 SRT 文件！")
            return

        file_paths = [self.list_widget.item(i).text() for i in range(count)]
        gap_ms = int(self.spin_gap.value() * 1000)

        final_entries = []

        try:
            for idx, filepath in enumerate(file_paths):
                entries = self.read_srt_file(filepath)
                if not entries: continue

                # 计算偏移量 logic
                if idx > 0:
                    last_end = final_entries[-1]['end_ms'] if final_entries else 0
                    current_start = entries[0]['start_ms']
                    # 偏移量 = (上一段结束 + 间隔) - 当前段开始
                    offset = (last_end + gap_ms) - current_start
                else:
                    offset = 0

                for entry in entries:
                    new_start = max(0, entry['start_ms'] + offset)
                    new_end = max(0, entry['end_ms'] + offset)
                    final_entries.append({
                        'start_ms': new_start,
                        'end_ms': new_end,
                        'text': entry['text']
                    })

            # 导出
            save_path, _ = QFileDialog.getSaveFileName(self, "保存合并字幕", "merged_subtitle.srt", "SRT 字幕 (*.srt)")
            if save_path:
                with open(save_path, 'w', encoding='utf-8') as f:
                    for i, entry in enumerate(final_entries):
                        # 强制重排序号，强制 UTF-8，强制标准空行
                        f.write(f"{i + 1}\n")
                        f.write(f"{self.format_time(entry['start_ms'])} --> {self.format_time(entry['end_ms'])}\n")
                        f.write(f"{entry['text']}\n\n")

                QMessageBox.information(self, "成功", f"字幕合并完成！\n路径：{save_path}")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"处理失败: {str(e)}")


# --- 测试入口 ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("测试字幕模块")
    window.resize(500, 600)
    window.setStyleSheet("background-color: #1e1e1e; color: white;")  # 测试时添加全局深色背景
    layout = QVBoxLayout(window)

    merger = SubtitleMergerWidget()
    layout.addWidget(merger)

    window.show()
    sys.exit(app.exec())