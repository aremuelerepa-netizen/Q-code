import os
import random
import requests
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_mail import Mail, Message
from supabase import create_client, Client
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# Secure secret key from .env or default for dev
app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_super_secure_key")

# --- 1. INITIALIZE CLIENTS ---
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

TERMII_API_KEY = os.getenv("TERMII_API_KEY")
TERMII_SENDER_ID = os.getenv("TERMII_SENDER_ID", "N-Alert")

def send_sms_via_termii(phone, message):
    url = "https://api.ng.termii.com/api/sms/send"
    payload = {
        "api_key": TERMII_API_KEY,
        "to": phone,
        "from": TERMII_SENDER_ID,
        "sms": message,
        "type": "plain",
        "channel": "dnd"
    }
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(url, headers=headers, json=payload)
        return response.json()
    except Exception as e:
        print(f"Termii Error: {e}")
        return None

# Mail Config
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USERNAME'] = os.getenv("GMAIL_USER")
app.config['MAIL_PASSWORD'] = os.getenv("GMAIL_APP_PASSWORD") 
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_DEFAULT_SENDER'] = os.getenv("GMAIL_USER")
mail = Mail(app)

# --- 2. PAGE ROUTING ---
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
    # Organization Dashboard Access
    if 'org_id' not in session: 
        return redirect(url_for('login_view'))
    return render_template('Admin page.html', org_name=session.get('org_name'))

@app.route('/super-admin')
def super_admin_view():
    # YOUR Private Master Dashboard Access
    if not session.get('is_super_admin'):
        return redirect(url_for('login_view'))
    
    # Get all organizations that are NOT YET verified
    res = supabase.table("organizations").select("*").eq("verified", False).execute()
    return render_template('super_admin.html', pending_orgs=res.data)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_view'))

# --- 3. AUTHENTICATION (LOGIN & REGISTER) ---

@app.route('/api/auth/register', methods=['POST'])
def register_org():
    org_name = request.form.get('orgName')
    email = request.form.get('email')
    phone = request.form.get('phone')
    password = request.form.get('password') 
    uploaded_file = request.files.get('verificationDoc')

    try:
        # 1. Save to Supabase
        supabase.table("organizations").insert({
            "name": org_name, "email": email, "phone": phone, 
            "password": password, "verified": False
        }).execute()

        # 2. Notify YOU (Owner) via Email with Attachment
        msg = Message(f"ACTION REQUIRED: New Org {org_name}", recipients=[app.config['MAIL_USERNAME']])
        msg.body = f"Review Request:\nName: {org_name}\nEmail: {email}\nPhone: {phone}"
        
        if uploaded_file:
            file_content = uploaded_file.read()
            msg.attach(uploaded_file.filename, uploaded_file.content_type, file_content)

        mail.send(msg)
        return jsonify({"status": "success", "message": "Pending admin approval."})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    # A. CHECK IF IT IS THE OWNER (YOU)
    if email == os.getenv("ADMIN_EMAIL") and password == os.getenv("ADMIN_PASSWORD"):
        session['is_super_admin'] = True
        return jsonify({"status": "success", "redirect": "/super-admin"})

    # B. CHECK IF IT IS AN ORGANIZATION
    res = supabase.table("organizations").select("*").eq("email", email).execute()
    if res.data:
        org = res.data[0]
        if org['password'] == password:
            if org.get('verified'):
                session['org_id'] = org['id']
                session['org_name'] = org['name']
                session['is_super_admin'] = False
                return jsonify({"status": "success", "redirect": "/admin"})
            else:
                return jsonify({"status": "pending", "message": "Account awaiting verification."}), 403
        return jsonify({"status": "error", "message": "Invalid credentials"}), 401
    
    return jsonify({"status": "error", "message": "User not found"}), 404

# --- 4. MASTER ADMIN ACTIONS ---

@app.route('/api/admin/approve-org/<int:org_id>', methods=['POST'])
def approve_org(org_id):
    if not session.get('is_super_admin'): return jsonify({"status": "denied"}), 403

    res = supabase.table("organizations").update({"verified": True}).eq("id", org_id).execute()
    if res.data:
        org = res.data[0]
        # Notify via Email
        try:
            msg = Message("Q-Code: Account Verified!", recipients=[org['email']])
            msg.body = f"Hello {org['name']},\n\nYour account is now active. You can log in."
            mail.send(msg)
        except: pass

        # Notify via SMS (Termii)
        send_sms_via_termii(org['phone'], f"Hello {org['name']}, your Q-Code account is now active!")
        
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 404

@app.route('/api/admin/reject-org/<int:org_id>', methods=['POST'])
def reject_org(org_id):
    if not session.get('is_super_admin'): return jsonify({"status": "denied"}), 403
    supabase.table("organizations").delete().eq("id", org_id).execute()
    return jsonify({"status": "success"})

# --- 5. OTP & QUEUE LOGIC ---

@app.route('/api/auth/request-otp', methods=['POST'])
def request_otp():
    phone = request.json.get('phone')
    otp = str(random.randint(100000, 999999))
    supabase.table("otp_codes").upsert({"phone": phone, "code": otp}).execute()
    send_sms_via_termii(phone, f"Your Q-CODE verification code is: {otp}")
    return jsonify({"status": "sent"})

@app.route('/api/auth/verify-otp', methods=['POST'])
def verify_otp():
    phone = request.json.get('phone')
    user_code = request.json.get('code')
    res = supabase.table("otp_codes").select("code").eq("phone", phone).single().execute()
    if res.data and res.data['code'] == user_code:
        session['user_phone'] = phone
        return jsonify({"status": "success"})
    return jsonify({"status": "invalid_code"}), 401

if __name__ == '__main__':
    app.run(debug=True, port=5000)
