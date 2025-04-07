import os
import sys
import json
import wave
import subprocess
import requests
import webbrowser
import pyaudio
from vosk import Model, KaldiRecognizer

VOSK_MODEL_PATH = "./vosk-model-small-en-us-0.15"
PIPER_EXE_PATH = "./piper/piper"
PIPER_VOICE_MODEL = "./en_US-ryan-medium.onnx"
TMP_WAV_FILE = "output_tts.wav"
CHUNK = 4096
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
DICTIONARY_API_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/"

current_word_data = None
current_word = None
p = None
stream = None
vosk_model = None
recognizer = None

if not os.path.exists(VOSK_MODEL_PATH):
    print(f"Ошибка: Папка с моделью VOSK не найдена: '{VOSK_MODEL_PATH}'")
    print("Пожалуйста, скачайте модель с https://alphacephei.com/vosk/models")
    print("и распакуйте ее в папку проекта.")
    sys.exit(1)
if not os.path.exists(PIPER_EXE_PATH):
    print(f"Ошибка: Исполняемый файл Piper не найден по пути: {PIPER_EXE_PATH}")
    sys.exit(1)
if not os.path.exists(PIPER_VOICE_MODEL):
    print(f"Ошибка: Модель голоса Piper не найдена по пути: {PIPER_VOICE_MODEL}")
    sys.exit(1)


def speak(text):
    print(f"Ассистент: {text}")

    command = [
        PIPER_EXE_PATH,
        "--model",
        PIPER_VOICE_MODEL,
        "--output_file",
        TMP_WAV_FILE,
    ]

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate(input=text.encode("utf-8"))

        if process.returncode != 0:
            print(f"Ошибка Piper TTS: {stderr.decode('utf-8')}")
            return

        if os.path.exists(TMP_WAV_FILE):
            play_wav(TMP_WAV_FILE)
            os.remove(TMP_WAV_FILE)
        else:
            print(f"Ошибка: Piper не создал файл {TMP_WAV_FILE}")

    except FileNotFoundError:
        print(f"Ошибка: Не удалось запустить Piper. Проверьте путь: {PIPER_EXE_PATH}")
    except Exception as e:
        print(f"Неожиданная ошибка при озвучивании: {e}")


def play_wav(filename):
    try:
        wf = wave.open(filename, "rb")
        p_out = pyaudio.PyAudio()

        stream_out = p_out.open(
            format=p_out.get_format_from_width(wf.getsampwidth()),
            channels=wf.getnchannels(),
            rate=wf.getframerate(),
            output=True,
        )

        data = wf.readframes(CHUNK)
        while data:
            stream_out.write(data)
            data = wf.readframes(CHUNK)

        stream_out.stop_stream()
        stream_out.close()
        wf.close()
        p_out.terminate()
    except FileNotFoundError:
        print(f"Ошибка: Файл для воспроизведения не найден: {filename}")
    except Exception as e:
        print(f"Ошибка воспроизведения WAV: {e}")


def listen():
    print("Слушаю...")
    if not stream:
        print("Ошибка: Аудиопоток не инициализирован.")
        return None

    while True:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            if recognizer.AcceptWaveform(data):
                result_json = recognizer.Result()
                result_dict = json.loads(result_json)
                text = result_dict.get("text", "")
                if text:
                    print(f"Распознано: {text}")
                    return text.lower()
        except OSError as e:
            print(f"Ошибка чтения с аудиоустройства: {e}")
            return None
        except Exception as e:
            print(f"Ошибка во время прослушивания: {e}")
            return None


def fetch_definition(word):
    global current_word_data, current_word
    try:
        response = requests.get(f"{DICTIONARY_API_URL}{word}")
        # response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and len(data) > 0:
            current_word_data = data[0]
            current_word = word
            return True
        else:
            speak(f"Sorry, I could not find the definition for {word}.")
            current_word_data = None
            current_word = None
            return False
    except requests.exceptions.RequestException as e:
        speak(f"Sorry, there was an error connecting to the dictionary service: {e}")
        current_word_data = None
        current_word = None
        return False
    except json.JSONDecodeError:
        speak("Sorry, I received an invalid response from the dictionary service.")
        current_word_data = None
        current_word = None
        return False


def handle_find(command_parts):
    if len(command_parts) > 1:
        word_to_find = command_parts[1]
        speak(f'Okay, searching for "{word_to_find}".')
        if fetch_definition(word_to_find):
            speak(f"Found definition for {word_to_find}!")
    else:
        speak("Please specify a word to find. For example: find apple.")


def handle_meaning():
    if not current_word_data:
        speak("Please find a word first using the 'find' command.")
        return

    try:
        meaning = (
            current_word_data.get("meanings", [{}])[0]
            .get("definitions", [{}])[0]
            .get("definition")
        )
        if meaning:
            speak(f"The meaning of {current_word} is: {meaning}")
        else:
            speak(f"Sorry, I couldn't extract a clear meaning for {current_word}.")
    except (IndexError, KeyError, AttributeError):
        speak(f"Sorry, I had trouble finding the meaning structure for {current_word}.")


