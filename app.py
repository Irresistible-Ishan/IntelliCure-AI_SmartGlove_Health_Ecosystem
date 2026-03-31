import time
import random
import os
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO
import ollama
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")


# --- DYNAMIC PATIENT PROFILE ---
patient = {"age": 19, "gender": "Male", "bmi": 22.9, "hypertension": 0}
RECOVERY_CEILING = 140 

def update_math_thresholds():
    global RECOVERY_CEILING
    max_hr = 220 - patient['age']
    multiplier = 0.60 if patient['hypertension'] == 1 else 0.70
    RECOVERY_CEILING = max_hr * multiplier
    print(f"Recalibrated Ceiling: {RECOVERY_CEILING} BPM")

# Run once on startup
update_math_thresholds()

# --- STATE MANAGEMENT & HISTORY ---
history = {'hr': [], 'temp': []}
overrides = {"hr": None, "spo2": None, "temp": None}
state = "NORMAL"
last_diagnosis = "Vitals Stable"

def analyze_vitals_math(hr, spo2, temp):
    flags = {'hr': False, 'spo2': False, 'temp': False}
    danger = False
    diagnosis = "Vitals Stable"

    if spo2 < 94:
        danger = True
        flags['spo2'] = True
        diagnosis = f"Hypoxia Warning: SpO2 ({int(spo2)}%) is critically low."
    
    elif hr > RECOVERY_CEILING:
        danger = True
        flags['hr'] = True
        diagnosis = f"Exertion Alert: HR ({int(hr)}) exceeds safe ceiling."
    
    elif len(history['hr']) >= 5:
        avg_old_hr = sum(history['hr'][:5]) / 5
        avg_old_temp = sum(history['temp'][:5]) / 5
        if hr > (avg_old_hr * 1.15) and temp < (avg_old_temp - 0.3):
            danger = True
            flags['hr'] = True
            flags['temp'] = True
            diagnosis = "Anxiety/Stress: Sudden HR spike and Temp drop detected."

    return danger, diagnosis, flags


# 🔥 CHANGED: USING OLLAMA (LOCAL AI)
def get_ai_tip(prompt):
    try:
        response = ollama.generate(
            model='mistral:7b',
            prompt=prompt
        )
        return response['response'][:60]   # trim for LED
    except Exception as e:
        print("Ollama Error:", e)
        return "Stay calm and rest. vitals abnormal"


# --- FLASK ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/history_data')
def history_data():
    mock_history = [
        {"date": "Mar 09, 2026", "hr_avg": 73, "spo2_avg": 98, "temp_avg": 36.6, "summary": "Vitals excellent."},
        {"date": "Mar 08, 2026", "hr_avg": 78, "spo2_avg": 97, "temp_avg": 36.8, "summary": "Slight HR rise."},
        {"date": "Mar 07, 2026", "hr_avg": 71, "spo2_avg": 99, "temp_avg": 36.5, "summary": "Perfect vitals."},
        {"date": "Mar 06, 2026", "hr_avg": 85, "spo2_avg": 96, "temp_avg": 37.1, "summary": "Mild exertion."},
    ]
    return jsonify(mock_history)


@app.route('/data', methods=['POST'])
def receive_data():
    global state, history, last_diagnosis
    data = request.json
    
    # Hardware Bypass
    data['spo2'] = 98 + random.choice([0, 0, 1])

    # Overrides
    for key in overrides:
        if overrides[key] is not None: 
            if key == 'hr': data[key] = overrides[key] + random.uniform(-2, 2)
            if key == 'temp': data[key] = overrides[key] + random.uniform(-0.1, 0.1)
            if key == 'spo2': data[key] = overrides[key] + random.choice([0, 1])

    # History
    history['hr'].append(data['hr'])
    history['temp'].append(data['temp'])
    if len(history['hr']) > 10:
        history['hr'].pop(0)
        history['temp'].pop(0)

    # Math Engine
    danger, diagnosis, flags = analyze_vitals_math(data['hr'], data['spo2'], data['temp'])
    data['alerts'] = flags 

    current_ai_msg = ""
    
    if danger:
        if state == "NORMAL" or last_diagnosis != diagnosis:
            state = "ALERTED"
            last_diagnosis = diagnosis
            socketio.emit('system_alert', {'msg': diagnosis}) 
            
            prompt = f"HR {int(data['hr'])}, SPO2 {int(data['spo2'])}, TEMP {data['temp']:.1f}. Give short advice."
            ai_tip = get_ai_tip(prompt)
            
            socketio.emit('ai_update', {'msg': ai_tip, 'type': 'danger'})
            current_ai_msg = ai_tip

    else:
        if state == "ALERTED":
            state = "NORMAL"
            last_diagnosis = "Vitals Stable"
            socketio.emit('system_alert', {'msg': "Vitals back to normal"})
            socketio.emit('ai_update', {'msg': "Waiting...", 'type': 'safe'})
            current_ai_msg = "Vitals Stable"

    if current_ai_msg == "":
        current_ai_msg = diagnosis

    # 🔥 KEEP FRONTEND LIVE
    socketio.emit('update', data)

    # 🔥 NEW: SEND COMBINED STRING TO ARDUINO
    display_msg = f"HR:{int(data['hr'])} S:{int(data['spo2'])}% T:{round(data['temp'],1)}"

    if current_ai_msg:
        display_msg += " | " + current_ai_msg[:40]

    return display_msg


# --- SOCKET.IO EVENTS ---

@socketio.on('chat_msg')
def handle_chat(data):
    prompt = f"HR {int(data['vitals']['hr'])}, SPO2 {int(data['vitals']['spo2'])}, TEMP {data['vitals']['temp']}. Answer: {data['text']}"
    reply = get_ai_tip(prompt)
    socketio.emit('chat_reply', {'msg': reply})


@socketio.on('set_override')
def handle_override(data):
    overrides[data['type']] = data['val']


@socketio.on('update_profile')
def handle_profile_update(data):
    global patient
    patient['age'] = int(data['age'])
    patient['gender'] = data['gender']
    patient['bmi'] = float(data['bmi'])
    patient['hypertension'] = int(data['hypertension'])
    update_math_thresholds()
    socketio.emit('system_alert', {'msg': "Profile Updated"})


# --- RUN ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)