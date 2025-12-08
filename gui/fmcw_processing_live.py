import math
import numpy as np
import scipy
import time

import pyaudio
import serial

from multiprocessing import Process, Queue
import tkinter as tk

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import matplotlib.animation as animation
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg, NavigationToolbar2Tk)
from matplotlib import style
from matplotlib import colors

SAMPLE_RATE = 48000
SAMPLES_PER_LOOP = 1500
SAMPLES_PER_CHIRP = int(96 * 1.5)
FFT_BINS = SAMPLES_PER_CHIRP // 2 + 1
BIT_DEPTH = 16

#filter cutoff
CUTOFF_HIGHPASS = 500

#window trigger threshold
CHIRP_TRIG_THRESH = 1500

WINDOW_LENGTH = 181
FFT_MIN = 60
FFT_MAX = 120

PICO_PORT = "COM6"

#radar sweep params
BW = 50e6
DFDT = 2.5e10
PRF = 3 #Hz
C = 3e8

l_sweep = BW / DFDT
pulse_period = 1/PRF

TKINTER_STICKY = "NSEW"
ANIMATION_INTERVAL = 1000

#Generate highpass filter coefficients
hpf = scipy.signal.butter(10, CUTOFF_HIGHPASS, "hp", fs=SAMPLE_RATE, output="sos")

def radar_thread(stream_id, audio_queue, close_queue):
    audio = pyaudio.PyAudio()
    
    stream = audio.open(format = pyaudio.paInt16,
        channels = 1,
        rate = SAMPLE_RATE, #sample rate
        input = True,
        frames_per_buffer = SAMPLES_PER_LOOP,
        input_device_index = 0,
        start=False)
        
    radar = serial.Serial(
    port = PICO_PORT,
    baudrate = 115200,
    timeout = 1
    )

    radar.close()
    radar.open()
    
    while close_queue.empty():
        t_start = time.time_ns()
        stream.start_stream()
        #dummy read just to clear the bufffer
        stream.read(SAMPLES_PER_LOOP, exception_on_overflow = True)
        
        radar.write(b' \n') #trigger a ramp
        audio_data_raw_ramp = stream.read(SAMPLES_PER_LOOP, exception_on_overflow = True) #immediately read 1ms worth of data

        stream.stop_stream() #we must close the stream each time to ensure we capture the pulse
        
        audio_queue.put(audio_data_raw_ramp)
        
        t_elapsed = (time.time_ns() - t_start) / 1e9
        
        time.sleep(pulse_period - t_elapsed)
    
    radar.close()
    stream.close()
    return
    
class Window:
    def __init__(self, window, stream_id):
        self.window = window
        self.widgets = {}
        
        self.audio_queue = Queue()
        self.close_queue = Queue()
        
        #start audio thread
        #self.thread = threading.Thread(target=self.audio_thread)
        self.thread = Process(target=radar_thread, args=(stream_id, self.audio_queue, self.close_queue))
        self.thread.start()
        
        #fft waterfall display
        plt.rcParams.update({'font.size': 20})
        
        self.fft_plot = Figure(figsize=(16, 9), dpi=60)
        self.fft_plot.set_tight_layout(True)
        self.fft_ax = self.fft_plot.add_subplot(1,1,1)
        self.fft_ax.set_ylabel('Time (s)')
        self.fft_ax.set_xlabel('Range (m)')
        self.fft_canvas = FigureCanvasTkAgg(self.fft_plot, self.window)
        self.fft_canvas.get_tk_widget().grid(column=0,row=0,rowspan=3,sticky=TKINTER_STICKY)
        self.fft_animation = animation.FuncAnimation(self.fft_plot, self.animate_plot, interval=ANIMATION_INTERVAL, blit=False)
        
        self.animation_iter = 0
        
        #init fft data array
        self.fft_data = []
        for x in range(WINDOW_LENGTH):
            self.fft_data.append([])
            for y in range(FFT_BINS):
                self.fft_data[x].append(0.1)
        
        self.fft_im = self.fft_ax.imshow(self.fft_data, 
                                            interpolation='none', 
                                            animated = True,
                                            norm=colors.LogNorm(vmin=FFT_MIN, vmax=FFT_MAX),
                                            aspect='auto',
                                            origin='lower',
                                            extent=[0, FFT_BINS, 
                                                    WINDOW_LENGTH, 0])
                                                    
        #function calls
        self.do_fft()

    def animate_plot(self, *args):
        self.fft_im.set_array(self.fft_data)
        self.animation_iter += 1
        
    def do_fft(self):
        data = []
        fft_output = []
        audio_samples_ramp = []
    
        if not self.audio_queue.empty():
            queue_size = self.audio_queue.qsize()
            
            if (queue_size > 20):
                print("WARNING: audio queue backup (len = {})".format(queue_size))
            
            data = self.audio_queue.get()
            
            for i in range(SAMPLES_PER_LOOP):
                audio_samples_ramp.append(int.from_bytes(data[(i*2):(i*2)+2], "little", signed=True))
            
            audio_samples_ramp_filtered = scipy.signal.sosfilt(hpf, audio_samples_ramp)

            #gate sampling until we pass an amplitude threshold
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
            
            #do FFT on pruned time domain data
            fft_output = (20 * np.log10(np.abs(np.fft.rfft(audio_samples_ramp_pruned)))).tolist()
            
            #shift in next fft slice
            self.fft_data = self.fft_data[1:] #delete last row
            self.fft_data.append(fft_output)
            
        #set axis labels
        bin_size = SAMPLE_RATE/SAMPLES_PER_CHIRP
        
        x_ticks = list(range(0, FFT_BINS, FFT_BINS//8))
        x_values = [round((C * (tick * bin_size)) / (2 * DFDT),2) for tick in x_ticks]
        
        y_ticks = list(range(0, WINDOW_LENGTH, WINDOW_LENGTH//6))
        y_values = [round(tick/PRF, 1) for tick in y_ticks]
        
        self.fft_ax.set_xticks(x_ticks, x_values)
        self.fft_ax.set_yticks(y_ticks, y_values)
        
        self.window.after(int(pulse_period * 1e3), self.do_fft)
        
    def on_resize(self, event):
        pass
        
    def close_window(self):
        self.close_queue.put(1)
        self.thread.terminate()
        self.window.destroy()

def main():
    #audio device setup
    stream_id = 0

    #main window
    root = tk.Tk()
    
    #configure resizing weights
    tk.Grid.columnconfigure(root,0,weight=1)
    tk.Grid.rowconfigure(root,0,weight=1)
    tk.Grid.rowconfigure(root,1,weight=1)
    tk.Grid.rowconfigure(root,2,weight=1)

    root.title("FMCW Radar")
    window = Window(root, stream_id)
    root.bind("<Configure>", window.on_resize)
    root.protocol("WM_DELETE_WINDOW", window.close_window)
    root.mainloop()

if __name__ == "__main__":
    main()