import os

# src/calendar_agent/knowledge_handler.py
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
USER_PERSONA_PATH = os.path.join(PROJECT_ROOT, 'knowledge', 'ryo-persona.txt') # ファイル名を確認

def get_user_profile() -> str:
    try:
        with open(USER_PERSONA_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "ユーザーの特別な特性に関する情報はありません。"
    
def load_knowledge_texts(knowledge_dir=None):
    """
    knowledgeディレクトリ内のテキスト/ドキュメント系ファイルを読み込み、
    {ファイル名: 内容} のdictで返す。
    対応拡張子: .txt, .md, .csv, .json, .doc, .docx
    """
    if knowledge_dir is None:
        knowledge_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'knowledge')
        knowledge_dir = os.path.abspath(knowledge_dir)
    knowledge = {}
    if not os.path.exists(knowledge_dir):
        return knowledge
    allowed_exts = ('.txt', '.md', '.csv', '.json', '.doc', '.docx')
    for fname in os.listdir(knowledge_dir):
        if fname.endswith(allowed_exts):
            path = os.path.join(knowledge_dir, fname)
            try:
                with open(path, encoding='utf-8') as f:
                    knowledge[fname] = f.read()
            except Exception:
                pass
    return knowledge
