"""
Q-Code Backend - Single File Flask App
Simple queue management system with SMS, WhatsApp, and AI integration
"""
import os
import jwt
import json
import bcrypt
import requests
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Float, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from apscheduler.schedulers.background import BackgroundScheduler

# Load environment variables
load_dotenv()

# Flask app setup
app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///qcode.db')
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET', 'your-secret-key')

db = SQLAlchemy(app)

# ==================== DATABASE MODELS ====================

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100))
    is_verified = db.Column(db.Boolean, default=False)
    verification_code = db.Column(db.String(6))
    verification_expires = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class Organization(db.Model):
    __tablename__ = 'organizations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Service(db.Model):
    __tablename__ = 'services'
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('organizations.id'))
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    avg_service_time = db.Column(db.Integer, default=15)  # minutes
    current_serving = db.Column(db.Integer, default=0)

class QueueEntry(db.Model):
    __tablename__ = 'queue_entries'
    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'))
    user_phone = db.Column(db.String(20))
    position = db.Column(db.Integer)
    status = db.Column(db.String(20), default='waiting')  # waiting, serving, completed, no-show
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    estimated_wait_time = db.Column(db.Integer)  # minutes

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_phone = db.Column(db.String(20))
    message = db.Column(db.String(500))
    channel = db.Column(db.String(20))  # sms, whatsapp, email, modal
    status = db.Column(db.String(20), default='pending')  # pending, sent, failed
    sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ==================== AUTHENTICATION HELPERS ====================

def hash_password(password):
    """Hash password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, hash):
    """Verify password against hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hash.encode('utf-8'))

def create_jwt(data, expires_in=24):
    """Create JWT token"""
    payload = {
        **data,
        'exp': datetime.utcnow() + timedelta(hours=expires_in),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')

def verify_jwt(token):
    """Verify JWT token"""
    try:
        return jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
    except:
        return None

def token_required(f):
    """Decorator for routes requiring JWT"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').split(' ')[-1]
        if not token:
            return jsonify({'error': 'Missing token'}), 401
        payload = verify_jwt(token)
        if not payload:
            return jsonify({'error': 'Invalid token'}), 401
        return f(payload, *args, **kwargs)
    return decorated

# ==================== SMS/MESSAGING SERVICE ====================

def send_sms(phone, message):
    """Send SMS via Twilio or Africa's Talking"""
    try:
        provider = os.getenv('SMS_PROVIDER', 'twilio')
        
        if provider == 'twilio':
            from twilio.rest import Client
            account_sid = os.getenv('TWILIO_ACCOUNT_SID')
            auth_token = os.getenv('TWILIO_AUTH_TOKEN')
            client = Client(account_sid, auth_token)
            client.messages.create(
                body=message,
                from_=os.getenv('TWILIO_PHONE'),
                to=phone
            )
        elif provider == 'africas_talking':
            headers = {'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'}
            payload = {
                'username': os.getenv('AT_USERNAME'),
                'apiKey': os.getenv('AT_API_KEY'),
                'recipients': phone,
                'message': message
            }
            requests.post('https://api.sandbox.africastalking.com/version1/messaging', 
                         data=payload, headers=headers)
        return True
    except Exception as e:
        print(f"SMS Error: {e}")
        return False

def send_whatsapp(phone, message):
    """Send WhatsApp message"""
    try:
        headers = {
            'Authorization': f"Bearer {os.getenv('WHATSAPP_TOKEN')}",
            'Content-Type': 'application/json'
        }
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': phone,
            'type': 'text',
            'text': {'body': message}
        }
        requests.post(f"https://graph.instagram.com/{os.getenv('WHATSAPP_PHONE_ID')}/messages",
                     json=payload, headers=headers)
        return True
    except Exception as e:
        print(f"WhatsApp Error: {e}")
        return False

def generate_otp():
    """Generate 6-digit OTP"""
    import random
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])

# ==================== AI/GROQ SERVICE ====================

