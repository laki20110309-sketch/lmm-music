import json
import time
from pathlib import Path

import gradio as gr
import requests


API_BASE = "http://127.0.0.1:8001"
DOWNLOAD_DIR = Path("generated")
DOWNLOAD_DIR.mkdir(exist_ok=True)


def api_get(path: str):
    response = requests.get(
        f"{API_BASE}{path}",
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def api_post(path: str, payload: dict):
    response = requests.post(
        f"{API_BASE}{path}",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def check_api():
    try:
        data = api_get("/health")
        return data.get("data", {}).get("status") == "ok"
    except Exception:
        return False


def build_prompt(purpose, description, genre, mood):
    parts = []

    if purpose:
        parts.append(f"Purpose: {purpose}")

    if description:
        parts.append(f"Creative direction: {description}")

    if genre:
        parts.append(f"Genre: {genre}")

    if mood:
        parts.append(f"Mood: {mood}")

    parts.append(
        "Detailed instrumental arrangement with clear sections, "
        "strong dynamics, layered drums, bass, harmony, melody, "
        "and professional modern production."
    )

    return ". ".join(parts)


def wait_for_result(task_id):
    for _ in range(240):
        try:
            data = api_post(
                "/query_result",
                {"task_id_list": [task_id]},
            )

            results = data.get("data", [])

            if not results:
                time.sleep(1)
                continue

            job = results[0]
            status = job.get("status", 0)

            if status == 2:
                raise RuntimeError("音楽生成に失敗しました。")

            if status == 1:
                raw_result = job.get("result", "[]")

                if isinstance(raw_result, str):
                    result = json.loads(raw_result)
                else:
                    result = raw_result

                if not result:
                    raise RuntimeError("生成結果が空でした。")

                return result[0]

        except requests.RequestException as exc:
            raise RuntimeError(
                f"ACE-Step APIに接続できません。\n{exc}"
            ) from exc

        time.sleep(2)

    raise TimeoutError("生成がタイムアウトしました。")


def generate_music(
    purpose,
    description,
    duration,
    genre,
    mood,
):
    if not check_api():
        raise RuntimeError(
            "ACE-Step APIが起動していません。\n"
            "先にACE-Step APIを起動してください。"
        )

    prompt = build_prompt(
        purpose,
        description,
        genre,
        mood,
    )

    duration_map = {
        "30秒": 30,
        "60秒": 60,
        "90秒": 90,
        "120秒": 120,
    }

    seconds = duration_map.get(duration, 60)

    task_response = api_post(
        "/release_task",
        {
            "prompt": prompt,
            "audio_duration": seconds,
            "audio_format": "mp3",
            "thinking": True,
            "use_cot_caption": True,
            "use_cot_language": True,
            "inference_steps": 8,
            "batch_size": 1,
            "lm_model_path": "acestep-5Hz-lm-0.6B",
            "lm_backend": "pt",
            "model": "acestep-v15-turbo",
        },
    )

    task_data = task_response.get("data", {})
    task_id = task_data.get("task_id")

    if not task_id:
        raise RuntimeError(
            f"タスクIDを取得できませんでした。\n"
            f"{task_response}"
        )

    result = wait_for_result(task_id)

    file_path = result.get("file")
    metas = result.get("metas", {}) or {}

    if not file_path:
        raise RuntimeError("生成された音源ファイルが見つかりません。")

    audio_response = requests.get(
        f"{API_BASE}{file_path}",
        timeout=60,
    )
    audio_response.raise_for_status()

    output_path = DOWNLOAD_DIR / f"{task_id}.mp3"
    output_path.write_bytes(audio_response.content)

    bpm = metas.get("bpm", "")
    key_scale = metas.get("keyscale", "")
    real_duration = metas.get("duration", seconds)
    genres = metas.get("genres", "") or genre

    info = (
        f"### 生成結果\n\n"
        f"**Genre:** {genres or '-'}  \n"
        f"**BPM:** {bpm or '-'}  \n"
        f"**Key:** {key_scale or '-'}  \n"
        f"**Duration:** {real_duration} sec"
    )

    return str(output_path), info, prompt


custom_css = """
body {
    background: #0b0b0f;
}

.gradio-container {
    max-width: 1100px !important;
    margin: auto !important;
}

#title {
    text-align: center;
    margin-bottom: 8px;
}

#subtitle {
    text-align: center;
    opacity: 0.7;
    margin-bottom: 30px;
}

.section-card {
    border-radius: 18px;
}

.generate-button {
    height: 58px !important;
    font-size: 18px !important;
    font-weight: 700 !important;
}
"""


with gr.Blocks(
    title="LMM MUSIC",
    theme=gr.themes.Soft(),
    css=custom_css,
) as demo:

    gr.Markdown(
        "# ♪ LMM MUSIC",
        elem_id="title",
    )

    gr.Markdown(
        "動画やコンテンツに合う音楽を、かんたんに作る。",
        elem_id="subtitle",
    )

    with gr.Row(equal_height=True):

        with gr.Column(
            scale=1,
            variant="panel",
        ):

            gr.Markdown("## MUSIC BRIEF")

            purpose = gr.Textbox(
                label="用途",
                placeholder="例：VALORANT大会の決勝ハイライト",
            )

            description = gr.Textbox(
                label="曲のイメージ",
                placeholder=(
                    "例：最初は緊張感、後半で一気に爆発。"
                    "重いキックとシンセを使いたい。"
                ),
                lines=5,
            )

            duration = gr.Radio(
                choices=[
                    "30秒",
                    "60秒",
                    "90秒",
                    "120秒",
                ],
                value="60秒",
                label="曲の長さ",
            )

            genre = gr.Dropdown(
                choices=[
                    "EDM",
                    "Cinematic",
                    "Rock",
                    "Hip-Hop",
                    "Electronic",
                    "Pop",
                    "Ambient",
                ],
                value="EDM",
                label="ジャンル",
            )

            mood = gr.CheckboxGroup(
                choices=[
                    "Epic",
                    "Energetic",
                    "Dark",
                    "Emotional",
                    "Aggressive",
                    "Uplifting",
                    "Cinematic",
                ],
                label="雰囲気",
            )

            generate_button = gr.Button(
                "✨ 音楽を作る",
                variant="primary",
                elem_classes="generate-button",
            )

        with gr.Column(
            scale=1,
            variant="panel",
        ):

            gr.Markdown("## YOUR TRACK")

            result_audio = gr.Audio(
                label="生成された音楽",
                type="filepath",
                interactive=False,
            )

            result_info = gr.Markdown(
                "まだ音楽が生成されていません。"
            )

            gr.Markdown("## AI PROMPT")

            generated_prompt = gr.Textbox(
                label="ACE-Stepに送った指示",
                lines=8,
                interactive=False,
            )

    generate_button.click(
        fn=generate_music,
        inputs=[
            purpose,
            description,
            duration,
            genre,
            mood,
        ],
        outputs=[
            result_audio,
            result_info,
            generated_prompt,
        ],
    )


if __name__ == "__main__":
    demo.launch(
        server_name="127.0.0.1",
        server_port=7861,
    )
