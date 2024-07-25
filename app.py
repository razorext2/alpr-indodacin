from flask import Flask, render_template, send_from_directory, redirect, url_for, request, session, jsonify
import os
from flask_mysqldb import MySQL,MySQLdb
from flask_bcrypt import Bcrypt
from werkzeug.wrappers import response
from alpr.alpr import alpr
from route.admin import admin
from route.user import user

app = Flask(__name__)
app.secret_key = "alpr"

bcrypt = Bcrypt(app)

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'flaskdb'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

@app.route("/")
def index():
    return render_template('index.html')

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        curl = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        curl.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = curl.fetchone()
        curl.close()

        if user:
            if bcrypt.check_password_hash(user['password'], password):
                session['logged_in'] = 'logged in'
                session['fname'] = user['fname']
                session['lname'] = user['lname']
                session['privilege'] = user['privilege']
                session['email'] = user['email']
                data = {'status': 1, 'message': 'You are successfully logged in'}
                return jsonify(data)
            else:
                data = {'status': 0, 'message': 'Invalid email or password'}
                return jsonify(data)
        else:
            data = {'status': 0, 'message': 'Invalid email or password'}
            return jsonify(data)
    else:
        return render_template('login.html')

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == 'GET':
        return render_template('signup.html')
    else:
        cur = mysql.connection.cursor()
        
        email = request.form['email']
        check = cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        
        if check:
            cur.close()  # Close cursor
            data = {'status': 0, 'message': 'Email already taken'}
            return jsonify(data)  # Return a JSON response
        
        fname = request.form['first_name']
        lname = request.form['last_name']
        password = request.form['password']
        hash_password = bcrypt.generate_password_hash(password).decode('utf-8')

        try:
            insert = cur.execute("INSERT INTO users (fname, lname, email, password) VALUES (%s, %s, %s, %s)", 
                                 (fname, lname, email, hash_password))
            mysql.connection.commit()
            if insert:
                session['fname'] = fname
                session['lname'] = lname
                session['email'] = email
                data = {'status': 1, 'message': 'Congratulations, your account has been successfully created.'}
            else:
                data = {'status': 0, 'message': 'Account creation failed'}
        except Exception as e:
            mysql.connection.rollback()  # Rollback in case of error
            data = {'status': 0, 'message': f'An error occurred: {str(e)}'}
        finally:
            cur.close()  # Close cursor
        
        return jsonify(data)  # Return a JSON response

@app.route("/dashboard")
def dashboard():
    data = {}
    data['title'] = 'Dashboard'
    if session.get('logged_in') and session.get('privilege') == '1':
        curl = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        curl.execute("SELECT count(*) as total FROM users where privilege=0")
        data['user'] = curl.fetchone()
        print(data['user'])
        curl.execute("SELECT count(*) as total FROM users where privilege=1")
        data['admin'] = curl.fetchone()
        curl.execute("SELECT count(*) as total FROM apps")
        data['apps'] = curl.fetchone()
        curl.execute("SELECT count(*) as total FROM license_plate")
        data['lp'] = curl.fetchone()
        curl.close()
        return render_template('admin/index.html', data=data)
    elif session.get('logged_in') and session.get('privilege') == '0':
        curl = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        curl.execute("SELECT * FROM users where email='"+session.get('email')+"'")
        users = curl.fetchone()
        curl.execute("SELECT * FROM apps WHERE user_id='%s'", (users['id'],))
        data['apps'] = curl.fetchall()
        curl.execute("SELECT * FROM `license_plate` LEFT JOIN apps on apps.id = license_plate.app_id LEFT JOIN users on users.id = apps.user_id WHERE user_id='%s'", (users['id'],))
        data['lp_total'] = curl.fetchall()
        curl.close()
        return render_template('user/index.html' , data=data)
    else:
        return redirect(url_for('login'))

@app.route('/logout', methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

app.register_blueprint(alpr, url_prefix='/api')
app.register_blueprint(admin, url_prefix='/manage')
app.register_blueprint(user, url_prefix='/user')

if __name__ == "__main__":
    app.run(debug=True)