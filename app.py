from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
import google.generativeai as genai
import os, json, hashlib
from dotenv import load_dotenv
from datetime import date, timedelta
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


LESSONS = [
  {"id":"greetings","unit":1,"unit_name":"I Fondamentali","unit_subtitle":"The Basics","unit_color":"#58CC02","order":1,"title":"Greetings","subtitle":"Say ciao like a local","icon":"👋","xp_reward":15,"exercises":[
    {"type":"multiple_choice","prompt":"What does 'Ciao' mean?","audio":"Ciao","options":["Hello / Bye","Thank you","Please","Sorry"],"correct":0,"feedback":"Ciao works for both hello AND goodbye — very casual!"},
    {"type":"multiple_choice","prompt":"How do you say 'Good morning'?","options":["Buongiorno","Buonasera","Buonanotte","Prego"],"correct":0,"feedback":"Buongiorno = Good day. Use until ~5pm."},
    {"type":"tap_word","prompt":"Arrange the words: 'My name is Marco'","tokens":["Mi","chiamo","Marco"],"distractors":["Sono","Ho","Tu"],"feedback":"Mi chiamo = literally 'I call myself'"},
    {"type":"multiple_choice","prompt":"How do you say 'How are you?' (informal)?","options":["Come stai?","Come sta?","Come va?","Come sei?"],"correct":0,"feedback":"Come stai? is informal. Come sta? is formal."},
    {"type":"matching","prompt":"Match the Italian to the English","pairs":[["Ciao","Hello/Bye"],["Grazie","Thank you"],["Prego","You're welcome"],["Scusi","Excuse me"]]},
    {"type":"fill_blank","prompt":"___ (good morning)","sentence":"___ , come stai?","options":["Buongiorno","Buonanotte","Arrivederci"],"correct":0,"feedback":"Buongiorno is used until afternoon!"}
  ]},
  {"id":"numbers","unit":1,"unit_name":"I Fondamentali","unit_subtitle":"The Basics","unit_color":"#58CC02","order":2,"title":"Numbers","subtitle":"Count to twenty","icon":"🔢","xp_reward":15,"exercises":[
    {"type":"multiple_choice","prompt":"How do you say 'five'?","options":["cinque","quattro","sei","tre"],"correct":0,"feedback":"cinque = 5, quattro = 4, sei = 6, tre = 3"},
    {"type":"multiple_choice","prompt":"What number is 'diciotto'?","options":["17","18","19","20"],"correct":1,"feedback":"Diciotto = 18. Diciassette=17, Diciannove=19, Venti=20"},
    {"type":"tap_word","prompt":"Arrange: 'I have ten cats'","tokens":["Ho","dieci","gatti"],"distractors":["Sono","venti","cani"],"feedback":"Ho = I have, dieci = 10, gatti = cats"},
    {"type":"fill_blank","prompt":"___ anni (30 years old)","sentence":"Ho ___ anni.","options":["trenta","venti","quaranta"],"correct":0,"feedback":"Trenta = 30. Ho trenta anni = I am 30 years old."},
    {"type":"multiple_choice","prompt":"How do you say 'first'?","options":["primo","uno","inizio","prima volta"],"correct":0,"feedback":"Primo/prima = first (ordinal)"},
    {"type":"matching","prompt":"Match the numbers","pairs":[["uno","one"],["cinque","five"],["dieci","ten"],["venti","twenty"]]}
  ]},
  {"id":"family","unit":1,"unit_name":"I Fondamentali","unit_subtitle":"The Basics","unit_color":"#58CC02","order":3,"title":"Family","subtitle":"Talk about your family","icon":"👨‍👩‍👧","xp_reward":15,"exercises":[
    {"type":"multiple_choice","prompt":"What does 'fratello' mean?","options":["brother","sister","father","uncle"],"correct":0,"feedback":"Fratello = brother. Sorella = sister."},
    {"type":"multiple_choice","prompt":"How do you say 'my mother'?","options":["mia madre","mio padre","mia sorella","mio fratello"],"correct":0,"feedback":"mia = my (feminine). madre = mother."},
    {"type":"tap_word","prompt":"Arrange: 'I have a sister'","tokens":["Ho","una","sorella"],"distractors":["Sono","mia","padre"],"feedback":"Ho una sorella = I have a sister"},
    {"type":"translation","prompt":"Translate: 'My father is a doctor'","answer":"mio padre è medico","accept_also":["il mio padre è medico","mio padre è un medico"],"feedback":"Mio padre = my father. È medico = is a doctor."},
    {"type":"matching","prompt":"Match family members","pairs":[["padre","father"],["madre","mother"],["fratello","brother"],["sorella","sister"]]},
    {"type":"fill_blank","prompt":"___ chiamo Marco","sentence":"Mi ___ Marco.","options":["chiamo","sono","ho"],"correct":0,"feedback":"Mi chiamo = My name is (I call myself)"}
  ]},
  {"id":"colors","unit":1,"unit_name":"I Fondamentali","unit_subtitle":"The Basics","unit_color":"#58CC02","order":4,"title":"Colors & Descriptions","subtitle":"Describe the world around you","icon":"🎨","xp_reward":20,"exercises":[
    {"type":"multiple_choice","prompt":"How do you say 'red'?","options":["rosso","blu","verde","giallo"],"correct":0,"feedback":"Rosso = red, blu = blue, verde = green, giallo = yellow"},
    {"type":"multiple_choice","prompt":"'The sky is ___' (blue)","options":["blu","rosso","nero","bianco"],"correct":0,"feedback":"Il cielo è blu. Blu is for strong blue; azzurro for light blue."},
    {"type":"tap_word","prompt":"Arrange: 'The cat is black'","tokens":["Il","gatto","è","nero"],"distractors":["La","bianco","rosso"],"feedback":"Il gatto è nero = The cat is black. Nero = black."},
    {"type":"translation","prompt":"Translate: 'The dress is beautiful'","answer":"il vestito è bello","accept_also":["il vestito è bellissimo","il vestito è molto bello"],"feedback":"Bello = beautiful. Bellissimo = very beautiful."},
    {"type":"fill_blank","prompt":"La macchina è ___ (red)","sentence":"La macchina è ___.","options":["rossa","rosso","rosse"],"correct":0,"feedback":"La macchina (feminine) → rossa. Il fiore (masculine) → rosso."},
    {"type":"multiple_choice","prompt":"How do you say 'big'?","options":["grande","piccolo","alto","basso"],"correct":0,"feedback":"Grande = big. Piccolo = small. Alto = tall. Basso = short."}
  ]},
  {"id":"cafe","unit":2,"unit_name":"Vita Quotidiana","unit_subtitle":"Daily Life","unit_color":"#1CB0F6","order":5,"title":"At the Café","subtitle":"Order like an Italian","icon":"☕","xp_reward":20,"exercises":[
    {"type":"multiple_choice","prompt":"How do you say 'I'd like a coffee'?","options":["Vorrei un caffè","Voglio un caffè","Dammi un caffè","Prendo caffè"],"correct":0,"feedback":"Vorrei is more polite than voglio. Always use vorrei in a café!"},
    {"type":"multiple_choice","prompt":"How do you ask for the bill?","options":["Il conto, per favore","La lista, grazie","Quanto costa?","Posso pagare?"],"correct":0,"feedback":"Il conto, per favore = The bill, please. Very useful!"},
    {"type":"tap_word","prompt":"Arrange: 'A cappuccino and a croissant'","tokens":["Un","cappuccino","e","un","cornetto"],"distractors":["La","il","due"],"feedback":"Un cappuccino e un cornetto — the classic Italian breakfast!"},
    {"type":"translation","prompt":"Translate: 'Where is the bathroom?'","answer":"dov'è il bagno","accept_also":["dov'è il bagno?","dove è il bagno"],"feedback":"Dov'è = where is. Bagno = bathroom."},
    {"type":"fill_blank","prompt":"Un ___ alla crema (croissant)","sentence":"Vorrei un ___ alla crema.","options":["cornetto","caffè","gelato"],"correct":0,"feedback":"Cornetto alla crema = cream-filled croissant"},
    {"type":"matching","prompt":"Match the café vocabulary","pairs":[["caffè","coffee"],["latte","milk"],["zucchero","sugar"],["acqua","water"]]}
  ]},
  {"id":"food","unit":2,"unit_name":"Vita Quotidiana","unit_subtitle":"Daily Life","unit_color":"#1CB0F6","order":6,"title":"Food & Eating","subtitle":"Mangia bene!","icon":"🍝","xp_reward":20,"exercises":[
    {"type":"multiple_choice","prompt":"How do you say 'I like pasta'?","options":["Mi piace la pasta","Voglio la pasta","Mangio la pasta","Amo pasta"],"correct":0,"feedback":"Mi piace = I like. Mi piacciono = I like (plural). Mi piace la pasta!"},
    {"type":"multiple_choice","prompt":"What does 'delizioso' mean?","options":["delicious","beautiful","expensive","spicy"],"correct":0,"feedback":"Delizioso/a = delicious. A very useful word in Italy!"},
    {"type":"tap_word","prompt":"Arrange: 'I eat bread every day'","tokens":["Mangio","il","pane","ogni","giorno"],"distractors":["bevo","la","pasta"],"feedback":"Mangio = I eat. Ogni giorno = every day."},
    {"type":"translation","prompt":"Translate: 'The food is very good'","answer":"il cibo è molto buono","accept_also":["il cibo è buonissimo","il cibo è molto buono!"],"feedback":"Cibo = food. Buono = good. Molto = very."},
    {"type":"matching","prompt":"Match the food items","pairs":[["pane","bread"],["carne","meat"],["pesce","fish"],["formaggio","cheese"]]},
    {"type":"fill_blank","prompt":"Mi ___ il gelato (I like)","sentence":"Mi ___ il gelato.","options":["piace","voglio","mangio"],"correct":0,"feedback":"Mi piace = I like. Mi piacciono = I like (plural things)."}
  ]},
  {"id":"directions","unit":2,"unit_name":"Vita Quotidiana","unit_subtitle":"Daily Life","unit_color":"#1CB0F6","order":7,"title":"Getting Around","subtitle":"Navigate Italian streets","icon":"🗺️","xp_reward":20,"exercises":[
    {"type":"multiple_choice","prompt":"How do you say 'Turn right'?","options":["Gira a destra","Gira a sinistra","Vai dritto","Torna indietro"],"correct":0,"feedback":"Destra = right. Sinistra = left. Dritto = straight."},
    {"type":"multiple_choice","prompt":"'Straight ahead' in Italian?","options":["Dritto","Destra","Sinistra","Vicino"],"correct":0,"feedback":"Vai dritto = go straight ahead."},
    {"type":"tap_word","prompt":"Arrange: 'Where is the hotel?'","tokens":["Dov'è","l'albergo"],"distractors":["Come","il","stazione"],"feedback":"Dov'è = where is. L'albergo = the hotel."},
    {"type":"translation","prompt":"Translate: 'The bank is near the station'","answer":"la banca è vicino alla stazione","accept_also":["la banca è vicino alla stazione."],"feedback":"Vicino a = near. La stazione = the station."},
    {"type":"fill_blank","prompt":"Gira a ___ (left)","sentence":"Poi gira a ___.","options":["sinistra","destra","dritto"],"correct":0,"feedback":"A sinistra = to the left. A destra = to the right."},
    {"type":"matching","prompt":"Match direction words","pairs":[["destra","right"],["sinistra","left"],["dritto","straight"],["vicino","near"]]}
  ]},
  {"id":"shopping","unit":2,"unit_name":"Vita Quotidiana","unit_subtitle":"Daily Life","unit_color":"#1CB0F6","order":8,"title":"Shopping","subtitle":"Fare shopping in Italia","icon":"🛍️","xp_reward":25,"exercises":[
    {"type":"multiple_choice","prompt":"How do you ask 'How much does it cost?'","options":["Quanto costa?","Cosa costa?","Che prezzo?","Quanto è?"],"correct":0,"feedback":"Quanto costa? = How much does it cost? Quanto costano? = How much do they cost?"},
    {"type":"multiple_choice","prompt":"How do you say 'too expensive'?","options":["Troppo caro","Molto caro","Caro troppo","È caro"],"correct":0,"feedback":"Troppo = too (much). Caro = expensive. Economico = cheap."},
    {"type":"tap_word","prompt":"Arrange: 'The shoes cost fifty euros'","tokens":["Le","scarpe","costano","cinquanta","euro"],"distractors":["Il","costa","trenta"],"feedback":"Le scarpe costano = the shoes cost. Cinquanta = 50."},
    {"type":"translation","prompt":"Translate: 'I want this shirt'","answer":"voglio questa camicia","accept_also":["vorrei questa camicia","voglio questa camicia."],"feedback":"Voglio = I want. Questa = this (feminine). Camicia = shirt."},
    {"type":"fill_blank","prompt":"___ costa questo? (how much)","sentence":"___ costa questo?","options":["Quanto","Come","Cosa"],"correct":0,"feedback":"Quanto = how much. Questo = this."},
    {"type":"multiple_choice","prompt":"'Do you have this in size 42?' → 'Ce l'ha in ___'","options":["taglia 42","numero 42","misura 42","size 42"],"correct":0,"feedback":"Taglia = clothing size. Numero = shoe size."}
  ]}
]

