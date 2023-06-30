import numpy as np
import scipy

import matplotlib.pyplot as plt
import matplotlib.animation as animation

import pyaudio

import threading
import queue

sample_rate = 4096
samples_per_loop = 256
loops_per_draw = 1

audio_queue = queue.Queue()
halt_queue = queue.Queue()

#matplotlib setup
fig = plt.figure()
samples = []

audio_samples = []
fft_output = []

#audio device setup
audio = pyaudio.PyAudio()
info = audio.get_host_api_info_by_index(0)
numdevices = info.get('deviceCount')

print("Available Audio Devices:")
for i in range(0, numdevices):
    if (audio.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
        print("Input Device id ", i, " - ", audio.get_device_info_by_host_api_device_index(0, i).get('name'))

input_device = int(input("Select input device ID:"))

stream = audio.open(format = pyaudio.paInt16,
    channels = 1,
    rate = sample_rate, #sample rate
    input = True,
    frames_per_buffer = sample_rate,
    input_device_index = input_device)

def audio_thread():
    while True:
        sample = stream.read(samples_per_loop, exception_on_overflow = False)
        audio_queue.put(sample)
        
        if not halt_queue.empty():
            print("Halting thread!")
            break

thread = threading.Thread(target=audio_thread)
thread.start()

for i in range(samples_per_loop):
    audio_samples.append(1)
    if (i <= samples_per_loop // 2):
        fft_output.append(0)

plt.ion()
fig = plt.figure()
ax = fig.add_subplot(111)
ax.set_ylim([1,1e9])
#ax.set_xlim([0,samples_per_loop/2])
ax.set_yscale("log")
line1, = ax.plot(fft_output)

loop_counter = 0  
while True:
    try:
        if not audio_queue.empty():
            data = audio_queue.get() #get samples from data
            
            if (loop_counter % loops_per_draw == 0):
                for i in range(samples_per_loop):
                    audio_samples[i] = int.from_bytes(data[(i*2):(i*2)+2], "little", signed=True)
            
                fft_output = np.abs(np.fft.rfft(audio_samples)) #only get one side
                
                max_tone = np.argmax(fft_output) * (sample_rate/samples_per_loop) #get freq of hightest amplitude
                
                print("Max frequency: {} Hz".format(max_tone))
                
                line1.set_ydata(fft_output)
                fig.canvas.draw()
                fig.canvas.flush_events()
                
            
            loop_counter += 1
    except KeyboardInterrupt:
        halt_queue.put(True)
        thread.join()
        print("Goodbye!")
        break