-- Medbook schema (PostgreSQL)
-- Run this against an empty database (e.g. medbook)
-- psql example:
--   psql -h HOST -U USER -d postgres -c "CREATE DATABASE medbook";
--   psql -h HOST -U USER -d medbook -f schema.sql

BEGIN;

CREATE TABLE users (
  userid SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  phone TEXT NOT NULL,
  password TEXT NOT NULL,
  age INTEGER,
  height INTEGER,
  weight INTEGER,
  gender VARCHAR,
  date_of_birth DATE,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE hospitals (
  hospitalid SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  address TEXT,
  phone TEXT,
  email TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE doctors (
  doctorid SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  speciality TEXT NOT NULL,
  hospitalid INTEGER NOT NULL REFERENCES hospitals(hospitalid) ON DELETE CASCADE,
  email TEXT NOT NULL,
  phone TEXT NOT NULL,
  -- Approval workflow
  approval_status TEXT NOT NULL DEFAULT 'pending', -- pending|approved|rejected|suspended
  approved_at TIMESTAMP NULL,
  approved_by INTEGER NULL REFERENCES users(userid),
  rejection_reason TEXT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE doctor_availability (
  dayid SERIAL PRIMARY KEY,
  dayname VARCHAR,              -- Mon, Tue, Wed, Thu, Fri, Sat, Sun
  doctorid INTEGER NOT NULL REFERENCES doctors(doctorid) ON DELETE CASCADE,
  starttime TIME,
  endtime TIME
);

CREATE TABLE appointments (
  appointmentid SERIAL PRIMARY KEY,
  userid INTEGER NOT NULL REFERENCES users(userid) ON DELETE CASCADE,
  doctorid INTEGER NOT NULL REFERENCES doctors(doctorid) ON DELETE CASCADE,
  status BOOLEAN NOT NULL DEFAULT TRUE,
  appointment_date DATE NOT NULL,
  appointment_time TIME NOT NULL,
  reason TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_doctors_hospital ON doctors(hospitalid);
CREATE INDEX idx_doctors_approval_status ON doctors(approval_status);
CREATE INDEX idx_availability_doctor ON doctor_availability(doctorid);
CREATE INDEX idx_appointments_user ON appointments(userid);
CREATE INDEX idx_appointments_doctor_date_time ON appointments(doctorid, appointment_date, appointment_time);

-- Optional: prevent double booking of same doctor slot (uncomment if desired)
-- ALTER TABLE appointments
--   ADD CONSTRAINT uq_doctor_slot UNIQUE (doctorid, appointment_date, appointment_time);

COMMIT;
