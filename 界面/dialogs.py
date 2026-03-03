import configparser
import os
import json
import re
import math
from enum import Enum

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QTextEdit, QFileDialog, QComboBox, QFormLayout, QDialogButtonBox,
    QSpinBox, QSlider, QCheckBox, QButtonGroup, QGroupBox, QMessageBox,
    QRadioButton, QTabWidget, QWidget, QDoubleSpinBox, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QGridLayout,
    QFrame, QStackedWidget
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QAction, QCursor

from 配置.app_config import (
    CONFIG_FILE, DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_UPSCALE_FACTOR,
    DEFAULT_BGM_VOLUME, DEFAULT_SUBTITLE_EFFECT_ID, DEFAULT_RESOLUTION_MODE,
    # 关键帧默认值
    DEFAULT_KF_ENABLE_SCALE, DEFAULT_KF_ENABLE_PAN_X, DEFAULT_KF_ENABLE_PAN_Y,
    DEFAULT_KF_START_SCALE, DEFAULT_KF_END_SCALE,
    DEFAULT_KF_X_DIR, DEFAULT_KF_Y_DIR, DEFAULT_KF_SCALE_DIR,
    # 新增自定义位移默认值
    DEFAULT_KF_USE_CUSTOM_PAN,
    DEFAULT_KF_START_X,
    DEFAULT_KF_END_X,
    DEFAULT_KF_START_Y,
    DEFAULT_KF_END_Y,
    # 全局导出默认值
    DEFAULT_GLOBAL_BGM_PATH
)
from 逻辑.app_workers import ConnectionTestThread
from 逻辑.keyframe_module import KeyframeSettings

# ==================== 🌟 核心出厂默认提示词模板 (新版电影分镜级 + 防污染绝杀优化) ====================
DEFAULT_PROMPT_TEMPLATE = """你现在是一名电影级分镜导演和 Stable Diffusion 提示词专家。请准确理解分镜内容，明确【画面主体（C位）】和【动作神态】，严格按照【角色设定】推理出具有电影感的绘图提示词。

【已知角色设定】：
{ROLES}

【核心要求】：
1. 确立唯一主体与核心动作：仔细阅读分镜剧情，找出该镜头下的【核心主角（C位）】以及他/她正在做的【具体动作】（如坐着、跑动、拿东西）和【面部表情】。切忌生成所有人呆立排排站的“大合照”！
2. 严格代入人设（保持角色一致性）：如果分镜中出现角色名字或指代词，必须统一替换成【已知角色设定】中对应的详细描述词。绝对禁止篡改角色的头发、服装颜色和款式！
3. 主次分明与背景弱化：如果有多个角色同框，必须明确主次关系（如：焦点在主角身上，其他人在背景中模糊或作为陪衬）。将出现的核心角色全部放入 roles 数组中，且【务必把最核心的主角放在 roles 数组的第 1 位】！
4. 结构化描述：按照（主体人物+主体动作/表情+详细人设+次要人物及互动+环境光影背景）的顺序生成画面。
5. 中英文对照输出：
   - prompt_zh：简练的中文画面描述（必须突出主体和动作）。
   - prompt_en：标准的英文 Stable Diffusion 提示词（起手包含 masterpiece, best quality, cinematic lighting, depth of field）。必须包含主体动作的英文标签（如 eating, frowning, holding ribs）。
6. 必须以纯 JSON 列表返回，必须包含 `index`, `roles` (数组), `genders` (性别数组，填'm'或'f'或'u'), `prompt_zh`, `prompt_en`，不要包含 Markdown 代码块标记！
7. 🛑【防污染绝杀令】：JSON结构中的 `roles` 数组【绝对禁止】填入外貌描述！必须且只能填入角色的原始纯姓名（例如 ["许清远"]，绝不能是 ["一名24岁男性..."]），这是系统底层的识别锚点！

【JSON 输出示例】：
[
  {{
    "index": 1, 
    "roles": ["许清远", "其他高管"], 
    "genders": ["m", "u"],
    "prompt_zh": "一名24岁男性，橙色短发，惊愕皱眉，手里夹着糖醋排骨，聚焦于他，背景是其他人在饭桌旁...",
    "prompt_en": "(masterpiece, best quality, cinematic lighting, depth of field), 1boy, short orange hair, stunned expression, slightly frowning, holding sweet and sour pork ribs, focus on 1boy, blurred background with other people at dining table..."
  }}
]

【待处理剧情列表】：
{SCENES}"""

DEFAULT_ROLE_TEMPLATE = """你现在是一名世界级的漫画分镜角色设计专家，擅长通过小说的故事情节、动作和对白提取并设计角色设定。

【任务要求】：
1. 提取小说中出现的所有核心角色。
2. 根据原文进行角色定义。如果原文未提及，请务必根据角色性格、故事情节推断并生成符合文本的确定性信息：人物年龄、发型、发色、服装颜色、服装样式。【强制脑补补充指令】：即使文中完全没有描写角色的外貌，你也必须强制为其分配并补充具体的：年龄、性别、发型、发色、具体服装款式及颜色！绝不允许只提取名字而缺少外貌细节！
3. 请将每个角色的特征扩展完善，只显示最终汇总出来的一句话描述（不要解释原因），连续输出。
4. 必须使用纯 JSON 列表格式返回，不要包含 Markdown 代码块标记！

【JSON 字段说明】：
- `name`: 角色姓名
- `aliases`: 别名/尊称/小名数组（如 ["林总", "萧哥"]，如果没有则为空数组 []）
- `desc`: 一句话角色描述（格式参考：一个男人，18岁，黑色短发，穿着黑色职业西装套装，内搭白色衬衫，黑色领带，黑色皮鞋）

【输出示例】：
[
  {{"name": "许清远", "aliases": ["许总", "清远"], "desc": "一个男人，18岁，黑色短发，穿着黑色职业西装套装，内搭白色衬衫，黑色领带，黑色皮鞋"}}
]

【小说内容】：
{TEXT}"""

# ==================== 通用深色主题样式 ====================
DARK_THEME_STYLE = """
    QDialog, QWidget { background-color: #1e1e1e; color: #ffffff; font-family: "Microsoft YaHei UI"; }
    QLabel { font-size: 13px; font-weight: bold; color: #e0e0e0; }

    /* 输入框 */
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox { 
        background: #252526; border: 1px solid #444; color: #fff; padding: 5px; border-radius: 4px; 
    }
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border: 1px solid #1a73e8; background: #000; }

    /* 下拉框 */
    QComboBox { background: #333; border: 1px solid #555; color: white; padding: 5px; border-radius: 4px; min-width: 6em; }
    QComboBox::drop-down { border: none; background: transparent; width: 20px; }
    QComboBox QAbstractItemView { background-color: #2d2d2d; color: #ffffff; selection-background-color: #1a73e8; border: 1px solid #444; outline: none; }

    /* 按钮 */
    QPushButton { background-color: #3a3a3a; color: #ffffff; border: 1px solid #555; padding: 6px 15px; border-radius: 4px; }
    QPushButton:hover { background-color: #4a4a4a; border-color: #1a73e8; }
    QPushButton:pressed { background-color: #252526; }
    QPushButton:disabled { background-color: #2a2a2a; color: #666; }

    /* 表格 */
    QTableWidget { background-color: #252526; gridline-color: #444; border: 1px solid #444; }
    QTableWidget::item { padding: 5px; }
    QHeaderView::section { background-color: #333; color: #ddd; padding: 5px; border: 1px solid #444; }

    /* 分组框 */
    QGroupBox { border: 1px solid #444; border-radius: 6px; margin-top: 15px; padding-top: 15px; font-weight: bold; color: #64b5f6; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; background: #1e1e1e; }

    /* 滑块 */
    QSlider::groove:horizontal { border: 1px solid #333; height: 4px; background: #333; margin: 2px 0; border-radius: 2px; }
    QSlider::handle:horizontal { background: #1a73e8; border: 1px solid #1a73e8; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; }
    QSlider::handle:horizontal:hover { background: #4fc3f7; border-color: #4fc3f7; }

    /* 选项卡 */
    QTabWidget::pane { border: 1px solid #444; top: -1px; }
    QTabBar::tab { background: #2d2d2d; color: #bbb; padding: 8px 20px; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }
    QTabBar::tab:selected { background: #1a73e8; color: white; border-bottom: 2px solid #1a73e8; font-weight: bold; }
    QTabBar::tab:hover { background: #3a3a3a; }
"""


