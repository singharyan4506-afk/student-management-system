from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os
from datetime import date
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your_secret_key_change_this'

DB = 'school.db'

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            roll_no TEXT UNIQUE NOT NULL,
            email TEXT,
            phone TEXT,
            course TEXT NOT NULL,
            year INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ("Present","Absent")),
            FOREIGN KEY(student_id) REFERENCES students(id),
            UNIQUE(student_id, date)
        );
    ''')
    c.execute("SELECT * FROM admin WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO admin (username, password) VALUES ('admin', 'admin123')")
    conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    error = None
    if request.method == 'POST':
        u, p = request.form['username'], request.form['password']
        conn = get_db()
        admin = conn.execute("SELECT * FROM admin WHERE username=? AND password=?", (u, p)).fetchone()
        conn.close()
        if admin:
            session['logged_in'] = True
            session['username'] = u
            return redirect(url_for('dashboard'))
        error = 'Invalid credentials. Try admin / admin123'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    today = date.today().isoformat()
    present = conn.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='Present'", (today,)).fetchone()[0]
    absent  = conn.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='Absent'",  (today,)).fetchone()[0]
    courses = conn.execute("SELECT course, COUNT(*) as cnt FROM students GROUP BY course").fetchall()
    conn.close()
    return render_template('dashboard.html', total=total, present=present, absent=absent, courses=courses, today=today)

@app.route('/students')
@login_required
def students():
    q = request.args.get('q', '').strip()
    conn = get_db()
    if q:
        rows = conn.execute(
            "SELECT * FROM students WHERE name LIKE ? OR roll_no LIKE ? OR course LIKE ? ORDER BY name",
            (f'%{q}%', f'%{q}%', f'%{q}%')).fetchall()
    else:
        rows = conn.execute("SELECT * FROM students ORDER BY name").fetchall()
    conn.close()
    return render_template('students.html', students=rows, q=q)

@app.route('/students/add', methods=['GET', 'POST'])
@login_required
def add_student():
    if request.method == 'POST':
        data = (request.form['name'], request.form['roll_no'], request.form['email'],
                request.form['phone'], request.form['course'], request.form['year'])
        try:
            conn = get_db()
            conn.execute("INSERT INTO students (name,roll_no,email,phone,course,year) VALUES (?,?,?,?,?,?)", data)
            conn.commit()
            conn.close()
            flash('Student added successfully!', 'success')
            return redirect(url_for('students'))
        except sqlite3.IntegrityError:
            flash('Roll number already exists.', 'danger')
    return render_template('student_form.html', action='Add', student=None)

@app.route('/students/edit/<int:sid>', methods=['GET', 'POST'])
@login_required
def edit_student(sid):
    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    if not student:
        conn.close()
        flash('Student not found.', 'danger')
        return redirect(url_for('students'))
    if request.method == 'POST':
        data = (request.form['name'], request.form['roll_no'], request.form['email'],
                request.form['phone'], request.form['course'], request.form['year'], sid)
        try:
            conn.execute("UPDATE students SET name=?,roll_no=?,email=?,phone=?,course=?,year=? WHERE id=?", data)
            conn.commit()
            flash('Student updated!', 'success')
        except sqlite3.IntegrityError:
            flash('Roll number already exists.', 'danger')
        conn.close()
        return redirect(url_for('students'))
    conn.close()
    return render_template('student_form.html', action='Edit', student=student)

@app.route('/students/delete/<int:sid>', methods=['POST'])
@login_required
def delete_student(sid):
    conn = get_db()
    conn.execute("DELETE FROM attendance WHERE student_id=?", (sid,))
    conn.execute("DELETE FROM students WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    flash('Student deleted.', 'info')
    return redirect(url_for('students'))

@app.route('/attendance', methods=['GET', 'POST'])
@login_required
def attendance():
    today = date.today().isoformat()
    sel_date = request.args.get('date', today)
    conn = get_db()
    if request.method == 'POST':
        sel_date = request.form.get('att_date', today)
        students_list = conn.execute("SELECT id FROM students").fetchall()
        for s in students_list:
            status = request.form.get(f'status_{s["id"]}', 'Absent')
            conn.execute(
                "INSERT OR REPLACE INTO attendance (student_id, date, status) VALUES (?,?,?)",
                (s['id'], sel_date, status))
        conn.commit()
        flash(f'Attendance saved for {sel_date}!', 'success')
    students_list = conn.execute("SELECT * FROM students ORDER BY name").fetchall()
    existing = {row['student_id']: row['status'] for row in
                conn.execute("SELECT student_id, status FROM attendance WHERE date=?", (sel_date,)).fetchall()}
    conn.close()
    return render_template('attendance.html', students=students_list, existing=existing, sel_date=sel_date)

@app.route('/attendance/report')
@login_required
def att_report():
    conn = get_db()
    report = conn.execute('''
        SELECT s.name, s.roll_no, s.course,
               COUNT(CASE WHEN a.status="Present" THEN 1 END) AS present,
               COUNT(CASE WHEN a.status="Absent"  THEN 1 END) AS absent,
               COUNT(a.id) AS total
        FROM students s
        LEFT JOIN attendance a ON s.id = a.student_id
        GROUP BY s.id ORDER BY s.name
    ''').fetchall()
    conn.close()
    return render_template('att_report.html', report=report)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
