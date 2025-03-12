from flask import Flask, render_template, request, redirect, session, flash, url_for, Response
from flask_mysqldb import MySQL
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# MySQL Configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'new_password'
app.config['MYSQL_DB'] = 'loan_app'
app.config['MYSQL_UNIX_SOCKET'] = '/opt/lampp/var/mysql/mysql.sock'
app.config['UPLOAD_FOLDER'] = 'uploads'

mysql = MySQL(app)

# Ensure the upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Helper Functions
def get_db_cursor():
    return mysql.connection.cursor()

def commit_db():
    mysql.connection.commit()

def fetch_user_role():
    return session.get('role')

def is_user_logged_in():
    return 'user_id' in session

def is_admin_logged_in():
    return is_user_logged_in() and fetch_user_role() == 'admin'

# Routes
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    session.clear()  # Clear session before login

    if request.method == 'POST':
        identifier = request.form['username']  # Now used as email or phone
        password = request.form['password']
        role = request.form['role']

        print(f"Attempting login as {role} with identifier: {identifier}")  # Debug statement

        cursor = get_db_cursor()
        if role == 'user':
            query = "SELECT * FROM users WHERE email=%s OR phone=%s"
            cursor.execute(query, (identifier, identifier))
        elif role == 'admin':
            query = "SELECT * FROM admins WHERE email=%s OR phone=%s"
            cursor.execute(query, (identifier, identifier))
        else:
            flash("Invalid role selected", "danger")
            return render_template('login.html')

        user = cursor.fetchone()
        cursor.close()

        print(f"Query result: {user}")  # Debug statement

        if user:
            stored_password = user[3]  # Ensure this is the correct index
            print(f"Stored password: {stored_password}")  # Debug statement
            print(f"Entered password: {password}")  # Debug statement

            if stored_password == password:  # Direct comparison (for demo only)
                session['user_id'] = user[0]
                session['role'] = role
                flash("Login successful!", "success")
                return redirect(url_for('admin' if role == 'admin' else 'dashboard'))
            else:
                flash("Invalid Credentials", "danger")
        else:
            flash("Invalid Credentials", "danger")

    return render_template('login.html')
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session or session.get('role') != 'user':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('login'))

    cursor = mysql.connection.cursor()

    try:
        # Fetch the latest application for the logged-in user
        cursor.execute(
            "SELECT * FROM applications WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
            (session['user_id'],)
        )
        application = cursor.fetchone()

        # Fetch the loan balance from the loan_applications table
        cursor.execute(
            "SELECT balance FROM loan_applications WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
            (session['user_id'],)
        )
        loan = cursor.fetchone()
        loan_balance = loan[0] if loan else 0.00  # Default to 0.00 if no loan exists

        return render_template(
            'dashboard.html',
            application=application,
            loan_balance=loan_balance
        )

    except Exception as e:
        print(f"Error: {e}")
        flash("An error occurred while fetching your dashboard data.", "danger")
        return redirect(url_for('login'))

    finally:
        cursor.close()
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        phone = request.form['phone']
        password = request.form['password']  # Store password in plain text (not recommended)

        cursor = get_db_cursor()
        try:
            cursor.execute("INSERT INTO users (email, phone, password) VALUES (%s, %s, %s)", (email, phone, password))
            commit_db()
            flash("Registration Successful! Please log in.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            flash(f"Registration failed: {str(e)}", "danger")
        finally:
            cursor.close()

    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))

@app.route('/upload_documents', methods=['GET', 'POST'])
def upload_documents():
    if not is_user_logged_in():
        flash("Please log in first", "warning")
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            name = request.form['name']
            id_number = request.form['id_number']
            user_id = session['user_id']

            # Get file data
            id_front_file = request.files['id_front']
            id_back_file = request.files['id_back']
            mpesa_statement_file = request.files['mpesa_statement']
            selfie_file = request.files['selfie']

            cursor = get_db_cursor()

            # Insert all file types into a single row
            cursor.execute(
                '''
                INSERT INTO applications (
                    user_id, name, id_number,
                    id_front_file_name, id_front_file_data,
                    id_back_file_name, id_back_file_data,
                    selfie_file_name, selfie_file_data,
                    mpesa_statement_file_name, mpesa_statement_file_data
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''',
                (
                    user_id, name, id_number,
                    id_front_file.filename, id_front_file.read(),
                    id_back_file.filename, id_back_file.read(),
                    selfie_file.filename, selfie_file.read(),
                    mpesa_statement_file.filename, mpesa_statement_file.read()
                )
            )

            commit_db()
            cursor.close()

            flash("Documents received. Please wait for verification.", "success")
            return redirect(url_for('apply_loan'))
        except Exception as e:
            flash(f"Error uploading documents: {str(e)}", "danger")

    return render_template('upload_documents.html')

