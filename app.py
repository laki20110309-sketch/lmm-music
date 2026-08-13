import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

import gradio as gr
import requests


# =========================================================
# 基本設定
# =========================================================

ACE_STEP_API = "http://127.0.0.1:8001"

APP_HOST = "127.0.0.1"
APP_PORT = 7861

OUTPUT_DIR = Path("generated")
REFERENCE_DIR = Path("reference_audio")

OUTPUT_DIR.mkdir(exist_ok=True)
REFERENCE_DIR.mkdir(exist_ok=True)

MAX_REFERENCE_SIZE = 50 * 1024 * 1024  # 50MB


# =========================================================
# ACE-Step API
# =========================================================

def check_api():
    try:
        response = requests.get(
            f"{ACE_STEP_API}/health",
            timeout=10,
        )

        response.raise_for_status()

        data = response.json()

        return data.get("code") == 200

    except Exception:
        return False


def api_post_json(
    endpoint: str,
    payload: dict,
    timeout: int = 300,
):
    response = requests.post(
        f"{ACE_STEP_API}{endpoint}",
        json=payload,
        timeout=timeout,
    )

    if response.status_code >= 400:
        try:
            error_data = response.json()
        except Exception:
            error_data = response.text

        raise RuntimeError(
            "ACE-Step API Error\n\n"
            f"HTTP: {response.status_code}\n\n"
            f"{error_data}"
        )

    data = response.json()

    if data.get("code") not in (None, 200):
        raise RuntimeError(
            data.get(
                "error",
                "ACE-Step APIでエラーが発生しました。",
            )
        )

    return data


def api_post_reference_audio(
    fields: dict,
    reference_path: str,
    timeout: int = 300,
):
    """
    ACE-Step公式APIのmultipart/form-data方式で
    reference_audioを送信する。
    """

    path = Path(reference_path)

    if not path.is_file():
        raise RuntimeError(
            f"参照音声が見つかりません:\n{path}"
        )

    file_size = path.stat().st_size

    if file_size <= 0:
        raise RuntimeError(
            "参照音声ファイルが空です。"
        )

    if file_size > MAX_REFERENCE_SIZE:
        raise RuntimeError(
            "参照音声が大きすぎます。"
            "50MB以下にしてください。"
        )

    suffix = path.suffix.lower()

    mime_types = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
    }

    mime_type = mime_types.get(
        suffix,
        "application/octet-stream",
    )

    with path.open("rb") as audio_file:

        files = {
            "reference_audio": (
                path.name,
                audio_file,
                mime_type,
            )
        }

        response = requests.post(
            f"{ACE_STEP_API}/release_task",
            data=fields,
            files=files,
            timeout=timeout,
        )

    if response.status_code >= 400:

        try:
            error_data = response.json()
        except Exception:
            error_data = response.text

        raise RuntimeError(
            "ACE-Step参照音声APIエラー\n\n"
            f"HTTP: {response.status_code}\n\n"
            f"{error_data}"
        )

    data = response.json()

    if data.get("code") not in (None, 200):
        raise RuntimeError(
            data.get(
                "error",
                "ACE-Step APIでエラーが発生しました。",
            )
        )

    return data


# =========================================================
# URLから参照音声をダウンロード
# =========================================================

