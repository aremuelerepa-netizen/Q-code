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
    try:
        res = db.table("queue").select("id", count='exact').eq("org_id", org_id).lt("id", user_id).execute()
        return (res.count or 0) + 1
    except:
        return "?"

# --- 3. PAGE ROUTES ---
@app.route('/')
def home(): 
    return render_template('index.html')

@app.route('/status')
def status_view():
    if 'user_id' not in session: return redirect(url_for('home'))
    return render_template('status.html')

@app.route('/userpage')
def user_dashboard():
    if 'user_id' not in session: return redirect(url_for('home'))
    return render_template('userpage.html')

@app.route('/login')
def login_view(): return render_template('login page.html')

@app.route('/register')
def reg_view(): return render_template('org reg page.html')

@app.route('/super-admin')
def super_admin_view():
    if not session.get('is_super_admin'): return redirect(url_for('login_view'))
    # Fetch organizations that are NOT yet verified
    res = db.table("organizations").select("*").eq("verified", False).execute()
    return render_template('super_admin.html', pending_orgs=res.data)

@app.route('/admin')
def admin_dashboard():
    if 'org_id' not in session: return redirect(url_for('login_view'))
    org_name = session.get('org_name', 'Organization')
    return render_template('Admin page.html', org_name=org_name)

# --- 4. SUPER ADMIN ACTIONS ---

@app.route('/api/admin/approve-org/<org_id>', methods=['POST'])
def approve_org(org_id):
    """Allows Super Admin to approve a pending organization."""
    if not session.get('is_super_admin'): return jsonify({"status": "error"}), 403
    try:
        db.table("organizations").update({"verified": True}).eq("id", org_id).execute()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 5. USER AUTH (FRICTIONLESS & PERSONAL) ---

@app.route('/api/auth/join-frictionless', methods=['POST'])
def join_frictionless():
    data = request.json
    service_code = data.get('service_code')
    visitor_name = data.get('name', 'Guest User')
    device_token = generate_unique_code()
    
    try:
        res = db.table("queue").insert({
            "org_id": service_code, "visitor_name": visitor_name,
            "login_code": device_token, "entry_type": "WEB_QUICK"
        }).execute()
        
        session.clear()
        session.permanent = True
        session['user_id'] = res.data[0]['id']
        session['org_id'] = service_code
        
        return jsonify({"status": "success", "token": device_token})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/user-register', methods=['POST'])
def user_register():
    """Handles Personal Account Creation (Email/Password)."""
    data = request.json
    email = data.get('email')
    password = data.get('password') # In production, use hash (e.g. werkzeug.security)
    
    try:
        res = db.table("queue").insert({
            "email": email, 
            "login_code": generate_unique_code(),
            "entry_type": "PERSONAL_ACCT",
            "status": "active" # Placeholder for persistent accounts
        }).execute()
        
        # You could add a password column to the 'queue' table in SQL
        # Or create a separate 'users' table. Assuming 'queue' for now:
        db.table("queue").update({"phone": password}).eq("email", email).execute() # Using phone as temp pass field
        
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/login-with-code', methods=['POST'])
def login_with_code():
    res = db.table("queue").select("*").eq("login_code", request.json.get('login_code')).execute()
    if res.data:
        session.clear()
        session['user_id'] = res.data[0]['id']
        session['org_id'] = res.data[0]['org_id']
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 401

# --- 6. ORG REGISTRATION & LOGIN ---

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
        return jsonify({"status": "success"})
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
            session['org_id'] = str(org['id'])
            session['org_name'] = org['name']
            return jsonify({"status": "success", "redirect": "/admin"})
        return jsonify({"status": "pending"}), 403
    return jsonify({"status": "error"}), 401

# --- 7. POLLING & SERVICES ---

@app.route('/api/queue/poll', methods=['GET'])
def poll_status():
    if 'user_id' not in session: return jsonify({"pos": "?"}), 401
    pos = get_live_position(session['user_id'], session.get('org_id'))
    return jsonify({"pos": pos})

@app.route('/api/services/list', methods=['GET'])
def list_services():
    if 'org_id' not in session: return jsonify([]), 401
    res = db.table("services").select("*").eq("org_id", session['org_id']).execute()
    return jsonify(res.data)
            
# --- SUPER ADMIN ADVANCED ROUTES ---

@app.route('/api/admin/stats')
def get_platform_stats():
    """Returns high-level numbers for the dashboard cards."""
    if not session.get('is_super_admin'): return jsonify({}), 403
    
    org_count = db.table("organizations").select("id", count='exact').execute().count
    queue_count = db.table("queue").select("id", count='exact').execute().count
    pending = db.table("organizations").select("id", count='exact').eq("verified", False).execute().count
    
    return jsonify({
        "total_orgs": org_count,
        "total_users": queue_count,
        "pending_apps": pending
    })

@app.route('/api/admin/suspend-org/<org_id>', methods=['POST'])
def suspend_org(org_id):
    """Allows admin to temporarily disable a business account."""
    if not session.get('is_super_admin'): return jsonify({"status": "error"}), 403
    db.table("organizations").update({"verified": False}).eq("id", org_id).execute()
    return jsonify({"status": "success", "message": "Organization suspended"})
            
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