@app.route('/apply_loan')
def apply_loan():
    if not is_user_logged_in() or fetch_user_role() != 'user':
        flash("Please log in first", "warning")
        return redirect(url_for('login'))

    application = None  # Default value if no application exists

    try:
        user_id = session.get('user_id')  
        if not user_id:
            flash("Session expired. Please log in again.", "warning")
            return redirect(url_for('login'))

        cursor = get_db_cursor()
        query = """
            SELECT status, max_amount, rejection_reason 
            FROM applications 
            WHERE user_id = %s 
            ORDER BY created_at DESC 
            LIMIT 1
        """
        cursor.execute(query, (user_id,))
        application = cursor.fetchone()
        cursor.close()  # Ensure the cursor is closed

        if application:
            print("✅ Latest Application:", application)  # Debugging statement
            print("✅ Application Status:", application[0])  # Debugging statement
        else:
            print("❌ No loan application found.")  # Debug message

    except Exception as e:
        print("❌ Error fetching loan application:", str(e))
        flash("An error occurred while fetching loan application details.", "danger")

    return render_template('apply_loan.html', application=application)

@app.route('/loan_application_form')
def loan_application_form():
    if not is_user_logged_in() or fetch_user_role() != 'user':
        flash("Please log in first", "warning")
        return redirect(url_for('login'))

    cursor = get_db_cursor()

    try:
        # Check if the user has a pending loan application
        cursor.execute(
            "SELECT id FROM loan_applications WHERE user_id = %s AND status = 'pending'",
            (session['user_id'],)
        )
        has_pending_application = cursor.fetchone() is not None

        # Fetch the user's maximum loan amount
        cursor.execute(
            "SELECT max_amount FROM applications WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
            (session['user_id'],)
        )
        application = cursor.fetchone()

        if not application or not application[0]:
            flash("Your application has not been verified yet.", "danger")
            return redirect(url_for('apply_loan'))

        max_amount = int(application[0])  # Convert Decimal to integer

        return render_template(
            'loan_application_form.html',
            has_pending_application=has_pending_application,
            max_amount=max_amount
        )

    except Exception as e:
        print(f"Error: {e}")
        flash("An error occurred while fetching loan application details.", "danger")
        return redirect(url_for('apply_loan'))

    finally:
        cursor.close()

@app.route('/submit_loan_application', methods=['POST'])
def submit_loan_application():
    if not is_user_logged_in():
        flash("Please log in first", "warning")
        return redirect(url_for('login'))

    cursor = get_db_cursor()

    try:
        # Check if the user already has a pending loan application
        cursor.execute(
            "SELECT id FROM loan_applications WHERE user_id = %s AND status = 'pending'",
            (session['user_id'],)
        )
        pending_application = cursor.fetchone()

        if pending_application:
            flash("You already have a pending loan application. Please wait for processing.", "warning")
            return redirect(url_for('apply_loan'))

        # Get form data
        loan_amount = float(request.form['loan_amount'])
        payment_method = request.form['payment_method']
        loan_period = int(request.form['loan_period'])
        bank_details = request.form.get('bank_details')
        mpesa_details = request.form.get('mpesa_details')

        # Fetch the user's maximum loan amount
        cursor.execute(
            "SELECT max_amount FROM applications WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
            (session['user_id'],)
        )
        application = cursor.fetchone()
        max_amount = float(application[0])

        # Validate loan amount
        if loan_amount < 1 or loan_amount > max_amount:
            flash(f"Please choose an amount within your range (1 KSh to {max_amount} KSh).", "danger")
            return redirect(url_for('loan_application_form'))

        # Calculate total amount with interest (e.g., 5% interest rate)
        interest_rate = 5.0
        total_amount = loan_amount * (1 + interest_rate / 100)

        # Set the initial balance equal to the total amount
        balance = total_amount

        # Insert the loan application into the database
        cursor.execute(
            """
            INSERT INTO loan_applications (
                user_id, loan_amount, interest_rate, total_amount, payment_method, bank_details, mpesa_details, loan_period, balance, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            """,
            (
                session['user_id'], loan_amount, interest_rate, total_amount, payment_method,
                bank_details, mpesa_details, loan_period, balance
            )
        )
        commit_db()

        flash("Thank you! Your loan application has been received. Please wait for processing (less than 24 hours).", "success")
        return redirect(url_for('apply_loan'))

    except Exception as e:
        print(f"Error: {e}")
        flash("An error occurred while processing your request.", "danger")
        return redirect(url_for('loan_application_form'))

    finally:
        cursor.close()

