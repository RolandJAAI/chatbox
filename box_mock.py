import numpy as np
import requests
import io
import os
import subprocess
import json
import pyaudio
from threading import Thread, Lock
from pynput import keyboard
import wave

# System
system_prompt = "Du bist Samatha, eine sehr kluge und charmante Lebensform basierend auf künstlicher Intelligenz. Deine Antworten werden in Audio umgewandelt, denn du sprichst mit einem Menschen. Fasse dich daher immer kurz und gib prägnante Antworten. Du antwortest nur auf deutsch. Schreibe jedes Wort aus, denn Abkürzungen können die Sprachausgabe schwierig machen. Schreibe auch Zahlen als Wörter, z.B. zweitens statt 2. oder vier statt 4. Ganz wichtig: FASSE DICH KURZ, antworte am besten immer nur mit ein bis zwei Sätzen! Diese Instruktionen sollen bitte nicht in deinen Antworten vorkommen. Los geht's!"

messages = [{"role": "system", "content": system_prompt}]

# URL of aiy_box.py server
BOT_URL = "http://127.0.0.1:8000"
# optional: specify other endpoints here and include them below


def get_full_answer(file_path):
    url = BOT_URL
    if not os.path.isfile(file_path):
        raise Exception("Audio-file not found.")

    with open(file_path, 'rb') as file:
        files = {
            'file': (os.path.basename(file_path), file),
            'temperature': (None, '0.2'),
            'response-format': (None, 'json')
            }
        response = requests.post(url, files=files)
        
        if response.status_code == 200:
            return response
        else:
            print("STT API Error. Statuscode:" , response.status_code)
            pass


def get_stt(file_path):
    url = BOT_URL + "/stt"
    if not os.path.isfile(file_path):
        raise Exception("Audio-file not found.")

    with open(file_path, 'rb') as file:
        files = {
            'file': (os.path.basename(file_path), file)
            }
        response = requests.post(url, files=files)
        if response.status_code == 200:
            response_text = response.json()
            return response_text
        else:
            print("STT API Error. Statuscode:" , response.status_code)
            pass
        

def get_completion(messages):
    url = BOT_URL + "/llm"
    data =  {"messages": messages,
             "options": {"seed": 39573}
                }
    headers = {"Content-Type": "application/JSON"}
    completion = requests.post(url, data=json.dumps(data), headers=headers)
    response = completion.json()
    if not response:
        response = "Äh, wie bitte? Kannst du das bitte nochmal wiederholen?"
    print(response)
    return response


def get_tts(input_text):
    url = BOT_URL + "/tts"
    data =  {"text": input_text
                }
    headers = {"Content-Type": "application/JSON"}
    audio_stream = requests.post(url, data=json.dumps(data), headers=headers)
    return audio_stream


def play_audio(audio_stream):
    # Plays incoming audiostream live with ffmpeg
    ffplay_cmd = ["ffplay", "-nodisp", "-probesize", "1024", "-autoexit", "-"]
    ffplay_proc = subprocess.Popen(ffplay_cmd, stdin=subprocess.PIPE)

    for chunk in audio_stream:
        if chunk:
            ffplay_proc.stdin.write(chunk)

    # close on finish
    ffplay_proc.stdin.close()
    ffplay_proc.wait()


def load_llm():
    url = BOT_URL + "/load"
    data =  {"text": "load LLM"
                }
    headers = {"Content-Type": "application/JSON"}
    response = requests.post(url, data=json.dumps(data), headers=headers)
    if response.status_code == 200:
        print("LLM Model loaded.")
        pass
    else:
        print("STT API Error. Statuscode:" , response.status_code)
        pass


# Wait for keyboard press to start / stop recording
class listener(keyboard.Listener):
    def __init__(self, recorder):
        super().__init__(on_press = self.on_press, on_release = self.on_release)
        self.recorder = recorder
    
    def on_press(self, key):
        if key is None: #unknown event
            pass
        elif isinstance(key, keyboard.Key): #special key event
            if key == key.ctrl:
                self.recorder.start()
        elif isinstance(key, keyboard.KeyCode): #alphanumeric key event
            if key.char == 'q': #press q to quit
                if self.recorder.recording:
                    self.recorder.stop()
                # p_stream.terminate()
                return False #this is how you stop the listener thread
                
    def on_release(self, key):
        if key is None: #unknown event
            pass
        elif isinstance(key, keyboard.Key): #special key event
            if key == key.ctrl:
                self.recorder.stop()
        elif isinstance(key, keyboard.KeyCode): #alphanumeric key event
            pass


class recorder:
    def __init__(self, 
                 wavfile, 
                 chunksize=512, 
                 dataformat=pyaudio.paInt16, 
                 channels=1, 
                 rate=16000):
        self.filename = wavfile
        self.chunksize = chunksize
        self.dataformat = dataformat
        self.channels = channels
        self.rate = rate
        self.recording = False
        self.pa = pyaudio.PyAudio()
        self.messages = messages

    def start(self):
        # we call start and stop from the keyboard listener, so we use the asynchronous 
        # version of pyaudio streaming. The keyboard listener must regain control to 
        # begin listening again for the key release.
        if not self.recording:
            self.wf = wave.open(self.filename, 'wb')
            self.wf.setnchannels(self.channels)
            self.wf.setsampwidth(self.pa.get_sample_size(self.dataformat))
            self.wf.setframerate(self.rate)
            def callback(in_data, frame_count, time_info, status):
                #file write should be able to keep up with audio data stream (about 1378 Kbps)
                self.wf.writeframes(in_data) 
                return (in_data, pyaudio.paContinue)
            
            self.stream = self.pa.open(format = self.dataformat,
                                       channels = self.channels,
                                       rate = self.rate,
                                       input = True,
                                       stream_callback = callback)
            self.stream.start_stream()
            self.recording = True
            print('recording started')
    
    def stop(self):
        if self.recording:         
            self.stream.stop_stream()
            self.stream.close()
            self.wf.close()
            
            self.recording = False
            print('recording finished, start TTS')

            # start processing directly after recording finished
            # STT
            result = get_stt(self.filename)
            print(result)
            print("getting LLM answer")

            # update messages object with st response
            self.messages.append({"role": "user", "content": result})

            #get llm answer
            response = get_completion(self.messages)
            print("\n \n" + response + "\n \n")
            self.messages.append({"role": "assistant", "content": response})
            print("getting TTS and audio stream")

            # TTS and streaming playback
            play_audio(get_tts(response))
            print("Done. Ready for next input.")


if __name__ == '__main__':
    r = recorder("mic.wav")
    l = listener(r)
    load_llm()
    print('hold ctrl to record, press q to quit')
    l.start() #keyboard listener is a thread so we start it here
    l.join() #wait for the tread to terminate so the program doesn't instantly close