from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token
from flask_cors import CORS
from datetime import datetime, date
import os

app = Flask(__name__)
CORS(app)
# ----------------------
# Configuration (updated for Render env vars & production enforcement)
# ----------------------
"""Goal: Prevent accidental sqlite usage in production (Render). Strengthen
detection & require explicit opt-in for sqlite fallback via ALLOW_SQLITE_FALLBACK=1.
Also delay optional .env loading until after Render detection so production
never depends on a bundled .env file."""

# First detect if we are on Render (independent of any .env loading)
render_markers = [
    'RENDER','RENDER_SERVICE_ID','RENDER_SERVICE_NAME','RENDER_INSTANCE_ID','RENDER_EXTERNAL_URL'
]
on_render = any(os.getenv(k) for k in render_markers)
_fs_detect_reasons = []
try:
    cwd = os.getcwd()
    if cwd.startswith('/opt/render'):
        _fs_detect_reasons.append(f"cwd:{cwd}")
    if os.path.exists('/opt/render'):
        _fs_detect_reasons.append('path:/opt/render')
except Exception:
    pass
if not on_render and _fs_detect_reasons:
    on_render = True

# Only load .env for local/dev (never in Render) so production env relies solely on platform vars.
if not on_render and os.path.exists('.env'):
    try:
        import importlib
        spec = importlib.util.find_spec('dotenv')
        if spec is not None:  # only attempt if installed
            from dotenv import load_dotenv  # type: ignore  # noqa: F401
            load_dotenv()
            print('[startup] Loaded local .env file')
    except Exception:
        pass

possible_db_vars = [
    'DATABASE_URL','DB_URL','POSTGRES_URL','POSTGRES_URI','DATABASE_URI',
    'MEDBOOK_DB','MEDBOOK_DATABASE_URL'
]
raw_db_url = None
for _v in possible_db_vars:
    val = os.getenv(_v)
    if val:
        raw_db_url = val
        break

ALLOW_SQLITE_FALLBACK = os.getenv('ALLOW_SQLITE_FALLBACK') == '1'

if raw_db_url and raw_db_url.startswith('postgres://'):
    raw_db_url = raw_db_url.replace('postgres://','postgresql://',1)
if raw_db_url and raw_db_url.startswith('postgresql://') and '+psycopg://' not in raw_db_url:
    raw_db_url = raw_db_url.replace('postgresql://', 'postgresql+psycopg://', 1)

if not raw_db_url:
    missing_msg = ('No database URL environment variable found among: ' + ', '.join(possible_db_vars))
    if on_render or not ALLOW_SQLITE_FALLBACK:
        env_keys_preview = ','.join(sorted(k for k in os.environ.keys() if k.startswith('RENDER')))
        raise RuntimeError(
            missing_msg + '. ' +
            ('Set DATABASE_URL in the platform dashboard. ' if on_render else 'Set one locally or export ALLOW_SQLITE_FALLBACK=1 for dev sqlite. ') +
            f'RenderDetected={on_render} RenderEnvKeys=[{env_keys_preview or "<none>"}] Heuristics={";".join(_fs_detect_reasons) or "none"}'
        )
    raw_db_url = 'sqlite:///local_dev.db'
    print('[startup] DEV SQLITE FALLBACK: using sqlite:///local_dev.db (set a DB URL or unset ALLOW_SQLITE_FALLBACK to force error)')

app.config['SQLALCHEMY_DATABASE_URI'] = raw_db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-insecure-key')
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 280
}
print(f"[startup] Using database URL: {app.config['SQLALCHEMY_DATABASE_URI']} (on_render={on_render} heuristics={_fs_detect_reasons} allow_sqlite={ALLOW_SQLITE_FALLBACK})")

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
    gender = db.Column(db.String)
    date_of_birth = db.Column(db.Date)
    medical_license_number = db.Column(db.String(50))
    years_of_experience = db.Column(db.Integer)
    professional_bio = db.Column(db.Text)
    password = db.Column(db.String)  # hashed
    # Approval workflow (Option B)
    approval_status = db.Column(db.String, nullable=False, default='pending')  # pending|approved|rejected|suspended
    approved_at = db.Column(db.DateTime)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.userid'))
    rejection_reason = db.Column(db.Text)
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