UNITS = [
  {"id":1,"name":"I Fondamentali","subtitle":"The Basics","color":"#58CC02","icon":"⭐","lesson_ids":["greetings","numbers","family","colors"]},
  {"id":2,"name":"Vita Quotidiana","subtitle":"Daily Life","color":"#1CB0F6","icon":"🌟","lesson_ids":["cafe","food","directions","shopping"]},
  {"id":3,"name":"Il Passato","subtitle":"The Past","color":"#CE82FF","icon":"🔒","lesson_ids":[],"locked":True},
  {"id":4,"name":"Espressioni","subtitle":"Complex Ideas","color":"#FF9600","icon":"🔒","lesson_ids":[],"locked":True},
]

ACHIEVEMENTS = [
  {"id":"first_steps","title":"First Steps","desc":"Complete your first lesson","icon":"🌱","xp":5},
  {"id":"on_fire","title":"On Fire","desc":"3-day streak","icon":"🔥","xp":10},
  {"id":"century","title":"Century","desc":"Earn 100 XP total","icon":"💯","xp":15},
  {"id":"perfect","title":"Perfectionist","desc":"Finish a lesson without any mistakes","icon":"⭐","xp":20},
  {"id":"unit1","title":"Unit 1 Master","desc":"Complete all Unit 1 lessons","icon":"🏆","xp":30},
  {"id":"bookworm","title":"Bookworm","desc":"Read 3 Italian stories","icon":"📚","xp":10},
  {"id":"week","title":"One Week","desc":"7-day streak","icon":"🗓️","xp":25},
  {"id":"xp500","title":"XP Champion","desc":"Earn 500 XP","icon":"⚡","xp":30},
  {"id":"inviter","title":"Ambassador","desc":"Invite a friend to Zuzu","icon":"🤝","xp":75},
]

