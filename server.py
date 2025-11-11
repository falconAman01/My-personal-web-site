from flask import Flask, request, jsonify, send_from_directory, abort
import os
from datetime import datetime
from PIL import Image
import json
import socket
import hashlib
from werkzeug.utils import secure_filename
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
UPLOAD_BASE = 'uploads'
THUMBNAIL_DIR = 'thumbnails'
METADATA_FILE = 'photo_metadata.json'

# Create necessary directories
os.makedirs(UPLOAD_BASE, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {
    'images': {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff', 'svg'},
    'documents': {'pdf', 'doc', 'docx', 'txt', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'rtf'},
    'videos': {'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv', 'webm'},
    'audio': {'mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac'},
    'archives': {'zip', 'rar', '7z', 'tar', 'gz', 'bz2'}
}

def get_system_info():
    """Get system hostname and IP address"""
    try:
        hostname = "Aman"
        ip = socket.gethostbyname(hostname)
    except Exception as e:
        hostname = "Unknown"
        ip = "Unknown"
        logger.warning(f"Could not get system info: {e}")
    return hostname, ip

def load_metadata():
    """Load metadata from JSON file with error handling"""
    if os.path.exists(METADATA_FILE):
        try:
            with open(METADATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Validate metadata structure
                if not isinstance(data, dict):
                    logger.warning("Invalid metadata format, creating new")
                    return {}
                return data
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding metadata JSON: {e}")
            # Backup corrupted file
            backup_file = f"{METADATA_FILE}.backup"
            try:
                os.rename(METADATA_FILE, backup_file)
                logger.info(f"Backed up corrupted metadata to {backup_file}")
            except Exception:
                pass
            return {}
        except Exception as e:
            logger.error(f"Error loading metadata: {e}")
            return {}
    return {}

def save_metadata(data):
    """Save metadata to JSON file with error handling"""
    try:
        # Write to temporary file first
        temp_file = f"{METADATA_FILE}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # Replace original file
        if os.path.exists(METADATA_FILE):
            os.replace(temp_file, METADATA_FILE)
        else:
            os.rename(temp_file, METADATA_FILE)
        
        logger.info("Metadata saved successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving metadata: {e}")
        # Clean up temp file
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
        return False

def get_file_size(filepath):
    """Format file size in human-readable format"""
    try:
        size = os.path.getsize(filepath)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"
    except Exception as e:
        logger.warning(f"Error getting file size: {e}")
        return "Unknown"

def is_image(filename):
    """Check if file is an image"""
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS['images']

def get_file_hash(filepath):
    """Generate SHA256 hash of file to detect duplicates"""
    try:
        hash_sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    except Exception as e:
        logger.warning(f"Error generating hash: {e}")
        return None

def scan_all_uploads():
    """Scan all uploaded files and generate metadata"""
    metadata = load_metadata()
    all_files = {}
    
    # Keep existing metadata
    for file_id, data in metadata.items():
        # Verify file still exists
        if 'filepath' in data and os.path.exists(data['filepath']):
            all_files[file_id] = data
        else:
            logger.info(f"File {file_id} no longer exists, removing from metadata")
    
    # Scan for new files
    if os.path.exists(UPLOAD_BASE):
        for folder_name in os.listdir(UPLOAD_BASE):
            folder_path = os.path.join(UPLOAD_BASE, folder_name)
            if os.path.isdir(folder_path):
                for filename in os.listdir(folder_path):
                    filepath = os.path.join(folder_path, filename)
                    if os.path.isfile(filepath):
                        try:
                            file_stat = os.stat(filepath)
                            file_id = f"{folder_name}_{filename}_{file_stat.st_mtime}"
                            
                            if file_id not in all_files:
                                is_img = is_image(filename)
                                thumbnail_filename = None
                                
                                if is_img:
                                    thumbnail_filename = f"{folder_name}_{filename}"
                                    thumbnail_path = os.path.join(THUMBNAIL_DIR, thumbnail_filename)
                                    
                                    if not os.path.exists(thumbnail_path):
                                        create_thumbnail(filepath, thumbnail_path)
                                
                                all_files[file_id] = {
                                    'folder': folder_name,
                                    'filename': filename,
                                    'description': 'Auto-detected file',
                                    'upload_date': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                                    'filepath': filepath,
                                    'thumbnail': thumbnail_filename,
                                    'uploaded_by': 'Unknown',
                                    'system_ip': 'Unknown',
                                    'file_size': get_file_size(filepath),
                                    'is_image': is_img
                                }
                        except Exception as e:
                            logger.error(f"Error processing file {filename}: {e}")
                            continue
    
    save_metadata(all_files)
    return all_files

def create_thumbnail(image_path, thumbnail_path, size=(300, 300)):
    """Create thumbnail for image files with better error handling"""
    try:
        with Image.open(image_path) as img:
            # Convert RGBA to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            elif img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            
            # Create thumbnail
            img.thumbnail(size, Image.Resampling.LANCZOS)
            img.save(thumbnail_path, "JPEG", quality=85, optimize=True)
            
        logger.info(f"Thumbnail created: {thumbnail_path}")
        return True
    except Exception as e:
        logger.error(f"Thumbnail creation failed for {image_path}: {e}")
        return False

def sanitize_filename(filename):
    """Sanitize filename to prevent security issues"""
    if not filename:
        return None
    
    # Get secure filename from werkzeug
    filename = secure_filename(filename)
    
    # Additional sanitization
    filename = "".join(c for c in filename if c.isalnum() or c in ('_', '-', '.'))
    
    # Ensure filename is not empty and has extension
    if not filename or '.' not in filename:
        return None
    
    return filename

def sanitize_foldername(foldername):
    """Sanitize folder name"""
    if not foldername:
        return None
    
    # Remove problematic characters
    foldername = "".join(c for c in foldername if c.isalnum() or c in ('_', '-', ' '))
    foldername = foldername.strip()
    
    # Ensure it's not empty and not too long
    if not foldername or len(foldername) > 100:
        return None
    
    return foldername

@app.route('/')
def index():
    """Serve the main HTML page"""
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error("index.html not found")
        return jsonify({'error': 'Page not found. Please ensure index.html exists.'}), 404
    except Exception as e:
        logger.error(f"Error loading page: {e}")
        return jsonify({'error': f'Could not load page: {str(e)}'}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload with comprehensive error handling"""
    try:
        # Validate request
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded!'}), 400
        
        file = request.files['file']
        foldername = request.form.get('foldername', '').strip()
        description = request.form.get('description', '').strip()
        
        # Validate file
        if not file or file.filename == '':
            return jsonify({'error': 'No file selected!'}), 400
        
        # Validate folder name
        if not foldername:
            return jsonify({'error': 'Name is required!'}), 400
        
        # Get system info
        hostname, ip = get_system_info()
        
        # Sanitize inputs
        foldername = sanitize_foldername(foldername)
        if not foldername:
            return jsonify({'error': 'Invalid name! Use only letters, numbers, spaces, hyphens and underscores.'}), 400
        
        filename = sanitize_filename(file.filename)
        if not filename:
            return jsonify({'error': 'Invalid filename! Please use a proper filename with extension.'}), 400
        
        # Create folder path
        folder_path = os.path.join(UPLOAD_BASE, foldername)
        os.makedirs(folder_path, exist_ok=True)
        
        # Handle duplicate filenames
        base_filename = filename
        counter = 1
        filepath = os.path.join(folder_path, filename)
        
        while os.path.exists(filepath):
            name, ext = os.path.splitext(base_filename)
            filename = f"{name}_{counter}{ext}"
            filepath = os.path.join(folder_path, filename)
            counter += 1
        
        # Save file
        file.save(filepath)
        logger.info(f"File saved: {filepath}")
        
        # Check if it's an image and create thumbnail
        is_img = is_image(filename)
        thumbnail_filename = None
        
        if is_img:
            thumbnail_filename = f"{foldername}_{filename}"
            thumbnail_path = os.path.join(THUMBNAIL_DIR, thumbnail_filename)
            create_thumbnail(filepath, thumbnail_path)
        
        # Save metadata
        metadata = load_metadata()
        file_id = f"{foldername}_{filename}_{datetime.now().timestamp()}"
        
        metadata[file_id] = {
            'folder': foldername,
            'filename': filename,
            'description': description if description else '',
            'upload_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'filepath': filepath,
            'thumbnail': thumbnail_filename,
            'uploaded_by': hostname,
            'system_ip': ip,
            'file_size': get_file_size(filepath),
            'is_image': is_img
        }
        
        if not save_metadata(metadata):
            logger.warning("Metadata save failed, but file uploaded successfully")
        
        return jsonify({
            'success': True,
            'folder': foldername,
            'filename': filename,
            'path': filepath,
            'uploaded_by': hostname,
            'ip': ip,
            'size': get_file_size(filepath)
        }), 200
        
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/gallery')
def gallery():
    """Get all uploaded files with error handling"""
    try:
        all_files = scan_all_uploads()
        
        files = []
        unique_systems = set()
        unique_folders = set()
        
        for file_id, data in all_files.items():
            try:
                files.append({
                    'id': file_id,
                    'folder': data.get('folder', 'Unknown'),
                    'name': data.get('filename', 'Unknown'),
                    'description': data.get('description', ''),
                    'date': data.get('upload_date', 'Unknown'),
                    'thumbnail': data.get('thumbnail', ''),
                    'uploaded_by': data.get('uploaded_by', 'Unknown'),
                    'system_ip': data.get('system_ip', 'Unknown'),
                    'file_size': data.get('file_size', 'Unknown'),
                    'is_image': data.get('is_image', False)
                })
                
                unique_systems.add(data.get('uploaded_by', 'Unknown'))
                unique_folders.add(data.get('folder', 'Unknown'))
            except Exception as e:
                logger.error(f"Error processing file {file_id}: {e}")
                continue
        
        # Sort by date (newest first)
        files.sort(key=lambda x: x.get('date', ''), reverse=True)
        
        return jsonify({
            'files': files,
            'stats': {
                'total_files': len(files),
                'total_folders': len(unique_folders),
                'total_systems': len(unique_systems)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Gallery error: {e}", exc_info=True)
        return jsonify({'error': str(e), 'files': [], 'stats': {'total_files': 0, 'total_folders': 0, 'total_systems': 0}}), 500

@app.route('/thumbnail/<path:filename>')
def serve_thumbnail(filename):
    """Serve thumbnail images with security checks"""
    try:
        # Sanitize filename to prevent directory traversal
        filename = secure_filename(filename)
        
        # Check if file exists
        thumbnail_path = os.path.join(THUMBNAIL_DIR, filename)
        if not os.path.exists(thumbnail_path):
            logger.warning(f"Thumbnail not found: {filename}")
            abort(404)
        
        return send_from_directory(THUMBNAIL_DIR, filename)
    except Exception as e:
        logger.error(f"Thumbnail serve error: {e}")
        abort(404)

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file size limit errors"""
    logger.warning("File too large uploaded")
    return jsonify({'error': 'File is too large! Please upload a smaller file.'}), 413

@app.errorhandler(500)
def internal_server_error(error):
    """Handle internal server errors"""
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error occurred. Please try again.'}), 500

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors"""
    return jsonify({'error': 'Resource not found'}), 404

if __name__ == '__main__':
    print("=" * 60)
    print("📁 UNIVERSAL FILE UPLOAD SERVER")
    print("=" * 60)
    
    hostname, ip = get_system_info()
    print(f"🖥️  System: {hostname}")
    print(f"🌐 IP Address: {ip}")
    print(f"🚀 Local: http://localhost:8000")
    print(f"🚀 Network: http://{ip}:8000")
    print(f"📁 Upload Folder: {os.path.abspath(UPLOAD_BASE)}")
    print(f"🖼️  Thumbnail Folder: {os.path.abspath(THUMBNAIL_DIR)}")
    print("=" * 60)
    print("✅ ALL FILE TYPES SUPPORTED!")
    print("✅ SECURE FILE HANDLING!")
    print("✅ DUPLICATE PREVENTION!")
    print("✅ AUTO THUMBNAILS!")
    print("✅ ERROR RECOVERY!")
    print("=" * 60)
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60)
    
    # Remove file size limit (use with caution in production)
    app.config['MAX_CONTENT_LENGTH'] = None
    
    # Run server
    try:
        app.run(host='0.0.0.0', port=8000, debug=True, threaded=True)
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        print(f"\n❌ Server error: {e}")