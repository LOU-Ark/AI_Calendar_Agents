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
        persona_path = os.path.join('knowledge', 'ak-persona.md')
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
        history = []
        
        # ★★★ 修正ポイント1: 無限ループを防ぐため、whileをforに変更 ★★★
        for _ in range(5): # 最大5回の思考ループ（安全対策）
            try:
                # プロンプト構築、Gemini呼び出し
                # (注: _build_react_prompt は存在しないため、既存の _build_user_prompt を使用します)
                
                # ★★★ ウィンドウイングの適用 ★★★
                # 対話履歴が長くなりすぎるのを防ぐため、最新10件のやりとりのみをプロンプトに含める
                WINDOW_SIZE = 10 
                recent_history = history[-WINDOW_SIZE:]

                context_for_prompt = "\n".join([f"{k}: {v}" for h in recent_history for k, v in h.items()])
                if not history:
                    context_for_prompt = f"ユーザー: {user_message}"
                
                react_prompt = self._build_user_prompt(context_for_prompt)
                ai_response = self._call_gemini(react_prompt)
                
                if not history:
                    history.append({"user": user_message})
                history.append({"ai": ai_response})

                parsed = self._parse_ai_response(ai_response)
                
                # ★★★ 修正ポイント2: actionの存在を安全にチェック ★★★
                action = parsed.get('action')

                if action == 'FinalAnswer':
                    final_message = parsed.get('final_answer', 'うまく言葉にできませんでした。')
                    yield {
                        "status": "final_answer",
                        "speaker": "ak",
                        "message": final_message,
                        "log": f"アーク：Final Answer: {final_message}"
                    }
                    # ★★★ 修正ポイント3: ジェネレータをここで明示的に終了させる！ ★★★
                    print("[AGENT] FinalAnswerを検知。ジェネレータを正常に終了します。")
                    return

                elif action and action != 'ParsingError' and action != 'ToolError':
                    # ツール実行のロジック
                    tool_name = action
                    tool_input = parsed.get('action_input', {})
                    yield {
                        "status": "tool_running",
                        "speaker": "ak",
                        "message": f"ツール『{tool_name}』を実行中...",
                        "log": f"ツール実行: {tool_name}({tool_input})"}
                    tool_result = self._run_tool(tool_name, tool_input)
                    history.append({"tool": tool_name, "result": tool_result})
                else:
                    # パースエラーなどの場合は、それを伝えて終了
                    error_message = parsed.get('action_input', 'AIの応答を解析できませんでした。')
                    yield { "status": "final_answer", "speaker": "ak",
                            "message": f"申し訳ありません、少し混乱しているようです。エラー: {error_message}",
                            "log": "パースエラーにより終了します。" }
                    return

            except Exception as e:
                print(f"[AGENT ERROR] chat_generatorでエラーが発生: {e}")
                import traceback
                traceback.print_exc()
                yield {"status": "error", "speaker": "ak", "message": "エージェント内部でエラーが発生しました。"}
                return

        # ループが5回に達した場合のフォールバック
        yield {
            "status": "final_answer",
            "speaker": "ak",
            "message": "うーん、少し考えがまとまらないようです。もう少し簡単な言葉で指示をいただけますか？",
            "log": "ループ回数上限に到達。"
        }

    def get_initial_idea(self, user_message: str) -> str:
        """
        複雑なツール使用はせず、自分のペルソナとユーザープロファイルに基づいて最初のアイデアだけを簡潔に返す
        """
        print("[AK AGENT] 最初のアイデアを生成中...")
        prompt = f"""
        # あなたのペルソナ:
        {self.persona}

        # サポート対象のユーザープロファイル:
        {self.user_profile}

        # ユーザーからの依頼:
        {user_message}

        # 指示:
        あなたのペルソナとユーザーの特性を考慮して、この依頼に対する最初のアイデアやアプローチを、箇条書きで簡潔に述べてください。
        ツール使用や複雑な思考は不要です。あくまで最初のブレインストーミングの素材としてください。
        """
        response = self.chat.send_message(prompt)
        return response.text

    def generate_final_response(self, prompt: str) -> str:
        """
        ReActループを使わず、与えられたプロンプトに対して単純に応答を生成する。
        Orchestratorが最終的な提案をまとめる際に使用する。
        """
        print("[AK AGENT] 最終応答を生成中...")
        # 既存のself.chatはReActループで状態が変化している可能性があるため、
        # 新しいチャットセッションをここで開始する方が安全。
        response_chat = self.client.chats.create(model=config.MODEL_NAME)
        response = response_chat.send_message(prompt)
        return response.text

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
        """
        AI応答を解析し、Action/Action Input/FinalAnswerを抽出。
        複数行や不正なJSONにも対応。
        """
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
                    parsed_input = json.loads(match.group(0))
                    return {"action": action, "action_input": parsed_input}
                else:
                    # JSONが見つからない場合もエラーとして扱う
                    raise json.JSONDecodeError("JSON object not found in Action Input", action_input_str, 0)
            
            # Action自体が見つからなかった場合
            return {"action": "ParsingError", "action_input": "Action not found in AI response."}

        except json.JSONDecodeError as e:
            print(f"[PARSING ERROR] Failed to parse JSON: {action_input_str} - Error: {e}")
            return {"action": "ParsingError", "action_input": f"Invalid JSON from AI: {action_input_str}"}
        except Exception as e:
            print(f"[PARSING ERROR] Unexpected error: {e}")
            return {"action": "ParsingError", "action_input": "An unexpected error occurred during parsing."}

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