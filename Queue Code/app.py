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

# --- 1. DYNAMIC PATH RESOLUTION ---
base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(base_dir, 'templates')
static_dir = os.path.join(base_dir, 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_final_key")
app.permanent_session_lifetime = timedelta(days=1)

# --- 2. SAFE CLIENT INITIALIZATION ---
supabase_client = None
def get_supabase():
    global supabase_client
    if supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if url and key:
            try:
                supabase_client = create_client(url, key)
            except Exception as e:
                print(f"Supabase Init Error: {e}")
    return supabase_client

groq_client = None
def get_groq():
    global groq_client
    if groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if api_key:
            try:
                groq_client = Groq(api_key=api_key)
            except Exception as e:
                print(f"Groq Init Error: {e}")
    return groq_client

# --- 3. MAIL CONFIG ---
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=465,
    MAIL_USERNAME=os.getenv("GMAIL_USER"),
    MAIL_PASSWORD=os.getenv("GMAIL_APP_PASSWORD"),
    MAIL_USE_SSL=True,
    MAIL_DEFAULT_SENDER=os.getenv("GMAIL_USER")
)
mail = Mail(app)

# --- 4. PAGE ROUTING ---

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
    if not session.get('is_super_admin'):
        return redirect(url_for('login_view'))
    
    db = get_supabase()
    pending_orgs = []
    if db:
        try:
            res = db.table("organizations").select("*").eq("verified", False).execute()
            pending_orgs = res.data
        except Exception as e:
            print(f"DB Fetch Error: {e}")
            
    return render_template('super_admin.html', pending_orgs=pending_orgs)

# --- 5. AUTHENTICATION ---

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    email = data.get('email')
    password = data.get('password')

    if email == os.getenv("ADMIN_EMAIL") and password == os.getenv("ADMIN_PASSWORD"):
        session.clear()
        session.permanent = True
        session['is_super_admin'] = True
        return jsonify({"status": "success", "redirect": "/super-admin"})

    db = get_supabase()
    if not db: return jsonify({"status": "error", "message": "DB disconnected"}), 500

    try:
        res = db.table("organizations").select("*").eq("email", email).execute()
        if res.data and res.data[0]['password'] == password:
            org = res.data[0]
            if org.get('verified'):
                session.clear()
                session.permanent = True
                session['org_id'] = str(org['id'])
                session['org_name'] = org['name']
                session['is_super_admin'] = False
                return jsonify({"status": "success", "redirect": "/admin"})
            return jsonify({"status": "pending", "message": "Verification required"}), 403
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
    return jsonify({"status": "error", "message": "Invalid login"}), 401

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_view'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
