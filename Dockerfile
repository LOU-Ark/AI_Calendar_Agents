# syntax=docker/dockerfile:1
FROM python:3.10-slim

# 環境変数でPYTHONPATHを設定し、srcディレクトリをPythonの検索パスに追加
ENV PYTHONPATH="${PYTHONPATH}:/app/src"

# 作業ディレクトリを設定
WORKDIR /app

# 必要なライブラリを先にインストールしてキャッシュを効かせる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのソースコードをコピー
COPY . .

# docker-entrypoint.shに実行権限を付与
RUN chmod +x /app/docker-entrypoint.sh

# ポート5001を公開
EXPOSE 5001

# docker-entrypoint.shを起動コマンドとして設定
CMD ["/app/docker-entrypoint.sh"]
