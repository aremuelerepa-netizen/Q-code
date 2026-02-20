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

# Path detection for "Queue Code" folder
base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, 
            template_folder=os.path.join(base_dir, 'templates'),
            static_folder=os.path.join(base_dir, 'static'))

app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_final_key")
app.permanent_session_lifetime = timedelta(days=1)

# --- DB & AI CLIENTS ---
def get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key: return None
    try:
        return create_client(url.strip(), key.strip())
    except: return None

def get_groq():
    key = os.getenv("GROQ_API_KEY")
    return Groq(api_key=key) if key else None

# --- MAIL CONFIG ---
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=465,
    MAIL_USERNAME=os.getenv("GMAIL_USER"),
    MAIL_PASSWORD=os.getenv("GMAIL_APP_PASSWORD"),
    MAIL_USE_SSL=True,
    MAIL_DEFAULT_SENDER=os.getenv("GMAIL_USER")
)
mail = Mail(app)

# --- ROUTES ---

@app.route('/')
def home(): return render_template('index.html')

@app.route('/login')
def login_view(): return render_template('login page.html')

@app.route('/register')
def reg_view(): return render_template('org reg page.html')

@app.route('/super-admin')
def super_admin_view():
    if not session.get('is_super_admin'): return redirect(url_for('login_view'))
    db = get_supabase()
    data = []
    if db:
        res = db.table("organizations").select("*").eq("verified", False).execute()
        data = res.data
    return render_template('super_admin.html', pending_orgs=data)

# --- REGISTRATION API (Fixed names) ---
@app.route('/api/auth/register', methods=['POST'])
def register_org():
    db = get_supabase()
    if not db: return jsonify({"status": "error", "message": "Database error"}), 500
    
    # Check if data is JSON or Form
    if request.is_json:
        data = request.json
        name = data.get('orgName')
        email = data.get('email')
        phone = data.get('phone')
        password = data.get('password')
    else:
        name = request.form.get('orgName')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')

    try:
        db.table("organizations").insert({
            "name": name,
            "email": email,
            "phone": phone,
            "password": password,
            "verified": False
        }).execute()
        return jsonify({"status": "success", "message": "Registration successful! Awaiting approval."})
    except Exception as e:
        print(f"REG ERROR: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    email, password = data.get('email'), data.get('password')

    if email == os.getenv("ADMIN_EMAIL") and password == os.getenv("ADMIN_PASSWORD"):
        session.clear()
        session.permanent = True
        session['is_super_admin'] = True
        return jsonify({"status": "success", "redirect": "/super-admin"})

    db = get_supabase()
    if not db: return jsonify({"status": "error"}), 500
    
    res = db.table("organizations").select("*").eq("email", email).execute()
    if res.data and res.data[0]['password'] == password:
        org = res.data[0]
        if org['verified']:
            session.update({'org_id': str(org['id']), 'org_name': org['name'], 'is_super_admin': False})
            return jsonify({"status": "success", "redirect": "/admin"})
        return jsonify({"status": "pending"}), 403
    return jsonify({"status": "error"}), 401

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
