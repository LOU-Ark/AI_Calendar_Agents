// static/js/script.js
document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const chatBox = document.getElementById('chat-box');
    const statusIndicator = document.getElementById('status-indicator'); // 追加

    let isFinalAnswerReceived = false;

    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const message = userInput.value.trim();
        if (!message) return;

        addMessage(message, 'user');
        userInput.value = '';
        userInput.disabled = true;
        chatForm.querySelector('button').disabled = true;
        // スピナー付きで初期ステータスを表示
        const spinnerHtml = '<div class="loading-spinner"></div>';
        statusIndicator.innerHTML = `${spinnerHtml} <span>アークに応答を依頼中...</span>`;

        try {
            const eventSource = new EventSourcePolyfill('/api/chat', {
                headers: { 'Content-Type': 'application/json' },
                payload: JSON.stringify({ message: message }),
                method: 'POST'
            });
            eventSource.onmessage = function(event) {
                removeLoadingIndicator && removeLoadingIndicator();
                const data = JSON.parse(event.data);
                handleAiResponse(data);
            };
            eventSource.onerror = function(err) {
                console.error("EventSource failed:", err);
                statusIndicator.innerHTML = ''; // ステータスをクリア
                if (isFinalAnswerReceived) {
                    console.log("Stream closed normally after final answer.");
                } else {
                    addMessage('AIとの通信中にエラーが発生しました。', 'ai');
                    // エラー時もUIを有効化
                    userInput.disabled = false;
                    chatForm.querySelector('button').disabled = false;
                    userInput.focus();
                }
                removeLoadingIndicator && removeLoadingIndicator();
                eventSource.close();
            };
        } catch (error) {
            statusIndicator.innerHTML = ''; // ステータスをクリア
            addMessage('エラーが発生しました。サーバーが起動しているか確認してください。', 'ai');
            userInput.disabled = false;
            chatForm.querySelector('button').disabled = false;
            userInput.focus();
        }
    });

    function handleAiResponse(data) {
        const spinnerHtml = '<div class="loading-spinner"></div>';

        if (data.status === 'thinking') {
            statusIndicator.innerHTML = `${spinnerHtml} <span>アークが考え中です...</span>`;
        } else if (data.status === 'tool_running') {
            statusIndicator.innerHTML = `${spinnerHtml} <span>アークがカレンダーを調べています...</span>`;
        } else if (data.status === 'final_answer') {
            statusIndicator.innerHTML = ''; // ステータスをクリア
            addMessage(data.message, 'ai');
            isFinalAnswerReceived = true; // ★★★ 最終応答を受信したらフラグを立てる
            // UIのロックを解除
            userInput.disabled = false;
            chatForm.querySelector('button').disabled = false;
            userInput.focus();
        } else if (data.reply) {
            statusIndicator.innerHTML = ''; // ステータスをクリア
            addMessage(data.reply, 'ai');
            // UIのロックを解除
            userInput.disabled = false;
            chatForm.querySelector('button').disabled = false;
            userInput.focus();
        }
    }

    // テキストからJSONイベントリストを抽出
    function extractEventListFromText(text) {
        const eventList = [];
        const regex = /```json([\s\S]*?)```/g;
        let match;
        while ((match = regex.exec(text)) !== null) {
            try {
                const event = JSON.parse(match[1]);
                if (event && event.start_time && event.end_time) {
                    eventList.push(event);
                }
            } catch (e) {}
        }
        return eventList;
    }

    // 予定リストを日本語で整形して表示
    function addEventListMessage(events) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', 'ai-message');
        let html = '<b>予定リスト</b><ul style="padding-left:1.2em;">';
        events.forEach(event => {
            const start = formatDateTime(event.start_time);
            const end = formatDateTime(event.end_time);
            html += `<li><b>${event.summary || '（タイトルなし）'}</b><br>` +
                `${start} ～ ${end}` +
                (event.location ? `<br>場所: ${event.location}` : '') +
                (event.description ? `<br>説明: ${event.description}` : '') +
                (event.id ? `<br><a href="https://calendar.google.com/calendar/u/0/r/eventedit/${event.id}" target="_blank">Googleカレンダーで開く</a>` : '') +
                '</li>';
        });
        html += '</ul>';
        messageElement.innerHTML = html;
        chatBox.appendChild(messageElement);
        scrollToBottom();
    }

    // 日時を日本語で整形
    function formatDateTime(dt) {
        try {
            const d = new Date(dt);
            return `${d.getFullYear()}年${d.getMonth()+1}月${d.getDate()}日 ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
        } catch {
            return dt;
        }
    }

    function addMessage(message, sender) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', `${sender}-message`);
        messageElement.innerHTML = `<p>${message.replace(/\n/g, '<br>')}</p>`;
        chatBox.appendChild(messageElement);
        scrollToBottom();
    }

    function addMessageWithDeleteOptions(message, candidates) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', 'ai-message');
        
        let html = `<p>${message}</p>`;
        html += '<ul class="delete-candidate-list">';
        candidates.forEach(event => {
            const startTime = new Date(event.start).toLocaleString('ja-JP');
            html += `<li data-event-id="${event.id}">${startTime} - ${event.summary}</li>`;
        });
        html += '</ul>';
        messageElement.innerHTML = html;
        
        chatBox.appendChild(messageElement);
        
        // 削除候補にクリックイベントを追加
        messageElement.querySelectorAll('.delete-candidate-list li').forEach(item => {
            item.addEventListener('click', async () => {
                const eventId = item.dataset.eventId;
                const eventSummary = item.textContent;
                
                addMessage(`「${eventSummary}」の削除を選択しました。`, 'user');
                addLoadingIndicator();

                try {
                    const response = await fetch('/delete_event', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ event_id: eventId }),
                    });
                    const result = await response.json();
                    removeLoadingIndicator();
                    addMessage(result.message || '削除処理が完了しました。', 'ai');
                } catch (error) {
                    removeLoadingIndicator();
                    addMessage('削除中にエラーが発生しました。', 'ai');
                }
            });
        });

        scrollToBottom();
    }
    
    function scrollToBottom() {
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    // チャット下部にGoogleカレンダー全体を開くボタンを追加（不要なら削除）
    const gcalBtn = document.getElementById('open-gcal-btn');
    if (gcalBtn) {
        gcalBtn.remove();
    }
});

// EventSourceのPOST対応Polyfill（fetch-SSEやevent-source-polyfill等を利用、または自作）
// ここでは簡易実装例を追加
window.EventSourcePolyfill = function(url, options) {
    // POSTでSSEを使うためのPolyfill（fetchでSSEストリームを受信）
    const controller = new AbortController();
    const listeners = {};
    fetch(url, {
        method: options.method || 'POST',
        headers: options.headers || {},
        body: options.payload || null,
        signal: controller.signal
    }).then(async res => {
        const reader = res.body.getReader();
        let buffer = '';
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += new TextDecoder().decode(value);
            let idx;
            while ((idx = buffer.indexOf('\n\n')) !== -1) {
                const chunk = buffer.slice(0, idx);
                buffer = buffer.slice(idx + 2);
                if (chunk.startsWith('data: ')) {
                    const data = chunk.slice(6);
                    if (listeners['message']) listeners['message']({ data });
                }
            }
        }
    }).catch(err => {
        if (listeners['error']) listeners['error'](err);
    });
    this.onmessage = null;
    this.onerror = null;
    listeners['message'] = (e) => { if (this.onmessage) this.onmessage(e); };
    listeners['error'] = (e) => { if (this.onerror) this.onerror(e); };
    this.close = () => controller.abort();
};
