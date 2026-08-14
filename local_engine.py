from __future__ import annotations

from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS


# =========================================================
# LMM MUSIC LOCAL ENGINE
# =========================================================

APP_HOST = "127.0.0.1"
APP_PORT = 8765

ACE_STEP_API = "http://127.0.0.1:8001"

OUTPUT_DIR = Path("generated")
OUTPUT_DIR.mkdir(exist_ok=True)


app = Flask(__name__)

CORS(
    app,
    resources={
        r"/*": {
            "origins": "*",
        }
    },
)


# =========================================================
# Health
# =========================================================

@app.get("/health")
def health():
    ace_step = False

    try:
        response = requests.get(
            f"{ACE_STEP_API}/health",
            timeout=5,
        )

        ace_step = (
            response.status_code == 200
        )

    except Exception:
        ace_step = False

    return jsonify(
        {
            "status": "ok",
            "engine": "LMM MUSIC Local Engine",
            "ace_step": ace_step,
            "host": APP_HOST,
            "port": APP_PORT,
        }
    )


# =========================================================
# Device
# =========================================================

@app.get("/device")
def device():
    return jsonify(
        {
            "local_engine": True,
            "ace_step": True,
            "engine_name": "LMM MUSIC Local Engine",
            "message": (
                "このPCではローカル生成エンジンを"
                "利用できます。"
            ),
        }
    )


# =========================================================
# Generate
# =========================================================

@app.post("/generate")
def generate():
    data = request.get_json(
        silent=True
    )

    if not data:
        return jsonify(
            {
                "error": "JSONがありません。"
            }
        ), 400

    try:
        # ACE-Stepにはフォーム形式で転送
        response = requests.post(
            f"{ACE_STEP_API}/release_task",
            data=data,
            timeout=300,
        )

        if response.status_code >= 400:

            try:
                detail = response.json()

            except Exception:
                detail = response.text

            return jsonify(
                {
                    "error": (
                        "ACE-Step APIで"
                        "エラーが発生しました。"
                    ),
                    "detail": detail,
                }
            ), response.status_code

        return jsonify(
            response.json()
        )

    except requests.RequestException as exc:

        return jsonify(
            {
                "error": (
                    "ACE-Step APIに"
                    "接続できませんでした。"
                ),
                "detail": str(exc),
            }
        ), 500


# =========================================================
# Query Result
# =========================================================

@app.post("/query_result")
def query_result():
    data = request.get_json(
        silent=True
    )

    if not data:
        return jsonify(
            {
                "error": "JSONがありません。"
            }
        ), 400

    try:
        response = requests.post(
            f"{ACE_STEP_API}/query_result",
            json=data,
            timeout=60,
        )

        if response.status_code >= 400:

            try:
                detail = response.json()

            except Exception:
                detail = response.text

            return jsonify(
                {
                    "error": (
                        "ACE-Stepの結果取得で"
                        "エラーが発生しました。"
                    ),
                    "detail": detail,
                }
            ), response.status_code

        return jsonify(
            response.json()
        )

    except requests.RequestException as exc:

        return jsonify(
            {
                "error": (
                    "ACE-Step APIから"
                    "結果を取得できませんでした。"
                ),
                "detail": str(exc),
            }
        ), 500


# =========================================================
# Audio
# =========================================================

@app.get("/audio")
def audio():
    filename = request.args.get(
        "file"
    )

    if not filename:
        return jsonify(
            {
                "error": (
                    "fileが指定されていません。"
                )
            }
        ), 400

    path = (
        OUTPUT_DIR /
        Path(filename).name
    )

    if not path.is_file():
        return jsonify(
            {
                "error": "音源が見つかりません。"
            }
        ), 404

    return send_file(
        path,
        as_attachment=True,
    )


# =========================================================
# Main
# =========================================================

if __name__ == "__main__":

    print("=" * 60)
    print("LMM MUSIC LOCAL ENGINE")
    print("=" * 60)

    print(
        f"Local Engine: "
        f"http://{APP_HOST}:{APP_PORT}"
    )

    print(
        f"ACE-Step API: "
        f"{ACE_STEP_API}"
    )

    print("=" * 60)

    app.run(
        host=APP_HOST,
        port=APP_PORT,
        debug=False,
    )
