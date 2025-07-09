// static/js/script.js
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
            startChatStream(message);
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
    
    // --- サーバー通信関数 ---
    async function startChatStream(message) {
        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message }),
            });

            if (!response.ok) {
                throw new Error(`Server responded with ${response.status}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = '';

            while (true) {
                const { value, done } = await reader.read();
                if (done) {
                    break;
                }
                buffer += decoder.decode(value, { stream: true });
                
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
            addAgentOpinionMessage(speakerName, data.message, data.speaker); // speakerIdを渡す
        } else if (data.status === 'final_answer') {
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

    // ★★★★★ ここからが主要な修正箇所 ★★★★★

    function addMessage(message, speakerId, speakerName) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', `${speakerId}-message`);
        
        // アイコン要素を生成
        const iconHtml = `<div class="message-icon" style="background-image: url('/static/images/${speakerId}.png');"></div>`;
        
        // コンテンツ要素を生成
        let contentHtml = '<div class="message-content">';
        if (speakerId !== 'user') {
            contentHtml += `<div class="speaker-name">${speakerName}</div>`;
        }
        // 【課題2解決策】marked.js を使ってマークダウンをHTMLに変換
        const parsedMessage = marked.parse(message);
        contentHtml += `<div class="message-body">${parsedMessage}</div>`;
        contentHtml += '</div>';
        
        // ユーザーかAIかでアイコンの表示順序を入れ替える
        if (speakerId === 'user') {
            messageElement.innerHTML = contentHtml + iconHtml;
        } else {
            messageElement.innerHTML = iconHtml + contentHtml;
        }
        
        chatBox.appendChild(messageElement);
        scrollToBottom();
    }
    
    function addAgentOpinionMessage(speakerName, message, speakerId) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', 'agent-opinion-message');
        
        // アイコン要素を生成
        const iconHtml = `<div class="message-icon" style="background-image: url('/static/images/${speakerId}.png');"></div>`;

        // コンテンツ要素を生成
        let contentHtml = '<div class="message-content">';
        contentHtml += `<div class="agent-opinion-header">${speakerName}の意見：</div>`;
        // 【課題2解決策】こちらもマークダウン対応
        const parsedMessage = marked.parse(message);
        contentHtml += `<div class="agent-opinion-body">${parsedMessage}</div>`;
        contentHtml += '</div>';

        messageElement.innerHTML = iconHtml + contentHtml;
        chatBox.appendChild(messageElement);
        scrollToBottom();
    }

    // ... (updateStatusIndicator, scrollToBottom は変更なし) ...
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