DAILY_QUESTS = [
  {"id":"lessons","title":"Complete 3 Lessons","icon":"📚","target":3,"xp":30},
  {"id":"earn_xp","title":"Earn 50 XP","icon":"⚡","target":50,"xp":20},
  {"id":"speak","title":"Use Zuzu Chat","icon":"🎤","target":1,"xp":25},
]


def make_ref_code(user_id):
    return hashlib.md5(user_id.encode()).hexdigest()[:7].upper()


# referral_codes -> user_id lookup
referral_map = {}   # ref_code -> user_id


def default_progress():
    return {
        'day': 1, 'level': 'A1', 'completed_days': [],
        'xp': 0, 'streak': 0, 'hearts': 5, 'max_hearts': 5,
        'last_activity': None,
        'completed_lessons': [],
        'total_questions': 0, 'correct_questions': 0,
        'xp_today': 0, 'quest_date': None,
        'quests': {'lessons': 0, 'earn_xp': 0, 'speak': 0},
        'quests_done': [],
        'achievements': [],
        'streak_freezes': 1,
        'referrals': 0,
        'ref_code': None,
    }


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


@app.route('/dev-login')
def dev_login():
    """Quick local login bypass for development."""
    session['user_id'] = 'dev-user-001'
    session['user_name'] = 'Aqif Raza'
    session['user_email'] = 'aqifrazadahri7@gmail.com'
    session['user_picture'] = ''
    return redirect(url_for('index'))


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

    # Handle referral reward
    ref = session.pop('referred_by', None)
    if ref and ref in referral_map:
        referrer_id = referral_map[ref]
        if referrer_id != user_info['sub']:
            if referrer_id not in user_progress:
                user_progress[referrer_id] = default_progress()
            rp = user_progress[referrer_id]
            rp['referrals'] = rp.get('referrals', 0) + 1
            rp['xp'] = rp.get('xp', 0) + 75
            if 'inviter' not in rp.get('achievements', []):
                rp.setdefault('achievements', []).append('inviter')

    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── Main app routes ──