def download_reference_from_url(
    url: str,
):
    """
    直接アクセスできる音声ファイルURLを
    ローカルへ保存する。

    例:
    https://example.com/my_voice.wav
    https://example.com/audio/sample.mp3
    """

    url = url.strip()

    if not url:
        return None

    parsed = urlparse(url)

    if parsed.scheme not in (
        "http",
        "https",
    ):
        raise RuntimeError(
            "リンクは http:// または https:// で始まる"
            "音声ファイルURLを使用してください。"
        )

    # 不要なクエリなどを除いて拡張子を取得
    clean_path = parsed.path.lower()

    extension = Path(
        clean_path
    ).suffix.lower()

    allowed_extensions = {
        ".wav",
        ".mp3",
        ".m4a",
        ".aac",
        ".flac",
        ".ogg",
        ".webm",
    }

    try:

        response = requests.get(
            url,
            stream=True,
            timeout=60,
            allow_redirects=True,
            headers={
                "User-Agent": "LMM-MUSIC/1.0"
            },
        )

        response.raise_for_status()

        content_type = (
            response.headers.get(
                "Content-Type",
                ""
            ).lower()
        )

        # 拡張子がない場合はContent-Typeから判断
        content_is_audio = (
            content_type.startswith("audio/")
            or "application/octet-stream"
            in content_type
        )

        if (
            extension not in allowed_extensions
            and not content_is_audio
        ):
            raise RuntimeError(
                "このリンクは直接の音声ファイルとして"
                "認識できませんでした。\n\n"
                "WAV / MP3 / M4A / FLAC / OGGなどの"
                "直接音声ファイルURLを使用してください。"
            )

        if extension not in allowed_extensions:

            extension = ".mp3"

        filename = (
            f"reference_"
            f"{int(time.time())}"
            f"{extension}"
        )

        output_path = (
            REFERENCE_DIR /
            filename
        )

        total_size = 0

        with output_path.open(
            "wb"
        ) as output_file:

            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):

                if not chunk:
                    continue

                total_size += len(chunk)

                if total_size > MAX_REFERENCE_SIZE:

                    output_file.close()

                    try:
                        output_path.unlink()
                    except FileNotFoundError:
                        pass

                    raise RuntimeError(
                        "参照音声が50MBを超えています。"
                    )

                output_file.write(chunk)

        if not output_path.exists():
            raise RuntimeError(
                "参照音声を保存できませんでした。"
            )

        if output_path.stat().st_size <= 0:
            raise RuntimeError(
                "ダウンロードした音声ファイルが空です。"
            )

        return output_path

    except requests.RequestException as exc:

        raise RuntimeError(
            "参照音声リンクのダウンロードに失敗しました。\n\n"
            f"{exc}"
        ) from exc


# =========================================================
# プロンプト
# =========================================================

