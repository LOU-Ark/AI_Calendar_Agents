# src/core/user_profile_handler.py
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
USER_PERSONA_PATH = os.path.join(PROJECT_ROOT, 'knowledge', 'ryo-persona.txt')

def get_user_profile() -> str:
    """
    ユーザーの特性プロファイル（ペルソナ）をファイルから読み込む
    """
    try:
        with open(USER_PERSONA_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"[WARNING] ユーザープロファイルファイルが見つかりません: {USER_PERSONA_PATH}")
        return "ユーザーの特別な特性に関する情報はありません。"