@app.route('/')
@login_required
def index():
    uid = session.get('user_id', 'default')
    if uid not in user_progress:
        user_progress[uid] = default_progress()
    prog = user_progress[uid]
    today = str(date.today())
    if prog.get('quest_date') != today:
        prog['quests'] = {'lessons': 0, 'earn_xp': 0, 'speak': 0}
        prog['quests_done'] = []
        prog['xp_today'] = 0
        prog['quest_date'] = today
    return render_template('home.html',
        user_name=session.get('user_name', 'Learner'),
        user_picture=session.get('user_picture', ''),
        progress_json=json.dumps(prog),
        lessons_json=json.dumps(LESSONS),
        units_json=json.dumps(UNITS),
        achievements_json=json.dumps(ACHIEVEMENTS),
        quests_json=json.dumps(DAILY_QUESTS),
    )


@app.route('/lesson/<lesson_id>')
@login_required
def lesson_page(lesson_id):
    lesson_data = next((l for l in LESSONS if l['id'] == lesson_id), None)
    if not lesson_data:
        return redirect('/')
    uid = session.get('user_id', 'default')
    if uid not in user_progress:
        user_progress[uid] = default_progress()
    prog = user_progress[uid]
    return render_template('lesson.html',
        lesson_json=json.dumps(lesson_data),
        user_name=session.get('user_name', 'Learner'),
        user_picture=session.get('user_picture', ''),
        hearts=prog.get('hearts', 5),
        current_xp=prog.get('xp', 0),
    )