def build_prompt(
    purpose,
    description,
    genre,
    moods,
    instruments,
    reference_enabled,
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

    if instruments:
        parts.append(
            "Instruments: " + ", ".join(instruments)
        )

    if reference_enabled:
        parts.append(
            "Use the reference audio as a vocal timbre "
            "and stylistic reference while creating a "
            "new musical arrangement."
        )

    parts.append(
        "Professional modern music production, "
        "detailed arrangement, layered instrumentation, "
        "clear rhythm section, strong transitions, "
        "dynamic progression, memorable climax."
    )

    return ". ".join(parts)


# =========================================================
# 生成結果を待つ
# =========================================================

def wait_for_result(
    task_id,
    progress=None,
):
    max_wait_seconds = 1200

    start_time = time.time()

    while True:

        elapsed = (
            time.time() -
            start_time
        )

        if elapsed >= max_wait_seconds:
            raise TimeoutError(
                "音楽生成が20分を超えたため停止しました。"
            )

        response = api_post_json(
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

        # 生成中
        if status == 0:

            if progress:

                progress(
                    None,
                    desc=(
                        "音楽を生成中... "
                        f"{int(elapsed)}秒"
                    ),
                )

            time.sleep(2)

            continue

        # 成功
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

        # 失敗
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


# =========================================================
# 生成音源保存
# =========================================================

def save_audio(
    file_value,
    task_id,
):
    if not file_value:
        raise RuntimeError(
            "生成された音源ファイルが見つかりません。"
        )

    file_value = str(file_value)

    output_path = (
        OUTPUT_DIR /
        f"{task_id}.mp3"
    )

    # ローカルパス
    local_path = Path(
        file_value
    )

    if local_path.is_file():

        shutil.copy2(
            local_path,
            output_path,
        )

        return output_path

    # 完全URL
    if (
        file_value.startswith(
            "http://"
        )
        or file_value.startswith(
            "https://"
        )
    ):

        response = requests.get(
            file_value,
            timeout=300,
        )

        response.raise_for_status()

        output_path.write_bytes(
            response.content
        )

        return output_path

    # /v1/audio
    if file_value.startswith(
        "/v1/audio"
    ):

        audio_url = (
            f"{ACE_STEP_API}"
            f"{file_value}"
        )

        response = requests.get(
            audio_url,
            timeout=300,
        )

        response.raise_for_status()

        output_path.write_bytes(
            response.content
        )

        return output_path

    raise RuntimeError(
        "生成された音源を取得できませんでした。\n\n"
        f"{file_value}"
    )


# =========================================================
# 音楽生成
# =========================================================

def generate_music(
    purpose,
    description,
    duration,
    genre,
    moods,
    instruments,
    vocal_enabled,
    lyrics,
    reference_audio,
    reference_url,
    reference_strength,
    progress=gr.Progress(),
):
    # -----------------------------------------------------
    # 入力チェック
    # -----------------------------------------------------

    if not purpose and not description:

        raise gr.Error(
            "用途か曲のイメージを入力してください。"
        )

    if vocal_enabled and not lyrics.strip():

        raise gr.Error(
            "ボーカルを有効にした場合は歌詞を入力してください。"
        )

    # -----------------------------------------------------
    # APIチェック
    # -----------------------------------------------------

    progress(
        0.02,
        desc="ACE-Stepとの接続を確認中...",
    )

    if not check_api():

        raise gr.Error(
            "ACE-Step APIが起動していません。"
        )

    # -----------------------------------------------------
    # 参照音声を決定
    # -----------------------------------------------------

    resolved_reference_audio = None

    if reference_url.strip():

        progress(
            0.04,
            desc="参照音声リンクを取得中...",
        )

        resolved_reference_audio = (
            download_reference_from_url(
                reference_url
            )
        )

    elif reference_audio:

        resolved_reference_audio = Path(
            reference_audio
        )

        if not resolved_reference_audio.is_file():

            raise gr.Error(
                "アップロードされた参照音声が見つかりません。"
            )

    # -----------------------------------------------------
    # 長さ
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # プロンプト
    # -----------------------------------------------------

    prompt = build_prompt(
        purpose=purpose,
        description=description,
        genre=genre,
        moods=moods,
        instruments=instruments,
        reference_enabled=(
            resolved_reference_audio
            is not None
        ),
    )

    # -----------------------------------------------------
    # API共通パラメータ
    # -----------------------------------------------------

    fields = {
        "prompt": prompt,
        "model": "acestep-v15-turbo",

        "audio_duration": str(
            audio_duration
        ),

        "audio_format": "mp3",

        "batch_size": "1",

        "inference_steps": "8",

        "thinking": "true",

        "use_cot_caption": "true",

        "use_cot_language": "true",

        "lm_model_path":
            "acestep-5Hz-lm-0.6B",

        "lm_backend": "pt",

        "vocal_language": "ja",

        "task_type": "text2music",
    }

    # -----------------------------------------------------
    # 歌詞
    # -----------------------------------------------------

    if vocal_enabled:

        fields["lyrics"] = (
            lyrics.strip()
        )

    else:

        fields["lyrics"] = "[inst]"

    # -----------------------------------------------------
    # 参照音声
    # -----------------------------------------------------

    reference_enabled = (
        resolved_reference_audio
        is not None
    )

    if reference_enabled:

        fields[
            "audio_cover_strength"
        ] = str(
            float(
                reference_strength
            )
        )

    # -----------------------------------------------------
    # 生成
    # -----------------------------------------------------

    try:

        progress(
            0.08,
            desc="音楽の設計を作成中...",
        )

        if reference_enabled:

            print()
            print(
                "[LMM MUSIC] "
                "Reference audio:"
            )
            print(
                resolved_reference_audio
            )

            task_response = (
                api_post_reference_audio(
                    fields,
                    str(
                        resolved_reference_audio
                    ),
                    timeout=300,
                )
            )

        else:

            task_response = api_post_json(
                "/release_task",
                {
                    **fields,
                },
                timeout=300,
            )

        # -------------------------------------------------
        # Task ID
        # -------------------------------------------------

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
            f"[LMM MUSIC] Task ID: "
            f"{task_id}"
        )

        progress(
            0.10,
            desc="音楽を生成中...",
        )

        result = wait_for_result(
            task_id,
            progress=progress,
        )

        # -------------------------------------------------
        # 保存
        # -------------------------------------------------

        progress(
            0.95,
            desc="音源を保存中...",
        )

        output_path = save_audio(
            result.get("file"),
            task_id,
        )

        # -------------------------------------------------
        # メタ情報
        # -------------------------------------------------

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

        if reference_enabled:

            reference_text = (
                "あり / "
                f"反映度 {reference_strength:.2f}"
            )

        else:

            reference_text = "なし"

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

**ボーカル**  
{"あり" if vocal_enabled else "なし"}

**参照音声**  
{reference_text}

**モデル**  
ACE-Step 1.5
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
            "ACE-Step APIからの応答が"
            "タイムアウトしました。"
        )

    except Exception as exc:

        raise gr.Error(
            str(exc)
        )


