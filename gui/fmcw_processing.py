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
SAMPLES_PER_CHIRP = int(96 * 1.5)
BIT_DEPTH = 16

PICO_PORT = "COM6"

#radar sweep params
DFDT = 2.5e10
C = 3e8

#chrip detector params
CHIRP_TRIG_THRESH = 1500

#filter cutoff
CUTOFF_HIGHPASS = 500 #500 Hz cutoff attenuates 0m and 3m bins

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
        
hpf = scipy.signal.butter(10, CUTOFF_HIGHPASS, "hp", fs=SAMPLE_RATE, output="sos")

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

    #apply scipy high pass filter to remove low frequency clutter
    audio_samples_ramp_filtered = scipy.signal.sosfilt(hpf, audio_samples_ramp)

    #gate sampling until we pass an amplitude threshold
    #this algorithm measures the average magnitude of each chrip window over the threshold and returns the index of the strongest one
    #chirp candidates is list of (index, window_avg)
    chirp_candidates = [(0,0)]
    
    for i, sample in enumerate(audio_samples_ramp_filtered):
        if sample > CHIRP_TRIG_THRESH:
            #only if the trigger threshold is exceeded do we do the more expensive task of computing the window average
            chirp_avg = np.average(np.abs(audio_samples_ramp_filtered[i:i+SAMPLES_PER_CHIRP]))
            chirp_candidates.append((i,chirp_avg))
    
    chirp_start = max(chirp_candidates, key=lambda x: x[1])[0]
    chirp_mag = max(chirp_candidates, key=lambda x: x[1])[1]
    
    print(f"Found {len(chirp_candidates)} chirp candidates above thresh")
    print(f"Selected window at N={chirp_start} with mag={chirp_mag}")
                
    if chirp_start == 0:
        print("WARNING: chirp start == 0, trigger likely failed!")
    
    chirp_end = chirp_start + SAMPLES_PER_CHIRP
    
    audio_samples_ramp_pruned = audio_samples_ramp_filtered[chirp_start: chirp_end]

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
    
    ax1.plot(list(range(0,len(audio_samples_ramp_filtered))), audio_samples_ramp_filtered)
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