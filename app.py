import json
import shutil
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import gradio as gr
import requests


# =========================================================
# LMM MUSIC
# =========================================================

ACE_STEP_API = "http://127.0.0.1:8001"

APP_HOST = "127.0.0.1"
APP_PORT = 7861

OUTPUT_DIR = Path("generated")
REFERENCE_DIR = Path("reference_audio")

OUTPUT_DIR.mkdir(exist_ok=True)
REFERENCE_DIR.mkdir(exist_ok=True)

MAX_REFERENCE_SIZE = 50 * 1024 * 1024


# =========================================================
# API
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
            f"ACE-Step API Error\n"
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
    path = Path(reference_path)

    if not path.is_file():
        raise RuntimeError(
            "参照音声ファイルが見つかりません。"
        )

    file_size = path.stat().st_size

    if file_size <= 0:
        raise RuntimeError(
            "参照音声ファイルが空です。"
        )

    if file_size > MAX_REFERENCE_SIZE:
        raise RuntimeError(
            "参照音声は50MB以下にしてください。"
        )

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
        path.suffix.lower(),
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
            f"ACE-Step Reference Audio Error\n"
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
# Reference Audio
# =========================================================

def download_reference_from_url(url: str):

    url = url.strip()

    if not url:
        return None

    parsed = urlparse(url)

    if parsed.scheme not in (
        "http",
        "https",
    ):
        raise RuntimeError(
            "音声リンクは http:// または https:// "
            "で始まるURLを入力してください。"
        )

    allowed_extensions = {
        ".wav",
        ".mp3",
        ".m4a",
        ".aac",
        ".flac",
        ".ogg",
        ".webm",
    }

    extension = Path(
        parsed.path
    ).suffix.lower()

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

    content_type = response.headers.get(
        "Content-Type",
        "",
    ).lower()

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
            "このリンクは直接の音声ファイルURLとして"
            "認識できませんでした。"
        )

    if extension not in allowed_extensions:
        extension = ".mp3"

    filename = (
        f"reference_"
        f"{int(time.time())}"
        f"{extension}"
    )

    output_path = (
        REFERENCE_DIR / filename
    )

    total_size = 0

    with output_path.open("wb") as output_file:

        for chunk in response.iter_content(
            chunk_size=1024 * 1024
        ):

            if not chunk:
                continue

            total_size += len(chunk)

            if total_size > MAX_REFERENCE_SIZE:

                try:
                    output_path.unlink()
                except FileNotFoundError:
                    pass

                raise RuntimeError(
                    "参照音声が50MBを超えています。"
                )

            output_file.write(chunk)

    return output_path


# =========================================================
# Prompt
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
            "and stylistic reference."
        )

    parts.append(
        "Professional modern music production, "
        "detailed arrangement, layered instrumentation, "
        "clear rhythm section, strong transitions, "
        "dynamic progression and memorable climax."
    )

    return ". ".join(parts)


# =========================================================
# Result
# =========================================================

def wait_for_result(
    task_id,
    progress=None,
):
    max_wait_seconds = 1200
    start_time = time.time()

    while True:

        elapsed = time.time() - start_time

        if elapsed >= max_wait_seconds:
            raise TimeoutError(
                "音楽生成が20分を超えました。"
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
                    "生成結果が空でした。"
                )

            return result[0]

        if status == 2:

            raise RuntimeError(
                "ACE-Stepで音楽生成に失敗しました。\n"
                f"{job.get('result', '')}"
            )

        time.sleep(2)


