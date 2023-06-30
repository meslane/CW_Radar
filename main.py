import numpy as np
import scipy

import matplotlib.pyplot as plt
import matplotlib.animation as animation

import pyaudio

import threading
import queue

sample_rate = 4000
spec_samples = 8192
samples_per_loop = 256
loops_per_draw = 2
audio_queue = queue.Queue()
halt_queue = queue.Queue()

#matplotlib setup
fig = plt.figure()
samples = []
fft_samples = []

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
    fft_samples.append(1)

plt.ion()
fig = plt.figure()
ax = fig.add_subplot(111)
#line1 = ax.specgram(samples, Fs = sample_rate)
ax.set_ylim([1,1000000])
ax.set_xlim([0,127])
ax.set_yscale("log")
line1, = ax.plot(fft_samples)

loop_counter = 0  
while True:
    try:
        if not audio_queue.empty():
            data = audio_queue.get() #get samples from data
            
            for i in range(samples_per_loop):
                fft_samples[i] = int.from_bytes(data[(i*2):(i*2)+2], "little", signed=True)
                
            #print(samples[-1])
            
            if (loop_counter % loops_per_draw == 0):
                #line1 = ax.specgram(samples, Fs = sample_rate)
                fft_samples = np.abs(np.fft.fft(fft_samples))
                line1.set_ydata(fft_samples)#ax.plot(fft_samples)
                fig.canvas.draw()
                fig.canvas.flush_events()
            
            loop_counter += 1
    except KeyboardInterrupt:
        halt_queue.put(True)
        thread.join()
        print("Goodbye!")
        break