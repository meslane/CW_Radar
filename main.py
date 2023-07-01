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
WINDOW_LENGTH = 200
ANIMATION_INTERVAL = 250

FFT_MIN = 1
FFT_MAX = 1e10

TKINTER_STICKY = "NSEW"

class Selector:
    def __init__(self, window, audio):
        self.window = window
        self.widgets = {}
        
        self.devices = []
        self.selection = tk.StringVar()
        
        self.audio = audio
        self.stream = None
        
        info = self.audio.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        for i in range(0, numdevices):
            if (audio.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
                self.devices.append("{} - {}".format(i,audio.get_device_info_by_host_api_device_index(0, i).get('name')))
        
        self.widgets['Title'] = tk.Label(self.window, text="Select Input Device", font=("Arial",20))
        self.widgets['Title'].grid(row=0,column=0)
        
        self.widgets['Dropdown'] = tk.OptionMenu(self.window, self.selection, *self.devices)
        self.widgets['Dropdown'].config(width=40)
        self.widgets['Dropdown'].grid(row=1,column=0, padx=10)
        
        self.widgets['Button'] = tk.Button(self.window, text="Select Device", command=self.button_press)
        self.widgets['Button'].grid(row=3,column=0)
        
    def button_press(self):
        if self.selection.get():
            self.stream = self.audio.open(format = pyaudio.paInt16,
            channels = 1,
            rate = SAMPLE_RATE, #sample rate
            input = True,
            frames_per_buffer = SAMPLE_RATE,
            input_device_index = int(self.selection.get()[0]))
            
            self.window.destroy()
        

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
        self.paused = False
        self.running = True
        self.audio_queue = queue.Queue()
        
        #area for resizing
        self.last_area = self.window_area()
        
        #fft waterfall display
        plt.rcParams.update({'font.size': 20})
        
        self.fft_plot = Figure(figsize=(16, 9), dpi=60)
        self.fft_plot.set_tight_layout(True)
        self.fft_ax = self.fft_plot.add_subplot(1,1,1)
        self.fft_ax.set_ylabel('Time (s)')
        self.fft_ax.set_xlabel('Frequency (Hz)')
        self.fft_canvas = FigureCanvasTkAgg(self.fft_plot, self.window)
        self.fft_canvas.get_tk_widget().grid(column=0,row=0,rowspan=3,sticky=TKINTER_STICKY)
        self.fft_animation = animation.FuncAnimation(self.fft_plot, self.animate_plot, interval=ANIMATION_INTERVAL, blit=False)
        
        self.animation_iter = 0
        
        #init fft data array
        self.fft_data = []
        for x in range(WINDOW_LENGTH):
            self.fft_data.append([])
            for y in range(SAMPLES_PER_LOOP // 2 + 1):
                self.fft_data[x].append(0.1)
        
        self.fft_im = self.fft_ax.imshow(self.fft_data, 
                                            interpolation='none', 
                                            animated = True,
                                            norm=colors.LogNorm(vmin=1, vmax=FFT_MAX),
                                            aspect='auto',
                                            origin='lower',
                                            extent=[0, SAMPLE_RATE // 2, (SAMPLES_PER_LOOP/SAMPLE_RATE) * WINDOW_LENGTH, 0])
        
        #widgets
        #threshold
        self.widgets['Thresh_frame'] = tk.Frame(self.window,highlightbackground="black",highlightthickness=2)
        self.widgets['Thresh_frame'].grid(row=0,column=1,padx=10,pady=10,sticky=TKINTER_STICKY)
        
        self.widgets['Threshold_title'] = tk.Label(self.widgets['Thresh_frame'], text="Threshold", font=("Arial",20))
        self.widgets['Threshold_title'].grid(row=0,column=0)
        
        self.widgets['Threshold'] = tk.Scale(self.widgets['Thresh_frame'],
                                             variable = self.detection_threshold,
                                             from_ = math.log(FFT_MIN,10), 
                                             to = math.log(FFT_MAX,10),
                                             orient = tk.HORIZONTAL,
                                             length = 200,
                                             font=("Arial",15))
        self.widgets['Threshold'].grid(row=1,column=0,sticky=TKINTER_STICKY)
        
        tk.Grid.columnconfigure(self.widgets['Thresh_frame'],0,weight=1)
        
        #frequency selector
        self.widgets['Freq_frame'] = tk.Frame(self.window,highlightbackground="black",highlightthickness=2)
        self.widgets['Freq_frame'].grid(row=1,column=1,padx=10,pady=10,sticky=TKINTER_STICKY)
        
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
        
        tk.Grid.columnconfigure(self.widgets['Freq_frame'],0,weight=1) #make sure it is centered
        tk.Grid.columnconfigure(self.widgets['Freq_frame'],1,weight=1)
        tk.Grid.columnconfigure(self.widgets['Freq_frame'],2,weight=1)
        tk.Grid.columnconfigure(self.widgets['Freq_frame'],3,weight=1)
        tk.Grid.columnconfigure(self.widgets['Freq_frame'],4,weight=1)
        
        #mph display
        self.widgets['Speed_frame'] = tk.Frame(self.window,highlightbackground="black",highlightthickness=2)
        self.widgets['Speed_frame'].grid(row=2,column=1,padx=10,pady=10,sticky=TKINTER_STICKY)
        
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
        self.widgets['Speed_select_mph'].grid(row=2,column=1)\
        
        tk.Grid.columnconfigure(self.widgets['Speed_frame'],0,weight=1) #make sure it is centered
        tk.Grid.columnconfigure(self.widgets['Speed_frame'],1,weight=1)
        
        #bottom buttons
        self.widgets['Button_frame'] = tk.Frame(self.window)
        self.widgets['Button_frame'].grid(row=4,column=0,padx=10,pady=10,sticky=TKINTER_STICKY)
        
        self.widgets['Pause_button'] = tk.Button(self.widgets['Button_frame'], 
                                                    text="Pause", 
                                                    width=15,
                                                    font=("Arial",15),
                                                    command=self.pause_button)
        self.widgets['Pause_button'].grid(row=0,column=0)
        tk.Grid.columnconfigure(self.widgets['Button_frame'],0,weight=1)
        
        #start audio thread
        self.thread = threading.Thread(target=self.audio_thread)
        self.thread.start()
        
        #function calls
        self.do_fft()

    def audio_thread(self):
        while self.running:
            audio_data = self.stream.read(SAMPLES_PER_LOOP, exception_on_overflow = False)
            self.audio_queue.put(audio_data)
    
    def do_fft(self):
        data = []
        audio_samples = []
        fft_output = []
    
        if not self.audio_queue.empty():
            queue_size = self.audio_queue.qsize()
            
            if (queue_size > 20):
                print("WARNING: audio queue backup (len = {})".format(queue_size))
            
            data = self.audio_queue.get()
            
            if not self.paused:
                for i in range(SAMPLES_PER_LOOP):
                    audio_samples.append(int.from_bytes(data[(i*2):(i*2)+2], "little", signed=True))
                    
                fft_output = np.abs(np.fft.rfft(audio_samples))    
                
                #remove artifacts at fractions of nyquest frequency
                if fft_output[-1] < 1.0:
                    fft_output[-1] = 1.0
                if fft_output[SAMPLES_PER_LOOP // 4] < 1.0:
                    fft_output[SAMPLES_PER_LOOP // 4] = 1.0
                if fft_output[0] < 1.0:
                    fft_output[0] = 1.0
                
                #shift in next fft slice
                self.fft_data = self.fft_data[1:] #delete last row
                self.fft_data.append(fft_output)
                
                fft_no_DC = fft_output[1:] #don't consider DC point in fft calculation
                
                max_tone = np.argmax(fft_no_DC) * (SAMPLE_RATE/SAMPLES_PER_LOOP) #get freq of hightest amplitude
                
                self.carrier_freq = (int(self.freq_ghz.get()) * 1e9) + (int(self.freq_mhz.get()) * 1e6) + (int(self.freq_khz.get()) * 1e3)
                velocity = (3e8 * max_tone) / (2 * self.carrier_freq)
                
                if np.max(fft_no_DC) >= (10 ** self.detection_threshold.get()): #only update if above threshold
                    self.velocity_ms = velocity
        
        #velocity display
        if self.speed_selection.get() == 1:
            self.units = "m/s"
            self.speed_display.set("{:.2f} {}".format(self.velocity_ms, self.units)) #m/s
        elif self.speed_selection.get() == 2:
            self.units = "mph"
            self.speed_display.set("{:.2f} {}".format(self.velocity_ms * 2.237, self.units)) #mph
        
        self.window.after(50, self.do_fft)
    
    def animate_plot(self, *args):
        self.fft_im.set_array(self.fft_data)
        self.animation_iter += 1
    
    def pause_button(self):
        if self.paused:
            self.paused = False
            self.widgets['Pause_button'].configure(text="Pause")
        else:
            self.paused = True
            self.widgets['Pause_button'].configure(text="Resume")
    
    def window_area(self):
        return self.window.winfo_height() * self.window.winfo_width()
    
    def on_resize(self, event): #scale fft animation speed on resize
        if (event.widget == self.window and (self.window_area() != self.last_area)): #if window resized
            self.last_area = self.window_area()
            
            new_interval = int(ANIMATION_INTERVAL * (self.window_area() / 726000)) #scale with window size to avoid overflows
            self.fft_animation.pause() #NEED THIS OR IT KEEPS PLAYING UNTIL GARBAGE COLLECTED
            self.fft_animation = animation.FuncAnimation(self.fft_plot, self.animate_plot, interval=new_interval, blit=False)
            
            print("new interval = {}".format(new_interval))
    
    def close_window(self):
        self.running = False
        self.thread.join()
        self.window.destroy()
   
def main():
    #audio device setup
    audio = pyaudio.PyAudio()
    
    root = tk.Tk()
    root.title("Radar")
    select_window = Selector(root, audio)
    root.mainloop()

    stream = select_window.stream

    #main window
    root = tk.Tk()
    
    #configure resizing weights
    tk.Grid.columnconfigure(root,0,weight=1)
    tk.Grid.rowconfigure(root,0,weight=1)
    tk.Grid.rowconfigure(root,1,weight=1)
    tk.Grid.rowconfigure(root,2,weight=1)

    root.title("Radar")
    window = Window(root, stream)
    root.bind("<Configure>", window.on_resize)
    root.protocol("WM_DELETE_WINDOW", window.close_window)
    root.mainloop()

if __name__ == "__main__":
    main()