def save_audio(
    file_value,
    task_id,
):
    if not file_value:
        raise RuntimeError(
            "生成された音源が見つかりません。"
        )

    file_value = str(file_value)

    output_path = (
        OUTPUT_DIR /
        f"{task_id}.mp3"
    )

    local_path = Path(file_value)

    if local_path.is_file():
        shutil.copy2(
            local_path,
            output_path,
        )
        return output_path

    if (
        file_value.startswith("http://")
        or file_value.startswith("https://")
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

    if file_value.startswith(
        "/v1/audio"
    ):

        audio_url = urljoin(
            ACE_STEP_API,
            file_value,
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
        f"音源を取得できませんでした。\n{file_value}"
    )


# =========================================================
# Generate
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
    if not purpose and not description:
        raise gr.Error(
            "用途か曲のイメージを入力してください。"
        )

    if vocal_enabled and not lyrics.strip():
        raise gr.Error(
            "ボーカルを有効にした場合は歌詞を入力してください。"
        )

    progress(
        0.02,
        desc="ACE-Stepとの接続を確認中...",
    )

    if not check_api():
        raise gr.Error(
            "ACE-Step APIが起動していません。"
        )

    reference_path = None

    if reference_url.strip():

        progress(
            0.04,
            desc="参照音声を取得中...",
        )

        reference_path = (
            download_reference_from_url(
                reference_url
            )
        )

    elif reference_audio:

        reference_path = Path(
            reference_audio
        )

        if not reference_path.is_file():
            raise gr.Error(
                "参照音声ファイルが見つかりません。"
            )

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

    prompt = build_prompt(
        purpose=purpose,
        description=description,
        genre=genre,
        moods=moods,
        instruments=instruments,
        reference_enabled=(
            reference_path is not None
        ),
    )

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

    if vocal_enabled:
        fields["lyrics"] = lyrics.strip()
    else:
        fields["lyrics"] = "[inst]"

    if reference_path:

        fields[
            "audio_cover_strength"
        ] = str(
            float(reference_strength)
        )

    try:

        progress(
            0.08,
            desc="音楽を設計中...",
        )

        if reference_path:

            task_response = (
                api_post_reference_audio(
                    fields,
                    str(reference_path),
                )
            )

        else:

            task_response = api_post_json(
                "/release_task",
                fields,
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
                "ACE-StepからタスクIDを取得できませんでした。"
            )

        progress(
            0.10,
            desc="音楽を生成中...",
        )

        result = wait_for_result(
            task_id,
            progress,
        )

        progress(
            0.95,
            desc="音源を保存中...",
        )

        output_path = save_audio(
            result.get("file"),
            task_id,
        )

        metas = result.get(
            "metas",
            {},
        ) or {}

        bpm = metas.get("bpm", "-")
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

        info = f"""
**{genres}**

BPM {bpm}　·　{keyscale}　·　{real_duration}秒

{"🎙️ 参照音声あり" if reference_path else "🎹 オリジナル生成"}
"""

        progress(
            1.0,
            desc="完成！",
        )

        return (
            str(output_path),
            info,
            prompt,
        )

    except Exception as exc:

        raise gr.Error(
            str(exc)
        )


# =========================================================
# Design
# =========================================================

CSS = """
:root {
    --bg: #08090d;
    --panel: #101218;
    --panel2: #141720;
    --line: rgba(255,255,255,.08);
    --text: #f5f7fb;
    --muted: #8d93a3;
    --accent: #ffffff;
}

body {
    background: var(--bg) !important;
}

.gradio-container {
    max-width: 1280px !important;
    margin: 0 auto !important;
    background: var(--bg) !important;
}

footer {
    display: none !important;
}

.contain {
    background: transparent !important;
}

#app-header {
    padding: 22px 8px 34px;
}

#logo {
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.6px;
}

#nav {
    color: var(--muted);
    font-size: 13px;
}

#hero {
    padding: 28px 8px 42px;
}

#hero h1 {
    font-size: 56px !important;
    line-height: 1.02 !important;
    letter-spacing: -2.8px !important;
    margin-bottom: 14px !important;
}

#hero p {
    color: var(--muted);
    font-size: 16px;
}

.lmm-card {
    background: var(--panel) !important;
    border: 1px solid var(--line) !important;
    border-radius: 22px !important;
    padding: 8px !important;
}

.lmm-card textarea,
.lmm-card input {
    background: var(--panel2) !important;
    border-color: var(--line) !important;
}

.section-title {
    font-size: 13px !important;
    font-weight: 700 !important;
    letter-spacing: .12em !important;
    color: var(--muted) !important;
}

.generate-button {
    min-height: 58px !important;
    border-radius: 14px !important;
    font-size: 16px !important;
    font-weight: 800 !important;
}

.track-card {
    min-height: 360px;
}

.small-muted {
    color: var(--muted) !important;
    font-size: 13px !important;
}

#footer {
    border-top: 1px solid var(--line);
    margin-top: 60px;
    padding: 22px 8px;
    color: var(--muted);
    font-size: 12px;
}

@media (max-width: 800px) {

    #hero h1 {
        font-size: 42px !important;
    }
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

    # -----------------------------------------------------
    # Header
    # -----------------------------------------------------

    with gr.Row(
        elem_id="app-header",
    ):

        with gr.Column(
            scale=1,
        ):

            gr.Markdown(
                "**LMM MUSIC**",
                elem_id="logo",
            )

        with gr.Column(
            scale=0,
        ):

            gr.Markdown(
                "CREATE  ·  MY TRACKS  ·  ACCOUNT",
                elem_id="nav",
            )

    # -----------------------------------------------------
    # Hero
    # -----------------------------------------------------

    with gr.Column(
        elem_id="hero",
    ):

        gr.Markdown(
            "# MAKE YOUR SOUND"
        )

        gr.Markdown(
            "あなたのアイデアから、音楽を作る。"
        )

    # -----------------------------------------------------
    # Main
    # -----------------------------------------------------

    with gr.Row():

        # ================================================
        # Creator
        # ================================================

        with gr.Column(
            scale=1,
            elem_classes=["lmm-card"],
        ):

            gr.Markdown(
                "CREATE",
                elem_classes=["section-title"],
            )

            purpose = gr.Textbox(
                label="用途",
                placeholder=(
                    "例：VALORANT大会の決勝ハイライト"
                ),
            )

            description = gr.Textbox(
                label="音楽のイメージ",
                placeholder=(
                    "例：最初は緊張感。"
                    "後半で一気に爆発する。"
                ),
                lines=5,
            )

            with gr.Row():

                duration = gr.Dropdown(
                    choices=[
                        "10秒",
                        "30秒",
                        "60秒",
                        "90秒",
                    ],
                    value="30秒",
                    label="長さ",
                )

                genre = gr.Dropdown(
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
                    label="ジャンル",
                )

            moods = gr.CheckboxGroup(
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
                label="雰囲気",
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
                label="使用する楽器",
            )

            vocal_enabled = gr.Checkbox(
                label="ボーカルを入れる",
                value=False,
            )

            lyrics = gr.Textbox(
                label="歌詞",
                placeholder="指定した歌詞を入力",
                lines=6,
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
                "REFERENCE VOICE",
                elem_classes=["section-title"],
            )

            reference_audio = gr.Audio(
                label="音声ファイル",
                type="filepath",
                sources=["upload"],
                format="wav",
            )

            reference_url = gr.Textbox(
                label="音声ファイルURL",
                placeholder="https://example.com/voice.wav",
            )

            reference_strength = gr.Slider(
                minimum=0.2,
                maximum=1.0,
                value=0.35,
                step=0.05,
                label="参照音声の反映度",
            )

            generate_button = gr.Button(
                "CREATE MUSIC  →",
                variant="primary",
                elem_classes=["generate-button"],
            )

        # ================================================
        # Result
        # ================================================

        with gr.Column(
            scale=1,
            elem_classes=[
                "lmm-card",
                "track-card",
            ],
        ):

            gr.Markdown(
                "YOUR TRACK",
                elem_classes=["section-title"],
            )

            result_audio = gr.Audio(
                label="",
                type="filepath",
                interactive=False,
            )

            result_info = gr.Markdown(
                "ここに生成した音楽が表示されます。",
                elem_classes=["small-muted"],
            )

            gr.Markdown(
                "AI PROMPT",
                elem_classes=["section-title"],
            )

            generated_prompt = gr.Textbox(
                label="",
                lines=8,
                interactive=False,
            )

    # -----------------------------------------------------
    # Footer
    # -----------------------------------------------------

    gr.Markdown(
        "LMM MUSIC · Local AI Music Studio",
        elem_id="footer",
    )

    # -----------------------------------------------------
    # Generate
    # -----------------------------------------------------

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
# Launch
# =========================================================

if __name__ == "__main__":

    demo.launch(
        server_name=APP_HOST,
        server_port=APP_PORT,
        show_error=True,
        theme=gr.themes.Base(),
        css=CSS,
    )
