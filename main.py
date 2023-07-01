import math
import numpy as np
import scipy

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg, NavigationToolbar2Tk)
from matplotlib.backend_bases import key_press_handler
from matplotlib.figure import Figure
import matplotlib.animation as animation
from matplotlib import style
from matplotlib import colors

import pyaudio
import sounddevice as sd

import threading
import queue

import tkinter as tk
from tkinter import ttk

sd.default.latency = 'low'

SAMPLE_RATE = 7000
SAMPLES_PER_LOOP = 512

FFT_MIN = 1
FFT_MAX = 1e10

class Window:
    def __init__(self, window, stream):
        self.window = window
        self.widgets = {}
        
        self.audio = pyaudio.PyAudio()
        self.stream = stream
        
        #variables
        self.detection_threshold = tk.IntVar()
        self.detection_threshold.set(5)
        
        self.freq_ghz = tk.StringVar()
        self.freq_mhz = tk.StringVar()
        self.freq_khz = tk.StringVar()
        
        self.freq_ghz.set('03')
        self.freq_mhz.set('400')
        self.freq_khz.set('000')
        
        self.speed_display = tk.StringVar()
        self.speed_display.set("0.0")
        
        self.speed_selection = tk.IntVar()
        self.speed_selection.set(1)
        
        #math stuff
        self.carrier_freq = 0.0
        self.velocity_ms = 0.0 #velocity in meters per second
        self.units = "m/s"
        
        #queues
        self.running = True
        self.audio_queue = queue.Queue()
        
        #fft waterfall display
        plt.rcParams.update({'font.size': 20})
        
        self.fft_plot = Figure(figsize=(16, 9), dpi=60)
        self.fft_plot.set_tight_layout(True)
        self.fft_ax = self.fft_plot.add_subplot(1,1,1)
        self.fft_ax.set_ylabel('Time (samples)')
        self.fft_ax.set_xlabel('Frequency (Hz)')
        self.fft_canvas = FigureCanvasTkAgg(self.fft_plot, self.window)
        self.fft_canvas.get_tk_widget().grid(column=0,row=0,rowspan=3)
        self.fft_animation = animation.FuncAnimation(self.fft_plot, self.animate_plot, interval=250)
        
        #init fft data array
        self.fft_data = []
        for x in range(200):
            self.fft_data.append([])
            for y in range(SAMPLES_PER_LOOP // 2 + 1):
                self.fft_data[x].append(0.1)
        
        self.fft_im = self.fft_ax.imshow(self.fft_data, 
                                            interpolation='none', 
                                            animated = True,
                                            norm=colors.LogNorm(vmin=1, vmax=FFT_MAX),
                                            aspect='auto',
                                            origin='lower',
                                            extent=[0, SAMPLE_RATE // 2, 200, 0])
        
        #widgets
        #threshold
        self.widgets['Thresh_frame'] = tk.Frame(self.window,highlightbackground="black",highlightthickness=2)
        self.widgets['Thresh_frame'].grid(row=0,column=1,padx=10, pady=10)
        
        self.widgets['Threshold_title'] = tk.Label(self.widgets['Thresh_frame'], text="Threshold", font=("Arial",20))
        self.widgets['Threshold_title'].grid(row=0,column=0)
        
        self.widgets['Threshold'] = tk.Scale(self.widgets['Thresh_frame'],
                                             variable = self.detection_threshold,
                                             from_ = math.log(FFT_MIN,10), 
                                             to = math.log(FFT_MAX,10),
                                             orient = tk.HORIZONTAL,
                                             length = 200,
                                             font=("Arial",15))
        self.widgets['Threshold'].grid(row=1,column=0)
        
        #frequency selector
        self.widgets['Freq_frame'] = tk.Frame(self.window,highlightbackground="black",highlightthickness=2)
        self.widgets['Freq_frame'].grid(row=1,column=1,padx=10, pady=10)
        
        self.widgets['Freq_label'] = tk.Label(self.widgets['Freq_frame'], text="Carrier Frequency", font=("Arial",20))
        self.widgets['Freq_label'].grid(row=0,column=0, columnspan=5)
        
        self.widgets['Ghz_title'] = tk.Label(self.widgets['Freq_frame'], text="GHz", font=("Arial",15))
        self.widgets['Ghz_title'].grid(row=1,column=0)
        self.widgets['Freq_ghz'] = tk.Spinbox(self.widgets['Freq_frame'], 
                                                from_=0, 
                                                to=99, 
                                                width = 2, 
                                                format="%02.f",
                                                textvariable=self.freq_ghz,
                                                font=("Arial",20))
        self.widgets['Freq_ghz'].grid(row=2,column=0)
        
        self.widgets['Freq_decimal'] = tk.Label(self.widgets['Freq_frame'], text=".", font=("Arial",20))
        self.widgets['Freq_decimal'].grid(row=2,column=1)
        
        self.widgets['Mhz_title'] = tk.Label(self.widgets['Freq_frame'], text="MHz", font=("Arial",15))
        self.widgets['Mhz_title'].grid(row=1,column=2)
        self.widgets['Freq_mhz'] = tk.Spinbox(self.widgets['Freq_frame'], 
                                                from_=0, 
                                                to=999, 
                                                increment=1, 
                                                width = 3, 
                                                format="%03.f",
                                                textvariable=self.freq_mhz,
                                                font=("Arial",20))
        self.widgets['Freq_mhz'].grid(row=2,column=2)
        
        self.widgets['Freq_decimal2'] = tk.Label(self.widgets['Freq_frame'], text=".", font=("Arial",20))
        self.widgets['Freq_decimal2'].grid(row=2,column=3)
        
        self.widgets['khz_title'] = tk.Label(self.widgets['Freq_frame'], text="kHz", font=("Arial",15))
        self.widgets['khz_title'].grid(row=1,column=4)
        self.widgets['Freq_khz'] = tk.Spinbox(self.widgets['Freq_frame'], 
                                                from_=0, 
                                                to=999, 
                                                increment=1, 
                                                width = 3, 
                                                format="%03.f",
                                                textvariable=self.freq_khz,
                                                font=("Arial",20))
        self.widgets['Freq_khz'].grid(row=2,column=4)
        
        #mph display
        self.widgets['Speed_frame'] = tk.Frame(self.window,highlightbackground="black",highlightthickness=2)
        self.widgets['Speed_frame'].grid(row=2,column=1,padx=10, pady=10)
        
        self.widgets['Speed_label'] = tk.Label(self.widgets['Speed_frame'], text="Target Velocity", font=("Arial",20))
        self.widgets['Speed_label'].grid(row=0,column=0,columnspan=2)
        
        self.widgets['Speed_display'] = tk.Entry(self.widgets['Speed_frame'], 
                                                    state="readonly",
                                                    textvariable=self.speed_display,
                                                    width=10,
                                                    justify=tk.CENTER,
                                                    font=("Arial",20))
        self.widgets['Speed_display'].grid(row=1,column=0,columnspan=2)
        
        self.widgets['Speed_select_ms'] = tk.Radiobutton(self.widgets['Speed_frame'], 
                                                            text="m/s",
                                                            font=("Arial",15),
                                                            variable=self.speed_selection,
                                                            value=1)
        self.widgets['Speed_select_ms'].grid(row=2,column=0)
        
        self.widgets['Speed_select_mph'] = tk.Radiobutton(self.widgets['Speed_frame'], 
                                                            text="mph",
                                                            font=("Arial",15),
                                                            variable=self.speed_selection,
                                                            value=2)
        self.widgets['Speed_select_mph'].grid(row=2,column=1)
        
        #start audio thread
        self.thread = threading.Thread(target=self.audio_thread)
        self.thread.start()
        
        #function calls
        self.do_fft()

    def audio_thread(self):
        while self.running:
            audio_data = self.stream.read(SAMPLES_PER_LOOP, exception_on_overflow = True)
            self.audio_queue.put(audio_data)
    
    def do_fft(self):
        data = []
        audio_samples = []
        fft_output = []
    
        if not self.audio_queue.empty():
            print(self.audio_queue.qsize())
            
            data = self.audio_queue.get()
            
            for i in range(SAMPLES_PER_LOOP):
                audio_samples.append(int.from_bytes(data[(i*2):(i*2)+2], "little", signed=True))
                
            fft_output = np.abs(np.fft.rfft(audio_samples))    
            
            if fft_output[-1] < 1.0: #remove artifacts at edge of sample range
                fft_output[-1] = 1.0
            
            #shift in next fft slice
            self.fft_data = self.fft_data[1:] #delete last row
            self.fft_data.append(fft_output)
            
            max_tone = np.argmax(fft_output) * (SAMPLE_RATE/SAMPLES_PER_LOOP) #get freq of hightest amplitude
            
            self.carrier_freq = (int(self.freq_ghz.get()) * 1e9) + (int(self.freq_mhz.get()) * 1e6) + (int(self.freq_khz.get()) * 1e3)
            velocity = (3e8 * max_tone) / (2 * self.carrier_freq)
            
            if np.max(fft_output) >= (10 ** self.detection_threshold.get()): #only update if above threshold
                self.velocity_ms = velocity
            
            if self.speed_selection.get() == 1:
                self.units = "m/s"
                self.speed_display.set("{:.2f} {}".format(self.velocity_ms, self.units)) #m/s
            elif self.speed_selection.get() == 2:
                self.units = "mph"
                self.speed_display.set("{:.2f} {}".format(self.velocity_ms * 2.237, self.units)) #mph
            
        else:
            print("empty queue")
        
        self.window.after(50, self.do_fft)
    
    def animate_plot(self, *args):
        self.fft_im.set_array(self.fft_data)
    
    def close_window(self):
        self.running = False
        self.thread.join()
        self.window.destroy()
   
def main():
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
        rate = SAMPLE_RATE, #sample rate
        input = True,
        frames_per_buffer = SAMPLE_RATE,
        input_device_index = input_device)

    root = tk.Tk()
    root.title("Radar")
    window = Window(root, stream)
    root.protocol("WM_DELETE_WINDOW", window.close_window)
    root.mainloop()

if __name__ == "__main__":
    main()