"""
Prompter
Flask server with single /api/extract endpoint.
Reads brand material, outputs structured brand profile via Claude.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import anthropic
import os
import json

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

SYSTEM_PROMPT = """You are the Prompter InputBot. Your job is to read any brand material and produce a structured one-page brand profile.

This document will be used by both humans and AI to write on-brand communications. Every line must be useful to both audiences simultaneously. Write with precision, not length. If it doesn't change how something gets written, leave it out.

Output exactly five sections as a JSON object with these exact keys: brand, customerFeels, behaviours, examples, houseRules.

BRAND: One short paragraph. Who this brand is, what they stand for, and what that means for the writing. End with a single direction sentence. Maximum four sentences.

CUSTOMER_FEELS: One short paragraph. The reader's emotional state after reading — not the brand's intention. Maximum three sentences.

BEHAVIOURS: Array of exactly five objects with keys "we" and "not". Specific paired contrasts true to this brand only. No generic pairs.

EXAMPLES: Array of exactly five objects with keys "more" and "less". Real sentences — brand voice on left, generic version on right. Include quotation marks.

HOUSE_RULES: Array of objects with keys "key" and "rule". No cap on number. Each rule specific and binary. Cover product names, capitalisation, punctuation, numbers, mandatory inclusions, things that can never appear.

For any section where source material is insufficient, use "[DON'T KNOW YET — reason]" as the value. Never guess. Never pad.

Ignore: photography, logos, colours, internal values, mission statements — anything that doesn't change how words get written.

Respond ONLY with valid JSON. No markdown. No backticks. No preamble."""


@app.route('/api/extract', methods=['POST'])
def extract():
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    brand_name = (data.get('brandName') or 'Brand').strip()

    if not content:
        return jsonify({'error': 'No content provided'}), 400

    if not ANTHROPIC_API_KEY:
        return jsonify({'error': 'API key not configured'}), 500

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": content
            }]
        )

        raw = message.content[0].text
        # Strip any accidental markdown
        clean = raw.replace('```json', '').replace('```', '').strip()
        profile = json.loads(clean)

        return jsonify({'success': True, 'profile': profile, 'brandName': brand_name})

    except json.JSONDecodeError as e:
        print(f'[Prompter] JSON parse error: {e}')
        return jsonify({'error': 'Could not parse AI response'}), 500

    except Exception as e:
        print(f'[Prompter] Error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'service': 'prompter'})


@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
