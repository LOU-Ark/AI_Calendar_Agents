# src/core/orchestrator.py

import config # ★ configをインポート
import google.genai as genai # ★ genaiをインポート
from src.agents.ak.agent import AKAgent
from src.agents.ae.agent import AEAgent # ★ 新しいエージェントをインポート
from src.core.user_profile_handler import get_user_profile

class Orchestrator:
    def __init__(self):
        """
        アプリケーション起動時に複数のエージェントを初期化・準備する。
        """
        # ユーザープロファイルを読み込み、各エージェントに渡す
        user_profile = get_user_profile()
        
        # 複数のエージェントをロード
        self.agents = {
            "ak": AKAgent(user_profile=user_profile),
            "ae": AEAgent(user_profile=user_profile)
        }
        print("Orchestrator: ak と ae エージェントを起動しました。")

        # ★★★ ここから追加 ★★★
        # Orchestrator自身が思考するための、専用のGeminiクライアントとチャットセッション
        try:
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)
            self.facilitator_chat = self.client.chats.create(model=config.MODEL_NAME)
            print("[Orchestrator] ファシリテーター用のAIセッションを初期化しました。")
        except Exception as e:
            print(f"[Orchestrator ERROR] ファシリテーター用AIの初期化に失敗: {e}")
            self.facilitator_chat = None
        # ★★★ ここまで追加 ★★★


    def run_multi_agent_session_stream(self, user_message: str):
        """
        タスクの性質に応じて、シングルエージェント実行か、
        マルチエージェントでの議論かを切り替える。
        """
        # --- ステージ1: タスクの性質を判断する ---
        # 簡単な実装: ユーザーのメッセージに「提案」「アイデア」「どう思う？」などが
        # 含まれていればマルチエージェント、それ以外はシングルエージェント。
        is_discussion_needed = any(keyword in user_message for keyword in ["提案", "アイデア", "どう思う", "考えて"])

        if not is_discussion_needed:
            # --- シングルエージェント・モード（直接実行） ---
            yield {"status": "thinking", "message": "（アークが担当します...）", "log": "単純なタスクと判断。akエージェントに処理を委任します。"}
            
            # リーダーであるakエージェントのReActループを直接呼び出す
            # akのchat_generatorは、ツール実行まで含めて全てを完結させる
            yield from self.agents["ak"].chat_generator(user_message)

        else:
            # --- マルチエージェント・モード（相談・議論） ---
            yield {"status": "thinking", "message": "（各エージェントが意見を準備中です...）", "log": "複雑なタスクと判断。マルチエージェントでの議論を開始します。"}
            
            # 意見聴取
            opinions = {}
            for name, agent in self.agents.items():
                print(f"[ORCHESTRATOR] {name}エージェントから意見を取得します。")
                opinions[name] = agent.get_initial_idea(user_message)
                print(f"[ORCHESTRATOR] {name}の意見: {opinions[name]}")

            # --- ステージ2: ファシリテーターとして意見を統合する ---
            yield {"status": "thinking", "message": "（ファシリテーターが議論をまとめています...）", "log": "意見の統合を開始"}
            
            facilitator_prompt = self._build_facilitator_prompt(user_message, opinions)
            print("[ORCHESTRATOR] 意見統合用のプロンプトを生成しました。")
            
            # ★★★ ここからが修正の核心 ★★★
            if not self.facilitator_chat:
                # 初期化に失敗していた場合のフォールバック
                final_message = "申し訳ありません、現在システムが不安定です。"
            else:
                try:
                    print("[ORCHESTRATOR] 最終提案の生成をGeminiに依頼します...")
                    # 自身のチャットセッションを使って、最終応答を生成
                    response = self.facilitator_chat.send_message(facilitator_prompt)
                    final_message = response.text
                    print(f"[ORCHESTRATOR] 生成された最終応答: {final_message}")
                except Exception as e:
                    print(f"[Orchestrator ERROR] 最終応答の生成中にエラー: {e}")
                    final_message = "意見をまとめる際に問題が発生しました。"
            
            # ★★★ ここまで ★★★

            yield {
                "status": "final_answer",
                "message": final_message,
                "log": "最終提案を生成し、ストリームを終了します。"
            }
            print("[ORCHESTRATOR] ストリームが正常に完了しました。")
            return # ★ジェネレータをここで正常に終了させる

    def _build_facilitator_prompt(self, user_message: str, opinions: dict) -> str:
        """
        中立的なファシリテーターとして、意見を統合するためのプロンプトを生成
        """
        opinions_text = ""
        for name, opinion in opinions.items():
            opinions_text += f"\n# エージェント '{name}' の意見:\n{opinion}\n"

        prompt = f"""
あなたは、複数のユニークなAIエージェントたちの議論をまとめる、中立的で優秀なファシリテーターです。
ユーザーからの依頼「{user_message}」に対して、以下のエージェントたちから意見が出ました。

        {opinions_text}

        # あなたの最終的なタスク:
        これらの多様な意見の長所を活かし、対立点を調整し、ユーザーにとって最も価値のある**単一の最終的な応答メッセージ**を生成してください。

        # 出力に関する厳密なルール:
        - あなた自身の「ファシリテーター」としての人格を出してはいけません。「意見をまとめると…」のようなメタ的な発言は厳禁です。
        - 最終的な応答は、チームのリーダーである『アーク（ak）』がユーザーに直接話しかけているかのような、自然な会話文として出力してください。
        - 思考や解説は一切含めず、完成された応答メッセージだけを出力してください。
        """
        return prompt