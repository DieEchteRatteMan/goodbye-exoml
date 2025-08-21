import json
import time
import uuid
from flask import Flask, request, Response, stream_with_context, jsonify
import requests

app = Flask(__name__)

BACKEND_API_URL = 'https://107.23.44.190/api/chat'

# Headers based on the provided curl command
# Some headers like Content-Length and Host will be added by the requests library
HEADERS = {
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
    'Content-Type': 'application/json',
    'Origin': 'https://107.23.44.190',
    'Referer': 'https://107.23.44.190/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Linux"',
}

def format_to_openai_stream_chunk(id, model, content, finish_reason=None, usage=None):
    """Formats a message into an OpenAI-compatible stream chunk."""
    chunk = {
        "id": id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
            }
        ]
    }
    if content:
        chunk["choices"][0]["delta"]["content"] = content
    if finish_reason:
        chunk["choices"][0]["finish_reason"] = finish_reason
    
    # Add usage to the chunk, which is a non-standard but useful addition for streaming
    if usage:
        chunk["usage"] = usage
        
    return f"data: {json.dumps(chunk)}\n\n"

def process_backend_stream(backend_response, chat_id, model_name):
    """Processes the backend's custom stream and yields OpenAI-compatible chunks."""
    tool_call_info = {}

    for line in backend_response.iter_lines(decode_unicode=True):
        if not line:
            continue

        try:
            # The stream format is like 'f:{"json"}', '9:{"json"}', '0:"string"'
            # Find the first colon to separate the prefix from the content
            prefix, content_str = line.split(':', 1)
            
            # The content is always a JSON-encoded string or object
            content = json.loads(content_str)

            if prefix == '0': # Text chunk
                yield format_to_openai_stream_chunk(chat_id, model_name, content)
            
            elif prefix == '9': # Tool call invocation start
                # Store tool call details to format them later
                tool_call_id = content.get("toolCallId")
                if tool_call_id:
                    tool_call_info[tool_call_id] = {
                        "name": content.get("toolName"),
                        "args": content.get("args", {})
                    }

            elif prefix == 'a': # Tool call result
                result = content.get("result", {})
                answer = result.get("answer", "")
                sources = result.get("results", [])
                
                formatted_text = answer
                if sources:
                    formatted_text += "\n\n**Sources:**\n"
                    for source in sources:
                        title = source.get('title', 'N/A')
                        url = source.get('url', '#')
                        formatted_text += f"- [{title}]({url})\n"
                
                if formatted_text:
                    yield format_to_openai_stream_chunk(chat_id, model_name, formatted_text)

            elif prefix in ['e', 'd']: # End of stream
                finish_reason = "stop"
                if content.get("finishReason") == "tool-calls":
                    finish_reason = "tool_calls"
                
                usage = content.get("usage")
                
                # Yield a final chunk with finish reason and usage
                yield format_to_openai_stream_chunk(chat_id, model_name, None, finish_reason, usage)

        except (ValueError, IndexError) as e:
            print(f"Skipping malformed line: {line} ({e})")
            continue
    
    yield "data: [DONE]\n\n"


