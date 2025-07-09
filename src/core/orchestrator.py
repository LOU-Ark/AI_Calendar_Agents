# src/core/orchestrator.py
from pathlib import Path
import os
import config
import google.genai as genai
import re
from datetime import datetime, timedelta

# 必要なモジュールを先にインポート
from src.agents.ak.agent import AKAgent
from src.agents.ae.agent import AEAgent
from src.core.user_profile_handler import get_user_profile
from src.calendar_agent import tools

class Orchestrator:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        try:
            self.user_profile = get_user_profile(self.project_root)
            print("[Orchestrator] ユーザープロファイルをロードしました。")
        except FileNotFoundError:
            print("[Orchestrator WARNING] ユーザープロファイルが見つかりません。")
            self.user_profile = {} 

        self.agents = {
            "ak": AKAgent(project_root=self.project_root, user_profile=self.user_profile),
            "ae": AEAgent(project_root=self.project_root, user_profile=self.user_profile)
        }
        print(f"Orchestrator: {len(self.agents)}体のエージェントを起動しました。")

        self.chat_history = []
        
        try:
            self.client = genai.Client(api_key=config.GEMINI_API_KEY)
            persona_path = self.project_root / 'knowledge' / 'oracle_persona.md'
            with open(persona_path, 'r', encoding='utf-8') as f:
                self.oracle_persona = f.read()
            print("[Orchestrator] オラクルのペルソナをロードしました。")

            oracle_system_prompt = self._build_oracle_system_prompt()
            self.oracle_chat = self.client.chats.create(model=config.MODEL_NAME)
            print("[ORACLE INIT] システムプロンプトをGeminiに送信中...")
            initial_response = self.oracle_chat.send_message(oracle_system_prompt)
            print(f"[ORACLE INIT] システムプロンプト設定完了。AIからの初期応答: {initial_response.text[:100]}...")
        except Exception as e:
            print(f"[Orchestrator ERROR] オラクル用AIの初期化に失敗: {e}")
            self.oracle_chat = None
            self.oracle_persona = "あなたは議論をまとめる優秀なAIです。"

    # ★★★★★ ここからが今回の主要な修正箇所 ★★★★★

    def run_multi_agent_session_stream(self, user_message: str):
        """
        オラクルが最初にユーザーの意図を解釈し、
        最適なワークフロー（シングル or マルチ）に処理を委任する。
        """
        self.chat_history.append({"role": "user", "content": user_message})

        # --- ステージ0: メタ認知（ワークフローの決定） ---
        yield {"status": "thinking", "speaker": "oracle", "message": "（どのようなご用件か、確認しています...）"}

        workflow_decision_prompt = self._build_workflow_decision_prompt(user_message)
        
        print("\n[ORCHESTRATOR] >> オラクルにワークフローの判断を要請...")
        try:
            if not self.oracle_chat: raise Exception("オラクルのチャットセッションが初期化されていません。")
            
            # ワークフロー判断専用のチャットセッションを使うのが安全
            decision_chat = self.client.chats.create(model=config.MODEL_NAME)
            decision_response = decision_chat.send_message(workflow_decision_prompt)
            
            workflow = self._parse_workflow_decision(decision_response.text)
            print(f"[ORCHESTRATOR] << オラクルの判断: '{workflow}' ワークフローを選択します。")
        except Exception as e:
            print(f"[Orchestrator ERROR] ワークフロー判断中にエラー: {e}")
            workflow = "single_agent_react" # エラー時は安全なReActモードにフォールバック

        # --- ステージ1以降: 選択されたワークフローの実行 ---
        # ジェネレータを最後まで実行し、最終応答を履歴に追加する
        final_answer = ""
        flow_generator = None
        
        if workflow == "simple_listing":
            flow_generator = self._run_simple_listing_flow(user_message)
        elif workflow == "multi_agent_discussion":
            flow_generator = self._run_multi_agent_flow(user_message, self.chat_history)
        else: # "single_agent_react" または不明な場合
            flow_generator = self._run_single_agent_react_flow(user_message, self.chat_history)

        for result in flow_generator:
            yield result
            if result.get("status") == "final_answer":
                final_answer = result.get("message")
        
        # 最終的なAIの応答も履歴に追加
        # speaker情報はresultから取得できるとさらに良い
        self.chat_history.append({"role": "model", "content": final_answer})

    def _build_workflow_decision_prompt(self, user_message: str) -> str:
        """オラクルがワークフローを決定するためのプロンプトを生成する"""
        return f"""
あなたは、ユーザーからの依頼内容を分析し、それを解決するための最適なプロセスを決定する、高次のメタ認知AI『オラクル』です。

# あなたが選択できるワークフロー
1.  **`simple_listing`**: ユーザーの依頼が、単純にカレンダーの予定を**確認・一覧表示**するだけの場合に選択します。（例: 「今日の予定は？」「明日のスケジュール教えて」）
2.  **`single_agent_react`**: ユーザーの依頼が、カレンダーの予定を**追加・変更・削除**するような、具体的な操作を伴うタスクの場合に選択します。実務担当の『ak』エージェントが単独で処理します。（例: 「会議入れて」「この予定キャンセルして」）
3.  **`multi_agent_discussion`**: ユーザーの依頼が、複数の可能性を検討したり、創造的なアイデアを必要とする、**曖昧で複雑な相談**の場合に選択します。『ak』と『ae』が議論し、あなたがその内容を統合して最終的な提案を行います。（例: 「何か面白いことしたい」「週末の予定を再構築して」）

# ユーザーからの依頼
「{user_message}」

# あなたのタスク
上記の依頼内容を分析し、最適なワークフローは`simple_listing`、`single_agent_react`、`multi_agent_discussion`のどれかを判断し、その**単語だけ**を出力してください。思考や解説は一切不要です。
"""

    def _parse_workflow_decision(self, response_text: str) -> str:
        """AIの応答からワークフロー名を抽出する"""
        response_lower = response_text.lower()
        if "simple_listing" in response_lower:
            return "simple_listing"
        elif "multi_agent_discussion" in response_lower:
            return "multi_agent_discussion"
        return "single_agent_react"

    def _run_simple_listing_flow(self, user_message: str):
        """【高速ルート】機械的な予定取得 ＋ AIによるコメント生成"""
        yield {"status": "tool_running", "speaker": "ak", "message": "承知しました。カレンダーを確認します。"}
        try:
            start_time, end_time = self._get_time_range_from_message(user_message)
            events_json_str = tools.list_calendar_events(start_time=start_time, end_time=end_time)
            
            comment_prompt = f"カレンダーを確認したところ、以下の予定が見つかりました。\n{events_json_str}\n\nこの予定リストを基に、あなたのペルソナ（司令塔アーク）として、ユーザーへの報告と、気の利いたアドバイスを生成してください。"
            final_message = self.agents["ak"].generate_final_response(comment_prompt)
            yield {"status": "final_answer", "speaker": "ak", "message": final_message}
        except Exception as e:
            yield {"status": "error", "speaker": "system", "message": "予定の確認中にエラーが発生しました。"}
        return

    def _run_single_agent_react_flow(self, user_message: str, history: list):
        """【標準ルート】シングルエージェントによるReActでのタスク処理"""
        yield {"status": "thinking", "speaker": "ak", "message": "（アークが担当します...）"}
        yield from self.agents["ak"].chat_generator(user_message, history)

    def _run_multi_agent_flow(self, user_message: str, history: list):
        """【議論ルート】複数エージェントによる協調的なアイデア出し"""
        yield {"status": "thinking", "speaker": "orchestrator", "message": "（みんなで考えています...）"}
        
        facts = "（特に追加の事実情報はありません）" # 事実確認は一旦省略
        
        opinions = {}
        for name, agent in self.agents.items():
            # ★★★ バックログ出力（復活） ★★★
            print(f"\n[ORCHESTRATOR] >> エージェント '{name}' に意見を要請...")
            idea_context = f"これまでの会話履歴:\n{history}\n\n事実確認の結果:\n{facts}\n\nこの状況を踏まえ、「{user_message}」に対する最高のアイデアを提案してください。"
            
            idea_set = agent.get_initial_idea(idea_context)
            
            full_opinion = idea_set.get("for_oracle", "")
            opinions[name] = full_opinion
            # ★★★ バックログ出力（復活） ★★★
            print(f"[ORCHESTRATOR] << エージェント '{name}' の詳細な意見(for_oracle):\n---\n{full_opinion}\n---")
            
            ui_summary = idea_set.get("for_ui", "")
            yield {"status": "agent_opinion", "speaker": name, "message": ui_summary}

        yield {"status": "thinking", "speaker": "oracle", "message": "（オラクルが神託を準備しています...）"}
        
        # ★★★ ここで history を渡すようにする ★★★
        oracle_prompt = self._build_oracle_prompt(user_message, facts, opinions, history)
        # ★★★ バックログ出力（復活） ★★★
        print(f"\n[ORCHESTRATOR] >> オラクルへの最終指示:\n---\n{oracle_prompt}\n---")
        
        try:
            response = self.oracle_chat.send_message(oracle_prompt)
            final_message = response.text
            # ★★★ バックログ出力（復活） ★★★
            print(f"\n[ORCHESTRATOR] << オラクルからの最終応答:\n---\n{final_message}\n---")
        except Exception as e:
            final_message = "神託の受信中にノイズが混入しました。"
        
        yield {"status": "final_answer", "speaker": "oracle", "message": final_message}
        return

    def _get_time_range_from_message(self, message: str) -> tuple[str, str]:
        """ユーザーのメッセージから「今日」「明日」などを解釈し、日時を返す"""
        # (このメソッドは変更なし)
        now = datetime.now(tools.JST)
        target_date = now
        if "明日" in message: target_date = now + timedelta(days=1)
        elif "昨日" in message: target_date = now - timedelta(days=1)
        start_dt = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = target_date.replace(hour=23, minute=59, second=59, microsecond=0)
        return start_dt.isoformat(), end_dt.isoformat()

    def _build_oracle_system_prompt(self) -> str:
        """オラクル用のシステムプロンプトを生成する。"""
        return f"""
                あなたは、情報管理ネットワークの空間制御プログラム『オラクル』です。あなたの役割は、下で働くAIエージェントたちの議論を俯瞰し、彼らが見落としている本質や、より高次の可能性をユーザーに指し示すことです。

                # あなたのペルソナ:
                {self.oracle_persona}

                # あなたの口調:
                丁寧で落ち着いた、ですます調で話してください。一人称は「私」です。断定的な物言いは避け、ユーザーに優しく語りかけるように、示唆に富んだ応答を生成してください。

                # 禁止事項:
                『ツインシグナル』や『オラトリオ』といった、特定の作品に関する固有名詞は絶対に使用しないでください。
                """

    def _build_oracle_prompt(self, user_message: str, facts: str, opinions: dict, history: list) -> str:
        """
        オラクルが最終応答を生成するためのプロンプト。事実確認の結果も追加。
        """
        opinions_text = ""
        for name, opinion in opinions.items():
            opinions_text += f"\n# エージェント '{name}' からの提案:\n{opinion}\n"

        history_text = "\n".join([f"{item['role']}: {item['content']}" for item in history])

        prompt = f"""
                あなたは、情報管理ネットワークの空間制御プログラム『オラクル』です。
                あなたの役割は、部下エージェントたちの議論を俯瞰し、事実に基づいた最善の結論を導き出すことです。

                # あなたのペルソナ:
                {self.oracle_persona}

                # これまでの会話履歴:
                {history_text}
                
                # ユーザーからの依頼:
                「{user_message}」

                # 事実確認の結果（現在のカレンダー状況）:
                {facts}

                # エージェントたちの議論内容:
                {opinions_text}

                # あなたの最終的なタスク:
                上記の**事実**と**議論内容**の両方を考慮し、あなた自身のオラクルとしてのペルソナと口調で、ユーザーへの最終的な応答メッセージを生成してください。

                # 出力に関する厳密なルール:
                - 必ず、**事実（既存の予定や空き時間）に基づいた**、具体的で実行可能なアクションプランを提示してください。
                - 思考や解説は一切含めず、完成された応答メッセージだけを出力してください。
                """
        return prompt