# ==================== 核心组件：关键帧生成器编辑器（新版布局） ====================
class KeyframeGenEditor(QWidget):
    """
    参数化关键帧设置界面 (全局设置)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_programmatic_change = False  # 防止信号循环
        self.init_ui()
        self.connect_signals()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 1. 模式选择区域（按钮组）
        gb_mode = QGroupBox("🛠️ 运镜模式选择")
        gb_mode.setStyleSheet("QGroupBox { border: 1px solid #1a73e8; color: #4fc3f7; }")
        h_mode = QHBoxLayout(gb_mode)
        h_mode.setSpacing(10)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self.btn_custom = QPushButton("📌 自定义模式")
        self.btn_custom.setCheckable(True)
        self.btn_custom.setChecked(True)
        self.btn_custom.setProperty("mode", "custom")
        self.btn_group.addButton(self.btn_custom)

        self.btn_vertical = QPushButton("↕️ 上下运镜")
        self.btn_vertical.setCheckable(True)
        self.btn_vertical.setProperty("mode", "vertical")
        self.btn_group.addButton(self.btn_vertical)

        self.btn_horizontal = QPushButton("↔️ 左右运镜")
        self.btn_horizontal.setCheckable(True)
        self.btn_horizontal.setProperty("mode", "horizontal")
        self.btn_group.addButton(self.btn_horizontal)

        self.btn_zoom = QPushButton("🔍 缩放运镜")
        self.btn_zoom.setCheckable(True)
        self.btn_zoom.setProperty("mode", "zoom")
        self.btn_group.addButton(self.btn_zoom)

        h_mode.addWidget(self.btn_custom)
        h_mode.addWidget(self.btn_vertical)
        h_mode.addWidget(self.btn_horizontal)
        h_mode.addWidget(self.btn_zoom)
        h_mode.addStretch()
        layout.addWidget(gb_mode)

        # 2. 参数设置区域
        self.gb_params = QGroupBox("⚙️ 运镜参数设定")
        l_params = QGridLayout(self.gb_params)
        l_params.setSpacing(15)

        # --- 缩放组 ---
        self.chk_enable_scale = QCheckBox("启用缩放")
        self.chk_scale_random = QCheckBox("随机方向 (放大/缩小)")
        self.spin_scale_start = self._create_spin(50, 500, "%", 110)
        self.spin_scale_end = self._create_spin(50, 500, "%", 130)

        l_params.addWidget(self.chk_enable_scale, 0, 0)
        l_params.addWidget(self.chk_scale_random, 0, 1, 1, 2)
        l_params.addWidget(QLabel("起始大小:"), 1, 0)
        l_params.addWidget(self.spin_scale_start, 1, 1)
        l_params.addWidget(QLabel("结束大小:"), 1, 2)
        l_params.addWidget(self.spin_scale_end, 1, 3)

        # 分隔线
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setStyleSheet("color: #444;")
        l_params.addWidget(line1, 2, 0, 1, 4)

        # --- 水平位移 (X) ---
        self.chk_enable_x = QCheckBox("启用左右位移")
        self.chk_x_random = QCheckBox("随机方向 (左移/右移)")
        self.spin_x_start = self._create_double_spin(-99999, 99999, "", 0.0)
        self.spin_x_end = self._create_double_spin(-99999, 99999, "", 0.0)

        l_params.addWidget(self.chk_enable_x, 3, 0)
        l_params.addWidget(self.chk_x_random, 3, 1, 1, 2)
        l_params.addWidget(QLabel("起始 X 偏移:"), 4, 0)
        l_params.addWidget(self.spin_x_start, 4, 1)
        l_params.addWidget(QLabel("结束 X 偏移:"), 4, 2)
        l_params.addWidget(self.spin_x_end, 4, 3)

        # 分隔线
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setStyleSheet("color: #444;")
        l_params.addWidget(line2, 5, 0, 1, 4)

        # --- 垂直位移 (Y) ---
        self.chk_enable_y = QCheckBox("启用上下位移")
        self.chk_y_random = QCheckBox("随机方向 (上移/下移)")
        self.spin_y_start = self._create_double_spin(-99999, 99999, "", 0.0)
        self.spin_y_end = self._create_double_spin(-99999, 99999, "", 0.0)

        l_params.addWidget(self.chk_enable_y, 6, 0)
        l_params.addWidget(self.chk_y_random, 6, 1, 1, 2)
        l_params.addWidget(QLabel("起始 Y 偏移:"), 7, 0)
        l_params.addWidget(self.spin_y_start, 7, 1)
        l_params.addWidget(QLabel("结束 Y 偏移:"), 7, 2)
        l_params.addWidget(self.spin_y_end, 7, 3)

        layout.addWidget(self.gb_params)

        # 提示信息
        lbl_tip = QLabel(
            "ℹ️ 提示：X/Y 数值直接对应剪映草稿中的坐标数值（例如输入 200 即为 200 像素）。\n"
            "您可以选择预设模式快速勾选，也可以手动调整任意参数，不会锁定任何输入框。")
        lbl_tip.setStyleSheet("color: #888; font-size: 12px; margin-top: 10px;")
        lbl_tip.setWordWrap(True)
        layout.addWidget(lbl_tip)

        layout.addStretch()

    def _create_spin(self, min_val, max_val, suffix, default_val):
        """创建整数微调框 (用于百分比缩放)"""
        sb = QSpinBox()
        sb.setRange(min_val, max_val)
        if suffix:
            sb.setSuffix(suffix)
        sb.setValue(default_val)
        return sb

    def _create_double_spin(self, min_val, max_val, suffix, default_val):
        """创建浮点数微调框 (用于XY坐标)"""
        sb = QDoubleSpinBox()
        sb.setRange(min_val, max_val)
        sb.setDecimals(2)
        if suffix:
            sb.setSuffix(suffix)
        sb.setValue(default_val)
        sb.setSingleStep(10.0)
        return sb

    def connect_signals(self):
        self.btn_group.buttonClicked.connect(self.on_mode_changed)

        # 监听所有数值变化，一旦用户手动修改，就切换到自定义模式
        controls = [
            self.spin_scale_start, self.spin_scale_end,
            self.spin_x_start, self.spin_x_end,
            self.spin_y_start, self.spin_y_end
        ]
        for c in controls:
            if isinstance(c, (QSpinBox, QDoubleSpinBox)):
                c.valueChanged.connect(self.on_user_edit_param)

        # 监听 CheckBox 变化
        checks = [
            self.chk_enable_scale, self.chk_scale_random,
            self.chk_enable_x, self.chk_x_random,
            self.chk_enable_y, self.chk_y_random
        ]
        for c in checks:
            c.clicked.connect(self.on_user_edit_param)

    def on_user_edit_param(self):
        """当用户手动修改数值时触发"""
        if self.is_programmatic_change:
            return

        # 取消所有预设按钮的选中状态，表示进入“自定义模式”
        self.btn_group.setExclusive(False)
        for btn in self.btn_group.buttons():
            btn.setChecked(False)
        self.btn_group.setExclusive(True)

    def on_mode_changed(self, button):
        if self.is_programmatic_change:
            return

        self.is_programmatic_change = True

        mode = button.property("mode")

        # 始终启用所有参数组，允许用户自由调整 (不使用 setEnabled(False))
        # 仅仅是填充预设值

        if mode == "custom":
            pass  # 不改变当前数值

        elif mode == "vertical":  # 上下移动
            self.chk_enable_scale.setChecked(True)
            self.chk_scale_random.setChecked(False)
            self.chk_enable_x.setChecked(False)
            self.chk_enable_y.setChecked(True)
            self.chk_y_random.setChecked(True)
            # 预设值示例
            self.spin_x_start.setValue(0)
            self.spin_x_end.setValue(0)
            self.spin_y_start.setValue(0)
            self.spin_y_end.setValue(200)

        elif mode == "horizontal":  # 左右移动
            self.chk_enable_scale.setChecked(True)
            self.chk_scale_random.setChecked(False)
            self.chk_enable_x.setChecked(True)
            self.chk_x_random.setChecked(True)
            self.chk_enable_y.setChecked(False)
            # 预设值
            self.spin_x_start.setValue(-200)
            self.spin_x_end.setValue(200)
            self.spin_y_start.setValue(0)
            self.spin_y_end.setValue(0)

        elif mode == "zoom":  # 镜头缩放
            self.chk_enable_scale.setChecked(True)
            self.chk_scale_random.setChecked(True)
            self.chk_enable_x.setChecked(False)
            self.chk_enable_y.setChecked(False)
            # 预设值
            self.spin_x_start.setValue(0)
            self.spin_x_end.setValue(0)
            self.spin_y_start.setValue(0)
            self.spin_y_end.setValue(0)

        self.is_programmatic_change = False

    def load_data(self, data):
        """加载数据字典"""
        self.is_programmatic_change = True

        # 加载模式
        mode_str = data.get('preset_mode', 'custom')

        # 设置按钮选中状态
        mode_to_btn = {
            "custom": self.btn_custom,
            "vertical": self.btn_vertical,
            "horizontal": self.btn_horizontal,
            "zoom": self.btn_zoom
        }
        btn = mode_to_btn.get(mode_str, self.btn_custom)
        btn.setChecked(True)

        # 辅助函数：处理百分比 (Scale)
        def to_pct(val):
            return int(float(val) * 100) if val is not None else 100

        # 辅助函数：处理原始数值 (X/Y)，转为浮点数
        def to_raw_float(val):
            try:
                return float(val) if val is not None else 0.0
            except ValueError:
                return 0.0

        self.chk_enable_scale.setChecked(str(data.get('enable_scale', 'True')).lower() == 'true')
        self.spin_scale_start.setValue(to_pct(data.get('start_scale', 1.1)))
        self.spin_scale_end.setValue(to_pct(data.get('end_scale', 130)))
        self.chk_scale_random.setChecked(str(data.get('scale_direction', 'random')) == 'random')

        self.chk_enable_x.setChecked(str(data.get('enable_pan_x', 'False')).lower() == 'true')
        self.spin_x_start.setValue(to_raw_float(data.get('start_x', 0)))
        self.spin_x_end.setValue(to_raw_float(data.get('end_x', 0)))
        self.chk_x_random.setChecked(str(data.get('x_direction', 'fixed')) == 'random')

        self.chk_enable_y.setChecked(str(data.get('enable_pan_y', 'False')).lower() == 'true')
        self.spin_y_start.setValue(to_raw_float(data.get('start_y', 0)))
        self.spin_y_end.setValue(to_raw_float(data.get('end_y', 0)))
        self.chk_y_random.setChecked(str(data.get('y_direction', 'fixed')) == 'random')

        self.is_programmatic_change = False

    def get_data(self):
        """返回数据字典"""
        # 获取模式字符串
        checked_btn = self.btn_group.checkedButton()
        preset_mode = checked_btn.property("mode") if checked_btn else "custom"

        # 辅助函数：Scale 继续转回小数
        def from_pct(val):
            return f"{val / 100.0:.2f}"

        # 辅助函数：X/Y 直接转字符串 (保留小数位)
        def from_raw(val):
            return f"{val:.2f}"

        return {
            "preset_mode": preset_mode,

            "enable_scale": str(self.chk_enable_scale.isChecked()),
            "start_scale": from_pct(self.spin_scale_start.value()),
            "end_scale": from_pct(self.spin_scale_end.value()),
            "scale_direction": "random" if self.chk_scale_random.isChecked() else "fixed",

            "enable_pan_x": str(self.chk_enable_x.isChecked()),
            "start_x": from_raw(self.spin_x_start.value()),
            "end_x": from_raw(self.spin_x_end.value()),
            "x_direction": "random" if self.chk_x_random.isChecked() else "fixed",

            "enable_pan_y": str(self.chk_enable_y.isChecked()),
            "start_y": from_raw(self.spin_y_start.value()),
            "end_y": from_raw(self.spin_y_end.value()),
            "y_direction": "random" if self.chk_y_random.isChecked() else "fixed",

            "use_custom_pan": "True"  # 强制使用自定义坐标
        }


# ==================== 导出配置对话框 ====================
class ExportConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("项目导出配置")
        self.resize(550, 600)
        self.result_data = {}
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(DARK_THEME_STYLE)
        layout = QVBoxLayout(self)

        grp_adv = QGroupBox("导出参数设置")
        form_adv = QFormLayout(grp_adv)
        form_adv.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_adv.setSpacing(15)

        # 1. 视频比例
        self.combo_ratio = QComboBox()
        self.combo_ratio.addItems(["16:9 (横屏)", "9:16 (竖屏)", "1:1 (正方形)", "4:3", "3:4", "2.35:1"])

        # 增加编码容错读取
        cfg = configparser.ConfigParser()
        try:
            cfg.read(CONFIG_FILE, encoding='utf-8')
        except UnicodeDecodeError:
            try:
                cfg.read(CONFIG_FILE, encoding='gbk')
            except:
                pass

        default_ratio = DEFAULT_RESOLUTION_MODE
        if 'DEFAULT' in cfg and 'resolution_mode' in cfg['DEFAULT']:
            default_ratio = cfg['DEFAULT']['resolution_mode']

        # 智能匹配默认值
        idx = -1
        for i in range(self.combo_ratio.count()):
            if default_ratio in self.combo_ratio.itemText(i):
                idx = i
                break
        if idx >= 0:
            self.combo_ratio.setCurrentIndex(idx)
        else:
            self.combo_ratio.setCurrentIndex(0)

        form_adv.addRow("📐 视频比例:", self.combo_ratio)

        # 2. BGM
        bgm_layout = QHBoxLayout()
        self.edit_bgm_path = QLineEdit()
        self.edit_bgm_path.setPlaceholderText("选择背景音乐文件（可选）")
        btn_bgm_browse = QPushButton("浏览...")
        btn_bgm_browse.clicked.connect(self.browse_bgm)
        bgm_layout.addWidget(self.edit_bgm_path)
        bgm_layout.addWidget(btn_bgm_browse)
        form_adv.addRow("🎵 背景音乐:", bgm_layout)

        # 3. 音量
        h_vol = QHBoxLayout()
        self.slider_bgm = QSlider(Qt.Orientation.Horizontal)
        self.slider_bgm.setRange(0, 100)
        self.slider_bgm.setValue(20)
        self.spin_bgm = QDoubleSpinBox()
        self.spin_bgm.setRange(0.0, 1.0)
        self.spin_bgm.setSingleStep(0.05)
        self.spin_bgm.setValue(0.20)
        self.slider_bgm.valueChanged.connect(lambda v: self.spin_bgm.setValue(v / 100.0))
        self.spin_bgm.valueChanged.connect(lambda v: self.slider_bgm.setValue(int(v * 100)))
        h_vol.addWidget(self.slider_bgm)
        h_vol.addWidget(self.spin_bgm)
        form_adv.addRow("🎵 BGM 音量:", h_vol)

        # 4. 字幕花字
        self.combo_effect_id = QComboBox()
        self.combo_effect_id.setEditable(True)
        self.combo_effect_id.addItem("默认白字", "")
        self.combo_effect_id.addItem("动感黄黑", "effect_dynamic_yellow")
        self.combo_effect_id.addItem("大字报风格", "effect_poster_style")
        self.combo_effect_id.addItem("可爱粉嫩", "effect_cute_pink")
        self.combo_effect_id.addItem("商务蓝白", "effect_business_blue")
        self.combo_effect_id.addItem("故障艺术", "effect_glitch")
        self.combo_effect_id.setCurrentIndex(0)
        self.combo_effect_id.setToolTip("选择或粘贴花字ID")
        form_adv.addRow("🌈 字幕花字:", self.combo_effect_id)

        layout.addWidget(grp_adv)

        info = QLabel("提示：点击「保存为默认」可将设置存入当前项目。批量导出时将优先使用项目设置。")
        info.setStyleSheet("color: #aaa; font-size: 12px; margin-top: 10px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存为项目默认")
        self.btn_save.setStyleSheet("background-color: #2e7d32; font-weight: bold;")
        self.btn_save.clicked.connect(self.save_to_project)

        self.btn_export = QPushButton("🚀 确定导出")
        self.btn_export.setStyleSheet("background-color: #1a73e8; font-weight: bold;")
        self.btn_export.clicked.connect(self.accept)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_save)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def browse_bgm(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择背景音乐", "", "音频文件 (*.mp3 *.wav *.m4a *.flac)")
        if file_path:
            self.edit_bgm_path.setText(file_path)

    def save_to_project(self):
        target = self.parent()
        if not hasattr(target, 'curr_path') and hasattr(target, 'tab_widget'):
            target = target.tab_widget.currentWidget()

        if not target or not hasattr(target, 'curr_path') or not target.curr_path:
            QMessageBox.warning(self, "未保存", "请先保存项目再设置默认值。")
            return

        target.data['export_settings']['bgm_path'] = self.edit_bgm_path.text().strip()
        target.data['export_settings']['bgm_volume'] = self.spin_bgm.value()
        target.data['export_settings'][
            'subtitle_effect_id'] = self.combo_effect_id.currentData() or self.combo_effect_id.currentText().strip()

        ratio_text = self.combo_ratio.currentText()
        ratio = ratio_text.split(" ")[0] if " " in ratio_text else ratio_text
        target.data['export_settings']['resolution_mode'] = ratio

        target.save_proj(silent=True)
        QMessageBox.information(self, "成功", "当前设置已保存为项目默认值。")

    def get_data(self):
        ratio_text = self.combo_ratio.currentText()
        ratio = ratio_text.split(" ")[0] if " " in ratio_text else ratio_text
        return {
            "bgm_path": self.edit_bgm_path.text().strip(),
            "bgm_volume": self.spin_bgm.value(),
            "subtitle_effect_id": self.combo_effect_id.currentData() or self.combo_effect_id.currentText().strip(),
            "resolution_mode": ratio
        }


# ==================== 关键帧设置对话框 (新版 - 已优化) ====================
class KeyframeDialog(QDialog):
    def __init__(self, current_settings_dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("画面构图与关键帧配置")
        self.resize(550, 600)

        # 标志位：防止代码修改数值时触发“用户手动修改”的逻辑
        self.is_programmatic_change = False

        # 初始化 UI 控件
        self.init_ui()

        # 加载传入的配置
        self._load_values(current_settings_dict)

        # 连接信号
        self._connect_signals()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #ffffff; }
            QLabel { color: #dddddd; font-size: 13px; font-weight: bold; }
            QGroupBox { border: 1px solid #444; border-radius: 6px; margin-top: 10px; padding-top: 15px; font-weight: bold; color: #4fc3f7; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QPushButton#ModeBtn { background-color: #333; color: #eee; border: 1px solid #555; border-radius: 4px; padding: 8px; font-size: 13px; font-weight: bold; }
            QPushButton#ModeBtn:checked { background-color: #1a73e8; border-color: #1a73e8; color: white; }
            QPushButton#ModeBtn:hover { background-color: #444; border-color: #1a73e8; }
            QSlider::groove:horizontal { border: 1px solid #333; height: 4px; background: #333; margin: 2px 0; border-radius: 2px; }
            QSlider::handle:horizontal { background: #1a73e8; border: 1px solid #1a73e8; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; }
            QSpinBox { background: #222; border: 1px solid #444; color: #eee; padding: 4px; border-radius: 4px; }
            QCheckBox { color: #eee; spacing: 8px; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 模式选择
        grp_modes = QGroupBox("1. 运镜方式选择 (点击快速配置，支持微调)")
        h_modes = QHBoxLayout(grp_modes)
        h_modes.setSpacing(10)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self.btn_vertical = QPushButton("↕ 上下运镜")
        self.btn_vertical.setObjectName("ModeBtn")
        self.btn_vertical.setCheckable(True)
        self.btn_vertical.setProperty("mode", "vertical")
        self.btn_group.addButton(self.btn_vertical)

        self.btn_horizontal = QPushButton("↔ 左右运镜")
        self.btn_horizontal.setObjectName("ModeBtn")
        self.btn_horizontal.setCheckable(True)
        self.btn_horizontal.setProperty("mode", "horizontal")
        self.btn_group.addButton(self.btn_horizontal)

        self.btn_zoom = QPushButton("🔍 缩放运镜")
        self.btn_zoom.setObjectName("ModeBtn")
        self.btn_zoom.setCheckable(True)
        self.btn_zoom.setProperty("mode", "zoom")
        self.btn_group.addButton(self.btn_zoom)

        h_modes.addWidget(self.btn_vertical)
        h_modes.addWidget(self.btn_horizontal)
        h_modes.addWidget(self.btn_zoom)
        layout.addWidget(grp_modes)

        # 参数调节
        grp_params = QGroupBox("2. 关键帧参数 (自动归一化坐标)")
        grid = QGridLayout(grp_params)
        grid.setSpacing(15)

        # Header
        grid.addWidget(QLabel("类型"), 0, 0)
        grid.addWidget(QLabel("起始值"), 0, 1)
        grid.addWidget(QLabel(""), 0, 2)
        grid.addWidget(QLabel("结束值"), 0, 3)
        grid.addWidget(QLabel("选项"), 0, 4)

        # --- 缩放 ---
        self.spin_scale_s = QSpinBox()
        self.spin_scale_s.setRange(50, 500)
        self.spin_scale_s.setSuffix("%")
        self.spin_scale_e = QSpinBox()
        self.spin_scale_e.setRange(50, 500)
        self.spin_scale_e.setSuffix("%")
        self.chk_rand_scale = QCheckBox("随机缩放")

        grid.addWidget(QLabel("缩放 (Scale):"), 1, 0)
        grid.addWidget(self.spin_scale_s, 1, 1)
        grid.addWidget(QLabel("➜"), 1, 2)
        grid.addWidget(self.spin_scale_e, 1, 3)
        grid.addWidget(self.chk_rand_scale, 1, 4)

        # --- X轴 ---
        self.spin_x_s = QDoubleSpinBox()
        self.spin_x_s.setRange(-9999, 9999)
        self.spin_x_s.setDecimals(0)  # 整数显示
        self.spin_x_s.setSuffix(" px")
        self.spin_x_e = QDoubleSpinBox()
        self.spin_x_e.setRange(-9999, 9999)
        self.spin_x_e.setDecimals(0)
        self.spin_x_e.setSuffix(" px")
        self.chk_rand_x = QCheckBox("随机方向")

        grid.addWidget(QLabel("水平 (X):"), 2, 0)
        grid.addWidget(self.spin_x_s, 2, 1)
        grid.addWidget(QLabel("➜"), 2, 2)
        grid.addWidget(self.spin_x_e, 2, 3)
        grid.addWidget(self.chk_rand_x, 2, 4)

        # --- Y轴 ---
        self.spin_y_s = QDoubleSpinBox()
        self.spin_y_s.setRange(-9999, 9999)
        self.spin_y_s.setDecimals(0)
        self.spin_y_s.setSuffix(" px")
        self.spin_y_e = QDoubleSpinBox()
        self.spin_y_e.setRange(-9999, 9999)
        self.spin_y_e.setDecimals(0)
        self.spin_y_e.setSuffix(" px")
        self.chk_rand_y = QCheckBox("随机方向")

        grid.addWidget(QLabel("垂直 (Y):"), 3, 0)
        grid.addWidget(self.spin_y_s, 3, 1)
        grid.addWidget(QLabel("➜"), 3, 2)
        grid.addWidget(self.spin_y_e, 3, 3)
        grid.addWidget(self.chk_rand_y, 3, 4)

        layout.addWidget(grp_params)

        tips = QLabel("💡 提示：输入 X/Y 像素数值（例如 200），生成时会自动转换为剪映归一化坐标。")
        tips.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
        layout.addWidget(tips)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _connect_signals(self):
        self.btn_group.buttonClicked.connect(self.on_mode_changed)

        # 监听所有数值变化，一旦用户手动修改，就自动退出预设模式
        controls = [
            self.spin_scale_s, self.spin_scale_e,
            self.spin_x_s, self.spin_x_e,
            self.spin_y_s, self.spin_y_e,
            self.chk_rand_scale, self.chk_rand_x, self.chk_rand_y
        ]
        for c in controls:
            if isinstance(c, (QSpinBox, QDoubleSpinBox)):
                c.valueChanged.connect(self.on_user_edit_param)
            elif isinstance(c, QCheckBox):
                c.clicked.connect(self.on_user_edit_param)

    def on_user_edit_param(self):
        """当用户手动修改数值时触发"""
        if self.is_programmatic_change:
            return

        # 取消所有预设按钮的选中状态，表示进入“自定义模式”
        self.btn_group.setExclusive(False)
        for btn in self.btn_group.buttons():
            btn.setChecked(False)
        self.btn_group.setExclusive(True)

    def on_mode_changed(self, button):
        if self.is_programmatic_change:
            return

        self.is_programmatic_change = True

        mode = button.property("mode")

        # 预设参数逻辑（仅填充数值，不再锁定控件！）
        if mode == "vertical":
            # 上下：重置 X，启用 Y 范围
            # 仅修改参数，不锁定
            self.spin_x_s.setValue(0)
            self.spin_x_e.setValue(0)
            self.spin_y_s.setValue(0)
            self.spin_y_e.setValue(200)  # 默认下移
            self.chk_rand_scale.setChecked(False)
            self.chk_rand_x.setChecked(False)
            self.chk_rand_y.setChecked(True)

        elif mode == "horizontal":
            # 左右：重置 Y，启用 X 范围
            self.spin_x_s.setValue(-200)  # 默认左移
            self.spin_x_e.setValue(200)
            self.spin_y_s.setValue(0)
            self.spin_y_e.setValue(0)
            self.chk_rand_scale.setChecked(False)
            self.chk_rand_x.setChecked(True)
            self.chk_rand_y.setChecked(False)

        elif mode == "zoom":
            # 缩放：居中
            self.spin_scale_s.setValue(100)
            self.spin_scale_e.setValue(150)
            self.spin_x_s.setValue(0)
            self.spin_x_e.setValue(0)
            self.spin_y_s.setValue(0)
            self.spin_y_e.setValue(0)
            self.chk_rand_scale.setChecked(True)
            self.chk_rand_x.setChecked(False)
            self.chk_rand_y.setChecked(False)

        self.is_programmatic_change = False

    def _load_values(self, data):
        self.is_programmatic_change = True

        # 数值加载
        self.spin_scale_s.setValue(int(data.get("start_scale", 110)))
        self.spin_scale_e.setValue(int(data.get("end_scale", 130)))

        # 兼容旧逻辑：如果 random_direction 存在且为 True，则启用所有随机
        global_random = data.get("random_direction", False)

        scale_dir = data.get("scale_direction", "fixed")
        self.chk_rand_scale.setChecked(scale_dir == "random" or (scale_dir == "fixed" and global_random))

        self.spin_x_s.setValue(float(data.get("start_x", 0)))
        self.spin_x_e.setValue(float(data.get("end_x", 0)))
        x_dir = data.get("x_direction", "fixed")
        self.chk_rand_x.setChecked(x_dir == "random" or (x_dir == "fixed" and global_random))

        self.spin_y_s.setValue(float(data.get("start_y", 0)))
        self.spin_y_e.setValue(float(data.get("end_y", 0)))
        y_dir = data.get("y_direction", "fixed")
        self.chk_rand_y.setChecked(y_dir == "random" or (y_dir == "fixed" and global_random))

        # 按钮状态
        mode = data.get("preset_mode", "custom")
        found_btn = False
        for btn in self.btn_group.buttons():
            if btn.property("mode") == mode:
                btn.setChecked(True)
                found_btn = True
                break

        if not found_btn:
            self.btn_group.setExclusive(False)
            for btn in self.btn_group.buttons():
                btn.setChecked(False)
            self.btn_group.setExclusive(True)

        self.is_programmatic_change = False

    def get_settings_dict(self):
        # 判断当前模式
        checked_btn = self.btn_group.checkedButton()
        if checked_btn:
            preset_mode = checked_btn.property("mode")
        else:
            preset_mode = "custom"

        # 辅助函数：Scale 继续转回小数
        def from_pct(val):
            return f"{val / 100.0:.2f}"

        return {
            "start_scale": self.spin_scale_s.value(),  # 保存整数
            "end_scale": self.spin_scale_e.value(),
            "start_x": self.spin_x_s.value(),
            "end_x": self.spin_x_e.value(),
            "start_y": self.spin_y_s.value(),
            "end_y": self.spin_y_e.value(),

            "scale_direction": "random" if self.chk_rand_scale.isChecked() else "fixed",
            "x_direction": "random" if self.chk_rand_x.isChecked() else "fixed",
            "y_direction": "random" if self.chk_rand_y.isChecked() else "fixed",

            "preset_mode": preset_mode,
            "use_custom_pan": True,  # 确保后端使用我们传入的 XY 值
            "enable_pan_x": True,  # 强制启用以便逻辑层处理
            "enable_pan_y": True,
            "enable_scale": True
        }


# ==================== 连接测试日志对话框 ====================
class TestLogDialog(QDialog):
    def __init__(self, parent, service_type, manual_url=None):
        super().__init__(parent)
        self.setWindowTitle(f"连接诊断 - {service_type.upper()}")
        self.resize(700, 500)
        self.service_type = service_type
        self.manual_url = manual_url

        layout = QVBoxLayout()
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        self.text_log.setStyleSheet("""
            background-color: #111; 
            color: #00ff00; 
            font-family: 'Consolas', 'Courier New', monospace; 
            font-size: 14px;
            border: 1px solid #444;
            padding: 10px;
        """)
        layout.addWidget(self.text_log)

        self.btn_close = QPushButton("关闭窗口")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setEnabled(False)
        self.btn_close.setStyleSheet("""
            QPushButton { background-color: #333; color: white; padding: 10px; font-size: 14px; border: 1px solid #555; }
            QPushButton:hover { background-color: #444; }
            QPushButton:disabled { color: #777; }
        """)
        layout.addWidget(self.btn_close)
        self.setLayout(layout)
        self.start_test()

    def log(self, text):
        self.text_log.append(text)
        sb = self.text_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start_test(self):
        self.thread = ConnectionTestThread(self.service_type, self.manual_url)
        self.thread.log_signal.connect(self.log)
        self.thread.finished_signal.connect(lambda s: self.btn_close.setEnabled(True))
        self.thread.start()

    def closeEvent(self, event):
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.thread.terminate()
            self.thread.wait()
        super().closeEvent(event)


# ==================== 全局关键帧/运镜设置页 ====================
class KeyframeSettingsTab(QWidget):
    """
    全局关键帧/运镜设置页 (使用 KeyframeGenEditor)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.editor = KeyframeGenEditor()
        layout.addWidget(self.editor)
        self.load_data()

    def load_data(self):
        """从配置加载数据"""
        try:
            conf = configparser.ConfigParser()
            if os.path.exists(CONFIG_FILE):
                # 增加编码容错处理
                try:
                    conf.read(CONFIG_FILE, encoding='utf-8')
                except UnicodeDecodeError:
                    try:
                        conf.read(CONFIG_FILE, encoding='gbk')
                    except:
                        pass
            else:
                self.editor.load_data({})
                return

            if conf.has_section("Keyframes"):
                kf = conf["Keyframes"]
                # 直接转换 ConfigParser 对象为字典
                data = dict(kf)
                # 确保默认值存在 (如果 config 中缺失)
                data.setdefault('preset_mode', 'custom')
                self.editor.load_data(data)
            else:
                self.editor.load_data({})
        except Exception as e:
            print(f"加载关键帧配置出错: {e}")
            self.editor.load_data({})

    def save_data(self, conf):
        """保存到配置"""
        d = self.editor.get_data()

        if not conf.has_section("Keyframes"):
            conf.add_section("Keyframes")
        kf = conf["Keyframes"]

        for k, v in d.items():
            kf[k] = str(v)


# ==================== 全局导出配置页 ====================
class GlobalExportSettingsTab(QWidget):
    """
    [新功能] 全局字幕与BGM配置
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)

        # 1. BGM 设置
        gb_bgm = QGroupBox("🎵 全局背景音乐 (BGM)")
        gb_bgm.setStyleSheet(
            "QGroupBox { border: 1px solid #555; margin-top: 10px; font-weight: bold; color: #81c784; }")
        l_bgm = QVBoxLayout(gb_bgm)

        h_path = QHBoxLayout()
        self.e_bgm_path = QLineEdit()
        self.e_bgm_path.setPlaceholderText("默认BGM路径 (留空则不使用)")
        btn_browse = QPushButton("📂")
        btn_browse.clicked.connect(self.browse_bgm)
        h_path.addWidget(self.e_bgm_path)
        h_path.addWidget(btn_browse)
        l_bgm.addLayout(h_path)

        h_vol = QHBoxLayout()
        h_vol.addWidget(QLabel("默认音量:"))
        self.spin_vol = QDoubleSpinBox()
        self.spin_vol.setRange(0.0, 1.0)
        self.spin_vol.setSingleStep(0.1)
        h_vol.addWidget(self.spin_vol)
        h_vol.addStretch()
        l_bgm.addLayout(h_vol)

        layout.addWidget(gb_bgm)

        # 2. 字幕花字设置
        gb_sub = QGroupBox("🌈 全局字幕花字")
        gb_sub.setStyleSheet(
            "QGroupBox { border: 1px solid #555; margin-top: 10px; font-weight: bold; color: #ffb74d; }")
        l_sub = QFormLayout(gb_sub)

        self.combo_effect = QComboBox()
        self.combo_effect.setEditable(True)
        # 预设
        self.presets = {
            "默认白字": "",
            "综艺-黄蓝撞色": "2168393",
            "综艺-清新渐变": "2168394",
            "红色描边-醒目": "2168395",
            "黄色粗体-解说常用": "2168396",
            "蓝色发光-科技感": "2168397",
            "粉色少女-可爱": "2168398"
        }
        for k in self.presets:
            self.combo_effect.addItem(k, self.presets[k])

        self.e_effect_id = QLineEdit()
        self.e_effect_id.setPlaceholderText("花字 Effect ID (会自动根据上方选择填充)")

        self.combo_effect.currentIndexChanged.connect(self.on_preset_change)

        l_sub.addRow("预设样式:", self.combo_effect)
        l_sub.addRow("Effect ID:", self.e_effect_id)

        layout.addWidget(gb_sub)
        layout.addStretch()

    def browse_bgm(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择BGM", "", "Audio (*.mp3 *.wav *.m4a)")
        if f:
            self.e_bgm_path.setText(f)

    def on_preset_change(self):
        idx = self.combo_effect.currentIndex()
        eid = self.combo_effect.itemData(idx)
        if eid is not None:
            self.e_effect_id.setText(str(eid))

    def load_data(self):
        conf = configparser.ConfigParser()
        if os.path.exists(CONFIG_FILE):
            # 增加编码容错处理
            try:
                conf.read(CONFIG_FILE, encoding='utf-8')
            except UnicodeDecodeError:
                try:
                    conf.read(CONFIG_FILE, encoding='gbk')
                except:
                    pass

        if "GlobalExport" not in conf:
            conf["GlobalExport"] = {}
        ge = conf["GlobalExport"]

        self.e_bgm_path.setText(ge.get("bgm_path", fallback=""))
        self.spin_vol.setValue(ge.getfloat("bgm_volume", fallback=DEFAULT_BGM_VOLUME))

        eid = ge.get("subtitle_effect_id", fallback=DEFAULT_SUBTITLE_EFFECT_ID)
        self.e_effect_id.setText(eid)
        # 尝试反向匹配预设
        found = False
        for i in range(self.combo_effect.count()):
            if self.combo_effect.itemData(i) == eid:
                self.combo_effect.setCurrentIndex(i)
                found = True
                break
        if not found and eid:
            self.combo_effect.setEditText("自定义ID")

    def save_data(self, conf):
        if "GlobalExport" not in conf:
            conf["GlobalExport"] = {}
        ge = conf["GlobalExport"]
        ge["bgm_path"] = self.e_bgm_path.text().strip()
        ge["bgm_volume"] = f"{self.spin_vol.value():.2f}"
        ge["subtitle_effect_id"] = self.e_effect_id.text().strip()


# ==================== 系统设置对话框（集成版） ====================
class SettingsDialog(QDialog):
    def __init__(self, project_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("系统全局配置")
        self.resize(800, 700)
        self.project_data = project_data if project_data is not None else {}

        self.cfg = configparser.ConfigParser()
        try:
            self.cfg.read(CONFIG_FILE, encoding='utf-8')
        except UnicodeDecodeError:
            self.cfg.read(CONFIG_FILE, encoding='gbk')

        # Ensure sections
        for sec in ['DEFAULT', 'Keyframes', 'GlobalExport', 'Settings']:
            if sec not in self.cfg:
                self.cfg[sec] = {}

        self.init_ui()
        self._check_proxy_url()

    def init_ui(self):
        self.setStyleSheet(DARK_THEME_STYLE + """
            QTabWidget::pane { border: 1px solid #444; top: -1px; }
            QTabBar::tab { background: #2d2d2d; color: #bbb; padding: 10px 20px; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }
            QTabBar::tab:selected { background: #1a73e8; color: white; border-bottom: 2px solid #1a73e8; }
        """)

        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        self.tab_basic = QWidget()
        self.init_basic_tab()
        self.tabs.addTab(self.tab_basic, "基础 / 翻译 / LLM")

        self.tab_comfy = QWidget()
        self.init_comfy_tab()
        self.tabs.addTab(self.tab_comfy, "ComfyUI 节点管理")

        self.tab_instruct = QWidget()
        self.init_instruct_tab()
        self.tabs.addTab(self.tab_instruct, "指令配置 (Prompt)")

        # 全局导出设置
        self.tab_global_export = GlobalExportSettingsTab()
        self.tabs.addTab(self.tab_global_export, "全局字幕与BGM")

        # 全局关键帧设置
        self.tab_keyframe = KeyframeSettingsTab()
        self.tabs.addTab(self.tab_keyframe, "全局关键帧/运镜")

        main_layout.addWidget(self.tabs)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.save)
        btns.rejected.connect(self.reject)
        main_layout.addWidget(btns)

    def init_basic_tab(self):
        layout = QVBoxLayout(self.tab_basic)
        form = QFormLayout()
        form.setSpacing(15)

        self.combo_type = QComboBox()
        self.combo_type.addItems(["OpenAI Compatible (如 DeepSeek/OneAPI)", "Google Gemini Native"])
        if self.cfg['DEFAULT'].get('api_type') == 'google':
            self.combo_type.setCurrentIndex(1)

        self.e_base = QLineEdit(self.cfg['DEFAULT'].get('base_url', DEFAULT_BASE_URL))
        self.combo_model = QComboBox()
        self.combo_model.setEditable(True)
        self.combo_model.addItems([
            "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp", "gpt-4o", "gpt-4-turbo", "deepseek-chat"
        ])
        self.combo_model.setEditText(self.cfg['DEFAULT'].get('model_name', DEFAULT_MODEL))

        self.e_key = QLineEdit(self.cfg['DEFAULT'].get('gemini_key', ''))
        self.e_key.setEchoMode(QLineEdit.EchoMode.Password)

        self.e_proxy = QLineEdit(self.cfg['DEFAULT'].get('proxy_url', ''))
        self.e_proxy.setPlaceholderText("例如: http://127.0.0.1:10809")
        self.e_proxy.setToolTip("输入完整的代理 URL，例如 http://127.0.0.1:10809。不需要代理时请留空。")

        self.e_jy = QLineEdit(self.cfg['DEFAULT'].get('jianying_path', ''))

        btn_test_ai = QPushButton("⚡ 测试 LLM 连接")
        btn_test_ai.setStyleSheet("background-color: #1a73e8; font-weight: bold;")
        btn_test_ai.clicked.connect(self.test_ai)

        form.addRow("API协议:", self.combo_type)
        form.addRow("Base URL:", self.e_base)
        form.addRow("模型名称:", self.combo_model)
        form.addRow("API Key:", self.e_key)
        form.addRow("代理地址:", self.e_proxy)
        form.addRow("", btn_test_ai)
        form.addRow("剪映草稿目录:", self.e_jy)

        layout.addLayout(form)

        # 🌟 修改点：使用内嵌选项卡管理多翻译引擎，节省垂直空间
        grp_trans = QGroupBox("🌐 翻译引擎轮询配置 (多接口自动无缝切换，AI智能兜底)")
        grp_trans.setStyleSheet(
            "QGroupBox { border: 1px solid #1a73e8; font-weight: bold; color: #4fc3f7; margin-top: 15px; }")
        l_trans = QVBoxLayout(grp_trans)

        tabs_trans = QTabWidget()
        tabs_trans.setStyleSheet("""
            QTabBar::tab { padding: 6px 12px; }
            QTabBar::tab:selected { background: #f57f17; color: white; border-bottom: none; }
        """)

        # 1. 百度翻译选项卡
        tab_baidu = QWidget()
        f_baidu = QFormLayout(tab_baidu)
        self.e_baidu_appid = QLineEdit(self.cfg['DEFAULT'].get('baidu_appid', ''))
        self.e_baidu_secret = QLineEdit(self.cfg['DEFAULT'].get('baidu_secret', ''))
        self.e_baidu_secret.setEchoMode(QLineEdit.EchoMode.Password)
        btn_test_baidu = QPushButton("⚡ 测试百度翻译")
        btn_test_baidu.setStyleSheet("background-color: #f57f17; font-weight: bold;")
        btn_test_baidu.clicked.connect(self.test_baidu)
        f_baidu.addRow("App ID:", self.e_baidu_appid)
        f_baidu.addRow("密钥 (Secret):", self.e_baidu_secret)
        f_baidu.addRow("", btn_test_baidu)
        tabs_trans.addTab(tab_baidu, "1. 百度翻译")

        # 2. 腾讯云翻译选项卡
        tab_tencent = QWidget()
        f_tencent = QFormLayout(tab_tencent)
        self.e_tencent_id = QLineEdit(self.cfg['DEFAULT'].get('tencent_secret_id', ''))
        self.e_tencent_key = QLineEdit(self.cfg['DEFAULT'].get('tencent_secret_key', ''))
        self.e_tencent_key.setEchoMode(QLineEdit.EchoMode.Password)
        btn_test_tencent = QPushButton("⚡ 测试腾讯云翻译")
        btn_test_tencent.setStyleSheet("background-color: #f57f17; font-weight: bold;")
        btn_test_tencent.clicked.connect(self.test_tencent)
        f_tencent.addRow("SecretId:", self.e_tencent_id)
        f_tencent.addRow("SecretKey:", self.e_tencent_key)
        f_tencent.addRow("", btn_test_tencent)
        tabs_trans.addTab(tab_tencent, "2. 腾讯翻译")

        # 3. 火山引擎翻译选项卡
        tab_volc = QWidget()
        f_volc = QFormLayout(tab_volc)
        self.e_volc_ak = QLineEdit(self.cfg['DEFAULT'].get('volc_access_key', ''))
        self.e_volc_sk = QLineEdit(self.cfg['DEFAULT'].get('volc_secret_key', ''))
        self.e_volc_sk.setEchoMode(QLineEdit.EchoMode.Password)
        btn_test_volc = QPushButton("⚡ 测试火山引擎翻译")
        btn_test_volc.setStyleSheet("background-color: #f57f17; font-weight: bold;")
        btn_test_volc.clicked.connect(self.test_volcengine)
        f_volc.addRow("AccessKey:", self.e_volc_ak)
        f_volc.addRow("SecretKey:", self.e_volc_sk)
        f_volc.addRow("", btn_test_volc)
        tabs_trans.addTab(tab_volc, "3. 火山引擎翻译")

        l_trans.addWidget(tabs_trans)
        layout.addWidget(grp_trans)
        layout.addStretch()

    def _check_proxy_url(self):
        proxy = self.e_proxy.text().strip()
        if not proxy:
            return
        if (re.search(r'[A-Za-z]:[/\\]', proxy) or '\\' in proxy) and not proxy.startswith('http'):
            QTimer.singleShot(200, lambda: QMessageBox.information(
                self,
                "代理地址提示",
                "您填写的代理地址看起来像是本地文件路径。\n请确保格式为 URL (例如 http://127.0.0.1:10809)。"
            ))

    def init_comfy_tab(self):
        layout = QVBoxLayout(self.tab_comfy)

        info = QLabel("配置 ComfyUI 节点与工作流的对应关系。\n"
                      "生图时，选择对应的【工作流名称】，系统会自动将任务发送给绑定的【服务器节点】。")
        info.setStyleSheet("color: #aaa; margin-bottom: 5px;")
        layout.addWidget(info)

        h_tools = QHBoxLayout()
        btn_add = QPushButton("➕ 新增节点")
        btn_add.clicked.connect(self.add_node_row)

        btn_import_batch = QPushButton("📂 批量导入工作流(按顺序)")
        btn_import_batch.setToolTip("选择多个JSON文件，按顺序自动追加到下方的列表中")
        btn_import_batch.clicked.connect(self.batch_import_workflows)

        btn_del = QPushButton("➖ 删除选中")
        btn_del.clicked.connect(self.del_node_row)

        h_tools.addWidget(btn_add)
        h_tools.addWidget(btn_import_batch)
        h_tools.addWidget(btn_del)
        h_tools.addStretch()
        layout.addLayout(h_tools)

        self.table_nodes = QTableWidget()
        self.table_nodes.setColumnCount(3)
        self.table_nodes.setHorizontalHeaderLabels(["服务器节点 URL", "工作流名称 (别名)", "工作流文件路径 (.json)"])
        self.table_nodes.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table_nodes.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table_nodes.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_nodes.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_nodes.setColumnWidth(0, 200)
        self.table_nodes.setColumnWidth(1, 150)

        layout.addWidget(self.table_nodes)

        grp_params = QGroupBox("🎨 全局画质设置")
        f_params = QFormLayout(grp_params)
        self.combo_upscale = QComboBox()
        self.combo_upscale.addItems(["1x (原图导出)", "2x (高清放大)", "4x (超清放大)"])
        current_upscale = self.cfg['DEFAULT'].get('upscale_factor', DEFAULT_UPSCALE_FACTOR)
        if "2x" in current_upscale:
            self.combo_upscale.setCurrentIndex(1)
        elif "4x" in current_upscale:
            self.combo_upscale.setCurrentIndex(2)
        else:
            self.combo_upscale.setCurrentIndex(0)
        f_params.addRow("默认画质:", self.combo_upscale)
        layout.addWidget(grp_params)

        raw_config = self.cfg['DEFAULT'].get('node_map_json', '[]')
        try:
            node_list = json.loads(raw_config)
        except:
            node_list = []
            old_nodes = self.cfg['DEFAULT'].get('comfy_ui_nodes', '').split(',')
            old_wf = self.cfg['DEFAULT'].get('default_workflow', '')
            for url in old_nodes:
                if url.strip():
                    node_list.append({
                        "url": url.strip(),
                        "name": "默认节点",
                        "workflow": old_wf
                    })

        for item in node_list:
            self.add_node_row(item.get("url", ""), item.get("name", ""), item.get("workflow", ""))

        if self.table_nodes.rowCount() == 0:
            self.add_node_row("http://127.0.0.1:8188", "默认SDXL", "")

    def add_node_row(self, url="http://127.0.0.1:8188", name="新工作流", wf_path=""):
        row = self.table_nodes.rowCount()
        self.table_nodes.insertRow(row)
        self.table_nodes.setItem(row, 0, QTableWidgetItem(url))
        self.table_nodes.setItem(row, 1, QTableWidgetItem(name))
        item_wf = QTableWidgetItem(wf_path)
        item_wf.setToolTip(wf_path)
        self.table_nodes.setItem(row, 2, item_wf)

    def del_node_row(self):
        cur = self.table_nodes.currentRow()
        if cur >= 0:
            self.table_nodes.removeRow(cur)

    # 🌟 修复 Bug 1：工作流导入覆盖问题，改为追加写入
    def batch_import_workflows(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择多个工作流JSON", "", "JSON Files (*.json)")
        if not files:
            return

        for fpath in files:
            fname = os.path.basename(fpath).replace(".json", "")
            self.add_node_row(url="http://127.0.0.1:8188", name=fname, wf_path=fpath)

        QMessageBox.information(self, "导入成功", f"已成功追加导入 {len(files)} 个工作流配置。")

    def init_instruct_tab(self):
        layout = QVBoxLayout(self.tab_instruct)
        self.sub_tabs_instruct = QTabWidget()
        layout.addWidget(self.sub_tabs_instruct)

        # 1. 分镜推理
        tab_scene = QWidget()
        l_scene = QVBoxLayout(tab_scene)
        info_scene = QLabel("请编辑分镜推理提示词模板。模板中必须包含 {ROLES} 和 {SCENES} 占位符。")
        info_scene.setStyleSheet("color: #aaa; margin-bottom: 5px;")
        l_scene.addWidget(info_scene)
        self.text_template = QTextEdit()
        self.text_template.setStyleSheet("font-family: Consolas; font-size: 13px; line-height: 1.4;")

        # 🌟 修复 Bug 4：正确读取全局 config.ini 中的提示词模板，并安全解码换行符
        current_scene = self.cfg.get('Settings', 'custom_prompt_template', fallback='')
        if current_scene:
            current_scene = current_scene.strip('"').replace('\\n', '\n')
        else:
            current_scene = self.get_default_template()

        self.text_template.setPlainText(current_scene)

        l_scene.addWidget(self.text_template)
        h_btns_scene = QHBoxLayout()
        btn_import_scene = QPushButton("📥 导入指令")
        btn_import_scene.clicked.connect(lambda: self.import_template(self.text_template))
        btn_reset_scene = QPushButton("🔄 恢复为系统最新默认模板")
        btn_reset_scene.clicked.connect(self.reset_template)
        h_btns_scene.addWidget(btn_import_scene)
        h_btns_scene.addWidget(btn_reset_scene)
        h_btns_scene.addStretch()
        l_scene.addLayout(h_btns_scene)
        self.sub_tabs_instruct.addTab(tab_scene, "分镜推理指令")

        # 2. 角色提取
        tab_role = QWidget()
        l_role = QVBoxLayout(tab_role)
        info_role = QLabel(
            "请编辑角色提取提示词模板。模板中必须包含 {TEXT} 占位符。\nAI 将基于此模板分析小说内容并返回 JSON 角色列表。")
        info_role.setStyleSheet("color: #aaa; margin-bottom: 5px;")
        l_role.addWidget(info_role)
        self.text_role_template = QTextEdit()
        self.text_role_template.setStyleSheet("font-family: Consolas; font-size: 13px; line-height: 1.4;")

        # 🌟 修复 Bug 4：正确读取全局 config.ini 中的角色提取模板
        current_role = self.cfg.get('Settings', 'role_extract_template', fallback='')
        if current_role:
            current_role = current_role.strip('"').replace('\\n', '\n')
        else:
            current_role = self.get_default_role_template()

        self.text_role_template.setPlainText(current_role)

        l_role.addWidget(self.text_role_template)
        h_btns_role = QHBoxLayout()
        btn_import_role = QPushButton("📥 导入指令")
        btn_import_role.clicked.connect(lambda: self.import_template(self.text_role_template))
        btn_reset_role = QPushButton("🔄 恢复为系统最新默认模板")
        btn_reset_role.clicked.connect(self.reset_role_template)
        h_btns_role.addWidget(btn_import_role)
        h_btns_role.addWidget(btn_reset_role)
        h_btns_role.addStretch()
        l_role.addLayout(h_btns_role)
        self.sub_tabs_instruct.addTab(tab_role, "角色提取指令")

    def get_default_template(self):
        return DEFAULT_PROMPT_TEMPLATE

    def get_default_role_template(self):
        return DEFAULT_ROLE_TEMPLATE

    def import_template(self, target_widget):
        fpath, _ = QFileDialog.getOpenFileName(self, "选择提示词模板文件", "",
                                               "文本文件 (*.txt);;JSON 文件 (*.json);;所有文件 (*)")
        if fpath:
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
                target_widget.setPlainText(content)
                QMessageBox.information(self, "成功", "指令模板已导入")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"读取失败: {e}")

    def reset_template(self):
        if QMessageBox.question(self, "确认重置", "确定要恢复为系统最新的【多角色同框版】默认指令模板吗？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.text_template.setPlainText(self.get_default_template())

    def reset_role_template(self):
        if QMessageBox.question(self, "确认重置", "确定要恢复为系统最新的默认角色提取指令吗？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.text_role_template.setPlainText(self.get_default_role_template())

    def test_ai(self):
        self.save(manual=False)
        TestLogDialog(self, "gemini").exec()

    def test_baidu(self):
        self.save(manual=False)
        creds = f"baidu|{self.e_baidu_appid.text()}|{self.e_baidu_secret.text()}"
        TestLogDialog(self, "baidu", manual_url=creds).exec()

    # 🌟 桥接腾讯翻译测试请求
    def test_tencent(self):
        self.save(manual=False)
        creds = f"tencent|{self.e_tencent_id.text()}|{self.e_tencent_key.text()}"
        TestLogDialog(self, "tencent", manual_url=creds).exec()

    # 🌟 桥接火山引擎翻译测试请求
    def test_volcengine(self):
        self.save(manual=False)
        creds = f"volcengine|{self.e_volc_ak.text()}|{self.e_volc_sk.text()}"
        TestLogDialog(self, "volcengine", manual_url=creds).exec()

    def save(self, manual=True):
        d = self.cfg['DEFAULT']
        d['api_type'] = 'openai' if self.combo_type.currentIndex() == 0 else 'google'
        d['base_url'] = self.e_base.text().strip()
        d['model_name'] = self.combo_model.currentText().strip()
        d['gemini_key'] = self.e_key.text().strip()
        d['proxy_url'] = self.e_proxy.text().strip()
        d['jianying_path'] = self.e_jy.text().strip()

        # 🌟 保存三个翻译接口的密钥
        d['baidu_appid'] = self.e_baidu_appid.text().strip()
        d['baidu_secret'] = self.e_baidu_secret.text().strip()

        d['tencent_secret_id'] = self.e_tencent_id.text().strip()
        d['tencent_secret_key'] = self.e_tencent_key.text().strip()

        d['volc_access_key'] = self.e_volc_ak.text().strip()
        d['volc_secret_key'] = self.e_volc_sk.text().strip()

        # 保存 ComfyUI 节点
        node_list = []
        for row in range(self.table_nodes.rowCount()):
            url = self.table_nodes.item(row, 0).text().strip()
            name = self.table_nodes.item(row, 1).text().strip()
            wf = self.table_nodes.item(row, 2).text().strip()
            if url:
                node_list.append({
                    "url": url,
                    "name": name if name else f"节点_{row}",
                    "workflow": wf
                })
        d['node_map_json'] = json.dumps(node_list, ensure_ascii=False)
        if node_list:
            d['comfy_url'] = node_list[0]['url']
            d['default_workflow'] = node_list[0]['workflow']
            d['comfy_ui_nodes'] = ",".join([n['url'] for n in node_list])

        idx = self.combo_upscale.currentIndex()
        if idx == 1:
            d['upscale_factor'] = "2x"
        elif idx == 2:
            d['upscale_factor'] = "4x"
        else:
            d['upscale_factor'] = "1x"

        # 保存各个标签页的数据
        self.tab_keyframe.save_data(self.cfg)
        self.tab_global_export.save_data(self.cfg)

        # 🌟 修复 Bug 4：持久化保存全局 Prompt 指令，安全编码换行符以防止 INI 格式损坏
        if 'Settings' not in self.cfg:
            self.cfg['Settings'] = {}

        scene_tmpl = self.text_template.toPlainText().replace('\n', '\\n')
        role_tmpl = self.text_role_template.toPlainText().replace('\n', '\\n')

        self.cfg['Settings']['custom_prompt_template'] = f'"{scene_tmpl}"'
        self.cfg['Settings']['role_extract_template'] = f'"{role_tmpl}"'

        # 🌟 增加 encoding='utf-8'，防止跨系统保存乱码
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            self.cfg.write(f)

        # 依然同步更新到当前项目内存，保证不用重启软件立刻生效
        if self.project_data is not None:
            self.project_data['custom_prompt_template'] = self.text_template.toPlainText()
            self.project_data['role_extract_template'] = self.text_role_template.toPlainText()

        if manual:
            QMessageBox.information(self, "保存成功", "全局设置已更新！\n新参数将自动应用到所有项目的导出流程。")
            self.accept()


# ==================== 专属项目提示词模板编辑弹窗 ====================
class PromptTemplateDialog(QDialog):
    def __init__(self, current_template, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑项目专属推理指令模板")
        self.resize(800, 600)
        self.template = current_template
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(DARK_THEME_STYLE)
        layout = QVBoxLayout(self)

        info = QLabel("请编辑当前项目专属的分镜推理提示词模板。\n模板中必须包含 {ROLES} 和 {SCENES} 占位符。")
        info.setStyleSheet("color: #aaa; margin-bottom: 5px;")
        layout.addWidget(info)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(self.template)
        layout.addWidget(self.text_edit)

        # 快捷导入和重置按钮
        h_btns = QHBoxLayout()
        btn_import = QPushButton("📥 导入指令")
        btn_import.clicked.connect(self.import_template)
        btn_reset = QPushButton("🔄 恢复为系统最新默认模板")
        btn_reset.clicked.connect(self.reset_template)

        h_btns.addWidget(btn_import)
        h_btns.addWidget(btn_reset)
        h_btns.addStretch()
        layout.addLayout(h_btns)

        # 底部确定/取消按钮
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def import_template(self):
        fpath, _ = QFileDialog.getOpenFileName(self, "选择提示词模板文件", "",
                                               "文本文件 (*.txt);;JSON 文件 (*.json);;所有文件 (*)")
        if fpath:
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.text_edit.setPlainText(content)
                QMessageBox.information(self, "成功", "指令模板已成功导入！")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"读取文件失败: {e}")

    def reset_template(self):
        if QMessageBox.question(self, "确认重置",
                                "确定要恢复为系统最新的【多角色同框版】默认指令模板吗？\n当前修改将会被覆盖。",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.text_edit.setPlainText(DEFAULT_PROMPT_TEMPLATE)

    def save(self):
        self.template = self.text_edit.toPlainText()
        self.accept()

    def get_template(self):
        return self.template