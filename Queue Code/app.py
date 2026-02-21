import os
import random
import string
import requests
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

def send_api_email(to_email, subject, body_html):
    """Bypasses Render's SMTP block using Resend API"""
    api_key = os.getenv("RESEND_API_KEY")
    try:
        res = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": "Q-CODE <onboarding@resend.dev>",
                "to": [to_email],
                "subject": subject,
                "html": body_html
            }
        )
        return res.status_code in [200, 201]
    except:
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
    return render_template('Admin page.html')

# --- 4. ORG REGISTRATION & LOGIN ---

@app.route('/api/auth/register', methods=['POST'])
def register_org():
    # Handle Form Data (Multipart for file support)
    name = request.form.get('orgName')
    email = request.form.get('email')
    phone = request.form.get('phone')
    password = request.form.get('password')
    
    try:
        # Save to DB
        db.table("organizations").insert({
            "name": name, "email": email, "phone": phone, 
            "password": password, "verified": False
        }).execute()
        
        # Notify Super Admin via Email
        send_api_email(
            os.getenv("ADMIN_EMAIL"), 
            "New Org Application", 
            f"Organization <b>{name}</b> has registered and is waiting for your approval."
        )
        return jsonify({"status": "success", "message": "Application submitted!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    email, password = data.get('email'), data.get('password')

    # Check Super Admin
    if email == os.getenv("ADMIN_EMAIL") and password == os.getenv("ADMIN_PASSWORD"):
        session.clear()
        session['is_super_admin'] = True
        return jsonify({"status": "success", "redirect": "/super-admin"})

    # Check Regular Org
    res = db.table("organizations").select("*").eq("email", email).execute()
    if res.data and res.data[0]['password'] == password:
        org = res.data[0]
        if org['verified']:
            session.update({'org_id': str(org['id']), 'org_name': org['name'], 'is_super_admin': False})
            return jsonify({"status": "success", "redirect": "/admin"})
        return jsonify({"status": "pending", "message": "Awaiting verification"}), 403
    
    return jsonify({"status": "error", "message": "Invalid credentials"}), 401

# --- 5. USER AUTH (EMAIL OTP & LOGIN CODE) ---

@app.route('/api/auth/request-email-otp', methods=['POST'])
def request_email_otp():
    email = request.json.get('email')
    otp = str(random.randint(100000, 999999))
    session['temp_otp'], session['temp_email'] = otp, email
    
    success = send_api_email(
        email, 
        "Q-CODE Verification", 
        f"Your verification code is: <b style='font-size:24px;'>{otp}</b>"
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

@app.route('/api/auth/login-with-code', methods=['POST'])
def login_with_code():
    code = request.json.get('login_code', '').strip().upper()
    res = db.table("queue").select("*").eq("login_code", code).execute()
    if res.data:
        session['user_email'] = res.data[0]['email']
        return jsonify({"status": "success", "user": res.data[0]})
    return jsonify({"status": "error", "message": "Invalid Code"}), 401

# --- 6. ADMIN ACTIONS ---

@app.route('/api/admin/approve-org/<org_id>', methods=['POST'])
def approve_org(org_id):
    if not session.get('is_super_admin'): return jsonify({"status": "unauthorized"}), 403
    
    res = db.table("organizations").update({"verified": True}).eq("id", org_id).execute()
    if res.data:
        org = res.data[0]
        send_api_email(org['email'], "Account Approved!", f"Hello {org['name']}, your account is now active.")
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