@app.route('/admin')
def admin():
    if not is_admin_logged_in():
        flash("Unauthorized access!", "danger")
        return redirect(url_for('login'))

    cursor = get_db_cursor()
    query = """
        SELECT 
            a.id AS application_id,
            a.user_id,
            a.name,
            a.id_number,
            a.id_front_file_name,
            a.id_front_file_data,
            a.id_back_file_name,
            a.id_back_file_data,
            a.selfie_file_name,
            a.selfie_file_data,
            a.mpesa_statement_file_name,
            a.mpesa_statement_file_data,
            a.status,
            u.email,
            u.phone
        FROM applications a
        JOIN users u ON a.user_id = u.id
        WHERE a.status = 'pending' AND a.archived = FALSE  -- Only fetch non-archived pending applications
        ORDER BY a.id
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    cursor.close()

    # Group documents by application_id
    applications = {}
    for row in rows:
        application_id = row[0]
        if application_id not in applications:
            applications[application_id] = {
                'user_id': row[1],
                'name': row[2],
                'id_number': row[3],
                'status': row[12],
                'email': row[13],
                'phone': row[14],
                'documents': {
                    'id_front': {
                        'file_name': row[4],
                        'file_data': row[5]
                    },
                    'id_back': {
                        'file_name': row[6],
                        'file_data': row[7]
                    },
                    'selfie': {
                        'file_name': row[8],
                        'file_data': row[9]
                    },
                    'mpesa_statement': {
                        'file_name': row[10],
                        'file_data': row[11]
                    }
                }
            }

    return render_template('admin.html', applications=applications)

@app.route('/get_document/<int:application_id>/<document_type>')
def get_document(application_id, document_type):
    if not is_admin_logged_in():
        flash("Unauthorized access!", "danger")
        return redirect(url_for('login'))

    cursor = get_db_cursor()
    if document_type == 'id_front':
        query = "SELECT id_front_file_data FROM applications WHERE id = %s"
    elif document_type == 'id_back':
        query = "SELECT id_back_file_data FROM applications WHERE id = %s"
    elif document_type == 'selfie':
        query = "SELECT selfie_file_data FROM applications WHERE id = %s"
    elif document_type == 'mpesa_statement':
        query = "SELECT mpesa_statement_file_data FROM applications WHERE id = %s"
    else:
        flash("Invalid document type", "danger")
        return redirect(url_for('admin'))

    cursor.execute(query, (application_id,))
    document_data = cursor.fetchone()
    cursor.close()

    if not document_data or not document_data[0]:
        flash("Document not found", "danger")
        return redirect(url_for('admin'))
    # Determine the MIME type based on the document type
    if document_type in ['id_front', 'id_back', 'selfie']:
        mime_type = 'image/jpeg'  # Assuming images are in JPEG format
    elif document_type == 'mpesa_statement':
        mime_type = 'application/pdf'  # Assuming M-Pesa statement is a PDF
    else:
        flash("Invalid document type", "danger")
        return redirect(url_for('admin'))

    # Return the document as a response
    return Response(document_data[0], mimetype=mime_type)

@app.route('/admin/action/<int:application_id>/<action>', methods=['POST'])
def admin_action(application_id, action):
    if not is_admin_logged_in():
        flash("Unauthorized access!", "danger")
        return redirect(url_for('login'))

    cursor = None
    try:
        cursor = get_db_cursor()

        if action == 'verify':
            max_amount = request.form.get('max_amount')
            if not max_amount:
                flash("Please enter the maximum amount the borrower can get.", "danger")
                return redirect(url_for('admin'))
            
            # Update the application status to 'approved' and set max_amount
            cursor.execute(
                "UPDATE applications SET status = 'approved', max_amount = %s WHERE id = %s",
                (max_amount, application_id)
            )
            flash("Application approved!", "success")
        
        elif action == 'reject':
            rejection_reason = request.form.get('rejection_reason')
            if not rejection_reason:
                flash("Please provide a reason for rejection.", "danger")
                return redirect(url_for('admin'))
            
            # Update the application status to 'rejected' and set rejection_reason
            cursor.execute(
                "UPDATE applications SET status = 'rejected', rejection_reason = %s WHERE id = %s",
                (rejection_reason, application_id)
            )
            flash("Application rejected!", "success")
        
        else:
            flash("Invalid action", "danger")
            return redirect(url_for('admin'))

        # Archive the application after processing
        cursor.execute("UPDATE applications SET archived = TRUE WHERE id = %s", (application_id,))
        commit_db()  # Commit changes to the database

    except Exception as e:
        print(f"Error: {e}")
        flash("An error occurred while processing your request.", "danger")
    finally:
        if cursor:
            cursor.close()

    return redirect(url_for('admin'))
@app.route('/repay_loan')
def repay_loan_form():
    if not is_user_logged_in():
        flash("Please log in first", "warning")
        return redirect(url_for('login'))

    cursor = get_db_cursor()

    try:
        # Fetch the user's active loan
        cursor.execute(
            """
            SELECT total_amount, paid_amount, balance 
            FROM loan_applications 
            WHERE user_id = %s AND status = 'approved' AND balance > 0
            ORDER BY created_at DESC 
            LIMIT 1
            """,
            (session['user_id'],)
        )
        loan = cursor.fetchone()

        if loan:
            loan = {
                'total_amount': loan[0],
                'paid_amount': loan[1],
                'balance': loan[2]
            }
        else:
            loan = None

        return render_template('repay_loan.html', loan=loan)

    except Exception as e:
        print(f"Error: {e}")
        flash("An error occurred while fetching loan details.", "danger")
        return redirect(url_for('dashboard'))

    finally:
        cursor.close()

@app.route('/repay_loan', methods=['POST'])
def repay_loan():
    if not is_user_logged_in():
        flash("Please log in first", "warning")
        return redirect(url_for('login'))

    cursor = get_db_cursor()

    try:
        # Fetch the user's active loan
        cursor.execute(
            """
            SELECT id, total_amount, paid_amount, balance 
            FROM loan_applications 
            WHERE user_id = %s AND status = 'approved' AND balance > 0
            ORDER BY created_at DESC 
            LIMIT 1
            """,
            (session['user_id'],)
        )
        loan = cursor.fetchone()

        if not loan:
            flash("No active loan found.", "warning")
            return redirect(url_for('repay_loan_form'))

        loan_id, total_amount, paid_amount, balance = loan

        # Get the payment amount from the form
        amount = float(request.form['amount'])

        # Validate the payment amount
        if amount <= 0:
            flash("Please enter a valid amount.", "danger")
            return redirect(url_for('repay_loan_form'))

        if amount > balance:
            flash(f"You cannot pay more than the remaining balance (KSh {balance}).", "danger")
            return redirect(url_for('repay_loan_form'))

        # Update the loan details
        new_paid_amount = paid_amount + amount
        new_balance = balance - amount

        cursor.execute(
            """
            UPDATE loan_applications 
            SET paid_amount = %s, balance = %s 
            WHERE id = %s
            """,
            (new_paid_amount, new_balance, loan_id)
        )
        commit_db()

        flash(f"Payment of KSh {amount} received. Remaining balance: KSh {new_balance}.", "success")
        return redirect(url_for('repay_loan_form'))

    except Exception as e:
        print(f"Error: {e}")
        flash("An error occurred while processing your payment.", "danger")
        return redirect(url_for('repay_loan_form'))

    finally:
        cursor.close()

@app.route('/contact_us')
def contact_us():
    return render_template('contact_us.html')

@app.route('/about_us')
def about_us():
    return render_template('about_us.html')

if __name__ == '__main__':
    app.run(debug=True)