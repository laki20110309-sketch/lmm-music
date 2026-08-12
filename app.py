from music_generator import MusicGenerator


def main():
    print()
    print("=" * 60)
    print("        LMM MUSIC")
    print("   AI Music Generator")
    print("=" * 60)
    print()

    print("音楽生成AIを起動しています...")
    print()

    generator = MusicGenerator()

    print()
    print("-" * 60)
    print("作りたい音楽について入力してください。")
    print("-" * 60)
    print()

    prompt = input("Prompt > ").strip()

    if not prompt:
        print()
        print("プロンプトが入力されていません。")
        return

    print()

    output_path = generator.generate(prompt)

    print()
    print("🎧 音楽が完成しました！")
    print(f"保存場所: {output_path}")
    print()


if __name__ == "__main__":
    main()
