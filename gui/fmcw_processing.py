import math
import numpy as np
import scipy
import time

import pyaudio
import serial

from multiprocessing import Process, Queue
import tkinter as tk

import matplotlib.pyplot as plt

SAMPLE_RATE = 48000
SAMPLES_PER_LOOP = 1500
CHIRP_THRESH = 10000
SAMPLES_PER_CHIRP = 72
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

stream = audio.open(format = pyaudio.paInt16,
        channels = 1,
        rate = SAMPLE_RATE, #sample rate
        input = True,
        frames_per_buffer = SAMPLES_PER_LOOP,
        input_device_index = 0,
        start=False)

while input() != "quit":

    stream.start_stream()
    #dummy read just to clear the bufffer
    stream.read(SAMPLES_PER_LOOP, exception_on_overflow = True)
    
    radar.write(b' \n') #trigger a ramp
    audio_data_raw_ramp = stream.read(SAMPLES_PER_LOOP, exception_on_overflow = True) #immediately read 1ms worth of data

    stream.stop_stream() #we must close the stream each time to ensure we capture the pulse

    audio_samples_ramp = []

    for i in range(SAMPLES_PER_LOOP):
        audio_samples_ramp.append(int.from_bytes(audio_data_raw_ramp[(i*2):(i*2)+2], "little", signed=True))

    #gate sampling until we pass an amplitude threshold
    chirp_start = 0
    
    for i, sample in enumerate(audio_samples_ramp):
        if sample > CHIRP_THRESH:
            chirp_start = i
            break
    
    chirp_end = chirp_start + SAMPLES_PER_CHIRP
    
    audio_samples_ramp_pruned = audio_samples_ramp[chirp_start: chirp_end]

    bin_size = SAMPLE_RATE/SAMPLES_PER_CHIRP
    #Dynamic range of ADC + 10log(bandwidth of 1x bin)
    fft_offset = 0 #(6.02 * BIT_DEPTH) + 1.76 + 10 * np.log10(bin_size)

    fft_output_ramp = 20 * np.log10(np.abs(np.fft.rfft(audio_samples_ramp_pruned))) - fft_offset

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
    
    fig, (ax1, ax2) = plt.subplots(2,1, layout="constrained")
    
    ax1.plot(list(range(0,len(audio_samples_ramp))), audio_samples_ramp)
    ax1.axvline(x=chirp_start, color='red', linestyle='--')
    ax1.axvline(x=chirp_end, color='red', linestyle='--')
    ax1.set_ylabel("Sample Magnitude")
    ax1.set_xlabel("Sample Bin (Time domain)")

    ax2.plot(fft_labels, fft_output_ramp, label="Ramp Enabled")
    ax2.set_ylabel("FFT Magnitude (dB)")
    ax2.set_xlabel("Range (m)")
    
    #plt.legend()
    ax1.grid()
    ax2.grid()
    plt.show()