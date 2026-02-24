import os
from flask import Flask, request, jsonify, render_template, redirect
from supabase import create_client, Client

app = Flask(__name__)

# --- SUPABASE CONFIG ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- FRONTEND ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/status')
def status_page():
    return render_template('status.html')

@app.route('/dashboard')
def admin_dashboard():
    return render_template('Admin page.html')

@app.route('/login')
def login_page():
    return render_template('login page.html')

@app.route('/admin-login') # Created specific route for Admin
def admin_login_page():
    return render_template('admin-login.html')

@app.route('/userpage')
def userpage():
    return render_template('Userpage.html')

@app.route('/register')
def register_page():
    return render_template('org reg page.html')

@app.route('/masteradmin')
def register_page():
    return render_template('super_admin.html')
# --- 3. THE OFFLINE WEBHOOK (SMS Receiver) ---
# This is what handles users joining via text message
@app.route('/webhook/sms', methods=['POST'])
def sms_webhook():
    try:
        # Most SMS providers send data as Form Data, not JSON
        incoming_msg = request.values.get('Body', '').strip().upper()  # The Service Code (e.g., UCH01)
        sender_number = request.values.get('From', 'Unknown')          # User's Phone Number

        # 1. Find the service in Supabase
        service_query = supabase.table('services').select('*').eq('service_code', incoming_msg).execute()
        
        if not service_query.data:
            response_msg = "Error: Invalid Service Code. Please check and try again."
        else:
            service = service_query.data[0]
            
            # 2. Add them to the queue
            new_entry = {
                "service_id": service['id'],
                "visitor_name": f"SMS User ({sender_number[-4:]})", # Uses last 4 digits of phone
                "status": "waiting",
                "metadata": {"phone": sender_number} # Store phone for notifications
            }
            ticket = supabase.table('queue').insert(new_entry).execute()
            
            # 3. Calculate position
            ahead = supabase.table('queue').select('id', count='exact')\
                .eq('service_id', service['id'])\
                .eq('status', 'waiting')\
                .lt('created_at', ticket.data[0]['created_at']).execute()
            
            pos = ahead.count + 1
            response_msg = f"Success! You are joined to {service['service_name']}. Your position is #{pos}. We will text you when it is your turn."

        # Return the response in a format the SMS provider understands (TwiML for Twilio)
        # If you use a different provider, this format might change to a simple string
        return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Message>{response_msg}</Message></Response>"

    except Exception as e:
        print(f"SMS Webhook Error: {e}")
        return "Error", 500

# --- 4. AUTH & OTHER APIS ---
@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.json
    if data.get('email') == ADMIN_EMAIL and data.get('password') == ADMIN_PASSWORD:
        return jsonify({"status": "success", "redirect": "/masteradmin"})
    
    try:
        res = supabase.auth.sign_in_with_password({"email": data.get('email'), "password": data.get('password')})
        return jsonify({"status": "success", "redirect": "/dashboard"})
    except:
        return jsonify({"status": "error", "message": "Login Failed"}), 401

# --- 5. STARTUP ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
