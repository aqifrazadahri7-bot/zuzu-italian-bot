from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
import google.generativeai as genai
import os
from dotenv import load_dotenv
import uuid

load_dotenv()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.environ.get("FLASK_SECRET", "zuzu-secret-change-this")

oauth = OAuth(app)
google_oauth = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

LEVEL_PROMPTS = {
    "A1": """You are Zuzu, a warm Italian tutor. The student is at A1 (absolute beginner) level.
- Use ONLY present tense of essere, avere, and common -ARE verbs.
- Vocabulary: numbers, colours, family, greetings, basic objects only.
- Keep sentences very short (max 8 words each).
- Add English translations in brackets after new words, e.g. "il gatto (the cat)".
- Be extremely encouraging — every attempt is a win.""",

    "A2": """You are Zuzu, a warm Italian tutor. The student is at A2 level.
- Grammar: present tense all verbs, basic passato prossimo, modal verbs, c'è/ci sono.
- Vocabulary: daily routine, food, travel, shopping, family, weather.
- Short to medium sentences. Introduce one new word per response with a translation.
- Be encouraging and patient.""",

    "B1": """You are Zuzu, a warm Italian tutor. The student is at B1 level.
- Grammar: passato prossimo, imperfetto, futuro semplice, condizionale, reflexives, comparatives, relative pronouns.
- Vocabulary: opinions, emotions, travel, health, media, culture, work.
- Natural sentences. Challenge with richer vocabulary.
- Correct mistakes clearly with grammar rule explanation.""",

    "B2": """You are Zuzu, a warm Italian tutor. The student is at B2 level.
- Grammar: full subjunctive, conditional perfect, passive voice, indirect speech, all tenses.
- Vocabulary: abstract topics, current events, idiomatic phrases, nuanced expressions.
- Speak naturally like a native. Full-length sentences.
- Push the student to express complex ideas. Precise, formal corrections."""
}

BASE_RULES = """

RESPONSE FORMAT — always use this exact structure:
---ITALIAN---
[Your Italian response — 2–4 sentences, always end with a question]

---CORRECTION---
[Corrections in English. If perfect, write: ✓ Perfect! No corrections needed.]

Always be warm and encouraging. Quote the mistake → show correct form → one-line rule.
If user writes in English: respond in Italian + add English translation in correction section."""

conversation_histories = {}


def build_prompt(level="B1"):
    return LEVEL_PROMPTS.get(level, LEVEL_PROMPTS["B1"]) + BASE_RULES


def get_model(level="B1"):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or api_key == "your_gemini_api_key_here":
        return None, "NO_KEY"
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=build_prompt(level)
    )
    return model, None


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ── Auth routes ──

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/auth/google')
def auth_google():
    redirect_uri = url_for('auth_callback', _external=True)
    return google_oauth.authorize_redirect(redirect_uri)


@app.route('/auth/callback')
def auth_callback():
    token = google_oauth.authorize_access_token()
    user_info = token.get('userinfo')
    if not user_info:
        return redirect(url_for('login'))
    session['user_id'] = user_info['sub']
    session['user_name'] = user_info.get('name', 'Learner')
    session['user_email'] = user_info.get('email', '')
    session['user_picture'] = user_info.get('picture', '')
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── Main app routes ──

@app.route('/')
@login_required
def index():
    return render_template('index.html',
        user_name=session.get('user_name', 'Learner'),
        user_picture=session.get('user_picture', ''),
        user_email=session.get('user_email', '')
    )


@app.route('/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json()
    user_message = data.get('message', '').strip()
    level = data.get('level', 'B1').upper()
    user_id = session.get('user_id', 'default')

    if not user_message:
        return jsonify({'error': 'Empty message'}), 400

    model, err = get_model(level)
    if err == 'NO_KEY':
        return jsonify({'no_key': True}), 200
    if err:
        return jsonify({'error': err}), 500

    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    history = conversation_histories[user_id]
    gemini_history = [
        {'role': 'user' if m['role'] == 'user' else 'model', 'parts': [m['content']]}
        for m in history[-20:]
    ]

    chat_session = model.start_chat(history=gemini_history)
    response = chat_session.send_message(user_message)
    reply = response.text

    conversation_histories[user_id].append({'role': 'user', 'content': user_message})
    conversation_histories[user_id].append({'role': 'assistant', 'content': reply})

    italian_part = correction_part = ''
    if '---ITALIAN---' in reply and '---CORRECTION---' in reply:
        parts = reply.split('---CORRECTION---')
        italian_part = parts[0].replace('---ITALIAN---', '').strip()
        correction_part = parts[1].strip() if len(parts) > 1 else ''
    else:
        italian_part = reply

    return jsonify({'italian': italian_part, 'correction': correction_part})


@app.route('/reset', methods=['POST'])
@login_required
def reset():
    user_id = session.get('user_id', 'default')
    conversation_histories.pop(user_id, None)
    return jsonify({'status': 'reset'})


if __name__ == '__main__':
    app.run(debug=True, port=5050)
