import os
import random
import requests
from datetime import timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_mail import Mail, Message
from supabase import create_client, Client
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, 
            template_folder=os.path.join(base_dir, 'templates'),
            static_folder=os.path.join(base_dir, 'static'))

app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_dev_key")
app.permanent_session_lifetime = timedelta(days=1)

# --- CLIENT FETCHERS ---
def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    return create_client(url, key) if url and key else None

def get_groq():
    key = os.getenv("GROQ_API_KEY")
    return Groq(api_key=key) if key else None

# --- OTP / SMS LOGIC (TERMII) ---
def send_otp_sms(phone, code):
    api_key = os.getenv("TERMII_API_KEY")
    if not api_key: return False
    
    url = "https://api.ng.termii.com/api/sms/send"
    payload = {
        "api_key": api_key,
        "to": phone,
        "from": os.getenv("TERMII_SENDER_ID", "N-Alert"),
        "sms": f"Your Q-Code verification code is: {code}",
        "type": "plain",
        "channel": "generic" # Use generic for OTPs
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except:
        return False

# --- ROUTES ---

@app.route('/')
def home(): return render_template('index.html')

@app.route('/login')
def login_view(): return render_template('login page.html')

@app.route('/register')
def reg_view(): return render_template('org reg page.html')

# --- REGISTRATION FIX (The 404 solver) ---
@app.route('/api/auth/register', methods=['POST'])
def register_org():
    db = get_supabase()
    if not db: return jsonify({"status": "error", "message": "DB error"}), 500
    
    data = {
        "name": request.form.get('orgName'),
        "email": request.form.get('email'),
        "phone": request.form.get('phone'),
        "password": request.form.get('password'), # Ensure this matches the ALTER TABLE above
        "verified": False
    }

    try:
        db.table("organizations").insert(data).execute()
        return jsonify({"status": "success", "message": "Pending Admin Approval"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- OTP REQUEST ---
@app.route('/api/otp/request', methods=['POST'])
def request_otp():
    phone = request.json.get('phone')
    if not phone: return jsonify({"status": "error"}), 400
    
    otp_code = str(random.randint(1000, 9999))
    db = get_supabase()
    
    # Store OTP in Supabase 'otp_codes' table
    db.table("otp_codes").upsert({"phone": phone, "code": otp_code}).execute()
    
    # Try to send SMS
    success = send_otp_sms(phone, otp_code)
    
    if success:
        return jsonify({"status": "success", "message": "OTP Sent"})
    else:
        # For development, you might want to return the code so you can test without SMS
        return jsonify({"status": "debug", "message": "SMS Failed, use code: " + otp_code})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
