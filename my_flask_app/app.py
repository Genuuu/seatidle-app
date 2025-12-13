import sqlite3
import random
import os
import pytz
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

app = Flask(__name__)

# --- CONFIGURATION ---
app.secret_key = "super_secret_key_change_this" # Change this for security
ADMIN_PASSWORD = "admin123"                     # Change your admin password here
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'library.db')
TOTAL_SEATS = 50

# --- TIMEZONE HELPER ---
def get_sl_time():
    sl_timezone = pytz.timezone('Asia/Colombo')
    return datetime.now(sl_timezone).strftime("%Y-%m-%d %H:%M:%S")

# --- DATABASE SETUP ---
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS status (id INTEGER PRIMARY KEY, available_seats INTEGER)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS reservations (otp TEXT PRIMARY KEY, name TEXT, res_date TEXT, time_slot TEXT, created_at TEXT, is_used INTEGER)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS staff (uid TEXT PRIMARY KEY, name TEXT, is_present INTEGER, last_seen TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS announcements (id INTEGER PRIMARY KEY, message TEXT, created_at TEXT)''')

        cursor.execute('SELECT count(*) FROM status')
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO status (id, available_seats) VALUES (1, ?)', (TOTAL_SEATS,))
        
        # Initial Test Staff
        staff_list = [('CARD-001', 'Mr. Perera'), ('CARD-002', 'Ms. Silva'), ('CARD-003', 'Dr. Jayantha')]
        for uid, name in staff_list:
            cursor.execute('INSERT OR IGNORE INTO staff (uid, name, is_present, last_seen) VALUES (?, ?, 0, ?)', (uid, name, get_sl_time()))
        conn.commit()

init_db()

# --- HELPER FUNCTIONS ---
def get_seats():
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute('SELECT available_seats FROM status WHERE id=1').fetchone()[0]

def update_seats(change):
    with sqlite3.connect(DB_FILE) as conn:
        current = get_seats()
        new_count = max(0, min(TOTAL_SEATS, current + change))
        conn.execute('UPDATE status SET available_seats = ? WHERE id=1', (new_count,))

# --- PUBLIC ROUTES ---
@app.route('/')
def dashboard():
    seats = get_seats()
    announcement = None
    with sqlite3.connect(DB_FILE) as conn:
        # Show ONLY the single newest announcement
        row = conn.execute('SELECT message FROM announcements ORDER BY id DESC LIMIT 1').fetchone()
        if row: announcement = row[0]

    return render_template('dashboard.html', seats=seats, announcement=announcement)

@app.route('/staff')
def staff_view():
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        active_staff = conn.execute('SELECT * FROM staff WHERE is_present = 1').fetchall()
    return render_template('staff.html', staff=active_staff)

@app.route('/reservations', methods=['GET', 'POST'])
def reservations_view():
    new_otp = None
    message = None
    if request.method == 'POST':
        if 'create_booking' in request.form:
            name = request.form.get('name')
            date = request.form.get('date')
            time = request.form.get('time')
            new_otp = str(random.randint(1000, 9999))
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute('INSERT INTO reservations VALUES (?, ?, ?, ?, ?, 0)', (new_otp, name, date, time, get_sl_time()))
        elif 'cancel_booking' in request.form:
            otp = request.form.get('otp_check')
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM reservations WHERE otp = ? AND is_used = 0', (otp,))
                if cursor.fetchone():
                    cursor.execute('DELETE FROM reservations WHERE otp = ?', (otp,))
                    conn.commit()
                    message = "✅ Reservation cancelled successfully."
                else: message = "❌ Error: Invalid OTP or booking already used."

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        bookings = conn.execute('SELECT * FROM reservations WHERE is_used = 0 ORDER BY created_at DESC').fetchall()
    return render_template('reservations.html', bookings=bookings, new_otp=new_otp, message=message)

# --- ADMIN ROUTES ---

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if 'is_admin' in session: return redirect(url_for('admin_panel'))
    error = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('admin_panel'))
        else: error = "Invalid Password"
    return render_template('admin_login.html', error=error)

@app.route('/admin/panel', methods=['GET', 'POST'])
def admin_panel():
    if 'is_admin' not in session: return redirect(url_for('admin_login'))
    msg = None
    
    if request.method == 'POST':
        if 'post_announcement' in request.form:
            text = request.form.get('message')
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute('INSERT INTO announcements (message, created_at) VALUES (?, ?)', (text, get_sl_time()))
            msg = "📢 Announcement Posted"
        
        elif 'delete_announcement' in request.form:
            ann_id = request.form.get('ann_id')
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute('DELETE FROM announcements WHERE id = ?', (ann_id,))
            msg = "🗑️ Announcement Deleted"

        elif 'reset_seats' in request.form:
            target = int(request.form.get('seat_count'))
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute('UPDATE status SET available_seats = ? WHERE id=1', (target,))
            msg = f"✅ Seats reset to {target}"
        
        elif 'delete_staff' in request.form:
            uid = request.form.get('staff_uid')
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute('DELETE FROM staff WHERE uid = ?', (uid,))
            msg = "🗑️ Staff deleted."

        elif 'add_staff' in request.form:
            uid = request.form.get('new_uid')
            name = request.form.get('new_name')
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute('INSERT OR REPLACE INTO staff (uid, name, is_present, last_seen) VALUES (?, ?, 0, ?)', (uid, name, get_sl_time()))
            msg = f"✅ Added {name}"
            
        elif 'delete_res' in request.form:
            otp = request.form.get('res_otp')
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute('DELETE FROM reservations WHERE otp = ?', (otp,))
            msg = "🗑️ Reservation deleted."

    # Fetch All Data
    seats = get_seats()
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        all_staff = conn.execute('SELECT * FROM staff').fetchall()
        all_reservations = conn.execute('SELECT * FROM reservations ORDER BY created_at DESC').fetchall()
        all_announcements = conn.execute('SELECT * FROM announcements ORDER BY id DESC').fetchall()

    return render_template('admin_panel.html', seats=seats, staff=all_staff, reservations=all_reservations, announcements=all_announcements, msg=msg)

@app.route('/admin/edit_staff/<uid>', methods=['GET', 'POST'])
def edit_staff(uid):
    if 'is_admin' not in session: return redirect(url_for('admin_login'))
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        person = conn.execute('SELECT * FROM staff WHERE uid = ?', (uid,)).fetchone()
    if request.method == 'POST':
        new_name = request.form.get('new_name')
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('UPDATE staff SET name = ? WHERE uid = ?', (new_name, uid))
        return redirect(url_for('admin_panel'))
    return render_template('edit_staff.html', person=person)

@app.route('/admin/edit_announcement/<int:id>', methods=['GET', 'POST'])
def edit_announcement(id):
    if 'is_admin' not in session: return redirect(url_for('admin_login'))
    
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        ann = conn.execute('SELECT * FROM announcements WHERE id = ?', (id,)).fetchone()

    if request.method == 'POST':
        new_text = request.form.get('message')
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('UPDATE announcements SET message = ? WHERE id = ?', (new_text, id))
        return redirect(url_for('admin_panel'))
        
    return render_template('edit_announcement.html', ann=ann)

@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    return redirect(url_for('dashboard'))

# --- API ROUTES (ESP32 & AJAX) ---

@app.route('/api/get_reservations_table')
def get_reservations_table():
    if 'is_admin' not in session: return "Access Denied", 403
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT * FROM reservations ORDER BY created_at DESC').fetchall()
    return render_template('_table_rows.html', reservations=rows)

@app.route('/api/staff_entry', methods=['GET'])
def staff_entry():
    uid = request.args.get('uid')
    if not uid: return "ERROR_NO_UID"
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT name, is_present FROM staff WHERE uid = ?', (uid,))
        person = cursor.fetchone()
        if person:
            new_status = 0 if person[1] == 1 else 1
            cursor.execute('UPDATE staff SET is_present = ?, last_seen = ? WHERE uid = ?', (new_status, get_sl_time(), uid))
            conn.commit()
            return f"Updated {person[0]}"
        else:
            cursor.execute('INSERT INTO staff (uid, name, is_present, last_seen) VALUES (?, ?, 1, ?)', (uid, "Unknown User", 1, get_sl_time()))
            conn.commit()
            return "UNKNOWN_CARD_ADDED"

@app.route('/api/verify_otp', methods=['GET'])
def verify_otp():
    code = request.args.get('code')
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT is_used FROM reservations WHERE otp = ?', (code,))
        row = cursor.fetchone()
        if row and row[0] == 0:
            cursor.execute('UPDATE reservations SET is_used = 1 WHERE otp = ?', (code,))
            conn.commit()
            update_seats(-1)
            return "ACCESS_GRANTED"
        return "ACCESS_DENIED"

@app.route('/api/update_count', methods=['GET'])
def sensor_update():
    action = request.args.get('action')
    if action == 'enter': update_seats(-1)
    elif action == 'exit': update_seats(1)
    return "OK"

if __name__ == '__main__':
    app.run(debug=True, port=5000)