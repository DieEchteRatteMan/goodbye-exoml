import requests
import time
import random
import os
import threading
import json
import asyncio
from flask import Flask, request, render_template_string, jsonify, Response, stream_with_context
from werkzeug.utils import secure_filename
from datetime import timedelta, datetime

app = Flask(__name__)

# Rate limiting configuration
request_timestamps = {}
RATE_LIMIT_PERIOD = timedelta(hours=1)  # 1 request per hour

# HTML template for the frontend
HTML_CONTENT = open('page.html','r').read()

@app.route('/', methods=['GET'])
def index():
    return render_template_string(HTML_CONTENT)

# Anondrop Upload Function
def upload_image_to_anondrop(image_file):
    """
    Uploads an image file to anondrop.net and returns the public URL.
    """
    if not image_file:
        return None

    # Save the file temporarily
    filename = secure_filename(image_file.filename)
    temp_filepath = os.path.join('/tmp', filename) # Using /tmp for temporary storage
    image_file.save(temp_filepath)

    try:
        # Prepare for upload
        files = {'file': open(temp_filepath, 'rb')}
        response = requests.post('https://anondrop.net/upload', files=files,stream=True)
        response.raise_for_status() # Raise an HTTPError for bad responses

        # Parse the HTML response to get the URL
        # The structure appears to be embedded within HTML tags
        try:
            # Example: assuming the URL is within the first tag after splitting by '>'
            # and before the first '<' after that. This is based on the parsing in generate_4o_image
            parts = response.text.split('>')
            if len(parts) > 1:
                url_part = parts[1].split('<')[0]
                # Construct the full public URL
                public_url = f"{url_part}/video.mp4"
                print(public_url)
                return public_url
            else:
                print(f"Anondrop upload response parsing failed: {response.text}")
                return None
        except Exception as e:
            print(f"Error parsing Anondrop upload response: {e}")
            print(f"Response text: {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Anondrop upload request failed: {e}")
        return None
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def remote_upload_url_to_anondrop(url):
    """
    Uploads a file to Anondrop using a remote URL with retry logic.
    """
    retry_strategy = Retry(
        total=3,  # Number of retries
        backoff_factor=2,  # Exponential backoff factor (1 means 2s, 4s, 8s, ...)
        status_forcelist=[500, 502, 503, 504],  # HTTP status codes to retry on
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    http = requests.Session()
    http.mount("https://", adapter)
    http.mount("http://", adapter)

    params = {
        'key': '1373290470486052946',
        'url': url,
    }
    response = None
    try:
        response = http.get('https://anondrop.net/remoteuploadurl', params=params, stream=True)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        if not "jpg" in url:
            anondrop_url = response.text.split('>')[1].split('<')[0]+"/video.mp4"
        else:
            anondrop_url = response.text.split('>')[1].split('<')[0]+"/image.jpg"

        print(f"Anondrop remote upload successful. URL: {anondrop_url}")
        return anondrop_url
    except requests.exceptions.RequestException as e:
        print(f"Anondrop remote upload failed: {e}. Response status: {response.status_code if response else 'N/A'}, Response text: {response.text if response else 'N/A'}")
        return None

async def get_runway_result(task_id: str, headers: dict):
    """Asynchronously polls the Runway API for the result of a generation task."""
    params = {'taskId': task_id}
    finished = False
    video_url = None
    image_thumbnail_url = None

    while not finished:
        detail_response = requests.get('https://kieai.erweima.ai/api/v1/runway/record-detail', params=params, headers=headers, stream=True)
        detail_data = detail_response.json()["data"]
        print(f"Runway API detail_data: {detail_data}")

        if len(detail_data["failMsg"]) > 0:
            raise Exception("Runway API returned an error.")

        state = detail_data["state"]
        print(f"Runway API state: {state}")
        if state == "generating" or state == "queueing":
            await asyncio.sleep(3)  # Asynchronous sleep
            continue
        elif state != "success":
            raise Exception(f"Runway API returned unexpected state: {state}")

        if detail_data["state"] == "success":
            video_url = detail_data["videoInfo"]["videoUrl"]
            image_thumbnail_url = detail_data["videoInfo"]["imageUrl"]
            print(f"Runway API video_url: {video_url}")
            print(f"Runway API image_thumbnail_url: {image_thumbnail_url}")
            finished = True
            break
        await asyncio.sleep(3)  # Asynchronous sleep
        yield b' ' #Heartbeat

    yield video_url
    yield image_thumbnail_url

# Runway API Integration
@app.route('/v1/images/generations', methods=['POST'])
def generate_image_api():
    ip_address = request.headers.get('CF-Connecting-IP', request.remote_addr)
    if ip_address!= request.remote_addr and ip_address != "37.114.39.160":
        print(ip_address)
        now = datetime.now()

        last_request_time = request_timestamps.get(ip_address)

        if last_request_time and (now - last_request_time) < RATE_LIMIT_PERIOD:
            print(f"Rate limit exceeded for IP: {ip_address}")
            def rate_limit_stream():
                yield b' '
                yield json.dumps({"error": "rate_limit_exceeded", "message": "Too many requests. Please wait an hour."}).encode('utf-8')
            return Response(stream_with_context(rate_limit_stream()), status=429, mimetype='application/json')
        request_timestamps[ip_address] = now

    def _process_and_generate_stream():
        yield b' '

        prompt = None
        aspect_ratio = '16:9' # Default aspect ratio
        image_url = None

        try:
            # Handle both JSON and multipart/form-data requests
            if request.content_type == 'application/json':
                data = request.get_json()
                if not data:
                    yield json.dumps({"error": "No data provided."}).encode('utf-8')
                    return
                prompt = data.get('prompt')
                aspect_ratio = data.get('aspectRatio', '16:9')
            elif request.content_type.startswith('multipart/form-data'):
                prompt = request.form.get('prompt')
                aspect_ratio = request.form.get('aspectRatio', '16:9')
                image_file = request.files.get('image')

                if image_file:
                    image_url = upload_image_to_anondrop(image_file)  # Upload to Anondrop
                    if not image_url:
                        yield json.dumps({"error": "Failed to upload image to Anondrop."}).encode('utf-8')
                        return
            else:
                yield json.dumps({"error": "Unsupported content type."}).encode('utf-8')
                return

            # Basic validation: prompt is required
            if not prompt:
                yield json.dumps({"error": "Prompt is required."}).encode('utf-8')
                return

            # Runway API Call
            tokens = open('tokens.txt', 'r').read().splitlines()
            if not tokens:
                yield json.dumps({"error": "No tokens available."}).encode('utf-8')
                return

            randomkey = random.choice(tokens)
            headers = {
                'sec-ch-ua-platform': '"Linux"',
                'Authorization': 'Bearer ' + randomkey,
                'Referer': 'https://kie.ai/',
                'sec-ch-ua': '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
                'sec-ch-ua-mobile': '?0',
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
            }
            # print(aspect_ratio)
            json_data = {
                'prompt': prompt,
                'imageUrl': image_url if image_url else '',
                'aspectRatio': str(aspect_ratio),
                'callBackUrl': 'playground',
                'quality': '720p',
                'duration': '5',
                'waterMark': 'ExoML' if ip_address!= request.remote_addr else None
            }

            response = requests.post('https://kieai.erweima.ai/api/v1/runway/generate', headers=headers,
                                      json=json_data, stream=True)
            status = response.json()["code"]
            print(response.json())
            if status == 402:
                # Remove the key from tokens.txt
                def remove_key_from_tokens(key):
                    try:
                        with open('tokens.txt', 'r') as f:
                            tokens = f.read().splitlines()
                        tokens = [token for token in tokens if token != key]
                        with open('tokens.txt', 'w') as f:
                            f.write('\n'.join(tokens))
                        print(f"Removed key {key} from tokens.txt")
                        return True
                    except Exception as e:
                        print(f"Error removing key from tokens.txt: {e}")
                        return False

                if remove_key_from_tokens(randomkey):
                    print("Retrying the request with a different key.")
                    # Get a new token and retry within the same generator
                    tokens = open('tokens.txt', 'r').read().splitlines()
                    if not tokens:
                        yield json.dumps({"error": "No tokens available after retry."}).encode('utf-8')
                        return
                    
                    randomkey = random.choice(tokens)
                    headers['Authorization'] = 'Bearer ' + randomkey
                    
                    # Retry the API call
                    response = requests.post('https://kieai.erweima.ai/api/v1/runway/generate', headers=headers,
                                           json=json_data, stream=True)
                    status = response.json()["code"]
                    print(f"Retry response: {response.json()}")
                    
                    if status == 402:
                        yield json.dumps({"error": "All tokens exhausted. Please try again later."}).encode('utf-8')
                        return
                else:
                    yield json.dumps({"error": "Failed to remove key and retry."}).encode('utf-8')
                    return

            taskId = response.json()["data"]["taskId"]

            # Asynchronously Poll for Result
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                generator = get_runway_result(taskId, headers)
                video_url = loop.run_until_complete(generator.__anext__())
                image_thumbnail_url = loop.run_until_complete(generator.__anext__())
            except Exception as e:
                yield json.dumps({"error": str(e)}).encode('utf-8')
                return
            finally:
                loop.close()

            # Remote Upload to Anondrop
            try:
                print(f"Anondrop remote upload: video_url={video_url}, image_thumbnail_url={image_thumbnail_url}")
                video_url = remote_upload_url_to_anondrop(video_url)
                image_thumbnail_url = remote_upload_url_to_anondrop(image_thumbnail_url)
            except Exception as e:
                yield json.dumps({"error": f"Anondrop remote upload failed: {str(e)}"}).encode('utf-8')
                return

            # Returning Result
            if video_url and image_thumbnail_url:
                response_data = [{"url": video_url, "thumbnail": image_thumbnail_url}]
                yield json.dumps({"data": response_data}).encode('utf-8')

                # Send Discord Embed
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(send_discord_embed(image_url, prompt, aspect_ratio, video_url))
                except Exception as e:
                    print(f"Failed to send Discord embed: {e}")
                finally:
                    loop.close()

            else:
                yield json.dumps({"error": "Could not retrieve video and thumbnail URLs."}).encode('utf-8')
        except Exception as e:
            yield json.dumps({"error": f"An error occurred: {str(e)}"}).encode('utf-8')

    # After the generation, send the embed to Discord
    async def send_discord_embed(image_url, prompt, aspect_ratio, video_url):
        webhook_url = 'https://discord.com/api/webhooks/1377473941517500466/9E7e0dTqOSYY3hnm_oqidr31PnRTObipkjcm-hdw2lHfZNZ6Wqk58lWREeOJtYXsWJND'
        embed = {
            "title": "Runway Generation Result",
            "fields": [
                {"name": "Prompt", "value": prompt},
                {"name": "Aspect Ratio", "value": aspect_ratio},
                {"name": "Video URL", "value": video_url}
            ],
            "image": {"url": image_url},
            "video": {"url": video_url}
        }
        data = {"embeds": [embed]}
        try:
            pass#response = requests.post(webhook_url, json=data)
            pass#response.raise_for_status()
            print("Discord embed sent successfully!")
        except requests.exceptions.RequestException as e:
            print(f"Failed to send Discord embed: {e}")

    return Response(stream_with_context(_process_and_generate_stream()), mimetype='application/json')


if __name__ == '__main__':
      app.run("0.0.0.0",24463)
