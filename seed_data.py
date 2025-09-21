"""Seed sample data if tables are empty.
Usage:
  python seed_data.py
Requires DATABASE_URL env var (or fallback SQLite) already configured.
"""
from Medbook.table import app, db, Hospital, Doctor, DoctorAvailability, User, bcrypt
from datetime import time, date

def maybe_seed():
    with app.app_context():
        if Hospital.query.first():
            print('Data already present; skipping seed.')
            return
        h1 = Hospital(name='City Hospital', address='123 Main St', phone='111-222-3333', email='info@cityhosp.test')
        h2 = Hospital(name='Lakeside Clinic', address='789 Lake Rd', phone='222-333-4444', email='contact@lake.test')
        db.session.add_all([h1, h2]); db.session.flush()
        d1 = Doctor(name='Dr. Alice Smith', speciality='Cardiology', hospitalid=h1.hospitalid, email='alice@hospital.test', phone='555-1000')
        d2 = Doctor(name='Dr. Bob Lee', speciality='Dermatology', hospitalid=h1.hospitalid, email='bob@hospital.test', phone='555-1001')
        d3 = Doctor(name='Dr. Carol Jones', speciality='Neurology', hospitalid=h2.hospitalid, email='carol@hospital.test', phone='555-2000')
        db.session.add_all([d1, d2, d3]); db.session.flush()
        avails = [
            DoctorAvailability(doctorid=d1.doctorid, dayname='Mon', starttime=time(9,0), endtime=time(12,0)),
            DoctorAvailability(doctorid=d1.doctorid, dayname='Wed', starttime=time(13,0), endtime=time(17,0)),
            DoctorAvailability(doctorid=d2.doctorid, dayname='Tue', starttime=time(10,0), endtime=time(14,0)),
            DoctorAvailability(doctorid=d3.doctorid, dayname='Thu', starttime=time(8,30), endtime=time(11,30)),
            DoctorAvailability(doctorid=d3.doctorid, dayname='Fri', starttime=time(14,0), endtime=time(18,0)),
        ]
        db.session.add_all(avails)
        test_user = User(name='Test Patient', email='test@patient.test', phone='555-0000', password=bcrypt.generate_password_hash('password').decode('utf-8'), gender='Other', date_of_birth=date(1990,1,1))
        db.session.add(test_user)
        db.session.commit()
        print('Seed complete.')

if __name__ == '__main__':
    maybe_seed()
