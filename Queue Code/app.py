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
# Change this secret key in production
app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_secure_key")

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
app.config['MAIL_PASSWORD'] = os.getenv("GMAIL_APP_PASSWORD") # Must be 16-char App Password
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
    if 'org_id' not in session: 
        return redirect(url_for('login_view'))
    return render_template('Admin page.html', org_name=session.get('org_name'))

# --- 3. AUTHENTICATION (LOGIN & REGISTER) ---

@app.route('/api/auth/register', methods=['POST'])
def register_org():
    org_name = request.form.get('orgName')
    email = request.form.get('email')
    phone = request.form.get('phone')
    password = request.form.get('password') 
    uploaded_file = request.files.get('verificationDoc')

    try:
        # 1. Insert into Supabase with verified=False
        supabase.table("organizations").insert({
            "name": org_name, 
            "email": email, 
            "phone": phone, 
            "password": password, 
            "verified": False
        }).execute()

        # 2. Notify YOU (The Admin) via Email
        msg = Message(
            subject=f"New Registration: {org_name}",
            recipients=[app.config['MAIL_USERNAME']] # Sends to your own email
        )
        msg.body = f"New Organization Request:\nName: {org_name}\nEmail: {email}\nPhone: {phone}\n\nPlease verify this document in Supabase."
        
        if uploaded_file:
            # Important: Read once and attach
            file_content = uploaded_file.read()
            msg.attach(uploaded_file.filename, uploaded_file.content_type, file_content)

        mail.send(msg)
        return jsonify({"status": "success", "message": "Registered! Waiting for admin approval."})

    except Exception as e:
        print(f"Registration Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    res = supabase.table("organizations").select("*").eq("email", email).execute()
    
    if res.data:
        org = res.data[0]
        if org['password'] == password:
            # CHECK VERIFICATION STATUS
            if org.get('verified') == True:
                session['org_id'] = org['id']
                session['org_name'] = org['name']
                return jsonify({"status": "success", "redirect": "/admin"})
            else:
                return jsonify({
                    "status": "pending", 
                    "message": "Account pending admin approval. You will receive an email once verified."
                }), 403
        return jsonify({"status": "error", "message": "Invalid password"}), 401
    
    return jsonify({"status": "error", "message": "Organization not found"}), 404

# --- 4. ADMIN APPROVAL SYSTEM ---

@app.route('/api/admin/approve-org/<int:org_id>', methods=['POST'])
def approve_org(org_id):
    # This updates the DB to allow them to login
    res = supabase.table("organizations").update({"verified": True}).eq("id", org_id).execute()
    
    if res.data:
        org = res.data[0]
        # Notify the User via Email
        try:
            msg = Message("Q-Code: Account Approved!", recipients=[org['email']])
            msg.body = f"Hello {org['name']}, your account is now active. You can login now."
            mail.send(msg)
        except: pass

        # Notify via SMS
        send_sms_via_termii(org['phone'], "Q-Code: Your account is now active! Log in at the enterprise portal.")
        
        return jsonify({"status": "success", "message": "Organization approved and notified."})
    return jsonify({"status": "error"}), 404

# --- 5. OTP & QUEUE LOGIC ---

@app.route('/api/auth/request-otp', methods=['POST'])
def request_otp():
    phone = request.json.get('phone')
    otp = str(random.randint(100000, 999999))
    supabase.table("otp_codes").upsert({"phone": phone, "code": otp}).execute()
    
    result = send_sms_via_termii(phone, f"Your Q-CODE verification code is: {otp}")
    if result and (result.get("message_id") or result.get("status") == "success"):
        return jsonify({"status": "sent"})
    return jsonify({"status": "error"}), 500

@app.route('/api/auth/verify-otp', methods=['POST'])
def verify_otp():
    phone = request.json.get('phone')
    user_code = request.json.get('code')
    res = supabase.table("otp_codes").select("code").eq("phone", phone).single().execute()
    
    if res.data and res.data['code'] == user_code:
        session['user_phone'] = phone
        user_queue = supabase.table("queue").select("*").eq("phone", phone).execute()
        return jsonify({
            "status": "success", 
            "is_returning": len(user_queue.data) > 0, 
            "data": user_queue.data[0] if user_queue.data else None
        })
    return jsonify({"status": "invalid_code"}), 401

if __name__ == '__main__':
    app.run(debug=True, port=5000)
