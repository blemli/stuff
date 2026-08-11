import flask, flask_caching, flask_limiter, flask_limiter.util as util, logging, logli
import email.message, markupsafe, os, secrets, shutil, smtplib, sqlite3, threading, time

DATA = os.environ.get("DATA", "/data")
FILES, DELETED = f"{DATA}/files", f"{DATA}/deleted"
WEEK, YEAR, GRACE = 7 * 86400, 365 * 86400, 30 * 86400
URL = "https://stuff.problem.li"
SMTP = {k: os.environ.get("SMTP_" + k) for k in ("HOST", "USER", "PASS", "TO")}

app = flask.Flask(__name__)
logli.setup("stuff")
cache = flask_caching.Cache(app, config={"CACHE_TYPE": "SimpleCache"})
limiter = flask_limiter.Limiter(key_func=util.get_remote_address, app=app, storage_uri="memory://")
os.makedirs(FILES, exist_ok=True)
os.makedirs(DELETED, exist_ok=True)
db = sqlite3.connect(f"{DATA}/stuff.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS pending(name TEXT PRIMARY KEY, token TEXT UNIQUE, warned_at REAL)")


def sidecar(name):
    return f"{FILES}/{name}.txt"


def rm(path):
    shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)


def relocate(name, src, dst):  # a file travels with its .txt sidecar
    for n in (name, name + ".txt"):
        if os.path.exists(f"{src}/{n}"):
            shutil.move(f"{src}/{n}", f"{dst}/{n}")
            os.utime(f"{dst}/{n}")


def mail(name, token):
    if os.path.exists(sidecar(name)):
        desc = open(sidecar(name)).read().strip()[:300]
        subject = f"stuff: {name} expires in 30 days"
        body = (f'{name} is a year old — "{desc}"\n\nin 30 days it moves to the deleted folder, a year later it is gone.\n\n'
                f"keep another year: {URL}/keep/{token}\ndelete now:        {URL}/delete/{token}")
    else:
        subject = f"stuff: what is {name}?"
        body = (f"{name} has no description, so it expires: in 30 days it moves to the deleted folder, a year later it is gone.\n\n"
                f"say what it is (upgrades to a year): {URL}/describe/{token}\n"
                f"keep 7 more days:                    {URL}/keep/{token}\n"
                f"delete now:                          {URL}/delete/{token}")
    if not all(SMTP.values()):
        return print("expiry mail (no smtp):", subject, flush=True)
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = SMTP["USER"], SMTP["TO"], subject
    m.set_content(body)
    with smtplib.SMTP(SMTP["HOST"], 587) as s:
        s.starttls()
        s.login(SMTP["USER"], SMTP["PASS"])
        s.send_message(m)


def sweep():  # hourly: warn (1y described, 1w not), to deleted/ 30d later, purge after another year
    while True:
        try:
            now = time.time()
            for name in os.listdir(FILES):
                if name.endswith(".txt") and os.path.exists(f"{FILES}/{name[:-4]}"):
                    continue  # sidecar: lives and dies with its file
                age = now - os.path.getmtime(f"{FILES}/{name}")
                life = YEAR if os.path.exists(sidecar(name)) else WEEK
                row = db.execute("SELECT token, warned_at FROM pending WHERE name=?", (name,)).fetchone()
                if row and age < life:  # re-uploaded or described since the warning: clock reset
                    db.execute("DELETE FROM pending WHERE name=?", (name,))
                elif not row and age >= life:
                    token = secrets.token_urlsafe(32)
                    db.execute("INSERT INTO pending VALUES(?,?,?)", (name, token, now))
                    mail(name, token)
                    logging.warning(f"{name} expires, mail sent")
                elif row and now - row[1] >= GRACE:
                    relocate(name, FILES, DELETED)
                    logging.warning(f"{name} moved to deleted")
            for name in os.listdir(DELETED):
                if now - os.path.getmtime(f"{DELETED}/{name}") >= YEAR:
                    rm(f"{DELETED}/{name}")
                    db.execute("DELETE FROM pending WHERE name=?", (name,))
                    logging.warning(f"{name} purged")
            db.commit()
        except Exception as e:
            logging.error(f"sweep: {e}")
        time.sleep(3600)


threading.Thread(target=sweep, daemon=True).start()
logging.info("boot")


@app.route("/")
@limiter.limit("70/minute, 1000/hour")
@cache.cached()
def index():
    return flask.Response("stuff — put it somewhere\n\n"
                          "upload:   sftp upload@stuff.problem.li (into upload/)\n"
                          "          say what foo.zip is in a foo.zip.txt sidecar — undescribed stuff lives a week, described a year\n"
                          "download: https://stuff.problem.li/<filename>\n\n"
                          "before anything expires, info@ gets a keep-or-delete mail.\n", mimetype="text/plain")


@app.route("/favicon.svg")
@app.route("/stuff.svg")
def favicon():
    return flask.send_from_directory(app.root_path, "stuff.svg")


@app.route("/up")
def up():
    return "OK", 200


@app.route("/keep/<token>")
@limiter.limit("10/minute")
def keep(token):
    row = db.execute("SELECT name FROM pending WHERE token=?", (token,)).fetchone()
    if not row:
        flask.abort(404)
    name = row[0]
    relocate(name, DELETED, FILES)
    if not os.path.exists(f"{FILES}/{name}"):
        flask.abort(410)
    os.utime(f"{FILES}/{name}")  # keep = reset the clock
    db.execute("DELETE FROM pending WHERE token=?", (token,))
    db.commit()
    logging.warning(f"{name} kept")
    return f"{name} kept\n"


@app.route("/delete/<token>")
@limiter.limit("10/minute")
def delete(token):
    row = db.execute("SELECT name FROM pending WHERE token=?", (token,)).fetchone()
    if not row:
        flask.abort(404)
    for n in (row[0], row[0] + ".txt"):
        for d in (FILES, DELETED):
            if os.path.exists(f"{d}/{n}"):
                rm(f"{d}/{n}")
    db.execute("DELETE FROM pending WHERE token=?", (token,))
    db.commit()
    logging.warning(f"{row[0]} deleted by mail click")
    return f"{row[0]} deleted\n"


@app.route("/describe/<token>", methods=["GET", "POST"])
@limiter.limit("10/minute")
def describe(token):
    row = db.execute("SELECT name FROM pending WHERE token=?", (token,)).fetchone()
    if not row:
        flask.abort(404)
    name = row[0]
    if flask.request.method == "GET":
        return (f"<title>stuff</title><h2>what is {markupsafe.escape(name)}?</h2>"
                '<form method="post"><input name="d" size="60" autofocus required> <button>save</button></form>')
    relocate(name, DELETED, FILES)  # describing = caring: restore if already in deleted
    if not os.path.exists(f"{FILES}/{name}"):
        flask.abort(410)
    open(sidecar(name), "w").write(flask.request.form["d"].strip() + "\n")
    os.utime(f"{FILES}/{name}")
    db.execute("DELETE FROM pending WHERE token=?", (token,))
    db.commit()
    logging.warning(f"{name} described")
    return f"{name} described, lives a year now\n"


@app.route("/<path:name>")
@limiter.limit("120/minute, 3000/hour")
def fetch(name):
    return flask.send_from_directory(FILES, name)  # exact names only, no listing anywhere


if __name__ == "__main__":
    app.run(port=8080, debug=True)
