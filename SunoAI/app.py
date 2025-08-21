import requests
import time
import random
import os
import base64
import emoji
from flask import Flask, request, jsonify, render_template, session
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
import io

PILMOJI_AVAILABLE = False
Pilmoji = None
Twemoji = None

try:
    from pilmoji import Pilmoji
    from pilmoji.source import Twemoji
    PILMOJI_AVAILABLE = True
except ImportError:
    print("Pilmoji not available, falling back to text rendering")

app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.route('/fonts/NotoColorEmoji.ttf')
def serve_noto_emoji_font():
    """Serve the NotoColorEmoji font file"""
    from flask import send_file
    font_path = './NotoColorEmoji.ttf'
    if os.path.exists(font_path):
        return send_file(font_path, mimetype='font/ttf')
    else:
        return "Font not found", 404

def get_random_emojis(count=9):
    # Curated list of valid, renderable emojis that work well in captcha
    valid_emojis = [
        # Faces and People
        "😀", "😃", "😄", "😁", "😆", "😅", "😂", "🤣", "😊", "😇",
        "🙂", "🙃", "😉", "😌", "😍", "🥰", "😘", "😗", "😙", "😚",
        "😋", "😛", "😝", "😜", "🤪", "🤨", "🧐", "🤓", "😎", "🤩",
        "🥳", "😏", "😒", "😞", "😔", "😟", "😕", "🙁", "☹️", "😣",
        "😖", "😫", "😩", "🥺", "😢", "😭", "😤", "😠", "😡", "🤬",
        "🤯", "😳", "🥵", "🥶", "😱", "😨", "😰", "😥", "😓", "🤗",
        "🤔", "🤭", "🤫", "🤥", "😶", "😐", "😑", "😬", "🙄", "😯",
        "😦", "😧", "😮", "😲", "🥱", "😴", "🤤", "😪", "😵", "🤐",
        "🥴", "🤢", "🤮", "🤧", "😷", "🤒", "🤕",
        
        # Animals
        "🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼", "🐨", "🐯",
        "🦁", "🐮", "🐷", "🐽", "🐸", "🐵", "🙈", "🙉", "🙊", "🐒",
        "🐔", "🐧", "🐦", "🐤", "🐣", "🐥", "🦆", "🦅", "🦉", "🦇",
        "🐺", "🐗", "🐴", "🦄", "🐝", "🐛", "🦋", "🐌", "🐞", "🐜",
        "🦟", "🦗", "🕷️", "🦂", "🐢", "🐍", "🦎", "🦖", "🦕", "🐙",
        "🦑", "🦐", "🦞", "🦀", "🐡", "🐠", "🐟", "🐬", "🐳", "🐋",
        "🦈", "🐊", "🐅", "🐆", "🦓", "🦍", "🦧", "🐘", "🦛", "🦏",
        "🐪", "🐫", "🦒", "🦘", "🐃", "🐂", "🐄", "🐎", "🐖", "🐏",
        "🐑", "🦙", "🐐", "🦌", "🐕", "🐩", "🦮", "🐈", "🐓", "🦃",
        "🦚", "🦜", "🦢", "🦩", "🕊️", "🐇", "🦝", "🦨", "🦡", "🦦",
        
        # Food
        "🍎", "🍐", "🍊", "🍋", "🍌", "🍉", "🍇", "🍓", "🫐", "🍈",
        "🍒", "🍑", "🥭", "🍍", "🥥", "🥝", "🍅", "🍆", "🥑", "🥦",
        "🥬", "🥒", "🌶️", "🫑", "🌽", "🥕", "🫒", "🧄", "🧅", "🥔",
        "🍠", "🥐", "🥯", "🍞", "🥖", "🥨", "🧀", "🥚", "🍳", "🧈",
        "🥞", "🧇", "🥓", "🥩", "🍗", "🍖", "🦴", "🌭", "🍔", "🍟",
        "🍕", "🥪", "🥙", "🧆", "🌮", "🌯", "🫔", "🥗", "🥘", "🫕",
        "🍝", "🍜", "🍲", "🍛", "🍣", "🍱", "🥟", "🦪", "🍤", "🍙",
        "🍚", "🍘", "🍥", "🥠", "🥮", "🍢", "🍡", "🍧", "🍨", "🍦",
        "🥧", "🧁", "🍰", "🎂", "🍮", "🍭", "🍬", "🍫", "🍿", "🍩",
        "🍪", "🌰", "🥜", "🍯",
        
        # Objects and Symbols
        "⚽", "🏀", "🏈", "⚾", "🥎", "🎾", "🏐", "🏉", "🥏", "🎱",
        "🪀", "🏓", "🏸", "🏒", "🏑", "🥍", "🏏", "🪃", "🥅", "⛳",
        "🪁", "🏹", "🎣", "🤿", "🥊", "🥋", "🎽", "🛹", "🛷", "⛸️",
        "🥌", "🎿", "⛷️", "🏂", "🪂", "🏋️", "🤼", "🤸", "⛹️", "🤺",
        "🏇", "🧘", "🏄", "🏊", "🤽", "🚣", "🧗", "🚵", "🚴", "🏆",
        "🥇", "🥈", "🥉", "🏅", "🎖️", "🏵️", "🎗️", "🎫", "🎟️", "🎪",
        "🤹", "🎭", "🩰", "🎨", "🎬", "🎤", "🎧", "🎼", "🎵", "🎶",
        "🥁", "🪘", "🎹", "🥊", "🎺", "🎷", "🎸", "🪕", "🎻", "🎲",
        "♟️", "🎯", "🎳", "🎮", "🎰", "🧩",
        
        # Nature
        "🌍", "🌎", "🌏", "🌐", "🗺️", "🗾", "🧭", "🏔️", "⛰️", "🌋",
        "🗻", "🏕️", "🏖️", "🏜️", "🏝️", "🏞️", "🏟️", "🏛️", "🏗️", "🧱",
        "🪨", "🪵", "🛖", "🏘️", "🏚️", "🏠", "🏡", "🏢", "🏣", "🏤",
        "🏥", "🏦", "🏨", "🏩", "🏪", "🏫", "🏬", "🏭", "🏯", "🏰",
        "💒", "🗼", "🗽", "⛪", "🕌", "🛕", "🕍", "⛩️", "🕋", "⛲",
        "⛺", "🌁", "🌃", "🏙️", "🌄", "🌅", "🌆", "🌇", "🌉", "♨️",
        "🎠", "🎡", "🎢", "💈", "🎪",
        
        # Weather and Nature
        "🌞", "🌝", "🌛", "🌜", "🌚", "🌕", "🌖", "🌗", "🌘", "🌑",
        "🌒", "🌓", "🌔", "🌙", "🌟", "⭐", "🌠", "🌌", "☁️", "⛅",
        "⛈️", "🌤️", "🌦️", "🌧️", "⛈️", "🌩️", "🌨️", "❄️", "☃️", "⛄",
        "🌬️", "💨", "🌪️", "🌫️", "🌈", "🌂", "☂️", "☔", "⚡", "❄️",
        
        # Transport
        "🚗", "🚕", "🚙", "🚌", "🚎", "🏎️", "🚓", "🚑", "🚒", "🚐",
        "🛻", "🚚", "🚛", "🚜", "🏍️", "🛵", "🚲", "🛴", "🛹", "🛼",
        "🚁", "🛸", "✈️", "🛩️", "🛫", "🛬", "🪂", "💺", "🚀", "🛰️",
        "🚊", "🚝", "🚅", "🚄", "🚈", "🚞", "🚋", "🚃", "🚟", "🚠",
        "🚡", "⛴️", "🛥️", "🚤", "⛵", "🛶", "🚲", "🏍️", "🛺", "🚨",
        "🚥", "🚦", "🛑", "🚧"
    ]
    
    # Return a random sample of valid emojis
    return random.sample(valid_emojis, min(count, len(valid_emojis)))

