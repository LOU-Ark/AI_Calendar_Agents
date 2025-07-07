# src/app.py
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from src.core.orchestrator import Orchestrator
import json
import os
import time

app = Flask(__name__)
orchestrator = Orchestrator()

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
        
        response_generator = None # 先に変数を定義
        try:
            response_generator = orchestrator.run_chat_stream(user_message)
            for response_part in response_generator:
                formatted_data = f"data: {json.dumps(response_part, ensure_ascii=False)}\n\n"
                yield formatted_data
                time.sleep(0.1)
            # ★★★ forループが正常に完了した場合のログ ★★★
            print("[APP] forループが正常に完了しました。")
        except Exception as e:
            print(f"[APP] generate_stream でエラーが発生: {e}")
            error_data = {"status": "error", "message": "サーバー内部でエラーが発生しました。"}
            formatted_error = f"data: {json.dumps(error_data)}\n\n"
            yield formatted_error
        finally:
            # ★★★ ストリームが正常終了しても、エラーで終了しても、必ずここが実行される ★★★
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