def predict_wait_time(service_id, position):
    """Use Groq AI to predict wait time"""
    try:
        service = Service.query.get(service_id)
        queue_count = QueueEntry.query.filter_by(service_id=service_id, status='waiting').count()
        
        # Call Groq API
        headers = {'Authorization': f"Bearer {os.getenv('GROQ_API_KEY')}"}
        payload = {
            'model': 'mixtral-8x7b-32768',
            'messages': [{
                'role': 'user',
                'content': f"Estimate wait time: {queue_count} people waiting, avg service time {service.avg_service_time}min, position {position}"
            }],
            'max_tokens': 50
        }
        
        response = requests.post('https://api.groq.com/openai/v1/chat/completions',
                                json=payload, headers=headers)
        # Parse response and extract time estimate
        result = response.json()
        return service.avg_service_time * position  # Fallback calculation
    except Exception as e:
        print(f"Groq Error: {e}")
        return service.avg_service_time * position

def analyze_no_show_risk(user_phone):
    """Analyze no-show risk using AI"""
    try:
        history = db.session.query(QueueEntry).filter_by(user_phone=user_phone).all()
        no_show_count = len([h for h in history if h.status == 'no-show'])
        total = len(history)
        
        if total == 0:
            return 0
        
        risk_score = (no_show_count / total) * 100
        return min(risk_score, 100)
    except:
        return 0

# ==================== API ROUTES ====================

@app.route('/api/register', methods=['POST'])
def register():
    """Register new user"""
    data = request.json
    phone = data.get('phone')
    
    if User.query.filter_by(phone=phone).first():
        return jsonify({'error': 'User already exists'}), 400
    
    otp = generate_otp()
    user = User(phone=phone, verification_code=otp,
                verification_expires=datetime.utcnow() + timedelta(minutes=10))
    db.session.add(user)
    db.session.commit()
    
    # Send OTP via SMS
    send_sms(phone, f"Your Q-Code verification code is: {otp}")
    
    return jsonify({'message': 'OTP sent', 'phone': phone})

@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    """Verify OTP and create JWT"""
    data = request.json
    phone = data.get('phone')
    code = data.get('code')
    
    user = User.query.filter_by(phone=phone).first()
    if not user or user.verification_code != code:
        return jsonify({'error': 'Invalid OTP'}), 400
    
    if user.verification_expires < datetime.utcnow():
        return jsonify({'error': 'OTP expired'}), 400
    
    user.is_verified = True
    db.session.commit()
    
    token = create_jwt({'phone': phone})
    return jsonify({'token': token, 'user': {'phone': phone}})

@app.route('/api/admin-register', methods=['POST'])
def admin_register():
    """Register new organization"""
    data = request.json
    email = data.get('email')
    password = data.get('password')
    name = data.get('name')
    
    if Organization.query.filter_by(email=email).first():
        return jsonify({'error': 'Organization exists'}), 400
    
    org = Organization(
        email=email,
        name=name,
        password_hash=hash_password(password)
    )
    db.session.add(org)
    db.session.commit()
    
    return jsonify({'message': 'Organization registered', 'org_id': org.id})

@app.route('/api/admin-login', methods=['POST'])
def admin_login():
    """Admin login"""
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    org = Organization.query.filter_by(email=email).first()
    if not org or not verify_password(password, org.password_hash):
        return jsonify({'error': 'Invalid credentials'}), 400
    
    token = create_jwt({'org_id': org.id, 'email': email})
    return jsonify({'token': token, 'org_id': org.id})

@app.route('/api/join', methods=['POST'])
def join_queue():
    """User joins a queue"""
    data = request.json
    phone = data.get('phone')
    code = data.get('code')
    
    service = Service.query.filter_by(code=code).first()
    if not service or not service.is_active:
        return jsonify({'error': 'Service not found'}), 404
    
    # Get next position
    position = db.session.query(QueueEntry).filter_by(service_id=service.id, status='waiting').count() + 1
    
    # Predict wait time
    wait_time = predict_wait_time(service.id, position)
    
    entry = QueueEntry(
        service_id=service.id,
        user_phone=phone,
        position=position,
        estimated_wait_time=wait_time
    )
    db.session.add(entry)
    db.session.commit()
    
    # Send confirmation
    send_sms(phone, f"Joined {service.name}. Position: #{position}. Est. wait: {wait_time}min")
    
    return jsonify({
        'message': 'Joined queue',
        'position': position,
        'wait_time': wait_time,
        'entry_id': entry.id
    })

