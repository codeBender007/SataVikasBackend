import sqlite3

# Connect to database
conn = sqlite3.connect("app.db")
cursor = conn.cursor()

# Get all user-created tables except 'users'
cursor.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type='table'
      AND name NOT LIKE 'sqlite_%'
      AND name != 'users'
""")

tables = cursor.fetchall()

# Delete data from every table except 'users'
for (table_name,) in tables:
    cursor.execute(f'DELETE FROM "{table_name}"')
    # cursor.execute(f'DELETE FROM users')
    print(f"Deleted data from: {table_name}")

# Save changes
conn.commit()

# Close database
conn.close()

print("\nAll table data except 'users' deleted successfully!")