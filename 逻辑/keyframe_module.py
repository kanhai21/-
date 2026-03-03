import random
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class KeyframeSettings:
    """
    关键帧配置类 - 兼容旧项目结构并支持新版查询接口
    """
    enable_scale: bool = True  # 1. 大小 (缩放)
    enable_pan_x: bool = True  # 2. 左右 (水平位移)
    enable_pan_y: bool = True  # 3. 上下 (垂直位移)

    start_scale: float = 1.1
    end_scale: float = 1.3

    x_direction: str = "random"
    y_direction: str = "random"
    scale_direction: str = "random"

    preset_mode: str = "custom"
    random_direction: bool = True

    # === 新增自定义位移字段（可选保留，为了兼容性建议加上） ===
    use_custom_pan: bool = False
    start_x: float = 0.0
    end_x: float = 0.0
    start_y: float = 0.0
    end_y: float = 0.0

    def is_animated(self) -> bool:
        """
        【新增方法】判断当前配置是否会产生动画效果
        新版导出器依赖此方法
        """
        # 如果任意一个开关打开，则视为有动画
        if self.enable_scale or self.enable_pan_x or self.enable_pan_y:
            return True
        return False

    @classmethod
    def from_dict(cls, data: Dict):
        """从字典加载配置，兼容旧数据"""
        return cls(
            enable_scale=bool(data.get("enable_scale", True)),
            enable_pan_x=bool(data.get("enable_pan_x", True)),
            enable_pan_y=bool(data.get("enable_pan_y", True)),
            start_scale=float(data.get("start_scale", 1.1)),
            end_scale=float(data.get("end_scale", 1.3)),
            x_direction=str(data.get("x_direction", "random")),
            y_direction=str(data.get("y_direction", "random")),
            scale_direction=str(data.get("scale_direction", "random")),
            preset_mode=data.get("preset_mode", "custom"),
            random_direction=bool(data.get("random_direction", True)),

            use_custom_pan=bool(data.get("use_custom_pan", False)),
            start_x=float(data.get("start_x", 0.0)),
            end_x=float(data.get("end_x", 0.0)),
            start_y=float(data.get("start_y", 0.0)),
            end_y=float(data.get("end_y", 0.0)),
        )

    def to_dict(self) -> Dict:
        """转换为字典以便保存"""
        return {
            "enable_scale": self.enable_scale,
            "enable_pan_x": self.enable_pan_x,
            "enable_pan_y": self.enable_pan_y,
            "start_scale": self.start_scale,
            "end_scale": self.end_scale,
            "x_direction": self.x_direction,
            "y_direction": self.y_direction,
            "scale_direction": self.scale_direction,
            "preset_mode": self.preset_mode,
            "random_direction": self.random_direction,
            "use_custom_pan": self.use_custom_pan,
            "start_x": self.start_x,
            "end_x": self.end_x,
            "start_y": self.start_y,
            "end_y": self.end_y,
        }


def calculate_keyframe_values(
        settings: KeyframeSettings,
        base_scale: float = 1.0,
        base_x: float = 0.0,
        base_y: float = 0.0,
        canvas_w: int = 1920,
        canvas_h: int = 1080,
        randomize: bool = True
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    根据设置计算起始和结束的关键帧数值 (Scale, X, Y)
    """
    # ==========================
    # 1. 计算缩放 (大小)
    # ==========================
    if settings.enable_scale:
        s_start = settings.start_scale
        s_end = settings.end_scale

        mode = settings.scale_direction
        should_swap = False

        if mode == "zoom_out":
            if s_start < s_end:
                should_swap = True
        elif mode == "zoom_in":
            if s_start > s_end:
                should_swap = True
        else:  # random
            if randomize and random.random() > 0.5:
                should_swap = True

        if should_swap:
            s_start, s_end = s_end, s_start
    else:
        s_start = s_end = base_scale

    # ==========================
    # 2. 计算位移 (X, Y)
    # ==========================
    if settings.use_custom_pan:
        start_x = settings.start_x
        end_x = settings.end_x
        start_y = settings.start_y
        end_y = settings.end_y
    else:
        # 自动计算逻辑
        min_s = min(s_start, s_end)
        if min_s < 1.0:
            min_s = 1.0

        safe_margin_x = (min_s - 1.0) * canvas_w * 0.5 * 0.9
        safe_margin_y = (min_s - 1.0) * canvas_h * 0.5 * 0.9

        # X 位移
        start_x, end_x = base_x, base_x
        if settings.enable_pan_x and safe_margin_x > 1.0:
            direction = 1
            if settings.x_direction == "left_to_right":
                direction = 1
            elif settings.x_direction == "right_to_left":
                direction = -1
            else:
                if randomize:
                    direction = 1 if random.random() > 0.5 else -1
                else:
                    direction = 1

            start_x = -direction * safe_margin_x
            end_x = direction * safe_margin_x

        # Y 位移
        start_y, end_y = base_y, base_y
        if settings.enable_pan_y and safe_margin_y > 1.0:
            direction = 1
            if settings.y_direction == "up_to_down":
                direction = 1
            elif settings.y_direction == "down_to_up":
                direction = -1
            else:
                if randomize:
                    direction = 1 if random.random() > 0.5 else -1
                else:
                    direction = 1

            start_y = -direction * safe_margin_y
            end_y = direction * safe_margin_y

    return (
        {"scale": s_start, "x": start_x, "y": start_y},
        {"scale": s_end, "x": end_x, "y": end_y}
    )