def handle_example():
    if not current_word_data:
        speak("Please find a word first using the 'find' command.")
        return

    try:
        example = None
        meanings = current_word_data.get("meanings", [])
        for meaning in meanings:
            definitions = meaning.get("definitions", [])
            for definition in definitions:
                if "example" in definition and definition["example"]:
                    example = definition["example"]
                    break
            if example:
                break

        if example:
            speak(f"An example for {current_word} is: {example}")
        else:
            speak(f"Sorry, I couldn't find an example sentence for {current_word}.")
    except (IndexError, KeyError, AttributeError):
        speak(f"Sorry, I had trouble finding an example for {current_word}.")


def handle_link():
    if not current_word:
        speak("Please find a word first using the 'find' command.")
        return

    source_url = current_word_data.get("sourceUrls", [None])[0]
    if source_url:
        url_to_open = source_url
        speak(f"Opening the source link for {current_word}.")
    else:
        url_to_open = f"https://en.wiktionary.org/wiki/{current_word}"
        speak(f"Opening Wiktionary page for {current_word}.")

    try:
        webbrowser.open(url_to_open)
    except Exception as e:
        speak(f"Sorry, I could not open the link. Error: {e}")


def handle_save():
    if not current_word_data or not current_word:
        speak("Please find a word first using the 'find' command.")
        return

    filename = "saved_definitions.txt"
    try:
        with open(filename, "a", encoding="utf-8") as f:
            f.write(f"--- {current_word.upper()} ---\n")
            f.write(f"Phonetic: {current_word_data.get('phonetic', 'N/A')}\n\n")

            for i, meaning in enumerate(current_word_data.get("meanings", [])):
                part_of_speech = meaning.get("partOfSpeech", "N/A")
                f.write(f"Meaning {i + 1} ({part_of_speech}):\n")
                for j, definition in enumerate(meaning.get("definitions", [])):
                    f.write(f"  Def {j + 1}: {definition.get('definition', 'N/A')}\n")
                    example = definition.get("example")
                    if example:
                        f.write(f"  Example: {example}\n")
                f.write("\n")
            source_urls = current_word_data.get("sourceUrls", [])
            if source_urls:
                f.write("Source URLs:\n")
                for url in source_urls:
                    f.write(f"- {url}\n")

            f.write("--------------------\n\n")
        speak(f"Information about {current_word} saved to {filename}.")
    except IOError as e:
        speak(f"Sorry, I could not save the definition to the file. Error: {e}")
    except Exception as e:
        speak(f"An unexpected error occurred while saving: {e}")


def initialize():
    global p, stream, vosk_model, recognizer

    try:
        vosk_model = Model(VOSK_MODEL_PATH)
        recognizer = KaldiRecognizer(vosk_model, RATE)
        recognizer.SetWords(True)
        print("Модель VOSK загружена успешно.")
    except Exception as e:
        print(f"Ошибка инициализации VOSK: {e}")
        sys.exit(1)

    try:
        p = pyaudio.PyAudio()
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
        stream.start_stream()
        print("Аудиопоток PyAudio инициализирован.")
    except Exception as e:
        print(f"Ошибка инициализации PyAudio: {e}")
        if p:
            p.terminate()
        sys.exit(1)


def cleanup():
    global p, stream
    print("Завершение работы...")
    if stream:
        stream.stop_stream()
        stream.close()
        print("Аудиопоток остановлен.")
    if p:
        p.terminate()
        print("PyAudio освобожден.")
    if os.path.exists(TMP_WAV_FILE):
        try:
            os.remove(TMP_WAV_FILE)
        except OSError as e:
            print(f"Не удалось удалить временный файл {TMP_WAV_FILE}: {e}")


if __name__ == "__main__":
    initialize()
    speak(
        "Hello! To find a word in the dictionary, say “FIND <word>”. Once the word is found, you can ask me to tell you the MEANING, give an EXAMPLE of usage, SAVE the word to a file, or open a LINK from a dictionary entry. "
    )

    try:
        while True:
            command_text = listen()

            if command_text:
                parts = command_text.strip().split(maxsplit=1)
                command_name = parts[0]

                if command_name == "find":
                    handle_find(parts)
                elif command_name == "meaning":
                    handle_meaning()
                elif command_name == "example":
                    handle_example()
                elif command_name == "link":
                    handle_link()
                elif command_name == "save":
                    handle_save()
                elif command_name in ["stop", "exit", "quit", "bye"]:
                    speak("Goodbye!")
                    break
                else:
                    if len(command_text) > 3:
                        speak(f"Sorry, I don't understand the command: {command_text}")
            else:
                print("Ничего не распознано или произошла ошибка.")

    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
    finally:
        cleanup()