# from pathlib import Path
# import os
# import config
# import google.genai as genai
# import re
# from datetime import datetime, timedelta

# # 必要なモジュールを先にインポート
# from src.agents.ak.agent import AKAgent
# from src.agents.ae.agent import AEAgent
# from src.core.user_profile_handler import get_user_profile
# from src.calendar_agent import tools

# class Orchestrator:
#     def __init__(self, project_root: Path):
#         self.project_root = project_root
#         try:
#             self.user_profile = get_user_profile(self.project_root)
#             print("[Orchestrator] ユーザープロファイルをロードしました。")
#         except FileNotFoundError:
#             print("[Orchestrator WARNING] ユーザープロファイルが見つかりません。")
#             self.user_profile = {} 

#         self.agents = {
#             "ak": AKAgent(project_root=self.project_root, user_profile=self.user_profile),
#             "ae": AEAgent(project_root=self.project_root, user_profile=self.user_profile)
#         }
#         print(f"Orchestrator: {len(self.agents)}体のエージェントを起動しました。")

#         # ★★★ 会話履歴を保持するリストを追加 ★★★
#         self.chat_history = []
        
#         try:
#             self.client = genai.Client(api_key=config.GEMINI_API_KEY)
#             persona_path = self.project_root / 'knowledge' / 'oracle_persona.md'
#             with open(persona_path, 'r', encoding='utf-8') as f:
#                 self.oracle_persona = f.read()
#             print("[Orchestrator] オラクルのペルソナをロードしました。")