# =========================================================
# CSS
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

.reference-note {
    opacity: 0.7;
    font-size: 13px;
}
"""


# =========================================================
# UI
# =========================================================

with gr.Blocks(
    title="LMM MUSIC",
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
        # 左
        # =================================================

        with gr.Column(
            scale=1,
            variant="panel",
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

            gr.Markdown(
                "### 🎹 使用する楽器"
            )

            instruments = gr.CheckboxGroup(
                choices=[
                    "Piano",
                    "Electric Piano",
                    "Acoustic Guitar",
                    "Electric Guitar",
                    "Bass",
                    "Sub Bass",
                    "Drums",
                    "808",
                    "Synth Lead",
                    "Synth Pad",
                    "Arpeggio",
                    "Strings",
                    "Orchestra",
                    "Brass",
                    "Choir",
                    "Percussion",
                ],
                label="楽器",
            )

            gr.Markdown(
                "### 🎤 ボーカル"
            )

            vocal_enabled = gr.Checkbox(
                label="ボーカルを入れる",
                value=False,
            )

            lyrics = gr.Textbox(
                label="歌詞",
                placeholder=(
                    "ここに指定の歌詞を入力"
                ),
                lines=8,
                visible=False,
            )

            vocal_enabled.change(
                fn=lambda enabled: gr.update(
                    visible=enabled
                ),
                inputs=vocal_enabled,
                outputs=lyrics,
            )

            gr.Markdown(
                "### 🎙️ 参照音声"
            )

            reference_audio = gr.Audio(
                label="音声ファイル",
                type="filepath",
                sources=["upload"],
                format="wav",
            )

            reference_url = gr.Textbox(
                label="または音声ファイルのリンク",
                placeholder=(
                    "https://example.com/voice.wav"
                ),
                info=(
                    "直接WAV / MP3 / M4A / FLACなどを取得できる"
                    "音声ファイルURLを入力してください。"
                ),
            )

            gr.Markdown(
                "参照音声は声質・歌い方・音響的特徴の"
                "参考として使用します。",
                elem_classes=["reference-note"],
            )

            reference_strength = gr.Slider(
                minimum=0.2,
                maximum=1.0,
                value=0.35,
                step=0.05,
                label="参照音声の反映度",
                info=(
                    "低いほど自由度が高く、"
                    "高いほど参照音声に寄せます。"
                ),
            )

            generate_button = gr.Button(
                "✨ 音楽を作る",
                variant="primary",
                elem_classes="generate-button",
            )

        # =================================================
        # 右
        # =================================================

        with gr.Column(
            scale=1,
            variant="panel",
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
                lines=10,
                interactive=False,
            )

    # =====================================================
    # 生成ボタン
    # =====================================================

    generate_button.click(
        fn=generate_music,
        inputs=[
            purpose,
            description,
            duration,
            genre,
            moods,
            instruments,
            vocal_enabled,
            lyrics,
            reference_audio,
            reference_url,
            reference_strength,
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
        theme=gr.themes.Base(),
        css=CSS,
    )
