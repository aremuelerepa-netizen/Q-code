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
db: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Mail Config
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=465,
    MAIL_USERNAME=os.getenv("GMAIL_USER"),
    MAIL_PASSWORD=os.getenv("GMAIL_APP_PASSWORD"),
    MAIL_USE_SSL=True,
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

@app.route('/super-admin')
def super_admin_view():
    if not session.get('is_super_admin'): return redirect(url_for('login_view'))
    res = db.table("organizations").select("*").eq("verified", False).execute()
    return render_template('super_admin.html', pending_orgs=res.data)

# --- 4. USER AUTH (EMAIL OTP & LOGIN CODE) ---

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
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/verify-email-otp', methods=['POST'])
def verify_email_otp():
    user_otp = request.json.get('otp')
    phone = request.json.get('phone')
    
    if user_otp == session.get('temp_otp'):
        email = session.get('temp_email')
        login_code = generate_unique_code()
        
        # Save user and their unique login code to the DB
        # This links the email and phone to this persistent code
        db.table("queue").upsert({
            "email": email,
            "phone": phone,
            "login_code": login_code,
            "visitor_name": email.split('@')[0]
        }, on_conflict="phone").execute()
        
        session['user_phone'] = phone
        return jsonify({
            "status": "success", 
            "login_code": login_code,
            "message": "Verify once, use your Login Code next time!"
        })
    return jsonify({"status": "invalid"}), 401

@app.route('/api/auth/login-with-code', methods=['POST'])
def login_with_code():
    code = request.json.get('login_code').strip().upper()
    res = db.table("queue").select("*").eq("login_code", code).execute()
    
    if res.data:
        user = res.data[0]
        session['user_phone'] = user['phone']
        return jsonify({"status": "success", "user": user})
    return jsonify({"status": "error", "message": "Invalid Login Code"}), 401

# --- 5. SIM-BASED SMS GATEWAY WEBHOOK ---
@app.route('/api/sms/incoming', methods=['POST'])
def sim_webhook():
    # This endpoint is hit by your Android SMS Gateway App
    data = request.json 
    sender_phone = data.get('from') # The phone number texting your SIM
    service_code = data.get('message', '').strip().upper() # e.g. "ZENITH01"

    # Check if the service code exists (using Org ID or a Service ID)
    res = db.table("organizations").select("name").eq("id", service_code).execute()
    
    if res.data:
        org_name = res.data[0]['name']
        db.table("queue").insert({
            "phone": sender_phone,
            "service_id": service_code,
            "entry_type": "SIM",
            "visitor_name": "Offline User"
        }).execute()
        reply = f"Q-CODE: Success! You are in the queue for {org_name}. Use your phone number to track online."
    else:
        reply = "Q-CODE: Error. Invalid Service Code. Please check the code at the desk."

    # Return reply to the Android App so it sends the SMS back via your SIM
    return jsonify({"to": sender_phone, "message": reply})

# --- 6. AI LOGIC (GROQ) ---
@app.route('/api/ai-chat', methods=['POST'])
def ai_chat():
    user_msg = request.json.get("message")
    try:
        completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": user_msg}],
            model="llama3-8b-8192",
        )
        return jsonify({"reply": completion.choices[0].message.content})
    except Exception as e:
        return jsonify({"reply": "AI is resting. Try again later."}), 500

# --- 7. SUPER ADMIN & ORG ACTIONS ---
@app.route('/api/admin/approve-org/<org_id>', methods=['POST'])
def approve_org(org_id):
    if not session.get('is_super_admin'): return jsonify({"status": "unauthorized"}), 403
    db.table("organizations").update({"verified": True}).eq("id", org_id).execute()
    return jsonify({"status": "success"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