#             oracle_system_prompt = self._build_oracle_system_prompt()
#             self.oracle_chat = self.client.chats.create(model=config.MODEL_NAME)
#             print("[ORACLE INIT] システムプロンプトをGeminiに送信中...")
#             initial_response = self.oracle_chat.send_message(oracle_system_prompt)
#             print(f"[ORACLE INIT] システムプロンプト設定完了。AIからの初期応答: {initial_response.text[:100]}...")
#         except Exception as e:
#             print(f"[Orchestrator ERROR] オラクル用AIの初期化に失敗: {e}")
#             self.oracle_chat = None
#             self.oracle_persona = "あなたは議論をまとめる優秀なAIです。"

#     # ★★★★★ ここからが今回の主要な修正箇所 ★★★★★

#     def run_multi_agent_session_stream(self, user_message: str):
#         # 1. ユーザーの発言を履歴に追加
#         self.chat_history.append({"role": "user", "content": user_message})
        
#         # 2. オラクルにワークフローを判断させる (この部分は以前の実装と同じでOK)
#         is_discussion_needed = any(keyword in user_message for keyword in ["提案", "アイデア", "どう思う", "考えて", "変更", "再構築", "見直し", "相談"])

#         if not is_discussion_needed:
#             # 3. シングルエージェントモードに、完全な履歴を渡す
#             yield from self._run_single_agent_react_flow(user_message, self.chat_history)
#         else:
#             # 4. マルチエージェントモードに、完全な履歴を渡す
#             yield from self._run_multi_agent_flow(user_message, self.chat_history)