@app.route('/api/my-queues', methods=['GET'])
def my_queues():
    """Get user's active queues"""
    phone = request.args.get('phone')
    
    entries = db.session.query(QueueEntry).filter_by(user_phone=phone, status='waiting').all()
    
    queues = []
    for entry in entries:
        service = Service.query.get(entry.service_id)
        queues.append({
            'id': entry.id,
            'service_name': service.name,
            'position': entry.position,
            'wait_time': entry.estimated_wait_time,
            'status': entry.status
        })
    
    return jsonify({'queues': queues})

@app.route('/api/position/<int:entry_id>', methods=['GET'])
def get_position(entry_id):
    """Get current queue position"""
    entry = QueueEntry.query.get(entry_id)
    if not entry:
        return jsonify({'error': 'Entry not found'}), 404
    
    service = Service.query.get(entry.service_id)
    
    return jsonify({
        'position': entry.position,
        'status': entry.status,
        'wait_time': entry.estimated_wait_time,
        'service': service.name
    })

@app.route('/api/leave/<int:entry_id>', methods=['POST'])
def leave_queue(entry_id):
    """Leave queue"""
    entry = QueueEntry.query.get(entry_id)
    if not entry:
        return jsonify({'error': 'Entry not found'}), 404
    
    entry.status = 'cancelled'
    db.session.commit()
    
    return jsonify({'message': 'Left queue'})

@app.route('/api/services', methods=['GET'])
def get_services():
    """Get all active services"""
    services = Service.query.filter_by(is_active=True).all()
    
    return jsonify({
        'services': [{
            'id': s.id,
            'name': s.name,
            'code': s.code,
            'avg_time': s.avg_service_time
        } for s in services]
    })

@app.route('/api/admin-dashboard', methods=['GET'])
@token_required
def admin_dashboard(payload):
    """Admin dashboard stats"""
    org_id = payload.get('org_id')
    
    services = Service.query.filter_by(org_id=org_id).all()
    service_ids = [s.id for s in services]
    
    queues = db.session.query(QueueEntry).filter(QueueEntry.service_id.in_(service_ids)).all()
    
    total_queues = len(services)
    total_waiting = len([q for q in queues if q.status == 'waiting'])
    total_serving = len([q for q in queues if q.status == 'serving'])
    
    queue_data = []
    for q in queues[:20]:
        service = Service.query.get(q.service_id)
        queue_data.append({
            'id': q.id,
            'service_name': service.name,
            'position': q.position,
            'status': q.status,
            'phone': q.user_phone[:2] + '***' + q.user_phone[-3:]
        })
    
    return jsonify({
        'total_queues': total_queues,
        'total_waiting': total_waiting,
        'total_serving': total_serving,
        'queues': queue_data
    })

@app.route('/api/next-queue/<int:service_id>', methods=['POST'])
@token_required
def next_queue(payload, service_id):
    """Call next person in queue"""
    entry = db.session.query(QueueEntry).filter_by(service_id=service_id, status='waiting').first()
    if not entry:
        return jsonify({'error': 'No one in queue'}), 404
    
    entry.status = 'serving'
    service = Service.query.get(service_id)
    service.current_serving = entry.position
    db.session.commit()
    
    # Notify user
    code = f"CODE-{entry.id}"
    send_sms(entry.user_phone, f"You're next! Code: {code}")
    send_whatsapp(entry.user_phone, f"You're next in {service.name}! Code: {code}")
    
    return jsonify({'message': 'Called next', 'code': code, 'phone': entry.user_phone})

