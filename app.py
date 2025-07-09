# src/app.py
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from pathlib import Path
import sys
import json
import os
import time

# 1. このファイル(app.py)の絶対パスを基準に、プロジェクトのルートディレクトリを決定
PROJECT_ROOT = Path(__file__).resolve().parent

# 2. 'src'ディレクトリをPythonの検索パスに追加
#    これにより、`from src.core...`のようなインポートが安定する
sys.path.append(str(PROJECT_ROOT))

# 3. 必要なモジュールをインポート
from src.core.orchestrator import Orchestrator

# --- Flaskアプリケーションのインスタンスを生成 ---
app = Flask(__name__, 
            static_folder=str(PROJECT_ROOT / 'src/web/static'),
            template_folder=str(PROJECT_ROOT / 'src/web/templates'))

# 4. Orchestratorを初期化する際に、決定したPROJECT_ROOTを引数として渡す
orchestrator = Orchestrator(project_root=PROJECT_ROOT)

@app.route("/")
def index():
    return render_template("index.html")

@app.route('/api/chat', methods=['POST'])
def chat_api():
    data = request.get_json()
    user_message = data.get('message', '')
    if not user_message:
        return Response("Error: メッセージがありません", status=400)

    def generate_stream():
        print("[APP] generate_stream を開始します。")
        try:
            response_generator = orchestrator.run_multi_agent_session_stream(user_message)
            for response_part in response_generator:
                formatted_data = f"data: {json.dumps(response_part, ensure_ascii=False)}\n\n"
                yield formatted_data
            print("[APP] ストリームが正常に完了しました。")
        except Exception as e:
            print(f"[APP] generate_stream でエラーが発生: {e}")
            error_data = {"status": "error", "message": "サーバー内部でエラーが発生しました。"}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
        finally:
            print("[APP] finallyブロックが実行されました。ストリームを終了します。")
    return Response(generate_stream(), mimetype='text/event-stream')

@app.route("/delete_event", methods=["POST"])
def delete_event():
    event_id = request.json.get("event_id")
    if not event_id:
        return jsonify({"error": "イベントIDがありません"}), 400
    from src.calendar_agent import tools
    response_json = tools.delete_calendar_event(event_id)
    response = json.loads(response_json)
    return jsonify(response)

@app.route("/knowledge")
def knowledge():
    return render_template("knowledge.html")

@app.route("/add_knowledge", methods=["POST"])
def add_knowledge():
    data = request.get_json()
    filename = data.get("filename")
    content = data.get("content")
    if not filename or not content:
        return jsonify({"error": "ファイル名と内容は必須です"}), 400
    knowledge_dir = os.path.join(os.path.dirname(__file__), 'knowledge')
    os.makedirs(knowledge_dir, exist_ok=True)
    # セキュリティ: .txt/.md/.text/.csv/.tsv/.json/.yaml/.yml/.log/.ini/.conf/.cfg/.text/plainのみ許可
    allowed_exts = ['.txt', '.md', '.text', '.csv', '.tsv', '.json', '.yaml', '.yml', '.log', '.ini', '.conf', '.cfg']
    if not any(filename.endswith(ext) for ext in allowed_exts) and filename != 'text/plain':
        return jsonify({"error": "許可された拡張子のみアップロード可能です"}), 400
    file_path = os.path.join(knowledge_dir, filename)
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"message": f"{filename} を追加しました。"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/upload_knowledge", methods=["POST"])
def upload_knowledge():
    import os
    from werkzeug.utils import secure_filename
    file = request.files.get('file')
    if not file:
        return jsonify({"error": "ファイルがありません"}), 400
    filename = secure_filename(file.filename)
    allowed_exts = ('.txt', '.md', '.csv', '.json', '.doc', '.docx')
    if not filename.endswith(allowed_exts):
        return jsonify({"error": "許可された拡張子のみアップロード可能です"}), 400
    knowledge_dir = os.path.join(os.path.dirname(__file__), 'knowledge')
    os.makedirs(knowledge_dir, exist_ok=True)
    file_path = os.path.join(knowledge_dir, filename)
    try:
        file.save(file_path)
        return jsonify({"message": f"{filename} をアップロードしました。"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("======================================================")
    print("  AI Calendar Agent is ready!")
    print("")
    print("  Access it at: http://localhost:5001")
    print("  (Press Ctrl+C to stop the container)")
    print("======================================================")
    app.run(host="0.0.0.0", debug=True, port=5001)
