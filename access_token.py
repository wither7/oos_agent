
import hashlib
import os
from flask import Flask, redirect, request, session, redirect
import secrets
import requests
import base64
import urllib.parse
app = Flask(__name__)
app.secret_key = secrets.token_urlsafe(16)

CLIENT_ID = "4071151845732613353"
REDIRECT_URI = "http://127.0.0.1:5000/oauth/callback"

DISCOVERY_URL = "https://openapi-mcp.cn-hangzhou.aliyuncs.com/.well-known/oauth-authorization-server"

def set_key(key, value):
    """
    将键值对保存到本地配置文件中
    """
    os.environ[key] = value
    with open(".env", "a") as f:
        f.write(f"{key}={value}\n")
    print(f"Saved {key} to .env file")

def load_keys():
    """
    从.env文件中读取键值对并设置为环境变量
    """
    if not os.path.exists(".env"):
        print(".env file not found")
        return

    with open(".env", "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value
    print("Loaded environment variables from .env file")

def fetch_discovery_info():
    """从 discovery url 获取 Oauth 端点信息"""
    try:
        resp = requests.get(DISCOVERY_URL, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "authorization_endpoint": data.get("authorization_endpoint"),
                "token_endpoint": data.get("token_endpoint"),
                "registration_endpoint": data.get("registration_endpoint")
            }
    except Exception as e:
        print(f"Failed to fetch discovery info: {e}")
    return {}

# 默认端点
AUTHORIZATION_ENDPOINT = "https://signin.aliyun.com/oauth2/v1/auth"
TOKEN_ENDPOINT = "https://oauth.aliyun.com/v1/token"


def generate_pkce():
    """生成 PKCE 的 code_verifier 和 code_challenge"""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    # 计算 S256 code_challenge
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")

    return code_verifier, code_challenge

@app.route("/")
def home():
    return'<a href="/login">Login with OAuth</a>'

@app.route("/login")
def login():
    registration_endpoint = ""
    # 尝试用 discovery 信息覆盖端点
    discovery = fetch_discovery_info()
    print(f"Discovery info: {discovery}")
    if discovery.get("authorization_endpoint"):
        AUTHORIZATION_ENDPOINT = discovery["authorization_endpoint"]
    if discovery.get("token_endpoint"):
        TOKEN_ENDPOINT = discovery["token_endpoint"]
    if discovery.get("registration_endpoint"):
        registration_endpoint = discovery["registration_endpoint"]
    # 注册一个 client（如果 CLIENT_ID 未设置或为占位符）
    client_id = CLIENT_ID
    if (not client_id) or client_id.endswith("*******"):
        if not registration_endpoint:
            return"Registration endpoint not available", 400
        # 注册 client
        reg_data = {
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
        }
        try:
            reg_resp = requests.post(registration_endpoint, json=reg_data, timeout=5)
            if reg_resp.status_code != 201:
                return f"Client registration failed: {reg_resp.text}", 400
            reg_json = reg_resp.json()
            client_id = reg_json.get("client_id")
            if not client_id:
                return"No client_id returned from registration", 400
            session["client_id"] = client_id
        except Exception as e:
            return f"Client registration exception: {e}", 400
    else:
        session["client_id"] = client_id

    # 生成 PKCE 参数
    code_verifier, code_challenge = generate_pkce()

    # 生成随机 state 防止 CSRF
    state = secrets.token_urlsafe(16)

    # 保存到 session
    session.update({
        "code_verifier": code_verifier,
        "state": state
    })

    # 构造授权请求 URL
    params = {
        "response_type": "code",
        "client_id": session["client_id"],
        "redirect_uri": REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state
    }

    auth_url = f"{AUTHORIZATION_ENDPOINT}?{urllib.parse.urlencode(params)}"
    return redirect(auth_url)

@app.route("/oauth/callback")
def callback():
    # 检查错误响应
    if "error" in request.args:
        return f"Error: {request.args['error']}"

    # 验证 state
    if request.args.get("state") != session.get("state"):
        return"Invalid state parameter", 400

    # 获取授权码
    auth_code = request.args.get("amp;code") or request.args.get('code')  # 尝试两种可能的参数名
    if not auth_code:
        return"Missing authorization code", 400

    # 用授权码换取 token
    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": session.get("client_id", CLIENT_ID),
        "code_verifier": session["code_verifier"]
    }

    response = requests.post(TOKEN_ENDPOINT, data=data)

    if response.status_code != 200:
        return f"Token request failed: {response.text}", 400

    token_info = response.json().get("access_token")

    # 存储到本地配置文件
    print(f"Your access_token: {token_info}")
    set_key("ALI_OPENAPI_ACCESS_TOKEN", token_info)

    # 删掉session参数
    session.pop("code_verifier", None)
    session.pop("state", None)

    return response.json()

if __name__ == "__main__":
    app.run(port=5000, debug=True)