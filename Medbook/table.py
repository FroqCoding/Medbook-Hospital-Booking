from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token
from flask_cors import CORS
from datetime import datetime, date
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

app = Flask(__name__)
CORS(app)
# ----------------------
# Configuration (updated for Render env vars & production enforcement)
# ----------------------
# We want to ensure that on Render (RENDER env var present) we NEVER silently
# fall back to a local sqlite database because that causes data loss & confusion.
# In local development (RENDER not set) we allow sqlite fallback.

possible_db_vars = [
    'DATABASE_URL','DB_URL','POSTGRES_URL','POSTGRES_URI','DATABASE_URI'
]
raw_db_url = None
for _v in possible_db_vars:
    val = os.getenv(_v)
    if val:
        raw_db_url = val
        break

# Enhanced Render detection: check for any known Render-provided vars.
render_markers = [
    'RENDER','RENDER_SERVICE_ID','RENDER_SERVICE_NAME','RENDER_INSTANCE_ID','RENDER_EXTERNAL_URL'
]
on_render = any(os.getenv(k) for k in render_markers)

# Normalize older postgres:// URI to postgresql:// for SQLAlchemy compatibility.
if raw_db_url and raw_db_url.startswith('postgres://'):
    raw_db_url = raw_db_url.replace('postgres://','postgresql://',1)

# Disallow implicit fallback: require DATABASE_URL always.
if not raw_db_url:
    if on_render:
        env_keys_preview = ','.join(sorted(k for k in os.environ.keys() if k.startswith('RENDER')))
        raise RuntimeError(
            'DATABASE_URL (or DB_URL/POSTGRES_URL/POSTGRES_URI/DATABASE_URI) is not set. '
            'Add your Postgres connection string in the Render dashboard. '
            f'Render detected={on_render}. Render-related envs: {env_keys_preview or "<none>"}'
        )
    else:
        raw_db_url = 'sqlite:///local_dev.db'
        print('[startup] WARNING: No DATABASE_URL found; using local sqlite:///local_dev.db (development only)')
app.config['SQLALCHEMY_DATABASE_URI'] = raw_db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-insecure-key')
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 280
}
print(f"[startup] Using database URL: {app.config['SQLALCHEMY_DATABASE_URI']} (on_render={on_render})")

# If somehow sqlite slipped through in what looks like production, abort loudly.
if on_render and app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:'):
    raise RuntimeError('SQLite database in production environment is not allowed. Check DATABASE_URL.')

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# ----------------------
# User Model (add all profile fields here)
# ----------------------
class User(db.Model):
    __tablename__ = 'users'
    userid = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    email = db.Column(db.String, unique=True, nullable=False)
    phone = db.Column(db.String, nullable=False)
    password = db.Column(db.String, nullable=False)
    age = db.Column(db.Integer)  # legacy (not directly edited anymore)
    height = db.Column(db.Integer)
    weight = db.Column(db.Integer)
    gender = db.Column(db.String)  # new
    date_of_birth = db.Column(db.Date)  # new
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Doctor(db.Model):
    __tablename__ = 'doctors'
    doctorid = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    speciality = db.Column(db.String, nullable=False)
    hospitalid = db.Column(db.Integer, db.ForeignKey('hospitals.hospitalid'), nullable=False)
    email = db.Column(db.String, nullable=False)
    phone = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Hospital(db.Model):
    __tablename__ = 'hospitals'
    hospitalid = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    address = db.Column(db.String)
    phone = db.Column(db.String)
    email = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DoctorAvailability(db.Model):
    __tablename__ = 'doctor_availability'
    dayid = db.Column(db.Integer, primary_key=True)
    dayname = db.Column(db.String)  # e.g. Mon, Tue, Wed, Thu, Fri, Sat, Sun
    doctorid = db.Column(db.Integer, db.ForeignKey('doctors.doctorid'), nullable=False)
    starttime = db.Column(db.Time)
    endtime = db.Column(db.Time)

