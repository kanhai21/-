import os
import configparser
import threading  # 🌟 优化：引入线程模块用于声明全局锁

APP_VERSION = "v1.0.6"

# 配置文件路径
CONFIG_FILE = "config.ini"

# 🌟 优化：声明全局读写锁，保护项目文件和配置文件，绝对防止高并发下文件被写成 0KB
PROJECT_FILE_LOCK = threading.Lock()
CONFIG_FILE_LOCK = threading.Lock()

# ==================== 默认设置常量 ====================
# API & 模型
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-2.0-flash-exp"

# 绘图 & 图像处理
DEFAULT_UPSCALE_FACTOR = "2x"
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
IMAGE_OUTPUT_DIR = "output_images"

# 剪映 & 导出
# 注意：JIANYING_DRAFT_DIR 是旧变量名，建议使用 DEFAULT_JIANYING_PATH 保持一致，这里保留旧名兼容，但值指向配置读取逻辑
JIANYING_DRAFT_DIR = r"D:\APP\剪映\JianyingPro Drafts"
DEFAULT_JIANYING_PATH = JIANYING_DRAFT_DIR

DEFAULT_BGM_VOLUME = 0.2
DEFAULT_SUBTITLE_EFFECT_ID = ""
DEFAULT_RESOLUTION_MODE = "4:3"
DEFAULT_GLOBAL_BGM_PATH = ""  # 新增：全局BGM默认路径

# ==================== 关键帧/运镜 默认设置 ====================
# 1. 运镜方式开关
DEFAULT_KF_ENABLE_SCALE = True  # 启用 大小/缩放
DEFAULT_KF_ENABLE_PAN_X = True  # 启用 左右/水平
DEFAULT_KF_ENABLE_PAN_Y = True  # 启用 上下/垂直

# 2. 缩放参数
DEFAULT_KF_START_SCALE = 1.1  # 起始缩放 (1.1倍)
DEFAULT_KF_END_SCALE = 1.3  # 结束缩放 (1.3倍)

# 3. 方向控制 (random=随机, left_to_right=左到右, right_to_left=右到左, 等)
DEFAULT_KF_X_DIR = "random"  # 左右方向: random, left_to_right, right_to_left
DEFAULT_KF_Y_DIR = "random"  # 上下方向: random, up_to_down, down_to_up
DEFAULT_KF_SCALE_DIR = "random"  # 缩放方向: random, zoom_in, zoom_out

# 4. 新增：自定义位移开关及数值
DEFAULT_KF_USE_CUSTOM_PAN = False  # 是否启用自定义位移
DEFAULT_KF_START_X = 0.0  # 起始X位移
DEFAULT_KF_END_X = 0.0  # 结束X位移
DEFAULT_KF_START_Y = 0.0  # 起始Y位移
DEFAULT_KF_END_Y = 0.0  # 结束Y位移

# ==================== 新增：全局画风设置 ====================
DEFAULT_GLOBAL_STYLE_POS = ""
DEFAULT_GLOBAL_STYLE_NEG = ""


# ==================== 配置读写工具函数 ====================

def load_config():
    """读取配置，返回 ConfigParser 对象"""
    conf = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        try:
            # 尝试 utf-8 读取
            conf.read(CONFIG_FILE, encoding='utf-8')
        except:
            try:
                # 失败则尝试 gbk (兼容 Windows 旧文本)
                conf.read(CONFIG_FILE, encoding='gbk')
            except:
                pass
    return conf


def save_config(conf):
    """保存配置到文件 (🌟 优化：加入线程锁防止并发写入变成 0KB)"""
    with CONFIG_FILE_LOCK:
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                conf.write(f)
        except Exception as e:
            print(f"保存配置失败: {e}")


def get_jianying_draft_dir():
    """
    🌟 优化新增：统一获取剪映草稿保存根目录。
    替代原本散落在各处的硬编码和重复的 config.ini 解析逻辑。
    """
    conf = load_config()
    draft_dir = ""

    if "DEFAULT" in conf:
        draft_dir = conf["DEFAULT"].get("jianying_path", "")
    if not draft_dir and "Settings" in conf:
        draft_dir = conf["Settings"].get("jianying_path", "")

    if draft_dir:
        draft_dir = draft_dir.strip().strip('"').strip("'")

    if not draft_dir:
        default_paths = [
            os.path.expanduser("~") + "/Documents/JianyingPro Drafts",
            "D:/APP/剪映/JianyingPro Drafts",
            "C:/Users/Public/Documents/JianyingPro Drafts"
        ]
        for p in default_paths:
            if os.path.exists(p):
                draft_dir = p
                break

    return draft_dir


