import mysql.connector

# Connect to MySQL Server
try:
    db = mysql.connector.connect(
        host="localhost",
        user="root",
        passwd="Password1234"
    )
    cursor = db.cursor()
    cursor.execute("CREATE DATABASE IF NOT EXISTS agri_crm_db")
    print("Database 'agri_crm_db' created successfully.")
except mysql.connector.Error as err:
    print(f"Error: {err}")
finally:
    if 'db' in locals() and db.is_connected():
        cursor.close()
        db.close()
