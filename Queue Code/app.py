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

app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_final_key")
app.permanent_session_lifetime = timedelta(days=1)

# --- 1. INITIALIZE CLIENTS ---
def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key: return None
    return create_client(url.strip(), key.strip())

db = get_supabase()
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Termii Config
TERMII_API_KEY = os.getenv("TERMII_API_KEY")
TERMII_SENDER_ID = os.getenv("TERMII_SENDER_ID", "N-Alert")

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

# --- 2. HELPER FUNCTIONS ---
def send_sms(phone, message):
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
        res = requests.post(url, json=payload)
        return res.json()
    except: return None

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
    return render_template('Admin page.html')

# --- 4. AUTH & REGISTRATION API ---

@app.route('/api/auth/register', methods=['POST'])
def register_org():
    # Handle both JSON and Form Data (for files)
    name = request.form.get('orgName')
    email = request.form.get('email')
    phone = request.form.get('phone')
    password = request.form.get('password')
    uploaded_file = request.files.get('verificationDoc')

    try:
        # 1. Save to Database
        db.table("organizations").insert({
            "name": name, "email": email, "phone": phone, 
            "password": password, "verified": False
        }).execute()

        # 2. Send Alert Email with Attachment to YOU (Admin)
        if uploaded_file:
            msg = Message(f"New Registration: {name}", recipients=[app.config['MAIL_USERNAME']])
            msg.body = f"Organization {name} has applied. Review the attached CAC/ID document."
            # Read file once for the attachment
            file_data = uploaded_file.read()
            msg.attach(uploaded_file.filename, uploaded_file.content_type, file_data)
            mail.send(msg)

        return jsonify({"status": "success", "message": "Application submitted for review."})
    except Exception as e:
        print(f"REG ERROR: {e}")
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

    # Regular Org Check
    res = db.table("organizations").select("*").eq("email", email).execute()
    if res.data and res.data[0]['password'] == password:
        org = res.data[0]
        if org['verified']:
            session.update({'org_id': str(org['id']), 'org_name': org['name'], 'is_super_admin': False})
            return jsonify({"status": "success", "redirect": "/admin"})
        return jsonify({"status": "pending", "message": "Account awaiting verification"}), 403
    
    return jsonify({"status": "error", "message": "Invalid credentials"}), 401

# --- 5. SUPER ADMIN ACTION API (The missing link!) ---

@app.route('/api/admin/approve-org/<org_id>', methods=['POST'])
def approve_org(org_id):
    if not session.get('is_super_admin'): return jsonify({"status": "unauthorized"}), 403
    
    try:
        # 1. Update status in DB
        res = db.table("organizations").update({"verified": True}).eq("id", org_id).execute()
        
        if res.data:
            org = res.data[0]
            # 2. Send Acceptance SMS
            sms_msg = f"Q-CODE: Congratulations {org['name']}! Your account is verified. You can now log in."
            send_sms(org['phone'], sms_msg)
            
            # 3. Send Acceptance Email
            mail_msg = Message("Q-CODE: Account Activated", recipients=[org['email']])
            mail_msg.body = f"Hello {org['name']},\n\nYour organization has been verified. Welcome to Q-CODE!"
            mail.send(mail_msg)

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/decline-org/<org_id>', methods=['POST'])
def decline_org(org_id):
    if not session.get('is_super_admin'): return jsonify({"status": "unauthorized"}), 403
    try:
        db.table("organizations").delete().eq("id", org_id).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
