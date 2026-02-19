import os
import json
import random
import requests
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_mail import Mail, Message
from supabase import create_client, Client
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "qcode_2024_dev")

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
mail = Mail(app)

# --- 2. PAGE ROUTING ---
@app.route('/')
def home(): return render_template('index.html')

@app.route('/login')
def login_view(): return render_template('login page.html')

@app.route('/register')
def reg_view(): return render_template('org reg page.html')

@app.route('/admin')
def admin_view():
    if 'org_id' not in session: return redirect(url_for('login_view'))
    return render_template('Admin page.html')

@app.route('/user-page')
def user_view():
    if 'user_phone' not in session: return redirect(url_for('home'))
    return render_template('Userpage.html')

# --- 3. OTP SYSTEM ---
@app.route('/api/auth/request-otp', methods=['POST'])
def request_otp():
    phone = request.json.get('phone')
    otp = str(random.randint(100000, 999999))
    supabase.table("otp_codes").upsert({"phone": phone, "code": otp}).execute()
    msg = f"Your Q-CODE verification code is: {otp}"
    result = send_sms_via_termii(phone, msg)
    if result and result.get("message_id"):
        return jsonify({"status": "sent"})
    return jsonify({"status": "error"}), 500

@app.route('/api/auth/verify-otp', methods=['POST'])
def verify_otp():
    phone = request.json.get('phone')
    user_code = request.json.get('code')
    res = supabase.table("otp_codes").select("code").eq("phone", phone).single().execute()
    if res.data and res.data['code'] == user_code:
        session['user_phone'] = phone
        user_data = supabase.table("queue").select("*").eq("phone", phone).execute()
        return jsonify({"status": "success", "is_returning": len(user_data.data) > 0, "data": user_data.data[0] if user_data.data else None})
    return jsonify({"status": "invalid_code"}), 401

# --- 4. OFFLINE WEBHOOK ---
@app.route('/api/sms/incoming', methods=['POST'])
def sms_webhook():
    data = request.json
    phone = data.get('sender')
    text = data.get('message', '').upper().strip()
    if text.startswith("JOIN"):
        parts = text.split(" ")
        if len(parts) >= 3:
            supabase.table("queue").insert({"visitor_name": " ".join(parts[2:]), "phone": phone, "service_id": parts[1], "entry_type": "SMS"}).execute()
            send_sms_via_termii(phone, f"Success! You're in the queue. Track at your primary URL.")
    return "OK", 200

# --- 5. REGISTRATION & ADMIN CONFIRMATION ---

@app.route('/api/auth/register', methods=['POST'])
def register_org():
    org_name = request.form.get('orgName')
    email = request.form.get('email')
    phone = request.form.get('phone') # Ensure this is in your HTML form
    uploaded_file = request.files.get('verificationDoc')

    # Save to Supabase (verified=False)
    supabase.table("organizations").insert({"name": org_name, "email": email, "phone": phone, "verified": False}).execute()

    try:
        # Alert YOU (the admin)
        msg = Message(f"New Org Registration: {org_name}", sender=app.config['MAIL_USERNAME'], recipients=[app.config['MAIL_USERNAME']])
        if uploaded_file:
            file_data = uploaded_file.read() # Read the file into memory
            msg.attach(uploaded_file.filename, uploaded_file.content_type, file_data)
        mail.send(msg)
        return jsonify({"status": "success", "message": "Pending approval"})
    except Exception as e:
        print(f"Mail Error: {e}")
        return jsonify({"status": "success", "note": "Saved, but alert failed"})

# NEW ROUTE: Call this when YOU click 'Approve' in your admin panel
@app.route('/api/admin/approve-org/<int:org_id>', methods=['POST'])
def approve_org(org_id):
    # 1. Update DB
    res = supabase.table("organizations").update({"verified": True}).eq("id", org_id).execute()
    
    if res.data:
        target_email = res.data[0]['email']
        target_phone = res.data[0]['phone']
        
        # 2. Send Acceptance Email
        try:
            msg = Message("Q-Code: Registration Accepted!", sender=app.config['MAIL_USERNAME'], recipients=[target_email])
            msg.body = "Your organization has been verified. You can now log in to your dashboard."
            mail.send(msg)
        except: pass

        # 3. Send Acceptance SMS
        send_sms_via_termii(target_phone, "Q-Code: Your account is now active! Log in at your primary URL.")
        
        return jsonify({"status": "verified_and_notified"})
    return jsonify({"status": "error"}), 404

# --- 6. OTHER LOGIC ---
@app.route('/api/admin/call-next/<int:visitor_id>', methods=['POST'])
def call_next(visitor_id):
    res = supabase.table("queue").select("phone").eq("id", visitor_id).single().execute()
    if res.data:
        send_sms_via_termii(res.data['phone'], "Q-CODE: It is your turn!")
        supabase.table("queue").delete().eq("id", visitor_id).execute()
        return jsonify({"status": "called"})
    return jsonify({"status": "not_found"}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)
