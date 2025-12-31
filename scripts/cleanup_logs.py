#!/usr/bin/env python3
"""
Cleanup script to remove log files older than 7 days.
Run this as a cron job or manually.
"""
import os
import time
from pathlib import Path

LOG_DIR = Path("logs")
RETENTION_DAYS = 7
RETENTION_SECONDS = RETENTION_DAYS * 24 * 60 * 60


def cleanup_old_logs():
    """Remove log files older than retention period."""
    if not LOG_DIR.exists():
        print(f"Log directory {LOG_DIR} does not exist")
        return
    
    current_time = time.time()
    removed_count = 0
    total_size_freed = 0
    
    for log_file in LOG_DIR.iterdir():
        if not log_file.is_file():
            continue
        
        # Skip if file is too new
        file_age = current_time - log_file.stat().st_mtime
        if file_age < RETENTION_SECONDS:
            continue
        
        # Remove old log file
        file_size = log_file.stat().st_size
        try:
            log_file.unlink()
            removed_count += 1
            total_size_freed += file_size
            print(f"Removed: {log_file.name} ({file_size / 1024 / 1024:.2f} MB)")
        except Exception as e:
            print(f"Error removing {log_file.name}: {e}")
    
    if removed_count > 0:
        print(f"\n✅ Cleanup complete: {removed_count} files removed, {total_size_freed / 1024 / 1024:.2f} MB freed")
    else:
        print("✅ No old log files to remove")


if __name__ == "__main__":
    cleanup_old_logs()
