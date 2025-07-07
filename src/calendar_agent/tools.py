# src/calendar_agent/tools.py

import os
import json
from datetime import datetime, timedelta, timezone
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import config
import pytz # JSTの定義にpytzを使うのがより堅牢です

# --- タイムゾーンの定義 (pytz推奨) ---
JST = pytz.timezone('Asia/Tokyo')

def get_calendar_service():
    """Google Calendar APIのサービス（操作の本体）を取得する関数"""
    # ... (この部分は変更なし) ...
    creds = None
    if os.path.exists(config.GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(config.GOOGLE_TOKEN_FILE, config.GOOGLE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(config.GOOGLE_CREDS_FILE, config.GOOGLE_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(config.GOOGLE_TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)

# ▼▼▼ 以下、AIが呼び出すツール群 ▼▼▼

def add_calendar_event(summary: str, start_time: str, end_time: str, is_all_day: bool = False, description: str = None, location: str = None) -> str:
    """
    新しいカレンダーイベントを作成します。時間はJSTとして扱います。
    """
    # ... (この関数は変更なし) ...
    print(f"🛠️ ツール実行: add_calendar_event (タイトル: {summary})")
    service = get_calendar_service()
    event = {
        'summary': summary,
    }
    if is_all_day:
        event['start'] = {'date': start_time[:10]}
        event['end'] = {'date': end_time[:10]}
    else:
        event['start'] = {'dateTime': start_time, 'timeZone': 'Asia/Tokyo'}
        event['end'] = {'dateTime': end_time, 'timeZone': 'Asia/Tokyo'}
    if description:
        event['description'] = description
    if location:
        event['location'] = location
    
    try:
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return json.dumps({
            'status': 'success',
            'message': f"予定『{summary}』を追加しました。",
            'eventId': created_event.get('id')
        })
    except Exception as e:
        return json.dumps({
            'status': 'error',
            'message': f"予定追加時にエラーが発生しました: {e}"
        })

def _parse_datetime_str(date_str: str, is_end_time: bool = False) -> str:
    """
    日付文字列をRFC3339形式に変換する。
    """
    # ... (この関数は変更なし) ...
    now = datetime.now(JST)
    date_str = date_str.strip().lower()
    if "today" in date_str:
        target_date = now
    elif "tomorrow" in date_str:
        target_date = now + timedelta(days=1)
    else:
        target_date = None
    if target_date or len(date_str) == 10:
        if not target_date:
            try:
                target_date = datetime.fromisoformat(date_str)
            except ValueError:
                return now.isoformat()
        if is_end_time:
            dt = target_date.replace(hour=23, minute=59, second=59, microsecond=0)
        else:
            dt = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        if dt.tzinfo is None:
            dt = JST.localize(dt)
        return dt.isoformat()
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = JST.localize(dt)
        return dt.isoformat()
    except ValueError:
        print(f"[TOOL WARNING] 不正な日付形式: {date_str}")
        return now.isoformat()

def list_calendar_events(start_time: str, end_time: str) -> str:
    """
    指定された期間のカレンダーの予定リストを取得します。
    """
    # ... (この関数は変更なし) ...
    start_time_parsed = _parse_datetime_str(start_time, is_end_time=False)
    end_time_parsed = _parse_datetime_str(end_time, is_end_time=True)
    print(f"🛠️ ツール実行: list_calendar_events (期間: {start_time_parsed} - {end_time_parsed})")
    service = get_calendar_service()
    events_result = service.events().list(
        calendarId="primary",
        timeMin=start_time_parsed,
        timeMax=end_time_parsed,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    events = events_result.get("items", [])
    if not events:
        return json.dumps({"events": [], "message": "指定された期間に予定はありませんでした。"})
    
    simplified_events = [{
        "id": event["id"],
        "summary": event.get("summary", "（タイトルなし）"),
        "start": event["start"].get("dateTime", event["start"].get("date")),
        "end": event["end"].get("dateTime", event["end"].get("date")),
    } for event in events]
    return json.dumps({"events": simplified_events})

def delete_calendar_event(event_id: str) -> str:
    """
    指定されたIDのカレンダーイベントを削除します。
    """
    # ... (この関数は変更なし) ...
    print(f"🛠️ ツール実行: delete_calendar_event (ID: {event_id})")
    service = get_calendar_service()
    try:
        service.events().delete(calendarId='primary', eventId=event_id).execute()
        return json.dumps({
            "status": "success",
            "message": f"予定（ID: {event_id}）を削除しました。"
        })
    except HttpError as error:
        return json.dumps({
            "status": "error",
            "message": f"予定の削除中にエラーが発生しました: {error}"
        })

# ★★★★★ ここからが追記部分 ★★★★★

def get_current_datetime() -> str:
    """
    現在の正確な日時（JST）をISO 8601形式の文字列で取得します。
    ユーザーが日付や時刻について尋ねたり、提示された情報に疑問を呈した場合に、事実確認のために使用します。
    引数は不要です。
    """
    now = datetime.now(JST)
    current_time_str = now.isoformat()
    print(f"🛠️ ツール実行: get_current_datetime (現在時刻: {current_time_str})")
    
    # AIが解釈しやすいようにJSON形式で返す
    return json.dumps({
        "current_datetime": current_time_str,
        "message": f"現在の正確な日時は {current_time_str} です。"
    })