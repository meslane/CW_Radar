"""
run_specgram.py
Created By Alexander Yared (akyared@gmail.com)

Main Script for the Live Spectrogram project, a real time spectrogram
visualization tool

Dependencies: matplotlib, numpy and the mic_read.py module
"""
############### Import Libraries ###############
from matplotlib.mlab import window_hanning,specgram
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.colors import LogNorm
import numpy as np

############### Import Modules ###############
import pyaudio

RATE = 16000
FORMAT = pyaudio.paInt16 #conversion format for PyAudio stream
CHANNELS = 1 #microphone audio channels
CHUNK_SIZE = 8192 #number of samples to take per read
SAMPLE_LENGTH = int(CHUNK_SIZE*1000/RATE) #length of each sample in ms

############### Functions ###############
"""
open_mic:
creates a PyAudio object and initializes the mic stream
inputs: none
ouputs: stream, PyAudio object
"""
def open_mic():
    pa = pyaudio.PyAudio()
    stream = pa.open(format = FORMAT,
                     channels = CHANNELS,
                     rate = RATE,
                     input = True,
                     frames_per_buffer = CHUNK_SIZE)
    return stream,pa

"""
get_data:
reads from the audio stream for a constant length of time, converts it to data
inputs: stream, PyAudio object
outputs: int16 data array
"""
def get_data(stream,pa):
    input_data = stream.read(CHUNK_SIZE)
    data = np.fromstring(input_data,np.int16)
    return data

############### Test Functions ###############
"""
make_10k:
creates a 10kHz test tone
"""
def make_10k():
    x = np.linspace(-2*np.pi,2*np.pi,21000)
    x = np.tile(x,int(SAMPLE_LENGTH/(4*np.pi)))
    y = np.sin(2*np.pi*5000*x)
    return x,y

"""
show_freq:
plots the test tone for a sanity check
"""
def show_freq():
    x,y = make_10k()
    plt.plot(x,y)
    plt.show()


############### Constants ###############
#SAMPLES_PER_FRAME = 10 #Number of mic reads concatenated within a single window
SAMPLES_PER_FRAME = 4
nfft = 1024#256#1024 #NFFT value for spectrogram
overlap = 1000#512 #overlap value for spectrogram
rate = RATE #sampling rate

############### Functions ###############
"""
get_sample:
gets the audio data from the microphone
inputs: audio stream and PyAudio object
outputs: int16 array
"""
def get_sample(stream,pa):
    data = get_data(stream,pa)
    return data
"""
get_specgram:
takes the FFT to create a spectrogram of the given audio signal
input: audio signal, sampling rate
output: 2D Spectrogram Array, Frequency Array, Bin Array
see matplotlib.mlab.specgram documentation for help
"""
def get_specgram(signal,rate):
    arr2D,freqs,bins = specgram(signal,window=window_hanning,
                                Fs = rate,NFFT=nfft,noverlap=overlap)
    return arr2D,freqs,bins

"""
update_fig:
updates the image, just adds on samples at the start until the maximum size is
reached, at which point it 'scrolls' horizontally by determining how much of the
data needs to stay, shifting it left, and appending the new data. 
inputs: iteration number
outputs: updated image
"""
def update_fig(n):
    data = get_sample(stream,pa)
    arr2D,freqs,bins = get_specgram(data,rate)
    im_data = im.get_array()
    if n < SAMPLES_PER_FRAME:
        im_data = np.hstack((im_data,arr2D))
        im.set_array(im_data)
    else:
        keep_block = arr2D.shape[1]*(SAMPLES_PER_FRAME - 1)
        im_data = np.delete(im_data,np.s_[:-keep_block],1)
        im_data = np.hstack((im_data,arr2D))
        im.set_array(im_data)
    return im,

def main():
    ############### Initialize Plot ###############
    fig = plt.figure()
    """
    Launch the stream and the original spectrogram
    """
    stream,pa = open_mic()
    data = get_sample(stream,pa)
    arr2D,freqs,bins = get_specgram(data,rate)
    """
    Setup the plot paramters
    """
    extent = (bins[0],bins[-1]*SAMPLES_PER_FRAME,freqs[-1],freqs[0])
    im = plt.imshow(arr2D,aspect='auto',extent = extent,interpolation="none",
                    cmap = 'jet',norm = LogNorm(vmin=.01,vmax=1))
    plt.xlabel('Time (s)')
    plt.ylabel('Frequency (Hz)')
    plt.title('Real Time Spectogram')
    plt.gca().invert_yaxis()
    ##plt.colorbar() #enable if you want to display a color bar

    ############### Animate ###############
    anim = animation.FuncAnimation(fig,update_fig,blit = False,
                                interval=CHUNK_SIZE/1000)

                                
    try:
        plt.show()
    except:
        print("Plot Closed")

    ############### Terminate ###############
    stream.stop_stream()
    stream.close()
    pa.terminate()
    print("Program Terminated")

if __name__ == "__main__":
    main()