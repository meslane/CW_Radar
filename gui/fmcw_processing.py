import math
import numpy as np
import scipy
import time

import pyaudio
import serial

from multiprocessing import Process, Queue

import matplotlib.pyplot as plt

SAMPLE_RATE = 48000
DELAY_SAMPLES = 0 #samples to delay before grabbing chirp
SAMPLES_PER_LOOP = 1000
BIT_DEPTH = 16

PICO_PORT = "COM6"

#radar sweep params
DFDT = 5e10
C = 3e8

audio = pyaudio.PyAudio()
info = audio.get_host_api_info_by_index(0)

devices = []
numdevices = info.get('deviceCount')
for i in range(0, numdevices):
    if (audio.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
        devices.append("{} - {}".format(i,audio.get_device_info_by_host_api_device_index(0, i).get('name')))
        
print(devices)

radar = serial.Serial(
    port = PICO_PORT,
    baudrate = 115200,
    timeout = 1
    )

radar.close()
radar.open()

print(radar.is_open)

while input() != "quit":
    #open audio device
    stream = audio.open(format = pyaudio.paInt16,
        channels = 1,
        rate = SAMPLE_RATE, #sample rate
        input = True,
        frames_per_buffer = SAMPLES_PER_LOOP,
        input_device_index = 0)
            
    
    #Get baseline noise floor
    audio_data_raw_baseline = stream.read(SAMPLES_PER_LOOP, exception_on_overflow = True) #immediately read 1ms worth of data

    radar.write(b' \n') #trigger a ramp
    time.sleep(DELAY_SAMPLES/SAMPLES_PER_LOOP)

    audio_data_raw_ramp = stream.read(SAMPLES_PER_LOOP, exception_on_overflow = True) #immediately read 1ms worth of data

    stream.close() #we must close the stream each time to ensure we capture the pulse

    audio_samples_baseline = []
    audio_samples_ramp = []

    for i in range(SAMPLES_PER_LOOP):
        audio_samples_baseline.append(int.from_bytes(audio_data_raw_baseline[(i*2):(i*2)+2], "little", signed=True))
        audio_samples_ramp.append(int.from_bytes(audio_data_raw_ramp[(i*2):(i*2)+2], "little", signed=True))

    bin_size = SAMPLE_RATE/SAMPLES_PER_LOOP
    #Dynamic range of ADC + 10log(bandwidth of 1x bin)
    fft_offset = 0 #(6.02 * BIT_DEPTH) + 1.76 + 10 * np.log10(bin_size)

    fft_output_baseline = 20 * np.log10(np.abs(np.fft.rfft(audio_samples_baseline))) - fft_offset
    fft_output_ramp = 20 * np.log10(np.abs(np.fft.rfft(audio_samples_ramp))) - fft_offset

    fft_labels = []
    ranges = []
    for i in range(len(fft_output_ramp)):
        freq = i * bin_size
        #fft_labels.append(freq)
        fft_labels.append((C * freq) / (2 * DFDT)) #range bins

    print(radar.readline())
    #print(audio_samples)
    #print(fft_output)
    #print(fft_labels)

    plt.plot(fft_labels, fft_output_ramp, label="Ramp Enabled")
    plt.plot(fft_labels, fft_output_baseline, label="No Ramp")
    plt.ylabel("FFT Magnitude (dB)")
    plt.xlabel("Range (m)")
    plt.legend()
    plt.grid()
    plt.show()