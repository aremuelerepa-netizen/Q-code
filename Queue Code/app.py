import os
import json
import random
import requests  # Required for Termii
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

# Termii Configuration
TERMII_API_KEY = os.getenv("TERMII_API_KEY")
TERMII_SENDER_ID = os.getenv("TERMII_SENDER_ID", "N-Alert") # Default to N-Alert

# Helper function to send SMS via Termii
def send_sms_via_termii(phone, message):
    url = "https://api.ng.termii.com/api/sms/send"
    payload = {
        "api_key": TERMII_API_KEY,
        "to": phone,
        "from": TERMII_SENDER_ID,
        "sms": message,
        "type": "plain",
        "channel": "dnd"  # Use 'dnd' to bypass Nigerian DND restrictions
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

# --- 3. OTP VERIFICATION SYSTEM ---

@app.route('/api/auth/request-otp', methods=['POST'])
def request_otp():
    phone = request.json.get('phone')
    otp = str(random.randint(100000, 999999))
    
    # Save to Supabase
    supabase.table("otp_codes").upsert({"phone": phone, "code": otp}).execute()
    
    # Send via Termii
    msg = f"Your Q-CODE verification code is: {otp}"
    result = send_sms_via_termii(phone, msg)
    
    if result and result.get("message_id"):
        return jsonify({"status": "sent"})
    return jsonify({"status": "error", "message": "Failed to send SMS"}), 500

@app.route('/api/auth/verify-otp', methods=['POST'])
def verify_otp():
    phone = request.json.get('phone')
    user_code = request.json.get('code')
    
    res = supabase.table("otp_codes").select("code").eq("phone", phone).single().execute()
    
    if res.data and res.data['code'] == user_code:
        session['user_phone'] = phone
        user_data = supabase.table("queue").select("*").eq("phone", phone).execute()
        is_existing = len(user_data.data) > 0
        return jsonify({
            "status": "success", 
            "is_returning": is_existing,
            "data": user_data.data[0] if is_existing else None
        })
    return jsonify({"status": "invalid_code"}), 401

# --- 4. OFFLINE JOINING WEBHOOK (Adjusted for Termii) ---

@app.route('/api/sms/incoming', methods=['POST'])
def sms_webhook():
    data = request.json
    phone = data.get('sender')  # Termii uses 'sender'
    text = data.get('message', '').upper().strip() # Termii uses 'message'
    
    if text.startswith("JOIN"):
        parts = text.split(" ")
        if len(parts) >= 3:
            service_code = parts[1]
            name = " ".join(parts[2:])
            
            supabase.table("queue").insert({
                "visitor_name": name,
                "phone": phone,
                "service_id": service_code,
                "entry_type": "SMS"
            }).execute()
            
            reply = f"Success {name}! You're in the queue for {service_code}. Visit the web app to track your spot."
            send_sms_via_termii(phone, reply)
            
    return "OK", 200

# --- 5. AI LOGIC ---
@app.route('/api/ai-chat', methods=['POST'])
def ai_chat():
    user_msg = request.json.get("message")
    system_prompt = {"role": "system", "content": "You are the Q-Code AI Assistant..."}
    try:
        response = groq_client.chat.completions.create(
            messages=[system_prompt, {"role": "user", "content": user_msg}],
            model="llama3-8b-8192"
        )
        return jsonify({"reply": response.choices[0].message.content})
    except:
        return jsonify({"reply": "Error connecting to AI"}), 500

# --- 6. ADMIN & REGISTRATION ---
@app.route('/api/auth/register', methods=['POST'])
def register_org():
    org_name = request.form.get('orgName')
    email = request.form.get('email')
    uploaded_file = request.files.get('verificationDoc')
    supabase.table("organizations").insert({"name": org_name, "email": email, "verified": False}).execute()
    try:
        msg = Message(f"Verify: {org_name}", sender=app.config['MAIL_USERNAME'], recipients=[app.config['MAIL_USERNAME']])
        if uploaded_file: msg.attach(uploaded_file.filename, uploaded_file.content_type, uploaded_file.read())
        mail.send(msg)
        return jsonify({"status": "success"})
    except: return jsonify({"status": "error"}), 500

@app.route('/api/admin/call-next/<int:visitor_id>', methods=['POST'])
def call_next(visitor_id):
    res = supabase.table("queue").select("phone").eq("id", visitor_id).single().execute()
    if res.data:
        msg = "Q-CODE: It is your turn! Please proceed to the service desk."
        send_sms_via_termii(res.data['phone'], msg)
        supabase.table("queue").delete().eq("id", visitor_id).execute()
        return jsonify({"status": "called"})
    return jsonify({"status": "not_found"}), 404

@app.route('/api/auth/login', methods=['POST'])
def login_logic():
    data = request.json
    try:
        res = supabase.auth.sign_in_with_password({"email": data['email'], "password": data['password']})
        session['org_id'] = res.user.id
        return jsonify({"status": "success"})
    except: return jsonify({"status": "error"}), 401

if __name__ == '__main__':
    app.run(debug=True, port=5000)
