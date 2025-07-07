# src/core/orchestrator.py

# ★ AKAgentのインポートは変更なし
from src.agents.ak.agent import AKAgent 
# ★ user_profile_handlerのインポートも変更なし
from src.core.user_profile_handler import get_user_profile 

class Orchestrator:
    def __init__(self):
        """
        アプリケーション起動時に一度だけ実行される初期化処理。
        """
        # 1. ユーザープロファイルをファイルから読み込む
        user_profile = get_user_profile()
        
        # 2. 読み込んだユーザープロファイルを渡して、a-kエージェントを生成・準備する
        self.ak_agent = AKAgent(user_profile=user_profile)

    def run_chat_stream(self, user_message: str):
        """
        Webサーバー(app.py)から呼び出され、エージェントの思考プロセスを
        ストリーミングで中継する。
        """
        print(f"Orchestrator: a-kエージェントのストリームを開始します。メッセージ='{user_message}'")
        
        # ★★★ ここを修正 ★★★
        # AKAgentのchat_generatorに、ユーザーのメッセージだけを渡す。
        # (user_profileは、ak_agentがすでに知っているため不要)
        response_generator = self.ak_agent.chat_generator(user_message)
        
        print("[ORCHESTRATOR] ジェネレータからの中継を開始します。")
        
        # response_generatorからデータがyieldされるたびに、それをapp.pyに中継する
        yield from response_generator
        
        print("[ORCHESTRATOR] ジェネレータからの中継が完了しました。ストリームを正常に終了します。")

    # ★★★ このメソッドは現在使われていないため、削除またはコメントアウトしてOK ★★★
    # def run_chat_session(self, user_message: str):
    #     """
    #     ジェネレータを最後まで実行し、最後の応答だけを返す（シンプルな実装）
    #     """
    #     final_reply = {}
    #     for reply in self.ak_agent.chat_generator(user_message):
    #         print(f"[LOG] Agent Status: {reply['status']}, Message: {reply['log']}")
    #         final_reply = reply
    #     return final_reply