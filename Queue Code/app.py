import os
import random
import string
import requests
import smtplib
from email.message import EmailMessage
from datetime import timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from supabase import create_client, Client
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, 
            template_folder=os.path.join(base_dir, 'templates'),
            static_folder=os.path.join(base_dir, 'static'))

app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_secure_v2")
app.permanent_session_lifetime = timedelta(days=7)

# --- 1. INITIALIZE CLIENTS ---
db: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --- 2. HELPER FUNCTIONS ---
def generate_unique_code():
    return 'QC-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def send_free_email(to_email, subject, body_text):
    """FREE METHOD: Uses Gmail App Password. Render allows Port 465."""
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD") 
    
    msg = EmailMessage()
    msg.set_content(body_text)
    msg["Subject"] = subject
    msg["From"] = f"Q-CODE System <{gmail_user}>"
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(gmail_user, gmail_pass)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"EMAIL ERROR: {e}")
        return False

# --- 3. PAGE ROUTES ---
@app.route('/')
def home(): return render_template('index.html')

@app.route('/login')
def login_view(): return render_template('login page.html')

@app.route('/register')
def reg_view(): return render_template('org reg page.html')

@app.route('/super-admin')
def super_admin_view():
    if not session.get('is_super_admin'): return redirect(url_for('login_view'))
    res = db.table("organizations").select("*").eq("verified", False).execute()
    return render_template('super_admin.html', pending_orgs=res.data)

@app.route('/admin')
def admin_dashboard():
    if 'org_id' not in session: return redirect(url_for('login_view'))
    
    # FIX: Get real name from session or DB to replace "Admin Sarah"
    org_name = session.get('org_name', 'Organization')
    return render_template('Admin page.html', org_name=org_name)

# --- 4. ORG REGISTRATION & LOGIN ---

@app.route('/api/auth/register', methods=['POST'])
def register_org():
    # Handle both JSON and Form data to prevent 500 errors
    data = request.json if request.is_json else request.form
    
    name = data.get('orgName')
    email = data.get('email')
    phone = data.get('phone')
    password = data.get('password')
    
    try:
        db.table("organizations").insert({
            "name": name, "email": email, "phone": phone, 
            "password": password, "verified": False
        }).execute()
        
        # Notify Super Admin (Non-blocking)
        send_free_email(
            os.getenv("ADMIN_EMAIL"), 
            "New Org Application", 
            f"Organization {name} is waiting for approval."
        )
        return jsonify({"status": "success", "message": "Application submitted!"})
    except Exception as e:
        print(f"REG ERROR: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    email, password = data.get('email'), data.get('password')

    if email == os.getenv("ADMIN_EMAIL") and password == os.getenv("ADMIN_PASSWORD"):
        session.clear()
        session['is_super_admin'] = True
        return jsonify({"status": "success", "redirect": "/super-admin"})

    res = db.table("organizations").select("*").eq("email", email).execute()
    if res.data and res.data[0]['password'] == password:
        org = res.data[0]
        if org['verified']:
            session.clear()
            session.permanent = True
            session['org_id'] = str(org['id'])
            session['org_name'] = org['name']
            session['is_super_admin'] = False
            return jsonify({"status": "success", "redirect": "/admin"})
        return jsonify({"status": "pending", "message": "Awaiting verification"}), 403
    
    return jsonify({"status": "error", "message": "Invalid credentials"}), 401

# --- 5. SERVICE MANAGEMENT ---

@app.route('/api/services/create', methods=['POST'])
def create_service():
    if 'org_id' not in session: return jsonify({"status": "error"}), 401
    data = request.json
    try:
        db.table("services").insert({
            "org_id": session['org_id'],
            "name": data.get('name'),
            "start_time": data.get('start_time'),
            "end_time": data.get('end_time'),
            "avg_session": data.get('avg_time'),
            "staff_list": data.get('staff'),
            "required_fields": data.get('fields')
        }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/services/list', methods=['GET'])
def list_services():
    if 'org_id' not in session: return jsonify([]), 401
    try:
        res = db.table("services").select("*").eq("org_id", session['org_id']).execute()
        return jsonify(res.data)
    except Exception as e:
        print(f"DB Error: {e}")
        return jsonify([]), 500

# --- 6. USER AUTH (GMAIL OTP) ---

@app.route('/api/auth/request-email-otp', methods=['POST'])
def request_email_otp():
    email = request.json.get('email')
    otp = str(random.randint(100000, 999999))
    session['temp_otp'], session['temp_email'] = otp, email
    
    success = send_free_email(
        email, 
        "Q-CODE Verification", 
        f"Your verification code is: {otp}"
    )
    
    if success: return jsonify({"status": "sent"})
    return jsonify({"status": "error", "message": "Email delivery failed"}), 500

@app.route('/api/auth/verify-email-otp', methods=['POST'])
def verify_email_otp():
    user_otp = request.json.get('otp')
    if user_otp == session.get('temp_otp'):
        email = session.get('temp_email')
        login_code = generate_unique_code()
        
        db.table("queue").upsert({
            "email": email, "login_code": login_code, "visitor_name": email.split('@')[0]
        }, on_conflict="email").execute()
        
        return jsonify({"status": "success", "login_code": login_code})
    return jsonify({"status": "invalid"}), 401

# --- 7. SIM WEBHOOK ---

@app.route('/api/sms/incoming', methods=['POST'])
def sim_webhook():
    data = request.json 
    sender_phone = data.get('from')
    msg_body = data.get('message', '').strip().upper()

    res = db.table("organizations").select("name", "id").eq("id", msg_body).execute()
    if res.data:
        org = res.data[0]
        db.table("queue").insert({
            "phone": sender_phone, "org_id": org['id'], "entry_type": "SIM"
        }).execute()
        reply = f"Q-CODE: You are in line for {org['name']}."
    else:
        reply = "Q-CODE: Invalid Service Code."

    return jsonify({"to": sender_phone, "message": reply})
            
@app.route('/api/auth/login-with-code', methods=['POST'])
def login_with_code():
    data = request.json
    code = data.get('login_code')
    
    # Check if the code exists in the queue table
    res = db.table("queue").select("*").eq("login_code", code).execute()
    
    if res.data:
        user = res.data[0]
        session.clear()
        session['user_id'] = user['id']
        session['user_email'] = user.get('email')
        return jsonify({"status": "success"})
    
    return jsonify({"status": "error", "message": "Invalid Q-CODE"}), 401
            
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)