# ----------------------
# Doctor Review Model (existing table doctor_reviews)
# ----------------------
class DoctorReview(db.Model):
    __tablename__ = 'doctor_reviews'
    reviewid = db.Column(db.BigInteger, primary_key=True)
    doctorid = db.Column(db.Integer, db.ForeignKey('doctors.doctorid'), nullable=False)
    userid = db.Column(db.Integer, db.ForeignKey('users.userid'), nullable=False)
    appointmentid = db.Column(db.Integer, db.ForeignKey('appointments.appointmentid'), nullable=False)  # newly added to support per-appointment reviews
    rating = db.Column(db.Numeric(2,1), nullable=False)  # store as numeric(2,1); we will restrict to 1-5 whole stars
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_json(self):
        return {
            'reviewid': self.reviewid,
            'doctorid': self.doctorid,
            'userid': self.userid,
            'rating': float(self.rating) if self.rating is not None else None,
            'comments': self.comments,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

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

# ----------------------
# Shared aggregation helpers (availability + reviews)
# ----------------------
DAY_ORDER = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']

def _availability_blocks(rows):
    """Convert DoctorAvailability rows into simple blocks list."""
    blocks = []
    for r in rows:
        if r.dayname and r.starttime and r.endtime:
            blocks.append({
                'day': r.dayname,
                'start': r.starttime.strftime('%H:%M'),
                'end': r.endtime.strftime('%H:%M')
            })
    return blocks

def summarize_availability(blocks):
    """Produce compact summary string grouping identical time ranges across days."""
    if not blocks:
        return None
    from collections import defaultdict
    buckets = defaultdict(list)
    for blk in blocks:
        buckets[(blk['start'], blk['end'])].append(blk['day'])
    segments = []
    from datetime import datetime as dt
    for (start, end), days in buckets.items():
        days = sorted(set(days), key=lambda d: DAY_ORDER.index(d) if d in DAY_ORDER else 99)
        def _fmt(t):
            return dt.strptime(t, '%H:%M').strftime('%I:%M %p').lstrip('0')
        segments.append((DAY_ORDER.index(days[0]) if days and days[0] in DAY_ORDER else 99,
                          f"{', '.join(days)}: {_fmt(start)} - {_fmt(end)}"))
    segments.sort(key=lambda x: x[0])
    return ' | '.join(seg for _, seg in segments) if segments else None

def get_availability_for_doctors(doctor_ids):
    """Return mapping: doctorid -> (blocks list, summary). Single query to avoid N+1."""
    if not doctor_ids:
        return {}
    rows = DoctorAvailability.query.filter(DoctorAvailability.doctorid.in_(doctor_ids)).all()
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in rows:
        grouped[r.doctorid].append(r)
    result = {}
    for did, rlist in grouped.items():
        blocks = _availability_blocks(rlist)
        result[did] = {
            'blocks': blocks,
            'summary': summarize_availability(blocks)
        }
    return result

def get_review_aggregates(doctor_ids):
    """Return mapping doctorid -> {review_count, avg_rating}."""
    if not doctor_ids:
        return {}
    from sqlalchemy import func
    rows = db.session.query(
        DoctorReview.doctorid,
        func.count(DoctorReview.reviewid).label('review_count'),
        func.avg(DoctorReview.rating).label('avg_rating')
    ).filter(DoctorReview.doctorid.in_(doctor_ids)).group_by(DoctorReview.doctorid).all()
    return {
        r.doctorid: {
            'review_count': int(r.review_count),
            'avg_rating': float(r.avg_rating) if r.avg_rating is not None else None
        } for r in rows
    }

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
        # --- doctors table additive columns (new doctor signup extended profile) ---
        if 'doctors' in insp.get_table_names():
            dcols = {c['name'] for c in insp.get_columns('doctors')}
            col_additions = [
                ('gender','ALTER TABLE doctors ADD COLUMN gender VARCHAR'),
                ('date_of_birth','ALTER TABLE doctors ADD COLUMN date_of_birth DATE'),
                ('medical_license_number','ALTER TABLE doctors ADD COLUMN medical_license_number VARCHAR(50)'),
                ('years_of_experience','ALTER TABLE doctors ADD COLUMN years_of_experience INTEGER'),
                ('professional_bio','ALTER TABLE doctors ADD COLUMN professional_bio TEXT'),
                ('password','ALTER TABLE doctors ADD COLUMN password VARCHAR'),
                # Approval workflow columns
                ('approval_status',"ALTER TABLE doctors ADD COLUMN approval_status VARCHAR NOT NULL DEFAULT 'pending'"),
                ('approved_at','ALTER TABLE doctors ADD COLUMN approved_at TIMESTAMP'),
                ('approved_by','ALTER TABLE doctors ADD COLUMN approved_by INTEGER REFERENCES users(userid)'),
                ('rejection_reason','ALTER TABLE doctors ADD COLUMN rejection_reason TEXT')
            ]
            for cname, ddl in col_additions:
                if cname not in dcols:
                    try:
                        engine.execute(text(ddl))
                        print('[ensure_schema] added doctors.'+cname)
                    except Exception:
                        pass
            # Index on approval_status for filtering
            try:
                if backend == 'postgresql':
                    engine.execute(text('CREATE INDEX IF NOT EXISTS idx_doctors_approval_status ON doctors(approval_status)'))
                else:
                    engine.execute(text('CREATE INDEX IF NOT EXISTS idx_doctors_approval_status ON doctors(approval_status)'))
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

        # --- doctor_reviews additive columns ---
        if 'doctor_reviews' in insp.get_table_names():
            review_cols = {c['name'] for c in insp.get_columns('doctor_reviews')}
            if 'appointmentid' not in review_cols:
                try:
                    engine.execute(text('ALTER TABLE doctor_reviews ADD COLUMN appointmentid INTEGER REFERENCES appointments(appointmentid)'))
                    print('[ensure_schema] Added appointmentid column to doctor_reviews')
                except Exception:
                    pass
        # --- performance indexes (Postgres only) ---
        if backend == 'postgresql':
            try:
                engine.execute(text('CREATE INDEX IF NOT EXISTS idx_appointments_user_date ON appointments (userid, appointment_date)'))
            except Exception:
                pass
            try:
                engine.execute(text('CREATE INDEX IF NOT EXISTS idx_doctor_reviews_user_appt ON doctor_reviews (userid, appointmentid)'))
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
# Register Doctor (pending approval)
# ----------------------
@app.route('/doctors/register', methods=['POST'])
def register_doctor():
    data = request.get_json() or {}
    required = ['name','email','phone','speciality','hospital','password']
    missing = [k for k in required if not str(data.get(k,'' )).strip()]
    if missing:
        return json_error('Missing: '+', '.join(missing), 400)
    try:
        # Ensure hospital exists or create
        hosp_name = data.get('hospital').strip()
        hospital = Hospital.query.filter(Hospital.name.ilike(hosp_name)).first()
        if not hospital:
            hospital = Hospital(name=hosp_name)
            db.session.add(hospital)
            db.session.flush()

        hashed = bcrypt.generate_password_hash(data['password']).decode('utf-8')
        doctor = Doctor(
            name=data['name'].strip(),
            email=data['email'].strip(),
            phone=data['phone'].strip(),
            speciality=data['speciality'].strip(),
            hospitalid=hospital.hospitalid,
            gender=(data.get('gender') or None),
            date_of_birth=datetime.strptime(data['date_of_birth'],'%Y-%m-%d').date() if data.get('date_of_birth') else None,
            medical_license_number=(data.get('medical_license_number') or None),
            years_of_experience=int(data['experience']) if str(data.get('experience','')).isdigit() else None,
            professional_bio=(data.get('bio') or None),
            password=hashed,
            approval_status='pending'
        )
        db.session.add(doctor)
        db.session.flush()

        # availability blocks
        blocks = data.get('availability') or []
        for b in blocks:
            day = b.get('day'); start=b.get('start'); end=b.get('end')
            if not day or not start or not end:
                continue
            try:
                st = datetime.strptime(start,'%H:%M').time()
                en = datetime.strptime(end,'%H:%M').time()
            except Exception:
                continue
            db.session.add(DoctorAvailability(dayname=day, doctorid=doctor.doctorid, starttime=st, endtime=en))
        db.session.commit()
        return jsonify({'message':'Doctor submitted for approval','doctorid':doctor.doctorid}), 201
    except Exception as e:
        db.session.rollback()
        # Surface DB/backend error message to client for quicker diagnosis
        err_msg = str(getattr(e, 'orig', e))
        return json_error('Registration failed', 500, error=err_msg)

# ----------------------
# Doctor Login (must be approved)
# ----------------------
@app.route('/doctors/login', methods=['POST'])
def doctor_login():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip()
    password = (data.get('password') or '').strip()
    if not email or not password:
        return json_error('Email and password required', 400)
    doctor = Doctor.query.filter_by(email=email).first()
    if not doctor or not doctor.password or not bcrypt.check_password_hash(doctor.password, password):
        return json_error('Invalid credentials', 401)
    if doctor.approval_status != 'approved':
        return json_error('Doctor not approved', 403)
    return jsonify({'doctorid': doctor.doctorid, 'name': doctor.name})

# ----------------------
# Admin endpoints to approve/reject doctor
# Protect with X-Admin-Api-Key header if ADMIN_API_KEY env var set
# ----------------------
def _require_admin():
    admin_key = os.getenv('ADMIN_API_KEY')
    if not admin_key:
        return True
    return request.headers.get('X-Admin-Api-Key') == admin_key

@app.route('/admin/doctors/<int:doctor_id>/approve', methods=['POST'])
def approve_doctor(doctor_id):
    if not _require_admin():
        return json_error('Unauthorized', 401)
    doc = Doctor.query.get(doctor_id)
    if not doc:
        return json_error('Doctor not found', 404)
    doc.approval_status='approved'
    doc.approved_at=datetime.utcnow()
    # Optional: track approver if you pass X-Approver-UserId
    try:
        approver = int(request.headers.get('X-Approver-UserId','0'))
        if approver:
            doc.approved_by = approver
    except Exception:
        pass
    db.session.commit()
    return jsonify({'message':'approved','doctorid':doctor_id})

@app.route('/admin/doctors/<int:doctor_id>/reject', methods=['POST'])
def reject_doctor(doctor_id):
    if not _require_admin():
        return json_error('Unauthorized', 401)
    data = request.get_json() or {}
    reason = (data.get('reason') or '').strip() or None
    doc = Doctor.query.get(doctor_id)
    if not doc:
        return json_error('Doctor not found', 404)
    doc.approval_status='rejected'
    doc.rejection_reason = reason
    db.session.commit()
    return jsonify({'message':'rejected','doctorid':doctor_id,'reason':reason})

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
    # Only return approved doctors publicly
    doctors = db.session.query(
        Doctor.doctorid, Doctor.name, Doctor.speciality, Doctor.email, Doctor.phone, Hospital.name.label('hospital_name')
    ).join(Hospital, Doctor.hospitalid == Hospital.hospitalid).filter(Doctor.approval_status=='approved').all()
    ids = [d.doctorid for d in doctors]
    review_map = get_review_aggregates(ids)
    availability_map = get_availability_for_doctors(ids)
    result = []
    for d in doctors:
        avail_info = availability_map.get(d.doctorid, {})
        result.append({
            'doctorid': d.doctorid,
            'name': d.name,
            'speciality': d.speciality,
            'email': d.email,
            'phone': d.phone,
            'hospital': d.hospital_name,
            'availability_summary': avail_info.get('summary'),
            'availability_blocks': avail_info.get('blocks', []),
            'review_count': review_map.get(d.doctorid, {}).get('review_count', 0),
            'avg_rating': review_map.get(d.doctorid, {}).get('avg_rating')
        })
    return jsonify(result)

# ----------------------
# Route to Get Single Doctor (details)
# ----------------------
@app.route('/doctors/<int:doctor_id>', methods=['GET'])
def get_doctor_detail(doctor_id):
    # Only allow approved doctors to be fetched publicly
    row = (
        db.session.query(
            Doctor,
            Hospital.name.label('hospital_name')
        )
        .join(Hospital, Doctor.hospitalid == Hospital.hospitalid)
        .filter(Doctor.doctorid == doctor_id, Doctor.approval_status == 'approved')
        .first()
    )
    if not row:
        return json_error('Doctor not found', 404)

    doc, hospital_name = row
    # Aggregates
    review_map = get_review_aggregates([doc.doctorid])
    availability_map = get_availability_for_doctors([doc.doctorid])
    rev = review_map.get(doc.doctorid, {})
    avail = availability_map.get(doc.doctorid, {})
    payload = {
        'doctorid': doc.doctorid,
        'name': doc.name,
        'speciality': doc.speciality,
        'email': doc.email,
        'phone': doc.phone,
        'hospital': hospital_name,
        'gender': doc.gender,
        'date_of_birth': doc.date_of_birth.strftime('%Y-%m-%d') if doc.date_of_birth else None,
        'medical_license_number': doc.medical_license_number,
        'years_of_experience': doc.years_of_experience,
        'professional_bio': doc.professional_bio,
        'availability_summary': avail.get('summary'),
        'availability_blocks': avail.get('blocks', []),
        'review_count': rev.get('review_count', 0),
        'avg_rating': rev.get('avg_rating')
    }
    return jsonify(payload)

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
    # Require approved doctor
    doc_ok = Doctor.query.filter_by(doctorid=doctor_id, approval_status='approved').first()
    if not doc_ok:
        return jsonify([])
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
    try:
        print(f"[appointments] incoming request for user {user_id}")
    except Exception:
        pass
    user = User.query.get(user_id)
    if not user:
        return json_error('User not found', 404)
    from sqlalchemy import asc
    # Single query with LEFT OUTER JOIN to doctor_reviews for this user
    q = (
        db.session.query(
            Appointment,
            Doctor,
            Hospital,
            DoctorReview.rating.label('r_rating'),
            DoctorReview.comments.label('r_comments')
        )
        .join(Doctor, Appointment.doctorid==Doctor.doctorid)
        .join(Hospital, Doctor.hospitalid==Hospital.hospitalid)
        .outerjoin(DoctorReview, (DoctorReview.appointmentid==Appointment.appointmentid) & (DoctorReview.userid==user_id))
        .filter(Appointment.userid==user_id)
        .order_by(asc(Appointment.appointment_date), asc(Appointment.appointment_time))
        .all()
    )
    results = []
    for appt, doc, hosp, r_rating, r_comments in q:
        results.append({
            'appointmentid': appt.appointmentid,
            'doctorid': appt.doctorid,
            'date': appt.appointment_date.strftime('%Y-%m-%d'),
            'time': appt.appointment_time.strftime('%H:%M'),
            'reason': appt.reason,
            'status': appt.status,
            'doctor_name': doc.name,
            'speciality': doc.speciality,
            'hospital': hosp.name,
            'has_review': r_rating is not None,
            'user_rating': float(r_rating) if r_rating is not None else None,
            'user_comments': r_comments
        })
    try:
        print(f"[appointments] user {user_id} returning {len(results)} rows")
    except Exception:
        pass
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
# Submit / Update Rating for an Appointment
# ----------------------
@app.route('/appointments/<int:appointment_id>/rating', methods=['POST'])
def rate_appointment(appointment_id):
    appt = Appointment.query.get(appointment_id)
    if not appt:
        return json_error('Appointment not found', 404)
    # Prevent rating future / cancelled appointments
    today = date.today()
    if appt.status is False:
        return json_error('Cannot rate a cancelled appointment', 400)
    if appt.appointment_date >= today:
        return json_error('Can only rate a completed (past) appointment', 400)
    data = request.get_json() or {}
    if 'rating' not in data:
        return json_error('rating required', 400)
    try:
        rating_val = float(data['rating'])
    except (TypeError, ValueError):
        return json_error('rating must be a number', 400)
    if rating_val < 1 or rating_val > 5:
        return json_error('rating must be between 1 and 5', 400)
    # Support half-stars: round to nearest 0.5
    rating_val = round(rating_val * 2) / 2.0
    comments = (data.get('comment') or data.get('comments') or '').strip() or None
    # One review per appointment now that appointmentid column exists
    existing = DoctorReview.query.filter_by(appointmentid=appointment_id).first()
    if existing:
        existing.rating = rating_val
        existing.comments = comments
        existing.created_at = datetime.utcnow()
        action = 'updated'
    else:
        rev = DoctorReview(userid=appt.userid, doctorid=appt.doctorid, appointmentid=appointment_id, rating=rating_val, comments=comments)
        db.session.add(rev)
        action = 'created'
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return json_error('database error saving rating', 500, error=str(e))
    return jsonify({'message': f'rating {action}', 'doctorid': appt.doctorid, 'userid': appt.userid, 'appointmentid': appointment_id, 'rating': rating_val, 'comments': comments})

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

# Debug endpoint to show doctors schema
@app.route('/debug/doctors/schema')
def debug_doctors_schema():
    insp = inspect(db.engine)
    cols = []
    if 'doctors' in insp.get_table_names():
        for c in insp.get_columns('doctors'):
            cols.append({'name': c['name'], 'type': str(c['type'])})
    return jsonify({'columns': cols})

# ----------------------
# Simple static file serving (serve HTML from this package directory rather than CWD)
# Prevents breakage after removing legacy root-level duplicates.
from pathlib import Path
_FRONTEND_DIR = Path(__file__).parent

@app.route('/')
def serve_root():
    return send_from_directory(_FRONTEND_DIR, 'index.html')

@app.route('/<path:page>')
def serve_page(page):
    allowed = {
        'index.html','doctors.html','booking.html','confirm.html','profile.html','login.html','about.html','doc-profile.html','doctor_signup.html','doctor_login.html',
        # static assets
        'style.css'
    }
    if page in allowed:
        return send_from_directory(_FRONTEND_DIR, page)
    return ("Not Found", 404)


# Lightweight favicon to avoid noisy 404s in logs/browsers
@app.route('/favicon.ico')
def favicon():
    # Tiny 1x1 transparent PNG (base64 decoded) to keep it simple
    from base64 import b64decode
    from flask import Response
    png_base64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAAC0lEQVR42mP8/x8AAwMB/er+3T0AAAAASUVORK5CYII='
    data = b64decode(png_base64)
    return Response(data, mimetype='image/png')
# ----------------------
# Doctor detail with availability
# ----------------------
@app.route('/doctors/<int:doctor_id>', methods=['GET'])
def get_doctor_detail(doctor_id):
    doc = db.session.query(Doctor, Hospital).join(Hospital, Doctor.hospitalid==Hospital.hospitalid).filter(Doctor.doctorid==doctor_id, Doctor.approval_status=='approved').first()
    if not doc:
        return json_error('Doctor not found', 404)
    doctor, hospital = doc
    review_map = get_review_aggregates([doctor_id])
    review_info = review_map.get(doctor_id, {'review_count': 0, 'avg_rating': None})
    avail_map = get_availability_for_doctors([doctor_id])
    avail_info = avail_map.get(doctor_id, {'blocks': [], 'summary': None})
    return jsonify({
        'doctorid': doctor.doctorid,
        'name': doctor.name,
        'speciality': doctor.speciality,
        'email': doctor.email,
        'phone': doctor.phone,
        'hospital': hospital.name,
        'availability_blocks': avail_info.get('blocks', []),
        'availability_summary': avail_info.get('summary'),
        'review_count': review_info.get('review_count', 0),
        'avg_rating': review_info.get('avg_rating')
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
        'render_detection_heuristics': _fs_detect_reasons,
        'db_url_redacted': redacted,
        'db_driver': app.config['SQLALCHEMY_DATABASE_URI'].split(':',1)[0],
        'db_env_vars_seen': list(seen.keys()),
        'allow_sqlite_fallback': ALLOW_SQLITE_FALLBACK,
        'possible_db_vars': possible_db_vars
    })

# ----------------------
# Run the App
# ----------------------
if __name__ == '__main__':
    host = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.getenv('PORT', os.getenv('FLASK_RUN_PORT', '5000')))
    app.run(host=host, port=port, debug=True)