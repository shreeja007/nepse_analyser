import pymysql, os
from dotenv import load_dotenv
load_dotenv()
conn = pymysql.connect(
    host=os.getenv('DB_HOST','127.0.0.1'),
    port=int(os.getenv('DB_PORT','3306')),
    db=os.getenv('DB_DATABASE','nepsego'),
    user=os.getenv('DB_USERNAME','root'),
    password=os.getenv('DB_PASSWORD',''),
    charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor
)
cur = conn.cursor()
cur.execute('SHOW TABLES')
tables = [list(r.values())[0] for r in cur.fetchall()]
for t in tables:
    cur.execute(f'DESCRIBE {t}')
    cols = cur.fetchall()
    print(f'--- {t} ---')
    for c in cols:
        print(f"  {c['Field']:40s} {c['Type']:30s} {c['Null']:5s} {c['Key']}")
    print()
conn.close()
