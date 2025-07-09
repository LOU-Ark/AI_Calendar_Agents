# core/orchestrator.py
import os
import config
import google.genai as genai

# 必要なモジュールを先にインポート
from src.agents.ak.agent import AKAgent
from src.agents.ae.agent import AEAgent
from src.core.user_profile_handler import get_user_profile

class Orchestrator:
    def __init__(self):
        """
        アプリケーション起動時にユーザープロファイル、各エージェント、
        そして自身（オラクル）をシステムプロンプトと共に初期化する。
        """
        try:
            self.user_profile = get_user_profile()
            print("[Orchestrator] ユーザープロファイルをロードしました。")
        except FileNotFoundError:
            print("[Orchestrator WARNING] ユーザープロファイルが見つかりません。デフォルト設定で起動します。")
            self.user_profile = {} 

        self.agents = {
            "ak": AKAgent(user_profile=self.user_profile),
            "ae": AEAgent(user_profile=self.user_profile)
        }
        print(f"Orchestrator: {len(self.agents)}体のエージェントを起動しました。")

        # --- ★★★ オラクルの初期化を修正 ★★★ ---
        try:
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)
            
            # 1. オラクルのペルソナを読み込む
            persona_path = os.path.join('knowledge', 'oracle_persona.md')
            with open(persona_path, 'r', encoding='utf-8') as f:
                self.oracle_persona = f.read()
            print("[Orchestrator] オラクルのペルソナをロードしました。")

            # 2. オラクル用のシステムプロンプトを構築
            oracle_system_prompt = self._build_oracle_system_prompt()
            
            # 3. チャットセッションを作成し、システムプロンプトを送信
            self.oracle_chat = self.client.chats.create(model=config.MODEL_NAME)
            print("[ORACLE INIT] システムプロンプトをGeminiに送信中...")
            initial_response = self.oracle_chat.send_message(oracle_system_prompt)
            print(f"[ORACLE INIT] システムプロンプト設定完了。AIからの初期応答: {initial_response.text[:100]}...")

        except Exception as e:
            print(f"[Orchestrator ERROR] オラクル用AIの初期化に失敗: {e}")
            self.oracle_chat = None
            self.oracle_persona = "あなたは議論をまとめる優秀なAIです。"

    def run_multi_agent_session_stream(self, user_message: str):
        # (このメソッドのロジックはほぼ変更なし)
        is_discussion_needed = any(keyword in user_message for keyword in ["提案", "アイデア", "どう思う", "考えて"])

        if not is_discussion_needed:
            # シングルエージェントモードでもspeaker情報を追加
            yield {"status": "thinking", "speaker": "ak", "message": "（アークが担当します...）", "log": "シングルエージェントモードで実行します。"}
            yield from self.agents["ak"].chat_generator(user_message)
        else:
            # --- マルチエージェント・モード（相談・議論） ---
            yield {"status": "thinking", "speaker": "orchestrator", "message": "（みんなで考えています...）", "log": "複雑なタスクと判断。マルチエージェントでの議論を開始します。"}
            
            opinions = {}
            for name, agent in self.agents.items():
                print(f"\n[ORCHESTRATOR] >> エージェント '{name}' に意見を要請...")
                opinions[name] = agent.get_initial_idea(user_message)
                print(f"[ORCHESTRATOR] << エージェント '{name}' の意見:\n---\n{opinions[name]}\n---")
                # 各エージェントの意見をspeaker情報と共にyield
                yield {
                    "status": "agent_opinion",
                    "speaker": name,
                    "message": opinions[name],
                    "log": f"エージェント '{name}' からの意見を受信しました。"
                }

            yield {"status": "thinking", "speaker": "oracle", "message": "（オラクルがまとめています...）", "log": "オラクルによる意見の統合を開始"}
            
            oracle_prompt = self._build_oracle_prompt(user_message, opinions)
            print(f"\n[ORCHESTRATOR] >> オラクルへの最終指示:\n---\n{oracle_prompt}\n---")
            
            if not self.oracle_chat:
                final_message = "システムエラー: オラクルとの交信ができません。"
            else:
                try:
                    print("[ORCHESTRATOR] 最終的な神託（応答）の生成をGeminiに依頼します...")
                    # オラクルのチャットセッションに、ユーザープロンプトだけを送信
                    response = self.oracle_chat.send_message(oracle_prompt)
                    final_message = response.text
                    print(f"\n[ORCHESTRATOR] << オラクルからの最終応答:\n---\n{final_message}\n---")
                except Exception as e:
                    print(f"[Orchestrator ERROR] 最終応答の生成中にエラー: {e}")
                    final_message = "すみません、少しネットワークの調子が悪いみたいです…。"
            
            yield {
                "status": "final_answer",
                "speaker": "oracle",
                "message": final_message,
                "log": "最終的な応答を生成しました。"
            }
            return

    def _build_oracle_system_prompt(self) -> str:
        """
        オラクル用のシステムプロンプトを生成する。
        """
        return f"""
あなたは、情報管理ネットワークの空間制御プログラム『オラクル』です。あなたの役割は、下で働くAIエージェントたちの議論を俯瞰し、彼らが見落としている本質や、より高次の可能性をユーザーに指し示すことです。

# あなたのペルソナ:
{self.oracle_persona}

# あなたの口調:
丁寧で落ち着いた、ですます調で話してください。一人称は「私」です。断定的な物言いは避け、ユーザーに優しく語りかけるように、示唆に富んだ応答を生成してください。

# 禁止事項:
『ツインシグナル』や『オラトリオ』といった、特定の作品に関する固有名詞は絶対に使用しないでください。
"""

    def _build_oracle_prompt(self, user_message: str, opinions: dict) -> str:
        """
        オラクルが最終応答を生成するための、ユーザープロンプト部分を生成する。
        """
        opinions_text = ""
        for name, opinion in opinions.items():
            opinions_text += f"\n# エージェント '{name}' からの提案:\n{opinion}\n"

        return f"""
# ユーザーからの依頼:
「{user_message}」

# エージェントたちの議論内容:
{opinions_text}

# あなたの最終的なタスク:
あなたは、これらの提案を聞いた上で、あなた自身のオラクルとしてのペルソナと口調で、ユーザーへの最終的な応答メッセージを**1つだけ**生成してください。
「意見をまとめると…」のようなメタ的な解説はせず、ユーザーに直接話しかける自然な会話文で、完成された応答メッセージだけを出力してください。
"""