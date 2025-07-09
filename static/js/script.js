//  static/js/script.js
document.addEventListener('DOMContentLoaded', () => {
    // --- HTML要素の取得 ---
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const chatBox = document.getElementById('chat-box');
    const statusIndicator = document.getElementById('status-indicator'); 

    // --- イベントリスナーの設定 ---
    if (chatForm) {
        chatForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const message = userInput.value.trim();
            if (!message) return;

            addMessage(message, 'user', 'あなた');
            userInput.value = '';
            lockUi();
            startChatStream(message); // ストリーミング処理を開始
        });
    }

    // --- UI制御関数 ---
    function lockUi() {
        userInput.disabled = true;
        chatForm.querySelector('button').disabled = true;
        updateStatusIndicator('AIが応答を準備中です...');
    }

    function unlockUi() {
        updateStatusIndicator('');
        userInput.disabled = false;
        chatForm.querySelector('button').disabled = false;
        userInput.focus();
    }
    
    // ★★★★★ ここを全面的に書き換えます ★★★★★
    async function startChatStream(message) {
        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message: message }),
            });

            if (!response.ok) {
                throw new Error(`Server responded with ${response.status}`);
            }

            // ストリームを読み取るためのリーダーを取得
            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = '';

            // データを少しずつ読み取るループ
            while (true) {
                const { value, done } = await reader.read();
                if (done) {
                    // ストリームが正常に終了した
                    console.log("Stream finished.");
                    break;
                }

                // 受信したデータを文字列に変換し、バッファに追加
                buffer += decoder.decode(value, { stream: true });
                
                // バッファからSSEメッセージ形式（"data: {...}\n\n"）を抽出
                let idx;
                while ((idx = buffer.indexOf('\n\n')) !== -1) {
                    const line = buffer.slice(0, idx);
                    buffer = buffer.slice(idx + 2);
                    
                    if (line.startsWith('data: ')) {
                        const jsonData = line.slice(6);
                        try {
                            const data = JSON.parse(jsonData);
                            handleAiResponse(data);
                        } catch (e) {
                            console.error("Error parsing SSE data:", jsonData, e);
                        }
                    }
                }
            }

        } catch (error) {
            console.error("Chat stream failed:", error);
            addMessage('AIとの通信に失敗しました。', 'system', 'システム');
        } finally {
            // 正常終了でもエラーでも、最後にUIをアンロックする
            unlockUi();
        }
    }

    // --- 表示処理関数 ---
    function handleAiResponse(data) {
        const speakerName = getSpeakerName(data.speaker);

        if (data.status === 'thinking' || data.status === 'tool_running') {
            updateStatusIndicator(data.message);
        } else if (data.status === 'agent_opinion') {
            updateStatusIndicator('議論をまとめています...'); 
            addAgentOpinionMessage(speakerName, data.message);
        } else if (data.status === 'final_answer') {
            // 最終応答の場合は、ステータス表示を消してからメッセージを表示
            updateStatusIndicator('');
            addMessage(data.message, data.speaker, speakerName);
        }
    }
    
    function getSpeakerName(speakerId) {
        const names = {
            'ak': 'アーク', 'ae': 'エル', 'oracle': 'オラクル',
            'user': 'あなた', 'system': 'システム'
        };
        return names[speakerId] || 'AI';
    }

    function addMessage(message, speakerId, speakerName) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', `${speakerId}-message`);
        
        let html = '';
        if (speakerId !== 'user') {
            html += `<div class="speaker-name">${speakerName}</div>`;
        }
        html += `<p>${message.replace(/\n/g, '<br>')}</p>`;
        
        messageElement.innerHTML = html;
        chatBox.appendChild(messageElement);
        scrollToBottom();
    }
    
    function addAgentOpinionMessage(speakerName, message) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', 'agent-opinion-message');
        
        const summary = (message.length > 150) ? message.substring(0, 150) + '...' : message;

        let html = `<div class="agent-opinion-header">${speakerName}の意見：</div>`;
        html += `<div class.agent-opinion-body">${summary.replace(/\n/g, '<br>')}</div>`;
        
        messageElement.innerHTML = html;
        chatBox.appendChild(messageElement);
        scrollToBottom();
    }

    function updateStatusIndicator(text) {
        if (!statusIndicator) return;
        if (text) {
            statusIndicator.innerHTML = `<div class="loading-spinner"></div> <span>${text}</span>`;
            statusIndicator.style.display = 'flex';
        } else {
            statusIndicator.style.display = 'none';
        }
    }

    function scrollToBottom() {
        chatBox.scrollTop = chatBox.scrollHeight;
    }
});