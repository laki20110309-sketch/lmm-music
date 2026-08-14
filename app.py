from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import gradio as gr
import requests

from device_detector import analyze_device


# =========================================================
# LMM MUSIC
# =========================================================

ACE_STEP_API = "http://127.0.0.1:8001"
LOCAL_ENGINE_API = "http://127.0.0.1:8765"

APP_HOST = "127.0.0.1"
APP_PORT = 7861

OUTPUT_DIR = Path("generated")
REFERENCE_DIR = Path("reference_audio")

OUTPUT_DIR.mkdir(exist_ok=True)
REFERENCE_DIR.mkdir(exist_ok=True)

MAX_REFERENCE_SIZE = 50 * 1024 * 1024


# =========================================================
# API URL
# =========================================================

def get_generation_api(selected_mode: str):
    """
    端末性能に応じて生成先を決める。

    local_gpu / local_cpu
        -> Local Engine

    cloud
        -> 現段階ではACE-Step APIへ直接接続
    """

    if selected_mode in (
        "local_gpu",
        "local_cpu",
    ):
        return LOCAL_ENGINE_API

    return ACE_STEP_API


# =========================================================
# Health Check
# =========================================================

def check_api(base_url: str):
    try:
        response = requests.get(
            f"{base_url}/health",
            timeout=8,
        )

        response.raise_for_status()

        data = response.json()

        return data

    except Exception:
        return None


def check_generation_engine(selected_mode: str):
    """
    選択された生成エンジンが使えるか確認する。
    """

    base_url = get_generation_api(
        selected_mode
    )

    health = check_api(
        base_url
    )

    if not health:
        return False, base_url, None

    if selected_mode in (
        "local_gpu",
        "local_cpu",
    ):

        ace_step_ok = health.get(
            "ace_step",
            False,
        )

        return (
            bool(ace_step_ok),
            base_url,
            health,
        )

    return (
        True,
        base_url,
        health,
    )


# =========================================================
# JSON POST
# =========================================================

def api_post_json(
    base_url: str,
    endpoint: str,
    payload: dict,
    timeout: int = 300,
):
    response = requests.post(
        f"{base_url}{endpoint}",
        json=payload,
        timeout=timeout,
    )

    if response.status_code >= 400:

        try:
            error_data = response.json()

        except Exception:
            error_data = response.text

        raise RuntimeError(
            f"API Error\n"
            f"HTTP: {response.status_code}\n\n"
            f"{error_data}"
        )

    data = response.json()

    if data.get("code") not in (
        None,
        200,
    ):

        raise RuntimeError(
            data.get(
                "error",
                "APIでエラーが発生しました。",
            )
        )

    return data


# =========================================================
# Reference Audio
# =========================================================

def api_post_reference_audio(
    fields: dict,
    reference_path: str,
    timeout: int = 300,
):
    """
    参照音声はACE-Stepへ直接送る。
    """

    path = Path(
        reference_path
    )

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

    if data.get("code") not in (
        None,
        200,
    ):

        raise RuntimeError(
            data.get(
                "error",
                "ACE-Step APIでエラーが発生しました。",
            )
        )

    return data


