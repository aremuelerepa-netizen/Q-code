"""
Q-Code Backend - Single File Flask App
Queue management system with SMS, WhatsApp, AI integration
"""
import os
import jwt
import bcrypt
import requests
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler

# Load environment variables
load_dotenv()

# Flask setup
app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///qcode.db')
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET', 'super-secret-key')
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
    avg_service_time = db.Column(db.Integer, default=15)
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
    estimated_wait_time = db.Column(db.Integer)

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_phone = db.Column(db.String(20))
    message = db.Column(db.String(500))
    channel = db.Column(db.String(20))  # sms, whatsapp, modal
    status = db.Column(db.String(20), default='pending')  # pending, sent, failed
    sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ==================== AUTH HELPERS ====================

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, hash):
    return bcrypt.checkpw(password.encode('utf-8'), hash.encode('utf-8'))

def create_jwt(data, expires_in=24):
    payload = {**data, 'exp': datetime.utcnow() + timedelta(hours=expires_in), 'iat': datetime.utcnow()}
    return jwt.encode(payload, app.config['JWT_SECRET_KEY'], algorithm='HS256')

def verify_jwt(token):
    try:
        return jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
    except:
        return None

def token_required(f):
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

# ==================== SMS/WHATSAPP ====================

def send_sms(phone, message):
    try:
        provider = os.getenv('SMS_PROVIDER', 'twilio')
        if provider == 'twilio':
            from twilio.rest import Client
            client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
            client.messages.create(body=message, from_=os.getenv('TWILIO_PHONE'), to=phone)
        elif provider == 'africas_talking':
            headers = {'Accept':'application/json', 'Content-Type':'application/x-www-form-urlencoded'}
            payload = {'username': os.getenv('AT_USERNAME'),'apiKey': os.getenv('AT_API_KEY'),
                       'recipients': phone,'message': message}
            requests.post('https://api.sandbox.africastalking.com/version1/messaging', data=payload, headers=headers)
        return True
    except Exception as e:
        print(f"SMS Error: {e}")
        return False

def send_whatsapp(phone, message):
    try:
        headers = {'Authorization': f"Bearer {os.getenv('WHATSAPP_TOKEN')}", 'Content-Type':'application/json'}
        payload = {'messaging_product':'whatsapp','recipient_type':'individual','to':phone,'type':'text','text':{'body':message}}
        requests.post(f"https://graph.instagram.com/{os.getenv('WHATSAPP_PHONE_ID')}/messages", json=payload, headers=headers)
        return True
    except Exception as e:
        print(f"WhatsApp Error: {e}")
        return False

def generate_otp():
    import random
    return ''.join([str(random.randint(0,9)) for _ in range(6)])

# ==================== AI ====================

def predict_wait_time(service_id, position):
    try:
        service = Service.query.get(service_id)
        return service.avg_service_time * position
    except:
        return 15 * position

def analyze_no_show_risk(phone):
    try:
        history = QueueEntry.query.filter_by(user_phone=phone).all()
        total = len(history)
        if total==0: return 0
        no_show = len([h for h in history if h.status=='no-show'])
        return min((no_show/total)*100, 100)
    except:
        return 0

# ==================== ROUTES ====================

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    phone = data.get('phone')
    if User.query.filter_by(phone=phone).first(): return jsonify({'error':'User exists'}),400
    otp = generate_otp()
    user = User(phone=phone, verification_code=otp, verification_expires=datetime.utcnow()+timedelta(minutes=10))
    db.session.add(user); db.session.commit()
    send_sms(phone,f"Your Q-Code OTP: {otp}")
    return jsonify({'message':'OTP sent','phone':phone})

@app.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    data=request.json; phone=data.get('phone'); code=data.get('code')
    user=User.query.filter_by(phone=phone).first()
    if not user or user.verification_code!=code: return jsonify({'error':'Invalid OTP'}),400
    if user.verification_expires<datetime.utcnow(): return jsonify({'error':'OTP expired'}),400
    user.is_verified=True; db.session.commit()
    token=create_jwt({'phone':phone})
    return jsonify({'token':token,'user':{'phone':phone}})

@app.route('/api/join', methods=['POST'])
def join_queue():
    data=request.json; phone=data.get('phone'); code=data.get('code')
    service=Service.query.filter_by(code=code).first()
    if not service or not service.is_active: return jsonify({'error':'Service not found'}),404
    # Transactional join
    with db.session.begin_nested():
        position=db.session.query(QueueEntry).filter_by(service_id=service.id,status='waiting').count()+1
        wait_time=predict_wait_time(service.id,position)
        entry=QueueEntry(service_id=service.id,user_phone=phone,position=position,estimated_wait_time=wait_time)
        db.session.add(entry)
    db.session.commit()
    send_sms(phone,f"Joined {service.name}. Position #{position}. Est wait {wait_time}min")
    return jsonify({'message':'Joined queue','position':position,'wait_time':wait_time,'entry_id':entry.id})

@app.route('/api/my-queues', methods=['GET'])
def my_queues():
    phone=request.args.get('phone')
    entries=QueueEntry.query.filter_by(user_phone=phone,status='waiting').all()
    queues=[]
    for e in entries:
        service=Service.query.get(e.service_id)
        queues.append({'id':e.id,'service_name':service.name,'position':e.position,'wait_time':e.estimated_wait_time,'status':e.status})
    return jsonify({'queues':queues})

@app.route('/api/position/<int:entry_id>', methods=['GET'])
def get_position(entry_id):
    e=QueueEntry.query.get(entry_id)
    if not e: return jsonify({'error':'Entry not found'}),404
    s=Service.query.get(e.service_id)
    return jsonify({'position':e.position,'status':e.status,'wait_time':e.estimated_wait_time,'service':s.name})

@app.route('/api/leave/<int:entry_id>', methods=['POST'])
def leave_queue(entry_id):
    e=QueueEntry.query.get(entry_id)
    if not e: return jsonify({'error':'Entry not found'}),404
    e.status='cancelled'; db.session.commit()
    return jsonify({'message':'Left queue'})

@app.route('/api/services', methods=['GET'])
def get_services():
    services=Service.query.filter_by(is_active=True).all()
    return jsonify({'services':[{'id':s.id,'name':s.name,'code':s.code,'avg_time':s.avg_service_time} for s in services]})

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    phone=request.args.get('phone')
    notifications=Notification.query.filter_by(user_phone=phone).order_by(Notification.created_at.desc()).limit(20).all()
    return jsonify({'notifications':[{'id':n.id,'message':n.message,'channel':n.channel,'status':n.status,'sent_at':n.sent_at} for n in notifications]})

# ==================== BACKGROUND JOBS ====================

def check_queue_status():
    with app.app_context():
        entries=QueueEntry.query.filter_by(status='serving').all()
        for e in entries:
            if (datetime.utcnow()-e.joined_at).total_seconds()>900:
                e.status='no-show'; db.session.commit()

def start_background_jobs():
    scheduler=BackgroundScheduler()
    scheduler.add_job(check_queue_status,'interval',minutes=2)
    scheduler.start()
    print("Background jobs started")

@app.before_first_request
def initialize():
    db.create_all()
    start_background_jobs()

if __name__=='__main__':
    app.run(debug=True,host='0.0.0.0',port=5000)
