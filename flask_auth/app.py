from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import psycopg2
from sqlalchemy import create_engine, text
import requests
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Supabase 연결 설정
SUPABASE_URL = 'postgresql://postgres.ejhasfwebwaexlprpssc:vjtmxmqnehdtks@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres'

def get_supabase_data():
    """Supabase에서 데이터를 가져오는 함수"""
    try:
        # psycopg2로 직접 연결
        conn = psycopg2.connect(SUPABASE_URL)
        
        cur = conn.cursor()
        tables_data = {}
        
        # 모든 테이블 이름 조회
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        
        table_names = [row[0] for row in cur.fetchall()]
        
        # 각 테이블의 데이터 조회
        for table_name in table_names:
            try:
                # 테이블 컬럼 정보 조회
                cur.execute(f"""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = '{table_name}' 
                    AND table_schema = 'public'
                    ORDER BY ordinal_position
                """)
                
                columns = cur.fetchall()
                
                # 테이블 데이터 조회 (대소문자 구분을 위해 쌍따옴표 사용)
                cur.execute(f'SELECT * FROM "{table_name}" LIMIT 100')
                rows = cur.fetchall()
                
                tables_data[table_name] = {
                    'columns': columns,
                    'rows': [list(row) for row in rows],
                    'count': len(rows)
                }
                
            except Exception as e:
                tables_data[table_name] = {
                    'error': str(e),
                    'columns': [],
                    'rows': [],
                    'count': 0
                }
        
        cur.close()
        conn.close()
        return tables_data
            
    except Exception as e:
        return {'error': f'Supabase 연결 오류: {str(e)}'}

def create_tables():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="test").first():
            u = User(username="test", password=generate_password_hash("1234"))
            db.session.add(u)
            db.session.commit()

@app.route('/')
@login_required
def index():
    # Supabase에서 데이터 가져오기
    tables_data = get_supabase_data()
    return render_template('index.html', username=current_user.username, tables_data=tables_data)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        
        if not user_message:
            return jsonify({'error': '메시지가 없습니다.'}), 400
        
        # Ollama API 호출 (환경변수에서 URL 읽기)
        ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434/api/generate')
        ollama_data = {
            'model': 'llama3.1:8b',
            'prompt': f"당신은 부동산 회사 퍼스트부동산의 부동산 전문 상담사입니다. 다음 질문에 친절하고 전문적으로 답변해주세요:\n\n{user_message}",
            'stream': False,
            'options': {
                'num_predict': 200,  # 응답 길이 제한
                'temperature': 0.7,
                'top_p': 0.9
            }
        }
        
        print(f"Ollama 요청: {ollama_url}")
        print(f"요청 데이터: {ollama_data}")
        
        response = requests.post(
            ollama_url,
            json=ollama_data,
            headers={'Content-Type': 'application/json'},
            timeout=120
        )
        
        print(f"응답 상태 코드: {response.status_code}")
        print(f"응답 내용: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            ai_response = result.get('response', '죄송합니다. 응답을 생성할 수 없습니다.')
            return jsonify({'response': ai_response})
        else:
            return jsonify({'error': f'AI 서비스 오류 (상태 코드: {response.status_code})'}), 500
            
    except requests.exceptions.Timeout:
        print("Timeout 에러 발생")
        return jsonify({'error': '응답 시간이 초과되었습니다. 다시 시도해주세요.'}), 500
    except requests.exceptions.RequestException as e:
        print(f"Request 에러: {e}")
        return jsonify({'error': 'AI 서비스 연결 오류가 발생했습니다.'}), 500
    except Exception as e:
        print(f"일반 에러: {e}")
        return jsonify({'error': '서버 오류가 발생했습니다.'}), 500

if __name__ == '__main__':
    create_tables()
    app.run(debug=True, host='0.0.0.0', port=5001)
