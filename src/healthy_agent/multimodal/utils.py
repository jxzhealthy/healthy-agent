"""Multimodal utility functions"""

import base64
import mimetypes
from pathlib import Path
from typing import Union
import httpx
from .attachment import ImageAttachment


def encode_image_to_base64(file_path: Union[str, Path]) -> str:
    """
    Read image file and encode to base64
    
    Args:
        file_path: Image file path
        
    Returns:
        Base64 encoded string
    """
    path = Path(file_path)
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def detect_media_type(file_path: Union[str, Path]) -> str:
    """
    Detect media type based on file extension
    
    Args:
        file_path: File path
        
    Returns:
        MIME type string, e.g. "image/png"
    """
    path = Path(file_path)
    media_type, _ = mimetypes.guess_type(str(path))
    return media_type or "application/octet-stream"


async def fetch_image_url(url: str) -> ImageAttachment:
    """
    Download image URL and convert to base64
    
    Args:
        url: Image URL
        
    Returns:
        ImageAttachment instance
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        
        # Get content-type
        media_type = response.headers.get("content-type", "image/png")
        
        # Base64 encode
        base64_data = base64.b64encode(response.content).decode("utf-8")
        
        # Extract filename from URL
        filename = url.split("/")[-1].split("?")[0] or None
        
        return ImageAttachment(
            content_type="image",
            filename=filename,
            url=url,
            base64_data=base64_data,
            media_type=media_type,
            size_bytes=len(response.content)
        )


def extract_text_from_file(file_path: Union[str, Path]) -> str:
    """
    Extract text content from file
    
    Args:
        file_path: File path
        
    Returns:
        Extracted text content, binary files return description string
    """
    path = Path(file_path)
    
    # Supported plain text extensions
    text_extensions = {'.txt', '.md', '.py', '.json', '.csv', '.yaml', '.yml', 
                       '.xml', '.html', '.htm', '.css', '.js', '.ts', '.jsx', 
                       '.tsx', '.java', '.c', '.cpp', '.h', '.hpp', '.go', 
                       '.rs', '.rb', '.php', '.sql', '.sh', '.bash', '.zsh'}
    
    ext = path.suffix.lower()
    
    if ext in text_extensions:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except (UnicodeDecodeError, IOError):
            # If reading fails, try to handle as binary
            pass
    
    # Binary file or read failure
    size = path.stat().st_size if path.exists() else 0
    filename = path.name
    return f"[Binary file: {filename}, {size} bytes]"