def get_keyframe_defaults():
    """
    获取全局关键帧配置字典
    优先从 config.ini 读取，如果没有则使用文件顶部的 DEFAULT_... 常量
    """
    conf = load_config()

    # 默认值结构
    settings = {
        "enable_scale": DEFAULT_KF_ENABLE_SCALE,
        "enable_pan_x": DEFAULT_KF_ENABLE_PAN_X,
        "enable_pan_y": DEFAULT_KF_ENABLE_PAN_Y,

        "start_scale": DEFAULT_KF_START_SCALE,
        "end_scale": DEFAULT_KF_END_SCALE,

        "x_direction": DEFAULT_KF_X_DIR,
        "y_direction": DEFAULT_KF_Y_DIR,
        "scale_direction": DEFAULT_KF_SCALE_DIR,

        "random_direction": True,  # 兼容旧字段

        # 新增字段默认值
        "use_custom_pan": DEFAULT_KF_USE_CUSTOM_PAN,
        "start_x": DEFAULT_KF_START_X,
        "end_x": DEFAULT_KF_END_X,
        "start_y": DEFAULT_KF_START_Y,
        "end_y": DEFAULT_KF_END_Y,
    }

    # 从配置文件覆盖
    if "Keyframes" in conf:
        kf = conf["Keyframes"]
        settings["enable_scale"] = kf.getboolean("enable_scale", fallback=DEFAULT_KF_ENABLE_SCALE)
        settings["enable_pan_x"] = kf.getboolean("enable_pan_x", fallback=DEFAULT_KF_ENABLE_PAN_X)
        settings["enable_pan_y"] = kf.getboolean("enable_pan_y", fallback=DEFAULT_KF_ENABLE_PAN_Y)

        settings["start_scale"] = kf.getfloat("start_scale", fallback=DEFAULT_KF_START_SCALE)
        settings["end_scale"] = kf.getfloat("end_scale", fallback=DEFAULT_KF_END_SCALE)

        settings["x_direction"] = kf.get("x_direction", fallback=DEFAULT_KF_X_DIR)
        settings["y_direction"] = kf.get("y_direction", fallback=DEFAULT_KF_Y_DIR)
        settings["scale_direction"] = kf.get("scale_direction", fallback=DEFAULT_KF_SCALE_DIR)

        # 读取新增字段
        settings["use_custom_pan"] = kf.getboolean("use_custom_pan", fallback=DEFAULT_KF_USE_CUSTOM_PAN)
        settings["start_x"] = kf.getfloat("start_x", fallback=DEFAULT_KF_START_X)
        settings["end_x"] = kf.getfloat("end_x", fallback=DEFAULT_KF_END_X)
        settings["start_y"] = kf.getfloat("start_y", fallback=DEFAULT_KF_START_Y)
        settings["end_y"] = kf.getfloat("end_y", fallback=DEFAULT_KF_END_Y)

    return settings


def get_global_export_defaults():
    """
    [新增] 获取全局导出配置（BGM、花字、音量）
    优先从 config.ini 的 [GlobalExport] 节读取
    """
    conf = load_config()

    defaults = {
        "bgm_path": DEFAULT_GLOBAL_BGM_PATH,
        "bgm_volume": DEFAULT_BGM_VOLUME,
        "subtitle_effect_id": DEFAULT_SUBTITLE_EFFECT_ID,
    }

    if "GlobalExport" in conf:
        ge = conf["GlobalExport"]
        defaults["bgm_path"] = ge.get("bgm_path", fallback=DEFAULT_GLOBAL_BGM_PATH)
        defaults["bgm_volume"] = ge.getfloat("bgm_volume", fallback=DEFAULT_BGM_VOLUME)
        defaults["subtitle_effect_id"] = ge.get("subtitle_effect_id", fallback=DEFAULT_SUBTITLE_EFFECT_ID)

    return defaults


def get_global_style_settings():
    """
    [新增] 获取全局画风与提示词配置
    """
    conf = load_config()
    defaults = {
        "pos_prompt": DEFAULT_GLOBAL_STYLE_POS,
        "neg_prompt": DEFAULT_GLOBAL_STYLE_NEG,
    }
    if "GlobalStyle" in conf:
        gs = conf["GlobalStyle"]
        defaults["pos_prompt"] = gs.get("pos_prompt", fallback=DEFAULT_GLOBAL_STYLE_POS)
        defaults["neg_prompt"] = gs.get("neg_prompt", fallback=DEFAULT_GLOBAL_STYLE_NEG)
    return defaults
