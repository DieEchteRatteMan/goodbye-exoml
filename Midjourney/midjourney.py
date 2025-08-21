import os
import requests
import time
import json
import base64
import random
from flask import Flask, request, jsonify, render_template_string, Response
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# API Configuration
KEYS_FILE = 'mjkeys.txt'
GENERATION_API_URL = "https://api.kie.ai/api/v1/mj/generate"
RECORD_INFO_API_URL = "https://api.kie.ai/api/v1/mj/record-info"
IMGBB_API_KEY = "fa2c9168a76b6aa1eac132b498bf6257"
IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Midjourney Playground</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 2em; background-color: #f4f4f9; color: #333; }
        h1 { text-align: center; color: #0056b3; }
        form { display: flex; flex-direction: column; max-width: 600px; margin: 2em auto; padding: 2em; background: white; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        label { margin-top: 1em; margin-bottom: 0.5em; font-weight: bold; }
        input[type="text"], select { width: 100%; padding: 0.8em; border: 1px solid #ccc; border-radius: 4px; font-size: 1em; box-sizing: border-box; }
        button { margin-top: 1.5em; padding: 0.8em 1.2em; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1em; transition: background-color 0.3s; }
        button:hover { background-color: #0056b3; }
        button:disabled { background-color: #ccc; cursor: not-allowed; }
        #result { margin-top: 2em; text-align: center; }
        .image-gallery { display: flex; flex-wrap: wrap; justify-content: center; gap: 1em; margin-top: 1em; }
        img { max-width: 100%; height: auto; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .error { color: #d9534f; font-weight: bold; }
        .spinner { display: none; margin: 2em auto; width: 40px; height: 40px; border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; animation: spin 1s linear infinite; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <h1>Midjourney Playground</h1>
    <form id="generate-form">
        <label for="prompt">Prompt:</label>
        <input type="text" id="prompt" name="prompt" required>
        <label for="model">Model:</label>
        <select id="model" name="model">
            <option value="midjourney-v7">Version 7</option>
            <option value="midjourney-v6.1">Version 6.1</option>
            <option value="midjourney-v6">Version 6</option>
            <option value="midjourney-v5.2">Version 5.2</option>
            <option value="midjourney-v5.1">Version 5.1</option>
            <option value="midjourney-niji6">Niji 6</option>
        </select>
        <label for="size">Size (Aspect Ratio):</label>
        <select id="size" name="size">
            <option value="1024x1024">1024x1024 (1:1)</option>
            <option value="1792x1024">1792x1024 (16:9)</option>
            <option value="1024x1792">1024x1792 (9:16)</option>
        </select>
        <button type="submit" id="submit-button">Generate Image</button>
    </form>
    <div class="spinner" id="spinner"></div>
    <div id="result"></div>
    <script>
        document.getElementById('generate-form').addEventListener('submit', async function(event) {
            event.preventDefault();
            const form = event.target;
            const resultDiv = document.getElementById('result');
            const spinner = document.getElementById('spinner');
            const submitButton = document.getElementById('submit-button');
            resultDiv.innerHTML = '';
            spinner.style.display = 'block';
            submitButton.disabled = true;
            const formData = { prompt: form.prompt.value, model: form.model.value, size: form.size.value };
            try {
                const response = await fetch('/v1/images/generations', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(formData)
                });
                const data = await response.json();
                if (response.ok && data.data) {
                    const gallery = document.createElement('div');
                    gallery.className = 'image-gallery';
                    data.data.forEach(item => {
                        const img = document.createElement('img');
                        img.src = item.url;
                        img.alt = 'Generated Image';
                        gallery.appendChild(img);
                    });
                    resultDiv.appendChild(gallery);
                } else {
                    resultDiv.innerHTML = `<p class="error">Error: ${data.error || 'An unknown error occurred.'}</p>`;
                }
            } catch (error) {
                resultDiv.innerHTML = `<p class="error">Error: ${error.message}</p>`;
            } finally {
                spinner.style.display = 'none';
                submitButton.disabled = false;
            }
        });
    </script>
</body>
</html>
"""

def get_keys():
    if not os.path.exists(KEYS_FILE): return []
    with open(KEYS_FILE, 'r') as f:
        return [line.strip() for line in f if line.strip()]

def save_keys(keys):
    with open(KEYS_FILE, 'w') as f:
        for key in keys: f.write(f"{key}\n")

def size_to_aspect_ratio(size):
    return {"1024x1024": "1:1", "1792x1024": "16:9", "1024x1792": "9:16"}.get(size, "1:1")

def upload_to_imgbb(image_content):
    try:
        payload = {'key': IMGBB_API_KEY, 'image': base64.b64encode(image_content)}
        response = requests.post(IMGBB_UPLOAD_URL, data=payload,stream=True)
        response.text
        response_json = response.json()
        if response.status_code == 200 and response_json.get('data', {}).get('url'):
            imgbb_url = response_json['data']['url']
            logging.info(f"Successfully uploaded to ImgBB: {imgbb_url}")
            return imgbb_url
        else:
            logging.error(f"ImgBB upload failed: {response.text}")
            return None
    except Exception as e:
        logging.error(f"An error occurred during ImgBB upload: {e}")
        return None

#@app.route('/')
#def index():
#    return render_template_string(HTML_TEMPLATE)

@app.route('/v1/images/generations', methods=['POST'])
def generate_image_api():
    req_data = request.get_json()

    def streamer(data):
        keys = get_keys()
        if not keys:
            yield f'{json.dumps({"error": "No API keys available."})}\n\n'
            return

        if not data:
            yield f'{json.dumps({"error": "Invalid JSON."})}\n\n'
            return

        prompt = data.get('prompt')
        if not prompt:
            yield f'{json.dumps({"error": "A prompt is required."})}\n\n'
            return
        prompt += ""
        model = data.get('model', 'midjourney-v7')
        size = data.get('size', '1024x1024')
        logging.info(f"Received request: prompt='{prompt}', model='{model}', size='{size}'")

        version = model.replace('midjourney-v', '')
        aspect_ratio = size_to_aspect_ratio(size)

        payload = {
            "taskType": "mj_txt2img", "speed": "relaxed", "prompt": prompt,
            "aspectRatio": aspect_ratio, "version": version, "stylization": 100, "weirdness": 0
        }
        logging.info(f"Submitting task with payload: {payload}")

        task_id = None
        headers = None
        response_json = None

        while keys:
            api_key = keys[0]
            headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
            logging.info(f"Trying key ending in ...{api_key[-4:]}")

            response = None
            try:
                response = requests.post(GENERATION_API_URL, headers=headers, json=payload, stream=True)
                response_json = response.json()

                if response.status_code == 200 and response_json.get('code') == 200:
                    task_id = response_json.get('data', {}).get('taskId')
                    if task_id:
                        logging.info(f"Key successful. Task ID: {task_id}")
                        break  # Success, exit key loop
                    else:
                        logging.error("API success but no task ID from response.")
                        # This is a server-side issue, not a key issue, so we abort.
                        yield f'{json.dumps({"error": "API success but failed to get task ID."})}\n\n'
                        return
                elif response_json.get('code') in [401, 402, 403]:
                    logging.warning(f"Key failed with code {response_json.get('code')}. Removing key.")
                    keys.pop(0)
                    save_keys(keys)
                    continue  # Try next key
                else:
                    logging.error(f"API Error: {response.text}")
                    yield f'{json.dumps({"error": f"API Error: {response.text}"})}\n\n'
                    return
            except requests.exceptions.RequestException as e:
                logging.error(f"Request failed: {e}")
                yield f'{json.dumps({"error": f"Request failed: {str(e)}"})}\n\n'
                return
            except json.JSONDecodeError:
                error_text = response.text if response else "Unknown response"
                logging.error(f"Failed to decode JSON from response: {error_text}")
                yield f'{json.dumps({"error": "Failed to decode API response."})}\n\n'
                return

        if not task_id:
            yield f'{json.dumps({"error": "All available API keys failed."})}\n\n'
            return

        logging.info(f"Task submitted successfully. Task ID: {task_id}")

        yield "{"
        while True:
            yield ' ' * random.randint(0, 9)  # SSE comment for keep-alive
            time.sleep(5)
            logging.info(f"Polling for task ID: {task_id}")

            poll_response = None
            try:
                poll_response = requests.get(f"{RECORD_INFO_API_URL}?taskId={task_id}", headers=headers, stream=True)
                poll_json = poll_response.json()

                if poll_response.status_code != 200 or poll_json.get('code') != 200:
                    logging.error(f"Polling failed: {poll_response.text}")
                    yield f'{json.dumps({"error": f"Polling failed: {poll_response.text}"})[1:]}\n\n'
                    return

                task_data = poll_json.get('data', {})
                success_flag = task_data.get('successFlag')
                logging.info(f"Current task status: {success_flag} ({task_data.get('msg', 'N/A')})")

                if success_flag == 1:
                    result_info = task_data.get('resultInfoJson', {})
                    if isinstance(result_info, str):
                        try:
                            result_info = json.loads(result_info)
                        except json.JSONDecodeError:
                            logging.error("Failed to parse resultInfoJson string.")
                            yield f'{json.dumps({"error": "Failed to parse resultInfoJson."})[1:]}\n\n'
                            return

                    original_urls = [item.get('resultUrl') for item in result_info.get('resultUrls', []) if item.get('resultUrl')]
                    logging.info(f"Task successful. Original URLs: {original_urls}")

                    new_urls = []
                    for url in original_urls:
                        try:
                            logging.info(f"Downloading image from: {url}")
                            image_response = requests.get(url, stream=True)
                            if image_response.status_code == 200:
                                imgbb_url = upload_to_imgbb(image_response.content)
                                if imgbb_url:
                                    new_urls.append(imgbb_url)
                            else:
                                logging.error(f"Failed to download image from {url}. Status: {image_response.status_code}")
                        except requests.exceptions.RequestException as e:
                            logging.error(f"Error downloading image {url}: {e}")

                    logging.info(f"Final ImgBB URLs: {new_urls}")
                    final_json = json.dumps({"created": int(time.time()), "data": [{"url": u} for u in new_urls]})
                    yield f'{final_json[1:]}\n\n'
                    return
                elif success_flag in [2, 3]:
                    logging.error(f"Image generation failed. Reason: {task_data.get('msg', 'Unknown')}")
                    yield f'{json.dumps({"error": f"Generation failed: Unknown"})}\n\n'
                    return
            except requests.exceptions.RequestException as e:
                logging.error(f"Polling request failed: {e}")
                yield f'{json.dumps({"error": f"Polling request failed: {str(e)}"})[1:]}\n\n'
                return
            except json.JSONDecodeError:
                error_text = poll_response.text if poll_response else "Unknown response"
                logging.error(f"Failed to decode JSON from polling response: {error_text}")
                yield f'{json.dumps({"error": "Failed to decode API polling response."})[1:]}\n\n'
                return

    return Response(streamer(req_data), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=24460)