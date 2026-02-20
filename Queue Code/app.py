import os
import random
import requests
from datetime import timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_mail import Mail, Message
from supabase import create_client, Client
from groq import Groq
from dotenv import load_dotenv

# 1. Load env before anything else
load_dotenv()

app = Flask(__name__)

# --- CONFIGURATION ---
# Use a strong secret key for session signing
app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_default_key")
app.permanent_session_lifetime = timedelta(days=1)

# --- 2. INITIALIZE CLIENTS SAFELY ---
# We use a global variable but initialize it lazily to prevent startup hangs
supabase_client: Client = None

def get_supabase():
    global supabase_client
    if supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            print("CRITICAL: Supabase credentials missing from Environment Variables!")
            return None
        try:
            supabase_client = create_client(url, key)
        except Exception as e:
            print(f"FAILED TO CONNECT TO SUPABASE: {e}")
            return None
    return supabase_client

# Initialize Groq (Lazy check)
def get_groq():
    api_key = os.getenv("GROQ_API_KEY")
    if api_key:
        return Groq(api_key=api_key)
    return None

# Termii Config
TERMII_API_KEY = os.getenv("TERMII_API_KEY")
TERMII_SENDER_ID = os.getenv("TERMII_SENDER_ID", "N-Alert")

def send_sms_via_termii(phone, message):
    if not TERMII_API_KEY: 
        return None
    url = "https://api.ng.termii.com/api/sms/send"
    payload = {
        "api_key": TERMII_API_KEY,
        "to": phone,
        "from": TERMII_SENDER_ID,
        "sms": message,
        "type": "plain",
        "channel": "dnd"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Termii Error: {e}")
        return None

# Mail Config
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=465,
    MAIL_USERNAME=os.getenv("GMAIL_USER"),
    MAIL_PASSWORD=os.getenv("GMAIL_APP_PASSWORD"),
    MAIL_USE_SSL=True,
    MAIL_DEFAULT_SENDER=os.getenv("GMAIL_USER")
)
mail = Mail(app)

# --- 3. PAGE ROUTING ---

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
    if 'org_id' not in session: 
        return redirect(url_for('login_view'))
    return render_template('Admin page.html', org_name=session.get('org_name'))

@app.route('/super-admin')
def super_admin_view():
    if not session.get('is_super_admin'):
        return redirect(url_for('login_view'))
    
    db = get_supabase()
    if not db:
        return "Database Configuration Error. Please check Render Environment Variables.", 500

    try:
        res = db.table("organizations").select("*").eq("verified", False).execute()
        return render_template('super_admin.html', pending_orgs=res.data)
    except Exception as e:
        print(f"Admin Fetch Error: {e}")
        return f"Database Error: {e}", 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_view'))

# --- 4. AUTHENTICATION ---

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"status": "error", "message": "Missing credentials"}), 400

    # A. MASTER ADMIN LOGIN (Direct ENV check)
    if email == os.getenv("ADMIN_EMAIL") and password == os.getenv("ADMIN_PASSWORD"):
        session.clear()
        session.permanent = True
        session['is_super_admin'] = True
        return jsonify({"status": "success", "redirect": "/super-admin"})

    # B. ORGANIZATION LOGIN
    db = get_supabase()
    if not db:
        return jsonify({"status": "error", "message": "Database disconnected"}), 500

    try:
        res = db.table("organizations").select("*").eq("email", email).execute()
        if res.data:
            org = res.data[0]
            if org['password'] == password:
                if org.get('verified'):
                    session.clear()
                    session.permanent = True
                    session['org_id'] = str(org['id'])
                    session['org_name'] = org['name']
                    session['is_super_admin'] = False
                    return jsonify({"status": "success", "redirect": "/admin"})
                else:
                    return jsonify({"status": "pending", "message": "Account awaiting verification"}), 403
            return jsonify({"status": "error", "message": "Incorrect password"}), 401
    except Exception as e:
        print(f"Login DB Error: {e}")
        return jsonify({"status": "error", "message": "Database query failed"}), 500
    
    return jsonify({"status": "error", "message": "User not found"}), 404

# --- 5. REGISTER & ACTIONS ---

@app.route('/api/auth/register', methods=['POST'])
def register_org():
    db = get_supabase()
    if not db: 
        return jsonify({"status": "error", "message": "Database offline"}), 500
    
    org_name = request.form.get('orgName')
    email = request.form.get('email')
    phone = request.form.get('phone')
    password = request.form.get('password') 
    uploaded_file = request.files.get('verificationDoc')

    try:
        db.table("organizations").insert({
            "name": org_name, "email": email, "phone": phone, 
            "password": password, "verified": False
        }).execute()

        msg = Message(f"ACTION REQUIRED: New Org {org_name}", recipients=[app.config['MAIL_USERNAME']])
        msg.body = f"Review Request:\nName: {org_name}\nEmail: {email}\nPhone: {phone}"
        if uploaded_file:
            msg.attach(uploaded_file.filename, uploaded_file.content_type, uploaded_file.read())

        mail.send(msg)
        return jsonify({"status": "success", "message": "Application submitted successfully."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- STARTUP ---
if __name__ == '__main__':
    # Render requires host 0.0.0.0 and a dynamic port
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
