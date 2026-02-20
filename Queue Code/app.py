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
app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_default_key")
app.permanent_session_lifetime = timedelta(days=1)

# --- 2. INITIALIZE CLIENTS SAFELY ---
# We wrap this in a check to prevent the app from crashing during build
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("CRITICAL: Supabase credentials missing!")
    supabase = None
else:
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"FAILED TO CONNECT TO SUPABASE: {e}")
        supabase = None

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Termii Config
TERMII_API_KEY = os.getenv("TERMII_API_KEY")
TERMII_SENDER_ID = os.getenv("TERMII_SENDER_ID", "N-Alert")

def send_sms_via_termii(phone, message):
    if not TERMII_API_KEY: return None
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
    
    if not supabase:
        return "Database Configuration Error. Please check API Keys.", 500

    try:
        res = supabase.table("organizations").select("*").eq("verified", False).execute()
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

    # A. MASTER ADMIN LOGIN (Checks ENV first - doesn't need Supabase)
    if email == os.getenv("ADMIN_EMAIL") and password == os.getenv("ADMIN_PASSWORD"):
        session.clear()
        session.permanent = True
        session['is_super_admin'] = True
        return jsonify({"status": "success", "redirect": "/super-admin"})

    # B. ORGANIZATION LOGIN (Needs Supabase)
    if not supabase:
        return jsonify({"status": "error", "message": "Database disconnected"}), 500

    try:
        res = supabase.table("organizations").select("*").eq("email", email).execute()
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
    if not supabase: return jsonify({"status": "error", "message": "Database offline"}), 500
    
    org_name = request.form.get('orgName')
    email = request.form.get('email')
    phone = request.form.get('phone')
    password = request.form.get('password') 
    uploaded_file = request.files.get('verificationDoc')

    try:
        supabase.table("organizations").insert({
            "name": org_name, "email": email, "phone": phone, 
            "password": password, "verified": False
        }).execute()

        msg = Message(f"ACTION REQUIRED: New Org {org_name}", recipients=[app.config['MAIL_USERNAME']])
        msg.body = f"Review Request:\nName: {org_name}\nEmail: {email}\nPhone: {phone}"
        if uploaded_file:
            msg.attach(uploaded_file.filename, uploaded_file.content_type, uploaded_file.read())

        mail.send(msg)
        return jsonify({"status": "success", "message": "Application submitted."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- STARTUP ---
if __name__ == '__main__':
    # Use 0.0.0.0 for Render and dynamically find the PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
