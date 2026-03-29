import time
import random
import os
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize OpenAI client for OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1", 
    api_key=os.getenv("OPENROUTERAPIKEY")
)

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
    """Deterministic Math Engine for Tri-Factor Triage"""
    flags = {'hr': False, 'spo2': False, 'temp': False}
    danger = False
    diagnosis = "Vitals Stable"

    # 1. Hypoxemia Check
    if spo2 < 94:
        danger = True
        flags['spo2'] = True
        diagnosis = f"Hypoxia Warning: SpO2 ({int(spo2)}%) is critically low."
    
    # 2. Cardiac Exertion Check
    elif hr > RECOVERY_CEILING:
        danger = True
        flags['hr'] = True
        diagnosis = f"Exertion Alert: HR ({int(hr)}) exceeds safe ceiling."
    
    # 3. Acute Sympathetic Arousal (Cold Sweat/Anxiety) Check
    elif len(history['hr']) >= 5:
        avg_old_hr = sum(history['hr'][:5]) / 5
        avg_old_temp = sum(history['temp'][:5]) / 5
        if hr > (avg_old_hr * 1.15) and temp < (avg_old_temp - 0.3):
            danger = True
            flags['hr'] = True
            flags['temp'] = True
            diagnosis = "Anxiety/Stress: Sudden HR spike and Temp drop detected."

    return danger, diagnosis, flags

def get_ai_tip(prompt):
    """Fetches localized medical tips from the LLM"""
    try:
        response = client.chat.completions.create(
            model="arcee-ai/trinity-large-preview:free",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Connection Error: {e}")
        return "System error: Please rest and sit down."

# --- FLASK ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/history_data')
def history_data():
    """Serves mock historical data for the History Tab"""
    mock_history = [
        {"date": "Mar 09, 2026", "hr_avg": 73, "spo2_avg": 98, "temp_avg": 36.6, "summary": "Vitals excellent. Heart and lungs operating optimally in safe ranges."},
        {"date": "Mar 08, 2026", "hr_avg": 78, "spo2_avg": 97, "temp_avg": 36.8, "summary": "Slightly elevated HR in the afternoon, but recovered normally. Good overall health."},
        {"date": "Mar 07, 2026", "hr_avg": 71, "spo2_avg": 99, "temp_avg": 36.5, "summary": "Perfect resting vitals. No anomalies detected."},
        {"date": "Mar 06, 2026", "hr_avg": 85, "spo2_avg": 96, "temp_avg": 37.1, "summary": "Minor temperature rise and HR exertion noted. Hydration recommended."},
    ]
    return jsonify(mock_history)

@app.route('/data', methods=['POST'])
def receive_data():
    global state, history, last_diagnosis
    data = request.json
    
    # Hardware Bypass: Force healthy SpO2 base due to sensor limitations
    data['spo2'] = 98 + random.choice([0, 0, 1])

    # Apply Developer Overrides with natural biological jitter
    for key in overrides:
        if overrides[key] is not None: 
            if key == 'hr': data[key] = overrides[key] + random.uniform(-2, 2)
            if key == 'temp': data[key] = overrides[key] + random.uniform(-0.1, 0.1)
            if key == 'spo2': data[key] = overrides[key] + random.choice([0, 1])

    # Maintain rolling 10-second history for math derivatives
    history['hr'].append(data['hr'])
    history['temp'].append(data['temp'])
    if len(history['hr']) > 10:
        history['hr'].pop(0)
        history['temp'].pop(0)

    # Execute Math Engine
    danger, diagnosis, flags = analyze_vitals_math(data['hr'], data['spo2'], data['temp'])
    data['alerts'] = flags 

    current_ai_msg = ""
    
    # State Machine: Only trigger AI API on state/diagnosis change to save tokens
    if danger:
        if state == "NORMAL" or last_diagnosis != diagnosis:
            state = "ALERTED"
            last_diagnosis = diagnosis
            socketio.emit('system_alert', {'msg': diagnosis}) 
            
            prompt = f"Patient ({patient['age']}{patient['gender'][0]}, BMI {patient['bmi']}, HTN:{patient['hypertension']}). Diagnosis: {diagnosis} Vitals: HR {int(data['hr'])}, SpO2 {int(data['spo2'])}%, Temp {data['temp']:.1f}C. Give 1 short actionable tip (15 words)."
            ai_tip = get_ai_tip(prompt)
            
            socketio.emit('ai_update', {'msg': ai_tip, 'type': 'danger'})
            current_ai_msg = ai_tip
    else:
        if state == "ALERTED":
            state = "NORMAL"
            last_diagnosis = "Vitals Stable"
            socketio.emit('system_alert', {'msg': f"Vitals returned to normal for {patient['age']} yr old profile."})
            socketio.emit('ai_update', {'msg': "Waiting for anomalies...", 'type': 'safe'})
            current_ai_msg = "Vitals Stable"

    # CRITICAL FIX FOR ARDUINO: Ensure we ALWAYS return a string to the LED Matrix
    if current_ai_msg == "":
        current_ai_msg = diagnosis

    # Push live updates to frontend dashboard
    socketio.emit('update', data)
    
    # Send string response back to Arduino HTTP Client
    return current_ai_msg 

# --- SOCKET.IO EVENT HANDLERS ---

@socketio.on('chat_msg')
def handle_chat(data):
    """Handles messages from the Live AI Chatbox"""
    prompt = f"Patient ({patient['age']}{patient['gender'][0]}, HTN:{patient['hypertension']}). Current Vitals: HR {int(data['vitals']['hr'])}, SpO2 {int(data['vitals']['spo2'])}%, Temp {data['vitals']['temp']:.1f}C. User asks: '{data['text']}'. Give a short medical response."
    reply = get_ai_tip(prompt)
    socketio.emit('chat_reply', {'msg': reply})

@socketio.on('set_override')
def handle_override(data):
    """Handles Dev Simulator Buttons"""
    overrides[data['type']] = data['val']

@socketio.on('update_profile')
def handle_profile_update(data):
    """Updates Patient Demographics and recalibrates Math Engine"""
    global patient
    patient['age'] = int(data['age'])
    patient['gender'] = data['gender']
    patient['bmi'] = float(data['bmi'])
    patient['hypertension'] = int(data['hypertension'])
    update_math_thresholds()
    socketio.emit('system_alert', {'msg': "Patient Profile Updated. Formulas recalibrated."})

if __name__ == '__main__':
    # Runs the server on all local interfaces on port 5000
    socketio.run(app, host='0.0.0.0', port=5000)