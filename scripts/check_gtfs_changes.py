"""
File to check and update the gtfs directory as translink updates the static files every week
"""
import hashlib
import os
import shutil
import datetime
import subprocess

# Directories
STATIC_GTFS_DIR = "data/gtfs_static/"  # Current GTFS static data
STATIC_ARCHIVE_DIR = "data/static_archive/"  #  old GTFS files will be moved
STATIC_SOURCE_DIR = "data/static/"  #  new GTFS updates are stored
HASH_FILE = "database/gtfs_hashes.txt"
PROCESS_SCRIPT = "scripts/process_static.py"

#helpers
def get_latest_gtfs_folder():
    """Finds the most recent GTFS static folder in 'static/'."""
    subfolders = [f for f in os.listdir(STATIC_SOURCE_DIR) if os.path.isdir(os.path.join(STATIC_SOURCE_DIR, f))]
    if not subfolders:
        print("No GTFS static folders found in 'static/'.")
        return None
    latest_folder = max(subfolders)  
    return os.path.join(STATIC_SOURCE_DIR, latest_folder)

def hash_file(file_path):
    """Compute SHA256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(4096):
            hasher.update(chunk)
    return hasher.hexdigest()

def compute_folder_hash(folder):
    """Compute hashes for all key GTFS files in a folder."""
    hashes = {}
    for filename in ["stop_times.txt", "trips.txt", "routes.txt", "stops.txt"]:
        file_path = os.path.join(folder, filename)
        if os.path.exists(file_path):
            hashes[filename] = hash_file(file_path)
    return hashes

def check_gtfs_changes():
    """Compares the newest GTFS static files with the current version."""
    latest_gtfs_dir = get_latest_gtfs_folder()
    if not latest_gtfs_dir:
        return False

    new_hashes = compute_folder_hash(latest_gtfs_dir)
    old_hashes = compute_folder_hash(STATIC_GTFS_DIR)

    changes_detected = False
    for filename, new_hash in new_hashes.items():
        old_hash = old_hashes.get(filename, None)
        if new_hash != old_hash:
            print(f"⚠️ Change detected in {filename}!")
            changes_detected = True

    if changes_detected:
        archive_old_gtfs()
        move_new_gtfs(latest_gtfs_dir)
        update_hash_file(new_hashes)

        print("Processing new GTFS static data...")
        subprocess.run(["python", PROCESS_SCRIPT])

        return True 

    print("No changes detected in GTFS static files.")
    return False 

def archive_old_gtfs():
    """Move the current GTFS static data to an archive before replacing it."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d")
    archive_path = os.path.join(STATIC_ARCHIVE_DIR, f"GTFS_{timestamp}")

    if not os.path.exists(STATIC_ARCHIVE_DIR):
        os.makedirs(STATIC_ARCHIVE_DIR)

    shutil.move(STATIC_GTFS_DIR, archive_path)
    os.makedirs(STATIC_GTFS_DIR)  
    print(f"Archived old GTFS files to {archive_path}")

def move_new_gtfs(latest_gtfs_dir):
    """Replace old GTFS static files with the newest GTFS static files."""
    for filename in os.listdir(latest_gtfs_dir):
        src_path = os.path.join(latest_gtfs_dir, filename)
        dest_path = os.path.join(STATIC_GTFS_DIR, filename)
        shutil.copy2(src_path, dest_path)  
    print(f"Updated GTFS static with files from {latest_gtfs_dir}")

def update_hash_file(new_hashes):
    """Update the hash file with the latest GTFS file hashes."""
    with open(HASH_FILE, "w") as f:
        for filename, new_hash in new_hashes.items():
            f.write(f"{filename},{new_hash}\n")
    print("Hash file updated.")

if __name__ == "__main__":
    check_gtfs_changes()
    
    