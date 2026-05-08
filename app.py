from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
import google.generativeai as genai
import os, json
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
user_progress = {}   # user_id -> {day: int, level: str, completed_days: list}
_api_key_override = ""

BOOKS = [
    {"id":"a1-famiglia","level":"A1","emoji":"👨‍👩‍👧","title":"La Mia Famiglia","subtitle":"Meet Marco and his family","words":120,"paragraphs":[{"italian":"Mi chiamo Marco. Ho ventotto anni. Sono italiano e abito a Milano.","english":"My name is Marco. I am twenty-eight years old. I am Italian and I live in Milan."},{"italian":"La mia famiglia è grande. Ho un padre, una madre, una sorella e un fratello. Mio padre si chiama Antonio. Ha cinquantacinque anni ed è medico. Mia madre si chiama Lucia. Ha cinquantadue anni ed è insegnante.","english":"My family is big. I have a father, a mother, a sister and a brother. My father's name is Antonio. He is fifty-five years old and is a doctor. My mother's name is Lucia. She is fifty-two years old and is a teacher."},{"italian":"Mia sorella si chiama Sofia. Ha venticinque anni. È studentessa universitaria. Mio fratello si chiama Luca. Ha sedici anni ed è ancora a scuola.","english":"My sister's name is Sofia. She is twenty-five years old. She is a university student. My brother's name is Luca. He is sixteen years old and is still at school."},{"italian":"Noi abitiamo insieme in un appartamento grande nel centro di Milano. Siamo una famiglia felice. Il sabato sera mangiamo insieme la pizza. È la nostra tradizione!","english":"We live together in a big apartment in the centre of Milan. We are a happy family. On Saturday evenings we eat pizza together. It is our tradition!"}],"vocab":{"famiglia":"family","padre":"father","madre":"mother","sorella":"sister","fratello":"brother","medico":"doctor","insegnante":"teacher","studentessa":"female student","insieme":"together","felice":"happy","tradizione":"tradition","abito":"I live"},"questions":[{"q":"Dove abita Marco?","options":["A Roma","A Milano","A Napoli","A Firenze"],"correct":1,"explanation":"Marco abita a Milano."},{"q":"Quanti anni ha la sorella di Marco?","options":["16","25","28","52"],"correct":1,"explanation":"Sofia ha venticinque anni."},{"q":"Che lavoro fa il padre di Marco?","options":["Insegnante","Avvocato","Medico","Cuoco"],"correct":2,"explanation":"Antonio è medico."},{"q":"Cosa mangiano insieme il sabato sera?","options":["Pasta","Risotto","Pizza","Gelato"],"correct":2,"explanation":"Il sabato sera mangiano la pizza insieme."}]},
    {"id":"a1-bar","level":"A1","emoji":"☕","title":"Al Bar","subtitle":"A morning at the Italian café","words":110,"paragraphs":[{"italian":"Ogni mattina Anna va al bar vicino a casa sua. Il bar si chiama 'Bar Roma'. È un bar piccolo ma molto bello.","english":"Every morning Anna goes to the bar near her house. The bar is called 'Bar Roma'. It is a small but very beautiful bar."},{"italian":"Il barista si chiama Giovanni. È un uomo simpatico e allegro. Giovanni conosce Anna bene. Quando lei arriva, dice sempre: 'Ciao Anna! Il solito?'","english":"The barman's name is Giovanni. He is a friendly and cheerful man. Giovanni knows Anna well. When she arrives, he always says: 'Hi Anna! The usual?'"},{"italian":"Anna ordina sempre un cappuccino e un cornetto alla crema. Il cappuccino è caldo e buono. Il cornetto è fresco. Anna mangia il cornetto lentamente e beve il caffè.","english":"Anna always orders a cappuccino and a cream croissant. The cappuccino is hot and good. The croissant is fresh. Anna eats the croissant slowly and drinks the coffee."},{"italian":"Al bar ci sono anche altri clienti. Alcuni leggono il giornale. Altri parlano con gli amici. Il bar è un posto importante nella vita italiana.","english":"At the bar there are also other customers. Some read the newspaper. Others talk with friends. The bar is an important place in Italian life."}],"vocab":{"bar":"café/bar","barista":"barman/barista","cappuccino":"cappuccino","cornetto":"croissant","caldo":"hot","fresco":"fresh","simpatico":"friendly/nice","clienti":"customers","giornale":"newspaper","mattina":"morning","solito":"usual","allegro":"cheerful"},"questions":[{"q":"Come si chiama il bar?","options":["Bar Milano","Bar Roma","Bar Italia","Bar Venezia"],"correct":1,"explanation":"Il bar si chiama 'Bar Roma'."},{"q":"Cosa ordina sempre Anna?","options":["Caffè e brioche","Cappuccino e cornetto","Tè e biscotti","Succo e toast"],"correct":1,"explanation":"Anna ordina un cappuccino e un cornetto alla crema."},{"q":"Come si chiama il barista?","options":["Marco","Antonio","Giovanni","Luca"],"correct":2,"explanation":"Il barista si chiama Giovanni."}]},
    {"id":"a1-mercato","level":"A1","emoji":"🥦","title":"Al Mercato","subtitle":"Shopping at the Italian market","words":105,"paragraphs":[{"italian":"Ogni venerdì la signora Rossi va al mercato. Il mercato è in piazza centrale. Ci sono molti venditori con frutta, verdura, pane e formaggi.","english":"Every Friday Mrs Rossi goes to the market. The market is in the central square. There are many sellers with fruit, vegetables, bread and cheeses."},{"italian":"La signora Rossi compra sempre le mele, le arance e i pomodori. Vuole anche del pane fresco. Il pane del mercato è molto buono.","english":"Mrs Rossi always buys apples, oranges and tomatoes. She also wants some fresh bread. The market bread is very good."},{"italian":"Il venditore di frutta si chiama Mario. Lui ha la frutta più bella del mercato. 'Quanto costano le mele?' chiede la signora Rossi. 'Due euro al chilo!' risponde Mario.","english":"The fruit seller's name is Mario. He has the most beautiful fruit in the market. 'How much do the apples cost?' asks Mrs Rossi. 'Two euros per kilo!' replies Mario."},{"italian":"La signora Rossi compra due chili di mele. Paga e dice 'Grazie, arrivederci!' Il mercato è finito alle due del pomeriggio.","english":"Mrs Rossi buys two kilos of apples. She pays and says 'Thank you, goodbye!' The market finishes at two in the afternoon."}],"vocab":{"mercato":"market","venditori":"sellers","frutta":"fruit","verdura":"vegetables","pane":"bread","mele":"apples","pomodori":"tomatoes","quanto costa":"how much does it cost","chilo":"kilogram","piazza":"square/piazza","compra":"buys","paga":"pays"},"questions":[{"q":"Quando va al mercato la signora Rossi?","options":["Il lunedì","Il mercoledì","Il venerdì","Il sabato"],"correct":2,"explanation":"La signora Rossi va al mercato ogni venerdì."},{"q":"Quanto costano le mele?","options":["1 euro al chilo","2 euro al chilo","3 euro al chilo","5 euro al chilo"],"correct":1,"explanation":"Le mele costano due euro al chilo."},{"q":"Come si chiama il venditore di frutta?","options":["Marco","Giovanni","Mario","Antonio"],"correct":2,"explanation":"Il venditore di frutta si chiama Mario."}]},
    {"id":"a2-vacanze","level":"A2","emoji":"🏖️","title":"Le Vacanze di Giulia","subtitle":"A summer holiday in Sicily","words":180,"paragraphs":[{"italian":"L'estate scorsa Giulia è andata in vacanza in Sicilia con i suoi amici. Hanno preso il treno da Milano fino a Roma, e poi hanno preso l'aereo per Palermo. Il viaggio è durato quasi cinque ore.","english":"Last summer Giulia went on holiday to Sicily with her friends. They took the train from Milan to Rome, and then took the plane to Palermo. The journey lasted almost five hours."},{"italian":"Palermo è una città bellissima. Giulia e i suoi amici hanno visitato i mercati storici, le chiese antiche e i palazzi arabi. Hanno mangiato cibo straordinario: arancini, cannoli e granite al limone.","english":"Palermo is a very beautiful city. Giulia and her friends visited the historic markets, the ancient churches and the Arab palaces. They ate extraordinary food: arancini, cannoli and lemon granita."},{"italian":"Dopo tre giorni a Palermo, sono andati al mare. La spiaggia era meravigliosa: l'acqua era cristallina e il sole brillava tutto il giorno. Giulia ha imparato a fare snorkeling!","english":"After three days in Palermo, they went to the sea. The beach was wonderful: the water was crystal clear and the sun shone all day. Giulia learned to go snorkelling!"},{"italian":"L'ultimo giorno, Giulia ha comprato dei regali per la sua famiglia: ceramiche colorate e limoncello siciliano. Era triste partire, ma è tornata a casa con tanti bei ricordi.","english":"On the last day, Giulia bought some gifts for her family: colourful ceramics and Sicilian limoncello. She was sad to leave, but returned home with many beautiful memories."}],"vocab":{"vacanze":"holidays","estate scorsa":"last summer","viaggio":"journey/trip","ha visitato":"visited","mercati":"markets","chiese":"churches","cibo":"food","spiaggia":"beach","meravigliosa":"wonderful","cristallina":"crystal clear","regali":"gifts","ricordi":"memories","è tornata":"she returned","triste":"sad","ceramiche":"ceramics"},"questions":[{"q":"Come è andata a Palermo Giulia?","options":["In macchina","In treno e poi aereo","Solo in aereo","In nave"],"correct":1,"explanation":"Ha preso il treno fino a Roma e poi l'aereo per Palermo."},{"q":"Cosa ha imparato a fare Giulia al mare?","options":["Surfing","Nuotare","Snorkeling","Vela"],"correct":2,"explanation":"Giulia ha imparato a fare snorkeling."},{"q":"Cosa ha comprato come regalo?","options":["Libri e vino","Ceramiche e limoncello","Vestiti e scarpe","Dolci e caffè"],"correct":1,"explanation":"Ha comprato ceramiche colorate e limoncello siciliano."}]},
    {"id":"a2-ristorante","level":"A2","emoji":"🍝","title":"Una Cena Speciale","subtitle":"A birthday dinner at a restaurant","words":170,"paragraphs":[{"italian":"Ieri sera Lorenzo ha portato la sua ragazza, Chiara, in un ristorante speciale per festeggiare il suo compleanno. Il ristorante si trovava nel centro storico della città, in una piccola piazza illuminata.","english":"Yesterday evening Lorenzo took his girlfriend, Chiara, to a special restaurant to celebrate her birthday. The restaurant was in the historic centre of the city, in a small illuminated square."},{"italian":"Il cameriere li ha accompagnati a un tavolo vicino alla finestra. Hanno guardato il menu con attenzione. Lorenzo ha ordinato i rigatoni all'amatriciana e Chiara ha scelto le tagliatelle ai funghi porcini.","english":"The waiter led them to a table near the window. They looked at the menu carefully. Lorenzo ordered rigatoni all'amatriciana and Chiara chose tagliatelle with porcini mushrooms."},{"italian":"Per secondo, hanno condiviso una bistecca alla fiorentina con contorno di patate al forno. Il vino rosso della casa era eccellente. Chiara era molto contenta.","english":"For the main course, they shared a Florentine steak with a side of roast potatoes. The house red wine was excellent. Chiara was very happy."},{"italian":"Alla fine, il cameriere ha portato una torta al cioccolato con una candela. Tutti i clienti del ristorante hanno cantato 'Tanti auguri'. Chiara si è commossa. È stata una serata indimenticabile.","english":"At the end, the waiter brought a chocolate cake with a candle. All the restaurant's customers sang 'Happy Birthday'. Chiara was moved to tears. It was an unforgettable evening."}],"vocab":{"compleanno":"birthday","cameriere":"waiter","menu":"menu","ha ordinato":"ordered","ha scelto":"chose","condiviso":"shared","bistecca":"steak","patate al forno":"roast potatoes","vino rosso":"red wine","torta":"cake","candela":"candle","tanti auguri":"happy birthday","indimenticabile":"unforgettable","commossa":"moved/touched"},"questions":[{"q":"Perché Lorenzo ha portato Chiara al ristorante?","options":["Per un anniversario","Per il suo compleanno","Per una promozione","Per Natale"],"correct":1,"explanation":"Lorenzo ha portato Chiara per festeggiare il suo compleanno."},{"q":"Cosa ha ordinato Chiara?","options":["Rigatoni all'amatriciana","Bistecca fiorentina","Tagliatelle ai funghi","Pizza margherita"],"correct":2,"explanation":"Chiara ha scelto le tagliatelle ai funghi porcini."},{"q":"Cosa hanno portato alla fine della cena?","options":["Gelato","Torta al cioccolato","Tiramisù","Cannoli"],"correct":1,"explanation":"Il cameriere ha portato una torta al cioccolato con una candela."}]},
    {"id":"a2-roma","level":"A2","emoji":"🏛️","title":"Un Giorno a Roma","subtitle":"Exploring the Eternal City","words":165,"paragraphs":[{"italian":"Quando Elena era piccola, ha visitato Roma per la prima volta con i suoi genitori. Aveva dieci anni ed era estate. Roma era molto caotica ma straordinaria.","english":"When Elena was young, she visited Rome for the first time with her parents. She was ten years old and it was summer. Rome was very chaotic but extraordinary."},{"italian":"La prima mattina, sono andati al Colosseo. Era enorme e impressionante. La guida turistica ha spiegato la storia dell'antica Roma. Elena ascoltava con molta attenzione.","english":"On the first morning, they went to the Colosseum. It was enormous and impressive. The tour guide explained the history of ancient Rome. Elena listened with great attention."},{"italian":"Nel pomeriggio, hanno camminato fino alla Fontana di Trevi. C'era moltissima gente. La tradizione dice che se lanci una moneta nella fontana, tornerai a Roma. Elena ha lanciato due monete!","english":"In the afternoon, they walked to the Trevi Fountain. There were very many people. The tradition says that if you throw a coin in the fountain, you will return to Rome. Elena threw two coins!"},{"italian":"La sera, la famiglia ha mangiato in una trattoria vicino al Pantheon. Elena ha mangiato la pasta cacio e pepe per la prima volta. Le è piaciuta moltissimo. Da quel giorno, Roma è rimasta nel suo cuore.","english":"In the evening, the family ate at a trattoria near the Pantheon. Elena ate pasta cacio e pepe for the first time. She loved it very much. From that day, Rome stayed in her heart."}],"vocab":{"quando era piccola":"when she was young","per la prima volta":"for the first time","estate":"summer","Colosseo":"Colosseum","guida turistica":"tour guide","fontana":"fountain","moneta":"coin","lanciare":"to throw","trattoria":"traditional restaurant","cacio e pepe":"cheese and pepper pasta","le è piaciuta":"she liked it","cuore":"heart"},"questions":[{"q":"Quanti anni aveva Elena quando ha visitato Roma?","options":["8","10","12","15"],"correct":1,"explanation":"Elena aveva dieci anni."},{"q":"Quante monete ha lanciato Elena nella fontana?","options":["Una","Due","Tre","Nessuna"],"correct":1,"explanation":"Elena ha lanciato due monete nella Fontana di Trevi."},{"q":"Cosa ha mangiato Elena la prima sera?","options":["Pizza","Carbonara","Cacio e pepe","Lasagna"],"correct":2,"explanation":"Elena ha mangiato la pasta cacio e pepe per la prima volta."}]}
]


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


@app.route('/books')
@login_required
def books():
    return render_template('books.html',
        books=BOOKS,
        books_json=json.dumps(BOOKS),
        user_name=session.get('user_name', 'Learner'),
        user_picture=session.get('user_picture', '')
    )


@app.route('/progress', methods=['GET'])
@login_required
def get_progress():
    user_id = session.get('user_id', 'default')
    prog = user_progress.get(user_id, {'day': 1, 'level': 'A1', 'completed_days': []})
    return jsonify(prog)


@app.route('/progress', methods=['POST'])
@login_required
def save_progress():
    user_id = session.get('user_id', 'default')
    data = request.get_json()
    if user_id not in user_progress:
        user_progress[user_id] = {'day': 1, 'level': 'A1', 'completed_days': []}
    prog = user_progress[user_id]
    if 'day' in data:
        prog['day'] = data['day']
    if 'level' in data:
        prog['level'] = data['level']
    if 'complete_day' in data:
        day = data['complete_day']
        if day not in prog['completed_days']:
            prog['completed_days'].append(day)
        prog['day'] = max(prog['day'], day + 1)
    return jsonify(prog)


if __name__ == '__main__':
    app.run(debug=True, port=5050)
