# src/agents/ak/agent.py
import os
import time
import json
import config
import google.genai as genai
import re
from datetime import datetime, timezone, timedelta
from src.calendar_agent import tools

class AKAgent:
    def __init__(self, user_profile: str):
        persona_path = os.path.join(os.path.dirname(__file__), 'persona.md')
        with open(persona_path, 'r', encoding='utf-8') as f:
            self.persona = f.read()
        
        self.user_profile = user_profile
        print("アーク：a-kエージェント、起動完了です。")
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)

        # システムプロンプトを構築
        system_prompt = self._build_system_prompt()
        
        # チャットセッション作成時にシステムプロンプトを設定
        # ここではシステムプロンプトを最初のメッセージとして送信する方式を採用
        self.chat = self.client.chats.create(model=config.MODEL_NAME)
        print("[AGENT INIT] システムプロンプトをGeminiに送信中...")
        try:
            initial_response = self.chat.send_message(system_prompt)
            print(f"[AGENT INIT] システムプロンプト設定完了。AIからの初期応答: {initial_response.text[:100]}...")
        except Exception as e:
            print(f"[AGENT INIT ERROR] システムプロンプトの送信に失敗しました: {e}")
            raise e

    def chat_generator(self, user_message: str):
        FULL_PROMPT_LOGGING = False
        last_ai_thought = ""
        
        # ★★★ 履歴(context)の管理を修正 ★★★
        # 履歴はReActループの外で一貫して管理する
        # 最初のユーザーメッセージでコンテキストを開始
        context = f"ユーザー: {user_message}"
        print(f"[ReAct] ユーザー入力: {user_message}")

        for _ in range(5): # 最大5回のReActループ
            try:
                yield { "status": "thinking", "message": "（アークが考え中です...）", "log": "..." }
                
                user_prompt = self._build_user_prompt(context)
                
                if FULL_PROMPT_LOGGING:
                    print(f"[ReAct] ユーザープロンプト全文:\n{user_prompt}")
                else:
                    print("[ReAct] ユーザープロンプトを生成しました。")

                ai_response = self._call_gemini(user_prompt)
                print(f"[ReAct] Gemini応答:\n{ai_response}")
                
                context += f"\nアーク: {ai_response}" # 履歴にAIの思考全体を追加

                thought_match = re.search(r"Thought: ([\s\S]*?)(?=\nAction:)", ai_response)
                if thought_match:
                    last_ai_thought = thought_match.group(1).strip()
                
                parsed = self._parse_ai_response(ai_response)
                print(f"[ReAct] 解析結果: {parsed}")

                if parsed.get('action') == 'FinalAnswer':
                    final_message = str(parsed.get('final_answer', '...'))
                    yield {
                        "status": "final_answer",
                        "message": final_message,
                        "log": f"アーク：Final Answer: {final_message}"
                    }
                    print("[AGENT] FinalAnswerをyieldしました。ジェネレータを正常に終了します。")
                    return

                tool_name = parsed.get('action')
                tool_input = parsed.get('action_input', {})

                if not tool_name or tool_name in ['ParsingError', 'ToolError']:
                     context += f"\n[システムエラー] AIの応答形式が不正です。修正してください。"
                     continue # パースエラーの場合は、再度AIに思考させる

                yield { "status": "tool_running", "message": f"ツール『{tool_name}』を実行中...", "log": "..."}
                
                tool_result = self._run_tool(tool_name, tool_input)
                print(f"[ReAct] ツール実行結果: {tool_result}")
                
                context += f"\n[ツール実行: {tool_name}]\n[ツール結果: {tool_result}]" # ツール実行結果も履歴に追加

            except Exception as e:
                print(f"[AGENT ERROR] chat_generatorでエラー: {e}")
                import traceback
                traceback.print_exc()
                yield {"status": "error", "message": "エージェント内部でエラーが発生しました。"}
                return

        # ループ上限到達時の処理 (変更なし)
        # ...

    def _build_system_prompt(self) -> str:
        tools_description = """
- `add_calendar_event(summary: str, start_time: str, end_time: str)`: 新しいカレンダーイベントを作成します。
- `list_calendar_events(start_time: str, end_time: str)`: 指定された期間のカレンダーの予定リストを取得します。
- `delete_calendar_event(event_id: str)`: 指定されたIDのカレンダーイベントを削除します。
- `get_current_datetime()`: 現在の正確な日時（JST）をISO 8601形式で取得します。
        """
        
        system_prompt = f"""あなたは『アーク（a-k）』という、特定のユーザーをサポートする専属AIカレンダー司令塔です。

# あなたのペルソナ:
{self.persona}

# 最も重要な情報：サポート対象ユーザーの特性プロファイル
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
        return system_prompt

    def _build_user_prompt(self, context: str) -> str:
        jst = timezone(timedelta(hours=9))
        today_str = datetime.now(jst).strftime('%Y-%m-%d')
        
        user_prompt = f"""
# 現在の状況
- 今日の日付（JST）: {today_str}
- これまでのやり取り:
{context}

# あなたの思考と行動
"""
        return user_prompt

    def _call_gemini(self, prompt: str) -> str:
        try:
            response = self.chat.send_message(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[Gemini API Error] {e}")
            return "Thought: Gemini APIエラーが発生しました。\nAction: FinalAnswer\nAction Input: 申し訳ありません、AI側でエラーが発生しました。"

    def _parse_ai_response(self, ai_response: str) -> dict:
        action = None
        action_input_str = ""
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
        if action and action_input_str:
            try:
                match = re.search(r"\{.*\}", action_input_str, re.DOTALL)
                if match:
                    parsed_input = json.loads(match.group(0))
                    return {"action": action, "action_input": parsed_input}
                else:
                    raise json.JSONDecodeError("JSON object not found", action_input_str, 0)
            except json.JSONDecodeError as e:
                print(f"[PARSING ERROR] {e}")
                return {"action": "ToolError", "action_input": f"Invalid JSON format: {action_input_str}"}
        print(f"[PARSING WARNING] Could not parse action: {ai_response}")
        return {"action": "ParsingError", "action_input": "Could not parse AI response."}

    def _run_tool(self, tool_name: str, tool_args: dict) -> str:
        print(f"[ReAct] ツール呼び出し: {tool_name} 入力: {tool_args}")
        try:
            if tool_name == "add_calendar_event":
                return tools.add_calendar_event(**tool_args)
            elif tool_name == "list_calendar_events":
                return tools.list_calendar_events(**tool_args)
            elif tool_name == "delete_calendar_event":
                return tools.delete_calendar_event(**tool_args)
            elif tool_name == "get_current_datetime":
                return tools.get_current_datetime(**tool_args)
            else:
                return f"未対応ツール: {tool_name}"
        except Exception as e:
            print(f"ツール実行エラー: {e}")
            import traceback
            traceback.print_exc()
            return f"ツール実行エラー: {e}"