@app.route('/api/complete-lesson', methods=['POST'])
@login_required
def complete_lesson():
    data = request.get_json()
    lesson_id = data.get('lesson_id', '')
    xp_earned = int(data.get('xp', 0))
    mistakes = int(data.get('mistakes', 0))
    correct = int(data.get('correct', 0))

    uid = session.get('user_id', 'default')
    if uid not in user_progress:
        user_progress[uid] = default_progress()
    prog = user_progress[uid]

    today = str(date.today())

    # Reset daily quests if new day
    if prog.get('quest_date') != today:
        prog['quests'] = {'lessons': 0, 'earn_xp': 0, 'speak': 0}
        prog['quests_done'] = []
        prog['xp_today'] = 0
        prog['quest_date'] = today

    # Completed lessons
    if lesson_id and lesson_id not in prog.get('completed_lessons', []):
        prog.setdefault('completed_lessons', []).append(lesson_id)

    # XP
    prog['xp'] = prog.get('xp', 0) + xp_earned
    prog['xp_today'] = prog.get('xp_today', 0) + xp_earned

    # Streak
    last = prog.get('last_activity')
    if last != today:
        yesterday = str(date.today() - timedelta(days=1))
        if last == yesterday:
            prog['streak'] = prog.get('streak', 0) + 1
        elif last is None:
            prog['streak'] = 1
        else:
            if prog.get('streak_freezes', 0) > 0:
                prog['streak_freezes'] -= 1
            else:
                prog['streak'] = 1
        prog['last_activity'] = today

    # Accuracy
    prog['total_questions'] = prog.get('total_questions', 0) + correct + mistakes
    prog['correct_questions'] = prog.get('correct_questions', 0) + correct
    tq = prog['total_questions']
    prog['accuracy'] = round(prog['correct_questions'] / tq * 100) if tq > 0 else 100

    # Quests
    q = prog.get('quests', {'lessons': 0, 'earn_xp': 0, 'speak': 0})
    done = prog.get('quests_done', [])
    bonus_xp = 0
    q['lessons'] = q.get('lessons', 0) + 1
    if q['lessons'] >= 3 and 'lessons' not in done:
        done.append('lessons'); bonus_xp += 30
    q['earn_xp'] = prog['xp_today']
    if q['earn_xp'] >= 50 and 'earn_xp' not in done:
        done.append('earn_xp'); bonus_xp += 20
    prog['quests'] = q
    prog['quests_done'] = done
    if bonus_xp:
        prog['xp'] += bonus_xp

    # Achievements
    achieved = prog.get('achievements', [])
    new_ach = []
    checks = [
        ('first_steps', len(prog.get('completed_lessons', [])) >= 1),
        ('on_fire', prog.get('streak', 0) >= 3),
        ('week', prog.get('streak', 0) >= 7),
        ('century', prog.get('xp', 0) >= 100),
        ('xp500', prog.get('xp', 0) >= 500),
        ('perfect', mistakes == 0 and correct >= 4),
        ('unit1', all(lid in prog.get('completed_lessons', []) for lid in ['greetings','numbers','family','colors'])),
    ]
    for aid, cond in checks:
        if cond and aid not in achieved:
            achieved.append(aid)
            new_ach.append(aid)
    prog['achievements'] = achieved

    return jsonify({
        'xp': prog['xp'], 'streak': prog['streak'], 'hearts': prog.get('hearts', 5),
        'completed_lessons': prog['completed_lessons'],
        'quests': prog['quests'], 'quests_done': prog['quests_done'],
        'achievements': prog['achievements'], 'new_achievements': new_ach,
        'accuracy': prog.get('accuracy', 100), 'bonus_xp': bonus_xp,
    })