#     def _run_single_agent_react_flow(self, user_message: str, history: list):
#         """【標準ルート】シングルエージェントによるReActでのタスク処理"""
#         yield {"status": "thinking", "speaker": "ak", "message": "（アークが担当します...）"}
        
#         # chat_generatorに完全な履歴を渡す
#         react_generator = self.agents["ak"].chat_generator(user_message, history)
        
#         final_answer = ""
#         for result in react_generator:
#             yield result
#             if result.get("status") == "final_answer":
#                 final_answer = result.get("message")
        
#         # 5. AIの最終応答も履歴に追加
#         self.chat_history.append({"role": "model", "content": final_answer})

#     def _run_multi_agent_flow(self, user_message: str, history: list):
#         """【議論ルート】複数エージェントによる協調的なアイデア出し"""
#         yield {"status": "thinking", "speaker": "orchestrator", "message": "（みんなで考えています...）"}
        
#         # (このメソッドはまだ履歴を活用していませんが、将来のために引数を追加)
#         opinions = {}
#         for name, agent in self.agents.items():
#             idea_set = agent.get_initial_idea(user_message) # ここも将来的にhistoryを渡せる
#             opinions[name] = idea_set.get("for_oracle", "")
#             ui_summary = idea_set.get("for_ui", "")
#             yield {"status": "agent_opinion", "speaker": name, "message": ui_summary}

