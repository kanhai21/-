from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QRadioButton, QButtonGroup,
    QMessageBox, QAbstractItemView, QMenu, QFrame
)
from PyQt6.QtCore import Qt


class SplitPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._is_loading = False  # 防止刷新表格时触发编辑信号
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)  # 全局垂直间距
        layout.setContentsMargins(15, 15, 15, 15)

        # ==================== 顶部工具栏 (双行布局) ====================

        # --- 第一行：模式选择 ---
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(15)

        lbl_mode = QLabel("分镜模式:")
        lbl_mode.setStyleSheet("font-weight: bold; font-size: 14px; color: #ccc;")
        row1_layout.addWidget(lbl_mode)

        self.grp_mode = QButtonGroup(self)
        self.rb_count = QRadioButton("规则分镜 (按条数/标点)")
        self.rb_ai = QRadioButton("AI 语义分镜 (智能分析 + 条数限制)")
        self.rb_count.setChecked(True)  # 默认选中

        self.grp_mode.addButton(self.rb_count)
        self.grp_mode.addButton(self.rb_ai)

        # 优化单选框样式
        rb_style = "QRadioButton { font-size: 13px; color: #e0e0e0; padding: 5px; }"
        self.rb_count.setStyleSheet(rb_style)
        self.rb_ai.setStyleSheet(rb_style)

        row1_layout.addWidget(self.rb_count)
        row1_layout.addWidget(self.rb_ai)
        row1_layout.addStretch()

        layout.addLayout(row1_layout)

        # --- 第二行：阶梯式参数与操作 ---
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(10)

        # 阶梯式参数部分
        lbl_threshold = QLabel("前")
        lbl_threshold.setStyleSheet("color: #ccc;")
        self.spin_threshold = QSpinBox()
        self.spin_threshold.setRange(1, 1000)
        self.spin_threshold.setValue(30)
        self.spin_threshold.setMinimumWidth(70)

        lbl_early1 = QLabel("镜合并:")
        lbl_early1.setStyleSheet("color: #ccc;")

        self.spin_early_min = QSpinBox()
        self.spin_early_min.setRange(1, 50)
        self.spin_early_min.setValue(2)
        self.spin_early_min.setMinimumWidth(60)

        lbl_early2 = QLabel("-")
        lbl_early2.setStyleSheet("color: #ccc;")

        self.spin_early_max = QSpinBox()
        self.spin_early_max.setRange(1, 50)
        self.spin_early_max.setValue(3)
        self.spin_early_max.setMinimumWidth(60)

        lbl_late1 = QLabel("条；之后合并:")
        lbl_late1.setStyleSheet("color: #ccc;")

        self.spin_late_min = QSpinBox()
        self.spin_late_min.setRange(1, 50)
        self.spin_late_min.setValue(5)
        self.spin_late_min.setMinimumWidth(60)

        lbl_late2 = QLabel("-")
        lbl_late2.setStyleSheet("color: #ccc;")

        self.spin_late_max = QSpinBox()
        self.spin_late_max.setRange(1, 50)
        self.spin_late_max.setValue(8)
        self.spin_late_max.setMinimumWidth(60)

        lbl_late_end = QLabel("条")
        lbl_late_end.setStyleSheet("color: #ccc;")

        # 将组件按顺序添加到布局
        widgets_to_add = [
            lbl_threshold, self.spin_threshold,
            lbl_early1, self.spin_early_min, lbl_early2, self.spin_early_max,
            lbl_late1, self.spin_late_min, lbl_late2, self.spin_late_max,
            lbl_late_end
        ]

        for w in widgets_to_add:
            row2_layout.addWidget(w)
            if isinstance(w, QSpinBox):
                w.setToolTip("动态随机调整前后期分镜节奏，增强完播率")

        row2_layout.addStretch()

        # 重置按钮
        self.btn_reset = QPushButton("🔄 重置还原")
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset.clicked.connect(self.main_window.reset_split)
        self.btn_reset.setStyleSheet("""
            QPushButton { 
                background-color: #5c2b29; 
                color: #ff8a80; 
                font-weight: bold; 
                font-size: 13px;
                padding: 8px 15px; 
                border-radius: 4px; 
                border: 1px solid #ff5252;
            }
            QPushButton:hover { background-color: #d32f2f; color: white; }
        """)
        row2_layout.addWidget(self.btn_reset)

        # 开始按钮
        self.btn_split = QPushButton("⚡ 开始智能分镜")
        self.btn_split.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_split.clicked.connect(self.on_btn_split_click)
        self.btn_split.setStyleSheet("""
            QPushButton { 
                background-color: #1a73e8; 
                color: white; 
                font-weight: bold; 
                font-size: 14px;
                padding: 8px 25px; 
                border-radius: 4px; 
                border: 1px solid #1557b0;
                min-width: 120px;
            }
            QPushButton:hover { background-color: #1557b0; }
            QPushButton:pressed { background-color: #0d47a1; }
        """)
        row2_layout.addWidget(self.btn_split)

        layout.addLayout(row2_layout)

        # --- 分隔线 ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setStyleSheet("background-color: #333; max-height: 1px; margin: 10px 0;")
        layout.addWidget(sep)

        # ==================== 分镜结果表格 ====================
        self.tb_sb = QTableWidget()
        self.tb_sb.setColumnCount(4)
        self.tb_sb.setHorizontalHeaderLabels(["镜头ID", "预估时长(s)", "分镜文案内容 (可编辑)", "关联字幕ID"])

        # 表格列宽设置
        header = self.tb_sb.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.tb_sb.setColumnWidth(0, 70)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tb_sb.setColumnWidth(1, 90)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.tb_sb.setColumnWidth(3, 100)

        # 表格行为设置
        self.tb_sb.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tb_sb.setAlternatingRowColors(True)
        self.tb_sb.verticalHeader().setVisible(False)
        self.tb_sb.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                gridline-color: #333;
                selection-background-color: #264f78;
                border: 1px solid #444;
            }
            QTableWidget::item { padding: 6px; }
        """)

        self.tb_sb.itemChanged.connect(self.on_item_changed)
        self.tb_sb.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tb_sb.customContextMenuRequested.connect(self.show_context_menu)

        layout.addWidget(self.tb_sb)

    # ========== 核心修复：页面显示时自动刷新数据 ==========
    def showEvent(self, event):
        """当页面可见时，自动从数据中刷新表格"""
        super().showEvent(event)
        self.refresh_subtitle_table()

    # ===================================================

    def on_btn_split_click(self):
        # 传递阶梯式随机范围参数到核心调度逻辑
        self.main_window.run_split(
            threshold=self.spin_threshold.value(),
            early_min=self.spin_early_min.value(),
            early_max=self.spin_early_max.value(),
            late_min=self.spin_late_min.value(),
            late_max=self.spin_late_max.value()
        )

    def refresh_subtitle_table(self):
        """刷新表格显示（从项目数据加载）"""
        self._is_loading = True
        self.tb_sb.setRowCount(0)

        scenes = self.main_window.data.get('scenes', [])
        self.tb_sb.setRowCount(len(scenes))

        for i, s in enumerate(scenes):
            # 1. ID
            item_id = QTableWidgetItem(str(s['index']))
            item_id.setFlags(item_id.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_id.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tb_sb.setItem(i, 0, item_id)

            # 2. 时长
            item_dur = QTableWidgetItem(str(s['duration']))
            item_dur.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tb_sb.setItem(i, 1, item_dur)

            # 3. 文案
            item_text = QTableWidgetItem(s['text'])
            item_text.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.tb_sb.setItem(i, 2, item_text)

            # 4. 关联ID
            sub_ids = ",".join(map(str, s.get('sub_ids', [])))
            item_sub = QTableWidgetItem(sub_ids)
            item_sub.setFlags(item_sub.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_sub.setForeground(Qt.GlobalColor.gray)
            self.tb_sb.setItem(i, 3, item_sub)

            # 动态行高
            line_count = s['text'].count('\n') + 1
            row_height = max(60, line_count * 20 + 20)
            self.tb_sb.setRowHeight(i, row_height)

        self._is_loading = False

    def on_item_changed(self, item):
        if self._is_loading: return
        row = item.row()
        col = item.column()
        scenes = self.main_window.data.get('scenes', [])
        if row < 0 or row >= len(scenes): return

        new_val = item.text().strip()
        if col == 1:  # 时长
            try:
                scenes[row]['duration'] = float(new_val)
            except ValueError:
                self._is_loading = True
                item.setText(str(scenes[row]['duration']))
                self._is_loading = False
        elif col == 2:  # 文案
            scenes[row]['text'] = new_val

        self.main_window.mark_modified()

    def show_context_menu(self, pos):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu { background-color: #2d2d2d; color: white; border: 1px solid #555; }
            QMenu::item { padding: 8px 20px; }
            QMenu::item:selected { background-color: #1a73e8; }
        """)
        act_merge = menu.addAction("🔗 合并选中镜头 (Merge)")
        act_split = menu.addAction("✂️ 拆分当前镜头 (Split)")

        action = menu.exec(self.tb_sb.viewport().mapToGlobal(pos))
        if action == act_merge:
            self.main_window.merge_selected_subtitles()
        elif action == act_split:
            row = self.tb_sb.currentRow()
            if row >= 0:
                self.main_window.split_selected_subtitle(row)