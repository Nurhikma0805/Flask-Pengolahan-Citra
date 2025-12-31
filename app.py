from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash
from werkzeug.utils import secure_filename
import os
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import secrets
import sqlite3

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Gunakan path absolut
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['PROCESSED_FOLDER'] = os.path.join(BASE_DIR, 'static', 'processed')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}
app.config['DATABASE'] = os.path.join(BASE_DIR, 'image_processing.db')

# Buat folder jika belum ada
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROCESSED_FOLDER'], exist_ok=True)

# ==================== DATABASE FUNCTIONS ====================

def get_db_connection():
    """Membuat koneksi ke database SQLite"""
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Inisialisasi database dan buat tabel jika belum ada"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            processed_filename TEXT NOT NULL,
            filter_type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✓ Database initialized successfully")

def get_or_create_user(username):
    """Mendapatkan user_id atau membuat user baru jika belum ada"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    
    if user:
        user_id = user['id']
    else:
        cursor.execute('INSERT INTO users (username) VALUES (?)', (username,))
        conn.commit()
        user_id = cursor.lastrowid
        print(f"✓ New user created: {username} (ID: {user_id})")
    
    conn.close()
    return user_id

def save_to_db(user_id, username, original_filename, processed_filename, filter_type):
    """Simpan informasi gambar yang sudah diproses ke database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO processed_images 
        (user_id, username, original_filename, processed_filename, filter_type)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, original_filename, processed_filename, filter_type))
    
    conn.commit()
    image_id = cursor.lastrowid
    conn.close()
    
    print(f"✓ Saved to database: ID={image_id}, User={username}, Filter={filter_type}")
    return image_id

