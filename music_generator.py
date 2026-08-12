from pathlib import Path

import numpy as np
import scipy.io.wavfile
import torch
from transformers import AutoProcessor, MusicgenForConditionalGeneration


MODEL_NAME = "facebook/musicgen-small"
OUTPUT_DIR = Path("generated")
OUTPUT_DIR.mkdir(exist_ok=True)


class MusicGenerator:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        print("=" * 60)
        print("LMM MUSIC - MusicGen")
        print("=" * 60)
        print(f"Device : {self.device}")

        if self.device == "cuda":
            print(f"GPU    : {torch.cuda.get_device_name(0)}")
        else:
            print("WARNING: CUDAが使用できません。")

        print()
        print("MusicGenモデルを読み込んでいます...")
        print(f"Model: {MODEL_NAME}")
        print()

        self.processor = AutoProcessor.from_pretrained(MODEL_NAME)

        self.model = MusicgenForConditionalGeneration.from_pretrained(
            MODEL_NAME,
            torch_dtype=(
                torch.float16
                if self.device == "cuda"
                else torch.float32
            ),
        )

        self.model.to(self.device)

        print()
        print("モデルの読み込みが完了しました！")
        print()

    def generate(self, prompt: str):
        print("=" * 60)
        print("MUSIC GENERATION")
        print("=" * 60)
        print(f"Prompt: {prompt}")
        print()

        inputs = self.processor(
            text=[prompt],
            padding=True,
            return_tensors="pt",
        )

        inputs = {
            key: value.to(self.device)
            for key, value in inputs.items()
        }

        print("音楽を生成しています...")
        print("しばらく待ってください。")
        print()

        with torch.inference_mode():
            audio_values = self.model.generate(
                **inputs,
                do_sample=True,
                guidance_scale=3.0,
                max_new_tokens=1503,
            )

        audio = audio_values[0, 0].detach().cpu().numpy()

        # WAV保存用にfloat32へ変換
        audio = audio.astype(np.float32)

        # -1.0 ～ 1.0 の範囲に収める
        audio = np.clip(audio, -1.0, 1.0)

        output_path = OUTPUT_DIR / "music.wav"

        sampling_rate = self.model.config.audio_encoder.sampling_rate

        scipy.io.wavfile.write(
            output_path,
            rate=sampling_rate,
            data=audio,
        )

        print("=" * 60)
        print("GENERATED!")
        print("=" * 60)
        print(f"File: {output_path.resolve()}")
        print()

        return output_path


if __name__ == "__main__":
    generator = MusicGenerator()

    prompt = input(
        "作りたい音楽を入力してください: "
    ).strip()

    if not prompt:
        print("プロンプトが入力されていません。")
    else:
        generator.generate(prompt)