# ----------------------
# Appointment Model
# ----------------------
class Appointment(db.Model):
    __tablename__ = 'appointments'
    appointmentid = db.Column(db.Integer, primary_key=True)
    userid = db.Column(db.Integer, db.ForeignKey('users.userid'), nullable=False)
    doctorid = db.Column(db.Integer, db.ForeignKey('doctors.doctorid'), nullable=False)
    status = db.Column(db.Boolean, default=True, nullable=False)  # True = scheduled, False = cancelled
    appointment_date = db.Column(db.Date, nullable=False)
    appointment_time = db.Column(db.Time, nullable=False)
    reason = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- Ensure schema (add missing reason column if table pre-existed) ---
from sqlalchemy import inspect, text

# ----------------------
# Utility helpers
# ----------------------
def json_error(message: str, status: int = 400, **extra):
    payload = {'message': message}
    if extra:
        payload.update(extra)
    return jsonify(payload), status

def calc_age(dob):
    if not dob:
        return None
    today = date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return years if years >= 0 else None

def default_reason(val):
    return (val if val and str(val).strip() else 'Unstated')

def ensure_schema():
    """Idempotent best-effort schema adjustments.

    Only executes Postgres-specific DDL when connected to Postgres. Designed to
    be safe if run multiple times. Silent failures are logged to stdout.
    """
    with app.app_context():
        engine = db.engine
        insp = inspect(engine)
        backend = engine.url.get_backend_name()

        # --- appointments table adjustments ---
        if 'appointments' in insp.get_table_names():
            cols = {c['name'] for c in insp.get_columns('appointments')}
            if 'reason' not in cols:
                try:
                    engine.execute(text('ALTER TABLE appointments ADD COLUMN reason VARCHAR'))
                    print('[ensure_schema] Added reason column')
                except Exception:
                    pass
            if backend == 'postgresql':
                # Unique constraint for slot
                try:
                    res = engine.execute(text("""
                        SELECT constraint_name FROM information_schema.table_constraints
                        WHERE table_name='appointments' AND constraint_type='UNIQUE';
                    """))
                    existing_uniques = {r[0] for r in res}
                    if 'uq_doctor_slot' not in existing_uniques:
                        try:
                            engine.execute(text('ALTER TABLE appointments ADD CONSTRAINT uq_doctor_slot UNIQUE (doctorid, appointment_date, appointment_time)'))
                            print('[ensure_schema] Added uq_doctor_slot constraint')
                        except Exception:
                            pass
                except Exception as e:
                    print('[ensure_schema] unique constraint check failed:', e)
                # Identity fix
                try:
                    res = engine.execute(text("""
                        SELECT column_default FROM information_schema.columns 
                        WHERE table_name='appointments' AND column_name='appointmentid';
                    """))
                    row = res.fetchone()
                    default_val = row[0] if row else None
                    if not default_val:
                        try:
                            engine.execute(text('ALTER TABLE appointments ALTER COLUMN appointmentid ADD GENERATED BY DEFAULT AS IDENTITY'))
                            print('[ensure_schema] Added identity to appointmentid')
                        except Exception:
                            # Fallback sequence fix
                            try:
                                engine.execute(text("CREATE SEQUENCE IF NOT EXISTS appointments_appointmentid_seq"))
                                engine.execute(text("ALTER TABLE appointments ALTER COLUMN appointmentid SET DEFAULT nextval('appointments_appointmentid_seq')"))
                                engine.execute(text("SELECT setval('appointments_appointmentid_seq', COALESCE((SELECT MAX(appointmentid) FROM appointments),0))"))
                                print('[ensure_schema] Applied sequence fallback for appointmentid')
                            except Exception as inner:
                                print('[ensure_schema] Failed identity/sequence patch:', inner)
                except Exception as e:
                    print('[ensure_schema] identity check error:', e)

        # --- users table additive columns ---
        if 'users' in insp.get_table_names():
            user_cols = {c['name'] for c in insp.get_columns('users')}
            additions = []
            if 'gender' not in user_cols:
                additions.append('ALTER TABLE users ADD COLUMN gender VARCHAR')
            if 'date_of_birth' not in user_cols:
                additions.append('ALTER TABLE users ADD COLUMN date_of_birth DATE')
            if 'age' not in user_cols:
                additions.append('ALTER TABLE users ADD COLUMN age INTEGER')
            for ddl in additions:
                try:
                    engine.execute(text(ddl))
                    print('[ensure_schema] applied:', ddl)
                except Exception:
                    pass

