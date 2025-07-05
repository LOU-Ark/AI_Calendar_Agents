from flask import Flask, render_template, request, jsonify
from src.calendar_agent.agent import CalendarAgent
import json
import os

app = Flask(__name__)
agent = CalendarAgent()

@app.route("/")
def index():
    start_message = agent.start_message()
    return render_template("index.html", start_message=start_message)

@app.route("/chat", methods=["POST"])
def chat():
    user_input = request.json.get("message")
    if not user_input:
        return jsonify({"error": "メッセージがありません"}), 400
    response_data = agent.send_message_for_ui(user_input)
    return jsonify(response_data)

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
