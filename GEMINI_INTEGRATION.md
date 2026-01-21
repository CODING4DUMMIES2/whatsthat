# Google Gemini Studio API Integration Reference

## API Key Configuration

The Google Gemini Studio API key is already configured in `app.py`:
```python
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyCoEGIY014EkDxvgbs7yg69ODLYlkVTMtI")
```

## Image Upload Pattern

Reference code snippet for uploading images to Gemini:

```python
# src/mix_images.py
def remix_images(image_paths: list[str], prompt: str, output_dir: str):
    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    contents = _load_image_parts(image_paths)
    contents.append(genai.types.Part.from_text(text=prompt))

    stream = client.models.generate_content_stream(
        model="gemini-2.5-flash-image-preview",
        contents=contents,
        config=generate_content_config,
    )

    _process_api_stream_response(stream, output_dir)
```

## Helper Functions

### Load Image Parts
```python
def _load_image_parts(image_paths: list[str]) -> list[types.Part]:
    parts = []
    for image_path in image_paths:
        with open(image_path, "rb") as f:
            image_data = f.read()
            mime_type = _get_mime_type(image_path)
            parts.append(
                types.Part(inline_data=types.Blob(data=image_data,
                                                  mime_type=mime_type))
            )
    return parts
```

### Get MIME Type
```python
import mimetypes

def _get_mime_type(file_path: str) -> str:
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type or "image/png"
```

## Required Dependencies

To use Gemini API, add to `requirements.txt`:
```
google-genai>=0.2.0
```

## Integration Points

### Existing Image Upload System

The app already has image upload functionality for venue logos:
- Route: `/venue/<venue_id>/upload-logo` (POST)
- Storage: `venue_logos/` directory
- Current implementation: `app.py` lines 2656-2686

### Potential Use Cases

1. **Logo Enhancement**: Use Gemini to enhance or remix venue logos
2. **QR Code Customization**: Generate custom QR code backgrounds based on venue logos
3. **Image Analysis**: Analyze venue images for branding consistency
4. **Content Generation**: Generate promotional images or graphics

## Example Integration

```python
from google import genai
import os

def process_venue_logo_with_gemini(venue_id, prompt):
    """Process venue logo with Gemini API"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    
    client = genai.Client(api_key=api_key)
    
    # Load venue logo
    venue = venue_metadata.get(venue_id)
    if not venue or not venue.get('logo_path'):
        return None
    
    logo_path = os.path.join(VENUE_LOGOS_DIR, venue['logo_path'])
    
    # Load image and create content
    with open(logo_path, 'rb') as f:
        image_data = f.read()
    
    contents = [
        genai.types.Part.from_bytes(data=image_data, mime_type="image/png"),
        genai.types.Part.from_text(text=prompt)
    ]
    
    # Generate content
    response = client.models.generate_content(
        model="gemini-2.5-flash-image-preview",
        contents=contents
    )
    
    return response
```

## Notes

- Model: `gemini-2.5-flash-image-preview` (for image processing)
- API Key: Set `GEMINI_API_KEY` environment variable in Railway for production
- Current Status: API key configured, ready for implementation
