import sqlite3
import random
import os
import pytz
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

app = Flask(__name__)

# --- CONFIGURATION ---
app.secret_key = "super_secret_key_change_this" 
ADMIN_PASSWORD = "admin123"                     
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'library.db')

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
        cursor.execute('''CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, event_type TEXT, user_type TEXT, occupancy INTEGER)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        
        cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('system_status', '1'))
        cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('total_capacity', '50'))

        cursor.execute('SELECT count(*) FROM status')
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO status (id, available_seats) VALUES (1, 50)')
        
        staff_list = [('CARD-001', 'Mr. Perera'), ('CARD-002', 'Ms. Silva'), ('CARD-003', 'Dr. Jayantha')]
        for uid, name in staff_list:
            cursor.execute('INSERT OR IGNORE INTO staff (uid, name, is_present, last_seen) VALUES (?, ?, 0, ?)', (uid, name, get_sl_time()))
        conn.commit()

init_db()

# --- HELPER FUNCTIONS ---
def get_seats():
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute('SELECT available_seats FROM status WHERE id=1').fetchone()[0]

def get_total_capacity():
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute('SELECT value FROM settings WHERE key="total_capacity"').fetchone()
        return int(row[0]) if row else 50

def get_system_status():
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute('SELECT value FROM settings WHERE key="system_status"').fetchone()
        return int(row[0]) if row else 1

# --- PUBLIC ROUTES ---
@app.route('/')
def dashboard():
    seats = get_seats()
    total = get_total_capacity()
    occupancy = max(0, total - seats)
    system_status = get_system_status()
    
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        
        # 🟢 CHANGED: Fetch message AND created_at
        row = conn.execute('SELECT message, created_at FROM announcements ORDER BY id DESC LIMIT 1').fetchone()
        announcement = row[0] if row else None
        ann_time = row[1] if row else None
        
        logs = conn.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 50').fetchall()
        staff_count = conn.execute('SELECT count(*) FROM staff WHERE is_present = 1').fetchone()[0]
        res_count = conn.execute('SELECT count(*) FROM reservations WHERE is_used = 0').fetchone()[0]

    # Pass 'ann_time' to template
    return render_template('dashboard.html', seats=seats, announcement=announcement, ann_time=ann_time, 
                           logs=logs, system_status=system_status, occupancy=occupancy, 
                           staff_count=staff_count, res_count=res_count)

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
        
        elif 'update_capacity' in request.form:
            new_total = int(request.form.get('total_capacity'))
            current_seats = get_seats()
            old_total = get_total_capacity()
            people_inside = max(0, old_total - current_seats)
            new_available = max(0, new_total - people_inside)
            
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute('UPDATE settings SET value = ? WHERE key="total_capacity"', (new_total,))
                conn.execute('UPDATE status SET available_seats = ? WHERE id=1', (new_available,))
            msg = f"✅ Capacity updated to {new_total}. (People inside kept at {people_inside})"

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

        elif 'toggle_status' in request.form:
            current = get_system_status()
            new_val = '0' if current == 1 else '1'
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute('UPDATE settings SET value = ? WHERE key="system_status"', (new_val,))
            msg = "✅ System Status Updated"

    seats = get_seats()
    total_capacity = get_total_capacity() 
    system_status = get_system_status() 

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        all_staff = conn.execute('SELECT * FROM staff').fetchall()
        all_reservations = conn.execute('SELECT * FROM reservations ORDER BY created_at DESC').fetchall()
        all_announcements = conn.execute('SELECT * FROM announcements ORDER BY id DESC').fetchall()

    return render_template('admin_panel.html', seats=seats, total_capacity=total_capacity, staff=all_staff, reservations=all_reservations, announcements=all_announcements, msg=msg, system_status=system_status)

@app.route('/admin/edit_staff/<uid>', methods=['GET', 'POST'])
def edit_staff(uid):
    if 'is_admin' not in session: return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        new_name = request.form.get('name')
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('UPDATE staff SET name = ? WHERE uid = ?', (new_name, uid))
        return redirect(url_for('admin_panel'))

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        person = conn.execute('SELECT * FROM staff WHERE uid = ?', (uid,)).fetchone()

    if not person: return "Staff member not found", 404
    return render_template('edit_staff.html', person=person)

@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    return redirect(url_for('dashboard'))

# --- IOT ROUTE ---
@app.route('/update_data', methods=['POST'])
def update_data():
    try:
        data = request.get_json(force=True, silent=True)
        if not data: return jsonify({"status": "error", "message": "No JSON data"}), 400
        
        occupancy = int(data.get('occupancy', 0)) 
        event = data.get('event', "UPDATE")
        user = data.get('user', "STUDENT")
        uid = data.get('uid', None)
        
        now = get_sl_time()
        total_limit = get_total_capacity() 

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()

            if uid:
                is_present = 1 if event == "ENTRY" else 0
                cursor.execute('UPDATE staff SET is_present = ?, last_seen = ? WHERE uid = ?', (is_present, now, uid))
                cursor.execute('SELECT name FROM staff WHERE uid = ?', (uid,))
                if cursor.fetchone(): user = "STAFF"

            if user != "STAFF":
                new_available = max(0, total_limit - occupancy)
                cursor.execute('UPDATE status SET available_seats = ? WHERE id=1', (new_available,))
            
            cursor.execute("INSERT INTO logs (timestamp, event_type, user_type, occupancy) VALUES (?, ?, ?, ?)", (now, event, user, occupancy))
            conn.commit()

        print(f"✅ SENSOR: {event} | Occ: {occupancy}")
        return jsonify({"status": "success"}), 200

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- API ROUTES ---

@app.route('/api/dashboard_stats')
def get_dashboard_stats():
    # 1. Fetch Basic Data
    seats = get_seats()
    total = get_total_capacity()
    occupancy = max(0, total - seats)
    system_status = get_system_status()
    
    # 2. Fetch DB Counts & Announcement
    with sqlite3.connect(DB_FILE) as conn:
        staff_count = conn.execute('SELECT count(*) FROM staff WHERE is_present = 1').fetchone()[0]
        res_count = conn.execute('SELECT count(*) FROM reservations WHERE is_used = 0').fetchone()[0]
        
        # 🟢 CHANGED: Fetch message AND created_at
        row = conn.execute('SELECT message, created_at FROM announcements ORDER BY id DESC LIMIT 1').fetchone()
        announcement = row[0] if row else None
        ann_time = row[1] if row else None
    
    return jsonify({
        "seats": seats,
        "occupancy": occupancy,
        "staff": staff_count,
        "reservations": res_count,
        "system_status": system_status,
        "announcement": announcement,
        "announcement_time": ann_time # 🟢 NEW FIELD
    })

@app.route('/api/admin_stats')
def get_admin_stats():
    if 'is_admin' not in session: return jsonify({}), 403
    seats = get_seats()
    total = get_total_capacity()
    status = get_system_status()
    return jsonify({
        "seats": seats,
        "total_capacity": total,
        "system_status": status
    })

@app.route('/api/get_staff_table')
def get_staff_table():
    if 'is_admin' not in session: return "Access Denied", 403
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        all_staff = conn.execute('SELECT * FROM staff').fetchall()
    return render_template('_staff_rows.html', staff=all_staff)

@app.route('/api/get_reservations_table')
def get_reservations_table():
    if 'is_admin' not in session: return "Access Denied", 403
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        reservations = conn.execute('SELECT * FROM reservations ORDER BY created_at DESC').fetchall()
    return render_template('_table_rows.html', reservations=reservations)

@app.route('/api/get_seat_count')
def get_seat_count():
    if 'is_admin' not in session: return "Access Denied", 403
    return str(get_seats())

# --- SIMULATOR ---
@app.route('/simulator')
def simulator():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SeatIdle Simulator</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Inter', sans-serif; background: #111827; color: white; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
            .container { background: #1f2937; padding: 40px; border-radius: 20px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); text-align: center; width: 350px; }
            h1 { margin-bottom: 5px; color: #60a5fa; }
            h3 { margin-top: 0; color: #9ca3af; font-weight: 400; font-size: 14px; margin-bottom: 30px; }
            .counter-box { background: #374151; padding: 20px; border-radius: 12px; margin-bottom: 30px; }
            .count { font-size: 60px; font-weight: 800; }
            .label { color: #9ca3af; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
            .btn-group { display: flex; gap: 10px; margin-bottom: 30px; }
            button { flex: 1; padding: 15px; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; transition: 0.1s; }
            .btn-entry { background: #10b981; color: white; }
            .btn-exit { background: #ef4444; color: white; }
            .btn-rfid { background: #8b5cf6; color: white; width: 100%; margin-top: 5px;}
            button:active { transform: scale(0.96); opacity: 0.9; }
            input { width: 100%; padding: 12px; border-radius: 8px; border: 1px solid #4b5563; background: #374151; color: white; margin-bottom: 10px; box-sizing: border-box; text-align: center;}
            .section-title { text-align: left; color: #d1d5db; font-weight: 600; margin-bottom: 10px; font-size: 14px; }
            #status { margin-top: 20px; color: #6b7280; font-family: monospace; font-size: 12px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Virtual ESP32</h1>
            <h3>Hardware Simulator</h3>

            <div class="section-title">👥 CROWD SENSORS</div>
            <div class="counter-box">
                <div class="count" id="count-display">0</div>
                <div class="label">People Inside</div>
            </div>
            <div class="btn-group">
                <button class="btn-entry" onclick="updateCount(1)">+ ENTRY</button>
                <button class="btn-exit" onclick="updateCount(-1)">- EXIT</button>
            </div>

            <div class="section-title">💳 RFID READER (STAFF)</div>
            <input type="text" id="rfid-input" placeholder="Scan Card (e.g. CARD-001)">
            <div class="btn-group">
                <button class="btn-rfid" onclick="scanRFID('ENTRY')">Scan Entry</button>
                <button class="btn-rfid" style="background:#6366f1" onclick="scanRFID('EXIT')">Scan Exit</button>
            </div>

            <div id="status">Ready to simulate...</div>
        </div>

        <script>
            let localCount = 0;

            function updateCount(change) {
                localCount += change;
                if(localCount < 0) localCount = 0;
                document.getElementById('count-display').innerText = localCount;
                let eventType = change > 0 ? "ENTRY" : "EXIT";
                sendData(localCount, eventType, "STUDENT", null);
            }

            function scanRFID(eventType) {
                let uid = document.getElementById('rfid-input').value;
                if(!uid) { alert("Please enter a Card ID!"); return; }
                sendData(localCount, eventType, "STAFF", uid);
            }

            function sendData(occ, evt, usr, uid) {
                document.getElementById('status').innerText = "Sending " + evt + "...";
                
                fetch('/update_data', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        occupancy: occ,
                        event: evt,
                        user: usr,
                        uid: uid
                    })
                })
                .then(r => r.json())
                .then(d => {
                    document.getElementById('status').innerText = "✅ Sent: " + evt + " | " + (uid ? uid : "Student");
                    if(d.status === 'error') alert(d.message);
                })
                .catch(e => {
                    document.getElementById('status').innerText = "❌ Error";
                    console.error(e);
                });
            }
        </script>
    </body>
    </html>
    """

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)