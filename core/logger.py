"""
Centralized logging configuration.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

from core.config import settings


def setup_logger(
    name: str,
    log_file: Optional[str] = None,
    level: Optional[str] = None
) -> logging.Logger:
    """
    Set up a logger with console and optional file handlers.
    
    Args:
        name: Logger name (usually __name__)
        log_file: Optional log file path
        level: Log level (defaults to settings.log_level)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    log_level = getattr(logging, (level or settings.log_level).upper())
    logger.setLevel(log_level)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler with rotation (optional)
    if log_file:
        log_path = Path("logs") / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Use TimedRotatingFileHandler: rotate daily, keep 7 days of logs
        file_handler = TimedRotatingFileHandler(
            filename=str(log_path),
            when='midnight',  # Rotate at midnight
            interval=1,  # Every day
            backupCount=7,  # Keep 7 days of logs
            encoding="utf-8"
        )
        file_handler.setLevel(log_level)
        file_formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger
