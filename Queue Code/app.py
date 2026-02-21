import os
import random
import string
import requests
import smtplib
from email.message import EmailMessage
from datetime import timedelta
from functools import wraps
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
    """Uses Gmail App Password. Wrapped in try/except to prevent server SIGKILL."""
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD") 
    
    msg = EmailMessage()
    msg.set_content(body_text)
    msg["Subject"] = subject
    msg["From"] = f"Q-CODE System <{gmail_user}>"
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=5) as smtp:
            smtp.login(gmail_user, gmail_pass)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"NON-CRITICAL EMAIL ERROR: {e}")
        return False

def get_live_position(user_id, org_id):
    """Calculates how many people are ahead of a specific user in a specific queue."""
    try:
        # Count users in the same org who joined BEFORE this user
        res = db.table("queue").select("id", count='exact').eq("org_id", org_id).lt("id", user_id).execute()
        return (res.count or 0) + 1
    except:
        return "?"

# Middleware to protect separate feature pages (Identity Grows Later)
def upgrade_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('home'))
        
        res = db.table("queue").select("email").eq("id", session['user_id']).single().execute()
        if not res.data or not res.data.get('email'):
            return render_template('upgrade_prompt.html')
        return f(*args, **kwargs)
    return decorated_function

# --- 3. PAGE ROUTES ---
@app.route('/')
def home(): 
    return render_template('index.html')

@app.route('/status')
def status_view():
    """Live status page for the user."""
    if 'user_id' not in session:
        return redirect(url_for('home'))
    return render_template('status.html')

@app.route('/userpage')
def user_dashboard():
    """The mobile-app style dashboard."""
    if 'user_id' not in session:
        return redirect(url_for('home'))
    return render_template('userpage.html')

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
    org_name = session.get('org_name', 'Organization')
    return render_template('Admin page.html', org_name=org_name)

# --- 4. FRICTIONLESS USER FLOW ---

@app.route('/api/auth/join-frictionless', methods=['POST'])
def join_frictionless():
    """Uber-style frictionless onboarding: Just a name and service code."""
    data = request.json
    service_code = data.get('service_code')
    visitor_name = data.get('name', 'Guest User')
    device_token = generate_unique_code()
    
    try:
        res = db.table("queue").insert({
            "org_id": service_code,
            "visitor_name": visitor_name,
            "login_code": device_token,
            "entry_type": "WEB_QUICK"
        }).execute()
        
        session.clear()
        session.permanent = True
        session['user_id'] = res.data[0]['id']
        session['user_token'] = device_token
        session['org_id'] = service_code # Keep track of which queue they joined
        
        return jsonify({"status": "success", "token": device_token})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/upgrade-identity', methods=['POST'])
def upgrade_identity():
    """Later, if they want dashboard features, they add an email."""
    if 'user_id' not in session: return jsonify({"status": "error"}), 401
    
    email = request.json.get('email')
    try:
        db.table("queue").update({"email": email}).eq("id", session['user_id']).execute()
        send_free_email(email, "Q-CODE Verified", "Your queue session is now linked to your email.")
        return jsonify({"status": "success", "message": "Identity upgraded!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/queue/poll', methods=['GET'])
def poll_status():
    """API for the status page to get the current position number."""
    if 'user_id' not in session: return jsonify({"pos": "?"}), 401
    pos = get_live_position(session['user_id'], session.get('org_id'))
    return jsonify({"pos": pos})

# --- 5. ORG REGISTRATION & LOGIN ---

@app.route('/api/auth/register', methods=['POST'])
def register_org():
    data = request.json if request.is_json else request.form
    name = data.get('orgName') or data.get('business_name')
    email, phone, password = data.get('email'), data.get('phone'), data.get('password')
    
    try:
        db.table("organizations").insert({
            "name": name, "email": email, "phone": phone, 
            "password": password, "verified": False
        }).execute()
        send_free_email(os.getenv("ADMIN_EMAIL"), "New Org Application", f"Org {name} is waiting.")
        return jsonify({"status": "success", "message": "Application submitted!"})
    except Exception as e:
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

# --- 6. SERVICE MANAGEMENT & USER AUTH ---

@app.route('/api/services/create', methods=['POST'])
def create_service():
    if 'org_id' not in session: return jsonify({"status": "error"}), 401
    data = request.json
    try:
        db.table("services").insert({
            "org_id": session['org_id'], "name": data.get('name'),
            "start_time": data.get('start_time'), "end_time": data.get('end_time'),
            "avg_session": data.get('avg_time'), "staff_list": data.get('staff'),
            "required_fields": data.get('fields')
        }).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/services/list', methods=['GET'])
def list_services():
    if 'org_id' not in session: return jsonify([]), 401
    res = db.table("services").select("*").eq("org_id", session['org_id']).execute()
    return jsonify(res.data)

@app.route('/api/auth/request-email-otp', methods=['POST'])
def request_email_otp():
    email = request.json.get('email')
    otp = str(random.randint(100000, 999999))
    session['temp_otp'], session['temp_email'] = otp, email
    if send_free_email(email, "Q-CODE Verification", f"Your code: {otp}"):
        return jsonify({"status": "sent"})
    return jsonify({"status": "error"}), 500

@app.route('/api/auth/verify-email-otp', methods=['POST'])
def verify_email_otp():
    if request.json.get('otp') == session.get('temp_otp'):
        email = session.get('temp_email')
        login_code = generate_unique_code()
        db.table("queue").upsert({"email": email, "login_code": login_code}, on_conflict="email").execute()
        return jsonify({"status": "success", "login_code": login_code})
    return jsonify({"status": "invalid"}), 401

@app.route('/api/auth/login-with-code', methods=['POST'])
def login_with_code():
    res = db.table("queue").select("*").eq("login_code", request.json.get('login_code')).execute()
    if res.data:
        session.clear()
        session['user_id'] = res.data[0]['id']
        session['org_id'] = res.data[0]['org_id']
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 401

@app.route('/api/sms/incoming', methods=['POST'])
def sim_webhook():
    data = request.json 
    sender_phone, msg_body = data.get('from'), data.get('message', '').strip().upper()
    res = db.table("organizations").select("name", "id").eq("id", msg_body).execute()
    if res.data:
        org = res.data[0]
        db.table("queue").insert({"phone": sender_phone, "org_id": org['id'], "entry_type": "SIM"}).execute()
        reply = f"Q-CODE: In line for {org['name']}."
    else:
        reply = "Q-CODE: Invalid Service Code."
    return jsonify({"to": sender_phone, "message": reply})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