HTML_INTERFACE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Proxy Chat</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        body { font-family: sans-serif; display: flex; flex-direction: column; height: 100vh; margin: 0; background-color: #f0f0f0; }
        #messages { flex-grow: 1; overflow-y: auto; padding: 10px; border-bottom: 1px solid #ccc; background-color: #fff; }
        #form { display: flex; padding: 10px; border-top: 1px solid #ccc; background-color: #f0f0f0;}
        #input { flex-grow: 1; padding: 8px; border-radius: 5px; border: 1px solid #ccc; }
        button { padding: 8px 12px; margin-left: 10px; border-radius: 5px; border: none; background-color: #007bff; color: white; cursor: pointer; }
        .message { margin-bottom: 10px; padding: 8px; border-radius: 5px; max-width: 80%; }
        .user-message { background-color: #dcf8c6; align-self: flex-end; margin-left: auto; }
        .bot-message { background-color: #fff; align-self: flex-start; }
        #messages-container { display: flex; flex-direction: column; }
    </style>
</head>
<body>
    <div id="messages"><div id="messages-container"></div></div>
    <form id="form" action="">
        <input id="input" autocomplete="off" placeholder="Type a message..." /><button>Send</button>
    </form>
    <script>
        const form = document.getElementById('form');
        const input = document.getElementById('input');
        const messagesContainer = document.getElementById('messages-container');
        let conversationHistory = [];

        function addMessage(text, className) {
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message ' + className;
            messageDiv.innerHTML = marked.parse(text);
            messagesContainer.appendChild(messageDiv);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
            return messageDiv;
        }

        form.addEventListener('submit', async function(e) {
            e.preventDefault();
            if (input.value) {
                const userInput = input.value;
                addMessage(userInput, 'user-message');
                conversationHistory.push({ role: "user", content: userInput });
                input.value = '';

                const response = await fetch('/v1/chat/completions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        model: "exoml-search",
                        messages: conversationHistory,
                        stream: true
                    })
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let botMessageDiv = addMessage('', 'bot-message');
                let fullBotResponse = '';
                
                while (true) {
                    const { value, done } = await reader.read();

                    if (done) {
                        conversationHistory.push({ role: "assistant", content: fullBotResponse });
                        break;
                    }
                    
                    const chunk = decoder.decode(value, { stream: true });
                    const lines = chunk.split('\\n\\n');
                    
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            const dataStr = line.substring(6);
                            if (dataStr.trim() === '[DONE]') {
                                continue;
                            }
                            try {
                                const data = JSON.parse(dataStr);
                                if (data.choices && data.choices[0].delta && data.choices[0].delta.content) {
                                    fullBotResponse += data.choices[0].delta.content;
                                    botMessageDiv.innerHTML = marked.parse(fullBotResponse);
                                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                                }
                            } catch (e) {
                                console.error('Error parsing stream data:', e);
                            }
                        }
                    }
                }
            }
        });
    </script>
</body>
</html>
"""

@app.route('/proxyui')
def proxy_ui():
    return HTML_INTERFACE

@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    openai_request = request.json
    if not openai_request:
        return jsonify({"error": "Request must be a JSON"}), 400
        
    is_streaming = openai_request.get("stream", False)
    
    # Extract messages and model from the incoming request
    messages = openai_request.get("messages", [])
    model = openai_request.get("model", "exoml-search")

    # Construct the payload for the backend API
    # This is a simplified mapping; the backend might need more specific fields
    backend_payload = {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "messages": messages,
        "data": {},
        "sessionId": str(uuid.uuid4())
    }

    try:
        # Use stream=True to handle the response as a stream
        response = requests.post(
            BACKEND_API_URL,
            headers=HEADERS,
            json=backend_payload,
            stream=True,
            verify=False  # Corresponds to curl's --insecure flag
        )
        response.raise_for_status()

        if is_streaming:
            # Generate a unique ID for this chat completion
            chat_id = f"chatcmpl-{uuid.uuid4()}"
            # Return a streaming response
            return Response(stream_with_context(process_backend_stream(response, chat_id, model)), mimetype='text/event-stream')
        else:
            # Non-streaming logic: aggregate the response and return as a single JSON
            full_response_content = ""
            usage_data = None
            finish_reason = "stop"

            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    prefix, content_str = line.split(':', 1)
                    content = json.loads(content_str)

                    if prefix == '0':
                        full_response_content += content
                    elif prefix in ['e', 'd']:
                        usage_data = content.get("usage")
                        if content.get("finishReason") == "tool-calls":
                            finish_reason = "tool_calls"
                except (ValueError, IndexError):
                    continue # Skip malformed lines

            return jsonify({
                "id": f"chatcmpl-{uuid.uuid4()}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "usage": usage_data,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full_response_content,
                    },
                    "finish_reason": finish_reason
                }]
            })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    # To run this:
    # 1. Install dependencies: pip install Flask requests
    # 2. Run the script: python proxyintoopenai.py
    # 3. Send requests to http://127.0.0.1:5000/v1/chat/completions
    app.run(host="0.0.0.0", port=24461)