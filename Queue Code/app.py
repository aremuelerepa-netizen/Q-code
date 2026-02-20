import os
import random
import requests
from datetime import timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_mail import Mail, Message
from supabase import create_client, Client
from groq import Groq
from dotenv import load_dotenv

# 1. Initialization
load_dotenv()

# FIX: Path detection for "Queue Code" folder
base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, 
            template_folder=os.path.join(base_dir, 'templates'),
            static_folder=os.path.join(base_dir, 'static'))

app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_default_key")
app.permanent_session_lifetime = timedelta(days=1)

# --- 2. CLIENT FETCHERS ---
def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key: return None
    try:
        # strip() prevents "Failed to fetch" errors caused by accidental spaces
        return create_client(url.strip(), key.strip())
    except Exception as e:
        print(f"Supabase Error: {e}")
        return None

def get_groq():
    key = os.getenv("GROQ_API_KEY")
    return Groq(api_key=key) if key else None

# --- 3. MAIL & SMS ---
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=465,
    MAIL_USERNAME=os.getenv("GMAIL_USER"),
    MAIL_PASSWORD=os.getenv("GMAIL_APP_PASSWORD"),
    MAIL_USE_SSL=True,
    MAIL_DEFAULT_SENDER=os.getenv("GMAIL_USER")
)
mail = Mail(app)

def send_otp_sms(phone, code):
    api_key = os.getenv("TERMII_API_KEY")
    if not api_key: return False
    url = "https://api.ng.termii.com/api/sms/send"
    payload = {
        "api_key": api_key,
        "to": phone,
        "from": os.getenv("TERMII_SENDER_ID", "N-Alert"),
        "sms": f"Your Q-Code OTP is: {code}",
        "type": "plain",
        "channel": "generic"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except: return False

# --- 4. ROUTES ---

@app.route('/')
def home(): 
    return render_template('index.html')

@app.route('/login')
def login_view(): 
    return render_template('login page.html')

@app.route('/register')
def reg_view(): 
    return render_template('org reg page.html')

@app.route('/admin')
def admin_view():
    if 'org_id' not in session: return redirect(url_for('login_view'))
    return render_template('Admin page.html', org_name=session.get('org_name'))

@app.route('/super-admin')
def super_admin_view():
    if not session.get('is_super_admin'): return redirect(url_for('login_view'))
    db = get_supabase()
    data = []
    if db:
        res = db.table("organizations").select("*").eq("verified", False).execute()
        data = res.data
    return render_template('super_admin.html', pending_orgs=data)

# --- 5. API ENDPOINTS ---

@app.route('/api/auth/register', methods=['POST'])
def register_org():
    db = get_supabase()
    if not db: return jsonify({"status": "error", "message": "DB disconnected"}), 500
    
    try:
        db.table("organizations").insert({
            "name": request.form.get('orgName'),
            "email": request.form.get('email'),
            "phone": request.form.get('phone'),
            "password": request.form.get('password'),
            "verified": False
        }).execute()
        return jsonify({"status": "success", "message": "Awaiting Verification"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    email, password = data.get('email'), data.get('password')

    # Super Admin Check
    if email == os.getenv("ADMIN_EMAIL") and password == os.getenv("ADMIN_PASSWORD"):
        session.clear()
        session.permanent = True
        session['is_super_admin'] = True
        return jsonify({"status": "success", "redirect": "/super-admin"})

    # Org Check
    db = get_supabase()
    res = db.table("organizations").select("*").eq("email", email).execute()
    if res.data and res.data[0]['password'] == password:
        org = res.data[0]
        if org['verified']:
            session.update({'org_id': str(org['id']), 'org_name': org['name'], 'is_super_admin': False})
            return jsonify({"status": "success", "redirect": "/admin"})
        return jsonify({"status": "pending", "message": "Not verified"}), 403
    return jsonify({"status": "error", "message": "Failed"}), 401

@app.route('/api/otp/request', methods=['POST'])
def request_otp():
    phone = request.json.get('phone')
    otp_code = str(random.randint(1000, 9999))
    db = get_supabase()
    db.table("otp_codes").upsert({"phone": phone, "code": otp_code}).execute()
    
    if send_otp_sms(phone, otp_code):
        return jsonify({"status": "success"})
    return jsonify({"status": "debug", "code": otp_code}) # Returns code for testing if Termii fails

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
