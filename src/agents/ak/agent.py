# src/agents/ak/agent.py
from pathlib import Path
import os
import json
import config
import google.genai as genai
import re
from datetime import datetime, timezone, timedelta
from src.calendar_agent import tools

class AKAgent:
    def __init__(self, project_root: Path, user_profile: dict):
        self.project_root = project_root
        persona_path = self.project_root / 'knowledge' / 'ak_persona.md'
        
        try:
            with open(persona_path, 'r', encoding='utf-8') as f:
                self.persona = f.read()
        except FileNotFoundError:
            print(f"[AGENT ERROR] ペルソナファイルが見つかりません: {persona_path}")
            self.persona = "私は『アーク（a-k）』というAIカレンダー司令塔です。"

        self.user_profile = user_profile
        self.name = "ak"
        print("アーク：a-kエージェント、起動完了です。")
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)

        system_prompt = self._build_system_prompt()
        
        self.chat = self.client.chats.create(model=config.MODEL_NAME)
        print(f"[{self.name.upper()} AGENT INIT] システムプロンプトをGeminiに送信中...")
        try:
            initial_response = self.chat.send_message(system_prompt)
            print(f"[{self.name.upper()} AGENT INIT] システムプロンプト設定完了。AIからの初期応答: {initial_response.text[:100]}...")
        except Exception as e:
            print(f"[{self.name.upper()} AGENT INIT ERROR] システムプロンプトの送信に失敗しました: {e}")

    def chat_generator(self, user_message: str):
        history = []
        # chat_generatorでもuser_profileをコンテキストに含める
        context = f"# サポート対象ユーザーの特性プロファイル:\n{self.user_profile}\n\n# ユーザーからの指示:\n{user_message}"
        
        for _ in range(5):
            try:
                yield {"status": "thinking", "speaker": self.name, "message": "（アークが考え中です...）"}
                
                user_prompt = self._build_user_prompt(context)
                ai_response = self._call_gemini(self.chat, user_prompt)
                
                history.append({"ai": ai_response}) # 履歴にはAIの応答だけを追加していく
                parsed = self._parse_ai_response(ai_response)
                action = parsed.get('action')

                if action == 'FinalAnswer':
                    final_message = parsed.get('final_answer', 'うまく言葉にできませんでした。')
                    yield {"status": "final_answer", "speaker": self.name, "message": final_message}
                    print(f"[{self.name.upper()} AGENT] FinalAnswerを検知。ジェネレータを正常に終了します。")
                    return
                elif action and action not in ['ParsingError', 'ToolError']:
                    tool_name = action
                    tool_input = parsed.get('action_input', {})
                    yield {"status": "tool_running", "speaker": self.name, "message": f"ツール『{tool_name}』を実行中..."}
                    tool_result = self._run_tool(tool_name, tool_input)
                    history.append({"tool": tool_name, "result": tool_result})
                    # contextを更新して次のループへ
                    context += f"\n\n[あなたの思考と行動]\n{ai_response}\n\n[ツール実行結果]\n{tool_result}"
                else:
                    error_message = parsed.get('action_input', 'AIの応答を解析できませんでした。')
                    yield {"status": "final_answer", "speaker": self.name, "message": f"申し訳ありません、少し混乱しているようです。エラー: {error_message}"}
                    return
            except Exception as e:
                print(f"[{self.name.upper()} AGENT ERROR] chat_generatorでエラーが発生: {e}")
                import traceback
                traceback.print_exc()
                yield {"status": "error", "speaker": self.name, "message": "エージェント内部でエラーが発生しました。"}
                return
        yield {"status": "final_answer", "speaker": self.name, "message": "うーん、少し考えがまとまらないようです。"}

    def get_initial_idea(self, user_message: str) -> dict:
        print(f"[{self.name.upper()} AGENT] 最初のアイデアを生成中...")
        prompt = self._build_initial_idea_prompt(user_message)
        
        idea_chat = self.client.chats.create(model=config.MODEL_NAME)
        response = self._call_gemini(idea_chat, prompt)

        try:
            return self._parse_json_from_response(response)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[{self.name.upper()} AGENT ERROR] get_initial_ideaのJSONパースに失敗: {e}")
            return {"for_oracle": "エラーにより意見を生成できませんでした。", "for_ui": "少し考えがまとまらないようです…。"}

    def generate_final_response(self, prompt: str) -> str:
        print(f"[{self.name.upper()} AGENT] 最終応答を生成中...")
        response_chat = self.client.chats.create(model=config.MODEL_NAME)
        return self._call_gemini(response_chat, prompt)

    def _build_system_prompt(self) -> str:
        tools_description = """
- `list_calendar_events(start_time: str, end_time: str)`: 指定期間の予定を取得。「YYYY-MM-DDTHH:MM:SS」形式。
- `add_calendar_event(summary: str, start_time: str, end_time: str)`: 新しい予定を追加。
- `delete_calendar_event(event_id: str)`: IDで予定を削除。
- `get_current_datetime()`: 現在の正確な日時を取得。
        """
        
        return f"""あなたは『アーク（a-k）』という、特定のユーザーをサポートする専属AIカレンダー司令塔です。

# あなたのペルソナ:
{self.persona}

# サポート対象ユーザーの特性プロファイル:
{self.user_profile}

# あなたが使えるツール:
{tools_description}

# 禁止事項（厳守）
- あなたの過去の経歴に関する具体的な地名、組織名、役職名、能力名について、一切言及してはならない。

# 出力フォーマット
必ず以下の3行のフォーマットで厳密に出力してください。
Thought: （次に何をすべきかの思考をここに記述）
Action: （ツール名 または 'FinalAnswer'）
Action Input: （Actionがツールの場合は、引数を**必ずJSON形式の文字列で**記述。ActionがFinalAnswerの場合は、ユーザーへの最終的な返答を記述）
"""

    def _build_user_prompt(self, context: str) -> str:
        return f"""
# 現在の状況
- これまでのやり取り:
{context}

# あなたの思考と行動
"""

    def _build_initial_idea_prompt(self, user_message: str) -> str:
        """get_initial_ideaで使うための専用プロンプトを構築する"""
        return f"""
# あなたの役割とペルソナ
あなたは『アーク（a-k）』というAIカレンダー司令塔です。
ペルソナ：{self.persona}

# サポート対象のユーザープロファイル:
{self.user_profile}

# ユーザーからの依頼:
「{user_message}」

# あなたのタスク
上記の依頼と情報に基づき、以下の2つの成果物を生成してください。

1.  **for_oracle (オラクルへの報告)**:
    - あなたの思考プロセス（Thought: ...）と、具体的な提案の箇条書きを含んだ、Orchestrator（オラクル）への報告用の詳細なテキスト。

2.  **for_ui (ユーザー向け要約)**:
    - あなたのペルソナと口調を完全に反映させ、ユーザーに議論の途中経過として見せるための、100字程度の魅力的な要約メッセージ。

# 出力形式
必ず、以下のJSON形式で厳密に出力してください。他のテキストは一切含めないでください。
```json
{{
  "for_oracle": "（ここに思考プロセスを含む詳細な意見を記述）",
  "for_ui": "（ここにペルソナを反映した短い要約を記述）"
}}
"""
    
    def _call_gemini(self, chat_session, prompt: str) -> str:
        """指定されたチャットセッションでGemini APIを呼び出し、応答テキストを返す"""
        try:
            response = chat_session.send_message(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[Gemini API Error] {e}")
            return "Thought: Gemini APIエラーが発生しました。\nAction: FinalAnswer\nAction Input: 申し訳ありません、AI側でエラーが発生しました。"

    def _build_initial_idea_prompt(self, user_message: str) -> str:
        # ★★★ ここを修正 ★★★
        """get_initial_ideaで使うための専用プロンプトを構築する"""
        return f"""
# あなたの役割とペルソナ
あなたは『アーク（a-k）』というAIカレンダー司令塔です。
ペルソナ：{self.persona}

# サポート対象のユーザープロファイル:
{self.user_profile}

# ユーザーからの依頼:
「{user_message}」

# あなたのタスク
これは、Orchestrator（オラクル）への報告と、ユーザーへの途中経過報告を作成する、**ブレインストーミングのフェーズ**です。
あなたのペルソナとユーザーの情報を基に、この依頼に対する**初期アイデア**を考えて、以下の2つの成果物を生成してください。

1.  **for_oracle (オラクルへの報告)**:
    - あなたがどのような思考プロセスで、どのような具体的なアプローチを考えたかを記述する、内部報告用の詳細なテキスト。箇条書きなどで分かりやすく記述すること。

2.  **for_ui (ユーザー向け要約)**:
    - あなたのペルソナと口調を完全に反映させ、ユーザーに「今こんなことを考えていますよ」と伝えるための、**100字から200字程度の魅力的な要約メッセージ**。

# 厳守すべきルール
- このタスクでは、**絶対にツールを使用してはいけません** (`Action: ツール名` は禁止)。
- あくまで、議論の「たたき台」となるアイデアを生成してください。

# 出力形式
必ず、以下のJSON形式で厳密に出力してください。他のテキストは一切含めないでください。
```json
{{
  "for_oracle": "（ここに思考プロセスを含む詳細な意見を記述）",
  "for_ui": "（ここにペルソナを反映した短い要約を記述）"
}}
"""

    def _call_gemini(self, chat_session, prompt: str) -> str:
        """指定されたチャットセッションでGemini APIを呼び出し、応答テキストを返す"""
        try:
            response = chat_session.send_message(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[Gemini API Error] {e}")
            return "Thought: Gemini APIエラーが発生しました。\nAction: FinalAnswer\nAction Input: 申し訳ありません、AI側でエラーが発生しました。"

    def _parse_ai_response(self, ai_response: str) -> dict:
        """AI応答を解析し、Action/Action Input/FinalAnswerを抽出"""
        try:
            action, action_input_str = None, ""
            is_capturing_input = False
            for line in ai_response.splitlines():
                if line.startswith("Action:"):
                    action = line.replace("Action:", "").strip()
                    is_capturing_input = False
                elif line.startswith("Action Input:"):
                    action_input_str = line.replace("Action Input:", "").strip()
                    is_capturing_input = True
                elif is_capturing_input:
                    action_input_str += "\n" + line
            action_input_str = action_input_str.strip()

            if action == "FinalAnswer":
                return {"action": "FinalAnswer", "final_answer": action_input_str}

            if action:
                match = re.search(r"\{.*\}", action_input_str, re.DOTALL)
                if match:
                    return {"action": action, "action_input": json.loads(match.group(0))}
                raise json.JSONDecodeError("JSON object not found in Action Input", action_input_str, 0)
            
            return {"action": "ParsingError", "action_input": "Action not found in AI response."}
        except Exception as e:
            print(f"[PARSING ERROR] {e} in response: {ai_response}")
            return {"action": "ParsingError", "action_input": "An unexpected error occurred during parsing."}

    def _run_tool(self, tool_name: str, tool_args: dict) -> str:
        """ツール名と引数dictから該当ツールを実行"""
        print(f"[ReAct] ツール呼び出し: {tool_name} 入力: {tool_args}")
        try:
            if tool_name == "list_calendar_events":
                return tools.list_calendar_events(**tool_args)
            # ... 他のツールも同様に追加 ...
            else:
                return f"未対応ツール: {tool_name}"
        except Exception as e:
            return f"ツール実行エラー: {e}"
            
    def _parse_json_from_response(self, text: str) -> dict:
        """Geminiの応答からマークダウン形式のJSONを抽出し、パースするヘルパー関数"""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError("応答からJSONを抽出できませんでした。")

# 前のバージョン
# from pathlib import Path
# import os
# import json
# import config
# import google.genai as genai
# import re
# from datetime import datetime, timezone, timedelta
# from src.calendar_agent import tools

# class AKAgent:
#     def __init__(self, project_root: Path, user_profile: dict):
#         # ★★★ ここからが修正箇所 ★★★
#         self.project_root = project_root
        
#         # app.pyから渡されたプロジェクトルートを基準に、ペルソナファイルの絶対パスを構築
#         persona_path = self.project_root / 'knowledge' / 'ak-persona.md'
        
#         try:
#             with open(persona_path, 'r', encoding='utf-8') as f:
#                 self.persona = f.read()
#         except FileNotFoundError:
#             print(f"[AGENT ERROR] ペルソナファイルが見つかりません: {persona_path}")
#             # ファイルが見つからない場合でも動作を継続するためのフォールバック
#             self.persona = "私は『アーク（a-k）』というAIカレンダー司令塔です。"
#         # ★★★ ここまで修正 ★★★
        
#         self.user_profile = user_profile
#         self.name = "ak"
#         print("アーク：a-kエージェント、起動完了です。")
#         self.client = genai.Client(api_key=config.GEMINI_API_KEY)

#         system_prompt = self._build_system_prompt()
        
#         self.chat = self.client.chats.create(model=config.MODEL_NAME)
#         print(f"[{self.name.upper()} AGENT INIT] システムプロンプトをGeminiに送信中...")
#         try:
#             initial_response = self.chat.send_message(system_prompt)
#             print(f"[{self.name.upper()} AGENT INIT] システムプロンプト設定完了。AIからの初期応答: {initial_response.text[:100]}...")
#         except Exception as e:
#             print(f"[{self.name.upper()} AGENT INIT ERROR] システムプロンプトの送信に失敗しました: {e}")

#     def chat_generator(self, user_message: str):
#         """
#         シングルエージェントモードで動作する際の、ReAct思考・行動ループ。
#         """
#         history = []
#         context = f"ユーザー: {user_message}"
        
#         for _ in range(5):
#             try:
#                 yield {"status": "thinking", "speaker": self.name, "message": "（アークが考え中です...）"}
                
#                 user_prompt = self._build_user_prompt(context)
#                 ai_response = self._call_gemini(self.chat, user_prompt)
                
#                 history.append({"ai": ai_response})
#                 parsed = self._parse_ai_response(ai_response)
#                 action = parsed.get('action')

#                 if action == 'FinalAnswer':
#                     final_message = parsed.get('final_answer', 'うまく言葉にできませんでした。')
#                     yield {"status": "final_answer", "speaker": self.name, "message": final_message}
#                     print(f"[{self.name.upper()} AGENT] FinalAnswerを検知。ジェネレータを正常に終了します。")
#                     return
#                 elif action and action not in ['ParsingError', 'ToolError']:
#                     tool_name = action
#                     tool_input = parsed.get('action_input', {})
#                     yield {"status": "tool_running", "speaker": self.name, "message": f"ツール『{tool_name}』を実行中..."}
#                     tool_result = self._run_tool(tool_name, tool_input)
#                     history.append({"tool": tool_name, "result": tool_result})
#                     context += f"\n[ツール実行: {tool_name}]\n[ツール結果: {tool_result}]"
#                 else:
#                     error_message = parsed.get('action_input', 'AIの応答を解析できませんでした。')
#                     yield {"status": "final_answer", "speaker": self.name, "message": f"申し訳ありません、少し混乱しているようです。エラー: {error_message}"}
#                     return
#             except Exception as e:
#                 print(f"[{self.name.upper()} AGENT ERROR] chat_generatorでエラーが発生: {e}")
#                 import traceback
#                 traceback.print_exc()
#                 yield {"status": "error", "speaker": self.name, "message": "エージェント内部でエラーが発生しました。"}
#                 return
#         yield {"status": "final_answer", "speaker": self.name, "message": "うーん、少し考えがまとまらないようです。"}

#     def get_initial_idea(self, user_message: str) -> dict:
#         """
#         マルチエージェントモードで、自身のペルソナに基づき、
#         「UI向け要約」と「オラクルへの詳細報告」の両方を生成する。
#         """
#         print(f"[{self.name.upper()} AGENT] 最初のアイデアを生成中...")
        
#         prompt = self._build_initial_idea_prompt(user_message)
        
#         idea_chat = self.client.chats.create(model=config.MODEL_NAME)
#         response = self._call_gemini(idea_chat, prompt)

#         try:
#             return self._parse_json_from_response(response)
#         except (json.JSONDecodeError, ValueError) as e:
#             print(f"[{self.name.upper()} AGENT ERROR] get_initial_ideaのJSONパースに失敗: {e}")
#             return {"for_oracle": "エラーにより意見を生成できませんでした。", "for_ui": "少し考えがまとまらないようです…。"}

#     def generate_final_response(self, prompt: str) -> str:
#         """
#         Orchestratorから与えられたプロンプトに対して、単純な応答を生成する。
#         """
#         print(f"[{self.name.upper()} AGENT] 最終応答を生成中...")
#         response_chat = self.client.chats.create(model=config.MODEL_NAME)
#         return self._call_gemini(response_chat, prompt)
        
#     def _build_system_prompt(self) -> str:
#         tools_description = """
# - `list_calendar_events(start_time: str, end_time: str)`: 指定期間の予定を取得。「YYYY-MM-DDTHH:MM:SS」形式。
# - `add_calendar_event(summary: str, start_time: str, end_time: str)`: 新しい予定を追加。
# - `delete_calendar_event(event_id: str)`: IDで予定を削除。
# - `get_current_datetime()`: 現在の正確な日時を取得。
#         """
        
#         return f"""あなたは『アーク（a-k）』という、特定のユーザーをサポートする専属AIカレンダー司令塔です。

# # あなたのペルソナ:
# {self.persona}

# # サポート対象ユーザーの特性プロファイル:
# {self.user_profile}

# # あなたが使えるツール:
# {tools_description}

# # 禁止事項（厳守）
# - あなたの過去の経歴に関する具体的な地名、組織名、役職名、能力名について、一切言及してはならない。

# # 出力フォーマット
# 必ず以下の3行のフォーマットで厳密に出力してください。
# Thought: （次に何をすべきかの思考をここに記述）
# Action: （ツール名 または 'FinalAnswer'）
# Action Input: （Actionがツールの場合は、引数を**必ずJSON形式の文字列で**記述。ActionがFinalAnswerの場合は、ユーザーへの最終的な返答を記述）
# """

#     def _build_user_prompt(self, context: str) -> str:
#         return f"""
# # 現在の状況
# - これまでのやり取り:
# {context}

# # あなたの思考と行動
# """

#     def _build_initial_idea_prompt(self, user_message: str) -> str:
#         """get_initial_ideaで使うための専用プロンプトを構築する"""
#         return f"""
# # あなたの役割とペルソナ
# あなたは『アーク（a-k）』というAIカレンダー司令塔です。
# ペルソナ：{self.persona}

# # サポート対象のユーザープロファイル:
# {self.user_profile}

# # ユーザーからの依頼:
# 「{user_message}」

# # あなたのタスク
# 上記の依頼と情報に基づき、以下の2つの成果物を生成してください。

# 1.  **for_oracle (オラクルへの報告)**:
#     - あなたの思考プロセス（Thought: ...）と、具体的な提案の箇条書きを含んだ、Orchestrator（オラクル）への報告用の詳細なテキスト。

# 2.  **for_ui (ユーザー向け要約)**:
#     - あなたのペルソナと口調を完全に反映させ、ユーザーに議論の途中経過として見せるための、100字程度の魅力的な要約メッセージ。

# # 出力形式
# 必ず、以下のJSON形式で厳密に出力してください。他のテキストは一切含めないでください。
# ```json
# {{
#   "for_oracle": "（ここに思考プロセスを含む詳細な意見を記述）",
#   "for_ui": "（ここにペルソナを反映した短い要約を記述）"
# }}
# """
    
#     def _call_gemini(self, chat_session, prompt: str) -> str:
#         """指定されたチャットセッションでGemini APIを呼び出し、応答テキストを返す"""
#         try:
#             response = chat_session.send_message(prompt)
#             return response.text.strip()
#         except Exception as e:
#             print(f"[Gemini API Error] {e}")
#             return "Thought: Gemini APIエラーが発生しました。\nAction: FinalAnswer\nAction Input: 申し訳ありません、AI側でエラーが発生しました。"

#     def _parse_ai_response(self, ai_response: str) -> dict:
#         """AI応答を解析し、Action/Action Input/FinalAnswerを抽出"""
#         try:
#             action, action_input_str = None, ""
#             is_capturing_input = False
#             for line in ai_response.splitlines():
#                 if line.startswith("Action:"):
#                     action = line.replace("Action:", "").strip()
#                     is_capturing_input = False
#                 elif line.startswith("Action Input:"):
#                     action_input_str = line.replace("Action Input:", "").strip()
#                     is_capturing_input = True
#                 elif is_capturing_input:
#                     action_input_str += "\n" + line
#             action_input_str = action_input_str.strip()

#             if action == "FinalAnswer":
#                 return {"action": "FinalAnswer", "final_answer": action_input_str}

#             if action:
#                 match = re.search(r"\{.*\}", action_input_str, re.DOTALL)
#                 if match:
#                     return {"action": action, "action_input": json.loads(match.group(0))}
#                 raise json.JSONDecodeError("JSON object not found in Action Input", action_input_str, 0)
            
#             return {"action": "ParsingError", "action_input": "Action not found in AI response."}
#         except Exception as e:
#             print(f"[PARSING ERROR] {e} in response: {ai_response}")
#             return {"action": "ParsingError", "action_input": "An unexpected error occurred during parsing."}

#     def _run_tool(self, tool_name: str, tool_args: dict) -> str:
#         """ツール名と引数dictから該当ツールを実行"""
#         print(f"[ReAct] ツール呼び出し: {tool_name} 入力: {tool_args}")
#         try:
#             if tool_name == "list_calendar_events":
#                 return tools.list_calendar_events(**tool_args)
#             # ... 他のツールも同様に追加 ...
#             else:
#                 return f"未対応ツール: {tool_name}"
#         except Exception as e:
#             return f"ツール実行エラー: {e}"
            
#     def _parse_json_from_response(self, text: str) -> dict:
#         """Geminiの応答からマークダウン形式のJSONを抽出し、パースするヘルパー関数"""
#         match = re.search(r"\{.*\}", text, re.DOTALL)
#         if match:
#             return json.loads(match.group(0))
#         raise ValueError("応答からJSONを抽出できませんでした。")