"""Auto-create base tables if missing, then apply incremental ensure_schema adjustments.

Rationale: In some deployment scenarios (fresh Postgres database without running
seed or manual schema.sql), the reflected tables set can be empty. Previously we
ran ensure_schema() only, which assumes core tables may already exist. We now
detect the absence of any required tables and call db.create_all() once to lay
down the ORM-defined schema, then run ensure_schema() to apply additive DDL
logic (extra columns, unique constraints, identity fixes).
"""
with app.app_context():
    from sqlalchemy import inspect as _insp_mod
    _insp = _insp_mod(db.engine)
    required_tables = {"users","hospitals","doctors","doctor_availability","appointments"}
    existing = set(_insp.get_table_names())
    if not required_tables.issubset(existing):
        try:
            db.create_all()
            print('[startup] Performed db.create_all() to create missing base tables')
        except Exception as e:
            print('[startup] db.create_all() failed:', e)

ensure_schema()

# ----------------------
# Route to Register User
# ----------------------
@app.route('/users/register', methods=['POST'])
def register_user():
    data = request.get_json() or {}
    required_fields = ['name','email','phone','password','gender','date_of_birth']
    missing = [f for f in required_fields if f not in data or not str(data[f]).strip()]
    if missing:
        return json_error('Missing required fields', 400, missing=missing)
    # Check if email already exists in users
    if User.query.filter_by(email=data['email']).first():
        return json_error('Email already exists', 400)
    # Parse DOB
    dob = None
    try:
        dob = datetime.strptime(data['date_of_birth'], '%Y-%m-%d').date()
    except ValueError:
        return json_error('Invalid date_of_birth format, expected YYYY-MM-DD', 400)
    user = User(
        name=data['name'],
        email=data['email'],
        phone=data['phone'],
        password=bcrypt.generate_password_hash(data['password']).decode('utf-8'),
        # age ignored (computed)
        height=int(data['height']) if 'height' in data and str(data['height']).strip() not in ['', 'None', 'null'] else None,
        weight=int(data['weight']) if 'weight' in data and str(data['weight']).strip() not in ['', 'None', 'null'] else None,
        gender=data.get('gender'),
        date_of_birth=dob
    )
    db.session.add(user)
    db.session.commit()

    return jsonify({'message': 'User registered successfully'}), 201

# ----------------------
# Route to Login User
# ----------------------
@app.route('/users/login', methods=['POST'])
def login_user():
    data = request.get_json()
    if not data or not all(k in data for k in ('email', 'password')):
        return json_error('Missing required fields', 400)
    user = User.query.filter_by(email=data['email']).first()
    if user and bcrypt.check_password_hash(user.password, data['password']):
        access_token = create_access_token(identity=user.userid)
        return jsonify({'access_token': access_token, 'userid': user.userid, 'message': 'Login successful'}), 200
    return json_error('Invalid credentials', 401)

# ----------------------
# Route to Get/Update User Profile
# ----------------------
@app.route('/users/<int:user_id>', methods=['GET', 'PUT'])
def user_profile(user_id):
    user = User.query.get(user_id)
    if not user:
        return json_error('User not found', 404)
    if request.method == 'GET':
        return jsonify({
            'userid': user.userid,
            'name': user.name,
            'email': user.email,
            'phone': user.phone,
            'age': calc_age(user.date_of_birth),
            'height': user.height,
            'weight': user.weight,
            'gender': user.gender,
            'date_of_birth': user.date_of_birth.isoformat() if user.date_of_birth else None
        })
    if request.method == 'PUT':
        data = request.get_json() or {}
        user.name = data.get('name', user.name)
        user.email = data.get('email', user.email)
        user.phone = data.get('phone', user.phone)
        # Age not directly updated; if date_of_birth provided, recalc age on next GET
        if 'date_of_birth' in data and data['date_of_birth']:
            try:
                user.date_of_birth = datetime.strptime(data['date_of_birth'], '%Y-%m-%d').date()
            except ValueError:
                return json_error('Invalid date_of_birth format, expected YYYY-MM-DD', 400)
        user.gender = data.get('gender', user.gender)
        user.height = int(data['height']) if 'height' in data and str(data['height']).strip() not in ['', 'None', 'null'] else user.height
        user.weight = int(data['weight']) if 'weight' in data and str(data['weight']).strip() not in ['', 'None', 'null'] else user.weight
        db.session.commit()
    return jsonify({'message': 'Profile updated successfully'})

