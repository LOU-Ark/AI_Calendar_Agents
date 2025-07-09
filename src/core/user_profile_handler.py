# src/core/user_profile_handler.py
import os
from pathlib import Path

def get_user_profile(project_root: Path) -> str:
    """
    指定されたプロジェクトルートを基準に、ユーザーの特性プロファイル（ペルソナ）を
    ファイルから読み込む。
    
    Args:
        project_root (Path): アプリケーションのルートディレクトリのPathオブジェクト。
    
    Returns:
        str: 読み込んだプロファイルの内容。見つからない場合はデフォルトの文字列。
    """
    # ★★★ 修正箇所 ★★★
    # 引数で渡されたproject_rootを基準にパスを構築する
    user_persona_path = project_root / 'knowledge' / 'ryo-persona.txt'

    try:
        with open(user_persona_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"[WARNING] ユーザープロファイルファイルが見つかりません: {user_persona_path}")
        return "ユーザーの特別な特性に関する情報はありません。"