@app.route('/join')
def join_via_ref():
    ref = request.args.get('ref', '').upper()
    if ref:
        session['referred_by'] = ref
    return redirect(url_for('login'))


@app.route('/api/invite', methods=['GET'])
@login_required
def get_invite():
    uid = session.get('user_id', 'default')
    if uid not in user_progress:
        user_progress[uid] = default_progress()
    prog = user_progress[uid]
    if not prog.get('ref_code'):
        prog['ref_code'] = make_ref_code(uid)
        referral_map[prog['ref_code']] = uid
    base = request.host_url.rstrip('/')
    return jsonify({
        'ref_code': prog['ref_code'],
        'invite_url': f"{base}/join?ref={prog['ref_code']}",
        'referrals': prog.get('referrals', 0),
    })


@app.route('/api/hearts', methods=['POST'])
@login_required
def update_hearts():
    data = request.get_json()
    uid = session.get('user_id', 'default')
    if uid not in user_progress:
        user_progress[uid] = default_progress()
    prog = user_progress[uid]
    if data.get('action') == 'lose':
        prog['hearts'] = max(0, prog.get('hearts', 5) - 1)
    elif data.get('action') == 'restore':
        prog['hearts'] = 5
    return jsonify({'hearts': prog['hearts']})


@app.route('/chat')
@login_required
def chat_page():
    topic = request.args.get('topic', '')
    return render_template('index.html',
        user_name=session.get('user_name', 'Learner'),
        user_picture=session.get('user_picture', ''),
        user_email=session.get('user_email', ''),
        initial_topic=topic
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


@app.route('/download')
def download():
    return render_template('download.html',
        user_name=session.get('user_name', ''),
        user_picture=session.get('user_picture', '')
    )


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