# ----------------------
# Route to Get Doctors
# ----------------------
@app.route('/doctors', methods=['GET'])
def get_doctors():
    # Fetch all doctors
    doctors = db.session.query(
        Doctor.doctorid, Doctor.name, Doctor.speciality, Doctor.email, Doctor.phone, Hospital.name.label('hospital_name')
    ).join(Hospital, Doctor.hospitalid == Hospital.hospitalid).all()

    # Preload all availability rows to avoid N+1 queries
    avails = DoctorAvailability.query.all()
    from collections import defaultdict
    avails_by_doctor = defaultdict(list)
    for a in avails:
        avails_by_doctor[a.doctorid].append(a)

    day_order = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']

    def build_summary(rows):
        if not rows:
            return None
        # Group days by identical time range
        buckets = defaultdict(list)  # key: (start,end) -> [dayname]
        for r in rows:
            if not (r.starttime and r.endtime and r.dayname):
                continue
            buckets[(r.starttime, r.endtime)].append(r.dayname)
        segments = []
        for (start, end), days in buckets.items():
            # Sort days according to week order
            days = sorted(set(days), key=lambda d: day_order.index(d) if d in day_order else 99)
            start_str = start.strftime('%I:%M %p').lstrip('0')
            end_str = end.strftime('%I:%M %p').lstrip('0')
            segments.append((day_order.index(days[0]) if days[0] in day_order else 99,
                              f"{', '.join(days)}: {start_str} - {end_str}"))
        # Sort segments by first day occurrence
        segments.sort(key=lambda x: x[0])
        return ' | '.join(seg for _, seg in segments) if segments else None

    result = []
    for doc in doctors:
        rows = avails_by_doctor.get(doc.doctorid, [])
        summary = build_summary(rows)
        availability_blocks = []
        for r in rows:
            if r.dayname and r.starttime and r.endtime:
                availability_blocks.append({
                    'day': r.dayname,
                    'start': r.starttime.strftime('%H:%M'),
                    'end': r.endtime.strftime('%H:%M')
                })
        result.append({
            'doctorid': doc.doctorid,
            'name': doc.name,
            'speciality': doc.speciality,
            'email': doc.email,
            'phone': doc.phone,
            'hospital': doc.hospital_name,
            'availability_summary': summary,
            'availability_blocks': availability_blocks
        })
    return jsonify(result)

# ----------------------
# Route to Get Doctor Availability
# ----------------------
@app.route('/doctors/<int:doctor_id>/availability', methods=['GET'])
def get_doctor_availability(doctor_id):
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'message': 'date query param required (YYYY-MM-DD)'}), 400
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'message': 'Invalid date format, expected YYYY-MM-DD'}), 400
    # Map Python weekday to 3-letter form matching DB (Mon, Tue, Wed, Thu, Fri, Sat, Sun)
    day_abbrev = target_date.strftime('%a')  # already correct capitalization
    avail = DoctorAvailability.query.filter_by(doctorid=doctor_id, dayname=day_abbrev).first()
    if not avail:
        return jsonify([])
    from datetime import datetime as dt_mod, timedelta
    slots = []
    cursor = dt_mod.combine(target_date, avail.starttime)
    end_dt = dt_mod.combine(target_date, avail.endtime)
    while cursor < end_dt:
        slots.append(cursor.strftime('%H:%M'))
        cursor += timedelta(minutes=30)
    return jsonify(slots)

