import json
import time
from pathlib import Path
from urllib.parse import urljoin

import gradio as gr
import requests


# =========================================================
# LMM MUSIC 設定
# =========================================================

ACE_STEP_API = "http://127.0.0.1:8001"

APP_HOST = "127.0.0.1"
APP_PORT = 7861

OUTPUT_DIR = Path("generated")
OUTPUT_DIR.mkdir(exist_ok=True)


# =========================================================
# ACE-Step API 通信
# =========================================================

def check_api():
    """
    ACE-Step APIが起動しているか確認する。
    """

    try:
        response = requests.get(
            f"{ACE_STEP_API}/health",
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        return data.get("data", {}).get("status") == "ok"

    except Exception:
        return False


def api_post(
    endpoint: str,
    payload: dict,
    timeout: int = 300,
):
    """
    ACE-Step APIへPOST。

    release_taskはモデルやサーバー状態によって
    返答に時間がかかる場合があるため、
    30秒ではなく5分待つ。
    """

    response = requests.post(
        f"{ACE_STEP_API}{endpoint}",
        json=payload,
        timeout=timeout,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("code") not in (None, 200):
        error = data.get(
            "error",
            "ACE-Step APIでエラーが発生しました。",
        )

        raise RuntimeError(error)

    return data


# =========================================================
# AI用プロンプト生成
# =========================================================

def build_prompt(
    purpose: str,
    description: str,
    genre: str,
    moods: list[str] | None,
    instrumental: bool,
):
    parts = []

    if purpose:
        parts.append(
            f"Purpose: {purpose}"
        )

    if description:
        parts.append(
            f"Creative direction: {description}"
        )

    if genre:
        parts.append(
            f"Genre: {genre}"
        )

    if moods:
        parts.append(
            "Mood: " + ", ".join(moods)
        )

    if instrumental:
        parts.append(
            "Instrumental music with no vocals."
        )

    parts.append(
        "Professional modern music production. "
        "Detailed arrangement with layered instrumentation, "
        "strong drums, bass, harmony, melody, "
        "dynamic progression, transitions, "
        "and a memorable climax."
    )

    return ". ".join(parts)


# =========================================================
# 生成結果を待つ
# =========================================================

def wait_for_result(
    task_id: str,
    progress=None,
):
    """
    ACE-Stepのタスクが完了するまで確認する。

    status:
      0 = 生成中
      1 = 成功
      2 = 失敗
    """

    # 最大20分
    max_wait_seconds = 1200

    start_time = time.time()

    last_status_text = ""

    while True:

        elapsed = time.time() - start_time

        if elapsed >= max_wait_seconds:
            raise TimeoutError(
                "音楽生成が20分を超えたため停止しました。"
            )

        try:

            response = api_post(
                "/query_result",
                {
                    "task_id_list": [task_id]
                },
                timeout=60,
            )

            results = response.get(
                "data",
                [],
            )

            if not results:
                time.sleep(2)
                continue

            job = results[0]

            status = job.get(
                "status",
                0,
            )

            # ---------------------------------------------
            # 生成中
            # ---------------------------------------------

            if status == 0:

                elapsed_text = (
                    f"生成中... "
                    f"{int(elapsed)}秒経過"
                )

                if progress and elapsed_text != last_status_text:
                    progress(
                        None,
                        desc=elapsed_text,
                    )

                    last_status_text = elapsed_text

                time.sleep(2)

                continue

            # ---------------------------------------------
            # 成功
            # ---------------------------------------------

            if status == 1:

                raw_result = job.get(
                    "result",
                    "[]",
                )

                if isinstance(
                    raw_result,
                    str,
                ):
                    result = json.loads(
                        raw_result
                    )
                else:
                    result = raw_result

                if not result:
                    raise RuntimeError(
                        "ACE-Stepから生成結果が返ってきませんでした。"
                    )

                return result[0]

            # ---------------------------------------------
            # 失敗
            # ---------------------------------------------

            if status == 2:

                error_result = job.get(
                    "result",
                    "",
                )

                raise RuntimeError(
                    "ACE-Stepで音楽生成に失敗しました。\n"
                    f"{error_result}"
                )

            time.sleep(2)

        except requests.RequestException as exc:

            raise RuntimeError(
                "ACE-Step APIとの通信に失敗しました。\n"
                f"{exc}"
            ) from exc


# =========================================================
# 音源ダウンロード
# =========================================================

def download_audio(
    file_url: str,
    task_id: str,
):

    if file_url.startswith(
        "http://"
    ) or file_url.startswith(
        "https://"
    ):
        audio_url = file_url

    else:
        audio_url = urljoin(
            ACE_STEP_API,
            file_url,
        )

    response = requests.get(
        audio_url,
        timeout=300,
    )

    response.raise_for_status()

    output_path = (
        OUTPUT_DIR /
        f"{task_id}.mp3"
    )

    output_path.write_bytes(
        response.content
    )

    return output_path


# =========================================================
# 音楽生成
# =========================================================

def generate_music(
    purpose,
    description,
    duration,
    genre,
    moods,
    instrumental,
    progress=gr.Progress(),
):

    # ---------------------------------------------
    # 入力チェック
    # ---------------------------------------------

    if not purpose and not description:

        raise gr.Error(
            "用途か曲のイメージを入力してください。"
        )

    # ---------------------------------------------
    # API確認
    # ---------------------------------------------

    progress(
        0.02,
        desc="ACE-Stepとの接続を確認中...",
    )

    if not check_api():

        raise gr.Error(
            "ACE-Step APIが起動していません。\n\n"
            "ACE-Step側を先に起動してください。"
        )

    # ---------------------------------------------
    # 長さ
    # ---------------------------------------------

    duration_map = {
        "10秒": 10,
        "30秒": 30,
        "60秒": 60,
        "90秒": 90,
    }

    audio_duration = duration_map.get(
        duration,
        30,
    )

    # ---------------------------------------------
    # プロンプト
    # ---------------------------------------------

    prompt = build_prompt(
        purpose=purpose,
        description=description,
        genre=genre,
        moods=moods,
        instrumental=instrumental,
    )

    # ---------------------------------------------
    # ACE-Stepへ送信
    # ---------------------------------------------

    progress(
        0.05,
        desc="音楽の設計を作成中...",
    )

    payload = {
        "prompt": prompt,

        "model": "acestep-v15-turbo",

        "audio_duration": audio_duration,

        "audio_format": "mp3",

        "batch_size": 1,

        "inference_steps": 8,

        "thinking": True,

        "use_cot_caption": True,

        "use_cot_language": True,

        "lm_model_path": (
            "acestep-5Hz-lm-0.6B"
        ),

        "backend": "pt",
    }

    try:

        progress(
            0.08,
            desc="ACE-Stepへ送信中...",
        )

        # 5分待つ
        task_response = api_post(
            "/release_task",
            payload,
            timeout=300,
        )

        task_data = task_response.get(
            "data",
            {},
        )

        task_id = task_data.get(
            "task_id"
        )

        if not task_id:

            raise RuntimeError(
                "ACE-StepからタスクIDを取得できませんでした。\n"
                f"{task_response}"
            )

        print(
            f"[LMM MUSIC] Task ID: {task_id}"
        )

        # ---------------------------------------------
        # 生成待ち
        # ---------------------------------------------

        progress(
            0.10,
            desc="音楽を生成中...",
        )

        result = wait_for_result(
            task_id,
            progress=progress,
        )

        # ---------------------------------------------
        # 音源取得
        # ---------------------------------------------

        progress(
            0.95,
            desc="音源を保存中...",
        )

        file_url = result.get(
            "file"
        )

        if not file_url:

            raise RuntimeError(
                "生成された音源ファイルが見つかりません。"
            )

        output_path = download_audio(
            file_url,
            task_id,
        )

        # ---------------------------------------------
        # メタ情報
        # ---------------------------------------------

        metas = result.get(
            "metas",
            {},
        ) or {}

        bpm = metas.get(
            "bpm",
            "-",
        )

        keyscale = metas.get(
            "keyscale",
            "-",
        )

        real_duration = metas.get(
            "duration",
            audio_duration,
        )

        genres = metas.get(
            "genres",
            genre or "-",
        )

        time_signature = metas.get(
            "timesignature",
            "4",
        )

        # ---------------------------------------------
        # 結果表示
        # ---------------------------------------------

        result_markdown = f"""
## 🎵 生成完了

### 音楽情報

**ジャンル**  
{genres}

**BPM**  
{bpm}

**Key**  
{keyscale}

**拍子**  
{time_signature}/4

**長さ**  
{real_duration}秒

**モデル**  
ACE-Step 1.5

**タスクID**  
`{task_id}`
"""

        progress(
            1.0,
            desc="完成！",
        )

        return (
            str(output_path),
            result_markdown,
            prompt,
        )

    except requests.Timeout:

        raise gr.Error(
            "ACE-Stepからの応答がタイムアウトしました。\n\n"
            "生成処理がまだ動いている可能性があります。"
            "ACE-Step側の画面も確認してください。"
        )

    except requests.HTTPError as exc:

        raise gr.Error(
            "ACE-Step APIでHTTPエラーが発生しました。\n\n"
            f"{exc}"
        )

    except Exception as exc:

        raise gr.Error(
            str(exc)
        )


# =========================================================
# デザイン
# =========================================================

CSS = """
body {
    background: #090a0f;
}

.gradio-container {
    max-width: 1180px !important;
    margin: auto !important;
}

#main-title {
    text-align: center;
    margin-top: 25px;
    margin-bottom: 5px;
}

#main-subtitle {
    text-align: center;
    opacity: 0.65;
    margin-bottom: 30px;
}

.generate-button {
    min-height: 58px !important;
    font-size: 18px !important;
    font-weight: 700 !important;
}

.panel {
    border-radius: 18px !important;
}
"""


# =========================================================
# UI
# =========================================================

with gr.Blocks(
    title="LMM MUSIC",
    theme=gr.themes.Base(),
    css=CSS,
) as demo:

    gr.Markdown(
        "# ♪ LMM MUSIC",
        elem_id="main-title",
    )

    gr.Markdown(
        "動画やコンテンツに合わせた音楽を作る",
        elem_id="main-subtitle",
    )

    with gr.Row():

        # =================================================
        # 左側
        # =================================================

        with gr.Column(
            scale=1,
            variant="panel",
            elem_classes=["panel"],
        ):

            gr.Markdown(
                "## MUSIC BRIEF"
            )

            purpose = gr.Textbox(
                label="用途",
                placeholder=(
                    "例：VALORANT大会の決勝ハイライト"
                ),
            )

            description = gr.Textbox(
                label="曲のイメージ",
                placeholder=(
                    "例：最初は緊張感。"
                    "徐々に盛り上がって最後に爆発。"
                    "重いキックとシンセを使いたい。"
                ),
                lines=5,
            )

            duration = gr.Radio(
                label="曲の長さ",
                choices=[
                    "10秒",
                    "30秒",
                    "60秒",
                    "90秒",
                ],
                value="30秒",
            )

            genre = gr.Dropdown(
                label="ジャンル",
                choices=[
                    "EDM",
                    "Cinematic",
                    "Electronic",
                    "Rock",
                    "Hip-Hop",
                    "Pop",
                    "Ambient",
                    "Drum & Bass",
                ],
                value="EDM",
            )

            moods = gr.CheckboxGroup(
                label="雰囲気",
                choices=[
                    "Epic",
                    "Energetic",
                    "Dark",
                    "Aggressive",
                    "Emotional",
                    "Cinematic",
                    "Uplifting",
                    "Tense",
                ],
            )

            instrumental = gr.Checkbox(
                label="ボーカルなし",
                value=True,
            )

            generate_button = gr.Button(
                "✨ 音楽を作る",
                variant="primary",
                elem_classes="generate-button",
            )

        # =================================================
        # 右側
        # =================================================

        with gr.Column(
            scale=1,
            variant="panel",
            elem_classes=["panel"],
        ):

            gr.Markdown(
                "## YOUR TRACK"
            )

            result_audio = gr.Audio(
                label="生成された音楽",
                type="filepath",
                interactive=False,
            )

            result_info = gr.Markdown(
                "ここに生成結果が表示されます。"
            )

            gr.Markdown(
                "## AI PROMPT"
            )

            generated_prompt = gr.Textbox(
                label="実際にAIへ送った指示",
                lines=8,
                interactive=False,
            )

    # =====================================================
    # ボタン
    # =====================================================

    generate_button.click(
        fn=generate_music,
        inputs=[
            purpose,
            description,
            duration,
            genre,
            moods,
            instrumental,
        ],
        outputs=[
            result_audio,
            result_info,
            generated_prompt,
        ],
    )


# =========================================================
# 起動
# =========================================================

if __name__ == "__main__":

    demo.launch(
        server_name=APP_HOST,
        server_port=APP_PORT,
        show_error=True,
    )
