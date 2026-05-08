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
    # ── NEW STORIES from Facile A1 & A2 textbooks ──
    {"id":"a1-facile-ciao","level":"A1","emoji":"👋","title":"Ciao! Piacere!","subtitle":"From Facile A1 — First meeting between Li Ping and Mustafa","words":130,"source":"Facile A1","paragraphs":[
        {"italian":"Li Ping: Ciao, io mi chiamo Li Ping.\nMustafa: Io mi chiamo Mustafa. Piacere.\nLi Ping: Piacere mio. Io sono marocchino, sono di Casablanca e tu?\nLi Ping: Io sono cinese, di Pechino.","english":"Li Ping: Hi, my name is Li Ping.\nMustafa: My name is Mustafa. Nice to meet you.\nLi Ping: Nice to meet you too. I am Moroccan, I am from Casablanca and you?\nLi Ping: I am Chinese, from Beijing."},
        {"italian":"Li Ping: Buongiorno, io mi chiamo Li Ping. E tu?\nOlga: Io mi chiamo Olga. Piacere.\nLi Ping: Piacere mio. Di dove sei?\nOlga: Sono ucraina, di Borodianka. E tu?\nLi Ping: Io sono cinese, di Pechino.","english":"Li Ping: Good morning, my name is Li Ping. And you?\nOlga: My name is Olga. Nice to meet you.\nLi Ping: Nice to meet you too. Where are you from?\nOlga: I am Ukrainian, from Borodianka. And you?\nLi Ping: I am Chinese, from Beijing."},
        {"italian":"Olga: Lui, come si chiama?\nLi Ping: Lui si chiama Mustafa.\nOlga: Di dov'è lui?\nLi Ping: Ah! Lui è marocchino.","english":"Olga: What is his name?\nLi Ping: His name is Mustafa.\nOlga: Where is he from?\nLi Ping: Ah! He is Moroccan."},
        {"italian":"Le nazionalità: ALGERIA → algerino/algerina. BRASILE → brasiliano/brasiliana. CINA → cinese. EGITTO → egiziano/egiziana. FRANCIA → francese. ITALIA → italiano/italiana. MAROCCO → marocchino/marocchina. POLONIA → polacco/polacca. ROMANIA → rumeno/rumena. RUSSIA → russo/russa. UCRAINA → ucraino/ucraina.","english":"Nationalities: ALGERIA → Algerian. BRAZIL → Brazilian. CHINA → Chinese. EGYPT → Egyptian. FRANCE → French. ITALY → Italian. MOROCCO → Moroccan. POLAND → Polish. ROMANIA → Romanian. RUSSIA → Russian. UKRAINE → Ukrainian."}
    ],"vocab":{"piacere":"nice to meet you","di dove sei?":"where are you from?","sono di":"I am from","mi chiamo":"my name is","lui si chiama":"his name is","marocchino":"Moroccan","cinese":"Chinese","ucraina":"Ukrainian","nazionalità":"nationality","straniero":"foreigner"},"questions":[{"q":"Di dove è Li Ping?","options":["Marocco","Ucraina","Cina","Italia"],"correct":2,"explanation":"Li Ping è cinese, di Pechino."},{"q":"Come si chiama la ragazza ucraina?","options":["Fatima","Li Ping","Olga","Laura"],"correct":2,"explanation":"La ragazza ucraina si chiama Olga, è di Borodianka."},{"q":"Come diciamo 'nice to meet you' in italiano?","options":["Grazie","Piacere","Ciao","Arrivederci"],"correct":1,"explanation":"Piacere = nice to meet you. Risposta: Piacere mio = Nice to meet you too."}]},
    {"id":"a1-facile-numeri","level":"A1","emoji":"🔢","title":"I Numeri e i Giorni","subtitle":"From Facile A1 — Numbers, days and time expressions","words":100,"source":"Facile A1","paragraphs":[
        {"italian":"I giorni della settimana: LUNEDÌ, MARTEDÌ, MERCOLEDÌ, GIOVEDÌ, VENERDÌ, SABATO, DOMENICA.\n\nChe giorno è oggi? Oggi è lunedì.\nChe giorno era ieri? Ieri era domenica.\nChe giorno è domani? Domani è martedì.\nChe giorno è dopodomani? Dopodomani è mercoledì.","english":"The days of the week: MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY.\n\nWhat day is today? Today is Monday.\nWhat day was yesterday? Yesterday was Sunday.\nWhat day is tomorrow? Tomorrow is Tuesday.\nWhat day is the day after tomorrow? The day after tomorrow is Wednesday."},
        {"italian":"I saluti durante il giorno:\nMATTINA → Buongiorno!\nPOMERIGGIO → Buon pomeriggio!\nSERA → Buonasera!\nNOTTE → Buonanotte!\n\nProverbio: Il buongiorno si vede dal mattino.\n(A good morning can be seen from the morning — you can tell how the day will go from the start.)","english":"Greetings during the day:\nMORNING → Good morning!\nAFTERNOON → Good afternoon!\nEVENING → Good evening!\nNIGHT → Good night!\n\nProverb: You can tell a good day from the morning."},
        {"italian":"I numeri: uno (1), due (2), tre (3), quattro (4), cinque (5), sei (6), sette (7), otto (8), nove (9), dieci (10).\nUndici (11), dodici (12), tredici (13), quattordici (14), quindici (15), sedici (16), diciassette (17), diciotto (18), diciannove (19), venti (20).\nTrenta (30), quaranta (40), cinquanta (50), sessanta (60), settanta (70), ottanta (80), novanta (90), cento (100).","english":"Numbers: one, two, three, four, five, six, seven, eight, nine, ten. Eleven through twenty. Thirty, forty, fifty, sixty, seventy, eighty, ninety, one hundred."}
    ],"vocab":{"lunedì":"Monday","martedì":"Tuesday","mercoledì":"Wednesday","giovedì":"Thursday","venerdì":"Friday","sabato":"Saturday","domenica":"Sunday","oggi":"today","ieri":"yesterday","domani":"tomorrow","dopodomani":"the day after tomorrow","settimana":"week","mattina":"morning","pomeriggio":"afternoon","sera":"evening","notte":"night"},"questions":[{"q":"Come si dice 'Good evening' in italiano?","options":["Buongiorno","Buon pomeriggio","Buonasera","Buonanotte"],"correct":2,"explanation":"Buonasera = Good evening. Si usa dal tardo pomeriggio in poi."},{"q":"Che numero è 'diciotto'?","options":["17","18","19","20"],"correct":1,"explanation":"Diciotto = 18. Diciassette=17, Diciannove=19, Venti=20."},{"q":"Qual è il giorno dopo il venerdì?","options":["Giovedì","Domenica","Lunedì","Sabato"],"correct":3,"explanation":"Il giorno dopo il venerdì è il sabato."}]},
    {"id":"a1-facile-grammatica","level":"A1","emoji":"📖","title":"Grammatica: Essere e Chiamarsi","subtitle":"From Facile A1 — Subject pronouns and key verbs","words":110,"source":"Facile A1","paragraphs":[
        {"italian":"I PRONOMI SOGGETTO:\nio — I am → Io sono italiano.\ntu — you are → Tu sei straniero.\nlui/lei — he/she is → Lui è marocchino. Lei è cinese.\n\nPronomi negativi:\nIo NON sono italiano.\nTu NON sei professore.\nLui/Lei NON si chiama Fatima.","english":"SUBJECT PRONOUNS:\nio (I) — Io sono italiano = I am Italian.\ntu (you) — Tu sei straniero = You are a foreigner.\nlui/lei (he/she) — Lui è marocchino = He is Moroccan.\n\nNegative: NON before the verb makes it negative."},
        {"italian":"IL VERBO ESSERE (to be):\nio SONO — I am\ntu SEI — you are\nlui/lei È — he/she is\n\nIL VERBO CHIAMARSI (to be called):\nio MI CHIAMO — my name is\ntu TI CHIAMI — your name is\nlui/lei SI CHIAMA — his/her name is\n\nEsempio: Io mi chiamo Olga. Io sono ucraina.","english":"THE VERB TO BE:\nio SONO = I am\ntu SEI = you are\nlui/lei È = he/she is\n\nCALLING ONESELF:\nio MI CHIAMO = my name is\ntu TI CHIAMI = your name is\nlui/lei SI CHIAMA = his/her name is\n\nExample: My name is Olga. I am Ukrainian."},
        {"italian":"ERRORI COMUNI da evitare:\n✗ Io mi chiami Mario (SBAGLIATO)\n✓ Io mi chiamo Mario (CORRETTO)\n\n✗ Tu non sono albanese (SBAGLIATO)\n✓ Tu non sei albanese (CORRETTO)\n\n✗ Come ti chiamo? (SBAGLIATO)\n✓ Come ti chiami? (CORRETTO)","english":"COMMON MISTAKES to avoid:\n✗ Io mi chiami Mario (WRONG — wrong ending)\n✓ Io mi chiamo Mario (CORRECT)\n\n✗ Tu non sono albanese (WRONG — wrong pronoun)\n✓ Tu non sei albanese (CORRECT)\n\n✗ Come ti chiamo? (WRONG)\n✓ Come ti chiami? (CORRECT)"}
    ],"vocab":{"sono":"I am","sei":"you are","è":"he/she is","mi chiamo":"my name is","ti chiami":"your name is","si chiama":"his/her name is","non":"not","straniero":"foreigner","professore":"teacher/professor","sbagliato":"wrong","corretto":"correct"},"questions":[{"q":"Come si dice 'my name is' in italiano?","options":["Io sono","Mi chiamo","Ti chiami","Si chiama"],"correct":1,"explanation":"Mi chiamo = my name is. Letteralmente: 'I call myself'."},{"q":"Qual è la forma corretta?","options":["Io mi chiami Mario","Io mi chiamo Mario","Io mi chiamu Mario","Io mi chiamò Mario"],"correct":1,"explanation":"La forma corretta è 'io mi chiamo' — prima persona singolare del verbo chiamarsi."},{"q":"Come si dice 'she is not Italian'?","options":["Lei non sono italiana","Lei non sei italiana","Lei non è italiana","Lei non è italiano"],"correct":2,"explanation":"Lei non è italiana — NON va prima del verbo. Italiana con la A perché è femminile."}]},
    {"id":"a2-facile-laura","level":"A2","emoji":"📚","title":"La Storia di Laura","subtitle":"From Facile A2 — A life story using passato prossimo","words":200,"source":"Facile A2","paragraphs":[
        {"italian":"Sono nata a Napoli, in Campania, il 15 settembre del 1980. Ho studiato a Napoli e a Roma. A Napoli ho frequentato la scuola elementare da 6 a 10 anni, la scuola media da 11 a 14 anni e poi la scuola superiore per 5 anni, al Liceo Classico 'Genovesi'.","english":"I was born in Naples, in Campania, on 15 September 1980. I studied in Naples and Rome. In Naples I attended primary school from age 6 to 10, middle school from 11 to 14, and then high school for 5 years at the Liceo Classico 'Genovesi'."},
        {"italian":"Dopo il diploma di maturità classica, all'età di 19 anni mi sono trasferita a Roma, dove ho abitato per cinque anni e ho studiato Lingue Straniere all'università. Mi sono laureata nel 2004.","english":"After my classical high school diploma, at the age of 19 I moved to Rome, where I lived for five years and studied Foreign Languages at university. I graduated in 2004."},
        {"italian":"Nel 2005 sono tornata a Napoli, dove ho fatto l'insegnante in una scuola privata. Lì ho conosciuto Matteo. Dopo quattro anni ci siamo sposati, siamo andati a vivere a Roma e abbiamo comprato un appartamento un po' fuori città.","english":"In 2005 I returned to Naples, where I worked as a teacher in a private school. There I met Matteo. After four years we got married, went to live in Rome and bought an apartment a little outside the city."},
        {"italian":"Tre anni fa è nato Leo, il nostro primo figlio. Per due anni sono stata mamma a tempo pieno; l'anno scorso ho ricominciato a insegnare nei corsi di italiano per stranieri.\n\nVERBI CON ESSERE: sono nata, mi sono trasferita, sono tornata, ci siamo sposati, siamo andati, è nato, sono stata.\nVERBI CON AVERE: ho studiato, ho frequentato, ho abitato, ho conosciuto, abbiamo comprato, ho ricominciato.","english":"Three years ago Leo was born, our first child. For two years I was a full-time mum; last year I started teaching again in Italian courses for foreigners.\n\nVERBS WITH ESSERE: was born, moved, returned, got married, went, was born, was.\nVERBS WITH AVERE: studied, attended, lived, met, bought, started again."}
    ],"vocab":{"sono nata":"I was born","ho studiato":"I studied","mi sono trasferita":"I moved","mi sono laureata":"I graduated","sono tornata":"I returned","ho conosciuto":"I met","ci siamo sposati":"we got married","abbiamo comprato":"we bought","è nato":"he was born","a tempo pieno":"full time","l'anno scorso":"last year","tre anni fa":"three years ago"},"questions":[{"q":"Dove è nata Laura?","options":["Roma","Milano","Napoli","Firenze"],"correct":2,"explanation":"Laura è nata a Napoli, in Campania."},{"q":"Quando si è laureata Laura?","options":["2000","2002","2004","2005"],"correct":2,"explanation":"Laura si è laureata nel 2004, dopo aver studiato Lingue Straniere a Roma."},{"q":"Come si chiama il figlio di Laura?","options":["Matteo","Marco","Lorenzo","Leo"],"correct":3,"explanation":"Il figlio si chiama Leo. Matteo è il marito."},{"q":"Quale verbo usa il verbo ESSERE al passato prossimo?","options":["ho studiato","ho frequentato","sono nata","ho conosciuto"],"correct":2,"explanation":"'Sono nata' usa ESSERE. I verbi di movimento e cambiamento di stato usano essere."}]},
    {"id":"a2-facile-abubakar","level":"A2","emoji":"🌍","title":"La Storia di Abubakar","subtitle":"From Facile A2 — A powerful immigrant story","words":190,"source":"Facile A2","paragraphs":[
        {"italian":"Sono nato a Bakau, in Gambia, vicino a Banjul, il 30 ottobre del 1995. In questa città sono cresciuto e ho studiato. Ho fatto la scuola primaria da 6 a 12 anni, poi la scuola di base per altri 3 anni.","english":"I was born in Bakau, in Gambia, near Banjul, on 30 October 1995. In this city I grew up and studied. I attended primary school from age 6 to 12, then basic school for another 3 years."},
        {"italian":"A 15 anni ho smesso di studiare perché hanno arrestato mio padre per motivi politici. Allora con mia madre e la mia sorellina ci siamo trasferiti in Senegal, ma io ho deciso di andare in Libia, per trovare una sistemazione migliore e poter aiutare di più la mia famiglia.","english":"At 15 I stopped studying because my father was arrested for political reasons. So with my mother and little sister we moved to Senegal, but I decided to go to Libya, to find a better situation and be able to help my family more."},
        {"italian":"In Libia ho lavorato alcuni mesi in un'azienda agricola, senza mai ricevere lo stipendio, poi... la guerra! I militari hanno arrestato tutti i giovani neri come me. Sono stato in prigione 8-9 mesi.","english":"In Libya I worked for several months on a farm, without ever receiving my wages, then... the war! The soldiers arrested all the young Black men like me. I was in prison for 8-9 months."},
        {"italian":"Il mio datore di lavoro mi ha aiutato a uscire dalla prigione e mi ha pagato il viaggio per l'Italia. Una notte sono partito con un barcone e dopo tre giorni sono arrivato a Lampedusa. L'Italia mi ha salvato la vita e voglio fare qualcosa per servire e ringraziare questo paese.","english":"My employer helped me to leave prison and paid for my journey to Italy. One night I left on a boat and after three days I arrived in Lampedusa. Italy saved my life and I want to do something to serve and thank this country."}
    ],"vocab":{"sono nato":"I was born","sono cresciuto":"I grew up","ho smesso":"I stopped","hanno arrestato":"they arrested","ci siamo trasferiti":"we moved","ho deciso":"I decided","ho lavorato":"I worked","stipendio":"wage/salary","prigione":"prison","sono partito":"I left/departed","sono arrivato":"I arrived","barcone":"large boat","mi ha salvato":"saved me"},"questions":[{"q":"Da dove viene Abubakar?","options":["Senegal","Libia","Gambia","Nigeria"],"correct":2,"explanation":"Abubakar è nato a Bakau, in Gambia."},{"q":"Perché ha smesso di studiare a 15 anni?","options":["Non gli piaceva","Doveva lavorare","Hanno arrestato suo padre","Non aveva soldi"],"correct":2,"explanation":"Ha smesso di studiare perché hanno arrestato suo padre per motivi politici."},{"q":"Come è arrivato in Italia?","options":["In aereo","Con un barcone","In treno","Con la macchina"],"correct":1,"explanation":"È partito con un barcone ed è arrivato a Lampedusa dopo tre giorni."},{"q":"Quanto tempo è stato in prigione in Libia?","options":["3-4 mesi","5-6 mesi","8-9 mesi","12 mesi"],"correct":2,"explanation":"Sono stato in prigione 8-9 mesi."}]},
    {"id":"a2-facile-rachida","level":"A2","emoji":"💼","title":"Il Lavoro di Rachida","subtitle":"From Facile A2 — Work, reflexive verbs and daily routine","words":160,"source":"Facile A2","paragraphs":[
        {"italian":"Rachida si sveglia ogni mattina alle sei e mezza. Si alza, si fa la doccia e si veste. Si trucca rapidamente e fa colazione con un caffè e un biscotto. Poi esce di casa alle sette e un quarto.","english":"Rachida wakes up every morning at half past six. She gets up, showers and gets dressed. She puts on make-up quickly and has breakfast with a coffee and a biscuit. Then she leaves the house at quarter past seven."},
        {"italian":"Rachida lavora in un ufficio. Il suo capo si chiama signor Bianchi. Lei si chiama Rachida Ben Ali. Ogni giorno si occupa delle email, risponde al telefono e prepara i documenti. È una donna molto organizzata e puntuale.","english":"Rachida works in an office. Her boss is called Mr Bianchi. She is called Rachida Ben Ali. Every day she deals with emails, answers the phone and prepares documents. She is a very organised and punctual woman."},
        {"italian":"I VERBI RIFLESSIVI al presente:\nio mi sveglio — I wake up\ntu ti svegli — you wake up\nlui/lei si sveglia — he/she wakes up\nnoi ci svegliamo — we wake up\nvoi vi svegliate — you (pl) wake up\nloro si svegliano — they wake up","english":"REFLEXIVE VERBS in present tense:\nI wake up / you wake up / he-she wakes up / we wake up / you (plural) wake up / they wake up\n\nOther reflexive verbs: alzarsi (to get up), vestirsi (to get dressed), lavarsi (to wash), truccarsi (to put on make-up)."},
        {"italian":"AL PASSATO PROSSIMO (verbi riflessivi con ESSERE):\nIeri mattina Rachida si è svegliata alle sei.\nSi è alzata, si è fatta la doccia e si è vestita.\nSi è truccata e ha fatto colazione.\nPoi si è seduta alla scrivania e ha lavorato tutto il giorno.","english":"IN THE PAST (reflexive verbs always use ESSERE):\nYesterday morning Rachida woke up at six.\nShe got up, showered and got dressed.\nShe put on make-up and had breakfast.\nThen she sat at her desk and worked all day."}
    ],"vocab":{"si sveglia":"she wakes up","si alza":"she gets up","si fa la doccia":"she showers","si veste":"she gets dressed","si trucca":"she puts on make-up","fa colazione":"she has breakfast","esce":"she leaves","ufficio":"office","capo":"boss","puntuale":"punctual","organizzata":"organised","si è svegliata":"she woke up (past)"},"questions":[{"q":"A che ora si sveglia Rachida?","options":["Alle 6:00","Alle 6:30","Alle 7:00","Alle 7:15"],"correct":1,"explanation":"Rachida si sveglia alle sei e mezza = 6:30."},{"q":"I verbi riflessivi al passato prossimo usano...?","options":["avere","essere","sia avere che essere","nessuno dei due"],"correct":1,"explanation":"I verbi riflessivi usano sempre ESSERE al passato prossimo. Es: si è svegliata, si è alzata."},{"q":"Dove lavora Rachida?","options":["In un negozio","In una scuola","In un ufficio","In un ospedale"],"correct":2,"explanation":"Rachida lavora in un ufficio. Il suo capo si chiama signor Bianchi."}]},
    # ── ORIGINAL STORIES (A2) ──
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

@app.route('/robots.txt')
def robots():
    return app.send_static_file('robots.txt')


@app.route('/sitemap.xml')
def sitemap():
    return app.send_static_file('sitemap.xml'), 200, {'Content-Type': 'application/xml'}


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
        user_picture=session.get('user_picture', ''),
        apk_url='https://expo.dev/artifacts/eas/rUR4tNTaiRXVHM7Aw1rkbJ.apk'
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