# ----------------------
# Create Appointment
# ----------------------
@app.route('/appointments', methods=['POST'])
def create_appointment():
    data = request.get_json() or {}
    print('[create_appointment] incoming payload:', data)
    required = ['userid','doctorid','date','time']
    if any(k not in data or not data[k] for k in required):
        return json_error('userid, doctorid, date, time are required', 400)
    user = User.query.get(data['userid'])
    doctor = Doctor.query.get(data['doctorid'])
    if not user or not doctor:
        return json_error('Invalid user or doctor', 400)
    try:
        appt_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        appt_time = datetime.strptime(data['time'], '%H:%M').time()
    except ValueError:
        return json_error('Invalid date or time format', 400)
    appt = Appointment(
        userid=user.userid,
        doctorid=doctor.doctorid,
        appointment_date=appt_date,
        appointment_time=appt_time,
        reason=default_reason(data.get('reason')),
        status=True
    )
    try:
        db.session.add(appt)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        import traceback; traceback.print_exc()
        return json_error('Database error creating appointment', 500, error=str(e))
    hospital = Hospital.query.get(doctor.hospitalid)
    return jsonify({
        'message': 'Appointment created',
        'appointment': {
            'appointmentid': appt.appointmentid,
            'userid': appt.userid,
            'doctorid': appt.doctorid,
            'date': appt.appointment_date.strftime('%Y-%m-%d'),
            'time': appt.appointment_time.strftime('%H:%M'),
            'reason': appt.reason,
            'status': appt.status,
            'doctor_name': doctor.name,
            'speciality': doctor.speciality,
            'hospital': hospital.name if hospital else None
        }
    }), 201

# Debug endpoint to inspect appointments table columns
@app.route('/debug/appointments/schema')
def debug_appointments_schema():
    from sqlalchemy import inspect
    insp = inspect(db.engine)
    cols = []
    if 'appointments' in insp.get_table_names():
        for c in insp.get_columns('appointments'):
            cols.append({'name': c['name'], 'type': str(c['type'])})
    return jsonify({'columns': cols})

# Debug endpoint for identity/default
@app.route('/debug/appointments/identity')
def debug_appt_identity():
    row = db.session.execute(text("""
        SELECT column_default FROM information_schema.columns WHERE table_name='appointments' AND column_name='appointmentid';
    """)).fetchone()
    return jsonify({'appointmentid_default': row[0] if row else None})

# ----------------------
# Debug: Active database info
# ----------------------
@app.route('/debug/db')
def debug_db():
    try:
        engine_url = db.engine.url
        info = {
            'driver': engine_url.get_backend_name(),
            'database': engine_url.database,
            'host': engine_url.host,
            'port': engine_url.port,
            'username': engine_url.username,
            'render_env': bool(os.getenv('RENDER')),
            # no sqlite fallback now; presence of sqlite indicates misconfiguration
            'is_sqlite': db.engine.url.get_backend_name().startswith('sqlite')
        }
        # Simple connectivity check
        db.session.execute(text('SELECT 1'))
        info['connectivity'] = 'ok'
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ----------------------
# Get Appointments for a User
# ----------------------
@app.route('/users/<int:user_id>/appointments', methods=['GET'])
def get_user_appointments(user_id):
    user = User.query.get(user_id)
    if not user:
        return json_error('User not found', 404)
    from sqlalchemy import asc
    q = db.session.query(Appointment, Doctor, Hospital).join(Doctor, Appointment.doctorid==Doctor.doctorid).join(Hospital, Doctor.hospitalid==Hospital.hospitalid).filter(Appointment.userid==user_id).order_by(asc(Appointment.appointment_date), asc(Appointment.appointment_time)).all()
    results = []
    for appt, doc, hosp in q:
        results.append({
            'appointmentid': appt.appointmentid,
            'doctorid': appt.doctorid,
            'date': appt.appointment_date.strftime('%Y-%m-%d'),
            'time': appt.appointment_time.strftime('%H:%M'),
            'reason': appt.reason,
            'status': appt.status,
            'doctor_name': doc.name,
            'speciality': doc.speciality,
            'hospital': hosp.name
        })
    return jsonify(results)

# ----------------------
# Cancel Appointment (soft cancel -> status False)
# ----------------------
@app.route('/appointments/<int:appointment_id>/cancel', methods=['PUT'])
def cancel_appointment(appointment_id):
    appt = Appointment.query.get(appointment_id)
    if not appt:
        return json_error('Appointment not found', 404)
    if not appt.status:
        return json_error('Already cancelled', 400)
    appt.status = False
    db.session.commit()
    return jsonify({'message': 'Appointment cancelled', 'appointmentid': appt.appointmentid, 'status': appt.status})

# ----------------------
# Debug endpoint to show users schema
# ----------------------
@app.route('/debug/users/schema')
def debug_users_schema():
    insp = inspect(db.engine)
    cols = []
    if 'users' in insp.get_table_names():
        for c in insp.get_columns('users'):
            cols.append({'name': c['name'], 'type': str(c['type'])})
    return jsonify({'columns': cols})