@app.route('/captcha')
def captcha():
    # Rate limiting for captcha endpoint - 1 request per 5 minutes per IP
    ip_address = request.headers.get('CF-Connecting-IP', request.remote_addr)
    now = datetime.now()
    last_captcha_request = captcha_request_timestamps.get(ip_address)
    
    if last_captcha_request and (now - last_captcha_request) < CAPTCHA_RATE_LIMIT_PERIOD:
        return jsonify({"error": "rate_limit_exceeded", "message": "Too many captcha requests. Please wait 5 minutes."}), 429
    
    captcha_request_timestamps[ip_address] = now
    
    emojis = get_random_emojis()
    correct_emoji = random.choice(emojis)
    session['correct_emoji'] = correct_emoji
    session['emojis'] = emojis

    # Create image for emoji captcha with perfectly centered emojis
    canvas_size = 450
    image = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 255))
    
    # Define center positions for 3x3 grid
    positions = [(75, 75), (225, 75), (375, 75),
                 (75, 225), (225, 225), (375, 225),
                 (75, 375), (225, 375), (375, 375)]
    
    if PILMOJI_AVAILABLE and Pilmoji is not None and Twemoji is not None:
        print("Using Pilmoji with Twemoji for perfect emoji centering")
        
        # Try to load a suitable font, fallback to default if needed
        font = None
        font_paths = [
            "./NotoColorEmoji.ttf",
            "./AppleColorEmoji.ttf",
            "./seguiemj.ttf"
        ]
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    font = ImageFont.truetype(font_path, 72)
                    print(f"Using font: {font_path}")
                    break
                except Exception as e:
                    print(f"Failed to load {font_path}: {e}")
        
        if font is None:
            try:
                font = ImageFont.load_default()
                print("Using default font")
            except:
                font = None
        
        for emoji, center in zip(emojis, positions):
            try:
                # Create transparent temp image for this emoji
                temp_img = Image.new("RGBA", (150, 150), (0, 0, 0, 0))
                
                # Draw emoji on temp image using Twemoji source
                with Pilmoji(temp_img, source=Twemoji()) as pilmoji:
                    pilmoji.text((0, 0), emoji, font=font if font else ImageFont.load_default())
                
                # Trim transparent borders to get actual emoji bounds
                bbox = temp_img.getbbox()
                if bbox:
                    emoji_img = temp_img.crop(bbox)
                else:
                    emoji_img = temp_img
                
                # Calculate top-left position for perfectly centered paste
                emoji_w, emoji_h = emoji_img.size
                top_left = (center[0] - emoji_w // 2, center[1] - emoji_h // 2)
                
                # Paste the trimmed emoji at centered position
                image.paste(emoji_img, top_left, emoji_img)
                print(f"Placed emoji {emoji} at center {center}, size {emoji_w}x{emoji_h}")
                
            except Exception as e:
                print(f"Failed to render emoji {emoji} with Pilmoji: {e}")
    else:
        print("Pilmoji/Twemoji not available, using fallback TTF font rendering")
        # Fallback to TTF fonts if Pilmoji is not available
        draw = ImageDraw.Draw(image)
        
        # Randomly select one of the local emoji fonts
        font_paths = [
            "./NotoColorEmoji.ttf",
            "./AppleColorEmoji.ttf",
            "./seguiemj.ttf"
        ]
        selected_font_path = random.choice(font_paths)
        print(f"Using font: {selected_font_path}")
        
        # Load the selected emoji font with larger size
        emoji_font = None
        font_size = 72
        if os.path.exists(selected_font_path):
            try:
                emoji_font = ImageFont.truetype(selected_font_path, font_size)
                print(f"Loaded emoji font: {selected_font_path}")
            except Exception as e:
                print(f"Failed to load {selected_font_path}: {e}")
        
        for emoji, center in zip(emojis, positions):
            print(f"Drawing emoji {emoji} at center {center}")
            
            try:
                if emoji_font:
                    # Get text bounding box for precise centering
                    bbox = draw.textbbox((0, 0), emoji, font=emoji_font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    
                    # Calculate centered position
                    centered_x = center[0] - text_width // 2
                    centered_y = center[1] - text_height // 2
                    centered_pos = (centered_x, centered_y)
                    
                    print(f"Text size: {text_width}x{text_height}, centered at {centered_pos}")
                    draw.text(centered_pos, emoji, font=emoji_font, fill='black')
                else:
                    # Last resort: use default font with basic centering
                    default_font = ImageFont.load_default()
                    bbox = draw.textbbox((0, 0), emoji, font=default_font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                    
                    centered_x = center[0] - text_width // 2
                    centered_y = center[1] - text_height // 2
                    centered_pos = (centered_x, centered_y)
                    
                    draw.text(centered_pos, emoji, font=default_font, fill='black')
            except Exception as e:
                print(f"Failed to render emoji {emoji}: {e}")

    img_io = io.BytesIO()
    image.save(img_io, 'PNG')
    img_io.seek(0)
    img_base64 = base64.b64encode(img_io.getvalue()).decode()

    return jsonify({
        'image': f"data:image/png;base64,{img_base64}",
        'prompt': correct_emoji
    })

@app.route('/verify-captcha', methods=['POST'])
def verify_captcha():
    # Independent rate limiting for verify-captcha endpoint - 1 request per 5 minutes per IP
    ip_address = request.headers.get('CF-Connecting-IP', request.remote_addr)
    now = datetime.now()
    last_verify_request = verify_captcha_timestamps.get(ip_address)
    
    if last_verify_request and (now - last_verify_request) < CAPTCHA_RATE_LIMIT_PERIOD:
        return jsonify({"success": False, "message": "Too many verify attempts. Please wait 5 minutes."}), 429
    
    verify_captcha_timestamps[ip_address] = now
    
    if not request.json:
        return jsonify({"success": False, "message": "Invalid request."}), 400
    
    selected_emoji_index = request.json.get('emoji_index')
    emojis = session.get('emojis')
    correct_emoji = session.get('correct_emoji')

    if emojis and selected_emoji_index is not None and 0 <= selected_emoji_index < len(emojis):
        selected_emoji = emojis[selected_emoji_index]
        if selected_emoji == correct_emoji:
            # Mark this IP as having solved captcha recently
            ip_address = request.headers.get('CF-Connecting-IP', request.remote_addr)
            captcha_solved_ips[ip_address] = datetime.now()
            session['captcha_solved'] = True
            session.pop('correct_emoji', None)
            session.pop('emojis', None)
            return jsonify({"success": True})

    ip_address = request.headers.get('CF-Connecting-IP', request.remote_addr)
    request_timestamps[ip_address] = datetime.now()
    return jsonify({"success": False, "message": "Incorrect emoji. Please try again in 20 minutes."})

TOKENS_FILE_PATH = 'tokens.txt'
GENERATE_API_URL = 'https://api.kie.ai/api/v1/generate'
RECORD_INFO_API_URL = 'https://api.kie.ai/api/v1/generate/record-info'

request_timestamps = {}
captcha_request_timestamps = {}
verify_captcha_timestamps = {}
generate_request_timestamps = {}
captcha_solved_ips = {}  # Track which IPs have solved captcha recently
RATE_LIMIT_PERIOD = timedelta(minutes=20)
CAPTCHA_RATE_LIMIT_PERIOD = timedelta(minutes=5)
CAPTCHA_VALIDITY_PERIOD = timedelta(minutes=10)  # How long captcha solution is valid

def load_tokens():
    """Loads tokens from the tokens file."""
    if not os.path.exists(TOKENS_FILE_PATH):
        with open(TOKENS_FILE_PATH, 'w') as f:
            pass
        return []
    with open(TOKENS_FILE_PATH, 'r') as f:
        tokens = [line.strip() for line in f if line.strip()]
    return tokens

def save_tokens(tokens_list):
    """Saves the list of tokens to the tokens file."""
    with open(TOKENS_FILE_PATH, 'w') as f:
        for token in tokens_list:
            f.write(token + '\n')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def start_generate_task():
    # Check both session and IP-based captcha validation
    ip_address = request.headers.get('CF-Connecting-IP', request.remote_addr)
    now = datetime.now()
    
    # Check if IP has solved captcha recently
    captcha_solve_time = captcha_solved_ips.get(ip_address)
    session_captcha_solved = session.get('captcha_solved', False)
    
    if not session_captcha_solved or not captcha_solve_time or (now - captcha_solve_time) > CAPTCHA_VALIDITY_PERIOD:
        return jsonify({"error": "captcha_required", "message": "Please solve the captcha."}), 403
    """
    Initiates the generation task with rate limiting and token rotation.
    Returns taskId and the successful token for client-side polling.
    """
    # Independent rate limiting for generate endpoint
    last_generate_request = generate_request_timestamps.get(ip_address)

    if last_generate_request and (now - last_generate_request) < RATE_LIMIT_PERIOD:
        print(f"Generate rate limit exceeded for IP: {ip_address}")
        return jsonify({"error": "rate_limit_exceeded", "message": "Too many generate requests. Please wait 20 minutes."}), 429

    if not request.json or 'prompt' not in request.json:
        return jsonify({"error": "bad_request", "message": "Missing 'prompt' in JSON payload"}), 400

    generate_request_timestamps[ip_address] = now

    prompt_data = request.json['prompt']
    style = request.json.get('style', '')
    title = request.json.get('title', '')
    custom_mode = request.json.get('customMode', False)
    instrumental = request.json.get('instrumental', False)
    model = request.json.get('model', 'V4_5PLUS')

    json_payload_for_api = {
        'prompt': prompt_data, 'style': style, 'title': title,
        'customMode': custom_mode, 'instrumental': instrumental,
        'model': model, 'callBackUrl': 'playground',
    }

    available_tokens = load_tokens()
    if not available_tokens:
        print(f"Error: No API tokens found or {TOKENS_FILE_PATH} is empty.")
        return jsonify({"error": "server_error", "message": "Internal configuration error."}), 500

    tokens_to_try = list(available_tokens)
    random.shuffle(tokens_to_try)

    task_id = None
    selected_token = None
    last_api_response_data = None

    for current_token_attempt in list(tokens_to_try):
        headers_for_api = {'authorization': f'Bearer {current_token_attempt}'}
        try:
            print(f"Attempting API call to {GENERATE_API_URL} with token: ...{current_token_attempt[-4:]}")
            init_response = requests.post(GENERATE_API_URL, headers=headers_for_api, json=json_payload_for_api, timeout=15)
            last_api_response_data = init_response.json()

            if init_response.status_code == 200 and \
               last_api_response_data.get("msg") == "The current credits are insufficient. Please top up.":
                print(f"Token ...{current_token_attempt[-4:]} has insufficient credits. Removing and trying next.")
                if current_token_attempt in available_tokens:
                    available_tokens.remove(current_token_attempt)
                save_tokens(available_tokens)
                tokens_to_try.remove(current_token_attempt)
                continue

            init_response.raise_for_status()

            if last_api_response_data.get("code") == 200 and \
               "data" in last_api_response_data and \
               "taskId" in last_api_response_data["data"]:
                task_id = last_api_response_data["data"]["taskId"]
                selected_token = current_token_attempt
                print(f"Successfully initiated task {task_id} with token: ...{selected_token[-4:]}")
                break
            else:
                print(f"API call successful (status {init_response.status_code}) but taskId missing or data malformed with token ...{current_token_attempt[-4:]}. Response: {last_api_response_data}")

        except requests.exceptions.HTTPError as e:
            print(f"HTTPError during API call with token ...{current_token_attempt[-4:]}: {e}. Response: {e.response.text if e.response else 'No response text'}")
            last_api_response_data = {"error_details": str(e), "response_text": e.response.text if e.response else None}
        except requests.exceptions.RequestException as e:
            print(f"RequestException during API call with token ...{current_token_attempt[-4:]}: {e}")
            last_api_response_data = {"error_details": str(e)}
        except Exception as e:
            print(f"Unexpected error during API call attempt with token ...{current_token_attempt[-4:]}: {e}")
            last_api_response_data = {"error_details": str(e)}

    if not task_id or not selected_token:
        print(f"Failed to initiate task after trying all available tokens. Last API diagnostic info: {last_api_response_data}")
        return jsonify({"error": "server_error", "message": "Failed to initiate task with external API."}), 500

    return jsonify({
        "status": "initiated",
        "taskId": task_id,
        "token": selected_token
        })

@app.route('/check-status', methods=['POST'])
def check_task_status():
    """
    Performs a single poll for a given taskId using a specific token.
    Returns the status (PENDING, TEXT_SUCCESS with results, or error).
    """
    if not request.json or 'taskId' not in request.json or 'token' not in request.json:
        return jsonify({"error": "bad_request", "message": "Missing 'taskId' or 'token' in JSON payload"}), 400

    task_id = request.json['taskId']
    token = request.json['token']
    polling_headers = {'authorization': f'Bearer {token}'}
    polling_params = {'taskId': task_id}

    try:
        print(f"Polling {RECORD_INFO_API_URL} for taskId {task_id} with token ...{token[-4:]}")
        poll_response = requests.get(RECORD_INFO_API_URL, params=polling_params, headers=polling_headers, timeout=15)
        poll_response.raise_for_status()
        poll_data = poll_response.json()

        if poll_data.get("code") != 200 or "data" not in poll_data:
            print(f"Polling API call successful (status {poll_response.status_code}) but data malformed or error code. Response: {poll_data}")
            return jsonify({"status": "error", "message": "Polling API error"}), 500

        status = poll_data["data"].get("status")
        print(f"Polling status for {task_id}: {status}")

        if status == "PENDING":
            return jsonify({"status": "PENDING"})
        elif status == "TEXT_SUCCESS":
            results_to_return = []
            suno_api_data = poll_data.get("data", {}).get("response", {}).get("sunoData", [])
            for item in suno_api_data:
                results_to_return.append({
                    "title": item.get("title"),
                    "image_url": item.get("sourceImageUrl"),
                    "audio_url": item.get("sourceStreamAudioUrl"),
                    "lyrics": item.get("prompt"),
                    "tags": item.get("tags"),
                    "is_stream": True
                })
            return jsonify({"status": "TEXT_SUCCESS", "results": results_to_return})
        elif status == "SUCCESS":
            results_to_return = []
            suno_api_data = poll_data.get("data", {}).get("response", {}).get("sunoData", [])
            all_have_final_url = True
            for item in suno_api_data:
                 final_audio_url = item.get("sourceAudioUrl")
                 if not final_audio_url:
                     all_have_final_url = False
                     print(f"Warning: Status is SUCCESS but sourceAudioUrl missing for item in taskId {task_id}. Item: {item}")
                     final_audio_url = item.get("sourceStreamAudioUrl")

                 results_to_return.append({
                    "title": item.get("title"),
                    "image_url": item.get("sourceImageUrl"),
                    "audio_url": final_audio_url,
                    "lyrics": item.get("prompt"),
                    "tags": item.get("tags"),
                    "is_stream": False
                })
            print(f"Task {task_id} reached final SUCCESS state.")
            return jsonify({"status": "COMPLETED", "results": results_to_return})

        elif status and "ERROR" in status.upper():
            print(f"Task failed on external API during polling. Status: {status}. Details: {poll_data.get('data')}")
            return jsonify({"status": "error", "message": "Task failed on external API"}), 500
        else:
            print(f"Unknown or unexpected status during polling: {status}. Response: {poll_data}. Treating as PENDING.")
            return jsonify({"status": "PENDING"})

    except requests.exceptions.RequestException as e:
        print(f"Polling request failed for taskId {task_id}: {e}")
        return jsonify({"status": "error", "message": "Polling request failed"}), 500
    except Exception as e:
        print(f"An unexpected error occurred during polling for taskId {task_id}: {e}")
        return jsonify({"status": "error", "message": "Unexpected polling error"}), 500

if __name__ == '__main__':
    app.run("0.0.0.0", port=24464)