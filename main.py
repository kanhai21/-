import sys
import os
import time
import traceback
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from 界面.main_window import NovelTweetApp
from 逻辑.auth_module import AuthManager, SingleInstance
from 界面.auth_dialog import AuthDialog


# 🌟 终极防弹衣：拦截所有 PyQt 底层未捕获异常，防止 0xC0000409 闪退
def global_exception_handler(exc_type, exc_value, exc_traceback):
    err_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(f"【全局异常拦截，保护程序不崩溃】\n{err_msg}")

    # 将致命异常写入本地日志文件，方便后期排查
    try:
        with open("error_crash.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 发生致命异常:\n{err_msg}\n")
    except Exception:
        pass


sys.excepthook = global_exception_handler


def clean_temp_gen_folder():
    """
    优化：统一环境清理。
    将清理临时文件的逻辑放在程序最开头执行一次。
    绝对防止在运行中多个生图后台线程同时扫描并尝试删除同一个文件引发竞态奔溃。
    """
    try:
        temp_dir = os.path.join(os.getcwd(), "temp_gen")
        if os.path.exists(temp_dir):
            now = time.time()
            for f_name in os.listdir(temp_dir):
                f_path = os.path.join(temp_dir, f_name)
                # 清理 24 小时前遗留的临时图片
                if os.path.isfile(f_path) and now - os.path.getmtime(f_path) > 86400:
                    try:
                        os.remove(f_path)
                    except Exception:
                        pass
    except Exception as e:
        print(f"清理临时文件发生异常: {e}")


def main():
    # 程序启动前，先统一进行安全的临时文件清理
    clean_temp_gen_folder()

    app = QApplication(sys.argv)

    # 1. 防多开检测 (已配合最新的 auth_module 升级为 Mutex 互斥体机制，无需传端口参数)
    single_instance = SingleInstance()

    # 2. 授权验证拦截
    success, msg = AuthManager.load_local_license()
    if not success:
        # 如果本地没有卡密或者过期，弹出激活界面
        auth_dlg = AuthDialog()
        if auth_dlg.exec() != QDialog.DialogCode.Accepted:
            # 如果用户点击了退出或叉掉了窗口，直接退出程序
            sys.exit(0)

    # 3. 验证通过，正常启动主界面
    window = NovelTweetApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()