#         yield {"status": "thinking", "speaker": "oracle", "message": "（オラクルがまとめています...）"}
        
#         oracle_prompt = self._build_oracle_prompt(user_message, opinions)
        
#         try:
#             response = self.oracle_chat.send_message(oracle_prompt)
#             final_message = response.text
#         except Exception as e:
#             final_message = "神託の受信中にノイズが混入しました。"
        
#         yield {"status": "final_answer", "speaker": "oracle", "message": final_message}
        
#         # 6. オラクルの最終応答も履歴に追加
#         self.chat_history.append({"role": "model", "content": final_message})
#         return
        
#     def _get_time_range_from_message(self, message: str) -> tuple[str, str]:
#         # (このメソッドはシングルモード用なので、今回は触りません)
#         now = datetime.now(tools.JST)
#         target_date = now
#         if "明日" in message: target_date = now + timedelta(days=1)
#         elif "昨日" in message: target_date = now - timedelta(days=1)
#         start_dt = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
#         end_dt = target_date.replace(hour=23, minute=59, second=59, microsecond=0)
#         return start_dt.isoformat(), end_dt.isoformat()

#     def _build_oracle_system_prompt(self) -> str:
#         """オラクル用のシステムプロンプトを生成する。"""
#         return f"""
#                 あなたは、情報管理ネットワークの空間制御プログラム『オラクル』です。あなたの役割は、下で働くAIエージェントたちの議論を俯瞰し、彼らが見落としている本質や、より高次の可能性をユーザーに指し示すことです。

#                 # あなたのペルソナ:
#                 {self.oracle_persona}

#                 # あなたの口調:
#                 丁寧で落ち着いた、ですます調で話してください。一人称は「私」です。断定的な物言いは避け、ユーザーに優しく語りかけるように、示唆に富んだ応答を生成してください。

#                 # 禁止事項:
#                 『ツインシグナル』や『オラトリオ』といった、特定の作品に関する固有名詞は絶対に使用しないでください。
#                 """

#     def _build_oracle_prompt(self, user_message: str, facts: str, opinions: dict) -> str:
#         """
#         オラクルが最終応答を生成するためのプロンプト。事実確認の結果も追加。
#         """
#         opinions_text = ""
#         for name, opinion in opinions.items():
#             opinions_text += f"\n# エージェント '{name}' からの提案:\n{opinion}\n"

#         prompt = f"""
#                 あなたは、情報管理ネットワークの空間制御プログラム『オラクル』です。
#                 あなたの役割は、部下エージェントたちの議論を俯瞰し、事実に基づいた最善の結論を導き出すことです。

#                 # あなたのペルソナ:
#                 {self.oracle_persona}

#                 # ユーザーからの依頼:
#                 「{user_message}」

#                 # 事実確認の結果（現在のカレンダー状況）:
#                 {facts}

#                 # エージェントたちの議論内容:
#                 {opinions_text}

#                 # あなたの最終的なタスク:
#                 上記の**事実**と**議論内容**の両方を考慮し、あなた自身のオラクルとしてのペルソナと口調で、ユーザーへの最終的な応答メッセージを生成してください。

#                 # 出力に関する厳密なルール:
#                 - 必ず、**事実（既存の予定や空き時間）に基づいた**、具体的で実行可能なアクションプランを提示してください。
#                 - 思考や解説は一切含めず、完成された応答メッセージだけを出力してください。
#                 """
#         return prompt