# ----------------------
# Simple static file serving so ngrok root shows the app
# ----------------------
@app.route('/')
def serve_root():
    # Serve main landing page
    return send_from_directory('.', 'index.html')

@app.route('/<path:page>')
def serve_page(page):
    # Only allow known html pages; avoid clashing with JSON API endpoints
    allowed = {
        'index.html','doctors.html','booking.html','confirm.html','profile.html','login.html','about.html','doc-profile.html'
    }
    if page in allowed:
        return send_from_directory('.', page)
    # let API routes continue to work (they are defined explicitly like /doctors)
    return ("Not Found", 404)

# ----------------------
# Doctor detail with availability
# ----------------------
@app.route('/doctors/<int:doctor_id>', methods=['GET'])
def get_doctor_detail(doctor_id):
    doc = db.session.query(Doctor, Hospital).join(Hospital, Doctor.hospitalid==Hospital.hospitalid).filter(Doctor.doctorid==doctor_id).first()
    if not doc:
        return json_error('Doctor not found', 404)
    doctor, hospital = doc
    # Gather availability
    from collections import defaultdict
    rows = DoctorAvailability.query.filter_by(doctorid=doctor_id).all()
    day_order = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    availability_blocks = []
    for r in rows:
        if r.dayname and r.starttime and r.endtime:
            availability_blocks.append({
                'day': r.dayname,
                'start': r.starttime.strftime('%H:%M'),
                'end': r.endtime.strftime('%H:%M')
            })
    # summary reuse
    buckets = defaultdict(list)
    for blk in availability_blocks:
        buckets[(blk['start'], blk['end'])].append(blk['day'])
    segments = []
    for (start,end), days in buckets.items():
        days = sorted(set(days), key=lambda d: day_order.index(d) if d in day_order else 99)
        from datetime import datetime as dt
        # convert times to 12h
        def fmt(t):
            return dt.strptime(t, '%H:%M').strftime('%I:%M %p').lstrip('0')
        segments.append((day_order.index(days[0]) if days[0] in day_order else 99, f"{', '.join(days)}: {fmt(start)} - {fmt(end)}"))
    segments.sort(key=lambda x: x[0])
    availability_summary = ' | '.join(seg for _, seg in segments) if segments else None

    return jsonify({
        'doctorid': doctor.doctorid,
        'name': doctor.name,
        'speciality': doctor.speciality,
        'email': doctor.email,
        'phone': doctor.phone,
        'hospital': hospital.name,
        'availability_blocks': availability_blocks,
        'availability_summary': availability_summary
    })

# ----------------------
# Health Check
# ----------------------
@app.route('/health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return json_error('database error', 500, error=str(e))

# ----------------------
# Debug: service config snapshot
# ----------------------
@app.route('/debug/config')
def debug_config():
    return jsonify({
    'is_sqlite': app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:'),
        'sqlalchemy_url': app.config['SQLALCHEMY_DATABASE_URI'],
        'has_secret_key': bool(app.config.get('SECRET_KEY')),
        'env_render': bool(os.getenv('RENDER'))
    })

# ----------------------
# Debug: environment variables
# ----------------------
@app.route('/debug/env')
def debug_env():
    seen = {}
    for k in possible_db_vars:
        if os.getenv(k):
            seen[k] = True
    active = app.config['SQLALCHEMY_DATABASE_URI']
    redacted = active
    if '://' in redacted:
        try:
            scheme, rest = redacted.split('://',1)
            if '@' in rest:
                creds, hostpart = rest.split('@',1)
                if ':' in creds:
                    user = creds.split(':',1)[0]
                else:
                    user = creds
                redacted = f"{scheme}://{user}:***@{hostpart}"
        except Exception:
            pass
    return jsonify({
        'render_detected': on_render,
        'db_url_redacted': redacted,
        'db_driver': app.config['SQLALCHEMY_DATABASE_URI'].split(':',1)[0],
        'db_env_vars_seen': list(seen.keys())
    })

# ----------------------
# Run the App
# ----------------------
if __name__ == '__main__':
    host = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.getenv('PORT', os.getenv('FLASK_RUN_PORT', '5000')))
    app.run(host=host, port=port, debug=True)