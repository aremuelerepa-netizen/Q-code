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

# --- SMS GATEWAY WEBHOOK ---
@app.route('/api/sms/webhook', methods=['POST'])
def sms_webhook():
    """
    HANDLES OFFLINE USERS:
    The user texts a Service Code (e.g., 'TECH101') to your number.
    """
    try:
        # 1. Get data from the SMS Gateway (Standard form-data)
        sender_phone = request.form.get('From')  # The user's phone number
        message_body = request.form.get('Body', '').strip().upper() # The Service Code

        if not message_body:
            return "Empty message", 400

        # 2. Find the service associated with the texted code
        service_query = supabase.table('services').select('*').eq('service_code', message_body).single().execute()
        
        if not service_query.data:
            # If code is invalid, you can return a 'fail' message for the gateway to text back
            return f"<Response><Message>Error: Service code '{message_body}' not found.</Message></Response>", 200

        service = service_query.data
        
        # 3. Add the offline user to the queue
        new_ticket = {
            "service_id": service['id'],
            "visitor_name": f"Mobile-{sender_phone[-4:]}", # Shows as 'Mobile-1234' on your admin dash
            "phone_number": sender_phone,
            "status": "waiting",
            "is_offline": True # Flag to identify they don't have the web dashboard
        }
        
        ticket_result = supabase.table('queue').insert(new_ticket).execute()
        ticket = ticket_result.data[0]

        # 4. Calculate their current position
        ahead = supabase.table('queue').select('id', count='exact')\
            .eq('service_id', service['id'])\
            .eq('status', 'waiting')\
            .lt('created_at', ticket['created_at']).execute()
        
        position = (ahead.count + 1)

        # 5. Response to Gateway (This texts the user back immediately)
        return f"""
        <Response>
            <Message>
                Confirmed! You are #{position} in line for {service['service_name']}. 
                We will text you when it is your turn.
            </Message>
        </Response>
        """, 200

    except Exception as e:
        print(f"SMS Error: {str(e)}")
        return "Internal Server Error", 500

# --- API: AUTH & LOGIC FIXES ---

@app.route('/api/auth/login', methods=['POST'])
def unified_login():
    """
    FIXED: Handles Admin vs User logic
    """
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        login_type = data.get('role') # 'admin', 'super_admin', or 'user'

        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        
        # Check if user exists in your custom 'profiles' or 'orgs' table to verify role
        user_id = res.user.id
        profile = supabase.table('profiles').select('role').eq('id', user_id).single().execute()
        
        actual_role = profile.data.get('role') if profile.data else 'user'

        # Security check: Don't let users login to admin panel
        if login_type == 'admin' and actual_role != 'admin':
            return jsonify({"status": "error", "message": "Access Denied: Not an Admin"}), 403
        
        # Generate name from email
        display_name = email.split('@')[0].capitalize()

        # Route redirect based on actual role
        redirect_to = "/userpage"
        if actual_role == 'admin': redirect_to = "/dashboard"
        if actual_role == 'super_admin': redirect_to = "/super-admin-dashboard"

        return jsonify({
            "status": "success", 
            "redirect": redirect_to,
            "session": res.session.access_token,
            "user_name": display_name
        })
    except Exception as e:
        return jsonify({"status": "error", "message": "Invalid Credentials"}), 401

@app.route('/api/auth/user-register', methods=['POST'])
def user_register():
    """
    FIXED: Responds with correct success so frontend can redirect
    """
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        
        res = supabase.auth.sign_up({"email": email, "password": password})
        
        if res.user:
            # OPTIONAL: Add user to a 'profiles' table with 'user' role here
            return jsonify({"status": "success", "message": "Redirecting to verification..."})
        
        return jsonify({"status": "error", "message": "Registration failed"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- QUEUE OPERATIONS (RETAINED & CLEANED) ---

@app.route('/api/auth/join-frictionless', methods=['POST'])
def join_frictionless():
    try:
        data = request.json
        code = data.get('service_code', '').strip().upper()
        name = data.get('name', 'Guest')

        service_query = supabase.table('services').select('*').eq('service_code', code).execute()
        if not service_query.data:
            return jsonify({"status": "error", "message": "Invalid Service Code"}), 404

        service = service_query.data[0]
        new_ticket = {
            "service_id": service['id'],
            "org_id": service.get('org_id'),
            "visitor_name": name,
            "status": "waiting"
        }
        ticket_result = supabase.table('queue').insert(new_ticket).execute()
        ticket = ticket_result.data[0]

        return jsonify({
            "status": "success", 
            "ticket_id": ticket['id'],
            "organization_name": service.get('service_name', 'Organization')
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
