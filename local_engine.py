from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_file


# =========================================================
# LMM MUSIC LOCAL ENGINE
# =========================================================

APP_HOST = "127.0.0.1"
APP_PORT = 8765

ACE_STEP_API = "http://127.0.0.1:8001"

OUTPUT_DIR = Path("generated")
OUTPUT_DIR.mkdir(exist_ok=True)


app = Flask(__name__)


# =========================================================
# Health
# =========================================================

@app.get("/health")
def health():
    """
    LMM Engine自体が動いているか確認。
    """

    ace_step = False

    try:
        response = requests.get(
            f"{ACE_STEP_API}/health",
            timeout=3,
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
    """
    今後、実際のローカル生成能力をここへ追加する。
    """

    return jsonify(
        {
            "local_engine": True,
            "recommended": "local",
            "message": (
                "このPCでローカル生成エンジンが"
                "利用可能です。"
            ),
        }
    )


# =========================================================
# Generate
# =========================================================

@app.post("/generate")
def generate():
    """
    現段階ではACE-Step APIへの橋渡し。

    後で、
    - GPU生成
    - CPU生成
    - モデル選択
    - 180秒の分割生成
    などをここで管理する。
    """

    data = request.get_json(
        silent=True
    )

    if not data:
        return jsonify(
            {
                "error": "JSONがありません。"
            }
        ), 400

    if not Path.exists(
        Path(".")
    ):
        return jsonify(
            {
                "error": "Engine directory error"
            }
        ), 500

    try:

        response = requests.post(
            f"{ACE_STEP_API}/release_task",
            json=data,
            timeout=300,
        )

        response.raise_for_status()

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
                "error": "fileが指定されていません。"
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
        f"Local Engine:"
        f" http://{APP_HOST}:{APP_PORT}"
    )

    print(
        f"ACE-Step API:"
        f" {ACE_STEP_API}"
    )

    print("=" * 60)

    app.run(
        host=APP_HOST,
        port=APP_PORT,
        debug=False,
    )
