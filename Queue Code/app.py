import os
import random
import string
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

app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_secure_v2")
app.permanent_session_lifetime = timedelta(days=7)

# --- 1. INITIALIZE CLIENTS ---
# Initialize DB once at the top to avoid reconnecting constantly
db: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Mail Config - UPDATED TO TLS (PORT 587) TO PREVENT RENDER CRASHES
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USE_SSL=False,
    MAIL_USERNAME=os.getenv("GMAIL_USER"),
    MAIL_PASSWORD=os.getenv("GMAIL_APP_PASSWORD"),
    MAIL_DEFAULT_SENDER=os.getenv("GMAIL_USER")
)
mail = Mail(app)

# --- 2. HELPER FUNCTIONS ---
def generate_unique_code():
    return 'QC-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# --- 3. PAGE ROUTES ---
@app.route('/')
def home(): return render_template('index.html')

@app.route('/login')
def login_view(): return render_template('login page.html')

@app.route('/register')
def reg_view(): return render_template('org reg page.html')

@app.route('/super-admin')
def super_admin_view():
    # Only allow if the session says they are super admin
    if not session.get('is_super_admin'): 
        return redirect(url_for('login_view'))
    res = db.table("organizations").select("*").eq("verified", False).execute()
    return render_template('super_admin.html', pending_orgs=res.data)

@app.route('/admin')
def admin_dashboard():
    if 'org_id' not in session: return redirect(url_for('login_view'))
    return render_template('Admin page.html')

# --- 4. ADMIN & ORG LOGIN LOGIC (FIXED: This was missing!) ---
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    email = data.get('email')
    password = data.get('password')

    # 1. Check Super Admin (From .env)
    if email == os.getenv("ADMIN_EMAIL") and password == os.getenv("ADMIN_PASSWORD"):
        session.clear()
        session.permanent = True
        session['is_super_admin'] = True
        return jsonify({"status": "success", "redirect": "/super-admin"})

    # 2. Check Regular Organization
    res = db.table("organizations").select("*").eq("email", email).execute()
    if res.data and res.data[0]['password'] == password:
        org = res.data[0]
        if org['verified']:
            session.update({
                'org_id': str(org['id']), 
                'org_name': org['name'], 
                'is_super_admin': False
            })
            return jsonify({"status": "success", "redirect": "/admin"})
        return jsonify({"status": "pending", "message": "Account awaiting verification"}), 403
    
    return jsonify({"status": "error", "message": "Invalid credentials"}), 401

# --- 5. USER AUTH (EMAIL OTP & LOGIN CODE) ---
@app.route('/api/auth/request-email-otp', methods=['POST'])
def request_email_otp():
    email = request.json.get('email')
    otp = str(random.randint(100000, 999999))
    session['temp_otp'] = otp
    session['temp_email'] = email
    
    try:
        msg = Message("Q-CODE Verification", recipients=[email])
        msg.body = f"Your one-time verification code is: {otp}"
        mail.send(msg)
        return jsonify({"status": "sent"})
    except Exception as e:
        print(f"MAIL ERROR: {e}")
        return jsonify({"status": "error", "message": "Mail server failed. Check App Password."}), 500

@app.route('/api/auth/verify-email-otp', methods=['POST'])
def verify_email_otp():
    user_otp = request.json.get('otp')
    if user_otp == session.get('temp_otp'):
        email = session.get('temp_email')
        login_code = generate_unique_code()
        
        # Upsert using email as the identifier now
        db.table("queue").upsert({
            "email": email,
            "login_code": login_code,
            "visitor_name": email.split('@')[0]
        }, on_conflict="email").execute()
        
        return jsonify({"status": "success", "login_code": login_code})
    return jsonify({"status": "invalid"}), 401

@app.route('/api/auth/login-with-code', methods=['POST'])
def login_with_code():
    code = request.json.get('login_code', '').strip().upper()
    res = db.table("queue").select("*").eq("login_code", code).execute()
    
    if res.data:
        user = res.data[0]
        session['user_email'] = user['email']
        return jsonify({"status": "success", "user": user})
    return jsonify({"status": "error", "message": "Invalid Login Code"}), 401

# --- 6. SIM GATEWAY & AI ---
@app.route('/api/sms/incoming', methods=['POST'])
def sim_webhook():
    data = request.json 
    sender_phone = data.get('from')
    service_code = data.get('message', '').strip().upper()

    res = db.table("organizations").select("name").eq("id", service_code).execute()
    if res.data:
        org_name = res.data[0]['name']
        db.table("queue").insert({
            "phone": sender_phone, "service_id": service_code, "entry_type": "SIM"
        }).execute()
        return jsonify({"to": sender_phone, "message": f"Q-CODE: Added to {org_name} queue."})
    return jsonify({"to": sender_phone, "message": "Q-CODE: Invalid Code."})

@app.route('/api/ai-chat', methods=['POST'])
def ai_chat():
    user_msg = request.json.get("message")
    try:
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": user_msg}],
            model="llama3-8b-8192",
        )
        return jsonify({"reply": completion.choices[0].message.content})
    except:
        return jsonify({"reply": "AI is offline."}), 500

# --- 7. ADMIN ACTIONS ---
@app.route('/api/admin/approve-org/<org_id>', methods=['POST'])
def approve_org(org_id):
    if not session.get('is_super_admin'): return jsonify({"status": "unauthorized"}), 403
    db.table("organizations").update({"verified": True}).eq("id", org_id).execute()
    return jsonify({"status": "success"})

@app.route('/api/admin/decline-org/<org_id>', methods=['POST'])
def decline_org(org_id):
    if not session.get('is_super_admin'): return jsonify({"status": "unauthorized"}), 403
    db.table("organizations").delete().eq("id", org_id).execute()
    return jsonify({"status": "success"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
