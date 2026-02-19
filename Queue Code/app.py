import os
import json
import random # Added for OTP generation
import africastalking
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

africastalking.initialize(os.getenv("AT_USERNAME"), os.getenv("AT_API_KEY"))
at_sms = africastalking.SMS

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
    # If session exists, user stays logged in
    if 'user_phone' not in session: return redirect(url_for('home'))
    return render_template('Userpage.html')

# --- 3. OTP VERIFICATION SYSTEM (NEW) ---

@app.route('/api/auth/request-otp', methods=['POST'])
def request_otp():
    phone = request.json.get('phone')
    otp = str(random.randint(100000, 999999))
    
    # Save OTP to Supabase (Table: otp_codes)
    supabase.table("otp_codes").upsert({"phone": phone, "code": otp}).execute()
    
    try:
        at_sms.send(f"Your Q-CODE verification code is: {otp}", [phone])
        return jsonify({"status": "sent"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/verify-otp', methods=['POST'])
def verify_otp():
    phone = request.json.get('phone')
    user_code = request.json.get('code')
    
    res = supabase.table("otp_codes").select("code").eq("phone", phone).single().execute()
    
    if res.data and res.data['code'] == user_code:
        session['user_phone'] = phone # Start persistent session
        
        # Check if user already has an active queue record
        user_data = supabase.table("queue").select("*").eq("phone", phone).execute()
        is_existing = len(user_data.data) > 0
        
        return jsonify({
            "status": "success", 
            "is_returning": is_existing,
            "data": user_data.data[0] if is_existing else None
        })
    
    return jsonify({"status": "invalid_code"}), 401

# --- 4. OFFLINE JOINING WEBHOOK (NEW) ---

@app.route('/api/sms/incoming', methods=['POST'])
def sms_webhook():
    phone = request.values.get('from')
    text = request.values.get('text', '').upper().strip()
    
    # Expecting: JOIN [SERVICE_CODE] [NAME]
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
            
            at_sms.send(f"Success {name}! You are in the queue for {service_code}. Login to Q-Code web to see your dashboard.", [phone])
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
        return jsonify({"reply": "Error"}), 500

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
        at_sms.send("Q-CODE: It is your turn!", [res.data['phone']])
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