def download_reference_from_url(
    url: str,
):
    """
    音声ファイルURLをローカルへ保存。
    """

    url = url.strip()

    if not url:
        return None

    parsed = urlparse(
        url
    )

    if parsed.scheme not in (
        "http",
        "https",
    ):

        raise RuntimeError(
            "音声リンクは http:// または "
            "https:// のURLを使用してください。"
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

    content_type = (
        response.headers
        .get(
            "Content-Type",
            "",
        )
        .lower()
    )

    content_is_audio = (
        content_type.startswith(
            "audio/"
        )
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

                try:
                    output_path.unlink()
                except FileNotFoundError:
                    pass

                raise RuntimeError(
                    "参照音声が50MBを超えています。"
                )

            output_file.write(
                chunk
            )

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
            "Mood: "
            + ", ".join(moods)
        )

    if instruments:
        parts.append(
            "Instruments: "
            + ", ".join(instruments)
        )

    if reference_enabled:
        parts.append(
            "Use the reference audio as a vocal "
            "timbre and stylistic reference."
        )

    parts.append(
        "Professional modern music production, "
        "detailed arrangement, layered instrumentation, "
        "clear rhythm section, strong transitions, "
        "dynamic progression and memorable climax."
    )

    return ". ".join(
        parts
    )


# =========================================================
# Result
# =========================================================

def wait_for_result(
    base_url,
    task_id,
    progress=None,
):
    """
    Local Engine / ACE-Step共通。
    """

    max_wait_seconds = 1200

    start_time = time.time()

    while True:

        elapsed = (
            time.time()
            - start_time
        )

        if elapsed >= max_wait_seconds:

            raise TimeoutError(
                "音楽生成が20分を超えました。"
            )

        response = api_post_json(
            base_url,
            "/query_result",
            {
                "task_id_list": [
                    task_id
                ]
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
                "音楽生成に失敗しました。\n"
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

    file_value = str(
        file_value
    )

    output_path = (
        OUTPUT_DIR
        / f"{task_id}.mp3"
    )

    local_path = Path(
        file_value
    )

    if local_path.is_file():

        shutil.copy2(
            local_path,
            output_path,
        )

        return output_path

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
        "音源を取得できませんでした。\n"
        f"{file_value}"
    )


# =========================================================
# Device Detection
# =========================================================

def update_device_info(
    gpu_available,
    gpu_name,
    gpu_vendor,
    webgpu_available,
    cpu_threads,
    device_memory,
):
    try:

        gpu_available_bool = (
            str(
                gpu_available
            ).lower()
            == "true"
        )

        webgpu_available_bool = (
            str(
                webgpu_available
            ).lower()
            == "true"
        )

        try:
            cpu_threads_value = int(
                cpu_threads
            )

        except (
            ValueError,
            TypeError,
        ):
            cpu_threads_value = None

        try:
            memory_value = float(
                device_memory
            )

        except (
            ValueError,
            TypeError,
        ):
            memory_value = None

        info = analyze_device(
            gpu_available=(
                gpu_available_bool
            ),
            gpu_name=(
                gpu_name
                or None
            ),
            gpu_vendor=(
                gpu_vendor
                or None
            ),
            webgpu_available=(
                webgpu_available_bool
            ),
            cpu_threads=(
                cpu_threads_value
            ),
            device_memory_gb=(
                memory_value
            ),
        )

        if (
            info.recommended_mode
            == "local_gpu"
        ):

            status_text = (
                "⚡ ローカルGPU生成"
            )

        elif (
            info.recommended_mode
            == "local_cpu"
        ):

            status_text = (
                "🖥️ ローカルCPU生成"
            )

        else:

            status_text = (
                "☁️ クラウド生成"
            )

        gpu_text = (
            info.gpu_name
            if info.gpu_name
            else "取得できませんでした"
        )

        cpu_text = (
            f"{info.cpu_threads} threads"
            if info.cpu_threads
            else "取得できませんでした"
        )

        memory_text = (
            f"{info.device_memory_gb:g} GB"
            if info.device_memory_gb
            else "取得できませんでした"
        )

        html = f"""
        <div class="device-status">

            <div class="device-status-title">
                {status_text}
            </div>

            <div class="device-status-reason">
                {info.reason}
            </div>

            <div class="device-grid">

                <div class="device-item">
                    <span>GPU</span>
                    <strong>{gpu_text}</strong>
                </div>

                <div class="device-item">
                    <span>CPU</span>
                    <strong>{cpu_text}</strong>
                </div>

                <div class="device-item">
                    <span>Memory</span>
                    <strong>{memory_text}</strong>
                </div>

                <div class="device-item">
                    <span>WebGPU</span>
                    <strong>
                        {
                            "対応"
                            if info.webgpu_available
                            else "非対応"
                        }
                    </strong>
                </div>

            </div>

        </div>
        """

        return (
            html,
            info.recommended_mode,
        )

    except Exception as exc:

        return (
            f"""
            <div class="device-status error">

                <div class="device-status-title">
                    端末判定に失敗しました
                </div>

                <div class="device-status-reason">
                    {exc}
                </div>

            </div>
            """,
            "cloud",
        )


# =========================================================
# Music Generation
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
    selected_mode,
    progress=gr.Progress(),
):
    if (
        not purpose
        and not description
    ):

        raise gr.Error(
            "用途か曲のイメージを入力してください。"
        )

    if (
        vocal_enabled
        and not lyrics.strip()
    ):

        raise gr.Error(
            "ボーカルを有効にした場合は歌詞を入力してください。"
        )

    progress(
        0.02,
        desc="生成エンジンを確認中...",
    )

    engine_ok, base_url, health = (
        check_generation_engine(
            selected_mode
        )
    )

    if not engine_ok:

        if selected_mode in (
            "local_gpu",
            "local_cpu",
        ):

            raise gr.Error(
                "この端末はローカル生成が選択されていますが、"
                "LMM MUSIC Local Engineに接続できません。\n\n"
                "Local Engineが起動しているか確認してください。"
            )

        raise gr.Error(
            "音楽生成APIに接続できません。"
        )

    reference_path = None

    # -----------------------------------------------------
    # 参照音声
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Duration
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
    # Prompt
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # ACE-Step params
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

    if vocal_enabled:

        fields["lyrics"] = (
            lyrics.strip()
        )

    else:

        fields["lyrics"] = "[inst]"

    if reference_path:

        fields[
            "audio_cover_strength"
        ] = str(
            float(
                reference_strength
            )
        )

    # =====================================================
    # 生成
    # =====================================================

    try:

        progress(
            0.08,
            desc=(
                "音楽を設計中..."
            ),
        )

        # -------------------------------------------------
        # Reference audio
        # -------------------------------------------------
        #
        # 参照音声は現在ACE-Stepへ直接送る。
        # Local Engineへのmultipart中継は次段階で追加する。
        #

        if reference_path:

            task_response = (
                api_post_reference_audio(
                    fields,
                    str(
                        reference_path
                    ),
                )
            )

            result_base_url = (
                ACE_STEP_API
            )

        else:

            # -------------------------------------------------
            # ★ ここが今回の変更
            # -------------------------------------------------

            task_response = api_post_json(
                base_url,
                "/generate",
                fields,
                timeout=300,
            )

            result_base_url = (
                base_url
            )

        task_data = (
            task_response.get(
                "data",
                {},
            )
        )

        task_id = (
            task_data.get(
                "task_id"
            )
        )

        if not task_id:

            raise RuntimeError(
                "生成タスクIDを取得できませんでした。\n"
                f"{task_response}"
            )

        print()
        print(
            "=" * 60
        )
        print(
            "LMM MUSIC GENERATION"
        )
        print(
            "=" * 60
        )
        print(
            f"Mode: {selected_mode}"
        )
        print(
            f"Engine: {result_base_url}"
        )
        print(
            f"Task: {task_id}"
        )
        print(
            "=" * 60
        )
        print()

        progress(
            0.10,
            desc="音楽を生成中...",
        )

        result = wait_for_result(
            result_base_url,
            task_id,
            progress,
        )

        progress(
            0.95,
            desc="音源を保存中...",
        )

        output_path = save_audio(
            result.get(
                "file"
            ),
            task_id,
        )

        # -------------------------------------------------
        # Meta
        # -------------------------------------------------

        metas = (
            result.get(
                "metas",
                {},
            )
            or {}
        )

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

       genres = (
    metas.get("genres")
    or genre
    or "N/A"
)

        if (
            selected_mode
            == "local_gpu"
        ):

            mode_text = (
                "⚡ ローカルGPU"
            )

        elif (
            selected_mode
            == "local_cpu"
        ):

            mode_text = (
                "🖥️ ローカルCPU"
            )

        else:

            mode_text = (
                "☁️ クラウド"
            )

        info = f"""
### 生成完了

**{genres}**

BPM {bpm}　·　{keyscale}　·　{real_duration}秒

**生成方式:** {mode_text}

{
    "🎙️ 参照音声あり"
    if reference_path
    else "🎹 オリジナル生成"
}
"""

        progress(
            1.0,
            desc="完成！",
        )

        return (
            str(
                output_path
            ),
            info,
            prompt,
        )

    except Exception as exc:

        raise gr.Error(
            str(exc)
        )


# =========================================================
# Browser JS
# =========================================================

DEVICE_DETECTION_JS = """
async () => {

    const result = {
        gpu_available: false,
        gpu_name: "",
        gpu_vendor: "",
        webgpu_available: false,
        cpu_threads:
            navigator.hardwareConcurrency || "",
        device_memory:
            navigator.deviceMemory || ""
    };


    // WebGPU
    try {

        if (navigator.gpu) {

            const adapter =
                await navigator.gpu.requestAdapter();

            if (adapter) {

                result.webgpu_available = true;
                result.gpu_available = true;

                try {

                    const info =
                        await adapter.requestAdapterInfo();

                    result.gpu_name =
                        info.description ||
                        info.device ||
                        "";

                    result.gpu_vendor =
                        info.vendor ||
                        "";

                } catch (error) {
                }
            }
        }

    } catch (error) {
    }


    // WebGL fallback
    if (!result.gpu_name) {

        try {

            const canvas =
                document.createElement(
                    "canvas"
                );

            const gl =
                canvas.getContext(
                    "webgl"
                ) ||
                canvas.getContext(
                    "experimental-webgl"
                );

            if (gl) {

                const debugInfo =
                    gl.getExtension(
                        "WEBGL_debug_renderer_info"
                    );

                if (debugInfo) {

                    result.gpu_vendor =
                        gl.getParameter(
                            debugInfo
                            .UNMASKED_VENDOR_WEBGL
                        ) || "";

                    result.gpu_name =
                        gl.getParameter(
                            debugInfo
                            .UNMASKED_RENDERER_WEBGL
                        ) || "";
                }
            }

        } catch (error) {
        }
    }


    return [
        String(
            result.gpu_available
        ),

        result.gpu_name,

        result.gpu_vendor,

        String(
            result.webgpu_available
        ),

        String(
            result.cpu_threads
        ),

        String(
            result.device_memory
        )
    ];
}
"""


# =========================================================
# CSS
# =========================================================

CSS = """
:root {
    --bg: #08090d;
    --panel: #101218;
    --panel2: #141720;
    --line: rgba(255,255,255,.08);
    --text: #f5f7fb;
    --muted: #8d93a3;
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

#app-header {
    padding: 22px 8px 20px;
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
    padding: 28px 8px 28px;
}

#hero h1 {
    font-size: 56px !important;
    line-height: 1.02 !important;
    letter-spacing: -2.8px !important;
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

.generate-button {
    min-height: 58px !important;
    border-radius: 14px !important;
    font-size: 16px !important;
    font-weight: 800 !important;
}

.device-status {
    margin-top: 8px;
    padding: 18px;
    border: 1px solid var(--line);
    border-radius: 18px;
    background: var(--panel);
}

.device-status-title {
    font-size: 18px;
    font-weight: 800;
    margin-bottom: 8px;
}

.device-status-reason {
    color: var(--muted);
    font-size: 13px;
    line-height: 1.6;
}

.device-grid {
    display: grid;
    grid-template-columns:
        repeat(2, minmax(0, 1fr));
    gap: 10px;
    margin-top: 14px;
}

.device-item {
    padding: 12px;
    border-radius: 12px;
    background: var(--panel2);
}

.device-item span {
    display: block;
    color: var(--muted);
    font-size: 11px;
    margin-bottom: 4px;
}

.device-item strong {
    display: block;
    font-size: 13px;
    word-break: break-word;
}

.section-label {
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
    letter-spacing: .12em;
    margin-top: 10px;
    margin-bottom: 6px;
}

@media (max-width: 800px) {

    #hero h1 {
        font-size: 42px !important;
    }

    .device-grid {
        grid-template-columns: 1fr;
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
    # Hidden device info
    # -----------------------------------------------------

    gpu_available = gr.Textbox(
        visible=False,
    )

    gpu_name = gr.Textbox(
        visible=False,
    )

    gpu_vendor = gr.Textbox(
        visible=False,
    )

    webgpu_available = gr.Textbox(
        visible=False,
    )

    cpu_threads = gr.Textbox(
        visible=False,
    )

    device_memory = gr.Textbox(
        visible=False,
    )

    selected_mode = gr.Textbox(
        value="cloud",
        visible=False,
    )

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
    # Device
    # -----------------------------------------------------

    gr.Markdown(
        "DEVICE",
        elem_classes=[
            "section-label"
        ],
    )

    device_status = gr.HTML(
        """
        <div class="device-status">

            <div class="device-status-title">
                端末を確認しています...
            </div>

            <div class="device-status-reason">
                この端末に合った生成方式を確認しています。
            </div>

        </div>
        """
    )

    detect_button = gr.Button(
        "端末性能を確認する",
        visible=False,
    )

    # -----------------------------------------------------
    # Main
    # -----------------------------------------------------

    with gr.Row():

        # =================================================
        # Creator
        # =================================================

        with gr.Column(
            scale=1,
            elem_classes=[
                "lmm-card"
            ],
        ):

            gr.Markdown(
                "CREATE",
                elem_classes=[
                    "section-label"
                ],
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
                    "激しい",
                    "エネルギッシュ",
                    "ダーク",
                    "攻撃的",
                    "エモーショナル",
                    "シネマティック",
                    "明るい",
                    "緊張感",
                ],
                label="雰囲気",
            )

            instruments = gr.CheckboxGroup(
                choices=[
                    "ピアノ",
                    "エレクトリックピアノ",
                    "アコースティックギター",
                    "エレキギター",
                    "ベース",
                    "サブベース",
                    "ドラム",
                    "808",
                    "シンセリード",
                    "シンセパッド",
                    "アルペジオ",
                    "ストリングス",
                    "オーケストラ",
                    "ブラス",
                    "コーラス",
                    "パーカッション",
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
                elem_classes=[
                    "section-label"
                ],
            )

            reference_audio = gr.Audio(
                label="音声ファイル",
                type="filepath",
                sources=["upload"],
                format="wav",
            )

            reference_url = gr.Textbox(
                label="音声ファイルURL",
                placeholder=(
                    "https://example.com/voice.wav"
                ),
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
                elem_classes=[
                    "generate-button"
                ],
            )

        # =================================================
        # Result
        # =================================================

        with gr.Column(
            scale=1,
            elem_classes=[
                "lmm-card"
            ],
        ):

            gr.Markdown(
                "YOUR TRACK",
                elem_classes=[
                    "section-label"
                ],
            )

            result_audio = gr.Audio(
                label="",
                type="filepath",
                interactive=False,
            )

            result_info = gr.Markdown(
                "ここに生成した音楽が表示されます。"
            )

            gr.Markdown(
                "AI PROMPT",
                elem_classes=[
                    "section-label"
                ],
            )

            generated_prompt = gr.Textbox(
                label="",
                lines=8,
                interactive=False,
            )

    # =====================================================
    # Device detection
    # =====================================================

    detect_button.click(
        fn=update_device_info,
        inputs=[
            gpu_available,
            gpu_name,
            gpu_vendor,
            webgpu_available,
            cpu_threads,
            device_memory,
        ],
        outputs=[
            device_status,
            selected_mode,
        ],
    )

    demo.load(
        fn=update_device_info,
        inputs=[
            gpu_available,
            gpu_name,
            gpu_vendor,
            webgpu_available,
            cpu_threads,
            device_memory,
        ],
        outputs=[
            device_status,
            selected_mode,
        ],
        js=DEVICE_DETECTION_JS,
    )

    # =====================================================
    # Generate
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
            selected_mode,
        ],
        outputs=[
            result_audio,
            result_info,
            generated_prompt,
        ],
    )

    # =====================================================
    # Footer
    # =====================================================

    gr.Markdown(
        "LMM MUSIC · Local AI Music Studio"
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
        footer_links=[],
    )
