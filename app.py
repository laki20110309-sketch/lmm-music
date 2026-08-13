import json
import shutil
import time
from pathlib import Path
from urllib.parse import urljoin

import gradio as gr
import requests


# =========================================================
# 基本設定
# =========================================================

ACE_STEP_API = "http://127.0.0.1:8001"

APP_HOST = "127.0.0.1"
APP_PORT = 7861

OUTPUT_DIR = Path("generated")
OUTPUT_DIR.mkdir(exist_ok=True)


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


def api_post(
    endpoint: str,
    payload: dict,
    timeout: int = 300,
):
    response = requests.post(
        f"{ACE_STEP_API}{endpoint}",
        json=payload,
        timeout=timeout,
    )

    # 500でもACE-Stepが返した詳細を拾う
    if response.status_code >= 400:
        try:
            error_data = response.json()
        except Exception:
            error_data = response.text

        raise RuntimeError(
            "ACE-Step API Error\n\n"
            f"HTTP Status: {response.status_code}\n\n"
            f"Response:\n{error_data}"
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
# プロンプト
# =========================================================

def build_prompt(
    purpose,
    description,
    genre,
    moods,
    instruments,
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

    parts.append(
        "Professional modern music production, "
        "detailed arrangement, layered instrumentation, "
        "strong rhythm section, clear transitions, "
        "dynamic progression, memorable climax."
    )

    return ". ".join(parts)


# =========================================================
# 生成結果待ち
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
                "音楽生成が20分を超えたため停止しました。"
            )

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

        if status == 0:

            if progress:
                progress(
                    None,
                    desc=(
                        f"音楽を生成中... "
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
                    "ACE-Stepから生成結果が返ってきませんでした。"
                )

            return result[0]

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
# 音源保存
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

    # ローカルファイル
    local_path = Path(file_value)

    if local_path.is_file():

        shutil.copy2(
            local_path,
            output_path,
        )

        return output_path

    # URL
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

    # /v1/audio
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

    if not check_api():
        raise gr.Error(
            "ACE-Step APIが起動していません。"
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
    )

    # -----------------------------------------------------
    # ACE-Step APIパラメータ
    # -----------------------------------------------------

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

        "lm_model_path": "acestep-5Hz-lm-0.6B",
        "lm_backend": "pt",

        "vocal_language": "ja",

        "lyrics": (
            lyrics.strip()
            if vocal_enabled
            else "[inst]"
        ),
    }

    # -----------------------------------------------------
    # 参照音声
    # -----------------------------------------------------

    if reference_audio:

        reference_path = Path(
            reference_audio
        ).resolve()

        if not reference_path.is_file():
            raise gr.Error(
                "参照音声ファイルが見つかりません。"
            )

        # 公式API:
        # reference_audio_path = Style Transfer
        payload["reference_audio_path"] = str(
            reference_path
        )

        # Style Transferでは低めから試す
        payload["audio_cover_strength"] = float(
            reference_strength
        )

        # 参照音声はスタイル転送なので
        # task_typeはtext2musicのまま
        payload["task_type"] = "text2music"

    else:

        payload["task_type"] = "text2music"

    # -----------------------------------------------------
    # 生成開始
    # -----------------------------------------------------

    try:

        progress(
            0.05,
            desc="音楽の設計を作成中...",
        )

        print()
        print("=" * 60)
        print("LMM MUSIC REQUEST")
        print("=" * 60)
        print(json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ))
        print("=" * 60)
        print()

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
        # メタデータ
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

        reference_text = (
            f"あり / {reference_strength:.2f}"
            if reference_audio
            else "なし"
        )

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

    except Exception as exc:

        raise gr.Error(
            str(exc)
        )


# =========================================================
# UI
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
"""


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
        # 左側
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
                placeholder="ここに指定の歌詞を入力",
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
                label="参照音声",
                type="filepath",
                sources=["upload"],
                format="wav",
            )

            reference_strength = gr.Slider(
                minimum=0.2,
                maximum=1.0,
                value=0.35,
                step=0.05,
                label="参照音声の反映度",
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
