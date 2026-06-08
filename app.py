"""
Prompter v5
Single-stage consultation model.
Dot reads material, asks targeted questions, builds profile through conversation.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import anthropic
import os
import json
import io
import requests as req
from bs4 import BeautifulSoup
from prompts import CONSULT_PROMPT, EXTRACT_PROMPT, CONFIRM_PROMPT, SUMMARISE_PROMPT

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')


def extract_text_from_pdf(file_bytes):
    import pdfplumber
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return '\n\n'.join(text_parts)


def extract_text_from_docx(file_bytes):
    from docx import Document
    doc = Document(io.BytesIO(file_bytes))
    return '\n\n'.join([p.text for p in doc.paragraphs if p.text.strip()])


def extract_text_from_url(url):
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; Prompter/1.0)'}
    resp = req.get(url, headers=headers, timeout=12)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'lxml')
    for tag in soup(['script','style','nav','footer','header','aside','form','iframe']):
        tag.decompose()
    blocks = []
    for tag in soup.find_all(['h1','h2','h3','h4','p','li','blockquote']):
        text = tag.get_text(strip=True)
        if text and len(text) > 20:
            blocks.append(text)
    return '\n\n'.join(blocks)


@app.route('/api/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    filename = file.filename or 'unknown'
    file_bytes = file.read()
    try:
        ext = filename.rsplit('.', 1)[-1].lower()
        if ext == 'pdf':
            text = extract_text_from_pdf(file_bytes)
        elif ext in ('docx', 'doc'):
            text = extract_text_from_docx(file_bytes)
        else:
            return jsonify({'error': f'Unsupported file type: {ext}'}), 400
        if not text.strip():
            return jsonify({'error': 'Could not extract text from file'}), 400
        return jsonify({'success': True, 'filename': filename, 'text': text})
    except Exception as e:
        print(f'[Prompter] Upload error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/fetch', methods=['POST'])
def fetch_url():
    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    if not url.startswith('http'):
        url = 'https://' + url
    try:
        text = extract_text_from_url(url)
        if not text.strip():
            return jsonify({'error': 'Could not extract text from that URL'}), 400
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace('www.', '')
        filename = f'{domain} (website)'
        return jsonify({'success': True, 'filename': filename, 'text': text})
    except req.exceptions.Timeout:
        return jsonify({'error': 'That URL timed out.'}), 400
    except req.exceptions.RequestException as e:
        return jsonify({'error': f'Could not reach that URL: {str(e)}'}), 400
    except Exception as e:
        print(f'[Prompter] Fetch error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/consult', methods=['POST'])
def consult():
    data = request.get_json() or {}
    files = data.get('files', [])
    history = data.get('history', [])

    if not files:
        return jsonify({'error': 'No files provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        # Build file context
        file_context = "Brand material provided:\n\n"
        for f in files:
            file_context += f"--- {f['filename']} ---\n{f['text'][:3000]}\n\n"

        system = CONSULT_PROMPT + "\n\n" + file_context

        # Build message history
        messages = []
        for h in history:
            messages.append({'role': h['role'], 'content': h['content']})

        # If no history, trigger first observation
        if not messages:
            messages = [{'role': 'user', 'content': 'Please read the material and start.'}]

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=system,
            messages=messages
        )

        raw = response.content[0].text
        clean = raw.replace('```json', '').replace('```', '').strip()
        result = json.loads(clean)

        return jsonify({
            'success': True,
            'message': result.get('message', ''),
            'ready': result.get('ready', False)
        })

    except json.JSONDecodeError as e:
        print(f'[Prompter] Consult JSON error: {e}')
        return jsonify({'error': 'Could not parse response'}), 500
    except Exception as e:
        print(f'[Prompter] Consult error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/extract', methods=['POST'])
def extract():
    data = request.get_json() or {}
    files = data.get('files', [])
    history = data.get('history', [])

    if not files:
        return jsonify({'error': 'No content provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        calibration = data.get('calibration', [])
        labelled = [f"--- SOURCE: {f['filename']} ---\n{f['text']}" for f in files]
        user_content = "\n\n".join(labelled)

        if history:
            convo = "\n".join([f"{'Dot' if h['role']=='assistant' else 'User'}: {h['content']}" for h in history])
            user_content += f"\n\n--- CONSULTATION NOTES ---\n{convo}"

        if calibration:
            cal_text = "\n\n--- CALIBRATION DATA ---\n"
            for i, c in enumerate(calibration):
                cal_text += f"Check {i+1} ({c.get('dimension','')}): A='{c.get('sentenceA','')}' B='{c.get('sentenceB','')}' Slider={c.get('value',50)}/100 (0=fully A, 100=fully B)\n"
            user_content += cal_text

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=EXTRACT_PROMPT,
            messages=[{'role': 'user', 'content': user_content}]
        )

        raw = response.content[0].text
        clean = raw.replace('```json', '').replace('```', '').strip()
        profile = json.loads(clean)

        return jsonify({'success': True, 'profile': profile, 'brandName': profile.get('brandName', 'Brand')})

    except json.JSONDecodeError as e:
        print(f'[Prompter] Extract JSON error: {e}')
        return jsonify({'error': 'Could not parse AI response'}), 500
    except Exception as e:
        print(f'[Prompter] Extract error: {e}')
        return jsonify({'error': str(e)}), 500



@app.route('/api/confirm', methods=['POST'])
def confirm():
    data = request.get_json() or {}
    files = data.get('files', [])
    history = data.get('history', [])

    if not files:
        return jsonify({'error': 'No files provided'}), 400
    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        file_context = "Brand material:\n\n"
        for f in files:
            file_context += f"--- {f['filename']} ---\n{f['text'][:2500]}\n\n"

        convo = ""
        if history:
            convo = "\n\nConsultation so far:\n" + "\n".join([
                f"{'Dot' if h['role']=='assistant' else 'User'}: {h['content']}"
                for h in history
            ])

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1200,
            system=CONFIRM_PROMPT,
            messages=[{'role': 'user', 'content': file_context + convo}]
        )

        raw = message.content[0].text
        clean = raw.replace('```json', '').replace('```', '').strip()
        result = json.loads(clean)

        return jsonify({'success': True, 'checks': result.get('checks', [])})

    except json.JSONDecodeError as e:
        print(f'[Prompter] Confirm JSON error: {e}')
        return jsonify({'error': 'Could not parse response'}), 500
    except Exception as e:
        print(f'[Prompter] Confirm error: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'service': 'prompter'})


@app.route('/api/summarise', methods=['POST'])
def summarise():
    data = request.get_json() or {}
    text = (data.get('text') or '').strip()[:500]
    if not text:
        return jsonify({'success': True, 'label': 'Notes'})
    if not ANTHROPIC_API_KEY:
        return jsonify({'success': True, 'label': 'Notes'})
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=20,
            system=SUMMARISE_PROMPT,
            messages=[{'role': 'user', 'content': text}]
        )
        label = message.content[0].text.strip()
        return jsonify({'success': True, 'label': label})
    except Exception as e:
        print(f'[Prompter] Summarise error: {e}')
        return jsonify({'success': True, 'label': 'Notes'})


@app.route('/api/opening', methods=['GET'])
def opening():
    return jsonify({
        'success': True,
        'message': "How you talk is who you are. Drop in an example and let's chat."
    })


@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