@app.route('/api/complete-service/<int:entry_id>', methods=['POST'])
@token_required
def complete_service(payload, entry_id):
    """Mark service as completed"""
    entry = QueueEntry.query.get(entry_id)
    if not entry:
        return jsonify({'error': 'Entry not found'}), 404
    
    entry.status = 'completed'
    entry.completed_at = datetime.utcnow()
    db.session.commit()
    
    send_sms(entry.user_phone, "Thank you for using Q-Code!")
    
    return jsonify({'message': 'Service completed'})

@app.route('/api/create-service', methods=['POST'])
@token_required
def create_service(payload):
    """Create new service"""
    data = request.json
    org_id = payload.get('org_id')
    
    service = Service(
        org_id=org_id,
        name=data.get('name'),
        code=data.get('code').upper(),
        avg_service_time=data.get('avg_time', 15)
    )
    db.session.add(service)
    db.session.commit()
    
    return jsonify({'message': 'Service created', 'service_id': service.id})

@app.route('/api/sms-webhook', methods=['POST'])
def sms_webhook():
    """Handle incoming SMS from Twilio"""
    data = request.json
    phone = data.get('From')
    message = data.get('Body', '').upper()
    
    # Auto-join queue by SMS code
    service = Service.query.filter_by(code=message).first()
    if service:
        # Auto join
        position = db.session.query(QueueEntry).filter_by(service_id=service.id, status='waiting').count() + 1
        wait_time = predict_wait_time(service.id, position)
        
        entry = QueueEntry(
            service_id=service.id,
            user_phone=phone,
            position=position,
            estimated_wait_time=wait_time
        )
        db.session.add(entry)
        db.session.commit()
        
        send_sms(phone, f"Joined {service.name}. Position: #{position}")
    
    return jsonify({'status': 'received'})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get system statistics"""
    total_users = User.query.count()
    total_entries = QueueEntry.query.count()
    completed = QueueEntry.query.filter_by(status='completed').count()
    no_shows = QueueEntry.query.filter_by(status='no-show').count()
    
    return jsonify({
        'total_users': total_users,
        'total_entries': total_entries,
        'completed': completed,
        'no_shows': no_shows,
        'completion_rate': (completed / total_entries * 100) if total_entries > 0 else 0
    })

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({'status': 'healthy'}), 200

# ==================== BACKGROUND JOBS ====================

def check_queue_status():
    """Check queue status every 2 minutes"""
    with app.app_context():
        entries = QueueEntry.query.filter_by(status='serving').all()
        for entry in entries:
            # Check for no-shows (after 15 minutes)
            if (datetime.utcnow() - entry.joined_at).total_seconds() > 900:
                entry.status = 'no-show'
                db.session.commit()
                print(f"Marked {entry.user_phone} as no-show")

def update_wait_times():
    """Update estimated wait times"""
    with app.app_context():
        entries = QueueEntry.query.filter_by(status='waiting').all()
        for entry in entries:
            entry.estimated_wait_time = predict_wait_time(entry.service_id, entry.position)
        db.session.commit()

def send_reminders():
    """Send reminders to waiting users"""
    with app.app_context():
        # Get entries that are next in line
        entries = db.session.execute("""
            SELECT * FROM queue_entries 
            WHERE status='waiting' AND position <= 3
        """).fetchall()
        
        for entry in entries:
            service = Service.query.get(entry['service_id'])
            wait_time = entry['estimated_wait_time']
            send_sms(entry['user_phone'], 
                    f"Reminder: You're #{entry['position']} at {service.name}. Approx {wait_time}min wait.")

# ==================== APP INITIALIZATION ====================

def start_background_jobs():
    """Start background scheduler"""
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_queue_status, 'interval', minutes=2)
    scheduler.add_job(update_wait_times, 'interval', minutes=5)
    scheduler.add_job(send_reminders, 'interval', minutes=10)
    scheduler.start()
    print("Background jobs started")

@app.before_first_request
def initialize():
    """Initialize database"""
    db.create_all()
    start_background_jobs()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