def get_all_from_db():
    """Ambil semua gambar dari database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT username, original_filename as original, 
               processed_filename as processed, filter_type as filter
        FROM processed_images
        ORDER BY created_at DESC
    ''')
    
    images = cursor.fetchall()
    conn.close()
    
    return [dict(img) for img in images]

# ================================================================

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# ==================== ROUTES ====================

@app.route('/')
def index():
    """Halaman utama - input nama"""
    return render_template('index.html')

@app.route('/set_name', methods=['POST'])
def set_name():
    """Simpan nama ke session dan redirect ke halaman pengolahan"""
    username = request.form.get('username', '').strip()
    
    if not username:
        flash('Nama tidak boleh kosong!', 'error')
        return redirect(url_for('index'))
    
    # Simpan ke session
    session['username'] = username
    
    # Simpan user ke database
    user_id = get_or_create_user(username)
    session['user_id'] = user_id
    
    # Set session permanent agar tidak hilang
    session.permanent = True
    
    print(f"✓ Session created for: {username} (ID: {user_id})")
    print(f"✓ Session data: {dict(session)}")
    
    return redirect(url_for('processing'))

@app.route('/processing')
def processing():
    """Halaman pengolahan citra"""
    # Cek session
    if 'username' not in session:
        print("✗ No username in session, redirecting to index")
        print(f"✗ Current session: {dict(session)}")
        flash('Silakan masukkan nama terlebih dahulu!', 'error')
        return redirect(url_for('index'))
    
    print(f"✓ User in session: {session['username']}")
    return render_template('processing.html', 
                         username=session['username'],
                         uploaded_image=session.get('uploaded_image'),
                         processed_image=session.get('processed_image'))

@app.route('/upload', methods=['POST'])
def upload():
    """Handle upload dan proses gambar"""
    print("\n" + "="*60)
    print("UPLOAD REQUEST RECEIVED")
    print(f"Session before upload: {dict(session)}")
    
    # Cek session PERTAMA KALI
    if 'username' not in session:
        print("✗ ERROR: No username in session!")
        flash('Session habis. Silakan login kembali!', 'error')
        return redirect(url_for('index'))
    
    print(f"✓ Username in session: {session['username']}")
    
    # Cek file
    if 'file' not in request.files:
        print("✗ ERROR: No file in request")
        flash('Tidak ada file yang dipilih!', 'error')
        return redirect(url_for('processing'))
    
    file = request.files['file']
    
    if file.filename == '':
        print("✗ ERROR: Empty filename")
        flash('Tidak ada file yang dipilih!', 'error')
        return redirect(url_for('processing'))
    
    if not allowed_file(file.filename):
        print(f"✗ ERROR: File type not allowed: {file.filename}")
        flash(f'Format file tidak diizinkan! Gunakan: {", ".join(app.config["ALLOWED_EXTENSIONS"])}', 'error')
        return redirect(url_for('processing'))
    
    # Simpan file asli
    filename = secure_filename(file.filename)
    timestamp = secrets.token_hex(4)
    original_filename = f"{timestamp}_{filename}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], original_filename)
    
    try:
        file.save(filepath)
        print(f"✓ File saved: {filepath}")
        print(f"✓ File exists: {os.path.exists(filepath)}")
        print(f"✓ File size: {os.path.getsize(filepath)} bytes")
        
        # Simpan info ke session
        session['uploaded_image'] = original_filename
        session['processed_image'] = None
        session.modified = True  # PENTING: Tandai session sudah dimodifikasi
        
        print(f"✓ Session updated: {dict(session)}")
        flash('File berhasil diupload! Pilih filter untuk memproses gambar.', 'success')
        
    except Exception as e:
        print(f"✗ ERROR saving file: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Gagal menyimpan file: {str(e)}', 'error')
    
    print("="*60 + "\n")
    return redirect(url_for('processing'))

@app.route('/process', methods=['POST'])
def process():
    """Proses gambar dengan filter yang dipilih"""
    if 'username' not in session or 'uploaded_image' not in session:
        flash('Silakan upload gambar terlebih dahulu!', 'error')
        return redirect(url_for('processing'))
    
    filter_type = request.form.get('filter', 'grayscale')
    original_filename = session['uploaded_image']
    original_path = os.path.join(app.config['UPLOAD_FOLDER'], original_filename)
    
    if not os.path.exists(original_path):
        flash('File tidak ditemukan! Silakan upload ulang.', 'error')
        return redirect(url_for('processing'))
    
    try:
        # Buka gambar dan konversi ke RGB
        img = Image.open(original_path)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        print(f"\n{'='*50}")
        print(f"PROCESSING IMAGE")
        print(f"Original: {original_path}")
        print(f"Size: {img.size}")
        print(f"Filter: {filter_type.upper()}")
        print(f"{'='*50}\n")
        
        # Terapkan filter
        if filter_type == 'grayscale':
            processed_img = img.convert('L').convert('RGB')
            print(f"✓ Applied GRAYSCALE")
            
        elif filter_type == 'blur':
            processed_img = img.filter(ImageFilter.GaussianBlur(radius=15))
            print(f"✓ Applied BLUR")
            
        elif filter_type == 'sharpen':
            processed_img = img
            for i in range(5):
                processed_img = processed_img.filter(ImageFilter.SHARPEN)
            print(f"✓ Applied SHARPEN 5x")
            
        elif filter_type == 'edge':
            gray = img.convert('L')
            edges = gray.filter(ImageFilter.FIND_EDGES)
            edges_enhanced = ImageEnhance.Contrast(edges).enhance(3.0)
            processed_img = edges_enhanced.convert('RGB')
            print(f"✓ Applied EDGE DETECTION")
            
        elif filter_type == 'brightness':
            enhancer = ImageEnhance.Brightness(img)
            processed_img = enhancer.enhance(3.0)
            print(f"✓ Applied BRIGHTNESS 3.0x")
            
        elif filter_type == 'contrast':
            enhancer = ImageEnhance.Contrast(img)
            processed_img = enhancer.enhance(4.0)
            print(f"✓ Applied CONTRAST 4.0x")
            
        elif filter_type == 'sepia':
            grayscale = img.convert('L')
            processed_img = ImageOps.colorize(grayscale, '#704214', '#C0A080')
            print(f"✓ Applied SEPIA")
            
        elif filter_type == 'negative':
            processed_img = ImageOps.invert(img)
            print(f"✓ Applied NEGATIVE")
            
        else:
            processed_img = img
            print(f"✗ No filter applied")
        
        # Gunakan timestamp unik
        import time
        timestamp = int(time.time() * 1000)
        processed_filename = f"processed_{filter_type}_{timestamp}_{original_filename}"
        processed_path = os.path.join(app.config['PROCESSED_FOLDER'], processed_filename)
        
        # Simpan gambar
        if original_filename.lower().endswith('.png'):
            processed_img.save(processed_path, 'PNG', quality=95)
        else:
            processed_img.save(processed_path, 'JPEG', quality=95)
        
        print(f"✓ Saved to: {processed_path}")
        print(f"{'='*50}\n")
        
        # Simpan ke database SQLite
        save_to_db(
            user_id=session['user_id'],
            username=session['username'],
            original_filename=original_filename,
            processed_filename=processed_filename,
            filter_type=filter_type
        )
        
        session['processed_image'] = processed_filename
        session.modified = True
        
        flash(f'Gambar berhasil diproses dengan filter {filter_type.upper()}!', 'success')
        
    except Exception as e:
        print(f"✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Gagal memproses gambar: {str(e)}', 'error')
    
    return redirect(url_for('processing'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/processed/<filename>')
def processed_file(filename):
    """Serve processed files"""
    return send_from_directory(app.config['PROCESSED_FOLDER'], filename)

@app.route('/results')
def results():
    """Halaman daftar hasil pengolahan"""
    images = get_all_from_db()
    return render_template('results.html', images=images)

@app.route('/clear_history', methods=['POST'])
def clear_history():
    """Hapus semua riwayat pengolahan dan file gambar"""
    try:
        # 1. Hapus semua file di folder uploads
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
                print(f"✓ Deleted upload: {filename}")
        
        # 2. Hapus semua file di folder processed
        for filename in os.listdir(app.config['PROCESSED_FOLDER']):
            file_path = os.path.join(app.config['PROCESSED_FOLDER'], filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
                print(f"✓ Deleted processed: {filename}")
        
        # 3. Hapus semua data dari database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM processed_images')
        cursor.execute('DELETE FROM users')
        conn.commit()
        conn.close()
        
        print("✓ All history cleared from database")
        flash('Semua riwayat berhasil dihapus!', 'success')
        
    except Exception as e:
        print(f"✗ ERROR clearing history: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Gagal menghapus riwayat: {str(e)}', 'error')
    
    return redirect(url_for('results'))

@app.route('/logout')
def logout():
    """Logout dan kembali ke halaman utama"""
    session.clear()
    flash('Anda telah logout.', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    print(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    print(f"Processed folder: {app.config['PROCESSED_FOLDER']}")
    print(f"Database: {app.config['DATABASE']}")
    
    # Inisialisasi database
    init_db()
    
    app.run(debug=True, host='127.0.0.1', port=5000)